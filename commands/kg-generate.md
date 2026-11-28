---
description: Generate hypothesized idea candidates from the graph's structure (bridge|seed|compression|regroup|transplant|ensemble|periphery), phrase them via the language layer, and write them to the hypothesized lane — then hand off to /burgess:kg-ground as the filter.
argument-hint: "[mechanism-set] [k]"
allowed-tools: Task, mcp__plugin_burgess_burgess__kg_generate, mcp__plugin_burgess_burgess__kg_propose, mcp__plugin_burgess_burgess__kg_operate, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__kg_metrics, mcp__plugin_burgess_burgess__kg_absorption, mcp__plugin_burgess_burgess__kg_record_generation
---

# /burgess:kg-generate — the generative layer (PLAN Stages 3–6)

This is the *generation* half of the system. It turns the grounded graph from a **verification machine**
into an **idea-generation machine** — without weakening one anti-nonsense guarantee. The whole design
rests on **the inversion** (PLAN §1.2): **generate offensively, judge defensively.** Entry into the graph
is NEVER gatekept by a quality metric — every candidate is written `hypothesized`/`unverified`. The
*existing* grounding loop (`/burgess:kg-ground`) is the filter, applied **after**. The portico that used to stand
at the door of imagination is moved to after generation.

**This command needs no shell and no file access.** Do not run Bash, do not `Read` or `Grep` the canon, the
source, the plugin's files or saved tool output, and do not write helper scripts: `kg_generate` gives you the
candidates, the kg-generator reads what its phrasing needs, and `kg_record_generation` records the run. In auto
mode Claude Code ignores a command's permission to use Bash, so every shell command would wait on its
classifier, or on the user. If a step seems to need a shell or a file, stop and report it instead of working
around it. (Through 0.16.1 the ledger of Step 4 needed a shell: the second field run's write waited nine hours
for the user's approval.)

<!-- plain-words:begin (every command holds this block; tests/test_fix_annotators_and_plain_words.py keeps the ten identical) -->
**Talk to the user in plain words (0.29.1).** This text cites the plan's sections (§1.7) and names the engine's
fields and tools (`on_unusable_total`, `kg_merge`) so that you can find them; the user knows none of them. Say
what each one means: «2 grounded claims no longer rest on a usable source», not `on_unusable_total: 2`; «I can
merge the two nodes», not `kg_merge`. Show no plan section (§), in a table either. Keep as they are the commands
to type (`/burgess:kg-ground`), the ids of nodes and edges, file names, a section of the user's document by its
title or its number, the pack's relations and types (`grounds`, `claim`), the states and provenances
(`grounded`, `span-present`), and any reply this text asks the user to type exactly. A log entry keeps the format
its step gives.
<!-- plain-words:end -->

## Advisory DPP ordering (FUSION Stage 5 — `divergence.dpp`, default off)

When the pack sets `divergence: {dpp: true}` (or you pass `dpp: true` to the `kg_generate` tool),
the SAME candidate set comes back reordered by hybrid-descriptor DPP — one semantic axis (batch
embedding novelty) + graph-structural axes (community intra/cross, endpoint graph distance,
grounded-mix of the neighborhood) — with a `divergence_advisory` block: per-candidate niche bins,
semantic novelty, and distance to the graph's "center" (the top grounded hubs, the structural
cliché map — the periphery mechanism and cliché-distance are two views of the same
away-from-center pressure). Present candidates in that order with those labels, exactly like a
/burgess:kg-diverge slate. It is ADVISORY ONLY (I5, snapshot-enforced): same candidates, same scores,
bit-identical grounding downstream; if the advisory layer is unavailable the engine's own
deterministic mechanism ranking is kept and `note` says why.

A generated candidate enters as `provenance=hypothesized`, `epistemic_state=unverified`, **with no span**.
It is a *proposal from a discovery mechanism*, never a text claim — stored in a lane that can never be
mistaken for grounded content. Promotion to `grounded` happens ONLY through `kg_ground`, and only when a
grounder supplies a span or citation (which *upgrades* its provenance) — see `/burgess:kg-query`/`/burgess:kg-ground`.

Arguments, as typed (optional): `$ARGUMENTS`. They hold a mechanism set (`default` | `all` | a single
mechanism name) and an integer `k`, split at spaces; a whole number is `k`, the other word is the set.

