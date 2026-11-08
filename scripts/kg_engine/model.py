"""Core data model for the canon: the three axes, Node/Edge, span verification, frontmatter I/O.

This module is dependency-free (stdlib + pyyaml) and is the spine every other module binds to.
The write/boundary contract built on it is mirrored in skills/burgess/references/contract.md;
this code is authoritative.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from math import isfinite
from typing import Any

import yaml

# libyaml's C SafeLoader is ~8x faster than the pure-Python SafeLoader and is hit on every canon PARSE
# (all_nodes / reproject / kg_write baseline) — the dominant read-path cost (model-1). The fallback is
# MANDATORY: pyyaml>=6 does not guarantee the C extension on every platform/wheel (musl, some ARM, sdist).
# CSafeLoader is semantically identical to SafeLoader for our scalar/list/map frontmatter, so spans/
# verdicts/edge_id/epistemic_state parse identically. The DUMP side deliberately stays on pure-Python
# safe_dump: CSafeDumper escapes non-BMP scalars (emoji / supplementary-plane CJK, e.g. inside a span)
# that safe_dump emits literally — lossless but byte-different — and the write path is far less hot than
# the parse path, so we keep canon bytes identical (clean git diffs, canonmerge byte-stability).
try:
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover - exercised only on a libyaml-less build
    from yaml import SafeLoader as _YamlLoader

# --------------------------------------------------------------------------- axes (§1.3)


class Provenance(str, Enum):
    SPAN_PRESENT = "span-present"  # cites a verifiable textual span in the source
    INFERRED = "inferred"          # asserted without a verbatim span (relation is an inference)
    HYPOTHESIZED = "hypothesized"  # proposed by a discovery mechanism (structural/embedding adjacency)


class AuthoredBy(str, Enum):
    DETERMINISTIC = "deterministic"  # produced by a parser, not a language model
    AGENT = "agent"                  # produced by a subagent
    HUMAN = "human"                  # a person's verdict


class EpistemicState(str, Enum):
    UNVERIFIED = "unverified"
    GROUNDED = "grounded"    # passed the grounding loop
    REJECTED = "rejected"    # grounding rejected it
    FAILED = "failed"        # actively falsified (memory of failures, §1.7)
    OBSOLETE = "obsolete"    # superseded


class Confidence(str, Enum):
    """graphify-style extraction tier, surfaced by f4_probe. Orthogonal to the three axes."""
    EXTRACTED = "EXTRACTED"   # deterministic / parser
    INFERRED = "INFERRED"     # language-model judgement
    AMBIGUOUS = "AMBIGUOUS"


class Disposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    DEMOTED = "DEMOTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


# Verdict states may never be asserted by a write; only kg_ground may set them.
VERDICT_STATES = {EpistemicState.GROUNDED, EpistemicState.REJECTED, EpistemicState.FAILED}
# Every state kg_ground may stamp (a verdict OR the `obsolete` lifecycle transition). This is the
# single source of truth shared by the boundary (which demotes any of these on a write), the server
# (kg_ground's accepted verdicts), and the reconciler (which re-quarantines any of these reached
# out-of-band without a matching audit record). Keeping it in one place stops the three from drifting.
GROUNDABLE_STATES = VERDICT_STATES | {EpistemicState.OBSOLETE}
# Negative information that the projector must never prune (§1.7).
FAILURE_STATES = {EpistemicState.REJECTED, EpistemicState.FAILED}
# The same set in raw-string form, for the many sites that compare dict/JSON/SQL values rather than
# Enum members (projector rows, agenda edges, export, the materialized-fate ledger, the graph.html
# template). Single-homed here so extending the negative-memory vocabulary can never silently skip
# a consumer that had re-typed ("failed", "rejected") by hand (review-r5).
FAILURE_STATE_VALUES = frozenset(s.value for s in FAILURE_STATES)
# Edge states that are NOT LIVE TOPOLOGY: failure memory plus `obsolete` (a superseded relation). The
# live subgraph is what every structural signal is computed over — degree/community/betweenness/
# spec_betweenness in projector._live_subgraph, the answer lane in kg_context, and the generators'
# adjacency in generate._live_undirected. Those must agree: generate.py excluded only the failure states
# while the projector also dropped `obsolete` (added in review-fix L14), so the five edge mechanisms took
# adjacency/common-neighbour signal from superseded edges while reading node ranks computed WITHOUT them —
# a silent disagreement that generate._live_undirected's own docstring claimed was impossible. One home,
# so the two can never drift again (review-r11).
NON_LIVE_STATE_VALUES = FAILURE_STATE_VALUES | {EpistemicState.OBSOLETE.value}
UNDECLARED_TYPE = "undeclared-type"
# The two boundary numbers server.py needs at import time — single-homed HERE (not boundary.py, their
# original home) since review-r6: importing them from boundary made the read-only PreToolUse hook pay
# boundary's pydantic import (~75ms) on every Grep/Glob/Read for two plain constants. boundary.py
# re-imports them, so its validation logic and every existing `from .boundary import ...` site are
# unchanged.
# A span must be a verbatim anchor, not a degenerate one: a 1-char span ('a') is a substring of
# almost any prose and meets span-present letter-of-the-law while citing nothing. Require a minimum
# of real (non-whitespace) characters so the structural guarantee stays meaningful (§1.5).
MIN_SPAN_CHARS = 4
# Anti-injection-flooding rate limit (§Stage 9): a hostile or oversized source must not be able to
# stuff the canon with unbounded edges. The budget scales with source size; its floor
# (MIN_EDGE_BUDGET) lives in boundary.py next to the budget logic that applies it.
DEFAULT_MAX_EDGES_PER_KB = 20.0
# The three shared provenance axes that must be unwrapped from Enum to str on egress (§1.3). Stated
# once so Edge.to_dict and Node.frontmatter cannot drift; a raw Enum leak here would break the
# projector's json.dumps(frontmatter) content hash. Edge adds `confidence` on top of these.
_AXIS_FIELDS = ("provenance", "authored_by", "epistemic_state")


def coerce_enum(cls, value, default):
    """Coerce a (possibly hand-edited / typo'd) string to an enum member, falling back to a safe
    default instead of raising. A malformed enum value in a canon note must not blow up parsing and
    make the whole node disappear from every read (§1.2)."""
    if isinstance(value, cls):
        return value
    try:
        return cls(value)
    except ValueError:
        return default


def coerce_axes(obj, *, provenance_default: "Provenance") -> None:
    """Coerce the three provenance axes on `obj` in place, with the fixed safe defaults shared by
    Edge/Node: authored_by → AGENT and epistemic_state → UNVERIFIED (the never-forge-a-verdict net —
    a malformed verdict is demoted, never invented), and the caller-supplied provenance default (the
    only axis whose default differs between Edge and Node)."""
    obj.provenance = coerce_enum(Provenance, obj.provenance, provenance_default)
    obj.authored_by = coerce_enum(AuthoredBy, obj.authored_by, AuthoredBy.AGENT)
    obj.epistemic_state = coerce_enum(EpistemicState, obj.epistemic_state, EpistemicState.UNVERIFIED)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- text / span

_WS = re.compile(r"\s+")
# Typographic folds applied by normalize_text: curly quotes/dashes to ASCII, NBSP to a plain
# space. One translate table (with every codepoint spelled as an escape — the old replace chain
# ended in an INVISIBLE literal NBSP that rendered as .replace(" ", " ") in most editors).
_TYPOGRAPHIC_FOLDS = str.maketrans({
    "\u2018": "'", "\u2019": "'",   # curly single quotes
    "\u201c": '"', "\u201d": '"',   # curly double quotes
    "\u2013": "-", "\u2014": "-",   # en/em dashes
    "\u00a0": " ",                   # no-break space
})

# Windows reserved device names (case-insensitive). A file whose base name (the part before the first
# dot) equals one of these is a device alias and UNWRITABLE on Windows, so a node id like `con` slugging
# to `con.md` would fail to write there. slug() escapes a result equal to one of these by appending '-'.
_WINDOWS_RESERVED = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def normalize_text(s: str) -> str:
    """Whitespace-collapsed, case-folded form used for span verification.

    Applies Unicode NFC normalization (so a verbatim span in NFC matches a source stored as NFD, e.g.
    macOS/HFS+ paths and copy-paste), strips zero-width / format controls (BOM, ZWSP, word joiner),
    and folds curly quotes/dashes to ASCII so a paraphrase-free span still matches a source that
    differs only by typographic or composition-form normalization.
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", s)
    # U+0130 (İ, LATIN CAPITAL LETTER I WITH DOT ABOVE) casefolds to 'i' + U+0307 (COMBINING DOT
    # ABOVE), a non-NFC sequence that NFC — already applied above, and not idempotent across casefold —
    # will NOT recompose back to a bare 'i'. So a source written with 'İ' would fold to a 9-char form
    # that a lowercased verbatim span ('istanbul') can't substring-match, falsely rejecting an honest
    # span (the §1.5 gate promises case-insensitive matching). Fold it to 'i' BEFORE
    # casefold (so the spurious combining dot is never introduced); applied to span and source alike
    # via this shared function, so the symmetry the substring test relies on holds.
    s = s.replace("İ", "i")
    # drop zero-width / format controls (Cf) that are invisible but break a substring match
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    s = s.translate(_TYPOGRAPHIC_FOLDS)
    return _WS.sub(" ", s).strip().casefold()


def span_present_in(span: str, normalized_text: str) -> bool:
    """Core span-present test (§1.5): normalized `span` is a substring of ALREADY-normalized
    `normalized_text`. Guards on the normalized span — a Cf-only span normalizes to '' and must fail
    closed, not match every string (mirror in sources.verifies)."""
    ns = normalize_text(span)
    if not ns:
        return False
    return ns in normalized_text


def span_verifies(span: str, source_text: str) -> bool:
    """True iff `span` appears (normalized substring) in `source_text`. The span-present check (§1.5)."""
    # Guard on the NORMALIZED span, not the raw one: a span of only zero-width / format (Cf) characters
    # survives `str.strip()` (it is non-whitespace) but normalize_text() drops all Cf, leaving '' — and
    # '' is a substring of every string, so the raw guard would fail OPEN. Mirror sources.verifies (the
    # production sibling) which already guards on the normalized form (review-low: span_verifies Cf-only).
    return span_present_in(span, normalize_text(source_text))


def slug(s: str) -> str:
    """Canonical id/filename form of a label. Memoized — see `_slug` for the rule itself.

    `slug` is the single hottest pure function in the engine: `edge_id` calls it three times, and the
    O(n^2) candidate loops in `generate` call `edge_id` twice per pair. A profile of
    `kg_generate("all")` on an 800-node graph showed 535k `slug` calls costing 2.05s of 4.17s total —
    two regex substitutions, an NFC normalize, a casefold and a strip, re-executed on the same few
    thousand distinct labels over and over. It is a pure string->string function of a small, repeating
    domain, so the cache is free correctness-wise and bounded (LRU) for a long-lived server (review-r11).

    `str(s)` before the cached call: the body already coerced non-str input, and an unhashable argument
    must not turn a working call into a TypeError at the cache boundary."""
    return _slug(str(s))


@lru_cache(maxsize=8192)
def _slug(s: str) -> str:
    # NFC-normalize first so visually-identical strings in different composition forms (NFD from
    # macOS/HFS+ copy-paste vs NFC) produce the SAME slug — otherwise the same logical node/edge
    # forks into two ids/filenames and dedup (§1.4) silently fails.
    s = unicodedata.normalize("NFC", s).strip().lower()
    # MAP punctuation to a separator rather than DELETING it. This is the WEAKER of two guarantees,
    # not perfect injectivity: punctuation and separators all collapse to a single '-', so
    # punctuation-only variants are *intentionally* unified — slug('a/b')==slug('a-b')==slug('a b')
    # and slug('!!!foo!!!')==slug('foo'). What mapping (vs deleting) buys is that distinct inputs
    # which differ by a SEPARATING mark stay distinct ('a/b' vs 'ab', 'I/O' vs 'IO', 'foo.bar' vs
    # 'foobar' do NOT collapse onto one id/filename, as deletion would conflate them).
    s = re.sub(r"[^\w\s-]", "-", s)
    # The final `or "node"` fallback means ANY input that reduces to empty — '' or a
    # punctuation/separator-only string ('---', '!!!') — collapses to the literal slug "node", which
    # also collides with a node legitimately labelled 'node' (and, via edge_id, conflates distinct
    # empty-endpoint edges onto one id/file). The write boundary rejects empty/punctuation-only edge
    # endpoints (no word character) before edge_id is built so this fallback can't silently alias
    # distinct edges; callers that slug elsewhere should be aware of the collapse.
    out = re.sub(r"[\s_-]+", "-", s).strip("-") or "node"
    # Escape a Windows reserved device name (CON/NUL/AUX/PRN/COMn/LPTn): append '-' so `con` -> `con-`
    # and the canon file `con-.md` is writable. A normal slug never ENDS in '-' (the strip("-") above),
    # so the escaped form lives in a disjoint output space and can never collide with another input's
    # slug (deterministic + collision-free). Done in slug() so node ids and edge ids both benefit.
    if out.lower() in _WINDOWS_RESERVED:
        out += "-"
    return out


def edge_id(source: str, relation: str, target: str) -> str:
    """Deterministic identity of an edge (single-canonical-edge rule, §1.4)."""
    return f"e_{slug(source)}__{slug(relation)}__{slug(target)}"


# --------------------------------------------------------------------------- dataclasses


@dataclass
class Edge:
    source: str
    target: str
    relation: str
    provenance: Provenance = Provenance.INFERRED
    authored_by: AuthoredBy = AuthoredBy.AGENT
    epistemic_state: EpistemicState = EpistemicState.UNVERIFIED
    span: str = ""
    source_file: str = ""
    confidence: Confidence = Confidence.INFERRED
    confidence_score: float | None = None
    verdict_by: str | None = None   # who put the edge in its epistemic_state, and when (ISO-8601 UTC):
    verdict_at: str | None = None   # a re-verdict that keeps the state keeps both (kg_ground, 0.10.2)
    notes: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        # tolerate a typo'd/unknown enum string in a hand-edited note: coerce to a safe default rather
        # than raise (a single bad field must not make the whole node vanish from every read, §1.2).
        # UNVERIFIED is the safe epistemic default — it demotes a malformed verdict, never invents one.
        coerce_axes(self, provenance_default=Provenance.INFERRED)
        self.confidence = coerce_enum(Confidence, self.confidence, Confidence.INFERRED)
        # endpoints/relation may arrive as non-str from YAML; the id is a deterministic function of
        # them (single-canonical-edge rule). Always recompute so a stored/forged id can never diverge
        # from (source, relation, target).
        self.source, self.relation, self.target = str(self.source), str(self.relation), str(self.target)
        self.id = edge_id(self.source, self.relation, self.target)
        # Sanitize the confidence hint at the PARSE chokepoint, with the same rule the write boundary
        # applies: clamp to [0,1], drop non-finite. The boundary only sees agent payloads, but canon is
        # human-editable by design — a hand-written `confidence_score: .nan` parses to nan, survives
        # to_dict(), and reaches `json.dumps` (allow_nan=True by default), which emits a bare `NaN`
        # literal. That is not valid JSON (RFC 8259), so the derived graph.json becomes unreadable to any
        # strict external consumer even though the engine's own json.load tolerates it. This module
        # already coerces every other malformed field to a safe default rather than raising; the
        # confidence hint was the one that leaked through (review-r11).
        if self.confidence_score is not None:
            try:
                score = float(self.confidence_score)
            except (TypeError, ValueError):
                score = None  # a non-numeric hand-edit is no hint at all
            self.confidence_score = min(1.0, max(0.0, score)) if score is not None and isfinite(score) else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in _AXIS_FIELDS + ("confidence",):
            d[k] = d[k].value if isinstance(d[k], Enum) else d[k]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, source: str | None = None) -> "Edge":
        d = dict(d)
        # tolerate unknown keys AND drop None-valued known keys: a hand-edited `source: null` /
        # `relation: null` (or any explicit null) would otherwise be passed through and coerced to the
        # literal string "None" by __post_init__ (str(None)). Mirroring node_from_markdown, drop the
        # None so the field default applies instead — and, for `source`, so the resolved owning-node id
        # below fills it (setdefault after the drop, so a null `source` still resolves to `source`).
        known = set(cls.__dataclass_fields__)
        kw = {k: v for k, v in d.items() if k in known and v is not None}
        if source is not None:
            kw.setdefault("source", source)
        return cls(**kw)


