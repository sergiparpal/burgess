---
description: Render the human-facing knowledge-graph artifacts — a self-contained offline graph.html + GRAPH_REPORT.md.
argument-hint: "[html|report|all]"
allowed-tools: mcp__plugin_burgess_burgess__kg_export
---

# /burgess:kg-view — render the human-facing artifacts (R1)

The canon and the derived index are machine surfaces. This command renders two **disposable, human-facing**
artifacts so a person can *eyeball* the graph and its grounding state — without ever changing it.

`/burgess:kg-view` is **read-only**: it projects-if-stale, then consumes only the derived layer and writes only its
two artifacts under `${CLAUDE_PLUGIN_DATA}/derived/`. It never writes the canon, never sets a verdict, never
copies a span — it cannot forge anything (§1.4/§1.5/§1.8). Both files are **regenerable**; treat them as a
view, not a source of truth (the canon is the source of truth).

## Procedure

1. Read the kind from the arguments, `$ARGUMENTS`, trimmed and without quotes: `html`, `report` or `all`,
   and **`all`** when the line is empty. Call `mcp__plugin_burgess_burgess__kg_export(kind=<that kind>)`. It
   returns `{ok, kind, html_path, report_path}`.
2. Report the two artifact paths to the user:
   - **`graph.html`** — a self-contained, fully-offline force-directed viz (open it in any browser; no network,
     no dependencies). The **three orthogonal axes** are on **independent visual channels** — never one
     "confidence" colour:
     - `epistemic_state` → **edge line**: solid green = grounded · dashed = unverified · **red = failed/rejected**
       (drawn, never pruned — §1.7; but they exert **no force in the layout** and a legend checkbox can hide
       them, so a refuted relation never springs its endpoints together and fakes a connectivity grounding
       already rejected — matching `projector._live_subgraph`, which excludes them from every rank) · dotted = hypothesized;
     - `authored_by` → **node border**: deterministic · agent · human;
     - `provenance` → **node fill opacity**: span-present (opaque) · inferred (mid) · hypothesized (faint).
     - **Node size = degree** (the honest advisory). The **bridge highlight** (gold ring) is gate-aware —
       `spec_betweenness` only when the specificity gate earned promotion, else the structural-bridge advisory
       (§1.6); size is never the bridge metric, so the generality confound is never smuggled into it.
   - **`GRAPH_REPORT.md`** — headline counts (straight from `kg_metrics`, so they can't drift), per-community
     breakdowns by the three axes (single-node communities share one entry), the never-pruned **falsification
     memory**, the R3 **stale verdicts** (spans the source no longer contains), and per-source-file edge counts
     (R4). A list longer than 50 shows the first 50 and says how many more there are.
3. Do **not** present either artifact as authoritative. They are a regenerable *view* of the canon; if the user
   wants to change the graph, that flows through `/burgess:kg-build` → `/burgess:kg-ground` (verdicts) — never through this view.
