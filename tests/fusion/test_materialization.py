"""Stage 4 — pin materialization + unified negative memory (FUSION_PLAN §11).

Materialization is the ONLY way divergence output enters the graph, and it goes
through the front door (kg_propose -> kg_write -> boundary) exclusively. The
adversarial suite attacks that path directly; verdict neutrality proves a pin
never changes a grounding outcome; the I8 tests prove the unified negative
memory is consulted by BOTH generation paths; the e2e runs the whole fused loop.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from kg_engine.model import EpistemicState, Provenance, edge_id
from kg_engine.reconciler import Reconciler
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "pack" / "pack.yaml"

SOURCE = """\
Entropy grounds the arrow of time. Heat flows from hot to cold.
A compression stands in for many observations and grounds the claims beneath it.
Degree approximates importance. A failed claim defends against re-proposal.
"""


class FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A project WITH a source (the e2e adds grounding), engine + registered tools,
    plus a scripted diverge session with one ingested round and two pins."""
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    monkeypatch.delenv("KG_PACK_PATH", raising=False)

    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    src = tmp_path / "source.md"
    src.write_text(SOURCE, encoding="utf-8")

    engine = KGEngine(proj, source_path=src, pack_path=PACK)
    mcp = FakeMCP()
    _register(mcp, engine)
    t = mcp.tools

    t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    cands = [
        {"id": f"c{i}", "text": f"idea {i}: concept about topic {i} via approach {i}",
         "descriptor": {"angle": f"a{i}", "scope": "broad", "form": f"f{i % 2}",
                        "boldness": (i % 5) / 4.0, "mechanism": f"mechanism {i}"},
         "genealogy": {"operator_id": "analogy", "parents": []}}
        for i in range(6)
    ]
    r = t["kg_diverge_ingest"](project="brief", candidates=cands, axes="generic", seed=5)
    assert r["slate"]
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "c0"})
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "c1"})
    return engine, t, proj


def _node_id(project: str, cid: str) -> str:
    return f"idea-{project}-{cid}"


def test_materialize_pins_land_hypothesized_with_lineage(rig):
    engine, t, proj = rig
    out = t["kg_diverge_materialize"](project="brief")
    assert out["ok"] and out["materialized"] == 2, out["results"]

    node = engine.canon.read_node(_node_id("brief", "c0"))
    assert node.provenance is Provenance.HYPOTHESIZED          # the lane, forced
    assert node.epistemic_state is EpistemicState.UNVERIFIED   # never a verdict
    assert "[diverge] pinned candidate=c0 brief=brief session=s1" in node.body
    assert "mechanism 0" in node.body and "operator=analogy" in node.body

    from kg_engine.divergence.state import State
    ledger = State("brief", home=proj / ".kg" / "diverge").read_materialized()
    assert ledger["c0"]["nodes"] == [_node_id("brief", "c0")]


def test_materialize_refuses_unpinned_and_skips_stale(rig):
    engine, t, _ = rig
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=["c5", "c0"])
    by = {r["candidate"]: r for r in out["results"]}
    assert by["c5"]["status"] == "refused" and "not-pinned" in by["c5"]["reason"]
    assert by["c0"]["status"] in ("ACCEPTED", "DEMOTED")

    # a pin whose session record is gone (I10 wiped it) is skipped with guidance
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "ghost"})
    out2 = t["kg_diverge_materialize"](project="brief", candidate_ids=["ghost"])
    (res,) = out2["results"]
    assert res["status"] == "skipped" and "no-session-record" in res["reason"]


def test_adversarial_forged_verdict_via_materialize_edges_is_stripped(rig):
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief", candidate_ids=["c0", "c1"])
    a, b = _node_id("brief", "c0"), _node_id("brief", "c1")
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=[],
                                      edges=[{"source": a, "target": b, "relation": "bridges",
                                              "epistemic_state": "grounded",
                                              "candidate_id": "c0"}])
    details = out["propose"]["details"]
    d = next(d for d in details if d["kind"] == "edge")
    assert d["disposition"] == "DEMOTED" and "forged-verdict-stripped" in d["reason"]
    node = engine.canon.read_node(a)
    e = next(e for e in node.edges if e.id == d["id"])
    assert e.epistemic_state is EpistemicState.UNVERIFIED
    assert e.provenance is Provenance.HYPOTHESIZED and e.span == ""  # I2: no span-less grounded


