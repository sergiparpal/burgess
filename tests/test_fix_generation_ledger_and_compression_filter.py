"""0.17.0: compression offers nothing an earlier generation proposed, and the absorption ledger is the engine's.

Field run (2026-11-15, 0.16.1). The second `/burgess:kg-generate` on the field graph ran the default set at k=10.
The bridge cap and the star contract held, and all 26 written items were accepted. Two things went wrong:
- **Compression offered four candidates, and none of them was new.**
  - Two came back under the exact ids, so with the exact members, of the two compressions the field
    `/burgess:kg-ground` had rejected the day before. `compression` took the failure memory and never read it.
    The session dropped both by hand and wrote itself a rule to check every later run.
  - The other two held a compression grounded the day before, with nearly every member it had been proposed
    over. Their 14 star edges asked again memberships the grounders had already rejected against the older
    node (the gap 0.16.0 left open).
- **The ledger needed a shell.** Step 4 of the command was a sketch. Each session wrote its own script and ran
  it through the Bash tool, which writes outside the project, so the user was asked every time. That run's
  write waited nine hours for the approval.

So, in this release:
- compression leaves out a community a live compression node was already proposed over (at least half of the
  other members have a `collapses_into` edge into it, in any state), and a candidate whose id is already a
  node, judged or not; `kg_generate` lists both in `compression_skipped` and says so in `note`. A cluster that
  grew round an old compression can still be compressed: on the field graph with its unjudged proposals live,
  any compression node in a community would have blocked two larger clusters;
- `kg_record_generation` writes the ledger `kg_absorption` reads, and `/burgess:kg-generate` holds no shell.
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest
import yaml

from kg_engine import generate as gen
from kg_engine.canon import Canon
from kg_engine.model import Edge, EpistemicState, Node, Provenance, compression_id, edge_id
from kg_engine.projector import Projector
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
COMMAND = REPO / "commands" / "kg-generate.md"

# Cluster A's words are rare in the corpus (specific); cluster B's are common (vague). A passes the §7
# specificity screen and B does not, so A is the one community compression can offer.
CORPUS = "\n".join(["## intro"] + ["## s the system idea thing notion common system idea thing"] * 15
                   + ["## s betweenness specificity reconciler falsification entropy tensor rare technical terms"])
A = ["betweenness", "falsification", "reconciler", "specificity"]
A6 = sorted(A + ["entropy", "tensor"])
B = ["idea", "notion", "system", "thing"]
A_ID = compression_id(A)


def _clusters(extra=(), a=A) -> dict:
    """Complete clusters `a` (A by default) and B as {node id: [edges]}, plus `extra` (source, relation, target,
    state) edges."""
    nm: dict = {n: [] for n in a + B}
    for members in (a, B):
        for s, t in itertools.combinations(members, 2):
            nm[s].append(Edge(source=s, target=t, relation="bridges", span="x"))
    for s, rel, t, state in extra:
        nm.setdefault(s, []).append(Edge(source=s, target=t, relation=rel, span="x", epistemic_state=state))
        nm.setdefault(t, [])
    return nm


def _graph(canon: Canon, nm: dict, special: dict | None = None):
    """Write the nodes, `special` ones as given ({id: Node kwargs}), project, return the ranked graph."""
    special = special or {}
    nodes = [Node(id=k, label=k, node_type="claim", edges=v) for k, v in nm.items() if k not in special]
    nodes += [Node(id=k, edges=nm.get(k, []), **kw) for k, kw in special.items()]
    canon.write_nodes(nodes, message="seed compression fixture")
    proj = Projector(canon, source_text=CORPUS)
    proj.project(incremental=False)
    return proj.load_graph()


def _compression_node(label="betweenness reconciler", state=EpistemicState.GROUNDED,
                      provenance=Provenance.SPAN_PRESENT) -> dict:
    return {"label": label, "node_type": "compression", "epistemic_state": state, "provenance": provenance}


# --------------------------------------------------------------------------- compression


def test_compression_offers_cluster_a_alone(canon: Canon):
    """The fixture's baseline: cluster A is the one community compression offers, under the id of its members."""
    (c,) = gen.compression(_graph(canon, _clusters()), failures=set())
    assert c.members == A and c.id == A_ID


@pytest.mark.parametrize("state", [EpistemicState.GROUNDED, EpistemicState.UNVERIFIED])
def test_a_community_a_live_compression_node_was_proposed_over_is_not_compressed_again(canon: Canon, state):
    """As on the field graph: a compression of cluster A sits in A's community through one live star edge,
    and was proposed over half of A (one star edge grounded, one rejected). Through 0.16.1 compression offered
    the community again with that node as a member (a `compression-compression-…` id), grounded or not yet
    judged."""
    star = [("betweenness", "collapses_into", "comp-a", EpistemicState.GROUNDED),
            ("reconciler", "collapses_into", "comp-a", EpistemicState.REJECTED)]
    G = _graph(canon, _clusters(star), {"comp-a": _compression_node(state=state)})
    assert G.nodes["comp-a"]["community"] == G.nodes["betweenness"]["community"]
    assert gen.compression(G, failures=set()) == []
    assert gen.compression_skips(G) == {"already_compressed": ["comp-a"], "already_proposed": {}}


