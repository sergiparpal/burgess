"""0.14.2: the extractor starts without the project's instructions and memory, like the grounders.

Claude Code hands every subagent the user, project and local CLAUDE.md files and its auto-memory index
(`MEMORY.md`). 0.13.4 took them away from the grounders and left the extractor and the generator with them:
"they write candidates, and the grounders filter them". 0.14.0 changed what an extractor's silence costs. A
section it writes nothing from is recorded as edgeless, and no later build reads it again, so a relation a
note talks it out of never reaches a grounder.

Field report on 0.14.1 (2026-11-13). The plan held one section, Del LLM §3, whose one relation the canon
already holds as rejected. The session's memory index said so, in a line written after the previous build.
The extractor read the section and then, "by my notes", sent no `kg_write`. It recorded the section with a note
that described the rejected edge but could not give its id, because no quarantine had returned it. The note
was right that time. A stale one would have kept a writable relation out of the graph for good.

Since 0.14.2 `kg-extractor` declares `omitClaudeMd: true`. Its contract says that its facts come from the
section and from the engine's answers. It sends a relation even when it believes the canon holds it, and
records the section only once the quarantine comes back.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _agent(name: str) -> "tuple[dict, str]":
    yaml = pytest.importorskip("yaml")
    for path in sorted((REPO / "agents").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", path.read_text(encoding="utf-8"), re.DOTALL)
        assert m, f"{path} has no YAML frontmatter"
        head = yaml.safe_load(m.group(1))
        if head["name"] == name:
            return head, m.group(2)
    raise AssertionError(f"no agent named {name}")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_extractor_starts_without_instructions_or_memory():
    head, _ = _agent("kg-extractor")
    # a YAML boolean: Claude Code takes `true` or "true", and the string would read as a typo here
    assert head.get("omitClaudeMd") is True
    assert head.get("model") == "sonnet"          # the flag changes what it is given, not what runs it


def test_the_generator_keeps_the_project_instructions():
    # what the generator writes is a hypothesis the grounders filter, so nothing it omits is final
    head, _ = _agent("kg-generator")
    assert "omitClaudeMd" not in head


def test_the_contract_takes_facts_from_the_section_and_the_engine():
    _, body = _agent("kg-extractor")
    flat = _flat(body)
    assert ("**Your rules are this contract, and your facts are the section and the engine's answers.** Since "
            "0.14.2 you start without the project's CLAUDE.md files and without Claude Code's memory index") in flat
    assert "do not take a rule from a note, and where one disagrees with this contract, this contract wins" in flat
    assert "Nor take a fact about the canon from one" in flat
    assert "what the canon already holds comes back in `kg_write`'s answer" in flat
    assert "gives every subagent the project's memory index" not in flat            # through 0.14.1


def test_a_judged_relation_is_learned_from_kg_write():
    _, body = _agent("kg-extractor")
    rule = _flat(body.split("## A section that states no relation", 1)[1].split("\n## ", 1)[0])
    assert ("Learn it from `kg_write`, never from a note: send the edge even when you believe the canon already "
            "holds it, and record the section only once the quarantine comes back.") in rule
    assert "name the edge's id in the note" in rule


def test_the_brief_still_carries_what_the_extraction_needs():
    # the premise: the pack's vocabulary, the span rule and the record rules reach the extractor through its
    # contract and the build's brief, so dropping the project's notes takes nothing an extraction needs
    cmd = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
    brief = _flat(cmd.split('subagent_type: "kg-extractor"')[1].split('"""\n)', 1)[0])
    assert "declared node_types (compression, primitive, claim, metric, operation, failure)" in brief
    assert "MUST carry a verbatim \"span\" that is a substring of the section text" in brief
    assert "record that with mcp__plugin_burgess_burgess__kg_record_edgeless_section" in brief
