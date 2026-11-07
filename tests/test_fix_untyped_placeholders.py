"""Regression: an undeclared endpoint no longer becomes an untyped node silently, and the next section can
fill it in.

Field report on 0.6.0, a full /kg-build of an 8-file corpus: one extractor wrote
`camel defends_against agente-obedece-datos-maliciosos` without declaring `camel`. The boundary writes such a
source as a placeholder with no node_type and no body (documented, and it keeps a verified edge), and it said
nothing. Later sections saw `camel` in their known_nodes as an undeclared-type node, and two of them refused
to link to it, because their contract said never to redeclare a known node.

0.6.1 closes the loop at both ends:

- kg_write lists the NEW notes it created untyped, under `placeholders`, so the extractor can re-send its
  payload with the node declared.
- kg_section marks such a known node `untyped: true`, and the contract lets the section that defines it
  declare it: the one exception to "never redeclare a known node".

The contract also asks every extractor to declare every node its edges name.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.model import UNDECLARED_TYPE
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
TARGET = {"id": "agente-obedece-datos-maliciosos", "label": "agente obedece datos maliciosos",
          "node_type": "failure"}
EDGE = {"source": "camel", "target": "agente-obedece-datos-maliciosos", "relation": "defends_against",
        "span": "CaMeL defiende al agente de obedecer datos maliciosos", "source_file": "doc.md"}


@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text("## Riesgos\nCaMeL defiende al agente de obedecer datos maliciosos.\n\n"
                   "## Patrones\nCaMeL separa el plan del agente de los datos que lee.\n", encoding="utf-8")
    return KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")


def test_kg_write_reports_the_untyped_node_it_creates(eng):
    out = eng.kg_write({"nodes": [TARGET], "edges": [EDGE], "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 2
    assert out["placeholders"] == ["camel"]
    (camel,) = [n for n in eng.canon.all_nodes() if n.id == "camel"]
    assert (camel.node_type, camel.body) == (UNDECLARED_TYPE, "")


def test_no_placeholder_when_the_node_is_declared_or_already_known(eng):
    declared = eng.kg_write({"nodes": [TARGET, {"id": "camel", "label": "CaMeL", "node_type": "operation"}],
                             "edges": [EDGE], "complete": True})
    assert "placeholders" not in declared
    again = eng.kg_write({"edges": [EDGE], "complete": True})            # camel is in the canon now
    assert "placeholders" not in again


def test_the_next_section_sees_it_marked_untyped(eng):
    eng.kg_write({"nodes": [TARGET], "edges": [EDGE], "complete": True})
    known = {k["id"]: k for k in eng.kg_section("doc.md", 2)["known_nodes"]}
    assert known["camel"]["untyped"] is True


def test_declaring_it_fills_it_in_and_clears_the_mark(eng):
    eng.kg_write({"nodes": [TARGET], "edges": [EDGE], "complete": True})
    out = eng.kg_write({"nodes": [{"id": "camel", "label": "CaMeL", "node_type": "operation",
                                   "body": "Separa el plan del agente de los datos que lee."}], "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 1 and "placeholders" not in out
    (camel,) = [n for n in eng.canon.all_nodes() if n.id == "camel"]
    assert (camel.label, camel.node_type) == ("CaMeL", "operation")
    assert [e.target for e in camel.edges] == ["agente-obedece-datos-maliciosos"]   # its edge survives
    known = {k["id"]: k for k in eng.kg_section("doc.md", 2)["known_nodes"]}
    assert "untyped" not in known["camel"]


def test_a_typed_known_node_carries_no_mark(eng):
    eng.kg_write({"nodes": [TARGET, {"id": "camel", "label": "CaMeL", "node_type": "operation"}],
                  "edges": [EDGE], "complete": True})
    for k in eng.kg_section("doc.md", 2)["known_nodes"]:
        assert "untyped" not in k


def test_the_contract_declares_every_node_and_fills_in_placeholders():
    flat = " ".join(EXTRACTOR.split())
    assert "**Declare in `nodes[]` every node your edges name**" in flat
    assert "a `target` may reference a node you have not created yet" not in flat
    assert "**Except an `untyped: true` one.**" in flat
    assert "`placeholders` in the result → your edges named a node you did not declare" in flat
    cmd = " ".join(CMD.split())
    assert "never redeclare it in nodes[] unless it is marked untyped and your section defines it" in cmd
    assert "**`placeholders` in a kg_write result**" in cmd
