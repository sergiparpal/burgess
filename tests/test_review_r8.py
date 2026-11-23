"""Regression pins for the 2026-07-05 exhaustive review round (review-r8).

Each test corresponds to one verified finding and FAILS against the pre-fix code (every fix is
mutation-catching). Findings keep the review's numbering; grep `review-r8-N` in the engine for the
per-fix rationale.

  1  server.kg_rename dropped a grounding verdict when the endpoint rewrite collapsed two edges onto
     one canonical id (no dedup, unlike kg_merge) — the {e.id: e} collapse kept the wrong one.
  2  A kg_propose re-proposal of an already-grounded edge deduped-and-accepted (CORRECT — grounded
     structure must not block generation; only FAILURE_STATES bind it) but the canon merge dropped its
     source_file / confidence / confidence_score / authored_by.
  3  node_content_hash hashed the raw body while the disk round-trip strips leading/trailing newlines,
     so a trailing-\\n body defeated canon's idempotent-no-op write guard (churn on every re-run).
  4  groundaudit.audited_write raised a spurious OrphanAuditError on an empty-records rollback when the
     audit log did not exist yet (nothing appended → no orphan can exist).
  5  The re-examinable-verdicts term filter read incremental-parse shells (no body/notes), so a
     body-only distinguishing term never re-surfaced a falsified item.
  6  _unseal_discards un-sealed ANY named cid — a genuine user discard, unknown id, or still-valid
     failure — instead of only the currently re-examinable set; a bare-string reexamine iterated chars.
  7  The backend scrubbed only the section body, egressing the raw heading (PII/secret) to the API.
  8  A leading UTF-8 BOM stopped the first `## heading` matching, folding the first section into the
     preamble.
  10 A cross-owner edge_id collision resolved by node iteration order, so full vs incremental
     projection disagreed on which edge survived.
  12 A renamed (identical-content) source file was mistaken for newly-added evidence.
  13 The overlap tokenizer was ASCII-only, so the whole advisory went silent on a non-Latin source.
  16 _payload_receipt omitted file_type, so a file_type-only change replayed as an idempotent no-op.
  17 harness.absorption crashed on a non-dict history instead of degrading.
  18 harness._score_condition mis-scored a bare-string condition value character-by-character.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine import harness
from kg_engine.groundaudit import GroundAuditLog, OrphanAuditError
from kg_engine.model import (
    Confidence,
    Edge,
    EpistemicState,
    Node,
    Provenance,
    edge_id,
    node_content_hash,
    node_from_markdown,
    node_to_markdown,
)
from kg_engine.projector import Projector
from kg_engine.server import KGEngine
from kg_engine.sources import split_sections

PACK = Path(__file__).resolve().parents[1] / "pack" / "pack.yaml"


# --------------------------------------------------------------------------- #1 kg_rename
def test_r8_1_rename_dedup_preserves_grounded_verdict(vault):
    """A rename whose endpoint rewrite collapses two of a node's edges onto one canonical id must
    coalesce them (negative-info-sticky, verdict-preserving), not persist a duplicate id whose
    downstream {e.id: e} collapse silently drops the grounded edge."""
    eng = KGEngine(vault)
    grounded = Edge(source="cat", target="dog", relation="relates", span="a verbatim span here",
                    provenance=Provenance.SPAN_PRESENT, epistemic_state=EpistemicState.GROUNDED,
                    verdict_by="agent", verdict_at="2020-01-01T00:00:00+00:00")
    dangling = Edge(source="cat", target="feline", relation="relates")  # unverified, pre-existing
    eng.canon.write_one(Node(id="cat", label="cat", edges=[grounded, dangling]))
    eng.canon.write_one(Node(id="dog", label="dog"))

    assert eng.kg_rename("dog", "feline")["ok"]

    edges = eng.canon.read_node("cat").edges
    ids = [e.id for e in edges]
    assert len(ids) == len(set(ids)), f"duplicate canonical edge id persisted: {ids}"
    survivor = {e.id: e for e in edges}[edge_id("cat", "relates", "feline")]
    assert survivor.epistemic_state == EpistemicState.GROUNDED  # the verdict survived the rename
    assert survivor.span == "a verbatim span here"


def test_r8_1_rename_preserves_grounded_self_loop(vault):
    """The rename dedup must NOT drop self-loops (unlike kg_merge): a pre-rename `old→old` self
    relation legitimately becomes `new→new` and must keep its verdict."""
    eng = KGEngine(vault)
    self_edge = Edge(source="old", target="old", relation="relates", span="verbatim self span",
                     provenance=Provenance.SPAN_PRESENT, epistemic_state=EpistemicState.GROUNDED,
                     verdict_by="agent", verdict_at="2020-01-01T00:00:00+00:00")
    eng.canon.write_one(Node(id="old", label="old", edges=[self_edge]))

    assert eng.kg_rename("old", "new")["ok"]

    edges = eng.canon.read_node("new").edges
    assert len(edges) == 1
    assert edges[0].source == edges[0].target == "new"
    assert edges[0].epistemic_state == EpistemicState.GROUNDED


# --------------------------------------------------------------------------- #2 propose merge metadata
def test_r8_2_propose_regrounded_preserves_provenance_metadata(vault):
    """Re-proposing an already-grounded edge through the hypothesized lane deduplicates (grounded
    structure does NOT bind generation — only FAILURE_STATES do), and the canon merge must preserve
    the grounded edge's full evidence, not just its state/span."""
    src = vault / "source.md"
    src.write_text("heat flows from hot to cold and grounds the arrow of time.\n", encoding="utf-8")
    eng = KGEngine(vault, source_path=src)
    e = Edge(source="heat", target="cold", relation="flows_to", span="heat flows from hot to cold",
             provenance=Provenance.SPAN_PRESENT, epistemic_state=EpistemicState.GROUNDED,
             source_file="source.md", confidence=Confidence.EXTRACTED, confidence_score=0.9,
             verdict_by="agent", verdict_at="2020-01-01T00:00:00+00:00", notes="grounded note")
    eng.canon.write_one(Node(id="heat", label="heat", edges=[e]))

    out = eng.kg_propose({"edges": [{"source": "heat", "target": "cold", "relation": "flows_to"}]})
    # grounded structure is deduped, NOT quarantined (respects "only FAILURE_STATES bind generation")
    assert out["dispositions"]["QUARANTINED"] == 0
    assert out["dispositions"]["ACCEPTED"] == 1

    after = eng.canon.read_node("heat").edges[0]
    assert after.epistemic_state == EpistemicState.GROUNDED
    assert after.span == "heat flows from hot to cold"
    assert after.source_file == "source.md"           # <- dropped pre-fix
    assert after.confidence == Confidence.EXTRACTED    # <- dropped pre-fix
    assert after.confidence_score == 0.9               # <- dropped pre-fix


