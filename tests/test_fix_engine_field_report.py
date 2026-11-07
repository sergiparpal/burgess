"""Regression: three engine defects found by the first real /kg-build on 0.4.5. The build covered one
16-section Spanish document from an 8-file source folder, on the reporting Windows install. Each defect
was confirmed against that build's own canon, or against the engine code, before it was fixed.

1. kg_scrub counted only the placeholders its own call minted. Placeholders are consistent across a
   session, so a section whose values an earlier call had already redacted came back holding ⟦SECRET:1⟧
   with `redactions: 0` and `categories: []`. That reads as "the scrubbed text is the original".
2. kg_status coverage pooled every edge's span across all the source files. Three short spans of one
   document therefore marked three sections of ANOTHER document as covered, and a resumed build would
   have skipped them. A span now counts toward a file the way the boundary verified it.
3. 3 of the build's 39 edges named their endpoints by label ('Meta RADAR', 'componentes en masa'),
   while their id and owner used the slug. The projection hung those edges on phantom nodes, so
   get_neighbors, degree and bridges missed them. Their natural owner was ranked foreign, and rename
   and merge, which matched exactly, would have skipped them. Now:
   - the boundary stores endpoints as node ids;
   - the projector resolves the label-form ones an older canon still holds, and PROJECTION_RULES forces
     one full rebuild so the fix reaches an index that nothing else would touch;
   - rename and merge match endpoints by slug.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from kg_engine.boundary import merge_results_into_nodes, validate_payload
from kg_engine.canon import Canon
from kg_engine.graphio import node_link_graph
from kg_engine.model import Edge, Node, edge_id
from kg_engine.projector import PROJECTION_RULES, Projector
from kg_engine.server import KGEngine

PACK = Path(__file__).resolve().parents[1] / "pack" / "pack.yaml"
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one


# ---- 1. kg_scrub counts what the returned text holds --------------------------------------------------

def test_a_placeholder_minted_by_an_earlier_call_still_counts(engine: KGEngine):
    first = engine.kg_scrub(f"section 4 carries {TOKEN} here")
    assert first["redactions"] == 1 and first["categories"] == ["SECRET"]
    again = engine.kg_scrub(f"section 7 carries the same {TOKEN} again")
    assert "⟦SECRET:1⟧" in again["scrubbed"]
    assert again["redactions"] == 1 and again["categories"] == ["SECRET"]   # was 0 and []


def test_zero_redactions_means_the_text_came_back_unchanged(engine: KGEngine):
    texts = [
        "plain prose with nothing to hide",
        f"a key {TOKEN}",
        f"the key {TOKEN} once more",                  # reuses ⟦SECRET:1⟧
        "the literal ⟦EMAIL:7⟧ appears in the prose",   # an identity entry: bookkeeping, not a redaction
        "mail real@example.com",
        "and real@example.com again, among plain words",
    ]
    for text in texts:
        out = engine.kg_scrub(text)
        assert (out["redactions"] == 0) == (out["scrubbed"] == text), (text, out)


# ---- 2. coverage counts a span toward the file it was verified against --------------------------------

def _two_file_engine(tmp_path: Path, vault: Path) -> KGEngine:
    src = tmp_path / "fuente"
    src.mkdir()
    (src / "fabricas.md").write_text(
        "# Fábricas\n\n## Evidencia\nSin grupo de control.\n\n## Riesgos\nOtro texto.\n", encoding="utf-8")
    (src / "revision.md").write_text(
        "# Revisión\n\n## Casos\nSin grupo de control.\n\n## Coste\nNada que ver.\n", encoding="utf-8")
    return KGEngine(vault, source_path=src, pack_path=PACK)


def _covered_sections(eng: KGEngine) -> set:
    return {(s["file"], s["title"]) for s in eng.kg_status()["coverage"]["sections"] if s["covered"]}


def _seed_one_edge(eng: KGEngine, source_file: str) -> None:
    eng.canon.write_nodes([Node(id="a", edges=[Edge(source="a", target="b", relation="grounds",
                                                      span="Sin grupo de control.", source_file=source_file)]),
                           Node(id="b")], message="seed")


def test_a_span_covers_only_the_file_its_edge_names(tmp_path, vault):
    eng = _two_file_engine(tmp_path, vault)
    _seed_one_edge(eng, "fabricas.md")
    assert _covered_sections(eng) == {("fabricas.md", "Evidencia")}   # revision.md#Casos was covered too


@pytest.mark.parametrize("source_file", ["", "source.md"])
def test_an_edge_with_no_known_source_file_still_covers_any_file(tmp_path, vault, source_file):
    # As the lenient verification accepted it: a pre-R4 single-source edge (no source_file), or a name
    # that is not among the declared sources.
    eng = _two_file_engine(tmp_path, vault)
    _seed_one_edge(eng, source_file)
    assert _covered_sections(eng) == {("fabricas.md", "Evidencia"), ("revision.md", "Casos")}


# ---- 3. edge endpoints name node ids ------------------------------------------------------------------

def test_the_boundary_stores_endpoints_as_node_ids():
    payload = {"edges": [{"source": "Meta RADAR", "target": "Zalando", "relation": "attacked_by",
                          "provenance": "hypothesized"}]}
    nodes = merge_results_into_nodes(validate_payload(payload, pack=None))
    (e,) = nodes["meta-radar"].edges
    assert (e.source, e.target) == ("meta-radar", "zalando")
    assert e.id == edge_id("Meta RADAR", "attacked_by", "Zalando")   # the id the label form already had
    assert nodes["meta-radar"].label == "Meta RADAR"                 # the placeholder keeps a readable label


def _label_form_canon(canon: Canon) -> None:
    """What 0.4.5 left on disk: each edge in its source's note, keyed by slug, endpoints written as labels."""
    canon.write_nodes([
        Node(id="meta-radar", label="Meta RADAR",
             edges=[Edge(source="meta-radar", target="zalando", relation="relates_to")]),
        Node(id="zalando", label="Zalando"),
        Node(id="solo-strongdm", label="solo StrongDM",
             edges=[Edge(source="solo StrongDM", target="Meta RADAR", relation="attacked_by")]),
    ], message="seed")


