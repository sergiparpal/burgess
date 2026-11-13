"""0.10.0: a connective does not decide between `grounds` and `enables`, and each contract, not a memory note, is
its agent's rulebook.

Field report on 0.9.0. Two grounders ruled one span two ways: «O puedes bajar la variedad del entorno hasta que
el controlador que sí puedes construir sea suficiente. Por eso funcionan los robots industriales». The first
sealed `bajar-la-variedad-del-entorno grounds robot-industrial` as a lead, because «por eso» gives a reason. The
next pass rejected that edge as `wrong-relation`, because lowering the variety is the means that makes the
robots work, which the relation table calls `enables`. The second grounder noted that the contract's gloss of
`grounds`, "the span says the HEAD shows, or is why, the TAIL is true", also fits «por eso».

The first grounder had opened the user's memory note on grounder rules by itself, and that note lists «porque»,
«por eso» and «muestra» as cues for `grounds`, a list no contract has. Claude Code gives every subagent the
project's memory index, so a note reaches a grounder even when the orchestrator pastes nothing into its prompt,
the channel 0.8.1 closed. Now the relation block says that a connective explains, and the HEAD's role decides;
and every contract says its rules are its own.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
ADVERSARIAL = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _roles(text: str) -> str:
    return _flat(text.split("<!-- relation-roles:begin", 1)[1].split("<!-- relation-roles:end", 1)[0])


def test_a_connective_does_not_decide_between_grounds_and_enables():
    block = _roles(GROUNDER)
    assert "A connective does not decide between the two (0.10.0)" in block
    assert "so ask what the HEAD does for the TAIL" in block
    assert "Por eso funcionan los robots industriales» gives the means that makes the robots work: it states " \
           "`enables`, not `grounds`." in block
    # the gloss the second grounder found «por eso» to fit is gone
    assert "or is why, the TAIL is true" not in block
    assert "`grounds` is evidence or a reason to believe" in block
    assert "makes the TAIL possible, or makes it work" in block


def test_the_extractors_shortcut_list_says_the_same():
    assert ("a precondition or means that makes something possible, or makes it work → `enables`, never "
            "`grounds`, even when «por eso» or «porque» links them.") in _flat(EXTRACTOR)


def test_every_contract_says_its_rules_are_its_own():
    for name, text in (("grounder", GROUNDER), ("extractor", EXTRACTOR), ("adversarial", ADVERSARIAL)):
        flat = _flat(text)
        assert "**Your rules are this contract" in flat, name
        assert "do not take a rule from a note, and where one disagrees with this contract, this contract wins" \
               in flat, name
    # How a note reaches the agent. The extractor starts without the memory index since 0.14.2, and its contract
    # says so instead (tests/test_fix_extractor_without_memory.py).
    for name, text in (("grounder", GROUNDER), ("adversarial", ADVERSARIAL)):
        assert "gives every subagent the project's memory index" in _flat(text), name
    assert "you start without the project's CLAUDE.md files and without Claude Code's memory index" \
           in _flat(EXTRACTOR)
