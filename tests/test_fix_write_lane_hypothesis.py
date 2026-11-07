"""Regression: kg_write refuses the hypothesized lane, so every edge it accepts is span-verified.

Field report on 0.4.6, a real /kg-build of one 16-section document: the §14 extractor set
`provenance: "hypothesized"` on both its edges, because its contract said to use `hypothesized` "for a relation
you genuinely inferred across sentences — it still needs a span that anchors it". The boundary does the
opposite with that value: it treats the item as a discovery-mechanism proposal, stores it with an EMPTY span,
and checks nothing (contract §5a, right for kg_propose). So kg_write ACCEPTED two edges whose spans were
dropped unverified. Nothing was REJECTED or QUARANTINED, and the only symptom was a section that stayed
uncovered. The build's promise that every accepted edge carries a verified span was broken.

Two fixes, one per side of the mistake. The extractor's contract now says `inferred` (verified like
`span-present`) and never `hypothesized`. And kg_write refuses any item that claims the hypothesized lane
(REJECTED `write-lane-hypothesis`, retryable=false), the mirror of kg_propose refusing text claims with
`propose-lane-text-claim`. kg_propose reaches the shared validator through kg_write's internal
`lane="proposal"`, so the propose lane, kg_operate and materialization are unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_engine.model import Provenance, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
SPAN = "la tolerancia a fallos se mide con pruebas de mutación"
TEXT = f"## Qué aprender\nEn la práctica, {SPAN}, no con promesas.\n"


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text(TEXT, encoding="utf-8")
    return KGEngine(vault, source_path=src)


def _edge(provenance: str, relation: str = "grounds", span: str = SPAN) -> dict:
    return {"source": "tolerancia-a-fallos", "target": "pruebas-de-mutacion", "relation": relation,
            "provenance": provenance, "authored_by": "agent", "span": span, "source_file": "doc.md"}


def test_a_hypothesized_edge_is_refused_not_written_without_its_span(eng):
    # The §14 shape: the extractor even supplied a real span; the old boundary dropped it unchecked.
    out = eng.kg_write({"edges": [_edge("hypothesized")], "complete": True})
    assert out["dispositions"]["REJECTED"] == 1 and out["dispositions"]["ACCEPTED"] == 0
    (d,) = out["details"]
    assert d == {"kind": "edge", "id": edge_id("tolerancia-a-fallos", "grounds", "pruebas-de-mutacion"),
                 "disposition": "REJECTED", "reason": "write-lane-hypothesis", "retryable": False}
    assert out["refused_hypotheses"] == 1
    assert eng.canon.all_edges() == []


def test_the_rest_of_the_payload_is_still_written(eng):
    out = eng.kg_write({"nodes": [{"id": "idea", "label": "Idea", "provenance": "hypothesized"},
                                  {"id": "pruebas-de-mutacion", "label": "pruebas de mutación"}],
                        "edges": [_edge("hypothesized"), _edge("span-present", relation="approximates")],
                        "complete": True})
    assert out["dispositions"]["REJECTED"] == 2                    # the hypothesized node and edge
    assert [d["reason"] for d in out["details"][:2]] == ["write-lane-hypothesis"] * 2
    assert {n.id for n in eng.canon.all_nodes()} >= {"pruebas-de-mutacion"}
    assert "idea" not in {n.id for n in eng.canon.all_nodes()}
    assert [e.relation for e in eng.canon.all_edges()] == ["approximates"]


def test_the_same_claim_as_inferred_is_accepted_with_its_span_verified(eng):
    # What the extractor is now told to emit instead: `inferred`, verified exactly like span-present.
    ok = eng.kg_write({"edges": [_edge("inferred")], "complete": True})
    assert ok["dispositions"]["ACCEPTED"] == 1, ok
    (e,) = eng.canon.all_edges()
    assert (e.provenance, e.span) == (Provenance.INFERRED, SPAN)
    bad = eng.kg_write({"edges": [_edge("inferred", relation="approximates", span="algo que no dice")],
                        "complete": True})
    assert bad["details"][0]["reason"] == "span-not-in-named-source"   # checked against doc.md itself


def test_every_edge_kg_write_accepts_carries_a_verified_span(eng):
    eng.kg_write({"edges": [_edge("hypothesized"), _edge("inferred", relation="approximates"),
                            _edge("span-present", relation="survives")], "complete": True})
    edges = eng.canon.all_edges()
    assert len(edges) == 2
    assert all(e.provenance != Provenance.HYPOTHESIZED and e.span for e in edges)
    assert all(eng.source_set().verifies(e.span, e.source_file) for e in edges)


def test_kg_propose_still_writes_the_hypothesized_lane(eng):
    out = eng.kg_propose({"nodes": [{"id": "idea", "label": "Idea"}],
                          "edges": [{"source": "idea", "target": "pruebas-de-mutacion", "relation": "grounds"}]})
    assert out["dispositions"]["ACCEPTED"] == 2, out
    assert "refused_hypotheses" not in out
    (e,) = eng.canon.all_edges()
    assert (e.provenance, e.span) == (Provenance.HYPOTHESIZED, "")


def test_a_second_construction_write_refuses_it_too(eng, tmp_path):
    second = tmp_path / "second.md"
    second.write_text(TEXT, encoding="utf-8")
    out = eng.kg_write({"edges": [_edge("hypothesized")], "complete": True},
                       construction="t2", source=str(second))
    assert out["details"][0]["reason"] == "write-lane-hypothesis"


def test_an_idempotent_replay_keeps_the_refusal(eng):
    payload = {"edges": [_edge("hypothesized"), _edge("span-present", relation="survives")], "complete": True}
    first = eng.kg_write(payload, idempotency_key="k1")
    again = eng.kg_write(payload, idempotency_key="k1")
    assert again["idempotent_replay"] is True
    assert again["details"] == first["details"] and again["refused_hypotheses"] == 1


def test_an_unknown_lane_is_a_caller_error(eng):
    with pytest.raises(ValueError, match="unknown write lane"):
        eng.kg_write({"edges": []}, lane="anything")


def test_the_mcp_tool_refuses_it(eng):
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from kg_engine.server import _register

    mcp = FastMCP("burgess-test")
    _register(mcp, eng)
    out = asyncio.run(mcp.call_tool("kg_write", {"payload": {"edges": [_edge("hypothesized")],
                                                             "complete": True}}))
    if isinstance(out, tuple):
        out = out[0]
    got = json.loads(out[0].text)
    assert got["details"][0]["reason"] == "write-lane-hypothesis"


def test_the_extractor_is_told_inferred_never_hypothesized():
    assert "Use `hypothesized` only for a relation you genuinely inferred" not in EXTRACTOR
    assert "`provenance` ∈ `span-present | inferred`." in EXTRACTOR
    assert "**Never `hypothesized`.**" in EXTRACTOR
    assert "`retryable=false` + `write-lane-hypothesis`" in EXTRACTOR
