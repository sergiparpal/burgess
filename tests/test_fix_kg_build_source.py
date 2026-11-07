"""Regression: /kg-build must resolve the source through the ENGINE, never a shell env var (FALLO 3),
and enumerate a file's sections at its dominant heading level (FALLO 4).

FALLO 3: userConfig options (`source_path`) reach the MCP server process via `.mcp.json`'s
`${user_config.source_path}` → `KG_SOURCE_PATH`, but the host does NOT inject them into the model's Bash
tool shell. The old Step 0 read `${CLAUDE_PLUGIN_OPTION_SOURCE_PATH}` from that shell (always empty) and
silently fell back to `examples/source.md`, ignoring a REQUIRED, configured `source_path`. The engine
already knows the resolved path, so `kg_status()` now exposes it under a `source` block and the command
reads it from there — and fails loud instead of building the demo by surprise.

FALLO 4: the command enumerated only level-2 `## ` headings; a file whose single `## ` is its title but
whose content is `### ` subsections collapsed into one section, breaking span-isolation. Step 0b then
detected the dominant heading level per file in Bash; since 0.5.0 the engine does (`kg_build_plan`, through
`sources.plan_sections`), and the command reports the plan's `heading_level` instead of grepping for it.
"""
from pathlib import Path

import pytest

from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# FALLO 3 — the engine exposes the resolved source through kg_status()
# --------------------------------------------------------------------------- #
def test_kg_status_exposes_resolved_source(engine):
    st = engine.kg_status()
    assert "source" in st, "kg_status must expose the engine-resolved source (FALLO 3)"
    src = st["source"]
    assert src["path"] == str(engine.source_path)     # the path the ENGINE resolved, not a shell env var
    assert src["exists"] is True                       # it resolves to a readable file
    assert "source.md" in src["files"]                 # ...enumerated by basename (R4)


def test_kg_status_source_none_when_unconfigured(vault):
    # No source configured (and no bundled demo under this temp project) → path is None, exists False.
    # The command reads exactly this to STOP instead of silently building examples/source.md.
    pack_path = REPO / "pack" / "pack.yaml"
    eng = KGEngine(vault, source_path=None, pack_path=pack_path)
    src = eng.kg_status()["source"]
    assert src["path"] is None
    assert src["exists"] is False
    assert src["files"] == []


def test_kg_status_source_reports_configured_but_missing_path(vault, tmp_path):
    # A configured path that resolves to zero readable files: path is echoed (so the command can name it)
    # but exists is False — the command STOPs on this rather than falling through to the demo.
    missing = tmp_path / "nope" / "does-not-exist.md"
    eng = KGEngine(vault, source_path=missing, pack_path=REPO / "pack" / "pack.yaml")
    src = eng.kg_status()["source"]
    assert src["path"] == str(missing)
    assert src["exists"] is False
    assert src["files"] == []


# --------------------------------------------------------------------------- #
# FALLO 3 — the command reads the engine, not the shell env var, and fails loud
# --------------------------------------------------------------------------- #
def test_command_does_not_resolve_source_from_shell_env_var():
    # The old silent fallback `SOURCE="${1:-${CLAUDE_PLUGIN_OPTION_SOURCE_PATH:-examples/source.md}}"`
    # must be gone: that env var is empty in the tool shell, so it silently built the demo.
    assert "CLAUDE_PLUGIN_OPTION_SOURCE_PATH:-examples/source.md" not in CMD
    assert 'SOURCE="${1:-${CLAUDE_PLUGIN_OPTION_SOURCE_PATH' not in CMD


def test_command_reads_source_from_the_engine():
    # Since 0.5.0 the plan carries the engine-resolved source (kg_build_plan().source, the same block
    # kg_status returns): the single source of truth, and the command reports `source.path` from it.
    assert "kg_build_plan" in CMD
    assert "source.path" in CMD


def test_command_fails_loud_instead_of_demo_fallback():
    # When nothing is configured, the command STOPs rather than building the demo.
    flat = " ".join(CMD.split())
    assert "**`ok: false` → STOP.**" in flat
    assert "never fall back to the demo corpus" in flat


def test_the_plan_refuses_an_unconfigured_source(vault):
    plan = KGEngine(vault).kg_build_plan("", "")
    assert plan["ok"] is False
    assert plan["source"]["path"] is None
    assert "no source_path is configured" in plan["error"]
    # A subset cannot stand in for a missing source_path: spans verify against the configured source only.
    assert KGEngine(vault).kg_build_plan("notes.md", "")["ok"] is False


# --------------------------------------------------------------------------- #
# FALLO 4 — dominant heading level detection
# --------------------------------------------------------------------------- #
def _plan_file(tmp_path, vault, text: str) -> dict:
    src = tmp_path / "doc.md"
    src.write_text(text, encoding="utf-8")
    plan = KGEngine(vault, source_path=src).kg_build_plan("", "")
    assert plan["ok"], plan
    (entry,) = plan["files"]
    return entry


def test_a_title_only_file_is_planned_at_its_subsections(tmp_path, vault):
    # The FALLO 4 shape: one `## ` heading (the title), the content in `### ` subsections.
    entry = _plan_file(tmp_path, vault, "## Título\nintro\n\n### Uno\na\n\n### Dos\nb\n\n### Tres\nc\n")
    assert entry["heading_level"] == 3
    assert [s["title"] for s in entry["sections"]] == ["Uno", "Dos", "Tres"]
    assert "### subsections" in entry["note"]


def test_a_file_with_two_level_two_sections_stays_at_level_two(tmp_path, vault):
    entry = _plan_file(tmp_path, vault, "## A\n### a1\n### a2\n## B\n### b1\n")
    assert entry["heading_level"] == 2
    assert [s["title"] for s in entry["sections"]] == ["A", "B"]


def test_a_single_subsection_does_not_switch_the_level(tmp_path, vault):
    entry = _plan_file(tmp_path, vault, "## Título\n### Solo\ntexto\n")
    assert entry["heading_level"] == 2
    assert [s["title"] for s in entry["sections"]] == ["Título"]


def test_headings_inside_a_code_fence_are_not_counted(tmp_path, vault):
    # Step 0b's grep counted a `### ` inside a fence; the engine's rule (sources._chunks) does not.
    entry = _plan_file(tmp_path, vault, "## Título\n```\n### no\n### tampoco\n```\n")
    assert entry["heading_level"] == 2
    assert [s["title"] for s in entry["sections"]] == ["Título"]


def test_a_file_without_headings_is_one_whole_file_section(tmp_path, vault):
    entry = _plan_file(tmp_path, vault, "Solo prosa, sin encabezados.\n")
    assert [s["title"] for s in entry["sections"]] == ["(whole file)"]
    assert "whole file" in entry["note"]


def test_the_command_explains_the_heading_level():
    flat = " ".join(CMD.split())
    assert "`heading_level` is 2 for `## ` sections" in flat
    assert "FALLO 4" in flat
