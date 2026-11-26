"""The labeling sheet of /burgess:kg-eval as data (0.28.0): sample, fill, score.

`scripts/f4_probe.py` printed these numbers from a shell. Under the user's
`permissions.blockReadsOutsideWorkingDirectories`, Claude Code asks the person before every Bash command that
names a path outside the project, and the auto mode's classifier cannot answer that question for them, so on
2026-11-25 /kg-eval measured nothing. Since 0.28.0 the engine runs these steps itself (`kg_eval`), and
`f4_probe.py` is a thin command line over the same functions, for development and CI.

Nothing here prints: an MCP stdio server speaks its protocol on stdout. Errors raise `SheetError` with the
message the command line prints.

The sample is the extraction (0.25.2): `draw` leaves out the proposals still in the hypothesized lane. A
/burgess:kg-generate or /burgess:kg-perturb proposal carries `INFERRED` like an extracted edge, so through 0.25.1
it was sampled as one; /burgess:kg-ground judges proposals, and neither the pack nor the extractor prompt can
change them.

VERDICT vocabulary (the only judgment that matters):
  correct     - the relation is true and specific to the source
  fabricated  - the relation is not supported by the source at all (hallucinated)
  vague       - "true" only because it's generic/unfalsifiable (the generality confound)
  wrong_type  - endpoints related, but the relation label is wrong
span_found (y/n): is there an actual textual span in the source supporting it (the span-present check)?
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import shutil
import tempfile
from collections import Counter, defaultdict

EXTRACTED, INFERRED, AMBIGUOUS = "EXTRACTED", "INFERRED", "AMBIGUOUS"
HYPOTHESIZED = "hypothesized"   # the provenance of a proposal the grounding has not promoted (0.25.2)
SHEET_COLS = [
    "edge_id", "source_label", "target_label", "relation",
    "confidence", "confidence_score", "source_file",
    "verdict", "span_found", "notes",
]
GOOD = {"correct"}
ASTROLOGY = {"fabricated", "vague"}
VALID_VERDICTS = GOOD | ASTROLOGY | {"wrong_type"}
TRUE_VALUES = {"y", "yes", "true", "1"}  # accepted spellings for span_found
FALSE_VALUES = {"n", "no", "false", "0"}  # and for its negative, when `fill` reads a labels file
FILL_REPORT_CAP = 20     # problems `fill` lists before it summarizes the rest

PRECISION_GATE = 0.70    # advisory target reported with the precision (this measures, never enforces)
CALIBRATION_GAP = 0.10   # mean-confidence gap that counts as "scores track correctness"
MIN_RELATION_N = 3       # don't show a per-relation precision under this many labeled edges
SAMPLE_SEED = 42         # fixed seed so a sample is reproducible
SAMPLE_SIZE = 80         # the edges a sheet samples by default
TOP_RELATIONS = 15       # cap on the top-relations list in a summary


class SheetError(ValueError):
    """A sheet, a graph or a labels file that cannot be used, with the message to show."""


def verdict_of(row) -> str:
    """The verdict cell of a label row, normalized (stripped + lowercased)."""
    return (row.get("verdict") or "").strip().lower()


def is_correct(row) -> bool:
    """True iff the row's normalized verdict counts as correct."""
    return verdict_of(row) in GOOD


def span_found(row) -> bool:
    """True iff the row's span_found cell is one of the accepted true spellings."""
    return (row.get("span_found") or "").strip().lower() in TRUE_VALUES


def median(sorted_vals):
    """True median of an already-sorted, non-empty list: average the two central elements on even
    length rather than reporting the upper-middle one (finding harness-f4-2)."""
    m = len(sorted_vals)
    mid = m // 2
    if m % 2:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2


def load(path):
    """(nodes, edges, {node id: label}) of a node-link graph.json."""
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig tolerates a BOM-prefixed export
        data = json.load(f)
    if not isinstance(data, dict):
        raise SheetError(f"'{path}' is not a node-link graph (no nodes/links object)")
    nodes = data.get("nodes", [])
    edges = data.get("links", data.get("edges", []))
    id2label = {n.get("id"): n.get("label", n.get("id")) for n in nodes}
    return nodes, edges, id2label