def test_a_cluster_that_grew_round_an_old_compression_can_still_be_compressed(canon: Canon):
    """A live compression proposed over one member of a six-node cluster does not stand for the cluster. The
    new candidate holds the old node as a member, as it did through 0.16.1."""
    star = [("betweenness", "collapses_into", "comp-a", EpistemicState.GROUNDED)]
    G = _graph(canon, _clusters(star, a=A6), {"comp-a": _compression_node()})
    assert G.nodes["comp-a"]["community"] == G.nodes["betweenness"]["community"]
    (c,) = gen.compression(G, failures=set())
    assert c.members == sorted(A6 + ["comp-a"])
    assert gen.compression_skips(G) == {"already_compressed": [], "already_proposed": {}}


def test_a_rejected_compression_node_does_not_hold_its_community(canon: Canon):
    """A compression node in a non-live state stands for nothing: with its star rejected it is not in the
    community, and the community is offered under its own id."""
    star = [("betweenness", "collapses_into", "comp-a", EpistemicState.REJECTED)]
    G = _graph(canon, _clusters(star),
               {"comp-a": _compression_node(state=EpistemicState.REJECTED, provenance=Provenance.HYPOTHESIZED)})
    (c,) = gen.compression(G, failures=set())
    assert c.members == A and c.id == A_ID


@pytest.mark.parametrize("state", [EpistemicState.REJECTED, EpistemicState.GROUNDED, EpistemicState.UNVERIFIED])
def test_a_candidate_whose_id_is_already_a_node_is_not_offered_again(canon: Canon, state):
    """The id is a function of the members, so an existing node under it is the same proposal. Rejected, it is
    failure memory; grounded or not judged, it is already proposed. The node here has no live edge, so it is
    not in the community it was proposed for, as the two field compressions rejected on 2026-11-14 were not."""
    G = _graph(canon, _clusters(),
               {A_ID: _compression_node(label="system idea", state=state, provenance=Provenance.HYPOTHESIZED)})
    assert gen.compression(G, failures=set()) == []
    assert gen.compression_skips(G) == {"already_compressed": [], "already_proposed": {A_ID: state.value}}


def test_kg_generate_reports_what_compression_left_out(vault, tmp_path):
    src = tmp_path / "corpus.md"
    src.write_text(CORPUS, encoding="utf-8")
    engine = KGEngine(vault, source_path=src, pack_path=PACK)
    nm = _clusters()
    engine.canon.write_nodes(
        [Node(id=k, label=k, node_type="claim", edges=v) for k, v in nm.items()]
        + [Node(id=A_ID, label="system idea", node_type="compression", provenance=Provenance.HYPOTHESIZED,
                epistemic_state=EpistemicState.REJECTED)], message="seed")
    out = engine.kg_generate(mechanism="compression", k=10)
    assert [c for c in out["candidates"] if c["kind"] == "node"] == []
    assert out["compression_skipped"] == {"already_compressed": [], "already_proposed": {A_ID: "rejected"}}
    assert out["note"] == f"compression left out candidates whose id is already a node ({A_ID}: rejected)"
    assert "compression_skipped" not in engine.kg_generate(mechanism="bridge", k=10)
    assert "compression_skipped" in engine.kg_generate(mechanism="default", k=10)


# --------------------------------------------------------------------------- the ledger


def _propose_star(engine, cid="comp-a", members=("m1", "m2")):
    out = engine.kg_propose({
        "nodes": [{"id": cid, "label": "A compression", "node_type": "compression"}],
        "edges": [{"source": m, "target": cid, "relation": "collapses_into"} for m in members]})
    assert out["dispositions"]["ACCEPTED"] == 1 + len(members)
    return cid


def _ledger(engine) -> dict:
    return json.loads((engine.projector.derived / "generations.json").read_text(encoding="utf-8"))


def test_record_generation_starts_the_ledger_where_kg_absorption_reads_it(engine):
    cid = _propose_star(engine)
    out = engine.kg_record_generation({cid: "compression"})
    entry = {"introduced_at": 1, "introduced_degree": 2, "mechanism": "compression"}
    assert out == {"ok": True, "generation": 1, "tracked": 1, "recorded": {cid: entry}, "skipped": {}}
    assert _ledger(engine) == {"generation": 1, "tracked": {cid: entry}}
    absorbed = engine.kg_absorption()
    assert absorbed["tracked"] == 1 and absorbed["not_scored"] == {cid: "unverified"}


