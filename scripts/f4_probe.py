#!/usr/bin/env python3
"""
f4_probe.py — measure the extractor's precision on a non-self-grounding conceptual document.

Turns the extractor's output graph.json (NetworkX node-link) into precision numbers by sampling
edges, labeling each against the source, and scoring. Also reports the astrology rate
(fabricated+vague), the span-support rate, precision per relation type, and — if edges carry a
numeric confidence — whether that confidence actually predicts correctness.

Usage:
  python f4_probe.py summary  graph.json
  python f4_probe.py sheet    graph.json --n 80 --out labels.csv
  # label every row: {"<edge_id>": {"verdict": ..., "span_found": "y"|"n", "notes": ...}, ...}
  python f4_probe.py fill     labels.csv labels.json
  python f4_probe.py score    labels.csv

VERDICT vocabulary (the only judgment that matters):
  correct     - the relation is true and specific to the source
  fabricated  - the relation is not supported by the source at all (hallucinated)
  vague       - "true" only because it's generic/unfalsifiable (the generality confound)
  wrong_type  - endpoints related, but the relation label is wrong
span_found (y/n): is there an actual textual span in the source supporting it (the span-present check)?
"""

import argparse
import csv
import json
import math
import os
import random
import shutil
import sys
import tempfile
from collections import Counter, defaultdict

EXTRACTED, INFERRED, AMBIGUOUS = "EXTRACTED", "INFERRED", "AMBIGUOUS"
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

PRECISION_GATE = 0.70    # advisory exit gate printed by score() (this script measures, never enforces)
CALIBRATION_GAP = 0.10   # mean-confidence gap that counts as "scores track correctness"
MIN_RELATION_N = 3       # don't show a per-relation precision under this many labeled edges
SAMPLE_SEED = 42         # fixed seed so sheet() samples reproducibly
TOP_RELATIONS = 15       # cap on the top-relations list in summary()


def _verdict(row):
    """The verdict cell of a label row, normalized (stripped + lowercased)."""
    return row.get("verdict", "").strip().lower()


def _is_correct(row):
    """True iff the row's normalized verdict counts as correct."""
    return _verdict(row) in GOOD


def _span_found(row):
    """True iff the row's span_found cell is one of the accepted true spellings."""
    return row.get("span_found", "").strip().lower() in TRUE_VALUES


def _median(sorted_vals):
    """True median of an already-sorted, non-empty list: average the two central elements on even
    length rather than reporting the upper-middle one (finding harness-f4-2)."""
    m = len(sorted_vals)
    mid = m // 2
    if m % 2:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2


def load(path):
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig tolerates a BOM-prefixed export
        data = json.load(f)
    nodes = data.get("nodes", [])
    edges = data.get("links", data.get("edges", []))
    id2label = {n.get("id"): n.get("label", n.get("id")) for n in nodes}
    return nodes, edges, id2label


def _print_counter(title, counter, top=None, row=lambda k, v: f"  {k:12} {v}"):
    """Print a titled Counter as most_common rows; `top` caps the rows, `row` formats each."""
    print(title)
    for k, v in counter.most_common(top):
        print(row(k, v))


def summary(path):
    nodes, edges, _ = load(path)
    print(f"nodes: {len(nodes)}   edges: {len(edges)}\n")

    by_type = Counter(n.get("file_type", "?") for n in nodes)
    _print_counter("nodes by file_type:", by_type)

    by_conf = Counter(e.get("confidence", "?") for e in edges)
    _print_counter("\nedges by confidence:", by_conf)

    by_rel = Counter(e.get("relation", "?") for e in edges)
    _print_counter(f"\ntop relations ({len(by_rel)} distinct):", by_rel,
                   top=TOP_RELATIONS, row=lambda k, v: f"  {v:4}  {k}")

    scores = [e.get("confidence_score") for e in edges
              if e.get("confidence") == INFERRED and e.get("confidence_score") is not None]
    if scores:
        scores.sort()
        print(f"\nINFERRED confidence_score: n={len(scores)} "
              f"min={scores[0]:.2f} median={_median(scores):.2f} max={scores[-1]:.2f}")

    judged = sum(1 for e in edges if e.get("confidence") in (INFERRED, AMBIGUOUS))
    print(f"\njudged edges (INFERRED+AMBIGUOUS): {judged} / {len(edges)} "
          f"({100*judged/max(len(edges),1):.0f}%) <- the precision-relevant part")