def summarize(path) -> dict:
    """The graph's shape: counts, nodes by file_type, edges by confidence, the top relations, the INFERRED
    confidence scores, and the judged edges split into hypothesized proposals and the extraction to sample."""
    nodes, edges, _ = load(path)
    by_rel = Counter(e.get("relation", "?") for e in edges)
    scores = sorted(e.get("confidence_score") for e in edges
                    if e.get("confidence") == INFERRED and e.get("confidence_score") is not None)
    judged = [e for e in edges if e.get("confidence") in (INFERRED, AMBIGUOUS)]
    proposals = sum(1 for e in judged if e.get("provenance") == HYPOTHESIZED)
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "nodes_by_file_type": Counter(n.get("file_type", "?") for n in nodes).most_common(),
        "edges_by_confidence": Counter(e.get("confidence", "?") for e in edges).most_common(),
        "relations_distinct": len(by_rel),
        "top_relations": by_rel.most_common(TOP_RELATIONS),
        "inferred_confidence_score": ({"n": len(scores), "min": scores[0], "median": median(scores),
                                       "max": scores[-1]} if scores else None),
        "judged": len(judged),
        "hypothesized_proposals": proposals,
        "extraction_to_sample": len(judged) - proposals,
    }


def draw(path, n, include_extracted=False, include_hypothesized=False) -> "tuple[list[dict], int]":
    """The seeded sample of a graph's edges as sheet rows, and how many proposals it left out."""
    # n<=0 would slice an empty/mis-sliced pool and write a 0-row sheet (finding harness-f4-3).
    if n <= 0:
        raise SheetError(f"--n must be a positive integer, got {n}")
    _, edges, id2label = load(path)
    pool = list(enumerate(edges))
    if not include_extracted:
        pool = [(i, e) for i, e in pool if e.get("confidence") != EXTRACTED]
    # A proposal still in the hypothesized lane is not extraction (0.25.2, see the module docstring). It is
    # left out before the seeded shuffle, so a graph with no proposals samples exactly as it did before.
    left_out = 0
    if not include_hypothesized:
        kept = [(i, e) for i, e in pool if e.get("provenance") != HYPOTHESIZED]
        left_out, pool = len(pool) - len(kept), kept
    if not pool:
        hint = "--include-hypothesized" if left_out else "--include-extracted"
        raise SheetError(f"no edges to label (try {hint})")
    rng = random.Random(SAMPLE_SEED)
    rng.shuffle(pool)
    rows = [{
        # the deterministic edge_id (e_{slug(src)}__{slug(rel)}__{slug(tgt)}) is the stable handle back to
        # the canon; fall back to the positional index only if a link lacks it.
        "edge_id": e.get("id", i),
        "source_label": id2label.get(e.get("source"), e.get("source")),
        "target_label": id2label.get(e.get("target"), e.get("target")),
        "relation": e.get("relation", ""),
        "confidence": e.get("confidence", ""),
        "confidence_score": e.get("confidence_score", ""),
        "source_file": e.get("source_file", ""),
        "verdict": "", "span_found": "", "notes": "",
    } for i, e in pool[:n]]
    return rows, left_out


def write_sheet(rows, out) -> None:
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLS)
        w.writeheader()
        w.writerows(rows)


def _fill_label(edge_id, label):
    """One labels-file entry as (verdict, span_found, notes, problems). `fill`'s whole contract per row:
    a JSON object whose verdict is in the vocabulary and whose span_found reads as yes or no."""
    if not isinstance(label, dict):
        return None, None, None, [f"{edge_id}: expected an object with verdict/span_found/notes, got {label!r}"]
    problems = []
    verdict = str(label.get("verdict", "")).strip().lower()
    if verdict not in VALID_VERDICTS:
        problems.append(f"{edge_id}: verdict {label.get('verdict')!r} is not one of {sorted(VALID_VERDICTS)}")
    found = str(label.get("span_found", "")).strip().lower()
    if found in TRUE_VALUES:
        found = "y"
    elif found in FALSE_VALUES:
        found = "n"
    else:
        problems.append(f"{edge_id}: span_found {label.get('span_found')!r} is not y or n")
    notes = label.get("notes", "")
    notes = notes if isinstance(notes, str) else json.dumps(notes, ensure_ascii=False)
    return verdict, found, notes, problems