def test_record_generation_extends_a_ledger_and_keeps_what_it_tracks(engine):
    cid = _propose_star(engine)
    old = {"introduced_at": 1, "introduced_degree": 6, "mechanism": "compression"}
    engine.projector.derived.mkdir(parents=True, exist_ok=True)
    (engine.projector.derived / "generations.json").write_text(
        json.dumps({"generation": 2, "tracked": {"comp-old": old}}), encoding="utf-8")
    out = engine.kg_record_generation({cid: "compression", "comp-old": "compression"})
    assert out["generation"] == 3 and out["tracked"] == 2
    assert out["skipped"] == {"comp-old": "already tracked since generation 1"}
    assert _ledger(engine)["tracked"] == {
        "comp-old": old, cid: {"introduced_at": 3, "introduced_degree": 2, "mechanism": "compression"}}


def test_record_generation_skips_what_is_not_a_new_proposal(engine):
    cid = _propose_star(engine)
    engine.canon.write_one(Node(id="plain", label="Plain", provenance=Provenance.SPAN_PRESENT))
    out = engine.kg_record_generation({"ghost": "compression", "plain": "compression", cid: "  "})
    assert out["ok"] and out["recorded"] == {} and out["generation"] == 1
    assert out["skipped"] == {"ghost": "not in the canon",
                              "plain": "not a proposal: its provenance is span-present",
                              cid: "give the mechanism that proposed it, in a word"}


def test_a_run_with_no_new_node_still_advances_the_clock(engine):
    assert engine.kg_record_generation(None)["generation"] == 1
    assert engine.kg_record_generation({})["generation"] == 2
    assert _ledger(engine) == {"generation": 2, "tracked": {}}


def test_the_recorded_degree_counts_live_edges_only(engine):
    """As kg_absorption counts it: a star edge already rejected is not the node's degree."""
    cid = _propose_star(engine)
    assert engine.kg_ground(edge_id("m2", "collapses_into", cid), "rejected", note="no-support")["ok"]
    assert engine.kg_record_generation({cid: "compression"})["recorded"][cid]["introduced_degree"] == 1


def test_a_ledger_the_engine_cannot_read_is_left_alone(engine):
    path = engine.projector.derived / "generations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for text in ("not json", json.dumps({"generation": "two", "tracked": {}}), json.dumps([1, 2])):
        path.write_text(text, encoding="utf-8")
        out = engine.kg_record_generation({})
        assert out["ok"] is False and "nothing recorded" in out["error"]
        assert path.read_text(encoding="utf-8") == text


def test_the_bare_record_shape_kg_absorption_reads_is_extended(engine):
    engine.projector.derived.mkdir(parents=True, exist_ok=True)
    rec = {"introduced_at": 3, "introduced_degree": 1, "mechanism": "compression"}
    (engine.projector.derived / "generations.json").write_text(json.dumps({"comp-old": rec}), encoding="utf-8")
    assert engine.kg_record_generation({})["generation"] == 4
    assert _ledger(engine) == {"generation": 4, "tracked": {"comp-old": rec}}


def test_a_recorded_node_is_scored_once_it_is_grounded(engine):
    cid = _propose_star(engine)
    engine.kg_record_generation({cid: "compression"})
    assert engine.kg_ground(cid, "grounded", kind="node",
                            support_span="A compression stands in for many observations")["ok"]
    assert engine.kg_ground(edge_id("m1", "collapses_into", cid), "grounded",
                            support_span="The canon grounds trust")["ok"]
    assert engine.kg_ground(edge_id("m2", "collapses_into", cid), "rejected", note="no-support")["ok"]
    node = engine.kg_absorption()["nodes"][cid]
    assert node["introduced_degree"] == 2 and node["current_degree"] == 1 and node["status"] == "fertile"


def test_the_mcp_wrapper_takes_an_optional_map(engine):
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self, *a, **k):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn
            return deco

    mcp = FakeMCP()
    _register(mcp, engine)
    assert mcp.tools["kg_record_generation"]()["generation"] == 1
    assert mcp.tools["kg_record_generation"](nodes={})["generation"] == 2


# --------------------------------------------------------------------------- the command


def _frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    return yaml.safe_load(raw.split("---", 2)[1])


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def test_the_command_records_the_run_through_the_engine_and_holds_no_shell():
    grants = [t.strip() for t in _frontmatter(COMMAND)["allowed-tools"].split(",")]
    assert "Bash" not in grants
    assert "mcp__plugin_burgess_burgess__kg_record_generation" in grants
    text = _flat(COMMAND)
    assert "This command needs no shell and no file access." in text
    assert 'Call `mcp__plugin_burgess_burgess__kg_record_generation(nodes={"<node id>": "<mechanism>", …})` once' in text
    assert "```bash" not in text


def test_the_command_says_what_compression_leaves_out_and_hands_on_every_candidate():
    text = _flat(COMMAND)
    assert "plus `compression_skipped` when compression ran" in text
    assert "So hand the kg-generator every candidate returned" in text
    assert ("and any compression whose id is already a node or whose community a live compression node "
            "was already proposed over (0.17.0)") in text
