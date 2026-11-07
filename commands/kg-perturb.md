---
description: Grounding's second function — import EXTERNAL structure the graph's own dynamics would resist, build it as a second construction, and cross-generate (ensemble §9) to surface bridges that exist across constructions. The only mechanism that attacks coverage.
argument-hint: "[second_source_or_graph_json]"
allowed-tools: Task, Bash, mcp__plugin_burgess_burgess__kg_generate, mcp__plugin_burgess_burgess__kg_propose, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__kg_metrics
---

# /kg-perturb — perturbation & exo cross-generation (PLAN Stage 7; §9 / §15)

Every other generator is **endo**: it elaborates the graph using the graph's own structure, so it can only
ever surface what the current construction already implies. `/kg-perturb` is the **exo** move (§9): it
builds a *second construction* of the same territory — the same source under a different pack/resolution, or
a second source entirely — and cross-generates against it (the `ensemble` mechanism). The candidates it
emits are bridges that exist in one construction's structure but **not** the other's: precisely the
connections the graph's own dynamics would resist.

This is the **only** mechanism that *attacks coverage* rather than elaborating within it. Be honest about
its limit (the ensemble caveat): a second construction does not eliminate the blind spot — it **relocates**
it. You trade your construction's blind spots for a different set, and the bridges that survive both are the
ones worth grounding.

Arguments, as typed (optional): `$ARGUMENTS`. The whole line is one path, without any surrounding quotes:
a **second source document** to build into a second construction, or an already-built **`graph.json`** to
cross against. If omitted, perturb the current construction in place (a re-partition), which degrades to
`regroup`.

## Step 0 — confirm a primary graph exists

Call `mcp__plugin_burgess_burgess__kg_context(budget=2000)`. If empty, tell the user to run
`/kg-build` → `/kg-ground` (and optionally `/kg-generate`) first, and stop.

## Step 1 — obtain the SECOND construction (KEY-FREE, in-session)

The second construction is built **in-session by a `kg-extractor` subagent** through the same span-verified
`kg_write` boundary `/kg-build` uses — just routed to a **separately-named alternate canon** under
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
Build a SECOND CONSTRUCTION of a different source document into a NAMED alternate canon (NOT the primary
graph). `Read` the whole file at path: $SECOND_SOURCE  (this is the direct-invocation whole-file path —
read it off disk, then work section by section, one `##` section per payload).

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
`/kg-ground` is the backstop, but flag it explicitly rather than absorbing them silently).

## Step 2 — cross-generate (ensemble §9)

- **`MODE=source`** → `mcp__plugin_burgess_burgess__kg_generate(mechanism="ensemble", second_construction="$CONSTRUCTION", k=10)`.
  The engine projects the named construction's alternate canon in-session (key-free) and cross-generates.
- **`MODE=graph`** → `mcp__plugin_burgess_burgess__kg_generate(mechanism="ensemble", second_graph="$SECOND_GRAPH", k=10)`.

Either returns hypothesized candidate bridges that are adjacent in the second construction but absent in ours
(each rationale carries `perturbation=external`). With no second construction (`MODE=degrade`, or a
construction that built empty), the same call returns the `regroup` degrade (its `note` says so) — still
useful, but internal, not coverage-attacking.

## Step 3 — phrase & write to the hypothesized lane (Task → kg-generator)

Launch **kg-generator** with the candidates. Instruct it to mark each proposal as **imported structure**:
carry `perturbation=external` into the `notes`, so the slate is legible as cross-construction structure
rather than internal elaboration. It writes through `mcp__plugin_burgess_burgess__kg_propose`
(hypothesized/unverified, no span — never a verdict).

```
Task(subagent_type: "kg-generator", description: "Phrase exo bridges", prompt: """
  Candidates from kg_generate(ensemble): <paste candidates[]>. Phrase each as one falsifiable sentence,
  keeping source/target/relation verbatim, and tag each note with `perturbation=external` (imported from a
  second construction, not internal elaboration). Assemble ONE kg_propose payload (provenance=hypothesized,
  NO span, NO verdict) and call it. Report dispositions + the phrased slate.
""")
```

## Step 4 — report the perturbation slate

Present the ranked slate (mechanism `ensemble`, § = §9, one-sentence idea, specificity), flagged as
**imported external structure**, then `mcp__plugin_burgess_burgess__kg_metrics` (the new
hypothesized candidates land under `unverified`). State the caveat explicitly: *perturbation relocates the
blind spot; it does not eliminate it.* Then point at `/kg-ground` as the filter — a cross-construction bridge
earns `grounded` only by a span/citation, else it joins failure memory and binds the next generation.

## Invariants this command upholds

- Exo candidates are written `hypothesized`/`unverified`, in the separate lane, never as grounded fact.
- Generation is never gatekept by a metric (the inversion); `/kg-ground` is the post-hoc filter.
- Failure memory binds even imported structure: a candidate colliding with a known failure is dropped.
- This command never calls `kg_ground` and never forges a verdict or a span.
