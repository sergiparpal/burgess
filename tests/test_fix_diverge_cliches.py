"""0.20.0: /burgess:kg-diverge keeps its cliché map, shows it, exports it, and can carry it into the graph.

Before generating, the agent maps the obvious answers to the brief: three it generates away from (O_train)
and three it sets aside to check the ideas against (O_test). Until 0.20.0 the map lived only in the agent's
conversation. Nothing made the agent show it: in the three test sessions of 2026-11-21 two listed what
they avoided and one named a single cliché in passing. A compaction lost it, and no export held it. The
user asked for the avoided clichés to open every session, and for the clichés to be able to go into the
graph at the end.

They chose:
* round 1 shows the avoided clichés, and the held-out ones wait for the end, with the ideas closest to
  each, so the user's choices cannot steer the ideas away from them before the check;
* a cliché in the graph is an ordinary hypothesis: grounded with support, rejected without.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from kg_engine.divergence import originality, pipeline
from kg_engine.divergence.config import ConfigError
from kg_engine.model import EpistemicState, Provenance
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
DIVERGE = (REPO / "commands" / "kg-diverge.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
COMMANDS = (REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

CLICHES = {
    "avoided": ["a supervisor agent that reviews the others", "a timeout that pages a human",
                "retry when the same error repeats"],
    "held_out": ["a dashboard of agent activity", "a fixed iteration cap per task",
                 "ask the user when stuck"],
}


def _flat(text: str) -> str:
    return " ".join(text.split())


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _cands(tag: str = "a", n: int = 6) -> list[dict]:
    return [
        {"id": f"c{tag}{i}", "text": f"idea {tag}{i}: concept about topic {i} via approach {tag}{i}",
         "explanation": f"how idea {tag}{i} works, with an example",
         "descriptor": {"angle": f"a{i}", "scope": "broad", "form": f"f{i % 2}",
                        "boldness": (i % 5) / 4.0, "mechanism": f"mechanism {tag}{i}"},
         "genealogy": {"operator_id": "analogy", "parents": []}}
        for i in range(n)
    ]


def _make(root: Path):
    """A project with a source and the registered tools, inited; nothing ingested yet."""
    proj = root / "proj"
    proj.mkdir(parents=True)
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    src = root / "source.md"
    src.write_text("A supervisor agent that reviews the others catches loops.\n", encoding="utf-8")
    engine = KGEngine(proj, source_path=src, pack_path=PACK)
    mcp = _FakeMCP()
    _register(mcp, engine)
    t = mcp.tools
    t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    return engine, t, proj


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    monkeypatch.delenv("KG_PACK_PATH", raising=False)


@pytest.fixture
def rig(tmp_path):
    return _make(tmp_path)


def _in_canon(proj: Path, node_id: str) -> bool:
    return (proj / "canon" / f"{node_id}.md").exists()


# ------------------------------------------------------------------------------------------- the map


def test_the_map_is_numbered_avoided_first():
    out = pipeline.parse_cliches(CLICHES)
    assert [c["id"] for c in out] == ["o1", "o2", "o3", "o4", "o5", "o6"]
    assert [c["role"] for c in out] == ["avoided"] * 3 + ["held_out"] * 3
    assert out[0]["text"] == "a supervisor agent that reviews the others"


@pytest.mark.parametrize("bad", [
    ["a list, not a map"],
    {"avoided": []},
    {"avoided": ["ok"], "extra": ["no"]},
    {"avoided": ["ok", ""]},
    {"avoided": [3]},
    {"avoided": ["x"] * 7},
    {"avoided": ["x" * 401]},
])
def test_a_malformed_map_is_refused(bad):
    with pytest.raises(ConfigError):
        pipeline.parse_cliches(bad)


def test_a_malformed_map_touches_no_state(rig):
    _, t, proj = rig
    out = t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                                 cliches={"avoided": []})
    assert out["ok"] is False and "cliches.avoided" in out["error"]
    assert not (proj / ".kg" / "diverge" / "brief" / "session" / "cliches.json").exists()
    assert "slate" not in out   # the round was not ingested either


def test_the_first_ingest_stores_the_map_and_recall_returns_it(rig):
    _, t, _ = rig
    r = t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                               cliches=CLICHES)
    assert r["cliches_stored"] == 6
    recall = t["kg_diverge_recall"](project="brief")
    assert [c["id"] for c in recall["cliches"]] == ["o1", "o2", "o3", "o4", "o5", "o6"]
    # a later round without cliches keeps the map
    r2 = t["kg_diverge_ingest"](project="brief", candidates=_cands("b"), axes="generic", seed=5)
    assert "cliches_stored" not in r2
    assert len(t["kg_diverge_recall"](project="brief")["cliches"]) == 6


def test_recall_has_no_cliches_key_without_a_map(rig):
    _, t, _ = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5)
    assert "cliches" not in t["kg_diverge_recall"](project="brief")


def test_the_map_never_moves_the_geometry(tmp_path):
    outs = []
    for name, cl in (("with", CLICHES), ("without", None)):
        _, t, _ = _make(tmp_path / name)
        r1 = t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                                    cliches=cl)
        r2 = t["kg_diverge_ingest"](project="brief", candidates=_cands("b"), axes="generic", seed=5)
        par = t["kg_diverge_parents"](project="brief", seed=5)
        outs.append((r1["slate_ids"], r1["ask_pairs"], r1["monitor"]["mean_cosine"],
                     r2["slate_ids"], r2["ask_pairs"], [p["id"] for p in par["parents"]]))
    assert outs[0] == outs[1]


def test_a_new_session_wipes_the_map(rig):
    _, t, _ = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    t["kg_diverge_init"](project="brief", axes="generic", session="s2", seed=5)
    assert "cliches" not in t["kg_diverge_recall"](project="brief")


# ------------------------------------------------------------------------------------------ the export


def test_nearest_ideas_orders_by_similarity_then_id():
    obvious = np.array([[1.0, 0.0]], dtype=np.float32)
    ideas = np.array([[0.0, 1.0], [1.0, 0.0], [0.6, 0.8], [1.0, 0.0]], dtype=np.float32)
    (near,) = originality.nearest_ideas(obvious, ideas, ["d", "b", "c", "a"], k=3)
    assert [x["id"] for x in near] == ["a", "b", "c"]
    assert near[0]["similarity"] == 1.0 and near[2]["similarity"] == 0.6


def test_nearest_ideas_degrades_to_empty_lists():
    assert originality.nearest_ideas(np.zeros((2, 3)), np.zeros((0, 3)), [], k=3) == [[], []]
    assert originality.nearest_ideas(np.zeros((1, 3)), np.zeros((2, 4)), ["a", "b"], k=3) == [[]]


def test_the_export_lists_the_map_and_measures_only_the_held_out_ones(rig):
    _, t, _ = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    out = t["kg_diverge_export"](project="brief", brief="how to notice a stuck factory")
    by = {c["id"]: c for c in out["cliches"]}
    assert set(by) == {"o1", "o2", "o3", "o4", "o5", "o6"}
    for oid in ("o1", "o2", "o3"):
        assert by[oid]["role"] == "avoided" and "closest" not in by[oid]
    for oid in ("o4", "o5", "o6"):
        closest = by[oid]["closest"]
        assert len(closest) == 3 and all(x["id"].startswith("ca") for x in closest)
        sims = [x["similarity"] for x in closest]
        assert sims == sorted(sims, reverse=True)
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert "## Clichés" in text
    assert "**o1** (avoided): a supervisor agent that reviews the others" in text
    assert "**o4** (set aside): a dashboard of agent activity · closest ideas: " in text
    assert text.index("## Clichés") < text.index("## Batch 1")


def test_an_export_without_a_map_has_no_cliche_section(rig):
    _, t, _ = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5)
    out = t["kg_diverge_export"](project="brief")
    assert out["cliches"] == []
    assert "## Clichés" not in Path(out["path"]).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------- the graph


def test_cliches_go_into_the_graph_on_request_and_carry_no_pins(rig):
    engine, t, proj = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "ca0"})
    out = t["kg_diverge_materialize"](project="brief", cliche_ids=["o1", "o4", "o9"])
    by = {r.get("cliche"): r for r in out["results"]}
    assert by["o1"]["status"] == "ACCEPTED" and by["o4"]["status"] == "ACCEPTED"
    assert by["o9"]["status"] == "refused" and "unknown-cliche" in by["o9"]["reason"]
    assert not any("candidate" in r for r in out["results"])  # no pin rode along
    assert "cliche_advisory" in out and "advisory" not in out

    node = engine.canon.read_node("cliche-brief-o1")
    assert node.provenance is Provenance.HYPOTHESIZED
    assert node.epistemic_state is EpistemicState.UNVERIFIED
    assert node.body.startswith("a supervisor agent that reviews the others")
    assert "[cliche] id=o1 role=avoided brief=brief session=s1" in node.body
    assert "[diverge] pinned" not in node.body       # so the grounder treats it as an ordinary proposal
    assert _in_canon(proj, "cliche-brief-o4")
    assert not _in_canon(proj, "idea-brief-ca0")

    from kg_engine.divergence.state import State
    ledger = State("brief", home=proj / ".kg" / "diverge").read_materialized()
    assert ledger["_cliches"]["o1"]["nodes"] == ["cliche-brief-o1"]
    assert "o1" not in ledger


def test_pins_and_cliches_can_go_in_together(rig):
    engine, t, proj = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "ca0"})
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=["ca0"], cliche_ids=["o2"])
    assert out["materialized"] == 2
    assert _in_canon(proj, "idea-brief-ca0")
    assert _in_canon(proj, "cliche-brief-o2")
    assert "advisory" in out and "cliche_advisory" in out


def test_without_cliche_ids_materialize_still_defaults_to_every_pin(rig):
    engine, t, proj = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "ca1"})
    out = t["kg_diverge_materialize"](project="brief")
    assert [r.get("candidate") for r in out["results"]] == ["ca1"]
    assert not _in_canon(proj, "cliche-brief-o1")


def test_a_cliche_in_the_graph_never_joins_the_briefs_discards(rig):
    engine, t, _ = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    t["kg_diverge_materialize"](project="brief", cliche_ids=["o1"])
    verdict = engine.kg_ground("cliche-brief-o1", "failed", kind="node", note="refuted for the test")
    assert verdict.get("ok", True) is not False, verdict
    assert engine.canon.read_node("cliche-brief-o1").epistemic_state is EpistemicState.FAILED
    recall = t["kg_diverge_recall"](project="brief")   # the fate sync runs here
    assert recall["discards"] == []


def test_the_export_names_the_node_a_cliche_became(rig):
    _, t, _ = rig
    t["kg_diverge_ingest"](project="brief", candidates=_cands(), axes="generic", seed=5,
                           cliches=CLICHES)
    t["kg_diverge_materialize"](project="brief", cliche_ids=["o5"])
    out = t["kg_diverge_export"](project="brief")
    by = {c["id"]: c for c in out["cliches"]}
    assert by["o5"]["node"] == "cliche-brief-o5" and "node" not in by["o1"]
    assert "in the graph as `cliche-brief-o5`" in Path(out["path"]).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------- the text


def test_the_command_maps_shows_and_saves_the_cliches():
    text = _flat(DIVERGE)
    assert 'Send the map with the first ingest (step 6) as `cliches`: `{"avoided": [O_train texts], "held_out": [O_test texts]}`' in text
    step7 = text[text.index("7. **Present the returned `slate`**"):text.index("8. **Record & continue.**")]
    assert "**Round 1 opens with the clichés you are avoiding**, before its slate" in step7
    assert "Never list the held-out ones before the session ends" in step7
    step11 = text[text.index("11. **Save the ideas**"):text.index("## Notes")]
    assert "**Then show the set-aside clichés**" in step11
    assert "`cliches[].closest`" in step11
    assert "the clichés can go into the graph too" in step11
    assert "the `cliches` you sent with the first ingest" in text


def test_the_command_says_how_cliches_go_into_the_graph():
    text = _flat(DIVERGE)
    assert "**Clichés go in the same way, on the user's word:** `kg_diverge_materialize(project, cliche_ids=[\"o1\", …])`" in text
    assert "a call with `cliche_ids` alone carries no pins" in text
    assert "grounded when a source supports it, rejected when none does" in text


def test_the_grounder_treats_a_cliche_as_an_ordinary_proposal():
    text = _flat(GROUNDER)
    assert "**A `[cliche] …` node is one of these ordinary items.**" in text
    assert "`grounded` with support, `rejected` without, like any proposal" in text


def test_the_docs_say_it_too():
    assert "**The clichés.** Before generating, Claude writes down the obvious answers" in _flat(COMMANDS)
    tools = _flat(TOOLS)
    assert "### 1B.2 `kg_diverge_ingest(project, candidates, axes=None, seed=0, cliches=None)`" in TOOLS
    assert "Only a `held_out` cliché carries `closest`" in tools
    assert "**Clichés (0.20.0).** `cliche_ids`" in tools