def test_adversarial_text_claim_via_materialize_is_refused(rig):
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"])
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=[],
                                      edges=[{"source": _node_id("brief", "c0"),
                                              "target": "entropy", "relation": "grounds",
                                              "provenance": "span-present",
                                              "span": "Entropy grounds the arrow of time."}])
    d = next(d for d in out["propose"]["details"] if d["kind"] == "edge")
    assert d["disposition"] == "REJECTED" and d["reason"] == "propose-lane-text-claim"


_FORBIDDEN = re.compile(r"vec|vss|embed|faiss|vector", re.IGNORECASE)


def test_adversarial_vector_smuggle_is_schema_rejected_and_db_stays_clean(rig):
    engine, t, _ = rig
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"],
                                      edges=[{"source": "x", "target": "y", "relation": "bridges",
                                              "embedding": [0.1, 0.2, 0.3]}])
    # an unknown field rejects the WHOLE payload at the boundary (extra="forbid"):
    # nothing lands — not even the legitimate node riding in the same payload
    d = next(d for d in out["propose"]["details"] if d["disposition"] == "REJECTED")
    assert d["kind"] == "payload" and "schema-invalid" in d["reason"]
    assert out["materialized"] == 0
    with pytest.raises(FileNotFoundError):
        engine.canon.read_node(_node_id("brief", "c0"))

    # clean re-materialize, then prove no vector schema anywhere downstream
    ok = t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"])
    assert ok["materialized"] == 1
    engine.query_graph()  # project the derived layer AFTER materialization
    db = engine.data_dir / "derived" / "index.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for typ, name, ddl in con.execute("SELECT type, name, COALESCE(sql,'') FROM sqlite_master"):
            assert not _FORBIDDEN.search(name) and not _FORBIDDEN.search(ddl), (typ, name)
    finally:
        con.close()
    # and no vector reached the canon either
    node = engine.canon.read_node(_node_id("brief", "c0"))
    assert "embedding" not in node.body and "0.1, 0.2" not in node.body


def test_materialize_cannot_bypass_the_propose_door(rig, monkeypatch):
    """With kg_propose stubbed out, materialization must produce ZERO canon writes —
    proving every write routes through the one front door."""
    engine, t, _ = rig
    calls = []
    monkeypatch.setattr(engine, "kg_propose",
                        lambda payload, **kw: (calls.append(payload) or
                                               {"dispositions": {}, "details": []}))
    before = sorted(p.name for p in (engine.canon.notes_dir).glob("*.md"))
    t["kg_diverge_materialize"](project="brief")
    after = sorted(p.name for p in (engine.canon.notes_dir).glob("*.md"))
    assert calls, "materializer did not call kg_propose at all"
    assert before == after, "materializer wrote canon outside kg_propose"


def test_reconciler_requarantines_forged_grounded_on_materialized_node(rig):
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"])
    nid = _node_id("brief", "c0")
    recon = Reconciler(engine.canon)
    recon.scan(full_sweep=True)

    node = engine.canon.read_node(nid)
    node.epistemic_state = EpistemicState.GROUNDED  # forge: no kg_ground, no audit record
    engine.canon.write_one(node)

    report = recon.scan(full_sweep=True)
    assert nid in report.requarantined
    assert engine.canon.read_node(nid).epistemic_state is EpistemicState.UNVERIFIED


def test_pin_priority_is_verdict_neutral(rig):
    """The pinned lineage marker changes ORDER at most — never a grounding outcome.
    Two structurally identical hypothesized edges, one carrying the pinned marker:
    identical verdicts, identical provenance upgrades, identical failure records."""
    engine, t, _ = rig
    engine.kg_write({"nodes": [
        {"id": "entropy", "label": "Entropy", "node_type": "claim"},
        {"id": "arrow-of-time", "label": "Arrow of time", "node_type": "claim"},
        {"id": "heat", "label": "Heat", "node_type": "claim"},
        {"id": "cold", "label": "Cold", "node_type": "claim"}]})
    engine.kg_propose({"edges": [
        {"source": "entropy", "target": "arrow-of-time", "relation": "bridges",
         "notes": "[diverge] pinned candidate=c0 brief=brief session=s1"},
        {"source": "heat", "target": "cold", "relation": "bridges"}]})
    pinned_id = edge_id("entropy", "bridges", "arrow-of-time")
    plain_id = edge_id("heat", "bridges", "cold")

    span = "Heat flows from hot to cold."
    g1 = engine.kg_ground(pinned_id, "grounded", support_span=span)
    g2 = engine.kg_ground(plain_id, "grounded", support_span=span)
    assert g1.get("ok") and g2.get("ok")

    def _fields(eid, owner):
        e = next(e for e in engine.canon.read_node(owner).edges if e.id == eid)
        return (e.epistemic_state, e.provenance, e.verdict_by, bool(e.span))

    assert _fields(pinned_id, "entropy") == _fields(plain_id, "heat")

    engine.kg_propose({"edges": [
        {"source": "entropy", "target": "heat", "relation": "bridges",
         "notes": "[diverge] pinned candidate=c1 brief=brief session=s1"},
        {"source": "arrow-of-time", "target": "cold", "relation": "bridges"}]})
    f1 = engine.kg_ground(edge_id("entropy", "bridges", "heat"), "failed", note="falsified")
    f2 = engine.kg_ground(edge_id("arrow-of-time", "bridges", "cold"), "failed", note="falsified")
    assert f1.get("ok") and f2.get("ok")
    assert _fields(edge_id("entropy", "bridges", "heat"), "entropy")[:3] == \
           _fields(edge_id("arrow-of-time", "bridges", "cold"), "arrow-of-time")[:3]


