"""review-r6 (performance review 2026-07-03) regression pins.

Each test pins one applied finding so it cannot silently regress:

  F1  hook-import-tax   — importing kg_engine.server must not pull networkx/pydantic/yaml-heavy pack
  F2  vector store      — embeddings persist as npz, round-trip exactly, legacy JSON still reads
  F3  mech-spread cap   — _cap_by_novelty: identity at/below cap, most-novel above it
  F4  lazy-row FPS      — farthest_point_sampling matches the reference full-matrix walk exactly
  F5  incremental parse — a one-note edit re-parses ONE file; derived output identical to a rebuild
  F6  term cap          — a kg_context query searches on at most _QUERY_TERM_CAP terms
  F7  session-zone I/O  — durable=False skips fsync but stays atomic; an unchanged mech store and a
                          surface-reusable open-axis batch do no redundant work
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- F1: import weight


def test_f1_server_import_pulls_no_heavy_modules():
    """The PreToolUse hook imports kg_engine.server on every Grep/Glob/Read; networkx (~70ms),
    pydantic (~75ms, via boundary) and the pack loader are write/projection-side only and must stay
    off the import graph (review-r6: hook-import-tax). Subprocess so other tests' imports of
    networkx/pydantic cannot mask a regression."""
    code = (
        "import sys\n"
        "import kg_engine.server\n"
        "heavy = [m for m in ('networkx', 'pydantic', 'kg_engine.pack') if m in sys.modules]\n"
        "assert not heavy, f'heavy modules on the hook import path: {heavy}'\n"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO / "scripts"))
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- F2: npz vector store


def test_f2_vector_store_roundtrips_exactly_and_lands_as_npz(tmp_path):
    from kg_engine.divergence.state import State

    st = State("r6proj", home=tmp_path).ensure()
    # awkward-but-legal caller-supplied ids: separators, a np.savez parameter name, empty string
    emb = {"c0": [0.1, 0.2, 0.30000000000000004], "a/b": [1.5, -2.25], "file": [7.0], "": [9.0]}
    st.write_embeddings(emb)
    assert st.embeddings_path.suffix == ".npz" and st.embeddings_path.exists()
    assert State("r6proj", home=tmp_path).read_embeddings() == emb  # exact float64 round-trip


def test_f2_legacy_json_store_still_reads_and_is_replaced_on_write(tmp_path):
    from kg_engine.divergence.state import State

    st = State("r6legacy", home=tmp_path).ensure()
    emb = {"x": [0.5, 0.25]}
    st._legacy_embeddings_json.write_text(json.dumps(emb), encoding="utf-8")
    assert st.read_embeddings() == emb          # fallback read of a pre-npz session
    st.write_embeddings(emb)                    # first write migrates the store
    assert st.embeddings_path.exists()
    assert not st._legacy_embeddings_json.exists()


def test_f2_compact_write_json_same_content_smaller_bytes(tmp_path):
    from kg_engine.divergence.state import State

    st = State("r6compact", home=tmp_path).ensure()
    obj = {"b": [1, 2, 3], "a": {"nested": True}}
    st.write_json(tmp_path / "pretty.json", obj)
    st.write_json(tmp_path / "compact.json", obj, compact=True)
    pretty, compact = (tmp_path / "pretty.json"), (tmp_path / "compact.json")
    assert json.loads(pretty.read_text()) == json.loads(compact.read_text()) == obj
    assert compact.stat().st_size < pretty.stat().st_size


# --------------------------------------------------------------------------- F3: mech-spread cap


def test_f3_cap_by_novelty_identity_below_cap_most_novel_above():
    from kg_engine.divergence.pipeline import _cap_by_novelty

    arc = SimpleNamespace(niches={
        f"nid{i}": SimpleNamespace(elite_id=f"e{i}", novelty=float(i)) for i in range(10)
    })
    ids = [f"e{i}" for i in range(10)]
    assert _cap_by_novelty(arc, ids, cap=10) == ids          # at cap: order untouched
    assert _cap_by_novelty(arc, ids, cap=99) == ids          # below cap: identity
    assert _cap_by_novelty(arc, ids, cap=3) == ["e9", "e8", "e7"]  # above: most-novel first


# --------------------------------------------------------------------------- F4: lazy-row FPS


def _reference_fps(vecs, k, start=0, seeds=None):
    """The pre-review-r6 full-matrix implementation, kept verbatim as the behavioral reference."""
    vecs = np.asarray(vecs, dtype=np.float64)
    n = vecs.shape[0]
    k = min(k, n)
    if k <= 0:
        return []
    dist = 1.0 - vecs @ vecs.T
    if seeds:
        selected = [int(s) for s in seeds]
        min_d = dist[:, selected].min(axis=1)
    else:
        selected = [int(start)]
        min_d = dist[start].copy()
    while len(selected) < k:
        min_d[selected] = -np.inf
        j = int(np.argmax(min_d))
        selected.append(j)
        min_d = np.minimum(min_d, dist[j])
    return selected


def test_f4_lazy_row_fps_matches_full_matrix_reference():
    from kg_engine.divergence.diversity import farthest_point_sampling

    rng = np.random.default_rng(11)
    for _ in range(60):
        n = int(rng.integers(1, 48))
        d = int(rng.integers(2, 24))
        v = rng.normal(size=(n, d))
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        k = int(rng.integers(0, n + 2))
        n_seeds = int(rng.integers(0, min(4, n) + 1))
        seeds = list(rng.integers(0, n, size=n_seeds)) or None
        assert farthest_point_sampling(v, k, seeds=seeds) == _reference_fps(v, k, seeds=seeds)


# --------------------------------------------------------------------------- F5: incremental parse


def _mini_canon(project_dir, n=12):
    from kg_engine.canon import Canon
    from kg_engine.model import Edge, Node

    nodes = [Node(id=f"n{i:03d}", label=f"Node {i}", node_type="concept",
                  edges=[Edge(source=f"n{i:03d}", target=f"n{(i + 1) % n:03d}",
                              relation="links_to", provenance="span-present",
                              span=f"span text {i} runs here")])
             for i in range(n)]
    Canon(project_dir).write_nodes(nodes, message="seed")


def _projector(project_dir, derived_dir):
    from kg_engine.canon import Canon
    from kg_engine.projector import Projector

    return Projector(Canon(project_dir), derived_dir, metrics_mode="structure_only",
                     source_text=lambda: "", source_set=None, specificity_seeds=lambda: {})


def _dump_tables(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        nodes = sorted((dict(r) for r in con.execute("SELECT * FROM nodes")),
                       key=lambda d: d["id"])
        edges = sorted((dict(r) for r in con.execute("SELECT * FROM edges")),
                       key=lambda d: d["id"])
    finally:
        con.close()
    return nodes, edges


def test_f5_one_note_edit_parses_exactly_one_file(tmp_path, monkeypatch):
    from kg_engine.canon import Canon

    _mini_canon(tmp_path / "proj")
    proj = _projector(tmp_path / "proj", tmp_path / "derived")
    proj.project()

    calls = []
    orig = Canon.parse_note
    monkeypatch.setattr(Canon, "parse_note", lambda self, p: calls.append(p.name) or orig(self, p))
    target = sorted((tmp_path / "proj" / "canon").glob("*.md"))[3]
    target.write_text(target.read_text(encoding="utf-8").replace("Node 3", "Node 3 EDITED"),
                      encoding="utf-8")
    assert proj.is_stale() is True
    proj.project()
    assert calls == [target.name]  # ONE parse for a one-note edit (was: the whole canon)


def test_f5_incremental_projection_identical_to_full_rebuild(tmp_path):
    _mini_canon(tmp_path / "proj")
    inc = _projector(tmp_path / "proj", tmp_path / "inc")
    inc.project()
    target = sorted((tmp_path / "proj" / "canon").glob("*.md"))[5]
    target.write_text(target.read_text(encoding="utf-8").replace("Node 5", "Node 5 EDITED"),
                      encoding="utf-8")
    assert inc.is_stale() is True
    inc.project()                                     # stat-gated: unchanged notes hydrate as shells
    full = _projector(tmp_path / "proj", tmp_path / "full")
    full.project()                                    # from-scratch parse of the same canon state
    assert _dump_tables(tmp_path / "inc" / "index.sqlite") == \
        _dump_tables(tmp_path / "full" / "index.sqlite")


def test_f5_missing_file_stats_falls_back_to_full_parse(tmp_path, monkeypatch):
    """A pre-review-r6 index (no file_stats meta) must take the full-parse path and stay correct."""
    from kg_engine.canon import Canon

    _mini_canon(tmp_path / "proj", n=6)
    proj = _projector(tmp_path / "proj", tmp_path / "derived")
    proj.project()
    con = sqlite3.connect(tmp_path / "derived" / "index.sqlite")
    con.execute("DELETE FROM meta WHERE key='file_stats'")
    con.commit()
    con.close()
    target = sorted((tmp_path / "proj" / "canon").glob("*.md"))[0]
    target.write_text(target.read_text(encoding="utf-8").replace("Node 0", "Node 0 EDITED"),
                      encoding="utf-8")
    calls = []
    orig = Canon.parse_note
    monkeypatch.setattr(Canon, "parse_note", lambda self, p: calls.append(p.name) or orig(self, p))
    assert proj.is_stale() is True
    assert len(calls) == 6                       # full parse — never worse than the old path
    proj.project()
    full = _projector(tmp_path / "proj", tmp_path / "full")
    full.project()
    assert _dump_tables(tmp_path / "derived" / "index.sqlite") == \
        _dump_tables(tmp_path / "full" / "index.sqlite")


# --------------------------------------------------------------------------- F6: term cap


def test_f6_query_terms_capped():
    from kg_engine.projector import _QUERY_TERM_CAP, DerivedReader

    # 0.11.5 replaced the per-term LIKE clause with a word match ranked in Python; the cap still bounds
    # the per-row work a pasted-paragraph query can ask for: only the first cap terms are searched on.
    query = " ".join(f"term{i:02d}" for i in range(_QUERY_TERM_CAP + 8))
    assert DerivedReader._query_terms(query) == [f"term{i:02d}" for i in range(_QUERY_TERM_CAP)]
    assert DerivedReader._query_terms("alpha beta") == ["alpha", "beta"]


# --------------------------------------------------------------------------- F7: session-zone I/O


def test_f7_durable_false_skips_fsync_but_stays_atomic(tmp_path, monkeypatch):
    import kg_engine.atomicio as atomicio

    fsyncs = []
    monkeypatch.setattr(atomicio.os, "fsync", lambda fd: fsyncs.append(fd))
    atomicio.atomic_write_text(tmp_path / "ephemeral.json", "{}", durable=False)
    assert fsyncs == []                                     # no fsync for session-zone writes
    assert (tmp_path / "ephemeral.json").read_text() == "{}"  # ...but the write itself landed
    atomicio.atomic_write_text(tmp_path / "durable.json", "{}")
    assert len(fsyncs) >= 1                                 # durable default keeps the protocol


def test_f7_unchanged_mech_store_written_once(tmp_path, monkeypatch):
    """With no open axis the mech store is an empty {} that never changes: it must land once (so the
    paths()-listed file exists) and never be rewritten on later cycles."""
    from kg_engine.divergence import pipeline
    from kg_engine.divergence.state import State

    monkeypatch.setenv("KG_DIVERGE_HOME", str(tmp_path))
    axes = {"domain": "d", "unit_of_generation": "idea",
            "axes": [{"name": "form", "type": "categorical"}],
            "slate_size": 4, "candidates_per_generation": 6}
    writes = []
    orig = State.write_mech_embeddings
    monkeypatch.setattr(State, "write_mech_embeddings",
                        lambda self, e: writes.append(len(e)) or orig(self, e))

    def cands(tag, n=6):
        return [{"id": f"c{tag}{i}", "text": f"idea {tag}{i} about topic {i}",
                 "descriptor": {"form": f"v{i}"}} for i in range(n)]

    pipeline.init_project("proj", axes, seed=3, home=tmp_path, session="sess-A")
    pipeline.ingest("proj", cands("a"), axes, seed=3, home=tmp_path)
    assert writes == [0]                     # first cycle: file absent -> written once, empty
    pipeline.ingest("proj", cands("b"), axes, seed=3, home=tmp_path)
    assert writes == [0]                     # second cycle: unchanged -> skipped


def test_f7_assign_open_cells_reuses_surface_rows(tmp_path):
    from kg_engine.divergence.config import Axis, AxesSpec
    from kg_engine.divergence.pipeline import assign_open_cells

    class CountingEmbedder:
        name = "counting"

        def __init__(self):
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            rows = []
            for t in texts:
                rng = np.random.default_rng(abs(hash(t)) % (2**32))
                v = rng.normal(size=8)
                rows.append(v / np.linalg.norm(v))
            return np.asarray(rows, dtype=np.float32)

    spec = AxesSpec(domain="d", unit_of_generation="idea",
                    axes=[Axis(name="mechanism", type="open", primary_novelty=True)], slate_size=4)
    texts = [f"idea number {i}" for i in range(5)]
    descriptors = [{} for _ in texts]        # no descriptor value -> every item falls back to text
    emb = CountingEmbedder()
    surface = emb.embed(texts)
    baseline = emb.calls
    _, cells_reused, vecs_reused = assign_open_cells(
        spec, descriptors, texts, emb, seed=1, surface_vecs=surface)
    assert emb.calls == baseline             # zero re-embeds: every row reused
    _, cells_fresh, vecs_fresh = assign_open_cells(spec, descriptors, texts, emb, seed=1)
    assert emb.calls == baseline + 1         # the old path embeds the batch again
    assert cells_reused == cells_fresh
    np.testing.assert_array_equal(vecs_reused, vecs_fresh)
