---
description: Grounding's second function — build a second reading of a source as a second construction and cross-generate (ensemble §9) the edges it wrote that the graph lacks, each with the passage it was read from. The only mechanism that attacks coverage; only passages in the graph's own sources can ground.
argument-hint: "[second_source_or_graph_json]"
allowed-tools: Task, Bash, mcp__plugin_burgess_burgess__kg_generate, mcp__plugin_burgess_burgess__kg_propose, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__kg_metrics
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

## Step 0 — confirm a primary graph exists

Call `mcp__plugin_burgess_burgess__kg_context(budget=2000)`. If empty, tell the user to run
`/burgess:kg-build` → `/burgess:kg-ground` (and optionally `/burgess:kg-generate`) first, and stop.

## Step 1 — obtain the SECOND construction (KEY-FREE, in-session)

The second construction is built **in-session by a `kg-extractor` subagent** through the same span-verified
`kg_write` boundary `/burgess:kg-build` uses — just routed to a **separately-named alternate canon** under
`<project>/.kg/constructions/<slug>/`. **No `ANTHROPIC_API_KEY` and no `backend` extra are needed** — the
session does the language work, the engine only validates + stores (§2.2, the "LLM is the session" model).

Classify that path (a tiny Bash step — no runner/venv needed). Write it in place of `__SECOND__`, inside the
double quotes, or leave the quotes empty when no argument was given. A placeholder left as it is stops the
step, so a forgotten substitution can never pass for "no second source":

```bash
SECOND="__SECOND__"   # the path from the arguments, without quotes; "" when there is none
case "$SECOND" in (__*__) echo "the path from the arguments was not filled in above (or leave the quotes empty)"; exit 1 ;; esac
if [ -z "$SECOND" ]; then
  echo "MODE=degrade"                       # no second source → ensemble degrades to regroup
elif [ "${SECOND##*.}" = "json" ]; then
  echo "MODE=graph"; echo "SECOND_GRAPH=$SECOND"   # a pre-built graph.json → use it directly (§11)
else
  # a second SOURCE document → derive a stable construction NAME from its basename
  NAME=$(basename "$SECOND"); NAME="${NAME%.*}"
  # POSIX BRE (`*`, not the GNU `\+` extension — BSD/macOS sed treats `\+` as a literal `+`, so the
  # basename would not be cleaned there). The engine's _construction_slug re-slugs identically anyway,
  # so this only keeps the echoed NAME clean and portable.
  NAME=$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-][^a-z0-9._-]*/-/g; s/^[-_.][-_.]*//; s/[-_.][-_.]*$//')
  [ -n "$NAME" ] || NAME="second"
  echo "MODE=source"; echo "CONSTRUCTION=$NAME"; echo "SECOND_SOURCE=$SECOND"
fi
```

- **`MODE=graph`** → skip to Step 2 with `second_graph="$SECOND_GRAPH"` (the pre-built escape hatch).
- **`MODE=source`** → launch **kg-extractor** (Task) to build the named construction, then go to Step 2 with
  `second_construction="$CONSTRUCTION"`. The extractor writes the second source's nodes/edges via
  `kg_write(..., construction="$CONSTRUCTION", source="$SECOND_SOURCE")` — spans verified against the SECOND
  source, landing in that construction's own canon, key-free.
- **`MODE=degrade`** (no argument) → skip the second construction; `kg_generate` **degrades to `regroup`**
  (a re-partition of the current construction). Surface this as a one-line note and continue — never block.

Exact Task invocation for `MODE=source` (substitute `$CONSTRUCTION` and `$SECOND_SOURCE`):

