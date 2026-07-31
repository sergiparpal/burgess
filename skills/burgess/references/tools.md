# Reference: tools & CLIs

Load on demand. The MCP **tool surface** — the twenty graph tools (§1), then the seven divergence-surface
tools (§1B) — then the deterministic **CLI surface**
(`f4_probe.py`, `kg_engine.pack`, `kg_engine.harness`, `kg_engine.divergence`). Every name, signature, and
return shape below
mirrors `scripts/kg_engine/server.py` + `scripts/kg_engine/projector.py` (+ `scripts/kg_engine/divergence/`
for §1B). Nothing here is invented — if a
field is missing, grep the engine source, don't guess. Every tool is also wrapped by a uniform
transport-error envelope: a RAISED internal exception (not a deliberate domain `{ok:false}` disposition)
returns `{"ok": false, "error": "<message>", "error_kind": "<ExceptionType>"}` and is logged, so a tool
call never crashes the session; success returns and domain `{ok:false}` results pass through unchanged.

---

## 1 · MCP tool surface

A plugin-bundled MCP server's tools are namespaced `mcp__plugin_<plugin>_<server>__<tool>` — here both the
plugin and the server are named `burgess`, so every tool is `mcp__plugin_burgess_burgess__<tool>`
(use this exact form in agent `tools:` / command `allowed-tools:` grants). These **twenty** are the **only**
graph tools — the verify/read tools (§1.1–§1.11, including `kg_merge` §1.5b and the read-only egress
`kg_explain_path` §1.10b) plus the four generative-layer tools (§1.12–§1.15)
plus the read-only `kg_agenda` (§1.16), `kg_export` (§1.17), and the projection-free `kg_status` (§1.18).
The seven **divergence-surface** tools (§1B) complete the server's **twenty-seven**.
There is no `kg_build` / `kg_query` /
`kg_project` MCP tool — those are slash commands (`/kg-build`, …) that *orchestrate* these tools.

Mutation tools (`kg_write`, `kg_propose`, `kg_ground`, `kg_rename`, `kg_merge`) write the **canon** (human-editable Markdown,
the single source of truth) — `kg_propose` (§1.12) is the hypothesized write lane and `kg_operate` (§1.14) writes
through it. Read tools (`get_node`, `get_neighbors`, `shortest_path`, `kg_explain_path`, `query_graph`, `kg_context`) and the
generative reads (`kg_generate` §1.13, `kg_absorption` §1.15) read the **derived** layer; they call
`_ensure_projected()` first, which reprojects only if `index.sqlite`/`graph.json` is missing or
`projector.is_stale()` — a content-driven check (a cheap per-note `(name, size, mtime)` signature pre-gate,
then an authoritative per-node content-hash comparison), regardless of git HEAD, so an uncommitted edit
still reprojects. The derived layer contains nothing the canon does not (§1.2) and never prunes failure
memory (§1.7). A reprojection that raises does not crash the read: it is logged, `projection_degraded` is set,
an empty-schema derived layer is materialised, and the tool serves canon-derived/empty data with that flag
merged into its result (a list-returning read like `get_neighbors` can't carry the flag, so it returns `[]`).
Writes never pass through this seam.

### 1.1 `mcp__plugin_burgess_burgess__kg_ping()`

Health check / config probe. No args.

```json
{"name": "burgess", "version": "<__version__>", "metrics_mode": "structure_only",
 "sensitivity": "medium", "pack_loaded": true}
```

`pack_loaded` is `true` only when `pack/pack.yaml` validated as a `PackContract` at startup. `metrics_mode`
is `structure_only` by default (centrality stays advisory; the specificity-weighted bridge metric is gated,
§1.4/§1.6).

### 1.2 `mcp__plugin_burgess_burgess__kg_scrub(text=None)`

The §1.9 **egress scrub**. Redacts **secrets (always)** + **PII (per `sensitivity`)** with **CONSISTENT
placeholders** (`⟦SECRET:1⟧`, `⟦EMAIL:1⟧`, …) before any text is handed to a subagent for semantic work.
Pass `text` to scrub a snippet, or omit to scrub the configured source. It accumulates the session
placeholder→original mapping so that `kg_write` then **RESTORES** placeholder spans to the **ORIGINAL** text
for the canon — the boundary stores the restored original span, so the scrub protects the egress, not the
local canon.

```json
{"scrubbed": "<text with placeholders>", "redactions": 0, "sensitivity": "medium", "categories": []}
```

- `scrubbed` — the text the subagent should see (original where nothing matched).
- `redactions` — count of distinct placeholders introduced.
- `sensitivity` — the engine's configured sensitivity (`kg_ping().sensitivity`); gates which PII categories
  are redacted (secrets are always redacted).
- `categories` — sorted distinct redaction categories present (e.g. `["EMAIL", "SECRET"]`), `[]` when none.

For the no-PII demo source (`examples/source.md`), `kg_scrub` is a **no-op**: `redactions: 0`,
`categories: []`, and `scrubbed` equals the source verbatim.

### 1.3 `mcp__plugin_burgess_burgess__kg_write(payload: dict, idempotency_key: str | None = None, construction: str | None = None, source: str | None = None)`

The boundary (§1.5). Validates an extraction payload, writes ACCEPTED/DEMOTED nodes & edges to the canon,
quarantines or rejects the rest. `payload` is the write contract (see `references/contract.md` / the shared
contract): `{nodes:[…], edges:[…], complete:true}`. **`complete` MUST be `true`** or the whole payload is
REJECTED as `truncated-payload`.

`construction` (optional) routes this SAME key-free, span-verified write to a separately-named **second
construction**'s alternate canon under `<project>/.kg/constructions/<slug>/` instead of the primary canon —
the in-session second construction `/kg-perturb` cross-generates against (§9/§15, `kg_generate`'s
`second_construction`). `source` names the second source document so spans verify against IT. Omit both for
the normal primary-canon write (byte-for-byte unchanged).

```json
{
  "dispositions": {"ACCEPTED": 3, "DEMOTED": 1, "QUARANTINED": 0, "REJECTED": 2},
  "details": [
    {"kind": "edge", "id": "e_generality-confound__attacked-by__specificity",
     "disposition": "ACCEPTED", "reason": "", "retryable": false},
    {"kind": "edge", "id": "e_x__grounds__y",
     "disposition": "REJECTED", "reason": "span-not-in-source", "retryable": false}
  ],
  "written_nodes": ["generality-confound", "specificity", "compression"],
  "receipt": "rcpt_3f2a…",
  "rolled_back": false,
  "error": null
}
```

- `dispositions` — counts keyed by every `Disposition` value: `ACCEPTED | DEMOTED | QUARANTINED | REJECTED`.
- `details[]` — one per validated item: `kind` (`node`|`edge`), `id` (the derived edge id
  `e_{source}__{relation}__{target}`, or `null`), `disposition`, `reason` (e.g. `no-supporting-span`,
  `span-not-in-source`, `span-not-in-named-source` (R4: span present in the corpus but not in the edge's
  named `source_file`), `truncated-payload`, `schema-invalid`, `forged-verdict-stripped`,
  `human-claim-stripped`, `undeclared-node-type`, `undeclared-edge-type`), `retryable` (**`false`** for SEMANTIC rejections — no-span,
  span-not-in-source; **`true`** for TRANSPORT — truncation, schema-invalid).
- `written_nodes[]` — node ids actually committed (includes boundary-auto-created placeholder source nodes).
- `rolled_back` / `error` — `rolled_back` is `true` (and `error` carries the failure message) when the multi-file canon write could not commit and was rolled back.
- `receipt` — a deterministic token: a short hash over the SORTED set of the payload's target ids (node ids +
  derived edge ids) **and each item's content-bearing fields** (a node's `label`/`body`/`node_type`/three axes/
  `confidence`; an edge's `span`/`note`/`confidence`/axes/`source_file`), so a same-ids payload whose TEXT
  changed (e.g. a corrected span) yields a DIFFERENT `receipt`. Same payload → same `receipt`, across restarts.
