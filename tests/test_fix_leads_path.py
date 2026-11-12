"""0.9.0: a rejected claim carries a lead, the edge its span does state, and `/kg-build --leads` writes it.

Field report on 0.8.1, the third /kg-ground on the Windows corpus: the grounding loop converged (empty queue,
every hub attacked), and the grounders' reports had named thirteen leads over three passes, among them two
`enables` edges the 0.8.0 pack added and a narrower `manipulacion-de-tests` node. None could be written:
`/kg-build` skips every section that already has edges, and a lead lived only in a report and the user's
memory notes. Now:

- `kg_ground(..., verdict="rejected", lead="<head> <relation> <tail>")` checks the lead against the pack and
  appends it to the rejected edge's notes as `lead: <head> <relation> <tail>`;
- `kg_build_plan("--leads")` lists the pending leads by the section that holds each rejected span, and
  `kg_section(..., leads=True)` hands that section's extractor the leads with their spans;
- the edge an extractor writes opens its notes with `lead (from <rejected-edge-id>)`, which marks the lead
  taken; a lead whose edge already exists is not offered either.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kg_engine.buildplan import parse_arguments
from kg_engine.groundplan import LEAD_FROM_MARK, LEAD_MARK, lead_from, lead_of, parse_lead
from kg_engine.model import edge_id
from kg_engine.pack import load_pack
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK_PATH = REPO / "pack" / "pack.yaml"
TYPES = load_pack(PACK_PATH).edge_types
ROW = "Tests protegidos | Manipulación de tests"
PRE = "La autonomía alta aparece donde la verificación es automática y el riesgo, bajo"
DOC = ("# Retirar revisión\n\n## Mecanismos\n\n| Mecanismo | Cubre | Falla por |\n| --- | --- | --- |\n"
       "| Tests protegidos | Manipulación de tests | Trampas sin tocar tests |\n\n"
       f"## Autonomía\n\n{PRE}.\n")
TABLE_EDGE = edge_id("tests-protegidos", "defends_against", "hacer-trampas-con-los-tests")
PRE_EDGE = edge_id("verificacion-automatica", "grounds", "autonomia-alta")


def _nodes() -> list:
    return [{"id": "tests-protegidos", "label": "Tests protegidos", "node_type": "operation"},
            {"id": "hacer-trampas-con-los-tests", "label": "Hacer trampas con los tests", "node_type": "failure"},
            {"id": "verificacion-automatica", "label": "Verificación automática", "node_type": "primitive"},
            {"id": "autonomia-alta", "label": "Autonomía alta", "node_type": "claim"}]


def _edges(source_file: str = "doc.md") -> list:
    return [{"source": "tests-protegidos", "target": "hacer-trampas-con-los-tests", "relation": "defends_against",
             "span": ROW, "source_file": source_file},
            {"source": "verificacion-automatica", "target": "autonomia-alta", "relation": "grounds",
             "span": PRE, "source_file": source_file}]


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=PACK_PATH)
    out = e.kg_write({"nodes": _nodes(), "edges": _edges(), "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 6, out
    return e


def _reject_both(e: KGEngine) -> None:
    assert e.kg_ground(TABLE_EDGE, "rejected", note="wrong-node: the cell names test tampering",
                       lead="tests-protegidos defends_against manipulacion-de-tests")["ok"]
    assert e.kg_ground(PRE_EDGE, "rejected", note="wrong-relation: a precondition",
                       lead="verificacion-automatica enables autonomia-alta")["ok"]


def _notes(e: KGEngine, eid: str) -> str:
    return next(x for n in e._canon_baseline().values() for x in n.edges if x.id == eid).notes or ""


def _state(e: KGEngine, eid: str) -> str:
    return next(x for n in e._canon_baseline().values() for x in n.edges if x.id == eid).epistemic_state.value


# ---- reading and writing a lead ----------------------------------------------------------------------

def test_a_lead_is_two_ids_and_a_pack_relation():
    assert parse_lead("a enables b", TYPES) == (("a", "enables", "b"), "")
    assert parse_lead("Tests-Protegidos defends-against Manipulación", TYPES) == (
        ("tests-protegidos", "defends_against", "manipulación"), "")
    for bad in ("a enables", "a enables b c", "", "a causes b", "a enables a"):
        triple, problem = parse_lead(bad, TYPES)
        assert triple is None and problem, bad


def test_the_latest_lead_is_read_and_table_pipes_do_not_fool_it():
    notes = ("wrong-node: row 'Tests protegidos | Manipulación de tests' | lead: a defends_against b"
             " | Re-verdict: same | lead: a defends_against c")
    assert lead_of(notes) == ("a", "defends_against", "c")
    assert lead_of("lead: x enables y") == ("x", "enables", "y")
    for none in (None, "", "no lead here", "see lead: x enables", "a | lead: x enables y z"):
        assert lead_of(none) is None, none


def test_a_written_lead_names_the_edge_it_came_from():
    assert lead_from(f"{LEAD_FROM_MARK}e_a__grounds__b): the precondition") == "e_a__grounds__b"
    assert lead_from(f"  {LEAD_FROM_MARK}e_a__grounds__b)") == "e_a__grounds__b"
    for none in (None, "", "from lead e_a__grounds__b", f"note | {LEAD_FROM_MARK}e_a__grounds__b)"):
        assert lead_from(none) is None, none


def test_kg_ground_records_the_lead_after_the_note(eng):
    out = eng.kg_ground(PRE_EDGE, "rejected", note="wrong-relation: a precondition",
                        lead="verificacion-automatica enables autonomia-alta")
    assert out["ok"] and out["lead"] == "verificacion-automatica enables autonomia-alta", out
    assert _notes(eng, PRE_EDGE) == ("wrong-relation: a precondition | "
                                     f"{LEAD_MARK}verificacion-automatica enables autonomia-alta")
    assert lead_of(_notes(eng, PRE_EDGE)) == ("verificacion-automatica", "enables", "autonomia-alta")


@pytest.mark.parametrize("verdict,kind,lead", [
    ("rejected", "edge", "verificacion-automatica causes autonomia-alta"),     # not a pack relation
    ("rejected", "edge", "verificacion-automatica enables"),                   # malformed
    ("rejected", "edge", "autonomia-alta enables autonomia-alta"),             # self-loop
    ("rejected", "edge", "verificacion-automatica grounds autonomia-alta"),    # repeats the rejected edge
    ("grounded", "edge", "verificacion-automatica enables autonomia-alta"),    # a lead goes with a rejection
])
def test_a_bad_lead_changes_nothing(eng, verdict, kind, lead):
    before = _notes(eng, PRE_EDGE)
    out = eng.kg_ground(PRE_EDGE, verdict, kind=kind, note="t", lead=lead)
    assert not out["ok"] and "lead" in out["error"], out
    assert _state(eng, PRE_EDGE) == "unverified" and _notes(eng, PRE_EDGE) == before


def test_a_node_verdict_takes_no_lead(eng):
    out = eng.kg_ground("autonomia-alta", "rejected", kind="node", lead="a enables b")
    assert not out["ok"] and "lead" in out["error"]


# ---- the plan and the section --------------------------------------------------------------------------

def test_the_leads_plan_groups_the_pending_leads_by_section(eng):
    assert eng.kg_build_plan("--leads")["leads_total"] == 0
    _reject_both(eng)
    plan = eng.kg_build_plan("--leads")
    assert plan["ok"] and plan["mode"] == "leads" and plan["leads_total"] == 2 and plan["waves"] == 1, plan
    assert [(g["source_file"], g["section"], g["title"]) for g in plan["leads"]] == [
        ("doc.md", 1, "Mecanismos"), ("doc.md", 2, "Autonomía")]
    assert plan["leads"][0]["leads"] == [{"from_edge": TABLE_EDGE,
                                          "lead": "tests-protegidos defends_against manipulacion-de-tests"}]
    assert "files" not in plan and "sections_uncovered" not in plan     # a leads plan is not a build plan


def test_kg_section_hands_its_extractor_the_leads_with_their_spans(eng):
    _reject_both(eng)
    assert "leads" not in eng.kg_section("doc.md", 1)
    assert eng.kg_section("doc.md", 1, leads=True)["leads"] == [
        {"from_edge": TABLE_EDGE, "head": "tests-protegidos", "relation": "defends_against",
         "tail": "manipulacion-de-tests", "head_known": True, "tail_known": False, "span": ROW}]
    (only,) = eng.kg_section("doc.md", 2, leads=True)["leads"]
    assert (only["from_edge"], only["relation"], only["tail_known"], only["span"]) == (PRE_EDGE, "enables", True, PRE)


def test_a_written_lead_is_taken_and_queued_for_grounding(eng):
    _reject_both(eng)
    assert eng.kg_ground_plan("", "")["queue"]["leads_pending"] == 2
    out = eng.kg_write({"edges": [{"source": "verificacion-automatica", "target": "autonomia-alta",
                                   "relation": "enables", "span": PRE, "source_file": "doc.md",
                                   "notes": f"{LEAD_FROM_MARK}{PRE_EDGE}): the precondition"}]})
    assert out["dispositions"]["ACCEPTED"] == 1, out
    plan = eng.kg_build_plan("--leads")
    assert [lead["from_edge"] for g in plan["leads"] for lead in g["leads"]] == [TABLE_EDGE]
    ground = eng.kg_ground_plan("", "")
    assert ground["queue"]["leads_pending"] == 1
    assert {"id": edge_id("verificacion-automatica", "enables", "autonomia-alta"), "kind": "edge"} in [
        item for batch in ground["batches"] for item in batch]


def test_a_lead_written_under_another_id_is_still_taken(eng):
    # the extractor may reuse a known node for the lead's new end: the mark, not the id, takes the lead
    _reject_both(eng)
    out = eng.kg_write({"nodes": [{"id": "manipular-tests", "label": "Manipular los tests", "node_type": "failure"}],
                        "edges": [{"source": "tests-protegidos", "target": "manipular-tests",
                                   "relation": "defends_against", "span": ROW, "source_file": "doc.md",
                                   "notes": f"{LEAD_FROM_MARK}{TABLE_EDGE})"}]})
    assert out["dispositions"]["ACCEPTED"] == 2, out
    assert TABLE_EDGE not in str(eng.kg_build_plan("--leads")["leads"])


def test_a_lead_whose_edge_already_exists_is_not_offered(eng):
    eng.kg_write({"edges": [{"source": "verificacion-automatica", "target": "autonomia-alta", "relation": "enables",
                             "span": PRE, "source_file": "doc.md"}]})
    _reject_both(eng)
    assert PRE_EDGE not in str(eng.kg_build_plan("--leads")["leads"])


def test_a_lead_on_a_claim_judged_again_follows_its_latest_rejection(eng):
    _reject_both(eng)
    assert eng.kg_ground(PRE_EDGE, "rejected", note="again",
                         lead="autonomia-alta grounds verificacion-automatica")["ok"]
    (only,) = eng.kg_section("doc.md", 2, leads=True)["leads"]
    assert (only["head"], only["relation"], only["tail"]) == ("autonomia-alta", "grounds", "verificacion-automatica")
    assert eng.kg_ground(PRE_EDGE, "grounded", note="on reflection")["ok"]       # no longer rejected
    assert eng.kg_section("doc.md", 2, leads=True)["leads"] == []


def test_a_lead_whose_span_left_the_source_is_reported(vault: Path, tmp_path: Path, eng):
    _reject_both(eng)
    moved = tmp_path / "moved" / "doc.md"
    moved.parent.mkdir()
    moved.write_text(DOC.replace(PRE, "La autonomía cambió de sitio"), encoding="utf-8")
    plan = KGEngine(vault, source_path=moved, pack_path=PACK_PATH).kg_build_plan("--leads")
    assert plan["leads_unlocated"] == [PRE_EDGE] and plan["leads_total"] == 1, plan


def test_a_subset_narrows_the_leads(vault: Path, tmp_path: Path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "a.md").write_text(DOC, encoding="utf-8")
    (folder / "b.md").write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=folder, pack_path=PACK_PATH)
    assert e.kg_write({"nodes": _nodes(), "edges": _edges("a.md"), "complete": True})["dispositions"]["REJECTED"] == 0
    _reject_both(e)
    assert e.kg_build_plan("--leads")["leads_total"] == 2
    assert e.kg_build_plan("--leads b.md")["leads_total"] == 0
    assert e.kg_build_plan("--leads a.md 3")["leads_total"] == 2


# ---- the typed line ----------------------------------------------------------------------------------

@pytest.mark.parametrize("line,subset,wave,leads", [
    ("--leads", "", "", True),
    ("--leads 4", "", "4", True),
    ("--LEADS Fábricas de software.md 3", "Fábricas de software.md", "3", True),
    ("  --leads   \"capítulo 3\"  ", "capítulo 3", "", True),
    ("leads.md", "leads.md", "", False),
    ("--leadsx", "--leadsx", "", False),
    ("4", "", "4", False),
])
def test_leads_is_a_first_word(line, subset, wave, leads):
    got = parse_arguments(line)
    assert (got.subset, got.wave_size, got.leads, got.problem) == (subset, wave, leads, "")


# ---- the texts that wire it together -----------------------------------------------------------------

def _flat(rel: str) -> str:
    return " ".join((REPO / rel).read_text(encoding="utf-8").split())


def test_the_grounder_passes_the_lead_to_kg_ground():
    flat = _flat("agents/grounder.md")
    assert 'lead = "<head-id> <relation> <tail-id>"' in flat          # the verdict path's signature
    assert 'lead="tests-protegidos defends_against manipulacion-de-tests"' in flat
    template = " ".join(_flat("commands/kg-ground.md").split('subagent_type: "kg-grounder"', 1)[1]
                        .split('"""', 2)[1].split())
    assert "pass the edge the span does state as kg_ground's `lead`" in template


def test_kg_ground_points_at_kg_build_leads():
    flat = _flat("commands/kg-ground.md")
    assert "`queue.leads_pending`" in flat and "`/burgess:kg-build --leads`" in flat
    assert "this command writes no edge, and `/burgess:kg-build` skips every section that already has one" not in flat


def test_kg_build_documents_the_leads_mode_and_its_mark():
    text = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert re.search(r'argument-hint: "\[--leads\]', text)
    assert "kg_section(source_file: \"<file>\", section: <n>, leads: true)" in flat
    assert f"{LEAD_FROM_MARK}<from_edge>)" in flat


def test_the_extractor_has_a_leads_mode_with_the_same_mark():
    flat = _flat("agents/extractor.md")
    assert "## Leads mode (`/kg-build --leads`, 0.9.0)" in flat
    assert f"`{LEAD_FROM_MARK}<from_edge>)`" in flat
    assert "write nothing else" in flat
