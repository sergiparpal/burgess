"""0.11.3 — GRAPH_REPORT.md says what it leaves out.

Found on 2026-11-10 while reviewing a ``/kg-view`` run on the Windows corpus (425 nodes, 221 edges: 162
grounded, 58 rejected, 1 failed). ``graph.html`` matched the canon, but the report had two gaps:

1. Its lists stop at ``_LIST_CAP`` (50). The falsification header said 59 over a list that stopped at 50
   without a word. Now a list that stops at the cap ends with a line saying how many more there are.
2. Every community had its own entry, and a node with no live edge is a community of one. On the corpus
   172 of the 264 communities had a single node, and their entries made up most of the report. Now they
   share one entry.
"""
from __future__ import annotations

import re

from kg_engine.export import _LIST_CAP, _report_md
from kg_engine.model import edge_id

CAP = _LIST_CAP


def _n(nid, community, *, degree=0, provenance="span-present", authored_by="agent", label=None):
    return {"id": nid, "label": label or nid, "degree": degree, "provenance": provenance,
            "authored_by": authored_by, "community": community, "structural_bridge": 0,
            "spec_betweenness": 0.0, "gate_on": 0}


def _e(eid, src, tgt, *, epistemic_state="rejected", relation="grounds", span="a span"):
    return {"id": eid, "source": src, "target": tgt, "relation": relation,
            "epistemic_state": epistemic_state, "provenance": "span-present", "source_file": "s.md",
            "span": span}


def _md(nodes=(), edges=(), stale=(), reexaminable=()):
    metrics = {"nodes": len(nodes), "edges": len(edges), "edges_by_epistemic_state": {}}
    return _report_md(metrics, list(nodes), list(edges), list(stale), 0, list(reexaminable))


def _section(md: str, heading: str) -> list:
    """The non-blank lines of the ``## `` section whose heading starts with ``heading``."""
    lines = md.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## " + heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [line for line in lines[start:end] if line.strip()]


def _entries(md: str) -> dict:
    """Each ``### `` entry of ``## Communities`` (its title line) -> the lines under it, in report order."""
    out, cur = {}, None
    for line in _section(md, "Communities")[1:]:
        if line.startswith("### "):
            cur = line
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def _items(section: list) -> list:
    return [line for line in section if line.startswith("- `")]


def _refuted(k: int) -> list:
    """``k`` failed/rejected edges between distinct pairs, ids sorting as e000, e001, …"""
    return [_e(f"e{i:03d}", f"s{i:03d}", f"t{i:03d}", epistemic_state="failed" if i == 0 else "rejected")
            for i in range(k)]


# --------------------------------------------------------------------------- 1. capped lists


def test_falsification_list_past_the_cap_says_how_many_more():
    sec = _section(_md(edges=_refuted(CAP + 9)), "Falsification memory")
    assert sec[0] == f"## Falsification memory (§1.7 — never pruned): {CAP + 9}"
    assert len(_items(sec)) == CAP
    assert sec[-1] == (f"- … and 9 more not listed here (this report lists the first {CAP}; "
                       "graph.html draws them all).")


def test_a_list_at_the_cap_has_no_remainder_line():
    sec = _section(_md(edges=_refuted(CAP)), "Falsification memory")
    assert len(_items(sec)) == CAP
    assert not any("more not listed" in line for line in sec)
    assert _section(_md(), "Falsification memory")[1] == "_(none — nothing refuted yet)_"


def test_stale_and_reexaminable_lists_past_the_cap_say_how_many_more():
    stale = [{"edge_id": f"e{i:03d}", "reason": "span-no-longer-in-source"} for i in range(CAP + 3)]
    reex = [{"item_id": f"n{i:03d}", "kind": "node", "state": "rejected", "reason": "source-changed"}
            for i in range(CAP + 1)]
    md = _md(stale=stale, reexaminable=reex)
    s = _section(md, "Stale verdicts")
    r = _section(md, "Re-examinable verdicts")
    assert len(_items(s)) == CAP and len(_items(r)) == CAP
    assert s[-1] == f"- … and 3 more not listed here (this report lists the first {CAP})."
    assert r[-1] == f"- … and 1 more not listed here (this report lists the first {CAP})."


# --------------------------------------------------------------------------- 2. single-node communities