INCOMING = edge_id("solo-strongdm", "attacked_by", "meta-radar")


def _neighbor_ids(proj: Projector, node_id: str) -> set:
    return {e["id"] for e in proj.get_neighbors(node_id)}


def test_a_label_form_endpoint_reaches_neighbors_and_degree(canon: Canon):
    _label_form_canon(canon)
    proj = Projector(canon)
    proj.project()
    assert _neighbor_ids(proj, "meta-radar") == {INCOMING, edge_id("meta-radar", "relates_to", "zalando")}
    g = node_link_graph(json.loads(proj.graph_path.read_text(encoding="utf-8")))
    assert "Meta RADAR" not in g and "solo StrongDM" not in g        # no phantom nodes
    assert set(g.nodes) == {"meta-radar", "zalando", "solo-strongdm"}
    assert g.degree("meta-radar") == 2


def test_resolution_leaves_a_well_formed_canon_untouched(canon: Canon):
    canon.write_nodes([Node(id="a", edges=[Edge(source="a", target="b", relation="r")]), Node(id="b")],
                      message="seed")
    nodes = canon.all_nodes()
    assert all(x is y for x, y in zip(nodes, Projector._resolve_endpoints(nodes)))


def test_a_slugged_endpoint_finds_a_legacy_raw_id(canon: Canon):
    # A node stored with a raw id (`id: FEP`, from before node ids were slugged on write) is still the
    # node a slugged endpoint names.
    canon.write_nodes([Node(id="FEP", label="FEP"),
                       Node(id="x", edges=[Edge(source="x", target="fep", relation="relates_to")])],
                      message="seed")
    proj = Projector(canon)
    proj.project()
    assert _neighbor_ids(proj, "FEP") == {edge_id("x", "relates_to", "fep")}


def test_an_index_built_under_older_rules_is_rebuilt_once(canon: Canon, monkeypatch):
    _label_form_canon(canon)
    proj = Projector(canon)
    # Build the index the way 0.4.5 did: no endpoint resolution, and no projection rules recorded.
    monkeypatch.setattr(Projector, "_resolve_endpoints", staticmethod(lambda nodes: nodes))
    proj.project()
    con = sqlite3.connect(proj.db_path)
    con.execute("DELETE FROM meta WHERE key='projection_rules'")
    con.commit()
    con.close()
    assert INCOMING not in _neighbor_ids(proj, "meta-radar")         # the field symptom
    monkeypatch.undo()
    # Nothing in the canon changed, and its notes are stat-unchanged, yet the index must be rebuilt.
    assert proj.is_stale()
    assert proj.project().full_rebuild
    assert INCOMING in _neighbor_ids(proj, "meta-radar")
    con = sqlite3.connect(proj.db_path)
    assert con.execute("SELECT value FROM meta WHERE key='projection_rules'").fetchone() == (PROJECTION_RULES,)
    con.close()
    assert not proj.is_stale()                                        # once, not on every read


def _crisis_canon(engine: KGEngine, *extra: Node) -> None:
    engine.canon.write_nodes([
        Node(id="crisis-del-software", label="crisis del software"),
        Node(id="componentes-en-masa", label="componentes en masa",
             edges=[Edge(source="componentes en masa", target="crisis del software",
                         relation="defends_against")]),
        *extra,
    ], message="seed")


def test_rename_rewrites_a_label_form_endpoint(engine: KGEngine):
    _crisis_canon(engine)
    assert engine.kg_rename("crisis-del-software", "crisis-sw")["ok"]
    (e,) = engine.canon.read_node("componentes-en-masa").edges
    assert e.target == "crisis-sw"                                   # left dangling before


def test_merge_rewrites_a_label_form_endpoint(engine: KGEngine):
    _crisis_canon(engine, Node(id="crisis", label="crisis"))
    assert engine.kg_merge("crisis-del-software", "crisis")["ok"]
    (e,) = engine.canon.read_node("componentes-en-masa").edges
    assert e.target == "crisis"                                      # left dangling before
