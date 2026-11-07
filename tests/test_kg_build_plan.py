"""0.5.0: /kg-build plans and cuts its sections in the engine, so the build needs no shell.

Field report on 0.4.6 (a Windows install in auto mode): every /kg-build asked for permission over and over,
and stalled until the user answered. Claude Code's auto mode ignores a command's `Bash` permission (and its
`Task` one), because a tool-wide grant would let the model step around the classifier; every Bash call
therefore went to the classifier, and the ones it did not clear became prompts. The Step 0b block waited
3.5 minutes on one run and passed in a second on another. The orchestrator's own helper scripts, which cut
the document into section files and applied the scrub to them because the command asked it to copy each
section verbatim twice, waited up to 11 minutes each, about 32 minutes in one build. MCP tools the command
declares are honored in auto mode, so the fix moves the work into two of them:

- `kg_build_plan(arguments, configured_wave_size)`: the files, their sections, coverage and the wave size;
- `kg_section(source_file, section)`: one section's text, cut and egress-scrubbed by the engine, which the
  extractor fetches itself, so no section text passes through the orchestrator at all.

The pins below cover the argument rules, the subset rules, that a plan's section N is the text kg_section
serves for N, the scrub/restore round trip through kg_section, coverage per file and section, egress, the
scrub lock, and the command and agent texts that wire it together.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from kg_engine.buildplan import parse_arguments, resolve_subset
from kg_engine.model import Edge, Node
from kg_engine.server import KGEngine
from kg_engine.sources import SourceSet, plan_sections, split_sections

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one
TOKEN2 = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"

DOC = (
    "# Fábricas\n\nNov 5 · @Sergi\n\n"
    "## Resumen\nLa fábrica funciona cuando verifica.\n\n"
    f"## Evidencia\nSin grupo de control. Clave {TOKEN} en la nota.\n\n"
    "```bash\n## no es una sección\n```\n\n"
    "## Qué aprender\nEmpieza por lo determinista.\n"
)
REVIEW = "# Revisión\n\n## Casos\nSin grupo de control.\n\n## Coste\nNada que ver.\n"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    d = tmp_path / "fuente con espacios"
    d.mkdir()
    (d / "Fábricas de software.md").write_text(DOC, encoding="utf-8")
    (d / "Revisión humana.md").write_text(REVIEW, encoding="utf-8")
    return d


@pytest.fixture
def eng(vault: Path, folder: Path) -> KGEngine:
    return KGEngine(vault, source_path=folder)


# ---- the typed line ------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,subset,wave", [
    ("", "", ""),
    ("   ", "", ""),
    ("4", "", "4"),                                                  # a lone whole number: the wave size
    ("notas.md", "notas.md", ""),
    ("notas.md 4", "notas.md", "4"),
    ("Fábricas de software qué son.md 4", "Fábricas de software qué son.md", "4"),   # the field report's line
    ("Fábricas de software qué son.md", "Fábricas de software qué son.md", ""),
    ('"capítulo 3"', "capítulo 3", ""),                              # a quoted name keeps its number
    ('"capítulo 3" 5', "capítulo 3", "5"),
    ("capítulo 3", "capítulo", "3"),                                 # ...and an unquoted one loses it
    ("'notas con espacios.md' 2", "notas con espacios.md", "2"),
    ('""doble.md""', "doble.md", ""),                                # peeled repeatedly, like envconfig
    ("notas 2.md", "notas 2.md", ""),
    ('"sin cerrar.md', '"sin cerrar.md', ""),                       # unbalanced: kept as typed
])
def test_the_arguments_line_splits_into_a_subset_and_a_wave_size(raw, subset, wave):
    assert parse_arguments(raw) == parse_arguments(raw)              # pure
    got = parse_arguments(raw)
    assert (got.subset, got.wave_size, got.problem) == (subset, wave, "")


@pytest.mark.parametrize("raw", ['"a.md" "b.md"', "'a.md' 'b.md' 4"])
def test_two_quoted_parts_are_refused(raw):
    assert "two or more quoted parts" in parse_arguments(raw).problem


def test_a_non_ascii_digit_is_not_a_wave_size():
    # `[0-9]`, never `\d`: an Arabic-Indic four would otherwise split off and then resolve to the default.
    got = parse_arguments("notas.md ٤")
    assert (got.subset, got.wave_size) == ("notas.md ٤", "")


# ---- the subset ----------------------------------------------------------------------------------

def test_no_subset_selects_every_configured_file_in_source_order(folder, tmp_path):
    names, problems = resolve_subset("", project_dir=tmp_path, declared=SourceSet.resolve(folder))
    assert (names, problems) == (SourceSet(folder).basenames, [])


def test_a_bare_name_matches_a_configured_file_from_any_project_folder(folder, tmp_path):
    elsewhere = tmp_path / "otro proyecto"
    elsewhere.mkdir()
    names, problems = resolve_subset("Revisión humana.md", project_dir=elsewhere,
                                     declared=SourceSet.resolve(folder))
    assert (names, problems) == (["Revisión humana.md"], [])


def test_a_glob_over_names_matches_configured_files(folder, tmp_path):
    names, _ = resolve_subset("F*.md", project_dir=tmp_path / "nada", declared=SourceSet.resolve(folder))
    assert names == ["Fábricas de software.md"]


def test_a_missing_folder_never_falls_back_to_matching_names(folder, tmp_path):
    # `otra/*.md` meant a folder that does not exist: matching `*.md` against every configured file
    # instead would build files the user never pointed at.
    names, problems = resolve_subset("otra/*.md", project_dir=tmp_path, declared=SourceSet.resolve(folder))
    assert names == []
    assert problems == ["the subset 'otra/*.md' matched no file of the configured source"]


def test_an_empty_heading_is_an_untitled_section_not_the_whole_file(vault, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("## \nsin título\n\n## B\nbe\n", encoding="utf-8")
    plan = KGEngine(vault, source_path=src).kg_build_plan("", "")
    (f,) = plan["files"]
    assert [s["title"] for s in f["sections"]] == ["(untitled)", "B"]
    assert "note" not in f


def test_the_folder_itself_is_the_whole_source(folder, tmp_path):
    names, problems = resolve_subset(str(folder), project_dir=tmp_path, declared=SourceSet.resolve(folder))
    assert (sorted(names), problems) == (sorted(SourceSet(folder).basenames), [])


# ---- plan and section agree ----------------------------------------------------------------------

def test_the_plan_numbers_exactly_the_sections_kg_section_serves(eng, folder):
    plan = eng.kg_build_plan("", "")
    assert plan["ok"], plan
    for f in plan["files"]:
        level, secs = plan_sections((folder / f["file"]).read_text(encoding="utf-8"))
        assert f["heading_level"] == level
        for row in f["sections"]:
            got = eng.kg_section(f["file"], row["section"])
            assert got["ok"], got
            assert (got["section"], got["of"]) == (row["section"], len(secs))
            assert got["title"] == row["title"] or "⟦" in got["title"]
            assert got["text"].splitlines()[0].lstrip("#").strip() == got["title"]


def test_the_preamble_and_a_fenced_heading_are_not_sections(eng):
    plan = eng.kg_build_plan("Fábricas de software.md", "")
    (f,) = plan["files"]
    assert [s["title"] for s in f["sections"]] == ["Resumen", "Evidencia", "Qué aprender"]
    assert "Nov 5" not in json.dumps(plan, ensure_ascii=False)


def test_a_section_is_the_sources_own_text_heading_included(eng, folder):
    raw = (folder / "Revisión humana.md").read_text(encoding="utf-8")
    got = eng.kg_section("Revisión humana.md", 1)
    assert got["text"] == "## Casos\nSin grupo de control.\n"
    assert got["text"] in raw
    assert (got["redactions"], got["categories"]) == (0, [])


def test_split_sections_is_unchanged_by_the_refactor():
    # split_sections and plan_sections now share sources._chunks; the historic shape must hold.
    assert split_sections(DOC, preamble_title="(p)")[0][0] == "(p)"
    assert [t for t, _ in split_sections(DOC)][1:] == ["Resumen", "Evidencia", "Qué aprender"]
    assert split_sections("## A\nx", include_heading=True) == [("A", "## A\nx")]
    assert split_sections("﻿## A\nx") == [("A", "x")]
    assert split_sections("## \nx", preamble_title="(p)") == [("(p)", "x")]


# ---- the scrub, through kg_section ---------------------------------------------------------------

def test_kg_section_scrubs_and_kg_write_restores(eng):
    got = eng.kg_section("Fábricas de software.md", 2)
    assert TOKEN not in got["text"]
    assert (got["redactions"], got["categories"]) == (1, ["SECRET"])
    ph = re.search(r"⟦SECRET:\d+⟧", got["text"]).group(0)
    # the extractor copies its span from the scrubbed text, placeholder included
    span = f"Clave {ph} en la nota."
    res = eng.kg_write({"edges": [{"source": "evidencia", "target": "clave", "relation": "grounds",
                                   "provenance": "span-present", "authored_by": "agent", "span": span,
                                   "source_file": "Fábricas de software.md"}], "complete": True})
    assert res["dispositions"]["ACCEPTED"] >= 1, res
    stored = next(e.span for e in eng.canon.all_edges() if e.relation == "grounds")
    assert stored == f"Clave {TOKEN} en la nota."


def test_a_secret_in_a_heading_never_leaves_raw(vault, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(f"## Clave {TOKEN}\ntexto\n\n## Otra\nmás\n", encoding="utf-8")
    eng = KGEngine(vault, source_path=src)
    plan = eng.kg_build_plan("", "")
    assert TOKEN not in json.dumps(plan)
    got = eng.kg_section("doc.md", 1)
    assert TOKEN not in json.dumps(got)
    assert got["title"].startswith("Clave ⟦SECRET:")
    assert got["text"].startswith(f"## {got['title']}\n")     # one placeholder for one value, title and text


def test_concurrent_sections_keep_one_placeholder_per_value(vault, tmp_path):
    # A whole wave asks for its sections at once. However the transport schedules those calls, each value
    # must keep one placeholder, and every placeholder must restore to its own value (the scrub lock).
    src = tmp_path / "doc.md"
    src.write_text("".join(f"## S{i}\nuno {TOKEN} dos {TOKEN2} fin\n\n" for i in range(12)), encoding="utf-8")
    eng = KGEngine(vault, source_path=src)
    results: "dict[int, dict]" = {}

    def fetch(i: int) -> None:
        results[i] = eng.kg_section("doc.md", i)

    threads = [threading.Thread(target=fetch, args=(i,)) for i in range(1, 13)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bodies = {r["text"].split("\n", 1)[1] for r in results.values()}
    assert len(bodies) == 1, bodies                       # every section scrubbed to the same placeholders
    phs = re.findall(r"⟦SECRET:\d+⟧", bodies.pop())
    assert len(set(phs)) == 2
    assert {eng._scrub_map[p] for p in phs} == {TOKEN, TOKEN2}


# ---- coverage in the plan ------------------------------------------------------------------------

def _seed(eng: KGEngine, span: str, source_file: str) -> None:
    eng.canon.write_nodes([Node(id="a", edges=[Edge(source="a", target="b", relation="grounds", span=span,
                                                    source_file=source_file)]), Node(id="b")], message="seed")


def _covered(plan: dict) -> set:
    return {(f["file"], s["title"]) for f in plan["files"] for s in f["sections"] if s["covered"]}


def test_coverage_counts_a_span_toward_its_own_file_and_section(eng):
    _seed(eng, "Sin grupo de control.", "Fábricas de software.md")
    plan = eng.kg_build_plan("", "")
    assert _covered(plan) == {("Fábricas de software.md", "Evidencia")}   # not Revisión's «Casos»
    assert plan["sections_uncovered"] == plan["sections_total"] - 1


def test_an_unattributed_span_still_covers_any_file(eng):
    _seed(eng, "Sin grupo de control.", "")
    assert _covered(eng.kg_build_plan("", "")) == {("Fábricas de software.md", "Evidencia"),
                                                   ("Revisión humana.md", "Casos")}


def test_a_span_from_the_heading_covers_its_section(eng):
    _seed(eng, "Qué aprender", "Fábricas de software.md")
    assert _covered(eng.kg_build_plan("", "")) == {("Fábricas de software.md", "Qué aprender")}


def test_the_plan_carries_no_section_text(eng):
    blob = json.dumps(eng.kg_build_plan("", ""), ensure_ascii=False)
    assert "La fábrica funciona" not in blob and "Empieza por lo determinista" not in blob


# ---- refusals ------------------------------------------------------------------------------------

def test_kg_section_refuses_what_the_plan_did_not_list(eng):
    assert eng.kg_section("otro.md", 1)["ok"] is False
    assert "no section 9" in eng.kg_section("Revisión humana.md", 9)["error"]
    assert eng.kg_section("Revisión humana.md", 0)["ok"] is False
    assert eng.kg_section("Revisión humana.md", "dos")["ok"] is False


def test_an_unreadable_file_is_skipped_from_a_whole_build_and_refused_as_a_subset(eng, folder):
    (folder / "utf16.txt").write_bytes("## Hola\n".encode("utf-16"))
    plan = eng.kg_build_plan("", "")
    assert plan["ok"] and plan["skipped"] == ["utf16.txt"]
    refused = eng.kg_build_plan("utf16.txt", "")
    assert refused["ok"] is False
    assert "could not be read as UTF-8" in refused["error"]


# ---- through the real MCP tool layer -------------------------------------------------------------

def _call(mcp, name: str, args: dict) -> dict:
    import asyncio

    out = asyncio.run(mcp.call_tool(name, args))
    if isinstance(out, tuple):   # (content, structured) on mcp versions that return both
        out = out[0]
    return json.loads(out[0].text)


def test_the_tools_accept_what_a_model_sends(eng):
    # Argument validation happens in FastMCP before the facade runs: a model may send the option as a
    # number or the section as a string, and neither may turn into a validation error.
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    from kg_engine.server import _register

    mcp = FastMCP("burgess-test")
    _register(mcp, eng)
    for cfg in (3, "3"):
        plan = _call(mcp, "kg_build_plan", {"arguments": "", "configured_wave_size": cfg})
        assert (plan["ok"], plan["wave_size"], plan["wave_size_from"]) == (True, 3, "option")
    unset = _call(mcp, "kg_build_plan", {"arguments": "Revisión humana.md 2",
                                         "configured_wave_size": "${user_config.extract_wave_size}"})
    assert (unset["wave_size"], unset["wave_size_from"]) == (2, "argument")
    for section in (2, "2"):
        got = _call(mcp, "kg_section", {"source_file": "Revisión humana.md", "section": section})
        assert (got["ok"], got["title"]) == (True, "Coste")


# ---- the texts that wire it together -------------------------------------------------------------

def _frontmatter_line(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.*)$", text.split("---", 2)[1], re.M)
    assert m, key
    return m.group(1)


def test_kg_build_declares_no_shell_and_no_file_access():
    allowed = {t.strip() for t in _frontmatter_line(CMD, "allowed-tools").split(",")}
    assert allowed == {"Task"} | {f"mcp__plugin_burgess_burgess__{t}" for t in
                                  ("kg_build_plan", "kg_status", "kg_metrics", "kg_context", "query_graph")}
    assert "```bash" not in CMD
    flat = " ".join(CMD.split())
    assert "This command needs no shell and no file access." in flat
    assert "Never paste section text into a prompt." in flat
    assert "SECTION TEXT" not in CMD                     # the 0.4.x inline-text launch template is gone


def test_kg_build_passes_the_typed_line_to_the_plan_verbatim():
    assert "**Arguments, as typed:** `$ARGUMENTS`" in CMD
    assert "Do not split that line yourself" in CMD
    assert 'arguments: "<the arguments line above, verbatim; empty if nothing was typed>"' in CMD


def test_the_extractor_fetches_its_own_section():
    tools = {t.strip() for t in _frontmatter_line(EXTRACTOR, "tools").split(",")}
    assert "mcp__plugin_burgess_burgess__kg_section" in tools
    assert "mcp__plugin_burgess_burgess__kg_section(source_file, section)" in EXTRACTOR
    # the launch template tells it how
    assert 'mcp__plugin_burgess_burgess__kg_section(source_file: "source.md", section: 1)' in CMD
