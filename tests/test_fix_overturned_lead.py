"""0.11.1: a lead belongs to the rejection that recorded it.

Field report on 0.11.0, the Windows corpus. Re-judging the first pass rejected three grounded edges as
`wrong-node`, each with a lead to a new node. The user then ruled that each node already named what its span
names, and a grounder grounded the three edges again. Their leads stayed in the notes, and `lead_of` read the
newest lead whatever verdicts came after it. So if a later re-judge rejected one of them without a lead, as
`vague` say, `leads_pending` would offer the lead the user had ruled out, and `/kg-build --leads` would write
it: for `e_zalando__grounds__autonomia-n4-a-escala`, a node that duplicates the N4 claim.

Now a verdict that changes an edge's state and records no lead of its own appends `lead: none`, which
withdraws the lead the notes held, and `kg_ground` returns it as `lead_withdrawn`. A re-confirmation keeps the
lead, as it keeps the time (0.10.2), and a lead a verdict records still replaces the old one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.groundplan import LEAD_MARK, LEAD_NONE, lead_of
from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
SPAN = "Zalando aprueba de forma automática los cambios de bajo riesgo"
DOC = f"# Fábricas\n\n## Integración\n\n{SPAN}, y solo en pocas empresas a escala.\n"
EDGE = edge_id("zalando", "grounds", "autonomia-n4-a-escala")
OVERTURNED = "zalando grounds aprobacion-automatica-a-escala"      # the lead the user ruled out
OTHER = "zalando enables autonomia-n4-a-escala"


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    out = e.kg_write({"nodes": [{"id": "zalando", "label": "Zalando", "node_type": "primitive"},
                                {"id": "autonomia-n4-a-escala", "label": "N4 existe a escala", "node_type": "claim"}],
                      "edges": [{"source": "zalando", "target": "autonomia-n4-a-escala", "relation": "grounds",
                                 "span": SPAN, "source_file": "doc.md"}],
                      "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 3, out
    assert e.kg_ground(EDGE, "grounded", note="first pass")["ok"]
    return e


def _notes(e: KGEngine) -> str:
    return next(x for x in e.canon.read_node("zalando").edges if x.id == EDGE).notes or ""


def _pending(e: KGEngine) -> int:
    return e.kg_ground_plan("", "")["queue"]["leads_pending"]


def _reject_with_the_lead(e: KGEngine) -> None:
    out = e.kg_ground(EDGE, "rejected", note="wrong-node: the row never names N4", lead=OVERTURNED)
    assert out["ok"] and out["lead"] == OVERTURNED, out
    assert _pending(e) == 1


# ---- the field case ----------------------------------------------------------------------------------

def test_an_overturned_lead_is_not_offered_again(eng):
    _reject_with_the_lead(eng)
    assert eng.kg_ground(EDGE, "grounded", note="re-verdict with the user's decision")["ok"]
    out = eng.kg_ground(EDGE, "rejected", note="vague: a later re-judge")
    assert out["ok"] and "lead_withdrawn" not in out, out    # already withdrawn when it was overturned
    assert _pending(eng) == 0                                # 0.11.0 offered OVERTURNED again
    assert eng.kg_build_plan("--leads")["leads"] == []


def test_the_verdict_that_overturns_a_rejection_withdraws_its_lead(eng):
    _reject_with_the_lead(eng)
    out = eng.kg_ground(EDGE, "grounded", note="re-verdict with the user's decision")
    assert out["ok"] and out["lead_withdrawn"] == OVERTURNED, out
    assert _notes(eng).endswith(f"re-verdict with the user's decision | {LEAD_NONE}")
    assert lead_of(_notes(eng)) is None


def test_a_lead_overturned_before_0_11_1_is_withdrawn_when_the_edge_is_rejected_again(eng):
    _reject_with_the_lead(eng)
    assert eng.kg_ground(EDGE, "grounded", note="re-verdict with the user's decision")["ok"]
    node = eng.canon.read_node("zalando")                    # as 0.11.0 left the field edges: no `lead: none`
    edge = next(x for x in node.edges if x.id == EDGE)
    edge.notes = edge.notes.removesuffix(f" | {LEAD_NONE}")
    eng.canon.write_one(node)
    assert lead_of(_notes(eng)) == tuple(OVERTURNED.split())
    out = eng.kg_ground(EDGE, "rejected", note="vague: a later re-judge")
    assert out["ok"] and out["lead_withdrawn"] == OVERTURNED, out
    assert _notes(eng).endswith(f"vague: a later re-judge | {LEAD_NONE}")
    assert _pending(eng) == 0


# ---- what keeps a lead, and what replaces it -----------------------------------------------------------

def test_a_reconfirmed_rejection_keeps_its_lead(eng):
    _reject_with_the_lead(eng)
    out = eng.kg_ground(EDGE, "rejected", note="re-judged: still wrong-node")
    assert out["ok"] and "lead_withdrawn" not in out, out
    assert LEAD_NONE not in _notes(eng)
    assert lead_of(_notes(eng)) == tuple(OVERTURNED.split()) and _pending(eng) == 1


def test_a_new_lead_replaces_the_withdrawn_one(eng):
    _reject_with_the_lead(eng)
    assert eng.kg_ground(EDGE, "grounded", note="t")["ok"]
    out = eng.kg_ground(EDGE, "rejected", note="wrong-relation: a precondition", lead=OTHER)
    assert out["ok"] and out["lead"] == OTHER and "lead_withdrawn" not in out, out
    assert _notes(eng).endswith(f"{LEAD_MARK}{OTHER}")
    assert [x["lead"] for g in eng.kg_build_plan("--leads")["leads"] for x in g["leads"]] == [OTHER]


@pytest.mark.parametrize("verdict", ["failed", "obsolete"])
def test_any_change_of_state_withdraws_the_lead(eng, verdict):
    _reject_with_the_lead(eng)
    out = eng.kg_ground(EDGE, verdict, note="t")
    assert out["ok"] and out["lead_withdrawn"] == OVERTURNED, out
    assert lead_of(_notes(eng)) is None


def test_a_change_of_state_with_no_lead_to_withdraw_adds_nothing(eng):
    assert _notes(eng) == "first pass"
    out = eng.kg_ground(EDGE, "rejected", note="vague: t")
    assert out["ok"] and "lead_withdrawn" not in out, out
    assert _notes(eng) == "first pass | vague: t"


def test_a_lead_is_withdrawn_once(eng):
    _reject_with_the_lead(eng)
    assert eng.kg_ground(EDGE, "grounded", note="t")["ok"]
    out = eng.kg_ground(EDGE, "failed", note="t")
    assert out["ok"] and "lead_withdrawn" not in out, out
    assert _notes(eng).count(LEAD_NONE) == 1


# ---- reading the notes -----------------------------------------------------------------------------------

def test_lead_of_reads_a_withdrawal():
    lead = "lead: a grounds b"
    assert lead_of(f"wrong-node: t | {lead} | grounded again | {LEAD_NONE}") is None
    assert lead_of(f"{LEAD_NONE} | t | {lead}") == ("a", "grounds", "b")     # a later lead replaces it
    assert lead_of("lead: none grounds b") == ("none", "grounds", "b")      # a node may be called `none`
    for no_lead in ("lead: nonesuch", "lead: none.", "see lead: none", f"t | {LEAD_NONE}"):
        assert lead_of(no_lead) is None, no_lead


def test_the_tool_and_the_references_say_a_change_of_state_withdraws_a_lead():
    server = (REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8")
    tools = " ".join((REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8").split())
    arch = " ".join((REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").split())
    assert "returned as `lead_withdrawn`" in " ".join(server.split())
    assert "`lead: none`" in tools and '`"lead_withdrawn"`' in tools
    assert "`lead: none`" in arch
