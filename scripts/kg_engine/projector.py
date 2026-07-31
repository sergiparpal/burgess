"""The derived layer (§1.2): canon -> NetworkX node-link graph.json + SQLite index.

- Leiden communities (igraph + leidenalg; graceful label-propagation fallback if unavailable)
- precomputed ranks: local DEGREE (cheap advisory) + a labelled STRUCTURAL-BRIDGE signal
  (a node whose neighbours span >=2 communities, §1.4/§1.6) — computed OFF the hot path
- incremental reproject keyed by per-file content hash (mismatch => stale => rebuild)
- kg_context: reads precomputed ranks O(1), token-budgeted, carries provenance + epistemic tier +
  falsification counters; NEVER computes centrality in-request
- the derived layer contains nothing the canon does not, and never prunes failure memory (§1.7)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from . import envconfig
from .atomicio import atomic_write_text as _atomic_write
from .canon import Canon, _git
from .graphio import node_link_data
from .harness import idf_seeds, node_specificity
from .harness import specificity as _specificity_gate
from .model import (Edge, EpistemicState, FAILURE_STATE_VALUES, NON_LIVE_STATE_VALUES, Node, Provenance,
                    node_content_hash, normalize_text)
from .sources import section_corpus

if TYPE_CHECKING:  # type-only; the projector duck-types .verifies/.concat at runtime
    # networkx is type-only at module scope and imported lazily inside the few graph-building/rank
    # functions below (review-r6: hook-import-tax). Its import costs ~70ms, and the PreToolUse hook
    # imports this module on every Grep/Glob/Read only to READ precomputed columns — a path that
    # never touches networkx. `from __future__ import annotations` keeps the `nx.*` annotations lazy.
    import networkx as nx
    from .sources import SourceSet

GRAPH_JSON = "graph.json"
INDEX_DB = envconfig.INDEX_DB_NAME  # value hosted in the envconfig leaf (the hook's pre-check reads it)
# The full set of `nodes` columns the current schema declares. The four generative-layer columns
# (betweenness/spec_betweenness/specificity/gate_on, PLAN Stage 2) were added after the original 11;
# an index.sqlite built before them lacks the columns, so a projection that finds them missing forces
# a full rebuild (CREATE TABLE IF NOT EXISTS cannot add a column to an existing table).
_NEW_NODE_COLUMNS = {"betweenness", "spec_betweenness", "specificity", "gate_on"}
# Same late-addition marker for the `edges` table: `owner` (the note file an edge is persisted in)
# was added after the original 11 edge columns — see _EDGE_COLUMNS for why it exists. A pre-owner
# index.sqlite must full-rebuild exactly like a pre-Stage-2 one.
_NEW_EDGE_COLUMNS = {"owner"}
# The `nodes` table column order, in DDL order — the single source of truth for the positional
# persistence contract. `_NODES_DDL`, the INSERT placeholder string, `_node_row`, and the
# incremental rank-refresh all derive from this tuple, so a column add/reorder is one edit here
# (no hand-counted bare indices). `(name, sql_type)` per column.
_NODE_COLUMNS = (
    ("id", "TEXT PRIMARY KEY"), ("label", "TEXT"), ("node_type", "TEXT"), ("file_type", "TEXT"),
    ("provenance", "TEXT"), ("authored_by", "TEXT"), ("epistemic_state", "TEXT"),
    ("degree", "INTEGER"), ("community", "INTEGER"), ("bridge_communities", "INTEGER"),
    ("structural_bridge", "INTEGER"), ("betweenness", "REAL"), ("spec_betweenness", "REAL"),
    ("specificity", "REAL"), ("gate_on", "INTEGER"),
)
_NODE_COLUMN_NAMES = tuple(name for name, _ in _NODE_COLUMNS)
# The subset of node columns the incremental pass diffs + refreshes for an unchanged node when a
# GLOBAL rank moves. structural_bridge is deliberately EXCLUDED from the diff: it is a pure function
# of bridge_communities (1 iff bridge_communities >= 2), which IS in this subset, so a structural_bridge
# change can never occur without a bridge_communities change already triggering the refresh.
_RANK_DIFF_COLUMNS = ("degree", "community", "bridge_communities",
                      "betweenness", "spec_betweenness", "specificity", "gate_on")
# The columns the rank-refresh UPDATE writes — _RANK_DIFF_COLUMNS plus structural_bridge (written
# from its derived value, just never used to decide WHETHER to write).
_RANK_UPDATE_COLUMNS = ("degree", "community", "bridge_communities", "structural_bridge",
                        "betweenness", "spec_betweenness", "specificity", "gate_on")
# The `edges` table columns, single-sourced exactly like _NODE_COLUMNS so the DDL, the INSERT VALUES
# placeholder count, the incremental-diff SELECT column list, and _edge_row's value order all derive
# from ONE definition — a column add/reorder is one edit here, and the positional contract between the
# diff SELECT and _edge_row can't silently desync into a false 'unchanged'/'changed' persistence bug.
# (kg_context reads edges by NAME via sqlite3.Row with its own deliberately-different column subset, so
# it is not part of this positional contract and intentionally does not derive from here.)
_EDGE_COLUMNS = (
    ("id", "TEXT PRIMARY KEY"), ("source", "TEXT"), ("target", "TEXT"), ("relation", "TEXT"),
    ("provenance", "TEXT"), ("authored_by", "TEXT"), ("epistemic_state", "TEXT"), ("span", "TEXT"),
    ("source_file", "TEXT"), ("confidence", "TEXT"), ("confidence_score", "REAL"),
    # `owner` = the id of the canon NOTE the edge is persisted in. Normally identical to `source`,
    # but a hand-edited note may legitimately carry an edge whose explicit `source:` names another
    # node (model.Edge.from_dict honors it). The incremental diff/delete must be keyed on the OWNING
    # FILE — keying on `source` left a removed foreign-source edge as a stale row the canon no longer
    # holds (violating "derived contains nothing the canon does not") until the next full rebuild.
    ("owner", "TEXT"),
)
_EDGE_COLUMN_NAMES = tuple(name for name, _ in _EDGE_COLUMNS)
# Hard ceiling on the kg_context token budget so a client passing a huge value can't make the engine
# serialize the entire edge table into one response (server-4). The limit clamp on query_graph is the
# row-count analogue.
MAX_CONTEXT_TOKENS = 100_000
# Reader-facing bounds/knobs, named (review-r5: these were inline magic numbers):
BRIDGE_LIMIT = 10          # top-N structural-bridge rows kg_context serves; export's report consumes it
MAX_QUERY_LIMIT = 10_000   # clamp for query_graph's LIMIT (a negative LIMIT is unbounded in SQLite)
MAX_AGENDA_LIMIT = 50      # clamp for kg_agenda's limit
_CHARS_PER_TOKEN = 4       # the crude chars-per-token estimate the context budget fill uses
# Cap on the distinct query terms kg_context turns into LIKE clauses. Each term adds four
# `LIKE '%…%'` predicates evaluated against EVERY edge row (span text included) — an unbounded
# pasted-paragraph query would multiply that full-scan cost per term for match quality the budget
# fill then truncates anyway (review-r6). Queries with more terms match on the first cap terms.
_QUERY_TERM_CAP = 12
_STALE_PREVIEW_LABELS = 3  # how many stale-verdict labels the advisory names inline
# Cap the R3 stale-verdict advisory list in kg_context so it can't bypass the token budget (review-low).
_STALE_VERDICTS_CAP = 50
# The R3-MIRROR re-examinable-verdicts advisory (non-monotonic evidence): a READ-ONLY signal that a
# failed/rejected item was judged against a source set that has since changed, so it deserves a
# grounder re-look. Cap parallels the stale-verdict advisory's (_STALE_VERDICTS_CAP) so the inline
# kg_context list can never bust the token budget. The advisory NEVER mutates a verdict, never re-queues.
_REEXAMINABLE_CAP = 50
# The two verdict states the re-examinable advisory covers — the SAME negative-memory vocabulary as
# model.FAILURE_STATES ({REJECTED, FAILED}), referenced here (never redefining that global) so
# extending the vocabulary there extends this advisory too. Unlike R3, the predicate is item-agnostic
# (nodes AND edges) and span-agnostic (span-present AND span-less) — falsified divergence pins, the
# motivating case, are typically span-less nodes R3 cannot see.
_REEXAMINABLE_STATES = (EpistemicState.FAILED, EpistemicState.REJECTED)
# Term-overlap noise filter (§Stage 6): tokens for the relevance test that decides whether the CHANGED
# source text actually bears on a failed/rejected item. Applied AFTER normalize_text (which casefolds),
# so the class is lowercase-only; it deliberately splits on '-'/'_' (unlike harness._WORD, which keeps
# them) so a slug endpoint id like `generality-confound` matches prose "generality confound" across the
# item↔source boundary. >=3 chars mirrors the kg_context query-term floor.
# Unicode-letter-aware (not `[a-z]`): normalize_text casefolds but does NOT transliterate, so an
# ASCII-only `[a-z][a-z0-9]{2,}` yielded ZERO terms on a non-Latin-script source — making the whole
# re-examinable advisory silently empty there (a recall gap, never a false positive). `[^\W\d_]` is a
# unicode letter; `[^\W_]` is a letter-or-digit (both exclude underscore), so this keeps the exact old
# ASCII semantics — a letter followed by >=2 letters/digits — extended to every script (review-r8-13).
_OVERLAP_WORD = re.compile(r"[^\W\d_][^\W_]{2,}")
# Non-content terms dropped before the overlap test so a shared "with"/"that"/"from" can never make an
# unrelated changed source flag an item. Small, generic, English-only by design — the filter only needs
# to remove obviously-uninformative overlaps, not to be a full stoplist (sub-3-char words like a/is/of/
# to/in are already excluded by the length floor above).
_OVERLAP_STOPWORDS = frozenset({
    "the", "and", "but", "for", "with", "from", "are", "was", "were", "been", "being", "this", "that",
    "these", "those", "not", "nor", "too", "very", "can", "will", "would", "should", "could", "may",
    "might", "must", "does", "did", "has", "have", "had", "its", "their", "our", "your", "who", "whom",
    "which", "what", "when", "where", "why", "how", "all", "any", "each", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "about", "into", "over", "under", "out", "off", "again",
    "once", "here", "there", "also", "one", "two", "new", "then", "than", "them", "his", "her", "you",
    "use", "used", "using", "per", "via", "etc",
})

# R6 (kg_agenda) detector thresholds. A node with >= _HUB_DEGREE live edges is a "hub"; its
# grounded/(grounded+unverified) ratio splits well-grounded (answerable) from under-grounded (blocked).
_HUB_DEGREE = 3
_GROUNDED_RATIO = 0.5


def _like_escape(term: str) -> str:
    """Escape SQL LIKE wildcards so a query term like `span_present` or `100%` matches literally
    (the matching clauses use `ESCAPE '\\'`)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# The gate-aware bridge ranking — ONE source of truth shared by kg_context (a SQL ORDER BY) and
# kg_agenda (a Python sort key). When the specificity gate earned promotion this projection, rank by
# the confound-corrected spec_betweenness; otherwise fall back to the honest structural-bridge / raw-
# betweenness / degree advisory (§1.6). The two surfaces emit different SHAPES (SQL string vs key fn),
# so only the ordered column names + label are shared; the per-column coercion below keeps the Python
# key numeric (SQLite types its columns natively).
_RANK_COERCE = {"spec_betweenness": (float, 0.0), "betweenness": (float, 0.0),
                "structural_bridge": (int, 0), "degree": (int, 0)}


def gate_ranking(gate_on: bool) -> "tuple[str, tuple[str, ...]]":
    """(ranked_by_label, ordered descending column names) for the bridge ranking, keyed on the gate."""
    if gate_on:
        return "spec_betweenness", ("spec_betweenness", "degree")
    return "structural_bridge", ("structural_bridge", "betweenness", "degree")


# --------------------------------------------------------------------------- communities


def _leiden(undirected: nx.Graph) -> dict:
    """Return node_id -> community int. Leiden if available, else label propagation."""
    import networkx as nx  # deferred — see the TYPE_CHECKING note (review-r6: hook-import-tax)
    if undirected.number_of_nodes() == 0:
        return {}
    try:
        import igraph as ig
        import leidenalg as la

        nodes = list(undirected.nodes())
        idx = {n: i for i, n in enumerate(nodes)}
        edges = [(idx[u], idx[v]) for u, v in undirected.edges()]
        g = ig.Graph(n=len(nodes), edges=edges, directed=False)
        part = la.find_partition(g, la.RBConfigurationVertexPartition, seed=42)
        return {nodes[i]: m for i, m in enumerate(part.membership)}
    except Exception:  # noqa: BLE001 — any import/runtime failure degrades to fallback
        communities = nx.community.label_propagation_communities(undirected)
        return {n: ci for ci, com in enumerate(communities) for n in com}


# --------------------------------------------------------------------------- reports


@dataclass
class ProjectReport:
    up_to_date: bool = False
    full_rebuild: bool = False
    n_nodes: int = 0
    n_edges: int = 0
    communities: int = 0
    touched_nodes: list[str] = field(default_factory=list)
    touched_edges: list[str] = field(default_factory=list)
    built_from_commit: str = ""
    # True when project() could not acquire the canon lease and served/synthesized the existing (or an
    # empty cold-start) derived layer instead of reprojecting — a 410-contention observability signal
    # server.py:_ensure_projected reads. PINNED interface: the field name must stay exactly `contended`.
    contended: bool = False


class _ParseCache(NamedTuple):
    """The canon parse is_stale() stashes for the project() that follows (projector-5/-11), keyed by
    the cheap dir signature (review-r5: it was an anonymous tuple consumed as cache[1]/cache[2])."""
    sig: str
    nodes: list
    hashes: dict
    stats: dict  # per-file stat map {file name: [size, mtime_ns, node id]} — the review-r6 parse gate


