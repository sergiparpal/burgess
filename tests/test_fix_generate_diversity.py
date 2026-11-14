"""0.16.0: one node cannot take a generation's slate, and a compression is written as the star it was scored as.

Field run (2026-11-14, 0.15.2). The first `/burgess:kg-generate` on the field graph ran the default set at k=10.
- **All 10 bridges hung off radar-meta**, and 11 of the 12 edge candidates touched it.
  - No node of that graph was a structural bridge: every community was one connected component, about 270 of
    them. With the gate off, a node's bridging strength was `structural_bridge + 1e-6·degree`, so the rank was
    degree alone.
  - The pair score is the sum of the two strengths. So the node with the most links (radar-meta, 12) paired with
    the top node of every other community. Its specificity is 1.74 against a graph mean of 2.81, the generic
    hub §4 is meant to hold back.
  - The rationale printed "strength=0.0000 via structural-bridge", and the session read it as naming radar-meta
    the only structural bridge.
- **Unjudged proposals are live structure.** After the write, the gate turned on, radar-meta became a bridge of
  10 communities, and its betweenness grew 13-fold. Replayed on a copy, the next run bridged radar-meta to 10
  more nodes and seeded pairs whose shared neighbour was an unjudged compression node. Nothing said so.
- **A compression candidate carried its members only in `rationale`, and no id.** Neither the command nor the
  generator said to write the `collapses_into` star the MDL screen scored. The session read `operations.py` to
  find the collapse id rule.

So, in this release:
- the gate-off strength is weighted by specificity, as `spec_betweenness` weights betweenness;
- no endpoint takes more than `ENDPOINT_CAP` (2) slots of a bridge or regroup slate;
- `kg_generate` counts the unjudged hypothesized edges and says so;
- a compression candidate carries `members` and the `id` `kg_operate collapse` writes.
"""
from __future__ import annotations

import collections
import itertools
import json
import re
from pathlib import Path

import pytest

from kg_engine import generate as gen
from kg_engine import operations as ops
from kg_engine.canon import Canon
from kg_engine.model import Edge, Node, compression_id, edge_id
from kg_engine.projector import Projector

REPO = Path(__file__).resolve().parents[1]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _ranked(canon: Canon, edges, *, corpus="## a\n## b\n## c", labels=None):
    """Write a graph into the canon and return the projected, rank-attributed in-memory graph."""
    labels = labels or {}
    nm: dict = {}
    for s, t in edges:
        nm.setdefault(s, []).append(Edge(source=s, target=t, relation="bridges", span="x"))
        nm.setdefault(t, [])
    nodes = [Node(id=k, label=labels.get(k, k), node_type="claim", edges=v) for k, v in nm.items()]
    canon.write_nodes(nodes, message="seed generate fixture")
    proj = Projector(canon, source_text=corpus)
    proj.project(incremental=False)
    return proj.load_graph()


def _stars(hubs: dict) -> list:
    """Disconnected stars, {hub: leaf count}. Each is a connected component of its own, so the projection gives each
    its own community and no node a neighbour in a second one: no structural bridge, as on the field graph."""
    return [(h, f"{h}-leaf{i}") for h, n in hubs.items() for i in range(n)]


def _set(G, attr: str, values: dict, default=None):
    for n in G.nodes():
        v = values.get(n, default)
        if v is not None:
            G.nodes[n][attr] = v


def _old_strength(G, n, gate_on):
    """The 0.15.2 rule, to show what the field run ranked by."""
    if gate_on:
        return float(G.nodes[n].get("spec_betweenness", 0.0))
    return float(G.nodes[n].get("structural_bridge", 0)) + 1e-6 * float(G.nodes[n].get("degree", 0))


def _pairs(cands) -> list:
    return [frozenset((c.source, c.target)) for c in cands]


def _slots(cands) -> collections.Counter:
    return collections.Counter(n for c in cands for n in (c.source, c.target))


# ---- (c) the gate-off strength is weighted by specificity -----------------------------------------------------


