---
description: Grounding's second function — build a second reading of a source as a second construction and cross-generate (ensemble §9) the edges it wrote that the graph lacks, each with the passage it was read from. The only mechanism that attacks coverage; only passages in the graph's own sources can ground.
argument-hint: "[second_source_or_graph_json]"
allowed-tools: Task, mcp__plugin_burgess_burgess__kg_perturb_plan, mcp__plugin_burgess_burgess__kg_generate, mcp__plugin_burgess_burgess__kg_propose, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__kg_metrics
---

# /burgess:kg-perturb — perturbation & exo cross-generation (PLAN Stage 7; §9 / §15)

Every other generator is **endo**: it elaborates the graph using the graph's own structure, so it can only
ever surface what the current construction already implies. `/burgess:kg-perturb` is the **exo** move (§9): it
builds a *second construction* of the same territory — a second reading of one of the graph's own sources, a
document outside them, or a pre-built `graph.json` — and cross-generates against it (the `ensemble`
mechanism). Each candidate is an edge the second construction wrote between two nodes the graph does not
join, with its relation, its direction and the passage it was read from: precisely the connections the
graph's own dynamics would resist.

This is the **only** mechanism that *attacks coverage* rather than elaborating within it. Be honest about
its two limits:
- **A second construction relocates the blind spot; it does not eliminate it.** You trade your
  construction's blind spots for a different set.
- **The grounder judges against the graph's own sources only.** A candidate whose passage lies in them can be
  grounded on that passage. One read from a document outside them cannot, however true it is: to make such a
  document count, add it to the sources and run `/burgess:kg-build`. So re-reading one of the graph's own
  sources gives a second opinion on its extraction, and an outside document mainly previews what it would
  connect.

Arguments, as typed (optional): `$ARGUMENTS`. The whole line is one path, without any surrounding quotes:
a **second source document** to build into a second construction, or an already-built **`graph.json`** to
cross against. If omitted, perturb the current construction in place (a re-partition), which degrades to
`regroup`.

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

## Step 0 — confirm a primary graph exists

Call `mcp__plugin_burgess_burgess__kg_context(budget=2000)`. If empty, tell the user to run
`/burgess:kg-build` → `/burgess:kg-ground` (and optionally `/burgess:kg-generate`) first, and stop.

## Step 1 — obtain the SECOND construction (KEY-FREE, in-session)

The second construction is built **in-session by a `kg-extractor` subagent** through the same span-verified
`kg_write` boundary `/burgess:kg-build` uses — just routed to a **separately-named alternate canon** under
`<project>/.kg/constructions/<slug>/`. **No `ANTHROPIC_API_KEY` and no `backend` extra are needed** — the
session does the language work, the engine only validates + stores (§2.2, the "LLM is the session" model).

Classify that path with `mcp__plugin_burgess_burgess__kg_perturb_plan(arguments="$ARGUMENTS")`, passing the
typed line verbatim: the engine strips the quotes, resolves a relative path against the project and checks the
file exists. This step needs no shell (0.28.0). Through 0.27.0 it was a Bash block, and under the setting
`permissions.blockReadsOutsideWorkingDirectories` Claude Code asks the person before a block its parser cannot
analyse (a `case`, a `${…}`); in the end-to-end run of 2026-11-25 both tries were refused and the session
classified the path by hand.

- **`ok: false`** → the path names no file. Tell the user what `error` says, and stop: nothing is built.
- **`mode: "graph"`** → skip to Step 2 with `second_graph="<second_graph>"` (the pre-built escape hatch, §11).
- **`mode: "source"`** → launch **kg-extractor** (Task) to build the named construction, then go to Step 2 with
  `second_construction="<construction>"`. The extractor writes the second source's nodes/edges via
  `kg_write(..., construction="<construction>", source="<second_source>")` — spans verified against the SECOND
  source, landing in that construction's own canon, key-free. `sections` is how many sections it has, and
  `own_source` says whether the file is one of the graph's own sources: a second reading of it gives a second
  opinion on its extraction, while an outside document mainly previews what it would connect.