@dataclass
class Node:
    id: str
    label: str = ""
    node_type: str = UNDECLARED_TYPE
    file_type: str = "prose"
    provenance: Provenance = Provenance.SPAN_PRESENT
    authored_by: AuthoredBy = AuthoredBy.AGENT
    epistemic_state: EpistemicState = EpistemicState.UNVERIFIED
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    edges: list[Edge] = field(default_factory=list)

    def __post_init__(self) -> None:
        coerce_axes(self, provenance_default=Provenance.SPAN_PRESENT)
        # YAML may coerce id/label/timestamps to non-str (numbers, booleans, datetime). Coerce to str
        # so frontmatter() stays JSON-serializable (the projector hashes json.dumps(frontmatter)) and a
        # falsy-but-present label (0 / false) is not mistaken for "missing" and overwritten by the id.
        self.id = str(self.id)
        self.label = self.id if self.label in (None, "") else str(self.label)
        now = utcnow()
        self.created_at = str(self.created_at) if self.created_at else now
        self.updated_at = str(self.updated_at) if self.updated_at else now
        self.edges = [e if isinstance(e, Edge) else Edge.from_dict(e, source=self.id) for e in self.edges]

    def frontmatter(self) -> dict[str, Any]:
        # Explicit ordered dict — key order is load-bearing for byte-identical canon (clean git diffs,
        # canonmerge). The three axis cells are built from _AXIS_FIELDS (stated once with Edge.to_dict)
        # but spliced here in their fixed position so the order is unchanged.
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type,
            "file_type": self.file_type,
            **{k: getattr(self, k).value for k in _AXIS_FIELDS},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "edges": [e.to_dict() for e in self.edges],
        }