- `idempotency_key` (optional arg) — re-sending an identical write (same payload ⇒ same `receipt`) with the
  same key after a lost transport response is a TRUE no-op: the cached response is replayed VERBATIM with
  `idempotent_replay: true` (no re-validation, no second write). A reused key with a DIFFERENT payload is NOT
  replayed (a logged caller error; the new write is processed). A rolled-back batch is never cached, so a
  transient failure is still retryable.

A write may never set a non-`unverified` state or claim parser/human authorship: such payloads are
**DEMOTED** — any verdict or `obsolete` is reset to `unverified` (`forged-verdict-stripped`); `human` →
`agent` (`human-claim-stripped`); `deterministic` → `agent` (`deterministic-claim-stripped`, so an
extractor can't dodge span-present by self-declaring parser authorship). None are accepted as-is.

### 1.4 `mcp__plugin_burgess_burgess__kg_ground(target_id, verdict, kind="edge", note="", support_span="", support_note="")`

**The ONLY path that may set a verdict** (§1.4/§1.8). Stamps the epistemic_state and appends a `ground.audit`
record so the reconciler treats the transition as legitimate.

- `target_id: str` — an edge id (default `kind="edge"`) or node id (`kind="node"`).
- `verdict: str` — one of `VALID_VERDICTS = {grounded, rejected, failed, obsolete}` (lower-cased internally).
- `kind: str = "edge"` — `edge` or `node`.
- `note: str = ""` — appended to the edge's `notes` (e.g. the rejection reason `vague` for a generality-confound
  edge that is "true" only because it is generic/unfalsifiable, §1.6).
- `support_span: str = ""` / `support_note: str = ""` — **promotion support** (Stage 8). To move a
  `hypothesized` edge to `grounded` you MUST supply one, and it **upgrades the edge's provenance**:
  `support_span` (a verbatim source substring, span-verified) → `span-present`; `support_note` (an external
  citation, no span) → `inferred`. Ignored for non-hypothesized edges and for any verdict other than `grounded`.

```json
{"ok": true, "key": "e_generality-confound__attacked-by__specificity",
 "from": "unverified", "to": "grounded", "by": "agent"}
```

A promoted hypothesis adds `"provenance_upgraded_to": "span-present" | "inferred"` to the success return.
On failure: `{"ok": false, "error": "invalid verdict 'maybe'"}` / `"invalid kind 'Node'; expected node|edge"` / `"node not found"` / `"edge not found"`.
Promotion-specific refusals: `hypothesis-needs-support` (grounding a `hypothesized` edge with neither
`support_span` nor `support_note`), `support-span-not-in-source`, `support-span-too-short`.
For an edge, also sets `verdict_by` (always `agent` via this tool — a human verdict cannot be forged
through the tool surface) and `verdict_at`. Note: the return `key` for a node verdict is `node:<id>`;
for an edge it is the edge id.

> Adversarial grounding (§1.7): the adversarial grounder adds `attacked_by` edges then calls
> `kg_ground(target_id=<edge>, verdict="failed")`. Failed/rejected edges are NEGATIVE INFORMATION — never
> pruned, surfaced by `kg_context.falsification_counters`.

### 1.5 `mcp__plugin_burgess_burgess__kg_rename(old_id, new_id)`

Renames a node and rewrites every edge endpoint (`source`/`target`) referencing it, preserving the
single-canonical-edge rule. Both ids are slugged.

```json
{"ok": true, "old": "betweeness", "new": "betweenness",
 "touched": ["betweenness", "generality-confound", "specificity"]}
```

Failure: `{"ok": false, "error": "node not found"}` or `"target id exists"`. `ok` is `false` (with `error: "rename rolled back: …"`) if the multi-file write had to roll back.

`kg_rename` stays **strict** — `"target id exists"` is a refusal, never a silent merge. To collapse two
nodes that genuinely name the same concept, use `kg_merge` (below).

### 1.5b `mcp__plugin_burgess_burgess__kg_merge(from_id, into_id)`

The **deliberate node-merge** `kg_rename` refuses. Folds `from_id` into the existing `into_id` (both must
exist), rewrites every edge endpoint `from_id`→`into_id`, then RETIRES `from_id`. Where the rewrite makes
two edges share one canonical id they are **deduped** (never duplicated, never an error):

- **Negative information is sticky (§1.7):** if either edge is `failed` or `rejected`, the merged edge keeps
  that state — it is never pruned. Otherwise the stronger of `grounded` > `unverified` wins.
- The **verbatim span** and the stored **verdict note** are kept; provenance prefers `span-present`. No
  verdict or span is ever forged, upgraded, or invented — the merged state is always one a real edge held.
- **Self-loops** the rewrite creates (`source == target`) are dropped and reported — **except** a
  `failed`/`rejected` self-loop, which is PRESERVED (negative information is never pruned, §1.7): a refuted
  edge lying directly between the two merged concepts survives as a degenerate self-loop so its verdict +
  span stay in `falsification_counters`.

Keeps `into_id`'s `node_type`/`label`, and **refuses** (`"node_type conflict — refusing to merge"`) a merge
across two *different declared* node types so a wrong merge can't corrupt typing. A surviving verdict whose
edge id changed is re-keyed via the same id-migrating audit record as `kg_rename`, so it survives the
reconciler's §1.8 forgery sweep.

```json
{"ok": true, "from": "dpp", "into": "dpp-selection",
 "touched": ["dpp-selection", "collapse-toward-typical"],
 "edges_rewritten": 3, "edges_deduped": [{"id": "e_dpp-selection__defends-against__collapse-toward-typical", "state": "grounded"}],
 "self_loops_dropped": [], "nodes": 41, "edges": 87}
```

Failure: `{"ok": false, "error": "source node not found" | "target node not found" | "cannot merge a node into itself" | "node_type conflict — refusing to merge"}`; `ok` is `false` (`error: "merge rolled back: …"`) if the multi-file write rolled back — the graph is left untouched.

### 1.6 `mcp__plugin_burgess_burgess__kg_metrics()`

Cheap summary counts straight off the canon (no projection). No args.

```json
{"nodes": 24, "edges": 41, "edges_by_epistemic_state": {"unverified": 30, "grounded": 7, "failed": 4}}
```

`edges_by_epistemic_state` keys are whatever `EpistemicState` values are present
(`unverified|grounded|rejected|failed|obsolete`).

### 1.7 `mcp__plugin_burgess_burgess__query_graph(node_type=None, relation=None, epistemic_state=None, limit=50)`

Filtered read of the derived index. Nodes filtered by `node_type` and/or `epistemic_state`, **ordered by
precomputed `degree` DESC** (the honest MVP advisory, §1.6), capped at `limit`. Edges filtered by `relation` and **ordered by `id` ASC** (a deterministic, byte-stable top-N),
capped at `limit`. All filters optional.

