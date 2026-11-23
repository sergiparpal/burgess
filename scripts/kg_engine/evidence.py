"""External evidence (0.21.0): outside texts the user registers to support or refute what the graph says,
each with an epistemic level.

Through 0.20.2 every verdict was judged against the configured sources, the user's own notes, so `grounded`
meant "my notes say it". The one way to bring in outside support was `kg_ground(support_note=...)`, a citation
with no span: the engine could check neither that it exists nor that it says what the grounder claimed, and
the promotion recorded it as `inferred`. A registered source turns that outside support into a span the
engine verifies, because the text it is checked against is a copy the engine made itself.

**The level measures the filter a text passed before it was published, never whether a claim is true** (the
engine's razor, "embeddings measure dispersion, never truth", applied to sources). A grounder still judges only
whether a passage says what a claim says. The level travels beside the verdict and decides only what may be
used as support or as a refutation:

- ``LEVELS``: 1 reviewed (peer review), 2 institutional (a body answers for it, with a published method),
  3 editorial (an editor checks and corrects), 4 author or community (the author's reputation, moderation
  after publication), 5 unfiltered (no filter, or the aim is to sell, persuade or rank). Level 5 is an object
  of study only: it supports and refutes nothing.
- ``ROLES``: how far the text is from the fact. Primary is its origin (the data, the experiment, the spec, the
  code, the author's own statement); secondary analyses primaries and cites them; tertiary summarizes without
  pointing to the origin.
- ``MARKS``: `interest` (the author gains if the claim holds), `corrected`, `retracted`, `superseded` (a newer
  version of this same document exists). A retracted or superseded source supports and refutes nothing.
- The configured sources sit outside the scale, as ``OWN``.

**Where they live.** ``<project>/evidence/``, per source: the text file the engine wrote
(``ext-<slug>-<hash>.md``), a sidecar ``<same stem>.source.json`` with the record, and for a fetched URL the
bytes as received under ``raw/``. The text file holds only the extracted text, so a span can only match the
content. The record keeps the sha256 of the text as written, and a text file whose bytes no longer match is
left out of the evidence set and reported: a hand edit can never forge a span (register the source again
instead). A ``.md``/``.txt`` with no sidecar is reported as unregistered and ignored, fail-closed.

**What they are used for.** Span verification (kg_write, kg_ground, the R3 staleness scan), the grounder's
evidence views (kg_ground_item), and the source signature that wakes waiting pins. Never extraction:
kg_build_plan, kg_section, coverage and the specificity corpus read the configured sources only, so a
registered paper never floods the graph with its own content.

**The copy is the engine's.** WebFetch answers a prompt about a page with a small model, so a "verbatim" span
taken from it would be verbatim of a paraphrase. The engine fetches the bytes itself (stdlib urllib, a generic
User-Agent that says nothing about the user) and extracts the text with a fixed rule (stdlib html.parser: no
native code, which Smart App Control blocks on the user's Windows machine). PDF is refused, as the configured
sources refuse it (`sources.py`): a lossy transcript would make a verbatim span a guess. Convert it to Markdown
and register the file.

**Every source has a level, the notes included (0.22.0).** Through 0.21.0 the configured sources sat outside
the scale, so notes of unknown level verified an idea as a peer-reviewed paper did, and were shielded from it.
Now the project's ``Policy`` (``policy.json`` in the evidence directory) gives each configured file a level
(``notes_level``, 4 by default: a text by an author nobody reviewed, unless the user sets another per file),
says the worst level that may still support or refute (``required_level``, 4 by default: everything but
unfiltered; 1: only peer-reviewed sources verify, and the notes only propose), and whether the configured
sources are extracted at all (``build_from_notes``). A registered source with ``build`` is extracted like a
note, so a graph can be built from level-1 sources alone. The veto on `failed` is the same for every source.
With no policy file every default reproduces 0.21.0, except that the notes are no longer out of reach of an
external source of a higher level.

Everything here is pure or touches only ``<project>/evidence/``: no canon write, no verdict.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from html.parser import HTMLParser
from pathlib import Path

from .atomicio import atomic_write_bytes, atomic_write_text
from .model import slug, utcnow

EVIDENCE_DIRNAME = "evidence"
RAW_DIRNAME = "raw"
META_SUFFIX = ".source.json"
NAME_PREFIX = "ext-"
SCHEMA = 1

LEVELS = {1: "reviewed", 2: "institutional", 3: "editorial", 4: "author-or-community", 5: "unfiltered"}
UNFILTERED = 5
ROLES = ("primary", "secondary", "tertiary")
MARKS = ("interest", "corrected", "retracted", "superseded")
# A source with one of these marks supports and refutes nothing (it stays registered, and readable).
UNUSABLE_MARKS = ("retracted", "superseded")
OWN = "own"
# The relations a counter-edge carries: the adversarial grounder's weapons (agents/adversarial-grounder.md).
# A `failed` verdict names one such edge as what refutes the claim, so the engine knows the refutation's
# source and can apply the level rules (`failed_veto`).
COUNTER_RELATIONS = ("attacked_by", "confounded_by", "collapses_into")
LEVEL_BY = ("agent", "human")
# What a support_note promotion writes (0.21.0; `citation: ` through 0.20.2): the engine cannot check it.
CITATION_MARK = "citation (unchecked): "
# What a failed verdict appends: the counter-edge whose span refuted the claim.
REFUTED_BY_MARK = "refuted by: "
# What grounding a claim on another source's span appends to the edge's notes (0.22.0), as a JSON object so a
# ` | ` inside the span (a table row) cannot split it: the claim keeps the span it was extracted from, and the
# support it was grounded on is recorded beside it.
SUPPORT_MARK = "support: "
# Another passage an extractor quoted for the same edge (0.23.1): the edge keeps the passage it was first written
# with, and each later one is kept beside it, so every section that wrote the edge counts as covered.
ALSO_MARK = "also stated: "
ALSO_MAX = 8
POLICY_FILE = "policy.json"
DEFAULT_REQUIRED_LEVEL = 4     # the worst level that may support or refute: everything but unfiltered
DEFAULT_NOTES_LEVEL = 4        # a configured file with no level of its own: a text by an author nobody reviewed
# A project's own notes folder (0.23.0, `Policy.notes_path`): empty for the plugin's global `source_path`, this
# word for no notes at all, else a path inside the project. Claude Code keeps plugin options per user and ignores
# a project's settings for them (a cloned repository must not choose what the plugin reads), so the project's
# choice lives in its policy, and stays inside the project for the same reason.
NOTES_NONE = "none"
# What a project's notes path may not name: the engine's own folders, whose files are not the user's notes.
NOTES_RESERVED = (".git", ".claude", ".kg", ".kg-data", "canon", EVIDENCE_DIRNAME)
VETO_HINTS = {
    "refuted-by-has-no-span": "the counter-edge has no span the engine can place, so nothing says where the "
                              "refutation comes from",
    "failed-by-unusable-source": "the refuting span lies in a source that refutes nothing under this project's "
                                 "policy (level 5, retracted, superseded, or below the required level); leave "
                                 "the counter-edge as a recorded challenge",
    "failed-by-lower-level": "a source of a lower level cannot fail a claim supported by a higher one: the "
                             "counter-edge stands as a visible dispute",
}

_TEXT_EXTS = (".md", ".txt")
_LOCAL_TEXT_EXTS = (".md", ".markdown", ".txt")
_LOCAL_HTML_EXTS = (".html", ".htm")
_HTML_TYPES = ("text/html", "application/xhtml+xml")
_PLAIN_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
MAX_BYTES = 5_000_000
FETCH_TIMEOUT = 20.0
# Generic on purpose: the request goes to a third party and must carry nothing about the user or the project.
USER_AGENT = "Mozilla/5.0 (compatible; evidence-copy/1.0)"
_ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9,text/markdown;q=0.9,*/*;q=0.1"
# The fixed HTML rule's version, recorded with each copy. 2 (0.22.1) drops MathML annotations and invisible
# math operators: version 1 copied the LaTeX source beside each rendered formula (`15×\times`, field arXiv copy
# of 2026-11-22). 3 (0.23.1) keeps only a page's <main> when it has one and leaves out page furniture
# (`_FURNITURE_RE`). A copy keeps the version it was made with: its hash is its record's.
HTML_EXTRACTOR = "html-text/3"
VERBATIM = "verbatim"
PREVIEW_CHARS = 1500
_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_LOOSE_DATE_RE = re.compile(r"(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?")
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_WS_RE = re.compile(r"\s+")


class EvidenceError(Exception):
    """A refusal with a stable `code` (the tool returns it as `error`) and a human `detail`."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------------------- the record

