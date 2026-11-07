---
description: Build the grounded knowledge graph from a source document — extract section-by-section into the canon (bounded parallel waves), then project.
argument-hint: "[source_path] [wave_size]"
allowed-tools: Task, Bash, mcp__plugin_burgess_burgess__kg_scrub, mcp__plugin_burgess_burgess__kg_metrics, mcp__plugin_burgess_burgess__kg_status, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__query_graph
---

# /kg-build — orchestrate the BUILD

You are the **build orchestrator**. You turn a non-self-grounding conceptual document into a grounded,
queryable graph by driving the `kg-extractor` subagent over the source **section by section**, then forcing the
derived projection and reporting what landed. You do the *coordination*; the extractor does the *language work*;
the engine does the *deterministic work* behind the `kg_write` boundary.

You do **not** call `kg_write` yourself, and you **never** assert a verdict — verdicts come only from `kg_ground`
(out of scope for this command). See §1.4 / §1.8 (never-forge-a-verdict).

## Inputs

- `$1` — an **optional subset** of the configured source: a single **file**, or a **directory / glob** of
  `.md`/`.txt` files (R4 — multi-document), that lies **inside** the configured `source_path`. It narrows
  what gets built; it cannot replace the configured source. `kg_write` verifies every span against the
  files of the configured `source_path` (the engine's SourceSet, keyed by basename), never against `$1`,
  so a file outside it would have every edge REJECTED `span-not-in-source`; Step 0b checks this before
  any extractor runs. **When omitted, the source is the user's configured
  `source_path`, which you read from the ENGINE in Step 0a (`kg_status().source.path`) — NOT from a
  shell env var.** `CLAUDE_PLUGIN_OPTION_SOURCE_PATH` / `KG_SOURCE_PATH` are **not visible to this
  command's Bash shell** (the host injects userConfig options only into the MCP server process), so
  resolving the default in Bash silently misses a configured `source_path` and builds the demo by
  surprise. Step 0 resolves the path through the engine and **fails loud** — it never falls back to
  `examples/source.md` when a `source_path` is configured (FALLO 3). `source_path` is `required` in
  `plugin.json`, so a configured value must be honored.

- `$2` — **optional inline wave size**: how many section-extractor subagents to launch CONCURRENTLY per
  wave (bounded parallelism). **Precedence: explicit `$2` > user_config > default.** When `$2` is omitted
  it falls back to `${CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE}`, then to `6`. The value is parsed to an
  integer and **clamped to 1–10** (unset / non-numeric / `< 1` → `6`; `> 10` → `10`). One section is still
  one subagent (the span-isolation property, below); the wave size only controls how many of those run at
  once. Resolved deterministically in Step 0.

## Procedure

### 0. Resolve & enumerate the source FILES

#### 0a. Resolve the source path via the ENGINE (tool, not the shell)

Call `mcp__plugin_burgess_burgess__kg_status()` and read its **`source`** block — `{path, exists, files}`.
`source.path` is the engine-resolved `source_path` (the server has `KG_SOURCE_PATH`, already dequoted): the
single source of truth. Decide the source, in this order:

- **`$1` given** → the source is **`$1`**, narrowed to what the engine can verify: Step 0b checks that every
  file it enumerates is listed in `source.files`.
- **else `source.path` is set** → the source is **`source.path`**.
- **else** (no `$1` and `source.path` is `null`) → **STOP.** No `source_path` is configured. Do **not**
  silently build the demo corpus — tell the user to set the plugin's `source_path` (see *Changing
  `source_path`* below). Passing `$1` cannot stand in for it: spans verify against the configured source
  only. (`source_path` is `required` in `plugin.json`; a missing value is a configuration error, not a cue
  to build `examples/source.md`.)

