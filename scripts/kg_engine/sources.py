"""SourceSet (R4): resolve a file | dir | glob of ``.md``/``.txt`` into an ordered ``{basename → text}``
map and make span verification **source-aware**.

This turns the previously-dead ``Edge.source_file`` field load-bearing: a span must verify against
*some* declared source, and when an edge names a ``source_file``, against *that* file specifically (a
lenient any-source fallback when the named basename isn't among the declared sources — legacy
``source.md`` / an agent typo — per Stage-0 Q1). Single-file is the trivial one-entry case, byte-identical
to the old single-blob path, so every existing single-source canon keeps verifying unchanged.

**Markdown/text only — no PDF/media** (a lossy transcript becoming a "verbatim" span would break
span-present, §1.5, and the deterministic tier). Pure stdlib + ``model.normalize_text``; read-only.
"""
from __future__ import annotations

import glob as _glob
import re
from dataclasses import dataclass
from pathlib import Path

from .model import normalize_text, span_present_in

_EXTS = (".md", ".txt")
_GLOB_CHARS = "*?["

# What starts a section: a level-2 ATX heading — `##` followed by whitespace. `###` and deeper never
# match (the char after `##` is `#`, not whitespace) and stay inside their section's body.
_SECTION_HEAD_RE = re.compile(r"^##\s+(.*)$")
# The same rule one level down, for a file whose sections are `###` subsections (see section_level).
# `####` and deeper never match it, for the same reason.
_SUBSECTION_HEAD_RE = re.compile(r"^###\s+(.*)$")
_HEAD_RES = {2: _SECTION_HEAD_RE, 3: _SUBSECTION_HEAD_RE}
# A fenced-code-block delimiter (``` or ~~~, optionally indented, with an optional info string). Lines
# INSIDE a fence are literal content, so a `## ...` there (a shell comment, Markdown-about-Markdown) is
# NOT a section heading — toggling on this keeps split_sections from carving a code block at such a line
# (review-fix: the single section-splitting home, so backend/projector/harness all inherit the fix).
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _chunks(text: str, level: int = 2) -> "list[tuple[str | None, str | None, list[str]]]":
    """The section rule itself: ``(heading_line, title, body_lines)`` per section, in order, split at
    ATX headings of exactly ``level`` (2 or 3) outside fenced code. The preamble, the text before the
    first heading, comes first with ``heading_line`` and ``title`` both None, and only when it has any
    lines (blank ones included). An empty heading (``## `` alone) has the title ``""``. A section left
    open at EOF is always emitted. split_sections and plan_sections are both views over this, so they
    can never disagree about where a section starts."""
    head_re = _HEAD_RES[level]
    # Strip a single leading UTF-8 BOM (U+FEFF): a Windows/Notepad-authored .md is read with
    # encoding="utf-8" (SourceSet/harness/backend), which PRESERVES a leading BOM, and it would then
    # keep the first line `﻿## Heading` from matching `_SECTION_HEAD_RE` — folding the first
    # section into the preamble and losing its title. Fixed here (the single section-splitting home) so
    # every reader is covered; span verification is already BOM-immune via normalize_text (review-r8-8).
    if text.startswith("﻿"):
        text = text[1:]
    chunks: "list[tuple[str | None, str | None, list[str]]]" = []
    heading, title, buf = None, None, []  # title=None -> still in the preamble
    in_fence = False  # inside a ``` / ~~~ fenced code block — headings there are literal content
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else head_re.match(line)
        if m:
            if title is not None or buf:
                chunks.append((heading, title, buf))
            heading, title, buf = line, m.group(1).strip(), []
        else:
            buf.append(line)
    if title is not None or buf:
        chunks.append((heading, title, buf))
    return chunks


def split_sections(text: str, *, include_heading: bool = False,
                   preamble_title: str = "") -> "list[tuple[str, str]]":
    """Split a source document into ``(title, body)`` pairs at level-2 ``##`` headings — THE single
    home for the section rule (review-r5: it previously existed as four implementations with three
    algorithms across server/backend/projector/harness, all claiming to be "the SAME unit
    /kg-build extracts per subagent").

    ``include_heading`` keeps the raw heading line at the top of each section body (the extraction
    payload unit — the model needs the heading for context); the default drops it (coverage matches
    spans against body prose). Text before the first heading is emitted as one leading section
    titled ``preamble_title`` whenever any preamble lines exist (blank ones included — the historic
    behavior of every prior copy); an empty heading (``## `` alone) also falls back to
    ``preamble_title``. A section left open at EOF is always emitted.
    """
    return [(title or preamble_title,
             "\n".join(([heading] if include_heading and heading is not None else []) + lines))
            for heading, title, lines in _chunks(text, 2)]


