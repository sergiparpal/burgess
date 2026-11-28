"""0.29.1: three findings of the field and end-to-end runs, fixed in the text the agents read.

- **A focused progress probe lists a recorded item again.** A focus offers the items a grounder recorded
  unsupported again, as a fresh look (0.20.1), and a withdrawn grounding is recorded the same way (0.24.7). So the
  probe after a focused wave lists again the pin its grounder has just recorded, or whose support it has just
  withdrawn. `/kg-ground` said such an item drops out of the plan, which holds only without a focus. Twice on
  2026-11-24 (`--reexamine` with a pin's full id) the orchestrator saw the withdrawn pin back in the probe and did
  not re-launch it on its own judgment; the command now says so.
- **The annotators label by the table the extractor wrote by.** `/kg-eval`'s annotators had no table of what each
  relation asserts. In the end-to-end run of 2026-11-25 they labeled `wrong_type` two edges the grounders had
  grounded by that table: a counter-edge built on a limit the source states («One caveat limits the span
  check…»), and a lead typed `enables` where the author had written *grounds* for a precondition. The 0.25.2
  record left the question to the user; the user approved the alignment as 0.29.1 («Sí, prepárala»). The
  annotator now holds the extractor's relation table word for word (`tests/test_fix_relation_rules.py`), with
  two rules for the two cases. Its examples are made up, from no graph a run judged.
- **The user sees no plan section and no engine name.** The same run showed `on_unusable_total` (policy),
  `kg_merge` (build), §1.6 and §1.7 (query) and a § column reading §9 (perturb) to the user. Every command now
  holds one block, identical in all ten, read before its first step, and the templates the user sees carry none.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from kg_engine.model import Node, Provenance
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
COMMANDS = sorted((REPO / "commands").glob("kg-*.md"))
ANNOTATOR = REPO / "agents" / "annotator.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------------------------- a focused probe lists it again

NOTES = ("## Notes\n\nA warm cache serves the first reads of a release from memory.\n\n"
         "## Other\n\nEntropy fixes the arrow of time.\n")
SPAN = "A warm cache serves the first reads of a release from memory."
PIN = "idea-warm-cache-c1a"
PIN_BODY = ("Warm the cache before each release, so that its first reads come from memory."
            "\n\n[diverge] pinned candidate=c1a brief=cache")


@pytest.fixture
def eng(tmp_path):
    """A project whose notes hold one passage, with one materialized [diverge] pin."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text(NOTES, encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label="Warm the cache before each release", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body=PIN_BODY)], message="pin")
    return e


def _queued(plan: dict) -> "list[dict]":
    return [item for batch in plan["batches"] for item in batch]


def test_a_focused_probe_lists_again_the_pin_its_grounder_just_recorded(eng):
    assert _queued(eng.kg_ground_plan(focus=PIN)) == [{"id": PIN, "kind": "node"}]
    assert eng.kg_record_unsupported(PIN, "node", note="no passage warms the cache before a release")["ok"]
    plan = eng.kg_ground_plan()
    assert _queued(plan) == [] and plan["queue"]["unsupported_waiting"] == 1        # without a focus it waits
    plan = eng.kg_ground_plan(focus=PIN)                                             # the same probe as before
    assert _queued(plan) == [{"id": PIN, "kind": "node"}] and plan["queue"]["unsupported_waiting"] == 0


def test_a_focused_probe_lists_again_the_pin_whose_grounding_was_withdrawn(eng):
    assert eng.kg_ground(PIN, "grounded", kind="node", support_span=SPAN, note="the notes state it")["ok"]
    assert _queued(eng.kg_ground_plan(focus=PIN, reexamine=True)) == [{"id": PIN, "kind": "node",
                                                                        "reexamine": True}]
    out = eng.kg_ground(PIN, "unverified", kind="node", note="the notes warm no cache before a release")
    assert out["ok"] and out["withdrawn"] and out["recorded_unsupported"] is True
    assert eng.kg_ground_plan()["queue"]["unsupported_waiting"] == 1
    # the field case of 2026-11-24: the progress probe of a `--reexamine <id>` pass, after the withdrawal
    assert _queued(eng.kg_ground_plan(focus=PIN, reexamine=True)) == [{"id": PIN, "kind": "node"}]