```json
{
  "nodes": [
    {"id": "compression", "label": "Compression", "node_type": "compression", "file_type": "prose",
     "provenance": "span-present", "authored_by": "agent", "epistemic_state": "unverified",
     "degree": 6, "community": 0, "bridge_communities": 2, "structural_bridge": 1}
  ],
  "edges": [
    {"id": "e_generality-confound__attacked-by__specificity", "source": "generality-confound",
     "target": "specificity", "relation": "attacked_by", "provenance": "span-present",
     "authored_by": "agent", "epistemic_state": "unverified",
     "span": "a more specific claim, when it holds, defeats a vaguer one", "source_file": "source.md",
     "confidence": "INFERRED", "confidence_score": 0.6}
  ]
}
```

Node rows carry precomputed rank columns: `degree`, `community` (Leiden membership, `-1` if none),
`bridge_communities` (count of distinct communities among neighbours), `structural_bridge` (`1` iff
`bridge_communities >= 2`). Because the read does `SELECT *`, rows also carry the Stage-2 generative
columns — `betweenness`, the confound-corrected `spec_betweenness`, per-node `specificity`, and `gate_on`
— trusted as a ranking signal only when the specificity gate is ON (§1.6); until then they are advisory.
Valid `node_type` filters are the pack's declared types
(`compression|primitive|claim|metric|operation|failure`); `relation` filters the declared edge types
(`grounds|attacked_by|reconciles_with|bridges|collapses_into|confounded_by|approximates|defends_against|projects|survives`).

### 1.8 `mcp__plugin_burgess_burgess__get_node(node_id)`

One node row + its incident edges (both `source=` and `target=` matches).

```json
{
  "id": "specificity", "label": "Specificity", "node_type": "compression", "file_type": "prose",
  "provenance": "span-present", "authored_by": "agent", "epistemic_state": "unverified",
  "degree": 4, "community": 0, "bridge_communities": 1, "structural_bridge": 0,
  "edges": [
    {"id": "e_generality-confound__attacked-by__specificity", "source": "generality-confound",
     "target": "specificity", "relation": "attacked_by", "provenance": "span-present",
     "authored_by": "agent", "epistemic_state": "unverified", "span": "...", "source_file": "source.md",
     "confidence": "INFERRED", "confidence_score": 0.6}
  ]
}
```

Returns `{"error": "not found"}` when the id is unknown.

### 1.9 `mcp__plugin_burgess_burgess__get_neighbors(node_id, relation=None)`

A **list** (not a dict) of edge dicts incident to `node_id` (as `source` OR `target`), optionally filtered by
`relation`. Each element has the same shape as an edge row above. Empty list if the node has no incident edges.

### 1.10 `mcp__plugin_burgess_burgess__shortest_path(source, target)`

BFS over the derived edge list, treated as **undirected** (no centrality is computed).

```json
{"path": ["generality-confound", "specificity", "betweenness"]}
```

`{"path": ["x"]}` when `source == target`; `{"path": null}` when no path exists.

### 1.10b `mcp__plugin_burgess_burgess__kg_explain_path(nodes)`

**READ-ONLY egress** (§2). Traces the associative chain connecting `nodes` over **`grounded` edges only** —
`unverified`/`hypothesized`/`failed`/`rejected` edges are excluded entirely, so a returned chain is one that
has actually been verified. For >2 nodes the visiting order comes from a deterministic nearest-neighbour
walk (a TSP approximation, byte-stable across processes) over the grounded shortest-path closure; 2 nodes use a
deterministic sorted-neighbour BFS. Each hop carries its grounded `relation` + verbatim `span` for audit, and
`leap` (= path edge-count) is an **advisory** "creative-leap"/creative-distance signal — never a verdict,
never written, never a score.

```json
{"path": ["entropy", "time", "betweenness"],
 "edges": [{"source": "entropy", "target": "time", "relation": "grounds", "span": "Entropy grounds the arrow of time"}],
 "leap": 2, "grounded_only": true}
```

When no fully-grounded path exists: `{"path": [], "edges": [], "leap": null, "grounded_only": true,
"reason": "no fully-grounded path between <a> and <b>"}` — an honest absence (the concepts are joined only
through unverified/hypothesized/refuted links, or not at all), never an exception.

**At most 32 distinct nodes per call.** The grounded shortest-path closure costs one BFS per pair, so the
work is quadratic in the number of concepts you pass. Beyond the cap the tool refuses in the same empty
shape rather than wedging the engine: `{"path": [], "edges": [], "leap": null, "grounded_only": true,
"reason": "too many nodes: 80 (max 32)"}`.
Duplicates are deduped before the cap is applied. If you want to relate more concepts than that, ask a
narrower question — a 32-hop chain is already past what a person can read.

### 1.11 `mcp__plugin_burgess_burgess__kg_context(query=None, budget=2000)`

The **grounding-aware, provenance-carrying, token-budgeted** context tool — the one to call before reasoning
over the graph. Reads precomputed ranks **O(1)**; it **NEVER computes centrality in-request** (centrality is
precomputed off the hot path by the projector). `query` (optional) does a `LIKE` filter over edge
`source|target|relation|span`. `budget` (default `2000`) caps approximate tokens (`len(json)//4` per item).

Priority fill order (best context first, until the budget is spent): **grounded edges first**, then
`span-present` provenance, then `inferred`, then by `confidence_score` DESC. The grounded `items[]` and the
hypothesized `hypotheses[]` lanes share **one** running budget (§1.11): hypotheses fill only what the items
lane left, and `approx_tokens` reports the true total across both.

```json
{
  "items": [
    {"id": "e_compression__grounds__claim", "source": "compression", "target": "claim",
     "relation": "grounds", "provenance": "span-present", "authored_by": "agent",
     "epistemic_state": "grounded", "span": "...", "confidence": "INFERRED", "confidence_score": 0.82}
  ],
  "hypotheses": [
    {"id": "e_entropy__bridges__time", "source": "entropy", "target": "time", "relation": "bridges",
     "provenance": "hypothesized", "authored_by": "deterministic", "epistemic_state": "unverified",
     "span": "", "confidence": "AMBIGUOUS", "confidence_score": 0.5}
  ],
  "approx_tokens": 1840,
  "budget": 2000,
  "falsification_counters": {"failed_or_rejected_edges": 4},
  "advisory": {
    "signal": "structural-bridge",
    "note": "advisory heuristic, not a guarantee",
    "nodes": [
      {"id": "compression", "label": "Compression", "degree": 6, "bridge_communities": 2}
    ],
    "bridge_metric": {
      "gate_on": 0,
      "ranked_by": "structural_bridge",
      "note": "gated: spec_betweenness stays advisory; ranking by structural-bridge/degree (§1.6)",
      "nodes": [
        {"id": "compression", "label": "Compression", "degree": 6, "betweenness": 0.21,
         "spec_betweenness": 0.46, "specificity": 2.0}
      ]
    }
  }
}
```

- `items[]` — budget-trimmed **grounded/text-claim** edge records (note: `source_file` is omitted from context
  items, unlike `query_graph`/`get_node` edge rows).
- `hypotheses[]` — the **SEPARATE** hypothesized lane (Stage 8 query segregation): machine proposals from
  `/kg-generate`, `provenance=hypothesized`, never mixed into the grounded `items[]`. A hypothesis becomes a
  fact only after `kg_ground` promotes it with support (§1.4).
