"""0.24.4: a new usable source wakes a waiting item by its words only when one paragraph shares three of them.

The field's full loop of `/burgess:kg-sources find` (2026-11-23, `prueba-burgess`, on 0.24.3) registered an English
design-pattern page found for one Spanish idea (c1l). The next `/burgess:kg-ground` queued 16 ideas: c1l, woken by
its `found_for`, and 15 others, each woken by a paragraph that shared exactly two of its words, cognates or generic
words (agentes/agents, planes/plan, tests, local, token, final, persona, detector). All 15 went back to waiting.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.model import Node, Provenance
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

PIN = "idea-reparto-c2d"
PIN_TEXT = "Los agentes se reparten las tareas con un token que pasa de mano en mano sin coordinador."


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text("## Notas\n\nLa entropía fija la flecha del tiempo.\n", encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label=PIN_TEXT[:60] + "...", node_type="claim", provenance=Provenance.HYPOTHESIZED,
                              body=PIN_TEXT + "\n\n[diverge] pinned candidate=c2d brief=reparto")], message="pin")
    assert e.kg_record_unsupported(PIN, "node", "no source states it")["ok"]
    return e, tmp_path


def _add(e, tmp_path, name, paragraph, **kw):
    page = f"<html><head><title>{name}</title></head><body><main><p>{paragraph}</p></main></body></html>"
    f = tmp_path / f"{name}.html"
    f.write_bytes(page.encode("utf-8"))
    out = e.kg_source_add(path=str(f), level=4, role="primary", **kw)
    assert out["ok"], out
    return out


def _queued(e) -> "list[str]":
    return [i["id"] for b in e.kg_ground_plan()["batches"] for i in b]


def test_two_shared_words_no_longer_wake_an_item(eng):
    e, tmp = eng
    # an English page that shares two cognates with the Spanish idea: agentes/agents and token
    _add(e, tmp, "loops", "When agents loop, raise the sampling temperature; every token then varies more.")
    assert _queued(e) == [] and e.kg_ground_plan()["queue"]["unsupported_waiting"] == 1


def test_three_shared_words_still_wake_it(eng):
    e, tmp = eng
    _add(e, tmp, "reparto", "Los agentes se reparten el trabajo pasando un token, sin ningún coordinador central.")
    assert _queued(e) == [PIN]


def test_a_source_found_for_the_item_wakes_it_whatever_its_words(eng):
    e, tmp = eng
    _add(e, tmp, "ring", "A ring of workers hands a single permit around; whoever holds it takes the next job.",
         for_items=PIN)
    assert _queued(e) == [PIN]


def test_the_bar_is_three_words_or_all_of_a_short_item(eng):
    e, _ = eng
    assert KGEngine.WAKE_WORDS == 3
    from kg_engine.groundplan import rank_units, text_forms
    forms = [text_forms("gamma bridges delta here")]
    assert rank_units(forms, ["gamma", "bridges"], need=3)              # two words: both must be there
    assert not rank_units(forms, ["gamma", "bridges", "omega"], need=3)


def test_the_reference_states_the_bar():
    assert "a paragraph must share three of its words (0.24.4" in " ".join(TOOLS.split())