@dataclass(frozen=True)
class PlannedSection:
    """One section of a /kg-build plan: the unit ONE extractor receives (0.5.0, kg_build_plan and
    kg_section). ``index`` is 1-based among the file's headed sections at its section_level; ``text``
    is the heading line plus the body, verbatim (before the egress scrub); ``body`` drops the heading.
    The title ``""`` marks a file with no heading at that level, which is one whole-file section."""
    index: int
    title: str
    text: str
    body: str


def section_level(text: str) -> int:
    """The heading level a file's sections sit at: 3 when its only ``##`` heading is the file's title
    and two or more ``###`` subsections carry the content, else 2. That is the rule /kg-build's Step 0b
    applied in Bash through 0.4.6 (FALLO 4: such a file had collapsed into one section, breaking
    span-isolation), now counted with the same fence-aware rule as the split itself."""
    h2 = sum(1 for heading, _t, _l in _chunks(text, 2) if heading is not None)
    if h2 > 1:
        return 2
    h3 = sum(1 for heading, _t, _l in _chunks(text, 3) if heading is not None)
    return 3 if h3 >= 2 else 2


def plan_sections(text: str) -> "tuple[int, list[PlannedSection]]":
    """``(level, sections)``: what /kg-build extracts from one file, one extractor per section.

    The sections are the file's headed sections at ``section_level(text)``. The preamble before the
    first heading is not one of them: through 0.4.6 Step 0b enumerated headings only, and the preamble
    is usually a title and a byline. A file with no heading at that level is one section holding the
    whole file, so a headingless note still gets built. ``kg_build_plan`` numbers sections and
    ``kg_section`` serves them through this one function, so a plan's section N is always the text an
    extractor asking for N receives."""
    level = section_level(text)
    sections: "list[PlannedSection]" = []
    for heading, title, lines in _chunks(text, level):
        if heading is None:
            continue
        # An empty heading (`## ` alone) is still a section of its own; only the whole-file case is "".
        sections.append(PlannedSection(len(sections) + 1, title or "(untitled)", "\n".join([heading] + lines),
                                       "\n".join(lines)))
    if not sections and text.strip():
        whole = text[1:] if text.startswith("﻿") else text
        sections.append(PlannedSection(1, "", whole, whole))
    return level, sections


def section_corpus(text: str) -> "list[str]":
    """The source as a list of per-section documents for IDF — one ``"title\\nbody"`` string per
    section, whitespace-only sections dropped. The projector's specificity gate and the harness
    ``specificity`` CLI both consume exactly this, so the two stay bit-identical by construction
    (they previously each hand-rolled a ``split("\\n## ")`` that treated a heading at byte 0
    differently). Title terms deliberately stay in the document: a section's own heading words
    count toward its term statistics, as they always have."""
    docs = []
    for title, body in split_sections(text):
        doc = f"{title}\n{body}" if title else body
        if doc.strip():
            docs.append(doc)
    return docs


def _looks_like_glob(s: str) -> bool:
    return any(ch in s for ch in _GLOB_CHARS)


def _source_order(p: Path) -> tuple:
    """The platform-stable sort key: by basename, then full path. The full-path tiebreak is what makes
    a cross-dir basename collision pick the same winner on every machine (filesystem iteration order is
    not portable)."""
    return (p.name, str(p))


def _dedupe_stable(cands: list[Path]) -> list[Path]:
    """The dedup pipeline: sort by ``_source_order``, skip dotfiles / non-files / wrong-suffix
    (case-insensitive), and dedupe by basename keeping the lexicographically-first full path. The
    case-insensitive ``.lower()`` suffix filter matches the glob branch, so ``/dir`` and ``/dir/*``
    agree on an uppercase-extension file (``UP.MD``)."""
    out: dict[str, Path] = {}
    for q in sorted(cands, key=_source_order):
        if q.name.startswith(".") or not q.is_file() or q.suffix.lower() not in _EXTS:
            continue
        out.setdefault(q.name, q)
    return list(out.values())


