"""0.24.5: a changed source flags a rejected item for re-examination only where a paragraph shares three of its
words, both that bar and the wake count words rather than spellings, and a registration says why each waiting item
comes back.

The field test of 0.24.4 (2026-11-23, `prueba-burgess`) registered an English arXiv abstract found for one Spanish
idea (c1j). The next `/burgess:kg-ground` queued c1j alone, as 0.24.4 meant, and also four rejected edges the
abstract had flagged for re-examination on two generic words each (llm with tests or reward). A grounder rejected
all four again. On 2026-11-22 the copies of another English page had flagged eight edges the same way, and all eight
stayed rejected. Two smaller faults showed in the same run:
- A claim that wrote both `test` and `tests` counted one word of a paragraph twice. Three of the seven pins the
  two-word rule would have woken matched that way.
- The registering agent told the user c1j came back because it shared words with the source. It came back
  because the source was found for it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.groundplan import distinct_words, rank_units, text_forms, word_groups
from kg_engine.model import Node, Provenance, edge_id
from kg_engine.projector import BEARING_WORDS
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
SOURCES_CMD = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")

NOTES = "## Notes\n\nDegree approximates importance in every sampled network.\n"


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
    return e, tmp_path


def _add(e, tmp_path, name, paragraphs, level=4, **kw):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    page = f"<html><head><title>{name}</title></head><body><main>{body}</main></body></html>"
    f = tmp_path / f"{name}.html"
    f.write_bytes(page.encode("utf-8"))
    out = e.kg_source_add(path=str(f), level=level, role="primary", **kw)
    assert out["ok"], out
    return out


def _rejected_edge(e) -> str:
    e.kg_propose({"edges": [{"source": "token-ring-scheduler", "target": "agent-coordination",
                             "relation": "bridges"}]})
    eid = edge_id("token-ring-scheduler", "bridges", "agent-coordination")
    assert e.kg_ground(eid, "rejected", note="no-support: the notes never join them")["ok"]
    e.kg_context(query="")                       # projected once, so the next source is a change
    return eid


def _flagged(e) -> "list[str]":
    e.kg_context(query="")
    return [f["item_id"] for f in e.kg_context()["advisory"]["reexaminable_verdicts"]]


def _pin(e, pid: str, text: str) -> None:
    e.canon.write_nodes([Node(id=pid, label=text[:60] + "...", node_type="claim", provenance=Provenance.HYPOTHESIZED,
                              body=text + f"\n\n[diverge] pinned candidate={pid[-3:]} brief=b")], message="pin")
    assert e.kg_record_unsupported(pid, "node", "no source states it")["ok"]


def _queued(e) -> "list[str]":
    return [i["id"] for b in e.kg_ground_plan()["batches"] for i in b]


def test_two_shared_words_no_longer_flag_a_rejection(eng):
    e, tmp = eng
    eid = _rejected_edge(e)
    _add(e, tmp, "slots", ["The scheduler hands each agent a slot in turn."])   # scheduler, agent
    assert eid not in _flagged(e)
    assert e.kg_ground_plan()["queue"]["reexaminable"] == 0


def test_three_shared_words_still_flag_it(eng):
    e, tmp = eng
    eid = _rejected_edge(e)
    _add(e, tmp, "ring", ["A token ring scheduler hands each agent a slot."])   # token, ring, scheduler, agent
    assert eid in _flagged(e)
    assert e.kg_ground_plan()["queue"]["reexaminable"] == 1


def test_a_word_in_two_spellings_counts_once():
    terms = ["test", "tests", "demo", "demos", "version", "versiones", "agentes"]
    groups = word_groups(terms)
    assert len(set(groups.values())) == 4
    assert distinct_words(terms) == ["test", "demo", "version", "agentes"]
    one = [text_forms("Rerun the failing test.")]
    assert not rank_units(one, ["test", "tests", "agentes"], need=2)        # one word, two spellings
    two = [text_forms("Each agent reruns the failing test.")]
    assert rank_units(two, ["test", "tests", "agentes"], need=2)
    assert not rank_units(two, ["test", "tests", "agentes", "cuarentena"], need=3)
    assert rank_units([text_forms("test")], ["test", "tests"], need=3)      # a one-word claim needs that word


def test_two_spellings_of_one_word_no_longer_wake_a_pin(eng):
    e, tmp = eng
    pid = "idea-cuarentena-c3a"
    _pin(e, pid, "Los agentes repiten cada test; los tests que fallan dos veces van a cuarentena.")
    # agent + test: two words, which 0.24.4 counted as three (test, tests, agentes)
    _add(e, tmp, "rerun", ["Each agent reruns the failing test before the release."])
    assert pid not in _queued(e)
    assert e.kg_ground_plan()["queue"]["unsupported_waiting"] == 1


def test_the_registration_says_why_each_item_comes_back(eng):
    e, tmp = eng
    found, by_words, waiting = "idea-anillo-c1a", "idea-reparto-c2d", "idea-entropia-c4b"
    _pin(e, found, "Un anillo de trabajadores pasa un permiso; quien lo tiene toma la tarea siguiente.")
    _pin(e, by_words, "Los agentes se reparten las tareas con un token que pasa de mano en mano sin coordinador.")
    _pin(e, waiting, "La entropía fija la flecha del tiempo en los sistemas cerrados.")
    out = _add(e, tmp, "reparto",
               ["Los agentes se reparten el trabajo pasando un token, sin ningún coordinador central."],
               for_items=found)
    back = {i["id"]: i for i in out["comes_back"]}
    assert [i["id"] for i in out["comes_back"]] == [found, by_words]          # found_for first
    assert back[found]["why"] == "found_for" and "words" not in back[found]
    assert back[by_words]["why"] == "words"
    assert {"agentes", "token", "coordinador"} <= set(back[by_words]["words"])
    assert out["comes_back_total"] == 2 and out["still_waiting"] == 1
    assert sorted(_queued(e)) == sorted([found, by_words])                   # the plan agrees


def test_a_source_the_policy_does_not_accept_brings_nothing_back(eng):
    e, tmp = eng
    pid = "idea-reparto-c2d"
    _pin(e, pid, "Los agentes se reparten las tareas con un token que pasa de mano en mano sin coordinador.")
    out = _add(e, tmp, "anuncio", ["Los agentes se reparten el trabajo pasando un token, sin coordinador."],
               level=5, for_items=pid)
    assert out["source"]["usable"] is False
    assert out["comes_back"] == [] and out["still_waiting"] == 1


def test_one_bar_for_both_rules():
    assert BEARING_WORDS == 3 and KGEngine.WAKE_WORDS == BEARING_WORDS


def test_the_texts_state_the_bar_and_the_reasons():
    tools = _flat(TOOLS)
    assert "flagged only when a paragraph of the changed text shares three of the words of what it claims (0.24.5" in tools
    assert "Words, not spellings: `test` and `tests` are one word." in tools
    assert "`comes_back` (0.24.5) — the waiting items the registration wakes" in tools
    sources = _flat(SOURCES_CMD)
    assert "Name each item with the reason its `why` gives, never another:" in sources
    assert "`found_for`: the source was found for it;" in sources
    assert "a paragraph of the changed text shares three of the words of what the item claims (0.24.5" in _flat(GROUND_CMD)
