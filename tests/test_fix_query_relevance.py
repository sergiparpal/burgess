"""0.11.5: a question finds the edges it is about, and the reader sees what the budget left out.

Field report on 0.11.3. A /kg-query on the 8-document Spanish canon (425 nodes, 221 edges) asked «¿En qué
condiciones se puede retirar la revisión humana del código?». The answer it gave was faithful, but
kg_context had handed it 18 edges of which it used 5, so it read canon/ through the shell 19 times, and
every one of those commands waited for the user's approval. The session took two hours.

- kg_context took every run of three or more characters as a term and matched it as a substring of the
  edge's ids, relation and span. «del» matched 37 of the 61 hits, inside «modelo» as well. «revisión» and
  «código» never matched the accent-free ids (`retirar-revision`), and no node label was searched.
- The matches were then ordered by state, the extractor's confidence (0.7/0.6/0.5) and id, not by how well
  they matched. The edge the question was about (`comprobadores-deterministas --enables--> retirar-revision`,
  0.6) ranked 24th, and the 2000-token budget held 18.
- Nothing said that 43 matches were left out; the session could only guess «probablemente se truncó».
- query_graph could not find a node by what it says, so the session grepped `^label:` in canon/.

Since 0.11.5 a search matches /kg-build's content words (case, accents, function words and plural endings
ignored) in the span, the relation and both endpoints' ids and labels, and ranks the matches by the rarity
weight of the words they share (grounded before unverified as before). kg_context reports `items_total`,
`hypotheses_total` and `query_terms`, and query_graph takes `text`.
"""
from __future__ import annotations

import inspect
import unicodedata
from pathlib import Path

import pytest

from kg_engine.buildplan import _fold
from kg_engine.canon import Canon
from kg_engine.model import Edge, EpistemicState, Node, Provenance
from kg_engine.projector import DerivedReader, Projector
from kg_engine.server import _register

REPO = Path(__file__).resolve().parents[1]
QUERY_MD = (REPO / "commands" / "kg-query.md").read_text(encoding="utf-8")
TOOLS_MD = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

FIELD_QUESTION = "¿En qué condiciones se puede retirar la revisión humana del código?"
G, U = EpistemicState.GROUNDED, EpistemicState.UNVERIFIED


def _edge(src, rel, tgt, span, *, state=G, score=0.7, prov=Provenance.SPAN_PRESENT):
    return Edge(source=src, target=tgt, relation=rel, span=span, provenance=prov, epistemic_state=state,
                confidence_score=score)


def _project(canon: Canon, edges, labels=None, extra_nodes=()) -> Projector:
    """Write `edges` (each into its source's note), every endpoint as a node labelled from `labels`, then
    project."""
    labels = dict(labels or {})
    by_src: dict = {}
    ids: list = []
    for e in edges:
        by_src.setdefault(e.source, []).append(e)
        for nid in (e.source, e.target):
            if nid not in ids:
                ids.append(nid)
    for nid in extra_nodes:
        if nid not in ids:
            ids.append(nid)
    canon.write_nodes([Node(id=nid, label=labels.get(nid, nid), edges=by_src.get(nid, [])) for nid in ids],
                      message="seed")
    proj = Projector(canon)
    proj.project()
    return proj


def _ids(rows) -> list:
    return [r["id"] for r in rows]


# ---- what a query matches on -----------------------------------------------------------------------------

def test_function_words_are_not_terms(canon):
    proj = _project(canon, [_edge("arquitectura", "grounds", "modelo-grande", "la arquitectura del modelo")])
    ctx = proj.kg_context("del")
    assert ctx["query_terms"] == [] and ctx["items"] == [] and ctx["items_total"] == 0  # 0.11.4: 1 item
    assert proj.kg_context("¿Qué es esto?")["items"] == []
    assert _ids(proj.kg_context("¿Qué hay del modelo?")["items"]) == [
        "e_arquitectura__grounds__modelo-grande"]


def test_a_word_is_not_matched_inside_another(canon):
    proj = _project(canon, [_edge("arquitectura", "grounds", "otra-cosa", "el modelo general")])
    assert proj.kg_context("model")["items"] == []  # 0.11.4 matched «model» inside «modelo»