- **`mode: "degrade"`** (no argument) → skip the second construction; `kg_generate` **degrades to `regroup`**
  (a re-partition of the current construction). Surface this as a one-line note and continue — never block.

Exact Task invocation for `mode: "source"` (substitute the plan's `construction`, `second_source` and
`source_file`):

```
Task(
  subagent_type: "kg-extractor",
  description: "Build second construction",
  prompt: """
Build a SECOND CONSTRUCTION of a source document into a NAMED alternate canon (NOT the primary graph),
section by section. Get each section from
  mcp__plugin_burgess_burgess__kg_section(source_file="<source_file>", section=<n>, construction="<construction>", source="<second_source>")
starting at section 1; its `of` says how many sections the document has. Its `text` is your section: extract
from it and nothing else, and cite spans only from it. Its `known_nodes` are the PRIMARY graph's nodes the
section names: for the same concept, write the graph's id (your contract's rules for known nodes hold), and
declare that node in `nodes[]` with a label and body from your text, since the construction is a separate
canon.

On EVERY mcp__plugin_burgess_burgess__kg_write call, pass these two extra arguments so the write is routed
to the second construction (they are the whole point — without them you would overwrite the primary graph):
  construction: "<construction>"
  source: "<second_source>"
Set each edge's `source_file` to "<source_file>". Follow your full system contract: declared
pack node_types/edge_types only; every non-deterministic edge carries a verbatim `span` that is a substring
of the section text (§1.5); never set a verdict (epistemic_state stays `unverified`) and never authored_by
`human`. Emit one `complete: true` payload per section and report the dispositions per section, then a final
node/edge tally.
"""
)
```

The ensemble step pairs the two constructions by node id alone, so the known nodes are what let it compare
them: in the field test of 2026-11-16 a second reading that saw none gave 13 of its 39 nodes an id the graph
had, and only 4 of its 22 edges could be compared. A second reading the same day, which saw them, gave all 20
of its nodes the graph's id; its 10 edges all repeated the graph's own (9 grounded, 1 a known failure), so it
proposed nothing. A source the graph was built from mostly confirms its extraction.

After the extractor finishes, sanity-check the build landed (its reported ACCEPTED counts are non-zero). If
it wrote **nothing**, tell the user the second source yielded no anchored structure and either fix the source
or fall back to `mode: "degrade"` — do not proceed on an empty construction (Step 2 would then degrade to
`regroup` anyway, with a note saying so).

**Also verify nothing leaked into the PRIMARY graph.** Routing depends on the extractor passing
`construction=`/`source=` on *every* `kg_write`; a single omitted pair writes into the real canon instead.
Counts cannot show it. The second reading writes the graph's own ids and declares those nodes with a label and
body of its own, so such a write does not grow the primary: it rewrites the labels and bodies of nodes the
graph already has, without changing any count. So, before launching the extractor, call
`mcp__plugin_burgess_burgess__kg_metrics(digest=true)` and keep its counts and its `canon_digest`, a hash of
every note in the canon; when the extractor returns, call it again. Counts and digest must both be
**unchanged** — the whole build lands in the construction's own canon. This check needs no Bash: do not hash
or list the canon yourself. If either moved, the primary canon changed while the second construction was
built, through a write that lost its routing or another session writing the graph at the same time. Stop
before Step 2, tell the user, and do **not** ground. The engine keeps no earlier copy of a note, so only the
user's own version control or backup can bring one back.

## Step 2 — cross-generate (ensemble §9)

- **`mode: "source"`** → `mcp__plugin_burgess_burgess__kg_generate(mechanism="ensemble", second_construction="<construction>", k=10)`.
  The engine projects the named construction's alternate canon in-session (key-free) and cross-generates.
- **`mode: "graph"`** → `mcp__plugin_burgess_burgess__kg_generate(mechanism="ensemble", second_graph="<second_graph>", k=10)`.