@dataclass
class EvidenceRecord:
    """One registered source, as its sidecar stores it. `retrieved_at` is the one date the engine certifies
    (it made the copy then); `published` is what the source or the caller claims (`published_from`: `page`,
    `caller` or "")."""
    name: str
    title: str = ""
    url: str = ""
    final_url: str = ""
    origin: str = "url"            # url | file
    retrieved_at: str = ""
    published: str = ""
    published_from: str = ""       # page | caller | ""
    level: int = 4
    level_by: str = "agent"        # through the tool surface always "agent"; only a hand edit says "human"
    role: str = "secondary"
    marks: list = field(default_factory=list)
    derives_from: str = ""         # another registered source this one repeats: it is not independent of it
    note: str = ""                 # why this level
    content_type: str = ""
    extractor: str = ""
    sha256_raw: str = ""           # of the bytes as received (or as read, for a local file)
    sha256_text: str = ""          # of the text file as written: the integrity check
    raw: str = ""                  # the raw copy's path under evidence/, or ""
    build: bool = False            # extracted into the graph like a configured source (0.22.0)
    updated_at: str = ""
    schema: int = SCHEMA

    @property
    def stem(self) -> str:
        return Path(self.name).stem


_RECORD_FIELDS = {f.name for f in fields(EvidenceRecord)}


def level_unusable(level: int, marks, required: int = DEFAULT_REQUIRED_LEVEL) -> str:
    """Why a source at `level` with `marks` can neither support nor refute anything under a project that
    requires `required`, or "" when it can: `unfiltered` (level 5, an object of study only), the first of its
    `UNUSABLE_MARKS`, or `below-required-level` (0.22.0)."""
    if level >= UNFILTERED:
        return "unfiltered"
    for mark in UNUSABLE_MARKS:
        if mark in (marks or ()):
            return mark
    if level > required:
        return "below-required-level"
    return ""


def unusable_reason(rec: EvidenceRecord, required: int = DEFAULT_REQUIRED_LEVEL) -> str:
    """`level_unusable` for a registered source."""
    return level_unusable(rec.level, rec.marks, required)


def label(rec: EvidenceRecord, required: int = DEFAULT_REQUIRED_LEVEL) -> dict:
    """What a grounder sees of an external source beside a passage from it (kg_ground_item)."""
    why = unusable_reason(rec, required)
    out = {"class": "external", "file": rec.name, "level": rec.level, "level_name": LEVELS[rec.level],
           "role": rec.role, "marks": list(rec.marks), "usable": not why,
           "title": rec.title, "url": rec.url, "published": rec.published}
    if why:
        out["unusable"] = why
    if rec.derives_from:
        out["derives_from"] = rec.derives_from
    if rec.build:
        out["build"] = True
    return out


def failed_veto(claim: dict, refuting: dict) -> str:
    """"" when a counter-edge whose span lies in `refuting` may stamp `failed` on a claim whose support lies
    in `claim`, else the refusal code. Each side is ``{"class": "own" | "external" | "none", "level": int,
    "usable": bool}`` ("none": no span, or a span the engine cannot place).

    The level is a veto, never the winner (2026-11-21 design): a refutation only removes what a grounder may
    do, and the text must still refute the claim. An unusable source refutes nothing; a lower level cannot fail
    a claim a higher one supports; a claim with no usable support has nothing to protect. Since 0.22.0 the
    same rules hold for every source: the notes have a level (`Policy`), so a source of a higher level can fail
    a claim only the notes support, and the notes can fail a claim of a lower level. Through 0.21.0 the notes
    and an external source never failed each other, which shielded notes of unknown level from a reviewed
    paper."""
    if refuting.get("class") not in ("own", "external"):
        return "refuted-by-has-no-span"
    if not refuting.get("usable"):
        return "failed-by-unusable-source"
    if claim.get("class") not in ("own", "external") or not claim.get("usable"):
        return ""
    if int(refuting.get("level", UNFILTERED)) > int(claim.get("level", UNFILTERED)):
        return "failed-by-lower-level"
    return ""


