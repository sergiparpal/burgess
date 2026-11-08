"""0.8.0: the extractor and the grounder judge a claim by one table of relations, and the pack has `enables`.

Field report on 0.7.0, the first full /kg-ground on a 406-node canon:

- The grounder contract defined no relation. The extractor's HEAD/TAIL table never reached the grounders, so
  the grounders running in parallel each decided for themselves what a relation admits. They split four to one
  on whether "X permite Y" (X makes Y possible) grounds Y. Several of them listed the graph with `query_graph`
  to see how other edges used a relation.
- The pack had no relation for a precondition, and the extractor contract said both "map it to the nearest pack
  relation" and "leave the edge out instead of approximating it", so «permite» claims were filed under
  `grounds`.
- The command's grounder template listed "a table cell" among the spans that state no relation.

Now the pack declares `enables`; `grounds` is evidence or a reason; the grounder repeats the extractor's
relation block word for word, which this file keeps identical and complete. The grounder no longer has
`query_graph`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kg_engine.backend import _FALLBACK_EDGE_TYPES
from kg_engine.pack import load_pack
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = load_pack(REPO / "pack" / "pack.yaml")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")


def _roles(text: str) -> str:
    """The lines strictly between the relation-roles markers."""
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith("<!-- relation-roles:begin"))
    end = next(i for i, line in enumerate(lines) if line.startswith("<!-- relation-roles:end"))
    return "\n".join(lines[begin + 1:end])


def test_the_pack_declares_enables():
    assert "enables" in PACK.edge_types


def test_an_enables_edge_is_accepted(vault: Path, tmp_path: Path):
    src = tmp_path / "doc.md"
    src.write_text("## R\nLo que lo permite son comprobadores deterministas.\n", encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    out = e.kg_write({"nodes": [{"id": "comprobadores", "label": "comprobadores deterministas",
                                 "node_type": "operation"},
                                {"id": "retirar-revision", "label": "retirar la revisión", "node_type": "claim"}],
                      "edges": [{"source": "comprobadores", "target": "retirar-revision", "relation": "enables",
                                 "span": "Lo que lo permite son comprobadores deterministas",
                                 "source_file": "doc.md"}],
                      "complete": True})
    assert out["dispositions"] == {"ACCEPTED": 3, "DEMOTED": 0, "QUARANTINED": 0, "REJECTED": 0}, out


def test_the_grounder_judges_by_the_extractors_relation_table():
    assert _roles(GROUNDER) == _roles(EXTRACTOR)


def test_the_relation_table_covers_every_pack_relation():
    block = _roles(EXTRACTOR)
    rows = set(re.findall(r"^\| (\w+)\s+\|", block, flags=re.M)) - {"relation"}
    named = set(re.findall(r"`(\w+)`", block))
    assert set(PACK.edge_types) <= rows | named
    assert "enables" in rows and "grounds" in rows


def test_grounds_is_evidence_and_a_precondition_is_enables():
    flat = " ".join(_roles(EXTRACTOR).split())
    assert "`grounds` is evidence or a reason" in flat
    assert "`enables` is a precondition or a means" in flat
    assert "map it to the nearest pack relation" not in " ".join(EXTRACTOR.split())


def test_the_grounder_reads_tables_under_their_header_and_does_not_list_the_graph():
    tools = {t.strip() for t in GROUNDER.split("---", 2)[1].split("tools:", 1)[1].splitlines()[0].split(",")}
    assert "mcp__plugin_burgess_burgess__query_graph" not in tools
    assert "mcp__plugin_burgess_burgess__get_node" in tools
    flat = " ".join(GROUNDER.split())
    assert "**Tables.** A table row states a relation when the table's header says what each cell is" in flat
    assert "**Judge from the evidence, not from the graph.**" in flat


def test_the_command_template_no_longer_rejects_table_cells_wholesale():
    flat = " ".join(CMD.split())
    assert "(a bare label, a table cell, or its opposite)" not in flat
    assert "A table row states a relation when the table's header says what its cells are." in flat
    assert "as your contract's relation table defines it" in flat


@pytest.mark.parametrize("path", [
    "README.md", "agents/extractor.md", "agents/generator.md", "commands/kg-build.md", "commands/kg-query.md",
    "skills/burgess/SKILL.md", "skills/burgess/references/contract.md", "skills/burgess/references/tools.md",
    "skills/burgess/references/pack-schema.md",
])
def test_every_text_that_lists_the_relations_lists_them_all(path):
    text = (REPO / path).read_text(encoding="utf-8")
    missing = [t for t in PACK.edge_types if not re.search(rf"\b{t}\b", text)]
    assert missing == [], f"{path} lists the relations without {missing}"


def test_the_backends_fallback_vocabulary_is_the_pack():
    assert _FALLBACK_EDGE_TYPES == PACK.edge_types


def test_the_adversarial_contract_names_the_node_types_it_may_declare():
    # 0.8.0 asks it to declare new endpoints instead of leaving untyped placeholders; in the end-to-end check
    # its first write used `concept`, which the pack does not declare, and was quarantined
    text = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")
    assert [t for t in PACK.node_types if f"`{t}`" not in text] == []
