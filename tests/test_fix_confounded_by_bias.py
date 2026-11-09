"""0.11.0: `confounded_by` is a confound that biases a figure, not only one that inflates it.

Field report on 0.10.2. The 142 first-pass grounded edges of a 416-node canon were judged again under the
current contract. Grounders in several batches ratified eight `confounded_by` edges whose confound does not
inflate the figure:

- equivalent mutants lower a mutation score;
- a denominator moves a usage figure both ways;
- a share taken over comments instead of reviews counts something other than what it claims to.

The relation table said "the inflated metric/value | the confound that inflates it", and the pack has no other
relation for such confounds. So the grounders read the relation as "distorts" without the contract saying so.
Taking the table literally would have rejected the eight as `wrong-relation` with no lead, dropping true and
specific claims. The table, the pack comment and the adversarial contract now say that a confound biases the
figure: it inflates it, lowers it, or makes it count something else.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def _roles(text: str) -> str:
    """The lines strictly between the relation-roles markers (as in test_fix_relation_rules)."""
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith("<!-- relation-roles:begin"))
    end = next(i for i, line in enumerate(lines) if line.startswith("<!-- relation-roles:end"))
    return "\n".join(lines[begin + 1:end])


@pytest.mark.parametrize("path", ["agents/extractor.md", "agents/grounder.md"])
def test_the_relation_table_says_the_confound_biases_the_figure(path):
    row = next(line for line in _roles(_read(path)).splitlines() if line.startswith("| confounded_by"))
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    assert cells == ["confounded_by", "the biased metric/value", "the confound that biases it"]


def test_the_table_says_a_confound_may_lower_the_figure_or_change_what_it_counts():
    flat = " ".join(_roles(_read("agents/extractor.md")).split())
    assert ("a factor that biases the HEAD's figure, whether it inflates it, lowers it, or makes it count "
            "something other than what it claims to") in flat
    assert "lower a mutation score: the score is `confounded_by` them" in flat


@pytest.mark.parametrize("path", [
    "pack/pack.yaml", "skills/burgess/references/pack-schema.md", "agents/extractor.md", "agents/grounder.md",
    "agents/adversarial-grounder.md",
])
def test_no_contract_or_pack_text_says_a_confound_only_inflates(path):
    flat = " ".join(_read(path).split())
    for old in ("the inflated metric/value", "the confound that inflates it", "apparent value is inflated",
                "HEAD's apparent value is inflated by TAIL", "HEAD = the inflated metric"):
        assert old not in flat, f"{path} still says {old!r}"


def test_the_pack_and_its_schema_reference_describe_confounded_by_alike():
    def line(path: str) -> str:
        return next(l.strip() for l in _read(path).splitlines() if l.strip().startswith("- confounded_by"))
    assert line("pack/pack.yaml") == line("skills/burgess/references/pack-schema.md")
    assert "biased by TAIL: inflated, lowered, or made to count something else" in line("pack/pack.yaml")


def test_the_adversarial_contract_still_reads_the_generality_confound_as_inflation():
    # inflation stays one case of a confound: the worked counter-edge is unchanged
    flat = " ".join(_read("agents/adversarial-grounder.md").split())
    assert "`confounded_by` reads HEAD = the biased metric, TAIL = the confound that biases it (here it inflates it)" in flat
    assert '"source": "betweenness", "target": "generality-confound", "relation": "confounded_by"' in flat
