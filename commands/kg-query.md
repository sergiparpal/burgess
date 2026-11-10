---
description: Answer a question against the knowledge graph with provenance and falsification counters attached.
argument-hint: <question>
allowed-tools: mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__query_graph, mcp__plugin_burgess_burgess__get_node, mcp__plugin_burgess_burgess__get_neighbors, mcp__plugin_burgess_burgess__shortest_path, mcp__plugin_burgess_burgess__kg_explain_path, mcp__plugin_burgess_burgess__kg_agenda
---

You are answering a question **against the grounded knowledge graph**, not against your own prior
knowledge. The graph is the human-editable canon projected into a derived index; every edge carries three
orthogonal axes (provenance / authored_by / epistemic_state) and the engine never prunes its failures. Your
job is to answer the question while **faithfully surfacing the grounding state of every claim you lean on**.

Question: **$ARGUMENTS**

## What you may NOT do
- Do **not** present a hypothesized or unverified edge as fact. An edge is only a *fact in the canon* when its
  `epistemic_state` is `grounded`. Everything else is a candidate, a downgrade, or negative information.
- Do **not** present the structural-bridge advisory as a centrality truth. It is a degree-based heuristic and
  is **confounded_by** the generality confound (§1.6) — a vague node sits on many paths for empty reasons.
- Do **not** invent edges, nodes, spans, or verdicts. If the graph does not contain the answer, say so and
  point at what *is* there.
- Do **not** read `canon/`, the derived index or the source through the shell to build the answer. The tools
  below carry every claim, its three axes and its verbatim span, so a shell read adds no fact to a grounded
  answer, and in many setups each shell command waits for the user's approval. Open a canon note only when
  the user asks why a verdict fell as it did: its `notes` say, and no read tool returns them.

## Procedure

