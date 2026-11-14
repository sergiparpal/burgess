"""Stage 5 — advisory geometry over /kg-generate, behind divergence.dpp (FUSION_PLAN §12).

The I5 snapshot test is the stage's contract: on one fixture corpus, generate ->
propose -> ground with the flag OFF and ON produce BIT-IDENTICAL grounding
artifacts (canon bytes, audit log, negative-memory counters) — only candidate
presentation/ordering may differ. Clocks are frozen so "bit-identical" is literal.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import networkx as nx
import pytest

import kg_engine.advisory_geometry as ag
from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "pack" / "pack.yaml"

SOURCE = """\
Entropy grounds the arrow of time. Heat flows from hot to cold.
Degree approximates importance. A compression stands in for many observations.
The bridge intuition reconciles with specificity weighting.
"""

_EDGES = [
    ("a1", "a2"), ("a2", "a3"), ("a1", "a3"),
    ("b1", "b2"), ("b2", "b3"), ("b1", "b3"), ("a1", "b1"),
]


def _freeze_clocks(monkeypatch):
    """Freeze EVERY module-level `utcnow` binding the grounding flow stamps bytes through.

    `from .model import utcnow` gives each importer its OWN binding, so patching model alone
    covers only calls resolved in model's namespace — every importing module must be patched
    too. canon was missing (ci-flake 2026-07-03): canon.write_nodes stamps `updated_at` into
    the note frontmatter through its own binding, so whenever the off-arm and on-arm writes
    straddled a wall-clock second the two canons' BYTES differed and the I5 digest assert
    failed — a timing flake seen on the slow Windows runner with the engine code unchanged.
    If a new module ever imports utcnow and stamps persisted bytes, add it here."""
    frozen = lambda: "2026-01-01T00:00:00+00:00"  # noqa: E731
    import kg_engine.canon
    import kg_engine.groundaudit
    import kg_engine.model
    import kg_engine.server
    monkeypatch.setattr(kg_engine.model, "utcnow", frozen)
    monkeypatch.setattr(kg_engine.server, "utcnow", frozen)
    monkeypatch.setattr(kg_engine.groundaudit, "utcnow", frozen)
    monkeypatch.setattr(kg_engine.canon, "utcnow", frozen)


def _build(tmp_path, name):
    proj = tmp_path / name
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    # Both arms read the same corpus under the same file name, each in its own folder. A promotion
    # records the file its support span is in (0.16.1), so differently named copies would put a
    # different `source_file` in each canon for a reason that has nothing to do with the flag.
    src_dir = tmp_path / f"{name}-src"
    src_dir.mkdir()
    src = src_dir / "source.md"
    src.write_text(SOURCE, encoding="utf-8")
    engine = KGEngine(proj, source_path=src, pack_path=PACK)
    engine.kg_write({"edges": [
        {"source": u, "target": v, "relation": "bridges",
         "span": "Heat flows from hot to cold."} for u, v in _EDGES]})
    return engine, proj


def _digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.md")):
        h.update(str(p.relative_to(root)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def test_i5_snapshot_grounding_is_bit_identical_flag_on_vs_off(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    _freeze_clocks(monkeypatch)

    e_off, p_off = _build(tmp_path, "off")
    e_on, p_on = _build(tmp_path, "on")

    out_off = e_off.kg_generate(mechanism="bridge", k=12, dpp=False)
    out_on = e_on.kg_generate(mechanism="bridge", k=12, dpp=True)

    # the flag may only reorder/label: identical candidate SETS
    key = lambda c: json.dumps(c, sort_keys=True)  # noqa: E731
    assert sorted(map(key, out_off["candidates"])) == sorted(map(key, out_on["candidates"]))
    assert "divergence_advisory" not in out_off
    adv = out_on["divergence_advisory"]
    assert adv["applied"] and adv["order"] == "dpp"
    assert len(adv["bins"]) == len(out_on["candidates"]) == len(adv["semantic_novelty"])

    # identical downstream actions in both projects (the propose lane is
    # id-canonical; the agent's presentation order is not a write order)
    edges = sorted(
        ({"source": c["source"], "target": c["target"], "relation": c["relation"]}
         for c in out_off["candidates"] if c.get("source")),
        key=lambda e: (e["source"], e["target"]))
    assert edges, "fixture produced no edge candidates — snapshot would be vacuous"
    for eng in (e_off, e_on):
        eng.kg_propose({"edges": edges})
        first = edge_id(edges[0]["source"], "bridges", edges[0]["target"])
        last = edge_id(edges[-1]["source"], "bridges", edges[-1]["target"])
        won = eng.kg_ground(first, "grounded", support_span="Degree approximates importance.")
        assert won.get("ok"), won
        lost = eng.kg_ground(last, "failed", note="falsified on re-check")
        assert lost.get("ok"), lost

    # grounding artifacts: bit-identical canon, bit-identical audit ledger,
    # identical negative-memory counters
    assert _digest_tree(p_off / "canon") == _digest_tree(p_on / "canon")
    audit_off = (p_off / ".kg-ground-audit.jsonl").read_bytes()
    audit_on = (p_on / ".kg-ground-audit.jsonl").read_bytes()
    assert audit_off == audit_on
    ctx_off = e_off.projector.kg_context()["falsification_counters"]
    ctx_on = e_on.projector.kg_context()["falsification_counters"]
    assert ctx_off == ctx_on


def _mini_graph() -> "nx.MultiDiGraph":
    G = nx.MultiDiGraph()
    for n, com in (("a", 1), ("b", 1), ("c", 2), ("d", 2)):
        G.add_node(n, community=com, label=f"node {n}")
    G.add_edge("a", "b", epistemic_state="grounded")
    G.add_edge("b", "c", epistemic_state="unverified")
    G.add_edge("c", "d", epistemic_state="grounded")
    return G


def test_structural_descriptor_axes():
    G = _mini_graph()
    und = G.to_undirected(as_view=True)
    cache: dict = {}
    intra = ag._structural_descriptor({"source": "a", "target": "b", "kind": "edge"}, G, und, cache)
    assert intra["community"] == "intra" and intra["graph_distance"] == "d1"
    cross = ag._structural_descriptor({"source": "a", "target": "d", "kind": "edge"}, G, und, cache)
    assert cross["community"] == "cross" and cross["graph_distance"] == "d3"
    assert 0.0 <= cross["grounded_mix"] <= 1.0
    node = ag._structural_descriptor({"kind": "node", "label": "x"}, G, und, cache)
    assert node == {"community": "node", "graph_distance": "node", "grounded_mix": 0.0}
    G.add_node("island", community=9)
    far = ag._structural_descriptor({"source": "a", "target": "island", "kind": "edge"}, G, und, cache)
    assert far["graph_distance"] == "unreachable"


def test_grounded_hubs_rank_by_grounded_degree():
    G = _mini_graph()
    hubs = ag._grounded_hubs(G, 2)
    ids = [n for n, _ in hubs]
    assert ids[0] in ("a", "b", "c") and len(hubs) == 2  # grounded-incident nodes only
    G2 = nx.MultiDiGraph()
    G2.add_edge("x", "y")  # no grounded edges at all -> degree fallback
    assert {n for n, _ in ag._grounded_hubs(G2, 2)} == {"x", "y"}


def test_order_candidates_is_a_pure_reorder(monkeypatch):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    G = _mini_graph()
    cands = [{"kind": "edge", "mechanism": "bridge", "source": s, "target": t,
              "relation": "bridges", "score": 0.5 + i / 10}
             for i, (s, t) in enumerate((("a", "c"), ("a", "d"), ("b", "d"), ("b", "c")))]
    ordered, adv = ag.order_candidates([dict(c) for c in cands], G, seed=3)
    key = lambda c: json.dumps(c, sort_keys=True)  # noqa: E731
    assert sorted(map(key, ordered)) == sorted(map(key, cands))  # same set, nothing mutated
    assert adv["applied"] and len(adv["bins"]) == 4 and len(adv["cliche_distance"]) == 4
    assert adv["cliche_hubs"], "grounded hubs should feed the cliché map"

    one, adv1 = ag.order_candidates([dict(cands[0])], G)
    assert len(one) == 1 and adv1["applied"] is False


def test_order_candidates_pool_cap_falls_back_beyond(monkeypatch):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    G = _mini_graph()
    cands = [{"kind": "edge", "mechanism": "bridge", "source": "a", "target": "d",
              "relation": "bridges", "score": 1.0 - i / 100, "rationale": f"r{i}"}
             for i in range(30)]
    ordered, adv = ag.order_candidates([dict(c) for c in cands], G, pool_cap=10)
    assert adv["pool"] == 10 and adv["beyond_cap_kept_in_donor_order"] == 20
    assert [c["rationale"] for c in ordered[10:]] == [f"r{i}" for i in range(10, 30)]


def test_pack_dpp_default_reads_flag():
    from kg_engine.pack import load_pack
    pack = load_pack(PACK)
    assert ag.pack_dpp_default(pack) is False  # shipped OFF (D1 may flip it in Stage 6)
    assert ag.pack_dpp_default(None) is False

    class P:  # minimal stand-in
        divergence = {"dpp": True}
    assert ag.pack_dpp_default(P()) is True


def test_advisory_failure_keeps_donor_ordering(tmp_path, monkeypatch):
    """I9 for the advisory layer: if geometry blows up, kg_generate returns the
    donor-ordered candidates and says why — never an error."""
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    engine, _ = _build(tmp_path, "degrade")

    def boom(*a, **k):
        raise RuntimeError("geometry exploded")
    monkeypatch.setattr(ag, "order_candidates", boom)

    out = engine.kg_generate(mechanism="bridge", k=12, dpp=True)
    assert out["candidates"], "candidates must survive an advisory failure"
    assert "divergence_advisory" not in out
    assert "advisory ordering unavailable" in out["note"]


def test_perf_budget_embed_and_dpp_single_digit_seconds(monkeypatch):
    """Plan Stage 5.5: embedding <=200 candidates and DPP selection each complete
    within single-digit seconds on CPU (hash embedder; actuals go to DECISIONS.md)."""
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    from kg_engine.divergence import diversity as ddiv
    from kg_engine.divergence.embed import get_embedder, reset_cache

    reset_cache()
    texts = [f"candidate {i}: connects concept {i % 17} with concept {(i * 7) % 23} "
             f"via mechanism {i % 11}" for i in range(200)]
    t0 = time.perf_counter()
    vecs = get_embedder().embed(texts)
    embed_s = time.perf_counter() - t0
    assert vecs.shape[0] == 200

    import numpy as np
    scores = np.linspace(0.1, 1.0, 200)
    t0 = time.perf_counter()
    order = ddiv.select_diverse(vecs, k=199, quality=scores, seed=0, quality_weight=0.3)
    dpp_s = time.perf_counter() - t0
    assert len(set(order)) == len(order)

    print(f"\nperf budget actuals: embed(200)={embed_s:.3f}s dpp(200)={dpp_s:.3f}s")
    assert embed_s < 9.0, f"embedding budget blown: {embed_s:.2f}s"
    assert dpp_s < 9.0, f"DPP budget blown: {dpp_s:.2f}s"
