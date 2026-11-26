"""0.26.0: a built section whose text changed is extracted again, for what is new.

End-to-end run of 2026-11-25 (Windows, 0.25.1). A sentence stating a new claim was added to a section that was
already built, and `/burgess:kg-build` said all six sections were built and launched nothing. A section counted as
built once a span-present edge quoted it (`covered`), nothing kept the text its extraction had read, and no
argument read a covered section again, so the new claim could never reach the graph.

Now each extraction leaves a record of the units it read (paragraphs, list items, table rows) in a ledger beside
the canon (`canon.READ_SECTIONS`): after its `kg_write`, or its `kg_record_edgeless_section` when the text held
nothing new. The plan marks a covered section `changed` once it holds a unit no record of its file holds, and
`kg_section` hands its extractor those units and the claims already written from the section. A file built before
the ledger existed gets a baseline at its first plan (or its first record): its current text stands for the text
its extraction read. `--again <file>` reads a file's covered sections again, whole. `spans_gone` counts the claims
whose span the notes no longer hold.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.buildplan import (AGAIN_NEEDS_A_FILE, parse_arguments, read_record, read_units, section_digest,
                                 section_units, unit_digest)
from kg_engine.canon import EDGELESS_SECTIONS, READ_SECTIONS
from kg_engine.server import KGEngine
from kg_engine.sources import plan_sections

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

FILE = "Fábricas de software.md"
CLAIM = "La fábrica funciona cuando verifica cada cambio"
SECOND = "El oráculo decide si una salida es correcta"
ADDED = "El arnés aproxima el entorno de producción"
DOC = ("# Fábricas\n\nNov 5 · @Sergi\n\n"
       f"## Argumento\n{CLAIM}.\n\n{SECOND}.\n\n"
       "## Vocabulario\n- **Oráculo:** lo que decide si una salida es correcta.\n"
       "- **Arnés:** el entorno que ejecuta al agente.\n")
NODES = [{"id": "fabrica", "label": "fábrica", "node_type": "claim", "body": "La fábrica de software."},
         {"id": "verificacion", "label": "verificación", "node_type": "operation", "body": "Verificar cada cambio."}]
EDGE = {"source": "fabrica", "target": "verificacion", "relation": "grounds", "span": CLAIM, "source_file": FILE}
NEW_EDGE = {"source": "arnes", "target": "entorno-de-produccion", "relation": "approximates", "span": ADDED,
            "source_file": FILE}
NEW_NODES = [{"id": "arnes", "label": "arnés", "node_type": "primitive", "body": "El entorno del agente."},
             {"id": "entorno-de-produccion", "label": "entorno de producción", "node_type": "primitive",
              "body": "Donde corre el software."}]
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one


@pytest.fixture
def src(tmp_path: Path) -> Path:
    path = tmp_path / FILE
    path.write_text(DOC, encoding="utf-8")
    return path


@pytest.fixture
def eng(vault: Path, src: Path) -> KGEngine:
    return KGEngine(vault, source_path=src, pack_path=PACK)


def _rows(plan: dict) -> "dict[str, dict]":
    return {s["title"]: s for f in plan["files"] for s in f["sections"]}


def _ledger(e: KGEngine) -> Path:
    return e.canon.root / READ_SECTIONS


def _lines(e: KGEngine) -> "list[dict]":
    path = _ledger(e)
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _extract(e: KGEngine, section: int = 1, nodes=NODES, edges=(EDGE,), **kw) -> dict:
    """What a /kg-build extractor does: read its section, then send one kg_write."""
    assert e.kg_section(FILE, section, **kw)["ok"]
    out = e.kg_write({"nodes": list(nodes), "edges": list(edges)})
    assert out["dispositions"]["REJECTED"] == 0, out
    return out


def _edit(src: Path, old: str, new: str) -> None:
    text = src.read_text(encoding="utf-8")
    assert old in text
    src.write_text(text.replace(old, new, 1), encoding="utf-8")


def _built(e: KGEngine) -> None:
    """A section built under 0.26.0: its extraction's write recorded its read."""
    plan = e.kg_build_plan("", "")
    assert plan["sections_uncovered"] == 2 and "baseline" not in plan
    _extract(e)
    assert [ln["by"] for ln in _lines(e)] == ["write"]


# ---- units and records ---------------------------------------------------------------------------------