def test_accents_and_case_are_ignored_both_ways(canon):
    proj = _project(canon, [_edge("comprobadores", "enables", "retirar-revision",
                                  "Lo que lo permite son comprobadores")],
                    labels={"retirar-revision": "Retirar revisión"})
    for q in ("REVISIÓN", "revision", "Revisión"):
        ctx = proj.kg_context(q)
        assert ctx["query_terms"] == ["revision"]
        assert _ids(ctx["items"]) == ["e_comprobadores__enables__retirar-revision"], q


def test_endpoint_labels_are_searched(canon):
    proj = _project(canon, [_edge("x1", "grounds", "x2", "un dato sin la palabra")],
                    labels={"x2": "Supervisión graduada por riesgo"})
    assert _ids(proj.kg_context("supervisión")["items"]) == ["e_x1__grounds__x2"]


def test_singular_and_plural_meet(canon):
    proj = _project(canon, [_edge("a", "grounds", "b", "los mecanismos de defensa")])
    assert _ids(proj.kg_context("mecanismo")["items"]) == ["e_a__grounds__b"]
    proj2 = _project(canon, [_edge("c", "grounds", "d", "un mecanismo de defensa")])
    assert "e_c__grounds__d" in _ids(proj2.kg_context("mecanismos")["items"])


def test_short_letter_digit_codes_are_terms(canon):
    proj = _project(canon, [_edge("zalando", "grounds", "autonomia-n4-a-escala", "aprobación automática")])
    ctx = proj.kg_context("¿Qué dice el grafo de N4?")
    assert "n4" in ctx["query_terms"]
    assert _ids(ctx["items"]) == ["e_zalando__grounds__autonomia-n4-a-escala"]


def test_non_latin_queries_match(canon):
    proj = _project(canon, [_edge("a", "grounds", "b", "привет большой мир")])
    assert _ids(proj.kg_context("мир")["items"]) == ["e_a__grounds__b"]


def test_blank_query_is_no_query(canon):
    proj = _project(canon, [_edge("a", "grounds", "b", "uno"), _edge("c", "grounds", "d", "dos")])
    blank, none = proj.kg_context("   "), proj.kg_context(None)
    assert "query_terms" not in blank and "query_terms" not in none
    assert blank["items"] == none["items"] and blank["items_total"] == none["items_total"] == 2


# ---- how the matches are ranked ----------------------------------------------------------------------------

def _field_shape(canon: Canon) -> Projector:
    """The field case in miniature: many grounded edges that share one common word of the question and sort
    first by the old keys (confidence 0.7, early ids), and the edge the question is about (confidence 0.6, a
    late id) that shares three of its words."""
    filler = [_edge(f"a{i:02d}-tema", "grounds", f"a{i:02d}-otro", "esto puede pasar a veces") for i in range(20)]
    key = _edge("zz-comprobadores", "enables", "retirar-revision",
                "Lo que lo permite son comprobadores deterministas que el agente no puede tocar", score=0.6)
    return _project(canon, filler + [key], labels={"retirar-revision": "Retirar revisión"})


KEY = "e_zz-comprobadores__enables__retirar-revision"


def test_relevance_outranks_confidence_and_id(canon):
    proj = _field_shape(canon)
    ctx = proj.kg_context(FIELD_QUESTION, budget=200)
    assert ctx["items"][0]["id"] == KEY  # 0.11.4: last of 21, never inside a small budget
    assert ctx["items_total"] == 21 and len(ctx["items"]) < 21


def test_a_rarer_word_ranks_first_on_an_equal_count(canon):
    common = [_edge(f"c{i}", "grounds", f"d{i}", "la revisión del equipo") for i in range(6)]
    rare = _edge("zz", "grounds", "yy", "retirar algo")
    proj = _project(canon, common + [rare])
    # one word each: «retirar» is on one edge, «revisión» on six, so «retirar» weighs more
    assert proj.kg_context("retirar revisión")["items"][0]["id"] == "e_zz__grounds__yy"


def test_more_words_matched_rank_first(canon):
    proj = _project(canon, [_edge("a", "grounds", "b", "retirar la revisión humana"),
                            _edge("0a", "grounds", "0b", "retirar")])
    assert _ids(proj.kg_context("retirar revisión humana")["items"]) == ["e_a__grounds__b", "e_0a__grounds__0b"]