def test_with_no_structural_bridge_a_generic_hub_no_longer_wins_on_links_alone(canon: Canon, monkeypatch):
    G = _ranked(canon, _stars({"system": 3, "falsification": 2, "reconciler": 2}))
    assert not any(G.nodes[n].get("structural_bridge") for n in G.nodes())    # the field premise
    _set(G, "gate_on", {}, default=0)
    _set(G, "specificity", {"falsification": 4.0, "reconciler": 4.0}, default=1.0)
    top = gen.bridge(G, failures=set(), k=10)[0]
    assert {top.source, top.target} == {"falsification", "reconciler"}       # 8e-6 + 8e-6 > 3e-6 + 8e-6
    assert top.rationale.endswith("via degree × specificity; neither end is a structural bridge")
    assert "strength=1.6e-05" in top.rationale                              # 0.15.2 printed 0.0000
    # 0.15.2 ranked the same graph by links alone: the generic hub took the first pair
    monkeypatch.setattr(gen, "_bridge_strength", _old_strength)
    old_top = gen.bridge(G, failures=set(), k=10)[0]
    assert "system" in {old_top.source, old_top.target}


def test_the_strength_is_the_old_one_times_the_nodes_specificity(canon: Canon):
    G = _ranked(canon, _stars({"system": 3, "falsification": 2}))
    _set(G, "specificity", {"system": 1.5, "falsification": 3.25}, default=2.0)
    for n in G.nodes():
        assert gen._bridge_strength(G, n, 0) == pytest.approx(_old_strength(G, n, 0) * G.nodes[n]["specificity"])
    # with the gate on, spec_betweenness is already specificity-weighted and stays the strength
    _set(G, "spec_betweenness", {"system": 0.25}, default=0.0)
    assert gen._bridge_strength(G, "system", 1) == 0.25


def test_with_no_specificity_spread_the_order_is_the_old_one(canon: Canon, monkeypatch):
    G = _ranked(canon, _stars({"h": 5, "a": 3, "b": 2, "c": 2}))
    _set(G, "gate_on", {}, default=0)
    _set(G, "specificity", {}, default=2.5)                                 # every node alike: no IDF spread
    new = _pairs(gen.bridge(G, failures=set(), k=10))
    monkeypatch.setattr(gen, "_bridge_strength", _old_strength)
    assert _pairs(gen.bridge(G, failures=set(), k=10)) == new


# ---- (b) no endpoint takes more than two slots -----------------------------------------------------------------

# the field shape: one node with 12 links, ten other communities whose top nodes have 3
_FIELD = {"hub": 12, **{f"c{i}": 3 for i in range(10)}}


def test_one_node_takes_at_most_two_slots_of_the_bridge_slate(canon: Canon, monkeypatch):
    G = _ranked(canon, _stars(_FIELD))
    _set(G, "gate_on", {}, default=0)
    _set(G, "specificity", {}, default=1.0)
    cands = gen.bridge(G, failures=set(), k=10)
    assert len(cands) == 10
    assert max(_slots(cands).values()) <= gen.ENDPOINT_CAP == 2
    assert _slots(cands)["hub"] == 2 and "hub" in {cands[0].source, cands[0].target}  # still a hub, first
    # without the cap the field graph's slate came back: ten pairs, all with the hub
    monkeypatch.setattr(gen, "_rank_spread", lambda c, k, cap=2: gen._rank(c, k))
    assert all("hub" in p for p in _pairs(gen.bridge(G, failures=set(), k=10)))


def test_the_cap_holds_with_the_gate_on(canon: Canon):
    # the replayed second run: the gate on, the hub's spec_betweenness far above every other node's
    G = _ranked(canon, _stars(_FIELD))
    _set(G, "gate_on", {}, default=1)
    _set(G, "spec_betweenness", {"hub": 0.0549, **{f"c{i}": 0.01 for i in range(10)}}, default=0.001)
    cands = gen.bridge(G, failures=set(), k=10)
    assert len(cands) == 10 and max(_slots(cands).values()) <= 2 and _slots(cands)["hub"] == 2


def test_a_shorter_run_keeps_what_a_longer_one_keeps_first(canon: Canon):
    """run_generators runs a mechanism at a large k for the convergence tally and surfaces its first k, so the
    capped slate at k must be the first k of the capped slate at any larger k."""
    G = _ranked(canon, _stars(_FIELD))
    _set(G, "gate_on", {}, default=0)
    full = _pairs(gen.bridge(G, failures=set(), k=10_000))
    for k in range(0, 12):
        assert _pairs(gen.bridge(G, failures=set(), k=k)) == full[:k]
    assert _pairs(gen.run_generators(G, "bridge", failures=set(), k=10)) == full[:10]


def test_regroup_shares_its_slate_the_same_way(canon: Canon):
    # one star is one stored community; split into singletons, every leaf pair is an invisible bridge
    G = _ranked(canon, _stars({"hub": 6}))
    assert len({G.nodes[n].get("community") for n in G.nodes()}) == 1
    singletons = {n: i for i, n in enumerate(G.nodes())}
    cands = gen.regroup(G, failures=set(), k=20, new_comm=singletons)
    assert cands and max(_slots(cands).values()) <= 2
    assert len(cands) == 6                                                  # six leaves, two slots each


