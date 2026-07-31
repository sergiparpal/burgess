"""Regression pins for review-r12.

Three findings, each of which the suite passed straight through before the fix:

1. `obsolete` was live topology on two surfaces. `model.NON_LIVE_STATE_VALUES` (failures PLUS
   the superseded `obsolete` state) is the single live-topology vocabulary, and review-fix L14 /
   review-r11 moved `_live_subgraph`, `generate._live_undirected` and `kg_context`'s answer lane
   onto it — but `DerivedReader.shortest_path` and the `kg_agenda` builder were left on the older
   FAILURE-only set. So one `obsolete` edge could carry a live path, and be counted as a live
   relation by the agenda detectors, while the node ranks those same surfaces read were computed
   with it excluded.

2. `_sync_materialized_fates` caught only `FileNotFoundError` around `canon.read_node`, so a
   canon note that was MALFORMED rather than missing failed the whole diverge fate-sync instead
   of skipping one ledger entry (§1.2: one bad note must not crash every read).

3. `canonmerge.merge_nodes` suppressed the NODE-level demotion note whenever OURS was already
   `unverified` — exactly the case where THEIRS held the verdict being dropped — while the
   mirrored edge branch always reported it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.canon import Canon
from kg_engine.canonmerge import merge_nodes
from kg_engine.model import (
    Edge,
    EpistemicState,
    FAILURE_STATE_VALUES,
    NON_LIVE_STATE_VALUES,
    Node,
    Provenance,
)
from kg_engine.projector import Projector

# The three states that must all read as "not live topology". Parametrizing on the set itself
# means a future state added to NON_LIVE_STATE_VALUES is covered here automatically.
NON_LIVE = sorted(NON_LIVE_STATE_VALUES)


def _project(vault: Path, nodes: list[Node]) -> Projector:
    canon = Canon(vault, git_enabled=False)
    canon.write_nodes(nodes, message="r12", commit=False)
    proj = Projector(canon)
    proj.project(incremental=False)
    return proj


# --------------------------------------------------------------------------- finding 1


def test_obsolete_is_in_the_non_live_vocabulary():
    """The premise the other tests rest on: `obsolete` is non-live but NOT a failure state."""
    assert EpistemicState.OBSOLETE.value in NON_LIVE_STATE_VALUES
    assert EpistemicState.OBSOLETE.value not in FAILURE_STATE_VALUES


@pytest.mark.parametrize("state", NON_LIVE)
def test_shortest_path_never_routes_through_a_non_live_edge(tmp_path, state):
    """A path must not present connectivity that `degree` and `kg_context` both call dead.

    Pre-fix, `obsolete` returned ['a','b'] here while a→b's own degree was 0 — three surfaces
    disagreeing about one edge.
    """
    proj = _project(tmp_path, [
        Node(id="a", label="A", edges=[Edge(source="a", target="b", relation="grounds",
                                            provenance=Provenance.SPAN_PRESENT, span="zzzz",
                                            epistemic_state=EpistemicState(state))]),
        Node(id="b", label="B"),
    ])
    reader = proj.reader
    assert reader.shortest_path("a", "b") is None
    # ...and it agrees with the two surfaces that were already correct.
    assert reader.get_node("a")["degree"] == 0
    assert reader.kg_context()["items"] == []


@pytest.mark.parametrize("state", NON_LIVE)
def test_agenda_detectors_treat_every_non_live_state_alike(tmp_path, state):
    """`h` has one hypothesized edge + one non-live edge, so its ONLY live relation is the
    hypothesis and `hypothesized-only` must fire — whichever non-live state the second edge is in.

    Pre-fix, `rejected`/`failed` fired but `obsolete` made `all(hypothesized)` false and `h`
    dropped out of the agenda entirely.
    """
    proj = _project(tmp_path, [
        Node(id="h", label="H", edges=[
            Edge(source="h", target="x", relation="grounds",
                 provenance=Provenance.HYPOTHESIZED, epistemic_state=EpistemicState.UNVERIFIED),
            Edge(source="h", target="y", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState(state)),
        ]),
        Node(id="x", label="X"), Node(id="y", label="Y"),
    ])
    agenda = proj.reader.kg_agenda(limit=10)
    detectors = {i["detector"] for lane in ("answerable_now", "blocked_on_grounding")
                 for i in agenda[lane] if i["focus"] == ["h"]}
    assert detectors == {"hypothesized-only"}


@pytest.mark.parametrize("state", NON_LIVE)
def test_agenda_flags_a_cluster_joined_only_by_a_non_live_edge(tmp_path, state):
    """A community reachable ONLY through a non-live edge is still a coverage gap: the
    edgeless-communities crossing test must not count that edge as connecting the two."""
    nodes = [
        # a grounded triangle, then a lone pair joined to it by ONE non-live edge
        Node(id="a", label="A", edges=[
            Edge(source="a", target="b", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState.GROUNDED),
            Edge(source="a", target="c", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState.GROUNDED),
        ]),
        Node(id="b", label="B", edges=[
            Edge(source="b", target="c", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState.GROUNDED),
            # the ONLY link to the far pair — non-live, so it must not count as crossing
            Edge(source="b", target="p", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState(state)),
        ]),
        Node(id="c", label="C"),
        Node(id="p", label="P", edges=[
            Edge(source="p", target="q", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState.GROUNDED),
        ]),
        Node(id="q", label="Q"),
    ]
    proj = _project(tmp_path, nodes)
    reader = proj.reader
    # the non-live edge carries no path between the two clusters
    assert reader.shortest_path("a", "q") is None
    # and it is not counted as a live inter-community crossing
    agenda = reader.kg_agenda(limit=10)
    focuses = [i["focus"] for i in agenda["blocked_on_grounding"]
               if i["detector"] == "edgeless-communities"]
    assert any({"p", "q"} <= set(f) for f in focuses), (
        f"the p/q cluster is joined only by a {state} edge and must surface as disconnected; "
        f"got {focuses}")


def test_a_live_edge_still_carries_a_path_and_joins_communities(tmp_path):
    """The control: none of the above narrowed what a genuinely live edge does."""
    proj = _project(tmp_path, [
        Node(id="a", label="A", edges=[Edge(source="a", target="b", relation="grounds",
                                            provenance=Provenance.SPAN_PRESENT, span="zzzz",
                                            epistemic_state=EpistemicState.GROUNDED)]),
        Node(id="b", label="B"),
    ])
    assert proj.reader.shortest_path("a", "b") == ["a", "b"]
    assert proj.reader.get_node("a")["degree"] == 1


def test_falsification_counter_still_counts_failures_only(tmp_path):
    """kg_context's falsification counter must stay on the FAILURE set — it counts refutations,
    and `obsolete` is a lifecycle transition, not negative information (§1.7)."""
    proj = _project(tmp_path, [
        Node(id="a", label="A", edges=[
            Edge(source="a", target="b", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState.OBSOLETE),
            Edge(source="a", target="c", relation="grounds", provenance=Provenance.SPAN_PRESENT,
                 span="zzzz", epistemic_state=EpistemicState.REJECTED),
        ]),
        Node(id="b", label="B"), Node(id="c", label="C"),
    ])
    counters = proj.reader.kg_context()["falsification_counters"]
    assert counters["failed_or_rejected_edges"] == 1, "obsolete must not be counted as a refutation"


# --------------------------------------------------------------------------- finding 2


def test_fate_sync_skips_a_malformed_note_instead_of_failing(engine, monkeypatch):
    """A ledger entry pointing at a note that is MALFORMED (not missing) must be skipped.

    Pre-fix the narrow `except FileNotFoundError` let the ValueError from `node_from_markdown`
    escape through `_tool_result` and turn the whole kg_diverge_recall / kg_diverge_metrics call
    into {ok: False}.
    """
    (engine.canon.notes_dir / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
    # the canon's own tolerant readers already skip it — the fate sync must match that posture
    assert engine.canon.parse_note(engine.canon.notes_dir / "broken.md") is None
    with pytest.raises(ValueError):
        engine.canon.read_node("broken")

    ledger = {"c-1": {"nodes": ["broken"], "edges": [{"owner": "broken", "id": "e_x__y__z"}]}}

    class _FakeState:
        def read_materialized(self):
            return dict(ledger)

        def write_materialized(self, data):
            ledger.clear()
            ledger.update(data)

        def add_discard(self, domain, cid):  # pragma: no cover - must never be reached here
            raise AssertionError("an unreadable note is no evidence of a failed fate")

    class _FakeSession:
        def __init__(self, project, home=None):
            self.state = _FakeState()
            self.domain = "d"

    monkeypatch.setattr("kg_engine.divergence.session.Session", _FakeSession)
    assert engine._sync_materialized_fates("proj") == []


def test_fate_sync_still_folds_a_genuinely_failed_node(engine, monkeypatch):
    """The control for the widened except: a readable, actually-`failed` node still discards."""
    engine.canon.write_one(Node(id="dead", label="Dead",
                                epistemic_state=EpistemicState.FAILED))
    discarded: list = []
    ledger = {"c-1": {"nodes": ["dead"], "edges": []}}

    class _FakeState:
        def read_materialized(self):
            return ledger

        def write_materialized(self, data):
            ledger.update(data)

        def add_discard(self, domain, cid):
            discarded.append(cid)

    class _FakeSession:
        def __init__(self, project, home=None):
            self.state = _FakeState()
            self.domain = "d"

    monkeypatch.setattr("kg_engine.divergence.session.Session", _FakeSession)
    out = engine._sync_materialized_fates("proj")
    assert out == [{"candidate": "c-1", "fate": "failed"}]
    assert discarded == ["c-1"]


# --------------------------------------------------------------------------- finding 3


# --------------------------------------------------------------------------- dependency cap


def test_the_mcp_server_import_path_the_engine_uses_still_exists():
    """Hard pin on `mcp.server.fastmcp` — the ONE import the whole tool surface hangs off.

    `pyproject` caps mcp at <2 because 2.0.0 REMOVED `mcp.server.fastmcp` and the `FastMCP` class
    entirely (the server API moved to `mcp.server.mcpserver`). Under a bump past the cap,
    `server.main()` raises ModuleNotFoundError at startup and every kg_* tool vanishes for the
    session. The existing coverage in test_fix_server.py guards this behind `pytest.importorskip`,
    so it would SKIP rather than fail on exactly the bump that breaks production — the same
    "coverage vanishes with the suite still green" hazard the CI config calls out for the Node
    launcher tests. This asserts it instead, so a bad Dependabot bump fails CI.
    """
    import importlib

    mod = importlib.import_module("mcp.server.fastmcp")
    assert hasattr(mod, "FastMCP"), (
        "mcp.server.fastmcp no longer exposes FastMCP — the mcp<2 cap in pyproject has been lifted "
        "without porting server.py's tool surface + readiness_lifespan to the 2.x server API")


# --------------------------------------------------------------------------- finding 3


def _node(state: EpistemicState, *, with_edge: bool) -> Node:
    edges = [Edge(source="n", target="t", relation="grounds", epistemic_state=state,
                  provenance=Provenance.SPAN_PRESENT, span="zzzz")] if with_edge else []
    return Node(id="n", label="N", epistemic_state=state, edges=edges)


def test_node_demotion_is_reported_even_when_ours_was_unverified():
    """`merged` starts as a deepcopy of OURS, so the old `!= UNVERIFIED` guard tested the wrong
    side: when ours was already unverified, THEIRS' verdict was dropped with no note at all."""
    merged, demotions = merge_nodes(
        None, _node(EpistemicState.UNVERIFIED, with_edge=False),
        _node(EpistemicState.GROUNDED, with_edge=False))
    assert merged.epistemic_state is EpistemicState.UNVERIFIED  # still never forges a verdict
    assert demotions == ["node:n: unverified/grounded -> unverified"]


