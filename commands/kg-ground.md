---
description: Drain the grounding queue — verdict unverified edges, attack hub candidates, then report verdict counts and falsification memory.
argument-hint: "[query-or-node-filter]"
allowed-tools: Task, mcp__plugin_burgess_burgess__kg_ground_plan, mcp__plugin_burgess_burgess__kg_metrics, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__kg_agenda, mcp__plugin_burgess_burgess__kg_merge
---

# /kg-ground — grounding loop + adversarial grounder + memory of failures (§1.6/§1.7/§1.8, plan Stage 6)

Candidate edges are written `unverified` by `/kg-build`. This command turns them into *grounded knowledge*:
weak edges are rejected, genuinely falsified ones are remembered as negative information, and vague hubs get
attacked. Verdicts are the canonical grounding state and the ONLY way to set one is `kg_ground` (§1.4/§1.8) —
this command never forges a verdict; it dispatches the two grounder subagents and then *reports*.

**This command needs no shell and no file access.** Do not run Bash, do not `Read` or `Grep` the canon, the
source, the plugin's files or saved tool output, and do not write helper scripts: `kg_ground_plan` gives you
the queue in batches, and each grounder fetches its own evidence. In auto mode Claude Code ignores a command's
permission to use Bash, so every shell command would wait on its classifier, or on the user. If a step seems
to need a shell or a file, stop and report it instead of working around it. (Never pull the queue through
`query_graph`: on a real canon it is hundreds of thousands of characters.)

**Arguments, as typed:** `$ARGUMENTS`

An optional focus: a word or a node id (e.g. `betweenness`, `compression`). Pass the line verbatim as
`kg_ground_plan`'s `focus`, which keeps the items touching a node it names. Empty = the whole queue.

## Stage 0 — Plan the pass (read-only)

Find what is actually pending before spending any subagent budget.

1. `mcp__plugin_burgess_burgess__kg_metrics()` → record the baseline `edges_by_epistemic_state` map (keys are the
   `epistemic_state` values: `unverified | grounded | rejected | failed | obsolete`).
2. Call:

   ```
   mcp__plugin_burgess_burgess__kg_ground_plan(
     focus: "<the arguments line above, verbatim; empty if nothing was typed>",
     configured_wave_size: "${user_config.extract_wave_size}"
   )
   ```

   Copy `configured_wave_size` exactly as this text shows it, even if it still reads `${user_config.…}`.
   The plan holds:
   - `batches[]`: the queue, as `{id, kind}` items, one batch per grounder (`batch_size` items, 12 by default).
     It holds every `unverified` edge and every `unverified` HYPOTHESIZED node. A materialized `/kg-diverge`
     pin is such a node, often with **no incident edge at all**, and it is groundable *as a node*: "no edge →
     can't be grounded" is false. The order is already decided: pins, then the other hypotheses, then the
     edges their extractor marked weak, then the rest, each group in source order. Keep it.
   - `queue`: the counts, including `weak_edges` and `extractor_nodes_not_queued`. The extractor's own nodes
     are not queued: each names a concept the text uses, and the claims about it are its edges, which are
     queued. `leads_pending` (0.9.0) counts the leads rejected claims carry that no edge has taken yet: they
     are not this command's work, but `/kg-build --leads`'s.
   - `wave_size` and `wave_size_from`: how many grounders run at once (the `extract_wave_size` option, else 6),
     and `waves`.
   - `hubs[]`: the candidates for Stage 2, the nodes with the most live claims (refuted edges and counter-edges
     do not count). A node an earlier pass attacked, with no claim grounded since, is not among them: it is
     listed in `attacked_hubs` instead, so each pass attacks the next hubs down the list. With a focus, the
     hubs it names are offered even if attacked before: that is how a user asks for a second attack. A hub
     still needs 3 or more live claims, focus or not.
   - `source`: the configured source files, for the adversarial grounder.
