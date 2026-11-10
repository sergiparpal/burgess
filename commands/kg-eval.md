---
description: Measure extractor precision (Stage 4) and grounding reliability (Stage 7); record the numbers in the project's .kg/PROGRESS.md.
argument-hint: "[graph.json] (default: the engine's derived graph.json)"
allowed-tools: Task, Bash, mcp__plugin_burgess_burgess__query_graph
---

# /kg-eval — extraction & grounding measurement

Run the two measurement stages over the current canon's derived graph and append the results to the
project's `.kg/PROGRESS.md`. This command **measures**; it does not gate. No metric blocks the flow (§4,
"logged and proceeds, no human gate"). In a development checkout, a stage that falls short of its threshold
**auto-iterates** (refine the pack + extractor prompt, re-extract, re-measure — up to 3 passes) and records
the **best** result. An installed copy records the refinements the numbers point to instead (see 4.5).

- **Stage 4 — extraction precision.** Sample the derived edges, have the annotator label each against the
  source, score with `f4_probe.py`. Reports PRECISION (target `>= 0.70`), astrology rate (fabricated+vague),
  span-support rate, and per-relation precision.
- **Stage 7 — annotation agreement + specificity.** Two **independent** annotator passes over the same
  sample → Krippendorff's α (`harness agreement`, reliable `>= 0.67`); then the specificity bridge-metric
  gate verdict (`harness specificity`).

## Where things are

Claude Code filled these in when the command loaded. Use them as they stand:

- **Plugin root:** `${CLAUDE_PLUGIN_ROOT}`.
- **Engine data:** `${CLAUDE_PLUGIN_DATA}`. The derived graph is `${CLAUDE_PLUGIN_DATA}/derived/graph.json`.
- **Project:** `${CLAUDE_PROJECT_DIR}`. The log is its `.kg/PROGRESS.md`, and scratch files go in its
  `.kg/eval/`. Everything this command writes stays under `.kg/`, which Burgess never reads as a source
  document. The source can be the project folder itself, and then every `.md`/`.txt` file at the top of
  that folder is one of its documents.
- **Source:** `${user_config.source_path}`, what the graph was built from. It is one file, or a folder whose
  `.md`/`.txt` files are the documents. Each edge's `source_file` names its document in that folder.

`GRAPH` is the path in the arguments, `$ARGUMENTS` (the whole line is one path; drop any surrounding quotes),
if one was given, else `${CLAUDE_PLUGIN_DATA}/derived/graph.json`.

## Step 0 — a fresh graph and the engine's interpreter

1. **Call `mcp__plugin_burgess_burgess__query_graph(limit=1)` before any Bash step.** Every session on the
   machine shares the engine data dir, so `graph.json` may hold another project's projection; a read tool
   re-projects it for this project first. If it returns no nodes, tell the user to run `/kg-build` first,
   and stop.
2. **Start every Bash block with the same four lines** (shown in full in each block below). Each Bash call
   is a fresh shell, so nothing set in one block survives into the next:

   ```bash
   PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
   export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
   GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
   EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
   ```

   `engine_python.mjs` prints the interpreter the plugin's launcher uses: `.venv\Scripts\python.exe` on
   Windows, `.venv/bin/python` elsewhere. If it exits 1, the engine is not provisioned yet: tell the user to
   start a new Claude Code session, whose SessionStart hook builds it, and stop.

---

## Stage 4 — extraction precision

### 4.1 Inspect the graph (sanity, no labeling yet)

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" summary "$GRAPH"
"$PY" -m kg_engine.harness legacy-log "${CLAUDE_PROJECT_DIR}" "${user_config.source_path}"
```

This prints node/edge counts, the nodes grouped by `file_type` (distinct from the `node_type` used in the
§7.3 cross-check), the confidence mix (EXTRACTED | INFERRED | AMBIGUOUS), the top relations, and the count
of *judged* edges (INFERRED+AMBIGUOUS) — that judged slice is the precision-relevant part. The deterministic
EXTRACTED tier is span-present by construction, so the sheet excludes it by default.

`legacy-log` prints nothing unless a `PROGRESS.md` at the top of the project is one of the source documents.
Through 0.11.6 this command kept its log there. If it prints a note, pass it on to the user now and again at
the end, and go on. Don't move or delete the file; that is the user's call.

### 4.2 Emit the labeling sheet

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" sheet "$GRAPH" --n 80 --out "$EVAL/labels.csv"
```