```
Task(
  subagent_type: "kg-extractor",
  description: "Build second construction",
  prompt: """
Build a SECOND CONSTRUCTION of a source document into a NAMED alternate canon (NOT the primary graph),
section by section. Get each section from
  mcp__plugin_burgess_burgess__kg_section(source_file="<the basename of $SECOND_SOURCE>", section=<n>, construction="$CONSTRUCTION", source="$SECOND_SOURCE")
starting at section 1; its `of` says how many sections the document has. Its `text` is your section: extract
from it and nothing else, and cite spans only from it. Its `known_nodes` are the PRIMARY graph's nodes the
section names: for the same concept, write the graph's id (your contract's rules for known nodes hold), and
declare that node in `nodes[]` with a label and body from your text, since the construction is a separate
canon.

On EVERY mcp__plugin_burgess_burgess__kg_write call, pass these two extra arguments so the write is routed
to the second construction (they are the whole point — without them you would overwrite the primary graph):
  construction: "$CONSTRUCTION"
  source: "$SECOND_SOURCE"
Set each edge's `source_file` to the basename of $SECOND_SOURCE. Follow your full system contract: declared
pack node_types/edge_types only; every non-deterministic edge carries a verbatim `span` that is a substring
of the section text (§1.5); never set a verdict (epistemic_state stays `unverified`) and never authored_by
`human`. Emit one `complete: true` payload per section and report the dispositions per section, then a final
node/edge tally.
"""
)
```

The ensemble step pairs the two constructions by node id alone, so the known nodes are what let it compare
them: in the field test of 2026-11-16 a second reading that saw none gave 13 of its 39 nodes an id the graph
had, and only 4 of its 22 edges could be compared.

After the extractor finishes, sanity-check the build landed (its reported ACCEPTED counts are non-zero). If
it wrote **nothing**, tell the user the second source yielded no anchored structure and either fix the source
or fall back to `MODE=degrade` — do not proceed on an empty construction (Step 2 would then degrade to
`regroup` anyway, with a note saying so).

**Also verify nothing leaked into the PRIMARY graph.** Routing depends on the extractor passing
`construction=`/`source=` on *every* `kg_write`; a single omitted pair silently writes second-source
structure into the real canon, where it would later be grounded as native. Before Step 1, record the
primary node/edge counts (`mcp__plugin_burgess_burgess__kg_metrics()` / `kg_status()`); after the extractor
returns, re-read them. The primary counts must be **unchanged** — the whole build lands in the construction's
own canon. If the primary grew, the extractor dropped the routing args on some section: tell the user, and do
**not** ground until the leaked primary nodes/edges are identified (they are `unverified`, so a subsequent
`/burgess:kg-ground` is the backstop, but flag it explicitly rather than absorbing them silently).

## Step 2 — cross-generate (ensemble §9)

- **`MODE=source`** → `mcp__plugin_burgess_burgess__kg_generate(mechanism="ensemble", second_construction="$CONSTRUCTION", k=10)`.
  The engine projects the named construction's alternate canon in-session (key-free) and cross-generates.
- **`MODE=graph`** → `mcp__plugin_burgess_burgess__kg_generate(mechanism="ensemble", second_graph="$SECOND_GRAPH", k=10)`.

Either returns hypothesized candidates, each rationale carrying `perturbation=external`: the edges the second
construction wrote between two nodes not adjacent in ours, each with its relation, its direction and
`passage`, the span it was read from. `passage.in_source` says whether that span is in the graph's own
sources, the only text a grounder judges against; `passages` counts both kinds, and `note` says when some lie
outside them. A pre-built graph whose edges record no relation gives plain `bridges` with no passage. With no
second construction (`MODE=degrade`, or a construction that built empty), the same call returns the
`regroup` degrade (its `note` says so) — still useful, but internal, not coverage-attacking.

## Step 3 — phrase & write to the hypothesized lane (Task → kg-generator)

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

Present the ranked slate (mechanism `ensemble`, § = §9, one-sentence idea, specificity, and whether its
passage is in the graph's sources), flagged as **imported external structure**, then
`mcp__plugin_burgess_burgess__kg_metrics` (the new hypothesized candidates land under `unverified`). From
`kg_propose`'s `passages`, say how many proposals carry a passage the grounder will see. State the caveat
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
- This command never calls `kg_ground` and never forges a verdict or a span.