If `source.path` is set but **`source.exists` is `false`** (configured but resolving to zero readable
`.md`/`.txt` files), **STOP** and report that unreadable path — never fall through to the demo, and do not
work around it with `$1`, for the same reason. This is the FALLO 3 fix: the command reads the path the
engine actually resolved instead of an env var that is empty in the tool shell, so a configured
`source_path` can never be silently ignored.

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
> engine default, surfaced as `source.path`, not a silent Bash fallback.

#### 0b. Enumerate the FILES and each file's sections (Bash)

With the source chosen in 0a, build the file list and enumerate each file's sections. A single file is the
common case; a directory or glob builds from **every** `.md`/`.txt` member. **Substitute the chosen path for
`SRC` below** — pass `$1` verbatim if the user gave one, else the `source.path` string from 0a — inside
the double quotes, as one string, even when it holds spaces. Never hard-code `examples/source.md` here;
Step 0a already decided (or stopped).

```bash
SOURCE="$SRC"   # $1 if the user passed one, else the source.path value from kg_status() (Step 0a)
# Dequote defensively: a path a user wrapped in quotes — or a host that handed back a JSON-quoted value —
# must not carry literal quotes into the ls/find below. Peel matched surrounding pairs REPEATEDLY (a
# double-wrapped ""path"" collapses to the bare path), mirroring kg_engine.envconfig.clean.
while :; do
  case "$SOURCE" in
    \"*\") SOURCE="${SOURCE#\"}"; SOURCE="${SOURCE%\"}" ;;
    \'*\') SOURCE="${SOURCE#\'}"; SOURCE="${SOURCE%\'}" ;;
    *) break ;;
  esac
done
[ -n "$SOURCE" ] || { echo "no source resolved — see Step 0a (configure source_path or pass \$1)"; exit 1; }
# Resolve the extraction WAVE SIZE: inline override ($2) > user_config > default 6; integer; clamp 1..10.
# (This pure-Bash resolution mirrors kg_engine.waves.resolve_wave_size, the unit-tested reference — no
# venv/PYTHONPATH dependency here. A present-but-invalid value falls straight to the default 6, not the
# next level down.)
WAVE_RAW="${2:-${CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE:-6}}"
case "$WAVE_RAW" in (''|*[!0-9]*) WAVE_SIZE=6 ;; (*) WAVE_SIZE=$WAVE_RAW ;; esac   # unset/non-numeric -> 6
[ "$WAVE_SIZE" -lt 1 ] 2>/dev/null && WAVE_SIZE=6      # below range -> default
[ "$WAVE_SIZE" -gt 10 ] 2>/dev/null && WAVE_SIZE=10    # above range -> clamp to max
echo "extraction wave size: $WAVE_SIZE"
# Build the list of source FILES, ONE PATH PER LINE: a single file, every .md/.txt in a directory, or a glob.
# Never let the shell word-split a path. Windows paths routinely hold spaces ("Proyectos personales",
# "OneDrive - Org"), and an unquoted $SOURCE or `for f in $FILES` cuts them into pieces that name nothing.
if [ -d "$SOURCE" ]; then
  FILES=$(find "$SOURCE" -maxdepth 1 -type f \( -iname '*.md' -o -iname '*.txt' \) ! -name '.*' | sort)
elif [ -f "$SOURCE" ]; then
  FILES="$SOURCE"   # one file, taken whole
else
  # A glob, expanded as ONE pattern, so its spaces stay literal. `\` becomes `/` first, so the separators of
  # a Windows pattern (C:\docs\*.md) are not read as glob escapes. Same .md/.txt filter as the engine.
  FILES=$(compgen -G "${SOURCE//\\//}" | grep -iE '\.(md|txt)$' | sort)
fi
[ -n "$FILES" ] || { echo "no .md/.txt source found at: $SOURCE"; exit 1; }
echo "building from:"; echo "$FILES"
# Enumerate each file's section headings at that file's DOMINANT heading level (FALLO 4). Most files use
# level-2 `## ` sections; a file whose ONLY `## ` is its title but that carries several `### ` subsections
# is split at `### ` instead — otherwise the whole file collapses into ONE section, breaking the
# per-section span-isolation the extractor relies on (see the span-isolation note in Step 2). Warn when a
# file yields 0-1 sections at level 2 so a mis-levelled document is never silently built as one blob.
while IFS= read -r f; do
  echo "== $f =="
  H2=$(grep -cE '^## '  "$f"); H2=${H2:-0}
  H3=$(grep -cE '^### ' "$f"); H3=${H3:-0}
  if [ "$H2" -le 1 ] && [ "$H3" -ge 2 ]; then
    echo "(dominant heading level: '### ' — $H3 subsections; the single '## ' is the file title)"
    grep -nE '^### ' "$f"
  else
    [ "$H2" -le 1 ] && echo "WARNING: only $H2 level-2 '## ' section(s) here — the whole file is one section; verify the heading level before launching one extractor over the entire file"
    grep -nE '^## ' "$f"
  fi