`sheet` deterministically samples (seed 42) up to 80 non-EXTRACTED edges into `labels.csv` with columns
`edge_id, source_label, target_label, relation, confidence, confidence_score, source_file, verdict,
span_found, notes`. The `verdict`, `span_found` and `notes` columns are empty; the annotator's labels fill
them in 4.4.

### 4.3 Label the sheet (annotator subagent)

Launch the annotator via the **Task** tool to label `labels.csv` against the real source. The only legal
labels are the f4_probe vocabulary — do not invent others.

```
Task(
  subagent_type: "kg-annotator",
  description: "Label Stage-4 precision sheet",
  prompt: """
    Label the sheet at ${CLAUDE_PROJECT_DIR}/.kg/eval/labels.csv and write your labels to
    ${CLAUDE_PROJECT_DIR}/.kg/eval/labels.json. The source is ${user_config.source_path}. If that is a
    folder, each row's document is the file its `source_file` column names inside it; if it is a file, that
    file is the whole source. Read each document your rows cite; those documents are your only ground truth.

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
write their labels as one JSON file. In a setup that asks before every shell command, an annotator with a
shell cost the user one approval per search. They have **no** graph-write tools, so they cannot forge a
verdict into the canon (verdicts reach the canon only via `kg_ground`, §1.4).

### 4.4 Score

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" fill "$EVAL/labels.csv" "$EVAL/labels.json" || exit 1
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" score "$EVAL/labels.csv"
"$PY" -m kg_engine.harness writers "$EVAL/labels.csv" "${CLAUDE_PROJECT_DIR}"
```

`fill` writes the annotator's labels into the sheet, or changes nothing and says why: a row with no label,
a label for an edge the sheet lacks, a verdict outside the vocabulary, a `span_found` other than y/n, or a
file that is not valid JSON. In that case, hand its message to the same annotator and let it write the file
again. Never write or change a label yourself.

Capture from stdout:

- **PRECISION** = correct / labeled — the Stage-4 target is `>= 0.70`.
- **astrology rate** = (fabricated + vague) / labeled — the grounding risk, measured.
- **span-support rate** = span_found=y / labeled — the §1.5 span-present check.
- **per-relation precision** (rows with n>=3) — which `pack.yaml` relations the extractor confuses
  (e.g. `grounds` vs `attacked_by` vs `confounded_by`).
- the **confidence-calibration** line, if a numeric `confidence_score` is present (does it separate correct
  from wrong, or is it vocabulary, not grounding?).
- **writers** — `harness writers` reads each labeled edge in the canon and splits the sample two ways:
  - **by writer**, from the mark its canon notes open with:
    - `extractor`: a `/kg-build` extraction;
    - `lead`: written by `/kg-build --leads` from a grounder's lead;
    - `counter-edge`: written by an adversarial pass of `/kg-ground`;
    - `proposal`: written by `/kg-generate`.
  - **by the grounding verdict** each edge holds now. An error the grounding already rejected is not a fact
    in the graph.

  It ends with the list of edges labeled other than `correct`, each with its writer and verdict.

**Before you recommend a refinement, here or in 4.5, check it against the current plugin.**
- The canon keeps every edge it has accepted since its first build, and it does not record which plugin
  version wrote an edge. So a sampled error shows how its writer worked then, which need not be how the
  current one works.
- Read the current contract:
  - `${CLAUDE_PLUGIN_ROOT}/agents/extractor.md` and `${CLAUDE_PLUGIN_ROOT}/pack/pack.yaml` for extractor
    and lead edges;
  - `${CLAUDE_PLUGIN_ROOT}/agents/adversarial-grounder.md` for counter-edges.
- When the contract already states the rule an error breaks, the edge was written before the rule. Record
  that instead of the refinement.
- A refinement is only for an error the current contract allows. Name the writer it is for.

### 4.5 Below target — iterate in a development checkout, recommend in an installed copy

If **PRECISION >= 0.70**, skip to recording. Otherwise, what a pass may change depends on which copy of the
plugin is running. Its root is `${CLAUDE_PLUGIN_ROOT}`:

- **Installed copy:** the root lies inside a `plugins/cache` folder, where Claude Code keeps installed
  plugins.
  - Do **not** edit `pack.yaml` or `agents/*.md` there. That copy belongs to one plugin version, every
    project on the machine shares it, and the next update replaces it.
  - Do **not** re-run `/kg-build` either. Re-extraction rewrites the user's canon, and a measurement must
    leave it alone.
  - Record the refinements the numbers point to (the two shapes below, checked against the current
    contract as 4.4 says) under "iterations" in the log, tell the user, and go on with one pass (K = 1).
- **Development checkout:** any other root, such as a repo run with `--plugin-dir`. Iterate, up to 3 passes.
  Each pass:

1. Read the per-relation precision and verdict breakdown. The two failure shapes drive two fixes:
   - many `vague` → the **generality confound**: tighten `node_types` / sharpen the extractor prompt
     (`${CLAUDE_PLUGIN_ROOT}/agents/extractor.md`) to reject unfalsifiable edges, and add
     `specificity_seeds` for the confused vague terms in `${CLAUDE_PLUGIN_ROOT}/pack/pack.yaml` so they are
     not mistaken for content.
   - many `wrong_type` / `fabricated` → tighten the relation definitions in `pack.yaml` and the
     extractor's worked example; the boundary already REJECTS span-not-in-source, so persistent
     `fabricated` here means the prompt is over-reaching.
2. Validate the pack before re-extracting:
   ```bash
   PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
   export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
   "$PY" -m kg_engine.pack validate "${CLAUDE_PLUGIN_ROOT}/pack/pack.yaml" "${user_config.source_path}"
   ```
3. Re-run `/kg-build` (re-extract → re-project → fresh `graph.json`), then redo 4.2–4.4.

Stop after the precision target is met **or** after 3 passes. Record the **best** precision seen, not the
last (§4: "record the best precision and proceed regardless").

---

## Stage 7 — annotation agreement + specificity

### 7.1 Two independent annotator passes

