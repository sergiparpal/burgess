# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Burgess is a Claude Code **plugin** fusing two engines around one trust boundary: a **convergence** engine (grounded knowledge graph extracted from a source document) and a **divergence** engine (MAP-Elites/DPP ideation). The design razor that resolves disputes here: **embeddings measure dispersion, never truth.**

## Commands

```bash
uv sync --extra dev                  # install (or: pip install -e ".[dev]"; CI uses ".[dev,backend]")
uv run pytest tests/                 # full suite (pyproject sets -q; ~1200 tests, no network needed)
uv run pytest tests/test_grounding.py::test_name   # single test
uv run pytest -m "not selftest"      # faster loop (skips divergence selftest e2e) — run the FULL suite before committing
```

Other gates CI runs (all from repo root):

```bash
python -m kg_engine.pack validate pack/pack.yaml examples/source.md   # pack ↔ source coverage
python -m kg_engine.harness agreement|specificity|ideation|convergence   # eval harness CLIs
python scripts/validate_plugin.py    # manifest/component structural check (enforces plugin.json version == kg_engine.__version__)
claude plugin validate ./ --strict   # real plugin validator (best-effort in CI)
python scripts/check_donors_clean.py # donor pin gate — see "Donors" below; installed as local pre-commit hook
```

Dev extras: `python -m kg_engine.divergence <init-project|paths|ingest|recall|remember|parents|metrics|selftest|import-cambrian>` (divergence CLI, no MCP needed); `python -m kg_engine.backend` (headless API extraction; needs the `backend` extra). Run the plugin live with `claude --plugin-dir /path/to/Burgess` — the MCP server refuses to start until the required `source_path` userConfig is set.

Notes:
- **No linter/formatter is configured.** pytest is the only gate.
- `uv.lock` is deliberately **gitignored** (per-machine, built by provisioning).
- Node ≥ 20 is needed for the launcher tests (`tests/test_launchers.py`); without it they skip silently.
- The test count in README.md between `<!-- test-count:begin/end -->` is **generated from pytest output** — regenerate it when the count changes, never hand-edit it.

## Architecture

Two layers, one boundary:

1. **Deterministic Python engine** — `scripts/kg_engine/`. Exposed as the `burgess` MCP server (27 tools, namespaced `mcp__plugin_burgess_burgess__*`). `server.py` is the KGEngine facade + FastMCP tool surface = the trust boundary. The engine is **never installed**: it resolves via `PYTHONPATH=<repo>/scripts` (see `.mcp.json`), so engine source edits need no rebuild; the venv (built by `scripts/bootstrap.py`, triggered by the SessionStart hook, dev fallback `<repo>/.venv`) holds only dependencies.
2. **Language layer** — 9 slash commands (`commands/kg-*.md`), 6 subagents (`agents/`: extractor, grounder, adversarial-grounder, generator, annotator, evaluator), the operating-guide skill (`skills/burgess/SKILL.md` + on-demand `references/`). LLM work happens ONLY here; agents hand structured JSON back across the MCP boundary. The engine stays rule-bound.

`scripts/launch_server.mjs` supervises the Python engine (cold-start venv self-heal, restart policy); `hooks/precontext.mjs` (PreToolUse on Grep/Glob/Read) injects grounded graph context, fails silent.

### Convergence spine (canon vs derived)

