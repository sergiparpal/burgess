"""0.11.10 — a release that only bumps the version leaves the engine venv current.

Found on 2026-11-11, in the first Windows session after the 0.11.9 update. Its MCP server connected after
29.5 s, against Claude Code's 30 s default: the launcher waited 18 s for a venv rebuild, and the engine took 11 s
more. Nothing the venv installs had changed. `bootstrap.compute_stamp` hashed `pyproject.toml` whole, so the
`version` line every release bumps left each venv stale. `bootstrap.py --check` on the Windows venv passed with
the 0.11.9 copy and failed with the 0.11.8 one. Half a second more and the session would have started without
the Burgess tools until a reconnect.

The stamp now leaves out `[project]`'s version line. Every other byte of the file still counts, and so does the
interpreter's identity.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bootstrap = _load("kg_bootstrap_0_11_10", "scripts/bootstrap.py")
bump_version = _load("kg_bump_version_0_11_10", "scripts/bump_version.py")

PYPROJECT = """[project]
name = "burgess"
version = "{version}"
requires-python = ">=3.10"
dependencies = [
  "mcp>=1.2,<2",
  "networkx>=3",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


def _stamp(monkeypatch, tmp_path: Path, text: str, *, newline: str = "\n") -> str:
    pp = tmp_path / "pyproject.toml"
    pp.write_bytes(text.replace("\n", newline).encode("utf-8"))
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    return bootstrap.compute_stamp("3.12|win32|AMD64")


def test_a_version_bump_leaves_the_stamp(monkeypatch, tmp_path):
    assert _stamp(monkeypatch, tmp_path, PYPROJECT.format(version="0.11.8")) == \
        _stamp(monkeypatch, tmp_path, PYPROJECT.format(version="0.11.9"))


def test_the_bump_script_s_own_edit_leaves_the_stamp(monkeypatch, tmp_path):
    # the repo's real pyproject.toml, bumped exactly as `scripts/bump_version.py --write` bumps it
    real = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    monkeypatch.setattr(bump_version, "_text", lambda rel: real)
    bumped = bump_version._rewrite_toml("pyproject.toml", "99.0.0")
    assert bumped != real and 'version = "99.0.0"' in bumped
    assert _stamp(monkeypatch, tmp_path, real) == _stamp(monkeypatch, tmp_path, bumped)


@pytest.mark.parametrize("edit", [
    lambda t: t.replace('"networkx>=3",', '"networkx>=3",\n  "numpy>=1",'),       # a dependency added
    lambda t: t.replace('"mcp>=1.2,<2"', '"mcp>=1.3,<2"'),                         # a pin moved
    lambda t: t.replace('requires-python = ">=3.10"', 'requires-python = ">=3.11"'),
    lambda t: t.replace('dev = ["pytest>=8"]', 'dev = ["pytest>=9"]'),             # an optional extra
    lambda t: t.replace('requires = ["hatchling"]', 'requires = ["hatchling>=1.25"]'),
    lambda t: t + '\n[tool.example]\nversion = "2"\n',                             # another table's version
    lambda t: t + '\n[[tool.example.items]]\nversion = "2"\n',                     # an array of tables
], ids=["dependency", "pin", "requires-python", "extra", "build-system", "tool-table", "array-of-tables"])
def test_anything_else_still_moves_the_stamp(monkeypatch, tmp_path, edit):
    base = PYPROJECT.format(version="0.11.9")
    assert _stamp(monkeypatch, tmp_path, base) != _stamp(monkeypatch, tmp_path, edit(base))


def test_a_version_key_after_another_table_is_not_the_projects(monkeypatch, tmp_path):
    base = PYPROJECT.format(version="0.11.9") + '\n[tool.example]\nversion = "1"\n'
    assert _stamp(monkeypatch, tmp_path, base) != _stamp(monkeypatch, tmp_path, base.replace('version = "1"',
                                                                                              'version = "2"'))


def test_line_endings_do_not_move_the_stamp(monkeypatch, tmp_path):
    # the Windows marketplace clone checks pyproject.toml out with CRLF
    text = PYPROJECT.format(version="0.11.9")
    assert _stamp(monkeypatch, tmp_path, text) == _stamp(monkeypatch, tmp_path, text, newline="\r\n")


def test_the_interpreter_still_moves_the_stamp(monkeypatch, tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text(PYPROJECT.format(version="0.11.9"), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    assert bootstrap.compute_stamp("3.12|win32|AMD64") != bootstrap.compute_stamp("3.13|win32|AMD64")


def test_a_venv_stamped_the_old_way_rebuilds_once(monkeypatch, tmp_path):
    # SCHEMA "2": no stamp written through 0.11.9 can match, so the first 0.11.10 session rebuilds once
    text = PYPROJECT.format(version="0.11.9")
    new = _stamp(monkeypatch, tmp_path, text)
    monkeypatch.setattr(bootstrap, "SCHEMA", "1")
    monkeypatch.setattr(bootstrap, "_install_inputs", lambda t: t)  # the whole file, as through 0.11.9
    assert _stamp(monkeypatch, tmp_path, text) != new


def test_only_the_project_version_line_is_left_out():
    text = PYPROJECT.format(version="0.11.9")
    kept = bootstrap._install_inputs(text)
    assert 'version = "0.11.9"' not in kept
    assert kept == text.replace('version = "0.11.9"\n', "")