done <<< "$FILES"
```

**Check the enumerated files against the engine before launching anything.** Every basename printed under
`building from:` must appear in `source.files` from Step 0a. A file the engine does not list can never
verify a span (each of its edges would be REJECTED `span-not-in-source`), so **STOP** and name it instead of
launching extractors for it, and tell the user to move it into the configured source or change
`source_path`. With no `$1` the two lists should match; report any file `source.files` lists that Step 0b
did not find.

The demo corpus (`examples/source.md`) is the five-section "theory of grounded conceptual knowledge":
**§1 Compression and the cost of generality**, **§2 Provenance and the span**, **§3 Bridges and betweenness**,
**§4 Memory of failures**, **§5 The canon and the projection**. One extractor launch per section — at each
file's **dominant heading level** from Step 0b (usually `## `; `### ` for a file whose only `## ` is its
title), **per file**; pass the file's basename (e.g. `source.md`) as the extractor's `source_file`.

> **Resume note.** `kg_status().coverage` reports `##`-level sections; for a `### `-dominant file it shows a
> single section, so treat your Step 0b per-file enumeration as the authority for which slices to launch and
> use `coverage` as a best-effort "has this file been touched" signal.

### 1. Egress scrub — the §1.9 egress point (now WIRED)

You are reading a **source on disk** and handing *section text* to a subagent. The §1.9 egress scrub is the
engine's `scrub.py`, now exposed as the MCP tool `mcp__plugin_burgess_burgess__kg_scrub`. It is real and wired into the
flow as **Step 0** of each section:

1. **Step 0 — scrub before egress.** Call `mcp__plugin_burgess_burgess__kg_scrub(text=<section body>)` to get the
   `scrubbed` source. This redacts secrets (always) and PII (per sensitivity) into **consistent placeholders**
   (`⟦SECRET:1⟧`, `⟦EMAIL:1⟧`, …) before any text crosses the egress to a subagent. It returns
   `{scrubbed, redactions, sensitivity, categories}`. For the no-PII demo source (`examples/source.md`),
   `kg_scrub` is a **no-op** — `redactions: 0` and the scrubbed text equals the original.
2. **Hand the SCRUBBED text to `kg-extractor`.** The subagent only ever sees the scrubbed (placeholder) form, so
   it emits spans in **scrubbed form** when a redaction fell inside a span.
3. **`kg_write` RESTORES the spans to the original for the canon.** The boundary maps each placeholder span back
   to the original text before span verification and stores the **restored original** span in the canon. The
   scrub protects the **egress**, not the local canon — the canonical record keeps the true text.

So the scrub does run for §1.9 egress protection, but it runs **before** the extractor (Step 0), not silently
inside `kg_write`; the boundary's role is the **restore**. You do **not** post-process spans yourself — the
extractor copies spans **verbatim** (§1.5) from the scrubbed text it was given, and the boundary restores and
validates them. Do not paraphrase or "clean up" the section text you pass in; a mangled span will be **REJECTED**
as `span-not-in-source` (fabrication).

