"""0.13.2 — the blind subagents start without the project's instruction files and its memory.

Claude Code hands every subagent it starts the user, project and local CLAUDE.md files and the auto-memory
index (`MEMORY.md`). The field session on Windows saves each /kg-experiment run's results in its memory, so
the index reached the agents that must work blind:
- In the first judged run (0.13.0, 2026-11-11), the twelve judges and both evaluator passes received "5 runs
  of the 5-arm ideation on the Spanish prompts…: graph never beat control".
- In the next run (0.13.1), the evaluator received the judges' verdict: "graph loses to rag 3/9, beats
  control 11/1".

A judge must not learn what the experiment tests, and an annotator must not learn how earlier coders labelled
an edge. Since 0.13.2 the three blind agents declare `omitClaudeMd: true`, and Claude Code starts them
without those files and without the memory index. This was checked headless on Claude Code 2.1.316 and
2.1.321 with a project holding a CLAUDE.md marker and a memory marker:
- the same judge file without the flag received both markers;
- kg-judge, kg-evaluator and kg-annotator received neither.

The judge's own prompt told it what it must not know, too. Since 0.13.0 it said "some were written with
help, some without, and two are controls planted to check you". The command's rule says never to tell a
judge that controls exist, and the pilots that fixed the method told their judges only that they did not
know who wrote the ideas or how. The agent's `description` still names the controls: it is for the session
that picks the agent, and Claude Code does not show it to the agent (checked in the 0.13.0 run's judge
transcripts).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _split(path: Path) -> tuple[dict, str]:
    yaml = pytest.importorskip("yaml")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", path.read_text(encoding="utf-8"), re.DOTALL)
    assert m, f"{path} has no YAML frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2)


def _agents() -> dict[str, tuple[dict, str]]:
    found = {}
    for path in sorted((REPO / "agents").glob("*.md")):
        head, body = _split(path)
        found[head["name"]] = (head, body)
    return found


def _blind_agents() -> frozenset:
    spec = importlib.util.spec_from_file_location("kg_precontext_memory", REPO / "hooks" / "precontext.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook._BLIND_AGENTS


def test_every_blind_agent_starts_without_instructions_or_memory():
    agents = _agents()
    blind = _blind_agents()
    assert blind == {"kg-evaluator", "kg-annotator", "kg-judge"}
    for name in blind:
        head, _ = agents[name]
        # a YAML boolean: Claude Code takes `true` or "true", and the string would read as a typo here
        assert head.get("omitClaudeMd") is True, f"{name} must declare omitClaudeMd: true"


def test_the_working_agents_keep_the_project_instructions():
    # Only the measurements must be blind. The agents that build and phrase the graph may follow a project's
    # CLAUDE.md, so the flag stays off them until a decision says otherwise. The grounders took it in 0.13.4
    # (tests/test_fix_grounders_without_memory.py), and the extractor in 0.14.2
    # (tests/test_fix_extractor_without_memory.py).
    for name, (head, _) in _agents().items():
        if name not in _blind_agents() | {"kg-grounder", "kg-adversarial-grounder", "kg-extractor"}:
            assert "omitClaudeMd" not in head, f"{name} sets omitClaudeMd without a decision"


def test_the_judge_is_not_told_how_the_ideas_were_made_or_that_controls_exist():
    _, body = _agents()["kg-judge"]
    flat = " ".join(body.split())
    assert "You do not know who wrote the ideas or how, and you must not try to guess." in flat
    leaks = re.findall(r"\bcontrols?\b|planted|with help|\bdecoys?\b|\barms?\b|\bgraph\b|\brag\b|experiment",
                       body, re.IGNORECASE)
    assert leaks == [], f"the judge's prompt names the study's design: {leaks}"
