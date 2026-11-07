"""The /kg-build plan's deterministic halves: reading the typed arguments and resolving a subset (0.5.0),
and the nodes already in the canon that a section names (0.6.0, `related_nodes`).

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
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

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


# ---- the nodes a section names (0.6.0) ----------------------------------------------------------------
#
# A /kg-build extractor names its nodes without seeing the canon, so one concept written by two sections
# lands under two ids: `radar` / `meta-radar`, `pass-at-k` / `pass-k`, `experimento-con-oraculo` /
# `experimentos-con-oraculo`, about 19 groups in one 84-section build of a real corpus (field report on
# 0.5.2). kg_section now hands each extractor the canon nodes whose NAME its section mentions, so it can
# reuse an id. The match is lexical and deterministic, on purpose: it decides only what an extractor is
# SHOWN, never what is merged. Whether a section's concept is the same as a known node stays the
# extractor's judgment, and identity is never guessed by the engine (no embeddings: they measure
# dispersion, never truth).

# How many known nodes one section is shown at most, most specifically named first: about 1.5k tokens per
# extractor. Measured offline on the field report's own canon (486 nodes) and its 84 sections: of the 18
# duplicate groups that build produced, two members of a group appear together in some section's list for
# 12 groups at a cap of 20, 14 at 40 and 16 at 60, and still 16 at 80. The two left are a translation
# (`mutation-score` / `puntuacion-de-mutacion`) and synonyms with no word in common, which no lexical
# match can see.
KNOWN_NODES_LIMIT = 60

# Function words that would otherwise "match" every section. Accent-folded, so `más`/`según` are listed bare.
_STOPWORDS = frozenset("""
a al algo algun alguna ante antes asi aun bajo bien cada casi como con contra cual cuando cuanto de del
desde donde dos durante e el ella ellas ellos en entre era eran es esa esas ese eso esos esta estan estas
este esto estos fue fueron ha han hasta hay la las le les lo los mas me menos mi mientras muy ni no nos
nuestra nuestro o os otra otras otro otros para pero poco por porque que quien se segun ser si sin sino
sobre solo son su sus tal tambien tan tanto te tiene tienen todo todos tras tu un una unas uno unos y ya
an and any are as at be been but by can for from has have how if in into is it its no not of on or our
over so such than that the their them then there these they this those through to under up was we were
what when where which while who why will with without you your
""".split())
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _fold(text: str) -> str:
    """Casefolded, with accents and other combining marks dropped (`Revisión` → `revision`), the form the
    extractor contract asks ids to take."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _words(text: str) -> "list[str]":
    """The content words of `text`: folded, function words dropped, and words under three characters
    dropped unless they are a number of two or more digits (`vercel-58-monorepo` keeps its `58`)."""
    return [w for w in _WORD.findall(_fold(text))
            if w not in _STOPWORDS and (len(w) >= 3 or (w.isdigit() and len(w) >= 2))]


def _forms(word: str) -> "set[str]":
    """`word` and the singulars it could be the plural of: `mecanismos` → `mecanismo`, `senales` → `senal`
    and `senale`. Applied to both sides, so a singular and a plural of one word always share a form."""
    forms = {word}
    if len(word) > 3 and word.endswith("s"):
        forms.add(word[:-1])
        if len(word) > 4 and word.endswith("es"):
            forms.add(word[:-2])
    return forms


def related_nodes(text: str, nodes: "Iterable", *, degree: "Mapping[str, int] | None" = None,
                  limit: int = KNOWN_NODES_LIMIT) -> "tuple[list, int]":
    """``(nodes, total)``: the nodes whose NAME `text` mentions, most specifically named first, at most
    `limit` of them, and how many qualified in all.

    A node is named when at least half the content words of its id, or of its label, occur in `text`,
    singular or plural, accents ignored: `meta-radar` is named by a section that says "RADAR", and
    `experimentos-con-oraculo` by one that says "experimento con oráculo".

    In a canon of a few hundred nodes a long section names a hundred of them that way, mostly through
    words every other name shares (`revision`, `agente`), so the order is what decides what an extractor
    sees. Each name word is weighted by its rarity among the canon's names (an IDF: `radar` or `camel`
    outweighs `codigo`). Nodes rank by the weighted share of their name found, then by the weight found,
    then by degree (an established hub first), then by id, so the list is the same on every run.
    """
    nodes = list(nodes)
    present: "set[str]" = set()
    for w in _words(text):
        present |= _forms(w)
    names = []
    df: "dict[str, int]" = {}
    for n in nodes:
        sets = [ws for ws in (set(_words(n.id.replace("-", " "))), set(_words(n.label or ""))) if ws]
        names.append(sets)
        for w in set().union(*sets) if sets else ():
            df[w] = df.get(w, 0) + 1
    total_names = max(len(nodes), 1)

    def weight(w: str) -> float:
        return math.log(1 + total_names / df.get(w, 1))

    scored = []
    for n, sets in zip(nodes, names):
        best = None
        for words in sets:
            found = [w for w in words if _forms(w) & present]
            if not found or len(found) * 2 < len(words):
                continue
            got = sum(weight(w) for w in found)
            key = (got / sum(weight(w) for w in words), got)
            best = key if best is None or key > best else best
        if best is not None:
            scored.append((-best[0], -best[1], -int((degree or {}).get(n.id, 0)), n.id, n))
    scored.sort(key=lambda row: row[:4])
    return [row[4] for row in scored[:limit]], len(scored)
