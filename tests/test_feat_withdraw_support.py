"""0.24.7: a grounding can be judged again on request, and a pin found to rest on a neighbouring claim has its
support withdrawn rather than rejected.

On 2026-11-24 a grounder in the field left an idea unsupported because its best passage stated a neighbouring
claim: the same mechanism, put to another purpose. Two pins grounded earlier rested on passages their own
grounders had noted fell short of the idea. Nothing could judge them again: `--reexamine` brought back only
rejected nodes, and no verdict returned a grounded pin to the waiting pins. A pin is never rejected for want of
support. Now:
- the grounder contract says what grounds a node;
- `--reexamine` with a focus also brings the grounded promotions the focus names, with `grounded_on`;
- `kg_ground(verdict="unverified")` withdraws a pin's support: back to unverified and hypothesized, audited, the
  old support kept as withdrawn, and recorded unsupported.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.canon import GROUND_AUDIT, UNSUPPORTED_PINS
from kg_engine.model import EpistemicState, Node, Provenance
from kg_engine.reconciler import Reconciler
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

NOTES = ("## Notas\n\nCuando un agente se atasca, el sistema sube la temperatura de muestreo para salir del bucle.\n\n"
         "## Otra\n\nLa entropía fija la flecha del tiempo.\n")
SPAN = "Cuando un agente se atasca, el sistema sube la temperatura de muestreo para salir del bucle."
PIN = "idea-recocido-c1l"
PIN_BODY = ("Cuando la fábrica se atasca, recalienta la búsqueda: acepta soluciones peores y enfría al progresar."
            "\n\n[diverge] pinned candidate=c1l brief=recocido")
LACKS = "it raises the temperature when stuck, but never accepts worse solutions or cools on progress."


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text(NOTES, encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label="Recocido: recalentar al atascarse...", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body=PIN_BODY)], message="pin")
    assert e.kg_ground(PIN, "grounded", kind="node", support_span=SPAN, note="close enough")["ok"]
    return e


def _queued(plan) -> "list[dict]":
    return [i for b in plan["batches"] for i in b]


def _unsupported(e) -> "list[dict]":
    path = e.canon.root / UNSUPPORTED_PINS
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def test_reexamine_with_a_focus_brings_a_grounded_promotion_back(eng):
    plan = eng.kg_ground_plan(focus=PIN, reexamine=True)
    assert _queued(plan) == [{"id": PIN, "kind": "node", "reexamine": True}]
    assert plan["queue"]["reexamine"] == 1


def test_never_without_a_focus_nor_without_reexamine(eng):
    assert eng.kg_ground_plan(focus="", reexamine=True)["queue"]["reexamine"] == 0
    assert _queued(eng.kg_ground_plan(focus=PIN, reexamine=False)) == []


def test_its_grounder_sees_what_it_rests_on(eng):
    item = eng.kg_ground_item(PIN, "node")
    spans = item["grounded_on"]["spans"]
    assert spans[0]["span"] == SPAN and spans[0]["source_file"] == "notes.md"
    assert SPAN in spans[0]["context"]["excerpt"]
    assert "[diverge] pin's support is withdrawn (verdict unverified)" in item["grounded_on"]["rule"]
    assert "grounded_on" not in eng.kg_ground_item("cliche-none", "node")      # an unknown node: no view at all


def test_withdrawing_returns_the_pin_to_the_waiting_pins(eng):
    out = eng.kg_ground(PIN, "unverified", kind="node", note=LACKS)
    assert out["ok"] and out["withdrawn"] and out["from"] == "grounded" and out["to"] == "unverified"
    assert out["recorded_unsupported"] is True
    node = eng.canon.read_node(PIN)
    assert node.epistemic_state == EpistemicState.UNVERIFIED and node.provenance == Provenance.HYPOTHESIZED
    paras = [p.strip() for p in node.body.split("\n\n")]
    assert not any(p.startswith(("grounding span: ", "grounding source: ")) for p in paras)
    assert paras[-1] == (f"verdict (unverified): support withdrawn (0.24.7): {LACKS} It rested on «{SPAN}» "
                         f"(notes.md).")
    assert "verdict (grounded): close enough" in paras                 # the earlier note stays, as history
    plan = eng.kg_ground_plan()
    assert plan["queue"]["nodes"] == 0 and plan["queue"]["unsupported_waiting"] == 1
    assert [r["item"] for r in _unsupported(eng)] == [PIN]


def test_the_withdrawal_is_audited_and_the_reconciler_keeps_it(eng):
    recon = Reconciler(eng.canon)
    recon.scan(full_sweep=True)                                         # baseline: the pin is grounded
    assert eng.kg_ground(PIN, "unverified", kind="node", note=LACKS)["ok"]
    audit = [json.loads(x) for x in (eng.canon.root / GROUND_AUDIT).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {"key": f"node:{PIN}", "from": "grounded", "to": "unverified"}.items() <= audit[-1].items()
    recon.scan(full_sweep=True)
    assert eng.canon.read_node(PIN).epistemic_state == EpistemicState.UNVERIFIED


def test_a_withdrawn_pin_can_be_grounded_again_later(eng):
    assert eng.kg_ground(PIN, "unverified", kind="node", note=LACKS)["ok"]
    again = eng.kg_ground(PIN, "grounded", kind="node", support_span=SPAN)
    assert again["ok"] and again["to"] == "grounded" and again["provenance_upgraded_to"] == "span-present"


def test_what_cannot_be_withdrawn(eng):
    assert eng.kg_ground(PIN, "unverified", kind="node")["error"] == "withdraw-needs-note"
    assert eng.kg_ground(PIN, "unverified", kind="edge", note=LACKS)["error"] == "withdraw-node-only"
    eng.canon.write_nodes([Node(id="cliche-b-o1", label="An obvious answer", node_type="claim",
                                provenance=Provenance.HYPOTHESIZED, body="An obvious answer.\n\n[cliche] b o1")],
                          message="cliche")
    assert eng.kg_ground("cliche-b-o1", "grounded", kind="node", support_span=SPAN)["ok"]
    out = eng.kg_ground("cliche-b-o1", "unverified", kind="node", note=LACKS)
    assert out["error"] == "withdraw-not-allowed"                     # not a pin: it takes `rejected`
    assert eng.kg_ground(PIN, "unverified", kind="node", note=LACKS)["ok"]
    assert eng.kg_ground(PIN, "unverified", kind="node", note=LACKS)["error"] == "withdraw-not-allowed"   # no longer grounded
    assert eng.kg_ground("no-such-node", "unverified", kind="node", note=LACKS)["error"] == "node not found"


def test_the_texts_state_the_rule():
    grounder = _flat(GROUNDER)
    assert "### What grounds a node (0.24.7)" in GROUNDER
    assert "These are **neighbouring claims**, and none of them grounds the node:" in grounder
    assert "### A grounded node judged again (0.24.7)" in GROUNDER
    assert "Never reject a pin." in grounder
    cmd = _flat(GROUND_CMD)
    assert "A grounding is never judged again without a focus." in cmd
    assert "List every grounding judged again with `--reexamine` (0.24.7)" in cmd
    tools = _flat(TOOLS)
    assert "**Withdrawing a pin's grounding (0.24.7, `KGEngine._withdraw_support`).**" in tools
    assert "- `grounded_on` (0.24.7) —" in tools


def test_the_contract_names_no_field_item():
    """A contract example that names a pending field claim primes its verdict (0.18.1): the new rule stays neutral."""
    section = GROUNDER.split("### What grounds a node (0.24.7)")[1].split("## The edge.id format")[0]
    for name in ("c1l", "c1j", "c2c", "quorum", "Sentry", "H3", "annealing", "recocido"):
        assert name not in section
