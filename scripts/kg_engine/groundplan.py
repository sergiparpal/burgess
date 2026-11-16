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

0.9.0: a rejected claim can carry a lead, the edge its span does state, which `/kg-build --leads` writes.

0.10.0: an attack that writes no counter-edge is recorded too, so the plan stops offering that hub as well.

0.18.0: an edge with no span, a proposal, is judged against the source sections where both its ends are
discussed, found by the spans of their other edges (`nearest_pair`, `pair_excerpts`).

Pure stdlib + `model`/`buildplan`; no I/O. `KGEngine.kg_ground_plan` / `kg_ground_item` assemble around these.
"""
from __future__ import annotations

import json
import re

from .buildplan import _forms, _words
from .model import Confidence, EpistemicState, normalize_text, slug, span_present_in

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
# An attack that writes no counter-edge (0.10.0). When no span in the source sets itself against a hub or one
# of its claims, the adversarial grounder ends with a falsifying question instead (its contract's Output B),
# and through 0.9.0 that left nothing behind: no counter-edge, so no mark. A hub that had gained a grounded
# claim since its last mark was then offered on every later pass, and each attack searched the source for
# nothing again (field report on 0.9.0: a lead written from one of the hub's own rejected counter-edges was
# grounded on it, which reopened the hub, and the re-attack found nothing in eight documents). The grounder
# now records such an attack with `kg_record_attack`: one line in the ledger beside the canon
# (`canon.HUB_ATTACKS`), which the plan counts like a counter-edge judged at the time of the record. The
# ledger is engine state, not canon: a lost or unreadable one only offers those hubs again, as before 0.10.0.
ATTACK_REASONS = ("no-span", "vague")     # the decline tags of the adversarial contract's Output B
ATTACK_RECORDED = "recorded"              # what a ledger record stands for among `already_attacked`'s marks
MAX_QUESTION_CHARS = 2000
# A lead (0.9.0): the edge a rejected claim's span does state instead, when a grounder rejects it as
# `wrong-relation` or `wrong-node`. `kg_ground(..., lead=...)` appends it to the rejected edge's notes as the
# segment `lead: <head> <relation> <tail>`, `/kg-build --leads` has an extractor write it, and the written
# edge opens its notes with `lead (from <rejected-edge-id>)`, which marks the lead taken. Through 0.8.1 a lead
# was only named in a report: `/kg-build` skips every section that already has edges, so nothing could write
# it (field report on 0.8.1: thirteen leads, two of them `enables` edges the 0.8.0 pack added).
# A lead belongs to the rejection that recorded it (0.11.1). A verdict that changes the edge's state and
# records no lead of its own appends `lead: none`, which withdraws the lead the notes held. Through 0.11.0 a
# lead outlived the rejection it came from: an edge rejected with a lead, grounded again by the user's
# decision and later rejected once more without a lead offered the overturned lead again as pending (field
# report on 0.11.0: the three edges the user grounded again each carry a lead the user had ruled out).
LEAD_MARK = "lead: "
LEAD_NONE = LEAD_MARK + "none"
LEAD_FROM_MARK = "lead (from "
_LEAD = re.compile(r"(?:^|\s\|\s)lead: (?:([\w-]+) ([a-z_]+) ([\w-]+)|(none))(?=\s\|\s|\s*$)")
_LEAD_FROM = re.compile(r"lead \(from (e_[\w-]+)\)")
# The most source text one excerpt carries. A grounder judges whether a span states a relation, which needs
# the sentence and its neighbours, not the whole section (one section of the field corpus is 44 000 chars).
EXCERPT_CHARS = 3000
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# A markdown table's rule row, the `| --- | :---: |` line under its header.
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
# The line an excerpt puts between a table's header and the rows it kept, when it skipped rows in between.
TABLE_GAP = "…"
# What kg_ground_item shows for an edge with no span (0.18.0): the sections that hold a span of each end, the
# nearest pair of those spans first. Each section's excerpts fit in EXCERPT_CHARS together, so one proposal
# brings at most three excerpts' worth of text, and each end's own list names at most END_SECTIONS sections.
SHARED_SECTIONS = 3
END_SECTIONS = 12
# The paragraphs a node's promotion on a support span writes into its body (0.16.1): the span, then its file.
GROUNDING_SPAN_MARK = "grounding span: "
GROUNDING_SOURCE_MARK = "grounding source: "
# A second reading's passage (0.19.0). `/kg-perturb` crosses a second construction of a source against the
# graph, and an `ensemble` candidate keeps the edge that construction wrote, with the span it wrote it from.
# `kg_propose` checks that span against the configured sources and, when it holds there, opens the proposal's
# notes with the segment `passage: {"span": …, "source_file": …}` (JSON, so a span holding ` | ` or quotes
# cannot cut it short). Only the engine writes it: `kg_propose` drops an opening passage segment it was handed.
# `kg_ground_item` reads it back and shows the grounder the excerpt around it. Through 0.18.1 the candidate was
# always `bridges` and carried no text: the field test of 2026-11-16 re-read a source the graph was built from,
# and the one relation the re-reading found that the graph lacked (`tcp-ip-frente-a-osi grounds
# regla-de-centralizacion`) reached the grounder as a bridge with no passage, and was rejected `no-support`.
PASSAGE_MARK = "passage: "


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

    `marks` are the `(epistemic_state, verdict_at)` of the counter-edges that name the hub, plus one
    `(ATTACK_RECORDED, at)` for each attack the ledger records against it (0.10.0); `newest_claim` is the
    latest `verdict_at` among its grounded claims (ISO-8601 UTC, so they compare as strings). A hub with no
    mark has never been attacked. `verdict_at` is when an edge entered its state: a re-verdict that keeps
    the state keeps it (0.10.2), so neither a re-confirmed claim nor a re-sealed counter-edge moves a time."""
    if not marks:
        return False
    if any(state == EpistemicState.UNVERIFIED.value for state, _ in marks):
        return True
    return (newest_claim or "") <= max(at or "" for _, at in marks)


