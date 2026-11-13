"""0.14.4: a span-backed edge is re-examinable only when the file its span comes from changes.

Field report on 0.14.3 (2026-11-13). The user added a ninth document to the source folder, a 12 KB synthesis of
the topic the other eight cover. The next projection flagged ALL 62 rejected/failed verdicts of the field graph
`source-set-changed-since-judged`. None of them came from the new file: they were edges whose spans live in
the eight unchanged documents (46 span-present, 16 inferred), and no extractor of the new file re-wrote any of
them. The filter flags an item when the changed text shares ANY non-stopword term with it, and a topical
document shares one with nearly everything.

That mattered for two reasons:
- `/burgess:kg-ground`'s Stage 0c asks the orchestrator to reconsider every flagged item. That orchestrator is
  not a grounder: it reads the project's notes.
- A flag lasts while its item stays rejected or failed, so a kept rejection would come back on every pass.

A span-backed edge was judged on its own span, and a change to another file cannot change what that span states.
Now such an edge is flagged only when its own file changed, with `span-file-changed-since-judged`. Span-less
items keep the source-set rule. PROJECTION_RULES "4" makes the first read after the upgrade rebuild the index,
and that rebuild drops the flags the old rule raised on span-backed edges.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from kg_engine.model import Edge, EpistemicState, Node, edge_id
from kg_engine.projector import PROJECTION_RULES, REEX_SOURCE_SET, REEX_SPAN_FILE, Projector
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
SPAN = "La revisión humana no escala cuando los agentes abren mil PR por semana"
A_TEXT = f"## Revisión\n{SPAN}.\n"
EDGE = edge_id("mil-pr-por-semana", "grounds", "revision-humana-no-escala")


def _bump(path: Path, text: str) -> None:
    """Write a source file and push its mtime forward, so the SourceSet re-resolves within one mtime tick."""
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 100))


def _flags(eng: KGEngine) -> "dict[str, dict]":
    return {r["item_id"]: r for r in eng.projector.kg_context()["advisory"]["reexaminable_verdicts"]}


def _setup(vault: Path, tmp_path: Path) -> "tuple[KGEngine, Path]":
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.md").write_text(A_TEXT, encoding="utf-8")
    eng = KGEngine(vault, source_path=d, pack_path=PACK)
    nodes = [{"id": "mil-pr-por-semana", "label": "Mil PR por semana", "node_type": "metric",
              "body": "Los agentes abren mil PR por semana."},
             {"id": "revision-humana-no-escala", "label": "La revisión humana no escala", "node_type": "claim",
              "body": "La revisión humana no da abasto."}]
    edge = {"source": "mil-pr-por-semana", "target": "revision-humana-no-escala", "relation": "grounds",
            "span": SPAN, "source_file": "a.md"}
    assert eng.kg_write({"nodes": nodes, "edges": [edge]})["dispositions"]["ACCEPTED"] == 3
    assert eng.kg_ground(EDGE, "rejected", note="vague: the span asserts it, it does not show it")["ok"]
    eng.projector.project()
    assert _flags(eng) == {}
    return eng, d


# ---- the field case --------------------------------------------------------------------------------

def test_a_new_file_does_not_flag_a_span_backed_edge(vault, tmp_path):
    eng, d = _setup(vault, tmp_path)
    # a topical document that shares plenty of terms with the edge: 0.14.3 flagged it
    _bump(d / "sintesis.md", "## Fábricas\nLa revisión humana se reserva a lo crítico; los agentes abren PR.\n")
    eng.projector.project()
    assert EDGE not in _flags(eng)


def test_a_change_to_its_own_file_flags_it_and_says_so(vault, tmp_path):
    eng, d = _setup(vault, tmp_path)
    _bump(d / "a.md", A_TEXT + "\nAhora la revisión humana se apoya en clasificadores de riesgo.\n")
    eng.projector.project()
    assert _flags(eng)[EDGE] == {"item_id": EDGE, "kind": "edge", "state": "rejected",
                                 "reason": REEX_SPAN_FILE}


def test_span_less_items_keep_the_source_set_rule(vault, tmp_path):
    eng, d = _setup(vault, tmp_path)
    eng.kg_propose({"edges": [{"source": "agentes-revisores", "target": "deuda-tecnica", "relation": "grounds"}]})
    hyp = edge_id("agentes-revisores", "grounds", "deuda-tecnica")
    assert eng.kg_ground(hyp, "rejected", note="no support in the source")["ok"]
    eng.canon.write_nodes([Node(id="fabrica-oscura", label="Fábrica oscura", node_type="claim")], message="seed")
    assert eng.kg_ground("fabrica-oscura", "failed", kind="node")["ok"]
    eng.projector.project()
    _bump(d / "sintesis.md", "## Críticas\nLa fábrica oscura acumula deuda técnica con agentes revisores.\n")
    eng.projector.project()
    flags = _flags(eng)
    assert flags[hyp]["reason"] == REEX_SOURCE_SET and flags["fabrica-oscura"]["reason"] == REEX_SOURCE_SET
    assert EDGE not in flags                           # the span-backed edge still is not


def test_which_edges_count_as_span_backed():
    configured = {"a.md", "b.md"}
    backed = Edge(source="x", target="y", relation="grounds", span="una frase", source_file="a.md")
    assert Projector._span_file(backed, configured) == "a.md"
    pathy = Edge(source="x", target="y", relation="grounds", span="una frase", source_file="docs/b.md")
    assert Projector._span_file(pathy, configured) == "b.md"           # matched by basename, like SourceSet
    for e in (Edge(source="x", target="y", relation="grounds", span="", source_file="a.md"),
              Edge(source="x", target="y", relation="grounds", span="una frase", source_file=""),
              Edge(source="x", target="y", relation="grounds", span="una frase", source_file="gone.md")):
        assert Projector._span_file(e, configured) is None


# ---- the flags an older plugin stored --------------------------------------------------------------

def _store(eng: KGEngine, flags: list, rules: "str | None" = None) -> None:
    con = sqlite3.connect(eng.projector.db_path)
    try:
        con.execute("INSERT OR REPLACE INTO meta VALUES ('reexaminable_verdicts', ?)", (json.dumps(flags),))
        if rules is not None:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('projection_rules', ?)", (rules,))
        con.commit()
    finally:
        con.close()


def test_the_upgrade_drops_the_old_rules_flags_on_span_backed_edges(vault, tmp_path):
    eng, d = _setup(vault, tmp_path)
    eng.canon.write_nodes([Node(id="fabrica-oscura", label="Fábrica oscura", node_type="claim")], message="seed")
    assert eng.kg_ground("fabrica-oscura", "failed", kind="node")["ok"]
    eng.projector.project()
    # what a 0.14.3 index holds after a topical file was added: source-set flags on everything
    _store(eng, [{"item_id": EDGE, "kind": "edge", "state": "rejected", "reason": REEX_SOURCE_SET},
                 {"item_id": "fabrica-oscura", "kind": "node", "state": "failed", "reason": REEX_SOURCE_SET}],
           rules="3")
    assert eng.projector.is_stale()                    # PROJECTION_RULES moved: the first read rebuilds
    eng.projector.project()
    flags = _flags(eng)
    assert EDGE not in flags                           # 0.14.3's flag on a span-backed edge is gone
    assert flags["fabrica-oscura"]["reason"] == REEX_SOURCE_SET   # a span-less item's flag is kept
    con = sqlite3.connect(eng.projector.db_path)
    try:
        assert con.execute("SELECT value FROM meta WHERE key='projection_rules'").fetchone() == (PROJECTION_RULES,)
    finally:
        con.close()


def test_a_span_file_flag_lasts_until_the_edge_leaves_its_verdict(vault, tmp_path):
    eng, d = _setup(vault, tmp_path)
    _bump(d / "a.md", A_TEXT + "\nAhora la revisión humana se apoya en clasificadores de riesgo.\n")
    eng.projector.project()
    assert EDGE in _flags(eng)
    _bump(d / "otro.md", "## Otro\nLas placas tectónicas derivan.\n")    # a later, unrelated change
    eng.projector.project()
    assert _flags(eng)[EDGE]["reason"] == REEX_SPAN_FILE                # carried forward, as before
    assert eng.kg_ground(EDGE, "grounded", note="re-judged: the span now states it")["ok"]
    eng.projector.project()
    assert EDGE not in _flags(eng)
    assert eng.canon.read_node("mil-pr-por-semana").edges[0].epistemic_state == EpistemicState.GROUNDED


# ---- the text that acts on it ----------------------------------------------------------------------

def test_stage_0c_explains_both_reasons():
    stage = " ".join((REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
                     .split("## Stage 0c", 1)[1].split("\n## ", 1)[0].split())
    assert REEX_SPAN_FILE in stage and REEX_SOURCE_SET in stage
    assert "the file its span comes from changed" in stage