3. If `$ARGUMENTS` is non-empty, also call `mcp__plugin_burgess_burgess__kg_context(query="$ARGUMENTS")` and read
   its `advisory` block: `advisory.signal == "structural-bridge"` marks `advisory.nodes[]` as bridges (the
   honest advisory is degree; specificity-weighted betweenness stays GATED until validated, §1.6). Add them to
   the hub candidates, except any the plan lists in `attacked_hubs`.

Stop and report "queue empty — nothing to ground" **only if** the plan has **no** `batches` **and** there are
no hub candidates; when `attacked_hubs` is not empty, add that every hub has been attacked and none has gained
a grounded claim since, and when `queue.leads_pending` is not 0, that that many leads wait for
`/kg-build --leads`. Otherwise tell the user in a line what this pass covers: items, batches, waves and
hubs.

> **Alternative prioritization (optional).** `mcp__plugin_burgess_burgess__kg_agenda()`'s
> `blocked_on_grounding[]` lane is a read-only structural shortlist of what grounding would unblock. You may
> show it beside the plan; it suggests, never grounds. **Convergence** (`/kg-generate` candidates' count of
> distinct mechanisms that proposed the same edge) may be displayed, and only once the harness gate is ON may
> it reorder which batch goes first; it **never** decides a verdict or lets an item skip grounding (G5).

## Stage 0b — Drain stale verdicts (source-staleness advisory, R3)

A grounded/`failed` **span-present** edge's stored `span` is a snapshot taken when it was verdicted. If the
source was later edited so that span no longer appears, the verdict is now resting on text that is gone. The
projector recomputes this off the hot path and surfaces it (read-only — it **never** mutates the verdict):

1. `mcp__plugin_burgess_burgess__kg_context(query="$ARGUMENTS")` → read
   `advisory.stale_verdicts[]`. Each entry is `{edge_id, reason: "span-no-longer-in-source"}`: a grounded or
   `failed` edge whose stored span no longer verifies against its source file. (Empty when nothing diverged —
   the common case; if so, skip to Stage 1.)
2. Route these `edge_id`s to one extra `kg-grounder` launch (the Stage 1 template, with these ids as its batch
   and a line saying they are stale verdicts) to **re-verify against the current source**. Searching the
   configured source files for where the claim moved is the one step where the grounder reads a file:
   - if the claim still holds but the span **moved to new text** → the stored span must be relocated, which is
     a canon edit, so re-emit the edge with the new verbatim span via
     `kg_write({"edges": [{"source": ..., "target": ..., "relation": ..., "span": "<the new verbatim span>"}]})`.
     Do **not** use `kg_ground(..., support_span=...)` for this: `support_span` only supports promoting a
     *hypothesized* item — it is ignored for a span-present edge, so the stored span never moves and the flag
     would persist. The span edit re-opens the edge for grounding, and Stage 1 re-verdicts it against the live
     text.
   - if the source no longer supports it at all → `kg_ground(edge_id, verdict="rejected", note="source no
     longer supports this span")`.
   The advisory is a **heuristic, not a verdict**: the flag clears on the next projection once the edge leaves
   the grounded/`failed` set (re-grounded to `rejected`, or re-opened by the span edit) **or** its stored span
   verifies again — never by editing `epistemic_state` directly to silence it (§1.4/§1.8).

## Stage 0c — Reconsider re-examinable verdicts (R3-mirror — source set changed since judged)

Evidence is non-monotonic: a verdict correct against the source set *at the time it was judged* can become
wrong when the source set later **grows or changes** (sources contradict each other). R3 above catches only
one direction (a span that vanished); this **mirror** catches the other — a `failed`/`rejected` item, **nodes
and span-less items included** (which R3 cannot see), that was judged against a source set that has since
changed, so it may now be supportable and deserves a second look. The grounder queue never re-surfaces
verdicted items on its own, so this is the only place they come back up.

