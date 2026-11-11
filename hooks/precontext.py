#!/usr/bin/env python3
"""PreToolUse hook (§Stage 5): inject grounding-aware graph context on Grep/Glob/Read so the session
queries the graph first. Reads precomputed ranks O(1); never computes centrality. Fails silent."""
import json
import os
import pathlib
import sys


def _dequote(v: str) -> str:
    """Mirror of ``envconfig._dequote``: peel matched surrounding quote pairs, repeatedly, so a
    double-wrapped value collapses to the bare path. Each pass drops >=2 chars, so it terminates."""
    while len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v


def _clean(value: "str | None") -> str:
    """The ONE permitted local copy of the env-value cleaner: it runs BEFORE sys.path can reach
    kg_engine.envconfig (the rule's single home, review-r5), solely to read CLAUDE_PLUGIN_ROOT.
    Everything after the sys.path insert resolves through envconfig — keep this body in lockstep
    with envconfig.clean.

    The dequote step is load-bearing for the mirror, and the ORDER matters: dequote first, THEN test the
    ``${...}`` placeholder, so a quoted-unsubstituted ``"${VAR}"`` is recognised as a placeholder rather
    than treated as a real path. envconfig.clean gained the dequote with the quoted-source_path fix; this
    copy did not, and the parametrized guard test had no quoted rows, so the two drifted while a test
    named `test_precontext_clean_mirrors_bootstrap` asserted they agreed (review-r11)."""
    if not value:
        return ""
    v = _dequote(value.strip())
    if not v or v.startswith("${") or v in ("/.venv", "/venv"):
        return ""
    return v


root = _clean(os.environ.get("CLAUDE_PLUGIN_ROOT"))
if root:
    sys.path.insert(0, str(pathlib.Path(root) / "scripts"))


def emit(ctx: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ctx}}))


# Reads that must stay blind (0.11.9). The context this hook injects is meant for the session exploring the
# project; a measurement must not receive it. In the second field /kg-experiment (0.11.8, Windows, 2026-11-10)
# the kg-evaluator subagent's Reads came back with grounded edges attached: the prompt file's, read before the
# control answers that must see no context, and three of the rag arm's passage files. The query is a file's
# stem, so "prompts-<run>" and "08" matched edges as readily as a document title does. The kg-annotator reads
# the source documents it labels, where the attached edges carry the grounding verdicts it must not see.
# So the hook stays silent when:
# - the call comes from a measurement subagent. Claude Code puts `agent_id` and `agent_type` in a hook's input
#   when a subagent made the call (2.1.316's schema; absent on the main thread), and a plugin's agent type is
#   "<plugin>:<name>";
# - the target lies under the project's `.kg/`: Burgess's own working files (prompts, rag passages, eval
#   sheets, labels, the divergence archives), never the project's knowledge. This holds on a Claude Code too
#   old to name the caller, and for the main session reading the run's files.
# The kg-judge (0.13.0) reads only its packet under `.kg/experiment/`, which the second rule already silences;
# naming it here keeps it blind even if a packet ever lived elsewhere.
_BLIND_AGENTS = frozenset({"kg-evaluator", "kg-annotator", "kg-judge"})
_WORKSPACE_DIRNAME = ".kg"
_GLOB_CHARS = "*?[{"


def _blind_caller(payload: dict) -> bool:
    agent = payload.get("agent_type")
    return isinstance(agent, str) and agent.rsplit(":", 1)[-1].strip() in _BLIND_AGENTS


def _norm(path: "str | os.PathLike") -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _targets_workspace(payload: dict, project: "str | os.PathLike") -> bool:
    """True when the Read/Grep/Glob targets the project's `.kg/` (or a path under it)."""
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        return False
    base = pathlib.Path(payload.get("cwd") or project)
    candidates = [ti.get("file_path"), ti.get("path")]
    pattern = ti.get("pattern")
    if payload.get("tool_name") == "Glob" and isinstance(pattern, str):
        # a Glob pattern is a path: its literal head, up to the first wildcard, names where it looks
        head = pattern
        for ch in _GLOB_CHARS:
            head = head.split(ch, 1)[0]
        candidates.append(str(pathlib.Path(ti.get("path") or base) / head) if head else None)
    workspace = _norm(pathlib.Path(project) / _WORKSPACE_DIRNAME)
    for value in candidates:
        if not isinstance(value, str) or not value.strip():
            continue
        p = pathlib.Path(value)
        if not p.is_absolute():
            p = base / p
        target = _norm(p)
        if target == workspace or target.startswith(workspace + os.sep):
            return True
    return False


# Render/latency knobs, named (review-r5). This hook fires on every Grep/Glob/Read, so the injected
# context is kept small and the work bounded:
_CONTEXT_BUDGET = 800          # token budget passed to kg_context (a fraction of a normal read)
_MAX_ITEMS = 6                 # grounded items rendered
_MAX_BRIDGES = 3               # advisory bridge labels rendered
_MAX_HOOK_REPROJECT_NOTES = 400  # ~the scale where pure-Python betweenness nears the 5s kill cap; above it
                                 # the hook serves only a fresh index (0.10.1)
# The hook's short canon-lease TTL: precontext.mjs kills us at 5s, a killed hook leaves its lease
# behind, and on Windows a dead pid can't be probed — so the lease must expire well inside the
# writers' 30s acquire budget (review-r4: hook-kill-wedges-windows-writers). While the hook is ALIVE
# the projection's heartbeats keep the lease fresh, so a legitimate slow projection is never stolen.
_HOOK_LEASE_TTL = 15.0


