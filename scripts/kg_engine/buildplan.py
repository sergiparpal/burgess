"""The /kg-build plan's deterministic halves: reading the typed arguments and resolving a subset (0.5.0),
the nodes already in the canon that a section names (0.6.0, `related_nodes`), the record of a section an
extraction wrote no edge from (0.14.0, `edgeless_records`), and the record of the text an extraction read
(0.26.0, `section_units` and `read_units`).

Through 0.4.6 `/kg-build` worked these out in its Step 0b Bash block and in the orchestrator's head. In
auto mode Claude Code ignores a command's `Bash` permission (a tool-wide shell grant would let the model
step around its classifier), so every one of those Bash calls went to the classifier, and the ones it
would not clear stopped the build on a permission prompt (field report on 0.4.6). Moving the work into
`kg_build_plan`, an MCP tool the command declares, takes the shell out of the build, and makes the rules
code that tests can run instead of prose an orchestrator interprets.

Pure stdlib + `envconfig`/`sources`/`model`; no I/O beyond resolving the subset's paths. `KGEngine.kg_build_plan`
assembles the plan around these.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from . import envconfig
from .model import normalize_text
from .sources import SourceSet

_QUOTES = ("'", '"')
# A trailing run of ASCII digits after whitespace: the wave size. `[0-9]`, never `\d`, which also matches
# other scripts' digits that the wave-size rule (waves.explain_wave_size) would then reject.
_TRAILING_WAVE = re.compile(r"(.*\S)\s+([0-9]+)", re.DOTALL)


@dataclass(frozen=True)
class BuildArguments:
    """What the typed line asks for. ``subset`` is ``""`` for the whole configured source; ``wave_size``
    is the typed wave size, ``""`` when none was typed. A non-empty ``problem`` means the line cannot be
    read as one subset, and the plan stops on it. ``leads`` is true for ``--leads``: write the leads
    grounders recorded instead of extracting the uncovered sections (0.9.0). ``every`` is true for ``--all``:
    plan the sections `skip_reason` leaves out too (0.23.1). ``again`` is true for ``--again``: read the covered
    sections of the named files again, whole, as if each had changed (0.26.0)."""
    subset: str
    wave_size: str
    problem: str = ""
    leads: bool = False
    every: bool = False
    again: bool = False


# `--leads` first on the line: the /kg-build mode that writes the leads grounders recorded (0.9.0). Matched
# case-insensitively and only as a whole first word, so a file named `leads.md` is still a subset.
_LEADS_FLAG = re.compile(r"--leads(?:\s+|$)", re.IGNORECASE)


_ALL_FLAG = re.compile(r"--all(?:\s+|$)", re.I)
# `--again` first on the line (0.26.0): read the covered sections of the named files again. It needs a subset:
# with none it would launch one extractor per covered section of the whole source.
_AGAIN_FLAG = re.compile(r"--again(?:\s+|$)", re.I)
AGAIN_NEEDS_A_FILE = ("--again reads again the sections of the files it names: give one, as in "
                      "/burgess:kg-build --again notes.md")

# Sections a build leaves out unless `--all` asks for them (0.23.1, `skip_reason`): a reference list, the back
# matter a publisher's page carries, and a section with no text below its heading. In the field's two Springer
# articles (2026-11-22) they made 42 of the 137 sections, every one read by an extractor and recorded as holding no
# edge (the reference lists among the longest: 9 000 to 25 000 characters); none of the 41 that held edges matches.
# A short section is not left out: the 16 between 1 and 59 characters there were all page furniture, which
# html-text/3 no longer copies, while a one-line note can state an edge ("La fábrica funciona cuando verifica cada
# cambio.", 49 characters, in the suite's notes).
_REFERENCE_TITLES = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:references?|bibliography|bibliograf[ií]a|referencias(?: bibliogr[aá]ficas)?|"
    r"refer[eê]ncias|works cited|literature cited|cited literature|literaturverzeichnis)\s*$", re.I)
_BACK_MATTER_TITLES = re.compile(
    r"^(?:rights and permissions|about this (?:article|chapter|paper)|cite this (?:article|chapter|paper)|"
    r"share this (?:article|chapter|paper)|publisher[’'`]*s? note|additional information|author information|"
    r"authors? and affiliations|corresponding authors?|profiles|ethics declarations|keywords|"
    r"acknowledge?ments?|funding|competing interests|conflicts? of interest(?:s?/competing interests)?|"
    r"ethical approval|informed consent|compliance with ethical standards|"
    # `avail[ai]bility`: the field's Copilot article titles it "Data Availibility Statement"
    r"data avail[ai]bility(?: statement)?|code avail[ai]bility)\s*$", re.I)
_ANY_WORD = re.compile(r"\w")


def skip_reason(title: "str | None", text: str) -> str:
    """Why a build leaves a section out (0.23.1), or "": `reference-list` (titled References, Bibliography,
    Referencias…), `back-matter` (a publisher's Rights and permissions, Cite this article, Author information,
    Funding, Competing interests…) or `empty` (no letter or digit below its heading, as a heading followed at once
    by its subheadings: nothing a verbatim span could quote). An extractor found no edge in any of them on the
    field's papers; each cost a run. `--all` plans them anyway."""
    head = (title or "").strip()
    if _REFERENCE_TITLES.match(head):
        return "reference-list"
    if _BACK_MATTER_TITLES.match(head):
        return "back-matter"
    body = text or ""
    first, _, rest = body.partition("\n")
    if first.lstrip().startswith("#"):
        body = rest
    return "" if _ANY_WORD.search(body) else "empty"


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
    - ``--leads`` as the first word asks for the leads mode (0.9.0); the rest of the line reads as above.
    - ``--all`` as the first word (0.23.1) plans every section, the ones `skip_reason` leaves out included.
    - ``--again`` as the first word (0.26.0) plans the covered sections of the subset's files again, whole. It
      needs a subset, and it does not go with ``--leads``.
    """
    line = (raw or "").strip()
    m = _LEADS_FLAG.match(line)
    if m:
        rest = parse_arguments(line[m.end():])
        problem = rest.problem or ("--leads and --again do not go together: --leads writes the leads grounders "
                                   "recorded, --again reads sections again" if rest.again else "")
        return BuildArguments(rest.subset, rest.wave_size, problem, leads=True, every=rest.every,
                              again=rest.again)
    m = _ALL_FLAG.match(line)
    if m:
        rest = parse_arguments(line[m.end():])
        return BuildArguments(rest.subset, rest.wave_size, rest.problem, leads=rest.leads, every=True,
                              again=rest.again)
    m = _AGAIN_FLAG.match(line)
    if m:
        rest = parse_arguments(line[m.end():])
        problem = rest.problem or ("" if rest.subset else AGAIN_NEEDS_A_FILE)
        if not problem and rest.leads:
            problem = ("--leads and --again do not go together: --leads writes the leads grounders recorded, "
                       "--again reads sections again")
        return BuildArguments(rest.subset, rest.wave_size, problem, leads=rest.leads, every=rest.every,
                              again=True)
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
    extractor contract asks ids to take.

    The marks are dropped with one `str.translate` over the distinct characters the text holds, not by a
    Python test of every character: since 0.11.5 a kg_context query folds the span of every edge it
    searches, and the per-character loop was about half its time. The result is the same string: exactly
    the characters with a nonzero combining class go."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    if not decomposed.isascii():  # no ASCII character is a combining mark
        marks = {ord(ch): None for ch in set(decomposed) - _ASCII_CHARS if unicodedata.combining(ch)}
        if marks:
            decomposed = decomposed.translate(marks)
    return decomposed.casefold()


_ASCII_CHARS = frozenset(map(chr, range(128)))


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


# ---- the sections an extraction wrote no edge from (0.14.0) ---------------------------------------------
#
# A section is covered once a span-present edge quotes it, and /kg-build launches an extractor for every section
# that is not. Some sections state no relation at all: a list of sources, a glossary, a checklist, a timeline.
# Their extractor writes nothing, or nodes without an edge, and through 0.13.6 every later build launched one
# again, to read the same text and find nothing again (field report on 0.13.6: a plain build re-planned 18 of
# 84 sections whose extractors had written no edge when the canon was built, and only the session's memory kept
# it from launching 18 extractors). The extractor now records such a section with `kg_record_edgeless_section`: one line in the
# ledger beside the canon (`canon.EDGELESS_SECTIONS`). The plan leaves the section out while a record still
# describes it, that is, while the section's text and the pack's types are the ones the extraction read. The
# ledger is engine state, not canon: a lost or unreadable one only offers those sections again, as before.

# The longest note a record keeps: a sentence on why the section held nothing to write.
MAX_EDGELESS_NOTE_CHARS = 500


def section_digest(text: str) -> str:
    """What a record knows a section's text by: the SHA-256 of its normalized text (`model.normalize_text`, the
    form coverage reads), heading line included. A record keeps matching a section that moved to another
    number, and stops matching once the text says something else."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def vocabulary_digest(pack) -> str:
    """The SHA-256 of the pack's node and edge type names, in any order: what an extractor may write. A new type
    can give a section that held nothing writable an edge (until 0.8.0 added `enables`, a span saying what makes
    something possible had no relation to go under), so a record made under another vocabulary no longer
    applies. ``""`` when no pack is loaded."""
    if pack is None:
        return ""
    types = {"node_types": sorted(pack.node_types), "edge_types": sorted(pack.edge_types)}
    return hashlib.sha256(json.dumps(types, sort_keys=True).encode("utf-8")).hexdigest()