1. `mcp__plugin_burgess_burgess__kg_context(query="$ARGUMENTS")` → read `advisory.reexaminable_verdicts[]`.
   Each entry is `{item_id, kind: "node"|"edge", state: "failed"|"rejected", reason:
   "source-set-changed-since-judged"}`, restricted by a term-overlap filter to items the changed source
   actually mentions. (Empty when the source set has not moved since these items were judged — the common
   case; if so, skip to Stage 1.)
2. For each `item_id`, decide whether the **new** source now supports it, then re-verdict it **only** via
   `kg_ground` — exactly as for a fresh item: promote to `grounded` with real support (a verbatim
   `support_span` for a hypothesized item, else `support_note`), or leave the negative verdict in place. This
   advisory is **strictly read-only**: it changes no `epistemic_state` and enqueues nothing; re-grounding is
   always a manual `kg_ground` decision. The flag self-clears on the next projection once the item leaves the
   `{failed, rejected}` set.

## Stage 1 — Verdict the queue in waves (kg-grounder)

Launch one `kg-grounder` per batch of the plan, **`wave_size` launches in a single message** (so they run in
parallel); wait for that whole wave, then launch the next, until every batch is done. Each grounder fetches
the evidence for its own items with `kg_ground_item` and stamps verdicts with `kg_ground`; `kg_ground` calls
from parallel grounders serialize in the engine, so nothing is lost. **Never paste evidence or rules into a
prompt:** give each grounder its item ids and nothing else. Its contract holds the rules: the relation table
(a precondition is `enables`, never `grounds`), and its rules on tables and on what each node names. A rule
added to one batch's prompt makes that batch judge differently from the others. A rule recalled from an earlier
session may also predate the contract: in 0.8.0's field pass, one told a grounder the pack had no `enables`.

```
Task(
  subagent_type: "kg-grounder",
  description: "Ground batch 1 of 14",
  prompt: """
You are grounding ONE batch of the grounding queue (focus: <the focus, or none>).

items:
- e_generality-confound__attacked-by__specificity (edge)
- e_span-present__grounds__claim (edge)

For each item, call mcp__plugin_burgess_burgess__kg_ground_item(target_id: "<id>", kind: "<edge|node>") and
judge it from what it returns: the edge and its span, span_in_source, its two nodes, and the context excerpt
of the source. Do not read files. Then apply ONE verdict with
mcp__plugin_burgess_burgess__kg_ground(target_id, verdict, kind, note, lead), per your contract:
  - grounded: span_in_source is true, the excerpt shows the span stating THIS relation in this direction,
    between what the two nodes name, as your contract's relation table defines it, and the relation is
    specific and falsifiable. A table row states a relation when the table's header says what its cells are.
  - rejected: span_in_source is false; the span does not state the relation (a bare label, a cell its
    header relates to nothing, or its opposite); it states another relation, such as a precondition
    (`enables`) filed as `grounds` (note reason `wrong-relation`); it states the relation for a concept
    narrower or broader than one of the nodes (`wrong-node`); or the edge is true only by being vague
    (`vague`). For `wrong-relation` and `wrong-node`, pass the edge the span does state as kg_ground's
    `lead`: "<head-id> <relation> <tail-id>".
  - a hypothesized item is grounded only with support (a support_span copied from the context, placeholders
    included, or a support_note); a [diverge]-pinned item without support stays unverified.
Do NOT write verdicts into any kg_write payload (§1.4: forged verdicts are stripped/DEMOTED); kg_ground is the
only verdict channel. Report a per-item table: id, kind, verdict, reason.
"""
)
```

The kg-grounder owns `kg_ground`; this command does not call it. Verdicts persist in the canon and survive a
full reproject because the reconciler re-attaches them (§1.8).

**Progress probe.** Between waves, or after a hiccup, call `kg_ground_plan` again with the same two arguments:
an item drops out of it once it has a verdict, so its `batches` are exactly the work left. Re-launch only
those. An item a grounder deliberately left `unverified` (a `[diverge]` pin with no support) stays in the plan:
do not re-launch it, report it.

