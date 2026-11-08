"""0.10.2: a verdict that keeps an edge's state keeps the time the edge entered it.

Field report on 0.10.1 (the Windows corpus: 416 nodes and 203 edges, every edge with a verdict). 142 of its 162
grounded edges were judged on 0.6.x/0.7.0, before 0.8.1's rules on tables and on what each node names, so the
next step was to judge them again under the current contract. Through 0.10.1, `kg_ground` stamped `verdict_at`
on every call, and `kg_ground_plan` reads that field as the time a claim was grounded. So re-confirming a
grounded claim of a hub an adversarial pass had already attacked made the claim look new, and the plan offered
the hub to a second attack that had nothing new to find. On a scratch copy of the field canon, re-confirming
one claim of `radar-meta` and one of `autonomia-n4-a-escala` reopened both hubs.

Now `verdict_by` and `verdict_at` record who put an edge in its state, and when. A re-verdict that keeps the
state still appends its note and lead, and the audit log still records it at its own time, but the two fields
stay as they were.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_engine.canon import GROUND_AUDIT
from kg_engine.groundplan import ATTACK_MARK
from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
DOC = "## H\nEl centro une a, b, c y d.\n\nLa crítica ataca al centro por vago.\n"
CENTRO, CRITICA = "El centro une a, b, c y d", "La crítica ataca al centro por vago"
QUESTION = "¿Qué medida independiente del centro lo falsaría?"
COUNTER = edge_id("centro", "attacked_by", "critica")


def _claim(target: str) -> dict:
    return {"source": "centro", "target": target, "relation": "grounds", "span": CENTRO, "source_file": "hub.md"}


def _eid(target: str) -> str:
    return edge_id("centro", "grounds", target)


@pytest.fixture
def eng(vault: Path, tmp_path: Path, monkeypatch) -> KGEngine:
    ticks = iter(f"2026-11-08T10:{m:02d}:00+00:00" for m in range(60))
    clock = lambda: next(ticks)                                          # noqa: E731
    monkeypatch.setattr("kg_engine.server.utcnow", clock)               # verdicts and ledger records
    monkeypatch.setattr("kg_engine.groundaudit.utcnow", clock)          # audit records, on the same clock
    src = tmp_path / "hub.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    assert e.kg_write({"edges": [_claim(t) for t in "abc"]})["dispositions"]["ACCEPTED"] == 3
    for t in "abc":
        assert e.kg_ground(_eid(t), "grounded", note="t")["ok"]
    return e


def _edge(e: KGEngine, eid: str):
    return next(x for x in e.canon.read_node("centro").edges if x.id == eid)


def _hubs(e: KGEngine) -> "tuple[list[str], list[str]]":
    plan = e.kg_ground_plan("", "")
    return [h["id"] for h in plan["hubs"]], plan["attacked_hubs"]


def _audit(e: KGEngine) -> list:
    lines = (e.canon.root / GROUND_AUDIT).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _counter_edge(e: KGEngine) -> None:
    counter = {"source": "centro", "target": "critica", "relation": "attacked_by", "span": CRITICA,
               "source_file": "hub.md", "notes": f"{ATTACK_MARK}centro): vague"}
    assert e.kg_write({"edges": [counter]})["dispositions"]["ACCEPTED"] >= 1


# ---- the field case ----------------------------------------------------------------------------------

def test_reconfirming_a_claim_keeps_an_attacked_hub_out(eng):
    assert eng.kg_record_attack("centro", QUESTION, "no-span")["ok"]
    assert _hubs(eng) == ([], ["centro"])
    before = _edge(eng, _eid("a"))
    out = eng.kg_ground(_eid("a"), "grounded", note="re-judged under the current contract")
    assert out["ok"] and (out["from"], out["to"]) == ("grounded", "grounded")
    after = _edge(eng, _eid("a"))
    assert (after.verdict_by, after.verdict_at) == (before.verdict_by, before.verdict_at)
    assert after.notes.endswith("re-judged under the current contract")
    assert _hubs(eng) == ([], ["centro"])                       # 0.10.1 offered it to a second attack


def test_reconfirming_a_claim_of_a_hub_attacked_with_counter_edges(eng):
    _counter_edge(eng)
    assert eng.kg_ground(COUNTER, "grounded", note="t")["ok"]
    assert _hubs(eng) == ([], ["centro"])
    for t in "abc":
        assert eng.kg_ground(_eid(t), "grounded", note="re-judged")["ok"]
    assert _hubs(eng) == ([], ["centro"])


def test_the_reconfirmation_is_audited_at_its_own_time(eng):
    kept = _edge(eng, _eid("a")).verdict_at
    assert eng.kg_ground(_eid("a"), "grounded", note="again")["ok"]
    last = _audit(eng)[-1]
    assert (last["key"], last["from"], last["to"], last["by"]) == (_eid("a"), "grounded", "grounded", "agent")
    assert last["at"] > kept


# ---- a change of state still stamps the time ---------------------------------------------------------

def test_a_change_of_state_still_stamps_the_time(eng):
    grounded_at = _edge(eng, _eid("a")).verdict_at
    assert eng.kg_ground(_eid("a"), "rejected", note="t")["ok"]
    rejected_at = _edge(eng, _eid("a")).verdict_at
    assert rejected_at > grounded_at
    assert eng.kg_ground(_eid("a"), "grounded", note="t")["ok"]
    assert _edge(eng, _eid("a")).verdict_at > rejected_at


def test_a_claim_grounded_again_after_a_rejection_reopens_the_hub(eng):
    assert eng.kg_write({"edges": [_claim("d")]})["dispositions"]["ACCEPTED"] >= 1
    assert eng.kg_ground(_eid("d"), "grounded", note="t")["ok"]
    assert eng.kg_record_attack("centro", QUESTION, "no-span")["ok"]
    assert eng.kg_ground(_eid("a"), "rejected", note="t")["ok"]
    assert _hubs(eng) == ([], ["centro"])                       # three live claims, none grounded since
    assert eng.kg_ground(_eid("a"), "grounded", note="t")["ok"]  # it entered `grounded` after the attack
    assert _hubs(eng) == (["centro"], [])


# ---- a re-sealed rejected edge -----------------------------------------------------------------------

def test_resealing_a_rejected_edge_with_a_lead_keeps_its_time(eng):
    assert eng.kg_ground(_eid("a"), "rejected", note="wrong-node: t")["ok"]
    kept = _edge(eng, _eid("a"))
    out = eng.kg_ground(_eid("a"), "rejected", note="lead chosen by the user", lead="b grounds c")
    assert out["ok"] and out["lead"] == "b grounds c"
    edge = _edge(eng, _eid("a"))
    assert (edge.verdict_by, edge.verdict_at) == (kept.verdict_by, kept.verdict_at)
    assert edge.notes.endswith("lead: b grounds c")
    assert eng.kg_ground_plan("", "")["queue"]["leads_pending"] == 1


def test_resealing_a_counter_edge_keeps_the_time_of_the_attack(eng):
    _counter_edge(eng)
    assert eng.kg_ground(COUNTER, "rejected", note="wrong-node: t")["ok"]
    assert _hubs(eng) == ([], ["centro"])
    assert eng.kg_write({"edges": [_claim("d")]})["dispositions"]["ACCEPTED"] >= 1
    assert eng.kg_ground(_eid("d"), "grounded", note="t")["ok"]  # a claim grounded after the attack
    assert _hubs(eng) == (["centro"], [])
    assert eng.kg_ground(COUNTER, "rejected", note="re-judged")["ok"]
    assert _hubs(eng) == (["centro"], [])                       # 0.10.1 moved the mark past the new claim


# ---- who put the edge in its state -------------------------------------------------------------------

def test_a_reconfirmation_keeps_who_put_the_edge_in_its_state(eng):
    kept = _edge(eng, _eid("a"))
    out = eng.kg_ground(_eid("a"), "grounded", by="human", note="looked at it")
    assert out["ok"] and out["by"] == "human"
    edge = _edge(eng, _eid("a"))
    assert (edge.verdict_by, edge.verdict_at) == ("agent", kept.verdict_at)
    assert _audit(eng)[-1]["by"] == "human"                     # the audit log says who re-confirmed it


def test_an_edge_in_a_verdict_state_with_no_time_gets_one(eng):
    node = eng.canon.read_node("centro")
    edge = next(x for x in node.edges if x.id == _eid("a"))
    edge.verdict_by = edge.verdict_at = None                    # as a hand edit can leave it
    eng.canon.write_one(node)
    assert eng.kg_ground(_eid("a"), "grounded", note="t")["ok"]
    edge = _edge(eng, _eid("a"))
    assert edge.verdict_by == "agent" and edge.verdict_at