def edgeless_record(file: str, section: int, title: str, text_digest: str, vocabulary: str, at: str,
                    note: str) -> str:
    """One ledger line (0.14.0): the file and section the plan named, the section's title, the digests of its
    text and of the pack's vocabulary, when it was recorded, and the extractor's note on why it wrote no edge.
    Only the file and the two digests decide whether a record applies; the rest is for whoever reads it."""
    return json.dumps({"file": file, "section": section, "title": title, "text_sha256": text_digest,
                       "vocabulary_sha256": vocabulary, "at": at, "note": note}, ensure_ascii=False)


def edgeless_records(lines) -> "dict[tuple[str, str, str], dict]":
    """``(file, text digest, vocabulary digest) -> {at, note}`` of the newest record for each, from the ledger's
    lines. A line that is not such a record (a torn last line, a hand edit, another shape) is skipped, never an
    error."""
    out: "dict[tuple[str, str, str], dict]" = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        key = (rec.get("file"), rec.get("text_sha256"), rec.get("vocabulary_sha256"))
        at, note = rec.get("at"), rec.get("note")
        if not (all(isinstance(k, str) for k in key) and key[0] and key[1]
                and isinstance(at, str) and at and isinstance(note, str)):
            continue
        if key not in out or at >= out[key]["at"]:
            out[key] = {"at": at, "note": note}
    return out