def fill(path, labels_path) -> dict:
    """Fill the sheet's `verdict`, `span_found` and `notes` from an annotator's labels file (0.11.7).

    The annotator has no shell. It writes one JSON object, `{edge_id: {"verdict", "span_found", "notes"}}`,
    with Claude Code's Write tool, and this writes the CSV with the csv module's quoting. The fill takes the
    labels whole or not at all: a row with no entry, an entry for an edge the sheet lacks, a label outside the
    vocabulary or a span_found that is neither yes nor no raises `SheetError` before the sheet is touched, so
    the orchestrator can hand the message back to the annotator. Every other column, and the row order, stay
    as the sheet was written. Returns {"filled": rows filled, "counts": [(verdict, count), ...]}."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    lacking = [c for c in ("edge_id", "verdict", "span_found", "notes") if c not in fields]
    if lacking:
        raise SheetError(f"'{path}' is not a labeling sheet: no {', '.join(lacking)} column")
    try:
        with open(labels_path, encoding="utf-8-sig") as f:
            labels = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SheetError(f"could not read '{labels_path}' as JSON: {e}") from None
    if not isinstance(labels, dict):
        raise SheetError(f"'{labels_path}' must hold one JSON object keyed by edge_id, not {type(labels).__name__}")

    ids = [r["edge_id"] for r in rows]
    problems = [f"{i}: no entry in the labels file" for i in ids if i not in labels]
    sheet_ids = set(ids)
    problems += [f"{k}: not a row of the sheet" for k in labels if k not in sheet_ids]
    filled = []
    for r in rows:
        if r["edge_id"] not in labels:
            continue
        verdict, found, notes, bad = _fill_label(r["edge_id"], labels[r["edge_id"]])
        problems += bad
        filled.append((r, verdict, found, notes))
    if problems:
        shown = problems[:FILL_REPORT_CAP]
        more = len(problems) - len(shown)
        raise SheetError(f"'{labels_path}' does not label '{path}' row for row; the sheet is unchanged:\n  "
                         + "\n  ".join(shown) + (f"\n  ... and {more} more" if more else ""))

    for r, verdict, found, notes in filled:
        r["verdict"], r["span_found"], r["notes"] = verdict, found, notes
    # Write beside the sheet and swap it in, so an interrupted fill never leaves half a sheet behind.
    fd, tmp = tempfile.mkstemp(prefix=".fill-", suffix=".csv", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        try:
            shutil.copymode(path, tmp)  # mkstemp makes the file 0600; the sheet keeps its own permissions
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"filled": len(filled), "counts": Counter(v for _, v, _, _ in filled).most_common()}


def labeled_rows(path) -> list:
    """The label CSV's rows that carry a verdict."""
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if verdict_of(r)]


def score_rows(rows) -> dict:
    """Precision, astrology rate, span-support rate, the verdict breakdown, precision per relation and the
    confidence calibration of labeled rows. Raises `SheetError` when no row is labeled."""
    if not rows:
        raise SheetError("no labeled rows (fill the `verdict` column first)")
    n = len(rows)
    verdicts = Counter(verdict_of(r) for r in rows)
    unknown = {v: c for v, c in verdicts.items() if v not in VALID_VERDICTS}
    correct = sum(verdicts[v] for v in GOOD)
    astro = sum(verdicts[v] for v in ASTROLOGY)
    span_y = sum(1 for r in rows if span_found(r))

    per_rel = defaultdict(lambda: [0, 0])
    has_relation = any("relation" in r for r in rows)
    for r in rows:
        rel = r.get("relation") or "?"
        per_rel[rel][0] += is_correct(r)
        per_rel[rel][1] += 1
    relations = [{"relation": rel, "correct": ok, "labeled": tot, "precision": ok / tot}
                 for rel, (ok, tot) in sorted(per_rel.items(), key=lambda x: -x[1][1]) if tot >= MIN_RELATION_N]

    scores_for_correct, scores_for_wrong = [], []
    for r in rows:
        try:
            value = float(r.get("confidence_score", ""))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(value):  # 'NaN'/'inf' parse to a float but would poison the calibration mean
            continue
        (scores_for_correct if is_correct(r) else scores_for_wrong).append(value)
    calibration = None
    if scores_for_correct and scores_for_wrong:
        mean_correct = sum(scores_for_correct) / len(scores_for_correct)
        mean_wrong = sum(scores_for_wrong) / len(scores_for_wrong)
        gap = mean_correct - mean_wrong
        calibration = {"mean_correct": mean_correct, "mean_wrong": mean_wrong, "gap": gap,
                       "tracks": gap >= CALIBRATION_GAP}
    return {
        "labeled": n,
        "correct": correct,
        "precision": correct / n,
        "astrology_rate": astro / n,
        "span_support_rate": span_y / n,
        "verdicts": verdicts.most_common(),
        "unknown_verdicts": unknown,
        "per_relation": relations if has_relation else None,
        "calibration": calibration,
    }