- `approx_tokens` — tokens actually used across **both** lanes (`<= budget`).
- `falsification_counters.failed_or_rejected_edges` — count of edges in `FAILURE_STATES`
  (`rejected` + `failed`). **Memory of failures (§1.7): surfaced here, never pruned.** A non-zero counter is a
  signal that the graph already knows what was refuted; don't re-propose it.
- `advisory` — the **labelled structural-bridge** signal: `signal:"structural-bridge"`, an explicit
  `note:"advisory heuristic, not a guarantee"`, and up to 10 `nodes` with `structural_bridge=1` ordered by
  `degree` DESC. Treat as a hint, not a metric — the specificity-weighted bridge metric is GATED until the
  harness validates it (§1.4/§1.6). A structural bridge that is vague is the generality confound, not a real
  bridge.
- `advisory.bridge_metric` — the completed bridge metric (Stage 2): `gate_on` (`0`/`1`), `ranked_by`
  (`spec_betweenness` when the gate is ON, else `structural_bridge`), a `note`, and up to 10 `nodes` carrying
  **both** `betweenness` and the confound-corrected `spec_betweenness` so a reader sees the correction. Until
  the harness turns the gate on (`gate_on:1`), the trusted ranking stays the structural-bridge/degree advisory.

---

## 1A · The generative layer (§2–§14)

The four tools below are the *offensive* half (the inversion: **generate offensively, judge defensively**).
`kg_generate`/`kg_absorption` are read-only structural reads; `kg_propose`/`kg_operate` write through the
**hypothesized** lane only — they can never set a verdict or forge a text anchor. A candidate becomes grounded
knowledge solely when `kg_ground` (§1.4) promotes it with support.

### 1.12 `mcp__plugin_burgess_burgess__kg_propose(payload, construction=None, source=None)`

The **hypothesized write lane** (PLAN Stage 1). A thin, explicit alias over `kg_write` that forces every item
to `provenance=hypothesized` and **REFUSES** any item arriving with a text-claim provenance
(`span-present`/`inferred`) with reason `propose-lane-text-claim` — text claims belong on `kg_write`. Accepted
items transit the SAME `validate_payload`, so the hypothesized-lane rules apply (no span required; forged
verdicts demoted; failure-collapse `QUARANTINED/collapses-into-known-failure`; pack vocabulary enforced;
`authored_by=deterministic` **preserved** here, `human` demoted to `agent`). `construction`/`source` route the
proposal to a named second construction's alternate canon exactly like `kg_write` (§9/§15); omit both for the
primary canon.

Returns the `kg_write` shape plus two fields:

```json
{"dispositions": {"ACCEPTED": 2, "DEMOTED": 0, "QUARANTINED": 1, "REJECTED": 1},
 "details": [ … ], "written_nodes": [ … ], "rolled_back": false, "error": null,
 "propose_lane": true, "refused_text_claims": 1}
```

`refused_text_claims` counts the call-site `propose-lane-text-claim` refusals (folded into `details[]` and the
`REJECTED` count).

### 1.13 `mcp__plugin_burgess_burgess__kg_generate(mechanism="bridge", k=10, second_graph=None, dpp=None, second_construction=None)`

The **discovery engine** (PLAN Stage 3). **READ-ONLY** — projects if stale, reads precomputed ranks O(1),
dispatches to the chosen mechanism, and returns ranked candidates. It never writes; `/kg-generate` routes the
candidates through `kg_propose`.

- `mechanism` — `bridge` (§2/§4) | `seed` (§3 residual `c − E[c|d]`) | `compression` (§7 dense-cluster MDL) |
  `regroup` (§8 re-partition bridges) | `transplant` (§5 hub pattern) | `ensemble` (§9 cross two
  constructions) | `periphery` (§5 low-degree sources → max-connectability anchor; the periphery the
  hub-seeking mechanisms ignore), or `all`/`default`.
- `k: int = 10` — max candidates returned (ranked).
- `second_graph: str | None` — path to a **pre-built** second construction's `graph.json` for `ensemble`
  (the §11 escape hatch). Without a second construction, `ensemble`/`all` **degrades to `regroup`** and says
  so in `note` (run `/kg-perturb` to supply one).
- `second_construction: str | None` — the **name** of an in-session second construction built key-free via
  `kg_write(..., construction=<name>)`. The engine projects its alternate canon
  (`<project>/.kg/constructions/<slug>/`) here and cross-generates — no API key, no `backend` extra. Takes
  effect only when `second_graph` is not given (an explicit path wins); an absent/empty construction degrades
  to `regroup` with a `note`. This is what `/kg-perturb` uses for its in-session exo move (§9/§15).
- `dpp: bool | None = None` — the **advisory-DPP presentation** (I5). `None` falls back to the pack's
  `divergence.dpp` (default **off**). When ON and >1 candidate came back, the SAME candidate set is
  reordered by hybrid-descriptor DPP — one semantic axis (batch k-NN novelty over candidate embeddings)
  plus three graph-structural axes (`community` intra/cross, endpoint `graph_distance`, `grounded_mix` of
  the neighborhood) — and a `divergence_advisory` block is added: `{applied, order:"dpp", axes,
  bins, semantic_novelty, cliche_distance, cliche_hubs, pool, beyond_cap_kept_in_donor_order, note}`. `cliche_distance` is
  distance from the graph's "center" (the top-6 grounded-degree hubs — the structural cliché map);
  only the first 200 candidates enter the DPP pool (the rest keep mechanism order, reported via
  `beyond_cap_kept_in_donor_order`). **Advisory ceiling, snapshot-enforced:** same candidates, same
  scores, bit-identical grounding downstream; if the divergence deps are unavailable the deterministic
  mechanism ranking is kept and `note` says why (I9).

```json
{"mechanism": "bridge", "k": 10, "gate_on": 0, "count": 2, "note": "",
 "candidates": [
   {"kind": "edge", "mechanism": "bridge", "source": "entropy", "target": "time", "relation": "bridges",
    "label": "", "node_type": "", "score": 0.81, "specificity": 2.1,
    "rationale": "cross-community pair, generality-controlled", "section": "§4", "convergence": 2}
 ]}
```

Each candidate is a `Candidate` dict: `{kind, mechanism, source, target, relation, label, node_type, score,
specificity, rationale, section, convergence}` (`provenance` is always `hypothesized`, never carried — the
propose lane forces it). `convergence` is **advisory** — the number of *distinct* mechanisms that
independently proposed the same edge (≥1); a grounding-queue ranking prior, never folded into `score` and
never written to the canon, harness-gated (`harness.convergence`) before it may reorder grounding.

### 1.14 `mcp__plugin_burgess_burgess__kg_operate(op, target=None, label="", body="", members=None, k=None)`

The **four §8 endo operations** (PLAN Stage 4), each persisting its result **through the propose lane**
(`kg_propose`), so everything lands `hypothesized`/`unverified` with no span.

- `op` — `collapse` (cluster → a new compression node + `collapses_into` edges; `members` names an explicit
  member set, else the cluster is inferred from `target`) | `explode` (a node → latent facet children) |
  `regroup` (persist §8 re-partition bridges) | `open` (a new primitive + attachment points).
- `target`, `label`, `body`, `members`, `k` — operation-specific (see the docstrings); unused ones are ignored.

Returns the `kg_propose` shape with `{ok: true, op, info}` merged in. On a bad op or nothing to operate on:
`{"ok": false, "op": "collapse", "error": "no structure to operate on", "info": …}` or
`{"ok": false, "error": "unknown op 'foo'; expected collapse|explode|regroup|open"}`.