def test_grounded_still_comes_before_unverified(canon):
    proj = _project(canon, [_edge("a", "grounds", "b", "retirar la revisión humana", state=U),
                            _edge("z", "grounds", "y", "retirar")])
    ctx = proj.kg_context("retirar revisión humana")
    assert [i["epistemic_state"] for i in ctx["items"]] == ["grounded", "unverified"]


def test_equal_matches_keep_the_old_order(canon):
    # same words matched: provenance, then confidence, then id, as without a query
    proj = _project(canon, [_edge("b", "grounds", "x", "retirar", score=0.9),
                            _edge("a", "grounds", "x", "retirar", score=0.5),
                            _edge("c", "grounds", "x", "retirar", prov=Provenance.INFERRED, score=1.0)])
    assert _ids(proj.kg_context("retirar")["items"]) == [
        "e_b__grounds__x", "e_a__grounds__x", "e_c__grounds__x"]


def test_the_ranking_is_a_pure_function_of_the_canon(canon):
    proj = _field_shape(canon)
    first = proj.kg_context(FIELD_QUESTION, budget=400)
    again = Projector(canon)
    assert again.project(incremental=False).full_rebuild  # rows re-inserted in a fresh order
    assert again.kg_context(FIELD_QUESTION, budget=400) == first == proj.kg_context(FIELD_QUESTION, budget=400)


def test_the_hypothesis_lane_is_ranked_and_counted_too(canon):
    hyp = dict(prov=Provenance.HYPOTHESIZED, state=U)
    proj = _project(canon, [_edge("a", "bridges", "b", "", score=0.9, **hyp),
                            _edge("z", "bridges", "retirar-revision", "", score=0.1, **hyp)],
                    labels={"retirar-revision": "Retirar revisión humana"})
    ctx = proj.kg_context("retirar revisión humana")
    assert _ids(ctx["hypotheses"]) == ["e_z__bridges__retirar-revision"] and ctx["hypotheses_total"] == 1
    assert ctx["items"] == [] and ctx["items_total"] == 0


# ---- what the reader is told ------------------------------------------------------------------------------

def test_totals_say_what_the_budget_left_out(canon):
    proj = _field_shape(canon)
    ctx = proj.kg_context(FIELD_QUESTION, budget=150)
    assert 0 < len(ctx["items"]) < ctx["items_total"] == 21
    assert ctx["approx_tokens"] <= 150


def test_without_a_query_the_order_is_unchanged_and_counted(canon):
    proj = _project(canon, [_edge("b", "grounds", "x", "uno", score=0.9),
                            _edge("a", "grounds", "x", "dos", state=U),
                            _edge("c", "grounds", "x", "tres", prov=Provenance.INFERRED, score=1.0)])
    ctx = proj.kg_context(None, budget=5000)
    assert _ids(ctx["items"]) == ["e_b__grounds__x", "e_c__grounds__x", "e_a__grounds__x"]
    assert ctx["items_total"] == 3 and ctx["hypotheses_total"] == 0 and "query_terms" not in ctx


def test_query_terms_cap(canon):
    from kg_engine.projector import _QUERY_TERM_CAP
    proj = _project(canon, [_edge("a", "grounds", "b", "uno")])
    words = " ".join(f"palabra{i:02d}" for i in range(_QUERY_TERM_CAP + 5))
    assert proj.kg_context(words)["query_terms"] == [f"palabra{i:02d}" for i in range(_QUERY_TERM_CAP)]


# ---- query_graph(text=…) ------------------------------------------------------------------------------------

def _review_world(canon: Canon) -> Projector:
    return _project(
        canon,
        [_edge("comprobadores", "enables", "retirar-revision", "comprobadores que el agente no puede tocar"),
         _edge("radar", "grounds", "aprobacion-humana", "RADAR muestra que se erosiona")],
        labels={"retirar-revision": "Retirar revisión", "no-retirar-revision-hoy": "Dónde no retirar la revisión hoy",
                "aprobacion-humana": "La aprobación humana se erosiona", "otro": "Algo distinto"},
        extra_nodes=("no-retirar-revision-hoy", "otro"))


