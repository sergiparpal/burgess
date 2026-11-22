"""The R3-MIRROR "re-examinable verdicts" advisory (non-monotonic evidence).

A grounding verdict is permanent negative memory: once an item is `failed` (actively falsified) or
`rejected` (unsupported), the grounder never revisits it (its queue is `unverified`-only). R3 flags the
one-directional case (a grounded/failed SPAN-PRESENT edge whose span DISAPPEARED). This advisory mirrors
R3 for the opposite, equally real case: a `failed`/`rejected` item — NODES and SPAN-LESS items included,
which R3 cannot cover — was judged against a source set that has since CHANGED, so new evidence may make
it supportable. It is READ-ONLY: it never mutates a verdict and never re-queues anything; re-grounding
stays an explicit `kg_ground` decision. A term-overlap filter keeps only items the changed source bears on.
"""
from __future__ import annotations

import os
from pathlib import Path

from kg_engine.export import build_report
from kg_engine.model import EpistemicState, Node, edge_id
from kg_engine.server import KGEngine

_PACK = Path(__file__).resolve().parents[1] / "pack" / "pack.yaml"


def _engine(vault, source_path):
    return KGEngine(vault, source_path=source_path, pack_path=_PACK)


def _rewrite(path: Path, text: str) -> None:
    """Rewrite a source file AND push its mtime forward, so the SourceSet (signature-cached on mtime) is
    guaranteed to re-resolve even within the same filesystem mtime tick (mirrors test_projector)."""
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 100))


def _reexaminable(eng) -> list:
    return eng.projector.kg_context()["advisory"]["reexaminable_verdicts"]


def _reexaminable_ids(eng) -> set:
    return {r["item_id"] for r in _reexaminable(eng)}


def _seed_node(eng, nid: str, label: str) -> None:
    eng.canon.write_nodes([Node(id=nid, label=label, node_type="claim")], message=f"seed {nid}")


# --------------------------------------------------------------------------- coverage R3 lacks


def test_failed_span_less_node_flagged_on_source_change(vault, tmp_path):
    """The exact gap R3 cannot see: a span-less NODE (nodes have no span field) grounded `failed`. It is
    flagged only AFTER the source set changes to something that mentions it."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.projector.project()
    assert _reexaminable_ids(eng) == set()   # source unchanged since judged -> no flag yet

    _rewrite(src, "New findings: photosynthesis converts light into chemical energy.\n")
    eng.projector.project()
    assert _reexaminable(eng) == [{"item_id": "photosynthesis", "kind": "node", "state": "failed",
                                   "reason": "source-set-changed-since-judged",
                                   "files": ["s.md"]}]   # 0.22.3: the changed file that raised the flag


def test_rejected_span_less_edge_and_node_flagged_on_source_change(vault, tmp_path):
    """Node + edge AND `rejected` coverage: a span-less REJECTED edge (R3 only checks span-present edges)
    and a `rejected` node are both surfaced on a source change that mentions them."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    # a span-less hypothesized edge, grounded rejected (unsupported — the expected state of a novel idea).
    # `grounds` is a declared pack relation; the point is that the edge carries NO span, which R3 ignores.
    eng.kg_propose({"edges": [{"source": "photosynthesis", "target": "oxygen",
                               "relation": "grounds"}]})
    eid = edge_id("photosynthesis", "grounds", "oxygen")
    eng.kg_ground(eid, "rejected")
    # a rejected node
    _seed_node(eng, "mitochondria", "Mitochondria")
    eng.kg_ground("mitochondria", "rejected", kind="node")
    eng.projector.project()
    assert _reexaminable_ids(eng) == set()

    _rewrite(src, "Photosynthesis grounds the release of oxygen; the mitochondria makes energy.\n")
    eng.projector.project()
    by_id = {r["item_id"]: r for r in _reexaminable(eng)}
    assert set(by_id) == {eid, "mitochondria"}
    assert by_id[eid]["kind"] == "edge" and by_id[eid]["state"] == "rejected"
    assert by_id["mitochondria"]["kind"] == "node" and by_id["mitochondria"]["state"] == "rejected"


# --------------------------------------------------------------------------- self-clearing / gating