# --------------------------------------------------------------------------- markdown I/O

# The closing fence's trailing whitespace is HORIZONTAL-only (`[^\S\n]*`): a bare `\s*` here is greedy
# ACROSS newlines and eats the body's first-line indentation, so node_from_markdown(node_to_markdown(n))
# is lossy — a 4-space Markdown code block loses its first line, and worse, the re-parsed on-disk body
# no longer equals the incoming body, silently defeating Canon._write_batch's idempotent-no-op guard
# (node_content_hash mismatch → a spurious rewrite + timestamp-only commit on every touch) — review-r7.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---[^\S\n]*\r?\n?(.*)$", re.DOTALL)


def node_to_markdown(node: Node) -> str:
    fm = yaml.safe_dump(node.frontmatter(), sort_keys=False, allow_unicode=True, width=1000)
    body = node.body.rstrip("\n")
    return f"---\n{fm}---\n\n{body}\n" if body else f"---\n{fm}---\n"


def node_content_hash(node: Node) -> str:
    """Content hash of a note EXCLUDING the created_at/updated_at timestamps — THE shared rule
    behind both the projector's content-driven staleness gate (``_file_hash``) and the canon's
    idempotent-no-op write detection (``_content_hash``), whose agreement is load-bearing
    (review-r5: they were two byte-identical copies coupled only by comments). Timestamps are
    metadata, not content: a hand-authored note that omits them gets a fresh ``utcnow()`` on every
    parse (``Node.__post_init__``), which would churn the hash — forcing redundant reprojection on
    every read, or an updated_at bump on a no-op re-write (review-low: timestamp staleness churn).
    A real edge/axis/verdict change still moves the hash.

    The body is hashed as ``strip("\\n")`` — the SAME leading/trailing-newline fold the disk round-trip
    applies (``node_to_markdown`` rstrips, ``node_from_markdown`` strips). Hashing the raw ``node.body``
    instead made an in-memory node carrying a trailing ``\\n`` (normal in an LLM's kg_write JSON) hash
    differently from its own on-disk form, so canon's idempotent-no-op guard (``_write_batch``) never
    matched — every idempotent /kg-build re-run rewrote the note with a fresh ``updated_at`` (redundant
    write, forced reprojection, a timestamp-only commit), the exact churn this hash exists to prevent
    (review-r8-3). ``strip("\\n")`` only — NOT a broader strip — so first/last-line spaces stay content."""
    fm = {k: v for k, v in node.frontmatter().items() if k not in ("created_at", "updated_at")}
    return hashlib.sha256((json.dumps(fm, sort_keys=True) + node.body.strip("\n")).encode()).hexdigest()


