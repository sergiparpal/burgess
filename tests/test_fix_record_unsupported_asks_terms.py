"""0.28.2: an item a registered source was found for is recorded unsupported only after the grounder has asked once
in the source's language.

0.24.6 let a grounder ask for passages with its own words (`kg_ground_item(..., terms=…)`) when the item and a source
are in different languages and nothing in its excerpts bears on the item. The contract said it *may*. In a run built
for it (2026-11-26, Windows, Claude Code 2.1.332, Burgess 0.28.1, test project `prueba-e2e-2`), a Spanish pin had an
English test note found for it. The note's three sections that shared the scout's search words said nothing of the
pin, and its fourth section stated it in other words. The grounder saw exactly those three sections, and recorded the
pin unsupported without asking, twice: once in a normal pass and once with the pin as the focus. So a passage the
request exists to find stayed unseen, and the pin would have waited for a new source forever.

Now `kg_record_unsupported` answers `terms-not-asked` for an item a usable registered source was found for
(`found_for`) while no request of the grounder's is on record against the item and the sources as they are. It does
not ask it of an item with a held verdict open: its second grounder declines it by recording it, and may not search.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.canon import UNSUPPORTED_PINS
from kg_engine.model import EpistemicState, Node, Provenance, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"

PIN = "idea-cita-c1c"
PIN_BODY = ("Registrar el rol retórico del bloque que contiene la cita y prohibir que ciertos roles respalden aristas "
            "afirmativas sin una revisión explícita.\n\n[diverge] pinned candidate=c1c brief=cita")
STATES = ("a tool that copies quoted lines into a knowledge graph should store what kind of enclosing part held "
          "each line, and hold every edge drawn from those kinds of part for a review")
COUNTER = "role-labels-misfire"
REFUTES = "labels of the enclosing part were wrong for most of the quotes we checked, so the review held the wrong edges"


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
    e.canon.write_nodes([Node(id=PIN, label="Registrar el rol retórico del bloque...", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body=PIN_BODY)], message="pin")
    return e, tmp_path


def _page(tmp_path, name, paragraphs, title="Quoted lines"):
    f = tmp_path / f"{name}.html"
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    f.write_bytes(f"<html><head><title>{title}</title></head><body><main>{body}</main></body></html>".encode("utf-8"))
    return f


def _register(e, tmp_path, name="note", paragraphs=None, level=4, **kw):
    out = e.kg_source_add(path=str(_page(tmp_path, name, paragraphs or [f"In short, {STATES}."])), level=level,
                          role="primary", **kw)
    assert out["ok"], out
    return out


def _ledger(e) -> bytes:
    path = e.canon.root / UNSUPPORTED_PINS
    return path.read_bytes() if path.exists() else b""


def _plan_items(e):
    plan = e.kg_ground_plan()
    return plan, [i for b in plan["batches"] for i in b]


def test_an_item_a_source_was_found_for_is_not_recorded_before_the_request(eng):
    e, tmp = eng
    name = _register(e, tmp, for_items=PIN)["name"]
    before = _ledger(e)
    out = e.kg_record_unsupported(PIN, "node", "no section of the note states it")
    assert out["ok"] is False and out["error"] == "terms-not-asked" and out["item"] == PIN
    assert out["files"] == [name] and out["max_terms"] == 8
    assert "kg_ground_item(target_id, kind, terms=" in out["hint"] and "held for a second grounder" in out["hint"]
    assert _ledger(e) == before                                      # nothing written
    plan, items = _plan_items(e)
    assert {"id": PIN, "kind": "node"} in [{k: i[k] for k in ("id", "kind")} for i in items]   # still queued


def test_after_the_request_it_is_recorded_and_waits(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)
    asked = e.kg_ground_item(PIN, "node", terms="enclosing part quoted line review")
    assert asked["requested_context"]["sections"]
    out = e.kg_record_unsupported(PIN, "node", "the requested sections hold the passage, but it is a narrower claim")
    assert out["ok"], out
    plan, items = _plan_items(e)
    assert plan["queue"]["unsupported_waiting"] == 1 and PIN not in [i["id"] for i in items]


def test_a_new_source_is_a_new_look_with_a_request_of_its_own(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)
    e.kg_ground_item(PIN, "node", terms="enclosing part quoted line review")
    _register(e, tmp, name="other", paragraphs=["Citation counts treat every citation alike."])
    out = e.kg_record_unsupported(PIN, "node", "nothing states it")
    assert out["ok"] is False and out["error"] == "terms-not-asked"
    e.kg_ground_item(PIN, "node", terms="enclosing part quoted line review")
    assert e.kg_record_unsupported(PIN, "node", "nothing states it")["ok"]


def test_an_item_no_usable_source_was_found_for_is_recorded_as_before(eng):
    e, tmp = eng
    assert e.kg_record_unsupported(PIN, "node", "no source states it")["ok"]          # no source at all
    _register(e, tmp, name="unrelated", paragraphs=["Citation counts treat every citation alike."])
    assert e.kg_record_unsupported(PIN, "node", "the new source is not about it")["ok"]   # not found for it
    _register(e, tmp, name="unfiltered", level=5, for_items=PIN)                         # found for it, not usable
    assert e.kg_record_unsupported(PIN, "node", "the only source found for it is not usable")["ok"]


def test_a_second_grounder_declines_a_held_grounding_without_searching(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)
    e.kg_ground_item(PIN, "node", terms="enclosing part quoted line review")
    assert e.kg_ground(PIN, "grounded", kind="node", support_span=STATES)["held"]
    _register(e, tmp, name="later", paragraphs=["Citation counts treat every citation alike."])   # the request is old
    assert e.kg_ground_item(PIN, "node", terms="quoted line")["error"] == "terms-not-allowed"
    out = e.kg_record_unsupported(PIN, "node", "the passage states a narrower claim than the idea")
    assert out["ok"], out
    plan, _items = _plan_items(e)
    assert plan["queue"]["confirm"] == 0


def test_a_second_grounder_declines_a_held_refutation_without_a_request(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)                                 # usable, found for it, never searched
    against = _register(e, tmp, name="limits", level=1, against_items=PIN,
                        paragraphs=["We checked labelled quotes.", f"In our checks, {REFUTES}."])
    out = e.kg_write({"nodes": [{"id": COUNTER, "label": "Role labels misfire", "node_type": "claim"}],
                      "edges": [{"source": PIN, "target": COUNTER, "relation": "attacked_by", "span": REFUTES,
                                 "source_file": against["name"], "notes": f"counter-edge (adversarial pass, hub {PIN})"}]})
    assert out.get("ok", True), out
    eid = edge_id(PIN, "attacked_by", COUNTER)
    assert e.kg_ground(PIN, "failed", kind="node", refuted_by=eid)["held"]
    done = e.kg_record_unsupported(PIN, "node", "the paper limits the labels; it does not refute the idea")
    assert done["ok"], done
    assert e.canon.read_node(PIN).epistemic_state == EpistemicState.UNVERIFIED


def test_the_contract_the_reference_and_the_tool_say_so():
    grounder = _flat((REPO / "agents" / "grounder.md").read_text(encoding="utf-8"))
    assert ("call `kg_ground_item(target_id, kind, terms=\"…\")` once, before you record the item unsupported"
            in grounder)
    assert "`kg_record_unsupported` answers `terms-not-asked` until you have asked (0.28.2)" in grounder
    assert "**When a registered source was found for the pin, ask first** in the source's language" in grounder
    assert "you may call `kg_ground_item" not in grounder
    tools = _flat((REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8"))
    assert "`terms-not-asked` (0.28.2), with `files` and a `hint`" in tools
    assert "Since 0.28.2 the request is due before an item a usable source was found for is recorded unsupported" in tools
    server = _flat((REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8"))
    assert "refused with `terms-not-asked` until you have asked once in the source's language" in server
    architecture = _flat((REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8"))
    assert "`kg_record_unsupported` answers `terms-not-asked`" in architecture