def test_reexaminable_clears_on_reground(vault, tmp_path):
    """Self-clearing (mirrors R3): once the item is re-grounded OUT of {failed, rejected}, the next
    (canon-only) projection's refilter drops the flag."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.projector.project()
    _rewrite(src, "Photosynthesis converts light to energy.\n")
    eng.projector.project()
    assert _reexaminable_ids(eng) == {"photosynthesis"}

    # re-ground it out of {failed, rejected}; the next projection (source unchanged) self-clears it
    eng.kg_ground("photosynthesis", "grounded", kind="node", support_note="the source now supports it")
    eng.projector.project()
    assert _reexaminable_ids(eng) == set()


def test_no_reexaminable_when_source_unchanged(vault, tmp_path):
    """A `failed` verdict under an UNCHANGED source raises no flag — the item was judged against the
    current corpus, so there is nothing to re-examine (no NEW flags on a canon-only change)."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.projector.project()
    eng.kg_ground("photosynthesis", "failed", kind="node")   # canon change, source unchanged
    eng.projector.project()
    assert _reexaminable_ids(eng) == set()


def test_no_reexaminable_without_source(vault):
    """No source configured -> the advisory is empty (mirror R3: no divergence without a source)."""
    eng = _engine(vault, None)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.projector.project()
    assert eng.projector.kg_context()["advisory"]["reexaminable_verdicts"] == []


def test_advisory_never_mutates_verdict_or_grounder_queue(vault, tmp_path):
    """READ-ONLY guarantee: after any projection the verdict is unchanged AND the item is NOT enqueued
    for grounding (the grounder's queue is `unverified`-only)."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.projector.project()
    _rewrite(src, "Photosynthesis converts light to energy.\n")
    eng.projector.project()
    assert _reexaminable_ids(eng) == {"photosynthesis"}

    node = eng.canon.read_node("photosynthesis")
    assert node.epistemic_state == EpistemicState.FAILED          # verdict untouched
    unverified = {n["id"] for n in eng.projector.query_graph(epistemic_state="unverified")["nodes"]}
    assert "photosynthesis" not in unverified                     # never auto-re-queued


# --------------------------------------------------------------------------- Stage 6: term-overlap filter


def test_reexaminable_filtered_by_term_overlap(vault, tmp_path):
    """The changed source flags ONLY the failed items it actually mentions — an item whose terms are
    absent from the changed text is filtered out (noise control)."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    _seed_node(eng, "photosynthesis", "Photosynthesis in plants")
    _seed_node(eng, "quantum-entanglement", "Quantum entanglement of particles")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.kg_ground("quantum-entanglement", "failed", kind="node")
    eng.projector.project()

    # the changed source mentions ONLY photosynthesis
    _rewrite(src, "Photosynthesis converts light into chemical energy in plants.\n")
    eng.projector.project()
    assert _reexaminable_ids(eng) == {"photosynthesis"}   # quantum node's terms absent -> not flagged


# --------------------------------------------------------------------------- carry-forward / surfacing


def test_flag_carried_forward_across_unrelated_source_change(vault, tmp_path):
    """A flag raised by one source change is not silently dropped by a LATER, unrelated source change
    that does not mention the item — it persists until the item is re-grounded."""
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.md").write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, d)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.projector.project()

    _rewrite(d / "a.md", "Photosynthesis converts light to energy.\n")   # change 1: mentions it -> flag
    eng.projector.project()
    assert _reexaminable_ids(eng) == {"photosynthesis"}

    # change 2: add an UNRELATED source file (no photosynthesis) -> the earlier flag is carried forward
    (d / "b.md").write_text("Tectonic plates drift across geological epochs.\n", encoding="utf-8")
    eng.projector.project()
    assert _reexaminable_ids(eng) == {"photosynthesis"}


def test_report_lists_reexaminable_verdicts(vault, tmp_path):
    """The GRAPH_REPORT renders the R3-mirror section, parallel to the R3 stale-verdicts section."""
    src = tmp_path / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = _engine(vault, src)
    _seed_node(eng, "photosynthesis", "Photosynthesis")
    eng.kg_ground("photosynthesis", "failed", kind="node")
    eng.projector.project()
    _rewrite(src, "Photosynthesis converts light to energy.\n")
    eng.projector.project()

    md = build_report(eng).read_text(encoding="utf-8")
    assert "## Re-examinable verdicts (R3-mirror" in md
    assert "photosynthesis" in md
