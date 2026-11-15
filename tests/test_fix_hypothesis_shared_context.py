"""0.18.0: a proposal is judged against the source sections where both of its ends are discussed.

Field run (2026-11-15, 0.17.1). `/burgess:kg-ground` judged the fourth field generation, 40 span-less
proposals, in four batches. `kg_ground_item` gave a proposal its two nodes and no source text. Three grounders
looked the ends up with get_node and kg_context; the fourth judged its twelve proposals on the nodes alone. The
one proposal that grounded, `andamiaje-rivaliza-con-fine-tuning bridges o1-sin-prompting`, was promoted on a
span of the one section where both of its ends are discussed. How a proposal was judged depended on whether
its grounder went looking.

So, in this release:
- `kg_ground_item` gives an edge with no span a `shared_context`: the sections where a span of each end lies,
  nearest pair first, at most three, with excerpts, and where each end is discussed. Only live edges place an
  end, and a node promoted on a support span is also where that span lies;
- `kg_ground` refuses a lead on an edge with no span, which `/burgess:kg-build --leads` could not locate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_engine.groundplan import (END_SECTIONS, EXCERPT_CHARS, SHARED_SECTIONS, grounding_spans,
                                  nearest_pair, pair_excerpts, span_excerpt)
from kg_engine.model import normalize_text
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one

DOC = ("## Mecanismos\nIntro de los mecanismos.\n\n"
       "Medprompt llevó a GPT-4 al 90 % en MedQA. Es la prueba de que el andamiaje puede rivalizar con el "
       "fine-tuning.\n\n"
       "Su seguimiento mostró que o1-preview sin técnicas de prompting alcanzaba un 96 % en MedQA.\n\n"
       "Cierre de los mecanismos.\n\n"
       "## Costes\nEl RADAR de Meta mide el riesgo de cada cambio.\n\n"
       f"La clave {TOKEN} abre el panel del RADAR.\n\n"
       "## Riesgos\nAislar al agente reduce lo que puede romper.\n")
OTRO = "## Defensas\nCaMeL separa los datos del flujo de control.\n"

ANDAMIAJE = "Es la prueba de que el andamiaje puede rivalizar con el fine-tuning"
O1 = "o1-preview sin técnicas de prompting alcanzaba un 96 % en MedQA"
BRIDGE = "e_andamiaje__bridges__o1"
APART = "e_aislar__bridges__camel"


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text(DOC, encoding="utf-8")
    (src / "otro.md").write_text(OTRO, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    nodes = [("medprompt", "Medprompt", "operation"), ("andamiaje", "el andamiaje rivaliza", "claim"),
             ("o1", "o1-preview sin prompting", "claim"), ("radar", "RADAR de Meta", "metric"),
             ("riesgo", "riesgo", "failure"), ("panel", "panel", "primitive"),
             ("aislar", "aislar al agente", "operation"), ("rotura", "lo que puede romper", "failure"),
             ("camel", "CaMeL", "operation"), ("control", "flujo de control", "primitive")]
    out = e.kg_write({
        "nodes": [{"id": i, "label": label, "node_type": t} for i, label, t in nodes],
        "edges": [{"source": "medprompt", "target": "andamiaje", "relation": "grounds", "span": ANDAMIAJE,
                   "source_file": "doc.md"},
                  {"source": "medprompt", "target": "o1", "relation": "attacked_by", "span": O1,
                   "source_file": "doc.md"},
                  {"source": "radar", "target": "riesgo", "relation": "approximates",
                   "span": "El RADAR de Meta mide el riesgo de cada cambio", "source_file": "doc.md"},
                  {"source": "panel", "target": "radar", "relation": "projects",
                   "span": f"La clave {TOKEN} abre el panel del RADAR", "source_file": "doc.md"},
                  {"source": "aislar", "target": "rotura", "relation": "defends_against",
                   "span": "Aislar al agente reduce lo que puede romper", "source_file": "doc.md"},
                  {"source": "camel", "target": "control", "relation": "defends_against",
                   "span": "CaMeL separa los datos del flujo de control", "source_file": "otro.md"}]})
    assert out["dispositions"]["ACCEPTED"] == 16, out
    got = e.kg_propose({"edges": [{"source": "andamiaje", "target": "o1", "relation": "bridges"},
                                  {"source": "aislar", "target": "camel", "relation": "bridges"},
                                  {"source": "riesgo", "target": "radar", "relation": "confounded_by"}]})
    assert got["dispositions"]["ACCEPTED"] == 3, got
    return e


def _where(listed: "list[dict]") -> "list[tuple[str, int]]":
    return [(s["source_file"], s["section"]) for s in listed]


# --------------------------------------------------------------------------- the evidence


def test_a_proposal_gets_the_section_where_both_ends_are_discussed(eng):
    got = eng.kg_ground_item(BRIDGE)
    assert got["ok"] and got["context"] is None and got["span_in_source"] is None
    shared = got["shared_context"]
    assert _where(shared["sections"]) == [("doc.md", 1)] and shared["sections_total"] == 1
    assert shared["sections"][0]["title"] == "Mecanismos"
    excerpts = shared["sections"][0]["excerpts"]
    assert len(excerpts) == 1                    # the two spans sit in neighbouring paragraphs: one passage
    assert ANDAMIAJE in excerpts[0] and O1 in excerpts[0]
    assert _where(shared["source_node_sections"]) == _where(shared["target_node_sections"]) == [("doc.md", 1)]


def test_ends_never_discussed_together_share_no_section(eng):
    shared = eng.kg_ground_item(APART)["shared_context"]
    assert shared["sections"] == [] and shared["sections_total"] == 0
    assert _where(shared["source_node_sections"]) == [("doc.md", 3)]
    assert _where(shared["target_node_sections"]) == [("otro.md", 1)]
    assert (shared["source_node_sections_total"], shared["target_node_sections_total"]) == (1, 1)


def test_an_end_with_no_span_edge_is_not_placed(eng):
    eng.kg_propose({"nodes": [{"id": "compression-x", "label": "X", "node_type": "compression"}],
                    "edges": [{"source": "riesgo", "target": "compression-x", "relation": "collapses_into"}]})
    shared = eng.kg_ground_item("e_riesgo__collapses-into__compression-x")["shared_context"]
    assert shared["sections"] == [] and shared["target_node_sections"] == []
    assert shared["target_node_sections_total"] == 0
    assert _where(shared["source_node_sections"]) == [("doc.md", 2)]


def test_only_live_edges_place_an_end(eng):
    out = eng.kg_ground("e_medprompt__attacked-by__o1", "rejected", note="no-support: test")
    assert out["ok"], out
    shared = eng.kg_ground_item(BRIDGE)["shared_context"]
    assert shared["sections"] == [] and shared["target_node_sections_total"] == 0


def test_the_edge_between_the_two_ends_counts_for_both(eng):
    """An end pair an existing edge already joins shares that edge's section; the proposal is judged against
    the passage that states the other relation."""
    shared = eng.kg_ground_item("e_riesgo__confounded-by__radar")["shared_context"]
    assert _where(shared["sections"]) == [("doc.md", 2)]
    assert "El RADAR de Meta mide el riesgo de cada cambio" in shared["sections"][0]["excerpts"][0]


def test_an_edge_with_a_span_keeps_its_context_and_no_shared_context(eng):
    got = eng.kg_ground_item("e_medprompt__grounds__andamiaje")
    assert got["span_in_source"] is True and got["context"]["title"] == "Mecanismos"
    assert got["shared_context"] is None


def test_a_node_promoted_on_a_span_is_placed_by_it(eng):
    eng.kg_propose({"nodes": [{"id": "compression-y", "label": "Y", "node_type": "compression"}],
                    "edges": [{"source": "camel", "target": "compression-y", "relation": "collapses_into"}]})
    star = "e_camel__collapses-into__compression-y"
    assert eng.kg_ground_item(star)["shared_context"]["target_node_sections"] == []
    out = eng.kg_ground("compression-y", "grounded", kind="node",
                        support_span="CaMeL separa los datos del flujo de control")
    assert out["ok"], out
    shared = eng.kg_ground_item(star)["shared_context"]
    assert _where(shared["target_node_sections"]) == [("otro.md", 1)]
    assert _where(shared["sections"]) == [("otro.md", 1)]


def test_shared_excerpts_leave_through_the_session_scrub(eng):
    eng.kg_propose({"edges": [{"source": "panel", "target": "riesgo", "relation": "bridges"}]})
    got = eng.kg_ground_item("e_panel__bridges__riesgo")
    blob = json.dumps(got)
    assert TOKEN not in blob
    assert "⟦SECRET:" in got["shared_context"]["sections"][0]["excerpts"][0]
    restore = eng._restore_fn()
    assert TOKEN in restore(got["shared_context"]["sections"][0]["excerpts"][0])


def test_at_most_three_sections_nearest_pair_first(vault: Path, tmp_path: Path):
    """Five sections discuss both ends, the pair of spans 3, 2, 1, 0 and 0 paragraphs apart."""
    filler = "Relleno sin nada.\n\n"
    sections, edges = [], []
    for i, gap in enumerate((3, 2, 1, 0, 0), start=1):
        x, y = f"Equis menciona a{i} aquí", f"Ye menciona b{i} allí"
        body = f"{x}. {y}." if i == 4 else f"{x}.\n\n{filler * gap}{y}."
        sections.append(f"## S{i}\n{body}\n")
        edges += [{"source": "x", "target": f"a{i}", "relation": "grounds", "span": x, "source_file": "doc.md"},
                  {"source": "y", "target": f"b{i}", "relation": "grounds", "span": y, "source_file": "doc.md"}]
    src = tmp_path / "doc.md"
    src.write_text("\n".join(sections), encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    ids = ["x", "y"] + [f"a{i}" for i in range(1, 6)] + [f"b{i}" for i in range(1, 6)]
    e.kg_write({"nodes": [{"id": i, "label": i, "node_type": "claim"} for i in ids], "edges": edges})
    e.kg_propose({"edges": [{"source": "x", "target": "y", "relation": "bridges"}]})
    shared = e.kg_ground_item("e_x__bridges__y")["shared_context"]
    assert SHARED_SECTIONS == 3
    assert [s["section"] for s in shared["sections"]] == [4, 5, 3]
    assert shared["sections_total"] == 5
    assert [s["section"] for s in shared["source_node_sections"]] == [1, 2, 3, 4, 5]


def test_each_end_lists_at_most_twelve_sections(vault: Path, tmp_path: Path):
    n = END_SECTIONS + 2
    src = tmp_path / "doc.md"
    src.write_text("\n".join(f"## S{i}\nEquis trata el tema {i} a fondo.\n" for i in range(n)), encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    e.kg_write({"nodes": [{"id": i, "label": i, "node_type": "claim"} for i in ["x", "y"] + [f"t{i}" for i in range(n)]],
                "edges": [{"source": "x", "target": f"t{i}", "relation": "grounds",
                           "span": f"Equis trata el tema {i} a fondo", "source_file": "doc.md"} for i in range(n)]})
    e.kg_propose({"edges": [{"source": "x", "target": "y", "relation": "bridges"}]})
    shared = e.kg_ground_item("e_x__bridges__y")["shared_context"]
    assert len(shared["source_node_sections"]) == END_SECTIONS
    assert shared["source_node_sections_total"] == n


# --------------------------------------------------------------------------- the pure helpers


def test_nearest_pair_counts_the_paragraphs_between_the_two_spans():
    text = "Uno dice alfa.\n\nDos.\n\nTres.\n\nCuatro dice beta.\n\nCinco dice alfa otra vez.\n\nSeis dice beta."
    assert nearest_pair(text, ["Uno dice alfa"], ["Cuatro dice beta"]) == (2, "Uno dice alfa", "Cuatro dice beta")
    # the nearest pair wins, whatever the order of the lists
    assert nearest_pair(text, ["Uno dice alfa", "Cinco dice alfa otra vez"], ["Cuatro dice beta", "Seis dice beta"]
                        ) == (0, "Cinco dice alfa otra vez", "Cuatro dice beta")
    assert nearest_pair(text, ["Uno dice alfa"], ["no está"]) is None
    # as near, a span both ends share beats two spans in neighbouring paragraphs
    assert nearest_pair(text, ["Cinco dice alfa otra vez"], ["Seis dice beta", "Cinco dice alfa otra vez"]
                        ) == (0, "Cinco dice alfa otra vez", "Cinco dice alfa otra vez")


def test_pair_excerpts_are_one_passage_when_it_fits_else_one_each():
    near = "Alfa dice algo.\n\nBeta responde."
    assert pair_excerpts(near, "Alfa dice algo", "Beta responde") == [near]
    filler = ("palabra " * 120 + "\n\n") * 6
    far = f"Alfa dice algo.\n\n{filler}Beta responde."
    got = pair_excerpts(far, "Alfa dice algo", "Beta responde")
    assert len(got) == 2 and "Alfa dice algo" in got[0] and "Beta responde" in got[1]
    assert sum(len(x) for x in got) <= EXCERPT_CHARS
    # one span for both ends (the edge that joins them) is span_excerpt's own excerpt, with the whole room
    assert pair_excerpts(far, "Alfa dice algo", "Alfa dice algo") == [span_excerpt(far, "Alfa dice algo")]


def test_grounding_spans_read_the_promotion_paragraphs():
    body = ("Una idea.\n\ngrounding span: la cita exacta\n\ngrounding source: doc.md\n\n"
            "grounding span: otra cita\n\nverdict (grounded): ok")
    assert grounding_spans(body) == [("la cita exacta", "doc.md"), ("otra cita", "")]
    assert grounding_spans("") == [] and grounding_spans(None) == []


def test_the_excerpts_match_what_the_span_check_matches():
    text = "Primera línea.\n\nEl  RADAR\nde Meta mide el riesgo."
    got = pair_excerpts(text, "el radar de meta", "mide el riesgo")
    assert len(got) == 1 and normalize_text("el radar de meta mide el riesgo") in normalize_text(got[0])


# --------------------------------------------------------------------------- the lead


def test_a_lead_on_an_edge_with_no_span_is_refused_before_anything_changes(eng):
    out = eng.kg_ground(BRIDGE, "rejected", note="no-support: §1 states another relation",
                        lead="andamiaje attacked_by o1")
    assert out["ok"] is False and out["error"].startswith("lead: this edge has no span")
    assert "/burgess:kg-build --leads" in out["error"]
    assert eng.kg_ground_item(BRIDGE)["edge"]["epistemic_state"] == "unverified"
    assert eng.kg_ground(BRIDGE, "rejected", note="no-support: §1 states andamiaje attacked_by o1")["ok"]


# --------------------------------------------------------------------------- the texts that wire it


def test_the_grounder_judges_a_proposal_against_its_shared_context():
    flat = " ".join(GROUNDER.split())
    assert "**The check is the excerpt, not a file.**" in flat       # the 0.7.0 rule stands
    assert "For a proposal, the excerpts are those of `shared_context`." in flat
    assert "**Judge a proposal against its `shared_context`** (0.18.0)." in flat
    assert ("the source never discusses the two together and holds no support for the proposal: reject it "
            "`no-support`") in flat
    assert "A citation from outside the source still goes in `support_note`" in flat
    assert "A proposal takes no `lead`" in flat
    assert "judge it by **Judge a proposal against its `shared_context`**" in flat


def test_the_batch_prompt_and_the_references_name_shared_context():
    flat = " ".join(GROUND_CMD.split())
    assert "shared_context, the source sections where both its ends are discussed" in flat
    assert "A proposal takes no lead" in flat
    assert "`shared_context` — for an edge with no span, a proposal" in TOOLS
    assert "So is a lead on an edge with no span" in " ".join(TOOLS.split())
    server = (REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8")
    assert "`shared_context` instead: up to 3 source sections where both its ends are discussed" in server