# ---------------------------------------------------------------------------------------- the policy

@dataclass
class Policy:
    """A project's evidence policy (0.22.0), stored as `policy.json` in its evidence directory.

    `required_level` is the worst level that may still support or refute (1-4; 4 accepts everything but
    unfiltered sources, 1 only peer-reviewed ones). `notes_level` is the level of a configured file with no
    record of its own (1-5). `notes` holds the per-file records the user set: ``{basename: {level, role,
    marks, note, updated_at}}``. `build_from_notes` says whether the configured sources are extracted into
    the graph; false, with registered sources marked `build`, builds a graph from those sources alone.
    `notes_path` (0.23.0) is the project's own notes: empty for the plugin's `source_path`, `NOTES_NONE` for no
    notes, else a path relative to the project, a folder, a file or a glob, always inside it."""
    required_level: int = DEFAULT_REQUIRED_LEVEL
    notes_level: int = DEFAULT_NOTES_LEVEL
    build_from_notes: bool = True
    notes: dict = field(default_factory=dict)
    notes_path: str = ""
    updated_at: str = ""
    schema: int = SCHEMA

    def is_default(self) -> bool:
        """True when the policy changes nothing 0.21.0 did on support (the source signature leaves it out)."""
        return (self.required_level == DEFAULT_REQUIRED_LEVEL and self.notes_level == DEFAULT_NOTES_LEVEL
                and self.build_from_notes and not self.notes and not self.notes_path)

    def fingerprint(self) -> str:
        """A stable text of what bears on verdicts, for the source signature: a change wakes waiting items."""
        out = {"required_level": self.required_level, "notes_level": self.notes_level,
               "build_from_notes": self.build_from_notes,
               "notes": {k: {"level": v.get("level"), "marks": v.get("marks", [])}
                         for k, v in sorted(self.notes.items())}}
        if self.notes_path:   # left out when unset, so a 0.22 policy keeps its fingerprint
            out["notes_path"] = self.notes_path
        return json.dumps(out, sort_keys=True, ensure_ascii=False)

    def note(self, name: str) -> dict:
        """The record of a configured file: its own, else the default level with no role and no marks."""
        rec = self.notes.get(Path(name or "").name) or {}
        return {"level": rec.get("level", self.notes_level), "role": rec.get("role", ""),
                "marks": list(rec.get("marks", [])), "note": rec.get("note", ""), "recorded": bool(rec)}


def parse_required_level(value) -> int:
    level = parse_level(value)
    if level >= UNFILTERED:
        raise EvidenceError("bad-required-level", "level 5 supports nothing: the required level is 1-4")
    return level


_GLOB_CHARS = set("*?[")


def _glob_cut(parts) -> int:
    """The index of the first path part with a wildcard, or the number of parts."""
    return next((i for i, part in enumerate(parts) if _GLOB_CHARS & set(part)), len(parts))


def notes_path_problem(value: str, project_dir: "Path | None") -> str:
    """Why a stored or given notes path cannot be used (0.23.0), or "" when it can. It must lie inside the
    project once resolved, symlinks and `..` included, and name none of the engine's own folders
    (`NOTES_RESERVED`). A glob is checked by the folder before its first wildcard."""
    if not value or value.lower() == NOTES_NONE:
        return ""
    if project_dir is None:
        return "notes-path-without-project"
    raw = Path(value)
    cut = _glob_cut(raw.parts)
    base = Path(*raw.parts[:cut]) if cut else Path(".")
    full = base if base.is_absolute() else Path(project_dir) / base
    try:
        root = Path(project_dir).resolve()
        target = full.resolve()
    except (OSError, RuntimeError):
        return "notes-path-unreadable"
    try:
        rel = target.relative_to(root)
    except ValueError:
        return "notes-path-outside-project"
    if rel.parts and rel.parts[0].lower() in {r.lower() for r in NOTES_RESERVED}:
        return "notes-path-reserved"
    return ""


def parse_notes_path(value, project_dir: "Path | None") -> str:
    """The notes path a user gives (0.23.0), as the policy stores it: "" for `default` (the plugin's
    `source_path`), `NOTES_NONE` for `none`, else a path inside the project, stored relative to it with
    forward slashes ("." for the project folder itself). Refused when it lies outside the project, names one of
    the engine's folders, or names nothing that exists (a glob may match nothing yet)."""
    text = str(value if value is not None else "").strip().strip('"').strip("'").strip()
    if text.lower() in ("", "default", "global"):
        return ""
    if text.lower() == NOTES_NONE:
        return NOTES_NONE
    problem = notes_path_problem(text, project_dir)
    if problem:
        hint = {"notes-path-outside-project": "a project's notes must lie inside the project folder; the "
                "plugin option source_path names a folder anywhere, for every project",
                "notes-path-reserved": "canon, evidence, .kg, .git and .claude hold the engine's own files, "
                "not notes"}.get(problem, "")
        raise EvidenceError(problem, f"{text}: {hint}" if hint else text)
    raw = Path(text)
    cut = _glob_cut(raw.parts)
    base = Path(*raw.parts[:cut]) if cut else Path(".")
    full = base if base.is_absolute() else Path(project_dir) / base
    if cut == len(raw.parts) and not full.exists():
        raise EvidenceError("notes-path-not-found", text)
    rel = full.resolve().relative_to(Path(project_dir).resolve())
    return Path(rel, *raw.parts[cut:]).as_posix() if (rel.parts or cut < len(raw.parts)) else "."


def parse_bool(value, code: str = "bad-flag") -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "si", "sí", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise EvidenceError(code, "true or false")


