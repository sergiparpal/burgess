---
description: Measure extractor precision (Stage 4) and grounding reliability (Stage 7); record the numbers in the project's .kg/PROGRESS.md.
argument-hint: "[graph.json] (default: the engine's derived graph.json)"
allowed-tools: Task, Read, mcp__plugin_burgess_burgess__kg_eval, mcp__plugin_burgess_burgess__query_graph
---

# /burgess:kg-eval — extraction & grounding measurement

Run the two measurement stages over the current canon's derived graph and append the results to the
project's `.kg/PROGRESS.md`. This command **measures**; it does not gate. No metric blocks the flow (§4,
"logged and proceeds, no human gate"). In a development checkout, a stage that falls short of its threshold
**auto-iterates** (refine the pack + extractor prompt, re-extract, re-measure — up to 3 passes) and records
the **best** result. An installed copy records the refinements the numbers point to instead (see 4.5).

- **Stage 4 — extraction precision.** Sample the derived edges, have the annotator label each against the
  source, and score the labels. Reports PRECISION (target `>= 0.70`), astrology rate (fabricated+vague),
  span-support rate, and per-relation precision.
- **Stage 7 — annotation agreement + specificity.** Two **independent** annotator passes over the same
  sample → Krippendorff's α (reliable `>= 0.67`); then the specificity bridge-metric gate verdict.

Every step runs in the engine, through `mcp__plugin_burgess_burgess__kg_eval`, and this command runs no
shell (0.28.0). Through 0.27.0 its steps were Bash blocks that started the plugin's Python from the plugin's
folder. Under the setting `permissions.blockReadsOutsideWorkingDirectories`, Claude Code asks the person
before any such command, and the auto mode's classifier cannot answer for them: an end-to-end run on
2026-11-25 was refused four times and measured nothing.

## Where things are

