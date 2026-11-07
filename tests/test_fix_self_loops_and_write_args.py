"""Regression: the write boundary refuses a self-loop, and the extractor calls kg_write with the payload alone.

Field report on 0.5.1, a full /kg-build of an 8-file source (84 sections, 819 items ACCEPTED):

- The extractor of one section wrote `h1-comprobadores-retiran-mas-revision survives h1-…` (the same node at
  both ends) as a placeholder, at confidence 0.2. Its span verified, so the boundary ACCEPTED it, and it is
  the one self-loop in that 225-edge canon. No pack relation states a claim about a concept and itself, so the
  boundary now REJECTS it as `self-loop`. Endpoints are compared as the slugs that key their node, and the
  rule binds every lane. kg_merge's own handling of the self-loops ITS rewrite creates (unverified ones
  dropped, failed/rejected ones kept as failure memory, §1.7) never passes through the boundary and is
  unchanged.
- Two extractors passed `source` to kg_write, probably echoing their `source_file`, and the call was refused
  ("`source` is only valid together with `construction`"). The refusal is deliberate (review-fix L3/server-5:
  a caller who thinks it re-points the primary source must hear it), so the fix is in the contract: call
  kg_write with the payload and nothing else.

The same build's orchestrator had to add three more rules to every launch prompt, and the extractor's contract
now carries them: name ids in the source's own words and language, and keep an edge's direction as the text
says it, leaving a doubtful relation out rather than approximating it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
SPAN = "H1: los comprobadores retiran más revisión"
NODE = "h1-comprobadores-retiran-mas-revision"


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text(f"## Hipótesis\n{SPAN} cuando el oráculo existe. Meta RADAR mide el riesgo.\n",
                   encoding="utf-8")
    return KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")


def _edge(source: str, target: str, relation: str = "survives", span: str = SPAN) -> dict:
    return {"source": source, "target": target, "relation": relation, "provenance": "span-present",
            "authored_by": "agent", "span": span, "source_file": "doc.md", "confidence_score": 0.2}


def test_the_reported_self_loop_is_rejected(eng):
    out = eng.kg_write({"edges": [_edge(NODE, NODE)], "complete": True})
    assert out["dispositions"]["REJECTED"] == 1 and out["dispositions"]["ACCEPTED"] == 0
    (d,) = out["details"]
    assert (d["reason"], d["retryable"]) == ("self-loop", False)
    assert eng.canon.all_edges() == []


def test_endpoints_are_compared_as_the_slugs_that_key_the_node(eng):
    # `Meta RADAR` and `meta-radar` name one node (0.4.6 stores endpoints as ids), so this is a loop too.
    out = eng.kg_write({"edges": [_edge("Meta RADAR", "meta-radar", relation="approximates",
                                        span="Meta RADAR mide el riesgo")]})
    assert out["details"][0]["reason"] == "self-loop"


def test_the_rest_of_the_payload_is_still_written(eng):
    out = eng.kg_write({"edges": [_edge(NODE, NODE), _edge(NODE, "oraculo", relation="grounds")],
                        "complete": True})
    assert [d["reason"] for d in out["details"]] == ["self-loop", ""]
    assert [(e.source, e.target) for e in eng.canon.all_edges()] == [(NODE, "oraculo")]


def test_the_propose_lane_refuses_a_self_loop_too(eng):
    out = eng.kg_propose({"edges": [{"source": "idea", "target": "idea", "relation": "bridges"}]})
    assert out["details"][0]["reason"] == "self-loop"
    assert eng.canon.all_edges() == []


def test_source_without_construction_is_still_refused_before_anything_is_written(eng):
    # The deliberate loud refusal stays; the fix is that the extractor stops sending it.
    with pytest.raises(ValueError, match="only valid together with `construction`"):
        eng.kg_write({"edges": [_edge(NODE, "oraculo", relation="grounds")]}, source="doc.md")
    assert eng.canon.all_edges() == []


def test_the_extractor_calls_kg_write_with_the_payload_alone():
    flat = " ".join(EXTRACTOR.split())
    assert "with that payload and nothing else" in flat
    assert "Never pass `construction` or `source`" in flat
    assert "call kg_write with that payload only (never `source` or `construction`)" in " ".join(CMD.split())


def test_the_extractor_keeps_ids_in_the_sources_words_and_edges_between_two_nodes():
    flat = " ".join(EXTRACTOR.split())
    assert "**Name ids in the source's own words and language.**" in flat
    assert "never a translation of it" in flat
    # ASCII with the accents dropped: the convention every id of the reporting canon already follows (555 of
    # 555), so `revisión` and `revision` can never split one concept between two nodes.
    assert "lowercase ASCII kebab-case with accents dropped" in flat
    assert "**An edge joins two DIFFERENT nodes.**" in flat
    assert "`retryable=false` + `self-loop`" in flat