def test_i8_generate_path_consults_unified_failure_memory(rig):
    engine, t, _ = rig
    engine.kg_write({"edges": [
        {"source": "a1", "target": "a2", "relation": "bridges", "span": "Heat flows from hot to cold."},
        {"source": "a2", "target": "a3", "relation": "bridges", "span": "Heat flows from hot to cold."},
        {"source": "a1", "target": "a3", "relation": "bridges", "span": "Heat flows from hot to cold."},
        {"source": "b1", "target": "b2", "relation": "bridges", "span": "Degree approximates importance."},
        {"source": "b2", "target": "b3", "relation": "bridges", "span": "Degree approximates importance."},
        {"source": "b1", "target": "b3", "relation": "bridges", "span": "Degree approximates importance."},
        {"source": "a1", "target": "b1", "relation": "bridges", "span": "Entropy grounds the arrow of time."},
    ]})
    base = engine.kg_generate(mechanism="bridge", k=20)
    pairs = {frozenset((c["source"], c["target"])) for c in base["candidates"]}
    assert pairs, "fixture graph produced no bridge candidates — test would be vacuous"
    victim = sorted(pairs)[0]
    u, v = sorted(victim)

    engine.kg_propose({"edges": [{"source": u, "target": v, "relation": "bridges"}]})
    assert engine.kg_ground(edge_id(u, "bridges", v), "failed", note="falsified").get("ok")

    after = engine.kg_generate(mechanism="bridge", k=20)
    after_pairs = {frozenset((c["source"], c["target"])) for c in after["candidates"]}
    assert victim not in after_pairs, "generate re-proposed a FAILED pair (I8 violated)"


def test_e2e_diverge_pin_materialize_ground_failure_feeds_back(rig):
    """The plan's Stage-4 e2e: brief -> diverge -> pin -> materialize -> source exists ->
    ground: one span won + one failure recorded -> the failed candidate is auto-discarded
    and never re-proposed in a follow-up round."""
    engine, t, _ = rig
    out = t["kg_diverge_materialize"](project="brief")   # pins c0 + c1
    assert out["materialized"] == 2
    n0, n1 = _node_id("brief", "c0"), _node_id("brief", "c1")

    # one span won: c0's idea earns grounding with a verbatim source span
    won = engine.kg_ground(n0, "grounded", kind="node",
                           support_span="Entropy grounds the arrow of time.")
    assert won.get("ok"), won
    assert engine.canon.read_node(n0).epistemic_state is EpistemicState.GROUNDED

    # one failure: c1's idea is actively falsified
    lost = _refute(engine, n1)   # held, then confirmed by a second grounder (0.25.0)
    assert lost.get("ok"), lost

    # negative memory is permanent AND flows back into the brief's discards
    resumed = t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    fates = resumed.get("materialized_failures_discarded", [])
    assert {"candidate": "c1", "fate": "failed"} in fates, resumed

    from kg_engine.divergence.state import State
    st = State("brief", home=Path(engine.project_dir) / ".kg" / "diverge")
    domain = "generic"
    assert "c1" in st.read_discards(domain)
    assert "c0" in st.read_pins(domain)          # the winner stays pinned

    # follow-up round: the discarded sibling never reappears in slate or parents
    cands = [
        {"id": "c1", "text": "idea 1: concept about topic 1 via approach 1",
         "descriptor": {"angle": "a1", "scope": "broad", "form": "f1",
                        "boldness": 0.25, "mechanism": "mechanism 1"}},
        {"id": "d1", "text": "a genuinely fresh follow-up idea via a new route",
         "descriptor": {"angle": "a9", "scope": "narrow", "form": "f0",
                        "boldness": 1.0, "mechanism": "entirely new mechanism"}},
    ]
    r2 = t["kg_diverge_ingest"](project="brief", candidates=cands, axes="generic", seed=5)
    assert "c1" not in [s["id"] for s in r2["slate"]]
    par = t["kg_diverge_parents"](project="brief", k=4, seed=5)
    assert "c1" not in [p["id"] for p in par["parents"]]
    # idempotent: a second sync doesn't re-discard or flip anything
    again = t["kg_diverge_recall"](project="brief")
    assert not again.get("materialized_failures_discarded")