- **The run's folder.** The first step opens a run in the project's `.kg/eval/<run>/` and returns its paths.
  It holds the sheets, the annotators' labels, the saved results and two copies:
  - `source/`: the documents the graph's edges cite, exactly as the engine reads them. The annotators read
    these. The source itself may live outside the project (the plugin's option, or the copies a project
    built from registered sources keeps in the plugin's data folder), where the same setting blocks `Read`.
  - `contract/`: the plugin's `extractor.md`, `adversarial-grounder.md` and `pack.yaml`, for the check in 4.4.
- **The log** is the project's `.kg/PROGRESS.md`. Everything this command writes stays under `.kg/`, which
  Burgess never reads as a source document. The source can be the project folder itself, and then every
  `.md`/`.txt` file at the top of that folder is one of its documents.

A path in the arguments, `$ARGUMENTS` (the whole line is one path; drop any surrounding quotes), names a
graph.json to measure instead of the project's own graph.

## Step 0 — open the run

Call `mcp__plugin_burgess_burgess__kg_eval(step="sample")`, with `graph="<the path>"` only when the arguments
named one. It re-projects the project's graph first, so the numbers are this project's.
- `ok: false` means there is nothing to measure: tell the user what `error` says (for no graph or no edge to
  label, run `/burgess:kg-build` first), and stop.
- Note `run`: every later call passes it as `run="<run>"`. Note `sheets`, `labels`, `source.folder`,
  `contract.folder` and `copy` too.
- `legacy_log` is null unless a `PROGRESS.md` at the top of the project is one of the source documents.
  Through 0.11.6 this command kept its log there. If it holds a note, pass it on to the user now and again
  at the end, and go on. Don't move or delete the file; that is the user's call.

---

## Stage 4 — extraction precision

### 4.1 Inspect the graph (sanity, no labeling yet)

The `summary` gives the node/edge counts, the nodes grouped by `file_type` (distinct from the `node_type`
used in the §7.3 cross-check), the confidence mix (EXTRACTED | INFERRED | AMBIGUOUS), the top relations, and
the count of *judged* edges (INFERRED+AMBIGUOUS), split into the hypothesized proposals among them and the
extraction left to sample — that extraction is the precision-relevant part. The deterministic EXTRACTED
tier is span-present by construction, so the sheet excludes it; it leaves out the proposals too (4.2).

### 4.2 The labeling sheet

`sheets.labels` is the sheet: up to 80 non-EXTRACTED edges, sampled deterministically (seed 42), with columns
`edge_id, source_label, target_label, relation, confidence, confidence_score, source_file, verdict,
span_found, notes`. The `verdict`, `span_found` and `notes` columns are empty; the annotator's labels fill
them in 4.4.

The sheet leaves out every proposal still in the hypothesized lane (0.25.2); `sample.left_out_proposals`
says how many. Stage 4 measures the extraction: a `/burgess:kg-generate` or `/burgess:kg-perturb` proposal is
the generator's, `/burgess:kg-ground` judges it, and neither the pack nor the extractor prompt can change it.
Through 0.25.1 the sheet sampled proposals as extraction: in an end-to-end run (2026-11-25)
17 of 34 sampled edges were proposals, and the precision read 0.47 while the extractor's own edges were 15 of
15 correct. A proposal the grounding promoted to span-present is a grounded claim of the graph, and the sheet
keeps it.

### 4.3 Label the sheet (annotator subagent)

Launch the annotator via the **Task** tool to label the sheet against the real source. The only legal labels
are the vocabulary below — do not invent others. Fill in the three paths from Step 0's result:

```
Task(
  subagent_type: "kg-annotator",
  description: "Label Stage-4 precision sheet",
  prompt: """
    Label the sheet at <sheets.labels> and write your labels to <labels.labels>. The source documents are
    the files in <source.folder>: each row's document is the file its `source_file` column names there.
    Read each document your rows cite; those documents are your only ground truth.

    For EACH row, judge the (source_label, relation, target_label) claim STRICTLY against the source text
    and give it a verdict and a span_found:

      verdict ∈ {correct | fabricated | vague | wrong_type}
        correct    — the relation is true AND specific to the source
        fabricated — not supported by the source at all (hallucinated)
        vague      — "true" only because it is generic/unfalsifiable (the generality confound, §1.6):
                     reject anything that holds for almost any pair of nodes
        wrong_type — endpoints are related but the relation label is wrong
                     (e.g. labeled `grounds` where the source only says `attacked_by`)
      span_found ∈ {y | n}
        y — there is a verbatim textual span in the source supporting the claim (the span-present check)
        n — no such span exists

    Do not paraphrase to make a span "found". A span must be an actual substring of the source.
    Write ONE JSON object with the Write tool, one entry per row of the sheet, keyed by its edge_id:
      {"<edge_id>": {"verdict": "<label>", "span_found": "y", "notes": "<the verbatim span, or why not>"}, ...}
    Do not edit the CSV; it is filled from your JSON.
    Report: how many rows you labeled and the verdict counts.
  """
)
```

Annotators get `Read`, `Grep` and `Write`, and no shell: they read the documents with `Read` and `Grep` and
write their labels as one JSON file. Everything they read and write lies in the run's folder, inside the
project. They have **no** graph-write tools, so they cannot forge a verdict into the canon (verdicts reach the
canon only via `kg_ground`, §1.4).

### 4.4 Score

Call `mcp__plugin_burgess_burgess__kg_eval(step="score", run="<run>")`. It fills the sheet from the
annotator's labels and scores it, or, with `ok: false`, changes nothing and says why in `problems`: a row with
no label, a label for an edge the sheet lacks, a verdict outside the vocabulary, a `span_found` other than
y/n, or a file that is not valid JSON. In that case, hand `problems` to the same annotator and let it write
the file again. Never write or change a label yourself.

Read from `score`:

- **precision** = correct / labeled — the Stage-4 target is `>= 0.70` (`below_target` says whether it fell
  short).
- **astrology_rate** = (fabricated + vague) / labeled — the grounding risk, measured.
- **span_support_rate** = span_found=y / labeled — the §1.5 span-present check.
- **per_relation** (relations with 3 or more labeled rows) — which `pack.yaml` relations the extractor
  confuses (e.g. `grounds` vs `attacked_by` vs `confounded_by`).
- **calibration**, when the rows carry a numeric `confidence_score`: does it separate correct from wrong
  (`tracks`), or is it vocabulary, not grounding?
- **writers** — each labeled edge read in the canon, the sample split two ways:
  - **by writer** (`by_writer`), from the mark its canon notes open with:
    - `extractor`: a `/burgess:kg-build` extraction;
    - `lead`: written by `/burgess:kg-build --leads` from a grounder's lead;
    - `counter-edge`: written by an adversarial pass of `/burgess:kg-ground`;
    - `proposal`: still in the hypothesized lane, from `/burgess:kg-generate` or `/burgess:kg-perturb`.
      The sheet leaves these out (4.2), so this row appears only for a sheet that sampled proposals.
  - **by the grounding verdict** each edge holds now (`by_state`). An error the grounding already rejected
    is not a fact in the graph.

  `not_correct` lists the edges labeled other than `correct`, each with its writer and verdict.

**Before you recommend a refinement, here or in 4.5, check it against the current plugin.**
- The canon keeps every edge it has accepted since its first build, and it does not record which plugin
  version wrote an edge. So a sampled error shows how its writer worked then, which need not be how the
  current one works.
- Read the current contract, copied into Step 0's `contract.folder`:
  - `extractor.md` and `pack.yaml` for extractor and lead edges;
  - `adversarial-grounder.md` for counter-edges.
- When the contract already states the rule an error breaks, the edge was written before the rule. Record
  that instead of the refinement.
- A refinement is only for an error the current contract allows. Name the writer it is for.

### 4.5 Below target — iterate in a development checkout, recommend in an installed copy

If **precision >= 0.70**, skip to Stage 7. Otherwise, what a pass may change depends on which copy of the
plugin is running, which Step 0's `copy` says:

- **`installed`:** the plugin runs from the `plugins/cache` folder where Claude Code keeps installed plugins.
  - Do **not** edit `pack.yaml` or `agents/*.md` there. That copy belongs to one plugin version, every
    project on the machine shares it, and the next update replaces it.
  - Do **not** re-run `/burgess:kg-build` either. Re-extraction rewrites the user's canon, and a measurement
    must leave it alone.
  - Record the refinements the numbers point to (the two shapes below, checked against the current
    contract as 4.4 says) for the log's `iterations`, tell the user, and go on with one pass (K = 1).
- **`development`:** a checkout run with `--plugin-dir`, at `${CLAUDE_PLUGIN_ROOT}`. Iterate, up to 3 passes.
  Each pass:

1. Read the per-relation precision and verdict breakdown. The two failure shapes drive two fixes:
   - many `vague` → the **generality confound**: tighten `node_types` / sharpen the extractor prompt
     (`${CLAUDE_PLUGIN_ROOT}/agents/extractor.md`) to reject unfalsifiable edges, and add
     `specificity_seeds` for the confused vague terms in `${CLAUDE_PLUGIN_ROOT}/pack/pack.yaml` so they are
     not mistaken for content.
   - many `wrong_type` / `fabricated` → tighten the relation definitions in `pack.yaml` and the
     extractor's worked example; the boundary already REJECTS span-not-in-source, so persistent
     `fabricated` here means the prompt is over-reaching.
2. Validate the pack before re-extracting: `mcp__plugin_burgess_burgess__kg_eval(step="validate_pack",
   run="<run>")` (`ok: false` with `error` means the pack does not load).
3. Re-run `/burgess:kg-build` (re-extract → re-project → fresh `graph.json`), then
   `mcp__plugin_burgess_burgess__kg_eval(step="sample", run="<run>")` for the next pass of the same run, and
   redo 4.3–4.4.

Stop after the precision target is met **or** after 3 passes. The log records the **best** precision seen,
not the last (§4: "record the best precision and proceed regardless").

---

## Stage 7 — annotation agreement + specificity

### 7.1 Two independent annotator passes

Reliability needs **independent** coders: launch the annotator **twice** over the *same* edge sample, each
pass blind to the other (no shared notes, no second pass seeing the first's labels). Step 0 wrote both
sheets, `sheets.labels_a` and `sheets.labels_b`, from the same seed-42 sample as 4.2,
without the hypothesized proposals, so they cover the *identical* edges — exactly what α needs. Run two
separate Task calls (one per sheet); do not let pass B read pass A's output:

```
Task(subagent_type: "kg-annotator", description: "Independent pass A", prompt: "<4.3 prompt, sheet = sheets.labels_a, labels = labels.labels_a>")
Task(subagent_type: "kg-annotator", description: "Independent pass B", prompt: "<4.3 prompt, sheet = sheets.labels_b, labels = labels.labels_b>")
```

### 7.2 Compute α

Call `mcp__plugin_burgess_burgess__kg_eval(step="agreement", run="<run>")`. It fills each sheet from its
pass's labels, as in 4.4 (with `ok: false`, `problems` names the sheet whose labels to hand back to its
annotator), and returns `krippendorff_alpha` and a `verdict`. **α >= 0.67** → the grounding signal is treated
as reliable; **α < 0.67** → the grounding signal (and any gated metric) stays advisory. Units rated by fewer
than 2 coders are ignored; `units` counts the edges both passes labeled.

### 7.3 Specificity bridge-metric gate

Call `mcp__plugin_burgess_burgess__kg_eval(step="specificity", run="<run>")`. It reads the source exactly as
the projector does, so the IDF corpus is the projector's own, and compares specificity-weighted betweenness
against raw degree and raw betweenness over the source corpus (§1.4/§1.6). Read these fields of
`specificity`: `generality_confound_detected`, `rank_churn`, `top_raw_betweenness` vs
`top_specificity_weighted`, `gate_on`, and `verdict`. `gate_on: true` ("specificity-weighting earns its place
— gate ON") means the specificity-weighted bridge metric separates real bridges from vague high-traffic nodes
beyond the churn band and may be promoted out of advisory; otherwise degree stays the honest MVP advisory and
specificity-weighted betweenness remains GATED (§1.6).

> Cross-check (optional): `mcp__plugin_burgess_burgess__query_graph(node_type="compression")` shows the live
> compression nodes; the specificity leaders should be these, not vague terms like `idea`/`system`.

Stage 7 does not gate either — log α and the gate verdict and proceed (§4).

---

## Record the results — append to the log

Call `mcp__plugin_burgess_burgess__kg_eval(step="log", run="<run>", iterations="<…>")`. The engine appends a
dated entry to `.kg/PROGRESS.md` (never overwriting), written from the saved results: the graph, the source,
the best Stage-4 pass with the number of passes, Stage 7's α and the gate. `iterations` is the one thing only
you know: the refinements made in a development checkout, or recommended in an installed copy (checked as 4.4
says), or just `none` when there were none (the entry already says the precision and how many passes ran).
`entry` is the text appended.

Then print a one-line summary to the user:
`precision <p> (best/<K>) · α <alpha> (<reliable?>) · specificity gate <on|off>` — and remind them the
numbers are recorded in `.kg/PROGRESS.md`, nothing was gated, the flow proceeds. In an installed copy, list
the refinements you recommended and say that acting on them is a change to the plugin itself. Name the errors
whose rule the current contract already states: their edges were written before it. If Step 0's `legacy_log`
held a note, repeat it.

## Invariants this command upholds

- **Measure, never gate (§4).** Every threshold here is a *target*, not a barrier. Below target → iterate
  up to 3× then record the best and proceed. No human gate.
- **Annotators cannot forge verdicts (§1.4).** They write labels to a file; they hold no
  `kg_write`/`kg_ground` tools and no shell. Precision is measured *about* the canon, not written *into* it.
- **No shell, and nothing read outside the project (0.28.0).** Every step runs in the engine through
  `kg_eval`, which writes only under `.kg/`; the documents and the contract the agents read are copies in the
  run's folder.
- **An installed copy is never edited, and the user's canon is never rebuilt (step 4.5).** Below target,
  an installed plugin records what it would refine; only a development checkout edits its pack and
  re-extracts.
- **Span-present is the honest floor (§1.5).** The span-support rate is reported alongside precision so a
  high precision built on unverifiable spans is visible.
- **Generality confound stays visible (§1.6).** The `vague` rate and the specificity gate verdict together
  say whether centrality is real or inflated; degree remains the honest advisory until the gate turns on.
