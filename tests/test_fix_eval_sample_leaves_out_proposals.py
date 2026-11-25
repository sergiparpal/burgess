"""0.25.2: `/kg-eval` Stage 4 samples the extraction, not the generator's proposals.

The end-to-end run of 2026-11-25 built the demo, grounded it, ran `/kg-generate all` and `/kg-perturb`, and then
`/kg-eval`. `f4_probe.py sheet` kept every edge whose confidence was not EXTRACTED, and a proposal carries
INFERRED like an extracted edge, so 17 of the 34 sampled edges were proposals still in the hypothesized lane. The
annotators marked 13 of them fabricated, and the precision read 0.47 while the extractor's own edges were 15 of 15
correct. `/kg-ground` judges proposals, and neither the pack nor the extractor prompt can change them, so in a
development checkout the command would have iterated on the extractor for nothing.

Now the sheet leaves out the edges whose provenance is `hypothesized`, says how many, and samples them only with
`--include-hypothesized`. A graph without proposals samples exactly as before (same pool, same seed).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import random
from pathlib import Path

import pytest

from kg_engine import harness

REPO = Path(__file__).resolve().parents[1]
_F4_PATH = REPO / "scripts" / "f4_probe.py"
EVAL = (REPO / "commands" / "kg-eval.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")


def _load_f4():
    spec = importlib.util.spec_from_file_location("kg_f4_probe_sample", _F4_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


f4 = _load_f4()

_NODES = [{"id": n, "label": n.title()} for n in ("a", "b", "c", "d", "e")]


def _edge(eid: str, confidence: str = "INFERRED", provenance: str = "span-present", state: str = "grounded") -> dict:
    src, rel, tgt = eid.split("__")
    return {"id": f"e_{src}__{rel}__{tgt}", "source": src, "target": tgt, "relation": rel,
            "confidence": confidence, "provenance": provenance, "epistemic_state": state,
            "source_file": "" if provenance == "hypothesized" else "source.md"}


_EXTRACTION = [_edge("a__grounds__b"), _edge("b__enables__c"), _edge("c__approximates__d", state="rejected")]
_PROPOSALS = [_edge("a__bridges__e", provenance="hypothesized", state="rejected"),
              _edge("d__collapses_into__e", provenance="hypothesized", state="unverified")]
_DETERMINISTIC = [_edge("e__projects__a", confidence="EXTRACTED", provenance="span-present")]


def _graph(tmp_path: Path, links: list[dict]) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": _NODES, "links": links}), encoding="utf-8")
    return path


def _ids(sheet: Path) -> list[str]:
    with open(sheet, encoding="utf-8", newline="") as f:
        return [r["edge_id"] for r in csv.DictReader(f)]


def test_the_sheet_leaves_out_proposals_and_says_how_many(tmp_path, capsys):
    graph = _graph(tmp_path, _EXTRACTION + _PROPOSALS + _DETERMINISTIC)
    out = tmp_path / "labels.csv"
    f4.sheet(str(graph), 80, str(out), include_extracted=False)
    assert sorted(_ids(out)) == sorted(e["id"] for e in _EXTRACTION)
    printed = capsys.readouterr().out
    assert "wrote 3 edges" in printed
    assert "left out 2 hypothesized proposals" in printed
    assert "/burgess:kg-generate" in printed and "/burgess:kg-perturb" in printed
    assert "--include-hypothesized" in printed


def test_include_hypothesized_samples_them_again(tmp_path, capsys):
    graph = _graph(tmp_path, _EXTRACTION + _PROPOSALS + _DETERMINISTIC)
    out = tmp_path / "labels.csv"
    f4.sheet(str(graph), 80, str(out), include_extracted=False, include_hypothesized=True)
    assert sorted(_ids(out)) == sorted(e["id"] for e in _EXTRACTION + _PROPOSALS)
    assert "left out" not in capsys.readouterr().out


def test_the_cli_flag_reaches_the_sheet(tmp_path):
    graph = _graph(tmp_path, _EXTRACTION + _PROPOSALS)
    plain, wide = tmp_path / "plain.csv", tmp_path / "wide.csv"
    f4.main(["sheet", str(graph), "--n", "80", "--out", str(plain)])
    f4.main(["sheet", str(graph), "--n", "80", "--out", str(wide), "--include-hypothesized"])
    assert len(_ids(plain)) == 3 and len(_ids(wide)) == 5


def test_a_graph_without_proposals_samples_exactly_as_before(tmp_path):
    """Same pool, same seed-42 shuffle, same first n: the fix filters before the shuffle, and filters nothing here."""
    links = [_edge(f"n{i}__grounds__m{i}") for i in range(30)] + _DETERMINISTIC
    graph = _graph(tmp_path, links)
    out = tmp_path / "labels.csv"
    f4.sheet(str(graph), 7, str(out), include_extracted=False)
    pool = [(i, e) for i, e in enumerate(links) if e["confidence"] != "EXTRACTED"]
    random.seed(42)
    random.shuffle(pool)
    assert _ids(out) == [e["id"] for _, e in pool[:7]]


def test_only_proposals_left_points_at_the_flag(tmp_path):
    graph = _graph(tmp_path, _PROPOSALS)
    with pytest.raises(SystemExit) as exc:
        f4.sheet(str(graph), 80, str(tmp_path / "labels.csv"), include_extracted=False)
    assert "--include-hypothesized" in str(exc.value)


def test_nothing_at_all_still_points_at_include_extracted(tmp_path):
    graph = _graph(tmp_path, _DETERMINISTIC)
    with pytest.raises(SystemExit) as exc:
        f4.sheet(str(graph), 80, str(tmp_path / "labels.csv"), include_extracted=False)
    assert "--include-extracted" in str(exc.value)


def test_summary_splits_the_judged_edges(tmp_path, capsys):
    f4.summary(str(_graph(tmp_path, _EXTRACTION + _PROPOSALS + _DETERMINISTIC)))
    printed = capsys.readouterr().out
    assert "judged edges (INFERRED+AMBIGUOUS): 5 / 6" in printed
    assert "hypothesized proposals among them: 2" in printed
    assert "extraction to sample: 3 <- the precision-relevant part" in printed


def test_the_writers_legend_names_both_generators_and_the_flag():
    assert "/burgess:kg-perturb" in harness._WRITER_LEGEND
    assert "--include-hypothesized" in harness._WRITER_LEGEND


def test_the_command_and_the_reference_say_so():
    assert "The sheet leaves out every proposal still in the hypothesized lane (0.25.2)" in EVAL
    assert "17 of 34 sampled edges were" in EVAL
    assert "without the hypothesized proposals" in EVAL           # Stage 7 draws the same sample
    assert "`--include-hypothesized`" in EVAL
    assert "--include-hypothesized" in TOOLS and "Since 0.25.2 it leaves out" in TOOLS
