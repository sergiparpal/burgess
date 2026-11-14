"""0.16.1: absorption scores only grounded nodes over live edges, a node verdict keeps its note, and a
promotion span records its file.

Field run (2026-11-14, plugin 0.15.2). `/burgess:kg-ground` judged the 37 items the first field
`/burgess:kg-generate` had proposed. 2 of the 4 compression nodes were grounded, and 2 of their 21 star edges.
Three things the verdicts should have left behind were missing:
- **`kg_absorption` scored all four compressions `fertile`**, at the degree each was born with. It read every
  tracked node and every edge of the derived graph, so the two rejected nodes were scored, and the rejected
  star edges still counted as the graph absorbing a node.
- **A node verdict's `note` was dropped.** The grounders rejected two compression nodes with a reason each.
  `kg_ground` documented `note` as edge-only and ignored it for a node, so the reasons survived only in the
  session's report and memory.
- **A promoted hypothesis had no `source_file`.** The two grounded star edges carried their span, verified
  against any source because they named none, but not the file it was found in. So they were cited without
  their document. A grounded node's `grounding span:` paragraph had the same gap.

So, in this release:
- `harness.absorption_window` scores a tracked node only when the graph holds it as grounded, over live
  edges; every other tracked node is listed in `not_scored` with its state, or `absent`;
- a node verdict's note is kept in the body as `verdict (<state>): <note>`;
- a promotion span records the first source file that holds it: an edge's `source_file`, a node's
  `grounding source:` paragraph.
"""
from __future__ import annotations

import json
from pathlib import Path

from kg_engine import harness
from kg_engine.model import EpistemicState, Node, Provenance, edge_id
from kg_engine.server import KGEngine
from kg_engine.sources import SourceSet

PACK = Path(__file__).resolve().parents[1] / "pack" / "pack.yaml"


def _graph(nodes, links) -> dict:
    return {"directed": True, "multigraph": True, "graph": {}, "nodes": nodes, "links": links}


def _edge(engine, eid):
    return next(x for x in engine.canon.all_edges() if x.id == eid)


def _seed_hypothesized_node(engine, nid="comp-x"):
    engine.canon.write_one(Node(id=nid, label=nid.title(), node_type="compression",
                                provenance=Provenance.HYPOTHESIZED, body="Hypothesis body."))
    return nid


def _two_file_engine(vault, tmp_path, a_text: str, b_text: str) -> KGEngine:
    srcdir = tmp_path / "sources"
    srcdir.mkdir()
    (srcdir / "a.md").write_text(a_text, encoding="utf-8")
    (srcdir / "b.md").write_text(b_text, encoding="utf-8")
    return KGEngine(vault, source_path=srcdir, pack_path=PACK)


# --------------------------------------------------------------------------- absorption


def test_absorption_counts_live_edges_only():
    """A rejected, failed or obsolete edge is not the graph absorbing a node; an unverified one is live
    topology, as everywhere else. Through 0.16.0 all six edges counted, and the node read `absorbed`."""
    nodes = [{"id": "g", "epistemic_state": "grounded"}] + [{"id": f"n{i}"} for i in range(6)]
    links = [{"source": "n0", "target": "g", "epistemic_state": "grounded"},
             {"source": "n1", "target": "g", "epistemic_state": "rejected"},
             {"source": "n2", "target": "g", "epistemic_state": "rejected"},
             {"source": "n3", "target": "g", "epistemic_state": "failed"},
             {"source": "n4", "target": "g", "epistemic_state": "obsolete"},
             {"source": "n5", "target": "g", "epistemic_state": "unverified"}]
    res = harness.absorption(_graph(nodes, links), {"g": {"introduced_at": 0, "introduced_degree": 1}}, now=5)
    assert res["g"]["current_degree"] == 2
    assert res["g"]["densification"] == 1 and res["g"]["status"] == "fertile"


def test_absorption_window_scores_only_grounded_tracked_nodes():
    """Only a node the graph holds as grounded has a window. The others come back in `not_scored` with
    their state, and a tracked node the graph no longer holds comes back `absent`."""
    nodes = [{"id": "g", "epistemic_state": "grounded"}, {"id": "r", "epistemic_state": "rejected"},
             {"id": "u", "epistemic_state": "unverified"}, {"id": "o", "epistemic_state": "obsolete"},
             {"id": "m"}]
    links = [{"source": "m", "target": "g"}, {"source": "m", "target": "r"}, {"source": "m", "target": "u"}]
    history = {x: {"introduced_at": 0, "introduced_degree": 1} for x in ("g", "r", "u", "o", "gone")}
    scored, not_scored = harness.absorption_window(_graph(nodes, links), history, now=2)
    assert set(scored) == {"g"}
    assert not_scored == {"r": "rejected", "u": "unverified", "o": "obsolete", "gone": "absent"}
    assert harness.absorption(_graph(nodes, links), history, now=2) == scored