### 1.15 `mcp__plugin_burgess_burgess__kg_absorption()`

The **§14 absorption window** (PLAN Stage 5). For each node grounded *from* a hypothesis, scores how long it
stayed perturbing before the graph renormalised, so the slate can prefer the fertile middle. Reads the derived
graph plus the `derived/generations.json` ledger that `/kg-generate` appends to. No args.

```json
{"tracked": 3, "summary": {"fertile": 1, "absorbed": 1, "isolated": 1},
 "nodes": {"compression": {"half_life": 2.0, "status": "fertile"}},
 "note": ""}
```

`status ∈ fertile | absorbed | isolated`. With no ledger yet, `tracked` is `0` and `note` explains that
`/kg-generate` has not started tracking the window (never an error).

### 1.16 `mcp__plugin_burgess_burgess__kg_agenda(limit=5)`

**Read-only structural "suggested questions"** (R6). Reads ONLY precomputed derived columns (node ranks +
edge provenance/state) and returns ~`limit` structural gaps, split into two lanes that mirror `kg_context`'s
`items[]`/`hypotheses[]`:

```json
{"answerable_now": [{"detector": "well-grounded", "lane": "answerable_now", "focus": ["compression"],
                     "question": "'compression' is a well-grounded hub (degree 4, 4 grounded) — how do its neighbours (claim, …) interrelate?",
                     "signals": {"degree": 4, "structural_bridge": 1, "betweenness": 0.3, "spec_betweenness": 0.2, "specificity": 0.7}}],
 "blocked_on_grounding": [{"detector": "under-grounded-hub", "lane": "blocked_on_grounding", "focus": ["betweenness"],
                           "question": "Hub 'betweenness' (degree 5) is under-grounded — only 1/5 of its edges are grounded. Drain its unverified queue (/kg-ground) to trust it.", "signals": {…}}],
 "count": 2, "limit": 5, "gate_on": 0, "ranked_by": "structural_bridge",
 "note": "structural suggestions — a heuristic, not a guarantee. …"}
```

- **Detectors**: `orphan` (degree 0), `hypothesized-only` (every live edge a proposal — always **blocked**,
  never laundered into answerable), `under-grounded-hub`, `well-grounded` (the only **answerable_now** kind),
  `edgeless-communities` (a disconnected cluster). The `answerable_now` vs `blocked_on_grounding` split is the
  honesty move: a question you cannot ground-back-honestly surfaces as blocked.
- **Ranking** mirrors `kg_context`'s gate-aware switch — `spec_betweenness` **only** when `gate_on=1`, else the
  `structural_bridge`/degree advisory; **never** raw betweenness as lead. `ranked_by` reports which.
- **Read-only / measure-never-gate**: it asserts no edges, copies no spans, stamps no verdicts; the question
  text is session-time only and never written to the canon. It is a **heuristic, not a guarantee** — it
  suggests where to look or what to ground next; it never answers or acts. `limit` is clamped to `[1, 50]`.

### 1.17 `mcp__plugin_burgess_burgess__kg_export(kind="all")`

**Read-only human-facing render** (R1). Projects-if-stale, then consumes ONLY the derived layer (through the
shared `_agenda_reader()` seam) plus `kg_metrics`, and writes two **disposable** artifacts under the derived
dir. `kind ∈ {html, report, all}` (default `all`).

```json
{"ok": true, "kind": "all",
 "html_path": "…/derived/graph.html", "report_path": "…/derived/GRAPH_REPORT.md"}
```

- **`graph.html`** — a self-contained, fully-offline canvas force layout (no network, no `<script src>`, data
  inlined). The **three axes are on INDEPENDENT visual channels** (never one "confidence" colour):
  `epistemic_state`→edge line (solid grounded · dashed unverified · **red failed/rejected** · dotted
  hypothesized; failed/rejected are **drawn, never filtered** — §1.7), `authored_by`→node border,
  `provenance`→node fill opacity. **Node size = degree** (the honest advisory); the bridge highlight is
  gate-aware (`spec_betweenness` only when `gate_on=1`, else the structural-bridge advisory — size is never
  the bridge metric).
- **`GRAPH_REPORT.md`** — headline counts from `kg_metrics` (cannot drift), per-community axis breakdowns, the
  never-pruned falsification list, R3 stale verdicts, and R4 per-source-file edge counts.
- **Read-only / measure-never-gate**: consumes only the derived layer, writes only its two artifacts; never
  reads prose, never writes through `kg_write`/`kg_ground`, never `_atomic_write`s `graph.json`/`index.sqlite`
  (`projector.py` stays their sole writer). Cannot forge a verdict or bypass span-present. Also: CLI
  `python -m kg_engine.export html|report|all` and the `/kg-view` command.

### 1.18 `mcp__plugin_burgess_burgess__kg_status()`

A cheap, **projection-FREE** status + coverage probe. Reads ONLY the canon (and the source text for coverage);
it **never** triggers or refreshes the derived layer (unlike `kg_metrics`, which serves off the index when
fresh), so it is safe and instant even mid-build. Use it to confirm build progress and **resume a partial
build** after a transport hiccup without grepping the filesystem. No args.

```json
{
  "ok": true,
  "version": "<__version__>",
  "nodes": 113,
  "edges": 180,
  "edges_by_epistemic_state": {"unverified": 150, "grounded": 25, "failed": 5},
  "nodes_by_epistemic_state": {"unverified": 113},
  "unverified_edges": 150,
  "source": {"path": "/abs/path/source.md", "exists": true, "files": ["source.md"]},
  "coverage": {
    "files": [{"file": "source.md", "covered": true, "sections": 19, "covered_sections": 12}],
    "sections": [{"file": "source.md", "title": "The boundary", "covered": true}]
  },
  "derived_present": true,
  "projection_degraded": null
}
```

- `unverified_edges` — the still-`unverified` grounding-queue size (the `/kg-ground` backlog).
- `source` — the **engine-resolved** source (`{path, exists, files}`): `path` is the configured
  `source_path` the server resolved (or `null` when nothing is configured), `exists` is true iff it
  resolves to ≥1 readable `.md`/`.txt` file, `files` are the ordered basenames (R4). `/kg-build` reads the
  source path from HERE, not from a shell env var — the host injects userConfig only into the server
  process, so a Bash-shell env-var read would silently miss a configured `source_path` and build the demo
  by surprise.
- `coverage` — which source files / `##` sections already have at least one ANCHORED (span-present) edge:
  `files[]` (`{file, covered, sections, covered_sections}`) and per-section `sections[]`
  (`{file, title, covered}`). A section with no covered span hasn't been extracted yet — the **resume**
  signal. If the source can't be read it degrades to
  `{"files": [], "sections": [], "note": "source unavailable (…)"}`.
- `derived_present` — a path-existence check on the derived db only (no db open).
- `projection_degraded` — echoes the last reprojection failure (a read sets it, never this probe); `null` when
  healthy.

Unlike `kg_metrics` (§1.6) this NEVER opens the derived db. Granted to `/kg-build` for the resume use.

---

## 1B · The divergence surface (`kg_diverge_*`) — seven tools

The divergence engine (`scripts/kg_engine/divergence/` — embedder, MAP-Elites archive, k-NN novelty, DPP
slates, anti-collapse monitor) runs inside the same MCP server as seven tools. They sit **below the
grounding boundary**: geometry affects what is proposed and in what order, never what is true (I5); nothing
under `divergence/` can set or upgrade an epistemic state (I3, import-firewalled); and every `kg_*` graph
tool keeps working when the divergence deps are blocked (I9) — a `kg_diverge_*` call then returns a
provisioning error to relay verbatim.