## Stage 2 — Attack the hubs (kg-adversarial-grounder)

After the last wave returns, take the hub candidates from the **last progress probe** (its `hubs[]`, computed
once the claims are verdicted, so a rejected claim no longer counts) plus any Stage 0 advisory nodes not in
its `attacked_hubs`. If there are none, skip this stage and say why: no node has 3 live claims, or every one
that has was attacked with nothing grounded since (it is in `attacked_hubs`). Otherwise launch the
`kg-adversarial-grounder` over them. For each hub it
constructs the strongest counter-edges and falsifying questions, emits them as typed `attacked_by` edges (the
declared edge type — see `pack/pack.yaml`), and marks any existing claim it genuinely falsifies as `failed`.
This is bounded by a per-run cap so a vague hub cannot spawn unbounded attacks, and the mark on each
counter-edge keeps a later pass from attacking the same hub again before it gains a new grounded claim. A hub
it attacks without writing a counter-edge gets the same mark from `kg_record_attack` (0.10.0); through 0.9.0
such a hub was offered again on every pass.

```
Task(
  subagent_type: "kg-adversarial-grounder",
  description: "Attack hub candidates",
  prompt: """
    Hub candidates: <the last probe's hubs[] ids, plus the advisory nodes>.
    Source files to search for counter-spans: <the plan's source.files>, in <source.path>.
    For each hub, inspect its incident edges (get_neighbors, then kg_ground_item for one edge's span and
    excerpt) and generate the strongest falsifying counter-edges:
      1. Write attacked_by counter-edges (relation: attacked_by) via the extraction/kg_write path, each
         carrying a VERBATIM span from those source files (§1.5 — no span => REJECTED), with its file's
         basename as source_file, and notes opening with `counter-edge (adversarial pass, hub <hub-id>)`.
      2. For any existing edge your counter genuinely refutes, call
         kg_ground(target_id=<edge_id>, verdict="failed", note=<what refuted it>) on THAT edge, never on
         your own counter-edge, which stays unverified for the next pass's grounders.
      3. For each hub where kg_write accepted no counter-edge, record the attack with
         kg_record_attack(hub_id=<hub-id>, question=<your falsifying question>, reason=<no-span|vague>).
    Write a counter-edge only when its span, in its own context, sets itself against the claim it attacks.
    A contradiction that no single span states goes in your report, not into an edge.
    Respect the per-run attack cap. A `failed` edge is negative information (§1.7): never pruned,
    surfaced later as a falsification counter. Report: counter-edges written, edges failed, each hub you
    attacked without a counter-edge and whether you recorded it, and the contradictions no single span
    states.
  """
)
```

`failed` and `rejected` edges are NEGATIVE INFORMATION (§1.7) — never pruned, and surfaced in `kg_context` as
falsification counters. That is the whole point of the memory-of-failures layer: falsification grounds trust
as much as confirmation (source §4).

## Stage 3 — Report (read-only)

Both subagents have applied verdicts. Re-read the engine and present the delta — do NOT re-verdict anything.

1. `mcp__plugin_burgess_burgess__kg_metrics()` → show the new `edges_by_epistemic_state`. Print a before/after diff
   against the Stage 0 baseline for `unverified` (should drop), `grounded`, `rejected`, and `failed`.
2. `mcp__plugin_burgess_burgess__kg_context(query="$ARGUMENTS")` → read `falsification_counters` and report
   `falsification_counters.failed_or_rejected_edges` as the size of the negative-information memory. Also note
   `approx_tokens` vs `budget` if context was requested for downstream use.

Render a summary like:

```
Grounding pass complete.
  queue drained : unverified  N → M
  verdicts      : grounded +g, rejected +r, failed +f
  memory        : falsification_counters.failed_or_rejected_edges = K  (never pruned, §1.7)
  hubs attacked : <hub list> → C attacked_by counter-edges, R recorded with none
```

For each hub attacked without a counter-edge, give its falsifying question: it is for a human, and its
record keeps the hub out of the next plan until the hub gains a newer grounded claim.