class SourceSet:
    """An ordered, deterministic ``{basename → raw_text}`` view over the configured source(s)."""

    def __init__(self, path: "str | Path | None" = None):
        self.path = Path(path) if path is not None else None
        self._texts: dict[str, str] = {}
        for p in self.resolve(self.path):
            try:
                self._texts[p.name] = p.read_text(encoding="utf-8")
            except (OSError, ValueError):
                # OSError = unreadable; ValueError covers UnicodeDecodeError (its superclass, NOT an
                # OSError) so a non-UTF-8 / binary / UTF-16 file among the resolved set is SKIPPED instead
                # of propagating out of the constructor and disabling the whole tool surface (review-H3).
                # Skip — never decode with errors='replace', which could forge phantom span matches.
                continue  # mirrors canon.all_nodes()'s "one bad file must not crash every read" tolerance
        # normalized form per file, computed once for source-aware verification (off the hot path)
        self._norm: dict[str, str] = {name: normalize_text(t) for name, t in self._texts.items()}

    # ---- resolution
    @classmethod
    def resolve(cls, path: "str | Path | None") -> list[Path]:
        """The ordered list of source files for ``path``.

        - an explicit **file** → just that file (ANY extension — single-file back-compat: the user
          pointed at it directly, so honor it even if it is not ``.md``/``.txt``);
        - a **directory** or **glob** → its ``.md``/``.txt`` members (case-insensitive extension),
          ordered by ``(basename, full path)``, dotfiles skipped (mirroring ``canon.note_paths``),
          deduped by basename — on a cross-dir collision the lexicographically-first full path wins
          (a stable, platform-independent order);
        - a nonexistent path → ``[]`` (so ``source_text()`` degrades to ``""`` exactly as before).
        """
        if path is None:
            return []
        p = Path(path)
        s = str(path)
        if p.is_file():
            return [p]  # explicit single file — always included, any extension
        if p.is_dir():
            cands = list(p.iterdir())  # the case-insensitive suffix filter below unifies dir + glob
        elif _looks_like_glob(s):
            # recursive=True so a `**` segment recurses into nested directories rather than being
            # treated as a single `*` (one level) — else `src/**/*.md` silently under-collects the
            # nested sources R4 is meant to gather (review-low: ** glob recursion).
            cands = [Path(x) for x in _glob.glob(s, recursive=True)]
        else:
            return []  # nonexistent literal path
        # The dir/glob candidates run through the platform-stable dedup pipeline (sort + dotfile/suffix
        # filter + first-path-wins by basename) so the resolved order is identical across machines.
        return _dedupe_stable(cands)

    @classmethod
    def signature(cls, path: "str | Path | None") -> tuple:
        """A cheap ``(basename, size, mtime_ns)`` tuple over the resolved files (no content reads).
        KGEngine keys its SourceSet cache on this so an added/removed/edited source is picked up, else the
        cache is served — keeping the resolve+read off the hot path. Uses ``st_mtime_ns`` + ``st_size``
        (not float ``st_mtime``) to match ``projector._cheap_sig``, so a same-second in-place edit
        reliably invalidates the cache rather than serving stale text past the one-projection-lag (R3)."""
        sig = []
        for p in cls.resolve(path):
            try:
                st = p.stat()
                sig.append((p.name, st.st_size, st.st_mtime_ns))
            except OSError:
                sig.append((p.name, None, None))
        return tuple(sig)

    # ---- views
    @property
    def texts(self) -> dict[str, str]:
        """The ordered ``{basename → raw_text}`` map (a copy)."""
        return dict(self._texts)

    @property
    def basenames(self) -> list[str]:
        return list(self._texts.keys())

    @property
    def concat(self) -> str:
        """All sources concatenated in deterministic order (one ``\\n`` between files). For a single
        file this is byte-identical to the file's text. Feeds the IDF corpus + the flood-budget size."""
        return "\n".join(self._texts.values())

    @property
    def normalized(self) -> str:
        """The whitespace/case-normalized concat (whole-corpus form)."""
        return normalize_text(self.concat)

    @staticmethod
    def _key(name: str) -> str:
        """The basename lookup key — normalized identically to the storage key (``p.name``), so a
        lookup can never miss a stored source by forgetting to strip the directory part."""
        return Path(name).name

    def for_file(self, name: str) -> str:
        """The raw text of one declared source by basename, or ``""`` if not present."""
        return self._texts.get(self._key(name), "")

    def has_file(self, name: str) -> bool:
        """True iff ``name``'s basename is a declared source — lets the boundary distinguish
        ``span-not-in-named-source`` (named source known, span absent there) from ``span-not-in-source``."""
        return bool(name) and self._key(name) in self._texts

    def __len__(self) -> int:
        return len(self._texts)

    def __bool__(self) -> bool:
        return bool(self._texts)

    # ---- the source-aware span check
    def verifies(self, span: str, source_file: str = "") -> bool:
        """True iff ``span`` is a normalized verbatim substring of a DECLARED source.

        When ``source_file`` names a KNOWN basename, verify against THAT file only
        (named-source-exact); when it names an UNKNOWN basename (legacy ``source.md`` / an agent typo)
        or is empty, fall back to ANY declared source (lenient — Stage-0 Q1). The check is per-file
        (never against a cross-file concat), so a span can never "verify" by straddling a file
        boundary. Delegates the normalize + empty-guard + substring atom to ``model.span_present_in``
        (the single primitive ``span_verifies`` also calls), so the §1.5 fail-closed gate cannot drift;
        this method keeps ONLY the source SELECTION over the pre-normalized ``self._norm`` texts."""
        if source_file:
            name = self._key(source_file)
            if name in self._norm:
                return span_present_in(span, self._norm[name])
            # unknown named source → lenient any-source fallback
        return any(span_present_in(span, nt) for nt in self._norm.values())
