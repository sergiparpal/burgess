"""0.18.1: the grounder's example of a proposal's passage stating another relation comes from the demo corpus.

Field run (2026-11-15, 0.18.0). The user had one grounder re-judge the one generated edge that had grounded,
`andamiaje-rivaliza-con-fine-tuning bridges o1-sin-prompting`, giving it only the id. 0.18.0's contract
illustrated its "No lead" rule with that very pair and a reading of it, `§5 states
andamiaje-rivaliza-con-fine-tuning attacked_by o1-sin-prompting, not bridges`. The grounder rejected the edge
`wrong-relation` with that lead and reported that its note "names the same attacked_by edge as the contract's
own example for this pair". The verdict was primed, and so would have been the lead's own grounding: the
contract asserted that the source states it.

So, in this release, the example is a proposal against `examples/source.md`, the demo corpus every other
example of the contract uses, and no agent-facing text names that field pair.
"""
from __future__ import annotations

from pathlib import Path

from kg_engine.sources import plan_sections

REPO = Path(__file__).resolve().parents[1]
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
DEMO = (REPO / "examples" / "source.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_no_lead_example_is_a_demo_proposal():
    flat = _flat(GROUNDER)
    assert ("For the proposal `generality-confound bridges specificity` against `examples/source.md`, that note is "
            "`no-support: §1 states generality-confound attacked_by specificity, not bridges`.") in flat
    # the example's ids are the demo ids the contract's other examples use
    assert "`generality-confound` ── `attacked_by` ──▶ `specificity`" in GROUNDER


def test_the_demo_source_states_the_example_in_section_one():
    sections = plan_sections(DEMO)[1]
    first = next(s for s in sections if s.index == 1)
    assert first.title.startswith("1. Compression")
    assert "Generality is therefore *attacked_by* specificity" in _flat(first.text)


def test_no_agent_facing_text_names_the_pending_field_pair():
    texts = (list((REPO / "agents").glob("*.md")) + list((REPO / "commands").glob("*.md"))
             + list((REPO / "skills").rglob("*.md")))
    assert texts
    for path in texts:
        text = path.read_text(encoding="utf-8")
        for field_id in ("andamiaje-rivaliza-con-fine-tuning", "o1-sin-prompting"):
            assert field_id not in text, f"{path.relative_to(REPO)} names {field_id}"