# --------------------------------------------------------------------------- #3 node_content_hash
def test_r8_3_node_content_hash_ignores_body_edge_newlines():
    """A body carrying a trailing newline (normal LLM JSON output) must hash identically to its own
    disk round-trip, or canon's idempotent-no-op guard never skips and every re-run rewrites."""
    n = Node(id="x", label="X", body="paragraph text\n")
    round_tripped = node_from_markdown(node_to_markdown(n), fallback_id="x")
    assert node_content_hash(n) == node_content_hash(round_tripped)
    # a REAL body change still moves the hash
    assert node_content_hash(Node(id="x", label="X", body="different")) != node_content_hash(n)


# --------------------------------------------------------------------------- #4 groundaudit
def test_r8_4_empty_records_rollback_returns_clean(tmp_path):
    """An empty-records rollback against a not-yet-created log must return the clean payload, never a
    spurious OrphanAuditError (nothing was appended, so there is no orphan to truncate)."""
    log = GroundAuditLog(tmp_path / "audit.jsonl")
    payload = {"ok": False, "error": "rename rolled back: real reason"}
    assert log.audited_write([], lambda: (False, payload)) == payload
    assert not (tmp_path / "audit.jsonl").exists()


def test_r8_4_real_orphan_still_raises(tmp_path):
    """The narrowing must not weaken the real guarantee: a genuine un-truncatable orphan (records
    appended, truncate fails) still raises OrphanAuditError."""
    log = GroundAuditLog(tmp_path / "audit.jsonl")
    log.truncate = lambda offset: False  # simulate an un-truncatable log
    with pytest.raises(OrphanAuditError):
        log.audited_write([("k", "unverified", "grounded", "agent")], lambda: (False, None))


