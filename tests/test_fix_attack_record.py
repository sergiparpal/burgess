"""0.10.0: an adversarial attack that writes no counter-edge is recorded, so the plan stops offering its hub until
the hub gains a newer grounded claim.

Field report on 0.9.0 (the Windows corpus, 416 nodes). Since 0.8.0 the plan remembers an attack by the mark on
each counter-edge, and leaves a hub out while no claim of it has been grounded since its newest mark. An attack
that finds no span setting itself against the hub writes no counter-edge, so it leaves no mark: 0.8.0 accepted
that as a rare case. The 0.9.0 leads made it common. The grounders had rejected both counter-edges on
`escribir-codigo-parte-pequena`, and one of them with a lead: its span, the source's own support for the hub.
`/kg-build --leads` wrote that lead and the next pass grounded it, which reopened the hub. The re-attack searched
eight documents and found nothing, so it left no mark either, and the plan would have offered the hub to an
attack on every later pass.

Now the adversarial grounder records such an attack with `kg_record_attack(hub_id, question, reason)`: one line
in a ledger beside the canon, which the plan counts like a counter-edge judged at the time of the record. The
record sets no state, and a lost or damaged ledger only brings back the repeat.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.canon import HUB_ATTACKS
from kg_engine.groundplan import (ATTACK_MARK, ATTACK_REASONS, MAX_QUESTION_CHARS, attack_record,
                                  attack_records)
from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
ADVERSARIAL = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")
DOC = ("## H\nEl centro une a, b, c y d.\n\nEl otro une x, y y z.\n\n"
       "La crítica ataca al centro por vago.\n")
CENTRO, OTRO, CRITICA = "El centro une a, b, c y d", "El otro une x, y y z", "La crítica ataca al centro por vago"
QUESTION = "¿Qué parte de la semana medida por telemetría va a escribir código?"


def _claim(hub: str, target: str, span: str) -> dict:
    return {"source": hub, "target": target, "relation": "grounds", "span": span, "source_file": "hub.md"}


@pytest.fixture
def eng(vault: Path, tmp_path: Path, monkeypatch) -> KGEngine:
    ticks = iter(f"2026-11-08T10:{m:02d}:00+00:00" for m in range(60))
    monkeypatch.setattr("kg_engine.server.utcnow", lambda: next(ticks))   # one verdict or record per minute
    src = tmp_path / "hub.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    claims = [_claim("centro", t, CENTRO) for t in "abc"] + [_claim("otro", t, OTRO) for t in "xyz"]
    assert e.kg_write({"edges": claims})["dispositions"]["ACCEPTED"] == 6
    for c in claims:
        assert e.kg_ground(edge_id(c["source"], "grounds", c["target"]), "grounded", note="t")["ok"]
    return e


def _hubs(e: KGEngine, focus: str = "") -> "tuple[list[str], list[str]]":
    plan = e.kg_ground_plan(focus, "")
    return [h["id"] for h in plan["hubs"]], plan["attacked_hubs"]


def _record(e: KGEngine, hub: str = "centro", reason: str = "no-span") -> dict:
    out = e.kg_record_attack(hub, QUESTION, reason)
    assert out["ok"], out
    return out


def _ledger(e: KGEngine) -> Path:
    return e.canon.root / HUB_ATTACKS


# ---- the plan ----------------------------------------------------------------------------------------

def test_a_recorded_attack_moves_the_plan_to_the_next_hub(eng):
    assert _hubs(eng) == (["centro", "otro"], [])
    _record(eng)
    assert _hubs(eng) == (["otro"], ["centro"])


def test_a_record_keeps_the_hub_out_until_it_gains_a_grounded_claim(eng):
    _record(eng)
    eng.kg_write({"edges": [_claim("centro", "d", CENTRO)]})
    assert _hubs(eng) == (["otro"], ["centro"])                 # unverified: nothing grounded since the attack
    assert eng.kg_ground(edge_id("centro", "grounds", "d"), "grounded", note="t")["ok"]
    assert _hubs(eng) == (["centro", "otro"], [])               # its newest claim is newer than the record
    _record(eng)                                                # the next attack finds nothing again
    assert _hubs(eng) == (["otro"], ["centro"])


def test_the_field_case(eng):
    # the hub's counter-edge was rejected, a claim grounded after that reopened it, and the re-attack wrote nothing
    counter = {"source": "centro", "target": "critica", "relation": "attacked_by", "span": CRITICA,
               "source_file": "hub.md", "notes": f"{ATTACK_MARK}centro): vague"}
    assert eng.kg_write({"edges": [counter]})["dispositions"]["ACCEPTED"] >= 1
    assert eng.kg_ground(edge_id("centro", "attacked_by", "critica"), "rejected", note="t")["ok"]
    assert _hubs(eng) == (["otro"], ["centro"])
    eng.kg_write({"edges": [_claim("centro", "d", CENTRO)]})
    assert eng.kg_ground(edge_id("centro", "grounds", "d"), "grounded", note="t")["ok"]
    assert _hubs(eng) == (["centro", "otro"], [])               # 0.9.0 stopped here, and offered it every pass
    _record(eng)
    assert _hubs(eng) == (["otro"], ["centro"])


def test_a_focus_attacks_a_recorded_hub_again(eng):
    _record(eng)
    assert _hubs(eng, "centro") == (["centro"], [])


def test_a_record_on_a_node_that_is_no_hub_yet_is_kept_for_later(eng):
    # the command also attacks advisory nodes outside `hubs`; a record on one counts once it qualifies, unless a
    # claim grounded after the record reopens it
    eng.kg_write({"edges": [_claim("tercero", t, CENTRO) for t in "pq"]})
    for t in "pq":
        assert eng.kg_ground(edge_id("tercero", "grounds", t), "grounded", note="t")["ok"]
    _record(eng, "tercero")
    eng.kg_write({"edges": [_claim("tercero", "r", CENTRO)]})
    assert _hubs(eng) == (["centro", "otro"], ["tercero"])      # three live claims, none grounded since
    assert eng.kg_ground(edge_id("tercero", "grounds", "r"), "grounded", note="t")["ok"]
    assert "tercero" in _hubs(eng)[0]                           # a claim grounded after the record


# ---- the record --------------------------------------------------------------------------------------

def test_the_record_is_one_ledger_line(eng):
    out = _record(eng, reason=" No-Span ")
    assert out == {"ok": True, "hub": "centro", "at": out["at"], "reason": "no-span"}
    lines = _ledger(eng).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"hub": "centro", "at": out["at"], "reason": "no-span", "question": QUESTION}]


def test_the_record_sets_no_state(eng):
    notes = {p.name: p.read_bytes() for p in eng.canon.note_paths()}
    before = eng.kg_metrics()
    _record(eng)
    _record(eng, "otro", "vague")
    assert {p.name: p.read_bytes() for p in eng.canon.note_paths()} == notes
    assert eng.kg_metrics() == before


@pytest.mark.parametrize("hub, question, reason, error", [
    ("", QUESTION, "no-span", "name the hub"),
    ("   ", QUESTION, "no-span", "name the hub"),
    ("nadie", QUESTION, "no-span", "node not found"),
    ("centro", QUESTION, "refuted", "invalid reason"),
    ("centro", "  \n ", "no-span", "falsifying question"),
    ("centro", "x" * (MAX_QUESTION_CHARS + 1), "no-span", "over"),
])
def test_a_bad_record_is_refused_and_writes_nothing(eng, hub, question, reason, error):
    out = eng.kg_record_attack(hub, question, reason)
    assert not out["ok"] and error in out["error"], out
    assert not _ledger(eng).exists()


def test_the_reasons_are_the_contracts_decline_tags():
    assert set(ATTACK_REASONS) == {"no-span", "vague"}
    output_b = ADVERSARIAL.split("## Output B", 1)[1].split("\n## ", 1)[0]
    assert "(`vague`" in output_b and "`no-span`" in output_b


def test_a_lost_or_damaged_ledger_fails_open(eng):
    _record(eng)
    assert _hubs(eng) == (["otro"], ["centro"])
    path = _ledger(eng)
    good = path.read_bytes()
    path.write_bytes(b'not json\n[1, 2]\n{"hub": 3, "at": "x"}\n\xff\xfe\n' + good + b'{"hub": "otro", "at')
    assert _hubs(eng) == (["otro"], ["centro"])                 # the good record still counts; the rest is skipped
    path.unlink()
    assert _hubs(eng) == (["centro", "otro"], [])               # lost: back to offering it, as before 0.10.0
    path.mkdir()                                                # unreadable
    assert _hubs(eng) == (["centro", "otro"], [])


def test_the_plan_never_creates_the_ledger(eng):
    eng.kg_ground_plan("", "")
    assert not _ledger(eng).exists()


def test_the_ledger_stays_out_of_git(eng):
    _record(eng)
    exclude = (eng.canon.root / ".git" / "info" / "exclude").read_text(encoding="utf-8").split()
    assert HUB_ATTACKS in exclude
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=eng.canon.root,
                            capture_output=True, text=True, check=True).stdout
    assert HUB_ATTACKS not in status


def test_attack_records_reads_what_attack_record_writes():
    lines = [attack_record("a", "2026-11-08T10:00:00+00:00", "no-span", "q1"),
             "", "{}", '{"hub": "", "at": "t"}',
             attack_record("b", "2026-11-08T10:01:00+00:00", "vague", "q2"),
             attack_record("a", "2026-11-08T10:02:00+00:00", "no-span", "q3")]
    assert attack_records(lines) == {"a": ["2026-11-08T10:00:00+00:00", "2026-11-08T10:02:00+00:00"],
                                     "b": ["2026-11-08T10:01:00+00:00"]}


# ---- the texts that wire it together -----------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_adversarial_contract_records_an_attack_with_no_counter_edge():
    tools = ADVERSARIAL.split("---", 2)[1]
    assert "mcp__plugin_burgess_burgess__kg_record_attack" in tools
    flat = _flat(ADVERSARIAL)
    output_b = _flat(ADVERSARIAL.split("## Output B", 1)[1].split("\n## ", 1)[0])
    assert "kg_record_attack(hub_id=" in output_b
    assert "carries no mark" not in flat                        # the 0.8.0 trade-off this release removes
    report = _flat(ADVERSARIAL.split("## Report back", 1)[1])
    assert "kg_record_attack" in report


def test_the_command_asks_for_the_record():
    template = _flat(CMD.split('subagent_type: "kg-adversarial-grounder"', 1)[1].split('"""\n)', 1)[0])
    assert "kg_record_attack(" in template
    stage2 = _flat(CMD.split("## Stage 2", 1)[1].split("## Stage 3", 1)[0])
    assert "kg_record_attack" in stage2