- **Canon** = source of truth: one human-editable Markdown file per node at `<project>/canon/<id>.md` (YAML frontmatter; directed edges live in the source node's `edges:` block). Carries the grounding state.
- **Derived** = disposable projection (`$CLAUDE_PLUGIN_DATA/derived/{graph.json,index.sqlite}`, built by `projector.py`). Contains nothing the canon does not; never hand-edit — reproject.
- **Three orthogonal axes, never collapsed to one scalar**: `provenance` (span-present|inferred|hypothesized), `authored_by` (deterministic|agent|human), `epistemic_state` (unverified|grounded|rejected|failed|obsolete).
- **Write path**: `kg_write` → `boundary.py` validation → dispositions `ACCEPTED` / `DEMOTED` / `QUARANTINED` (undeclared pack type) / `REJECTED`. Every non-deterministic edge must carry a **verbatim** source span (span-present); a payload asserting a verdict or human/deterministic authorship is DEMOTED (never-forge-a-verdict).
- **Verdict monopoly**: only `kg_ground` sets epistemic states; `reconciler.py` re-quarantines out-of-band verdict edits. `rejected`/`failed` edges are permanent negative memory — never pruned, surfaced in `kg_context` falsification counters.
- **Domain pack**: `pack/pack.yaml` declares the node/edge type vocabulary (plus an optional `divergence:` config section); templates in `pack/domains/`.

### Divergence engine

`scripts/kg_engine/divergence/` — model2vec embedder (deterministic hash embedder in tests/offline), MAP-Elites archive, k-NN novelty, DPP slates, anti-collapse monitor. Constraints, all test-enforced in `tests/fusion/`:

- **Import firewall** (**I3**, both directions, `tests/fusion/test_divergence_firewall.py`): no grounding/verdict/reconciler module may import `divergence` even lazily, and no module under `divergence/` may import anything in `kg_engine` outside its own siblings and the capability-free leaves `atomicio`/`envconfig` (allowlist) — so nothing there can set or upgrade an epistemic state.
- **Advisory ceiling**: geometry (DPP order, novelty, cliché distance) affects what is proposed and in what order, never what is true — grounding output is snapshot-tested bit-identical with `divergence.dpp` on vs off.
- **Ephemerality**: archives live under project-local `.kg/diverge/` and die with the session; only pins/discards/comparisons persist. Pins enter the graph ONLY via the propose lane (`kg_propose`/`kg_diverge_materialize`) as `provenance=hypothesized, epistemic_state=unverified` — the next `/kg-ground` is the filter.
- **Graceful degradation**: every `kg_*` graph tool works with divergence deps blocked.

### Workflow the commands implement

build → ground → generate → ground → query → eval → experiment. Generation is offensive (emits into the `hypothesized` lane, never gates on a metric); grounding is the only defensive filter and the only verdict path.

### Tests

`tests/` = vendored convergence suite (files named `test_fix_*`, `test_rfix_*`, `test_review_*` pin regressions from past reviews — keep them green); `tests/fusion/` = the eleven fusion invariants I1–I11; `tests/fusion/divergence/` = ported donor suite. `tests/conftest.py` provides a git-backed temp canon `vault`, a configured `engine` (KGEngine), and the real `pack`.

## Donors (read-only)

Burgess was fused from two pinned donor repos expected as siblings: `../sproutgraph` @ `17c4066` and `../cambrian` @ `a2adfa1` (`scripts/donor_pins.json`). `scripts/check_donors_clean.py` (invariant I11) must pass before every commit.

The gate asserts that each pinned Stage-0 commit **still exists and is reachable from the donor's `HEAD`** — not that `HEAD` still equals it. I11 protects a historical fact (the fusion never wrote to a donor), and the original frozen-`HEAD` rule was a proxy for it that held only while both donors stayed retired. Cambrian has since been republished and resumed development, so the proxy began failing on every commit while the invariant stayed intact. Reachability keeps what the invariant is actually for: the copied-from tree remains recoverable with `git show <sha>`, so every `ATTRIBUTION.md` claim stays checkable. An *unreachable* pin is still a hard failure — that is where provenance is genuinely lost. Donor working-tree cleanliness and an unmoved `HEAD` are deliberately no longer asserted; a live repo has neither, and neither says anything about what the fusion did.

## Conventions and gotchas

- Comments and docs cite plan sections (`§1.5`, `§2.2`) and invariant/decision IDs (`I1`–`I11`, `D1`–`D5`). The decision record lives in `docs/fusion/` (FUSION_PLAN.md, DECISIONS.md, PLAN_STATE.md, EXPERIMENT.md, ATTRIBUTION.md) — consult it before changing invariant-adjacent behavior; code comments here carry rationale, keep that density when editing.
- `docs/ARCHITECTURE.md` is the self-contained architecture reference (no donor doc was ever vendored — see `docs/fusion/ATTRIBUTION.md`). The engine source stays the final authority: when in doubt about a field or symbol, grep `scripts/kg_engine` rather than guessing, and keep ARCHITECTURE.md in sync when invariant-adjacent behavior changes.
- Runtime/session state at the project root (`.kg/`, `.kg-ground-audit.jsonl*`, `.kg-reconcile-state.json`, `derived/`) is gitignored engine state, never canon.
- `canon/*.md` routes through the `kgcanon` semantic merge driver (`.gitattributes`); activation is an opt-in `git config` per clone (see the comment in `.gitattributes`).
- Engine env contract (`.mcp.json`): `KG_PROJECT_DIR`, `KG_DATA`, `KG_PACK_PATH`, `KG_SOURCE_PATH`; `KG_ENGINE_VENV` overrides the venv; divergence knobs are `KG_DIVERGE_*`; the optional lightrag experiment arm needs the `lightrag` extra + `KG_LIGHTRAG=1` + `OPENAI_API_KEY`.
- **Git workflow:** `main` is protected by a branch ruleset — direct pushes are rejected, and merging requires the `ci-complete` status check to pass. So: branch, push, open a PR, let CI go green, merge. Review approvals are **not** required (the count is 0), so a solo change is still a one-person operation — the gate is CI, not a second pair of eyes. `ci-complete` (`.github/workflows/ci.yml`) is a single aggregating job that fails unless `test` succeeded; `plugin-validate` stays out of its `needs:` because it is `continue-on-error` by its author's intent. **Any new job that must gate merges has to be added to that `needs:` list.** The ruleset requires that one stable name rather than the individual matrix legs, because a dropped Python version would otherwise become a required check that never reports again and blocks every merge.
- **Actions are pinned to full commit SHAs** with a trailing `# vX.Y.Z` comment, never to tags — a tag can be repointed by its upstream owner, a commit SHA cannot. Keep new `uses:` lines pinned the same way. This posture (ruleset + `ci-complete` + SHA pins + `permissions: contents: read` + per-job `timeout-minutes`) is shared across all six plugin repositories in this account.
- **`mcp>=1.2,<2` is load-bearing — do not bump it as routine.** mcp 2.0.0 removed `mcp.server.fastmcp` and the `FastMCP` class outright (the server API moved to `mcp.server.mcpserver`), so `server.py`'s import raises `ModuleNotFoundError` at startup and every `kg_*` tool disappears for the session. Adopting 2.x is a port of the tool surface + `readiness_lifespan`, not a version edit. `tests/test_review_r12.py` asserts the import path with a hard assertion (never `importorskip` — that would skip on exactly the bump that breaks production), and `.github/dependabot.yml` ignores mcp **major** updates only, so 1.x security patches keep flowing. Delete that ignore entry as part of the port, not before it.
- **The version lives in five places** (both `.claude-plugin` manifests, `pyproject.toml`, `kg_engine.__version__`, `kg_engine.divergence.__version__`). Bump all five at once with `python scripts/bump_version.py --to X.Y.Z --write` (or `--part minor`); it is a dry run without `--write`, and refuses to bump from an inconsistent state. `tests/test_version_consistency.py` gates that they agree.
