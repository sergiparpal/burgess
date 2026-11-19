"""0.19.4: /burgess:kg-diverge presents the rest of each round too, not only the engine's slate.

Field session (Windows, 2026-11-16 to 11-19, 86 ideas over 7 rounds). Step 7 presented the returned slate, six of
a round's twelve. Round 1 showed nothing else. Round 2 showed the rest as a one-line table, and the user wrote «Así
no sé de qué van» and asked how ideas were picked for explanation. One idea the user pinned had never been
explained. The session then explained every idea of each round, on its own initiative.

So step 7 now lists every other idea ingested that round, in two or three plain lines with an example, and
invites pinning any idea of the round, from the slate or the rest.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIVERGE = (REPO / "commands" / "kg-diverge.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_rest_of_the_round_is_presented_after_the_slate():
    flat = _flat(DIVERGE)
    assert "**Then the rest of this round.** After the slate, list every other idea you ingested this round" in flat
    assert "by id, in two or three plain lines each: what it claims, and one concrete example" in flat
    assert "Not a table of one-liners, and not ideas from earlier rounds." in flat
    assert flat.index("**Present the returned `slate`**") < flat.index("**Then the rest of this round.**")


def test_any_idea_of_the_round_can_be_pinned():
    flat = _flat(DIVERGE)
    assert "pin any idea of this round to keep exploring from, from the slate or the rest, not just A/B" in flat
    assert "pin any of these to keep exploring from? any of them" not in flat