# --------------------------------------------------------------------------- #
# Only FALSIFICATION (`failed`) folds a materialized pin into the brief's permanent
# discards. A merely-UNSUPPORTED pin (`rejected` — no in-source span, the expected state
# of a genuinely novel idea awaiting sources) stays recoverable. The verdict a pin receives
# is unchanged and provenance-neutral; only the diverge-brief-local discard CONSEQUENCE was
# narrowed (server.MATERIALIZED_DISCARD_STATES, distinct from the global model.FAILURE_STATES).
# --------------------------------------------------------------------------- #


def test_materialize_rejected_node_pin_is_not_discarded(rig):
    """A materialized pin (node) that grounding merely REJECTS (no support — what grounding a
    novel idea against the original source yields) must NOT fold into the brief's permanent
    discards; it stays recoverable as a pin. Only FALSIFICATION discards."""
    engine, t, _ = rig
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"])
    assert out["materialized"] == 1, out["results"]
    nid = _node_id("brief", "c0")

    res = engine.kg_ground(nid, "rejected", kind="node")   # merely unsupported, no support
    assert res.get("ok"), res
    assert engine.canon.read_node(nid).epistemic_state is EpistemicState.REJECTED

    resumed = t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    assert not resumed.get("materialized_failures_discarded"), resumed

    from kg_engine.divergence.state import State
    st = State("brief", home=Path(engine.project_dir) / ".kg" / "diverge")
    assert "c0" not in st.read_discards("generic")           # not buried for being novel
    assert "c0" in st.read_pins("generic")                   # still recoverable as a pin
    assert st.read_materialized()["c0"].get("fate") is None  # no failure fate stamped


def test_materialize_rejected_edge_is_not_discarded(rig):
    """The edge path mirrors the node path: a materialized pin whose optional hypothesized
    EDGE is grounded REJECTED (no support) must not fold its owning candidate into discards."""
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief", candidate_ids=["c0", "c1"])
    a, b = _node_id("brief", "c0"), _node_id("brief", "c1")
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=[],
                                      edges=[{"source": a, "target": b, "relation": "bridges",
                                              "candidate_id": "c0"}])
    d = next(dd for dd in out["propose"]["details"] if dd["kind"] == "edge")
    assert d["disposition"] in ("ACCEPTED", "DEMOTED"), d   # landed hypothesized under c0
    eid = edge_id(a, "bridges", b)
    assert engine.kg_ground(eid, "rejected", kind="edge").get("ok")   # no support
    e = next(e for e in engine.canon.read_node(a).edges if e.id == eid)
    assert e.epistemic_state is EpistemicState.REJECTED

    resumed = t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    assert not resumed.get("materialized_failures_discarded"), resumed
    from kg_engine.divergence.state import State
    st = State("brief", home=Path(engine.project_dir) / ".kg" / "diverge")
    assert "c0" not in st.read_discards("generic")
    assert st.read_materialized()["c0"].get("fate") is None


def test_materialize_failed_edge_still_discards(rig):
    """Regression parity for the EDGE path: a materialized pin whose hypothesized edge is
    FALSIFIED (`failed`) still folds its candidate into the brief's discards. (The e2e above
    covers the node+failed case; this locks the edge+failed case so the whole
    {node,edge} × {rejected→keep, failed→discard} matrix is executable.)"""
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief", candidate_ids=["c0", "c1"])
    a, b = _node_id("brief", "c0"), _node_id("brief", "c1")
    t["kg_diverge_materialize"](project="brief", candidate_ids=[],
                                edges=[{"source": a, "target": b, "relation": "bridges",
                                        "candidate_id": "c0"}])
    eid = edge_id(a, "bridges", b)
    assert engine.kg_ground(eid, "failed", kind="edge", note="falsified").get("ok")

    resumed = t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    fates = resumed.get("materialized_failures_discarded", [])
    assert {"candidate": "c0", "fate": "failed"} in fates, resumed
    from kg_engine.divergence.state import State
    st = State("brief", home=Path(engine.project_dir) / ".kg" / "diverge")
    assert "c0" in st.read_discards("generic")