Then list the leads the grounders named for an extractor: for each `wrong-relation` rejection, the relation its
span does state (a precondition filed as `grounds` is an `enables` edge from the same span), and for each
`wrong-node` rejection, the concept its span names. Each lead is recorded on its rejected edge (0.9.0), and the
last probe's `queue.leads_pending` counts the ones no edge has taken yet: tell the user that `/kg-build --leads`
writes them, as unverified edges with the same span, and that the next `/kg-ground` judges them. This command
writes no edge itself.

## §Stage 6 — Merge checkpoint (NON-BLOCKING)

If either grounder reports a genuinely ambiguous node merge (two nodes that may be the same concept), surface
exactly ONE elicitation and do not block the pass:

```
Merge A and B? [y/N]
```

Default is **N** (keep the nodes separate) after a brief wait — proceed without merging unless the human
explicitly answers `y`. If accepted, perform the merge with **`kg_merge(from_id, into_id)`** — the
deliberate node-merge tool: it rewrites + dedups the colliding edges (negative information stays sticky,
`grounded` beats `unverified`, no verdict is forged) and re-keys any surviving verdict so the reconciler
(§1.8) does not re-quarantine it. (`kg_rename` will NOT do this — it refuses a target-id collision.)

## Invariants this command upholds

- It runs no shell command and reads no file: `kg_ground_plan` plans the pass, each grounder fetches its
  evidence with `kg_ground_item`, and the verdicts go through `kg_ground`.
- It NEVER calls `kg_ground` itself and NEVER forges a verdict in a write payload (§1.4/§1.8). Verdicts come
  only from the two grounder subagents via `kg_ground`.
- It gives each grounder its item ids and nothing else: the rules are in the grounders' contracts, which every
  batch reads alike (0.8.1).
- It uses only the declared vocabulary: edge type `attacked_by`, `epistemic_state` values
  `unverified|grounded|rejected|failed`, verdict reason `vague` for generality-confound rejections (§1.6).
- An unfocused pass attacks each hub once until the hub gains a grounded claim: the counter-edges carry the
  hub's mark, and the plan leaves an attacked hub out of `hubs[]` (0.8.0). So the passes end; through 0.7.0
  every pass attacked the same hubs again and left new unverified counter-edges behind.
- Rejected and failed edges are kept forever and reported as `falsification_counters.failed_or_rejected_edges`
  (§1.7); this command surfaces that count rather than pruning anything.

## Materialized pins go first (FUSION Stage 4 — ordering only)

`kg_ground_plan` puts the edges/nodes whose notes/body carry the `[diverge] pinned` lineage
marker at the front of the queue — the human explicitly selected these ideas, so they earn it. Note the shape: a materialized pin is a
hypothesized **node** (`kg_diverge_materialize` writes one node per pin; any `edges` are
optional extras), so a pin **routinely has no incident edge** — and is nonetheless
groundable *as a node* via `kg_ground(kind="node")`. **"No edge → can't be grounded" is false.**
This is PURELY an ordering preference: the verdict logic is identical for pinned and unpinned
items (verdict neutrality is test-enforced), a pin never lowers the evidence bar, and promotion
still requires support (span or citation, restated into the node body) like any hypothesis.

Because a materialized pin is a *novel* idea, grounding it against the current source will
usually find no in-source span — that is the expected outcome, **not** a failure. So the
grounder **leaves an unsupported `[diverge]`-lineage node (or edge) `unverified`** (triage: don't
spend a rejection on an item that by construction has no span yet) rather than rejecting it. Only a pin
that is actively **FALSIFIED** (`failed`, the adversarial grounder's verdict) folds back into its
/kg-diverge brief's **permanent** discards; a merely-unsupported (`rejected`) pin stays recoverable
in the lane until sources are added. Ordinary `/kg-generate` proposals (no `[diverge]` marker) are
unchanged: unsupported → `rejected` → failure memory.