def attack_record(hub: str, at: str, reason: str, question: str) -> str:
    """One ledger line (0.10.0): the hub, when the attack was recorded, why it wrote no counter-edge
    (`ATTACK_REASONS`), and the falsifying question it ended with."""
    return json.dumps({"hub": hub, "at": at, "reason": reason, "question": question}, ensure_ascii=False)


def attack_records(lines) -> "dict[str, list[str]]":
    """hub id -> the times of the attacks recorded against it, from the ledger's lines. A line that is not
    such a record (a torn last line, a hand edit, another shape) is skipped, never an error."""
    out: "dict[str, list[str]]" = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        hub, at = (rec.get("hub"), rec.get("at")) if isinstance(rec, dict) else (None, None)
        if isinstance(hub, str) and hub and isinstance(at, str) and at:
            out.setdefault(hub, []).append(at)
    return out


def parse_lead(text: "str | None", edge_types) -> "tuple[tuple[str, str, str] | None, str]":
    """A lead as a grounder types it, `<head-id> <relation> <tail-id>`: the ids slugged, the relation one of
    the pack's (`defends-against` names `defends_against`). Returns ``(triple, "")``, or ``(None, problem)``.
    The lead is the edge a rejected claim's span does state (0.9.0); its span is that claim's own."""
    parts = (text or "").split()
    if len(parts) != 3:
        return None, "write a lead as '<head-id> <relation> <tail-id>'"
    head, relation, tail = slug(parts[0]), parts[1].lower().replace("-", "_"), slug(parts[2])
    if relation not in edge_types:
        return None, f"the pack declares no relation {parts[1]!r}"
    if head == tail:
        return None, "a lead joins two different nodes"
    return (head, relation, tail), ""


def lead_of(notes: "str | None") -> "tuple[str, str, str] | None":
    """The latest lead recorded in an edge's notes (the ``lead: <head> <relation> <tail>`` segment
    `kg_ground` appends), or None. A later lead replaces an earlier one, and a later ``lead: none``
    (`LEAD_NONE`, 0.11.1) withdraws it."""
    found = _LEAD.findall(notes or "")
    if not found:
        return None
    head, relation, tail, withdrawn = found[-1]
    return None if withdrawn else (head, relation, tail)


def lead_from(notes: "str | None") -> "str | None":
    """The rejected edge an edge was written from as its lead: its notes open with
    ``lead (from <edge-id>)``. None for any other edge."""
    m = _LEAD_FROM.match((notes or "").lstrip())
    return m.group(1) if m else None


def _opening_passage(notes: "str | None") -> "tuple[dict, int] | None":
    """The JSON object of the passage segment ``notes`` open with, and where it ends in the stripped notes;
    None when they open with no such segment (`PASSAGE_MARK`, 0.19.0)."""
    text = (notes or "").lstrip()
    if not text.startswith(PASSAGE_MARK):
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(text, len(PASSAGE_MARK))
    except ValueError:
        return None
    return (value, end) if isinstance(value, dict) else None


