"""0.25.2: `/kg-experiment --judge` checks first whether the source can hold a positive control.

The end-to-end run of 2026-11-25 ran `/kg-experiment --judge` on the demo that ships with the plugin, the corpus
its 12 default prompts are written for. Step 3b wrote the controls, `judge-packets` refused them (exit 3), the
command wrote them again, they were refused again, and the judge was skipped. Both refusals were certain: a
positive control must cite two or more of the source's figures or names drawn from at least two documents, the
demo is one document, and its 254 distinct lowercase words all fall inside the 400 "common" ones, so almost none
of its words counts as a name.

`judge-check SOURCE` answers that before anything is spent, by the controls' own rules, and the command runs it in
Step 0. It is a necessary condition only; `judge-packets` still checks each prompt's controls.
"""
from __future__ import annotations

import json
from pathlib import Path

from kg_engine import harness, judge

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "examples" / "source.md"
EXPERIMENT = (REPO / "commands" / "kg-experiment.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")


def _capacity(documents: dict[str, str]) -> dict:
    return judge.control_capacity(judge.Evidence(documents))


_NOTES = ("the team said that the plan was late and the review found that the plan was not ready for the "
          "release, so the team moved the date and asked the review board to look again at the plan. ")


def test_the_demo_can_never_hold_a_positive_control():
    res = _capacity({"source.md": DEMO.read_text(encoding="utf-8")})
    assert res["judge_possible"] is False
    assert res["documents"] == 1
    assert any("one document" in p for p in res["problems"])


def test_two_documents_with_names_can():
    res = _capacity({"a.md": _NOTES + "In 2024 the vendor Zalando shipped it.",
                     "b.md": _NOTES + "Later the auditors at Deloitte measured 37 % fewer faults."})
    assert res["judge_possible"] is True, res
    assert res["documents_with_names"] == 2
    assert "Zalando" in res["examples"]["a.md"] and "2024" in res["examples"]["a.md"]
    assert "Deloitte" in res["examples"]["b.md"] and "37 %" in res["examples"]["b.md"]


def test_names_in_one_document_only_are_not_enough():
    res = _capacity({"a.md": _NOTES + "In 2024 the vendor Zalando shipped it.", "b.md": _NOTES})
    assert res["judge_possible"] is False
    assert any("fewer than two of the source's documents" in p for p in res["problems"])


def test_a_word_that_only_opens_sentences_is_not_a_name():
    """The controls' rule: a capitalised word opening a sentence is read as the sentence's first word."""
    text = _NOTES + "The plan slipped. Meanwhile the board waited. Meanwhile nothing moved."
    res = _capacity({"a.md": text, "b.md": text})
    assert res["judge_possible"] is False
    assert res["names_and_figures"] == 0
    assert any("fewer than two figures or names" in p for p in res["problems"])


def test_a_small_vocabulary_makes_every_word_common():
    """Under 400 distinct lowercase words, a capitalised word whose lowercase form also occurs is common."""
    text = "the review of the release went well, and later the review board said the release was fine."
    res = _capacity({"a.md": text + " Then the team said Review and Release were done.",
                     "b.md": text + " Then the board said Review was done."})
    assert res["names_and_figures"] == 0 and res["judge_possible"] is False


def test_what_the_check_rejects_the_controls_reject_too():
    """On the demo, a positive control citing what the source holds fails `check_controls` on documents."""
    evidence = judge.Evidence({"source.md": DEMO.read_text(encoding="utf-8")})
    positive = ("A plugin like Burgess could keep refuted claims as negative information. "
                "It would then show This as a test of the span check.")
    result = judge.check_controls(evidence, ["Per the 2019 Gartner survey, 87 % of graphs drift."], [positive])
    assert any("fewer than two documents" in p for p in result[0]["problems"])


def test_the_cli_prints_json_and_exits_0_either_way(tmp_path, capsys):
    assert harness._main(["judge-check", str(DEMO)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["judge_possible"] is False and out["problems"]
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "a.md").write_text(_NOTES + "In 2024 the vendor Zalando shipped it.", encoding="utf-8")
    (folder / "b.md").write_text(_NOTES + "Later the auditors at Deloitte measured 37 % fewer faults.", encoding="utf-8")
    assert harness._main(["judge-check", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out)["judge_possible"] is True


def test_the_cli_refuses_a_missing_source(tmp_path, capsys):
    assert harness._main(["judge-check"]) == 2
    assert harness._main(["judge-check", str(tmp_path / "nowhere")]) == 2
    assert "judge-check" in capsys.readouterr().err


def test_step_0_runs_the_check_and_step_3b_obeys_it():
    step0 = EXPERIMENT.split("## Step 0", 1)[1].split("## Step 1", 1)[0]
    # 0.28.0: the engine's first step returns the check (kg_engine.measure.experiment_start: judge.control_capacity)
    assert 'kg_experiment(step="start")' in step0 and "`judge` (0.25.2)" in step0
    assert "judge_possible" in step0 and "write no controls" in step0
    assert "the source cannot hold a positive control" in step0
    step3b = EXPERIMENT.split("## Step 3b", 1)[1].split("## Step 4", 1)[0]
    assert "`judge_possible` false" in step3b
    step1 = EXPERIMENT.split("## Step 1", 1)[1].split("## Step 1b", 1)[0]
    assert "cannot run on it" in step1


def test_the_reference_documents_it():
    assert "**`judge-check`** prints, as JSON, whether the source can hold a positive control" in TOOLS
