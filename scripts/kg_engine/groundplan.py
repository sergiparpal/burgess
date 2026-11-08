"""The /kg-ground plan's deterministic halves (0.7.0): which items wait for a verdict, in what order and in
which batches, and the excerpt of the source a grounder judges an edge against.

Through 0.6.1 `/kg-ground` had its orchestrator list the queue with `query_graph`. A real canon of 168
unverified edges and 399 nodes came back as 300 000 characters, which Claude Code saved to a file, and the
orchestrator wrote Python scripts to read it, run through the Bash tool. In auto mode Claude Code ignores a
command's Bash permission, so those scripts went to the classifier and stopped on permission prompts (field
report on 0.6.1, the same failure `/kg-build` had before 0.5.0). `kg_ground_plan` hands the orchestrator the
queue as compact ids in batches, and `kg_ground_item` hands each grounder what it needs to judge one item, so
neither ever reads a file.

0.8.0, after the first full pass on that canon (field report on 0.7.0): an adversarial pass marks each
counter-edge with the hub it attacks, so the plan stops offering a hub it has already attacked and nothing
new has come since; and an excerpt cut out of a long table keeps the table's header rows.

Pure stdlib + `model`/`buildplan`; no I/O. `KGEngine.kg_ground_plan` / `kg_ground_item` assemble around these.
"""
from __future__ import annotations

import re

from .buildplan import _forms, _words
from .model import Confidence, EpistemicState, normalize_text, span_present_in

# Items per grounder. The grounder contract caps a run at 20 items, so a batch never exceeds that; 12 keeps
# one grounder's context to about a dozen excerpts.
DEFAULT_BATCH_SIZE = 12
MAX_BATCH_SIZE = 20
# The lineage marker kg_diverge_materialize leaves on a pinned idea (FUSION Stage 4): pins go first.
DIVERGE_MARK = "[diverge] pinned"
# An extractor marks a claim weak with `confidence: AMBIGUOUS`, or with a `confidence_score` under one half (it
# rated the claim less likely than not). Weak text edges are grounded before the other text edges, so a pass
# cut short has judged the claims most likely to be rejected.
WEAK_SCORE = 0.5
# The mark an adversarial pass leaves on each counter-edge it writes (0.8.0): the edge's `notes` open with
# `counter-edge (adversarial pass, hub <hub-id>)`. Through 0.7.0 nothing recorded an attack, and hub degree
# counted every edge, refuted ones and the attack's own counter-edges included, so the plan offered the same
# five hubs on every pass and each pass ended with ten new unverified counter-edges against them: the queue
# never emptied (field report on 0.7.0, a canon of 406 nodes). The form is the one the adversarial grounder
# already wrote on all ten of that pass's counter-edges, so they count.
ATTACK_MARK = "counter-edge (adversarial pass, hub "
_ATTACK_HUB = re.compile(r"counter-edge \(adversarial pass, hub ([a-z0-9][a-z0-9-]*)")
# The most source text one excerpt carries. A grounder judges whether a span states a relation, which needs
# the sentence and its neighbours, not the whole section (one section of the field corpus is 44 000 chars).
EXCERPT_CHARS = 3000
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# A markdown table's rule row, the `| --- | :---: |` line under its header.
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
# The line an excerpt puts between a table's header and the rows it kept, when it skipped rows in between.
TABLE_GAP = "…"