**State layout** — project-local under `.kg/diverge/<project-slug>/` (base dir: `$KG_DIVERGE_HOME` if set,
else `$KG_PROJECT_DIR`, else cwd):

```text
meta.json  axes.json  session.json  materialized.json     durable
session/                                                  EPHEMERAL (I10)
  archive.json          MAP-Elites niches + counts
  candidates.json       id -> candidate record
  embeddings.npz        surface vectors (binary npz)
  mech_embeddings.npz   open-axis/mechanism vectors (npz)
  open_nicher.json      the open-axis Voronoi partition
memory/<domain-slug>/                                     durable
  pins.json  discards.json  comparisons.jsonl
```

**Session rule (I10):** `kg_diverge_init` with a NEW (or omitted) `session` id wipes `session/` plus the
geometry-coupled meta series (cycle count, cosine/novelty windows, erosion streak, gap log); re-passing the
SAME id resumes it. Pins, discards, comparisons and the `materialized.json` ledger always survive — the
knowledge graph, not the archive, is the durable store.

### 1B.1 `kg_diverge_init(project, axes=None, seed=0, session=None)`

Begin/resume a divergence session for a brief. `axes` resolves by cascade: an inline axes dict → a path or
shipped template name (`pack/domains/*.yaml`, `pack/domains/examples/*.yaml`) → `None`, which prefers the
pack's `divergence:` section and falls back to `pack/domains/generic.yaml`. Also syncs materialized fates
(see §1B.7): any previously materialized pin whose canon node/edge was actively **falsified** (`failed`) is
folded into this brief's **discards** (unified negative memory, I8) and reported; a merely-unsupported
(`rejected`) pin — the expected state of a novel idea with no in-source span yet — stays recoverable in the
lane and is **not** discarded.

```json
{"ok": true, "domain": "generic", "reset": false, "session_id": "sess-…", "new_session": true,
 "paths": {"state_dir": "…/.kg/diverge/cold-brew-launch"}, "materialized_failures_discarded": []}
```

### 1B.2 `kg_diverge_ingest(project, candidates, axes=None, seed=0)`

One divergence cycle: embed → near-duplicate dedupe → MAP-Elites placement → k-NN novelty → DPP slate,
with the monitor reading the round. Candidate shape (see `/kg-diverge` step 6):
`{id, text, descriptor: {<axis>: value, …, mechanism: "…"}, fitness?, genealogy: {operator_id, parents}}`.

```json
{"slate": [{"id": "c3", "text": "…", "coords": {"angle": "…"}, "niche_id": "…", "novelty": 0.41,
            "mechanism_novelty": 0.38, "fitness": 0.8}],
 "ask_pairs": [["c3", "c7"]], "ask_policy": "refine",
 "monitor": {"collapsing": false, "under_generation": false, "variety_eroding": false,
             "mean_cosine": 0.34, "entropy": 0.82},
 "slate_ids": ["c3", "c7"], "slate_mechanism_novelty": 0.44,
 "open_axis": {"frozen": false, "n": 9}}
```

Field honesty: `slate_ids` is the id list of the slate items, NOT breeding parents — it honors neither
pins nor discards, so never breed from it; use `kg_diverge_parents` for that. `novelty` is mean k-NN
cosine distance (k=5) to THIS SESSION's own ideas — a variety proxy,
never originality against the world; `mechanism_novelty` is the same for the open-axis value. `monitor`
flags are advisory notices (react per `/kg-diverge` step 9). When the axes set `engine: {gap_probe: true}`
the result also carries a `surface_mechanism_gap` block (measurement only).

### 1B.3 `kg_diverge_remember(project, event)`

Append one durable preference event: `{"type": "pin", "id": …}` · `{"type": "discard", "id": …}` ·
`{"type": "comparison", "winner": …, "loser": …}`. Pins are the strongest signal (always parents, recalled
across sessions, materializable); a discard is durable negative memory (never re-slated, never bred from;
re-pinning un-discards). Returns `{ok, type, …}`.

### 1B.4 `kg_diverge_parents(project, k=4, seed=0)`

Diverse stepping stones for the next generation, DPP-selected from the archive — pins ALWAYS included,
discards NEVER. Returns `{"parents": [{id, text, coords, niche_id, novelty, pinned}]}`.

### 1B.5 `kg_diverge_metrics(project)`

Archive health: `{entropy, mean_cosine, coverage, n, mechanism_spread, mechanism_n, open_axis}` (+
`gap_log` when the gap probe is on).

### 1B.6 `kg_diverge_recall(project, k=10, reexamine=None)`

The brief's preference memory, for injection into generation: `{domain, preferences, pins, discards,
summary: {n_comparisons, win_counts, preferred_values}}`. Like `init`, it first syncs materialized fates
(I8) — generate AWAY from `discards`, FROM `pins`. On a source change it also surfaces `failed`-fated
discards under `reexaminable_discards` (the divergence mirror of the graph R3-mirror; SURFACE-ONLY, never
auto-un-sealed). Pass `reexamine=[candidate_ids]` to EXPLICITLY un-seal those candidates — each drops from
`discards` and has its failure fate cleared, returning to the proposal pool (reported under
`reexamined_unsealed`); un-sealing never changes a graph verdict.

### 1B.7 `kg_diverge_materialize(project, candidate_ids=None, node_type="claim", edges=None)`

The **explicit door** from divergence into the graph — the ONLY way an idea leaves `.kg/diverge/`.
Materializes pinned ideas (`candidate_ids` defaults to all pins) as nodes routed **exclusively through the
propose lane** (`kg_propose` → the same boundary as every write):

- Only **pinned** candidates with a live session record materialize; a non-pinned id is `refused`
  (`not-pinned`); a pin whose session record is gone (I10) is `skipped` (`no-session-record` — re-ingest it
  first).
- Node id `idea-<project-slug>-<candidate-slug>`; the body carries the full lineage:
  `[diverge] pinned candidate=<id> brief=<project> session=<id> mechanism=<open-axis value>
  operator=<genealogy.operator_id>`.
- The boundary forces `provenance=hypothesized`, `epistemic_state=unverified`, `authored_by=agent` — a
  materialized pin earns promotion only via `kg_ground` with support, like any hypothesis.
- Optional `edges` link the new nodes to existing ones and transit the same boundary (text-claim provenance
  refused, forged verdicts stripped).
- The `materialized.json` ledger maps each candidate to its written nodes/edges; only if grounding later
  **falsifies** one (`failed`) does the next `init`/`recall` auto-discard it from the brief (I8) — a
  merely-unsupported (`rejected`) pin, the expected state of a novel idea with no in-source span yet, stays
  recoverable in the lane. The sync only *reads* verdicts — verdicts stay `kg_ground`'s monopoly.
- When a source is already configured and ≥1 pin materialized, the result carries an advisory-only
  `advisory` string (grounding these novel pins against the existing source will correctly leave them
  `unverified` until sources are added) — never a disposition, verdict, or ledger write.

```json
{"ok": true, "materialized": 2,
 "results": [{"candidate": "c3", "status": "materialized", "node": "idea-cold-brew-launch-c3"},
             {"candidate": "c9", "status": "skipped", "reason": "no-session-record"}],
 "advisory": "A source is already configured. Grounding these pins will correctly leave a novel idea unverified…",
 "propose": {"dispositions": {"ACCEPTED": 2}, "…": "…"}}