# --------------------------------------------------------------------------- #5 reexaminable body terms
def _reex_ids(eng) -> set:
    return {r["item_id"] for r in eng.projector.kg_context()["advisory"]["reexaminable_verdicts"]}


def _bump(path: Path, text: str) -> None:
    import os
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 100))


def test_r8_5_reexaminable_filter_counts_body_terms(vault):
    """A source change that mentions a failed item's BODY term (not its label) must re-surface it: the
    filter re-reads the full note from canon, not the body-less incremental shell."""
    src = vault / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = KGEngine(vault, source_path=src, pack_path=PACK)
    eng.canon.write_nodes([Node(id="n1", label="Model organism", node_type="claim",
                                body="The zebrafish is a widely used vertebrate model organism.")],
                          message="seed n1")
    eng.kg_ground("n1", "failed", kind="node")
    eng.projector.project()
    assert _reex_ids(eng) == set()

    # body-only terms; since 0.24.5 a paragraph must share three of the claim's words (two from 0.22.4,
    # tests/test_fix_reexamine_needs_three_words.py), so it names three of the body's
    _bump(src, "New study: the zebrafish genome of this widely studied vertebrate has been sequenced.\n")
    eng.projector.project()
    assert "n1" in _reex_ids(eng)  # <- empty pre-fix (shell had no body)


# --------------------------------------------------------------------------- #6 unseal validation
def test_r8_6_unseal_ignores_non_reexaminable_discard(vault):
    """The explicit un-seal lever must ignore a cid that is not currently re-examinable — a genuine
    user discard is never revived, and the return list reports only what was actually un-sealed."""
    from kg_engine.divergence import pipeline as dpipe
    from kg_engine.divergence.state import State

    src = vault / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = KGEngine(vault, source_path=src, pack_path=PACK)
    home = Path(eng.project_dir) / ".kg" / "diverge"
    dpipe.init_project("brief", str(PACK.parent / "domains" / "generic.yaml"),
                       home=home, session="s1", seed=5)
    st = State("brief", home=home)
    st.write_discards("generic", ["user-hated"])  # a deliberate user discard, never materialized/failed

    assert eng._unseal_discards("brief", ["user-hated"]) == []          # nothing un-sealed
    assert "user-hated" in State("brief", home=home).read_discards("generic")  # stays sealed


def test_r8_6_unseal_bare_string_does_not_iterate_chars(vault):
    """A bare-string reexamine must be treated as one cid, not iterated character-by-character."""
    src = vault / "s.md"
    src.write_text("Heat flows from hot to cold.\n", encoding="utf-8")
    eng = KGEngine(vault, source_path=src, pack_path=PACK)
    from kg_engine.divergence import pipeline as dpipe
    dpipe.init_project("brief", str(PACK.parent / "domains" / "generic.yaml"),
                       home=Path(eng.project_dir) / ".kg" / "diverge", session="s1", seed=5)
    # "c1" must not un-seal the chars "c" and "1"; neither exists / is re-examinable, so result is empty.
    assert eng._unseal_discards("brief", "c1") == []


# --------------------------------------------------------------------------- #7 backend title scrub
def test_r8_7_backend_scrubs_section_title(vault):
    """The backend must scrub the section TITLE before it reaches the API prompt, not only the body —
    a heading carrying PII/a secret would otherwise egress verbatim."""
    from test_backend import _FakeClient  # sibling test module (pytest puts tests/ on sys.path)

    src = vault / "source.md"
    src.write_text("## Notes from jane@example.com\nHeat flows from hot to cold.\n", encoding="utf-8")
    eng = KGEngine(vault, source_path=src, pack_path=PACK)
    fake = _FakeClient([{"nodes": [], "edges": []}])
    eng2_extractor = _BackendExtractor(eng, client=fake)
    eng2_extractor.run()

    prompt = fake.messages.calls[0]["messages"][0]["content"]
    assert "jane@example.com" not in prompt          # raw PII must not egress
    assert "⟦EMAIL:1⟧" in prompt            # the scrubbed placeholder is what the model sees


