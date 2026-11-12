"""Human-facing exporter (R1): a deterministic, READ-ONLY render of the derived layer into two fresh,
disposable artifacts under ``${KG_DATA}/derived/`` — a self-contained offline ``graph.html`` and a
``GRAPH_REPORT.md``.

It consumes ONLY the derived layer (the SQLite node/edge rows + their precomputed rank columns, via the
shared read-only ``Projector._agenda_reader()`` seam R6 introduced) and ``engine.kg_metrics()`` (so the
report's headline counts can never drift from the canon). It never reads prose, never writes through
``kg_write``/``kg_ground``, and never ``_atomic_write``s ``graph.json``/``index.sqlite`` — ``projector.py``
stays the sole writer of the derived index. Pure render/serialize; no new "quality" scalar.

Three ways in: ``python -m kg_engine.export html|report|all`` (CLI), ``kg_export`` (a thin read-only MCP
tool), and ``/kg-view``.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from .atomicio import atomic_write_text as _atomic_write
from .model import FAILURE_STATE_VALUES
from .projector import BRIDGE_LIMIT
from .templates.graph_html import HTML_TEMPLATE

_FAILURE = FAILURE_STATE_VALUES  # the single-homed negative-memory vocabulary (review-r5)

# Reader-facing limits. The bridge top-N IS the projector's kg_context bridge LIMIT (review-r5: the
# two used to be independent literals coordinated by a keep-in-sync comment).
_BRIDGE_TOP_N = BRIDGE_LIMIT
# The export kinds, named once for the engine entry point and the CLI (review-r5).
_KINDS = ("html", "report", "all")
_COMMUNITY_PREVIEW = 8        # community-member preview count (the slice AND the "…"-more threshold must match)
# The cap on every list the report prints: falsification memory, stale and re-examinable verdicts, and the
# names in the single-node-communities entry. A list that stops at the cap says how many it leaves out
# (_remainder) — through 0.11.2 the falsification header said 59 over a list that silently stopped at 50.
_LIST_CAP = 50
_SPAN_TRUNCATE = 80          # span truncation width
_UNATTRIBUTED = "(unattributed)"  # R4 fallback key for an edge with no declared source_file


def _ranked_by(gate_on) -> str:
    """The bridge-highlight ranking signal name for this projection's gate state — the single source of
    truth for the gate-aware legend label shared by the HTML and the report (mirrors kg_context's switch
    in projector.py; that cross-file twin is a deliberate engine/render seam, intentionally not shared)."""
    return "spec_betweenness" if gate_on else "structural_bridge"


# --------------------------------------------------------------------------- read model (read-only)


def _load_render_model(engine) -> dict:
    """Read the derived layer through the shared read-only seam. Returns plain dicts + the per-projection
    gate state and the R3 stale-verdict list — never touches the canon or the prose source."""
    nodes, edges = engine.projector._agenda_reader()
    gate_on = int(next((n.get("gate_on") for n in nodes if n.get("gate_on") is not None), 0) or 0)
    meta = engine.projector._read_meta()
    stale = meta.get("stale_verdicts", []) or []
    reexaminable = meta.get("reexaminable_verdicts", []) or []
    return {"nodes": nodes, "edges": edges, "gate_on": gate_on,
            "stale_verdicts": stale, "reexaminable_verdicts": reexaminable}


def _bridge_set(nodes: list, gate_on: int) -> set:
    """The gate-aware bridge-highlight set, mirroring kg_context's switch (projector.kg_context): when the
    gate is OFF use the honest binary ``structural_bridge`` advisory; when it is ON (the specificity
    weighting earned promotion) use the confound-corrected ``spec_betweenness`` (top by that signal). Node
    SIZE is degree-only elsewhere — the bridge metric never drives size, so the confound can't sneak in."""
    if gate_on:
        # Descend on the metric, then degree, but tie-break id ASCENDING — the SAME
        # (spec_betweenness DESC, degree DESC, id ASC) order kg_context's bridge_metric SQL uses
        # (projector._bridge_metric_block) — so among exact ties the HTML highlights the SAME nodes
        # kg_context reports. The `degree` key was missing, so two nodes tied on spec_betweenness but
        # differing in degree could straddle the top-N cutoff differently in the two views — the exact
        # drift this comment claimed could not happen (review-r11).
        ranked = sorted((n for n in nodes if (n.get("spec_betweenness") or 0) > 0),
                        key=lambda n: (-(n.get("spec_betweenness") or 0), -(n.get("degree") or 0),
                                       n.get("id")))
        return {n["id"] for n in ranked[:_BRIDGE_TOP_N]}
    return {n["id"] for n in nodes if n.get("structural_bridge")}