# ---- the text an extraction read (0.26.0) ----------------------------------------------------------------
#
# Through 0.25.2 a section counted as built once a span-present edge quoted it, and nothing kept the text its
# extraction had read. A claim added to such a section later never reached the graph: the plan called the
# section covered, and no argument read it again (end-to-end run of 2026-11-25: a sentence added to a built
# section, `/kg-build` again, "nothing to build"). Now each extraction leaves a record of what it read, in a
# ledger beside the canon (`canon.READ_SECTIONS`): the digest of every unit of the section's text, a unit being
# a paragraph, a list item or a table row. The plan offers a covered section again when it holds a unit that no
# record of its file holds, and `kg_section` hands that section's extractor the new units and the claims already
# written from the section, so it writes what is new. The ledger is engine state, not canon: a lost or unreadable
# one is replaced by a new baseline at the next plan, and an edit made before that baseline goes unseen.

# A unit starts at a list item, a numbered item, a table row or a heading line, or after a blank line.
_UNIT_START = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|\||#)")

# How many claims already written from a section `kg_section` hands a re-reading extractor at most, the same
# cap as the known nodes: a section quoted by more than this is rare, and `written_more` counts the rest.
WRITTEN_LIMIT = KNOWN_NODES_LIMIT


def section_units(text: str) -> "list[str]":
    """The units of a section's text, in order: each paragraph, list item and table row, verbatim, without the
    section's heading line (its title, which states no claim of its own). A unit with no letter or digit (a
    table's separator row, a rule) is left out. A paragraph re-wrapped over other lines is the same unit, since
    `unit_digest` reads the normalized text."""
    lines = (text or "").splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is not None and lines[first].lstrip().startswith("#"):
        lines = lines[first + 1:]
    units: "list[str]" = []
    current: "list[str]" = []

    def flush() -> None:
        if current:
            unit = "\n".join(current)
            if _ANY_WORD.search(unit):
                units.append(unit)
            current.clear()

    for line in lines:
        if not line.strip():
            flush()
            continue
        if current and _UNIT_START.match(line):
            flush()
        current.append(line)
    flush()
    return units