def test_pin_rejected_verdict_is_provenance_neutral(rig):
    """We narrowed the CONSEQUENCE (the fate sync), never the VERDICT. A materialized-lineage
    hypothesized edge and an equivalent plain one, both grounded `rejected` with no support,
    must land in the SAME EpistemicState.REJECTED — proving the verdict was NOT made
    provenance-dependent (the §4 rejected approach we deliberately did not take). This is the
    rejected-verdict analogue of test_pin_priority_is_verdict_neutral (grounded/failed)."""
    engine, t, _ = rig
    engine.kg_write({"nodes": [
        {"id": "px", "label": "Px", "node_type": "claim"},
        {"id": "py", "label": "Py", "node_type": "claim"},
        {"id": "qx", "label": "Qx", "node_type": "claim"},
        {"id": "qy", "label": "Qy", "node_type": "claim"}]})
    engine.kg_propose({"edges": [
        {"source": "px", "target": "py", "relation": "bridges",
         "notes": "[diverge] pinned candidate=c0 brief=brief session=s1"},
        {"source": "qx", "target": "qy", "relation": "bridges"}]})
    pinned_id = edge_id("px", "bridges", "py")
    plain_id = edge_id("qx", "bridges", "qy")
    r1 = engine.kg_ground(pinned_id, "rejected")   # no support
    r2 = engine.kg_ground(plain_id, "rejected")
    assert r1.get("ok") and r2.get("ok"), (r1, r2)

    e_pinned = next(e for e in engine.canon.read_node("px").edges if e.id == pinned_id)
    e_plain = next(e for e in engine.canon.read_node("qx").edges if e.id == plain_id)
    assert e_pinned.epistemic_state is EpistemicState.REJECTED
    assert e_plain.epistemic_state is EpistemicState.REJECTED


# --------------------------------------------------------------------------- #
# Stage 5 — the DIVERGENCE MIRROR of the graph R3-mirror advisory. A materialized-pin
# FAILURE is permanent negative memory (I8); on a SOURCE CHANGE it is SURFACED as
# re-examinable (never auto-un-sealed) and can be EXPLICITLY un-sealed back into the
# proposal pool. Evidence is non-monotonic; the brief's negative memory stays sealed
# until the user acts.
# --------------------------------------------------------------------------- #


def _bump_source(path: Path, text: str) -> None:
    """Rewrite the source AND push its mtime forward so the engine's signature-cached SourceSet
    re-resolves (mirrors the graph-side _rewrite helper)."""
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 100))



def _refute(engine, node_id, **kw):
    """Stamp a pin `failed`. Since 0.25.0 a refutation of a `[diverge]` pin is held for a second grounder, so the
    first call is held and the second, the confirmation, applies it (tests/test_feat_attack_ideas.py)."""
    first = engine.kg_ground(node_id, "failed", kind="node", **kw)
    assert first.get("held"), first
    second = engine.kg_ground(node_id, "failed", kind="node", **kw)
    assert second.get("confirmed"), second
    return second

def _diverge_state(engine):
    from kg_engine.divergence.state import State
    return State("brief", home=Path(engine.project_dir) / ".kg" / "diverge")


def test_failed_fated_discard_surfaces_reexaminable_after_source_change(rig):
    """A `failed`-fated pin is surfaced as re-examinable ONLY after the source set changes — and only
    the failed one (a live/unverified pin is never surfaced). Surface-only: the discard is NOT removed."""
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief")               # materialize c0 + c1
    assert _refute(engine, _node_id("brief", "c1")).get("ok")
    resumed = t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    assert {"candidate": "c1", "fate": "failed"} in resumed.get("materialized_failures_discarded", [])
    assert not resumed.get("reexaminable_discards")            # source unchanged since judged

    _bump_source(engine.source_path, "New evidence about the c1 idea has now arrived.\n")
    recalled = t["kg_diverge_recall"](project="brief")
    reex = recalled.get("reexaminable_discards", [])
    assert {"candidate": "c1", "fate": "failed",
            "reason": "source-set-changed-since-judged"} in reex
    assert "c0" not in {r["candidate"] for r in reex}         # live/unverified pin never surfaced
    assert "c1" in _diverge_state(engine).read_discards("generic")   # surface-only: still sealed