def test_node_and_edge_branches_report_the_same_conflict():
    """The two branches are documented as mirrors; a two-sided conflict must be reported by both."""
    _merged, demotions = merge_nodes(
        None, _node(EpistemicState.UNVERIFIED, with_edge=True),
        _node(EpistemicState.GROUNDED, with_edge=True))
    assert demotions == [
        "e_n__grounds__t: unverified/grounded -> unverified",
        "node:n: unverified/grounded -> unverified",
    ]


def test_no_demotion_note_when_the_node_states_agree():
    """The guard's legitimate job — no conflict, no note — is unaffected."""
    merged, demotions = merge_nodes(
        _node(EpistemicState.GROUNDED, with_edge=False),
        _node(EpistemicState.GROUNDED, with_edge=False),
        _node(EpistemicState.GROUNDED, with_edge=False))
    assert merged.epistemic_state is EpistemicState.GROUNDED
    assert demotions == []


def test_one_sided_node_verdict_still_survives_the_merge():
    """Base-aware 3-way: only OURS moved off base, so ours' verdict is kept, not demoted."""
    merged, demotions = merge_nodes(
        _node(EpistemicState.UNVERIFIED, with_edge=False),   # base
        _node(EpistemicState.GROUNDED, with_edge=False),     # ours changed it
        _node(EpistemicState.UNVERIFIED, with_edge=False))   # theirs left it
    assert merged.epistemic_state is EpistemicState.GROUNDED
    assert demotions == []
