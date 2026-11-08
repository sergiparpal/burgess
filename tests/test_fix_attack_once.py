"""0.8.0: an adversarial pass marks its counter-edges with the hub they attack, and the plan stops offering that
hub until it gains a grounded claim.

Field report on 0.7.0 (a canon of 406 nodes): `kg_ground_plan` ranked hubs by every incident edge, refuted ones
and the adversarial grounder's own counter-edges included, and nothing recorded an attack. On that canon the
next plan offered the same five hubs the pass had just attacked, so every /kg-ground would have ended with about
ten new unverified counter-edges against them, and the queue would never have emptied. Now:

- a hub's degree counts its live claims: no edge in `NON_LIVE_STATE_VALUES` (the set every structural surface
  reads) and no counter-edge;
- a counter-edge is one whose notes open with `counter-edge (adversarial pass, hub <id>)`, the form the
  adversarial grounder wrote on all ten of that pass's counter-edges;
- an unfocused plan leaves out, in `attacked_hubs`, a hub with a counter-edge awaiting its verdict, or whose
  newest counter-edge verdict is no older than its newest grounded claim. A focus attacks the hubs it names
  regardless: naming a concept is how a user asks for a second attack.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kg_engine.groundplan import ATTACK_MARK, already_attacked, attacked_hub
from kg_engine.model import NON_LIVE_STATE_VALUES, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
ADVERSARIAL = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")
DOC = ("## H\nEl centro une a, b, c y d.\n\nEl otro une x, y y z.\n\n"
       "La crítica ataca al centro por vago.\n")
CENTRO, OTRO, CRITICA = "El centro une a, b, c y d", "El otro une x, y y z", "La crítica ataca al centro por vago"


# ---- the mark and the rule ---------------------------------------------------------------------------

def test_the_mark_names_the_hub_in_the_forms_the_field_pass_wrote():
    assert attacked_hub("counter-edge (adversarial pass, hub radar-meta): the source sets RADAR") == "radar-meta"
    assert attacked_hub("counter-edge (adversarial pass, hub radar-meta via its grounded neighbor H7), "
                        "standing challenge") == "radar-meta"
    assert attacked_hub("counter-edge (adversarial pass, hub escribir-codigo-parte-pequena, the vaguest hub)"
                        ) == "escribir-codigo-parte-pequena"
    assert attacked_hub("  counter-edge (adversarial pass, hub strongdm)") == "strongdm"


def test_other_notes_carry_no_mark():
    for notes in (None, "", "counter-edge: no hub named", "see counter-edge (adversarial pass, hub x)"):
        assert attacked_hub(notes) is None


def test_the_attack_rule():
    assert not already_attacked([], "2026-11-08T10:00:00+00:00")                     # never attacked
    assert already_attacked([("unverified", None)], "2026-11-08T10:05:00+00:00")     # awaiting its verdict
    judged = [("rejected", "2026-11-08T10:02:00+00:00")]
    assert already_attacked(judged, "2026-11-08T10:01:00+00:00")                     # nothing grounded since
    assert already_attacked(judged, None)
    assert not already_attacked(judged, "2026-11-08T10:03:00+00:00")                 # a claim grounded since


# ---- the plan ----------------------------------------------------------------------------------------

def _claim(hub: str, target: str, span: str) -> dict:
    return {"source": hub, "target": target, "relation": "grounds", "span": span, "source_file": "hub.md"}


@pytest.fixture
def eng(vault: Path, tmp_path: Path, monkeypatch) -> KGEngine:
    ticks = iter(f"2026-11-08T10:{m:02d}:00+00:00" for m in range(60))
    monkeypatch.setattr("kg_engine.server.utcnow", lambda: next(ticks))   # one verdict per minute, in order
    src = tmp_path / "hub.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    claims = [_claim("centro", t, CENTRO) for t in "abc"] + [_claim("otro", t, OTRO) for t in "xyz"]
    assert e.kg_write({"edges": claims})["dispositions"]["ACCEPTED"] == 6
    for c in claims:
        assert e.kg_ground(edge_id(c["source"], "grounds", c["target"]), "grounded", note="t")["ok"]
    return e


def _attack(e: KGEngine, hub: str, target: str = "critica", notes: "str | None" = None) -> str:
    out = e.kg_write({"edges": [{"source": hub, "target": target, "relation": "attacked_by", "span": CRITICA,
                                 "source_file": "hub.md",
                                 "notes": notes if notes is not None else f"{ATTACK_MARK}{hub}): vague"}]})
    assert out["dispositions"]["ACCEPTED"] >= 1, out
    return edge_id(hub, "attacked_by", target)


def _hubs(e: KGEngine, focus: str = "") -> "tuple[list[str], list[str]]":
    plan = e.kg_ground_plan(focus, "")
    return [h["id"] for h in plan["hubs"]], plan["attacked_hubs"]


def test_both_hubs_are_offered_before_any_attack(eng):
    assert _hubs(eng) == (["centro", "otro"], [])


def test_a_pending_attack_moves_the_plan_to_the_next_hub(eng):
    _attack(eng, "centro")
    assert _hubs(eng) == (["otro"], ["centro"])


def test_a_judged_attack_keeps_the_hub_out_until_it_gains_a_grounded_claim(eng):
    assert eng.kg_ground(_attack(eng, "centro"), "rejected", note="t")["ok"]
    assert _hubs(eng) == (["otro"], ["centro"])
    eng.kg_write({"edges": [_claim("centro", "d", CENTRO)]})
    assert _hubs(eng) == (["otro"], ["centro"])                 # unverified: nothing grounded since the attack
    assert eng.kg_ground(edge_id("centro", "grounds", "d"), "grounded", note="t")["ok"]
    assert _hubs(eng) == (["centro", "otro"], [])               # its newest claim is newer than the attack


def test_once_every_hub_is_attacked_there_is_none_left(eng):
    _attack(eng, "centro")
    _attack(eng, "otro")
    plan = eng.kg_ground_plan("", "")
    assert (plan["hubs"], plan["attacked_hubs"]) == ([], ["centro", "otro"])


def test_a_focus_attacks_again(eng):
    _attack(eng, "centro")
    assert _hubs(eng, "centro") == (["centro"], [])


def test_counter_edges_add_no_degree(eng):
    for target in ("p", "q", "r"):
        _attack(eng, "suelto", target=target)
    hubs, attacked = _hubs(eng)
    assert "suelto" not in hubs + attacked                      # three counter-edges, no claim of its own


def test_an_attacked_by_edge_without_the_mark_is_a_claim(eng):
    _attack(eng, "centro", notes="counter-edge: no hub named")
    assert _hubs(eng) == (["centro", "otro"], [])


@pytest.mark.parametrize("state", sorted(NON_LIVE_STATE_VALUES))
def test_a_dead_claim_does_not_count(eng, state):
    assert eng.kg_ground(edge_id("centro", "grounds", "a"), state, note="t")["ok"]
    assert _hubs(eng) == (["otro"], [])                         # centro is down to two live claims


# ---- the texts that wire it together -----------------------------------------------------------------

def _json_after(text: str, heading: str) -> dict:
    return json.loads(text.split(heading, 1)[1].split("```json", 1)[1].split("```", 1)[0])


def test_the_adversarial_examples_carry_the_mark_and_read_victim_first():
    edge = _json_after(ADVERSARIAL, "## Output A")["edges"][0]
    assert edge["relation"] == "attacked_by" and attacked_hub(edge["notes"]) == edge["source"]
    worked = _json_after(ADVERSARIAL, "## Worked example")["edges"][0]
    assert (worked["relation"], worked["source"], worked["target"]) == ("confounded_by", "betweenness",
                                                                        "generality-confound")
    assert attacked_hub(worked["notes"]) == "betweenness"


def test_the_worked_example_fails_the_refuted_claim_not_its_own_counter_edge():
    worked = ADVERSARIAL.split("## Worked example", 1)[1]
    failed = re.search(r'kg_ground\(target_id="([^"]+)",\s*verdict="failed"', worked).group(1)
    counter = _json_after(ADVERSARIAL, "## Worked example")["edges"][0]
    assert failed != edge_id(counter["source"], counter["relation"], counter["target"])
    assert "**Never ground your own counter-edge:**" in ADVERSARIAL


def test_the_command_and_the_contract_ask_for_the_mark():
    mark = f"{ATTACK_MARK}<hub-id>)"
    assert mark in CMD and mark in ADVERSARIAL
    assert "attacked_hubs" in CMD
    tools = ADVERSARIAL.split("---", 2)[1]
    assert "query_graph" not in tools
