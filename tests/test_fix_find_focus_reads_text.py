"""0.24.1: the focus of `/burgess:kg-sources find` reads what an item claims, not only its id and label.

The first field run of `find` (2026-11-23, `prueba-burgess`, 119 waiting pins) typed `find compresión 3` and got
nothing: the focus was matched against the id and the label alone. A pin's id names its brief and candidate
(`idea-atasco-fabrica-agentes-c1a`), and its label is its first 80 characters, cut, so the one pin about
compression had the label "Comprimir el historial de acciones del agente y vigilar la ratio de compresió...".
The ground plan's focus is left as it was: it names nodes, and a word in a node's body would bring every edge
touching that node into a grounding pass.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.model import Node, Provenance
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

IDEA = ("Comprimir el historial de acciones del agente y vigilar la ratio de compresión: si cada paso nuevo apenas "
        "añade información (el log se comprime cada vez mejor), el agente se repite aunque cambie las palabras, y "
        "se le obliga a cambiar de estrategia.")
C1A = "idea-atasco-fabrica-agentes-c1a"
C1B = "idea-atasco-fabrica-agentes-c1b"


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text("## Notes\n\nEntropy grounds the arrow of time.\n", encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    pins = [(C1A, IDEA),
            (C1B, "Un mercado de predicción interno: antes de cada intento, varios agentes apuestan créditos.")]
    # a materialized pin: its label is the idea's first 80 characters, cut, and its body the whole idea
    e.canon.write_nodes([Node(id=nid, label=text[:77] + "...", node_type="claim", provenance=Provenance.HYPOTHESIZED,
                              body=f"{text}\n\n[diverge] pinned candidate={nid[-3:]} brief=atasco-fabrica-agentes")
                         for nid, text in pins], message="pins")
    for nid, _text in pins:
        assert e.kg_record_unsupported(nid, "node", "no passage states it")["ok"]
    return e


def _ids(out: dict) -> "list[str]":
    return [i["id"] for i in out["items"]]


def test_a_word_cut_from_the_label_is_found_in_the_text(eng):
    assert eng.canon.read_node(C1A).label.endswith("compresió...")       # the field's label, cut mid-word
    assert _ids(eng.kg_source_find(focus="compresión", limit=3)) == [C1A]
    assert _ids(eng.kg_source_find(focus="compresion")) == [C1A]         # accents ignored
    assert _ids(eng.kg_source_find(focus="estrategia historial")) == [C1A]


def test_every_word_of_the_focus_must_be_there(eng):
    assert _ids(eng.kg_source_find(focus="compresión mercado")) == []
    assert _ids(eng.kg_source_find(focus="mercado")) == [C1B]


def test_the_id_still_names_an_item(eng):
    assert sorted(_ids(eng.kg_source_find(focus="atasco"))) == [C1A, C1B]
    assert _ids(eng.kg_source_find(focus="c1a")) == [C1A]


def test_the_ground_plan_focus_is_unchanged(eng):
    # a body word does not reach the grounding focus: it names nodes by id and label
    queued = [i["id"] for b in eng.kg_ground_plan(focus="estrategia")["batches"] for i in b]
    assert queued == []


def test_the_texts_say_the_focus_reads_the_text():
    assert "whose text or id holds every one of these words" in _flat(COMMAND)
    assert "every word of it occurs in what the item claims" in _flat(TOOLS)
