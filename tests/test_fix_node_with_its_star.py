"""0.17.1: a proposed node is judged with its star, and a proposal into a rejected node is not promoted.

Field run (2026-11-15, 0.17.0). `/burgess:kg-ground` judged the second field generation: 10 bridges, 2 nested
compression nodes and their 14 star edges. `kg_ground_plan` put the nodes first and cut the queue every 12
items, edges in id order, so one compression sat in batch 1 and its six star edges in all three batches. The
batches ran in parallel. In the same second, batch 1 rejected the node and batch 3 grounded an edge into it,
on an outside citation, and that new "claim" offered its source node to the adversarial grounder as a hub
again, for nothing.

So, in this release:
- `groundplan.node_star_batches` keeps a queued node, the queued edges that touch it and any queued node they
  reach in one batch, node first, and `kg_ground_plan` batches with it;
- the promotion gate refuses to promote a hypothesized edge into a node that is rejected, failed or obsolete
  (`hypothesis-into-non-live-node`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kg_engine.groundplan import batches, node_star_batches
from kg_engine.model import Edge, EpistemicState, Node, Provenance, edge_id

REPO = Path(__file__).resolve().parents[1]


def _node(i):
    return {"id": i, "kind": "node"}


def _edge(i):
    return {"id": i, "kind": "edge"}


def _ids(planned):
    return [[it["id"] for it in batch] for batch in planned]


# --------------------------------------------------------------------------- the batches


def test_a_node_and_the_edges_that_touch_it_stay_in_one_batch():
    items = [_node("A"), _node("B"), _edge("e1"), _edge("e2"), _edge("e3"), _edge("e4"), _edge("e5")]
    ends = {"e1": ("x", "A"), "e2": ("x", "y"), "e3": ("A", "z"), "e4": ("w", "B"), "e5": ("q", "r")}
    assert _ids(node_star_batches(items, ends, 3)) == [["A", "e1", "e3"], ["B", "e4", "e2"], ["e5"]]


def test_a_queue_with_no_node_is_cut_as_before():
    items = [_edge(f"e{i}") for i in range(30)]
    ends = {f"e{i}": (f"s{i}", f"t{i}") for i in range(30)}
    assert node_star_batches(items, ends, 12) == batches(items, 12)


def test_a_unit_larger_than_a_batch_is_a_batch_of_its_own():
    star = [_edge(f"m{i:02d}") for i in range(14)]
    items = [_node("C")] + star + [_edge("lone")]
    ends = {**{f"m{i:02d}": (f"m{i:02d}", "C") for i in range(14)}, "lone": ("p", "q")}
    planned = node_star_batches(items, ends, 12)
    assert _ids(planned) == [["C"] + [f"m{i:02d}" for i in range(14)], ["lone"]]


def test_two_queued_nodes_an_edge_joins_share_a_batch_nodes_first():
    items = [_node("A"), _edge("e0"), _node("B"), _edge("eAB"), _edge("eB")]
    ends = {"e0": ("p", "q"), "eAB": ("A", "B"), "eB": ("B", "s")}
    assert _ids(node_star_batches(items, ends, 12)) == [["A", "B", "eAB", "eB", "e0"]]


def test_kg_ground_plan_keeps_a_proposed_compression_with_its_star(engine):
    """The field shape: two compressions with stars of 8 and 6, and 10 bridges whose ids sort before the star
    edges. Through 0.17.0 the first batch held both nodes and the 10 bridges, and the stars went to the
    other batches."""
    engine.kg_propose({
        "nodes": [{"id": "comp-a", "label": "A", "node_type": "compression"},
                  {"id": "comp-b", "label": "B", "node_type": "compression"}],
        "edges": ([{"source": f"m{i:02d}", "target": "comp-a", "relation": "collapses_into"} for i in range(8)]
                  + [{"source": f"n{i:02d}", "target": "comp-b", "relation": "collapses_into"} for i in range(6)]
                  + [{"source": f"aa-{i}", "target": f"zz-{i}", "relation": "bridges"} for i in range(10)])})
    plan = engine.kg_ground_plan("", None, 12)
    assert plan["queue"]["nodes"] == 2 and plan["queue"]["edges"] == 24
    for node, prefix, n in (("comp-a", "m", 8), ("comp-b", "n", 6)):
        (batch,) = [b for b in plan["batches"] if any(it["id"] == node for it in b)]
        ids = [it["id"] for it in batch]
        assert ids[0] == node
        star = {edge_id(f"{prefix}{i:02d}", "collapses_into", node) for i in range(n)}
        assert star <= set(ids)
    assert sum(len(b) for b in plan["batches"]) == 26


# --------------------------------------------------------------------------- the promotion gate


def _proposal_into(engine, state: EpistemicState):
    engine.kg_propose({"nodes": [{"id": "comp-a", "label": "A", "node_type": "compression"}],
                       "edges": [{"source": "m01", "target": "comp-a", "relation": "collapses_into"}]})
    if state != EpistemicState.UNVERIFIED:
        support = {"support_span": "A compression stands in for many observations"} \
            if state == EpistemicState.GROUNDED else {}
        assert engine.kg_ground("comp-a", state.value, kind="node", **support)["ok"]
    return edge_id("m01", "collapses_into", "comp-a")


@pytest.mark.parametrize("state", [EpistemicState.REJECTED, EpistemicState.FAILED, EpistemicState.OBSOLETE])
def test_a_proposal_into_a_node_that_is_not_live_is_not_promoted(engine, state):
    eid = _proposal_into(engine, state)
    out = engine.kg_ground(eid, "grounded", support_span="The canon grounds trust")
    assert out == {"ok": False, "error": "hypothesis-into-non-live-node", "node": "comp-a",
                   "node_state": state.value}
    e = next(x for x in engine.canon.all_edges() if x.id == eid)
    assert e.epistemic_state == EpistemicState.UNVERIFIED and e.provenance == Provenance.HYPOTHESIZED
    assert engine.kg_ground(eid, "rejected", note="no-support: its node is not live")["ok"]


def test_a_citation_does_not_get_round_the_refusal(engine):
    """The field edge was grounded on an outside citation: that path is refused too."""
    eid = _proposal_into(engine, EpistemicState.REJECTED)
    out = engine.kg_ground(eid, "grounded", support_note="Knight & Leveson 1986")
    assert out["ok"] is False and out["error"] == "hypothesis-into-non-live-node"


@pytest.mark.parametrize("state", [EpistemicState.UNVERIFIED, EpistemicState.GROUNDED])
def test_a_proposal_into_a_live_node_still_promotes(engine, state):
    eid = _proposal_into(engine, state)
    out = engine.kg_ground(eid, "grounded", support_span="The canon grounds trust")
    assert out["ok"] and out["provenance_upgraded_to"] == "span-present"


def test_a_text_edge_into_a_rejected_node_is_not_refused(engine):
    """The rule is the proposal lane's: a span-present edge an extractor wrote is judged on its span."""
    engine.canon.write_one(Node(id="comp-x", label="X", node_type="compression",
                                provenance=Provenance.HYPOTHESIZED, epistemic_state=EpistemicState.REJECTED))
    engine.canon.write_one(Node(id="canon", label="canon", edges=[
        Edge(source="canon", target="comp-x", relation="grounds", span="The canon grounds trust")]))
    eid = edge_id("canon", "grounds", "comp-x")
    assert engine.kg_ground(eid, "grounded", note="the span states it")["ok"]


# --------------------------------------------------------------------------- the contracts


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def test_the_grounder_judges_a_node_before_its_star():
    text = _flat(REPO / "agents" / "grounder.md")
    assert "judge the node first" in text and "`hypothesis-into-non-live-node`" in text


def test_the_command_says_a_node_comes_with_its_star():
    text = _flat(REPO / "commands" / "kg-ground.md")
    assert "a queued node comes in one batch with the queued edges that touch it" in text
