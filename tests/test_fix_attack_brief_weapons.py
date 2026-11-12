"""0.13.5 — the attack brief names the weapons the adversarial grounder's contract names.

`/burgess:kg-ground`'s brief told the adversarial grounder "Write attacked_by counter-edges (relation:
attacked_by)". Its contract says the pack vocabulary names the weapon: `attacked_by` (a more specific claim
defeats a vaguer one), `confounded_by` (a confound biases a figure), `collapses_into` (the claim reduces to a
known failure). In the field on 2026-11-12 (0.13.3 and 0.13.4) the grounder twice attacked `radar-meta` with a
`confounded_by` counter-edge, a bias in RADAR's figures. Each time it explained why it had not followed the brief,
and each edge was grounded. The same day an `attacked_by` edge of that shape had been rejected as
`wrong-relation` and re-written as `confounded_by`.

Since 0.13.5 the brief, the command's account of the attack stage and its report line, the agent's description
and opening, ARCHITECTURE.md and the skill all name the three weapons. The mark that records an attack lives in
the counter-edge's notes, so it never depended on the relation; the engine tests below pin that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kg_engine.groundplan import ATTACK_MARK
from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
AGENT = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _weapons() -> list[str]:
    m = re.search(r"The pack edge vocabulary names the weapon: (.*?)\.\s", _flat(AGENT))
    assert m, "the contract's weapon sentence moved"
    return re.findall(r"`([a-z_]+)`", m.group(1))


def _brief() -> str:
    return _flat(CMD.split('subagent_type: "kg-adversarial-grounder"', 1)[1].split('"""', 2)[1])


def test_the_contract_names_three_weapons_and_the_pack_declares_them():
    weapons = _weapons()
    assert weapons == ["attacked_by", "confounded_by", "collapses_into"]
    pack = (REPO / "pack" / "pack.yaml").read_text(encoding="utf-8")
    for w in weapons:
        assert re.search(rf"^\s+- {w}\b", pack, re.M), f"{w} is not a declared edge type"


def test_the_brief_names_the_weapons_its_contract_names():
    brief = _brief()
    assert "relation: attacked_by" not in brief and "Write attacked_by counter-edges" not in brief
    assert ("each typed by the weapon its span states (attacked_by, confounded_by or collapses_into, as your "
            "contract defines them)") in brief
    # what never changed: the span rule and the mark the plan reads
    assert "VERBATIM span" in brief and "`counter-edge (adversarial pass, hub <hub-id>)`" in brief


def test_the_command_and_the_agent_describe_the_same_weapons():
    stage = _flat(CMD.split("## Stage 2", 1)[1].split("```", 1)[0])
    head = re.match(r"^---\n(.*?)\n---\n", AGENT, re.S).group(1)
    opening = _flat(AGENT.split("---", 2)[2])[:600]
    for text in (stage, head, opening):
        for w in _weapons():
            assert w in text
    assert "→ C counter-edges, R recorded with none" in CMD
    assert "attacked_by counter-edges" not in CMD
    for doc in ("docs/ARCHITECTURE.md", "skills/burgess/SKILL.md"):
        flat = _flat((REPO / doc).read_text(encoding="utf-8"))
        assert "`attacked_by` edges +" not in flat and "via `attacked_by` edges" not in flat, doc


# ---- the engine: the mark, not the relation, records the attack ----------------------------------------

DOC = ("## H\nEl centro une a, b, c y d.\n\nLa crítica ataca al centro por vago.\n")
CENTRO, CRITICA = "El centro une a, b, c y d", "La crítica ataca al centro por vago"


@pytest.fixture
def eng(vault: Path, tmp_path: Path, monkeypatch) -> KGEngine:
    ticks = iter(f"2026-11-12T10:{m:02d}:00+00:00" for m in range(60))
    monkeypatch.setattr("kg_engine.server.utcnow", lambda: next(ticks))
    src = tmp_path / "hub.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    claims = [{"source": "centro", "target": t, "relation": "grounds", "span": CENTRO, "source_file": "hub.md"}
              for t in "abc"]
    assert e.kg_write({"edges": claims})["dispositions"]["ACCEPTED"] == 3
    for c in claims:
        assert e.kg_ground(edge_id("centro", "grounds", c["target"]), "grounded", note="t")["ok"]
    return e


@pytest.mark.parametrize("weapon", ["attacked_by", "confounded_by", "collapses_into"])
def test_a_counter_edge_of_any_weapon_marks_its_hub(eng, weapon):
    assert [h["id"] for h in eng.kg_ground_plan("", "")["hubs"]] == ["centro"]
    out = eng.kg_write({"edges": [{"source": "centro", "target": "critica", "relation": weapon, "span": CRITICA,
                                   "source_file": "hub.md", "notes": f"{ATTACK_MARK}centro): t"}]})
    assert out["dispositions"]["ACCEPTED"] >= 1, out
    plan = eng.kg_ground_plan("", "")
    assert (plan["hubs"], plan["attacked_hubs"]) == ([], ["centro"])
    # grounding the counter-edge keeps the hub attacked: it is the attack's mark, not a new claim of the hub
    assert eng.kg_ground(edge_id("centro", weapon, "critica"), "grounded", note="t")["ok"]
    plan = eng.kg_ground_plan("", "")
    assert (plan["hubs"], plan["attacked_hubs"]) == ([], ["centro"])