### 2. Launch the `kg-extractor` subagent per section, in BOUNDED PARALLEL WAVES (Task)

For **each** section **of each file** — at that file's dominant heading level from Step 0b (`## `, or `### `
for a title-only-`##` file) — launch the extractor with the **section's verbatim text** and the **basename of
the file it came from** as `source_file`. The extractor stamps every edge in that section with that
basename; with a multi-file build the boundary verifies each span against **that file specifically** (R4 — a span
attributed to the wrong file is REJECTED `span-not-in-named-source`). The extractor reads the section, emits a
single complete `kg_write` payload, and reports its dispositions back to you.

**Launch the per-section subagents CONCURRENTLY in waves of `WAVE_SIZE` (from Step 0).** Collect the full list of
`(file, section)` pairs, then process it in batches: issue `WAVE_SIZE` `Task(...)` calls **in a single message**
(so they run in parallel), wait for that whole wave to finish, then launch the next wave, until every section is
done. The default `WAVE_SIZE` is `6`; a 19-section document is therefore four waves (6 + 6 + 6 + 1) instead of 19
serial launches — the extractors' (slow) token generation overlaps across the wave, while the (brief) `kg_write`
calls all funnel through the one MCP server process and **serialize cleanly** there, so nothing is dropped or
corrupted. Ordering does **not** matter for correctness: the boundary auto-creates a placeholder node for an
edge's `source`, and a `target` may reference a node a later section creates, so edges across waves resolve
regardless of which wave lands first. Keep **one section per subagent** (never batch sections into one launch —
see the span-isolation note below).