def test_reexaminable_discards_empty_without_source(rig, monkeypatch):
    """No source configured -> the divergence mirror is empty (parallels the graph advisory)."""
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief")
    assert _refute(engine, _node_id("brief", "c1")).get("ok")
    t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    engine.source_path = None                                  # drop the source
    recalled = t["kg_diverge_recall"](project="brief")
    assert not recalled.get("reexaminable_discards")


def test_explicit_unseal_removes_discard_and_clears_fate(rig):
    """The EXPLICIT un-seal lever: `reexamine=[cid]` drops the candidate from discards and clears its
    fate; WITHOUT it the discard remains (permanence not silently broken)."""
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief")
    assert _refute(engine, _node_id("brief", "c1")).get("ok")
    t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    st = _diverge_state(engine)
    assert "c1" in st.read_discards("generic")
    assert st.read_materialized()["c1"].get("fate") == "failed"

    _bump_source(engine.source_path, "New evidence for the c1 idea.\n")
    # surfaced but NOT auto-un-sealed
    recalled = t["kg_diverge_recall"](project="brief")
    assert "c1" in {r["candidate"] for r in recalled.get("reexaminable_discards", [])}
    assert "c1" in st.read_discards("generic")
    assert st.read_materialized()["c1"].get("fate") == "failed"

    # explicit un-seal -> removed from discards, fate cleared, no longer surfaced
    unsealed = t["kg_diverge_recall"](project="brief", reexamine=["c1"])
    assert unsealed.get("reexamined_unsealed") == ["c1"]
    assert "c1" not in st.read_discards("generic")
    assert st.read_materialized()["c1"].get("fate") is None
    assert "c1" not in {r["candidate"] for r in unsealed.get("reexaminable_discards", [])}


def test_unseal_holds_across_next_fate_sync_until_source_changes(rig):
    """Un-sealing is durable: the very next fate-sync must NOT re-fold the still-`failed` graph item
    (which would silently undo the un-seal) while the source is unchanged."""
    engine, t, _ = rig
    t["kg_diverge_materialize"](project="brief")
    assert _refute(engine, _node_id("brief", "c1")).get("ok")
    t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    _bump_source(engine.source_path, "New evidence for the c1 idea.\n")
    t["kg_diverge_recall"](project="brief", reexamine=["c1"])   # un-seal
    st = _diverge_state(engine)
    assert "c1" not in st.read_discards("generic")

    t["kg_diverge_recall"](project="brief")                    # next sync, source unchanged
    assert "c1" not in st.read_discards("generic")             # un-seal held (guard)
    assert st.read_materialized()["c1"].get("fate") is None


def test_materialize_advisory_present_when_source_exists(rig):
    """Part C: the advisory is gated on BOTH conjuncts of `source_path is not None and
    materialized_count` — present only when a source is configured AND >=1 pin materialized;
    absent when either conjunct is false. Advisory only — never a disposition, verdict, or
    ledger write (the ledger/materialized count is unchanged)."""
    engine, t, _ = rig
    assert engine.source_path is not None                # the rig configures a real source

    # source present + >=1 materialized → advisory present
    out = t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"])
    assert out["materialized"] == 1
    assert "advisory" in out and "unverified" in out["advisory"]

    # source present but a NON-empty payload that fully REJECTS at the boundary (unknown field →
    # extra="forbid") → the code REACHES the advisory block with materialized_count == 0, so the
    # advisory must still be absent. Guards the SECOND conjunct of the AND: dropping
    # `and materialized_count` would emit a "grounding these pins" advisory here, naming no pins.
    # (A refused/all-skipped batch instead short-circuits on the empty-payload early return and
    # never reaches this block, so it would NOT catch that regression — this path does.)
    zero = t["kg_diverge_materialize"](project="brief", candidate_ids=["c0"],
                                       edges=[{"source": "x", "target": "y", "relation": "bridges",
                                               "embedding": [0.1, 0.2, 0.3]}])
    assert zero["materialized"] == 0
    assert "advisory" not in zero

    # no source configured + >=1 materialized → advisory absent (first conjunct false)
    engine.source_path = None
    out2 = t["kg_diverge_materialize"](project="brief", candidate_ids=["c1"])
    assert out2["materialized"] == 1
    assert "advisory" not in out2
