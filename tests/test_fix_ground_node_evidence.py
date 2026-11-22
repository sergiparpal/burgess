"""0.20.2: a node's grounder reads the source sections that share its words, and a rejected node can be
judged again with them.

Through 0.20.1 `kg_ground_item(kind="node")` returned only the node and its incident edges. A pin or a cliché has
no edge, so its grounder had no source text at all: it could only search the spans other edges already cited.
The field pass of 2026-11-21 judged 120 pins and 6 clichés that way, and its own report said so: "they searched
the spans of edges already in the graph, not the full source files". One cliché grounded because its passage
happened to be cited by an edge. Five were rejected, and a rejection is permanent.

Now a node gets `source_context`, the sections that share the most of its words, rare words weighing more, with
excerpts. A 0.20.1 unsupported-pin record no longer keeps its pin waiting, since its judgment saw no source
text. `--reexamine` queues the rejected hypothesized nodes a focus names, for a judgment with the new evidence.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.groundplan import node_terms, rank_units, text_forms, text_units, unit_excerpt
from kg_engine.model import EpistemicState
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
LEDGER = ".kg-unsupported-pins.jsonl"

SOURCE = """\
# Fábrica

## Memoria del proyecto

El metaharnés guarda en Markdown las decisiones previas para no rastrear todo el código.

Las convenciones del equipo se repasan cada semana.

## Verificación

Los tests verifican el comportamiento de cada cambio antes de integrarlo.

## Despliegue