def test_query_graph_text_finds_edgeless_nodes(canon):
    res = _review_world(canon).query_graph(text="retirar revisión")
    assert res["query_terms"] == ["retirar", "revision"]
    assert _ids(res["nodes"]) == ["retirar-revision", "no-retirar-revision-hoy"]  # equal weight: degree first
    assert _ids(res["edges"]) == ["e_comprobadores__enables__retirar-revision"]
    assert res["matched"] == {"nodes": 2, "edges": 1}


def test_query_graph_text_limit_keeps_the_true_count(canon):
    res = _review_world(canon).query_graph(text="retirar revisión humana", limit=1)
    assert len(res["nodes"]) == 1 and res["matched"]["nodes"] == 3


def test_query_graph_text_combines_with_the_filters(canon):
    proj = _review_world(canon)
    res = proj.query_graph(text="retirar revisión humana", relation="grounds")
    assert _ids(res["edges"]) == ["e_radar__grounds__aprobacion-humana"]
    assert _ids(res["nodes"]) == ["aprobacion-humana"]  # radar is kept by the filter but names no word
    assert proj.query_graph(text="retirar", epistemic_state="rejected") == {
        "nodes": [], "edges": [], "query_terms": ["retirar"], "matched": {"nodes": 0, "edges": 0}}


def test_query_graph_without_text_is_unchanged(canon):
    proj = _review_world(canon)
    res = proj.query_graph(limit=50)
    assert set(res) == {"nodes", "edges"}
    assert proj.query_graph(text="  ") == res == proj.query_graph(text=None, limit=50)


# ---- the tool surface --------------------------------------------------------------------------------------

class _FakeMCP:
    def __init__(self):
        self.tools: dict = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_the_mcp_tools_take_and_return_the_new_fields(engine):
    mcp = _FakeMCP()
    _register(mcp, engine)
    qg = mcp.tools["query_graph"]
    sig = inspect.signature(qg)
    assert sig.parameters["text"].default is None and "None" in str(sig.parameters["text"].annotation)
    assert list(sig.parameters)[:4] == ["node_type", "relation", "epistemic_state", "limit"]  # positional calls
    assert isinstance(qg(None, None, None), dict)
    out = qg(None, None, None, 50, "compresión")
    assert out["query_terms"] == ["compresion"] and set(out["matched"]) == {"nodes", "edges"}
    ctx = mcp.tools["kg_context"]("compression", 2000)
    assert {"items_total", "hypotheses_total", "query_terms"} <= set(ctx)


# ---- buildplan._fold got faster, not different --------------------------------------------------------------

def _reference_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def test_fold_is_the_same_function_over_every_code_point():
    chars = [chr(c) for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF]
    for i in range(0, len(chars), 4096):
        chunk = "".join(chars[i:i + 4096])
        assert _fold(chunk) == _reference_fold(chunk), hex(ord(chars[i]))
    for s in ("Revisión", "ÅNGSTRÖM", "Straße", "ﬁn", "ȩ́", "привет й", "Ελληνικά ΐ", "", None):
        assert _fold(s) == _reference_fold(s)


# ---- /kg-query and the tool reference ------------------------------------------------------------------------

def test_kg_query_reads_authorship_and_verdict_apart():
    assert "it has not yet been confirmed by a verdict" not in QUERY_MD
    assert "`epistemic_state` is the verdict" in QUERY_MD


def test_kg_query_names_the_configured_source_not_the_demo():
    assert "literal substring of `examples/source.md`" not in QUERY_MD
    assert "${user_config.source_path}" in QUERY_MD


def test_kg_query_explains_totals_and_text_search():
    for needle in ("items_total", "query_terms", 'query_graph(text="', "budget"):
        assert needle in QUERY_MD, needle
    # a headless /kg-query on the Spanish field canon translated its query_graph text into English, after
    # an English example in this file, and matched 2 nodes; the match is on the graph's own words
    assert "a translation finds little" in QUERY_MD
    assert 'query_graph(text="human review"' not in QUERY_MD


def test_tool_reference_documents_the_new_surface():
    for needle in ("query_graph(node_type=None, relation=None, epistemic_state=None, limit=50, text=None)",
                   "items_total", "hypotheses_total", "query_terms", "matched"):
        assert needle in TOOLS_MD, needle
    assert "does a `LIKE` filter" not in TOOLS_MD