```

### Engine constants (drift-guarded by tests)

- **Embedder** (`KG_DIVERGE_EMBEDDER`): `static` (default) = model2vec `minishlab/potion-multilingual-128M`
  — 256-dim, CPU/numpy, torch-free, ~120 MB, lazily downloaded, cached under `$HF_HOME` (pointed at
  `$KG_DATA/models` when unset); `hash` = deterministic 512-dim char-n-gram vectorizer (tests/offline
  escape hatch — an unavailable static model raises with instructions, it never silently degrades);
  `local` = sentence-transformers `BAAI/bge-small-en-v1.5` (384-dim, needs torch). Embedding widths may
  not mix within a project.
- **Geometry:** k-NN novelty `k=5`; near-duplicate cosine tau per embedder (static 0.93, hash 0.92,
  local 0.94); DPP pool cap 200; novelty-reference cap 500; open-axis Voronoi niches 24, partition frozen
  once 2×24 = 48 mechanisms accumulate; continuous axes bin 5 by default.
- **Judge bounds:** fitness blended at weight 0.3, affine-rescaled and clipped to a [0.7, 1.3] multiplier —
  it sharpens within-niche ordering, it can never prune variety.
- **Monitor:** mean-cosine threshold 0.55 (absolute fallback) / entropy threshold 0.50 (≥3 occupied
  niches) / relative flag at baseline+0.15 with absolute ceiling 0.80, rolling window 5, min baseline 2;
  variety-erosion sensor: window 5, fires at ≥1.5× decay acceleration for 2 consecutive generations;
  `under_generation` below 0.6× the per-generation target.
- Per-domain overrides live in the axes spec's `engine:` block — schema + defaults table in
  `pack/domains/_schema.md`.
- **Env:** `KG_DIVERGE_EMBEDDER` (provider), `KG_DIVERGE_HOME` (state base override),
  `KG_DIVERGE_DEBUG` (tracebacks).

---

## 2 · Deterministic CLI surface

Run via Bash. **Dev**: repo venv `/home/sergi/Burgess/.venv/bin/python` (or `uv run`). **Runtime**:
`${CLAUDE_PLUGIN_DATA}/.venv/bin/python` with `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/scripts`. The `kg_engine.*`
module CLIs require that `PYTHONPATH`; `f4_probe.py` is a standalone script. None of these gate the pipeline —
each prints a number + verdict; the orchestration logs it and proceeds (§4).

### 2.1 `f4_probe.py` — extraction precision scorer

Operates on a derived `graph.json` (NetworkX node-link; reads `links` or `edges`). Three subcommands.

```bash
python scripts/f4_probe.py summary "$GRAPH"                     # shape of the graph
python scripts/f4_probe.py sheet   "$GRAPH" --n 80 --out labels.csv   # sample edges to label
python scripts/f4_probe.py score   labels.csv                  # precision / astrology / span-support
```

- **`summary <graph.json>`** — prints node/edge counts, nodes by `file_type`, edges by `confidence`
  (`EXTRACTED|INFERRED|AMBIGUOUS`), top relations, the `INFERRED` `confidence_score` distribution
  (min/median/max), and the count of *judged* edges (`INFERRED+AMBIGUOUS`) — the precision-relevant slice.
- **`sheet <graph.json> --n <N> --out <csv>`** — random-samples (seed 42) up to `N` non-`EXTRACTED` edges into
  a CSV with columns `edge_id, source_label, target_label, relation, confidence, confidence_score,
  source_file, verdict, span_found, notes`. Add `--include-extracted` to also sample deterministic edges.
  An annotator then fills two columns:
  - `verdict` ∈ **`correct | fabricated | vague | wrong_type`** (the only allowed labels).
  - `span_found` ∈ **`y | n`** (the span-present check).
- **`score <labels.csv>`** — reads rows with a filled `verdict` and prints:
  - `PRECISION (correct / labeled)` — **exit gate is `>= 0.70`**.
  - `astrology rate (fabricated+vague)` — the grounding risk, measured.
  - `span-support rate (span_found=y)` — the span-present rate.
  - verdict breakdown, precision per relation (n>=3), and confidence calibration (mean `confidence_score` for
    correct vs incorrect; a gap `>= 0.10` means the score tracks correctness, else it is "vocabulary, not
    grounding").

`vague` is the generality confound made measurable: a relation "true" only because it is generic/unfalsifiable.

### 2.2 `python -m kg_engine.pack` — pack validation + glossary coverage

```bash
python -m kg_engine.pack validate pack/pack.yaml            # PackContract validation only
python -m kg_engine.pack validate pack/pack.yaml examples/source.md   # validate + coverage
python -m kg_engine.pack coverage pack/pack.yaml examples/source.md   # coverage (source required)
```

`validate` loads the YAML as a `PackContract` (Pydantic, `extra="forbid"`; `node_types`/`edge_types` must be
non-empty + unique). On success prints `PACK OK: domain=… node_types=N edge_types=M glossary=K`; on failure
`PACK INVALID: <error>` to stderr (exit 1). If a source path is given (always for `coverage`), also prints
`coverage(...)`:

```
PACK OK: domain='conceptual theory' node_types=6 edge_types=10 glossary=12
  source_defined_terms: 10
  glossary_terms: 12
  source_terms_in_glossary: 10
  source_coverage: 1.0
  glossary_grounded_in_source: 1.0
