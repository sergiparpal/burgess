"""The generative layer (PLAN_generative_layer §3): deterministic candidate generators.

This module holds **deterministic** candidate generators that read the derived graph + source +
pack and emit `hypothesized` candidates — *proposals from a discovery mechanism*, never text claims.
Each generator realises one mechanism from the source theory ("Conclusiones v6") and tags every
candidate with the § it implements.

The design contract (PLAN §1) every generator obeys:
  1. A candidate is `provenance=hypothesized`, `epistemic_state=unverified`, **with no span**. It is
     stored in a lane that can never be mistaken for grounded content.
  2. Generate offensively; judge defensively. Generation is NEVER gatekept by a quality metric — the
     existing grounding loop (`kg_ground`) is the post-hoc filter.
  3. Generality control travels with every generator (§4): structural rankings are
     specificity-weighted; compression candidates pass an MDL screen. No candidate ranks high merely
     for being generic. That includes the bridge fallback when the gate is off (0.16.0), and a pair
     ranked on its endpoints' strengths shares the slate: no endpoint takes more than ENDPOINT_CAP slots.
  4. Failure memory binds generation (§13): a candidate whose `(source, relation, target)` (or its
     reverse) is already in `FAILURE_STATES` is dropped on sight.

Generators are **pure and read-only**: they never write the canon. The `/kg-generate` command (Stage
6) routes their output through the propose lane (`kg_propose`, Stage 1).
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from .graphio import node_attr, node_link_graph
from .model import NON_LIVE_STATE_VALUES, compression_id, edge_id

# The edge epistemic_state string values the generators must treat as NON-live (§1.7). Generators build
# their adjacency/undirected topology over the SAME non-live-EXCLUDED subgraph that node ranks were
# computed over (projector._live_subgraph): a `failed`/`rejected` edge is negative information and an
# `obsolete` edge is superseded — neither may seed a spurious shared-neighbour bridge/seed/periphery
# candidate or inflate absorption density. Shared with the projector via model.NON_LIVE_STATE_VALUES so
# the two definitions cannot drift (review-r11: this set omitted `obsolete` while the projector's did not,
# so generators walked a topology the ranks they read were never computed over).
_NON_LIVE_VALUES = NON_LIVE_STATE_VALUES  # single vocabulary home in model (review-r5/r11)

# The mechanism vocabulary. The DEFAULT_SET is what `/kg-generate` runs unless the user opts into all
# seven (PLAN Stage 6 non-blocking survey). "all" runs ALL_SET.
DEFAULT_SET = ["bridge", "seed", "compression"]
# `periphery` (§5, low-degree sources) is ALL-only: it deliberately stays OUT of DEFAULT_SET so the
# default `/kg-generate` slate — and every golden expectation built on it — is byte-identical, exactly
# like regroup/transplant/ensemble. "all" runs ALL_SET.
ALL_SET = ["bridge", "seed", "compression", "regroup", "transplant", "ensemble", "periphery"]

# The relation emitted by every structural-bridge mechanism (bridge/seed/regroup/ensemble). It MUST
# exist in pack.yaml edge_types or the candidate is QUARANTINED at the kg_write boundary; and within a
# mechanism the failure-memory check and the emit must use the same string or failure memory silently
# never matches. transplant is exempt — it emits the hub's dynamic dominant relation, not this constant.
BRIDGES_RELATION = "bridges"

# The community id meaning "no community" — the sentinel _attr default for a node's "community" attr.
NO_COMMUNITY = -1

# The most slots one endpoint may take in a slate that ranks a pair by the SUM of its endpoints' strengths
# (bridge, and regroup with ensemble's degraded path, 0.16.0). A sum lets the strongest node pair with every
# other strong node before any pair without it. On the field graph of 2026-11-14, 10 of 10 bridges hung off
# one node. Replayed after those proposals were written, the next run did the same with the gate on. Two
# lets a hub show up as a hub and leaves the rest of the slate to the other pairs. The cap holds at every k:
# the selection walks the ranked list in order, so the first k it keeps are the same whatever the run's k.
ENDPOINT_CAP = 2

# seed (§3) all-pairs BFS size gate (perf #8). At or below this node count `seed` runs the EXACT
# original code path (unbounded BFS + full O(V^2) pair scan) so small graphs stay byte-identical with
# the golden/reproducibility expectations. Above it, BFS is bounded by SEED_BFS_CUTOFF (see `seed`).
SEED_ALLPAIRS_MAX_NODES = 400
# Convergence-tally exactness gate (review-r4: big-k-materializes-o(v2)-candidates). At or below this
# node count run_generators runs every mechanism UNTRUNCATED so the cross-mechanism convergence tally
# sees each full pre-truncation candidate list — the exact behavior the convergence-undercount fix
# introduced, and where every golden expectation lives. Above it, that full materialization (a
# Candidate object with a formatted rationale string per surviving pair, O(V^2) of them) is a real
# memory/time cliff, so mechanisms run at the surfaced k and the tally covers the union of the top-k
# lists only. The SURFACED slate is identical either way (slicing a full ranked list to k is
# byte-identical to ranking at k); `convergence` is an advisory ranking prior (G3/G4), so a possible
# undercount on a >400-node graph trades bounded precision for bounded cost.
FULL_TALLY_MAX_NODES = 400
# The cutoff radius the seed model actually consumes. seed scores a pair by the residual of its
# common-neighbour count; a shared neighbour can exist only at distance ≤ 2, so pairs at distance ≥ 3
# always score 0 and are dropped. Radius 2 enumerates every pair seed can ever turn into a candidate.
SEED_BFS_CUTOFF = 2

# Distinct "argument not supplied" sentinel for the re-partition memo (perf #13). The contract (the
# authoritative statement; downstream sites point here): None is a legitimate `_repartition` return
# value (both community algorithms failed and it fell back to no usable partition), so None cannot
# double as "not supplied" — `_UNSET` carries that meaning and a real None still flows through.
_UNSET = object()


@dataclass
class Candidate:
    """A single machine-proposed graph element, destined for the hypothesized write lane.

    `provenance` is always `hypothesized`, `epistemic_state` always `unverified`, and there is never
    a span — these are structural proposals, not text claims, so they are not carried on the dataclass
    (the propose lane forces them). An ensemble candidate may carry `passage`, where a second
    construction read its edge (0.19.0): context for the grounder, never the proposal's span.
    """
    kind: str            # "edge" | "node"
    mechanism: str       # "bridge" | "seed" | "compression" | "regroup" | "transplant" | "ensemble" | "periphery"
    source: str = ""     # for edges
    target: str = ""     # for edges
    relation: str = ""   # for edges (a pack edge_type)
    label: str = ""      # for nodes (e.g. a proposed compression)
    node_type: str = ""  # for nodes (a pack node_type)
    score: float = 0.0
    specificity: float = 0.0
    rationale: str = ""
    section: str = ""    # the source-theory § the mechanism implements
    convergence: int = 1  # advisory (§4): # of DISTINCT mechanisms that independently proposed this edge.
    # A RANKING PRIOR for the grounding queue — NEVER a score, NEVER a verdict, NEVER folded into
    # `score` or onto a canon edge (G3/G4). Set in run_generators' dedup pass; node candidates keep 1.
    # Node candidates only (0.16.0): the members a compression collapses and the id to write it under, the
    # one `kg_operate collapse` gives the same members (`model.compression_id`). Through 0.15.2 the members
    # were only in `rationale` and there was no id, so the language layer had to parse the one and invent
    # the other, and nothing said to write the `collapses_into` star the MDL screen scored.
    members: list = field(default_factory=list)
    id: str = ""
    # Ensemble edge candidates only (0.19.0): the passage the SECOND construction wrote this edge from,
    # `{"span", "source_file"}`. It is not the candidate's span (a proposal cites no text): `kg_propose` checks it
    # against the configured sources and keeps it for the grounder only when it holds there. Through 0.18.1
    # ensemble emitted every cross-construction pair as `bridges` with no text, so what the second reading had
    # found, and where, was lost before grounding (field test of 2026-11-16).
    passage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = asdict(self)
        if self.kind != "node":  # an edge candidate's dict is unchanged: its identity is its endpoints
            del d["members"], d["id"]
        if not self.passage:     # only an ensemble candidate read off a second construction carries one
            del d["passage"]
        return d


# --------------------------------------------------------------------------- shared helpers


# The node-attr accessor now lives in the graphio leaf, so operations.py imports it there instead of
# reaching into this module's privates (it used to `from .generate import _attr`). Kept as a local alias
# for this module's own internal call sites.
_attr = node_attr


def _gate_on(G) -> int:
    n = next(iter(G.nodes()), None)  # graph-level flag stamped on every node; read it off the first
    return 0 if n is None else int(_attr(G, n, "gate_on", 0))


def _mean_specificity(G) -> float:
    vals = [float(_attr(G, n, "specificity", 1.0)) for n in G.nodes()]
    return (sum(vals) / len(vals)) if vals else 1.0


def _bridge_strength(G, n, gate_on: int) -> float:
    """The endpoint's bridging strength under the generality control (PLAN §4). When the gate is ON,
    trust spec_betweenness (the confound-corrected metric); when OFF, fall back to the honest
    structural-bridge flag, tie-broken by degree — never raw betweenness, which the confound inflates.

    The fallback is weighted by the node's specificity, as spec_betweenness weights betweenness (0.16.0).
    Through 0.15.2 it was not. On the field graph of 2026-11-14 no node was a structural bridge, so the
    strength was degree alone. A degree leader is confounded by generality just as a betweenness leader
    is, and the bridge slate paired the node with the most links with the top node of every other
    community: radar-meta, specificity 1.74 against a graph mean of 2.81. With no IDF spread every node
    has the same specificity, the weighting is a constant factor, and the order is the old one."""
    if gate_on:
        return float(_attr(G, n, "spec_betweenness", 0.0))
    structural = float(_attr(G, n, "structural_bridge", 0)) + 1e-6 * float(_attr(G, n, "degree", 0))
    return structural * float(_attr(G, n, "specificity", 1.0))


def _pair_specificity(G, a, b) -> float:
    """A candidate's specificity is the MIN of its two endpoints' specificity, defaulting to 1.0 — the
    §4 generality-control rule shared by every edge mechanism (no candidate ranks high for being generic)."""
    return min(float(_attr(G, a, "specificity", 1.0)), float(_attr(G, b, "specificity", 1.0)))


def _live_undirected(G):
    """Undirected projection with the NON-LIVE edges excluded — `failed`/`rejected` (§1.7) and `obsolete`
    (superseded) — mirroring projector._live_subgraph so generators walk the SAME live topology their node
    ranks were computed over. The exclusion set is `model.NON_LIVE_STATE_VALUES`, shared with the projector
    so this claim stays TRUE (review-r11: it once said "mirroring" while omitting `obsolete`).
    Nodes are all kept (an attacked hub whose edges are all refuted still appears at degree 0)."""
    live = nx.MultiDiGraph()
    live.add_nodes_from(G.nodes(data=True))
    live.add_edges_from((u, v, k, d) for u, v, k, d in G.edges(keys=True, data=True)
                        if d.get("epistemic_state") not in _NON_LIVE_VALUES)
    return live.to_undirected()


def _undirected_adjacency(G) -> dict:
    adj: dict = defaultdict(set)
    for u, v, st in G.edges(data="epistemic_state"):
        if u != v and st not in _NON_LIVE_VALUES:  # failure memory is not live topology (§1.7)
            adj[u].add(v)
            adj[v].add(u)
    return adj


def _internal_edge_count(und, members: set) -> int:
    """Count undirected internal edges among `members`, each counted exactly once (frozenset-dedup).
    Feeds compression's MDL screen and transplant's absorption-capacity density proxy."""
    return len({frozenset((u, v)) for u in members for v in und.neighbors(u)
                if v in members and u != v})


def _members_by_community(G) -> dict:
    """Group node ids by their stored community attr (NO_COMMUNITY default), as a defaultdict(list)."""
    by_comm: dict = defaultdict(list)
    for n in G.nodes():
        by_comm[_attr(G, n, "community", NO_COMMUNITY)].append(n)
    return by_comm


def _resolve_und(G, und):
    """Lazy shared-structure resolution (perf #12), ONE rule for every mechanism (review-r5: the
    `if x is None: build` contract was copy-pasted six ways). On a full `kg_generate('all')` run
    run_generators builds these once and threads them in; a standalone mechanism call passes None
    and builds lazily here — byte-for-byte identical either way (same constructors)."""
    return und if und is not None else _live_undirected(G)


def _resolve_adj(G, adj):
    """The adjacency twin of `_resolve_und` (see there)."""
    return adj if adj is not None else _undirected_adjacency(G)


def _strength_map(G) -> "tuple[int, dict]":
    """(gate_on, {node: generality-controlled bridging strength}) — the endpoint-strength setup
    bridge and regroup shared verbatim (review-r5); precomputed once per mechanism run (perf)."""
    gate_on = _gate_on(G)
    return gate_on, {n: _bridge_strength(G, n, gate_on) for n in G.nodes()}


def _is_failure(failures: set, source: str, relation: str, target: str) -> bool:
    """invariant 5 (PLAN §13): a candidate edge whose identity OR its reverse already lives in failure
    memory is dropped on sight — generation never re-proposes what was refuted.

    Called once per candidate pair, so it runs O(n^2) times per mechanism. Building both `edge_id`s costs
    six `slug` calls; against an EMPTY failure set — the common case, before any adversarial grounding has
    produced a `failed`/`rejected` edge — every one of them is wasted, since nothing can be a member of
    an empty set. Short-circuit first (review-r11: ~1.1s of pointless work per 200k pairs)."""
    if not failures:
        return False
    return (edge_id(source, relation, target) in failures
            or edge_id(target, relation, source) in failures)


def _rank(cands: list, k: int) -> list:
    """Deterministic ordering: stable sort by score DESC, tie-broken by a stable identity so repeated
    runs over the same graph are byte-identical (PLAN §"deterministic ordering")."""
    def key(c):
        ident = (c.source, c.relation, c.target, c.label, c.node_type)
        return (-c.score, ident)
    return sorted(cands, key=key)[: max(0, int(k))]


def _rank_spread(cands: list, k: int, cap: int = ENDPOINT_CAP) -> list:
    """`_rank`'s order, keeping a candidate only while both of its endpoints have taken fewer than `cap`
    slots (see ENDPOINT_CAP). It walks the whole ranked list and decides each candidate on the ones kept
    before it, so cutting at k keeps exactly what a larger k keeps first. `run_generators` relies on that:
    it runs a mechanism at a large k for the convergence tally and surfaces the first k."""
    k = max(0, int(k))
    kept: list = []
    slots: dict = defaultdict(int)
    for c in _rank(cands, len(cands)):
        if len(kept) >= k:
            break
        if slots[c.source] >= cap or slots[c.target] >= cap:
            continue
        slots[c.source] += 1
        slots[c.target] += 1
        kept.append(c)
    return kept


def _edge_cand(mechanism, source, target, relation, *, score, specificity, rationale, section, passage=None):
    return Candidate(kind="edge", mechanism=mechanism, source=source, target=target, relation=relation,
                     score=round(float(score), 6), specificity=round(float(specificity), 4),
                     rationale=rationale, section=section, passage=dict(passage or {}))


# --------------------------------------------------------------------------- the mechanisms (six core + periphery §5)


def _bridge_basis(G, u, v, gate_on: int) -> str:
    """What a bridge pair's strength was computed from, for its rationale. The field session of 2026-11-14
    read "strength=0.0000 via structural-bridge" as naming radar-meta the graph's only structural bridge,
    when no node was one and the rank was degree alone (0.16.0)."""
    if gate_on:
        return "spec_betweenness"
    if _attr(G, u, "structural_bridge", 0) or _attr(G, v, "structural_bridge", 0):
        return "structural-bridge × specificity"
    return "degree × specificity; neither end is a structural bridge"


def bridge(G, *, failures, k=10, adj=None) -> list:
    """§2/§4 — generate FROM the bridges (Swanson literature-based discovery, structurally). Rank
    non-adjacent, cross-community node pairs by the combined bridging strength of their endpoints; the
    strength is generality-controlled (spec_betweenness when the gate is on, structural-bridge/degree
    weighted by specificity otherwise). Connecting two strong-but-separate hubs creates a shortcut the
    graph lacked. No endpoint takes more than ENDPOINT_CAP slots of the slate (0.16.0)."""
    gate_on, strength = _strength_map(G)
    adj = _resolve_adj(G, adj)
    nodes = list(G.nodes())
    cands: list = []
    for i, u in enumerate(nodes):
        su = strength[u]
        if su <= 0:
            continue
        cu = _attr(G, u, "community", NO_COMMUNITY)
        for v in nodes[i + 1:]:
            if v in adj[u] or _attr(G, v, "community", NO_COMMUNITY) == cu:
                continue  # already connected, or same community (not a cross-community bridge)
            sv = strength[v]
            if sv <= 0:
                continue
            if _is_failure(failures, u, BRIDGES_RELATION, v):
                continue
            spec = _pair_specificity(G, u, v)
            score = su + sv
            # `:.3g`, not `:.4f`: a fallback strength without a structural bridge is ~1e-5, which `.4f`
            # printed as 0.0000 (0.16.0)
            cands.append(_edge_cand(
                "bridge", u, v, BRIDGES_RELATION, score=score, specificity=spec, section="§2/§4",
                rationale=(f"cross-community bridge: {_attr(G, u, 'label', u)} (c{cu}) ⇄ "
                           f"{_attr(G, v, 'label', v)} (c{_attr(G, v, 'community', NO_COMMUNITY)}); "
                           f"strength={score:.3g} via {_bridge_basis(G, u, v, gate_on)}")))
    return _rank_spread(cands, k)


def seed(G, *, failures, k=10, und=None, adj=None) -> list:
    """§3 — the residual, not the product. For each non-adjacent connected pair compute graph distance
    d and a connectability proxy c (common-neighbour count). Fit E[c|d] as the mean c per distance, and
    score by the POSITIVE residual c - E[c|d] — "abnormally connectable for its distance." We do NOT
    multiply d×c (the source rejects that as double-counting one tension)."""
    und, adj = _resolve_und(G, und), _resolve_adj(G, adj)
    nodes = list(G.nodes())
    # gather (u, v, d, c) for non-adjacent, connected pairs
    pairs: list = []
    by_dist: dict = defaultdict(list)
    # perf #8 — bound the all-pairs BFS ONLY above the size gate; small graphs keep the exact original
    # unbounded path (byte-identical golden output). cutoff=2 is exact, not an approximation: a model
    # candidate needs a POSITIVE residual c-E[c|d], and the proxy c is the common-neighbour count
    # (len(nbu & adj[v])). Two nodes share a common neighbour iff they are at distance ≤ 2, so every
    # pair at d ≥ 3 has c = 0; those pairs only contribute zeros to by_dist[d], giving E[c|d]=0 and
    # residual 0, which is dropped by the `residual <= 0` filter below. Thus no d ≥ 3 pair can ever
    # become a candidate, and refusing to enumerate them (cutoff=2) changes nothing the model consumes.
    cutoff = None if G.number_of_nodes() <= SEED_ALLPAIRS_MAX_NODES else SEED_BFS_CUTOFF
    for i, u in enumerate(nodes):
        try:
            dist = nx.single_source_shortest_path_length(und, u, cutoff=cutoff)
        except (nx.NetworkXError, nx.NodeNotFound):
            continue
        nbu = adj[u]
        for v in nodes[i + 1:]:
            if v in nbu:
                continue  # adjacent — nothing to seed
            d = dist.get(v)
            if d is None or d < 2:
                continue  # disconnected, beyond the cutoff radius, or already adjacent
            c = len(nbu & adj[v])  # common neighbours
            pairs.append([u, v, d, c])
            by_dist[d].append(c)
    exp = {d: (sum(cs) / len(cs)) for d, cs in by_dist.items()}  # E[c | d]
    cands: list = []
    for u, v, d, c in pairs:
        residual = c - exp.get(d, 0.0)
        if residual <= 0:
            continue  # only abnormally-connectable pairs (positive residual)
        if _is_failure(failures, u, BRIDGES_RELATION, v):
            continue
        spec = _pair_specificity(G, u, v)
        cands.append(_edge_cand(
            "seed", u, v, BRIDGES_RELATION, score=residual, specificity=spec, section="§3",
            rationale=(f"abnormally connectable for its distance: d={d}, shared neighbours={c} vs "
                       f"expected {exp.get(d, 0.0):.2f} (residual {residual:+.2f})")))
    return _rank(cands, k)


COMPRESSION_NODE_TYPE = "compression"
COLLAPSES_RELATION = "collapses_into"
# Why `_compression_screen` leaves out a community the MDL and specificity screens passed (0.17.0).
ALREADY_COMPRESSED = "already-compressed"
ALREADY_PROPOSED = "already-proposed"


def _compression_skip(G, members: list):
    """Why a community that passed the §7 screens is not a new compression, or None (0.17.0).

    - `(ALREADY_COMPRESSED, [ids])`: a live compression node among its members was already proposed over
      at least half of the other members, each of which has a `collapses_into` edge into it, in any
      state. A new compression would ask those memberships again. A compression node in a non-live state
      (rejected, failed, obsolete) stands for nothing, and one proposed over fewer members does not hold
      the community: a cluster that grew round an old compression can still be compressed.
    - `(ALREADY_PROPOSED, id)`: its id, a function of its members alone, is already a node of the graph,
      in any state. Rejected, it is failure memory; grounded or not yet judged, it is already proposed.

    Through 0.16.1 neither was checked. The second field `/burgess:kg-generate` (2026-11-15) offered four
    compressions: two held a compression grounded the day before, together with nearly every member it
    had been proposed over, and the other two came back under the ids of the two it had rejected. The
    session dropped the second pair by hand and wrote the first, whose star edges asked again memberships
    already rejected against the older node. Checking for any compression node in the community instead
    left out, on the same graph with its unjudged proposals live, two larger clusters that had merged
    round one."""
    member_set = set(members)
    covering = []
    for c in members:
        if (_attr(G, c, "node_type") != COMPRESSION_NODE_TYPE
                or _attr(G, c, "epistemic_state") in _NON_LIVE_VALUES):
            continue
        incoming = G.in_edges(c, data=True) if G.is_directed() else G.edges(c, data=True)
        asked = set()
        for u, v, d in incoming:
            other = v if u == c else u
            if other != c and other in member_set and d.get("relation") == COLLAPSES_RELATION:
                asked.add(other)
        if 2 * len(asked) >= len(member_set) - 1:
            covering.append(c)
    if covering:
        return ALREADY_COMPRESSED, sorted(covering)
    cid = compression_id(members)
    if cid in G:
        return ALREADY_PROPOSED, cid
    return None


def _compression_screen(G, und):
    """Every community that passes the §7 screens, as `(members sorted, internal edges, bits saved, mean
    member specificity, graph mean specificity, skip)`, where `skip` is `_compression_skip`'s answer.
    `compression` and `compression_skips` share this one walk, so a candidate and the report of what was
    left out cannot disagree."""
    mean_spec = _mean_specificity(G)
    by_comm = _members_by_community(G)
    N = max(G.number_of_nodes(), 2)
    bits = math.log2(N)
    for cid, members in by_comm.items():
        if cid == NO_COMMUNITY or len(members) < 3:
            continue
        mset = set(members)
        e_int, m = _internal_edge_count(und, mset), len(members)
        direct = e_int * 2 * bits                 # each internal edge: two endpoint ids
        compressed = (m + 1) * bits               # m collapses_into edges + the one new node
        if compressed >= direct:
            continue  # MDL screen: no description-length saving — not a real compression
        member_spec = sum(float(_attr(G, u, "specificity", mean_spec)) for u in members) / m
        if member_spec < mean_spec:
            continue  # vague compression rejected (§4 — generality control)
        ms = sorted(members)
        yield ms, e_int, direct - compressed, member_spec, mean_spec, _compression_skip(G, ms)


def compression(G, *, failures, k=10, und=None) -> list:
    """§7 — new NODES, not new edges. Detect dense communities and propose a `compression` node that
    `collapses_into`-links the members, but only when an MDL screen shows a description-length SAVING
    (re-expressing the cluster's internal edges as a star through one new node costs fewer bits) AND the
    cluster is not vague (mean member specificity ≥ the graph-wide mean specificity). The label is left BLANK for the
    language layer (Stage 6) to name. The candidate carries its `members` and the `id` to write the node
    under (0.16.0), so the language layer writes the star the screen scored: the node, and one
    `collapses_into` edge from each member to it. The rationale still names the members, for reading.

    It leaves out a community a live compression node was already proposed over, and a candidate whose
    id is already a node (0.17.0, `_compression_skip`); `compression_skips` reports both."""
    und = _resolve_und(G, und)
    cands: list = []
    for ms, e_int, saved, member_spec, mean_spec, skip in _compression_screen(G, und):
        if skip:
            continue
        cands.append(Candidate(
            kind="node", mechanism="compression", node_type="compression", label="",
            score=round(saved, 4), specificity=round(member_spec, 4), section="§7",
            rationale=(f"MDL: {e_int} internal edges among {len(ms)} members re-express as a star "
                       f"(saves ~{saved:.0f} bits); specificity {member_spec:.2f} ≥ graph mean "
                       f"{mean_spec:.2f}; collapses: {', '.join(ms)}"),
            members=ms, id=compression_id(ms)))
    return _rank(cands, k)


def compression_skips(G, *, und=None) -> dict:
    """What `compression` left out, for `kg_generate` to report (0.17.0): `already_compressed`, the live
    compression nodes whose communities it did not compress again, and `already_proposed`, each existing
    node a candidate's id named, with that node's state."""
    und = _resolve_und(G, und)
    compressed: set = set()
    proposed: dict = {}
    for *_screened, skip in _compression_screen(G, und):
        if not skip:
            continue
        why, what = skip
        if why == ALREADY_COMPRESSED:
            compressed.update(what)
        else:
            proposed[what] = _attr(G, what, "epistemic_state") or ""
    return {"already_compressed": sorted(compressed), "already_proposed": dict(sorted(proposed.items()))}


def regroup(G, *, failures, k=10, und=None, adj=None, new_comm=_UNSET) -> list:
    """§8 — re-partition surfaces invisible bridges. Re-run Leiden at a DIFFERENT resolution and diff
    the community assignment against the stored one; any non-adjacent pair that was intra-community
    before but becomes cross-community under the new partition is a bridge that "was invisible under the
    prior partition." This is the generative use of the freedom of resolution."""
    und = _resolve_und(G, und)
    # perf #13 — the Leiden re-partition is the expensive step. On a full `kg_generate('all')` run it
    # is computed once in `run_generators` and threaded in (regroup AND ensemble's degraded path share
    # it), so Leiden runs once per run instead of twice. `_UNSET` vs None: see the sentinel def — a real
    # None (both algorithms failed) is supplied and must flow through; `_UNSET` means "not supplied".
    if new_comm is _UNSET:
        new_comm = _repartition(und)
    # _repartition returns None ONLY when BOTH community algorithms failed and it fell back to the
    # identity (all-nodes-its-own-community) partition — a non-partition that would make EVERY
    # intra-community pair "split apart", exploding into an O(n^2) slate of meaningless candidates
    # (review-M6). A legitimate high-resolution partition that happens to be all-singletons is a real
    # dict and still flows through (that is how regroup surfaces bridges on small graphs).
    if new_comm is None:
        return []
    adj = _resolve_adj(G, adj)
    gate_on, strength = _strength_map(G)
    nodes = list(G.nodes())
    cands: list = []
    for i, u in enumerate(nodes):
        ou, nu = _attr(G, u, "community", NO_COMMUNITY), new_comm.get(u)
        for v in nodes[i + 1:]:
            if v in adj[u]:
                continue
            # intra-community BEFORE (same stored community), cross-community AFTER (new partition splits)
            if ou == NO_COMMUNITY or _attr(G, v, "community", NO_COMMUNITY) != ou:
                continue
            if nu is None or new_comm.get(v) == nu:
                continue
            if _is_failure(failures, u, BRIDGES_RELATION, v):
                continue
            su = strength[u]
            sv = strength[v]
            spec = _pair_specificity(G, u, v)
            cands.append(_edge_cand(
                "regroup", u, v, BRIDGES_RELATION, score=(su + sv) + 1e-3, specificity=spec, section="§8",
                rationale=(f"invisible under the prior partition: {_attr(G, u, 'label', u)} and "
                           f"{_attr(G, v, 'label', v)} share community c{ou} at the stored resolution but "
                           f"split apart when re-partitioned")))
    # ranked on the same endpoint-strength sum as bridge, so it shares the slate the same way (0.16.0)
    return _rank_spread(cands, k)


def transplant(G, *, failures, k=10, und=None, adj=None) -> list:
    """§5 — hubs as macro-bridges. Take a high-degree hub from one community and import its reorganising
    pattern (its dominant outgoing relation) into the community with the highest ABSORPTION CAPACITY
    (proxy: high mean specificity, low density). Transfer is asymmetric — we transplant INTO the
    absorptive community and flag the reverse as risky. The rationale names the hub's hidden commitments
    to audit (the language layer expands them in Stage 6)."""
    if G.number_of_nodes() < 4:
        return []
    und = _resolve_und(G, und)  # hoisted once: absorption() reads its neighbours m times per call (perf)
    by_comm = _members_by_community(G)
    if len([c for c in by_comm if c != NO_COMMUNITY]) < 2:
        return []
    # the hub: highest-degree node in a real community
    hub = max((n for n in G.nodes() if _attr(G, n, "community", NO_COMMUNITY) != NO_COMMUNITY),
              key=lambda n: (float(_attr(G, n, "degree", 0)), n), default=None)
    if hub is None:
        return []
    hub_comm = _attr(G, hub, "community", NO_COMMUNITY)
    # the hub's dominant outgoing relation (its reorganising pattern). Blank/missing relations are
    # dropped first: a relation='' candidate is always QUARANTINED at the boundary (never in pack
    # edge_types), so emitting it only wastes candidate/k budget and prints a nonsensical rationale. A
    # hub whose out-edges are all blank is treated like a hub with no out-edges (the `if not …` guard).
    rel_counts: dict = defaultdict(int)
    for _, _, data in G.out_edges(hub, data=True):
        rel = data.get("relation", "")
        if rel:
            rel_counts[rel] += 1
    if not rel_counts:
        return []
    dominant_relation = max(sorted(rel_counts), key=lambda r: rel_counts[r])
    # absorption capacity per other community: mean specificity / density
    def absorption(members):
        m = len(members)
        if m < 1:
            return 0.0
        member_set = set(members)
        e_int = _internal_edge_count(und, member_set)
        density = (e_int / (m * (m - 1) / 2)) if m > 1 else 1.0
        mean_spec = sum(float(_attr(G, u, "specificity", 1.0)) for u in members) / m
        return mean_spec / (density + 1e-6)
    targets = [(c, members) for c, members in by_comm.items() if c != hub_comm and c != NO_COMMUNITY]
    if not targets:
        return []
    best_c, best_members = max(targets, key=lambda c_members: (absorption(c_members[1]), c_members[0]))
    best_absorption = absorption(best_members)  # loop-invariant: compute once, reuse per candidate (perf)
    adj = _resolve_adj(G, adj)
    cands: list = []
    for target_node in sorted(best_members, key=lambda n: (-float(_attr(G, n, "degree", 0)), n)):
        if target_node == hub or target_node in adj[hub]:
            continue
        if _is_failure(failures, hub, dominant_relation, target_node):
            continue
        spec = _pair_specificity(G, hub, target_node)
        # hub.degree * best_absorption is loop-INVARIANT across targets, so on its own every candidate
        # ties and _rank collapses to target-id order — discarding the degree-desc intent the emit order
        # already encodes. Fold in a per-target signal (the target's own live degree, +1 so a degree-0
        # target still scores) so a higher-degree target genuinely outranks a lower-degree one (review).
        score = float(_attr(G, hub, "degree", 0)) * best_absorption * (float(_attr(G, target_node, "degree", 0)) + 1.0)
        cands.append(_edge_cand(
            "transplant", hub, target_node, dominant_relation, score=score, specificity=spec, section="§5",
            rationale=(f"macro-bridge: transplant hub '{_attr(G, hub, 'label', hub)}' (c{hub_comm}, "
                       f"degree {int(_attr(G, hub, 'degree', 0))}) reorganising relation '{dominant_relation}' into "
                       f"the more absorptive community c{best_c}; hidden commitments to audit: does "
                       f"'{_attr(G, target_node, 'label', target_node)}' actually admit a '{dominant_relation}' the way the hub's targets do?")))
    return _rank(cands, k)


def _second_reading(second_graph) -> dict:
    """``{frozenset(pair): [(source, relation, target, span, source_file), …]}``: the live, typed edges a second
    construction holds between each pair of its nodes, in a stable order (0.19.0). An edge with no relation
    (a pre-built graph.json that carries none) is left out, so its pair falls back to a plain `bridges`."""
    out: dict = defaultdict(list)
    for u, v, d in second_graph.edges(data=True):
        relation = str(d.get("relation") or "").strip()
        if u == v or not relation or d.get("epistemic_state") in _NON_LIVE_VALUES:
            continue
        out[frozenset((u, v))].append((u, relation, v, str(d.get("span") or ""), str(d.get("source_file") or "")))
    for edges in out.values():
        edges.sort(key=lambda e: (e[1], e[0], e[2]))
    return out


def ensemble(G, *, failures, k=10, second_graph=None, und=None, adj=None,
             new_comm=_UNSET) -> list:
    """§9 — exo: cross constructions. Given an optional SECOND construction (a second derived graph from
    a different pack/resolution), emit the edges that exist in one construction's structure but not the
    other's — the connections the graph's own dynamics would resist. With only one construction
    available, this degrades to `regroup` (the internal analogue), tagged so the slate stays honest.

    A pair the second construction joins and ours does not is proposed as the edge the second construction
    wrote: its relation, its direction, and the passage it wrote it from (0.19.0, `Candidate.passage`), each
    such edge checked against failure memory on its own id. Only a pair whose second-construction edges carry
    no relation (a pre-built graph.json that records none) is proposed as a plain `bridges`, as through 0.18.1.
    The field test of 2026-11-16 re-read a source the graph was built from: of the four edges the two
    constructions could compare, one was new (`tcp-ip-frente-a-osi grounds regla-de-centralizacion`), and as a
    `bridges` with no passage it was rejected `no-support`."""
    if second_graph is None:
        # perf #13 — pass the shared undirected graph/adjacency and the run's memoized re-partition
        # through to the degraded regroup so Leiden is not recomputed (already run by regroup on 'all').
        out = regroup(G, failures=failures, k=k, und=und, adj=adj, new_comm=new_comm)
        for c in out:
            c.mechanism = "ensemble"
            c.section = "§9"
            c.rationale = "no second construction supplied — degraded to regroup: " + c.rationale
        return out
    adj1 = _resolve_adj(G, adj)
    own = set(G.nodes())
    adj2 = _undirected_adjacency(second_graph)
    read = _second_reading(second_graph)
    cands: list = []
    seen: set = set()
    for u in second_graph.nodes():
        if u not in own:
            continue
        for v in adj2[u]:
            if v not in own or v in adj1[u]:
                continue  # endpoint absent from our construction, or already adjacent here
            key = frozenset((u, v))
            if key in seen:
                continue
            seen.add(key)
            spec = _pair_specificity(G, u, v)
            typed = read.get(key, [])
            if not typed:
                if _is_failure(failures, u, BRIDGES_RELATION, v):
                    continue
                cands.append(_edge_cand(
                    "ensemble", u, v, BRIDGES_RELATION, score=1.0, specificity=spec, section="§9",
                    rationale=(f"exo bridge: {_attr(G, u, 'label', u)} ⇄ {_attr(G, v, 'label', v)} is adjacent "
                               f"in the SECOND construction but absent here — external structure our own "
                               f"dynamics resisted (perturbation=external)")))
                continue
            for src, relation, tgt, span, source_file in typed:
                if _is_failure(failures, src, relation, tgt):
                    continue
                passage = {"span": span, "source_file": source_file} if span.strip() else {}
                cands.append(_edge_cand(
                    "ensemble", src, tgt, relation, score=1.0, specificity=spec, section="§9",
                    rationale=(f"exo edge: the SECOND construction reads {_attr(G, src, 'label', src)} "
                               f"{relation} {_attr(G, tgt, 'label', tgt)}"
                               + (" from a passage of its source" if passage else "")
                               + "; the two are not adjacent here — external structure our own dynamics "
                                 "resisted (perturbation=external)"),
                    passage=passage))
    return _rank(cands, k)


def periphery(G, *, failures, k=10, adj=None) -> list:
    """§5 — explore the periphery. Source candidates from LOW-degree nodes (the periphery the
    hub-seeking mechanisms ignore): for each peripheral node, propose a `bridges` edge to a
    non-adjacent anchor that maximises connectability (shared-neighbour count), specificity-
    controlled. Distinct from transplant (hubs) and seed (any residual-rich pair): here the SOURCE
    is deliberately low-degree, surfacing hypotheses that challenge the dense centre's status quo.

    The peripheral band is ADAPTIVE (Stage-1 survey): the bottom quartile of the live degree
    distribution — nodes whose precomputed `degree` is > 0 (degree-0 orphans are surfaced by
    kg_agenda, not re-proposed here) and <= the 25th-percentile degree, computed by the nearest-rank
    rule (no interpolation) so the threshold is byte-stable across repeated runs over the same graph
    (G6). Reuses BRIDGES_RELATION (an existing pack edge_type) — never a new type."""
    # periphery only needs the undirected ADJACENCY (it never walks `und`); resolve adj like `bridge`
    # does, so a standalone single-mechanism run pays no wasted `G.to_undirected()` build.
    adj = _resolve_adj(G, adj)
    nodes = list(G.nodes())
    degree = {n: int(_attr(G, n, "degree", 0)) for n in nodes}
    # the live degree distribution over CONNECTED nodes (degree-0 orphans excluded — kg_agenda surfaces
    # those; a peripheral SOURCE with no neighbours has no shared-neighbour anchor anyway).
    deg_values = sorted(d for d in degree.values() if d > 0)
    if not deg_values:
        return []
    # adaptive 25th-percentile threshold via the nearest-rank rule: deterministic, no interpolation,
    # corpus-size-independent. p_idx is 0-based, so an all-equal-degree distribution yields its single
    # degree as the threshold (every connected node is then in-band — honest for a flat graph).
    p_idx = max(0, math.ceil(0.25 * len(deg_values)) - 1)
    threshold = deg_values[p_idx]
    peripheral = sorted(n for n in nodes if 0 < degree[n] <= threshold)
    cands: list = []
    for u in peripheral:
        nbu = adj[u]
        # the best non-adjacent connectable anchor: most shared neighbours, then the MORE SPECIFIC
        # anchor, then the smaller id (the deterministic tie rule, §4 generality-control / G6). A
        # failed/rejected pair (forward OR reverse) is excluded from anchor candidacy so failure memory
        # never re-proposes what was refuted (§13).
        options = []
        for v in nodes:
            if v == u or v in nbu:
                continue
            shared = len(nbu & adj[v])
            if shared <= 0:
                continue  # not connectable — no shared neighbour, nothing to bridge through
            if _is_failure(failures, u, BRIDGES_RELATION, v):
                continue
            options.append((shared, float(_attr(G, v, "specificity", 1.0)), v))
        if not options:
            continue  # no non-adjacent connectable anchor — skip this peripheral source
        shared, _spec_v, v = min(options, key=lambda t: (-t[0], -t[1], t[2]))
        deg_u = degree[u]
        # score = peripherality (low source degree) × connectability (shared-neighbour count): monotone
        # in BOTH, never collapsed with specificity (which travels in its own field — §4 / G4).
        score = (1.0 / (deg_u + 1)) * (shared + 1)
        spec = _pair_specificity(G, u, v)
        cands.append(_edge_cand(
            "periphery", u, v, BRIDGES_RELATION, score=score, specificity=spec, section="§5",
            rationale=(f"periphery bridge: low-degree source '{_attr(G, u, 'label', u)}' (degree {deg_u}, "
                       f"bottom-quartile ≤ {threshold}) ⇄ '{_attr(G, v, 'label', v)}' sharing {shared} "
                       f"neighbour(s) — sourced FROM the periphery the hub-seeking mechanisms ignore, "
                       f"NOT a hub transplant")))
    return _rank(cands, k)


# --------------------------------------------------------------------------- partition / loading helpers


# The §8 re-partition tuning pair — named ONCE (review-r5: the two literals were spelled at three
# sites that had to agree for the memoized 'all'-run repartition to stay byte-identical with a
# standalone regroup run, a silent-divergence trap in a determinism-critical path).
_REPART_RESOLUTION = 4.0
_REPART_SEED = 7


def _repartition(und, resolution=_REPART_RESOLUTION, seed=_REPART_SEED) -> "dict | None":
    """Re-run community detection at a DIFFERENT resolution than the stored projection (§8). Higher
    resolution -> more, smaller communities -> intra-community pairs surface as cross-community. Falls
    back to a different-seed label propagation when leidenalg is unavailable."""
    if und.number_of_nodes() == 0:
        return {}
    try:
        import igraph as ig
        import leidenalg as la
        nodes = list(und.nodes())
        idx = {n: i for i, n in enumerate(nodes)}
        edges = [(idx[u], idx[v]) for u, v in und.edges()]
        g = ig.Graph(n=len(nodes), edges=edges, directed=False)
        part = la.find_partition(g, la.RBConfigurationVertexPartition, seed=seed,
                                 resolution_parameter=resolution)
        return {nodes[i]: m for i, m in enumerate(part.membership)}
    except Exception:  # noqa: BLE001 — degrade to a different-seed label propagation
        try:
            communities = nx.community.asyn_lpa_communities(und, seed=seed)
            return {n: ci for ci, com in enumerate(communities) for n in com}
        except Exception:  # noqa: BLE001 — BOTH algorithms failed: signal "no usable repartition"
            # Return None (not the identity {n: i} partition): the all-singleton identity makes every
            # intra-community pair appear to "split", which regroup would explode into O(n^2) noise.
            # The sentinel lets regroup short-circuit cleanly (review-M6).
            return None


def load_second_graph(path: str | Path) -> nx.MultiDiGraph:
    """Load a second construction's graph.json into a MultiDiGraph (PLAN Stage 7 — the ensemble path)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return node_link_graph(data)


# --------------------------------------------------------------------------- dispatch


# mechanism name -> (fn, the lazy shared structures its signature accepts). Adding a mechanism is
# ONE row here (review-r5: a _DISPATCH lookup used to be followed by an `if fn is bridge: ...`
# identity ladder that re-encoded every signature a second time, ending in an admitted-unreachable
# else). "ensemble_new_comm" marks ensemble's conditional re-partition: forced only on its degraded
# (no-second-construction) path — with a real second_graph the exo path never consults new_comm.
_DISPATCH = {
    "bridge": (bridge, ("adj",)),
    "bridges": (bridge, ("adj",)),
    "seed": (seed, ("und", "adj")),
    "compression": (compression, ("und",)),
    "regroup": (regroup, ("und", "adj", "new_comm")),
    "transplant": (transplant, ("und", "adj")),
    "ensemble": (ensemble, ("und", "adj", "second_graph", "ensemble_new_comm")),
    "periphery": (periphery, ("adj",)),
}


def _resolve_mechanisms(mechanism: str) -> list:
    """`all` -> ALL_SET; a known single name -> itself; `default`/unknown -> DEFAULT_SET (never
    raises)."""
    if mechanism == "all":
        return list(ALL_SET)
    if mechanism in _DISPATCH:
        return [mechanism]
    return list(DEFAULT_SET)


def resolve_mechanisms(mechanism: str) -> list:
    """The mechanisms `run_generators(G, mechanism)` runs, by `_resolve_mechanisms`'s one rule. Public so
    `kg_generate` can tell whether compression ran, and report what it left out, without restating the
    rule (0.17.0)."""
    return _resolve_mechanisms(mechanism)


def _edge_key(c) -> tuple:
    """The dedup/convergence identity of an edge candidate. BRIDGES_RELATION candidates
    (bridge/seed/regroup/ensemble) are treated as semantically symmetric throughout this layer (the
    dual-orientation _is_failure check, ensemble's frozenset `seen`, the hypothesized lane's
    check_reverse=True), so an orientation-swapped pair is a logical duplicate — the ensemble exo
    path orients pairs by the SECOND construction's node order, so bridge can emit (a,b) while
    ensemble-exo emits (b,a) for the same undirected bridge; a directional key would let both
    survive (review-M10). The directional key is kept for transplant, whose dominant_relation is
    genuinely directional."""
    if c.relation == BRIDGES_RELATION:
        return (frozenset((c.source, c.target)), c.relation)
    return (c.source, c.target, c.relation)


def _convergence_tally(full: list, degraded_ensemble: bool) -> dict:
    """Convergence (§4 advisory): how many DISTINCT mechanisms independently proposed each edge key,
    tallied over `full` — each mechanism's PRE-truncation candidate list, NOT the surfaced top-k
    slate: a pair proposed by two mechanisms but dropped from one mechanism's own top-k would
    otherwise be undercounted (review). The degraded-ensemble path re-emits regroup's edges under a
    SECOND name — but that is the SAME construction, not a second independent one, so `ensemble`
    collapses to `regroup` for the tally (else the degrade path would spuriously inflate convergence
    to 2 on every regroup edge; asserted in a test). Computed purely from mechanism agreement on
    STRUCTURE — no text, no span, no verdict — and only ever rides the response / queue ordering,
    never `score` and never a canon edge (G3/G4)."""
    def conv_mech(c):
        return "regroup" if (degraded_ensemble and c.mechanism == "ensemble") else c.mechanism

    mech_by_key: dict = defaultdict(set)
    for c in full:
        if c.kind == "edge":
            mech_by_key[_edge_key(c)].add(conv_mech(c))
    return mech_by_key


def _dedup_candidates(out: list, mech_by_key: dict) -> list:
    """Dedup EDGE candidates across mechanisms by `_edge_key`, keeping the FIRST occurrence
    (highest-priority mechanism by run order) and stamping its `convergence` from the tally. NODE
    candidates (compressions) pass through untouched. Their label is blank until Stage 6 names them, so
    an empty-label key must not collapse them. They carry an `id` since 0.16.0, but only `compression`
    emits them, one per community, and communities are disjoint, so no two can share one."""
    seen: set = set()
    deduped: list = []
    for c in out:
        if c.kind == "edge":
            key = _edge_key(c)
            if key in seen:
                continue
            seen.add(key)
            c.convergence = len(mech_by_key[key])  # >=1; node candidates keep the default 1
        deduped.append(c)
    return deduped


def run_generators(G, mechanism="bridge", *, pack=None, corpus=None, failures=None, k=10,
                   second_graph=None) -> list:
    """Dispatch to one mechanism, the default set, or all seven. `mechanism="all"` runs ALL_SET;
    `mechanism="default"` runs DEFAULT_SET; an unknown name runs DEFAULT_SET (never raises).
    `pack`/`corpus` are accepted for API stability but unused: no mechanism reads them (review-r5
    dropped them from the mechanism signatures, where they were dead weight on every call site)."""
    failures = failures or set()
    k = max(0, int(k))
    mechs = _resolve_mechanisms(mechanism)

    # perf #12 — build the undirected projection + adjacency ONCE per run and thread them into every
    # mechanism (they are otherwise rebuilt 5-6× on an 'all' run). The threaded values are identical to
    # what each mechanism would build itself (same constructors), so output is unchanged. Built lazily
    # (only when a mechanism in this run actually needs them) so a single-mechanism run pays no extra.
    _shared_und = None
    _shared_adj = None

    def und_of():
        nonlocal _shared_und
        if _shared_und is None:
            _shared_und = _live_undirected(G)
        return _shared_und

    def adj_of():
        nonlocal _shared_adj
        if _shared_adj is None:
            _shared_adj = _undirected_adjacency(G)
        return _shared_adj

    # perf #13 — memoize the §8 Leiden re-partition for the run: regroup and ensemble's degraded path
    # both consume it, so on an 'all' run it is computed once instead of twice. Computed lazily; here
    # `_UNSET` means "not yet computed", distinct from a real None result (see the sentinel def).
    _shared_repart = _UNSET

    def repart_of():
        nonlocal _shared_repart
        if _shared_repart is _UNSET:
            _shared_repart = _repartition(und_of())
        return _shared_repart

    # Run every mechanism at a k large enough that NOTHING is truncated (its full pre-truncation
    # candidate list), then surface only that mechanism's own top-k. `_BIG_K` >= any mechanism's
    # candidate count (edge mechanisms are O(V^2); node/periphery/transplant are O(V)). Slicing a
    # full ranked list to k is byte-identical to calling the mechanism with k (_rank sorts then
    # truncates), so the SURFACED slate is unchanged — but the retained full lists let the convergence
    # tally (below) count a pair proposed by two mechanisms even when it fell off ONE mechanism's top-k
    # (review: convergence undercount). SIZE-GATED at FULL_TALLY_MAX_NODES: above the gate the exact
    # tally's O(V^2) materialization is prohibitive, so mechanisms run at the surfaced k and the tally
    # is approximate (see the constant's rationale).
    n_nodes = G.number_of_nodes()
    _BIG_K = (n_nodes ** 2 + n_nodes + 1) if n_nodes <= FULL_TALLY_MAX_NODES else k
    out: list = []
    full: list = []  # every mechanism's PRE-truncation candidate list — feeds the convergence tally only
    for m in mechs:
        fn, needs = _DISPATCH[m]
        kwargs: dict = {}
        if "und" in needs:
            kwargs["und"] = und_of()
        if "adj" in needs:
            kwargs["adj"] = adj_of()
        if "new_comm" in needs:
            kwargs["new_comm"] = repart_of()
        if "second_graph" in needs:
            kwargs["second_graph"] = second_graph
        if "ensemble_new_comm" in needs:
            # force the (lazy) re-partition only for the degraded path; with a real second_graph the
            # exo path never consults new_comm, so it stays unforced (_UNSET).
            kwargs["new_comm"] = repart_of() if second_graph is None else _UNSET
        produced = fn(G, failures=failures, k=_BIG_K, **kwargs)
        full += produced
        out += produced[:k]  # the SURFACED slate: this mechanism's own top-k (unchanged)

    # Cross-mechanism dedup + the §4 convergence advisory — the key, tally, and dedup rules live in
    # the module-level _edge_key / _convergence_tally / _dedup_candidates (review-r5: they were three
    # nested closures inside this function, untestable in isolation).
    mech_by_key = _convergence_tally(full, degraded_ensemble=second_graph is None)
    return _dedup_candidates(out, mech_by_key)
