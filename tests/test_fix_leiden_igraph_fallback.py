"""0.19.4: a leidenalg that cannot load still leaves the graph Leiden communities, through igraph's own Leiden.

Field report (Windows install, Smart App Control on, 2026-11-18). At two engine starts Windows refused
leidenalg's native library (``_c_leiden`` and the igraph DLL bundled with it), while python-igraph's own DLL, a
core import, loaded. The projection then fell to networkx label propagation, a different algorithm with
different communities, and regroup's re-partition fell to asynchronous label propagation. The canon did not
change that day, so the field graph kept its Leiden communities; the next change would have redrawn them.

So, in this release:
- ``projector.leiden_membership`` runs leidenalg when it loads, else igraph's built-in ``community_leiden`` on the
  same objective (modularity at the given resolution), seeded through a private generator;
- the projection and regroup's re-partition both use it, and label propagation is left for an engine without
  igraph;
- the bootstrap probe and the engine's preload log name the new fallback.
"""
from __future__ import annotations

import logging
import random
import sys

import networkx as nx
import pytest

import kg_engine.server as S
from kg_engine import generate, projector

GROUP_A = [f"a{i}" for i in range(6)]
GROUP_B = [f"b{i}" for i in range(6)]


def _two_cliques() -> nx.Graph:
    g = nx.Graph()
    for group in (GROUP_A, GROUP_B):
        g.add_edges_from((u, v) for i, u in enumerate(group) for v in group[i + 1:])
    g.add_edge("a0", "b0")
    return g


def _karate() -> nx.Graph:
    g = nx.karate_club_graph()
    return nx.relabel_nodes(g, {n: f"n{n}" for n in g})


def _groups(membership: dict) -> set:
    by: dict = {}
    for node, community in membership.items():
        by.setdefault(community, set()).add(node)
    return {frozenset(members) for members in by.values()}


@pytest.fixture
def no_leidenalg(monkeypatch):
    """leidenalg as Smart App Control left it: installed, but its import fails."""
    monkeypatch.setitem(sys.modules, "leidenalg", None)


def test_without_leidenalg_the_projection_keeps_leiden_communities(no_leidenalg):
    assert _groups(projector._leiden(_two_cliques())) == {frozenset(GROUP_A), frozenset(GROUP_B)}


def test_the_fallback_is_igraphs_own_leiden_not_label_propagation(no_leidenalg):
    import igraph as ig

    g = _karate()
    nodes = list(g.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    ig_graph = ig.Graph(n=len(nodes), edges=[(idx[u], idx[v]) for u, v in g.edges()], directed=False)
    ig.set_random_number_generator(random.Random(42))
    try:
        expected = ig_graph.community_leiden(objective_function="modularity", resolution=1.0,
                                             n_iterations=2).membership
    finally:
        ig.set_random_number_generator(random)
    got = projector._leiden(g)
    assert got == {nodes[i]: m for i, m in enumerate(expected)}
    lpa = {n: ci for ci, com in enumerate(nx.community.label_propagation_communities(g)) for n in com}
    assert _groups(got) != _groups(lpa), "the karate club tells the two algorithms apart"


def test_igraphs_leiden_is_deterministic_and_leaves_the_global_generator_alone(no_leidenalg):
    g = _karate()
    random.seed(1234)
    state = random.getstate()
    first = projector.leiden_membership(g, seed=42)
    assert random.getstate() == state
    assert projector.leiden_membership(g, seed=42) == first


def test_with_leidenalg_the_projection_is_unchanged():
    la = pytest.importorskip("leidenalg")
    import igraph as ig

    g = _karate()
    nodes = list(g.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    ig_graph = ig.Graph(n=len(nodes), edges=[(idx[u], idx[v]) for u, v in g.edges()], directed=False)
    membership = la.find_partition(ig_graph, la.RBConfigurationVertexPartition, seed=42).membership
    assert projector._leiden(g) == {nodes[i]: m for i, m in enumerate(membership)}


def test_without_igraph_the_projection_falls_back_to_label_propagation(monkeypatch, no_leidenalg):
    monkeypatch.setitem(sys.modules, "igraph", None)
    g = _karate()
    lpa = {n: ci for ci, com in enumerate(nx.community.label_propagation_communities(g)) for n in com}
    assert projector._leiden(g) == lpa


def test_regroups_repartition_without_leidenalg_runs_igraphs_leiden(no_leidenalg):
    g = _karate()
    part = generate._repartition(g)
    assert part == projector.leiden_membership(g, seed=generate._REPART_SEED,
                                               resolution=generate._REPART_RESOLUTION)
    assert len(set(part.values())) > len(set(projector._leiden(g).values())), "a higher resolution splits more"


def test_the_preload_log_names_igraphs_leiden(monkeypatch, caplog):
    import builtins
    real_import = builtins.__import__

    def refuse_leidenalg(name, *a, **k):
        if name == "leidenalg":
            raise ImportError("DLL load failed while importing _c_leiden: blocked")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", refuse_leidenalg)
    with caplog.at_level(logging.INFO, logger="kg_engine"):
        S._preload_native_deps()
    assert "preload: leidenalg unavailable" in caplog.text
    assert "projection will use igraph's built-in Leiden instead" in caplog.text