```

- `source_coverage` — fraction of the source's *defined terms* (bold/`code`/quoted phrases) present in the
  glossary.
- `glossary_grounded_in_source` — fraction of glossary terms that actually occur in the source (don't invent
  vocabulary the source never uses).

### 2.3 `python -m kg_engine.harness` — agreement · specificity · ideation · convergence

Deterministic measurement over data the subagents produce. Four subcommands, each reads/writes JSON. If the
optional path is missing, each falls back to a built-in demo and notes it on stderr.

#### `agreement [label_sets.json]`

Nominal **Krippendorff's alpha** across independent coders. **Input JSON is a LIST of coder dicts**, one per
coder, mapping `unit_id -> label`; units rated by `<2` coders are ignored. Labels are the f4_probe verdict
vocabulary `correct | fabricated | vague | wrong_type`.

```json
[
  {"e1": "correct", "e2": "vague", "e3": "correct"},
  {"e1": "correct", "e2": "vague", "e3": "fabricated"}
]
```

Prints `krippendorff_alpha: <a>` and `verdict: RELIABLE (>=0.67)` or `BELOW THRESHOLD — grounding signal stays
advisory`. Threshold **`>= 0.67`** = reliable inter-annotator agreement.

#### `specificity [graph.json] [source.md]`

The **bridge-metric gate** (§1.4/§1.6). Compares specificity-weighted betweenness vs raw degree vs raw
betweenness over the derived graph, using IDF seeds from the source corpus (or a demo corpus). Args default to
`derived/graph.json` and the demo corpus. Emits JSON:

```json
{
  "n": 24,
  "mean_specificity": 1.42,
  "specificity_spread": 1.9,
  "betweenness_leader_specificity": 0.91,
  "top_raw_betweenness": ["system", "idea", "specificity"],
  "top_specificity_weighted": ["specificity", "betweenness", "reconciler"],
  "rank_churn": 0.4,
  "generality_confound_detected": true,
  "gate_on": true,
  "verdict": "specificity-weighting earns its place — gate ON"
}
```

`gate_on` is `true` only when the generality confound is detected (raw-betweenness leaders are vaguer than
average), rank churn `> 0.2`, **and** the node specificities actually spread (a degenerate corpus where every specificity is equal keeps the gate closed). Until this returns `gate_on:true` on real data, the specificity-weighted
bridge metric stays advisory and `kg_context` exposes only the structural-bridge heuristic. (Graphs with
`< 3` nodes return `{"gate_on": false, "reason": "graph too small", "n": …}`.)

#### `ideation [outputs.json]`

Scores pooled ideation outputs per condition (the value-of-the-graph experiment). **Input JSON**:

```json
{
  "outputs": {
    "control": ["A is connected to B."],
    "graph":   ["A bridges B and C because entropy grounds time."],
    "rag":     ["A relates to B somehow."]
  },
  "source": "<full source text for novelty/unsupported scoring>"
}
```

(`source` optional; if the top-level object isn't `{outputs, source}` it is treated as the
outputs-by-condition map directly.) Emits a per-condition `table` with `n, diversity, novelty, utility,
unsupported_rate` and a `verdict` comparing **graph vs control**:

```json
{
  "table": {
    "control": {"n": 5, "diversity": 0.71, "novelty": 0.62, "utility": 0.3, "unsupported_rate": 0.2},
    "graph":   {"n": 5, "diversity": 0.83, "novelty": 0.74, "utility": 0.6, "unsupported_rate": 0.18},
    "rag":     {"n": 5, "diversity": 0.7,  "novelty": 0.55, "utility": 0.2, "unsupported_rate": 0.25}
  },
  "verdict": "graph condition produced more diverse/novel ideas without more unsupported claims"
}
```

The `graph` condition "wins" only if it is `>=` control on diversity AND novelty, **strictly greater** on at least one of them, AND its `unsupported_rate` is no more than `control + 0.05` — i.e. measurably more/better ideas **without** more unsupported claims (an exact tie on both axes is not a win).
The canonical arm names are `control | graph | graph+generate | graph+generate+dpp | rag | lightrag`; when
the extra arms are present the output also carries `generate_verdict`, `dpp_verdict`, and
`lightrag_verdict` under the same win rule.

#### `convergence [generation_labels.json]`

The **convergence gate** for `kg_generate`'s advisory tally. Input: labeled generated edges, each with its
`convergence` count (distinct mechanisms that proposed it) and its grounding outcome. Compares the grounding
rate of the HIGH band (`convergence >= 2`) vs the LOW band (`== 1`); `gate_on` is `true` only when the high
band grounds at a rate more than **0.10** above the low band with enough samples per band. Until then the
tally stays a display-only prior — it never reorders the grounding queue.

### 2.4 `python -m kg_engine.divergence` — the divergence engine, no MCP needed

The same engine the `kg_diverge_*` tools call, as a CLI (dev/debug; `/kg-diverge` uses the tools):

```bash
python -m kg_engine.divergence init-project --project <slug> --axes <dict|path|template> [--seed N] [--session ID]
python -m kg_engine.divergence ingest   --project <slug> --candidates <json> --axes <…> [--seed N]
python -m kg_engine.divergence recall   --project <slug> [--k 10]
python -m kg_engine.divergence remember --project <slug> --event <json>
python -m kg_engine.divergence parents  --project <slug> [--k 4] [--seed N]
python -m kg_engine.divergence metrics  --project <slug>
python -m kg_engine.divergence paths    --project <slug>          # print resolved state paths
python -m kg_engine.divergence selftest [--live] [--seed N]       # exit 1 on failure
python -m kg_engine.divergence import-cambrian --project <slug> [--from <dir>]
```

**`selftest`** is the engine's offline correctness contract (hash embedder unless `--live`; also run by the
suite's `selftest`-marked e2e test). `ok` requires ALL of:

- **variety gate** — the engine beats a single-shot baseline on mean pairwise distance (margin +0.10) AND
  Vendi score (margin +0.5) AND niche entropy; the DPP slate beats taking the first N (margin +0.01,
  averaged over 3 seeds); on a uniform pool the DPP does not regress below a random subset (eps 0.02,
  50 trials); a higher within-niche fitness wins its niche (and swapping flips the elite);
- **collapse reversal** — a deliberately samey generation trips `collapsing: true`, and the next diverse
  one recovers with a lower mean cosine;
- **files written** — the session state files all exist afterwards.

`import-cambrian` maps a pre-fusion project's preference memory (pins, discards, comparisons — per domain,
read-only on the source, default `~/.cambrian/<project>` or `$CAMBRIAN_HOME`) into
`.kg/diverge/<slug>/memory/`. Geometry files and `meta.json`/`axes.json` are deliberately NOT imported
(session-ephemeral by design; re-created by `init`) and are reported as `skipped` so nothing disappears
silently. Report: `{ok, source, target, imported: {<domain>: {pins, discards, comparisons}}, skipped,
errors}`.

---

## 3 · Quick map

| You want to… | Use |
|---|---|
| check the server is up / pack loaded | `kg_ping()` |
| write extracted nodes/edges | `kg_write(payload)` (boundary, §1.5) |
| set a verdict (grounded/rejected/failed/obsolete) | `kg_ground(...)` — the **only** way |
| fix a node id everywhere | `kg_rename(old, new)` (strict — refuses if `new` exists) |
| merge two nodes that name the same concept | `kg_merge(from, into)` (dedups edges, keeps negative info) |
| cheap counts | `kg_metrics()` |
| projection-free status / resume a partial build | `kg_status()` |
| browse by type/relation/state, ranked by degree | `query_graph(...)` |
| one node + its edges | `get_node(id)` |
| a node's edges (list) | `get_neighbors(id, relation=?)` |
| connect two nodes (structural) | `shortest_path(a, b)` |
| connect concepts over GROUNDED edges only (+ advisory leap) | `kg_explain_path(nodes)` |
| budgeted, grounding-aware context (+ failures + bridges) | `kg_context(query=?, budget=?)` |
| propose hypothesized candidates (the offensive lane) | `kg_propose(payload)` |
| generate structural idea candidates (read-only) | `kg_generate(mechanism=?, k=?, second_graph=?, dpp=?, second_construction=?)` |
| run a §8 endo operation (collapse/explode/regroup/open) | `kg_operate(op, …)` |
| score the §14 absorption window | `kg_absorption()` |
| start/resume a divergence session for a brief | `kg_diverge_init(project, axes=?, session=?)` |
| run one divergence cycle (embed → slate → monitor) | `kg_diverge_ingest(project, candidates, …)` |
| record a pin / discard / A-vs-B answer | `kg_diverge_remember(project, event)` |
| diverse stepping stones (pins in, discards out) | `kg_diverge_parents(project, k=?)` |
| archive health / gap log | `kg_diverge_metrics(project)` |
| recall a brief's pins/discards/comparisons | `kg_diverge_recall(project)` |
| carry pinned ideas into the hypothesized lane | `kg_diverge_materialize(project, …)` |
| score extraction precision | `f4_probe.py summary|sheet|score` |
| validate the pack / glossary coverage | `kg_engine.pack validate|coverage` |
| inter-annotator agreement | `kg_engine.harness agreement` |
| bridge-metric gate verdict | `kg_engine.harness specificity` |
| value-of-the-graph experiment | `kg_engine.harness ideation` |
| divergence engine offline correctness contract | `kg_engine.divergence selftest` |
