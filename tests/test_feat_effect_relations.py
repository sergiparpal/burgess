"""0.29.0: the pack gains `increases` and `decreases`, the two signs of an effect.

Field report (2026-11-22, two empirical papers registered as level-1 sources and built into a graph). Most of
their findings are effects: automatic suggestions lower experts' actual productivity and raise novices', and
interruptions raise stress. The pack had no relation for one. So the extractors restated each effect as a claim
node, «Experts are more productive with disabled suggestions», with a result node `grounds`-ing it: 26 of the
graph's 190 nodes were claims whose label states an effect, and no edge joined the factor to the quantity it
changes. They left other sections edgeless with notes such as «causal claims (intrusive suggestions lower
perceived productivity) that no pack relation carries». One predictor, «acceptance rate is a significant predictor
of perceived productivity», went in as `approximates`, a proxy, and was grounded.

Now the pack declares the two relations, sign in the name (the canon format, the payload and the boundary do not
change), and the relation table the extractor and the grounder share says what states an effect and what does not:
a hypothesis, a difference the source calls not significant, and an association or a predictor do not. The
grounder names the rejection for each wrong effect, the annotator counts a wrong sign as `wrong_type`, and a
«Fuentes» list joins the reference lists a build leaves out (6 of the 14 sections the new vocabulary brought back
on the field's notes). A record made under the old vocabulary stops applying, by 0.14.0's design.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kg_engine.buildplan import skip_reason
from kg_engine.groundplan import LEAD_MARK, lead_of, parse_lead
from kg_engine.model import edge_id
from kg_engine.pack import load_pack
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK_PATH = REPO / "pack" / "pack.yaml"
PACK = load_pack(PACK_PATH)
EFFECTS = ("increases", "decreases")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _roles(text: str) -> str:
    """The lines strictly between the relation-roles markers."""
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith("<!-- relation-roles:begin"))
    end = next(i for i, line in enumerate(lines) if line.startswith("<!-- relation-roles:end"))
    return "\n".join(lines[begin + 1:end])


EXTRACTOR = _read("agents/extractor.md")
GROUNDER = _read("agents/grounder.md")
SPAN = "For expert developers PRODa is significantly higher when suggestions are disabled"
FILE = "estudio.md"
DOC = ("# Estudio\n\nNov 27 · notas\n\n"
       f"## Resultados\n{SPAN}, with a large effect size.\n\n"
       "## Vocabulario\n- **PRODa:** la productividad real, medida por tarea.\n\n"
       "## Fuentes\n- Ashby, *An Introduction to Cybernetics*, 1956.\n")
HEAD, TAIL = "automatic-suggestions", "experts-actual-productivity"
NODES = [{"id": HEAD, "label": "Automatic suggestions", "node_type": "operation"},
         {"id": TAIL, "label": "Experts' actual productivity (PRODa)", "node_type": "metric"}]


def _edge(relation: str) -> dict:
    return {"source": HEAD, "target": TAIL, "relation": relation, "span": SPAN, "source_file": FILE}


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / FILE
    src.write_text(DOC, encoding="utf-8")
    return KGEngine(vault, source_path=src, pack_path=PACK_PATH)


def _edges(e: KGEngine) -> dict:
    return {x.id: x for n in e.canon.all_nodes() for x in n.edges}


# ---- the vocabulary ----------------------------------------------------------------------------------------

def test_the_pack_declares_both_signs_of_an_effect():
    assert all(r in PACK.edge_types for r in EFFECTS)
    assert "enables" in PACK.edge_types and len(PACK.edge_types) == 13


def test_the_pack_reference_mirrors_the_pack_lines():
    for relation in EFFECTS:
        line = next(x for x in _read("pack/pack.yaml").splitlines() if x.strip().startswith(f"- {relation} "))
        assert line in _read("skills/burgess/references/pack-schema.md").splitlines(), relation
    assert "### `edge_types` (13)" in _read("skills/burgess/references/pack-schema.md")


@pytest.mark.parametrize("relation", EFFECTS)
def test_an_effect_edge_is_accepted(eng, relation):
    out = eng.kg_write({"nodes": NODES, "edges": [_edge(relation)], "complete": True})
    assert out["dispositions"] == {"ACCEPTED": 3, "DEMOTED": 0, "QUARANTINED": 0, "REJECTED": 0}, out
    assert _edges(eng)[edge_id(HEAD, relation, TAIL)].relation == relation


def test_the_two_signs_between_the_same_nodes_are_two_edges(eng):
    # findings that disagree (two sources, or two groups written on one quantity by mistake) both stay in the
    # graph, for a grounder to judge each: neither collapses into the other as a duplicate
    assert eng.kg_write({"nodes": NODES, "edges": [_edge("increases")], "complete": True})["dispositions"][
        "ACCEPTED"] == 3
    out = eng.kg_write({"edges": [_edge("decreases")], "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 1, out
    edges = _edges(eng)
    assert {edge_id(HEAD, r, TAIL) for r in EFFECTS} <= set(edges)


def test_a_wrong_sign_is_rejected_with_the_other_sign_as_its_lead(eng):
    eng.kg_write({"nodes": NODES, "edges": [_edge("increases")], "complete": True})
    wrong = edge_id(HEAD, "increases", TAIL)
    lead = f"{HEAD} decreases {TAIL}"
    out = eng.kg_ground(wrong, "rejected", note="wrong-relation: PRODa falls with the suggestions on", lead=lead)
    assert out["ok"] and out["lead"] == lead, out
    assert lead_of(_edges(eng)[wrong].notes) == (HEAD, "decreases", TAIL)
    assert LEAD_MARK + lead in _edges(eng)[wrong].notes
    assert parse_lead("a increases b", PACK.edge_types) == (("a", "increases", "b"), "")


# ---- what the contracts say --------------------------------------------------------------------------------

def test_the_shared_table_has_a_row_for_each_sign():
    block = _roles(EXTRACTOR)
    rows = {r: (h, t) for r, h, t in re.findall(r"^\| (\w+)\s+\| (.+?)\s+\| (.+?)\s+\|$", block, flags=re.M)}
    assert rows["increases"] == ("the factor (cause/treatment)", "the quantity it raises")
    assert rows["decreases"] == ("the factor (cause/treatment)", "the quantity it lowers")
    assert rows["enables"] == ("the precondition or means", "what it makes possible")
    assert _roles(GROUNDER) == block                      # the grounder judges by the same table


def test_the_table_says_what_states_an_effect_and_what_does_not():
    flat = _flat(_roles(EXTRACTOR))
    for phrase in (
            "`increases` and `decreases` state an effect and its sign (0.29.0)",
            "The sign is the quantity's own",
            "The HEAD is the factor present, so a TAIL that rises when the HEAD is taken away is a decrease",
            "«PRODa is significantly higher when suggestions are disabled» states `automatic-suggestions decreases "
            "experts-actual-productivity`",
            "When the source gives the effect for one group or condition only, the TAIL names it",
            "None of these states an effect: a hypothesis or an expectation",
            "a difference the source itself calls not significant",
            "an association or a predictor («is associated with», «predicts», «se asocia con»), which has no pack "
            "relation",
            "a predictor is no proxy either, so it is not `approximates`",
            "What makes the TAIL possible is `enables`",
            "A remedy the source adopts or recommends against a threat is `defends_against`",
            "while a fall it reports in a quantity is `decreases`",
            "A bias of a figure is `confounded_by`"):
        assert phrase in flat, phrase


def test_the_extractor_writes_the_effect_not_a_claim_node_restating_it():
    flat = _flat(EXTRACTOR)
    assert "`increases`, `decreases`" in flat.split("## Relation DIRECTION")[0]       # the vocabulary list
    assert ("an effect («X reduces Y», «Y is higher with X») → `increases`/`decreases` from the factor to the "
            "quantity, written as that edge: never a claim node that restates the effect") in flat
    assert ("A hypothesis, an association or a difference the source calls not significant gets no effect edge"
            in flat)


def test_the_grounder_names_the_rejection_for_each_wrong_effect():
    flat = _flat(GROUNDER)
    for phrase in (
            "For `increases` and `decreases` (0.29.0): a span with the other sign → `wrong-relation`, its lead the "
            "same two ends with the other sign",
            "a span that only expects or hypothesizes the effect, or finds no significant difference → `no-support`",
            "one that reports an association or a predictor → `wrong-relation` with no lead, since the pack has no "
            "relation for it",
            "an effect the span gives for one group or condition, on a TAIL that names none → `wrong-node`"):
        assert phrase in flat, phrase


def test_the_annotator_counts_a_wrong_sign_as_wrong_type():
    flat = _flat(_read("agents/annotator.md"))
    assert ("A wrong sign is `wrong_type` too (0.29.0): `increases` where the source says the quantity falls, "
            "or the reverse") in flat


# ---- the build ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title", ["Fuentes", "5. Fuentes", "Fuentes consultadas", "FUENTES"])
def test_a_list_of_sources_is_a_reference_list(title):
    assert skip_reason(title, f"## {title}\n- Ashby, *An Introduction to Cybernetics*, 1956.\n") == "reference-list"


@pytest.mark.parametrize("title", ["Fuentes de error", "Fuentes de datos y sesgos"])
def test_a_section_about_sources_of_error_is_still_read(title):
    assert skip_reason(title, f"## {title}\nEl sesgo de selección infla la cifra de incidentes.\n") == ""


def _rows(plan: dict) -> "dict[str, dict]":
    return {s["title"]: s for f in plan["files"] for s in f["sections"]}


def test_a_record_made_before_the_effect_relations_no_longer_applies(eng):
    current = eng.pack
    eng.pack = current.model_copy(update={"edge_types": [t for t in current.edge_types if t not in EFFECTS]})
    section = _rows(eng.kg_build_plan("", ""))["Vocabulario"]["section"]
    assert eng.kg_section(FILE, section)["ok"]
    assert eng.kg_record_edgeless_section(FILE, section, "Un glosario: define términos, no los relaciona.")["ok"]
    assert "edgeless" in _rows(eng.kg_build_plan("", ""))["Vocabulario"]              # 0.28.3's vocabulary
    eng.pack = current
    plan = eng.kg_build_plan("", "")
    row = _rows(plan)["Vocabulario"]
    assert "edgeless" not in row and not row["covered"] and "skipped" not in row       # 0.29.0 reads it again
    assert _rows(plan)["Fuentes"]["skipped"] == "reference-list"
    assert plan["sections_uncovered"] == 2 and plan["sections_skipped"] == 1