def main() -> int:
    try:
        # Decode stdin as UTF-8 explicitly — json.load(sys.stdin) would use the locale text
        # encoding, so a non-ASCII payload mojibakes (empty kg_context match) or raises
        # UnicodeDecodeError on a non-UTF-8 locale (e.g. Windows cp1252), silently disabling
        # precontext for unicode payloads. Reading bytes makes the decode deterministic.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return 0
    if not isinstance(payload, dict) or _blind_caller(payload):
        return 0  # a measurement subagent works blind (see _BLIND_AGENTS)
    # Every resolution below goes through kg_engine.envconfig — the SAME single-homed rules the
    # server's build_engine_from_env uses (review-r5: this hook used to carry a hand-synced copy of
    # the whole chain, and the review-r4 ${...} placeholder-filter fix had landed only in the server
    # copy, so an unsubstituted ${user_config.metrics_mode} passed through here as a real value).
    # The hook's two documented differences are explicit knobs, not forks: `plugin_data_fallback`
    # (its env lacks the .mcp.json KG_DATA=${CLAUDE_PLUGIN_DATA} wiring, so it reads the source var)
    # and `plugin_root` (on an installed plugin the project dir has no pack/pack.yaml; a project-only
    # lookup would wire EMPTY specificity seeds into a projection the server then serves as fresh —
    # finding: precontext-bypasses-facade).
    try:
        from kg_engine import envconfig
    except Exception:
        return 0  # no plugin root / scripts on path — the fail-silent contract
    project = envconfig.resolve_project(payload.get("cwd"))
    if not project:
        return 0
    try:
        if _targets_workspace(payload, project):
            return 0  # Burgess's own working files, never the project's knowledge (see _BLIND_AGENTS)
    except (OSError, ValueError):
        pass  # an unresolvable path is no reason to withhold context
    data = envconfig.resolve_data_dir(project, plugin_data_fallback=True)
    # Check the index exists BEFORE constructing the engine — this hook runs on every Grep/Glob/Read;
    # don't build context (or touch the derived tree) when nothing has been projected yet. The names
    # come from the same envconfig leaf the projector consumes, so they can't drift (review-r5).
    if not (data / envconfig.DERIVED_DIRNAME / envconfig.INDEX_DB_NAME).exists():
        return 0
    source = envconfig.resolve_source(project)
    pack_path = envconfig.resolve_pack_path(project, plugin_root=root or None)
    metrics_mode = envconfig.plugin_option("METRICS_MODE", "structure_only")
    try:
        from kg_engine.server import KGEngine
        # read_only_projector wires source/pack/metrics through the SAME seam as the server AND keeps a
        # no-side-effect Canon(ensure_layout=False): a pure read path that never mkdir's the canon dir or
        # rewrites .git/info/exclude on a plain Grep/Glob/Read (the writer-side server maintains those).
        # The derived dir exists (index.sqlite checked above), so the projector's own mkdir is a no-op.
        # lease_ttl=_HOOK_LEASE_TTL is the SIGKILL bound (see the constant's rationale above) — set
        # through the constructor seam rather than a reach-through mutation of proj.canon.lock.ttl.
        proj = KGEngine.read_only_projector(project, data, source_path=source, pack_path=pack_path,
                                            metrics_mode=metrics_mode, lease_ttl=_HOOK_LEASE_TTL)
        if not proj.db_path.exists():
            return 0  # nothing projected yet
        # Mirror the server's lazy-reproject gate (server._ensure_projected): a raw kg_context read off a
        # stale projection would inject obsolete provenance / epistemic labels. The index already exists
        # (guarded above), so this is a cheap incremental reproject, never a side-effecting cold build.
        # SIZE-GATED: this hook runs on every Grep/Glob/Read and is killed at 5s, and a projection's
        # betweenness pass is O(V·E) — on a large canon it can NEVER finish inside the cap, so every
        # read tool would burn 5s of CPU and get killed again, forever, while serving nothing
        # (review-r4: hook-reprojects-doomed-on-large-canons).
        # Above the gate the hook injects NOTHING while the index is stale (0.10.1), and the server's own
        # next read reprojects. Through 0.10.0 it served the stale index there, and on a canon of 410
        # notes a Grep made right after six kg_merge calls was shown the edges of two nodes those
        # merges had retired; the session took it for a bug (field report on 0.10.0). `is_stale()`
        # needs no projection: past its O(dir-listing) pre-gate it re-parses only the notes whose stat
        # moved, and an mtime-only touch re-arms the pre-gate, so the hook falls silent only when the
        # canon or the source really changed.
        if proj.is_stale():
            if len(proj.canon.note_paths()) > _MAX_HOOK_REPROJECT_NOTES:
                return 0
            proj.project()
        ti = payload.get("tool_input", {})
        query = ti.get("pattern") or ti.get("query") \
            or (pathlib.Path(ti.get("file_path", "")).stem or None)
        ctx = proj.kg_context(query, budget=_CONTEXT_BUDGET)
        if not ctx["items"] and not ctx["advisory"]["nodes"]:
            return 0
        lines = ["Burgess (query the graph first; provenance + falsification attached):"]
        for it in ctx["items"][:_MAX_ITEMS]:
            lines.append(f"- {it['source']} --{it['relation']}--> {it['target']} "
                         f"[{it['provenance']}/{it['epistemic_state']}]")
        fc = ctx["falsification_counters"]["failed_or_rejected_edges"]
        if fc:
            lines.append(f"- {fc} falsified/rejected edge(s) on record (memory of failures)")
        if ctx["advisory"]["nodes"]:
            br = ", ".join(n["label"] for n in ctx["advisory"]["nodes"][:_MAX_BRIDGES])
            lines.append(f"- structural-bridge advisory (heuristic, NOT a guarantee): {br}")
        emit("\n".join(lines))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