def sheet(path, n, out, include_extracted):
    # n<=0 would slice an empty/mis-sliced pool and write a 0-row sheet while exiting success
    # (finding harness-f4-3). Reject it loudly so the labeling run can't silently produce nothing.
    if n <= 0:
        sys.exit(f"--n must be a positive integer, got {n}")
    _, edges, id2label = load(path)
    pool = list(enumerate(edges))
    if not include_extracted:
        pool = [(i, e) for i, e in pool if e.get("confidence") != EXTRACTED]
    if not pool:
        sys.exit("no edges to label (try --include-extracted)")
    random.seed(SAMPLE_SEED)
    random.shuffle(pool)
    pick = pool[:n]

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLS)
        w.writeheader()
        for i, e in pick:
            w.writerow({
                # the deterministic edge_id (e_{slug(src)}__{slug(rel)}__{slug(tgt)}) is the stable
                # handle back to the canon; fall back to the positional index only if a link lacks it.
                "edge_id": e.get("id", i),
                "source_label": id2label.get(e.get("source"), e.get("source")),
                "target_label": id2label.get(e.get("target"), e.get("target")),
                "relation": e.get("relation", ""),
                "confidence": e.get("confidence", ""),
                "confidence_score": e.get("confidence_score", ""),
                "source_file": e.get("source_file", ""),
                "verdict": "", "span_found": "", "notes": "",
            })
    print(f"wrote {len(pick)} edges to {out}")
    print("label every row (verdict: correct|fabricated|vague|wrong_type, span_found: y|n) in a JSON file, then:")
    print(f"  python f4_probe.py fill {out} <labels.json>")
    print(f"  python f4_probe.py score {out}")


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