def test_kg_ground_says_not_to_relaunch_what_a_focused_probe_lists_again():
    flat = _flat(_read(REPO / "commands" / "kg-ground.md"))
    assert ("With a focus, the probe lists such an item again: a focus offers recorded items again, as a fresh "
            "look, so the pin or claim a grounder of this pass has just recorded, or whose grounding it has just "
            "withdrawn on `--reexamine`, is back in its `batches`. It has had its look in this pass: do not "
            "re-launch it (0.29.1).") in flat
    assert "One it did not record stays in the plan: do not re-launch it, report it." in flat


# ------------------------------------------------------------------------- the annotators label by the table


def test_the_annotator_reads_the_table_before_its_inputs_and_its_decision_order_points_at_it():
    text = _read(ANNOTATOR)
    assert (text.index("## The verdict vocabulary") < text.index("## What each relation asserts")
            < text.index("<!-- relation-roles:begin") < text.index("## Inputs you receive"))
    flat = _flat(text)
    assert ("3. Are the endpoints related but the relation wrong for what the source actually says, read by the "
            "table below? → **wrong_type**.") in flat
    assert ("The extractor wrote each edge by this table, and the grounders judged it by the same one: label it by "
            "the same one too (0.29.1).") in flat


def test_the_table_decides_not_the_source_word_for_the_relation():
    flat = _flat(_read(ANNOTATOR))
    assert "**The table decides, not the source's word for the relation (0.29.1).**" in flat
    assert "even with one of the pack's own names: what decides is what the span says the HEAD does for the TAIL" in flat
    assert ("«Yeast *grounds* a light crumb: without yeast the dough does not rise» gives a precondition, so "
            "`yeast enables light-crumb` is `correct` and `yeast grounds light-crumb` is `wrong_type`") in flat


def test_a_limit_the_source_sets_against_a_claim_is_an_attack():
    flat = _flat(_read(ANNOTATOR))
    assert "**An attack does not have to refute (0.29.1).**" in flat
    assert ("A limit the source states is such an attack, the case its TAIL, even though the HEAD still holds "
            "elsewhere") in flat
    assert "states `daily-watering attacked_by heatwave`" in flat
    assert ("It is `wrong_type` when the span relates the two another way: the TAIL supports the HEAD, explains "
            "it, or is a part of it.") in flat


def test_the_annotators_examples_give_no_label_of_a_graph_away():
    # A pending field claim used as an example primed a grounder's verdict once (0.18.1). These are made up: the
    # demo every fresh install measures, and the end-to-end source whose two edges raised the question, hold
    # neither, and the annotator's section names neither of those edges.
    demo = _read(REPO / "examples" / "source.md").lower()
    for word in ("yeast", "crumb", "lawn", "heatwave"):
        assert word not in demo, word
    section = _read(ANNOTATOR).split("## What each relation asserts", 1)[1].split("## Inputs you receive", 1)[0]
    assert "span check" not in section and "span-check" not in section and "provenance" not in section.lower()


def test_kg_eval_tells_its_annotators_to_judge_by_the_table():
    flat = _flat(_read(REPO / "commands" / "kg-eval.md"))
    assert ("Judge each relation by the table in your contract of what each relation asserts, not by the word "
            "the source uses for it (0.29.1).") in flat


# ------------------------------------------------------------------------- what the user sees


def _plain(text: str) -> "tuple[int, int, str]":
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith("<!-- plain-words:begin"))
    end = next(i for i, line in enumerate(lines) if line.startswith("<!-- plain-words:end"))
    return begin, end, "\n".join(lines[begin + 1:end])


