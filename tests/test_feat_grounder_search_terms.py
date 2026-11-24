"""0.24.6: a grounder can reach a source in another language than the item, and what its own search finds is
confirmed by a second grounder.

`/burgess:kg-sources find` pairs the field's Spanish ideas with English sources. Every excerpt `kg_ground_item`
gave a grounder was chosen by the item's own words, so an English source matched a Spanish idea only through words
both languages spell alike. If its key paragraph shared fewer than two of them, the grounder never saw it, and the
idea was recorded unsupported with nobody the wiser. Now:
- the sections of a source found for the item are also ranked by the words its scout searched with
  (`search_context`), chosen before anyone judged;
- a grounder may ask once, in at most 8 words, for passages in the source's language (`terms`,
  `requested_context`), and the request is recorded;
- a grounded verdict with support given after such a request is held, and the plan queues the item last, marked
  `confirm`, for a second grounder. The span check stops an invented citation, not one picked by a search run until
  something fitted.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.canon import GROUND_AUDIT, GROUND_REQUESTS
from kg_engine.model import Node, Provenance, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

PIN = "idea-quorum-c2c"
PIN_TEXT = ("Detección de quórum: cada agente emite una señal de frustración cuando falla; la señal se acumula y se "
            "degrada, y al superar un umbral todos cambian de modo a la vez.")
SPAN = "once the signal passes a quorum threshold, the collective switch to a safe mode is triggered"
PAPER = ["We study cooperation in large teams of software workers.",
         "Each worker emits a signal on failure; " + SPAN + "."]


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text("## Notas\n\nLa entropía fija la flecha del tiempo en los sistemas cerrados.\n", encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label=PIN_TEXT[:40] + "...", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED,
                              body=PIN_TEXT + "\n\n[diverge] pinned candidate=c2c brief=quorum")], message="pin")
    assert e.kg_record_unsupported(PIN, "node", "no source states it")["ok"]
    return e, tmp_path


def _page(tmp_path, name, paragraphs):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    f = tmp_path / f"{name}.html"
    f.write_bytes(f"<html><head><title>{name}</title></head><body><main>{body}</main></body></html>".encode("utf-8"))
    return f


def _register(e, tmp_path, name="paper", paragraphs=PAPER, **kw):
    out = e.kg_source_add(path=str(_page(tmp_path, name, paragraphs)), level=4, role="primary", **kw)
    assert out["ok"], out
    return out


def _scout_searched(e, query="quorum sensing threshold collective switch agents", item=PIN):
    assert e._log_source_search([{"type": "search", "kind": "node", "item": item, "stance": "for", "query": query}]) is None


def _requests(e) -> "list[dict]":
    path = e.canon.root / GROUND_REQUESTS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _matched(ctx) -> "list[list[str]]":
    return [s["matched"] for s in (ctx or {}).get("sections", [])]


def _plan(e):
    plan = e.kg_ground_plan()
    return plan, [i for b in plan["batches"] for i in b]


def test_a_source_found_for_an_item_is_ranked_by_the_scouts_words(eng):
    e, tmp = eng
    _scout_searched(e)
    _register(e, tmp, for_items=PIN)
    item = e.kg_ground_item(PIN, "node")
    assert item["source_context"]["sections"] == []                 # the Spanish words reach nothing
    assert item["search_context"]["files"] and SPAN.split(",")[0] in item["search_context"]["sections"][0]["excerpt"]
    assert {"quorum", "threshold"} <= set(_matched(item["search_context"])[0])


def test_no_search_context_without_a_source_found_for_it_or_a_search(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)                                 # found for it, but no search on record
    assert "search_context" not in e.kg_ground_item(PIN, "node")
    _scout_searched(e)
    _register(e, tmp, name="other", paragraphs=["A quorum threshold makes the collective switch."])
    ctx = e.kg_ground_item(PIN, "node")["search_context"]
    assert ctx["files"] == [n for n in ctx["files"] if "paper" in n]   # only the source found for it


def test_the_grounder_may_ask_once_with_its_own_words(eng):
    e, tmp = eng
    _register(e, tmp)
    first = e.kg_ground_item(PIN, "node", terms="failure signal quorum threshold")["requested_context"]
    assert first["repeated"] is False and {"quorum", "threshold"} <= set(_matched(first)[0])
    again = e.kg_ground_item(PIN, "node", terms="entirely different words now")["requested_context"]
    assert again["repeated"] is True and again["terms"] == first["terms"]
    assert [r["type"] for r in _requests(e)] == ["request"]
    assert _requests(e)[0]["terms"] == ["failure", "signal", "quorum", "threshold"]


def test_too_many_or_no_words_are_refused_and_not_recorded(eng):
    e, tmp = eng
    _register(e, tmp)
    many = e.kg_ground_item(PIN, "node", terms="alpha beta gamma delta epsilon zeta theta iota kappa")
    assert many["ok"] is False and many["error"] == "terms-too-many" and many["max"] == KGEngine.GROUND_TERMS_MAX == 8
    assert e.kg_ground_item(PIN, "node", terms="the of and")["error"] == "terms-empty"
    assert _requests(e) == []


def test_a_new_source_allows_a_new_request(eng):
    e, tmp = eng
    _register(e, tmp)
    e.kg_ground_item(PIN, "node", terms="quorum threshold")
    _register(e, tmp, name="second", paragraphs=["Signals decay over time in every colony we watched."])
    out = e.kg_ground_item(PIN, "node", terms="signal decay colony")["requested_context"]
    assert out["repeated"] is False and len(_requests(e)) == 2


def test_support_found_after_a_request_is_held(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)
    e.kg_ground_item(PIN, "node", terms="failure signal quorum threshold")
    before = (e.canon.root / GROUND_AUDIT).read_bytes() if (e.canon.root / GROUND_AUDIT).exists() else b""
    out = e.kg_ground(PIN, "grounded", kind="node", support_span=SPAN, note="states the mechanism")
    assert out["ok"] and out["held"] and out["needs_confirmation"]
    assert out["terms"] == ["failure", "signal", "quorum", "threshold"]
    assert e.canon.read_node(PIN).epistemic_state.value == "unverified"
    after = (e.canon.root / GROUND_AUDIT).read_bytes() if (e.canon.root / GROUND_AUDIT).exists() else b""
    assert after == before                                           # no verdict was recorded
    hold = [r for r in _requests(e) if r["type"] == "hold"][0]
    assert hold["span"] == SPAN and hold["note"] == "states the mechanism"
    plan, items = _plan(e)
    assert plan["queue"]["confirm"] == 1 and plan["queue"]["nodes"] == 0
    assert items == [{"id": PIN, "kind": "node", "confirm": True}]


def test_support_without_a_request_is_not_held(eng):
    e, tmp = eng
    _scout_searched(e)
    _register(e, tmp, for_items=PIN)                                 # its passage shows in search_context
    out = e.kg_ground(PIN, "grounded", kind="node", support_span=SPAN)
    assert out["ok"] and out.get("to") == "grounded" and "held" not in out
    assert _requests(e) == []


def test_the_second_grounder_confirms_it(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)
    e.kg_ground_item(PIN, "node", terms="failure signal quorum threshold")
    assert e.kg_ground(PIN, "grounded", kind="node", support_span=SPAN)["held"]
    view = e.kg_ground_item(PIN, "node")
    assert view["confirm"]["span"] == SPAN and view["confirm"]["terms"] == ["failure", "signal", "quorum", "threshold"]
    assert SPAN in view["confirm"]["context"]["excerpt"] and "note" not in view["confirm"]   # the first note is not shown
    assert e.kg_ground_item(PIN, "node", terms="quorum")["error"] == "terms-not-allowed"
    out = e.kg_ground(PIN, "grounded", kind="node", support_span=SPAN, note="the passage states it")
    assert out["ok"] and out["to"] == "grounded" and out["confirmed"] is True
    assert out["search_terms"] == ["failure", "signal", "quorum", "threshold"]
    body = e.canon.read_node(PIN).body
    assert "verdict (grounded): confirmed by a second grounder (0.24.6)" in body
    plan, items = _plan(e)
    assert plan["queue"]["confirm"] == 0 and items == []


def test_an_unsupported_record_declines_it(eng):
    e, tmp = eng
    _register(e, tmp, for_items=PIN)
    e.kg_ground_item(PIN, "node", terms="failure signal quorum threshold")
    assert e.kg_ground(PIN, "grounded", kind="node", support_span=SPAN)["held"]
    assert e.kg_record_unsupported(PIN, "node", "the passage is about safe modes, not frustration signals")["ok"]
    plan, items = _plan(e)
    assert plan["queue"]["confirm"] == 0 and items == []
    assert plan["queue"]["unsupported_waiting"] == 1
    assert "confirm" not in e.kg_ground_item(PIN, "node")


def test_an_edge_is_held_too(eng):
    e, tmp = eng
    _register(e, tmp)
    e.kg_propose({"edges": [{"source": "signal-quorum", "target": "safe-mode-switch", "relation": "enables"}]})
    eid = edge_id("signal-quorum", "enables", "safe-mode-switch")
    assert e.kg_ground_item(eid, "edge", terms="quorum threshold safe mode")["requested_context"]["sections"]
    out = e.kg_ground(eid, "grounded", kind="edge", support_span=SPAN)
    assert out["ok"] and out["held"]
    plan, items = _plan(e)
    assert {"id": eid, "kind": "edge", "confirm": True} in items and plan["queue"]["confirm"] == 1
    confirmed = e.kg_ground(eid, "grounded", kind="edge", support_span=SPAN)
    assert confirmed["confirmed"] is True
    owner = e._owner_of_edge(eid)
    notes = next(x for x in owner.edges if x.id == eid).notes
    assert "confirmed by a second grounder (0.24.6)" in notes


def test_the_ledger_is_engine_state(eng):
    e, _ = eng
    exclude = Path(e.canon.root) / ".git" / "info" / "exclude"
    assert GROUND_REQUESTS == ".kg-ground-requests.jsonl"
    assert GROUND_REQUESTS in exclude.read_text(encoding="utf-8").splitlines()   # a project's git never sees it
    assert GROUND_REQUESTS in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_texts_state_the_rules():
    grounder = _flat(GROUNDER)
    assert "you may call `kg_ground_item(target_id, kind, terms=\"…\")` once: at most 8 words" in grounder
    assert "Never confirm a verdict you were held on yourself." in grounder
    cmd = _flat(GROUND_CMD)
    assert "Never hand it back to the grounder that was held" in cmd
    assert "List apart every item a grounder asked passages for with its own words (0.24.6)" in cmd
    tools = _flat(TOOLS)
    assert "**Held for a second grounder (0.24.6, `KGEngine._hold_or_confirm`).**" in tools
    assert "- **`queue.confirm` (0.24.6):**" in tools
