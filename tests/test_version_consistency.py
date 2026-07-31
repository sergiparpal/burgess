"""Every file that declares the version must declare the SAME version.

Burgess states its version in five places — the two `.claude-plugin` manifests, the
`kg_engine` and `kg_engine.divergence` packages, and `pyproject.toml` — and drift between
them means the plugin manifest, the installed package and the engine's own `kg_ping` stamp
disagree about what is running. `scripts/validate_plugin.py` already cross-checks four of
them; the divergence package was outside every gate, and nothing asserted the set as a
whole from the test suite (the thing `ci-complete` actually requires).

Read independently of `scripts/bump_version.py` on purpose: a guard that shares its parser
with the tool it guards only proves the parser is self-consistent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import kg_engine
import kg_engine.divergence

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+([-.+].*)?$")


def _pyproject_version() -> str:
    """`[project].version`, table-scoped.

    `tomllib` is stdlib only from 3.11 and CI's matrix floor is 3.10, so fall back to a
    table-scoped text scan rather than taking a dependency for one string. The scan must be
    table-scoped either way: a line-anchored search would lock onto the first
    `version = "..."` in the file, which may sit under `[build-system]` or a `[tool.*]`.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:
        in_project = False
        for line in text.splitlines():
            if line.lstrip().startswith("["):
                in_project = line.strip().startswith("[project]")
                continue
            if in_project:
                m = re.match(r'''^\s*version\s*=\s*["']([^"']+)["']''', line)
                if m:
                    return m.group(1)
        raise AssertionError("pyproject.toml has no version under [project]")
    return tomllib.loads(text)["project"]["version"]


def _declared_versions() -> dict:
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    burgess_entries = [p for p in market["plugins"] if p.get("name") == "burgess"]
    assert burgess_entries, "marketplace.json declares no burgess plugin"
    return {
        ".claude-plugin/plugin.json": plugin["version"],
        # Every matching entry, not just the first: a duplicated entry carrying a stale
        # version has to fail here rather than hide behind a correct sibling.
        **{f".claude-plugin/marketplace.json[{i}]": e["version"]
           for i, e in enumerate(burgess_entries)},
        "kg_engine.__version__": kg_engine.__version__,
        "kg_engine.divergence.__version__": kg_engine.divergence.__version__,
        "pyproject.toml": _pyproject_version(),
    }


def test_all_declared_versions_agree():
    declared = _declared_versions()
    assert len(set(declared.values())) == 1, (
        "version sites disagree: "
        + ", ".join(f"{site}={v}" for site, v in sorted(declared.items()))
    )


def test_version_is_semver_like():
    for site, version in _declared_versions().items():
        assert SEMVER.match(version), f"{site} declares a non-SemVer version: {version!r}"
