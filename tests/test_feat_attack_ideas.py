"""0.25.0: a source found against a `[diverge]` idea leads to an attack, and a refutation is confirmed by a second
grounder before the idea is marked failed.

`/burgess:kg-sources find` searches for and against every idea, and its scouts record each proposal's stance. On
2026-11-23 one proposed a peer-reviewed paper that `refutes` an idea of the field project (c2e). Registering it
would have led nowhere:
- the source would have woken the idea to be grounded on it;
- the grounder may not refute an idea;
- the adversarial grounder attacks only hubs, and an idea never is one.
Now the source is recorded `found_against`, the plan lists the idea in `pin_attacks` for the adversarial grounder,
and a `failed` it gives an idea is held for a second grounder, because a refutation is permanent.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.model import EpistemicState, Node, Provenance, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
ADVERSARIAL = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
SCOUT = (REPO / "agents" / "scout.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
SOURCES_CMD = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

PIN = "idea-alerta-c2e"
PIN_BODY = ("Vigilar la autocorrelación y la varianza crecientes de las métricas del proyecto avisa de un cambio de "
            "régimen antes de que ocurra.\n\n[diverge] pinned candidate=c2e brief=alerta")
SPAN = ("rising autocorrelation and variance gave false alarms in most of the systems we tested and missed most real "
        "transitions")
COUNTER = "early-warnings-misfire"


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text("## Notas\n\nLa entropía fija la flecha del tiempo.\n", encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label="Señales tempranas en las métricas...", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body=PIN_BODY)], message="pin")
    assert e.kg_record_unsupported(PIN, "node", "no source states it")["ok"]
    return e, tmp_path


def _page(tmp_path, name, title, paragraphs):
    f = tmp_path / f"{name}.html"
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    f.write_bytes(f"<html><head><title>{title}</title></head><body><main>{body}</main></body></html>".encode("utf-8"))
    return f


def _against_page(tmp_path, name="limits", extra=""):
    return _page(tmp_path, name, "Limits of early warnings",
                 ["We studied early warning indicators" + extra + ".", f"In our tests, {SPAN}."])


def _scout_proposed(e, title="Limits of early warnings", stance="refutes"):
    assert e._log_source_search([
        {"type": "search", "kind": "node", "item": PIN, "stance": "against",
         "query": "early warning indicators false alarms autocorrelation variance"},
        {"type": "proposed", "kind": "node", "item": PIN,
         "candidates": [{"url": "https://example.org/limits", "title": title, "doi": "", "level": 1,
                         "stance": stance}], "note": ""}]) is None


def _attack(e, source_name):
    out = e.kg_write({"nodes": [{"id": COUNTER, "label": "Early-warning indicators misfire", "node_type": "claim"}],
                      "edges": [{"source": PIN, "target": COUNTER, "relation": "attacked_by", "span": SPAN,
                                 "source_file": source_name,
                                 "notes": f"counter-edge (adversarial pass, hub {PIN})"}]})
    assert out.get("ok", True), out
    return edge_id(PIN, "attacked_by", COUNTER)


def _plan_items(e):
    plan = e.kg_ground_plan()
    return plan, [i for b in plan["batches"] for i in b]


def test_a_refutes_proposal_records_the_source_against_the_idea(eng):
    e, tmp = eng
    _scout_proposed(e)
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary")
    assert out["found_against"] == [PIN] and "found_for" not in out
    assert out["to_attack"] == [PIN] and out["comes_back"] == []          # attacked, not woken to be grounded


def test_named_items_win_over_the_ledger_and_cannot_be_both(eng):
    e, tmp = eng
    _scout_proposed(e)
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary", for_items=PIN)
    assert out["found_for"] == [PIN] and "found_against" not in out
    both = e.kg_source_add(path=str(_against_page(tmp, "two", " twice")), level=1, role="primary",
                           for_items=PIN, against_items=PIN)
    assert both["ok"] is False and both["error"] == "item-for-and-against"


def test_the_plan_lists_the_idea_to_attack_until_it_is_attacked(eng):
    e, tmp = eng
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary", against_items=PIN)
    plan, items = _plan_items(e)
    assert plan["pin_attacks"] == [{"id": PIN, "label": "Señales tempranas en las métricas...",
                                    "sources": [out["name"]]}]
    assert plan["queue"]["pin_attacks"] == 1 and items == []
    assert e.kg_record_attack(PIN, "the paper limits the indicators; does it hold for project metrics?")["ok"]
    assert e.kg_ground_plan()["pin_attacks"] == []
    e.kg_source_add(path=str(_against_page(tmp, "newer", " again")), level=1, role="primary", against_items=PIN)
    assert [a["id"] for a in e.kg_ground_plan()["pin_attacks"]] == [PIN]  # a newer source: a new attack


def test_an_unusable_source_attacks_nothing(eng):
    e, tmp = eng
    out = e.kg_source_add(path=str(_against_page(tmp)), level=5, role="primary", against_items=PIN)
    assert out["found_against"] == [PIN] and "to_attack" not in out
    assert e.kg_ground_plan()["pin_attacks"] == []


def test_the_attacker_sees_the_passages_against(eng):
    e, tmp = eng
    _scout_proposed(e)
    e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary")
    ctx = e.kg_ground_item(PIN, "node")["against_context"]
    assert {"false", "alarms", "autocorrelation", "variance"} <= set(ctx["sections"][0]["matched"])
    assert SPAN in ctx["sections"][0]["excerpt"]


def test_a_refutation_of_an_idea_is_held_then_confirmed(eng):
    e, tmp = eng
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary", against_items=PIN)
    eid = _attack(e, out["name"])
    held = e.kg_ground(PIN, "failed", kind="node", refuted_by=eid, note="the indicators misfire")
    assert held["ok"] and held["held"] and held["needs_confirmation"] and held["refuted_by"] == eid
    assert e.canon.read_node(PIN).epistemic_state == EpistemicState.UNVERIFIED
    plan, items = _plan_items(e)
    assert {"id": PIN, "kind": "node", "confirm": True} in items and plan["pin_attacks"] == []
    view = e.kg_ground_item(PIN, "node")["confirm"]
    assert view["verdict"] == "failed" and view["refuted_by"] == eid and SPAN in view["context"]["excerpt"]
    assert "note" not in view                                             # the attacker's note is not shown
    done = e.kg_ground(PIN, "failed", kind="node", refuted_by=eid, note="the passage shows the mechanism failing")
    assert done["ok"] and done["to"] == "failed" and done["confirmed"] is True
    body = e.canon.read_node(PIN).body
    assert f"refuted by: {eid}" in body and "confirmed by a second grounder (0.25.0)" in body
    plan, items = _plan_items(e)
    assert plan["queue"]["confirm"] == 0 and plan["queue"]["unsupported_waiting"] == 0
    assert all(i["id"] != PIN for i in items)


def test_declining_keeps_the_idea_waiting(eng):
    e, tmp = eng
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary", against_items=PIN)
    eid = _attack(e, out["name"])
    assert e.kg_ground(PIN, "failed", kind="node", refuted_by=eid)["held"]
    assert e.kg_record_unsupported(PIN, "node", "the paper limits the indicators; it does not refute the idea")["ok"]
    plan, items = _plan_items(e)
    assert plan["queue"]["confirm"] == 0 and plan["queue"]["unsupported_waiting"] == 1
    assert plan["pin_attacks"] == []                                      # the held refutation was its attack
    assert e.canon.read_node(PIN).epistemic_state == EpistemicState.UNVERIFIED


def test_a_grounded_idea_can_be_attacked_too(eng):
    e, tmp = eng
    notes_span = "La entropía fija la flecha del tiempo."
    assert e.kg_ground(PIN, "grounded", kind="node", support_span=notes_span)["ok"]   # a weak grounding, for the test
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary", against_items=PIN)
    assert [a["id"] for a in e.kg_ground_plan()["pin_attacks"]] == [PIN]
    eid = _attack(e, out["name"])
    assert e.kg_ground(PIN, "failed", kind="node", refuted_by=eid)["held"]
    plan, items = _plan_items(e)
    assert {"id": PIN, "kind": "node", "confirm": True} in items           # queued although it is grounded
    assert e.kg_ground(PIN, "grounded", kind="node", note="the paper limits it; it still holds")["ok"]
    assert e.kg_ground_plan()["queue"]["confirm"] == 0                      # grounding it again declined the hold


def test_a_failed_on_a_node_that_is_no_pin_is_not_held(eng):
    e, tmp = eng
    out = e.kg_source_add(path=str(_against_page(tmp)), level=1, role="primary")
    e.canon.write_nodes([Node(id="claim-x", label="Indicators warn of transitions", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body="Indicators warn of transitions.")],
                        message="claim")
    w = e.kg_write({"nodes": [{"id": COUNTER, "label": "Early-warning indicators misfire", "node_type": "claim"}],
                    "edges": [{"source": "claim-x", "target": COUNTER, "relation": "attacked_by", "span": SPAN,
                               "source_file": out["name"], "notes": "counter-edge (adversarial pass, hub claim-x)"}]})
    assert w.get("ok", True), w
    done = e.kg_ground("claim-x", "failed", kind="node", refuted_by=edge_id("claim-x", "attacked_by", COUNTER))
    assert done["ok"] and done["to"] == "failed" and "held" not in done


def test_the_texts_state_the_rules():
    adversarial = _flat(ADVERSARIAL)
    assert "## Attacking an idea (0.25.0)" in ADVERSARIAL
    assert "**What refutes an idea.** A passage refutes it only when, in its own context, it shows the idea's own mechanism failing for the idea's purpose, or states the contrary of what the idea claims." in adversarial
    assert "The engine HOLDS a refutation of an idea for a second grounder" in adversarial
    grounder = _flat(GROUNDER)
    assert "**A `confirm` whose `verdict` is `failed` (0.25.0)**" in grounder
    assert "This is the one `failed` you ever give an idea, and only to confirm another grounder's refutation." in grounder
    assert "Since 0.25.0 `refutes` sends the item to be attacked once the user registers the source" in _flat(SCOUT)
    cmd = _flat(GROUND_CMD)
    assert "and the **ideas to attack**, its `pin_attacks` (0.25.0)" in cmd
    assert "**A refuted idea is confirmed in a later wave (0.25.0).**" in cmd
    assert "When the result has `to_attack` (0.25.0)" in _flat(SOURCES_CMD)
    tools = _flat(TOOLS)
    assert "**A refutation of a pin is held (0.25.0, `KGEngine._hold_refutation`).**" in tools
    assert "- **`pin_attacks` (0.25.0)**" in tools
    assert "- `against_context` (0.25.0) —" in tools