Reliability needs **independent** coders: launch the annotator **twice** over the *same* edge sample, each
pass blind to the other (no shared notes, no second pass seeing the first's labels). Emit two CSVs:

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" sheet "$GRAPH" --n 80 --out "$EVAL/labels_a.csv"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" sheet "$GRAPH" --n 80 --out "$EVAL/labels_b.csv"
```

`sheet` is deterministic (seed 42), so `labels_a.csv` and `labels_b.csv` cover the *identical* edge sample —
exactly what α needs. Run two separate Task calls (one per file); do not let pass B read pass A's output.
Each pass writes its own labels file:

```
Task(subagent_type: "kg-annotator", description: "Independent pass A", prompt: "<4.3 prompt, sheet = labels_a.csv, labels = labels_a.json>")
Task(subagent_type: "kg-annotator", description: "Independent pass B", prompt: "<4.3 prompt, sheet = labels_b.csv, labels = labels_b.json>")
```

### 7.2 Build the label-sets file and compute α

`harness agreement` consumes a JSON **list of coder dicts** `[{unit_id: label, ...}, {...}]` with labels in
`{correct | fabricated | vague | wrong_type}`. Fill each sheet from its pass's labels, as in 4.4, then
convert the two CSVs (key each row by `edge_id`, value = `verdict`) into `label_sets.json`:

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" fill "$EVAL/labels_a.csv" "$EVAL/labels_a.json" || exit 1
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/f4_probe.py" fill "$EVAL/labels_b.csv" "$EVAL/labels_b.json" || exit 1
"$PY" - "$EVAL/labels_a.csv" "$EVAL/labels_b.csv" > "$EVAL/label_sets.json" <<'EOF'
import csv, json, sys
def coder(p):
    with open(p, encoding="utf-8") as f:
        return {r["edge_id"]: r["verdict"].strip().lower()
                for r in csv.DictReader(f) if r.get("verdict", "").strip()}
json.dump([coder(p) for p in sys.argv[1:]], sys.stdout)
EOF
"$PY" -m kg_engine.harness agreement "$EVAL/label_sets.json"
```

Prints `krippendorff_alpha: <x>` and a verdict line. **α >= 0.67** → the grounding signal is treated as
reliable; **α < 0.67** → the grounding signal (and any gated metric) stays advisory. Units rated by fewer
than 2 coders are ignored, so both passes must cover the same `edge_id`s — they do, by the seed-42 sample.

### 7.3 Specificity bridge-metric gate

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
"$PY" -m kg_engine.harness specificity "$GRAPH" "${user_config.source_path}"
```

The source may be the folder of documents: the harness reads it exactly as the projector does, so the IDF
corpus is the projector's own. Emits JSON comparing specificity-weighted betweenness against raw degree and
raw betweenness over the source corpus (§1.4/§1.6). Read these fields: `generality_confound_detected`,
`rank_churn`, `top_raw_betweenness` vs `top_specificity_weighted`, `gate_on`, and `verdict`. `gate_on: true`
("specificity-weighting earns its place — gate ON") means the specificity-weighted bridge metric separates
real bridges from vague high-traffic nodes beyond the churn band and may be promoted out of advisory;
otherwise degree stays the honest MVP advisory and specificity-weighted betweenness remains GATED (§1.6).

> Cross-check (optional): `mcp__plugin_burgess_burgess__query_graph(node_type="compression")` shows the live
> compression nodes; the specificity leaders should be these, not vague terms like `idea`/`system`.

Stage 7 does not gate either — log α and the gate verdict and proceed (§4).

---

## Record the results — append to the log

Append (never overwrite) a dated block to `${CLAUDE_PROJECT_DIR}/.kg/PROGRESS.md`. Fill `<...>` from the
captured stdout; under "iterations" note how many Stage-4 passes ran and that the **best** precision is
recorded, or, in an installed copy, the refinements you recommend, checked as 4.4 says. Everything after the
first two lines is a quoted heredoc, so the shell leaves that text alone: write backticks and `$` as they are.

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"   # or the path given in the arguments
EVAL="${CLAUDE_PROJECT_DIR}/.kg/eval"; mkdir -p "$EVAL"
{
  printf '\n## /kg-eval — %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'graph: %s   (labeled n=%s)\n' "$GRAPH" "<N>"
  cat <<'EOF'
source: ${user_config.source_path}

Stage 4 — extraction precision
- PRECISION (best of <K> pass(es)):  <precision>   (target >= 0.70 — recorded, non-gating)
- astrology rate (fabricated+vague): <astro>
- span-support rate (span_found=y):  <span>
- per-relation precision:            <rel1>=<p1>, <rel2>=<p2>, ...
- by writer:                         <writer>=<precision> (<correct>/<labeled>), ...   (harness writers)
- by grounding verdict:              <state> <correct>/<labeled> correct, ...
- confidence calibration:            <gap / "n/a">
- iterations:                        <K> (<pack/extractor refinements made, or recommended in an installed copy, or "none">)

Stage 7 — agreement + specificity
- krippendorff_alpha:                <alpha>   (reliable >= 0.67 — <RELIABLE | advisory>)
- specificity gate:                  gate_on=<true|false> — <verdict>
- generality confound detected:      <true|false>; rank_churn=<churn>
EOF
} >> "${CLAUDE_PROJECT_DIR}/.kg/PROGRESS.md"
```

Then print a one-line summary to the user:
`precision <p> (best/<K>) · α <alpha> (<reliable?>) · specificity gate <on|off>` — and remind them the
numbers are recorded in `${CLAUDE_PROJECT_DIR}/.kg/PROGRESS.md`, nothing was gated, the flow proceeds. In an
installed copy, list the refinements you recommended and say that acting on them is a change to the plugin
itself. Name the errors whose rule the current contract already states: their edges were written before it.
If `legacy-log` printed a note, repeat it.

## Invariants this command upholds

- **Measure, never gate (§4).** Every threshold here is a *target*, not a barrier. Below target → iterate
  up to 3× then record the best and proceed. No human gate.
- **Annotators cannot forge verdicts (§1.4).** They write labels to a file; they hold no
  `kg_write`/`kg_ground` tools and no shell. Precision is measured *about* the canon, not written *into* it.
- **An installed copy is never edited, and the user's canon is never rebuilt (step 4.5).** Below target,
  an installed plugin records what it would refine; only a development checkout edits its pack and
  re-extracts.
- **Span-present is the honest floor (§1.5).** The span-support rate is reported alongside precision so a
  high precision built on unverifiable spans is visible.
- **Generality confound stays visible (§1.6).** The `vague` rate and the specificity gate verdict together
  say whether centrality is real or inflated; degree remains the honest advisory until the gate turns on.