def fill(path, labels_path):
    """Fill the sheet's `verdict`, `span_found` and `notes` from an annotator's labels file (0.11.7).

    The annotator has no shell. It writes one JSON object, `{edge_id: {"verdict", "span_found", "notes"}}`,
    with Claude Code's Write tool, and this writes the CSV with the csv module's quoting. Through 0.11.6
    the annotator wrote the CSV itself through Bash, and in a setup that asks before every shell command
    one /kg-eval needed 74 approvals from its three annotators (2026-11-10). The fill takes the labels
    whole or not at all: a row with no entry, an entry for an edge the sheet lacks, a label outside the
    vocabulary or a span_found that is neither yes nor no stops it before the sheet is touched, so the
    orchestrator can hand the message back to the annotator. Every other column, and the row order, stay
    as `sheet` wrote them."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    lacking = [c for c in ("edge_id", "verdict", "span_found", "notes") if c not in fields]
    if lacking:
        sys.exit(f"'{path}' is not a labeling sheet: no {', '.join(lacking)} column")
    try:
        with open(labels_path, encoding="utf-8-sig") as f:
            labels = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f"could not read '{labels_path}' as JSON: {e}")
    if not isinstance(labels, dict):
        sys.exit(f"'{labels_path}' must hold one JSON object keyed by edge_id, not {type(labels).__name__}")

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
        sys.exit(f"'{labels_path}' does not label '{path}' row for row; the sheet is unchanged:\n  "
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
    counts = Counter(v for _, v, _, _ in filled)
    print(f"filled {len(filled)} rows of {path} from {labels_path}: "
          + ", ".join(f"{v} {c}" for v, c in counts.most_common()))


def _load_labeled_rows(path):
    """Read the label CSV, keeping only rows with a non-empty verdict cell."""
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if _verdict(r)]


def _report_headline(rows, n):
    """Print the precision / astrology / span-support headline block."""
    verdicts = Counter(_verdict(r) for r in rows)
    unknown = {v: c for v, c in verdicts.items() if v not in VALID_VERDICTS}
    if unknown:
        print(f"WARNING: {sum(unknown.values())} row(s) carry an unrecognized verdict "
              f"{dict(unknown)} (expected {sorted(VALID_VERDICTS)}) — these are excluded from `correct` "
              f"but still count toward the denominator, deflating precision. Fix them.", file=sys.stderr)
    correct = sum(verdicts[v] for v in GOOD)
    astro = sum(verdicts[v] for v in ASTROLOGY)
    span_y = sum(1 for r in rows if _span_found(r))

    print(f"labeled edges: {n}\n")
    print(f"PRECISION (correct / labeled):        {correct/n:.2f}   <- exit gate is >= {PRECISION_GATE:.2f}")
    print(f"astrology rate (fabricated+vague):    {astro/n:.2f}   <- the grounding risk, measured")
    print(f"span-support rate (span_found=y):     {span_y/n:.2f}   <- the span-present check")
    return verdicts


def _report_verdict_breakdown(verdicts, n):
    """Print the per-verdict count breakdown."""
    print("\nverdict breakdown:")
    for v, c in verdicts.most_common():
        print(f"  {v:12} {c:4}  ({100*c/n:.0f}%)")


def _report_per_relation(rows):
    """Print precision per relation type for relations with enough labeled edges."""
    per_rel = defaultdict(lambda: [0, 0])
    has_relation = any("relation" in r for r in rows)
    for r in rows:
        ok = _is_correct(r)
        rel = r.get("relation") or "?"
        per_rel[rel][0] += ok
        per_rel[rel][1] += 1
    print(f"\nprecision per relation (n>={MIN_RELATION_N}):")
    if not has_relation:
        # don't present a single bogus "?" bucket as a per-relation breakdown when the sheet simply has
        # no 'relation' column — say so instead (review-nit).
        print("  (no 'relation' column in the sheet — per-relation breakdown unavailable)")
    else:
        for rel, (ok, tot) in sorted(per_rel.items(), key=lambda x: -x[1][1]):
            if tot >= MIN_RELATION_N:
                print(f"  {ok/tot:.2f}  ({ok}/{tot})  {rel}")


def _report_calibration(rows):
    """Print whether a numeric confidence_score (if present) predicts correctness."""
    scores_for_correct, scores_for_wrong = [], []
    for r in rows:
        try:
            score = float(r.get("confidence_score", ""))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(score):  # 'NaN'/'inf' parse to a float but would poison the calibration mean
            continue
        (scores_for_correct if _is_correct(r) else scores_for_wrong).append(score)
    if scores_for_correct and scores_for_wrong:
        mean_correct = sum(scores_for_correct)/len(scores_for_correct)
        mean_wrong = sum(scores_for_wrong)/len(scores_for_wrong)
        print("\nconfidence calibration (does the numeric confidence predict correctness?):")
        print(f"  mean confidence_score | correct edges:   {mean_correct:.2f}")
        print(f"  mean confidence_score | incorrect edges: {mean_wrong:.2f}")
        gap = mean_correct - mean_wrong
        calibration_msg = ("scores track correctness — the confidence means something"
                           if gap >= CALIBRATION_GAP else
                           "scores DON'T separate correct from wrong — confidence is vocabulary, not grounding")
        print(f"  gap: {gap:+.2f}  ->  {calibration_msg}")


def score(path):
    rows = _load_labeled_rows(path)
    if not rows:
        sys.exit("no labeled rows (fill the `verdict` column first)")

    n = len(rows)
    verdicts = _report_headline(rows, n)
    _report_verdict_breakdown(verdicts, n)
    _report_per_relation(rows)
    _report_calibration(rows)


def main(argv=None):
    # argparse subcommands (review-r5: this probe hand-rolled _flag_str/_flag_int while the sibling
    # CLIs used argparse — three idioms across the repo for the same job).
    ap = argparse.ArgumentParser(
        prog="f4_probe.py",
        description="Measure the extractor's precision on a non-self-grounding conceptual document "
                    "(see the module docstring for the verdict vocabulary).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("summary", help="graph shape + confidence/relation distributions")
    sp.add_argument("path", help="graph.json (node-link)")
    sp = sub.add_parser("sheet", help="sample edges into a labeling CSV")
    sp.add_argument("path", help="graph.json (node-link)")
    sp.add_argument("--n", type=int, default=80, help="edges to sample (default 80)")
    sp.add_argument("--out", default="labels.csv", help="output CSV path (default labels.csv)")
    sp.add_argument("--include-extracted", action="store_true",
                    help="include EXTRACTED (deterministic) edges in the pool")
    sp = sub.add_parser("fill", help="fill a sheet's verdict/span_found/notes from an annotator's JSON labels")
    sp.add_argument("path", help="labels.csv written by `sheet`")
    sp.add_argument("labels", help='JSON object {"<edge_id>": {"verdict", "span_found", "notes"}, ...}')
    sp = sub.add_parser("score", help="score a filled labels CSV")
    sp.add_argument("path", help="labels.csv with verdict/span_found filled")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "summary":
            summary(args.path)
        elif args.cmd == "sheet":
            sheet(args.path, args.n, args.out, include_extracted=args.include_extracted)
        elif args.cmd == "fill":
            fill(args.path, args.labels)
        else:
            score(args.path)
    except FileNotFoundError as e:
        sys.exit(f"file not found: {e.filename}")
    except (json.JSONDecodeError, csv.Error, UnicodeDecodeError) as e:
        # a present-but-corrupt graph.json/labels.csv must fail cleanly, not surface a raw traceback
        sys.exit(f"could not read '{args.path}': {e}")


if __name__ == "__main__":
    main()