def passage_of(notes: "str | None") -> "tuple[str, str] | None":
    """``(span, source_file)`` of the passage a proposal's notes open with (0.19.0): the span a second
    construction wrote the proposed edge from, as `kg_propose` recorded it once it verified against a
    configured source. None for any other edge, and for a segment that is not one the engine writes."""
    found = _opening_passage(notes)
    if found is None:
        return None
    span, name = found[0].get("span"), found[0].get("source_file", "")
    if not (isinstance(span, str) and span.strip() and isinstance(name, str)):
        return None
    return span, name


def without_passage(notes: "str | None") -> str:
    """``notes`` without the passage segment they open with, and its ` | ` separator; unchanged when they
    open with none."""
    found = _opening_passage(notes)
    if found is None:
        return notes or ""
    rest = (notes or "").lstrip()[found[1]:]
    return rest[3:] if rest.startswith(" | ") else rest.lstrip()


def with_passage(notes: "str | None", span: str, source_file: str) -> str:
    """``notes`` opened by the passage segment for ``span`` in ``source_file``, replacing any it opened with."""
    segment = PASSAGE_MARK + json.dumps({"span": span, "source_file": source_file}, ensure_ascii=False)
    rest = without_passage(notes)
    return segment + (" | " + rest if rest else "")


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


def node_star_batches(items: list, ends: dict, size: int) -> "list[list]":
    """The queue in batches of `size` that keep each queued node with the queued edges that touch it
    (0.17.1).

    `items` is the plan's queue in its order, as `{"id", "kind"}` dicts, and `ends` maps each queued edge
    id to its two node ids. A queued node, the queued edges that touch it, and any other queued node those
    edges reach make one unit, its nodes first. A unit is never split: it joins the current batch when it
    fits, else it starts the next one, and a unit larger than `size` is a batch of its own. The rest is
    packed in queue order, as `batches` packs it, so a queue with no node comes out exactly as `batches`
    cuts it.

    Through 0.17.0 the queue was cut every `size` items. On the field graph of 2026-11-15 a generated
    compression sat in one batch and its star edges in all three. Two grounders judged it at the same time:
    one rejected the node while another grounded an edge into it."""
    parent = {it["id"]: it["id"] for it in items if it["kind"] == "node"}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    touched = {it["id"]: [n for n in ends.get(it["id"], ()) if n in parent]
               for it in items if it["kind"] == "edge"}
    for nodes in touched.values():
        for a, b in zip(nodes, nodes[1:]):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

    def unit_of(it):
        if it["kind"] == "node":
            return find(it["id"])
        nodes = touched.get(it["id"])
        return find(nodes[0]) if nodes else None

    members: dict = {}
    for it in items:
        key = unit_of(it)
        if key is not None:
            members.setdefault(key, []).append(it)
    units, emitted = [], set()
    for it in items:
        key = unit_of(it)
        if key is None:
            units.append([it])
        elif key not in emitted:
            emitted.add(key)
            unit = members[key]
            units.append([m for m in unit if m["kind"] == "node"] + [m for m in unit if m["kind"] != "node"])
    out, cur = [], []
    for unit in units:
        if cur and len(cur) + len(unit) > size:
            out.append(cur)
            cur = []
        cur.extend(unit)
        if len(cur) >= size:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _paragraphs(text: str) -> "list[str]":
    """The blank-line separated paragraphs of `text` that hold anything, the unit an excerpt is cut in."""
    return [p for p in _PARAGRAPH_BREAK.split(text) if p.strip()]


def _window(units: "list[str]", sep: str, widths, nspan: str) -> "tuple[int, int] | None":
    """`(lo, hi)` of the first run of `units` that holds the normalized span `nspan`, the narrowest width of
    `widths` first; None when no run does."""
    for width in widths:
        for i in range(len(units) - width + 1):
            if span_present_in(nspan, normalize_text(sep.join(units[i:i + width]))):
                return i, i + width
    return None


def _widen(units: "list[str]", sep: str, lo: int, hi: int, cap: int, floor: int = 0) -> "tuple[int, int]":
    """`(lo, hi)` grown one unit at a time on either side while the joined run stays within `cap`."""
    while True:
        grew = False
        for nlo, nhi in ((lo - 1, hi), (lo, hi + 1)):
            if floor <= nlo and nhi <= len(units) and len(sep.join(units[nlo:nhi])) <= cap:
                lo, hi, grew = nlo, nhi, True
        if not grew:
            return lo, hi


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
    paragraphs = _paragraphs(text)
    found = _window(paragraphs, "\n\n", (1, 2, 3), nspan)
    if found is None:
        return None
    lo, hi = found
    core = "\n\n".join(paragraphs[lo:hi])
    if len(core) <= max_chars:
        lo, hi = _widen(paragraphs, "\n\n", lo, hi, max_chars)
        return "\n\n".join(paragraphs[lo:hi])
    lines = core.split("\n")
    found = _window(lines, "\n", range(1, min(len(lines), 12) + 1), nspan)
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
            lo, hi = _widen(lines, "\n", lo, hi, room, floor=body)
            return "\n".join(top + ([TABLE_GAP] if lo > body else []) + lines[lo:hi])
    lo, hi = _widen(lines, "\n", lo, hi, max_chars)
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