def test_a_section_is_cut_into_paragraphs_items_and_rows():
    text = ("## Título\nUna frase\npartida en dos líneas.\n\nOtro párrafo.\n\n- uno\n- dos\n  sigue dos\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n")
    assert section_units(text) == ["Una frase\npartida en dos líneas.", "Otro párrafo.", "- uno",
                                   "- dos\n  sigue dos", "| a | b |", "| 1 | 2 |"]
    assert section_units("Sin título.\n") == ["Sin título."]
    assert section_units("## Solo un título\n") == []


def test_a_rewrapped_paragraph_is_the_same_unit_and_a_new_word_is_not():
    assert unit_digest("Una frase partida\nen dos líneas.") == unit_digest("Una frase\npartida en dos líneas.")
    assert unit_digest("Una frase partida en dos líneas.") != unit_digest("Una frase partida en tres líneas.")
    assert len(unit_digest("x")) == 16


def test_read_units_reads_what_read_record_writes():
    good = read_record(FILE, 1, "Argumento", "d" * 64, ["Uno.", "Dos."], "2026-11-25T10:00:00+00:00", "write")
    later = read_record(FILE, 2, "Vocabulario", "e" * 64, ["Tres."], "2026-11-25T11:00:00+00:00", "baseline")
    got = read_units(["not json", "[1]", '{"file": 3}', good, later, '{"file": "x", "units": 1, "at": "t"}',
                      '{"file": "x", "uni'])
    assert got == {FILE: {"units": {unit_digest("Uno."), unit_digest("Dos."), unit_digest("Tres.")},
                          "at": "2026-11-25T11:00:00+00:00",
                          # 0.27.0: the earliest record of each unit, when, by whom, and its audit mark
                          "first": {unit_digest("Uno."): ("2026-11-25T10:00:00+00:00", "write", None),
                                    unit_digest("Dos."): ("2026-11-25T10:00:00+00:00", "write", None),
                                    unit_digest("Tres."): ("2026-11-25T11:00:00+00:00", "baseline", None)}}}
    assert json.loads(good)["by"] == "write"


@pytest.mark.parametrize("line, subset, again, every, problem", [
    ("--again notas.md", "notas.md", True, False, ""),
    ("--again notas.md 4", "notas.md", True, False, ""),
    ("--all --again notas.md", "notas.md", True, True, ""),
    ("--again --all notas.md", "notas.md", True, True, ""),
    ("--again", "", True, False, AGAIN_NEEDS_A_FILE),
    ("--again 4", "", True, False, AGAIN_NEEDS_A_FILE),
    ("--leads --again notas.md", "notas.md", True, False, "do not go together"),
    ("--again --leads notas.md", "notas.md", True, False, "do not go together"),
    ("--again.md", "--again.md", False, False, ""),
])
def test_again_needs_a_file_and_never_goes_with_leads(line, subset, again, every, problem):
    args = parse_arguments(line)
    assert (args.subset, args.again, args.every) == (subset, again, every)
    assert (problem in args.problem) if problem else args.problem == ""


# ---- the plan and the section ----------------------------------------------------------------------

def test_the_field_case_a_claim_added_to_a_built_section_is_extracted(eng, src):
    _built(eng)
    assert eng.kg_build_plan("", "")["sections_changed"] == 0
    _edit(src, f"{SECOND}.\n", f"{SECOND}.\n\n{ADDED}.\n")
    plan = eng.kg_build_plan("", "1")
    row = _rows(plan)["Argumento"]
    assert row["covered"] is True                                     # through 0.25.2: skipped as built
    assert row["changed"] == {"new_units": 1, "of": 3, "since": _lines(eng)[0]["at"]}
    assert (plan["sections_changed"], plan["sections_uncovered"], plan["waves"]) == (1, 1, 2)
    section = eng.kg_section(FILE, 1)
    assert section["changed"]["new"] == [f"{ADDED}."]
    assert section["changed"]["again"] is False and section["changed"]["written_more"] == 0
    assert [(w["id"], w["epistemic_state"], w["span"]) for w in section["changed"]["written"]] == [
        ("e_fabrica__grounds__verificacion", "unverified", CLAIM)]
    out = eng.kg_write({"nodes": NEW_NODES, "edges": [NEW_EDGE]})
    assert out["dispositions"]["ACCEPTED"] == 3
    plan = eng.kg_build_plan("", "")
    assert "changed" not in _rows(plan)["Argumento"] and plan["sections_changed"] == 0
    assert [ln["by"] for ln in _lines(eng)] == ["write", "write"]