def _render_data(model: dict) -> dict:
    """The data inlined into the HTML as ``window.__KG_DATA__`` — the three axes kept on INDEPENDENT
    fields (provenance / authored_by per node; epistemic_state / provenance per edge), node ``degree`` for
    size, and a gate-aware per-node ``bridge`` flag. Deterministic: nodes/links sorted by id."""
    gate_on = int(model.get("gate_on") or 0)
    bridges = _bridge_set(model["nodes"], gate_on)
    nodes = [{
        "id": n["id"],
        "label": n.get("label") or n["id"],
        "degree": n.get("degree") or 0,            # SIZE channel — the honest advisory
        "provenance": n.get("provenance"),         # FILL-opacity channel
        "authored_by": n.get("authored_by"),       # BORDER channel
        "community": n.get("community"),
        "bridge": n["id"] in bridges,              # gate-aware highlight (never the size channel)
    } for n in sorted(model["nodes"], key=lambda n: n["id"])]
    # Mirror load_graph's dangling-target auto-create: an edge endpoint id that has no nodes-table row
    # (a target referenced in graph.json but never itself a canon note) would leave the HTML's byId
    # lookup empty and the JS would silently DROP that edge — yet the legend's edge count still includes
    # it, so the count and the drawing diverge. Synthesize a minimal placeholder node (degree 0, null
    # axes) for every such endpoint so those edges render and links.length matches the drawable count.
    known = {n["id"] for n in nodes}
    for e in model["edges"]:
        for endpoint in (e.get("source"), e.get("target")):
            if endpoint is not None and endpoint not in known:
                known.add(endpoint)
                nodes.append({
                    "id": endpoint,
                    "label": endpoint,
                    "degree": 0,
                    "provenance": None,
                    "authored_by": None,
                    "community": None,
                    "bridge": endpoint in bridges,
                })
    nodes.sort(key=lambda n: n["id"])
    links = [{
        "source": e.get("source"),
        "target": e.get("target"),
        "relation": e.get("relation"),
        "epistemic_state": e.get("epistemic_state"),  # LINE-style channel (failed/rejected DRAWN)
        "provenance": e.get("provenance"),
    } for e in sorted(model["edges"], key=lambda e: e.get("id") or "")]
    return {"nodes": nodes, "links": links, "gate_on": gate_on,
            "ranked_by": _ranked_by(gate_on)}


# --------------------------------------------------------------------------- artifacts