def grounding_spans(body: "str | None") -> "list[tuple[str, str]]":
    """`(span, file)` for each support span a node was promoted on, read from the paragraphs the promotion
    writes into its body: `grounding span: <span>`, then `grounding source: <file>` (0.16.1). `file` is ""
    when no such paragraph follows, as on a node promoted through 0.16.0."""
    paragraphs = [p.strip() for p in _paragraphs(body or "")]
    out = []
    for i, p in enumerate(paragraphs):
        if not p.startswith(GROUNDING_SPAN_MARK):
            continue
        span = p[len(GROUNDING_SPAN_MARK):].strip()
        after = paragraphs[i + 1] if i + 1 < len(paragraphs) else ""
        name = after[len(GROUNDING_SOURCE_MARK):].strip() if after.startswith(GROUNDING_SOURCE_MARK) else ""
        if span:
            out.append((span, name))
    return out


def nearest_pair(text: str, spans_a: "list[str]", spans_b: "list[str]") -> "tuple[int, str, str] | None":
    """`(gap, span_a, span_b)`: the span of each list that lies nearest a span of the other in `text`, one
    source section, with `gap` the number of paragraphs between them (0 when they share a paragraph or touch).
    A span sits where `span_excerpt` finds it, in the narrowest run of one to three paragraphs that holds it.
    Between pairs as near, two spans that share a paragraph win over two that only touch, and then the earlier
    span of each list. None when a list has no span that sits in such a run."""
    paragraphs = _paragraphs(text)
    runs = [(i, i + width, normalize_text("\n\n".join(paragraphs[i:i + width])))
            for width in (1, 2, 3) for i in range(len(paragraphs) - width + 1)]

    def placed(spans: "list[str]") -> "list[tuple[str, int, int]]":
        out = []
        for span in spans:
            nspan = normalize_text(span)
            hit = next(((lo, hi) for lo, hi, norm in runs if span_present_in(nspan, norm)), None)
            if nspan and hit is not None:
                out.append((span, *hit))
        return out

    best, best_key = None, None
    in_b = placed(spans_b)
    for sa, la, ha in placed(spans_a):
        for sb, lb, hb in in_b:
            apart = max(la, lb) - min(ha, hb)    # below 0: the runs share a paragraph; 0: they touch
            key = (max(0, apart), apart >= 0)
            if best_key is None or key < best_key:
                best, best_key = (key[0], sa, sb), key
    return best


def pair_excerpts(text: str, span_a: str, span_b: str, max_chars: int = EXCERPT_CHARS) -> "list[str]":
    """The excerpts of `text`, one source section, that show both spans, within `max_chars` together. When
    the paragraphs from one span to the other fit, that passage is the one excerpt, widened with its
    neighbours as `span_excerpt` widens. Otherwise each span gets its own `span_excerpt` of half the room,
    `span_a`'s first, and one excerpt that already holds the other span is kept alone."""
    na, nb = normalize_text(span_a), normalize_text(span_b)
    if na == nb:
        one = span_excerpt(text, span_a, max_chars)
        return [one] if one is not None else []
    paragraphs = _paragraphs(text)
    wa = _window(paragraphs, "\n\n", (1, 2, 3), na) if na else None
    wb = _window(paragraphs, "\n\n", (1, 2, 3), nb) if nb else None
    if wa is not None and wb is not None:
        lo, hi = min(wa[0], wb[0]), max(wa[1], wb[1])
        if len("\n\n".join(paragraphs[lo:hi])) <= max_chars:
            lo, hi = _widen(paragraphs, "\n\n", lo, hi, max_chars)
            return ["\n\n".join(paragraphs[lo:hi])]
    half = max_chars // 2
    ea, eb = span_excerpt(text, span_a, half), span_excerpt(text, span_b, half)
    if ea is not None and span_present_in(nb, normalize_text(ea)):
        return [ea]
    if eb is not None and span_present_in(na, normalize_text(eb)):
        return [eb]
    return [x for x in (ea, eb) if x is not None]
