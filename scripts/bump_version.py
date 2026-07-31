#!/usr/bin/env python3
"""Bump the project version across every file that declares it (stdlib only).

Burgess declares its version in five places — two manifests, two packages, and
``pyproject.toml`` — with no single source of truth. Editing them by hand is how they
drift, and a drifted version means the plugin manifest, the installed package and the
engine's own ``kg_ping`` stamp disagree about what is running.

Two rules make this safe to run:

* **Refuse to bump from an inconsistent state.** If the five sites do not already agree,
  the drift is a bug to be understood, not something a bump should paper over. Fix it
  first (the mismatch is printed), then bump.
* **Dry run by default.** ``--write`` applies; without it the plan is printed and nothing
  on disk changes. Exit 0 = everything agrees (and, with ``--write``, was rewritten);
  nonzero = the failure is printed, so CI can call this as a check.

Deliberately NOT a release driver. Cambrian's ``release.py`` also cuts GitHub releases and
publishes to PyPI; Burgess does neither, so only the version-site sweep is worth having.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "burgess"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)([-.+].*)?$")

# Site labels, in the order they are reported. Kept identical to the labels
# tests/test_version_consistency.py uses so a failure reads the same either way.
PLUGIN_JSON = ".claude-plugin/plugin.json"
MARKETPLACE_JSON = ".claude-plugin/marketplace.json"
ENGINE_INIT = "scripts/kg_engine/__init__.py"
DIVERGENCE_INIT = "scripts/kg_engine/divergence/__init__.py"
PYPROJECT = "pyproject.toml"

_DUNDER_VERSION = re.compile(r'''^(__version__\s*=\s*)(["'])([^"']+)\2''', re.M)
_TOML_TABLE = re.compile(r"^\s*\[")
_TOML_VERSION = re.compile(r'''^(\s*version\s*=\s*)(["'])([^"']+)\2''')


class VersionError(Exception):
    """A declaration site is missing or unparseable."""


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #
def _text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        raise VersionError(f"missing file: {rel}")
    return path.read_text(encoding="utf-8")


def _read_json_versions(rel: str) -> list[str]:
    """Every version string this manifest declares for the burgess plugin.

    marketplace.json can list several plugins (and, in a bad edit, the same one twice), so
    EVERY matching entry is returned rather than the first — a duplicate carrying a stale
    version has to fail the agreement check, not hide behind a good sibling.
    """
    data = json.loads(_text(rel))
    if rel == PLUGIN_JSON:
        version = data.get("version")
        if not isinstance(version, str):
            raise VersionError(f"{rel}: top-level 'version' is missing or not a string")
        return [version]
    found = [
        entry.get("version")
        for entry in data.get("plugins", [])
        if isinstance(entry, dict) and entry.get("name") == PLUGIN_NAME
    ]
    if not found:
        raise VersionError(f"{rel}: no plugins[] entry named {PLUGIN_NAME!r}")
    if any(not isinstance(v, str) for v in found):
        raise VersionError(f"{rel}: a {PLUGIN_NAME} entry has a non-string 'version'")
    return found


def _read_dunder_version(rel: str) -> str:
    match = _DUNDER_VERSION.search(_text(rel))
    if not match:
        raise VersionError(f"{rel}: no module-level __version__ assignment")
    return match.group(3)


def read_pyproject_version(text: str) -> str | None:
    """``[project].version`` specifically.

    A line-anchored scan would lock onto the first ``version = "..."`` in the file — which
    may sit under ``[build-system]`` or any ``[tool.*]`` table — and silently validate the
    wrong string. Same table-scoping discipline as scripts/validate_plugin.py.
    """
    in_project = False
    for line in text.splitlines():
        if _TOML_TABLE.match(line):
            in_project = line.strip().startswith("[project]")
            continue
        if in_project:
            match = _TOML_VERSION.match(line)
            if match:
                return match.group(3)
    return None


def _read_toml_version(rel: str) -> str:
    version = read_pyproject_version(_text(rel))
    if version is None:
        raise VersionError(f"{rel}: no version under the [project] table")
    return version


def read_all_versions() -> dict[str, list[str]]:
    """``{site: [declared versions]}`` for all five sites; raises on an unreadable one."""
    return {
        PLUGIN_JSON: _read_json_versions(PLUGIN_JSON),
        MARKETPLACE_JSON: _read_json_versions(MARKETPLACE_JSON),
        ENGINE_INIT: [_read_dunder_version(ENGINE_INIT)],
        DIVERGENCE_INIT: [_read_dunder_version(DIVERGENCE_INIT)],
        PYPROJECT: [_read_toml_version(PYPROJECT)],
    }


# --------------------------------------------------------------------------- #
# writers — surgical, so hand-formatting survives a bump
# --------------------------------------------------------------------------- #
def _rewrite_json(rel: str, old: str, new: str, expected: int) -> str:
    """Replace the manifest's version strings textually, not by re-serializing.

    ``json.dump`` would reformat the whole manifest (key order, spacing) for a three-byte
    change and bury the bump in the diff. The replacement is anchored on the exact
    ``"version": "<old>"`` pair and the hit count must match what the parse found, so an
    unrelated nested ``version`` key can never be caught by accident.
    """
    pattern = re.compile(r'("version"\s*:\s*")' + re.escape(old) + r'(")')
    text, hits = pattern.subn(r"\g<1>" + new + r"\g<2>", _text(rel))
    if hits != expected:
        raise VersionError(
            f"{rel}: expected to rewrite {expected} version string(s), matched {hits}"
        )
    return text


def _rewrite_dunder(rel: str, new: str) -> str:
    text, hits = _DUNDER_VERSION.subn(
        lambda m: f'{m.group(1)}{m.group(2)}{new}{m.group(2)}', _text(rel), count=1
    )
    if hits != 1:
        raise VersionError(f"{rel}: no module-level __version__ assignment to rewrite")
    return text


def _rewrite_toml(rel: str, new: str) -> str:
    """Rewrite only the ``[project]`` table's version line (see read_pyproject_version)."""
    lines = _text(rel).splitlines(keepends=True)
    in_project = False
    for i, line in enumerate(lines):
        if _TOML_TABLE.match(line):
            in_project = line.strip().startswith("[project]")
            continue
        if in_project:
            match = _TOML_VERSION.match(line)
            if match:
                quote = match.group(2)
                lines[i] = f"{match.group(1)}{quote}{new}{quote}" + line[match.end():]
                return "".join(lines)
    raise VersionError(f"{rel}: no version under the [project] table to rewrite")


