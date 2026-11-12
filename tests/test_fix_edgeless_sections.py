"""0.14.0: a /kg-build section whose extraction wrote no edge is recorded, so later builds do not extract it again
while its text and the pack's types stay the same.

Field report on 0.13.6 (the Windows corpus, 8 documents cut into 84 sections). A section is covered once a
span-present edge quotes it, and a build launches one extractor per section that is not. Some sections state no
relation the pack can type: the six «Fuentes» lists, a vocabulary, a checklist. The build that made the canon,
on 2026-11-07, extracted all 84 sections, and 19 of its extractors wrote no edge. Six sent a `kg_write` with no
node and no edge, two sent none, and eleven wrote nodes alone (the vocabulary wrote ten). None of these leaves a
mark, so on 2026-11-12 a plain build planned 18 of those sections again (the 19th had gained an edge since):
three waves of extractors to read the same text. Only the session's memory note kept it from launching them, by
asking the user first.

Now the extractor records such a section with `kg_record_edgeless_section(source_file, section, note)`: one line
in a ledger beside the canon, keyed by the digests of the section's normalized text and of the pack's node and
edge type names. The plan marks a matching section `edgeless` and leaves it out of the sections to extract. The
record sets no state, and a lost or damaged ledger only brings back the repeat.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_engine.buildplan import (MAX_EDGELESS_NOTE_CHARS, edgeless_record, edgeless_records, section_digest,
                                 vocabulary_digest)
from kg_engine.canon import EDGELESS_SECTIONS
from kg_engine.pack import load_pack
from kg_engine.server import KGEngine
from kg_engine.sources import plan_sections

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
PERTURB = (REPO / "commands" / "kg-perturb.md").read_text(encoding="utf-8")
ARGUMENT = "La fábrica funciona cuando verifica cada cambio"
SOURCES = "## Fuentes\n- Ashby, *An Introduction to Cybernetics*, 1956.\n- Beer, *Brain of the Firm*, 1972.\n"
DOC = ("# Fábricas\n\nNov 5 · @Sergi\n\n"
       f"## Argumento\n{ARGUMENT}.\n\n"
       "## Vocabulario\n- **Oráculo:** lo que decide si una salida es correcta.\n"
       "- **Arnés:** el entorno que ejecuta al agente.\n\n" + SOURCES)
NOTE = "Una lista de fuentes: autores, títulos y años, sin ninguna relación entre conceptos."
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one


@pytest.fixture
def src(tmp_path: Path) -> Path:
    path = tmp_path / "Fábricas de software.md"
    path.write_text(DOC, encoding="utf-8")
    return path


@pytest.fixture
def eng(vault: Path, src: Path) -> KGEngine:
    return KGEngine(vault, source_path=src, pack_path=PACK)


FILE = "Fábricas de software.md"


def _record(e: KGEngine, section: int = 3, note: str = NOTE) -> dict:
    out = e.kg_record_edgeless_section(FILE, section, note)
    assert out["ok"], out
    return out


def _rows(plan: dict) -> "dict[str, dict]":
    return {s["title"]: s for f in plan["files"] for s in f["sections"]}


def _to_extract(plan: dict) -> "list[str]":
    return [t for t, s in _rows(plan).items() if not s["covered"] and "edgeless" not in s]


def _ledger(e: KGEngine) -> Path:
    return e.canon.root / EDGELESS_SECTIONS


def _cover(e: KGEngine, span: str = ARGUMENT) -> None:
    edge = {"source": "fabrica", "target": "verificacion", "relation": "grounds", "span": span, "source_file": FILE}
    assert e.kg_write({"edges": [edge]})["dispositions"]["ACCEPTED"] >= 1


# ---- the plan ----------------------------------------------------------------------------------------

def test_a_recorded_section_leaves_the_plan(eng):
    plan = eng.kg_build_plan("", "1")
    assert (plan["sections_uncovered"], plan["sections_edgeless"], plan["waves"]) == (3, 0, 3)
    out = _record(eng)
    plan = eng.kg_build_plan("", "1")
    assert (plan["sections_uncovered"], plan["sections_edgeless"], plan["waves"]) == (2, 1, 2)
    assert _to_extract(plan) == ["Argumento", "Vocabulario"]
    fuentes = _rows(plan)["Fuentes"]
    assert fuentes["covered"] is False                          # still no edge quotes it: it is not covered
    assert fuentes["edgeless"] == {"at": out["at"], "note": NOTE}


def test_the_field_case(eng):
    # the argued section gets its edge; the vocabulary gets nodes and no edge; the sources get nothing at all
    _cover(eng)
    nodes = [{"id": "oraculo", "label": "Oráculo", "node_type": "primitive", "body": "Decide si una salida es correcta."},
             {"id": "arnes", "label": "Arnés", "node_type": "primitive", "body": "El entorno que ejecuta al agente."}]
    assert eng.kg_write({"nodes": nodes})["dispositions"]["ACCEPTED"] == 2
    assert _to_extract(eng.kg_build_plan("", "")) == ["Vocabulario", "Fuentes"]   # 0.13.6 offered these on every build
    _record(eng, 2, "Un glosario: define dos términos y no relaciona ninguno.")
    _record(eng, 3)
    plan = eng.kg_build_plan("", "")
    assert (plan["sections_uncovered"], plan["sections_edgeless"], plan["waves"]) == (0, 2, 0)


def test_a_changed_text_brings_the_section_back(eng, src):
    _record(eng)
    src.write_text(DOC + "- Wiener, *Cybernetics*, 1948.\n", encoding="utf-8")
    assert "Fuentes" in _to_extract(eng.kg_build_plan("", ""))


def test_a_section_that_moved_keeps_its_record(eng, src):
    _record(eng)
    src.write_text(DOC.replace("## Fuentes", "## Lagunas\nNadie midió el coste.\n\n## Fuentes"), encoding="utf-8")
    rows = _rows(eng.kg_build_plan("", ""))
    assert rows["Fuentes"]["section"] == 4 and "edgeless" in rows["Fuentes"]
    assert "edgeless" not in rows["Lagunas"]


def test_a_new_pack_type_brings_the_section_back(eng):
    _record(eng)
    pack = eng.pack
    eng.pack = pack.model_copy(update={"edge_types": list(reversed(pack.edge_types))})
    assert "Fuentes" not in _to_extract(eng.kg_build_plan("", ""))           # the same types in another order
    eng.pack = pack.model_copy(update={"edge_types": [*pack.edge_types, "contradicts"]})
    assert "Fuentes" in _to_extract(eng.kg_build_plan("", ""))               # a type the extraction lacked
    eng.pack = pack
    assert "Fuentes" not in _to_extract(eng.kg_build_plan("", ""))


def test_an_edge_written_later_makes_the_section_covered(eng):
    _record(eng)
    _cover(eng, "Ashby, *An Introduction to Cybernetics*, 1956")
    plan = eng.kg_build_plan("", "")
    assert _rows(plan)["Fuentes"]["covered"] is True and "edgeless" not in _rows(plan)["Fuentes"]
    assert plan["sections_edgeless"] == 0


def test_a_subset_skips_a_recorded_section_too(eng):
    _record(eng)
    assert _to_extract(eng.kg_build_plan(FILE, "")) == ["Argumento", "Vocabulario"]


def test_the_leads_plan_ignores_the_ledger(eng):
    _record(eng)
    plan = eng.kg_build_plan("--leads", "")
    assert plan["mode"] == "leads" and plan["leads_total"] == 0


def test_a_note_leaves_the_plan_through_the_egress_scrub(eng):
    _record(eng, note=f"Una lista de fuentes; la nota copió la clave {TOKEN} por error.")
    blob = json.dumps(eng.kg_build_plan("", ""), ensure_ascii=False)
    assert TOKEN not in blob and "Una lista de fuentes" in blob


# ---- the record --------------------------------------------------------------------------------------

def test_the_record_is_one_ledger_line(eng):
    out = _record(eng, note=f"  {NOTE[:30]}\n   {NOTE[30:]}  ")
    assert out == {"ok": True, "source_file": FILE, "section": 3, "title": "Fuentes", "at": out["at"]}
    text = plan_sections(DOC)[1][2].text
    assert [json.loads(line) for line in _ledger(eng).read_text(encoding="utf-8").splitlines()] == [
        {"file": FILE, "section": 3, "title": "Fuentes", "text_sha256": section_digest(text),
         "vocabulary_sha256": vocabulary_digest(load_pack(PACK)), "at": out["at"],
         "note": " ".join(NOTE.split())}]


def test_a_section_with_nodes_and_no_edge_can_be_recorded(eng):
    node = {"id": "oraculo", "label": "Oráculo", "node_type": "primitive", "body": "Decide si una salida es correcta."}
    assert eng.kg_write({"nodes": [node]})["dispositions"]["ACCEPTED"] == 1
    assert _record(eng, 2, "Un glosario: define términos y no relaciona ninguno.")["title"] == "Vocabulario"


def test_the_record_sets_no_state(eng):
    _cover(eng)
    notes = {p.name: p.read_bytes() for p in eng.canon.note_paths()}
    before = eng.kg_metrics()
    _record(eng)
    _record(eng, 2, "Un glosario.")
    assert {p.name: p.read_bytes() for p in eng.canon.note_paths()} == notes
    assert eng.kg_metrics() == before


def test_a_covered_section_is_refused(eng):
    _cover(eng)
    out = eng.kg_record_edgeless_section(FILE, 1, NOTE)
    assert not out["ok"] and "already quotes this section" in out["error"], out
    assert not _ledger(eng).exists()


@pytest.mark.parametrize("source_file, section, note, error", [
    ("otro.md", 1, NOTE, "not a configured source file"),
    (FILE, 0, NOTE, "there is no section 0"),
    (FILE, 4, NOTE, "there is no section 4"),
    (FILE, "tres", NOTE, "section must be a section number"),
    (FILE, 3, "", "carries a note"),
    (FILE, 3, " \n\t ", "carries a note"),
    (FILE, 3, "x" * (MAX_EDGELESS_NOTE_CHARS + 1), "over"),
])
def test_a_bad_record_is_refused_and_writes_nothing(eng, source_file, section, note, error):
    out = eng.kg_record_edgeless_section(source_file, section, note)
    assert not out["ok"] and error in out["error"], out
    assert not _ledger(eng).exists()


def test_a_lost_or_damaged_ledger_fails_open(eng):
    _record(eng)
    path = _ledger(eng)
    good = path.read_bytes()
    path.write_bytes(b'not json\n[1, 2]\n{"file": 3}\n\xff\xfe\n' + good + b'{"file": "x", "text_sha')
    assert "Fuentes" not in _to_extract(eng.kg_build_plan("", ""))  # the good record still counts
    path.unlink()
    assert "Fuentes" in _to_extract(eng.kg_build_plan("", ""))      # lost: offered again, as before 0.14.0
    path.mkdir()                                                    # unreadable
    assert "Fuentes" in _to_extract(eng.kg_build_plan("", ""))


def test_the_plan_never_creates_the_ledger(eng):
    eng.kg_build_plan("", "")
    eng.kg_build_plan("--leads", "")
    assert not _ledger(eng).exists()


def test_the_ledger_stays_out_of_git(eng):
    _record(eng)
    exclude = (eng.canon.root / ".git" / "info" / "exclude").read_text(encoding="utf-8").split()
    assert EDGELESS_SECTIONS in exclude
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=eng.canon.root,
                            capture_output=True, text=True, check=True).stdout
    assert EDGELESS_SECTIONS not in status


def test_edgeless_records_reads_what_edgeless_record_writes():
    lines = [edgeless_record("a.md", 1, "Fuentes", "t1", "v", "2026-11-12T10:00:00+00:00", "n1"),
             "", "{}", '{"file": "a.md", "text_sha256": "", "vocabulary_sha256": "v", "at": "t", "note": "n"}',
             edgeless_record("a.md", 2, "Glosario", "t2", "v", "2026-11-12T10:01:00+00:00", "n2"),
             edgeless_record("a.md", 1, "Fuentes", "t1", "v", "2026-11-12T10:02:00+00:00", "n3")]
    assert edgeless_records(lines) == {("a.md", "t1", "v"): {"at": "2026-11-12T10:02:00+00:00", "note": "n3"},
                                       ("a.md", "t2", "v"): {"at": "2026-11-12T10:01:00+00:00", "note": "n2"}}


def test_the_digests():
    pack = load_pack(PACK)
    assert section_digest("## Fuentes\n- Ashby,  1956.") == section_digest("## FUENTES\n- Ashby, 1956.")
    assert section_digest("## Fuentes\n- Ashby, 1956.") != section_digest("## Fuentes\n- Ashby, 1957.")
    reordered = pack.model_copy(update={"node_types": list(reversed(pack.node_types))})
    assert vocabulary_digest(reordered) == vocabulary_digest(pack)
    assert vocabulary_digest(pack.model_copy(update={"node_types": [*pack.node_types, "pregunta"]})) \
        != vocabulary_digest(pack)
    assert vocabulary_digest(None) == ""


def test_the_tool_accepts_what_a_model_sends(eng):
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from kg_engine.server import _register

    mcp = FastMCP("burgess-test")
    _register(mcp, eng)
    out = asyncio.run(mcp.call_tool("kg_record_edgeless_section",
                                    {"source_file": FILE, "section": "3", "note": NOTE}))
    if isinstance(out, tuple):   # (content, structured) on mcp versions that return both
        out = out[0]
    got = json.loads(out[0].text)
    assert (got["ok"], got["section"], got["title"]) == (True, 3, "Fuentes")


# ---- the texts that wire it together -----------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def _frontmatter_tools(text: str) -> "set[str]":
    line = next(ln for ln in text.split("---", 2)[1].splitlines() if ln.startswith("tools:"))
    return {t.strip() for t in line.split(":", 1)[1].split(",")}


def test_the_extractor_records_a_section_it_wrote_no_edge_from():
    assert "mcp__plugin_burgess_burgess__kg_record_edgeless_section" in _frontmatter_tools(EXTRACTOR)
    rule = _flat(EXTRACTOR.split("## A section that states no relation", 1)[1].split("\n## ", 1)[0])
    assert "mcp__plugin_burgess_burgess__kg_record_edgeless_section(source_file=" in rule
    assert "whether you wrote nodes or nothing at all" in rule
    assert "**Not after rejections.**" in rule
    assert "**Not in leads mode,** and not when you are building a second construction (`/kg-perturb`)" in rule
    procedure = _flat(EXTRACTOR.split("## Procedure", 1)[1].split("\n## ", 1)[0])
    assert "kg_record_edgeless_section" in procedure


def test_the_build_brief_asks_for_the_record_and_the_leads_brief_does_not():
    build, leads = (_flat(part.split('"""\n)', 1)[0])
                    for part in CMD.split('subagent_type: "kg-extractor"')[1:3])
    assert "mcp__plugin_burgess_burgess__kg_record_edgeless_section(source_file:" in build
    assert "Do not record a section whose edges kg_write rejected." in build
    assert "Say in your report whether you recorded it." in build
    assert "kg_record_edgeless_section" not in leads
    assert "kg_record_edgeless_section" not in PERTURB


def test_the_build_launches_only_the_sections_to_extract():
    flat = _flat(CMD)
    assert "For **each section to extract in each file of the plan** (`covered` false and no `edgeless`)" in flat
    assert "For **each uncovered section of each file in the plan**" not in flat     # through 0.13.6
    assert "`sections_edgeless`, the ones recorded as holding no edge" in flat
    report = _flat(CMD.split("### 3. Report", 1)[1].split("\n## ", 1)[0])
    assert "**Edgeless sections** — `sections_edgeless`" in report