def test_the_plugin_has_ten_commands():
    assert len(COMMANDS) == 10, [p.name for p in COMMANDS]


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.name)
def test_every_command_holds_the_block_once_before_its_first_step(path):
    text = _read(path)
    assert text.count("<!-- plain-words:begin") == 1 and text.count("<!-- plain-words:end -->") == 1
    begin, end, _ = _plain(text)
    first_heading = next(i for i, line in enumerate(text.splitlines()) if line.startswith("## "))
    assert begin < end < first_heading


def test_the_ten_blocks_are_one():
    assert len({_plain(_read(path))[2] for path in COMMANDS}) == 1


def test_the_block_says_what_to_put_in_plain_words_and_what_to_keep():
    flat = _flat(_plain(_read(COMMANDS[0]))[2])
    for phrase in ("**Talk to the user in plain words (0.29.1).**",
                   "cites the plan's sections (§1.7) and names the engine's fields and tools "
                   "(`on_unusable_total`, `kg_merge`) so that you can find them; the user knows none of them",
                   "«2 grounded claims no longer rest on a usable source», not `on_unusable_total: 2`",
                   "«I can merge the two nodes», not `kg_merge`",
                   "Show no plan section (§), in a table either.",
                   "Keep as they are the commands to type (`/burgess:kg-ground`), the ids of nodes and edges, file "
                   "names, a section of the user's document by its title or its number, the pack's relations and types "
                   "(`grounds`, `claim`), the states and provenances (`grounded`, `span-present`), and any "
                   "reply this text asks the user to type exactly.",
                   "A log entry keeps the format its step gives."):
        assert phrase in flat, phrase


def test_no_slate_shows_a_plan_section():
    generate = _read(REPO / "commands" / "kg-generate.md")
    header = next(line for line in generate.splitlines() if line.startswith("| # | mechanism"))
    assert header == "| # | mechanism | idea (one sentence) | specificity | provenance |"
    table = generate.split(header, 1)[1].split("```", 1)[0]
    assert "§" not in table
    perturb = _read(REPO / "commands" / "kg-perturb.md")
    present = _flat(perturb.split("## Step 4 — report the perturbation slate", 1)[1].split("## Invariants", 1)[0])
    assert "§" not in present and "§ = §9" not in perturb
    assert "Present the ranked slate (mechanism `ensemble`, one-sentence idea, specificity, and whether its" in present


def test_kg_query_answers_with_no_plan_section_and_no_field_name():
    text = _read(REPO / "commands" / "kg-query.md")
    quoted = [line for line in text.splitlines() if line.startswith(">")]
    assert quoted and not [line for line in quoted if "§" in line or "failed_or_rejected_edges" in line]
    shape = text.split("## Worked shape", 1)[1]
    assert "failed_or_rejected_edges" not in shape and "§-referenced" not in text
    flat = _flat(text)
    assert ("> **Falsification counters:** <n> claims rejected or refuted — kept as negative information and never "
            "pruned. > A non-zero count means the graph remembers claims it refuted.") in flat
    assert "3. **Falsification counters:** 0 claims rejected or refuted." in flat


def test_kg_grounds_summary_names_no_field_and_no_plan_section():
    text = _read(REPO / "commands" / "kg-ground.md")
    summary = text.split("Render a summary like:", 1)[1].split("```", 2)[1]
    assert "Grounding pass complete." in summary
    assert "§" not in summary and "falsification_counters" not in summary and "_" not in summary
    assert "memory        : K claims rejected or refuted, kept as negative memory (never pruned)" in summary


def test_kg_sources_says_what_on_unusable_total_counts():
    flat = _flat(_read(REPO / "commands" / "kg-sources.md"))
    assert ("Report the policy, the notes with their levels, and how many grounded claims no longer rest on a usable "
            "source (`on_unusable_total`; they keep their verdict).") in flat
    assert not re.search(r"and `on_unusable_total`:", flat)