def unit_digest(unit: str) -> str:
    """What a record knows a unit by: the first 16 hex digits of the SHA-256 of its normalized text, enough to
    tell apart the units of one file and small enough that a ledger line stays short."""
    return hashlib.sha256(normalize_text(unit).encode("utf-8")).hexdigest()[:16]


# Who wrote a read record: the extraction's own kg_write, its extractor's record that the section held nothing
# (new) to write, or the plan's baseline for a file whose sections were built before any record existed.
READ_BY = ("write", "record", "baseline")


def read_record(file: str, section: int, title: str, text_digest: str, units: "Iterable[str]", at: str,
                by: str, audit_mark: "int | None" = None) -> str:
    """One line of the read ledger (0.26.0): the file and section, the section's title, the digest of its whole
    text, the digests of its units (`unit_digest`), when, and who recorded it (`READ_BY`). Only the file and the
    unit digests decide whether a section is offered again; the rest is for whoever reads the ledger.
    ``audit_mark`` (0.27.0) is the grounding audit log's size when the read was recorded: a verdict whose record
    starts before it came first. A byte offset orders a read and a verdict exactly, as their times, stamped to the
    second, cannot (`KGEngine._obsolete_returns`)."""
    rec = {"file": file, "section": section, "title": title, "text_sha256": text_digest,
           "units": [unit_digest(u) for u in units], "at": at, "by": by}
    if isinstance(audit_mark, int) and audit_mark >= 0:
        rec["audit_mark"] = audit_mark
    return json.dumps(rec, ensure_ascii=False)


def read_units(lines) -> "dict[str, dict]":
    """``file -> {"units": set of unit digests, "at": the newest record's time, "first": {digest: (at, by, mark)}}``
    over every record of the ledger's lines. A unit any record of a file holds has been read; the plan offers a
    covered section again only for a unit no record holds. ``first`` (0.27.0) is the earliest record that holds each
    unit: when, by whom, and its ``audit_mark`` (None for a record from 0.26.0). A unit an extraction read first
    after a claim was marked obsolete is text new to that claim (`KGEngine._obsolete_returns`); one a baseline took
    is not. A line that is not such a record (a torn last line, a hand edit) is skipped, never an error."""
    out: "dict[str, dict]" = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        file, units, at = rec.get("file"), rec.get("units"), rec.get("at")
        if not (isinstance(file, str) and file and isinstance(units, list) and isinstance(at, str) and at):
            continue
        by = rec.get("by") if isinstance(rec.get("by"), str) else ""
        mark = rec.get("audit_mark")
        mark = mark if isinstance(mark, int) and not isinstance(mark, bool) and mark >= 0 else None
        entry = out.setdefault(file, {"units": set(), "at": at, "first": {}})
        for u in units:
            if not (isinstance(u, str) and u):
                continue
            entry["units"].add(u)
            seen = entry["first"].get(u)
            if seen is None or at < seen[0]:
                entry["first"][u] = (at, by, mark)
        if at > entry["at"]:
            entry["at"] = at
    return out