def test_rank_spread_walks_the_ranked_list_in_order():
    def cand(u, v, score):
        return gen._edge_cand("bridge", u, v, "bridges", score=score, specificity=1.0, rationale="r", section="s")
    cs = [cand("h", "a", 9), cand("h", "b", 8), cand("h", "c", 7), cand("a", "b", 6), cand("a", "c", 5),
          cand("b", "c", 4)]
    # (h,c) waits on h's two slots; (a,b) fits, since neither end has two yet; then a and b are full
    assert gen._rank_spread(cs, 10) == [cs[0], cs[1], cs[3]]
    assert gen._rank_spread(cs, 10, cap=1) == [cs[0], cs[5]]


# ---- unjudged hypotheses are counted and said ------------------------------------------------------------------


def _seed(engine):
    engine.kg_write({"edges": [
        {"source": "compression", "target": "claim", "relation": "grounds",
         "span": "grounds the claims beneath it", "authored_by": "agent"},
        {"source": "betweenness", "target": "generality-confound", "relation": "confounded_by",
         "span": "Betweenness is confounded by the generality confound", "authored_by": "agent"},
        {"source": "degree", "target": "importance", "relation": "approximates",
         "span": "Degree approximates importance", "authored_by": "agent"},
        {"source": "entropy", "target": "arrow", "relation": "grounds",
         "span": "Entropy grounds the arrow of time", "authored_by": "agent"},
    ]})


def test_kg_generate_counts_the_unjudged_hypotheses_and_says_to_ground_them(engine):
    _seed(engine)
    out = engine.kg_generate(mechanism="default", k=5)
    # four unverified edges, but span-present: a fresh extraction is not a proposal
    assert out["unjudged_hypotheses"] == 0 and "kg-ground" not in out["note"]
    got = engine.kg_propose({"edges": [{"source": "entropy", "target": "importance", "relation": "bridges",
                                        "provenance": "hypothesized", "notes": "bridge: a test proposal"}]})
    assert got["dispositions"]["ACCEPTED"] == 1
    out = engine.kg_generate(mechanism="default", k=5)
    assert out["unjudged_hypotheses"] == 1
    assert ("1 hypothesized edge(s) are not judged yet and count as graph structure here, so these candidates were "
            "ranked partly on earlier proposals; run /burgess:kg-ground first to rank on the judged graph") \
        in out["note"]
    # once judged it is no longer a proposal waiting (a rejection also leaves the live topology)
    assert engine.kg_ground(edge_id("entropy", "bridges", "importance"), "rejected")["ok"]
    out = engine.kg_generate(mechanism="default", k=5)
    assert out["unjudged_hypotheses"] == 0 and "kg-ground" not in out["note"]


def test_the_count_sits_beside_the_other_ensemble_note(engine):
    _seed(engine)
    engine.kg_propose({"edges": [{"source": "entropy", "target": "importance", "relation": "bridges",
                                  "provenance": "hypothesized"}]})
    out = engine.kg_generate(mechanism="all", k=3)
    assert out["note"].startswith("no second construction supplied; ensemble degraded to regroup")
    assert "; 1 hypothesized edge(s) are not judged yet" in out["note"]


# ---- a compression candidate carries its members and the collapse id -------------------------------------------


def _compressible(canon: Canon):
    a = list(itertools.combinations(["betweenness", "specificity", "reconciler", "falsification"], 2))
    b = list(itertools.combinations(["system", "idea", "thing", "notion"], 2))
    corpus = "\n".join(["## intro"] + ["## s the system idea thing notion common system idea thing"] * 15
                       + ["## s betweenness specificity reconciler falsification rare technical terms"])
    return _ranked(canon, a + b, corpus=corpus)


def test_a_compression_candidate_carries_its_members_and_the_collapse_id(canon: Canon):
    G = _compressible(canon)
    (c,) = gen.compression(G, failures=set(), k=10)
    assert c.members == ["betweenness", "falsification", "reconciler", "specificity"]
    assert c.rationale.endswith("collapses: " + ", ".join(c.members))
    assert c.id == compression_id(c.members) == "compression-betweenness-" + c.id.rsplit("-", 1)[1]
    # the id kg_operate collapse writes for the same members, in any order
    payload, comp_id = ops.collapse_payload(G, members=list(reversed(c.members)))
    assert comp_id == c.id
    assert sorted(e["source"] for e in payload["edges"]) == c.members
    assert {e["target"] for e in payload["edges"]} == {c.id}
    d = c.to_dict()
    assert d["members"] == c.members and d["id"] == c.id and d["label"] == ""


