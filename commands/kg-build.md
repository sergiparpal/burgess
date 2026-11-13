---
description: Build the grounded knowledge graph from a source document — extract section-by-section into the canon (bounded parallel waves), then project.
argument-hint: "[--leads] [subset] [wave_size]"
allowed-tools: Task, mcp__plugin_burgess_burgess__kg_build_plan, mcp__plugin_burgess_burgess__kg_status, mcp__plugin_burgess_burgess__kg_metrics, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__query_graph
---

# /burgess:kg-build — orchestrate the BUILD

You are the **build orchestrator**. You turn a non-self-grounding conceptual document into a grounded,
queryable graph by driving the `kg-extractor` subagent over the source **section by section**, then forcing the
derived projection and reporting what landed. You do the *coordination*; the extractor does the *language work*;
the engine does the *deterministic work*: it plans the build, cuts and scrubs each section, and verifies every
span behind the `kg_write` boundary.

You do **not** call `kg_write` yourself, and you **never** assert a verdict — verdicts come only from `kg_ground`
(out of scope for this command). See §1.4 / §1.8 (never-forge-a-verdict).

**This command needs no shell and no file access.** Do not run Bash, do not `Read` or `Grep` the source or the
plugin's files, and do not write helper scripts: the tools this command declares do all of it. In auto mode
Claude Code ignores a command's permission to use Bash, so every shell command would wait on its classifier,
or on the user. If a step seems to need a shell or a file, stop and report it instead of working around it.

## Inputs

**Arguments, as typed:** `$ARGUMENTS`

Do not split that line yourself: pass it to `kg_build_plan` exactly as it appears, and the engine reads it.

- **Empty** → the whole configured `source_path`, at the configured wave size.
- **A trailing whole number after a space** is the **wave size**, and the rest is the **subset**. So an
  unquoted name with spaces works: `/burgess:kg-build Fábricas de software.md 4`.
- **A line that is only a whole number** is the wave size: `/burgess:kg-build 4`.
- **Quotes** around the subset are dropped. Quote a name that itself ends in a number (`"capítulo 3"`), or
  that number is read as the wave size. Two separately quoted paths are refused: one subset is one file,
  folder or glob.
- **`--leads` as the first word** (0.9.0) writes the leads `/burgess:kg-ground` recorded instead of building: see
  **Leads mode**, below. The rest of the line still reads as a subset and a wave size: `/burgess:kg-build --leads 4`.

The two arguments:

- **subset** — optional. A file, or a folder / glob of `.md`/`.txt` files, **inside** the configured
  `source_path`, relative to the project folder or absolute. A bare file name also matches a configured file
  by name. It narrows what gets built and never replaces the configured source, because `kg_write` verifies
  every span against the files of the configured `source_path` (the engine's SourceSet, keyed by basename).
  A subset that reaches past those files makes the plan refuse, before any extractor runs. **When omitted,
  the source is the user's configured `source_path`**, which the engine resolved when it started; this
  command never reads it from a shell or an env var, so a configured `source_path` is never silently
  ignored (FALLO 3), and there is no fallback to `examples/source.md`.
- **wave size** — optional: how many extractor subagents run CONCURRENTLY per wave (bounded parallelism).
  - **Precedence:** the wave size in the arguments > the `extract_wave_size` option > 6.
  - **Validation:** parsed to a whole number and **clamped to 1–10**. Unset, not a number, or below 1 → 6;
    above 10 → 10.
  - **The option** reaches this command through its own text: Claude Code fills
    `${user_config.extract_wave_size}` when the command loads, and that is what you pass as
    `configured_wave_size`. When the option is unset the placeholder stays as written, and the engine reads
    it as unset.

  One section is still one subagent (the span-isolation property, below); the wave size only controls how
  many of those run at once.

## Procedure

### 0. Plan the build (`kg_build_plan`)

Call:

```
mcp__plugin_burgess_burgess__kg_build_plan(
  arguments: "<the arguments line above, verbatim; empty if nothing was typed>",
  configured_wave_size: "${user_config.extract_wave_size}"
)
```

Copy `configured_wave_size` exactly as this text shows it, even if it still reads `${user_config.…}`.

**`ok: false` → STOP.** Report `error`, and each of `problems` if there are any. Do not build anything, and
never fall back to the demo corpus:

- **No `source_path` is configured:** tell the user how to set it (*Changing `source_path`*, below). Naming a
  subset cannot stand in for it: spans verify against the configured source only.
- **Nothing readable at the configured path:** report `source.path`. Do not work around it with a subset,
  for the same reason.
- **A subset problem:** the subset names files outside the configured source, or nothing at all. Report it,
  and tell the user to move the files into the configured source or to change `source_path`.

**`ok: true`** → the plan holds the following. (With `--leads` it is `mode: "leads"` instead: go to **Leads
mode**, below.)

- `files[]`, one per file to build, in source order. Each has its `sections[]` (`section` number, `title`,
  `chars`, `covered`, and `edgeless` on a section recorded as holding no edge), its `heading_level` and any
  `note`.
  - `heading_level` is 2 for `## ` sections. It is 3 when the file's only `## ` heading is its title and its
    `### ` subsections carry the content (FALLO 4).
  - A file with no heading at that level is one section holding the whole file.
  - The text before a file's first heading (usually a title and a byline) is not a section.
- `wave_size`, and `wave_size_from`: `argument`, `option` or `default`.
- `sections_total`; `sections_uncovered`, the sections to extract; `sections_edgeless`, the ones recorded as
  holding no edge; and `waves`, the number of waves the sections to extract need.
- `skipped`, when a file of the folder could not be read as UTF-8 text.

Tell the user in a line or two what you are about to build: the files, the number of sections, and the wave
size and where it came from. A section whose `covered` is `true` already has span-present edges, from an
earlier or interrupted build: skip it. A section with `edgeless` (0.14.0) was extracted before, and its
extractor wrote no edge from it and recorded that (`edgeless.note` says why). Its text and the pack's types
are the ones that extraction read, so a new one would read the same text: skip it too, and say how many the
plan holds. A section is to extract when it is neither covered nor edgeless. When no section is, say so,
launch nothing, and go on to step 2.

**Changing `source_path`.** Give the user the value the engine reported, then the fix. From a terminal,
pipe a JSON object to `claude plugin configure burgess@<marketplace> --values-stdin` (Claude Code 2.1.285
or later; `burgess@sergiparpal` for this repo's own marketplace), for example in PowerShell:
`'{"source_path": "C:/docs/notes"}' | claude plugin configure burgess@sergiparpal --values-stdin`. Forward
slashes spare the JSON its backslash escapes. Windows PowerShell 5.1 pipes text as ASCII, so a path with
accents would be saved with `?` in their place, and no error: for such a path, have the user run
`$OutputEncoding = [System.Text.UTF8Encoding]::new($false)` first in the same window (PowerShell 7 already
sends UTF-8). `claude plugin configure burgess@<marketplace> --json` shows the saved values, under `inputs`.
Inside a session, the documented path is `/plugin` → *Installed* → **burgess** → *Configure options*. The
value is a bare path, without quotes: a file, a folder, or a glob of `.md`/`.txt` files. The MCP server
reads it only when it starts, so **Claude Code must be restarted** afterwards; a `/mcp` reconnect is not
documented to pick up a new value.

> In the plugin **dev repo**, an unconfigured run resolves to the bundled demo (`examples/source.md` exists
> under the project) and builds the five-section theory-of-grounding corpus — that path is a legitimate
> engine default, surfaced as `source.path`, not a silent fallback.

### 1. Launch the `kg-extractor` subagent per section, in BOUNDED PARALLEL WAVES (Task)

For **each section to extract in each file of the plan** (`covered` false and no `edgeless`), launch one
extractor and tell it only where its section is: the file's basename as `source_file`, and the plan's
`section` number and `title`. **Never paste section text into a prompt.** The extractor fetches its own with
`kg_section`: the engine cuts it from the source by the same rule the plan numbered by, and scrubs it on the
way out. What the extractor reads is therefore the source's own text, which is what lets its spans verify. With
a multi-file build the boundary verifies each span against **that file specifically** (R4 — a span attributed
to the wrong file is REJECTED `span-not-in-named-source`). The extractor reads its section, emits a single
complete `kg_write` payload, and reports its dispositions back to you. When its section states no relation the
pack's types can carry, it writes no edge and records the section with `kg_record_edgeless_section` (0.14.0),
which takes it out of later plans. It records the section too when every relation the section states is an
edge the canon already holds with a verdict, which `kg_write` quarantines (0.14.1).

**Only the extractor that read a section records it.** Never call `kg_record_edgeless_section` yourself, and
never offer the user to: you read no section, and a record says that a read of the section's current text,
under the current pack, found nothing new to write. The engine refuses a record for a section no `kg_section`
call served (0.14.1). A section still to extract after its launch is reported, not recorded (the resume probe,
below).

`kg_section` also lists the nodes already in the canon that the section names (`known_nodes`, 0.6.0), so an
extractor in a later wave reuses an id another section wrote instead of coining a near-duplicate. Extractors
in the same wave cannot see each other's nodes; that is the price of running them in parallel, and a later
`kg_merge` joins what slips through.

**Launch the per-section subagents CONCURRENTLY in waves of `wave_size` (from the plan).** Collect the plan's
`(file, section)` pairs to extract in plan order, then process them in batches: issue `wave_size` `Task(...)`
calls **in a single message** (so they run in parallel), wait for that whole wave to finish, then launch the
next wave, until every section is done. With the default of 6, a 19-section document is four waves (6 + 6 + 6
+ 1) instead of 19 serial launches. The extractors' (slow) token generation overlaps across the wave, while the
(brief) `kg_section` and `kg_write` calls all funnel through the one MCP server process and **serialize
cleanly** there, so nothing is dropped or corrupted. Ordering does **not** matter for correctness: the boundary
auto-creates a placeholder node for an edge's `source`, and a `target` may reference a node a later section
creates, so edges across waves resolve regardless of which wave lands first. Keep **one section per subagent**
(never batch sections into one launch — see the span-isolation note below).

Exact Task invocation (one per section — repeat across the wave, with each section's file, number and title):

```
Task(
  subagent_type: "kg-extractor",
  description: "Extract §1 Compression and the cost of generality",
  prompt: """
You are extracting ONE section of the source document into the canon via mcp__plugin_burgess_burgess__kg_write.

source_file: source.md      # basename of THIS section's file, from the plan — used as edge.source_file
section: 1                  # the plan's section number
title: "1. Compression and the cost of generality"

Get the section's text with mcp__plugin_burgess_burgess__kg_section(source_file: "source.md", section: 1)
and extract from that text only. It is the engine's verbatim, egress-scrubbed cut of the section: copy every
span EXACTLY from it, ⟦CAT:N⟧ placeholders included. If the title it returns is not the one above, say so in
your report. Its known_nodes are nodes other sections already wrote that your section names: reuse a known
node's id only for the same concept, and never redeclare it in nodes[] unless it is marked untyped and your
section defines it. Declare in nodes[] every other node your edges name.

Follow your system contract: declared node_types (compression, primitive, claim, metric, operation, failure)
and edge_types (grounds, attacked_by, reconciles_with, bridges, collapses_into, confounded_by, approximates,
defends_against, projects, survives, enables) only — anything else is QUARANTINED with a per-item
details[].reason of `undeclared-node-type` (nodes) or `undeclared-edge-type` (edges). Every
non-deterministic edge MUST carry a verbatim "span" that is a substring of the section text (§1.5), or it is
REJECTED. Do NOT set epistemic_state to a verdict and do NOT set authored_by=human (§1.4) — those are DEMOTED
("forged-verdict-stripped" / "human-claim-stripped"). Emit exactly one payload with "complete": true, call
kg_write with that payload only (never `source` or `construction`), and return the kg_write result
(dispositions, details[], written_nodes[], rolled_back).

If nothing in the section states a relation the pack's types can carry, write no edge, and record that with
mcp__plugin_burgess_burgess__kg_record_edgeless_section(source_file: "source.md", section: 1, note: "<why, in
one sentence>"), so later builds do not extract it again. If every edge you wrote comes back QUARANTINED as
collapses-into-known-failure or collapses-into-known-verdict, the canon already holds it with a verdict: do
not retry it, and record the section too, naming that edge's id in the note. Do not record a section whose
edges kg_write rejected. Say in your report whether you recorded it.
"""
)
```

> Why one section per launch (the **span-isolation** property — unchanged by the parallel waves): it keeps each
> extractor's span-verification scoped to text it can actually see, which is what makes `span-present` (§1.5)
> checkable rather than a paraphrase. A whole-document launch invites the extractor to "remember" spans and
> fabricate them. **Parallelism is across launches, never within one**: collapsing several sections into a single
> subagent would let an extractor mis-attribute a span across sections of the same file — undetectable by the
> boundary, which verifies the span against the whole `source_file`, not the one section. Waves change *how many*
> single-section extractors run at once; they never change *what one extractor sees*.

**The egress scrub (§1.9) happens inside `kg_section`.** Secrets (always) and PII (per the engine's
sensitivity) leave as **consistent placeholders** (`⟦SECRET:1⟧`, `⟦EMAIL:1⟧`, …), so the extractor only ever
sees the scrubbed form, and cites spans in that form when a redaction falls inside one. `kg_write` **restores**
each placeholder span to the original before verifying it, and stores the original in the canon: the scrub
protects the egress, not the local canon. You never see section text at all, so there is nothing for you to
scrub or to post-process: do not paraphrase, "clean up" or re-quote spans; the boundary validates them as the
extractor copied them.

**Resume / progress probe (projection-free).** Between waves — or to recover after a transport hiccup or a
cancelled request — call `kg_build_plan` again with the same two arguments. It reads the **canon** and the
ledger of edgeless sections only (it never projects): its `covered` flags show which sections already carry a
span-present edge, and `edgeless` which ones an extractor recorded as holding none. Re-launch only the sections
still to extract (re-writes are idempotent anyway). A section stays to extract after its launch when its
extractor wrote no span-present edge and recorded nothing (every edge REJECTED, or the record left out):
re-launch such a section at most once, then report it instead of looping. `kg_status()` stays available for
node and edge counts and the grounding queue.

Collect each launch's returned `kg_write` result: the `dispositions` counts
(**ACCEPTED / DEMOTED / QUARANTINED / REJECTED**), `details[]`, `written_nodes[]`, and `rolled_back`.

### 2. Force / confirm the derived projection

The canon is the single source of truth; the derived layer is regenerable and **projects** the canon (§5). The
read tools project **lazily** — they only rebuild the derived layer when it is stale. Confirm the build landed:

1. `mcp__plugin_burgess_burgess__kg_metrics()` — reads the **canon** directly and returns
   `{nodes, edges, edges_by_epistemic_state}`. This is your authoritative count of what the extractors wrote.
   Freshly written edges are `unverified` (no verdicts asserted at build time), so expect
   `edges_by_epistemic_state` to be dominated by `unverified`.
2. `mcp__plugin_burgess_burgess__kg_context(budget=2000)` — this **lazily projects** (rebuilds the derived layer if
   stale) and returns `{items[], approx_tokens, budget, falsification_counters:{failed_or_rejected_edges},
   advisory:{signal:"structural-bridge", note, nodes[]}}`. Calling it both *forces* the projection and confirms
   the derived layer agrees with the canon. The projection also brings the graph views `/burgess:kg-view`
   rendered up to date (0.15.0). At build time `falsification_counters.failed_or_rejected_edges` will
   typically be 0 — failures are negative information created later by an adversarial grounder via `kg_ground`
   (§1.7).

Optionally spot-check structure with `mcp__plugin_burgess_burgess__query_graph(node_type="compression")` or
`mcp__plugin_burgess_burgess__query_graph(epistemic_state="unverified", limit=50)` to eyeball the written nodes/edges.

### 3. Report

Summarize the build back to the user:

- **What was built** — the files and sections from the plan, the wave size and where it came from, and any
  section still to extract at the end (with its extractor's reason).
- **Edgeless sections** — `sections_edgeless` from the last plan: the sections this build or an earlier one
  recorded as holding no edge, which no build extracts again until their text or the pack's types change.
- **Dispositions** — summed across all section launches: ACCEPTED / DEMOTED / QUARANTINED / REJECTED, and for any
  REJECTED, the reason from `details[]` (`no-supporting-span`, `span-not-in-source`, `write-lane-hypothesis`,
  `self-loop`, `truncated-payload`, `schema-invalid`). For any QUARANTINED, its reason: an undeclared type
  (`undeclared-node-type`, `undeclared-edge-type`), or an edge the canon already holds with a verdict
  (`collapses-into-known-failure`: rejected or failed; `collapses-into-known-verdict`: grounded or obsolete).
  The reason alone does not tell rejected from failed: to name the edge's state, look it up (`query_graph`).
  Note `retryable=false` for SEMANTIC rejections (no-span, span-not-in-source) — those are extractor errors, not
  transport; `retryable=true` for TRANSPORT (truncation, schema).
- **Node / edge counts** — from `kg_metrics()`: `nodes`, `edges`, and the `edges_by_epistemic_state` breakdown.
- **Span-support** — every ACCEPTED non-deterministic edge carries a verifiable span by construction (the
  boundary rejects spanless edges). Call this out as the build's grounding guarantee, and surface any DEMOTED
  edges (a forged verdict or human claim was stripped back to `unverified` / `agent`).
- **Falsification counters** — from `kg_context`: `falsification_counters.failed_or_rejected_edges` (expected 0 at
  build; non-zero only after grounding).

## Leads mode (`/burgess:kg-build --leads`, 0.9.0)

A grounder that rejects a claim because its span states another relation (`wrong-relation`) or relates a
narrower or broader concept than one of its nodes (`wrong-node`) records the edge the span does state, the
**lead**, on the rejected edge. A build skips every section that already has edges, so this mode is the one
path a lead takes into the canon. It writes each lead once, as an `unverified` claim with the same span, and
the next `/burgess:kg-ground` judges it like any other.

1. **The plan** (`kg_build_plan` with the arguments as typed) is `mode: "leads"`:
   - `leads[]`, one entry per section, in source order: `source_file`, `section`, `title`, and its `leads[]`,
     each `{from_edge, lead}`: the rejected edge's id and the lead as `<head> <relation> <tail>`;
   - `leads_total`, `wave_size`, `wave_size_from` and `waves`;
   - `leads_unlocated`, when a rejected edge's span is no longer in the source. Report those ids: `/burgess:kg-ground`
     has to judge the claim again against the changed source before its lead can be written.

   `leads_total` 0 → report "no pending leads" and stop. Otherwise tell the user in a line how many leads, in
   how many sections, at what wave size.
2. **Launch one extractor per section,** `wave_size` launches in a single message, as for a build, and wait for
   each wave. Give each one its section and its leads' ids, and nothing else: it fetches the spans itself.

   ```
   Task(
     subagent_type: "kg-extractor",
     description: "Write the leads of §1 Mecanismos",
     prompt: """
   You are writing the LEADS of ONE section into the canon via mcp__plugin_burgess_burgess__kg_write (leads
   mode, in your contract).

   source_file: doc.md      # this section's file, from the plan
   section: 1               # the plan's section number
   title: "Mecanismos"
   leads (the rejected edge each came from, then the edge it names):
   - e_tests-protegidos__defends-against__hacer-trampas-con-los-tests: tests-protegidos defends_against manipulacion-de-tests

   Get the section with mcp__plugin_burgess_burgess__kg_section(source_file: "<file>", section: <n>, leads: true):
   its leads[] give each lead's span and say which ends the canon already holds. Write each lead as one edge
   with a verbatim span from the section's text, its notes opening with `lead (from <from_edge>)`, and declare
   a new end in nodes[] unless known_nodes holds the same concept: never the lead's other end, and never a
   claim about the end. Write nothing else: no other edge, and no known node redeclared. Return the kg_write
   result, and say why for any lead you did not write.
   """
   )
   ```
3. **Progress probe:** call `kg_build_plan` again with the same arguments. A written lead drops out of it. A lead
   its extractor declined stays in the plan: re-launch its section at most once, then report the lead with the
   extractor's reason instead of looping.
4. **Confirm the projection:** call `mcp__plugin_burgess_burgess__kg_context(budget=300)`, as a build's step 2
   does. It projects the canon, which also brings the graph views `/burgess:kg-view` rendered up to date.
5. **Report:** the leads written (the new edge ids) and the ones declined, with why; the summed dispositions, as
   for a build; and `kg_metrics()`'s counts. End by telling the user to run `/burgess:kg-ground`: the new edges wait in
   its queue as `unverified`.

## Worked example (against `examples/source.md`)

The plan lists five `## ` sections in `source.md`, so five extractor launches run as one wave at the default
`wave_size` of 6. You should expect ACCEPTED nodes like `compression`,
`generality-confound`, `specificity`, `bridge`, `betweenness`, `specificity-weighted-betweenness`, `degree`,
`canon`, `derived`, and ACCEPTED edges such as:

- `generality-confound --attacked_by--> specificity`
  span: `a more specific claim, when it holds, defeats a vaguer one`
- `betweenness --confounded_by--> generality-confound`
  span: `because a vague node sits on many paths for empty reasons`
- `specificity-weighted-betweenness --reconciles_with--> bridge`
  span: `weighting each node by the rarity of its terms`
- `degree --approximates--> importance`
  span: `plain **degree** is the honest advisory that *approximates* importance`
- `derived --projects--> canon`  (span: `The derived layer *projects* the canon`)

> Note on spans: `examples/source.md` wraps relation words in markdown emphasis (`*attacked_by*`, `*projects*`,
> …) and `normalize_text` does **not** strip `*`, so a span must either be asterisk-free clean prose (as above) or
> include the asterisks verbatim — never an asterisk-stripped `attacked_by` clause.

All emitted with `provenance: span-present`, `authored_by: agent`, `epistemic_state: unverified`. Edge IDs are
derived deterministically as `e_{source}__{relation}__{target}`, where `slug()` collapses underscores **and**
spaces to hyphens — e.g. `e_generality-confound__attacked-by__specificity` (the `attacked_by` relation slugs to
`attacked-by` in the id). After the build, `/burgess:kg-ground` (adversarial grounding) and
`/burgess:kg-query` (read) take over; **nothing here sets a verdict.**

## Failure modes to watch (and how you, the orchestrator, respond)

- **A section returns all REJECTED with `span-not-in-source`** → the extractor altered the text `kg_section` gave
  it (markdown stripped, whitespace mangled), or quoted text from outside its section. Re-launch that section
  once. Do not hand-edit spans yourself.
- **An extractor reports that `kg_section` refused** (`ok: false`: an unknown file or a section number out of
  range) → the source changed since the plan. Call `kg_build_plan` again, and launch from its new numbering.
- **REJECTED `self-loop`** → the extractor wrote an edge from a node to itself. Nothing to retry: there was no
  claim. Report it with the other rejections.
- **`placeholders` in a kg_write result** → the extractor named a node without declaring it, and the node landed
  untyped. Its contract has it re-send the payload with the node declared. If one is still untyped at the end,
  list it in the report: a later section that defines it can declare it, and `/burgess:kg-ground` can judge it.
- **A refused `kg_write` call** (`ok: false`, "`source` is only valid together with `construction`") → the
  extractor passed `source` to kg_write. Nothing was written; it should re-send the payload alone.
- **REJECTED `write-lane-hypothesis`** → the extractor marked an item `hypothesized`, the proposal lane that
  carries no span. Its contract tells it to re-emit the item as `inferred` with a verbatim span, or to drop
  it; if it reported the rejection instead, re-launch that section once.
- **`rolled_back: true`** on a launch → the whole payload was atomic-rejected (e.g. `truncated-payload`). This is
  `retryable=true`; re-launch the extractor for that section.
- **High QUARANTINED count** → the extractor used types outside the pack vocabulary (per-item
  `details[].reason` is `undeclared-node-type` / `undeclared-edge-type`; the offending node lands in the
  `undeclared-type` node_type bucket value). This is a pack-coverage gap, not a build error; report it so the pack
  (`pack/pack.yaml`) can be extended, then
  validated with `python -m kg_engine.pack validate pack/pack.yaml <source>` (a maintainer's step, not yours).
