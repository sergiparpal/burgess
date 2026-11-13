"""0.14.1: a record of an edgeless section needs a read of the section's current text, and a section whose only
relations are edges the canon already judged is recorded too.

Field report on 0.14.0 (the Windows corpus, 2026-11-13). Its first plain build showed two gaps.

1. The orchestrator offered to record sections itself. The plan listed 18 sections no extractor had read since
   2026-11-07, a day before the pack gained `enables`. The orchestrator loaded `kg_record_edgeless_section`
   through ToolSearch and asked the user whether to "call kg_record_edgeless_section on each one myself",
   reading none of them. The user did not pick it. Had they, each record would have stored the section's
   digest beside a vocabulary no extractor had read it under. Now the engine records only a section whose
   current text a `kg_section` call (not a leads read) served since it started.

2. A relation the canon already judged kept its section in every plan. The vocabulary section of "Del LLM"
   restates `mecanismo defends_against deficit-del-modelo`, an edge rejected on 2026-11-09 from another
   section's span. kg_write quarantines a re-emit of a judged edge (`collapses-into-known-failure`), so no edge
   quoted the section. Its extractor, told not to record after rejections, left it unrecorded, and every later
   plan would launch an extractor to hit the same quarantine. The extractor contract and the build brief now
   have it record such a section, naming the edge. The engine already accepted that record; the tests below
   pin that it still does.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kg_engine.buildplan import section_digest
from kg_engine.canon import EDGELESS_SECTIONS
from kg_engine.model import edge_id
from kg_engine.server import KGEngine
from kg_engine.sources import plan_sections

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
FILE = "Del LLM.md"
PREMISE = "Cada mecanismo compensa un déficit concreto del modelo"
GLOSS = "cada pieza que se añade para compensar un déficit"
DOC = ("# Del LLM\n\n"
       f"## Mecanismos\n{PREMISE}; cuesta latencia, tokens y mantenimiento.\n\n"
       f"## Vocabulario\n- **Mecanismo:** {GLOSS}.\n- **Arnés:** el entorno que ejecuta al agente.\n\n"
       "## Fuentes\n- Ashby, *An Introduction to Cybernetics*, 1956.\n")
NOTE = "Una lista de fuentes: autores, títulos y años, sin ninguna relación entre conceptos."
EDGE = edge_id("mecanismo", "defends_against", "deficit-del-modelo")
NODES = [{"id": "mecanismo", "label": "Mecanismo", "node_type": "primitive", "body": "Una pieza del andamiaje."},
         {"id": "deficit-del-modelo", "label": "Déficit del modelo", "node_type": "failure",
          "body": "Lo que el modelo no sabe o no puede hacer."}]
READ_ERROR = "no read stands behind the record"


@pytest.fixture
def src(tmp_path: Path) -> Path:
    path = tmp_path / FILE
    path.write_text(DOC, encoding="utf-8")
    return path


@pytest.fixture
def eng(vault: Path, src: Path) -> KGEngine:
    return KGEngine(vault, source_path=src, pack_path=PACK)


def _ledger(e: KGEngine) -> Path:
    return e.canon.root / EDGELESS_SECTIONS


def _rows(plan: dict) -> "dict[str, dict]":
    return {s["title"]: s for f in plan["files"] for s in f["sections"]}


def _to_extract(e: KGEngine) -> "list[str]":
    return [t for t, s in _rows(e.kg_build_plan("", "")).items() if not s["covered"] and "edgeless" not in s]


def _write_edge(e: KGEngine, span: str) -> dict:
    edge = {"source": "mecanismo", "target": "deficit-del-modelo", "relation": "defends_against", "span": span,
            "source_file": FILE}
    return e.kg_write({"nodes": NODES, "edges": [edge]})


def _judge_the_premise(e: KGEngine, verdict: str) -> None:
    assert _write_edge(e, PREMISE)["dispositions"]["ACCEPTED"] == 3
    out = e.kg_ground(EDGE, verdict, note=f"{verdict} for the test: the document's premise")
    assert out["ok"], out


# ---- a record needs a read ---------------------------------------------------------------------------

def test_a_record_nobody_read_is_refused_and_writes_nothing(eng):
    # the field offer: the orchestrator records every planned section itself, reading none of them
    before = eng.kg_build_plan("", "")
    for section in (1, 2, 3):
        out = eng.kg_record_edgeless_section(FILE, section, NOTE)
        assert not out["ok"] and READ_ERROR in out["error"], out
    assert not _ledger(eng).exists()
    assert eng.kg_build_plan("", "") == before


def test_the_extractor_that_read_the_section_records_it(eng):
    assert eng.kg_section(FILE, 3)["ok"]
    out = eng.kg_record_edgeless_section(FILE, 3, NOTE)
    assert out["ok"] and out["title"] == "Fuentes", out
    assert _rows(eng.kg_build_plan("", ""))["Fuentes"]["edgeless"]["note"] == NOTE


def test_a_read_of_another_section_does_not_count(eng):
    assert eng.kg_section(FILE, 2)["ok"]
    out = eng.kg_record_edgeless_section(FILE, 3, NOTE)
    assert not out["ok"] and READ_ERROR in out["error"], out
    assert not _ledger(eng).exists()


def test_a_leads_read_does_not_count(eng):
    # a leads read writes a rejected claim's leads, not the section (the contract's "not in leads mode")
    assert eng.kg_section(FILE, 3, leads=True)["ok"]
    out = eng.kg_record_edgeless_section(FILE, 3, NOTE)
    assert not out["ok"] and READ_ERROR in out["error"], out


def test_a_text_changed_since_the_read_waits_for_a_new_read(eng, src):
    assert eng.kg_section(FILE, 3)["ok"]
    src.write_text(DOC + "- Wiener, *Cybernetics*, 1948.\n", encoding="utf-8")
    out = eng.kg_record_edgeless_section(FILE, 3, NOTE)
    assert not out["ok"] and READ_ERROR in out["error"], out            # nobody read the text it now holds
    assert eng.kg_section(FILE, 3)["ok"]
    assert eng.kg_record_edgeless_section(FILE, 3, NOTE)["ok"]
    line = json.loads(_ledger(eng).read_text(encoding="utf-8"))
    assert line["text_sha256"] == section_digest(plan_sections(src.read_text(encoding="utf-8"))[1][2].text)


def test_a_restarted_engine_waits_for_a_new_read(vault, src):
    first = KGEngine(vault, source_path=src, pack_path=PACK)
    assert first.kg_section(FILE, 3)["ok"]
    restarted = KGEngine(vault, source_path=src, pack_path=PACK)
    out = restarted.kg_record_edgeless_section(FILE, 3, NOTE)
    assert not out["ok"] and READ_ERROR in out["error"], out
    assert restarted.kg_section(FILE, 3)["ok"]
    assert restarted.kg_record_edgeless_section(FILE, 3, NOTE)["ok"]


def test_the_bad_argument_errors_come_first(eng):
    # an unread section with a bad note is told about the note, the thing its caller can fix
    out = eng.kg_record_edgeless_section(FILE, 3, "")
    assert not out["ok"] and "carries a note" in out["error"], out


def test_the_tool_refuses_a_record_nobody_read(eng):
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    from kg_engine.server import _register

    mcp = FastMCP("burgess-test")
    _register(mcp, eng)
    out = asyncio.run(mcp.call_tool("kg_record_edgeless_section",
                                    {"source_file": FILE, "section": 3, "note": NOTE}))
    if isinstance(out, tuple):   # (content, structured) on mcp versions that return both
        out = out[0]
    got = json.loads(out[0].text)
    assert got["ok"] is False and READ_ERROR in got["error"], got
    tools = {t.name: t.description for t in asyncio.run(mcp.list_tools())}
    described = " ".join(tools["kg_record_edgeless_section"].split())
    assert "refused unless kg_section served the section's current text since the engine started" in described
    assert "collapses-into-known-failure or collapses-into-known-verdict" in described


# ---- a relation the canon already judged ---------------------------------------------------------------

@pytest.mark.parametrize("verdict, reason", [("rejected", "collapses-into-known-failure"),
                                             ("grounded", "collapses-into-known-verdict")])
def test_a_relation_the_canon_judged_leaves_its_section_to_record(eng, verdict, reason):
    _judge_the_premise(eng, verdict)
    assert "Mecanismos" not in _to_extract(eng)          # the judged edge's span covers its own section
    # the vocabulary's extractor reads its section and finds the same relation in other words
    assert eng.kg_section(FILE, 2)["ok"]
    out = _write_edge(eng, GLOSS)
    edge = next(d for d in out["details"] if d["kind"] == "edge")
    assert (edge["disposition"], edge["reason"], edge["retryable"]) == ("QUARANTINED", reason, False), out
    assert out["dispositions"]["QUARANTINED"] == 1
    assert "Vocabulario" in _to_extract(eng)             # 0.14.0's dead end: nothing quotes it, so it stays
    note = f"Its one relation, {EDGE}, is already in the canon with a verdict ({reason})."
    assert eng.kg_record_edgeless_section(FILE, 2, note)["ok"]
    assert _to_extract(eng) == ["Fuentes"]
    judged = next(e for e in eng.canon.all_edges() if e.id == EDGE)
    assert judged.epistemic_state.value == verdict and judged.span == PREMISE     # the verdict stands


# ---- the texts that wire it together -----------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    return _flat(text.split(heading, 1)[1].split("\n## ", 1)[0])


def test_the_extractor_records_a_section_whose_relations_the_canon_judged():
    rule = _section(EXTRACTOR, "## A section that states no relation")
    assert "**A relation the canon already judged is nothing new.**" in rule
    assert "`collapses-into-known-failure` (rejected or failed)" in rule
    assert "`collapses-into-known-verdict` (grounded or obsolete)" in rule
    assert "do not rename one of its ends to get past the check" in rule
    assert "If every edge you wrote came back that way, the section holds nothing new to write: record it" in rule
    assert "**Not after rejections.**" in rule                              # 0.14.0's rule stays
    assert "**The engine records only a section it served you** (0.14.1)" in rule


def test_the_retry_policy_tells_the_quarantines_apart():
    procedure = _section(EXTRACTOR, "## Procedure")
    assert "QUARANTINED items used an undeclared type" not in procedure     # through 0.14.0: one reason only
    assert "QUARANTINED `undeclared-node-type` / `undeclared-edge-type`" in procedure
    assert ("QUARANTINED `collapses-into-known-failure` / `collapses-into-known-verdict` → the canon already "
            "holds that edge with a verdict. **FINAL**") in procedure
    assert "one whose every edge collapsed into an edge the canon already judged" in procedure


def test_the_orchestrator_never_records_a_section():
    flat = _flat(CMD)
    assert "**Only the extractor that read a section records it.**" in flat
    assert "Never call `kg_record_edgeless_section` yourself, and never offer the user to" in flat
    allowed = next(ln for ln in CMD.split("---", 2)[1].splitlines() if ln.startswith("allowed-tools:"))
    assert "kg_record_edgeless_section" not in allowed


def test_the_build_brief_names_the_quarantine_and_the_report_its_reasons():
    build = _flat(CMD.split('subagent_type: "kg-extractor"')[1].split('"""\n)', 1)[0])
    assert ("If every edge you wrote comes back QUARANTINED as collapses-into-known-failure or "
            "collapses-into-known-verdict, the canon already holds it with a verdict: do not retry it, and "
            "record the section too, naming that edge's id in the note.") in build
    assert "Do not record a section whose edges kg_write rejected." in build
    report = _flat(CMD.split("### 3. Report", 1)[1].split("\n## ", 1)[0])
    assert ("(`collapses-into-known-failure`: rejected or failed; `collapses-into-known-verdict`: grounded or "
            "obsolete)") in report