## Step 0 — confirm a graph exists

Call `mcp__plugin_burgess_burgess__kg_context(budget=2000)`. If `items[]` **and**
`advisory.bridge_metric.nodes[]` are both empty, there is no graph to generate from — tell the user to run
`/burgess:kg-build` → `/burgess:kg-ground` first, and stop. Otherwise note `advisory.bridge_metric.gate_on` (whether
specificity-weighted betweenness is the trusted bridge signal this projection) and carry it into the report.

## Step 1 — mechanism set (NON-BLOCKING survey, §"Autonomy contract")

Ask the user exactly once, then proceed with the default if they don't redirect:

> **Run the default mechanism set `{bridge, seed, compression}` or all seven? [default/all]** (default: `default`)

- `default` (or no answer and no set in the arguments) → the three default mechanisms.
- `all` → all seven (`bridge, seed, compression, regroup, transplant, ensemble, periphery`). `periphery` (§5)
  sources candidates from the graph's **low-degree** nodes — the periphery the hub-seeking mechanisms ignore.
- a single mechanism name → just that one.

This is a **non-blocking checkpoint**: invite a reply, but never make progress conditional on it. Default
`k=10` unless the arguments give an integer.

## Step 2 — generate the structural candidates (read-only)

Call `mcp__plugin_burgess_burgess__kg_generate(mechanism=<chosen>, k=<k>)` (use
`mechanism="all"` for the full set; it runs the default set on `"default"`). It returns
`{mechanism, k, gate_on, unjudged_hypotheses, count, candidates[], note}`, plus `compression_skipped` when
compression ran. Each candidate carries
`{kind, mechanism, source, target, relation, label, node_type, score, specificity, rationale, section, convergence}`,
and a `kind:"node"` compression also carries `members` (the nodes it collapses) and `id` (the id to write it
under, the one `kg_operate collapse` gives the same members).