def test_a_sentence_appended_to_a_paragraph_makes_that_paragraph_new(eng, src):
    _built(eng)
    _edit(src, f"{SECOND}.", f"{SECOND}. {ADDED}.")
    assert _rows(eng.kg_build_plan("", ""))["Argumento"]["changed"]["new_units"] == 1
    assert eng.kg_section(FILE, 1)["changed"]["new"] == [f"{SECOND}. {ADDED}."]


@pytest.mark.parametrize("old, new", [
    ("## Argumento\n", "## El argumento\n"),                                  # a new heading only
    (f"{CLAIM}.\n\n{SECOND}.\n", f"{SECOND}.\n\n{CLAIM}.\n"),                 # the same paragraphs, reordered
    (f"\n\n{SECOND}.\n", "\n"),                                               # a paragraph deleted
    (f"{SECOND}.", SECOND.replace(" si una", "\nsi una") + "."),             # re-wrapped
])
def test_text_with_nothing_new_in_it_is_not_changed(eng, src, old, new):
    _built(eng)
    _edit(src, old, new)
    plan = eng.kg_build_plan("", "")
    assert plan["sections_changed"] == 0, _rows(plan)


def test_nothing_new_is_recorded_as_a_read_and_the_section_leaves_the_plan(eng, src):
    _built(eng)
    _edit(src, f"{SECOND}.", f"{SECOND}, y nada más.")
    assert eng.kg_build_plan("", "")["sections_changed"] == 1
    assert not eng.kg_record_edgeless_section(FILE, 1, "Nada nuevo.")["ok"]     # no read of this text yet
    assert eng.kg_section(FILE, 1)["changed"]["new"] == [f"{SECOND}, y nada más."]
    out = eng.kg_record_edgeless_section(FILE, 1, "El texto nuevo no afirma ninguna relación nueva.")
    assert out["ok"] and out["recorded"] == "read", out
    assert eng.kg_build_plan("", "")["sections_changed"] == 0
    assert [ln["by"] for ln in _lines(eng)] == ["write", "record"]
    assert not (eng.canon.root / EDGELESS_SECTIONS).exists()


def test_an_extractor_that_stopped_before_writing_leaves_the_section_changed(eng, src):
    _built(eng)
    _edit(src, f"{SECOND}.\n", f"{SECOND}.\n\n{ADDED}.\n")
    assert eng.kg_section(FILE, 1)["changed"]                       # read, then nothing: a crash, a cancel
    assert eng.kg_build_plan("", "")["sections_changed"] == 1
    assert len(_lines(eng)) == 1


def test_a_write_nobody_read_a_section_for_records_nothing(eng):
    eng.kg_build_plan("", "")
    assert eng.kg_write({"nodes": NODES, "edges": [EDGE]})["dispositions"]["ACCEPTED"] == 3
    assert _lines(eng) == []
    assert eng.kg_section(FILE, 1, leads=True)["ok"]                # a leads read is not an extraction's
    eng.kg_write({"nodes": NODES, "edges": [EDGE]})
    assert _lines(eng) == []


def test_an_uncovered_section_is_extracted_whole_as_ever(eng):
    eng.kg_build_plan("", "")
    section = eng.kg_section(FILE, 1)
    assert "changed" not in section
    assert eng.kg_section(FILE, 2, again=True).get("changed") is None


def test_the_changed_text_leaves_through_the_scrub(eng, src):
    _built(eng)
    _edit(src, f"{SECOND}.\n", f"{SECOND}.\n\nEl token {TOKEN} abre el arnés.\n")
    changed = eng.kg_section(FILE, 1)["changed"]
    blob = json.dumps(changed, ensure_ascii=False)
    assert TOKEN not in blob and "⟦SECRET:" in blob
    assert TOKEN not in json.dumps(eng.kg_build_plan("", ""), ensure_ascii=False)


# ---- a canon built before 0.26.0 -----------------------------------------------------------------------