def load_policy(directory: "Path | None") -> "tuple[Policy, list]":
    """The project's policy, or the defaults when there is none; a malformed file is reported and the
    defaults apply (fail-safe: the defaults are 0.21.0's acceptance), with ``problems`` naming it."""
    pol, problems = Policy(), []
    if directory is None:
        return pol, problems
    path = Path(directory) / POLICY_FILE
    if not path.is_file():
        return pol, problems
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise EvidenceError("policy-malformed", "not a JSON object")
        out = Policy(required_level=parse_required_level(data.get("required_level", DEFAULT_REQUIRED_LEVEL)),
                     notes_level=parse_level(data.get("notes_level", DEFAULT_NOTES_LEVEL)),
                     build_from_notes=parse_bool(data.get("build_from_notes", True), "policy-malformed"),
                     updated_at=str(data.get("updated_at") or ""))
        # The project's own notes (0.23.0). A value a hand edit or a cloned repository put there is checked
        # here too: one outside the project is reported and ignored, and the plugin's source_path applies.
        stored = data.get("notes_path") or ""
        if not isinstance(stored, str):
            raise EvidenceError("policy-malformed", "`notes_path` is a path")
        stored = stored.strip()
        problem = notes_path_problem(stored, Path(directory).parent)
        if problem:
            problems.append({"file": POLICY_FILE, "problem": problem, "detail": stored})
        else:
            out.notes_path = NOTES_NONE if stored.lower() == NOTES_NONE else stored
        notes = data.get("notes") or {}
        if not isinstance(notes, dict):
            raise EvidenceError("policy-malformed", "`notes` is a map of file names")
        for name, rec in notes.items():
            if not isinstance(rec, dict) or Path(str(name)).name != name:
                raise EvidenceError("policy-malformed", f"bad record for {name!r}")
            entry = {"level": parse_level(rec.get("level", out.notes_level)),
                     "marks": parse_marks(rec.get("marks", [])),
                     "role": parse_role(rec["role"]) if rec.get("role") else "",
                     "note": str(rec.get("note") or ""), "updated_at": str(rec.get("updated_at") or "")}
            out.notes[name] = entry
        return out, problems
    except EvidenceError as e:
        problems.append({"file": POLICY_FILE, "problem": e.code, "detail": e.detail})
    except (OSError, ValueError) as e:
        problems.append({"file": POLICY_FILE, "problem": "policy-unreadable", "detail": str(e)})
    return pol, problems


def write_policy(directory: Path, pol: Policy) -> None:
    pol.updated_at = utcnow()
    atomic_write_text(Path(directory) / POLICY_FILE,
                      json.dumps(asdict(pol), indent=2, ensure_ascii=False) + "\n")


def note_label(pol: Policy, name: str) -> dict:
    """What a grounder sees of a configured file (the user's notes) beside a passage from it (0.22.0)."""
    rec = pol.note(name)
    why = level_unusable(rec["level"], rec["marks"], pol.required_level)
    out = {"class": OWN, "file": Path(name).name, "level": rec["level"], "level_name": LEVELS[rec["level"]],
           "role": rec["role"], "marks": rec["marks"], "usable": not why}
    if why:
        out["unusable"] = why
    return out


# ------------------------------------------------------------------------------ support on another source

def support_segment(span: str, source_file: str) -> str:
    """The notes segment that records a claim grounded on `span` in `source_file` (0.22.0)."""
    return SUPPORT_MARK + json.dumps({"span": span, "source_file": source_file}, ensure_ascii=False)


def supports_of(notes: "str | None") -> "list[tuple[str, str]]":
    """``(span, source_file)`` of every support segment in an edge's notes, in order. A segment that is not
    one the engine writes is skipped."""
    return _segments(notes, SUPPORT_MARK)


def also_segment(span: str, source_file: str) -> str:
    """The notes segment that records another passage stating an edge (0.23.1)."""
    return ALSO_MARK + json.dumps({"span": span, "source_file": source_file}, ensure_ascii=False)


def also_passages(notes: "str | None") -> "list[tuple[str, str]]":
    """``(span, source_file)`` of every `also stated:` segment in an edge's notes, in order (0.23.1)."""
    return _segments(notes, ALSO_MARK)


def _segments(notes: "str | None", mark: str) -> "list[tuple[str, str]]":
    text, out, pos = notes or "", [], 0
    decoder = json.JSONDecoder()
    while True:
        at = text.find(mark + "{", pos)
        if at < 0:
            return out
        try:
            value, end = decoder.raw_decode(text, at + len(mark))
        except ValueError:
            pos = at + len(mark)
            continue
        pos = end
        if isinstance(value, dict) and isinstance(value.get("span"), str) and value["span"].strip() \
                and isinstance(value.get("source_file"), str):
            out.append((value["span"], value["source_file"]))


# ----------------------------------------------------------------------------------- argument parsing

def parse_level(value) -> int:
    """1–5 from an int, "3", "N3" or a level name; EvidenceError `bad-level` otherwise."""
    if isinstance(value, bool):
        raise EvidenceError("bad-level", "a level is 1-5")
    if isinstance(value, int) and value in LEVELS:
        return value
    text = str(value or "").strip().lower()
    if text.startswith("n") and text[1:].isdigit():
        text = text[1:]
    if text.isdigit() and int(text) in LEVELS:
        return int(text)
    for n, name in LEVELS.items():
        if text == name:
            return n
    raise EvidenceError("bad-level", "a level is 1-5: " + ", ".join(f"{n} {v}" for n, v in LEVELS.items()))


def parse_role(value) -> str:
    text = str(value or "").strip().lower()
    if text in ROLES:
        return text
    raise EvidenceError("bad-role", "a role is primary, secondary or tertiary")


def parse_marks(value) -> list:
    """The marks as a list in `MARKS` order, from a list or a comma/space-separated string ("" → [])."""
    items = value if isinstance(value, (list, tuple)) else re.split(r"[\s,]+", str(value or ""))
    marks = {str(m).strip().lower() for m in items if str(m).strip()}
    unknown = sorted(marks - set(MARKS))
    if unknown:
        raise EvidenceError("bad-marks", f"unknown mark(s) {', '.join(unknown)}; marks are {', '.join(MARKS)}")
    return [m for m in MARKS if m in marks]