Either returns hypothesized candidates, each rationale carrying `perturbation=external`: the edges the second
construction wrote between two nodes not adjacent in ours, each with its relation, its direction and
`passage`, the span it was read from. `passage.in_source` says whether that span is in the graph's own
sources, the only text a grounder judges against; `passages` counts both kinds, and `note` says when some lie
outside them. A pre-built graph whose edges record no relation gives plain `bridges` with no passage. With no
second construction (`mode: "degrade"`, or a construction that built empty), the same call returns the
`regroup` degrade (its `note` says so) — still useful, but internal, not coverage-attacking.

With a second construction the payload also carries `ensemble`: how each of its live edges fared, the parts
summing to `edges`. `ends_missing` counts edges with an end the graph does not have, which could not be
compared; `repeated`, edges the graph already has (the two readings agree); `joined_otherwise`, edges whose
pair the graph joins by another edge (a disagreement ensemble does not propose); `untyped`, edges that record
no relation; `known_failures`, with their ids in `known_failure_ids`, edges failure memory refuses; and `new`,
what ensemble proposes, before its top-`k` cut. When none is new, `note` says why. Report the outcome from these
fields; never re-derive it from the canon by hand.

## Step 3 — phrase & write to the hypothesized lane (Task → kg-generator)

If `count` is 0, skip this step and go to Step 4: there is nothing to phrase or propose.

Launch **kg-generator** with the candidates. Instruct it to mark each proposal as **imported structure**:
carry `perturbation=external` into the `notes`, so the slate is legible as cross-construction structure
rather than internal elaboration. It writes through `mcp__plugin_burgess_burgess__kg_propose`
(hypothesized/unverified, no span — never a verdict), and passes each candidate's `passage` on: `kg_propose`
keeps a passage that holds in the graph's sources and drops one that does not, and `kg_ground_item` later
shows the grounder the one it kept.

```
Task(subagent_type: "kg-generator", description: "Phrase exo edges", prompt: """
  Candidates from kg_generate(ensemble): <paste candidates[]>. Phrase each as one falsifiable sentence,
  keeping source/target/relation verbatim, copy each candidate's `passage` onto its edge unchanged, and tag
  each note with `perturbation=external` (imported from a second construction, not internal elaboration).
  Assemble ONE kg_propose payload (provenance=hypothesized, NO span, NO verdict) and call it. Report
  dispositions, `passages`, and the phrased slate.
""")
```

## Step 4 — report the perturbation slate

Present the ranked slate (mechanism `ensemble`, one-sentence idea, specificity, and whether its
passage is in the graph's sources), flagged as **imported external structure**, then
`mcp__plugin_burgess_burgess__kg_metrics` (the new hypothesized candidates land under `unverified`). From
`kg_propose`'s `passages`, say how many proposals carry a passage the grounder will see. From `ensemble`, say
how the second reading's edges fared: how many repeat the graph, how many join a pair it joins another way,
the known failures by id, how many could not be compared, and how many are new. With `count` 0, that and the
digest check are the whole report. State the caveat
explicitly: *perturbation relocates the blind spot; it does not eliminate it.* For a passage outside your
sources, say plainly that the grounder cannot see it, so that edge will be rejected unless your sources state
it too; to make the document count, add it to the sources and run `/burgess:kg-build`. Then point at
`/burgess:kg-ground` as the filter — a cross-construction edge earns `grounded` only by a span or citation,
else it joins failure memory and binds the next generation.

## Invariants this command upholds

- Exo candidates are written `hypothesized`/`unverified`, in the separate lane, never as grounded fact.
- A passage is context for the grounder, never the proposal's span; only one in the graph's own sources is
  kept, and only the engine writes it into the notes.
- Generation is never gatekept by a metric (the inversion); `/burgess:kg-ground` is the post-hoc filter.
- Failure memory binds even imported structure: a candidate colliding with a known failure is dropped.
- The primary canon is checked by its digest as well as its counts across the second construction's build.
- This command never calls `kg_ground` and never forges a verdict or a span.