Exact Task invocation (one per section — repeat across the wave, substituting each section's heading + body):

```
Task(
  subagent_type: "kg-extractor",
  description: "Extract §1 Compression",
  prompt: """
You are extracting ONE section of the source document into the canon via mcp__plugin_burgess_burgess__kg_write.

source_file: source.md          # basename of THIS section's file, as in source.files — used as edge.source_file
section: "## 1. Compression and the cost of generality"

SECTION TEXT (verbatim — copy spans EXACTLY from this; never paraphrase):
<<<
A **compression** is a single idea that stands in for many observations; it earns its keep only when it
predicts. The **generality confound** is the failure mode where a vague idea accumulates spurious
connections: because it touches everything loosely, it looks central while explaining nothing. Generality
is therefore *attacked_by* specificity — a more specific claim, when it holds, defeats a vaguer one that
merely overlaps it. A compression that survives specific attack is said to *grounds* the claims beneath it.
>>>

Follow your system contract: declared node_types (compression, primitive, claim, metric, operation, failure)
and edge_types (grounds, attacked_by, reconciles_with, bridges, collapses_into, confounded_by, approximates,
defends_against, projects, survives) only — anything else is QUARANTINED with a per-item
details[].reason of `undeclared-node-type` (nodes) or `undeclared-edge-type` (edges). Every
non-deterministic edge MUST carry a verbatim "span" that is a substring of the section text above (§1.5), or it
is REJECTED. Do NOT set epistemic_state to a verdict and do NOT set authored_by=human (§1.4) — those are DEMOTED
("forged-verdict-stripped" / "human-claim-stripped"). Emit exactly one payload with "complete": true and return
the kg_write result (dispositions, details[], written_nodes[], rolled_back).
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

**Resume / progress probe (projection-free).** Between waves — or to recover after a transport hiccup or a
cancelled request — call `mcp__plugin_burgess_burgess__kg_status()`: it reads the **canon
only** (it never projects) and returns the node/edge counts, the `unverified` queue size, and a `coverage` map
of which `##` sections already carry an anchored span-present edge. Re-launch only the **uncovered** sections
(covered re-writes are idempotent anyway), and call it once more at the end to confirm full coverage.

Collect each launch's returned `kg_write` result: the `dispositions` counts
(**ACCEPTED / DEMOTED / QUARANTINED / REJECTED**), `details[]`, `written_nodes[]`, and `rolled_back`.

### 3. Force / confirm the derived projection

The canon is the single source of truth; the derived layer is regenerable and **projects** the canon (§5). The
read tools project **lazily** — they only rebuild the derived layer when it is stale. Confirm the build landed:

1. `mcp__plugin_burgess_burgess__kg_metrics()` — reads the **canon** directly and returns
   `{nodes, edges, edges_by_epistemic_state}`. This is your authoritative count of what the extractors wrote.
   Freshly written edges are `unverified` (no verdicts asserted at build time), so expect
   `edges_by_epistemic_state` to be dominated by `unverified`.
2. `mcp__plugin_burgess_burgess__kg_context(budget=2000)` — this **lazily projects** (rebuilds the derived layer if
   stale) and returns `{items[], approx_tokens, budget, falsification_counters:{failed_or_rejected_edges},
   advisory:{signal:"structural-bridge", note, nodes[]}}`. Calling it both *forces* the projection and confirms
   the derived layer agrees with the canon. At build time `falsification_counters.failed_or_rejected_edges` will
   typically be 0 — failures are negative information created later by an adversarial grounder via `kg_ground`
   (§1.7).

Optionally spot-check structure with `mcp__plugin_burgess_burgess__query_graph(node_type="compression")` or
`mcp__plugin_burgess_burgess__query_graph(epistemic_state="unverified", limit=50)` to eyeball the written nodes/edges.

### 4. Report

Summarize the build back to the user:

- **Dispositions** — summed across all section launches: ACCEPTED / DEMOTED / QUARANTINED / REJECTED, and for any
  REJECTED, the reason from `details[]` (`no-supporting-span`, `span-not-in-source`, `truncated-payload`,
  `schema-invalid`). Note `retryable=false` for SEMANTIC rejections (no-span, span-not-in-source) — those are
  extractor errors, not transport; `retryable=true` for TRANSPORT (truncation, schema).
- **Node / edge counts** — from `kg_metrics()`: `nodes`, `edges`, and the `edges_by_epistemic_state` breakdown.
- **Span-support** — every ACCEPTED non-deterministic edge carries a verifiable span by construction (the
  boundary rejects spanless edges). Call this out as the build's grounding guarantee, and surface any DEMOTED
  edges (a forged verdict or human claim was stripped back to `unverified` / `agent`).
- **Falsification counters** — from `kg_context`: `falsification_counters.failed_or_rejected_edges` (expected 0 at
  build; non-zero only after grounding).

## Worked example (against `examples/source.md`)

After five extractor launches over the demo corpus (one wave at the default `WAVE_SIZE=6`, since the demo has
five `##` sections) you should expect ACCEPTED nodes like `compression`,
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
`attacked-by` in the id). After the build, `/kg-ground` (adversarial grounding) and
`/kg-query` (read) take over; **nothing here sets a verdict.**

## Failure modes to watch (and how you, the orchestrator, respond)

- **A section returns all REJECTED with `span-not-in-source`** → the section text you pasted into the Task prompt
  was altered (markdown stripped, whitespace mangled). Re-launch that section with the **verbatim** body. Do not
  hand-edit spans yourself.
- **`rolled_back: true`** on a launch → the whole payload was atomic-rejected (e.g. `truncated-payload`). This is
  `retryable=true`; re-launch the extractor for that section.
- **High QUARANTINED count** → the extractor used types outside the pack vocabulary (per-item
  `details[].reason` is `undeclared-node-type` / `undeclared-edge-type`; the offending node lands in the
  `undeclared-type` node_type bucket value). This is a pack-coverage gap, not a build error; report it so the pack
  (`pack/pack.yaml`) can be extended, then
  validated with `python -m kg_engine.pack validate pack/pack.yaml "$SOURCE"`.