def parse_published(value) -> str:
    """"" or a YYYY / YYYY-MM / YYYY-MM-DD date; EvidenceError `bad-published` otherwise."""
    text = str(value or "").strip()
    if not text:
        return ""
    m = _DATE_RE.match(text)
    if m and (m.group(2) is None or 1 <= int(m.group(2)) <= 12) \
            and (m.group(3) is None or 1 <= int(m.group(3)) <= 31):
        return text
    raise EvidenceError("bad-published", "a publication date is YYYY, YYYY-MM or YYYY-MM-DD")


def _loose_date(text: str) -> str:
    """The first YYYY[-MM[-DD]] in a page's date metadata, normalized, or ""."""
    m = _LOOSE_DATE_RE.search(text or "")
    if not m:
        return ""
    year, month, day = m.group(1), m.group(2), m.group(3)
    if month is None or not 1 <= int(month) <= 12:
        return year
    if day is None or not 1 <= int(day) <= 31:
        return f"{year}-{int(month):02d}"
    return f"{year}-{int(month):02d}-{int(day):02d}"


# ------------------------------------------------------------------------------------ the registry

@dataclass
class EvidenceRegistry:
    """The registered sources of one project, read from its evidence directory. `records` holds only the
    sources whose text file is present and matches its recorded sha256; `problems` names every sidecar left
    out and why; `unregistered` lists the text files no sidecar claims."""
    directory: "Path | None" = None
    records: "dict[str, EvidenceRecord]" = field(default_factory=dict)
    problems: list = field(default_factory=list)
    unregistered: list = field(default_factory=list)

    def get(self, name: str) -> "EvidenceRecord | None":
        return self.records.get(Path(name or "").name)

    def text_paths(self) -> "list[Path]":
        """The text files of the registered sources, in name order: what the verification set appends."""
        if self.directory is None:
            return []
        return [self.directory / name for name in self.records]

    def __bool__(self) -> bool:
        return bool(self.records)

    def __len__(self) -> int:
        return len(self.records)


def evidence_dir(project_dir) -> Path:
    return Path(project_dir) / EVIDENCE_DIRNAME


def registry_signature(directory: "Path | None") -> tuple:
    """A cheap ``(name, size, mtime_ns)`` tuple over the directory's own files (sidecars and texts; `raw/`
    is not read), so the engine re-reads the registry only when one of them moved."""
    if directory is None or not directory.is_dir():
        return ()
    sig = []
    for p in sorted(directory.iterdir(), key=lambda q: q.name):
        if p.name.startswith(".") or not p.is_file():
            continue
        try:
            st = p.stat()
            sig.append((p.name, st.st_size, st.st_mtime_ns))
        except OSError:
            sig.append((p.name, None, None))
    return tuple(sig)


def _record_from(data: dict) -> EvidenceRecord:
    """A record from a sidecar's JSON, or EvidenceError naming what is wrong with it."""
    if not isinstance(data, dict):
        raise EvidenceError("sidecar-malformed", "not a JSON object")
    known = {k: v for k, v in data.items() if k in _RECORD_FIELDS}
    name = known.get("name")
    if not isinstance(name, str) or Path(name).name != name or Path(name).suffix.lower() not in _TEXT_EXTS:
        raise EvidenceError("sidecar-malformed", "`name` must be the text file's basename (.md or .txt)")
    rec = EvidenceRecord(name=name)
    for key, value in known.items():
        if key != "name":
            setattr(rec, key, value)
    rec.level = parse_level(rec.level)
    rec.role = parse_role(rec.role)
    rec.marks = parse_marks(rec.marks)
    rec.published = parse_published(rec.published)
    if rec.level_by not in LEVEL_BY:
        raise EvidenceError("sidecar-malformed", "`level_by` is agent or human")
    if not isinstance(rec.build, bool):
        raise EvidenceError("sidecar-malformed", "`build` is true or false")
    for key in ("title", "url", "final_url", "origin", "retrieved_at", "published_from", "derives_from",
                "note", "content_type", "extractor", "sha256_raw", "sha256_text", "raw", "updated_at"):
        if not isinstance(getattr(rec, key), str):
            raise EvidenceError("sidecar-malformed", f"`{key}` must be a string")
    if not rec.sha256_text:
        raise EvidenceError("sidecar-malformed", "`sha256_text` is missing")
    return rec


def load_registry(directory: "Path | None") -> EvidenceRegistry:
    """Read every sidecar in `directory`. A malformed sidecar, a missing text file, or a text file whose
    sha256 no longer matches the record is left out and reported in `problems` (fail-closed: a hand edit
    of a copy must never become a span the engine vouches for)."""
    reg = EvidenceRegistry(directory=Path(directory) if directory else None)
    if reg.directory is None or not reg.directory.is_dir():
        return reg
    claimed: "set[str]" = set()
    for meta in sorted(reg.directory.glob(f"*{META_SUFFIX}"), key=lambda q: q.name):
        if meta.name.startswith("."):
            continue
        try:
            rec = _record_from(json.loads(meta.read_text(encoding="utf-8")))
        except EvidenceError as e:
            reg.problems.append({"file": meta.name, "problem": e.code, "detail": e.detail})
            continue
        except (OSError, ValueError) as e:
            reg.problems.append({"file": meta.name, "problem": "sidecar-unreadable", "detail": str(e)})
            continue
        if meta.name != rec.stem + META_SUFFIX:
            reg.problems.append({"file": meta.name, "problem": "name-mismatch",
                                 "detail": f"the sidecar names {rec.name}"})
            continue
        claimed.add(rec.name)
        text_path = reg.directory / rec.name
        try:
            data = text_path.read_bytes()
        except OSError:
            reg.problems.append({"file": meta.name, "problem": "text-missing", "detail": rec.name})
            continue
        if hashlib.sha256(data).hexdigest() != rec.sha256_text:
            reg.problems.append({"file": rec.name, "problem": "text-edited",
                                 "detail": "the copy no longer matches what the engine wrote; register the "
                                           "source again instead of editing it"})
            continue
        reg.records[rec.name] = rec
    for p in sorted(reg.directory.iterdir(), key=lambda q: q.name):
        if (p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _TEXT_EXTS
                and p.name not in claimed):
            reg.unregistered.append(p.name)
    return reg


