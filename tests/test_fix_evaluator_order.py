"""0.13.1 — the kg-evaluator's order is checkable.

The evaluator answers every arm in one context, so the experiment's blindness is procedural:
- control first, from the prompt alone;
- then the graph-based arms;
- rag last.

In the first judged field run (0.13.0), the evaluator's first pass read all twelve rag files before it wrote
any answer, and the session discarded it. The second pass improvised a draft before reading rag, and only that
draft showed the graph arms were written blind to rag. Nothing could show that control was written before the
graph calls, because the evaluator's reasoning is redacted in its transcript.

Since 0.13.1 the evaluator writes two drafts: the control draft before its first graph call, and the graph
draft before it reads the rag folder. `harness evaluator-order` checks two things on disk: that the drafts came
in that order, and that the final outputs carry them unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from kg_engine import harness

REPO = Path(__file__).resolve().parents[1]
CONTROL = ["Una idea de control.", "Otra idea de control."]
GRAPH = {"graph": ["Una idea con grafo.", "Otra con grafo."],
         "graph+generate": ["Con el slate.", "Otra con el slate."],
         "graph+generate+dpp": ["En orden DPP.", "Otra en orden DPP."]}
RAG = ["Desde los pasajes.", "Otra desde los pasajes."]


def _write(path: Path, outputs: dict, mtime: float) -> None:
    path.write_text(json.dumps({"outputs": outputs}, ensure_ascii=False), encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _run(tmp_path: Path, control=None, graph=None, final=None, times=(100.0, 200.0, 300.0), skip=()) -> Path:
    final_path = tmp_path / "ideation_outputs.json"
    files = {"control": (tmp_path / "ideation_outputs.control.json", control or {"control": CONTROL}),
             "graph": (tmp_path / "ideation_outputs.graph.json", graph or {"control": CONTROL, **GRAPH}),
             "final": (final_path, final or {"control": CONTROL, **GRAPH, "rag": RAG})}
    for (name, (path, outputs)), mtime in zip(files.items(), times):
        if name not in skip:
            _write(path, outputs, mtime)
    return final_path


def test_drafts_in_order_and_unchanged_are_verified(tmp_path):
    result = harness.evaluator_order(str(_run(tmp_path)))
    assert result == {"verified": True, "problems": [],
                      "drafts": {"control": str(tmp_path / "ideation_outputs.control.json"),
                                 "graph": str(tmp_path / "ideation_outputs.graph.json")}}


def test_a_changed_answer_is_caught(tmp_path):
    final = {"control": ["Una idea de control, retocada.", CONTROL[1]], **GRAPH, "rag": RAG}
    result = harness.evaluator_order(str(_run(tmp_path, final=final)))
    assert not result["verified"]
    assert "ideation_outputs.control.json: control differs from the final outputs" in result["problems"]
    assert "ideation_outputs.graph.json: control differs from the final outputs" in result["problems"]


def test_a_graph_arm_changed_after_the_draft_is_caught(tmp_path):
    final = {"control": CONTROL, **GRAPH, "graph": ["Reescrita tras leer rag.", GRAPH["graph"][1]], "rag": RAG}
    result = harness.evaluator_order(str(_run(tmp_path, final=final)))
    assert result["problems"] == ["ideation_outputs.graph.json: graph differs from the final outputs"]


def test_drafts_out_of_order_are_caught(tmp_path):
    result = harness.evaluator_order(str(_run(tmp_path, times=(300.0, 200.0, 400.0))))
    assert not result["verified"]
    assert result["problems"] == ["the files were not written in order: control draft, graph draft, final outputs"]


def test_a_missing_draft_is_caught(tmp_path):
    result = harness.evaluator_order(str(_run(tmp_path, skip=("graph",))))
    assert not result["verified"]
    assert result["problems"] == ["ideation_outputs.graph.json: not readable (FileNotFoundError)"]


def test_an_arm_the_run_lacks_is_not_required(tmp_path):
    graph = {"control": CONTROL, "graph": GRAPH["graph"], "graph+generate": GRAPH["graph+generate"]}
    final = {**graph, "rag": RAG}
    assert harness.evaluator_order(str(_run(tmp_path, graph=graph, final=final)))["verified"]


def test_the_subcommand_prints_the_check(tmp_path, capsys):
    assert harness._main(["evaluator-order"]) == 2
    assert "usage: evaluator-order OUTPUTS" in capsys.readouterr().err
    assert harness._main(["evaluator-order", str(_run(tmp_path))]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


def test_the_evaluator_writes_both_drafts_in_order():
    text = (REPO / "agents" / "evaluator.md").read_text(encoding="utf-8")
    procedure = _flat(_section(text, "## Procedure", "## Worked example"))
    assert "**Write** them at once to the **control draft**" in procedure
    assert "That Write is your first tool call after reading the prompt file" in procedure
    assert "Then **Write** the **graph draft**, before you read any file of the rag folder" in procedure
    assert "Copy `control` and the graph-based arms unchanged from the graph draft" in procedure
    check = _flat(_section(text, "## Self-check before you write", "## The dpp arm"))
    assert "The control draft was your first Write, before any graph call" in check


def test_the_command_checks_the_order_and_logs_it():
    text = (REPO / "commands" / "kg-experiment.md").read_text(encoding="utf-8")
    step2 = _flat(_section(text, "## Step 2", "## Step 3"))
    assert "Write all **control** answers first, from the prompts alone, before any tool call." in step2
    assert "Save them to the control draft (`ideation_outputs.control.json`" in step2
    assert "to the graph draft (`ideation_outputs.graph.json`) before reading any rag file" in step2
    step3 = _flat(_section(text, "## Step 3 —", "## Step 3b"))
    assert 'harness evaluator-order "$EXP/ideation_outputs.json"' in step3
    assert "It gates nothing (§4)" in step3
    step4 = _flat(text[text.index("## Step 4"):])
    assert "**Evaluator order:**" in step4
    assert "When the evaluator-order check was not verified, say so" in step4