Compression never offers a community that a live compression node was already proposed over (at least half
of the other members already have a `collapses_into` edge into it, in any state), nor a candidate whose `id`
is already a node, judged or not. `compression_skipped` lists both: `already_compressed` (those compression
nodes) and `already_proposed` (each existing id, with its state), and `note` names them. So hand the
kg-generator every candidate returned: the engine has already left out what an earlier generation proposed.
(Through 0.16.1 it did not, and the second field run's session dropped two rejected ids by hand.)
`convergence` is **advisory** — the number of *distinct* mechanisms that independently proposed the same edge
(≥1). It is a **ranking prior for the grounding queue** (which hypotheses to ground first), **never** a score,
**never** a verdict, and **never** written onto a canon edge; it does not change the slate's `score`/ranking.
This call is **READ-ONLY** — nothing is written yet. If `count==0`, report that the structure surfaced no
candidates for the chosen mechanisms (the demo graph is small; try `all`, a larger `k`, or `/burgess:kg-perturb`),
and stop. Note the `note` (e.g. ensemble degraded to regroup with no second construction).

If `unjudged_hypotheses` is above 0, earlier proposals are still waiting for `/burgess:kg-ground`. They count as
graph structure, so they shaped the ranks these candidates came from: a second generation feeds on the first.
Before Step 3, tell the user in one line how many there are and that grounding them first gives a slate ranked
on the judged graph. Then go on. It is a warning, not a gate: generation is never gatekept (the inversion).

## Step 3 — phrase & label the candidates (Task → kg-generator)

Launch the **kg-generator** subagent via the **Task** tool, handing it the candidate list. It is the
LANGUAGE layer: it phrases each candidate as a one-sentence idea, supplies a `label`+`body` for proposed
`compression`/`primitive` nodes (whose label is blank by design), and writes the transplant "hidden
commitments to audit" notes (§5). It does **not** invent structure and does **not** set verdicts.

```
Task(subagent_type: "kg-generator", description: "Phrase + label candidates", prompt: """
  Here are the structural candidates from kg_generate: <paste candidates[]>.
  For each: (a) phrase it as one falsifiable sentence keeping source/target/relation verbatim;
  (b) for kind:"node" (compression/primitive) supply a SPECIFIC label + a one-paragraph body whose
  prediction would earn the node its keep (§7), and write a compression as its star: the node under its
  `id`, plus one collapses_into edge from each of its `members` to that id; (c) for transplants, write the
  hidden-commitments-to-audit note (§5). Then assemble ONE kg_propose payload (provenance=hypothesized,
  NO span, NO verdict) and call kg_propose. Report dispositions + the phrased idea slate. Nothing is
  judged — these are hypotheses.
""")
```

The kg-generator owns `kg_propose`; it writes the hypothesized lane. (For purely structural ops —
collapse/explode/regroup/open — you may instead call
`mcp__plugin_burgess_burgess__kg_operate` directly; it also routes through the propose lane.)

## Step 4 — record the generation (for the absorption window, §14)

After the propose call returns, record the run in the absorption ledger so `kg_absorption` can later score
how long each new node stays perturbing (fertile vs absorbed vs isolated). It scores a node once
`/burgess:kg-ground` has grounded it, and lists the others apart with their state.

Call `mcp__plugin_burgess_burgess__kg_record_generation(nodes={"<node id>": "<mechanism>", …})` once, with every
node the kg-generator's `kg_propose` ACCEPTED (its `details`), each mapped to the mechanism of the candidate it
came from, usually `compression`. Call it even when the run wrote no node: the generation counter still
advances, and it is the clock every tracked node's window is read against. The engine records each node at its
live degree in the generation it opens, in the ledger `kg_absorption` reads, and returns
`{ok, generation, tracked, recorded, skipped}`. A `skipped` entry says why (not in the canon, already tracked,
not a proposal); report it, and record nothing by other means.

This step is best-effort — never block the slate on it.

## Step 5 — emit the ranked idea slate + report metrics

Present a ranked **idea slate** to the user, one row per accepted candidate:

```
| # | mechanism | idea (one sentence) | specificity | provenance |
|---|-----------|---------------------|-------------|------------|
| 1 | seed      | Betweenness and memory-of-failures may be abnormally connectable … | 1.83 | hypothesized |
```

Then call `mcp__plugin_burgess_burgess__kg_metrics` and report the new
`edges_by_epistemic_state` — the hypothesized candidates show up under `unverified`. State `gate_on` from
Step 0 (was the slate ranked by the confound-corrected `spec_betweenness` or the honest fallback?). A bridge's
`rationale` names what its strength came from; "neither end is a structural bridge" means the graph has
none, and the pair was ranked by degree weighted by specificity. If `unjudged_hypotheses` was above 0, say
again that this slate was ranked partly on earlier proposals nobody has judged yet. If `compression_skipped`
names anything, say in a line what compression left out and why, and give the generation `kg_record_generation`
recorded.

## Step 6 — the inversion, made explicit

State plainly: **nothing has been judged yet.** Every candidate is `hypothesized`/`unverified`. `/burgess:kg-ground`
now acts as the *filter* over the hypothesized lane — a grounder promotes a candidate to `grounded` ONLY by
supplying a span or external citation (which upgrades its provenance from `hypothesized` to
`span-present`/`inferred`), and rejects the rest into failure memory (§1.7), which then *binds* the next
generation (a candidate that collapses into a known failure is dropped on sight, invariant 5).

Optionally chain into `/burgess:kg-ground` restricted to the freshly-proposed hypothesized lane
(`epistemic_state=unverified, provenance=hypothesized`).

## Invariants this command upholds

- **The hypothesized lane is separate, never privileged.** Candidates are written `hypothesized`, never
  presented as grounded, never carrying a span.
- **Generation is never gatekept by a quality metric** (the inversion) — it always emits and writes; only
  `/burgess:kg-ground` filters, afterward.
- **Generality control travels with every mechanism** (§4): structural rankings are spec-weighted (the
  bridge fallback too, since 0.16.0), the gate decides whether `spec_betweenness` is trusted, compressions
  pass an MDL screen. A `bridge` or `regroup` slate gives no node more than two slots, so one hub cannot take
  the whole slate.
- **Failure memory binds generation** (§13): the engine drops any candidate whose identity (or its
  reverse) already lives in `failed`/`rejected`, and any compression whose id is already a node or whose
  community a live compression node was already proposed over (0.17.0).
- **No shell.** The ledger is the engine's: `kg_record_generation` writes it (0.17.0).
- This command **never** calls `kg_ground` and **never** forges a verdict or a span.
