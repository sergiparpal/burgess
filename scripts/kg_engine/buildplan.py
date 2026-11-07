"""The /kg-build plan's deterministic halves (0.5.0): reading the typed arguments and resolving a subset.

Through 0.4.6 `/kg-build` worked these out in its Step 0b Bash block and in the orchestrator's head. In
auto mode Claude Code ignores a command's `Bash` permission (a tool-wide shell grant would let the model
step around its classifier), so every one of those Bash calls went to the classifier, and the ones it
would not clear stopped the build on a permission prompt (field report on 0.4.6). Moving the work into
`kg_build_plan`, an MCP tool the command declares, takes the shell out of the build, and makes the rules
code that tests can run instead of prose an orchestrator interprets.

Pure stdlib + `envconfig`/`sources`; no I/O beyond resolving the subset's paths. `KGEngine.kg_build_plan`
assembles the plan around these.
"""
from __future__ import annotations

import fnmatch
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import envconfig
from .sources import SourceSet

_QUOTES = ("'", '"')
# A trailing run of ASCII digits after whitespace: the wave size. `[0-9]`, never `\d`, which also matches
# other scripts' digits that the wave-size rule (waves.explain_wave_size) would then reject.
_TRAILING_WAVE = re.compile(r"(.*\S)\s+([0-9]+)", re.DOTALL)


@dataclass(frozen=True)
class BuildArguments:
    """What the typed line asks for. ``subset`` is ``""`` for the whole configured source; ``wave_size``
    is the typed wave size, ``""`` when none was typed. A non-empty ``problem`` means the line cannot be
    read as one subset, and the plan stops on it."""
    subset: str
    wave_size: str
    problem: str = ""


def parse_arguments(raw: "str | None") -> BuildArguments:
    """Split `/kg-build`'s typed ``$ARGUMENTS`` into a subset and a wave size.

    The rules are the ones the command text gave the orchestrator in 0.4.5 and 0.4.6, with one change:

    - An empty line asks for the whole configured source at the configured wave size.
    - A trailing whole number after a space is the wave size, and the rest is the subset. So an unquoted
      name with spaces still works (``Fábricas de software.md 4``), and a name that itself ends in a
      number must be quoted (``"capítulo 3"``).
    - A line that is only a whole number is the wave size (new in 0.5.0: before, it was a subset that
      named no file).
    - Matched surrounding quotes are dropped, repeatedly, the way ``envconfig.clean`` drops them from a
      configured path. Two separately quoted parts (``"a.md" "b.md"``) are refused: one subset is one
      file, folder or glob.
    """
    line = (raw or "").strip()
    if not line:
        return BuildArguments("", "")
    if line.isascii() and line.isdigit():
        return BuildArguments("", line)
    m = _TRAILING_WAVE.fullmatch(line)
    rest, wave = (m.group(1), m.group(2)) if m else (line, "")
    subset = envconfig._dequote(rest)
    if rest[:1] in _QUOTES and subset != rest and rest[0] in subset:
        # Peeling the outer pair left that same quote inside: `"a.md" "b.md"` → `a.md" "b.md`. (An
        # unbalanced quote peels nothing; it stays as typed and simply names no file.)
        return BuildArguments("", wave, "the arguments hold two or more quoted parts; give one file, "
                                        "folder or glob, optionally followed by a wave size")
    return BuildArguments(subset, wave)


def _same_file_key(p: Path) -> str:
    """A comparable identity for a path: resolved, NFC-normalized, and case-folded where the platform's
    filesystem ignores case (``os.path.normcase``). Two spellings of one file compare equal."""
    try:
        q = p.resolve()
    except OSError:
        q = p.absolute()
    return os.path.normcase(unicodedata.normalize("NFC", str(q)))


def _name_key(name: str) -> str:
    return os.path.normcase(unicodedata.normalize("NFC", name))


def resolve_subset(subset: str, *, project_dir: Path, declared: "list[Path]") -> "tuple[list[str], list[str]]":
    """``(basenames, problems)``: the declared source files a typed subset selects, in source order.

    ``declared`` is the configured source's file list (``SourceSet.resolve(source_path)``). The subset
    narrows it and never replaces it: spans verify against the configured files (the boundary's
    SourceSet, keyed by basename), so a file outside them could never verify a span.

    - ``""`` selects every declared file.
    - Otherwise the subset is a file, folder or glob, relative to the project folder unless absolute,
      resolved by the same rule as the configured source itself (``SourceSet.resolve``).
    - A bare name or name glob (no folder part) that names no path there is matched against the declared
      basenames instead, so ``notes.md`` works whichever folder the session was opened in. A subset with
      a folder part that names no path matches nothing.

    Each problem is one sentence naming a file the subset reached that is not a configured source
    file, or saying that the subset matched nothing. The caller stops on any problem rather than build
    part of what was asked.
    """
    if not subset:
        return [p.name for p in declared], []
    by_identity = {_same_file_key(p): p.name for p in declared}
    names_in_order = [p.name for p in declared]
    target = Path(subset)
    if not target.is_absolute():
        target = Path(project_dir) / target
    found = SourceSet.resolve(target)
    chosen: "set[str]" = set()
    problems: "list[str]" = []
    if found:
        for f in found:
            name = by_identity.get(_same_file_key(f))
            if name is not None:
                chosen.add(name)
            elif f.name in names_in_order:
                # Named by its folder and basename, never its absolute path (the §1.9 posture of every
                # engine message that leaves the server).
                problems.append(f"{f.parent.name}/{f.name} is not the configured {f.name}: spans verify "
                                "against the configured file, so build from that one")
            else:
                problems.append(f"{f.name} is not part of the configured source_path, so none of its spans "
                                "could verify; move it there or change source_path")
    elif len(Path(subset).parts) == 1:
        # Only a bare name or name glob falls back to the configured basenames. A subset that names a
        # folder (`otra/*.md`) meant that folder: matching its last part against every configured file
        # would quietly build files the user never pointed at.
        pattern = _name_key(subset)
        for name in names_in_order:
            if fnmatch.fnmatchcase(_name_key(name), pattern):
                chosen.add(name)
    if not found and not chosen:
        problems.append(f"the subset {subset!r} matched no file of the configured source")
    return [n for n in names_in_order if n in chosen], problems
