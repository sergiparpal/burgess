"""0.8.0: every `query_graph` filter applies to both the nodes and the edges.

Field report on 0.7.0: `node_type` and `epistemic_state` filtered only the nodes, and `relation` only the edges,
so the two halves of one answer replied to different questions. On the field canon,
`query_graph(epistemic_state="grounded")`, which /kg-query presents as the trustworthy subgraph, returned 50
edges of which 8 were rejected and 1 unverified. Grounders that asked for `node_type="hypothesis"` (a type that
does not exist) or `node_type="failure"` got 100 or 80 unrelated edges, 62 to 89 KB that Claude Code saved to
files they then searched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.model import edge_id
from kg_engine.server import KGEngine

PACK = Path(__file__).resolve().parents[1] / "pack" / "pack.yaml"
DOC = ("## Uno\nEl RADAR de Meta mide el riesgo de cada cambio.\n\n"
       "## Dos\nLas pruebas de mutación miden la calidad de los tests.\n\n"
       "## Tres\nLos tests protegidos defienden contra la trampa.\n")


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=PACK)
    out = e.kg_write({"nodes": [{"id": "radar", "label": "RADAR", "node_type": "metric"},
                                {"id": "riesgo", "label": "riesgo", "node_type": "failure"},
                                {"id": "mutacion", "label": "pruebas de mutación", "node_type": "operation"},
                                {"id": "calidad", "label": "calidad", "node_type": "metric"},
                                {"id": "tests-protegidos", "label": "tests protegidos", "node_type": "operation"},
                                {"id": "trampa", "label": "trampa", "node_type": "failure"}],
                      "edges": [{"source": "radar", "target": "riesgo", "relation": "approximates",
                                 "span": "El RADAR de Meta mide el riesgo de cada cambio", "source_file": "doc.md"},
                                {"source": "mutacion", "target": "calidad", "relation": "approximates",
                                 "span": "Las pruebas de mutación miden la calidad de los tests",
                                 "source_file": "doc.md"},
                                {"source": "tests-protegidos", "target": "trampa", "relation": "defends_against",
                                 "span": "Los tests protegidos defienden contra la trampa", "source_file": "doc.md"}],
                      "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 9, out
    assert e.kg_ground(edge_id("radar", "approximates", "riesgo"), "grounded", note="t")["ok"]
    assert e.kg_ground(edge_id("mutacion", "approximates", "calidad"), "rejected", note="t")["ok"]
    e._ensure_projected()
    return e


def _edge_ids(res: dict) -> "set[str]":
    return {r["id"] for r in res["edges"]}


def test_a_state_filter_keeps_only_edges_in_that_state(eng):
    assert _edge_ids(eng.query_graph(epistemic_state="grounded")) == {edge_id("radar", "approximates", "riesgo")}
    assert _edge_ids(eng.query_graph(epistemic_state="rejected")) == {edge_id("mutacion", "approximates", "calidad")}


def test_a_node_type_keeps_the_edges_that_touch_one(eng):
    res = eng.query_graph(node_type="failure")
    assert {n["id"] for n in res["nodes"]} == {"riesgo", "trampa"}
    assert _edge_ids(res) == {edge_id("radar", "approximates", "riesgo"),
                              edge_id("tests-protegidos", "defends_against", "trampa")}


def test_a_relation_keeps_the_nodes_its_edges_touch(eng):
    res = eng.query_graph(relation="defends_against")
    assert {n["id"] for n in res["nodes"]} == {"tests-protegidos", "trampa"}
    assert _edge_ids(res) == {edge_id("tests-protegidos", "defends_against", "trampa")}


def test_filters_combine(eng):
    res = eng.query_graph(relation="approximates", epistemic_state="grounded")
    assert _edge_ids(res) == {edge_id("radar", "approximates", "riesgo")}
    assert res["nodes"] == []                       # the extractor's nodes stay unverified: only edges are judged


def test_a_node_type_that_does_not_exist_returns_nothing(eng):
    assert eng.query_graph(node_type="hypothesis", limit=100) == {"nodes": [], "edges": []}


def test_no_filter_returns_everything(eng):
    res = eng.query_graph()
    assert len(res["nodes"]) == 6 and len(res["edges"]) == 3