def normalize_note_text(text: str) -> str:
    r"""Canon note bytes -> their canonical on-read form: leading BOM stripped, CRLF/CR folded to LF.

    Tolerate a leading UTF-8 BOM (U+FEFF): every canon read decodes with encoding="utf-8", which
    preserves a BOM as a leading character, and the frontmatter regex then fails to match — so a note
    hand-edited in an editor that writes BOMs (Windows Notepad's default "UTF-8") would raise and
    SILENTLY vanish from every read via all_nodes()'s tolerance, taking its §1.7 failure memory with it.
    Engine writes never emit a BOM, so this is a no-op on engine-authored notes, and the note is
    re-serialized BOM-less on its next write.

    Normalize line endings for the same reason. A note hand-edited on Windows commonly saves CRLF;
    without this the `\r`s (a) survive `body.strip("\n")` and get written back verbatim, permanently
    corrupting the body with mixed endings AND breaking the idempotent-no-op guard (node_content_hash
    differs between the CRLF-on-disk and LF forms, so every re-save rewrites the note with a fresh
    updated_at and the reconciler flags it changed every time), and (b) a CR-ONLY note fails
    _FRONTMATTER_RE entirely -> ValueError -> all_nodes() swallows it and the whole node, incl. its §1.7
    failed/rejected counter-edges, silently vanishes from every read. Engine writes always emit LF.

    Single-homed here (review-r11) because `node_from_markdown` is NOT the only reader of raw note bytes:
    canonmerge's edgeless / unparseable fast path hands the raw texts to `git merge-file`, where a purely
    cosmetic CRLF or BOM difference reads as a whole-file divergence — every line differs by a `\r`, so
    git cannot 3-way it and a trivially-mergeable note comes back fully conflicted. One home, one rule.
    """
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def node_from_markdown(text: str, *, fallback_id: str | None = None) -> Node:
    # The single PARSE chokepoint; canonmerge's raw-text path normalizes through the same helper.
    text = normalize_note_text(text)
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("note has no YAML frontmatter")
    fm = yaml.load(m.group(1), Loader=_YamlLoader) or {}
    # The frontmatter between the fences must be a mapping. A valid-but-non-mapping YAML document (a
    # top-level list or scalar from a hand-edit, e.g. a stray `- foo`) would otherwise reach `fm.get(...)`
    # below and leak a raw AttributeError; fail through the SAME documented ValueError as a missing
    # frontmatter so every caller sees one malformed-note error type (§1.2).
    if not isinstance(fm, dict):
        raise ValueError("note frontmatter is not a mapping")
    body = m.group(2).strip("\n")
    # Resolve the node id ONCE (fm id > fallback_id > slug(label)) and reuse it for BOTH the edge-source
    # default and fields["id"] below. A present-but-NULL `id:` makes fm.get("id", fallback_id) return
    # None (the key exists, so the default is not applied); Edge.from_dict(e, source=None) on an edge
    # lacking its own `source:` would then raise TypeError, which Canon.all_nodes swallows — dropping
    # the WHOLE node, including its §1.7 failed/rejected counter-edges, from every read. One resolution
    # keeps the two ends consistent so a null-id note still parses.
    resolved_id = fm.get("id") or fallback_id or slug(fm.get("label", "node"))
    # Skip a malformed edge entry (e.g. a hand-edited `- just a string` scalar instead of a mapping)
    # rather than letting it raise and take the whole node — including its failed/rejected counter-
    # edges (§1.7) — out of every read.
    edges = [Edge.from_dict(e, source=resolved_id)
             for e in (fm.get("edges") or []) if isinstance(e, dict)]
    # Mirror Edge.from_dict: filter to known Node fields and drop None values so each absent/None key
    # falls through to the dataclass field default + __post_init__ coercion — the single source of every
    # static default (incl. "prose", and the enum defaults via coerce_axes). Then inject the two values
    # that are NOT plain field defaults: the resolved `id` (resolved once above) and the pre-parsed
    # `edges` (with the malformed-entry skipping above), plus the parsed body.
    known = set(Node.__dataclass_fields__)
    fields = {k: v for k, v in fm.items() if k in known and v is not None}
    fields["id"] = resolved_id
    fields["body"] = body
    fields["edges"] = edges
    return Node(**fields)