def _legacy(e: KGEngine) -> None:
    """Edges written with no kg_section read: a build before 0.26.0, or the headless backend."""
    vocab = [{"id": "oraculo", "label": "Oráculo", "node_type": "primitive", "body": "Decide."},
             {"id": "salida-correcta", "label": "salida correcta", "node_type": "primitive", "body": "Correcta."}]
    defined = {"source": "oraculo", "target": "salida-correcta", "relation": "grounds",
               "span": "lo que decide si una salida es correcta", "source_file": FILE}
    assert e.kg_write({"nodes": NODES + vocab, "edges": [EDGE, defined]})["dispositions"]["REJECTED"] == 0
    assert _lines(e) == []


def test_a_canon_built_before_gets_a_baseline_once(eng, src):
    _legacy(eng)
    plan = eng.kg_build_plan("", "")
    assert plan["baseline"] == {"sections": 2, "files": [FILE]}
    assert plan["sections_changed"] == 0 and plan["sections_uncovered"] == 0
    assert [(ln["section"], ln["by"]) for ln in _lines(eng)] == [(1, "baseline"), (2, "baseline")]
    assert "baseline" not in eng.kg_build_plan("", "")
    _edit(src, f"{SECOND}.\n", f"{SECOND}.\n\n{ADDED}.\n")                  # an edit after the baseline
    assert _rows(eng.kg_build_plan("", ""))["Argumento"]["changed"]["new_units"] == 1


def test_an_edit_made_before_the_baseline_goes_unseen_and_again_reads_it(eng, src):
    _legacy(eng)
    _edit(src, f"{SECOND}.\n", f"{SECOND}.\n\n{ADDED}.\n")                  # edited before 0.26.0's first plan
    assert eng.kg_build_plan("", "")["sections_changed"] == 0
    plan = eng.kg_build_plan(f"--again {FILE}", "")
    assert plan["again"] is True and plan["sections_changed"] == 2
    assert _rows(plan)["Argumento"]["changed"] == {"again": True, "units": 3}
    changed = eng.kg_section(FILE, 1, again=True)["changed"]
    assert changed["again"] is True and changed["new"] == [f"{CLAIM}.", f"{SECOND}.", f"{ADDED}."]
    assert [w["id"] for w in changed["written"]] == ["e_fabrica__grounds__verificacion"]


def test_the_first_record_of_a_file_lays_its_baseline_too(eng, src):
    _legacy(eng)
    _edit(src, f"{SECOND}.\n", f"{SECOND}.\n\n{ADDED}.\n")
    _extract(eng, 1, NEW_NODES, [NEW_EDGE])                                 # no plan ran first
    assert [(ln["section"], ln["by"]) for ln in _lines(eng)] == [(2, "baseline"), (1, "write")]
    plan = eng.kg_build_plan("", "")
    assert plan["sections_changed"] == 0 and "baseline" not in plan        # section 2 does not look new


def test_a_held_lease_leaves_the_baseline_for_later(eng, monkeypatch):
    _legacy(eng)
    monkeypatch.setattr(eng.canon, "try_acquire_lock", lambda: False)
    plan = eng.kg_build_plan("", "")
    assert plan["baseline"] == {"sections": 0, "files": [], "not_recorded": 2}
    assert plan["sections_changed"] == 0 and _lines(eng) == []
    monkeypatch.undo()
    assert eng.kg_build_plan("", "")["baseline"]["sections"] == 2


def test_a_lost_or_damaged_ledger_fails_open(eng, src):
    _built(eng)
    path = _ledger(eng)
    path.write_bytes(b'not json\n\xff\xfe\n' + path.read_bytes() + b'{"file": "x", "uni')
    assert eng.kg_build_plan("", "")["sections_changed"] == 0               # the good record still counts
    path.unlink()
    plan = eng.kg_build_plan("", "")                                        # lost: a new baseline
    assert plan["baseline"]["sections"] == 1 and plan["sections_changed"] == 0
    path.unlink()
    path.mkdir()                                                            # unreadable, unwritable
    plan = eng.kg_build_plan("", "")
    assert plan["ok"] and plan["baseline"] == {"sections": 0, "files": [], "not_recorded": 1}


def test_the_ledger_stays_out_of_git(eng):
    _built(eng)
    exclude = (eng.canon.root / ".git" / "info" / "exclude").read_text(encoding="utf-8").split()
    assert READ_SECTIONS in exclude
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=eng.canon.root,
                            capture_output=True, text=True, check=True).stdout
    assert READ_SECTIONS not in status
    assert READ_SECTIONS in (REPO / ".gitignore").read_text(encoding="utf-8").split()


