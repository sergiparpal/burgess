"""Regression pins for the review-r9 fix batch (exhaustive codebase review).

Each test fails against the pre-fix code and passes after. Grouped by finding id (H*/M*/L* from the
review). The full suite was green before AND after, so these pin behaviour the suite did not exercise.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from kg_engine.canonmerge import merge_nodes
from kg_engine.divergence.diversity import bounded_quality, select_diverse
from kg_engine.harness import absorption, ideation
from kg_engine.model import Edge, EpistemicState, Node, node_from_markdown, node_to_markdown
from kg_engine.projector import DerivedReader, Projector
from kg_engine.server import _scrub_error_text
from kg_engine import dirlock, graphio

import networkx as nx


# ===========================================================================
# H1 — canonmerge is base-aware: a one-sided verdict survives, a two-sided one demotes
# ===========================================================================

def _node_with_edge(state: EpistemicState, verdict_by=None) -> Node:
    e = Edge(source="a", target="b", relation="rel", epistemic_state=state, verdict_by=verdict_by)
    return Node(id="a", label="a", edges=[e])


def test_h1_edge_one_sided_verdict_preserved():
    # ours grounded the edge; theirs left it at the base's unverified -> only OURS changed -> KEEP grounded
    # (+ its verdict_by). The pre-fix blind demote destroyed this legitimate one-sided verdict.
    base = _node_with_edge(EpistemicState.UNVERIFIED)
    ours = _node_with_edge(EpistemicState.GROUNDED, verdict_by="agent")
    theirs = _node_with_edge(EpistemicState.UNVERIFIED)
    merged, demotions = merge_nodes(base, ours, theirs)
    assert merged.edges[0].epistemic_state is EpistemicState.GROUNDED
    assert merged.edges[0].verdict_by == "agent"
    assert not demotions


def test_h1_edge_one_sided_failure_memory_preserved():
    # the §1.7 half: a one-sided `failed` (never-pruned negative memory) must also survive the merge.
    base = _node_with_edge(EpistemicState.UNVERIFIED)
    ours = _node_with_edge(EpistemicState.FAILED, verdict_by="agent")
    theirs = _node_with_edge(EpistemicState.UNVERIFIED)
    merged, _ = merge_nodes(base, ours, theirs)
    assert merged.edges[0].epistemic_state is EpistemicState.FAILED


def test_h1_edge_two_sided_conflict_demotes_and_clears_verdict():
    # both sides changed the base to DIFFERENT verdicts -> genuine conflict -> never forge -> unverified,
    # verdict fields cleared. (Forge-safety unchanged; the reconciler is still the backstop.)
    base = _node_with_edge(EpistemicState.UNVERIFIED)
    ours = _node_with_edge(EpistemicState.GROUNDED, verdict_by="agent")
    theirs = _node_with_edge(EpistemicState.FAILED, verdict_by="agent")
    merged, demotions = merge_nodes(base, ours, theirs)
    assert merged.edges[0].epistemic_state is EpistemicState.UNVERIFIED
    assert merged.edges[0].verdict_by is None
    assert demotions


def test_h1_no_base_demotes_for_safety():
    # no merge base (edge added on both sides at different states) -> can't tell one-sided from conflict
    # -> demote, the safe default.
    ours = _node_with_edge(EpistemicState.GROUNDED)
    theirs = _node_with_edge(EpistemicState.UNVERIFIED)
    merged, _ = merge_nodes(None, ours, theirs)
    assert merged.edges[0].epistemic_state is EpistemicState.UNVERIFIED


def test_h1_node_level_one_sided_verdict_preserved():
    base = Node(id="a", label="a", epistemic_state=EpistemicState.UNVERIFIED)
    ours = Node(id="a", label="a", epistemic_state=EpistemicState.GROUNDED)
    theirs = Node(id="a", label="a", epistemic_state=EpistemicState.UNVERIFIED)
    merged, _ = merge_nodes(base, ours, theirs)
    assert merged.epistemic_state is EpistemicState.GROUNDED


# ===========================================================================
# M1a — egress path scrubber redacts spaced / Windows paths without leaking the tail
# ===========================================================================

def test_m1a_spaced_windows_path_fully_redacted():
    out = _scrub_error_text(r"could not read C:\Users\John Smith\vault\notes.md now")
    for leak in ("John", "Smith", "vault", "notes.md"):
        assert leak not in out, f"leaked {leak!r}: {out!r}"
    assert "<path>" in out


def test_m1a_unc_path_redacted():
    out = _scrub_error_text(r"open \\fileserver\share\Secret Project\x.md failed")
    assert "fileserver" not in out and "Secret Project" not in out and "<path>" in out


def test_m1a_posix_spaced_dir_redacted():
    out = _scrub_error_text("open /home/john doe/secret/report.md failed")
    assert "john doe" not in out and "secret" not in out and "<path>" in out


def test_m1a_still_redacts_plain_paths_and_spares_prose():
    assert "<path>" in _scrub_error_text("at /home/alice/proj/index.sqlite")
    # a bare fraction/either-or in prose is NOT a path run and must not be over-redacted
    assert "<path>" not in _scrub_error_text("choose x and/or y")


# ===========================================================================
# M2 — line endings normalized at the parse chokepoint (CRLF corruption / CR-only vanish)
# ===========================================================================

def test_m2_crlf_body_normalized_on_parse():
    md = node_to_markdown(Node(id="n", label="N", body="Line one.\n\nLine two."))
    node = node_from_markdown(md.replace("\n", "\r\n"))  # a Windows-saved note
    assert "\r" not in node.body
    assert node.body == "Line one.\n\nLine two."


def test_m2_cr_only_note_still_parses():
    md = node_to_markdown(Node(id="n", label="N", body="body", epistemic_state=EpistemicState.FAILED))
    # pre-fix: the frontmatter regex needs \n, so a CR-only note raised and vanished from every read.
    node = node_from_markdown(md.replace("\n", "\r"))
    assert node.id == "n" and node.epistemic_state is EpistemicState.FAILED


# ===========================================================================
# M3 — a source-only edit marks the projection stale (advisories no longer freeze)
# ===========================================================================

def test_m3_source_only_edit_marks_projection_stale(engine, source_path: Path):
    engine.canon.write_nodes([Node(id="a", label="a")], message="seed")
    engine.projector.project()
    assert engine.projector.is_stale() is False
    # edit ONLY the source (canon untouched); a different length moves the cheap stat signature.
    source_path.write_text("A wholly different, and notably longer, source body than before.\n",
                           encoding="utf-8")
    assert engine.projector.is_stale() is True


# ===========================================================================
# M4 — harness ideation tolerates non-string outputs / source instead of crashing
# ===========================================================================

def test_m4_ideation_survives_non_string_outputs_and_source():
    res = ideation({"control": [1, 2, 3], "graph": ["a real idea about cats and boxes"]},
                   source_text=123)  # non-string elements + non-string source
    assert isinstance(res, dict) and "table" in res
    # the non-string control elements are dropped -> that arm scores as empty, not a traceback
    assert res["table"]["control"]["n"] == 0


# ===========================================================================
# M5 — non-finite quality no longer duplicates a candidate in the DPP slate
# ===========================================================================

def test_m5_nonfinite_quality_yields_distinct_indices():
    vecs = np.eye(6)
    for bad in (np.nan, np.inf, -np.inf):
        quality = np.array([1.0, 2.0, bad, 3.0, 4.0, 5.0])
        sel = select_diverse(vecs, 4, quality)
        assert len(set(sel)) == len(sel), f"duplicate index with {bad}: {sel}"


def test_m5_bounded_quality_sanitizes_non_finite():
    q = bounded_quality(np.array([1.0, np.inf, np.nan, 2.0]), weight=1.0)
    assert np.all(np.isfinite(q))


# ===========================================================================
# L9 — absorption does not divide by zero when absorb_growth <= 0
# ===========================================================================

def test_l9_absorption_no_zero_division_on_nonpositive_growth():
    G = nx.MultiDiGraph()
    G.add_edge("x", "y", key="e1")            # x has degree 1
    gd = graphio._node_link_data(G)
    # x was introduced already at degree 1 (growth == 0); absorb_growth<=0 hit the absorbed branch.
    out = absorption(gd, {"x": {"introduced_degree": 1, "introduced_at": 0}}, absorb_growth=0)
    assert out["x"]["status"] == "absorbed"
    assert out["x"]["half_life"] is None      # guarded instead of ZeroDivisionError


# ===========================================================================
# L10 — the query tokenizer is unicode-aware (non-Latin queries keep multi-word matching)
# ===========================================================================

def test_l10_query_tokenizer_extracts_cyrillic_terms():
    # two Cyrillic terms; the pre-fix ASCII-only class yielded ZERO terms -> a single whole-string match
    # that only found a verbatim substring. Since 0.11.5 the terms feed a ranked word match, not LIKE.
    assert DerivedReader._query_terms("привет мир") == ["привет", "мир"]


# ===========================================================================
# M6 / L5 — dirlock: info-less-window not stealable; unwritable FS fails cleanly
# ===========================================================================

def test_m6_fresh_infoless_lock_not_stealable(tmp_path: Path):
    lock = tmp_path / "lock"
    lock.mkdir()  # a just-mkdir'd lock, before try_acquire writes its `info` record
    assert dirlock.is_stealable(lock, 1800) is False  # grace protects the mid-acquire window


def test_m6_aged_infoless_orphan_is_stealable(tmp_path: Path):
    lock = tmp_path / "lock"
    lock.mkdir()
    old = time.time() - 30  # past the info-less grace, still within stale_secs
    os.utime(lock, (old, old))
    assert dirlock.is_stealable(lock, 1800) is True


def test_l5_try_acquire_clean_false_on_unwritable_parent(tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")     # a FILE where a parent dir is expected
    lock = blocker / "sub" / "lock"               # parent.mkdir() will raise a non-FileExistsError OSError
    assert dirlock.try_acquire(lock, 1800) is False  # clean False, not a raw traceback


# ===========================================================================
# H2 — bootstrap refuses to reclaim (rmtree) a FUNCTIONAL venv beside a stranded sentinel
# ===========================================================================

def test_h2_reclaim_spares_functional_venv(tmp_path, monkeypatch):
    from test_bootstrap import bootstrap, _install_ok  # sibling helpers (top-level import per repo gotcha)

    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "data" / ".venv"

    # A husk-shaped dir (populated, sibling owner sentinel, NO completion marker) — but this time the
    # interpreter is FUNCTIONAL (imports the core deps), i.e. a user's `uv sync` venv the stranded token
    # sits beside. It must NOT be rmtree'd.
    venv_dir.mkdir(parents=True)
    bootstrap._claim_owner_sentinel(venv_dir)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (venv_dir / "user_data.txt").write_text("precious", encoding="utf-8")  # tripwire: rmtree would delete it
    py = bootstrap.venv_python(venv_dir)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!stub\n", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_is_functional_venv", lambda vd: True)  # pretend the interpreter works
    _install_ok(monkeypatch)
    bootstrap.do_install(venv_dir)

    assert (venv_dir / "user_data.txt").read_text(encoding="utf-8") == "precious"  # survived (not reclaimed)
    assert (venv_dir / bootstrap.PTR_NAME).exists()  # adopted in place, sealed
