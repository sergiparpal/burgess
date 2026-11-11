"""0.12.1 — /kg-experiment's evaluator writes about the domain, never about its materials.

Two blind-judge pilots (docs/fusion/EXPERIMENT.md, option D) read the fourth field run's ideas against the
source alone. The graph-based arms cited their own materials: "el grafo guarda 59 aristas fallidas o
rechazadas", "un candidato de compresión sin verificar", RADAR as "the highest-degree node". No source
passage can hold such a statement, so the judges marked those ideas down in 7 of 12 prompts, and the form
alone told which arm wrote an idea. The evaluator had been taught to write that way. Its worked example
opened with "The graph marks span-present as grounds-ing …" and "a proposed compression candidate would …",
and rule 4 of the anti-smuggling invariant told it to mention that the graph records a failure.

These tests pin the rule, the example and the self-check. They also keep the grounding discipline, which
the style rule must not loosen: every idea still traces to an edge the graph returned.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVALUATOR = REPO / "agents" / "evaluator.md"
COMMAND = REPO / "commands" / "kg-experiment.md"

# Words that name the evaluator's materials. "node" and "bridge" are left out on purpose: they are domain
# vocabulary in the demo source the worked example uses ("What makes a node a real bridge …?").
APPARATUS = [r"\bthe graph\b", r"\bedges?\b", r"candidate", r"epistemic_state", r"falsification_counters",
             r"structural-bridge", r"\badvisory\b", r"\bslate\b", r"\bkg_", r"grounds-ing", r"collapses_into",
             r"defends_against", r"confounded_by", r"\bthe text says\b", r"\bthe source says\b",
             r"\bper the prose\b", r"\bpassages?\b"]


def _text(path):
    return path.read_text(encoding="utf-8")


def _section(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


def _flat(s):
    return " ".join(s.split())


def _example_answers():
    """Every answer the worked example shows: the numbered lines and the values of its JSON block."""
    example = _section(_text(EVALUATOR), "## Worked example", "## Self-check")
    lines = re.findall(r'^\[\d\] "(.*)"$', example, re.M)
    block = re.search(r"```json\n(.*?)\n```", example, re.S).group(1)
    values = [answer for arm in json.loads(block)["outputs"].values() for answer in arm]
    return lines, values


def test_blindness_requires_writing_about_the_domain():
    blind = _flat(_section(_text(EVALUATOR), "### Blindness, concretely", "## The anti-smuggling invariant"))
    assert "Write about the domain, never about your materials" in blind
    for named in ("the graph", "edges or relation names", "epistemic states", "the candidates or the slate",
                  "the passages", "a tool"):
        assert named in blind, named
    assert "hedged hypothesis" in blind


def test_the_worked_example_answers_name_no_material():
    lines, values = _example_answers()
    assert len(lines) == 9      # CONTROL, GRAPH and RAG, three prompts each
    assert len(values) == 12    # the JSON block's four arms, three prompts each
    for answer in lines + values:
        for pattern in APPARATUS:
            assert not re.search(pattern, answer, re.I), (pattern, answer)


def test_a_failure_steers_and_is_not_cited():
    invariant = _flat(_section(_text(EVALUATOR), "## The anti-smuggling invariant", "## Input"))
    assert "mention that the graph *records* the failure" not in invariant
    assert "do not cite the record itself" in invariant


def test_the_grounding_discipline_stays():
    invariant = _flat(_section(_text(EVALUATOR), "## The anti-smuggling invariant", "## Input"))
    assert "Every idea must trace to a real `kg_context` `items[]` edge" in invariant
    assert "Do NOT invent edges, nodes, or relations the graph did not return" in invariant
    procedure = _flat(_section(_text(EVALUATOR), "## Procedure", "## Worked example"))
    assert "treated as *unverified candidates* (never as fact" in procedure
    assert "hedged hypothesis about the domain, without calling it a candidate" in procedure


def test_the_self_check_and_the_command_carry_the_rule():
    check = _flat(_section(_text(EVALUATOR), "## Self-check before you write", "## The dpp arm"))
    assert "No idea in any arm mentions the graph" in check
    assert "a slate candidate (phrased as a hypothesis)" in check
    assert "flagged unverified" not in check
    step2 = _flat(_section(_text(COMMAND), "## Step 2", "## Step 3"))
    assert "Write every idea about the domain, never about its materials" in step2
    assert "must not be able to tell the arms apart by their form" in step2