def write_record(directory: Path, rec: EvidenceRecord) -> None:
    """Write `rec`'s sidecar atomically (the text file is never rewritten: its hash is the record's)."""
    atomic_write_text(Path(directory) / (rec.stem + META_SUFFIX),
                      json.dumps(asdict(rec), indent=2, ensure_ascii=False) + "\n")


def store(directory: Path, rec: EvidenceRecord, text: str, raw: "bytes | None" = None,
          raw_ext: str = "") -> EvidenceRecord:
    """Write a new source: the raw copy (if any), then the text, then the sidecar, which is what registers
    it (a crash before the sidecar leaves an unregistered text, reported and ignored). Fills `sha256_text`,
    `raw` and `updated_at`."""
    directory = Path(directory)
    data = text.encode("utf-8")
    rec.sha256_text = hashlib.sha256(data).hexdigest()
    if raw is not None:
        rec.raw = f"{RAW_DIRNAME}/{rec.stem}{raw_ext}"
        atomic_write_bytes(directory / rec.raw, raw)
    atomic_write_bytes(directory / rec.name, data)
    rec.updated_at = utcnow()
    write_record(directory, rec)
    return rec


def make_name(title: str, url: str, fallback: str, text_sha: str) -> str:
    """``ext-<slug>-<first 8 of the text's sha256>.md``. The prefix keeps an external copy from ever sharing
    a basename with a configured source (span verification keys files by basename)."""
    base = title or _url_stem(url) or fallback or "source"
    stem = slug(base)[:48].strip("-_") or "source"
    return f"{NAME_PREFIX}{stem}-{text_sha[:8]}.md"


def _url_stem(url: str) -> str:
    m = re.match(r"^[a-z]+://([^/?#]+)([^?#]*)", url or "", re.I)
    if not m:
        return ""
    tail = [part for part in m.group(2).split("/") if part]
    return f"{m.group(1)} {tail[-1]}" if tail else m.group(1)


# --------------------------------------------------------------------------------- fetch and extract

@dataclass
class Fetched:
    data: bytes
    content_type: str
    charset: str
    final_url: str


def _urlopen(req, timeout):
    """The opener `fetch` uses (module-level, so a test replaces it: the suite never touches the network)."""
    return urllib.request.urlopen(req, timeout=timeout)


def fetch(url: str, *, timeout: float = FETCH_TIMEOUT, max_bytes: int = MAX_BYTES) -> Fetched:
    """The bytes at `url` as the server sends them. http(s) only; at most `max_bytes`."""
    target = (url or "").strip()
    if not re.match(r"^https?://[^/\s]+", target, re.I):
        raise EvidenceError("url-not-http", "only http:// and https:// URLs are fetched")
    req = urllib.request.Request(target, headers={"User-Agent": USER_AGENT, "Accept": _ACCEPT})
    try:
        with _urlopen(req, timeout) as resp:
            ctype = (resp.headers.get_content_type() or "").lower()
            charset = resp.headers.get_content_charset() or ""
            data = resp.read(max_bytes + 1)
            final = resp.geturl() or target
    except urllib.error.HTTPError as e:
        raise EvidenceError("fetch-failed", f"HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        raise EvidenceError("fetch-failed", str(reason)) from None
    if len(data) > max_bytes:
        raise EvidenceError("too-large", f"more than {max_bytes} bytes")
    return Fetched(data, ctype, charset, final)


def decode(data: bytes, charset: str = "") -> str:
    """Strict decoding: the declared charset, else UTF-8. Never `errors="replace"`, which could forge phantom
    span matches (the same rule as `SourceSet`). A leading BOM is dropped."""
    for name in ([charset] if charset else []) + ["utf-8"]:
        try:
            codecs.lookup(name)
        except LookupError:
            continue
        try:
            text = data.decode(name)
        except (UnicodeDecodeError, ValueError):
            continue
        return text[1:] if text.startswith("﻿") else text
    raise EvidenceError("undecodable", "the text is neither in its declared charset nor UTF-8")


def sniff_charset(data: bytes) -> str:
    m = _META_CHARSET_RE.search(data[:4096])
    return m.group(1).decode("ascii", "ignore") if m else ""


# The tags whose content is never text of the page. `annotation` / `annotation-xml` (0.22.1) hold a formula's
# source (LaTeX, content MathML) beside its rendering: copying both doubled every formula.
_SKIP = frozenset({"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed",
                   "nav", "footer", "form", "button", "select", "head", "annotation", "annotation-xml", "aside"})
# Page furniture inside a page's text (3, 0.23.1): an element whose role says it is navigation, a sidebar, a
# banner or a search box, or whose class or id names a recommendation list, related content, sharing,
# comments, cookies or an advert. Readability-style names, kept narrow: a "Related work" section is the
# article's own, so only `related-articles`, `related-content`, `related-subjects`… count, and no layout word:
# Springer's article container is `eds-l-with-sidebar`, and a sidebar itself is an <aside> or role=complementary.
_FURNITURE_ROLES = frozenset({"navigation", "complementary", "contentinfo", "search", "banner"})
_FURNITURE_RE = re.compile(
    r"(?:^|[\s_-])(?:recommend\w*|related[-_](?:articles?|content|subjects?|posts?|links?|stories|items?|reading)"
    r"|share|sharing|social\w*|breadcrumbs?|cookie\w*|advert\w*|sponsor\w*|promo\w*|newsletter|"
    r"comments?|subscribe\w*)(?=$|[\s_-])")
# Invisible math operators (function application, invisible times, separator, plus): rendering hints with no
# text, dropped everywhere; a zero-width space is dropped inside a formula only (0.22.1).
_MATH_INVISIBLE = {0x2061: None, 0x2062: None, 0x2063: None, 0x2064: None}
_IN_MATH_INVISIBLE = {**_MATH_INVISIBLE, 0x200B: None}
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                   "source", "track", "wbr"})
_BLOCKS = frozenset({"p", "div", "section", "article", "main", "header", "aside", "blockquote", "pre", "ul",
                     "ol", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "figure", "figcaption",
                     "address", "details", "summary", "hr", "center", "caption"})