### 0. (Optional) Orient with the structural agenda
If you want to suggest *where to look* (e.g. the question is open-ended, or you're cold-starting a session),
you **may** call `mcp__plugin_burgess_burgess__kg_agenda(limit=5)` first. It reads only
precomputed structural signals and returns `answerable_now[]` (well-grounded neighbourhoods you can answer
from now) vs `blocked_on_grounding[]` (orphans, hypothesized-only neighbourhoods, under-grounded hubs,
disconnected clusters that need `/kg-ground` or extraction first). It is a **heuristic, not a guarantee** and
suggests questions — it never answers them. This step is optional: skip it to keep the query token budget
predictable, and never present a `blocked_on_grounding` gap as if it were answered.

### 1. Get grounded, token-budgeted context
Call `mcp__plugin_burgess_burgess__kg_context(query=$ARGUMENTS)`. This is the primary source. It returns:
- `items[]` — **grounded-lane** edges, each carrying
  `{id, source, target, relation, provenance, authored_by, epistemic_state, span, confidence, confidence_score}`.
  This lane **never** contains a hypothesized proposal. With a query it holds the edges whose span, relation or
  endpoints (ids and labels) share a word with the question, **grounded before unverified**, then best match
  first: the more of its words an edge holds, and the rarer they are in the graph, the earlier it comes. Case,
  accents, plural endings and function words («del», "the") don't count. A search uses **at most 12 words**,
  the first ones in the question, and `query_terms` lists the words it searched on.
- `hypotheses[]` — the **SEPARATE** hypothesized lane: machine proposals from `/kg-generate`
  (`provenance: hypothesized`, `epistemic_state: unverified`, **no span**). These are NOT facts and NOT
  grounded content — present them only under an explicit "Hypotheses (unverified proposals)" heading, never
  mixed into the grounded answer. A hypothesis becomes a fact only after `/kg-ground` promotes it with
  support (which upgrades its provenance to `span-present`/`inferred`).
- `items_total`, `hypotheses_total` — every edge that matched each lane. When `items_total` is larger than the
  `items[]` you got, the budget (`budget`, default 2000 tokens; `approx_tokens` is what was used) left the
  rest out. Say so, and if the answer needs them, call again with a larger `budget` (up to 100000) or a
  narrower question.
- `falsification_counters: {failed_or_rejected_edges}` — the **memory of failures** (§1.7). NEVER omit this.
- `advisory: {signal: "structural-bridge", note: "advisory heuristic, not a guarantee", nodes:[...],
  bridge_metric: {gate_on, ranked_by, nodes:[...]}}` — `bridge_metric` ranks by the confound-corrected
  `spec_betweenness` when `gate_on`, else falls back to the structural-bridge/degree advisory (§1.6).

If `query` matches nothing, the items list may be empty even though the graph is non-empty — fall back to the
lookups below before concluding "not in the graph."

### 2. Find nodes, then follow relationships
Use these to find what `kg_context` did not return and to follow specific relationships:
- `mcp__plugin_burgess_burgess__query_graph(text="…")` — finds nodes and edges **by what they say**: the nodes
  whose id or label, and the edges whose span, relation or endpoints, share a word with `text`, ranked as
  `kg_context` ranks a question, with `query_terms` and `matched` (the counts before `limit`). It also finds
  nodes that have no edge yet, which `kg_context` (edges only) never returns. Such a node is a concept the
  extractor named with no claim behind it: present it as that, never as a finding. Write `text` in the
  language of the source documents, normally with the question's own key words. The match is on the words the
  graph holds, so a translation finds little. The same limit of 12 words applies, and the words past it are
  dropped. To look for more, such as a list of codes from `H1` to `H20`, split them over several searches and
  check `query_terms` in each result. `text` combines with the filters below, e.g.
  `query_graph(text="<key words of the question>", epistemic_state="grounded")`.
- `mcp__plugin_burgess_burgess__query_graph(node_type=…, relation=…, epistemic_state=…, limit=…)` — e.g.
  `query_graph(epistemic_state="grounded")` for the grounded claims, or
  `query_graph(relation="attacked_by")` to enumerate adversarial edges and the nodes they touch. Every filter
  applies to both nodes and edges. The claims are the edges: the extractor's nodes are never verdicted, so a
  state filter returns few nodes. Node types are
  `compression | primitive | claim | metric | operation | failure`; relations are
  `grounds | attacked_by | reconciles_with | bridges | collapses_into | confounded_by | approximates | defends_against | projects | survives | enables`.
- `mcp__plugin_burgess_burgess__get_node(node_id)` — one node plus its incident edges (use slug IDs, e.g. `compression`).
- `mcp__plugin_burgess_burgess__get_neighbors(node_id, relation=…)` — incident edges, optionally one relation.
- `mcp__plugin_burgess_burgess__shortest_path(source, target)` — `{path: [node_ids] | null}` over the derived graph.
  A path is a *structural* connection only; it is **not** evidence the chain of claims is grounded.
- `mcp__plugin_burgess_burgess__kg_explain_path(nodes)` — the associative chain connecting `nodes`
  over **grounded edges only** → `{path[], edges[{source,target,relation,span}], leap, grounded_only, reason?}`.
  Unlike `shortest_path`, every hop here has actually been verified; `leap` (= path length) is an **advisory**
  creative-distance signal, never a verdict. Empty `path`/`leap=null` with a `reason` when the only connection
  runs through unverified/hypothesized links — say so honestly rather than implying a grounded chain exists.
  **Pass at most 32 distinct nodes**: the cost is quadratic in that count, so beyond the cap the tool refuses
  in the same empty shape (`reason: "too many nodes: N (max 32)"`) rather than stalling the engine. If a
  question seems to need more, it is really several narrower questions.

### 3. Answer with provenance attached
For every edge you cite, surface its axes inline. A compact convention:

> `compression --grounds--> claim`  **[span-present / grounded]** — "*A compression that survives specific
> attack is said to*"

Rules:
- The bracket is always `[<provenance> / <epistemic_state>]`. Quote the `span` verbatim when the edge has one
  (never paraphrase a span — it is a literal substring of the configured source,
  `${user_config.source_path}`, §1.5).
- Lead with `grounded` edges. Flag `unverified` edges as **candidates, not facts**. Flag `inferred` /
  `hypothesized` provenance explicitly.
- `epistemic_state` is the verdict; `authored_by` only says who wrote the claim. An extractor's edge stays
  `authored_by: agent` for life. Once `/kg-ground` grounds it, a grounder has judged it against the source,
  and it is a grounded fact like any other. Don't hedge a grounded edge for its author, and don't look for a
  second verdict elsewhere: the read tools carry none, and the answer needs none.

### 4. Always report the falsification counters
Close with the negative information, even if the count is zero:

> **Falsification counters:** `failed_or_rejected_edges = <n>` — rejected/failed edges are kept as negative
> information (§1.7) and are never pruned. A non-zero count means the graph remembers claims it refuted.

If the question touches a node that has incident `failed`/`rejected` edges (check via `get_node` /
`query_graph(epistemic_state="failed")`), name them — a claim that `collapses_into` a known failure is
rejected on sight (§1.7).

### 5. Present the structural-bridge advisory — clearly LABELLED
If `advisory.nodes` is non-empty and relevant, present it under an explicit heading, never as fact:

> **Advisory (heuristic, NOT a guarantee):** structural-bridge signal flags `betweenness`, `compression`
> (by degree). Per the engine: "*advisory heuristic, not a guarantee*." Degree is the honest MVP proxy that
> `approximates` importance; specificity-weighted betweenness is **gated until validated** (§1.6), so do not
> treat these as confirmed bridges.

## Worked shape (from examples/source.md)
For a question like *"What grounds a compression?"*:

1. `kg_context(query="grounds compression")` → an item such as
   `{source:"specificity", target:"compression", relation:"attacked_by", provenance:"span-present", epistemic_state:"unverified", span:"a more specific claim, when it holds, defeats a vaguer one"}`.
2. Answer:
   - `specificity --attacked_by--> compression` **[span-present / unverified]** — candidate, not yet a verdict.
   - If a `grounds` edge is present and `grounded`, that is the fact to lead with.
3. **Falsification counters:** `failed_or_rejected_edges = 0`.
4. **Advisory (heuristic, NOT a guarantee):** structural-bridge nodes by degree, if any.

Keep the answer tight and §-referenced. The deliverable is a **grounded** answer: every claim tagged with its
provenance and epistemic state, failures surfaced, and the bridge advisory labelled as a heuristic.