# --------------------------------------------------------------------------- #
# version arithmetic
# --------------------------------------------------------------------------- #
def next_version(current: str, part: str) -> str:
    match = _SEMVER.match(current)
    if not match:
        raise VersionError(f"current version {current!r} is not X.Y.Z")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def current_version(sites: dict[str, list[str]]) -> str:
    """The single agreed version, or raise naming every site that disagrees."""
    distinct = {v for versions in sites.values() for v in versions}
    if len(distinct) != 1:
        report = "\n".join(f"  {site}: {', '.join(vs)}" for site, vs in sites.items())
        raise VersionError(
            "version sites disagree — fix the drift before bumping:\n" + report
        )
    return distinct.pop()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _plan(old: str, new: str, sites: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [
        (PLUGIN_JSON, _rewrite_json(PLUGIN_JSON, old, new, len(sites[PLUGIN_JSON]))),
        (MARKETPLACE_JSON,
         _rewrite_json(MARKETPLACE_JSON, old, new, len(sites[MARKETPLACE_JSON]))),
        (ENGINE_INIT, _rewrite_dunder(ENGINE_INIT, new)),
        (DIVERGENCE_INIT, _rewrite_dunder(DIVERGENCE_INIT, new)),
        (PYPROJECT, _rewrite_toml(PYPROJECT, new)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump the version across all five declaration sites."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--to", metavar="X.Y.Z", help="set this exact version")
    target.add_argument("--part", choices=("major", "minor", "patch"),
                        help="increment this component of the current version")
    parser.add_argument("--write", action="store_true",
                        help="apply the change (default: dry run, nothing is written)")
    args = parser.parse_args(argv)

    try:
        sites = read_all_versions()
        old = current_version(sites)
        if args.to:
            if not _SEMVER.match(args.to):
                raise VersionError(f"--to {args.to!r} is not a SemVer-like X.Y.Z")
            new = args.to
        elif args.part:
            new = next_version(old, args.part)
        else:
            # No target: this is the consistency CHECK. Reaching here means the five
            # sites already agree, which is the whole assertion CI needs.
            print(f"VERSION OK: all 5 sites declare {old}")
            return 0
        rewrites = _plan(old, new, sites)
    except VersionError as exc:
        print(f"bump-version: {exc}", file=sys.stderr)
        return 1

    print(f"{old} -> {new}")
    for rel, _text_out in rewrites:
        print(f"  {'wrote' if args.write else 'would write'} {rel}")
    if not args.write:
        print("dry run — pass --write to apply")
        return 0
    for rel, text_out in rewrites:
        (ROOT / rel).write_text(text_out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