_H2 = frozenset({"h1", "h2", "h3"})
_H3 = frozenset({"h4", "h5", "h6"})
# Page metadata a grounder or the command reads to propose a level (who published it, where, when).
_META_KEYS = ("citation_title", "citation_journal_title", "citation_conference_title", "citation_publisher",
              "citation_doi", "citation_publication_date", "citation_date", "citation_online_date",
              "citation_author", "dcterms.issued", "dc.date.issued", "dc.date", "article:published_time",
              "og:site_name", "og:type", "og:title", "author")
# The online date first (0.23.1): it is when the text became public. A journal's citation_publication_date is
# its issue's, often months later; the field's Copilot paper went online on 2026-11-03 for an April 2027 issue.
_DATE_KEYS = ("citation_online_date", "citation_publication_date", "citation_date", "dcterms.issued",
              "dc.date.issued", "dc.date", "article:published_time")


class _Extractor(HTMLParser):
    """The fixed HTML→text rule (`HTML_EXTRACTOR`). Headings h1–h3 become ``## `` lines and h4–h6 ``### ``
    lines, so `plan_sections` splits a copy as it splits a note; list items become ``- `` lines; table rows
    become lines of cells joined by `` | ``; paragraphs are separated by a blank line; whitespace collapses
    as a browser collapses it, except inside ``<pre>``. Scripts, styles, navigation, footers and forms are
    dropped. A pure function of the decoded text: the same bytes always give the same copy."""

    def __init__(self, scoped: bool = False):
        super().__init__(convert_charrefs=True)
        # `scoped` (3, 0.23.1): the page has a <main> (or role="main"), so only its text is the page's own;
        # `self.main` counts how deep inside it the parser is, by the tag that opened it.
        self.scoped = scoped
        self.main_tag = ""
        self.main = 0
        # a furniture subtree being skipped (3): its tag and how many of that tag are open inside it
        self.furniture_tag = ""
        self.furniture = 0
        self.lines: "list[str]" = []
        self.parts: "list[str]" = []
        self.prefix = ""
        self.skip = 0
        self.pre = 0
        self.cells = 0
        self.in_title = False
        self.title: "list[str]" = []
        self.meta: "dict[str, str]" = {}
        self.math = 0

    def _flush(self, paragraph: bool = True) -> None:
        text = "".join(self.parts)
        text = text.rstrip() if self.pre else _WS_RE.sub(" ", text).strip()
        if text:
            self.lines.append(self.prefix + text)
        self.parts, self.prefix = [], ""
        if paragraph and self.lines and self.lines[-1] != "":
            self.lines.append("")

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs if k}
            key = (a.get("name") or a.get("property") or "").strip().lower()
            if key in _META_KEYS and a.get("content", "").strip() and key not in self.meta:
                self.meta[key] = _WS_RE.sub(" ", a["content"]).strip()
            return
        if tag == "title":
            self.in_title = True
            return
        if tag == "body":
            # HTML lets a page omit </head>: the body starts the page's text whatever was left open before it.
            self.skip = 0
            return
        if tag == "math":
            self.math += 1
        a = None
        if self.scoped and not self.main_tag and tag not in _VOID:
            a = {k.lower(): (v or "") for k, v in attrs if k}
            if tag == "main" or a.get("role", "").strip().lower() == "main":
                self.main_tag, self.main = tag, 1
                return
        elif self.main_tag == tag:
            self.main += 1
        if self.furniture_tag:
            if tag == self.furniture_tag:
                self.furniture += 1
            return
        if tag in _SKIP:
            if tag not in _VOID:
                self.skip += 1
            return
        if self.skip:
            return
        if tag not in _VOID:
            a = a if a is not None else {k.lower(): (v or "") for k, v in attrs if k}
            names = f"{a.get('class', '')} {a.get('id', '')}".lower()
            if a.get("role", "").strip().lower() in _FURNITURE_ROLES or (names.strip() and _FURNITURE_RE.search(names)):
                self.furniture_tag, self.furniture = tag, 1
                return
        if tag in _H2 or tag in _H3:
            self._flush()
            self.prefix = "## " if tag in _H2 else "### "
        elif tag == "li":
            self._flush(paragraph=False)
            self.prefix = "- "
        elif tag == "tr":
            self._flush(paragraph=False)
            self.cells = 0
        elif tag in ("td", "th"):
            if self.cells:
                self.parts.append(" | ")
            self.cells += 1
        elif tag == "br":
            self._flush(paragraph=False)
        elif tag in _BLOCKS:
            self._flush()
            if tag == "pre":
                self.pre += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
            return
        if tag == "math" and self.math:
            self.math -= 1
        # The main part's depth counts every tag of its name, inside furniture too, as `handle_starttag` does:
        # a `<div role="main">` holding a furniture `<div>` must still close at its own `</div>`.
        main_over = False
        if self.main_tag and tag == self.main_tag:
            self.main -= 1
            main_over = self.main == 0
        if self.furniture_tag:
            if tag == self.furniture_tag:
                self.furniture -= 1
                if self.furniture == 0:
                    self.furniture_tag = ""
            if not main_over:
                return
            self.furniture_tag, self.furniture = "", 0   # a page that closes its main inside a furniture block
        if main_over:
            self._flush()
            self.main_tag = "-"   # the main part is over; nothing after it is the page's own
            return
        if tag in _SKIP:
            if self.skip and tag not in _VOID:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag in ("li", "tr"):
            self._flush(paragraph=False)
        elif tag in _H2 or tag in _H3 or tag in _BLOCKS:
            self._flush()
            if tag == "pre" and self.pre:
                self.pre -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
            return
        if self.skip or self.furniture_tag or (self.scoped and self.main <= 0):
            return
        self.parts.append(data.translate(_IN_MATH_INVISIBLE if self.math else _MATH_INVISIBLE))


_MAIN_RE = re.compile(r"<main[\s>]|\brole\s*=\s*[\"']?main\b", re.I)