El despliegue se hace por oleadas con una reversión probada.
"""
SENTENCE = "El metaharnés guarda en Markdown las decisiones previas para no rastrear todo el código."


def _flat(text: str) -> str:
    return " ".join(text.split())


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A project whose source has three sections, with the registered tools."""
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    monkeypatch.delenv("KG_PACK_PATH", raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    src = tmp_path / "source.md"
    src.write_text(SOURCE, encoding="utf-8")
    engine = KGEngine(proj, source_path=src, pack_path=PACK)
    mcp = _FakeMCP()
    _register(mcp, engine)
    return engine, mcp.tools, src


def _propose(engine, node_id: str, label: str, body: str) -> None:
    out = engine.kg_propose({"nodes": [{"id": node_id, "label": label, "node_type": "claim", "body": body}]})
    assert out["dispositions"]["ACCEPTED"] == 1, out


def _queued(plan: dict) -> list[dict]:
    return [item for batch in plan["batches"] for item in batch]


# ------------------------------------------------------------------------------------------ the evidence


def test_a_node_gets_the_sections_that_share_its_words(rig):
    engine, t, _ = rig
    _propose(engine, "registro-de-decisiones", "Registros de decisiones en Markdown junto al código",
             "Los agentes guardan las decisiones previas en Markdown.\n\n[cliche] id=o3 role=avoided brief=b")
    out = t["kg_ground_item"](target_id="registro-de-decisiones", kind="node")
    ctx = out["source_context"]
    assert ctx["sections"], ctx
    first = ctx["sections"][0]
    assert first["title"] == "Memoria del proyecto"
    assert {"decisiones", "markdown"} <= set(first["matched"])
    assert SENTENCE in first["excerpt"]
    assert ctx["sections_total"] >= 1 and "cliche" not in ctx["terms"]   # the lineage line is no claim


def test_a_node_whose_words_the_sources_never_use_gets_no_section(rig):
    engine, t, _ = rig
    _propose(engine, "quorum-bacteriano", "Quórum bacteriano entre agentes", "Señales químicas de quórum.")
    ctx = t["kg_ground_item"](target_id="quorum-bacteriano", kind="node")["source_context"]
    assert ctx["sections"] == [] and ctx["sections_total"] == 0


def test_a_span_copied_from_the_excerpt_grounds_the_node(rig):
    engine, t, _ = rig
    _propose(engine, "registro-de-decisiones", "Registros de decisiones en Markdown",
             "Los agentes guardan las decisiones previas en Markdown.")
    excerpt = t["kg_ground_item"](target_id="registro-de-decisiones", kind="node")["source_context"]["sections"][0]["excerpt"]
    assert SENTENCE in excerpt
    out = engine.kg_ground("registro-de-decisiones", "grounded", kind="node", note="the section states it",
                           support_span=SENTENCE)
    assert out.get("ok", True) is not False, out
    assert engine.canon.read_node("registro-de-decisiones").epistemic_state is EpistemicState.GROUNDED


def test_the_index_is_rebuilt_when_a_source_changes(rig):
    engine, t, src = rig
    _propose(engine, "oleadas", "Despliegue por oleadas", "Se despliega por oleadas.")
    assert t["kg_ground_item"](target_id="oleadas", kind="node")["source_context"]["sections"][0]["title"] == "Despliegue"
    src.write_text(SOURCE.replace("## Despliegue", "## Lanzamiento"), encoding="utf-8")
    assert t["kg_ground_item"](target_id="oleadas", kind="node")["source_context"]["sections"][0]["title"] == "Lanzamiento"


# ------------------------------------------------------------------------------------------- the helpers


def test_node_terms_leave_out_lineage_and_verdict_lines():
    terms = node_terms("Registro de decisiones",
                       "Guardar decisiones previas.\n\n[diverge] pinned candidate=c1 brief=marcadorx\n\n"
                       "verdict (rejected): no-support: palabraveredicto")
    assert "registro" in terms and "decisiones" in terms
    assert "marcadorx" not in terms and "palabraveredicto" not in terms and "pinned" not in terms


def test_a_rare_word_outweighs_a_common_one():
    units = [text_forms("agentes código memoria"), text_forms("agentes código tests"),
             text_forms("agentes código despliegue"), text_forms("agentes memoria código")]
    ranked = rank_units(units, ["agentes", "tests", "codigo"])
    assert ranked[0][1] == 1   # the only unit with the rare "tests"
    assert all(len(m) >= 2 for _s, _i, m in ranked)


def test_a_word_every_unit_uses_weighs_nothing():
    units = [text_forms("agentes código"), text_forms("agentes código"), text_forms("agentes memoria")]
    ranked = {i: score for score, i, _m in rank_units(units, ["agentes", "codigo"])}
    assert ranked[0] == ranked[1] > 0 and 2 not in ranked   # "agentes" is in all three, so only "código" counts


def test_units_are_paragraphs_and_the_lines_of_a_long_table():
    text = "Uno.\n\nDos dos.\n\n" + "\n".join(f"| fila {i} |" for i in range(400))
    units = text_units(text, max_chars=200)
    assert text[units[0][0]:units[0][1]] == "Uno." and text[units[1][0]:units[1][1]] == "Dos dos."
    assert text[units[2][0]:units[2][1]] == "| fila 0 |" and len(units) == 402


def test_the_excerpt_is_cut_from_the_source_around_the_best_unit():
    text = "Uno sin nada.\n\nLas decisiones previas se guardan en Markdown.\n\nOtro párrafo lejano."
    units = text_units(text)
    out = unit_excerpt(text, units, 1, max_chars=60)
    assert out.startswith("Las decisiones previas") and len(out) <= 60
    assert out in text                       # the source's own text, so a span copied from it verifies
    assert unit_excerpt(text, units, 1) == text


# ------------------------------------------------------------------------------- the stale 0.20.1 records


def test_a_record_made_before_0_20_2_no_longer_keeps_a_pin_waiting(rig):
    engine, t, _ = rig
    _propose(engine, "idea-b-c1", "Una idea fijada sobre colas",
             "Colas de trabajo.\n\n[diverge] pinned candidate=c1 brief=b session=s")
    assert t["kg_record_unsupported"](target_id="idea-b-c1", kind="node", note="none found")["ok"]
    assert engine.kg_ground_plan()["queue"]["unsupported_waiting"] == 1
    ledger = engine.canon.root / LEDGER
    rec = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert rec["evidence"] == 2
    rec.pop("evidence")                      # what 0.20.1 wrote
    ledger.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    plan = engine.kg_ground_plan()
    assert plan["queue"]["unsupported_waiting"] == 0
    assert "idea-b-c1" in [i["id"] for i in _queued(plan)]


# ------------------------------------------------------------------------------------------ re-examining


def test_reexamine_queues_the_rejected_hypothesized_nodes_the_focus_names(rig):
    engine, _t, _ = rig
    _propose(engine, "cliche-b-o1", "Un archivo de instrucciones para los agentes", "Instrucciones.\n\n[cliche] id=o1")
    _propose(engine, "otra-hipotesis", "Otra hipótesis sobre colas", "Colas.")
    for nid in ("cliche-b-o1", "otra-hipotesis"):
        assert engine.kg_ground(nid, "rejected", kind="node", note="no-support").get("ok", True)
    assert _queued(engine.kg_ground_plan()) == []
    plan = engine.kg_ground_plan(focus="instrucciones", reexamine=True)
    assert _queued(plan) == [{"id": "cliche-b-o1", "kind": "node", "reexamine": True}]
    assert plan["queue"]["reexamine"] == 1
    everything = engine.kg_ground_plan(reexamine=True)
    assert sorted(i["id"] for i in _queued(everything)) == ["cliche-b-o1", "otra-hipotesis"]


def test_a_failed_node_is_not_offered_for_reexamination(rig):
    engine, _t, _ = rig
    _propose(engine, "refutada", "Una hipótesis refutada", "Algo falso.")
    engine.kg_ground("refutada", "failed", kind="node", note="refuted by a counter-span")
    assert engine.kg_ground_plan(reexamine=True)["queue"]["reexamine"] == 0


def test_a_reexamined_rejection_can_become_grounded(rig):
    engine, _t, _ = rig
    _propose(engine, "registro-de-decisiones", "Registros de decisiones en Markdown", "Decisiones en Markdown.")
    engine.kg_ground("registro-de-decisiones", "rejected", kind="node", note="no-support")
    out = engine.kg_ground("registro-de-decisiones", "grounded", kind="node", note="re-examined",
                           support_span=SENTENCE)
    assert out.get("ok", True) is not False and out.get("from") == "rejected", out
    assert engine.canon.read_node("registro-de-decisiones").epistemic_state is EpistemicState.GROUNDED


# -------------------------------------------------------------------------------------------- the text


def test_the_grounder_judges_a_node_against_its_source_context():
    text = _flat(GROUNDER)
    assert "`source_context` (0.20.2): the source sections that share the most of the node's words" in text
    assert "copy a `support_span` verbatim from one that states it" in text
    # 0.22.4 names the second kind of re-examined item after this one (tests/test_fix_reexamination_answered.py)
    assert ("The exception is an item your batch marks `re-examine`: a rejected node the user asked to have judged "
            "again (0.20.2)") in text


def test_the_command_reads_reexamine_and_tells_the_grounder():
    text = _flat(GROUND_CMD)
    assert "If the line starts with the word `--reexamine`, drop that word" in text
    assert "reexamine: <true only when the line started with --reexamine>" in text
    assert "for a node: source_context, the source sections that share the most of its words" in text
    # 0.22.4: a re-examined item is also one a source changed under (tests/test_fix_reexamination_answered.py)
    assert ("An item marked re-examine was rejected before and is judged again: a node the user asked to have "
            "judged again") in text


def test_the_tool_reference_documents_it():
    text = _flat(TOOLS)
    assert "`source_context` (0.20.2)" in text
    assert "`reexamine=True` (0.20.2)" in text