@dataclass
class Ranks:
    """All precomputed per-node signals from one projection (PLAN Stage 2). Computed OFF the hot path
    (`_ranks`); read O(1) by the query surface. `betweenness` and `spec_betweenness` complete the
    partially-implemented bridge metric; `gate_on` (one value per projection) records whether the
    specificity-weighting earned promotion this projection (`harness.specificity`)."""
    community: dict = field(default_factory=dict)
    degree: dict = field(default_factory=dict)
    bridges: dict = field(default_factory=dict)
    betweenness: dict = field(default_factory=dict)
    spec_betweenness: dict = field(default_factory=dict)
    specificity: dict = field(default_factory=dict)
    gate_on: int = 0
    # signature of the live (failure-filtered) undirected topology these ranks were computed over;
    # persisted so the next projection can skip the O(V·E) betweenness pass when the topology is
    # unchanged (projector-1). "" when not computed (degenerate/empty graph).
    topo_sig: str = ""


# --------------------------------------------------------------------------- projector


class Projector:
    def __init__(self, canon: Canon, derived_dir: str | Path | None = None, *,
                 metrics_mode: str = "structure_only", source_text: "str | Callable[[], str] | None" = None,
                 source_set: "Callable[[], SourceSet] | None" = None,
                 specificity_seeds: "dict | Callable[[], dict] | None" = None):
        self.canon = canon
        self.derived = Path(derived_dir) if derived_dir else (canon.root / envconfig.DERIVED_DIRNAME)
        self.derived.mkdir(parents=True, exist_ok=True)
        self.graph_path = self.derived / GRAPH_JSON
        self.db_path = self.derived / INDEX_DB
        self.metrics_mode = metrics_mode
        # The source text feeds the IDF specificity weighting (PLAN Stage 2). Accept a str OR a
        # zero-arg callable (KGEngine passes its bound `source_text`, read lazily once per real
        # reprojection — off the hot path). Absent -> an empty corpus, so specificity is uniform and the
        # bridge-metric gate stays closed (spec_betweenness degrades to raw betweenness).
        self._source_text = source_text
        # The resolved SourceSet (R4), as a zero-arg callable, for the R3 source-staleness advisory: it
        # re-verifies each grounded/failed span-present edge against its OWN source_file (per-file, never
        # a global concat). Absent -> no staleness is ever flagged (can't diverge from a missing source).
        self._source_set = source_set
        # Pack-author-pinned per-term specificity (pack.specificity_seeds), as a dict or zero-arg
        # callable. Merged OVER the corpus IDF in _ranks so an author can boost/pin a term's specificity
        # — previously validated but never consumed (review-low: specificity_seeds unused).
        self._specificity_seeds = specificity_seeds
        # The parse is_stale() did for the content-hash check, stashed (keyed by cheap_sig) so the very
        # next project() reuses it instead of re-parsing the whole canon a second time (projector-5/-11).
        # Consumed once; the cheap_sig key guarantees a writer touching the vault in between invalidates it.
        self._parse_cache: "_ParseCache | None" = None

    def _spec_seeds(self) -> dict:
        s = self._specificity_seeds() if callable(self._specificity_seeds) else self._specificity_seeds
        return s or {}

    def _src_text(self) -> str:
        # Prefer the SourceSet's concat when configured, so the IDF corpus (specificity weighting) and
        # the R3 staleness advisory read the IDENTICAL source bytes — one source of truth, no divergence
        # between the two source inputs (review-low: IDF vs R3 source). Fall back to the explicit
        # source_text for a standalone Projector built without a source_set.
        if self._source_set is not None:
            try:
                return self._source_set().concat or ""
            except Exception:  # noqa: BLE001 — a source-read hiccup must never break ranking
                pass
        src = self._source_text() if callable(self._source_text) else self._source_text
        return src or ""

    def _corpus(self) -> list[str]:
        """The source split into per-section documents for IDF — the corpus `harness.idf_seeds`
        consumes. Empty when no source is configured. The split rule and document shape are
        single-homed in ``sources.section_corpus`` (review-r5), shared with the harness
        ``specificity`` CLI so the two corpora stay bit-identical by construction."""
        src = self._src_text()
        if not src:
            return []
        return section_corpus(src)

    # ---- helpers
    def _head(self) -> str:
        # NEVER let a git invocation wedge projection. _head() runs inside _project_locked on every
        # real reprojection; in the DETACHED MCP server process a `git` call with an inherited/absent
        # stdin can block forever on a credential/identity prompt, and on a NON-GIT canon (e.g. a
        # cloud-synced Documents folder) there is no HEAD to read anyway. A wedged _head() exceeds
        # KG_HANDLER_TIMEOUT and the supervisor force-exits the engine (exit 71). So: skip git
        # entirely without a .git entry (.exists() — not .is_dir() — so a `.git` FILE
        # worktree/submodule still counts), and route the git-repo case through canon._git — the ONE
        # hardened git seam (bounded, DEVNULL stdin, de-prompted env, degrading to a non-zero result
        # on timeout/spawn failure), which this method used to re-implement inline (review-r5).
        root = self.canon.root
        if not (root / ".git").exists():
            return ""  # non-git canon has no HEAD; never spawn git
        r = _git(root, "rev-parse", "HEAD", check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    @staticmethod
    def _file_hash(node) -> str:
        # the content-not-mtime hash that makes reprojection content-driven. The rule (and its
        # deliberate timestamp exclusion) is model.node_content_hash — shared with canon's
        # idempotent-write detection, whose agreement with this gate is load-bearing (review-r5).
        return node_content_hash(node)

    @staticmethod
    def _owner_rank(edge, owner: str) -> tuple:
        """Precedence for the single-canonical-edge rule (§1.4) when two notes declare the same edge id
        under different owners: the NATURAL owner (owner == edge.source) outranks any FOREIGN owner, and
        foreign owners tie-break by lexicographically-smallest id. Lower tuple wins."""
        return (0 if owner == edge.source else 1, owner)

    @classmethod
    def _canonical_edges(cls, nodes) -> list:
        """The deduplicated ``(edge, owner)`` list realizing single-canonical-edge (§1.4) DETERMINISTICALLY.
        A cross-owner id collision — only reachable by hand-editing a foreign-source edge that duplicates an
        existing natural edge — resolves by ``_owner_rank`` (natural owner wins, else smallest owner) instead
        of last-writer-in-node-order, so a full rebuild, graph.json, and the edges table always agree
        regardless of node iteration order (review-r8-10). FIRST-SEEN id order is preserved, so a graph with
        no collision (the universal case) yields the exact prior edge sequence — graph.json bytes and every
        snapshot are unchanged."""
        chosen: dict = {}   # id -> (edge, owner)
        order: list = []    # first-seen id order (stable output)
        for n in nodes:
            for e in n.edges:
                prior = chosen.get(e.id)
                if prior is None:
                    chosen[e.id] = (e, n.id)
                    order.append(e.id)
                elif cls._owner_rank(e, n.id) < cls._owner_rank(prior[0], prior[1]):
                    chosen[e.id] = (e, n.id)  # higher-ranked owner wins; keep first-seen position
        return [chosen[i] for i in order]

    def _build_graph(self, nodes):
        import networkx as nx  # deferred — see the TYPE_CHECKING note (review-r6: hook-import-tax)
        # MultiDiGraph (not DiGraph): two canon edges can share (source, target) but differ in
        # relation (e.g. `grounds` and `attacked_by`). A DiGraph keys edges by (u, v) only and would
        # silently collapse them — dropping edges from graph.json and undercounting n_edges, violating
        # "derived contains nothing the canon does not". The `key=e.id` keeps each parallel edge.
        G = nx.MultiDiGraph()
        for n in nodes:
            G.add_node(n.id, label=n.label, node_type=n.node_type, file_type=n.file_type,
                       provenance=n.provenance.value, authored_by=n.authored_by.value,
                       epistemic_state=n.epistemic_state.value)
        for e, _owner in self._canonical_edges(nodes):
            # derived contains nothing the canon doesn't; failure memory is kept, not pruned. Cross-owner
            # id collisions resolve deterministically via _canonical_edges (§1.4) so add_edge's last-writer
            # -wins can't make graph.json depend on node order.
            G.add_edge(e.source, e.target, key=e.id, id=e.id, relation=e.relation,
                       provenance=e.provenance.value, authored_by=e.authored_by.value,
                       epistemic_state=e.epistemic_state.value, span=e.span,
                       source_file=e.source_file, confidence=e.confidence.value,
                       confidence_score=e.confidence_score)
        return G

    @staticmethod
    def _topo_sig(und: nx.Graph) -> str:
        """A content hash of the live undirected TOPOLOGY (node set + deduped edge endpoint pairs) that
        betweenness depends on. Unweighted betweenness is a pure function of this structure, so an equal
        signature ⇒ provably-identical betweenness — the projector reuses the prior pass instead of
        recomputing it (projector-1). A verdict that flips an edge into/out of FAILURE_STATES changes the
        live subgraph (§1.7) and therefore this signature, forcing a recompute (the §1.7-correct gate)."""
        h = hashlib.sha256()
        for n in sorted(map(str, und.nodes())):
            h.update(n.encode()); h.update(b"\x00")
        h.update(b"\x01")
        for u, v in sorted({tuple(sorted((str(u), str(v)))) for u, v in und.edges()}):
            h.update(u.encode()); h.update(b"\x00"); h.update(v.encode()); h.update(b"\x00")
        return h.hexdigest()

    @staticmethod
    def _live_subgraph(G: nx.MultiDiGraph) -> nx.Graph:
        import networkx as nx  # deferred — see the TYPE_CHECKING note (review-r6: hook-import-tax)
        # The advisory ranks (degree/communities/betweenness/spec_betweenness) are computed over the
        # LIVE subgraph (§1.7). graph.json and the edges table stay COMPLETE — failure memory is never
        # pruned — but a `failed`/`rejected` edge must not inflate centrality: the adversarial grounder
        # stamps its attacked_by/confounded_by counter-edges `failed`, so counting them would make "more
        # refutation -> higher apparent centrality". `obsolete` is excluded for the SAME reason and for
        # consistency with the answer lane (kg_context excludes FAILURE_STATE_VALUES | {OBSOLETE}): a
        # SUPERSEDED relation is no longer live, so it must not confer degree/betweenness/community/bridge
        # weight while being invisible as an answer — previously obsolete was left IN centrality only,
        # an undocumented inconsistency (review-fix: L14). Excluding only the edges keeps every node
        # present (an attacked hub whose edges are all refuted still ranks honestly at degree 0).
        # The set is single-homed in model.NON_LIVE_STATE_VALUES and shared with generate._live_undirected,
        # which must exclude exactly the same edges or the generators walk a topology the ranks they read
        # were never computed over (review-r11).
        _excluded = NON_LIVE_STATE_VALUES
        live = nx.MultiDiGraph()
        live.add_nodes_from(G.nodes(data=True))
        live.add_edges_from((u, v, k, d) for u, v, k, d in G.edges(keys=True, data=True)
                            if d.get("epistemic_state") not in _excluded)
        return live.to_undirected()

    # ---- ranks (off the hot path)
    def _ranks(self, G: nx.DiGraph, *, prior_topo_sig: str | None = None,
               prior_betweenness: dict | None = None) -> Ranks:
        import networkx as nx  # deferred — see the TYPE_CHECKING note (review-r6: hook-import-tax)
        und = self._live_subgraph(G)
        comm = _leiden(und)
        # Degree is the DISTINCT-neighbour count, not the edge-multiplicity count. `und` is a MultiGraph
        # (to_undirected of a MultiDiGraph retains parallel edges), so `und.degree()` would count two
        # distinct relations between the same pair (e.g. A `grounds` B and A `bridges` B, both legal +
        # un-failed) as degree 2 for one neighbour — diverging from the bridge signal just below (which
        # uses `und.neighbors`, deduped) and from the glossary ("count of a node's connections" =
        # neighbours). The persisted `degree` drives query_graph ranking, the bridge advisory, and the
        # kg_agenda hub detector, so the two co-located signals must agree on what a connection is.
        # Exclude a node from its OWN neighbour set in BOTH the degree and the bridge-community span:
        # to_undirected keeps self-loops, so `und.neighbors(n)` yields `n` itself when one exists. A
        # self-loop is not a connection to another node — counting it would inflate degree by one and
        # could falsely flag a node as a structural_bridge (its own community would join the span).
        degree = {n: len(set(und.neighbors(n)) - {n}) for n in und.nodes()}
        bridges = {}
        for n in G.nodes():
            neigh_comms = {comm.get(nb) for nb in set(und.neighbors(n)) - {n}}
            neigh_comms.discard(None)
            bridges[n] = len(neigh_comms)

        # complete the bridge metric (PLAN Stage 2 / §2/§4), all OFF the hot path:
        #  - raw betweenness: the natural bridge metric, but confounded by generality (a vague node sits
        #    on many shortest paths for empty reasons).
        #  - specificity: IDF rarity of a node's label terms over the source corpus (the confound control).
        #  - spec_betweenness = betweenness * specificity: down-weights vague high-traffic hubs.
        # betweenness (the natural bridge metric) is a pure function of the live undirected topology, so
        # when that topology is unchanged since the last projection we REUSE the prior pass instead of
        # paying another O(V·E) computation on every reproject (projector-1) — the dominant cost of a
        # /kg-ground drain or any non-topological canon edit. A topology change (an added/removed edge,
        # or a verdict flipping an edge in/out of FAILURE_STATES per §1.7) moves topo_sig → recompute.
        topo_sig = self._topo_sig(und)
        if und.number_of_nodes() <= 2:
            betweenness = {n: 0.0 for n in und}
        elif (prior_betweenness is not None and prior_topo_sig and prior_topo_sig == topo_sig
              and all(n in prior_betweenness for n in und.nodes())):
            # Reuse only when EVERY live node has a prior value. A dangling edge target (a node present in
            # the undirected graph but never persisted to the nodes table) is absent from prior_betweenness,
            # so `.get(n, 0.0)` would zero-fill it — diverging from a full rebuild's real centrality for the
            # identical graph and destabilizing the specificity gate. If any such node exists, recompute.
            betweenness = {n: float(prior_betweenness[n]) for n in und.nodes()}
        else:
            betweenness = nx.betweenness_centrality(und)
        corpus = self._corpus()
        # the RAW corpus IDF seeds — computed ONCE and shared with the gate below (projector-low: idf_seeds
        # was previously computed a second time inside harness.specificity).
        raw_seeds = idf_seeds(corpus) if corpus else {}
        # merge the pack's author-pinned specificity_seeds OVER the corpus IDF (lowercased to match
        # idf_seeds' tokenization). An explicit pack seed wins, making the validated config actually
        # drive specificity / spec_betweenness (review-low: specificity_seeds was never consumed). The
        # gate keeps using raw_seeds (corpus-only), so this pack merge never perturbs the gate verdict.
        pack_seeds = self._spec_seeds()
        seeds = ({**raw_seeds, **{str(k).lower(): float(v) for k, v in pack_seeds.items()}}
                 if pack_seeds else raw_seeds)
        default = (sum(seeds.values()) / len(seeds)) if seeds else 1.0
        specificity = {n: node_specificity(G.nodes[n].get("label") or n, seeds, default) for n in G.nodes()}
        spec_betweenness = {n: betweenness.get(n, 0.0) * specificity.get(n, default) for n in G.nodes()}

        # the gate (one value per projection): does specificity-weighting separate real bridges from
        # vague high-traffic nodes beyond a churn band? Computed once via the harness (it measures the
        # confound + rank churn). gate_on decides only whether spec_betweenness is TRUSTED for ranking —
        # both raw and weighted values are always stored, so nothing is hidden.
        gate_on = 0
        try:
            # Decide the gate over the SAME live (failed/rejected-excluded) subgraph the stored ranks are
            # computed on — NOT the full graph G. Passing G let the adversarial grounder's `failed`
            # counter-edges (the exact edges §1.7 excludes from centrality) flip the gate that then
            # governs ranking of a live-subgraph spec_betweenness the gate never measured (review-M2).
            # `und` carries node attrs (incl. label) via `_live_subgraph`'s to_undirected, so
            # node_specificity works. Hand the gate the already-built undirected graph + betweenness +
            # raw seeds so it
            # neither rebuilds the graph nor recomputes betweenness/idf (projector-2/projector-3).
            verdict = _specificity_gate(None, corpus, precomputed_betweenness=betweenness,
                                        precomputed_seeds=raw_seeds, precomputed_undirected=und)
            gate_on = 1 if verdict.get("gate_on") else 0
        except Exception:  # noqa: BLE001 — a gate-computation hiccup must never break projection
            gate_on = 0
        # keyword construction (review-r5): six of these are indistinguishable bare dicts, so a
        # positional transposition would type-check and pass construction silently.
        return Ranks(community=comm, degree=degree, bridges=bridges, betweenness=betweenness,
                     spec_betweenness=spec_betweenness, specificity=specificity,
                     gate_on=gate_on, topo_sig=topo_sig)

    # ---- main
    def project(self, incremental: bool = True) -> ProjectReport:
        # Serialize the read+write critical section against canon writers AND other projectors: a
        # reprojection reads the whole canon then writes the derived layer, so without exclusion it
        # could persist a snapshot matching no single canon state, or two projectors could collide on
        # the SQLite write lock and crash a read (projector-1). Take the single-writer lease; if
        # another session holds it, skip and let the caller serve the existing derived layer (a later
        # read reprojects). Tests and the common single-session path never contend, so this is free.
        if not self.canon.try_acquire_lock():
            # another session is writing/projecting; serve the existing derived layer. But on a COLD
            # first read under contention there is no derived layer yet — create an empty schema'd
            # index + graph so the read tools return an empty graph instead of crashing on a missing
            # table (the next uncontended read reprojects for real). Schema creation is idempotent
            # (CREATE TABLE IF NOT EXISTS) and WAL-safe against a concurrent projector. ALSO heal an
            # OUTDATED schema here (not just a missing DB): after a plugin upgrade the DB may still
            # carry the pre-Stage-2 11-column `nodes` table, and _connect() is the only schema-heal
            # path (it drops/recreates the table with the full column set). Without this, a read under
            # contention would crash on `no such column: betweenness` for as long as the other session
            # holds the lease; the heal leaves the table empty until the next uncontended full reproject
            # repopulates it, so reads return an empty graph instead of crashing.
            if not self.db_path.exists() or self._schema_outdated():
                self._connect().close()
            if not self.graph_path.exists():
                import networkx as nx  # deferred — see the TYPE_CHECKING note (review-r6)
                # EXCLUSIVE create ("x"), not _atomic_write's replace: the lease-holder can finish a full
                # projection and write the REAL graph.json in the window between the existence check above
                # and this write, and an unconditional replace would clobber it with this empty placeholder
                # — leaving an empty graph.json shadowing a populated index until the next canon edit
                # (review-r8-15). "x" fails closed if the file now exists, so we only ever FILL an absent
                # file; the lease-holder's real graph always wins.
                try:
                    with open(self.graph_path, "x", encoding="utf-8") as f:
                        f.write(json.dumps(node_link_data(nx.MultiDiGraph())))
                except FileExistsError:
                    pass  # the lease-holder already wrote a real graph — keep it
            return ProjectReport(up_to_date=self.db_path.exists() and self.graph_path.exists(),
                                 contended=True)
        try:
            return self._project_locked(incremental)
        finally:
            self.canon.release_lock()

    def _project_locked(self, incremental: bool) -> ProjectReport:
        # Reuse the parse is_stale() just did for this same canon state (projector-5/-11): the cheap_sig
        # match proves no file changed between is_stale() and here, so the stashed nodes/hashes are
        # authoritative. Any writer touching the vault in the gap moves cheap_sig → cache miss → re-parse.
        cache = self._parse_cache
        self._parse_cache = None  # consume once, whether or not it hits
        cur_sig = self._cheap_sig()
        # prior meta is read BEFORE the parse (review-r6): the cache-miss parse is stat-gated
        # against it. Independent of the canon files, so the reorder changes nothing else.
        prior = self._read_meta() if self.db_path.exists() else {}
        if cache and cache.sig == cur_sig:
            nodes, cur_hashes, cur_stats = cache.nodes, cache.hashes, cache.stats
        else:
            nodes, cur_hashes, cur_stats = self._parse_canon(prior)
        head = self._head()
        prior_hashes = prior.get("file_hashes", {})
        # R3: the stale-verdict advisory is keyed on a hash of the SOURCE payload (SourceSet concat),
        # NOT the per-node canon hash (which never sees a source edit). Computed here, off the hot path —
        # is_stale (the per-read gate) is deliberately left source-blind (Q3 one-projection-lag).
        cur_source_hash = self._source_hash()

        do_full = (not incremental) or (not self.db_path.exists()) or (not prior_hashes) \
            or (not self.graph_path.exists()) or self._schema_outdated()
        report = ProjectReport(full_rebuild=do_full, built_from_commit=head)

        # Up-to-date requires the canon AND the source unchanged: a source edit alone (canon byte-
        # identical) must still fall through so the stale-verdict advisory refreshes — otherwise the flag
        # could never appear once a projection is actually invoked.
        if not do_full and prior.get("built_from_commit") == head and prior_hashes == cur_hashes \
                and prior.get("source_hash", "") == cur_source_hash:
            report.up_to_date = True
            report.n_nodes = len(nodes)
            # Count the DEDUPED canonical edges, exactly as a real projection does (G.number_of_edges()
            # below), not the raw per-note sum — the two disagree when a hand-edited cross-owner duplicate
            # id exists, making n_edges flip by one between an up-to-date no-op and any reproject on a
            # byte-identical canon (review-low: up_to_date n_edges mismatch).
            report.n_edges = len(self._canonical_edges(nodes))
            return report

        # R3: stale-verdict advisory (READ-ONLY). On a full rebuild OR a source change, re-scan ALL
        # grounded/failed span-present edges. Otherwise (canon-only change, source unchanged) re-check the
        # already-flagged edges (so a re-grounded/deleted one CLEARS) AND scan the edges on THIS
        # projection's `changed` notes — so a divergence introduced via the CANON (a hand-edited span on
        # an already-grounded edge) is caught too, without a full O(N) source scan.
        try:
            sources = self._source_set() if self._source_set else None
        except Exception:  # noqa: BLE001 — degrade to no-source (no staleness scan) rather than crash the projection
            sources = None
        changed = [] if do_full else [n for n in nodes if cur_hashes.get(n.id) != prior_hashes.get(n.id)]
        removed = [] if do_full else [nid for nid in prior_hashes if nid not in cur_hashes]
        if do_full or cur_source_hash != prior.get("source_hash", ""):
            stale = self._stale_verdicts(nodes, sources)
        else:
            refiltered = self._refilter_stale(prior.get("stale_verdicts") or [], nodes, sources)
            seen_ids = {s["edge_id"] for s in refiltered}
            stale = refiltered + [s for s in self._stale_verdicts(changed, sources)
                                  if s["edge_id"] not in seen_ids]

        # R3-MIRROR: the re-examinable-verdicts advisory (READ-ONLY, non-monotonic evidence). Same
        # source_hash pre-gate as R3, folded into the SAME `sources`/`nodes` pass (§8). On a full rebuild
        # OR a source change, term-filter every failed/rejected item against the CHANGED source text;
        # otherwise (canon-only change) just re-verify the already-flagged items so a re-grounded/deleted
        # one self-clears. On the full/source-moved branch we ALSO carry forward prior flags that still
        # qualify, so a LATER unrelated source change never silently drops an earlier, un-acted-on flag
        # (and a full rebuild with an UNCHANGED source keeps existing flags — changed_text is empty then,
        # so the fresh scan adds nothing and the carry-forward preserves them). It never mutates a verdict
        # and never re-queues anything (the grounder's queue stays unverified-only).
        cur_source_sigs = self._source_file_sigs(sources)
        prior_reexaminable = prior.get("reexaminable_verdicts") or []
        if do_full or cur_source_hash != prior.get("source_hash", ""):
            fresh_reex = self._reexaminable_verdicts(nodes, sources,
                                                     self._changed_source_text(sources, prior))
            carried_reex = self._refilter_reexaminable(prior_reexaminable, nodes, sources)
            seen_reex = {r["item_id"] for r in carried_reex}
            reexaminable = carried_reex + [r for r in fresh_reex if r["item_id"] not in seen_reex]
        else:
            reexaminable = self._refilter_reexaminable(prior_reexaminable, nodes, sources)

        G = self._build_graph(nodes)
        # On an incremental reproject hand _ranks the prior topology signature + prior betweenness so it
        # can skip the O(V·E) betweenness pass when the live topology is unchanged (projector-1). On a
        # full rebuild we pass nothing (the table is about to be rewritten from scratch → always compute).
        prior_topo_sig = None if do_full else prior.get("topo_sig", "")
        prior_betweenness = None if do_full else self._read_prior_betweenness()
        # Keep the single-writer lease fresh across the expensive critical section. project() holds the
        # lease for this whole read+compute+write span, and _ranks runs an O(V·E) pure-Python betweenness
        # pass; without a refresh a reprojection that outlives the lease TTL would be judged stale and
        # STOLEN by a concurrent writer mid-projection — breaking single-writer (the same hazard
        # write_nodes heartbeats against on a long batch). Refresh right before the betweenness pass and
        # again before the derived write, bounding the unheartbeated gap to a single betweenness pass.
        # heartbeat() is best-effort and swallows transient errors, so this never raises into projection.
        self.canon.lock.heartbeat()
        ranks = self._ranks(G, prior_topo_sig=prior_topo_sig, prior_betweenness=prior_betweenness)
        self.canon.lock.heartbeat()

        # graph.json is always written in full (cheap projection, must round-trip). Write atomically
        # (temp + os.replace) so a concurrent reader never observes a half-written file.
        data = node_link_data(G)
        # Determinism (review-fix: M7). A shell-hydrated reproject reads edges `ORDER BY rowid`, and rowids
        # are reassigned by `INSERT OR REPLACE` on incremental churn — so WITHOUT a stable emission sort,
        # graph.json's node/link order is a function of write HISTORY, not canon content, and a
        # byte-identical canon could emit a differently-ordered graph.json (violating the "graph.json is
        # reproducible" contract). Sort by content keys here so the SERIALIZED order is canonical regardless
        # of full-vs-shell parse or incremental history. Ranks/betweenness are computed on G above and are
        # order-invariant, so this only canonicalizes serialization — never a metric.
        data.get("nodes", []).sort(key=lambda n: str(n.get("id", "")))
        data.get("links", []).sort(
            key=lambda l: (str(l.get("source", "")), str(l.get("target", "")), str(l.get("id", ""))))
        data.setdefault("graph", {})["built_from_commit"] = head
        _atomic_write(self.graph_path, json.dumps(data, indent=2))

        if do_full:
            self._write_full(nodes, ranks, head, cur_hashes, report, cur_source_hash, stale,
                             cur_stats, reexaminable, cur_source_sigs)
        else:
            self._write_incremental(nodes, changed, removed, ranks, head, cur_hashes, report,
                                    cur_source_hash, stale, cur_stats, reexaminable, cur_source_sigs)
        # ranks (cheap_sig/topo_sig/etc.) are persisted by the write methods via _save_meta.

        report.n_nodes = G.number_of_nodes()
        report.n_edges = G.number_of_edges()
        report.communities = len(set(ranks.community.values()))
        return report

    # ---- sqlite
    # Both the DDL and the INSERT VALUES placeholder are generated from _NODE_COLUMNS so the column
    # set/order lives in exactly one place (no '(?,?,…)' whose '?' count must be hand-matched to 15).
    _NODES_DDL = ("CREATE TABLE IF NOT EXISTS nodes("
                  + ", ".join(f"{name} {sqltype}" for name, sqltype in _NODE_COLUMNS) + ")")
    _NODES_INSERT = ("INSERT OR REPLACE INTO nodes VALUES ("
                     + ",".join("?" * len(_NODE_COLUMNS)) + ")")
    # Same single-source treatment for `edges` (DDL / INSERT placeholder / incremental-diff SELECT),
    # all derived from _EDGE_COLUMNS so the column set/order lives in one place.
    _EDGES_DDL = ("CREATE TABLE IF NOT EXISTS edges("
                  + ", ".join(f"{name} {sqltype}" for name, sqltype in _EDGE_COLUMNS) + ")")
    _EDGES_INSERT = ("INSERT OR REPLACE INTO edges VALUES ("
                     + ",".join("?" * len(_EDGE_COLUMNS)) + ")")
    # Keyed on `owner` (the persisting note), NOT `source`: a changed note's edge diff must cover
    # exactly the rows that note contributed, or a removed foreign-source edge leaks (see _EDGE_COLUMNS).
    _EDGES_SELECT_BY_OWNER = ("SELECT " + ",".join(_EDGE_COLUMN_NAMES)
                              + " FROM edges WHERE owner=?")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA busy_timeout=5000")  # wait, don't raise, if another writer holds the lock
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
                {self._NODES_DDL};
                -- verdict_by/verdict_at are intentionally NOT columns here: verdict attribution lives
                -- authoritatively in the canon frontmatter + audit log (reconciler reads them from there).
                -- "derived contains nothing the canon does not" is one-directional — the derived layer MAY
                -- omit canon fields, so this is contractually allowed, not a gap.
                {self._EDGES_DDL};
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
                CREATE INDEX IF NOT EXISTS idx_nodes_degree ON nodes(degree);
                """
            )
            # idx_edges_owner is deliberately NOT in the script above: `owner` is a late-added column,
            # so on a pre-owner edges table (CREATE TABLE IF NOT EXISTS never adds columns) an eager
            # CREATE INDEX would raise "no such column" BEFORE the heal below could run. It is created
            # after the heal instead — see the end of this method.
            # CREATE TABLE IF NOT EXISTS cannot add the Stage-2 `nodes` columns — or the `owner`
            # edge column — to a pre-existing table. If either table is missing its late-added
            # columns, drop and recreate IT empty (a full reprojection — forced by _schema_outdated —
            # repopulates both). Done here so every connect path heals the schema. The pre-BEGIN read
            # below is only a cheap fast-path skip; the authoritative decision re-reads the columns
            # under the exclusive lock (TOCTOU guard).
            cols = {r[1] for r in con.execute("PRAGMA table_info(nodes)")}
            ecols = {r[1] for r in con.execute("PRAGMA table_info(edges)")}
            if not (_NEW_NODE_COLUMNS <= cols and _NEW_EDGE_COLUMNS <= ecols):
                # Heal an outdated schema by dropping + recreating the affected table(s) empty (a full
                # reproject, forced by _schema_outdated, repopulates them). Do the DROP+CREATE inside
                # ONE IMMEDIATE transaction so a concurrent lease-free WAL reader sees either the old
                # table or the new one — never the intermediate no-table state, which would raise "no
                # such table". executescript auto-commits between statements (reopening that window),
                # so drive explicit statements under manual transaction control instead.
                prior_iso = con.isolation_level
                con.isolation_level = None  # autocommit: BEGIN/COMMIT are explicit + predictable cross-version
                try:
                    con.execute("BEGIN IMMEDIATE")
                    try:
                        # Re-read the columns INSIDE the immediate transaction: a concurrent rebuild may
                        # have already healed + populated the tables between the pre-BEGIN read above and
                        # acquiring this exclusive lock. Dropping on that stale read would discard the
                        # freshly-projected rows, so only DROP/recreate what is STILL outdated under the
                        # lock.
                        healed = False
                        cols = {r[1] for r in con.execute("PRAGMA table_info(nodes)")}
                        if not _NEW_NODE_COLUMNS <= cols:
                            con.execute("DROP TABLE IF EXISTS nodes")
                            con.execute(self._NODES_DDL)
                            con.execute("CREATE INDEX IF NOT EXISTS idx_nodes_degree ON nodes(degree)")
                            healed = True
                        ecols = {r[1] for r in con.execute("PRAGMA table_info(edges)")}
                        if not _NEW_EDGE_COLUMNS <= ecols:
                            con.execute("DROP TABLE IF EXISTS edges")
                            con.execute(self._EDGES_DDL)
                            con.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)")
                            con.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)")
                            con.execute("CREATE INDEX IF NOT EXISTS idx_edges_owner ON edges(owner)")
                            healed = True
                        if healed:
                            # The DROP/CREATE just committed EMPTY new-schema tables; _write_full
                            # repopulates them in a SEPARATE transaction (`_connect` returns before that).
                            # Invalidate the stored staleness signature NOW, in the same transaction as the
                            # heal, so a crash in that window leaves is_stale()==True (no cheap_sig) and the
                            # next read reprojects — instead of trusting a committed-empty, schema-current
                            # index as "fresh" and serving an empty graph until an unrelated canon edit
                            # (review-fix: M6). _save_meta fully rewrites meta on the success path.
                            if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                                           "name='meta'").fetchone():
                                con.execute("DELETE FROM meta")
                        con.execute("COMMIT")
                    except Exception:
                        con.execute("ROLLBACK")
                        raise
                finally:
                    con.isolation_level = prior_iso
            # Safe only now: the edges table is guaranteed post-`owner` here — fresh (the DDL above
            # includes it), already current, or just healed by the transaction above.
            con.execute("CREATE INDEX IF NOT EXISTS idx_edges_owner ON edges(owner)")
            return con
        except Exception:
            con.close()  # never leak the connection if a PRAGMA/schema-heal step raises (returned only on success)
            raise

    def _schema_outdated(self) -> bool:
        """True if an index.sqlite exists but its `nodes` table predates the Stage-2 columns, or its
        `edges` table predates the `owner` column — forces a full rebuild so the late-added columns get
        populated for every row, not just the ones an incremental pass happens to touch."""
        if not self.db_path.exists():
            return False  # no db -> do_full is already True via the exists() check
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("PRAGMA busy_timeout=5000")  # another session's schema-heal DDL is exclusive
            try:
                cols = {r[1] for r in con.execute("PRAGMA table_info(nodes)")}
                ecols = {r[1] for r in con.execute("PRAGMA table_info(edges)")}
            finally:
                con.close()
        except sqlite3.Error:
            return True
        return not (_NEW_NODE_COLUMNS <= cols and _NEW_EDGE_COLUMNS <= ecols)

    def _node_row(self, n, ranks: Ranks) -> dict:
        """One node's persisted column values as a dict keyed by `_NODE_COLUMN_NAMES`, so callers read
        row['degree']/row['structural_bridge'] instead of bare DDL-order indices. structural_bridge is a
        pure function of bridge_communities (1 iff >= 2)."""
        bc = ranks.bridges.get(n.id, 0)
        return {
            "id": n.id, "label": n.label, "node_type": n.node_type, "file_type": n.file_type,
            "provenance": n.provenance.value, "authored_by": n.authored_by.value,
            "epistemic_state": n.epistemic_state.value,
            "degree": ranks.degree.get(n.id, 0), "community": ranks.community.get(n.id, -1),
            "bridge_communities": bc, "structural_bridge": 1 if bc >= 2 else 0,
            "betweenness": float(ranks.betweenness.get(n.id, 0.0)),
            "spec_betweenness": float(ranks.spec_betweenness.get(n.id, 0.0)),
            "specificity": float(ranks.specificity.get(n.id, 1.0)), "gate_on": int(ranks.gate_on),
        }

    @staticmethod
    def _node_values(row: dict) -> tuple:
        """A node row dict flattened to the positional value tuple in DDL order (`_NODES_INSERT`)."""
        return tuple(row[name] for name in _NODE_COLUMN_NAMES)

    @staticmethod
    def _edge_row(e, owner: str) -> tuple:
        """One edge's persisted column VALUES as a positional tuple in _EDGE_COLUMNS order. Built via a
        name->value dict and flattened through _EDGE_COLUMN_NAMES, so the order is DERIVED from the same
        single source the DDL / INSERT placeholder / incremental-diff SELECT use — the positional
        comparison in _write_incremental (cur SELECT row vs this tuple) can't desync on a column edit.
        `owner` is the id of the persisting NOTE (usually == e.source; see _EDGE_COLUMNS)."""
        v = {
            "id": e.id, "source": e.source, "target": e.target, "relation": e.relation,
            "provenance": e.provenance.value, "authored_by": e.authored_by.value,
            "epistemic_state": e.epistemic_state.value, "span": e.span, "source_file": e.source_file,
            "confidence": e.confidence.value, "confidence_score": e.confidence_score,
            "owner": owner,
        }
        return tuple(v[name] for name in _EDGE_COLUMN_NAMES)

    def _write_full(self, nodes, ranks: Ranks, head, hashes, report, source_hash, stale, stats,
                    reexaminable=None, source_file_sigs=None):
        con = self._connect()
        try:
            con.execute("DELETE FROM nodes")
            con.execute("DELETE FROM edges")
            con.executemany(
                self._NODES_INSERT,
                [self._node_values(self._node_row(n, ranks)) for n in nodes])
            canon_edges = self._canonical_edges(nodes)  # §1.4 deterministic cross-owner dedup (review-r8-10)
            con.executemany(self._EDGES_INSERT, [self._edge_row(e, owner) for e, owner in canon_edges])
            report.touched_nodes = [n.id for n in nodes]
            report.touched_edges = [e.id for e, _ in canon_edges]
            self._save_meta(con, head, hashes, ranks.gate_on, source_hash, stale, ranks.topo_sig,
                            stats, reexaminable, source_file_sigs)
            con.commit()
        finally:
            con.close()

    def _write_incremental(self, nodes, changed, removed, ranks: Ranks, head, hashes, report,
                           source_hash, stale, stats, reexaminable=None, source_file_sigs=None):
        con = self._connect()
        try:
            changed_ids = {c.id for c in changed}  # hoisted out of the per-node loop below
            vanished_ids: set = set()  # edge ids dropped by their owner this sweep — re-derived below
            # removed nodes: drop node + every edge its FILE contributed (owner, not source — a
            # hand-edited note can persist an edge whose source names another node; see _EDGE_COLUMNS)
            for nid in removed:
                con.execute("DELETE FROM nodes WHERE id=?", (nid,))
                con.execute("DELETE FROM edges WHERE owner=?", (nid,))
            for n in changed:
                con.execute(self._NODES_INSERT, self._node_values(self._node_row(n, ranks)))
                report.touched_nodes.append(n.id)
                # diff this note's edges against the DB; upsert only changed rows, delete vanished
                cur = {r[0]: r for r in con.execute(self._EDGES_SELECT_BY_OWNER, (n.id,))}
                new = {}
                for e in n.edges:
                    row = self._edge_row(e, n.id)
                    new[e.id] = row  # every id recorded so the vanished-edge sweep below keeps this note's set
                    if cur.get(e.id) == row:
                        continue
                    # §1.4 single-canonical-edge: a FOREIGN edge (its source names ANOTHER node) must not
                    # overwrite an existing NATURAL row (owner == source) for the same id — natural wins,
                    # matching the full build's _canonical_edges resolution so full/incremental agree
                    # (review-r8-10). A natural edge (source == this note) always wins over any foreign row.
                    if e.source != n.id:
                        clash = con.execute(
                            "SELECT owner, source FROM edges WHERE id=? AND owner<>?",
                            (e.id, n.id)).fetchone()
                        if clash and clash[0] == clash[1]:
                            continue  # an existing natural-owned row outranks this foreign edge
                    con.execute(self._EDGES_INSERT, row)
                    report.touched_edges.append(e.id)
                for eid in cur:
                    if eid not in new:
                        # Delete only OUR (owner==n.id) row for this vanished id, and remember the id: an
                        # UNCHANGED note may still declare the same edge FOREIGN (source names this note),
                        # in which case a full rebuild re-keys it to that surviving owner. Owner-scoping the
                        # delete + the re-derivation pass below keep incremental and full builds in
                        # agreement (review-low: cross-owner vanished-edge drop).
                        con.execute("DELETE FROM edges WHERE id=? AND owner=?", (eid, n.id))
                        report.touched_edges.append(eid)
                        vanished_ids.add(eid)
            # §1.4 cross-owner re-materialization: an edge that vanished from its owner above may still be
            # declared foreign by an UNCHANGED note. The incremental sweep can't see that (the shell it
            # hydrated for the unchanged note carries only MATERIALIZED edges, and the deduped-away foreign
            # row was never stored), so re-derive JUST the vanished ids from a full canon parse and upsert
            # any survivor with its winning owner (_canonical_edges). Paid ONLY when an edge actually
            # vanished (rare) — the common incremental path (no removals) never parses the full canon.
            if vanished_ids:
                for e, owner in self._canonical_edges(self.canon.all_nodes()):
                    if e.id in vanished_ids:
                        con.execute(self._EDGES_INSERT, self._edge_row(e, owner))
                        report.touched_edges.append(e.id)
            # refresh ranks for unchanged nodes only when a rank value actually moved. Betweenness/
            # spec_betweenness/specificity are GLOBAL — one new edge shifts them for distant nodes — so
            # they are diffed and refreshed here too, not just degree/community/bridge. Read every node's
            # prior rank tuple in ONE query instead of a SELECT per node (projector-N+1: the old per-node
            # `SELECT ... WHERE id=?` inside this loop was O(N) round-trips on every incremental reproject).
            # _RANK_DIFF_COLUMNS is the diff key; structural_bridge is left OUT of the diff because it is a
            # pure function of bridge_communities (which IS in the diff), so it can never move on its own.
            select_sql = ("SELECT id," + ",".join(_RANK_DIFF_COLUMNS) + " FROM nodes")
            update_sql = ("UPDATE nodes SET "
                          + ",".join(f"{c}=?" for c in _RANK_UPDATE_COLUMNS) + " WHERE id=?")
            prior_ranks = {r[0]: r[1:] for r in con.execute(select_sql)}
            for n in nodes:
                if n.id in changed_ids:
                    continue
                row = self._node_row(n, ranks)
                old = prior_ranks.get(n.id)
                new_vals = tuple(row[c] for c in _RANK_DIFF_COLUMNS)
                if old != new_vals:
                    con.execute(update_sql,
                                tuple(row[c] for c in _RANK_UPDATE_COLUMNS) + (n.id,))
            self._save_meta(con, head, hashes, ranks.gate_on, source_hash, stale, ranks.topo_sig,
                            stats, reexaminable, source_file_sigs)
            con.commit()
        finally:
            con.close()

    def _cheap_stat_map(self) -> "dict[str, tuple[int, int]]":
        """Per-note ``{name: (size, mtime_ns)}`` map — the GRANULAR form of ``_cheap_sig`` (same stat
        sweep, NO YAML parse / git fork), so a caller can detect WHICH notes moved rather than only THAT
        something did. Used by the kg_write baseline cache to re-read exactly the changed notes (ours OR
        a concurrent foreign writer's) instead of caching a stale baseline as fresh (review-low).
        ``note_paths()`` is already sorted, so ``.items()`` iteration order is stable."""
        out: "dict[str, tuple[int, int]]" = {}
        for p in self.canon.note_paths():
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.name] = (st.st_size, st.st_mtime_ns)
        return out

    @staticmethod
    def _sig_of_stat_map(stat_map: "dict[str, tuple[int, int]]") -> str:
        """The ``_cheap_sig`` digest of an already-computed stat map — one home for the hash so the sig
        and the map a caller diffs against can never drift, and both come from a SINGLE stat sweep."""
        h = hashlib.sha256()
        for name, (size, mtime_ns) in stat_map.items():
            h.update(f"{name}\x00{size}\x00{mtime_ns}\x00".encode())
        return h.hexdigest()

    def _cheap_sig(self) -> str:
        """A cheap signature of the canon dir — a digest over each note's (name, size, mtime) —
        computed with NO YAML parse and NO git fork. The fast staleness pre-gate (projector-2);
        per-node content hashing is the authoritative confirmation, run only when this signal moves.
        Digesting EVERY file's (size, mtime), not just the count + newest mtime, catches an in-place
        edit of a non-newest note (which would not move a max-mtime) and a same-mtime size change."""
        return self._sig_of_stat_map(self._cheap_stat_map())

    def _source_stat_sig(self) -> list:
        """A cheap ``[[basename, size, mtime_ns], …]`` signature of the source file(s) — NO content read
        — so is_stale() can catch a SOURCE-only edit (canon byte-identical) and still reproject, which is
        what refreshes the R3 stale-verdict / re-examinable advisories and the specificity ranks against
        the new source (review: source-blind staleness — _project_locked already handles a source_hash
        move, but only once a projection RUNS; without this gate a source-only edit never triggers one).
        Mirrors ``SourceSet.signature`` (same stat fields as _cheap_sig); ``[]`` when no source or on any
        hiccup, so a bare-source install simply never trips the gate."""
        try:
            if self._source_set is None:
                return []
            from .sources import SourceSet
            # list-of-lists so it round-trips through json identically to the stored value (tuples would
            # compare unequal to the json-decoded lists in is_stale).
            return [list(x) for x in SourceSet.signature(self._source_set().path)]
        except Exception:  # noqa: BLE001 — a source-stat hiccup degrades to "no signature", never crashes a read
            return []

    def _source_hash(self) -> str:
        """sha256 of the source payload (the SourceSet concat); '' when no source. R3's stale-verdict
        recompute pre-gate — moves on any add/remove/edit of any source file. Computed only inside a
        projection (off the hot path); is_stale gates a source-only edit on the cheap _source_stat_sig."""
        try:
            sources = self._source_set() if self._source_set else None
            payload = sources.concat if sources is not None else self._src_text()
        except Exception:  # noqa: BLE001 — a source-read hiccup degrades to "" (no source), matching _src_text's posture
            return ""
        return hashlib.sha256(payload.encode()).hexdigest() if payload else ""

    @staticmethod
    def _is_stale_edge(e, sources) -> bool:
        """The R3 staleness predicate: a grounded/failed span-present edge whose stored span no longer
        verifies against its OWN source_file. The single source of truth for both the full scan and the
        incremental refilter, so the two can never disagree about which edges are stale."""
        return (e.epistemic_state in (EpistemicState.GROUNDED, EpistemicState.FAILED)
                and e.provenance == Provenance.SPAN_PRESENT
                and not sources.verifies(e.span, source_file=e.source_file))

    @staticmethod
    def _stale_entry(e) -> dict:
        """The advisory record for a stale edge — one shape for both the full scan and the refilter."""
        return {"edge_id": e.id, "reason": "span-no-longer-in-source"}

    def _stale_verdicts(self, nodes, sources) -> list[dict]:
        """R3 — the source-staleness advisory (READ-ONLY). A grounded/failed span-present edge's stored
        span was verified at verdict time; if the source is later edited so it no longer appears, re-flag
        it as `span-no-longer-in-source`. Source-aware: each edge is checked against its OWN `source_file`
        (lenient any-source fallback), never a global concat — so a multi-file vault never false-flags an
        edge whose span lives in a non-default file. It NEVER mutates a verdict (re-grounding stays a
        kg_ground decision). Empty when no source is configured (no divergence without a source)."""
        if not sources:
            return []
        return [self._stale_entry(e) for n in nodes for e in n.edges
                if self._is_stale_edge(e, sources)]

    def _refilter_stale(self, prior, nodes, sources) -> list[dict]:
        """Re-verify ONLY the already-flagged edges against the current canon+source (the full re-scan is
        gated on do_full/source-moved). Drops a prior flag whose edge was deleted, re-grounded out of the
        grounded/failed set, or whose span verifies again — so a re-grounding clears its flag on the next
        projection even with an unchanged source. New staleness can only come from a source change (which
        moves the hash → full recompute), so this loses nothing."""
        if not prior or not sources:
            return []
        edges = {e.id: e for n in nodes for e in n.edges}
        return [self._stale_entry(e) for entry in prior
                if (e := edges.get(entry.get("edge_id"))) is not None
                and self._is_stale_edge(e, sources)]

    # ---- R3-mirror: the re-examinable-verdicts advisory (non-monotonic evidence, READ-ONLY)

    @staticmethod
    def _source_file_sigs(sources) -> dict:
        """Per-source-file content signatures ``{basename: sha256(text)}`` — the baseline the term-
        overlap filter diffs to find the CHANGED source text. Content-hashed (not stat), mirroring
        ``node_content_hash``'s content-not-mtime rule, so a byte-identical re-touch never registers as
        a change. ``{}`` when no source is configured."""
        if not sources:
            return {}
        try:
            texts = sources.texts  # {basename → raw_text} (a copy; the SourceSet is engine-memoized)
        except Exception:  # noqa: BLE001 — a source-read hiccup degrades to no signatures, never crashes projection
            return {}
        return {name: hashlib.sha256((t or "").encode()).hexdigest() for name, t in texts.items()}

    def _changed_source_text(self, sources, prior) -> str:
        """The concatenated text of source files whose CONTENT was not already in the prior corpus — the
        "what changed" the term-overlap filter (§Stage 6) tests each failed/rejected item against. Keyed
        on the SET of prior content hashes, not the per-basename signature, so a file that was merely
        RENAMED (identical bytes under a new basename) is NOT mistaken for newly-added evidence and does
        not spuriously flag every overlapping item (review-r8-12) — only text whose content is genuinely
        new to the corpus counts. Returns ``""`` (→ no item is re-examinable) when there is no source OR
        no prior signature baseline (a cold first projection, or the one-projection lag on a pre-feature
        index whose meta lacks ``source_file_sigs`` — mirroring R3's Q3 lag). Removed source files
        contribute nothing: a deleted source can't newly SUPPORT a failed idea."""
        if not sources or "source_file_sigs" not in prior:
            return ""
        prior_hashes = set((prior.get("source_file_sigs") or {}).values())
        try:
            texts = sources.texts
        except Exception:  # noqa: BLE001 — degrade to "no changed text" rather than crash the projection
            return ""
        changed = [t for _, t in texts.items()
                   if hashlib.sha256((t or "").encode()).hexdigest() not in prior_hashes]
        return "\n".join(changed)

    @staticmethod
    def _content_terms(text) -> set:
        """The non-trivial term set of a piece of text for the overlap filter: normalize (case/
        typographic fold, reusing model.normalize_text — the SAME primitive span verification uses),
        tokenize with ``_OVERLAP_WORD``, drop stopwords. Empty for empty/stopword-only text."""
        return {t for t in _OVERLAP_WORD.findall(normalize_text(text or ""))
                if t not in _OVERLAP_STOPWORDS}

    @classmethod
    def _node_terms(cls, n) -> set:
        """A node's own terms: its label + body. (An incremental-parse SHELL carries no body — the
        derived layer omits it — so a shell node contributes label terms only; a graceful degradation,
        the label being the salient text anyway.)"""
        return cls._content_terms(f"{n.label or ''} {n.body or ''}")

    @classmethod
    def _edge_terms(cls, e, by_id) -> set:
        """An edge's own terms: its span, notes, relation, and BOTH endpoint labels (falling back to the
        endpoint id — itself a slug of the label — for a dangling target). A rejected edge is typically
        span-less, so the endpoint labels + relation carry the relevance signal."""
        src = by_id.get(e.source)
        tgt = by_id.get(e.target)
        return cls._content_terms(" ".join([
            e.span or "", getattr(e, "notes", "") or "", e.relation or "",
            (src.label if src else e.source) or "", (tgt.label if tgt else e.target) or "",
        ]))

    @staticmethod
    def _reexaminable_entry(item_id, kind, state) -> dict:
        """The advisory record for one re-examinable item — one shape for the full scan and the refilter.
        ``kind`` is ``"node"``/``"edge"``; ``state`` is the current ``failed``/``rejected`` value."""
        return {"item_id": item_id, "kind": kind,
                "state": state.value if isinstance(state, EpistemicState) else state,
                "reason": "source-set-changed-since-judged"}

    def _full_note_for_terms(self, n):
        """Re-read a candidate note from canon so the term-overlap filter sees the FULL body + edge
        notes. This scan runs on a SOURCE-only change, whose projection takes the stat-gated incremental
        arm (canon file stats are unchanged) — which hydrates every node as a derived SHELL that omits
        the body and edge notes. Filtering a shell would silently narrow the overlap basis to
        label/span/relation/endpoint terms, so a pin whose substance lives in its body (materialize
        truncates the label to 80 chars and puts the full idea in the body) could never re-surface
        (review-r8-5). Re-reading is cheap — only failed/rejected candidates reach here — and degrades to
        the shell on any read fault, matching the projector's fail-to-degraded posture."""
        try:
            return self.canon.read_node(n.id)
        except Exception:  # noqa: BLE001 — a read hiccup degrades to the shell (label/endpoint terms only)
            return n

    def _reexaminable_verdicts(self, nodes, sources, changed_text="") -> list[dict]:
        """R3-MIRROR (READ-ONLY): failed/rejected items — nodes AND edges, span-present AND span-less —
        that were judged against a source set which has since changed, so they deserve a grounder re-look.
        Item-agnostic and span-agnostic on purpose (R3 covers neither nodes nor span-less items), because
        the motivating case — a falsified divergence pin — is a span-less node. It NEVER mutates a verdict
        (re-grounding stays a kg_ground decision) and never re-queues anything. Empty when no source is
        configured (mirror _stale_verdicts). The term-overlap filter (§Stage 6) keeps only items the
        CHANGED source text actually bears on — over the FULL node body + edge notes (re-read from canon
        for the small candidate set, not the body-less incremental shells); an empty ``changed_text`` (no
        detectable change) flags nothing — the filter carries the relevance load so the source-hash
        pre-gate need not."""
        if not sources:
            return []
        changed_terms = self._content_terms(changed_text)
        if not changed_terms:  # nothing meaningfully changed → nothing bears on any item
            return []
        by_id = {n.id: n for n in nodes}
        out: list[dict] = []
        for n in nodes:
            node_is_candidate = n.epistemic_state in _REEXAMINABLE_STATES
            edge_candidate = any(e.epistemic_state in _REEXAMINABLE_STATES for e in n.edges)
            if not node_is_candidate and not edge_candidate:
                continue  # most nodes: skip the canon re-read entirely
            full = self._full_note_for_terms(n)  # recover body + edge notes from canon (shell has neither)
            if node_is_candidate and (self._node_terms(full) & changed_terms):
                out.append(self._reexaminable_entry(n.id, "node", n.epistemic_state))
            for e in full.edges:
                if e.epistemic_state in _REEXAMINABLE_STATES and (self._edge_terms(e, by_id) & changed_terms):
                    out.append(self._reexaminable_entry(e.id, "edge", e.epistemic_state))
        return out

    def _refilter_reexaminable(self, prior, nodes, sources) -> list[dict]:
        """Re-verify ONLY the already-flagged items against the current canon (the term-overlap re-scan
        is gated on do_full/source-moved). Drops a prior flag whose item was DELETED or has LEFT
        ``{failed, rejected}`` (i.e. was re-grounded) — self-clearing, mirroring _refilter_stale. A flag,
        once raised, persists (regardless of later term overlap) until the item is re-grounded; new flags
        can only come from a source change (which moves source_hash → the full re-scan branch), so this
        loses nothing. Empty when no source is configured."""
        if not prior or not sources:
            return []
        node_state = {n.id: n.epistemic_state for n in nodes}
        edge_state = {e.id: e.epistemic_state for n in nodes for e in n.edges}
        out: list[dict] = []
        for entry in prior:
            item_id, kind = entry.get("item_id"), entry.get("kind")
            state = node_state.get(item_id) if kind == "node" else edge_state.get(item_id)
            if state in _REEXAMINABLE_STATES:
                out.append(self._reexaminable_entry(item_id, kind, state))
        return out

    def _save_meta(self, con, head, hashes, gate_on=0, source_hash="", stale_verdicts=None, topo_sig="",
                   stats=None, reexaminable_verdicts=None, source_file_sigs=None):
        con.execute("INSERT OR REPLACE INTO meta VALUES ('built_from_commit', ?)", (head,))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('file_hashes', ?)", (json.dumps(hashes),))
        # the per-file stat map the review-r6 incremental parse gates on: {name: [size, mtime_ns, id]}.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('file_stats', ?)",
                    (json.dumps(stats or {}, sort_keys=True),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('cheap_sig', ?)", (json.dumps(self._cheap_sig()),))
        # cheap (name,size,mtime) source signature — the SOURCE-side twin of cheap_sig, so is_stale() can
        # detect a source-only edit (canon byte-identical) and still reproject (review: source-blind
        # staleness). Self-computed here, like cheap_sig, so it needs no threading through the callers.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('source_stat_sig', ?)",
                    (json.dumps(self._source_stat_sig()),))
        # the live-topology signature these ranks were computed over (projector-1): lets the next
        # projection reuse betweenness when the topology is unchanged.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('topo_sig', ?)", (topo_sig or "",))
        # the bridge-metric gate verdict for this projection (PLAN Stage 2): one value, read by
        # kg_context to decide whether spec_betweenness is the TRUSTED ranking signal this projection.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('gate_on', ?)", (str(int(gate_on)),))
        # R3 source-staleness advisory: the source-payload hash (recompute pre-gate) + the flagged ids.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('source_hash', ?)", (source_hash or "",))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('stale_verdicts', ?)",
                    (json.dumps(stale_verdicts or []),))
        # R3-mirror re-examinable-verdicts advisory: the flagged failed/rejected items (nodes + edges)
        # and the per-source-file signature baseline the term-overlap filter diffs to find changed text.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('reexaminable_verdicts', ?)",
                    (json.dumps(reexaminable_verdicts or []),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('source_file_sigs', ?)",
                    (json.dumps(source_file_sigs or {}, sort_keys=True),))

    def _read_meta(self) -> dict:
        try:
            con = sqlite3.connect(self.db_path)
            # _read_meta runs on EVERY read via is_stale(). Without this, a reader that lands inside
            # another session's `BEGIN IMMEDIATE` schema heal gets `database is locked` immediately (WAL
            # does not cover the exclusive DDL window), degrades to {} -> "stale" -> a spurious full
            # rebuild that then contends on the lease. Wait instead of raising (review-r11).
            con.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            return {}
        try:
            rows = dict(con.execute("SELECT key,value FROM meta").fetchall())
        except sqlite3.Error:
            return {}
        finally:
            con.close()  # always close, even if the query raised (no leaked connection)
        out = {"built_from_commit": rows.get("built_from_commit", "")}
        # Catch TypeError too (not just ValueError): a NULL/non-string meta value (corruption) makes
        # json.loads raise TypeError, which must degrade to the default — matching _read_stale_advisory.
        try:
            out["file_hashes"] = json.loads(rows.get("file_hashes", "{}"))
        except (ValueError, TypeError):
            out["file_hashes"] = {}
        try:  # absent on a pre-review-r6 index -> {} -> _parse_canon falls back to the full parse
            out["file_stats"] = json.loads(rows.get("file_stats", "{}"))
        except (ValueError, TypeError):
            out["file_stats"] = {}
        try:
            out["cheap_sig"] = json.loads(rows.get("cheap_sig", "null"))
        except (ValueError, TypeError):
            out["cheap_sig"] = None
        out["source_hash"] = rows.get("source_hash", "")  # R3 stale-verdict recompute pre-gate
        # source_stat_sig is read ABSENT-PRESERVING (None when the row is missing, like source_file_sigs):
        # a pre-feature index has no such row, and is_stale's source gate keys "skip until next projection"
        # on the value being None — so a missing row must NOT default to [] (which would read as "a real
        # prior of zero source files" and force a spurious reproject on every read of a bare-source graph).
        if "source_stat_sig" in rows:
            try:
                out["source_stat_sig"] = json.loads(rows["source_stat_sig"])
            except (ValueError, TypeError):
                out["source_stat_sig"] = None
        else:
            out["source_stat_sig"] = None
        out["topo_sig"] = rows.get("topo_sig", "")         # projector-1 betweenness-reuse signature
        try:
            out["stale_verdicts"] = json.loads(rows.get("stale_verdicts", "[]"))
        except (ValueError, TypeError):
            out["stale_verdicts"] = []
        try:
            out["reexaminable_verdicts"] = json.loads(rows.get("reexaminable_verdicts", "[]"))
        except (ValueError, TypeError):
            out["reexaminable_verdicts"] = []
        # source_file_sigs is read ABSENT-PRESERVING (not defaulted like the keys above): a pre-feature
        # index has no such row, and _changed_source_text keys the "no baseline → flag nothing" cold-
        # start rule on the KEY being missing. Defaulting it to {} would make a pre-feature index look
        # like "a real prior baseline of zero files", diffing the whole current source as newly-added
        # and flagging every failed/rejected item on the first post-upgrade projection.
        if "source_file_sigs" in rows:
            try:
                out["source_file_sigs"] = json.loads(rows["source_file_sigs"])
            except (ValueError, TypeError):
                out["source_file_sigs"] = {}
        return out

    def _read_prior_betweenness(self) -> dict | None:
        """The prior projection's betweenness per node, read from the index in ONE query — fed back into
        _ranks so a topology-unchanged reproject reuses it instead of recomputing (projector-1). None if
        the index is unreadable (→ recompute)."""
        if not self.db_path.exists():
            return None
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("PRAGMA busy_timeout=5000")  # a locked read here forces a needless O(V*E) recompute
            try:
                return {r[0]: r[1] for r in con.execute("SELECT id,betweenness FROM nodes")}
            finally:
                con.close()
        except sqlite3.Error:
            return None

    def _rearm_cheap_sig(self, sig: str, stats: "dict | None" = None) -> None:
        """Persist the current cheap-signature when is_stale() proves (via the content-hash fallthrough)
        that the canon is unchanged though its mtimes moved (projector-2/finding #2). Without this the
        cheap pre-gate stays stuck at the pre-touch value and every later is_stale() pays a full O(N)
        canon parse forever. ``stats`` (review-r6) re-arms the per-FILE stat map the same way — a
        touched-but-identical note would otherwise stay "changed" against the stored stats and be
        re-parsed on every later confirmation. Best-effort + lock-free: single-key meta upserts are
        WAL-safe under busy_timeout; a read-only/locked vault just keeps the slow path (never raises
        from a read)."""
        try:
            con = sqlite3.connect(self.db_path)
            try:
                con.execute("PRAGMA busy_timeout=5000")
                con.execute("INSERT OR REPLACE INTO meta VALUES ('cheap_sig', ?)", (json.dumps(sig),))
                if stats is not None:
                    con.execute("INSERT OR REPLACE INTO meta VALUES ('file_stats', ?)",
                                (json.dumps(stats, sort_keys=True),))
                con.commit()
            finally:
                con.close()
        except sqlite3.Error:
            pass

    # ---- the review-r6 incremental canon parse (stat-gated; shells for unchanged files)

    def _parse_canon(self, prior: dict) -> "tuple[list, dict, dict]":
        """(nodes, file_hashes, file_stats) for the CURRENT canon — the ONE parse the staleness
        confirmation (is_stale) and projection (_project_locked) share. Parses only the files whose
        (size, mtime_ns) moved since the prior projection and rebuilds the rest as derived-row
        shells (review-r6: any one-note edit used to cost a full-canon YAML parse); node order stays
        note_paths order (exactly all_nodes'), and a stat-unchanged file reuses its STORED content
        hash. stat-unchanged ⇒ treated as content-unchanged: the same trust the cheap_sig pre-gate
        has always granted the canon as a whole (an mtime-spoofed edit is the reconciler full
        sweep's job, §1.8), now applied per file. Every precondition failure — no prior stats or
        hashes, outdated schema, an id missing from the index, duplicate node ids, a sqlite error —
        falls back to the full parse, so this path is never worse than the old one."""
        entries = []
        for p in self.canon.note_paths():
            try:
                st = p.stat()
            except OSError:
                continue  # vanished mid-scan (matches _cheap_sig's skip): treated as removed
            entries.append((p, st.st_size, st.st_mtime_ns))
        prior_stats = prior.get("file_stats") or {}
        prior_hashes = prior.get("file_hashes") or {}
        if prior_stats and prior_hashes and self.db_path.exists() and not self._schema_outdated():
            out = self._parse_canon_incremental(entries, prior_stats, prior_hashes)
            if out is not None:
                return out
        nodes, hashes, stats = [], {}, {}
        for p, size, mt in entries:
            n = self.canon.parse_note(p)
            if n is None:
                continue
            nodes.append(n)
            hashes[n.id] = self._file_hash(n)
            stats[p.name] = [size, mt, n.id]
        return nodes, hashes, stats

    def _parse_canon_incremental(self, entries, prior_stats, prior_hashes):
        """The stat-gated arm of _parse_canon; None means "fall back to the full parse"."""
        plan = []
        for p, size, mt in entries:
            e = prior_stats.get(p.name)
            hid = (e[2] if isinstance(e, list) and len(e) == 3 and e[0] == size and e[1] == mt
                   and e[2] in prior_hashes else None)
            plan.append((p, size, mt, hid))
        shells = self._shell_nodes_from_derived([hid for *_, hid in plan if hid is not None])
        if shells is None:
            return None
        nodes, hashes, stats = [], {}, {}
        for p, size, mt, hid in plan:
            if hid is not None:
                n = shells[hid]
            else:
                n = self.canon.parse_note(p)
                if n is None:
                    continue
            nodes.append(n)
            hashes[n.id] = prior_hashes[hid] if hid is not None else self._file_hash(n)
            stats[p.name] = [size, mt, n.id]
        if len(hashes) != len(nodes):
            # duplicate node ids across files: whose content wins is order-dependent, and a shell
            # could launder the stale copy — let the full parse decide exactly as before.
            return None
        return nodes, hashes, stats

    def _shell_nodes_from_derived(self, ids: list) -> "dict[str, Node] | None":
        """PROJECTION SHELLS ONLY — Node objects rebuilt from the derived rows for stat-UNCHANGED
        canon files. The derived layer deliberately omits canon-only fields (body, timestamps,
        verdict_by/verdict_at, edge notes — see _connect's DDL comment), so a shell must NEVER be
        written back to the canon or content-hashed; the projector reuses the file's stored hash and
        only feeds shells to _build_graph / _ranks / _stale_verdicts / _node_row / _edge_row, whose
        column sets the derived rows cover completely. Returns None (→ full parse) when any id is
        missing, a pre-owner edge row exists (ownership unknowable), or the index is unreadable."""
        if not ids:
            return {}
        want = set(ids)
        try:
            con = sqlite3.connect(self.db_path)
            con.row_factory = sqlite3.Row
            try:
                con.execute("PRAGMA busy_timeout=5000")
                if con.execute("SELECT COUNT(*) FROM edges WHERE owner IS NULL").fetchone()[0]:
                    return None
                nrows = list(con.execute("SELECT * FROM nodes"))
                # ORDER BY rowid: a shell's edge order is its derived insertion order (not the canon
                # file order, which only a parse can know) — pinned so identical indexes hydrate
                # identically across platforms.
                erows = list(con.execute(
                    "SELECT " + ",".join(_EDGE_COLUMN_NAMES) + " FROM edges ORDER BY rowid"))
            finally:
                con.close()
        except sqlite3.Error:
            return None
        by_owner: dict = {}
        for r in erows:
            by_owner.setdefault(r["owner"], []).append(r)
        shells: "dict[str, Node]" = {}
        for r in nrows:
            nid = r["id"]
            if nid not in want:
                continue
            edges = [Edge(source=e["source"], target=e["target"], relation=e["relation"],
                          provenance=e["provenance"], authored_by=e["authored_by"],
                          epistemic_state=e["epistemic_state"], span=e["span"] or "",
                          source_file=e["source_file"] or "", confidence=e["confidence"],
                          confidence_score=e["confidence_score"])
                     for e in by_owner.get(nid, ())]
            shells[nid] = Node(id=nid, label=r["label"], node_type=r["node_type"],
                               file_type=r["file_type"], provenance=r["provenance"],
                               authored_by=r["authored_by"], epistemic_state=r["epistemic_state"],
                               edges=edges)
        if want - set(shells):
            return None
        return shells

    def is_stale(self) -> bool:
        if not self.db_path.exists() or not self.graph_path.exists():
            return True
        # schema gate (review-H2): a derived DB built before the Stage-2 node columns
        # (betweenness/spec_betweenness/specificity/gate_on) must reproject EVEN when the canon is
        # unchanged — else the cheap-sig short-circuit below returns False forever on a read-only vault
        # after a plugin upgrade, and every read tool crashes with `no such column: betweenness` (the
        # read path's _ro() has no schema-heal). _schema_outdated() is a single O(1) PRAGMA, cheap
        # enough to front every read; a True here forces a full reproject that heals the schema.
        if self._schema_outdated():
            return True
        prior = self._read_meta()
        # source pre-gate (review: source-blind staleness): a source-only edit leaves the canon
        # byte-identical, so the canon cheap_sig below would return "not stale" and the R3 stale-verdict /
        # re-examinable advisories and specificity ranks would freeze — never recomputing in their own
        # edit-source-then-query workflow. A cheap (name,size,mtime) source signature (no content read)
        # catches it and forces the reproject, where _project_locked's source_hash compare does the
        # authoritative recompute. Absent on a pre-feature index (source_stat_sig is None) → gate skipped,
        # mirroring the R3 Q3 one-projection-lag until the next projection writes the key.
        prior_source_stat = prior.get("source_stat_sig")
        if prior_source_stat is not None and prior_source_stat != self._source_stat_sig():
            return True
        # cheap pre-gate (projector-2): if the canon dir's (count, newest mtime) is unchanged since the
        # last projection, nothing on disk changed -> not stale, WITHOUT a git fork or a full YAML
        # parse. This fronts EVERY read, so it must stay O(dir-listing), not O(N parse).
        cur_sig = self._cheap_sig()
        if prior.get("cheap_sig") is not None and prior["cheap_sig"] == cur_sig:
            return False
        # the cheap signal moved -> authoritative per-node content-hash comparison. This catches any
        # uncommitted canon change (a kg_ground verdict, a hand edit) regardless of HEAD; content
        # equality means the derived layer matches the canon whatever the commit is. The parse is
        # stat-gated per file (review-r6): only files whose (size, mtime_ns) moved are re-parsed and
        # re-hashed; the rest reuse their stored hash and hydrate as derived-row shells.
        nodes, cur_hashes, cur_stats = self._parse_canon(prior)
        if prior.get("file_hashes", {}) == cur_hashes:
            # content is identical though the cheap signal moved (an mtime-only touch: a no-op checkout,
            # an editor re-save, or an idempotent kg_write/kg_ground that rewrote a note to identical
            # bytes — os.replace always yields a fresh mtime). Re-arm the cheap pre-gate (and the
            # per-file stat map, review-r6) so the NEXT is_stale() short-circuits instead of
            # re-parsing the whole canon forever (finding #2).
            self._rearm_cheap_sig(cur_sig, cur_stats)
            return False
        # genuinely stale -> stash this parse so the project() that follows reuses it rather than parsing
        # the whole canon a second time (projector-5/-11). cur_sig keys the cache so a concurrent write
        # in the gap invalidates it.
        self._parse_cache = _ParseCache(sig=cur_sig, nodes=nodes, hashes=cur_hashes, stats=cur_stats)
        return True


    # ---- the read-only query surface, delegated to DerivedReader (review-r5: ~420 lines of
    # query methods lived inside this writer class while touching nothing of it but db_path —
    # readers of the hot query path had to scroll past locking/DDL/heal machinery they could
    # never affect). The seam every consumer holds (a Projector) is unchanged: these thin
    # delegates forward to the composed reader.

    @property
    def reader(self) -> "DerivedReader":
        return DerivedReader(self.db_path)

    def _ro(self):
        return self.reader._ro()

    def load_graph(self):
        return self.reader.load_graph()

    def owner_of_edge(self, edge_id: str) -> "str | None":
        return self.reader.owner_of_edge(edge_id)

    def get_node(self, node_id: str) -> "dict | None":
        return self.reader.get_node(node_id)

    def get_neighbors(self, node_id: str, *, relation: "str | None" = None) -> "list[dict]":
        return self.reader.get_neighbors(node_id, relation=relation)

    def query_graph(self, **kw) -> dict:
        return self.reader.query_graph(**kw)

    def shortest_path(self, source: str, target: str) -> "list[str] | None":
        return self.reader.shortest_path(source, target)

    def kg_context(self, query: "str | None" = None, *, budget: int = 2000) -> dict:
        return self.reader.kg_context(query, budget=budget)

    def kg_agenda(self, *, limit: int = 5) -> dict:
        return self.reader.kg_agenda(limit=limit)

    def _agenda_reader(self):
        return self.reader._agenda_reader()



def _agenda_signals(n: dict) -> dict:
    """The honest signals carried on each suggestion so the ranking is transparent — degree (the
    advisory), the structural-bridge / betweenness / specificity columns, never a minted scalar."""
    return {
        "degree": n.get("degree") or 0,
        "community": n.get("community"),
        "structural_bridge": n.get("structural_bridge") or 0,
        "betweenness": n.get("betweenness") or 0.0,
        "spec_betweenness": n.get("spec_betweenness") or 0.0,
        "specificity": n.get("specificity"),
    }


def _neighbor_labels(nid: str, live_edges: list, by_id: dict, *, cap: int = 4) -> list:
    names, seen = [], set()
    for e in live_edges:
        other = e.get("target") if e.get("source") == nid else e.get("source")
        if other == nid or other in seen:
            continue
        seen.add(other)
        names.append((by_id.get(other) or {}).get("label") or other)
        if len(names) >= cap:
            break
    return names


def _agenda_from_rows(nodes: list, edges: list, *, limit: int = 5) -> dict:
    """Pure R6 agenda builder over precomputed derived rows (no DB, no canon — testable in isolation).

    Detectors (each node matches at most one): orphan (degree 0), hypothesized-only (every live edge a
    proposal), well-grounded hub (answerable), under-grounded hub (blocked), plus edgeless-communities
    (a disconnected cluster of >=2 nodes). Ranked by the gate-aware honest signal — `spec_betweenness`
    ONLY when `gate_on=1`, else `structural_bridge`/betweenness/degree (mirroring kg_context's switch;
    never raw betweenness as lead). Split into the two lanes, each capped at `limit`. Read-only — it
    only inspects rows and returns text."""
    limit = max(1, min(int(limit), MAX_AGENDA_LIMIT))
    gate_on = int(next((n.get("gate_on") for n in nodes if n.get("gate_on") is not None), 0) or 0)
    # the gate-aware ranking — same source of truth as kg_context (gate_ranking); never raw betweenness
    # as lead. The shared `rank_cols` keep the two surfaces' tie-break order from silently diverging.
    ranked_by, rank_cols = gate_ranking(gate_on)
    by_id = {n["id"]: n for n in nodes}

    incident: dict = {n["id"]: [] for n in nodes}
    for e in edges:
        for endp in (e.get("source"), e.get("target")):
            if endp in incident:
                incident[endp].append(e)

    def rank_key(n: dict):  # mirror kg_context's gate switch via the shared rank_cols
        return tuple(_RANK_COERCE[c][0](n.get(c) or _RANK_COERCE[c][1]) for c in rank_cols)

    gaps: list = []  # (rank_key, id, item) — the id is the deterministic tiebreak (see the final sort)
    emitted: set = set()  # node ids already surfaced by a node-level detector (one detector per node)

    for n in nodes:
        nid = n["id"]
        label = n.get("label") or nid
        deg = n.get("degree") or 0
        # NON_LIVE, not failure-only: `deg` below is read from the nodes table, which the projector
        # computed over _live_subgraph (failures AND `obsolete` excluded). Filtering this `live` set on
        # the narrower FAILURE set let the two disagree about the same edge — a node whose only other
        # relation was superseded failed the `all(hypothesized)` test and dropped out of the agenda
        # entirely, while the identical graph with that edge `rejected` surfaced normally (review-r12).
        live = [e for e in incident[nid] if e.get("epistemic_state") not in NON_LIVE_STATE_VALUES]
        grounded = sum(1 for e in live if e.get("epistemic_state") == "grounded")
        unverified = sum(1 for e in live if e.get("epistemic_state") == "unverified")
        decided = grounded + unverified

        if deg == 0:
            item = {"detector": "orphan", "lane": "blocked_on_grounding", "focus": [nid],
                    "question": f"'{label}' is isolated — it has no live relations. What should connect "
                                f"to it, and can that be grounded?"}
        elif live and all(e.get("provenance") == "hypothesized" for e in live):
            item = {"detector": "hypothesized-only", "lane": "blocked_on_grounding", "focus": [nid],
                    "question": f"Every relation on '{label}' is a hypothesis — its role is unverified. "
                                f"Ground them (/kg-ground) before treating it as established."}
        elif deg >= _HUB_DEGREE and decided and grounded / decided >= _GROUNDED_RATIO:
            nbrs = _neighbor_labels(nid, live, by_id)
            item = {"detector": "well-grounded", "lane": "answerable_now", "focus": [nid],
                    "question": f"'{label}' is a well-grounded hub (degree {deg}, {grounded} grounded) — "
                                f"how do its neighbours ({', '.join(nbrs)}) interrelate?"}
        elif deg >= _HUB_DEGREE and decided and grounded / decided < _GROUNDED_RATIO:
            item = {"detector": "under-grounded-hub", "lane": "blocked_on_grounding", "focus": [nid],
                    "question": f"Hub '{label}' (degree {deg}) is under-grounded — only {grounded}/{decided} "
                                f"of its edges are grounded. Drain its unverified queue (/kg-ground) to trust it."}
        else:
            continue
        item["signals"] = _agenda_signals(n)
        gaps.append((rank_key(n), nid, item))
        emitted.add(nid)  # this node is now covered — don't re-surface it in an edgeless-communities item

    # edgeless communities: a disconnected cluster (>=2 nodes, no LIVE inter-community edge) — a coverage
    # gap, never answerable now. A single isolated node is already an `orphan`, so require >=2 members.
    comm_of = {n["id"]: n.get("community") for n in nodes}
    present = {c for c in comm_of.values() if c is not None and c != -1}
    if len(present) > 1:
        crossing: set = set()
        for e in edges:
            # NON_LIVE, matching the `live` set above and _live_subgraph: a community reachable ONLY
            # through a superseded edge is as disconnected as one reachable only through a refuted
            # one, so it must still surface as a coverage gap (review-r12).
            if e.get("epistemic_state") in NON_LIVE_STATE_VALUES:
                continue
            a, b = comm_of.get(e.get("source")), comm_of.get(e.get("target"))
            if a is not None and b is not None and a != b:
                crossing.add(a)
                crossing.add(b)
        for c in sorted(present - crossing):
            # exclude members already surfaced by a node-level detector — so a lone island (an `orphan`)
            # and a small cluster whose nodes are each already a gap (e.g. a freshly-proposed
            # hypothesized-only pair) are NOT re-surfaced here (one detector per node). Fire only when
            # >=2 members remain genuinely uncovered.
            # id ASC before choosing anything from `fresh`: `nodes` arrives from an unordered
            # `SELECT * FROM nodes` (and INSERT OR REPLACE reassigns rowids on incremental churn), so a
            # degree tie would make `max` pick a different representative — hence a different question
            # string, rank_key and focus order — between a full rebuild and an incremental reproject of
            # the byte-identical canon. The outer `gaps` list already takes this precaution below; the
            # item internals did not (review-r11).
            fresh = sorted((m for m in nodes if m.get("community") == c and m["id"] not in emitted),
                           key=lambda m: m["id"])
            if len(fresh) < 2:
                continue
            rep = max(fresh, key=lambda m: m.get("degree") or 0)  # first maximal on a tie == lowest id
            labels = ", ".join((m.get("label") or m["id"]) for m in fresh[:_STALE_PREVIEW_LABELS])
            more = "…" if len(fresh) > _STALE_PREVIEW_LABELS else ""
            gaps.append((rank_key(rep), rep["id"], {
                "detector": "edgeless-communities", "lane": "blocked_on_grounding",
                "focus": [m["id"] for m in fresh],
                "question": f"The '{rep.get('label') or rep['id']}' cluster ({labels}{more}) is disconnected "
                            f"from the rest of the graph — what relation bridges it?",
                "signals": _agenda_signals(rep)}))

    # Deterministic order: rank_key DESC, then node id ASC as the unique tiebreak — the input `nodes`
    # arrive from an unordered `SELECT * FROM nodes`, so without the id the order among rank-tied
    # suggestions (the common case: most nodes share betweenness/spec_betweenness 0.0 and a small degree)
    # is not reproducible across reprojections. A stable pre-sort by id ASC, then a stable sort by
    # rank_key DESC (reverse=True), leaves ties ordered by id ASC.
    gaps.sort(key=lambda gi: gi[1])           # id ASC (stable base order for ties)
    gaps.sort(key=lambda gi: gi[0], reverse=True)
    answerable: list = []
    blocked: list = []
    for _, _id, item in gaps:
        bucket = answerable if item["lane"] == "answerable_now" else blocked
        if len(bucket) < limit:
            bucket.append(item)
    return {
        "answerable_now": answerable,
        "blocked_on_grounding": blocked,
        "count": len(answerable) + len(blocked),
        "limit": limit,
        "gate_on": gate_on,
        "ranked_by": ranked_by,
        "note": ("structural suggestions — a heuristic, not a guarantee. answerable_now reads grounded "
                 "content; blocked_on_grounding needs grounding (or extraction) first."),
    }


class DerivedReader:
    """The read-only query surface over one derived index (review-r5: extracted from Projector,
    whose other half is the derived-layer WRITER — locking, DDL, heal, ranks). Everything here
    reads precomputed columns O(1); NO centrality is computed in-request. Constructed cheaply from
    the db path alone, so the writer composes one on demand and the two concerns can no longer
    couple accidentally."""

    def __init__(self, db_path):
        self.db_path = db_path
    def _ro(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA busy_timeout=5000")  # tolerate a concurrent reprojection mid-read
        con.row_factory = sqlite3.Row
        return con

    def load_graph(self) -> nx.MultiDiGraph:
        """Build an in-memory MultiDiGraph from the derived index, with every precomputed rank column
        attached as a node attribute (PLAN Stage 3 — the generative layer reads ranks O(1) off this).
        Read-only; assumes the caller has already projected. A dangling edge target (a node referenced
        but not itself a canon note) is auto-created attribute-less, so generators must `.get()` ranks."""
        import networkx as nx  # deferred — see the TYPE_CHECKING note (review-r6: hook-import-tax)
        con = self._ro()
        try:
            G = nx.MultiDiGraph()
            for r in con.execute("SELECT * FROM nodes"):
                d = dict(r)
                G.add_node(d.pop("id"), **d)
            for r in con.execute("SELECT * FROM edges"):
                d = dict(r)
                G.add_edge(d["source"], d["target"], key=d["id"], **d)
            return G
        finally:
            con.close()

    def owner_of_edge(self, edge_id: str) -> str | None:
        """Owning-NOTE id for an edge, via the indexed edges table (O(1) lookup); None if absent.
        Lets kg_ground resolve an edge's owner without an O(N) full-canon scan per call (server-2).
        Reads the `owner` column (the persisting file), not `source`: a hand-edited note may carry an
        edge whose source names another node, and the caller wants the note that HOLDS the edge."""
        con = self._ro()
        try:
            r = con.execute("SELECT owner FROM edges WHERE id=?", (edge_id,)).fetchone()
            return r[0] if r else None
        finally:
            con.close()

    def get_node(self, node_id: str) -> dict | None:
        con = self._ro()
        try:
            r = con.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if not r:
                return None
            out = dict(r)
            out["edges"] = [dict(e) for e in con.execute(
                "SELECT * FROM edges WHERE source=? OR target=?", (node_id, node_id))]
            return out
        finally:
            con.close()

    def get_neighbors(self, node_id: str, *, relation: str | None = None) -> list[dict]:
        con = self._ro()
        try:
            q = "SELECT * FROM edges WHERE (source=? OR target=?)"
            args = [node_id, node_id]
            if relation:
                q += " AND relation=?"
                args.append(relation)
            return [dict(e) for e in con.execute(q, args)]
        finally:
            con.close()

    def query_graph(self, *, node_type: str | None = None, relation: str | None = None,
                    epistemic_state: str | None = None, limit: int = 50) -> dict:
        limit = max(0, min(int(limit), MAX_QUERY_LIMIT))  # a negative LIMIT is unbounded in SQLite
        con = self._ro()
        try:
            nq, na = "SELECT * FROM nodes", []
            conds = []
            if node_type:
                conds.append("node_type=?"); na.append(node_type)
            if epistemic_state:
                conds.append("epistemic_state=?"); na.append(epistemic_state)
            if conds:
                nq += " WHERE " + " AND ".join(conds)
            if epistemic_state == EpistemicState.UNVERIFIED.value:
                # Grounding queue: float bare materialized `/kg-diverge` pins (provenance=hypothesized,
                # typically degree 0) to the FRONT so they are not pushed past `limit` behind high-degree
                # extractor nodes — /kg-ground is told to ground pins first, but degree DESC alone buried
                # them (review-fix: L8). id tiebreak keeps the top-N deterministic.
                nq += " ORDER BY (provenance='hypothesized') DESC, degree DESC, id ASC LIMIT ?"
            else:
                nq += " ORDER BY degree DESC, id ASC LIMIT ?"  # id tiebreak: deterministic top-N
            na.append(limit)
            nodes = [dict(r) for r in con.execute(nq, na)]
            eq, ea = "SELECT * FROM edges", []
            if relation:
                eq += " WHERE relation=?"; ea.append(relation)
            eq += " ORDER BY id ASC LIMIT ?"; ea.append(limit)  # deterministic top-N (mirror the nodes query)
            edges = [dict(r) for r in con.execute(eq, ea)]
            return {"nodes": nodes, "edges": edges}
        finally:
            con.close()

    def shortest_path(self, source: str, target: str) -> list[str] | None:
        # path search over the derived edge list; still no centrality computation. Exclude the NON-LIVE
        # edges (§1.7): grounding REFUTED a `failed`/`rejected` relation and a later verdict SUPERSEDED an
        # `obsolete` one, so a path must not route through either and present a connectivity the graph
        # already disproved or retired — matches _live_subgraph, which excludes the identical edges from
        # every centrality surface (review-fix: L13). The set is model.NON_LIVE_STATE_VALUES, the single
        # vocabulary home: this site was left on the FAILURE-only set when `obsolete` joined it (L14/r11),
        # so a superseded edge still carried a live path while its own endpoints read degree 0 and
        # kg_context refused to answer over it — three surfaces disagreeing about one edge. Failure memory
        # is still fully DRAWN/counted elsewhere; it just can't carry a live path here.
        con = self._ro()
        try:
            adj: dict[str, list[str]] = {}
            dead_states = sorted(NON_LIVE_STATE_VALUES)  # sorted → deterministic SQL text
            placeholders = ",".join("?" * len(dead_states))
            for s, t in con.execute(
                    f"SELECT source,target FROM edges WHERE epistemic_state NOT IN ({placeholders})",
                    dead_states):
                adj.setdefault(s, []).append(t)
                adj.setdefault(t, []).append(s)
        finally:
            con.close()
        if source == target:
            return [source]
        # Predecessor-map BFS (O(V+E)) over the UNDIRECTED reachability of the MultiDiGraph (adjacency
        # added both ways above): carry only one predecessor per visited node instead of a full path list
        # per frontier entry (the old O(V·L) frontier), then reconstruct the path from `source` at the end.
        from collections import deque
        pred: dict[str, str] = {source: source}  # source is its own predecessor — the reconstruction stop
        q = deque([source])
        while q:
            cur = q.popleft()
            for nb in adj.get(cur, []):
                if nb in pred:
                    continue
                pred[nb] = cur
                if nb == target:
                    path = [target]
                    while path[-1] != source:
                        path.append(pred[path[-1]])
                    path.reverse()
                    return path
                q.append(nb)
        return None

    @staticmethod
    def _query_term_clause(query: str | None) -> "tuple[str, list]":
        """Build the term-wise OR LIKE clause + its args for a natural-language query (empty when no
        query). A question matches edges that contain ANY of its >=3-char terms in any field; a single
        LIKE on the whole string would only match a verbatim substring, so multi-word queries always
        missed. Built once and reused for both the grounded and hypothesis lanes."""
        if not query:
            return "", []
        seen: set = set()
        # Unicode-aware term extraction: an ASCII-only class ([A-Za-z0-9_-]) yields ZERO terms on a
        # Cyrillic/CJK/Greek query, collapsing to a single whole-string LIKE that only matches a verbatim
        # substring — the exact multi-word miss the per-term OR-clause exists to fix, and the same defect
        # review-r8-13 already fixed for the re-examinable advisory's _OVERLAP_WORD. `[^\W_]{3,}` keeps the
        # >=3-char floor while matching word runs in any script (digits included; splits on `-`/`_`, which
        # only broadens the OR-match). re.UNICODE is the str default, spelled out here for intent.
        terms = [t for t in re.findall(r"[^\W_]{3,}", query.lower(), re.UNICODE)
                 if not (t in seen or seen.add(t))][:_QUERY_TERM_CAP]
        clause = ("(source LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' "
                  "OR relation LIKE ? ESCAPE '\\' OR span LIKE ? ESCAPE '\\')")
        if terms:
            term_args: list = []
            parts = []
            for t in terms:
                parts.append(clause)
                term_args += [f"%{_like_escape(t)}%"] * 4
            return "(" + " OR ".join(parts) + ")", term_args
        return clause, [f"%{_like_escape(query)}%"] * 4

    @staticmethod
    def _read_stale_advisory(con) -> "tuple[list, int]":
        """The R3 source-staleness advisory list (capped) + its true total. Grounded/failed span-present
        edges whose span no longer appears in the source (read-only; the verdict stays untouched until
        /kg-ground re-runs). Capped at `_STALE_VERDICTS_CAP` so it can't bypass the token budget; the
        true total is surfaced separately so truncation stays visible (review-low: stale_verdicts uncapped)."""
        srow = con.execute("SELECT value FROM meta WHERE key='stale_verdicts'").fetchone()
        try:
            stale_verdicts = json.loads(srow[0]) if srow and srow[0] else []
        except (ValueError, TypeError):
            stale_verdicts = []
        return stale_verdicts[:_STALE_VERDICTS_CAP], len(stale_verdicts)

    @staticmethod
    def _read_reexaminable_advisory(con) -> "tuple[list, int]":
        """The R3-MIRROR re-examinable-verdicts advisory list (capped) + its true total. Failed/rejected
        items (nodes and edges, span-less included) judged against a source set that has since changed —
        READ-ONLY; the verdict stays untouched until /kg-ground re-runs. Capped at ``_REEXAMINABLE_CAP``
        (parallel to the stale-verdict cap) so it can't bypass the token budget; the true total is
        surfaced separately so truncation stays visible."""
        rrow = con.execute("SELECT value FROM meta WHERE key='reexaminable_verdicts'").fetchone()
        try:
            reexaminable = json.loads(rrow[0]) if rrow and rrow[0] else []
        except (ValueError, TypeError):
            reexaminable = []
        return reexaminable[:_REEXAMINABLE_CAP], len(reexaminable)

    @staticmethod
    def _bridge_metric_block(con) -> dict:
        """The completed bridge metric (PLAN Stage 2): read the gate verdict for this projection and rank
        the top nodes gate-aware (gate_ranking) — spec_betweenness (the confound-corrected metric) when the
        gate is ON, else the honest structural-bridge / betweenness / degree advisory. Both raw and weighted
        values are always carried so a reader can see the correction. Reads precomputed columns only."""
        grow = con.execute("SELECT value FROM meta WHERE key='gate_on'").fetchone()
        gate_on = int(grow[0]) if grow and grow[0] is not None and str(grow[0]).isdigit() else 0
        ranked_by, rank_cols = gate_ranking(gate_on)
        # `id ASC` is the deterministic final tiebreak: in a typical graph most nodes share
        # betweenness == spec_betweenness == 0.0 and a small integer degree, so the rank columns leave
        # the top-10 heavily tied — without a unique tiebreak WHICH 10 surface is not reproducible
        # across reprojections / SQLite versions / planner changes.
        bm_sql = ("SELECT id,label,degree,betweenness,spec_betweenness,specificity FROM nodes ORDER BY "
                  + ", ".join(f"{c} DESC" for c in rank_cols) + f", id ASC LIMIT {BRIDGE_LIMIT}")
        return {
            "gate_on": gate_on,
            "ranked_by": ranked_by,
            "note": ("specificity-weighting earned promotion this projection — spec_betweenness is "
                     "the trusted bridge signal" if gate_on else
                     "gated: spec_betweenness stays advisory; ranking by structural-bridge/degree (§1.6)"),
            "nodes": [dict(r) for r in con.execute(bm_sql)],
        }

    def kg_context(self, query: str | None = None, *, budget: int = 2000) -> dict:
        """Grounding-aware, provenance-carrying, token-budgeted context. Reads precomputed columns
        only — no centrality is computed here (it is O(1) on the index)."""
        budget = max(0, min(int(budget), MAX_CONTEXT_TOKENS))  # enforce an upper ceiling (server-4)
        con = self._ro()
        try:
            # falsification counters (memory of failures, §1.7) — surfaced, never pruned.
            # sorted() so the generated SQL text is deterministic (FAILURE_STATE_VALUES is a set).
            fail_states = sorted(FAILURE_STATE_VALUES)
            qmarks = ",".join("?" * len(fail_states))
            counters = {
                "failed_or_rejected_edges": con.execute(
                    f"SELECT COUNT(*) FROM edges WHERE epistemic_state IN ({qmarks})", fail_states).fetchone()[0],
            }
            # priority fill: grounded -> span-present -> inferred. The trailing `id ASC` is a deterministic
            # tiebreak so WHICH tied edges survive a budget truncation in _fill is a pure function of the
            # canon (SQLite gives no stable order among rows equal under the ORDER BY key; row order can
            # flip between a full rebuild and an incremental reproject of the identical canon).
            order = ("epistemic_state='grounded' DESC, "
                     "CASE provenance WHEN 'span-present' THEN 0 WHEN 'inferred' THEN 1 ELSE 2 END, "
                     "confidence_score DESC, id ASC")
            cols = ("id,source,target,relation,provenance,authored_by,epistemic_state,span,"
                    "confidence,confidence_score")
            term_clause, term_args = self._query_term_clause(query)

            def _fill(where_sql, args, order_sql, cap):
                rows, used = [], 0
                # LIMIT cap+1 is provably output-identical: every accepted row costs >= 1 token
                # against `cap` and the loop STOPS at the first over-budget row (no skip-and-
                # continue), so it can never look past row cap+1. The bound turns the CASE-expression
                # ORDER BY (which no index can serve) into a bounded top-N sort instead of a full
                # sort of every matching edge (review-r6).
                for r in con.execute(f"SELECT {cols} FROM edges WHERE {where_sql} "
                                     f"ORDER BY {order_sql} LIMIT ?", [*args, int(cap) + 1]):
                    rec = dict(r)
                    tok = max(1, len(json.dumps(rec)) // _CHARS_PER_TOKEN)
                    if used + tok > cap:
                        break
                    used += tok
                    rows.append(rec)
                return rows, used

            # GROUNDED LANE — items[] never includes a hypothesized proposal (PLAN Stage 8). A
            # hypothesized edge is a machine proposal, not grounded content, and must never be laundered
            # into a grounded answer.
            # ...and never a refuted/obsolete edge: failed/rejected are negative information (surfaced
            # only via falsification_counters, never as an answer) and obsolete is superseded content,
            # so the answer lane must exclude them. falsification_counters above still counts them.
            # the excluded set = the non-live vocabulary (failures + the superseded lifecycle state),
            # single-homed in model.NON_LIVE_STATE_VALUES; sorted for a deterministic SQL text.
            excluded = ",".join(repr(s) for s in sorted(NON_LIVE_STATE_VALUES))
            iwhere = f"provenance != 'hypothesized' AND epistemic_state NOT IN ({excluded})"
            iargs = list(term_args)
            if term_clause:
                iwhere += " AND " + term_clause
            items, used = _fill(iwhere, iargs, order, budget)
            # HYPOTHESIS LANE — a SEPARATE block of hypothesized, unverified proposals, clearly distinct.
            # Both lanes share ONE running budget (§1.11): the hypotheses cap is what the items lane left
            # unspent (budget - used), so the total serialized payload never exceeds `budget` and the
            # reported approx_tokens (used + hused) is honest. Filling items first preserves grounded
            # priority; the items/hypotheses segregation in the output is unchanged.
            hwhere = "provenance = 'hypothesized' AND epistemic_state = 'unverified'"
            hargs = list(term_args)
            if term_clause:
                hwhere += " AND " + term_clause
            hypotheses, hused = _fill(hwhere, hargs, "confidence_score DESC, id ASC", budget - used)
            bridges = [dict(r) for r in con.execute(
                "SELECT id,label,degree,bridge_communities FROM nodes WHERE structural_bridge=1 "
                f"ORDER BY degree DESC, id ASC LIMIT {BRIDGE_LIMIT}")]
            bridge_metric = self._bridge_metric_block(con)
            stale_verdicts, stale_total = self._read_stale_advisory(con)
            reexaminable, reexaminable_total = self._read_reexaminable_advisory(con)
            return {
                "items": items,
                "hypotheses": hypotheses,   # the SEPARATE hypothesized lane — proposals, NOT grounded content
                "approx_tokens": used + hused,  # both lanes counted against the shared budget (§1.11)
                "budget": budget,
                "falsification_counters": counters,
                "advisory": {"signal": "structural-bridge", "note": "advisory heuristic, not a guarantee",
                             "nodes": bridges, "bridge_metric": bridge_metric,
                             "stale_verdicts": stale_verdicts, "stale_verdicts_total": stale_total,
                             # R3-mirror: failed/rejected items whose source set changed since judged —
                             # a re-look candidate, never a verdict change (read-only).
                             "reexaminable_verdicts": reexaminable,
                             "reexaminable_verdicts_total": reexaminable_total},
            }
        finally:
            con.close()

    # ---- R6: read-only structural agenda (and the shared reader seam R1 reuses)
    def _agenda_reader(self) -> "tuple[list[dict], list[dict]]":
        """Read ALL node + edge rows from the derived index into plain dicts, then close. READ-ONLY by
        construction: the connection is opened `PRAGMA query_only=ON`, so a consumer physically cannot
        write through it. This is the shared seam both R6 (`kg_agenda`) and R1 (the exporter) consume —
        `projector.py` stays the SOLE writer of the derived layer (graph.json/index.sqlite)."""
        con = self._ro()
        try:
            con.execute("PRAGMA query_only=ON")
            nodes = [dict(r) for r in con.execute("SELECT * FROM nodes")]
            edges = [dict(r) for r in con.execute("SELECT * FROM edges")]
            return nodes, edges
        finally:
            con.close()

    def kg_agenda(self, *, limit: int = 5) -> dict:
        """Read-only structural "suggested questions" (R6). Reads ONLY precomputed derived columns and
        returns ~`limit` structural gaps split into `answerable_now[]` (well-grounded neighbourhoods)
        vs `blocked_on_grounding[]` (orphans, hypothesized-only neighbourhoods, under-grounded hubs,
        disconnected clusters) — mirroring kg_context's items[]/hypotheses[]. Ranked by the existing
        honest signal (gate-aware, mirroring kg_context's switch; never raw betweenness as lead). It
        asserts no edges, copies no spans, stamps no verdicts — measure-never-gate (it suggests, never
        acts); the question text is session-time only and never touches the canon."""
        return _agenda_from_rows(*self._agenda_reader(), limit=limit)


# --------------------------------------------------------------------------- R6 agenda builder (pure)
