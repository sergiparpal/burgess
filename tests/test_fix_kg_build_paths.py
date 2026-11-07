"""Regression: /kg-build enumerates a source whose path holds spaces, and its argument is a subset of the
configured source, not a replacement for it.

Found on a Windows install whose sources sat under `Documents\\Proyectos personales\\prueba-burgess`, with
spaces and accents in the file names as well. The Step 0b script of 0.4.3 word-split every path.
`ls -1 $SOURCE` (unquoted, there to expand a glob) cut a single-file source in two, so it found nothing, and
`for f in $FILES` cut every enumerated path at its spaces, so the per-file heading scan ran over fragments
that name nothing (`grep: personales/prueba: No such file or directory`). 0.4.4 kept one path per line end
to end, and matched extensions case-insensitively, as the engine does.

The same report caught the command promising that its argument overrides the configured source, while
`kg_write` verifies every span against the configured `source_path` only (the engine's SourceSet, keyed by
basename): a file outside it gets every edge REJECTED `span-not-in-source`. The argument is a subset, checked
against the configured files before any extractor runs, and the command says how to change `source_path`
(and that Claude Code must restart to pick it up).

Since 0.5.0 there is no Step 0b script to split anything: `kg_build_plan` resolves the source and the
subset in the engine, with `SourceSet.resolve`, the same rule that resolves `source_path` itself. These
tests pin the same properties against it: whole paths with spaces and accents, the engine's own file list,
a quoted path, a loud failure for a missing source, and a subset that never reaches past the configured
files.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from kg_engine.server import KGEngine
from kg_engine.sources import SourceSet

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
FLAT = " ".join(CMD.split())  # the text with its line wrapping undone, for phrase checks
PACK = REPO / "pack" / "pack.yaml"

# name -> content. The directory's own path holds a space too (see `corpus`), like the reporting install.
FILES = {
    "Cómo se desarrolla software.md": "# Título\n\n## Uno\nx\n\n## Dos\ny\n",
    "fronteras-de-centralizacion.md": "# Título\n\n## A\n\n## B\n\n## C\n",
    "notas.txt": "## Nota 1\n\n## Nota 2\n",
    "MAYÚSCULAS.MD": "## M1\n\n## M2\n",
    ".oculto.md": "## hidden\n",      # dotfile: skipped by the engine
    "imagen.png": "png",               # not .md/.txt
}
SOURCES = {"Cómo se desarrolla software.md", "fronteras-de-centralizacion.md", "notas.txt", "MAYÚSCULAS.MD"}


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    d = tmp_path / "Proyectos personales" / "prueba burgess"
    d.mkdir(parents=True)
    for name, text in FILES.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def _plan(vault: Path, source, arguments: str = "") -> dict:
    return KGEngine(vault, source_path=source, pack_path=PACK).kg_build_plan(arguments, "")


def _titles(plan: dict) -> "dict[str, list[str]]":
    return {f["file"]: [s["title"] for s in f["sections"]] for f in plan["files"]}


def _headings(name: str) -> list[str]:
    return [ln[3:] for ln in FILES[name].splitlines() if ln.startswith("## ")]


def test_a_directory_whose_path_holds_spaces_lists_every_file_whole(corpus, vault):
    plan = _plan(vault, corpus)
    assert plan["ok"], plan
    assert set(_titles(plan)) == SOURCES
    for name in SOURCES:
        assert _titles(plan)[name] == _headings(name), name


def test_the_file_list_is_the_engines_own(corpus, vault):
    # The plan's files are the configured source exactly as span verification sees it: case-insensitive
    # .md/.txt, dotfiles skipped, in SourceSet order.
    plan = _plan(vault, corpus)
    assert [f["file"] for f in plan["files"]] == SourceSet(corpus).basenames
    assert plan["source"]["files"] == SourceSet(corpus).basenames


def test_a_single_file_whose_path_holds_spaces_is_taken_whole(corpus, vault):
    name = "Cómo se desarrolla software.md"
    plan = _plan(vault, corpus / name)
    assert plan["ok"], plan
    assert _titles(plan) == {name: _headings(name)}


def test_an_unquoted_subset_with_spaces_and_a_wave_size_is_one_path(corpus, vault):
    # The typed line of the field report: an unquoted name with spaces, then the wave size.
    name = "Cómo se desarrolla software.md"
    plan = _plan(vault, corpus, f"{corpus / name} 4")
    assert plan["ok"], plan
    assert (plan["subset"], plan["wave_size"], plan["wave_size_from"]) == (str(corpus / name), 4, "argument")
    assert _titles(plan) == {name: _headings(name)}


def test_a_glob_whose_directory_holds_spaces_expands_as_one_pattern(corpus, vault):
    # Built with the platform separator, so on Windows this is a backslash pattern (C:\...\*.md).
    plan = _plan(vault, str(corpus) + os.sep + "*.md")
    assert plan["ok"], plan
    lower = {"Cómo se desarrolla software.md", "fronteras-de-centralizacion.md"}
    # Whether `*.md` also takes MAYÚSCULAS.MD is the platform glob's call (case-insensitive on Windows), so
    # allow it, but nothing that is not .md, and never a dotfile.
    assert lower <= set(_titles(plan)) <= lower | {"MAYÚSCULAS.MD"}


def test_a_quoted_subset_whose_path_holds_spaces_is_dequoted_then_taken_whole(corpus, vault):
    plan = _plan(vault, corpus, f'"{corpus}"')
    assert plan["ok"], plan
    assert plan["subset"] == str(corpus)
    assert set(_titles(plan)) == SOURCES


def test_a_missing_source_still_fails_loud(tmp_path, vault):
    plan = _plan(vault, tmp_path / "no existe" / "fuente.md")
    assert plan["ok"] is False
    assert "no readable" in plan["error"]
    assert "files" not in plan


def test_a_subset_outside_the_configured_source_is_refused_before_any_extraction(corpus, tmp_path, vault):
    outside = tmp_path / "otra carpeta"
    outside.mkdir()
    (outside / "suelto.md").write_text("## Fuera\ntexto\n", encoding="utf-8")
    plan = _plan(vault, corpus, str(outside / "suelto.md"))
    assert plan["ok"] is False
    assert plan["problems"] == [plan["error"]]
    assert "suelto.md is not part of the configured source_path" in plan["error"]
    assert str(tmp_path) not in plan["error"]   # never an absolute path in an engine message


def test_a_copy_of_a_configured_file_elsewhere_is_refused(corpus, tmp_path, vault):
    # Same basename, different file: its spans would be verified against the configured one, not it.
    elsewhere = tmp_path / "copia"
    elsewhere.mkdir()
    (elsewhere / "notas.txt").write_text("## Otra cosa\n", encoding="utf-8")
    plan = _plan(vault, corpus, str(elsewhere / "notas.txt"))
    assert plan["ok"] is False
    assert "copia/notas.txt is not the configured notas.txt" in plan["error"]


def test_the_command_has_no_shell_step():
    # The paths are now the engine's business: no Bash block, no Bash permission, nothing to word-split.
    assert "```bash" not in CMD
    assert "Bash" not in CMD.split("---", 2)[1]          # the frontmatter's allowed-tools
    assert "kg_build_plan" in CMD


def test_the_argument_is_a_subset_of_the_configured_source():
    assert "explicit override wins" not in FLAT
    assert "**subset** — optional" in FLAT
    assert "never replaces the configured source" in FLAT
    # ...and the STOP advice never offers a subset as a stand-in for a missing or broken source_path.
    assert "Naming a subset cannot stand in for it" in FLAT
    assert "or pass the path as `$1`" not in FLAT


def test_the_command_says_how_to_change_source_path():
    assert "claude plugin configure" in CMD
    assert "--values-stdin" in CMD
    assert "restarted" in CMD
    # Windows PowerShell 5.1 pipes text as ASCII: an accented path is saved with `?` in place of each accent
    # and the CLI still reports success. Checked on the reporting machine; the command must keep the fix.
    assert "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)" in CMD
