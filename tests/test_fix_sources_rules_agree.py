"""0.25.2: `/kg-sources add` and the scout state the same rules for a level in doubt and for `interest`.

The end-to-end run of 2026-11-25 found two places where the command contradicted itself or the scout:

- **A level in doubt.** The scout proposes "the higher number" (the weaker level) when unsure between two; the
  command's `add` step said "propose the lower one". On the same run the scout, unsure between 2 and 3, proposed
  3, and the `add` step, unsure between 3 and 4, proposed 3.
- **`interest`.** The command's list of marks, and the engine, define it as "the author gains if the claim holds:
  a vendor about its product"; the `add` step said to mark it "when the author speaks about its own product,
  method or result", which every primary study does. The `add` step followed the narrow reading twice (field run
  of 2026-11-24, and this run), each time giving a reason the broad sentence did not admit.

Both now say the same thing everywhere: the higher number, and the engine's definition of `interest`.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
SCOUT = (REPO / "agents" / "scout.md").read_text(encoding="utf-8")
EVIDENCE = (REPO / "scripts" / "kg_engine" / "evidence.py").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_a_level_in_doubt_is_the_higher_number_in_both():
    assert "unsure between two levels, propose the higher number" in _flat(SCOUT)
    assert "When unsure between two levels, propose the higher number, the weaker level" in _flat(COMMAND)
    assert "propose the lower one" not in _flat(COMMAND)


def test_interest_has_one_definition():
    command = _flat(COMMAND)
    assert "`interest` (the author gains if the claim holds: a vendor about its product)" in command
    assert "Mark `interest` when the author gains if the claim holds (the definition above)" in command
    assert "own product, method or result" not in command
    assert "A study is not one for reporting its own result" in command
    assert "`interest` (the author gains if the claim holds)" in _flat(EVIDENCE)