def clamp_batch_size(value) -> int:
    """The batch size to use: a whole number from 1 to MAX_BATCH_SIZE, else DEFAULT_BATCH_SIZE."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_BATCH_SIZE
    return DEFAULT_BATCH_SIZE if n < 1 else min(n, MAX_BATCH_SIZE)


def is_weak(confidence, confidence_score) -> bool:
    """True for an edge its extractor marked weak: `AMBIGUOUS`, or a `confidence_score` under WEAK_SCORE."""
    return confidence == Confidence.AMBIGUOUS or (confidence_score is not None and confidence_score < WEAK_SCORE)


def attacked_hub(notes: "str | None") -> "str | None":
    """The hub a counter-edge attacks, read from the mark its `notes` open with
    (`counter-edge (adversarial pass, hub <hub-id>)`); None for any other edge."""
    m = _ATTACK_HUB.match((notes or "").lstrip())
    return m.group(1) if m else None


def already_attacked(marks: "list[tuple[str, str | None]]", newest_claim: "str | None") -> bool:
    """True when an adversarial pass has attacked a hub and nothing has come since that a new attack could
    test: one of its counter-edges still waits for a verdict, or the newest counter-edge verdict is no older
    than the hub's newest grounded claim.

    `marks` are the `(epistemic_state, verdict_at)` of the counter-edges that name the hub, `newest_claim` the
    latest `verdict_at` among its grounded claims (ISO-8601 UTC, so they compare as strings). A hub with no
    mark has never been attacked."""
    if not marks:
        return False
    if any(state == EpistemicState.UNVERIFIED.value for state, _ in marks):
        return True
    return (newest_claim or "") <= max(at or "" for _, at in marks)


def focus_matches(focus: str, node_id: str, label: str) -> bool:
    """True when every content word of `focus` names the node: occurs among the words of its id or of its
    label, singular or plural, accents ignored (the `buildplan` word rules). An empty focus, or one with no
    content word, matches everything."""
    wanted = _words(focus)
    if not wanted:
        return True
    have: "set[str]" = set()
    for w in _words(node_id.replace("-", " ")) + _words(label or ""):
        have |= _forms(w)
    return all(_forms(w) & have for w in wanted)


def batches(items: list, size: int) -> "list[list]":
    """`items` in consecutive chunks of `size` (the last one shorter)."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def span_excerpt(text: str, span: str, max_chars: int = EXCERPT_CHARS) -> "str | None":
    """The part of `text` (one source section) that holds `span`, with its neighbours as context, at most
    `max_chars` long; None when the span is not in the section.

    The unit is the paragraph (blank-line separated). The smallest run of one to three consecutive paragraphs
    that holds the span is the core, and neighbouring paragraphs are added on both sides while the whole stays
    under the cap. A core longer than the cap, such as a long table with no blank lines, is cut down the same
    way to the lines that hold the span and their neighbours. Matching is the span check's own
    (`normalize_text`), so whatever verified at the boundary is found here.

    A span in a body row of a table cut that way keeps the table's header and rule rows on top, with a
    `TABLE_GAP` line where rows were skipped (0.8.0). Through 0.7.0 the cut kept only the rows around the
    span: the field corpus's 60-line mechanism matrix reached its grounders without the row that names its
    columns (`| Mecanismo | Cubre | … |`), so one grounder guessed what the columns meant and grounded three
    rows, and another judged a fourth row two bare cells and rejected it."""
    if not span or not span.strip() or not text:
        return None
    nspan = normalize_text(span)

    def window(units: "list[str]", sep: str, widths) -> "tuple[int, int] | None":
        for width in widths:
            for i in range(len(units) - width + 1):
                if span_present_in(nspan, normalize_text(sep.join(units[i:i + width]))):
                    return i, i + width
        return None

    def widen(units: "list[str]", sep: str, lo: int, hi: int, cap: int, floor: int = 0) -> "tuple[int, int]":
        while True:
            grew = False
            for nlo, nhi in ((lo - 1, hi), (lo, hi + 1)):
                if floor <= nlo and nhi <= len(units) and len(sep.join(units[nlo:nhi])) <= cap:
                    lo, hi, grew = nlo, nhi, True
            if not grew:
                return lo, hi

    paragraphs = [p for p in _PARAGRAPH_BREAK.split(text) if p.strip()]
    found = window(paragraphs, "\n\n", (1, 2, 3))
    if found is None:
        return None
    lo, hi = found
    core = "\n\n".join(paragraphs[lo:hi])
    if len(core) <= max_chars:
        lo, hi = widen(paragraphs, "\n\n", lo, hi, max_chars)
        return "\n\n".join(paragraphs[lo:hi])
    lines = core.split("\n")
    found = window(lines, "\n", range(1, min(len(lines), 12) + 1))
    if found is None:  # the span runs across more lines than a window covers: hand back the head of the core
        return core[:max_chars]
    lo, hi = found
    head = _table_head(lines, lo)
    if head is not None:
        first, body = head
        top = lines[first:body]
        # room for the rows once the header, a gap line and their line breaks are counted
        room = max_chars - len("\n".join(top)) - len(TABLE_GAP) - 2
        if len("\n".join(lines[lo:hi])) <= room:
            lo, hi = widen(lines, "\n", lo, hi, room, floor=body)
            return "\n".join(top + ([TABLE_GAP] if lo > body else []) + lines[lo:hi])
    lo, hi = widen(lines, "\n", lo, hi, max_chars)
    excerpt = "\n".join(lines[lo:hi])
    return excerpt if len(excerpt) <= max_chars else excerpt[:max_chars]


def _table_head(lines: "list[str]", i: int) -> "tuple[int, int] | None":
    """`(first, body)` for the markdown table whose body holds line `i`: `lines[first:body]` are its header and
    rule rows, and its body starts at `body`. None when line `i` is no table body row."""
    if not lines[i].lstrip().startswith("|"):
        return None
    first = i
    while first > 0 and lines[first - 1].lstrip().startswith("|"):
        first -= 1
    if first + 2 <= i and _TABLE_RULE.match(lines[first + 1]):
        return first, first + 2
    return None
