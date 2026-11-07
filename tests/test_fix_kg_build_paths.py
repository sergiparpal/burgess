"""Regression: /kg-build's Step 0b enumerates a source whose path holds spaces, and `$1` is a subset of the
configured source, not a replacement for it.

Found on a Windows install whose sources sat under `Documents\\Proyectos personales\\prueba-burgess`, with
spaces and accents in the file names as well. The Step 0b script word-split every path. `ls -1 $SOURCE`
(unquoted, there to expand a glob) cut a single-file source in two, so it found nothing, and
`for f in $FILES` cut every enumerated path at its spaces, so the per-file heading scan ran over fragments
that name nothing (`grep: personales/prueba: No such file or directory`). The script now keeps one path per
line end to end: a file is taken whole, a glob is expanded as one pattern (`compgen -G`, with a Windows
pattern's `\\` turned into `/` first), and the loop reads lines. The directory listing also matches
extensions case-insensitively now, as the engine does, so a `NOTES.MD` it counts is no longer skipped.

The same report caught the command promising that `$1` overrides the configured source, while `kg_write`
verifies every span against the configured `source_path` only (the engine's SourceSet, keyed by basename):
a `$1` outside it gets every edge REJECTED `span-not-in-source`. `$1` is now documented as a subset, Step 0b
checks each enumerated file against `kg_status().source.files` before any extractor runs, and the command
says how to change `source_path` (and that Claude Code must restart to pick it up).

The bash tests run the command's ACTUAL Step 0b block, extracted from commands/kg-build.md, the way the
orchestrator runs it. On Windows they use Git Bash, which is what Claude Code runs there; the PATH `bash`
on a Windows runner is the WSL launcher stub (see test_waves._bash_available).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kg_engine.sources import SourceSet

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")


def _step0b_script() -> str:
    """The bash block of Step 0b, verbatim."""
    section = CMD[CMD.index("#### 0b."):]
    m = re.search(r"```bash\n(.*?)```", section, re.S)
    assert m, "no ```bash block under Step 0b in commands/kg-build.md"
    return m.group(1)


def _working_bash() -> "str | None":
    """A bash that actually runs, or None. On Windows, Git Bash first: it is the shell Claude Code's Bash
    tool uses there, while the `bash` on PATH may be the WSL stub, found by `which` but unable to run."""
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files"):
            if base:
                candidates.append(str(Path(base) / "Git" / "bin" / "bash.exe"))
    candidates.append(shutil.which("bash"))
    for c in candidates:
        if not c or not Path(c).exists():
            continue
        try:
            r = subprocess.run([c, "-c", "echo ok"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip() == "ok":
            return c
    return None


BASH = _working_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no working bash (Windows without Git Bash)")

# name -> content. The directory's own path holds a space too (see `corpus`), like the reporting install.
FILES = {
    "Cómo se desarrolla software.md": "# Título\n\n## Uno\nx\n\n## Dos\ny\n",
    "fronteras-de-centralizacion.md": "# Título\n\n## A\n\n## B\n\n## C\n",
    "notas.txt": "## Nota 1\n\n## Nota 2\n",
    "MAYÚSCULAS.MD": "## M1\n\n## M2\n",
    ".oculto.md": "## hidden\n",      # dotfile: skipped by the engine, so by the command too
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


def _run_step0b(src: str, tmp_path: Path) -> "tuple[int, str, dict[str, list[str]]]":
    """Run Step 0b with `src` substituted for SRC; return (exit code, output, {basename: [headings]})."""
    script = tmp_path / "step0b.sh"
    script.write_text(_step0b_script(), encoding="utf-8", newline="\n")  # CRLF would break bash
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE"}
    env["SRC"] = src
    r = subprocess.run([BASH, str(script)], capture_output=True, env=env, timeout=60)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace").replace("\r", "")
    files: dict[str, list[str]] = {}
    current = None
    for line in out.splitlines():
        m = re.fullmatch(r"== (.*) ==", line)
        if m:
            current = re.split(r"[\\/]", m.group(1))[-1]
            files[current] = []
        elif current is not None and re.match(r"\d+:#{2,3} ", line):
            files[current].append(line.split(":", 1)[1])
    return r.returncode, out, files


def _headings(name: str) -> list[str]:
    return [ln for ln in FILES[name].splitlines() if ln.startswith("## ")]


def _assert_no_split_paths(out: str) -> None:
    assert "No such file" not in out and "cannot access" not in out, out


@needs_bash
def test_a_directory_whose_path_holds_spaces_lists_every_file_whole(corpus, tmp_path):
    code, out, files = _run_step0b(str(corpus), tmp_path)
    assert code == 0, out
    _assert_no_split_paths(out)
    assert set(files) == SOURCES, out
    for name in SOURCES:
        assert files[name] == _headings(name), (name, out)


@needs_bash
def test_the_directory_listing_is_the_engines_own(corpus, tmp_path):
    # The cross-check against kg_status().source.files only holds if a plain directory build enumerates
    # exactly what the engine resolves: case-insensitive .md/.txt, dotfiles skipped.
    _, out, files = _run_step0b(str(corpus), tmp_path)
    assert set(files) == set(SourceSet(corpus).basenames), out


@needs_bash
def test_a_single_file_whose_path_holds_spaces_is_taken_whole(corpus, tmp_path):
    name = "Cómo se desarrolla software.md"
    code, out, files = _run_step0b(str(corpus / name), tmp_path)
    assert code == 0, out
    _assert_no_split_paths(out)
    assert files == {name: _headings(name)}, out


@needs_bash
def test_a_glob_whose_directory_holds_spaces_expands_as_one_pattern(corpus, tmp_path):
    # Built with the platform separator, so on Windows this is a backslash pattern (C:\...\*.md): the case
    # the `\` -> `/` rewrite exists for.
    code, out, files = _run_step0b(str(corpus) + os.sep + "*.md", tmp_path)
    assert code == 0, out
    _assert_no_split_paths(out)
    lower = {"Cómo se desarrolla software.md", "fronteras-de-centralizacion.md"}
    # bash globs case-sensitively; whether `*.md` also takes MAYÚSCULAS.MD is the shell's call, so allow
    # it, but nothing that is not .md, and never a dotfile.
    assert lower <= set(files) <= lower | {"MAYÚSCULAS.MD"}, out


@needs_bash
def test_a_quoted_source_whose_path_holds_spaces_is_dequoted_then_taken_whole(corpus, tmp_path):
    code, out, files = _run_step0b(f'"{corpus}"', tmp_path)
    assert code == 0, out
    assert set(files) == SOURCES, out


@needs_bash
def test_a_missing_source_still_fails_loud(tmp_path):
    code, out, _ = _run_step0b(str(tmp_path / "no existe" / "fuente.md"), tmp_path)
    assert code == 1, out
    assert "no .md/.txt source found at:" in out, out


def test_step0b_never_word_splits_a_path():
    # Static pins, which run even where no bash does: the two splitting constructs are gone from the code
    # (the comment that explains them may still name them), and the loop reads one path per line.
    code = "\n".join(ln for ln in _step0b_script().splitlines() if not ln.lstrip().startswith("#"))
    assert "for f in $FILES" not in code
    assert "ls -1 $SOURCE" not in code
    assert "while IFS= read -r f; do" in code
    assert 'done <<< "$FILES"' in code


def test_dollar_one_is_a_subset_of_the_configured_source():
    assert "explicit override wins" not in CMD
    assert "optional subset" in CMD
    # Step 0b checks each enumerated file against the engine's own list before launching extractors.
    assert "source.files" in CMD[CMD.index("#### 0b."):]
    # ...and the STOP advice no longer offers $1 as a stand-in for a missing or broken source_path.
    assert "or pass the path as `$1`" not in CMD


def test_the_command_says_how_to_change_source_path():
    assert "claude plugin configure" in CMD
    assert "--values-stdin" in CMD
    assert "restarted" in CMD
    # Windows PowerShell 5.1 pipes text as ASCII: an accented path is saved with `?` in place of each accent
    # and the CLI still reports success. Checked on the reporting machine; the command must keep the fix.
    assert "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)" in CMD