def html_text(markup: str) -> "tuple[str, str, dict]":
    """``(title, text, meta)`` of an HTML document by the fixed rule (`_Extractor`). Since version 3 (0.23.1) a
    page with a ``<main>`` (or ``role="main"``) gives only that part's text, and sidebars, recommendation lists,
    related-content and sharing blocks are left out wherever they sit (`_FURNITURE_RE`). In the field's two
    Springer articles those made a third of the copy's sections, each one an extractor run that found nothing
    (2026-11-22). The metadata and the title are read from the whole page as before."""
    parser = _Extractor(scoped=bool(_MAIN_RE.search(markup)))
    parser.feed(markup)
    parser.close()
    parser._flush()
    lines = [line.rstrip() for line in parser.lines]
    out: "list[str]" = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    text = "\n".join(out) + ("\n" if out else "")
    title = _WS_RE.sub(" ", "".join(parser.title)).strip()
    return title, text, dict(parser.meta)


def page_published(meta: dict) -> str:
    """The publication date a page declares in its metadata, normalized, or "": the first of `_DATE_KEYS` it
    declares, the online date first, and never a date still to come when the page declares one already past
    (an issue date ahead of its online date, 0.23.1)."""
    dates = [d for d in (_loose_date(meta.get(key, "")) for key in _DATE_KEYS) if d]
    if not dates:
        return ""
    today = utcnow()[:10]
    past = [d for d in dates if d <= today]
    return (past or dates)[0]


@dataclass
class Copy:
    """What a fetch or a local file becomes before it is registered."""
    text: str
    title: str
    meta: dict
    content_type: str
    extractor: str
    raw: bytes
    raw_ext: str
    final_url: str = ""


def copy_from_bytes(data: bytes, content_type: str, charset: str = "", *, final_url: str = "") -> Copy:
    """Turn received bytes into a copy by their content type: HTML by the fixed rule, plain text and Markdown
    verbatim. PDF and every other type are refused."""
    ctype = (content_type or "").lower()
    if ctype in _HTML_TYPES:
        markup = decode(data, charset or sniff_charset(data))
        title, text, meta = html_text(markup)
        extractor, ext = HTML_EXTRACTOR, ".html"
    elif ctype in _PLAIN_TYPES:
        text, title, meta = decode(data, charset), "", {}
        extractor, ext = VERBATIM, ".md" if "markdown" in ctype else ".txt"
    elif ctype == "application/pdf":
        raise EvidenceError("pdf-not-supported", "convert the PDF to Markdown and register that file")
    else:
        raise EvidenceError("content-type-not-supported", ctype or "no content type")
    if not text.strip():
        raise EvidenceError("no-text", "the page has no text the engine can read (it may need JavaScript); "
                                       "save its text as a .md file and register that file")
    return Copy(text=text, title=title, meta=meta, content_type=ctype, extractor=extractor, raw=data,
                raw_ext=ext, final_url=final_url)


def copy_from_file(path: Path) -> Copy:
    """A local file as a copy: .md/.markdown/.txt verbatim, .html/.htm by the fixed rule; PDF refused."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        raise EvidenceError("pdf-not-supported", "convert the PDF to Markdown and register that file")
    if ext not in _LOCAL_TEXT_EXTS + _LOCAL_HTML_EXTS:
        raise EvidenceError("file-type-not-supported", f"{ext or 'no extension'}: use .md, .txt or .html")
    try:
        size = p.stat().st_size
        if size > MAX_BYTES:
            raise EvidenceError("too-large", f"more than {MAX_BYTES} bytes")
        data = p.read_bytes()
    except OSError as e:
        raise EvidenceError("file-unreadable", str(e)) from None
    if ext in _LOCAL_HTML_EXTS:
        return copy_from_bytes(data, "text/html")
    text = decode(data)
    if not text.strip():
        raise EvidenceError("no-text", "the file is empty")
    return Copy(text=text, title="", meta={}, content_type="text/markdown" if ext != ".txt" else "text/plain",
                extractor=VERBATIM, raw=data, raw_ext=ext)


# A site's bot check served in place of the page (0.23.1). On 2026-11-22 Springer sent the engine on Windows a
# 210-character "Client Challenge" for each of three articles, which the preview took for the page.
_CHALLENGE_TITLES = frozenset({"client challenge", "just a moment...", "just a moment…", "just a moment",
                               "attention required! | cloudflare", "attention required!", "access denied",
                               "are you a robot?", "are you a human?", "checking your browser",
                               "checking your browser before accessing", "security check", "robot check",
                               "verifying you are human", "pardon our interruption", "human verification",
                               "403 forbidden", "ddos-guard", "please wait while we verify your browser"})
_CHALLENGE_PHRASES = ("a required part of this site couldn", "verify you are human", "verify that you are human",
                      "checking your browser", "enable javascript and cookies", "are not a robot", "captcha",
                      "unusual traffic", "press & hold", "access to this page has been denied",
                      "please complete the security check")
CHALLENGE_MAX_CHARS = 2000


def blocked_page(copy: Copy) -> str:
    """Why a copy is a site's bot check rather than the document, or "" (0.23.1): an HTML page titled like
    one of `_CHALLENGE_TITLES`, or a short one (under `CHALLENGE_MAX_CHARS`) that says what such a page says.
    Only HTML is checked: a Markdown or text file is the user's own."""
    if not copy.extractor.startswith("html-text"):
        return ""
    title = (copy.title or "").strip().lower()
    if title in _CHALLENGE_TITLES:
        return f"the page is titled {copy.title.strip()!r}, a site's bot check"
    if len(copy.text) < CHALLENGE_MAX_CHARS:
        low = copy.text.lower()
        hit = next((ph for ph in _CHALLENGE_PHRASES if ph in low), "")
        if hit:
            return f"the page holds {len(copy.text)} characters and says {hit!r}, as a site's bot check does"
    return ""


def preview(copy: Copy) -> dict:
    """What the command shows before registering: enough to propose a level and a role."""
    return {"title": copy.title, "chars": len(copy.text), "content_type": copy.content_type,
            "extractor": copy.extractor, "published": page_published(copy.meta), "meta": dict(copy.meta),
            "final_url": copy.final_url, "excerpt": copy.text[:PREVIEW_CHARS]}
