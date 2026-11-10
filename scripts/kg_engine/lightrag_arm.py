"""The optional `lightrag` experiment arm (§Stage 8) — an isolated LightRAG GraphRAG baseline.

This module is the ONLY place the plugin touches LightRAG, and it is deliberately quarantined:

  * **No engine module imports it.** Nothing in `kg_engine` has a hard dependency on LightRAG; this
    file is reached only as a standalone CLI (`python -m kg_engine.lightrag_arm ...`) that the
    `kg-evaluator` subagent invokes when — and only when — the operator opts in. The `lightrag`
    import lives inside the functions, so importing this module (e.g. in a test) never requires the
    package to be installed.
  * **Off by default.** The arm runs only when ALL of: `KG_LIGHTRAG=1` (explicit opt-in), the
    `lightrag-hku` package is importable, and `OPENAI_API_KEY` is set (LightRAG's default LLM +
    embedding backend is OpenAI). Absent any of these, `availability()` reports the arm unavailable
    and the evaluator omits it cleanly — the original four-arm experiment is unchanged.
  * **Same corpus, prose only.** The index is built from `examples/source.md` (the identical corpus
    the flat `rag` arm uses), through LightRAG's own retrieval. This module NEVER reads the canon's
    epistemic_state, bridges, falsification counters, degree, or any `kg_*` graph output — it sees
    flat prose, exactly like `rag`. It writes no verdict and no edge; it does not import the MCP
    boundary at all.
  * **Derived, gitignored, disposable.** The LightRAG working store (index/vectors/cache) lives under
    the engine's derived dir (`<KG_DATA or $CLAUDE_PROJECT_DIR/.kg-data>/derived/lightrag`), which is
    already gitignored. It is a regenerable cache, never source of truth.

LightRAG is a SEPARATE framework (PyPI `lightrag-hku`, import `lightrag`); its philosophy
(embedding-as-truth, spanless LLM relations, a retrieval-comprehensiveness objective) is explicitly
NOT imported into the engine — LightRAG appears here only as an external comparison arm.

The verified minimal API used below (lightrag-hku):
    from lightrag import LightRAG, QueryParam
    from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed
    from lightrag.kg.shared_storage import initialize_pipeline_status
    rag = LightRAG(working_dir=..., llm_model_func=gpt_4o_mini_complete, embedding_func=openai_embed)
    await rag.initialize_storages(); await initialize_pipeline_status()
    await rag.ainsert(text); await rag.aquery(prompt, param=QueryParam(mode="mix"))
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

# The env cleaner, data-dir rule, and derived-layer names are single-homed in envconfig
# (review-r5) — a stdlib leaf, so this isolated module still never imports the MCP server stack.
from .envconfig import DERIVED_DIRNAME
from .envconfig import clean_env as _clean_env
from .envconfig import plugin_option
from .envconfig import resolve_data_dir as _resolve_data_dir
from .envconfig import resolve_project as _resolve_project
from .sources import SourceSet

# A marker LightRAG writes once a document has been indexed into a working_dir, so a second run loads
# the cached index instead of re-extracting (which would re-spend LLM tokens on entity extraction).
_INDEX_MARKER = "kv_store_full_docs.json"
# A sidecar recording the source content signature the current index was built from. Keying the rebuild
# decision only on _INDEX_MARKER's presence served a CHANGED source from a stale index; comparing this
# signature forces a re-insert when the corpus content changed.
_SIGNATURE_FILE = "kg_source_signature.json"


def _source_signature(source_path: Path) -> str:
    """A cheap content signature of the corpus: ``sources.SourceSet.signature``, one ``(name, size,
    mtime_ns)`` per resolved document (no content read). ``st_mtime_ns`` is nanosecond-resolution so even a
    same-second in-place edit invalidates it. A missing source yields a stable placeholder rather than
    raising, so callers can compare freely.

    Through 0.11.3 this stat()ed the path itself. For a folder source (0.11.4) that is the folder's own
    entry, whose mtime does not move when a document inside is edited in place, so a stale index would
    have been served; the per-document signature catches it."""
    return json.dumps(SourceSet.signature(source_path))


def _needs_rebuild(working_dir: Path, source_path: Path) -> bool:
    """Rebuild the index when it's ABSENT or the source's content signature changed since it was built.
    A recorded signature that matches the current source means the cached index is fresh and reusable."""
    if not (working_dir / _INDEX_MARKER).exists():
        return True
    try:
        cached = (working_dir / _SIGNATURE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return True  # index present but no recorded signature → treat as stale and rebuild
    return cached != _source_signature(source_path)


def default_store_dir() -> Path:
    """The LightRAG working store, under the engine's (gitignored) derived dir — the SAME data-dir
    rule a KGEngine resolves (``KG_DATA`` if set, else ``<project>/.kg-data``; the rule's one home
    is ``envconfig``), then ``/derived/lightrag``."""
    base = _resolve_data_dir(_resolve_project(os.getcwd()))
    return base / DERIVED_DIRNAME / "lightrag"


def query_mode() -> str:
    """LightRAG retrieval mode (``KG_LIGHTRAG_QUERY_MODE``, default ``mix`` — merges local+global)."""
    return _clean_env("KG_LIGHTRAG_QUERY_MODE") or "mix"


def availability() -> tuple[bool, str]:
    """Is the optional `lightrag` arm runnable here? Returns (available, reason).

    Off unless ALL three hold, checked in opt-in → package → credential order so the reason names the
    first missing piece: `KG_LIGHTRAG=1`, the `lightrag` package importable, and `OPENAI_API_KEY` set.
    Pure inspection — never imports lightrag, never touches the graph."""
    if _clean_env("KG_LIGHTRAG") not in ("1", "true", "True", "yes", "on"):
        return False, "disabled: set KG_LIGHTRAG=1 to enable the optional LightRAG GraphRAG arm"
    if importlib.util.find_spec("lightrag") is None:
        return False, "package not installed: pip install lightrag-hku (optional)"
    if not _clean_env("OPENAI_API_KEY"):
        return False, "missing credential: OPENAI_API_KEY (LightRAG's default LLM/embedding backend)"
    return True, "available"


async def _answer_async(prompts: list[str], source_path: Path, working_dir: Path) -> list[str]:
    """Init storages, build/load the index, and answer EVERY prompt inside ONE event loop.

    LightRAG binds its locks/futures to the loop that ran `initialize_storages()`; the old shape ran init
    in one `asyncio.run` loop (which then closed) and each query in a fresh loop, so every `aquery` awaited
    cross-loop against now-stale storage and failed. Keeping init + all queries on a single loop fixes that;
    `finalize_storages()` in a `finally` releases the storages so the working_dir is left clean for reuse.

    All LightRAG imports are local so the package is required only on this opt-in path."""
    from lightrag import LightRAG, QueryParam
    from lightrag.kg.shared_storage import initialize_pipeline_status
    from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed

    working_dir.mkdir(parents=True, exist_ok=True)
    # §1.9 egress scrub: LightRAG's ainsert() ships the corpus to OpenAI for entity/embedding
    # extraction, so the raw source must be scrubbed first — matching the boundary's own contract and
    # backend.py's per-section scrub, rather than being the one egress point that bypasses it
    # (review-r8-9). No restore is needed (this arm never writes back to the canon); on the intended
    # public examples/source.md the scrub is a no-op, so experiment results are unchanged.
    from .scrub import Scrubber
    # The corpus as the projector reads the configured source (0.11.4): one file, or a folder (or glob) of
    # .md/.txt documents, concatenated in SourceSet's stable order. A single file reads byte-identically.
    raw = SourceSet(source_path).concat
    text = Scrubber(plugin_option("SENSITIVITY", "medium")).scrub(raw)[0]
    mode = query_mode()

    rag = LightRAG(working_dir=str(working_dir),
                   llm_model_func=gpt_4o_mini_complete,
                   embedding_func=openai_embed)
    try:
        # init INSIDE the try so a failure of initialize_pipeline_status() (or of initialize_storages
        # itself, which may leave partially-opened storages) still reaches finalize_storages() and leaves
        # the working_dir clean for reuse — previously init ran BEFORE the try, so an init-path failure
        # leaked the storages (review-fix).
        await rag.initialize_storages()
        await initialize_pipeline_status()
        # build the index the first time OR when the source content changed — a populated working_dir
        # matching the recorded signature is reused as a cache; a changed source re-inserts (and the
        # signature is re-recorded) so a stale index is never served.
        if _needs_rebuild(working_dir, source_path):
            await rag.ainsert(text)
            (working_dir / _SIGNATURE_FILE).write_text(_source_signature(source_path), encoding="utf-8")
        answers: list[str] = []
        for prompt in prompts:
            ans = await rag.aquery(prompt, param=QueryParam(mode=mode))
            answers.append(str(ans).strip())
        return answers
    finally:
        # best-effort: never let a cleanup error mask the real failure being propagated
        try:
            await rag.finalize_storages()
        except Exception:  # noqa: BLE001 — opt-in experiment arm; cleanup is advisory
            pass


def answer_prompts(prompts: list[str], source_path: Path, working_dir: Path | None = None) -> list[str]:
    """Answer each prompt from a LightRAG index built over `source_path`: the configured source, one file
    or a folder of .md/.txt documents (examples/source.md in the demo).

    Builds/loads the index once, then queries it per prompt — all on a SINGLE event loop. Raises if the
    arm is unavailable (the caller is expected to gate on `availability()` first) or if `source_path` is
    missing (the CLI maps that to the clean exit-3 'unavailable' path)."""
    import asyncio

    ok, reason = availability()
    if not ok:
        raise RuntimeError(f"lightrag arm unavailable: {reason}")
    if not SourceSet.resolve(source_path):
        raise FileNotFoundError(f"source not found or holds no .md/.txt document: {source_path}")
    working_dir = working_dir or default_store_dir()
    return asyncio.run(_answer_async(prompts, source_path, working_dir))


def _load_prompts(path: Path) -> list[str]:
    """Load prompts from a JSON array of strings, a ``{"prompts": [...]}`` object, or newline-delimited
    text — whichever the evaluator wrote."""
    raw = path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if isinstance(data, dict):
        data = data.get("prompts", [])
    if not isinstance(data, list):
        raise ValueError("prompts file must be a JSON array, a {'prompts': [...]} object, or one prompt per line")
    return [str(x) for x in data]


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m kg_engine.lightrag_arm",
                                description="Optional LightRAG GraphRAG arm for the ideation experiment.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="report whether the lightrag arm is runnable (JSON {available, reason})")

    ans = sub.add_parser("answer", help="build/load the index and answer prompts (JSON {answers: [...]})")
    ans.add_argument("--source", required=True,
                     help="the corpus: one file, or a folder of .md/.txt documents (the configured source_path)")
    ans.add_argument("--prompts", required=True, help="path to prompts (JSON array / {prompts:[]} / lines)")
    ans.add_argument("--out", help="write the answers JSON here instead of stdout")
    ans.add_argument("--store", help="LightRAG working dir (default: <derived>/lightrag)")

    args = p.parse_args(argv)

    if args.cmd == "check":
        ok, reason = availability()
        print(json.dumps({"available": ok, "reason": reason}))
        return 0

    # answer
    ok, reason = availability()
    if not ok:
        print(json.dumps({"available": False, "reason": reason}), file=sys.stderr)
        return 3  # distinct from argparse(2)/generic-error(1): "arm cleanly unavailable, omit it"
    store = Path(args.store) if args.store else default_store_dir()
    try:
        # _load_prompts sits INSIDE the try with answer_prompts: a missing or wrong-shaped --prompts file
        # (FileNotFoundError / ValueError) is the same class of operator error as a bad --source, and the
        # kg-evaluator subagent that drives this CLI must never see a raw traceback. Previously only the
        # bad-source path was mapped to the clean exit-3, and the arm's own CLI test never reached this
        # line because it returns 3 above on the unavailable path (review-r11).
        prompts = _load_prompts(Path(args.prompts))
        answers = answer_prompts(prompts, Path(args.source), store)
    except (FileNotFoundError, ValueError, OSError) as e:
        print(json.dumps({"available": False, "reason": str(e)}), file=sys.stderr)
        return 3  # bad source/prompts surfaces as the clean 'arm unavailable, omit it' path, not a traceback
    blob = json.dumps({"answers": answers}, indent=2)
    if args.out:
        Path(args.out).write_text(blob + "\n", encoding="utf-8")
        print(args.out)
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
