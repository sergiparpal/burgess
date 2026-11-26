#!/usr/bin/env python3
"""
f4_probe.py — measure the extractor's precision on a non-self-grounding conceptual document.

Turns the extractor's output graph.json (NetworkX node-link) into precision numbers by sampling
edges, labeling each against the source, and scoring. Also reports the astrology rate
(fabricated+vague), the span-support rate, precision per relation type, and — if edges carry a
numeric confidence — whether that confidence actually predicts correctness.

Since 0.28.0 /burgess:kg-eval runs these steps in the engine (`kg_eval`), because a shell step that names the
plugin's folder asks the person under `permissions.blockReadsOutsideWorkingDirectories`. This script is the
command line over the same functions (`kg_engine.evalsheet`), for development and CI: a sheet it writes is the
sheet `kg_eval` writes.

The sample is the extraction (0.25.2): `sheet` leaves out the proposals still in the hypothesized lane.
A /burgess:kg-generate or /burgess:kg-perturb proposal carries `INFERRED` like an extracted edge, so through
0.25.1 it was sampled as one; /burgess:kg-ground judges proposals, and neither the pack nor the extractor
prompt can change them. In an end-to-end run (2026-11-25) 17 of 34 sampled edges were proposals and the
precision read 0.47, while the extractor's own edges were 15 of 15 correct.

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
import sys

from kg_engine import evalsheet
from kg_engine.evalsheet import (  # noqa: F401 — re-exported: tests and older notes import them from here
    AMBIGUOUS, ASTROLOGY, CALIBRATION_GAP, EXTRACTED, FALSE_VALUES, FILL_REPORT_CAP, GOOD, HYPOTHESIZED,
    INFERRED, MIN_RELATION_N, PRECISION_GATE, SAMPLE_SEED, SHEET_COLS, TOP_RELATIONS, TRUE_VALUES,
    VALID_VERDICTS, SheetError, load,
)

_median = evalsheet.median
_verdict = evalsheet.verdict_of
_is_correct = evalsheet.is_correct
_span_found = evalsheet.span_found


def _print_counter(title, pairs, row=lambda k, v: f"  {k:12} {v}"):
    """Print a titled list of (key, count) rows; `row` formats each."""
    print(title)
    for k, v in pairs:
        print(row(k, v))


def summary(path):
    s = evalsheet.summarize(path)
    print(f"nodes: {s['nodes']}   edges: {s['edges']}\n")
    _print_counter("nodes by file_type:", s["nodes_by_file_type"])
    _print_counter("\nedges by confidence:", s["edges_by_confidence"])
    _print_counter(f"\ntop relations ({s['relations_distinct']} distinct):", s["top_relations"],
                   row=lambda k, v: f"  {v:4}  {k}")
    scores = s["inferred_confidence_score"]
    if scores:
        print(f"\nINFERRED confidence_score: n={scores['n']} "
              f"min={scores['min']:.2f} median={scores['median']:.2f} max={scores['max']:.2f}")
    print(f"\njudged edges (INFERRED+AMBIGUOUS): {s['judged']} / {s['edges']} "
          f"({100*s['judged']/max(s['edges'],1):.0f}%)")
    print(f"  hypothesized proposals among them: {s['hypothesized_proposals']} (the sheet leaves them out)")
    print(f"  extraction to sample: {s['extraction_to_sample']} <- the precision-relevant part")


def sheet(path, n, out, include_extracted, include_hypothesized=False):
    try:
        rows, left_out = evalsheet.draw(path, n, include_extracted, include_hypothesized)
    except SheetError as e:
        sys.exit(str(e))
    evalsheet.write_sheet(rows, out)
    print(f"wrote {len(rows)} edges to {out}")
    if left_out:
        print(f"left out {left_out} hypothesized proposals (/burgess:kg-generate, /burgess:kg-perturb): "
              "/burgess:kg-ground judges them, and they are not extraction (--include-hypothesized samples them)")
    print("label every row (verdict: correct|fabricated|vague|wrong_type, span_found: y|n) in a JSON file, then:")
    print(f"  python f4_probe.py fill {out} <labels.json>")
    print(f"  python f4_probe.py score {out}")


def fill(path, labels_path):
    """Fill the sheet's `verdict`, `span_found` and `notes` from an annotator's labels file (0.11.7); see
    `kg_engine.evalsheet.fill`. A labels file that does not label the sheet row for row exits with the
    problems and leaves the sheet unchanged."""
    try:
        res = evalsheet.fill(path, labels_path)
    except SheetError as e:
        sys.exit(str(e))
    print(f"filled {res['filled']} rows of {path} from {labels_path}: "
          + ", ".join(f"{v} {c}" for v, c in res["counts"]))


def score(path):
    try:
        res = evalsheet.score_rows(evalsheet.labeled_rows(path))
    except SheetError as e:
        sys.exit(str(e))
    n = res["labeled"]
    unknown = res["unknown_verdicts"]
    if unknown:
        print(f"WARNING: {sum(unknown.values())} row(s) carry an unrecognized verdict "
              f"{dict(unknown)} (expected {sorted(VALID_VERDICTS)}) — these are excluded from `correct` "
              f"but still count toward the denominator, deflating precision. Fix them.", file=sys.stderr)
    print(f"labeled edges: {n}\n")
    print(f"PRECISION (correct / labeled):        {res['precision']:.2f}   <- exit gate is >= {PRECISION_GATE:.2f}")
    print(f"astrology rate (fabricated+vague):    {res['astrology_rate']:.2f}   <- the grounding risk, measured")
    print(f"span-support rate (span_found=y):     {res['span_support_rate']:.2f}   <- the span-present check")
    print("\nverdict breakdown:")
    for v, c in res["verdicts"]:
        print(f"  {v:12} {c:4}  ({100*c/n:.0f}%)")
    print(f"\nprecision per relation (n>={MIN_RELATION_N}):")
    if res["per_relation"] is None:
        # don't present a single bogus "?" bucket as a per-relation breakdown when the sheet simply has
        # no 'relation' column — say so instead (review-nit).
        print("  (no 'relation' column in the sheet — per-relation breakdown unavailable)")
    else:
        for r in res["per_relation"]:
            print(f"  {r['precision']:.2f}  ({r['correct']}/{r['labeled']})  {r['relation']}")
    cal = res["calibration"]
    if cal:
        print("\nconfidence calibration (does the numeric confidence predict correctness?):")
        print(f"  mean confidence_score | correct edges:   {cal['mean_correct']:.2f}")
        print(f"  mean confidence_score | incorrect edges: {cal['mean_wrong']:.2f}")
        calibration_msg = ("scores track correctness — the confidence means something"
                           if cal["tracks"] else
                           "scores DON'T separate correct from wrong — confidence is vocabulary, not grounding")
        print(f"  gap: {cal['gap']:+.2f}  ->  {calibration_msg}")


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
    sp.add_argument("--n", type=int, default=evalsheet.SAMPLE_SIZE, help="edges to sample (default 80)")
    sp.add_argument("--out", default="labels.csv", help="output CSV path (default labels.csv)")
    sp.add_argument("--include-extracted", action="store_true",
                    help="include EXTRACTED (deterministic) edges in the pool")
    sp.add_argument("--include-hypothesized", action="store_true",
                    help="include proposals still in the hypothesized lane (left out since 0.25.2)")
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
            sheet(args.path, args.n, args.out, include_extracted=args.include_extracted,
                  include_hypothesized=args.include_hypothesized)
        elif args.cmd == "fill":
            fill(args.path, args.labels)
        else:
            score(args.path)
    except FileNotFoundError as e:
        sys.exit(f"file not found: {e.filename}")
    except (json.JSONDecodeError, csv.Error, UnicodeDecodeError, SheetError) as e:
        # a present-but-corrupt graph.json/labels.csv must fail cleanly, not surface a raw traceback
        sys.exit(f"could not read '{args.path}': {e}")


if __name__ == "__main__":
    main()