def test_absorption_loses_edges_as_no_growth():
    """A compression whose star was mostly rejected lost edges since its generation. That is no growth:
    it stays `fertile` while a live edge remains, and turns `isolated` with none."""
    nodes = [{"id": "kept", "epistemic_state": "grounded"}, {"id": "bare", "epistemic_state": "grounded"},
             {"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
    links = [{"source": "m1", "target": "kept", "epistemic_state": "grounded"},
             {"source": "m2", "target": "kept", "epistemic_state": "rejected"},
             {"source": "m3", "target": "bare", "epistemic_state": "rejected"}]
    history = {"kept": {"introduced_at": 1, "introduced_degree": 2},
               "bare": {"introduced_at": 1, "introduced_degree": 1}}
    res = harness.absorption(_graph(nodes, links), history, now=1)
    assert res["kept"]["status"] == "fertile" and res["kept"]["densification"] == 0
    assert res["bare"]["status"] == "isolated" and res["bare"]["current_degree"] == 0


def test_kg_absorption_reports_what_it_did_not_score(engine):
    """The tool path, end to end through kg_propose and kg_ground: of two generated compressions, the
    grounded one is scored over its one grounded star edge, the rejected one is listed apart, and the note
    says so. `tracked` still counts the whole ledger."""
    engine.kg_propose({
        "nodes": [{"id": "comp-kept", "label": "Kept", "node_type": "compression"},
                  {"id": "comp-gone", "label": "Gone", "node_type": "compression"}],
        "edges": [{"source": "m1", "target": "comp-kept", "relation": "collapses_into"},
                  {"source": "m2", "target": "comp-kept", "relation": "collapses_into"},
                  {"source": "m3", "target": "comp-kept", "relation": "collapses_into"},
                  {"source": "m4", "target": "comp-gone", "relation": "collapses_into"}]})
    assert engine.kg_ground("comp-kept", "grounded", kind="node",
                            support_span="A compression stands in for many observations")["ok"]
    assert engine.kg_ground(edge_id("m1", "collapses_into", "comp-kept"), "grounded",
                            support_span="The canon grounds trust")["ok"]
    for src, tgt in (("m2", "comp-kept"), ("m3", "comp-kept"), ("m4", "comp-gone")):
        assert engine.kg_ground(edge_id(src, "collapses_into", tgt), "rejected", note="no-support")["ok"]
    assert engine.kg_ground("comp-gone", "rejected", kind="node", note="no-support")["ok"]
    engine._ensure_projected()
    (engine.projector.derived / "generations.json").write_text(json.dumps({
        "generation": 1,
        "tracked": {"comp-kept": {"introduced_at": 1, "introduced_degree": 3, "mechanism": "compression"},
                    "comp-gone": {"introduced_at": 1, "introduced_degree": 1, "mechanism": "compression"}}}),
        encoding="utf-8")
    out = engine.kg_absorption()
    assert out["tracked"] == 2
    assert set(out["nodes"]) == {"comp-kept"}
    assert out["nodes"]["comp-kept"]["current_degree"] == 1
    assert out["summary"] == {"fertile": 1, "absorbed": 0, "isolated": 0}
    assert out["not_scored"] == {"comp-gone": "rejected"}
    assert out["note"].startswith("1 tracked node(s) not scored")


# --------------------------------------------------------------------------- a node verdict's note


def test_node_rejection_keeps_its_note_in_the_body(engine):
    nid = _seed_hypothesized_node(engine)
    out = engine.kg_ground(nid, "rejected", kind="node", note="no-support: the parts are stated apart")
    assert out["ok"] and out["to"] == "rejected"
    node = engine.canon.read_node(nid)
    assert node.epistemic_state == EpistemicState.REJECTED
    assert node.body.strip().split("\n\n") == [
        "Hypothesis body.", "verdict (rejected): no-support: the parts are stated apart"]


def test_node_grounding_keeps_span_file_and_note_in_that_order(engine):
    nid = _seed_hypothesized_node(engine)
    out = engine.kg_ground(nid, "grounded", kind="node",
                           support_span="A compression stands in for many observations",
                           note="the source states the compression's rule")
    assert out["ok"] and out["provenance_upgraded_to"] == "span-present"
    assert engine.canon.read_node(nid).body.strip().split("\n\n") == [
        "Hypothesis body.",
        "grounding span: A compression stands in for many observations",
        "grounding source: source.md",
        "verdict (grounded): the source states the compression's rule"]


def test_a_blank_node_note_adds_nothing(engine):
    nid = _seed_hypothesized_node(engine)
    assert engine.kg_ground(nid, "rejected", kind="node", note="   ")["ok"]
    assert engine.canon.read_node(nid).body.strip() == "Hypothesis body."


def test_node_verdict_note_survives_the_node_being_proposed_again(engine):
    """Canon keeps a judged node's body when the same id is written again, so the note lasts as an edge's
    notes do: a later generation re-emitting the node cannot erase why it was rejected."""
    nid = _seed_hypothesized_node(engine)
    assert engine.kg_ground(nid, "rejected", kind="node", note="no-support: stated apart")["ok"]
    engine.kg_propose({"nodes": [{"id": nid, "label": "Comp-X", "node_type": "compression",
                                  "body": "A rewritten body."}]})
    node = engine.canon.read_node(nid)
    assert node.epistemic_state == EpistemicState.REJECTED
    assert "verdict (rejected): no-support: stated apart" in node.body


# --------------------------------------------------------------------------- the span's file


def test_files_containing_lists_the_holding_files_in_source_order(tmp_path):
    srcdir = tmp_path / "sources"
    srcdir.mkdir()
    (srcdir / "a.md").write_text("Shared line. Only in a.\n", encoding="utf-8")
    (srcdir / "b.md").write_text("Shared line. Only in b.\n", encoding="utf-8")
    sources = SourceSet(srcdir)
    assert sources.files_containing("shared   LINE") == ["a.md", "b.md"]   # normalized, as verifies is
    assert sources.files_containing("Only in b") == ["b.md"]
    assert sources.files_containing("nowhere at all") == []


def test_promoted_edge_records_the_file_its_span_is_in(vault, tmp_path):
    eng = _two_file_engine(vault, tmp_path, "Alpha grounds beta in the first document.\n",
                           "Gamma bridges delta across the second document.\n")
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    eid = edge_id("gamma", "bridges", "delta")
    assert _edge(eng, eid).source_file == ""
    assert eng.kg_ground(eid, "grounded", support_span="Gamma bridges delta")["ok"]
    e = _edge(eng, eid)
    assert e.provenance == Provenance.SPAN_PRESENT and e.source_file == "b.md"


def test_promoted_edge_keeps_the_declared_file_it_names(vault, tmp_path):
    """An edge that names a declared file was verified against that file alone, so it keeps it, even when
    a file earlier in source order holds the same sentence."""
    same = "Both documents carry the same sentence about the bridge.\n"
    eng = _two_file_engine(vault, tmp_path, same, same)
    eng.canon.write_one(Node(id="x", label="X", edges=[]))
    eng.kg_propose({"edges": [{"source": "x", "target": "y", "relation": "bridges", "source_file": "b.md"}]})
    eid = edge_id("x", "bridges", "y")
    assert eng.kg_ground(eid, "grounded", support_span="the same sentence about the bridge")["ok"]
    assert _edge(eng, eid).source_file == "b.md"


def test_promoted_edge_naming_an_unknown_file_takes_the_one_that_holds_its_span(vault, tmp_path):
    eng = _two_file_engine(vault, tmp_path, "Alpha grounds beta in the first document.\n",
                           "Gamma bridges delta across the second document.\n")
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges",
                               "source_file": "legacy.md"}]})
    eid = edge_id("gamma", "bridges", "delta")
    assert eng.kg_ground(eid, "grounded", support_span="Gamma bridges delta")["ok"]
    assert _edge(eng, eid).source_file == "b.md"


def test_citation_promotion_records_no_file(vault, tmp_path):
    """An external citation has no span in the sources, so there is no file to record."""
    eng = _two_file_engine(vault, tmp_path, "Alpha grounds beta in the first document.\n",
                           "Gamma bridges delta across the second document.\n")
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    eid = edge_id("gamma", "bridges", "delta")
    out = eng.kg_ground(eid, "grounded", support_note="Swanson 1986")
    assert out["ok"] and out["provenance_upgraded_to"] == "inferred"
    assert _edge(eng, eid).source_file == ""


def test_promoted_node_names_its_grounding_source(vault, tmp_path):
    eng = _two_file_engine(vault, tmp_path, "Alpha grounds beta in the first document.\n",
                           "Gamma bridges delta across the second document.\n")
    eng.canon.write_one(Node(id="comp-y", label="Comp Y", node_type="compression",
                             provenance=Provenance.HYPOTHESIZED))
    assert eng.kg_ground("comp-y", "grounded", kind="node", support_span="Gamma bridges delta")["ok"]
    body = eng.canon.read_node("comp-y").body
    assert "grounding span: Gamma bridges delta" in body and "grounding source: b.md" in body