def test_single_node_communities_share_one_entry():
    nodes = [_n("a", 0, degree=1), _n("b", 0, degree=2), _n("c", 0, degree=1),
             _n("x1", 1), _n("x2", 2), _n("x3", 3, authored_by="human"), _n("x4", 4, degree=1),
             _n("x5", 5, provenance="inferred")]
    edges = [_e("e1", "a", "b", epistemic_state="grounded"), _e("e2", "b", "c", epistemic_state="grounded")]
    ent = _entries(_md(nodes, edges))
    assert list(ent) == ["### Community 0 — 3 node(s)", "### Single-node communities — 5 node(s)"]
    assert ent["### Single-node communities — 5 node(s)"] == [
        "- members: `x1`, `x2`, `x3`, `x4`, `x5`",
        "- provenance: inferred: 1, span-present: 4",
        "- authored_by: agent: 4, human: 1",
        "- intra-community edges by epistemic_state: —",
        "- degree 0: 4",
    ]


def test_single_node_entry_lists_up_to_the_cap_and_says_how_many_more():
    nodes = [_n(f"x{i:03d}", i) for i in range(CAP + 10)]
    ((title, lines),) = _entries(_md(nodes)).items()
    assert title == f"### Single-node communities — {CAP + 10} node(s)"
    assert re.findall(r"`(x\d{3})`", lines[0]) == [f"x{i:03d}" for i in range(CAP)]
    assert lines[0].endswith("… and 10 more")


def test_no_single_node_entry_without_single_node_communities():
    nodes = [_n("a", 0), _n("b", 0), _n("c", 1), _n("d", 1)]
    assert list(_entries(_md(nodes))) == ["### Community 0 — 2 node(s)", "### Community 1 — 2 node(s)"]


def test_nodes_without_a_community_keep_their_own_entry_last():
    nodes = [_n("a", 0), _n("b", 0), _n("x", 7), _n("u", None)]
    ent = _entries(_md(nodes))
    assert list(ent) == ["### Community 0 — 2 node(s)", "### Single-node communities — 1 node(s)",
                         "### Community None — 1 node(s)"]
    assert ent["### Single-node communities — 1 node(s)"][0] == "- members: `x`"


def test_every_node_is_counted_exactly_once():
    nodes = ([_n(f"a{i}", 0) for i in range(4)] + [_n(f"b{i}", 1) for i in range(2)]
             + [_n(f"x{i}", 10 + i) for i in range(6)] + [_n("u1", None), _n("u2", None)])
    titles = list(_entries(_md(nodes)))
    assert sum(int(re.search(r"— (\d+) node\(s\)$", t).group(1)) for t in titles) == len(nodes)


def test_a_self_loop_in_a_single_node_community_stays_visible():
    # Every write lane rejects a self-loop, but a hand-edited canon can still carry one. Through 0.11.2 the
    # community's own entry showed it, so the shared entry must too.
    ent = _entries(_md([_n("x", 3), _n("y", 4)], [_e("e1", "x", "x", epistemic_state="grounded")]))
    assert ent["### Single-node communities — 2 node(s)"][3] == (
        "- intra-community edges by epistemic_state: grounded: 1")


def test_engine_report_groups_nodes_left_alone_by_a_failed_edge(engine):
    # A failed edge is not live, so its two endpoints have no live edge and the real projector puts each in
    # a community of its own, while the grounded pair shares one. All four endpoints are canon notes, as on
    # the corpus: an edge target with no note of its own has no row in the report at all.
    out = engine.kg_write({
        "nodes": [{"id": "compression", "label": "Compression", "node_type": "compression"},
                  {"id": "claim", "label": "Claim", "node_type": "claim"},
                  {"id": "betweenness", "label": "Betweenness", "node_type": "metric"},
                  {"id": "generality-confound", "label": "Generality confound", "node_type": "claim"}],
        "edges": [{"source": "compression", "target": "claim", "relation": "grounds",
                   "span": "A compression stands in for many observations and grounds the claims beneath it",
                   "provenance": "span-present", "authored_by": "agent"},
                  {"source": "betweenness", "target": "generality-confound", "relation": "attacked_by",
                   "span": "Betweenness is confounded by the generality confound",
                   "provenance": "span-present", "authored_by": "agent"}],
        "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 6, out
    assert engine.kg_ground(edge_id("compression", "grounds", "claim"), "grounded")["ok"]
    assert engine.kg_ground(edge_id("betweenness", "attacked_by", "generality-confound"), "failed")["ok"]
    engine.projector.project()
    assert engine.kg_export("report")["ok"]
    ent = _entries((engine.projector.derived / "GRAPH_REPORT.md").read_text(encoding="utf-8"))
    titles = list(ent)
    assert len(titles) == 2 and re.fullmatch(r"### Community \d+ — 2 node\(s\)", titles[0]), titles
    assert titles[1] == "### Single-node communities — 2 node(s)"
    assert ent[titles[1]][0] == "- members: `Betweenness`, `Generality confound`"
    assert ent[titles[1]][-1] == "- degree 0: 2"