# --------------------------------------------------------------------------- #8 BOM section split
def test_r8_8_bom_does_not_swallow_first_heading():
    """A leading UTF-8 BOM must not stop the first `## heading` from being recognised as a section."""
    secs = split_sections("﻿## Overview\nbody text", include_heading=True)
    assert secs[0][0] == "Overview"  # <- was "" (folded into the preamble) pre-fix


# --------------------------------------------------------------------------- #10 cross-owner determinism
def test_r8_10_cross_owner_edge_resolves_natural_owner_deterministically():
    """When two notes declare the same edge_id under different owners, the NATURAL owner (owner ==
    source) wins deterministically, independent of node iteration order — so full and incremental
    projections agree."""
    natural = Node(id="a", label="a",
                   edges=[Edge(source="a", target="b", relation="relates", span="s1")])
    foreign = Node(id="b", label="b",  # a hand-edited foreign-source edge duplicating a's natural one
                   edges=[Edge(source="a", target="b", relation="relates", span="s2")])
    eid = edge_id("a", "relates", "b")
    for order in ([natural, foreign], [foreign, natural]):
        resolved = {e.id: owner for e, owner in Projector._canonical_edges(order)}
        assert resolved[eid] == "a"  # natural owner wins regardless of order


# --------------------------------------------------------------------------- #12 renamed source
def test_r8_12_renamed_identical_source_is_not_flagged_as_changed():
    """A source file renamed with identical bytes must NOT read as newly-added evidence."""
    from types import SimpleNamespace
    prior = {"source_file_sigs": {"old.md": Projector._source_file_sigs(
        SimpleNamespace(texts={"old.md": "identical content"}))["old.md"]}}
    renamed = SimpleNamespace(texts={"new.md": "identical content"})  # same bytes, new basename
    assert Projector._changed_source_text(None, renamed, prior) == ""
    # a genuinely new file IS flagged
    added = SimpleNamespace(texts={"new.md": "brand new evidence text"})
    assert "brand new evidence text" in Projector._changed_source_text(None, added, prior)


# --------------------------------------------------------------------------- #13 unicode terms
def test_r8_13_overlap_terms_are_unicode_aware():
    """The term tokenizer must not silently drop a non-Latin-script source (recall gap)."""
    assert Projector._content_terms("механизм модель") == {"механизм", "модель"}
    # ASCII behavior is unchanged: >=3 chars, underscore splits, 2-char excluded
    assert Projector._content_terms("foo_bar ab abc") == {"foo", "bar", "abc"}


# --------------------------------------------------------------------------- #16 receipt file_type
def test_r8_16_receipt_distinguishes_file_type():
    """A payload differing only in a node's file_type must yield a DIFFERENT idempotency receipt, or a
    file_type-only change replays as a no-op."""
    a = KGEngine._payload_receipt({"nodes": [{"id": "x", "file_type": "prose"}]})
    b = KGEngine._payload_receipt({"nodes": [{"id": "x", "file_type": "code"}]})
    assert a != b


# --------------------------------------------------------------------------- #17 / #18 harness guards
def test_r8_17_absorption_tolerates_non_dict_history():
    """A non-dict history (e.g. a hand-corrupted generations.json shaped {"tracked": [...]}) degrades
    to no records instead of crashing on `.items()`."""
    empty_graph = {"directed": True, "multigraph": True, "graph": {}, "nodes": [], "links": []}
    assert harness.absorption(empty_graph, ["not", "a", "dict"]) == {}


def test_r8_18_score_condition_rejects_non_list_value():
    """A bare-string condition value is treated as ONE idea (n == 1), not iterated character-by-
    character (which scored n == len(string))."""
    assert harness._score_condition("an idea string", "source text")["n"] == 1
    assert harness._score_condition(["idea one", "idea two"], "source text")["n"] == 2


# BackendExtractor is imported lazily so a missing `backend` extra doesn't break collection of the
# rest of this module (mirrors test_backend.py, which imports it at top only because that whole file
# is about the backend).
from kg_engine.backend import BackendExtractor as _BackendExtractor  # noqa: E402