def test_an_edge_candidate_dict_is_unchanged(canon: Canon):
    G = _ranked(canon, _stars({"a": 2, "b": 2}))
    d = gen.bridge(G, failures=set(), k=1)[0].to_dict()
    assert set(d) == {"kind", "mechanism", "source", "target", "relation", "label", "node_type", "score",
                      "specificity", "rationale", "section", "convergence"}


def test_kg_generate_returns_the_star_to_write(engine):
    """Through the tool: the compression candidate carries what the language layer writes, and the star built from
    it goes through the propose lane as the engine's own collapse would, under the same id."""
    # a dense cluster written straight into the canon, as _ranked does: the screen needs a K4, and the write
    # boundary would hold spans to the source's sentences
    nm: dict = {}
    for u, v in itertools.combinations(["degree", "importance", "entropy", "arrow"], 2):
        nm.setdefault(u, []).append(Edge(source=u, target=v, relation="grounds", span="x"))
        nm.setdefault(v, [])
    engine.canon.write_nodes([Node(id=n, label=n, node_type="claim", edges=es) for n, es in nm.items()],
                             message="seed a compressible cluster")
    out = engine.kg_generate(mechanism="compression", k=5)
    nodes = [c for c in out["candidates"] if c["kind"] == "node"]
    assert nodes, out
    c = nodes[0]
    assert c["id"] == compression_id(c["members"])
    star = {"nodes": [{"id": c["id"], "label": "A test compression", "node_type": "compression",
                       "provenance": "hypothesized", "body": "Compresses the test cluster."}],
            "edges": [{"source": m, "target": c["id"], "relation": "collapses_into", "provenance": "hypothesized"}
                      for m in c["members"]]}
    got = engine.kg_propose(star)
    assert got["dispositions"]["ACCEPTED"] == 1 + len(c["members"])
    node = engine.get_node(c["id"])
    assert node["provenance"] == "hypothesized" and node["degree"] == len(c["members"])


def test_the_moved_id_rule_gives_the_field_canons_ids():
    """The four ids the field session wrote by hand on 2026-11-14 with the old rule."""
    assert compression_id(["busqueda-externa", "conocimiento-ausente-o-cambiante", "context-rot",
                           "recuperacion"]) == "compression-busqueda-externa-8995eae3"
    assert compression_id(["sobreajuste", "conjunto-oculto", "escenarios-reservados", "llm-como-juez",
                           "manipulacion-de-tests", "tests-protegidos"]) == "compression-conjunto-oculto-7c08c8fc"


# ---- the contract says to write the star, and the command says when the slate fed on proposals -----------------


def test_the_generator_writes_a_compression_as_its_star():
    text = _flat((REPO / "agents" / "generator.md").read_text(encoding="utf-8"))
    assert ("**Write a compression as a star:** the node under the candidate's `id`, and one `collapses_into` edge "
            "from each of its `members` to that id") in text
    assert "Never make up an id, and never leave a member out." in text
    # the example payload is a real star: its id is the rule's id for its members, and every member points at it
    raw = (REPO / "agents" / "generator.md").read_text(encoding="utf-8")
    example = json.loads(re.search(r"```json\n(.*?)\n```", raw, re.S).group(1))
    (node,) = example["nodes"]
    star = [e for e in example["edges"] if e["relation"] == "collapses_into"]
    assert {e["target"] for e in star} == {node["id"]}
    assert node["id"] == compression_id([e["source"] for e in star])


def test_the_command_writes_the_star_and_reports_unjudged_proposals():
    text = _flat((REPO / "commands" / "kg-generate.md").read_text(encoding="utf-8"))
    assert "`{mechanism, k, gate_on, unjudged_hypotheses, count, candidates[], note}`" in text
    assert ("write a compression as its star: the node under its `id`, plus one collapses_into edge from each of "
            "its `members` to that id") in text
    assert ("If `unjudged_hypotheses` is above 0, earlier proposals are still waiting for `/burgess:kg-ground`."
            in text)
    assert "It is a warning, not a gate: generation is never gatekept (the inversion)." in text
    assert "A `bridge` or `regroup` slate gives no node more than two slots" in text
