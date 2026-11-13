"""0.13.4 — the grounders start without the project's instructions and memory, like the blind agents.

Claude Code hands every subagent the user, project and local CLAUDE.md files and its auto-memory index
(`MEMORY.md`). 0.13.2 took that away from the three measurement agents and left the grounders as "a separate
decision". The field session keeps notes on each grounding pass in its memory, so the index reached the
verdicts too:
- 2026-11-12, `/burgess:kg-ground tasas-radar`: the user asked for a fresh verdict on a grounded edge that an eval
  had flagged. The session's brief left the eval's view out. But in a project with no CLAUDE.md the memory
  index was the grounder's only instructions, and it read "tasas-radar edge flagged as confounded_by by all 3
  coders". Its verdict agreed with them.
- 2026-11-12, the second attack on radar-meta: the adversarial grounder justified a counter-edge's relation
  with that same note.
- 2026-11-08: a grounder applied a cue from a memory note that no contract had.

Since 0.13.4 `kg-grounder` and `kg-adversarial-grounder` declare `omitClaudeMd: true`. A verdict rests on the
claim's source text and the grounder's contract, which carries the rules the user settled. The extractor and
the generator keep the project's instructions: they write candidates, and the grounders filter them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GROUNDERS = {"kg-grounder", "kg-adversarial-grounder"}
MEASUREMENT = {"kg-evaluator", "kg-annotator", "kg-judge"}


def _agents() -> dict[str, tuple[dict, str]]:
    yaml = pytest.importorskip("yaml")
    found = {}
    for path in sorted((REPO / "agents").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", path.read_text(encoding="utf-8"), re.DOTALL)
        assert m, f"{path} has no YAML frontmatter"
        head = yaml.safe_load(m.group(1))
        found[head["name"]] = (head, m.group(2))
    return found


def test_both_grounders_start_without_instructions_or_memory():
    agents = _agents()
    for name in GROUNDERS:
        head, _ = agents[name]
        # a YAML boolean: Claude Code takes `true` or "true", and the string would read as a typo here
        assert head.get("omitClaudeMd") is True, f"{name} must declare omitClaudeMd: true"


def test_only_the_measurement_agents_the_grounders_and_the_extractor_carry_the_key():
    # the extractor took the key in 0.14.2 (tests/test_fix_extractor_without_memory.py); the generator keeps
    # the project's instructions
    carriers = {name for name, (head, _) in _agents().items() if head.get("omitClaudeMd") is True}
    assert carriers == MEASUREMENT | GROUNDERS | {"kg-extractor"}
    assert "kg-generator" in set(_agents()) - carriers


def test_the_grounders_contract_carries_the_rules_the_memory_held():
    # the premise of the change: the rules the user settled live in the contract, so dropping the memory
    # index takes nothing a verdict needs
    _, body = _agents()["kg-grounder"]
    flat = " ".join(body.split())
    assert "`grounds` and `enables` are not interchangeable." in flat
    assert "`confounded_by` is a confound: a factor that biases the HEAD's figure" in flat
    assert "A table row states a relation when the table's header says what each cell is" in flat
    assert "**Each end is the concept its span names.**" in flat