def test_the_record_holds_the_digests_of_what_was_read(eng):
    _built(eng)
    text = plan_sections(DOC)[1][0].text
    (line,) = _lines(eng)
    assert line == {"file": FILE, "section": 1, "title": "Argumento", "text_sha256": section_digest(text),
                    "units": [unit_digest(f"{CLAIM}."), unit_digest(f"{SECOND}.")], "at": line["at"],
                    "by": "write", "audit_mark": 0}           # 0.27.0: the audit log's size then (none yet)


# ---- claims whose sentence is gone -------------------------------------------------------------------

def test_the_plan_counts_the_claims_whose_span_is_gone(eng, src):
    _built(eng)
    assert "spans_gone" not in eng.kg_build_plan("", "")
    out = eng.kg_ground("e_fabrica__grounds__verificacion", "grounded", note="grounded for the test")
    assert out["ok"], out
    _edit(src, f"{CLAIM}.", "La fábrica funciona cuando alguien lo comprueba.")
    plan = eng.kg_build_plan("", "")
    assert plan["spans_gone"] == {"grounded": 1, "unverified": 0,
                                  "grounded_ids": ["e_fabrica__grounds__verificacion"]}
    assert plan["sections_uncovered"] == 2                                  # no span of it is left


def test_kg_section_refuses_again_with_leads_or_a_construction(eng):
    assert "do not go together" in eng.kg_section(FILE, 1, leads=True, again=True)["error"]
    out = eng.kg_section(FILE, 1, construction="otra", source=str(REPO / "examples" / "source.md"), again=True)
    assert not out["ok"] and "not a second construction" in out["error"]


def test_the_tool_accepts_again(eng):
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from kg_engine.server import _register

    _built(eng)
    mcp = FastMCP("burgess-test")
    _register(mcp, eng)
    out = asyncio.run(mcp.call_tool("kg_section", {"source_file": FILE, "section": 1, "again": True}))
    if isinstance(out, tuple):   # (content, structured) on mcp versions that return both
        out = out[0]
    got = json.loads(out[0].text)
    assert got["ok"] and got["changed"]["again"] is True and len(got["changed"]["new"]) == 2


# ---- the texts that wire it together -----------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_build_extracts_the_changed_sections_and_says_so():
    flat = _flat(CMD)
    assert "**`--again` as the first word** (0.26.0)" in flat
    assert "unless it has `changed`. A section with `changed` (0.26.0) was extracted before" in flat
    assert "`sections_changed` (0.26.0), the covered ones to extract again" in flat
    assert "When the plan has `baseline`, say in a sentence" in flat
    assert "When it has `spans_gone`, say how many claims quote a sentence the notes no longer hold." in flat
    brief = _flat(CMD.split('subagent_type: "kg-extractor"', 1)[1].split('"""\n)', 1)[0])
    assert "again: false # true only when the plan has `again`" in brief
    assert "(adding again: true when the line above says so)" in brief
    assert "If kg_section returns `changed`" in brief and "leave out every claim `changed.written` already holds" in brief
    report = _flat(CMD.split("### 3. Report", 1)[1].split("\n## ", 1)[0])
    assert "**Changed sections** (0.26.0)" in report


def test_the_extractor_writes_only_what_is_new():
    rule = _flat(EXTRACTOR.split("## A section read again", 1)[1].split("\n## ", 1)[0])
    assert "Write the claims `changed.new` states, and nothing else." in rule
    assert "Leave out a claim `changed.written` already holds" in rule
    assert "a judged one comes back QUARANTINED, which is final" in rule
    assert "the engine records your read" in rule
    procedure = _flat(EXTRACTOR.split("## Procedure", 1)[1].split("\n## ", 1)[0])
    assert "When it carries `changed`, write only what `changed.new` states" in procedure
    edgeless = _flat(EXTRACTOR.split("## A section that states no relation", 1)[1].split("\n## ", 1)[0])
    assert "the engine records your read of it (`recorded: \"read\"`)" in edgeless
    assert "The engine refuses a section an edge already quotes" not in edgeless    # through 0.25.2


def test_the_reference_documents_the_fields():
    flat = _flat(TOOLS)
    for field in ("`sections_changed`", "`changed`", "`baseline`", "`spans_gone`", "`--again`",
                  '"recorded": "read"', ".kg-read-sections.jsonl"):
        assert field in flat, field
