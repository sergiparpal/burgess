"""Stage 3 — the /kg-diverge surface (FUSION_PLAN §10).

Covers: the graphless guarantee (a full scripted divergence session in a project
with NO graph and NO sources), the MCP tool surface, the one-domain-pack-format
merge (pack.yaml `divergence:` section), axes-source resolution, and the one-shot
Cambrian state importer (read-only on its source).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kg_engine.divergence import importer
from kg_engine.divergence.config import ConfigError, load_all, resolve_axes_source
from kg_engine.divergence.state import State
from kg_engine.pack import load_pack
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "pack" / "pack.yaml"


class FakeMCP:
    """Captures registered wrapper callables (same idiom as test_fix_server.py)."""

    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


DIVERGE_TOOLS = {"kg_diverge_init", "kg_diverge_ingest", "kg_diverge_remember",
                 "kg_diverge_parents", "kg_diverge_metrics", "kg_diverge_recall",
                 "kg_diverge_materialize"}


def _round(tag: str, n: int = 6) -> list[dict]:
    return [
        {"id": f"{tag}{i}",
         "text": f"idea {tag}{i}: a distinct concept about topic {i} via approach {tag}{i}",
         "descriptor": {"angle": f"angle-{i}", "scope": "narrow" if i % 2 else "broad",
                        "form": f"form-{i % 3}", "boldness": (i % 5) / 4.0,
                        "mechanism": f"mechanism {tag} {i}"},
         "fitness": 0.8,
         "genealogy": {"operator_id": "analogy", "parents": []}}
        for i in range(n)
    ]


def test_graphless_scripted_session_end_to_end(tmp_path, monkeypatch):
    """The plan's graphless guarantee: /kg-diverge works with no graph, no sources,
    no setup beyond the plugin — and leaves state ONLY under .kg/diverge/."""
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    monkeypatch.setenv("KG_PACK_PATH", str(PACK))  # exercise the pack-format path

    proj = tmp_path / "bare-project"
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)

    engine = KGEngine(proj, pack_path=PACK)  # NO source_path: nothing to ground against
    mcp = FakeMCP()
    _register(mcp, engine)
    t = mcp.tools

    init = t["kg_diverge_init"](project="brief-x", session="s1")
    assert init["ok"] and init["session_id"] == "s1"
    assert init["domain"] == "conceptual theory"  # inherited from the pack's divergence section

    recall = t["kg_diverge_recall"](project="brief-x")
    assert recall is not None

    r1 = t["kg_diverge_ingest"](project="brief-x", candidates=_round("a"), seed=7)
    assert r1["slate"], f"empty slate: {json.dumps(r1)[:400]}"
    assert "mon" in r1 or "monitor" in r1
    slate_ids = [s["id"] for s in r1["slate"]]

    pinned, discarded = slate_ids[0], slate_ids[-1]
    assert t["kg_diverge_remember"](project="brief-x", event={"type": "pin", "id": pinned})
    assert t["kg_diverge_remember"](project="brief-x", event={"type": "discard", "id": discarded})

    par = t["kg_diverge_parents"](project="brief-x", k=3, seed=7)
    parent_ids = [p["id"] for p in par["parents"]]
    assert pinned in parent_ids and discarded not in parent_ids  # I8 at the diverge surface

    r2 = t["kg_diverge_ingest"](project="brief-x", candidates=_round("b"), seed=7)
    assert discarded not in [s["id"] for s in r2["slate"]]

    metrics = t["kg_diverge_metrics"](project="brief-x")
    assert metrics

    # --- state locality: everything divergence lives under .kg/diverge --------
    home = proj / ".kg" / "diverge"
    st = State("brief-x", home=home)
    assert st.read_session()["session_id"] == "s1"
    assert (st.session_dir / "archive.json").exists()
    assert st.read_pins(init["domain"]) == [pinned]
    assert st.read_discards(init["domain"]) == [discarded]

    # --- graphless means graphless: no canon content, no derived graph -------
    # (the engine constructor pre-creates empty dirs; the guarantee is that the
    # diverge flow put NOTHING in them)
    canon_files = list((proj / "canon").glob("*.md")) if (proj / "canon").exists() else []
    assert not canon_files, f"diverge flow wrote canon nodes: {canon_files}"
    derived = engine.data_dir / "derived"
    assert not (derived / "index.sqlite").exists() and not (derived / "graph.json").exists()


def test_mcp_surface_is_thirty_three_tools(engine):
    # 27 through 0.4.6; 0.5.0 added kg_build_plan and kg_section, which take /kg-build's planning and
    # section cutting out of Bash, 0.7.0 kg_ground_plan and kg_ground_item, which do the same for
    # /kg-ground's queue and evidence, 0.10.0 kg_record_attack, the mark an attack with no
    # counter-edge leaves for the plan, and 0.14.0 kg_record_edgeless_section, the mark an extraction
    # that wrote no edge leaves on its section for the build plan.
    mcp = FakeMCP()
    _register(mcp, engine)
    assert DIVERGE_TOOLS <= set(mcp.tools), sorted(mcp.tools)
    assert {"kg_build_plan", "kg_section", "kg_ground_plan", "kg_ground_item",
            "kg_record_attack", "kg_record_edgeless_section"} <= set(mcp.tools), sorted(mcp.tools)
    assert len(mcp.tools) == 33, sorted(mcp.tools)


def test_resolve_axes_source_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("KG_PACK_PATH", raising=False)

    spec = {"domain": "d", "axes": [{"name": "m", "type": "open"}]}
    assert resolve_axes_source(spec) is spec                        # dict passthrough

    named = resolve_axes_source("marketing")                        # bundled example template
    assert named.name == "marketing.yaml" and named.exists()
    generic = resolve_axes_source("generic")
    assert generic.name == "generic.yaml" and generic.exists()

    with pytest.raises(ConfigError, match="unknown axes source"):
        resolve_axes_source("no-such-domain-template")

    assert resolve_axes_source(None).name == "generic.yaml"         # no pack configured

    monkeypatch.setenv("KG_PACK_PATH", str(PACK))
    picked = resolve_axes_source(None)                              # pack embeds divergence:
    assert picked == PACK
    axes_spec, settings, econfig = load_all(picked)
    assert axes_spec.domain == "conceptual theory"                  # inherited from the pack
    assert axes_spec.primary_axis.name == "mechanism"
    assert settings.candidates_per_generation == 12


def test_pack_divergence_section_is_shape_validated():
    pack = load_pack(PACK)
    assert pack.divergence and isinstance(pack.divergence.get("axes"), list)

    from pydantic import ValidationError
    from kg_engine.pack import PackContract

    base = {"domain": "d", "node_types": ["n"], "edge_types": ["e"]}
    # a config-only section (just flags) is valid — axes are optional
    ok = PackContract.model_validate({**base, "divergence": {"dpp": True}})
    assert ok.divergence == {"dpp": True}
    with pytest.raises(ValidationError, match="divergence.axes"):
        PackContract.model_validate({**base, "divergence": {"axes": []}})
    with pytest.raises(ValidationError, match="non-empty 'name'"):
        PackContract.model_validate({**base, "divergence": {"axes": [{"type": "open"}]}})
    with pytest.raises(ValidationError, match="must be a boolean"):
        PackContract.model_validate({**base, "divergence": {"dpp": "yes"}})


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_import_cambrian_maps_memory_and_never_touches_source(tmp_path):
    old = tmp_path / "dot-cambrian" / "my-brief"
    mem = old / "memory" / "ideas"
    mem.mkdir(parents=True)
    (mem / "pins.json").write_text(json.dumps(["a", "b"]), encoding="utf-8")
    (mem / "discards.json").write_text(json.dumps(["c"]), encoding="utf-8")
    (mem / "comparisons.jsonl").write_text(
        json.dumps({"type": "comparison", "winner": "a", "loser": "c"}) + "\n"
        + "{corrupt-line\n"
        + json.dumps({"type": "comparison", "winner": "b", "loser": "c"}) + "\n",
        encoding="utf-8",
    )
    (old / "archive.json").write_text("{}", encoding="utf-8")   # geometry: must be skipped
    (old / "meta.json").write_text("{}", encoding="utf-8")      # meta: must be skipped
    before = _tree_digest(old)

    home = tmp_path / "new-home"
    report = importer.import_cambrian("my-brief", source=old, home=home)

    assert report["ok"]
    assert report["imported"]["ideas"] == {"pins": 2, "discards": 1, "comparisons": 2}
    assert any("corrupt" in e for e in report["errors"])
    assert any("archive.json" in s for s in report["skipped"])
    assert any("meta.json" in s for s in report["skipped"])

    st = State("my-brief", home=home)
    assert st.read_pins("ideas") == ["a", "b"]
    assert st.read_discards("ideas") == ["c"]
    assert len(st.read_comparisons("ideas")) == 2

    assert _tree_digest(old) == before, "importer modified its read-only source"


def test_import_cambrian_cli(tmp_path):
    old = tmp_path / "old-proj"
    mem = old / "memory" / "d"
    mem.mkdir(parents=True)
    (mem / "pins.json").write_text(json.dumps(["x"]), encoding="utf-8")

    env = {"KG_DIVERGE_HOME": str(tmp_path / "cli-home"), "PYTHONPATH": str(REPO / "scripts"),
           "PATH": "/usr/bin:/bin"}
    r = subprocess.run(
        [sys.executable, "-m", "kg_engine.divergence", "import-cambrian",
         "--project", "old-proj", "--from", str(old)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert r.returncode == 0, r.stderr[-1500:]
    report = json.loads(r.stdout)
    assert report["imported"]["d"]["pins"] == 1
    assert State("old-proj", home=tmp_path / "cli-home").read_pins("d") == ["x"]
