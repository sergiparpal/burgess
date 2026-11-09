"""Regression tests for review-r5 (the 2026-07-03 maintainability review): duplicated knowledge
that had drifted across file/language boundaries, now single-homed (findings 1.1-1.6), plus the
§2 comment-coupled-twin pins (the Node<->Python contract parity test and the dirlock extraction)
added when sections 2-7 landed.

Covers, in finding order:
  1.1 The `##` section rule has ONE home (sources.split_sections/section_corpus): semantics pinned
      (tab headings, ### stays in body, preamble emission, include_heading), the backend delegate
      is behavior-identical, and the retired per-file algorithms cannot silently return.
  1.2 env/config resolution has ONE home (envconfig): the ${...} placeholder filter applies to
      plugin options everywhere (the hook's metrics_mode had missed the review-r4 fix), the pack
      precedence is shared (engine → divergence via the threaded pack_path, so no split-brain),
      and KG_DIVERGE_HOME is honored through the explicit-project base_dir path the server uses.
  1.3 Atomic writes have ONE implementation (atomicio): the divergence state store and the canon
      merge driver delegate instead of carrying drifted copies.
  1.4 The failure-state vocabulary has ONE home (model.FAILURE_STATE_VALUES): consumers derive it,
      and the rendered graph.html gets it injected rather than hand-typed.
  1.5 Provisioning has ONE implementation (provision.mjs on _engine_resolve.systemPython); the
      sh/ps1 files are shims; the probe timeout constant lives once.
  1.6 pipeline's fallback knobs DERIVE from EngineConfig instead of hand-mirroring it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from kg_engine import envconfig
from kg_engine.divergence import config as dconfig
from kg_engine.divergence import state as dstate
from kg_engine.model import FAILURE_STATE_VALUES, FAILURE_STATES
from kg_engine.sources import section_corpus, split_sections

REPO = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# --- 1.1 section splitting ----------------------------------------------------------------------

def test_split_sections_semantics_pinned():
    text = "intro line\n## Alpha\nbody a\n### deeper\nstill a\n##\tTabbed\nbody t\n## \nuntitled body"
    secs = split_sections(text, preamble_title="(preamble)")
    # preamble emitted with the label; ### stays inside Alpha's body; a TAB heading splits (the
    # backend's regex rule, unified); an empty `## ` heading falls back to the preamble label.
    assert [t for t, _ in secs] == ["(preamble)", "Alpha", "Tabbed", "(preamble)"]
    assert secs[1][1] == "body a\n### deeper\nstill a"
    assert secs[2][1] == "body t"


def test_split_sections_include_heading_keeps_payload_unit():
    text = "## Alpha\nbody a\n## Beta\nbody b"
    secs = split_sections(text, include_heading=True)
    assert secs == [("Alpha", "## Alpha\nbody a"), ("Beta", "## Beta\nbody b")]
    # the backend's slicer is a delegate of the shared rule, not a second algorithm
    from kg_engine.backend import BackendExtractor
    assert BackendExtractor.split_sections(text) == secs


def test_section_corpus_shape(engine):
    text = "intro\n## Alpha\nbody a\n## Beta\nbody b"
    assert section_corpus(text) == ["intro", "Alpha\nbody a", "Beta\nbody b"]
    assert section_corpus("") == []
    assert section_corpus("\n\n") == []  # whitespace-only sections are dropped
    # the projector's IDF corpus IS the shared corpus (bit-identical by construction): the engine
    # fixture's source has no `##` headings, so both sides see the one-document corpus.
    assert engine.projector._corpus() == section_corpus(engine.source_text())


def test_retired_splitter_algorithms_cannot_return():
    # the three per-file algorithms are gone; the rule lives only in sources.py
    assert 'split("\\n## ")' not in _src("scripts/kg_engine/projector.py")
    assert 'split("\\n## ")' not in _src("scripts/kg_engine/harness.py")
    assert 'startswith("## ")' not in _src("scripts/kg_engine/server.py")
    assert 're.match(r"^##' not in _src("scripts/kg_engine/backend.py")


# --- 1.2 env/config resolution ------------------------------------------------------------------

def test_plugin_option_filters_unsubstituted_placeholder(monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_METRICS_MODE", "${user_config.metrics_mode}")
    assert envconfig.plugin_option("METRICS_MODE", "structure_only") == "structure_only"
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_METRICS_MODE", "full")
    assert envconfig.plugin_option("METRICS_MODE", "structure_only") == "full"


def test_clean_strips_placeholders_and_venv_sentinels():
    for bad in ("", "   ", "${user_config.source_path}", "/.venv", "/venv"):
        assert envconfig.clean(bad) == ""
    assert envconfig.clean(" /real/path ") == "/real/path"


def test_hook_resolves_through_envconfig_not_a_local_copy():
    hook = _src("hooks/precontext.py")
    # the pre-sys.path CLAUDE_PLUGIN_ROOT read is the ONE permitted local _clean; everything else
    # must route through envconfig, so the r4 placeholder-filter class of drift cannot re-enter.
    assert "envconfig.resolve_project" in hook
    assert "envconfig.resolve_data_dir" in hook
    assert "envconfig.resolve_pack_path" in hook
    assert 'plugin_option("METRICS_MODE"' in hook
    assert 'os.environ.get("CLAUDE_PLUGIN_OPTION_' not in hook


def test_resolve_pack_path_precedence(tmp_path, monkeypatch):
    for key in ("KG_PACK_PATH",):
        monkeypatch.delenv(key, raising=False)
    proj, root = tmp_path / "proj", tmp_path / "root"
    (proj / "pack").mkdir(parents=True)
    (root / "pack").mkdir(parents=True)
    (proj / "pack" / "pack.yaml").write_text("domain: p\n", encoding="utf-8")
    (root / "pack" / "pack.yaml").write_text("domain: r\n", encoding="utf-8")
    # plugin root (the hook's knob) beats the project fallback; project is found without it
    assert envconfig.resolve_pack_path(proj, plugin_root=str(root)) == str(root / "pack" / "pack.yaml")
    assert envconfig.resolve_pack_path(proj) == str(proj / "pack" / "pack.yaml")
    # env wins over both; a ${...} placeholder env reads as unset
    monkeypatch.setenv("KG_PACK_PATH", str(root / "pack" / "pack.yaml"))
    assert envconfig.resolve_pack_path(proj) == str(root / "pack" / "pack.yaml")
    monkeypatch.setenv("KG_PACK_PATH", "${CLAUDE_PLUGIN_ROOT}/pack/pack.yaml")
    assert envconfig.resolve_pack_path(proj) == str(proj / "pack" / "pack.yaml")


def test_resolve_data_dir_rule_and_hook_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("KG_DATA", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    assert envconfig.resolve_data_dir(tmp_path) == tmp_path / envconfig.DATA_DIRNAME
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plug"))
    # the server chain ignores CLAUDE_PLUGIN_DATA (its KG_DATA is wired by .mcp.json)...
    assert envconfig.resolve_data_dir(tmp_path) == tmp_path / envconfig.DATA_DIRNAME
    # ...the hook's documented adaptation opts in explicitly
    assert envconfig.resolve_data_dir(tmp_path, plugin_data_fallback=True) == tmp_path / "plug"
    monkeypatch.setenv("KG_DATA", str(tmp_path / "d"))
    assert envconfig.resolve_data_dir(tmp_path, plugin_data_fallback=True) == tmp_path / "d"


def test_engine_threads_its_pack_into_divergence_axes(engine, tmp_path, monkeypatch):
    # the engine records WHICH pack it loaded...
    assert engine.pack_path is not None and engine.pack_path.name == "pack.yaml"
    # ...and resolve_axes_source prefers that explicit pack over the env, so the kg_diverge_*
    # tools can never load a different domain config than the engine in the same process.
    monkeypatch.delenv("KG_PACK_PATH", raising=False)
    pack = tmp_path / "pack.yaml"
    pack.write_text("domain: t\ndivergence:\n  axes:\n    - name: m\n      type: open\n",
                    encoding="utf-8")
    assert dconfig.resolve_axes_source(None, pack_path=pack) == pack
    # with no explicit pack and only a placeholder env value, the generic fallback is used
    monkeypatch.setenv("KG_PACK_PATH", "${CLAUDE_PLUGIN_ROOT}/pack/pack.yaml")
    resolved = dconfig.resolve_axes_source(None)
    assert Path(resolved).name == "generic.yaml"


def test_diverge_home_honors_override_through_explicit_project(tmp_path, monkeypatch):
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    monkeypatch.delenv("KG_PROJECT_DIR", raising=False)
    proj = tmp_path / "proj"
    # the server passes its resolved project dir explicitly...
    assert dstate.base_dir(proj) == proj / ".kg" / "diverge"
    # ...and KG_DIVERGE_HOME still wins over it (I8: one home for pins/discards, CLI and MCP alike)
    override = tmp_path / "custom"
    monkeypatch.setenv("KG_DIVERGE_HOME", str(override))
    assert dstate.base_dir(proj) == override
    # the server-side helper routes through this rule (not a hardcoded project path); it lives on
    # the facade (KGEngine._diverge_home) since the materialize logic moved out of the closures
    assert "base_dir(self.project_dir)" in _src("scripts/kg_engine/server.py")


# --- 1.3 atomic writes --------------------------------------------------------------------------

def test_single_atomic_write_implementation(tmp_path):
    # functional: the divergence state writer round-trips through the shared atomicio protocol
    target = tmp_path / "nested" / "x.json"
    dstate._atomic_write(target, '{"a": 1}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    # and neither former copy carries its own temp+replace protocol anymore (docstrings may still
    # NAME mkstemp — the sweep in state.py describes atomicio's identically-prefixed temps)
    assert "tempfile.mkstemp(" not in _src("scripts/kg_engine/divergence/state.py")
    assert "tempfile.mkstemp(" not in _src("scripts/kg_engine/canonmerge.py")
    assert "atomic_write_bytes" in _src("scripts/kg_engine/canonmerge.py")


def test_canonmerge_write_stays_lf_and_fail_open(tmp_path):
    from kg_engine.canonmerge import _write_atomic
    p = tmp_path / "note.md"
    p.write_text("old", encoding="utf-8")
    _write_atomic(p, "line1\nline2\n")
    assert p.read_bytes() == b"line1\nline2\n"  # bytes mode: no CRLF translation, ever


# --- 1.4 failure-state vocabulary ---------------------------------------------------------------

def test_failure_state_values_is_the_derived_form():
    assert FAILURE_STATE_VALUES == {s.value for s in FAILURE_STATES}
    assert isinstance(FAILURE_STATE_VALUES, frozenset)


def test_no_hand_typed_failure_or_disposition_literals():
    for rel in ("scripts/kg_engine/projector.py", "scripts/kg_engine/export.py",
                "scripts/kg_engine/server.py", "scripts/kg_engine/generate.py"):
        src = _src(rel)
        assert '("failed", "rejected")' not in src, rel
        assert "('failed','rejected'" not in src, rel
    assert '("ACCEPTED", "DEMOTED")' not in _src("scripts/kg_engine/server.py")
    assert 'HYP = "hypothesized"' not in _src("scripts/kg_engine/operations.py")


def test_graph_html_gets_failure_states_injected(engine):
    engine.kg_write({"edges": [
        {"source": "degree", "target": "importance", "relation": "approximates",
         "span": "Degree approximates importance"}]})
    engine.kg_export("html")
    html = (engine.projector.derived / "graph.html").read_text(encoding="utf-8")
    assert "__KG_FAILURE_STATES_JSON__" not in html  # placeholder substituted
    assert f"var FAILURE_STATES = {json.dumps(sorted(FAILURE_STATE_VALUES))};" in html
    assert 'state === "failed"' not in html  # the hand-typed pair is gone from the template


# --- 1.5 provisioning ---------------------------------------------------------------------------

def test_provision_logic_lives_once_in_the_mjs():
    worker = _src("hooks/provision.mjs")
    assert "systemPython" in worker and "--background" in worker  # the real job, done here
    assert "PROBE_TIMEOUT_MS" in worker
    # the shell files are shims that exec the worker, not second implementations
    for shim in ("hooks/provision.sh", "hooks/provision.ps1"):
        s = _src(shim)
        assert "provision.mjs" in s, shim
        assert "version_info" not in s, shim  # no third/fourth copy of the Python probe


def test_probe_timeout_constant_has_one_home():
    resolver = _src("scripts/_engine_resolve.mjs")
    assert "export const PROBE_TIMEOUT_MS" in resolver
    launcher = _src("scripts/launch_server.mjs")
    assert "const PROBE_TIMEOUT_MS" not in launcher  # imported, not redeclared
    assert re.search(r"import \{[^}]*PROBE_TIMEOUT_MS[^}]*\} from \"./_engine_resolve.mjs\"",
                     launcher)


# --- 1.6 pipeline knobs derive from EngineConfig -------------------------------------------------

def test_pipeline_fallback_knobs_are_derived_not_mirrored():
    src = _src("scripts/kg_engine/divergence/pipeline.py")
    for knob in ("KNN_K", "OPEN_NICHES", "OPEN_NICHE_FREEZE_FACTOR",
                 "MAX_DPP_POOL", "NOVELTY_REF_CAP", "QUALITY_WEIGHT"):
        assert re.search(rf"^{knob} = _DEFAULTS\.", src, re.M), knob
    from kg_engine.divergence import pipeline
    assert pipeline.KNN_K == dconfig.EngineConfig().knn_k  # derivation, alive at import


# --- §2.3 the Node<->Python process contract ------------------------------------------------------

def _js_const(src_text: str, name: str) -> str:
    m = re.search(rf'(?:export )?const {name} = "([^"]+)"', src_text)
    assert m, f"JS constant {name} not found"
    return m.group(1)


def test_node_python_contract_constants_agree():
    """§2.3: the launcher/bootstrap contract constants are hand-synced across two languages ("kept
    in sync with" comments). This pin makes a rename on either side FAIL LOUDLY instead of silently
    degrading the supervisor's restart classification or the interpreter resolution — the review
    found no parity test existed."""
    import importlib.util
    from kg_engine import envconfig
    from kg_engine import server as S

    spec = importlib.util.spec_from_file_location("kg_bootstrap_parity", REPO / "scripts" / "bootstrap.py")
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)

    resolver = _src("scripts/_engine_resolve.mjs")
    launcher = _src("scripts/launch_server.mjs")
    # venv marker files: bootstrap writes them, the Node launchers read them
    assert _js_const(resolver, "PTR_NAME") == boot.PTR_NAME
    assert _js_const(resolver, "STAMP_NAME") == boot.STAMP_NAME
    # the worker's log, which the launcher names when it gives up on a connection mid-build
    assert _js_const(resolver, "PROVISION_LOG_NAME") == boot.LOG_NAME
    # the readiness marker: the supervisor hands each child its path in this env var, server.py writes
    # it there, and the supervisor classifies crashes by it (one marker per spawn since 0.11.2)
    assert _js_const(launcher, "READY_MARKER_ENV") == S.READY_MARKER_ENV
    # the shared rotating log + the data-dir fallback rule's dirname (serverLogDir mirrors
    # envconfig.resolve_data_dir)
    assert f'"{S.SERVER_LOG_NAME}"' in launcher
    assert f'"{envconfig.DATA_DIRNAME}"' in launcher
    # the env-value cleaner's sentinel list (envconfig.clean <-> _engine_resolve.clean)
    for sentinel in ('"${"', '"/.venv"', '"/venv"'):
        assert sentinel.strip('"') in resolver, sentinel


def test_dirlock_is_the_single_lock_home():
    """§2.1: bootstrap's ~250-line mkdir-lock twin now lives in the kg_engine.dirlock leaf;
    bootstrap only wraps it (venv-dir keying + the staleness knob)."""
    boot_src = _src("scripts/bootstrap.py")
    assert "from kg_engine import dirlock" in boot_src
    assert "def _steal(" not in boot_src  # the steal protocol has one home
    from kg_engine import dirlock
    assert callable(dirlock.try_acquire) and callable(dirlock.release)