def build_html(engine) -> Path:
    """Render the self-contained offline ``graph.html`` (data inlined, no network, no ``<script src>``)
    and atomically write it under the derived dir. Returns its path. Read-only on the projector files."""
    data = _render_data(_load_render_model(engine))
    # Inline the data as JSON inside a <script> block. Escape EVERY markup-significant character, not just
    # "</" — a "</"-only escape is defeated by the script-data-double-escape state: a label like
    # "<!--<script>" enters that state and swallows the template's real </script>, breaking the render and
    # opening a script-injection vector from untrusted source content (review-H1). The \uXXXX forms are a
    # no-op for the parsed JS value (they round-trip to the same object) but leave no literal </>& for the
    # HTML tokenizer, defeating both </script> and <!--<script>.
    payload = (json.dumps(data, sort_keys=True)
               .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
    # The failure-state vocabulary is injected from its single model home (review-r5) — sorted so
    # the rendered HTML bytes stay deterministic for a given derived state.
    #
    # SINGLE-PASS substitution (review-r7): chaining `.replace(DATA).replace(FAILURE_STATES)` rescanned
    # the already-inserted payload, so a node label equal to the "__KG_FAILURE_STATES_JSON__" sentinel
    # got rewritten mid-JSON and broke the whole render. re.sub replaces each placeholder from the
    # ORIGINAL template and never re-examines replacement text, so neither substitution can corrupt the
    # other's output regardless of what the payload contains.
    _subs = {"__KG_DATA_JSON__": payload,
             "__KG_FAILURE_STATES_JSON__": json.dumps(sorted(FAILURE_STATE_VALUES))}
    html = re.sub("|".join(re.escape(k) for k in _subs), lambda m: _subs[m.group(0)], HTML_TEMPLATE)
    out = engine.projector.derived / "graph.html"
    _atomic_write(out, html)
    return out


def _axis_breakdown(items: list, key: str) -> dict:
    out: dict = {}
    for it in items:
        out[it.get(key)] = out.get(it.get(key), 0) + 1
    return out


def _summary_lines(metrics: dict) -> list:
    """The header + ``## Summary`` section: headline node/edge counts and the epistemic_state breakdown,
    sourced from ``kg_metrics`` so they cannot drift from the canon."""
    lines: list = []
    lines.append("# Knowledge graph report")
    lines.append("")
    lines.append("> Disposable artifact regenerated by `kg_export` / `/burgess:kg-view`. A **read-only** render of the "
                 "derived layer — nothing here is authoritative; the human-editable canon is. Failed/rejected "
                 "edges are kept (§1.7, never pruned).")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- **Nodes:** {metrics.get('nodes', 0)}")
    lines.append(f"- **Edges:** {metrics.get('edges', 0)}")
    by_state = metrics.get("edges_by_epistemic_state", {}) or {}
    if by_state:
        lines.append("- **Edges by epistemic_state:** "
                     + ", ".join(f"{k} {v}" for k, v in sorted(by_state.items())))
    return lines


def _legend_lines(ranked_by: str, gate_on: int) -> list:
    """The ``## The three axes`` legend, mirroring the HTML channels (epistemic_state/authored_by/
    provenance) plus the gate-aware bridge-highlight signal name."""
    lines: list = []
    lines.append("")
    lines.append("## The three axes (legend, mirrors the HTML)")
    lines.append("- **epistemic_state** → edge line: solid green = grounded · dashed = unverified · "
                 "**red = failed/rejected** · dotted = hypothesized.")
    lines.append("- **authored_by** → node border: deterministic · agent · human.")
    lines.append("- **provenance** → node fill opacity: span-present (opaque) · inferred (mid) · hypothesized (faint).")
    lines.append(f"- **Node size = degree** (the honest advisory). **Bridge highlight = {ranked_by}** "
                 f"(gate {'ON' if gate_on else 'off'}).")
    return lines


def _remainder(total: int, shown: int) -> str:
    """How many items a capped list leaves out, as ``… and N more`` — empty when it shows them all."""
    return f"… and {total - shown} more" if total > shown else ""


def _remainder_line(total: int, note: str = "") -> list:
    """The closing line of a list capped at ``_LIST_CAP``: none when the list is whole. The section header
    already gives the total; this line says outright that the list stops short of it."""
    if total <= _LIST_CAP:
        return []
    return [f"- {_remainder(total, _LIST_CAP)} not listed here (this report lists the first {_LIST_CAP}{note})."]


def _community_entry(title: str, members: list, intra_edges: list) -> list:
    """One ``###`` community entry: a member preview of ``_COMMUNITY_PREVIEW`` names, the two node axes,
    and the intra-community edges by epistemic_state."""
    names = ", ".join(f"`{_escape_md(m.get('label') or m['id'])}`"
                      for m in sorted(members, key=lambda m: m["id"])[:_COMMUNITY_PREVIEW])
    more = " …" if len(members) > _COMMUNITY_PREVIEW else ""
    return [f"### {title} — {len(members)} node(s)",
            f"- members: {names}{more}",
            f"- provenance: {_fmt_counts(_axis_breakdown(members, 'provenance'))}",
            f"- authored_by: {_fmt_counts(_axis_breakdown(members, 'authored_by'))}",
            "- intra-community edges by epistemic_state: "
            f"{_fmt_counts(_axis_breakdown(intra_edges, 'epistemic_state')) or '—'}"]


def _single_node_entry(members: list, intra_edges: list) -> list:
    """The one entry every single-node community shares: their count, up to ``_LIST_CAP`` names (saying
    how many more there are), the two node axes, their intra-community edges, and how many have degree 0.
    An edge inside a one-node community is a self-loop. Every write lane rejects one, but a hand-edited
    canon can still carry it, so the edge line stays: grouping must not hide what the old entries showed."""
    shown = sorted(members, key=lambda m: m["id"])[:_LIST_CAP]
    names = ", ".join(f"`{_escape_md(m.get('label') or m['id'])}`" for m in shown)
    more = _remainder(len(members), len(shown))
    return [f"### Single-node communities — {len(members)} node(s)",
            f"- members: {names}{' ' + more if more else ''}",
            f"- provenance: {_fmt_counts(_axis_breakdown(members, 'provenance'))}",
            f"- authored_by: {_fmt_counts(_axis_breakdown(members, 'authored_by'))}",
            "- intra-community edges by epistemic_state: "
            f"{_fmt_counts(_axis_breakdown(intra_edges, 'epistemic_state')) or '—'}",
            f"- degree 0: {sum(1 for m in members if not m.get('degree'))}"]


def _community_lines(nodes: list, edges: list) -> list:
    """The ``## Communities`` per-community breakdown by the three axes, with an intra-community edge map.

    Communities of one node share a single entry, after the others (0.11.3). A node with no live edge is
    a community of its own, so on a sparse graph they swamp the section: on the Windows corpus 172 of 264
    communities had one node, and their entries made up most of the report. Nodes with no community
    (``None``) keep their own entry, last, as before."""
    lines: list = []
    lines.append("")
    lines.append("## Communities")
    comms: dict = {}
    for n in nodes:
        comms.setdefault(n.get("community"), []).append(n)
    edges_by_comm: dict = {}
    node_comm = {n["id"]: n.get("community") for n in nodes}
    for e in edges:
        c = node_comm.get(e.get("source"))
        if c is not None and c == node_comm.get(e.get("target")):
            edges_by_comm.setdefault(c, []).append(e)
    if not comms:
        lines.append("_(no nodes)_")
        return lines
    assigned = sorted(c for c in comms if c is not None)
    for c in assigned:
        if len(comms[c]) > 1:
            lines += _community_entry(f"Community {c}", comms[c], edges_by_comm.get(c, []))
    single = [c for c in assigned if len(comms[c]) == 1]
    if single:
        lines += _single_node_entry([comms[c][0] for c in single],
                                    [e for c in single for e in edges_by_comm.get(c, [])])
    if None in comms:
        lines += _community_entry("Community None", comms[None], [])
    return lines


def _falsification_lines(edges: list) -> list:
    """The ``## Falsification memory`` section: failed/rejected edges, kept forever (§1.7, never pruned)."""
    fails = [e for e in edges if e.get("epistemic_state") in _FAILURE]
    lines: list = []
    lines.append("")
    lines.append(f"## Falsification memory (§1.7 — never pruned): {len(fails)}")
    if fails:
        for e in sorted(fails, key=lambda e: e.get("id") or "")[:_LIST_CAP]:
            lines.append(f"- `{_escape_md(e.get('source'))} --{_escape_md(e.get('relation'))}--> "
                         f"{_escape_md(e.get('target'))}` "
                         f"[{e.get('epistemic_state')}]" + (f" — `{_truncate(e.get('span'))}`" if e.get("span") else ""))
        lines += _remainder_line(len(fails), "; graph.html draws them all")
    else:
        lines.append("_(none — nothing refuted yet)_")
    return lines


def _stale_lines(stale: list) -> list:
    """The ``## Stale verdicts`` section (R3 — span no longer in source)."""
    lines: list = []
    lines.append("")
    lines.append(f"## Stale verdicts (R3 — span no longer in source): {len(stale)}")
    if stale:
        for s in stale[:_LIST_CAP]:
            lines.append(f"- `{_escape_md(s.get('edge_id'))}` — `{_escape_md(s.get('reason'))}`")
        lines += _remainder_line(len(stale))
    else:
        lines.append("_(none)_")
    return lines


def _reexaminable_lines(items: list) -> list:
    """The ``## Re-examinable verdicts`` section (R3-mirror — source set changed since judged). Lists
    failed/rejected items (nodes AND edges, span-less included) worth a grounder re-look; READ-ONLY —
    the verdict is never mutated here, re-grounding stays a `/kg-ground` decision."""
    lines: list = []
    lines.append("")
    lines.append("## Re-examinable verdicts (R3-mirror — source set changed since judged): "
                 f"{len(items)}")
    if items:
        for r in items[:_LIST_CAP]:
            lines.append(f"- `{_escape_md(r.get('item_id'))}` ({_escape_md(r.get('kind'))}) — "
                         f"`{_escape_md(r.get('state'))}` — `{_escape_md(r.get('reason'))}`")
        lines += _remainder_line(len(items))
    else:
        lines.append("_(none)_")
    return lines


def _source_file_lines(edges: list) -> list:
    """The ``## Source files`` section (R4 — edges per declared source_file)."""
    by_file = Counter(e.get("source_file") or _UNATTRIBUTED for e in edges)
    lines: list = []
    lines.append("")
    lines.append("## Source files (R4 — edges per declared source)")
    for f, n in sorted(by_file.items()):
        # escape at render time (the Counter is keyed on the raw source_file so distinct files stay
        # distinct); source_file is agent-controlled free text — the one untrusted field that had skipped
        # _escape_md, so a backtick/markup-bearing value could break the code span (review-low).
        lines.append(f"- `{_escape_md(f)}`: {n} edge(s)")
    lines.append("")
    return lines


def _report_md(metrics: dict, nodes: list, edges: list, stale: list, gate_on: int,
               reexaminable: "list | None" = None) -> str:
    """The GRAPH_REPORT.md body. Headline counts come from ``kg_metrics`` (so they cannot drift from the
    canon); the per-community axis breakdowns, falsification list, R3 stale verdicts, the R3-mirror
    re-examinable verdicts, and R4 per-file edge counts come from the derived rows/meta. Pure string
    build — a short concatenation of per-section helpers, each testable in isolation. ``reexaminable``
    defaults to an empty section so a caller that predates the R3-mirror keeps rendering."""
    lines: list = []
    lines += _summary_lines(metrics)
    lines += _legend_lines(_ranked_by(gate_on), gate_on)
    lines += _community_lines(nodes, edges)
    lines += _falsification_lines(edges)
    lines += _stale_lines(stale)
    lines += _reexaminable_lines(reexaminable or [])
    lines += _source_file_lines(edges)
    return "\n".join(lines)


def _fmt_counts(d: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sorted(d.items(), key=lambda kv: str(kv[0]))) if d else ""


def _escape_md(s) -> str:
    """Neutralize the characters that let an untrusted label/relation/span/reason escape its rendering
    context in GRAPH_REPORT.md: the backtick (which would break out of a code span), the HTML angle
    brackets ``<``/``>`` (raw-HTML injection when the .md is rendered as HTML), and newlines. Uses
    visually-close lookalikes so the text stays legible (review-low).

    NOTE: this does NOT neutralize markdown link/emphasis metacharacters (``[ ] ( ) * _``), which are
    extremely common in legitimate prose and must stay intact. Those are only *active* outside a code
    span, so EVERY caller renders untrusted values INSIDE a backtick code span (where markdown is
    inert); the escaped backtick above is what guarantees the value cannot break back out. Do not
    inline an ``_escape_md`` result as bare markdown text."""
    return (str(s if s is not None else "")
            .replace("`", "ʼ").replace("<", "‹").replace(">", "›").replace("\n", " ").strip())


def _truncate(s: str, n: int = _SPAN_TRUNCATE) -> str:
    s = _escape_md(s)
    return s if len(s) <= n else s[:n] + "…"


def build_report(engine) -> Path:
    """Render GRAPH_REPORT.md and atomically write it under the derived dir. Returns its path."""
    model = _load_render_model(engine)
    md = _report_md(engine.kg_metrics(), model["nodes"], model["edges"],
                    model["stale_verdicts"], model["gate_on"], model["reexaminable_verdicts"])
    out = engine.projector.derived / "GRAPH_REPORT.md"
    _atomic_write(out, md)
    return out


# --------------------------------------------------------------------------- dispatch + CLI


def export(engine, kind: str = "all") -> dict:
    """Build the requested artifact(s) (``html`` | ``report`` | ``all``). Read-only — consumes the derived
    layer, writes only its two disposable artifacts. Returns ``{ok, kind, html_path, report_path}``."""
    kind = (kind or "all").lower()
    if kind not in _KINDS:
        return {"ok": False, "kind": kind, "error": f"unknown kind {kind!r}; expected html|report|all",
                "html_path": None, "report_path": None}
    html_path = build_html(engine) if kind in ("html", "all") else None
    report_path = build_report(engine) if kind in ("report", "all") else None
    return {"ok": True, "kind": kind,
            "html_path": str(html_path) if html_path else None,
            "report_path": str(report_path) if report_path else None}


def _main(argv: list) -> int:
    kind = (argv[0] if argv else "all").lower()
    if kind not in _KINDS:
        print("usage: python -m kg_engine.export [html|report|all]", file=sys.stderr)
        return 2
    from .server import build_engine_from_env
    engine = build_engine_from_env()
    engine._ensure_projected()  # project-if-stale, then render the derived layer (never writes the canon)
    out = export(engine, kind)
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
