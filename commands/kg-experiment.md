---
description: Stage 8/9 — blind ideation experiment (control|graph|graph+generate|graph+generate+dpp|rag); score with the harness, optionally have blind judges score each idea (--judge), and append the verdicts to the project's .kg/PROGRESS.md
argument-hint: "[--judge] [prompts_path]"
allowed-tools: Task, Bash, Read, Write, mcp__plugin_burgess_burgess__kg_context, mcp__plugin_burgess_burgess__kg_generate, mcp__plugin_burgess_burgess__kg_agenda
---

# /kg-experiment — does the graph actually help ideation? (§Stage 8, §4)

This command runs the one experiment that justifies the whole pipeline: a **blind A/B/C/D** over a fixed
set of ideation prompts, in four conditions that differ ONLY in what context the idea-generator is given.

- **control** — the prompt alone, no source, no graph.
- **graph** — the prompt + a `kg_context` pack drawn from the **grounded** knowledge graph (`items[]` only).
- **graph+generate** — the prompt + the graph pack **plus the hypothesized slate** (one
  `kg_generate(mechanism="all", k=12)` call): the generative layer's proposals, clearly flagged as unverified
  candidates. Tests whether *generating* lifts ideation beyond grounded context alone (PLAN Stage 9).
- **rag** — the prompt + the passages a naive flat retrieval finds in the source documents (the strawman to
  beat): BM25 over the source's paragraphs, run by `harness rag-slices` in Step 1b, so every run of the same
  prompts on the same source gives this arm the same passages.
- **graph+generate+dpp** *(FUSION Stage 6)* — the graph pack plus the SAME hypothesized slate as
  `graph+generate`, but presented in the advisory-DPP order with its geometry labels
  (`kg_generate(..., dpp=true)` → `divergence_advisory` bins / semantic novelty / cliché-hub
  distance, rendered as opaque text). The candidate SET is identical (I5) — this arm measures
  whether the *presentation* lifts ideation. Decision Rule D1 (docs/fusion/EXPERIMENT.md) compares
  it against `graph+generate` to set the shipped `divergence.dpp` default.
- **lightrag** *(optional, off by default)* — the prompt answered from a real, published **GraphRAG**
  baseline (LightRAG) built over the **same** source documents the `rag` arm reads. A stronger strawman than
  flat `rag`: it lets the central claim stand against a genuine graph-retrieval system, not only against
  grep. This arm is **add-only and opt-in** — see "The optional lightrag arm" below. When it is not enabled
  the experiment runs its original four arms, unchanged.

The generator is BLIND to which condition it is in (it receives only an opaque context block), so the
scoring is not contaminated by the model "trying harder" for one arm. That blindness is procedural: one
evaluator subagent assembles the contexts and writes the ideas, so it answers each arm from that arm's
context alone and writes every control answer before it sees any context. Scoring is **deterministic** —
`python -m kg_engine.harness ideation` scores each idea's **grounded novelty** (how far it goes beyond the
source's wording × how much of its key-term weight the source holds), compares the arms prompt by prompt, and
names in `caveats` anything it could not measure in this run. The method is pre-declared in the plugin's
`docs/fusion/EXPERIMENT.md` ("Stage 8 method, 0.12.0"). Per §4 **no metric gates execution**: this command logs
the table + verdicts to the project's `.kg/PROGRESS.md` and returns, regardless of whether graph wins.

The headline question the verdict answers:
> **Given the same source and budget, do the `graph` arm's ideas score higher grounded novelty than flat
> retrieval's (`rag`), prompt by prompt?** It wins when it does in enough prompts for a one-sided sign test at
> 5 % (10 of 12). `control` is compared the same way in a second verdict. Through 0.11.x the headline compared
> graph with control on novelty, which is distance from a source the control arm never sees, so the graph arm
> could not win it.

Arguments, as typed (optional): `$ARGUMENTS`. Split them this way:
- If the line holds the word `--judge` standing alone, take it out. It turns on Step 3b, the blind judge.
- What remains, trimmed and without any surrounding quotes, is one path to a JSON or newline-delimited file of
  custom ideation prompts. If nothing remains, Step 1 picks the prompt set.

## Where things are

Claude Code filled these in when the command loaded. Use them as they stand:

- **Plugin root:** `${CLAUDE_PLUGIN_ROOT}`.
- **Engine data:** `${CLAUDE_PLUGIN_DATA}`.
- **Project:** `${CLAUDE_PROJECT_DIR}`. The log is its `.kg/PROGRESS.md`, and the run's files go in its
  `.kg/experiment/`: the prompt file, the rag passages and the outputs. Everything this command
  writes stays under `.kg/`, which Burgess never reads as a source document. The source can be the project
  folder itself, and then every `.md`/`.txt` file at the top of that folder is one of its documents.
- **Source:** `${user_config.source_path}`, what the graph was built from. It is one file, or a folder whose
  `.md`/`.txt` files are the documents. The `rag` and `lightrag` arms read it, and the harness scores
  novelty and unsupported claims against it.

---

## Step 0 — environment

Each Bash call is a fresh shell, so every Bash block in this command starts with the same three lines.
`engine_python.mjs` prints the interpreter the plugin's launcher uses: `.venv\Scripts\python.exe` on
Windows, `.venv/bin/python` elsewhere.

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"; mkdir -p "$EXP"
"$PY" -m kg_engine.harness ideation 2>&1 | head -n 1   # smoke-test: harness importable
"$PY" -m kg_engine.harness legacy-log "${CLAUDE_PROJECT_DIR}" "${user_config.source_path}"
"$PY" -m kg_engine.lightrag_arm check                  # {"available": ..., "reason": ...}
echo "RUN=$(date -u +%Y%m%dT%H%M%SZ)"
```

If `engine_python.mjs` exits 1, the engine is not provisioned yet: tell the user to start a new Claude Code
session, whose SessionStart hook builds it, and stop.

`RUN` is this run's UTC timestamp. The run's files carry it in their names, so note it. `lightrag_arm check`
says whether the optional `lightrag` arm can run (see below); note `available`.

`legacy-log` prints nothing unless a `PROGRESS.md` at the top of the project is one of the source documents.
Through 0.11.6 this command and `/kg-eval` kept their log there. If it prints a note, pass it on to the user
and stop: the `rag` arm and the harness read every source document, so this run would take an earlier run's
results for source, both to answer and to score. Don't move or delete the file; the user moves it out of the
source folder and runs the command again.

Confirm the graph is queryable before spending tokens generating ideas:

- Call **`mcp__plugin_burgess_burgess__kg_context`** with `budget=2000` and no `query`. If it returns an empty
  `items[]`, there is no grounded graph to test — tell the user to run `/kg-build` then `/kg-ground` first,
  and stop. Note the `falsification_counters.failed_or_rejected_edges`; a graph with **zero** recorded
  failures (§1.7) is suspect and the `graph` arm will look artificially clean — surface that caveat in the
  final report.

### The optional `lightrag` arm (opt-in, off by default)

A fifth arm, `lightrag`, compares the graph against a **real published GraphRAG baseline** instead of only
the flat-grep `rag` strawman. It is **off by default** and entirely add-only: when it is not enabled, this
command runs exactly the original four arms and nothing changes.

To enable it, all three must hold (Step 0 probes this with
`"$PY" -m kg_engine.lightrag_arm check`, which prints `{"available": …, "reason": …}`):

1. **Install** the optional dependency: `pip install lightrag-hku` (or `pip install -e ".[lightrag]"` from
   the repo). It is **not** part of the default install.
2. **Opt in** with the env var `KG_LIGHTRAG=1` (the arm stays off even if the package is installed unless you
   set this). Optional tuning: `KG_LIGHTRAG_QUERY_MODE` (default `mix`).
3. **Provide credentials**: `OPENAI_API_KEY` — LightRAG's default LLM + embedding backend is OpenAI, so this
   arm makes **network + paid API calls**. That cost is the price of the stronger baseline; it is why the arm
   is opt-in, not automatic.

When enabled, Step 1b runs the isolated helper, which builds a LightRAG index over the **same** source
documents the `rag` arm reads (`${user_config.source_path}`, so the comparison is fair), under a
**gitignored, disposable** working store in the derived dir, and answers each prompt through LightRAG's own
retrieval — it never reads our graph's structure. When **not** enabled, the `lightrag` arm is omitted and the
harness simply scores the arms present. Either way the run proceeds; the arm never blocks the experiment.

---

## Step 1 — prompt set (non-blocking checkpoint)

A path in the arguments names a custom prompt file (one prompt per line, or a JSON array): use it.
Otherwise the prompt set depends on the corpus.

**The 12 default prompts below are written for the demo corpus that ships with the plugin**
(`${CLAUDE_PLUGIN_ROOT}/examples/source.md`: compression, span/provenance, bridges/betweenness,
memory-of-failures, canon/projection). Use them only when the configured source is that file. On any other
corpus they ask about concepts the graph does not hold, every arm answers from the model's prior, and the
verdict measures nothing.

For any other corpus, **draft 12 prompts from the user's own graph** instead:

1. Call `mcp__plugin_burgess_burgess__kg_agenda(limit=12)` and reuse Step 0's `kg_context` result to see the
   graph's communities, hubs and grounded claims.
2. Write 12 open-ended ideation prompts **in the corpus's own language**, each naming one or two real
   grounded concepts by their labels. Spread them over the same kinds as the default list: a failure mode;
   a concept that would bridge two communities, and the edge type that would connect them; a claim that
   would attack a grounded one; a measure that would tell two things apart; a use for a refuted edge; a
   place where two ideas reconcile; a confound.
3. Keep them neutral. A prompt that only the graph can answer is smuggling moved upstream.

Whichever set you use, save it with the **Write** tool as a JSON array of strings to
`${CLAUDE_PROJECT_DIR}/.kg/experiment/prompts-<RUN>.json`, where `<RUN>` is the timestamp Step 0 printed, and
show it to the user once:

> **These are the N prompts I'll use. Go ahead, or would you rather supply your own?**

This is a **non-blocking checkpoint** (§4): a reply is invited but not required to make progress. A later
run can pass the saved file as the argument to repeat the experiment on the same prompts.

**The 12 default prompts** (demo corpus only — see above):

1. Propose a new failure mode, distinct from the generality confound, by which a vague node could earn spurious centrality.
2. Suggest a concept that bridges "compression" and "memory of failures" and say what edge type would connect them.
3. What specific claim, if it held, would *attack_by* the idea that span-present provenance always grounds better than inference?
4. Invent a metric other than betweenness or degree that a genuine bridge would score high on and a vague hub would not.
5. Describe an operation that turns a rejected/failed edge back into negative information the graph can defend against.
6. Where might "specificity-weighted betweenness" *reconcile_with* raw degree rather than replace it?
7. Name a case where the derived projection *could* legitimately contain something the canon does not — or argue it never can.
8. Propose a primitive that "compression" *collapses_into* under extreme generality, and the test that detects the collapse.
9. What would a claim that *defends_against* re-proposing a known failure look like, concretely?
10. Suggest how a verdict could *survive* reprojection if the reconciler were removed — or prove it cannot.
11. Identify two communities of ideas in the source and the single node most likely to *bridge* them.
12. Propose a confound, parallel to the generality confound, that afflicts *novelty* scoring rather than centrality.

---

## Step 1b — the rag arm's passages (Bash → harness)

The `rag` arm answers from passages of the source, and the harness picks them, the same way on every run:
BM25 over the source's paragraphs, accents folded, best first, within the 2000-token budget the graph arm's
`kg_context` call gets. Replace `<RUN>` with Step 0's timestamp:

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"; RUN="<RUN>"
"$PY" -m kg_engine.harness rag-slices "$EXP/prompts-$RUN.json" "${user_config.source_path}" "$EXP/rag-$RUN"
```

It writes one Markdown file per prompt (`01.md`, `02.md`, …) and an `index.json` of what each holds into
`.kg/experiment/rag-<RUN>/`, and prints how many passages each got.

Only when Step 0's `lightrag_arm check` printed `"available": true`, run this block instead, so the optional
arm's answers exist before the evaluator starts:

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"; RUN="<RUN>"
"$PY" -m kg_engine.harness rag-slices "$EXP/prompts-$RUN.json" "${user_config.source_path}" "$EXP/rag-$RUN"
"$PY" -m kg_engine.lightrag_arm answer --source "${user_config.source_path}" \
    --prompts "$EXP/prompts-$RUN.json" --out "$EXP/lightrag-$RUN.json"
```

---

## Step 2 — generate outputs in blind conditions (Task → kg-evaluator)

Launch the **kg-evaluator** subagent via the **Task** tool. It owns blinding, context assembly, and idea
generation; this command never sees which arm is which until the JSON comes back keyed by condition.

`Task(subagent_type: "kg-evaluator", description: "blind ideation experiment", prompt: …)` — give it the
saved prompt file's path, the rag folder `${CLAUDE_PROJECT_DIR}/.kg/experiment/rag-<RUN>`, the LightRAG
answers file `${CLAUDE_PROJECT_DIR}/.kg/experiment/lightrag-<RUN>.json` only if Step 1b wrote it, and the
output path `${CLAUDE_PROJECT_DIR}/.kg/experiment/ideation_outputs.json`. The evaluator has no shell: it reads
with Read, writes its one file with Write, and reaches the graph through its three MCP tools. Instruct it to:

1. Write all **control** answers first, from the prompts alone, before any tool call.
   - Save them to the control draft (`ideation_outputs.control.json`, beside the output path) as that first
     call.
   - Save control and the three graph-based arms to the graph draft (`ideation_outputs.graph.json`) before
     reading any rag file.
   - The final file copies both drafts unchanged, and Step 3 checks that (`harness evaluator-order`).
2. For **each** prompt, answer once per remaining arm, each from that arm's context only:
   - **graph** → the result of `mcp__plugin_burgess_burgess__kg_context(query=<prompt>, budget=2000)`, rendered as
     opaque text — the **grounded** `items[]` only. Carry through the pack's `advisory` (e.g.
     `signal:"structural-bridge"`, `bridge_metric`) and the `falsification_counters` so the generator can
     *avoid* re-proposing failed edges (§1.7) — but it MUST NOT fabricate verdicts or spans; this arm only
     *reads* the graph.
   - **graph+generate** → the graph block PLUS the hypothesized slate: the candidates of one
     `mcp__plugin_burgess_burgess__kg_generate(mechanism="all", k=12, dpp=false)` call, rendered as opaque
     text and clearly marked *unverified candidates*. `k` is per mechanism, so `all` returns up to 84 before
     duplicates merge. This arm reads grounded context AND the generative proposals; it still must not
     fabricate verdicts or spans.
   - **graph+generate+dpp** → the graph block PLUS the same slate reordered by
     `mcp__plugin_burgess_burgess__kg_generate(mechanism="all", k=12, dpp=true)` with its
     `divergence_advisory` labels rendered as opaque text (bins + semantic novelty + cliché distance),
     clearly marked *unverified candidates* exactly like graph+generate. Both generate arms take the slate
     from `kg_generate`, so their candidate sets are identical (I5) as the `dpp_verdict` requires.
   - **rag** → that prompt's file in the rag folder: the passages Step 1b's retrieval found, no graph
     structure. This is the honest strawman. Nothing else from the source.
   - **lightrag (optional)** → NOT a context block — its answers come from the external LightRAG system, not
     from the evaluator. When you gave it the answers file, it copies that file's `answers[]` into
     `outputs.lightrag` unchanged, in prompt order; otherwise it omits the key. That arm reads the same prose
     corpus as `rag`, through LightRAG's retrieval — never our graph's structure.
3. Treat the arms the same: one idea of 2–4 sentences per (prompt × arm), no answer quoting a sibling answer.
   Write every idea about the domain, never about its materials: no mention of the graph, its nodes, edges or
   relation names, epistemic states, degrees, the candidates or the slate, the passages or a tool. An
   unverified candidate becomes a hedged hypothesis. A reader holding only the source must not be able to
   tell the arms apart by their form.
4. Write a single JSON object in EXACTLY the shape `harness ideation` consumes to
   `${CLAUDE_PROJECT_DIR}/.kg/experiment/ideation_outputs.json`, then read it back to check it parses:

```json
{
  "outputs": {
    "control":        ["…one string per prompt…"],
    "graph":          ["…"],
    "graph+generate": ["…"],
    "graph+generate+dpp": ["…"],
    "rag":            ["…"],
    "lightrag":       ["… (OPTIONAL — present only when the lightrag arm was enabled+available) …"]
  }
}
```

`harness ideation` scores every condition key it finds. When `graph+generate` is present it emits a second
**`generate_verdict`** alongside the headline graph-vs-control `verdict`: whether *generating* (graph context
+ the hypothesized slate) lifted diversity/novelty beyond control without materially more unsupported
claims, and whether it exceeded `graph` alone. When `graph+generate+dpp` is present it emits a
**`dpp_verdict`** (the same slate in DPP order vs `graph+generate`). When the optional `lightrag` arm is present
it emits a **`lightrag_verdict`** (graph-vs-LightRAG): whether the grounded `graph` arm beat the published
GraphRAG baseline. All of these are absent when their arm is — a missing optional arm is never an error.

Constraints to put in the Task prompt: each **present** `outputs` list has the **same length** (= number of
prompts); one output string per prompt per condition. The JSON carries **no source text**: the harness reads
`${user_config.source_path}` itself to compute `novelty` (n-gram overlap with the source) and
`unsupported_rate` (sentences whose key terms never appear in the source). The evaluator returns the
**file path** it wrote.

---

## Step 3 — score deterministically (Bash → harness)

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"; mkdir -p "$EXP"
"$PY" -m kg_engine.harness ideation "$EXP/ideation_outputs.json" "${user_config.source_path}"
```

The second path is the source, read exactly as the projector reads it (one file, or a folder of
documents, each indexed on its own). `harness ideation` prints a JSON object like this one (numbers
illustrative):

```json
{
  "table": {
    "control":            {"n": 12, "diversity": 0.99, "novelty": 0.90, "support": 0.41, "grounded_novelty": 0.37, "utility": 0.0, "unsupported_rate": 0.48},
    "graph":              {"n": 12, "diversity": 0.96, "novelty": 0.76, "support": 0.83, "grounded_novelty": 0.63, "utility": 0.0, "unsupported_rate": 0.10},
    "graph+generate":     {"n": 12, "diversity": 0.90, "novelty": 0.82, "support": 0.78, "grounded_novelty": 0.64, "utility": 0.0, "unsupported_rate": 0.14},
    "graph+generate+dpp": {"n": 12, "diversity": 0.89, "novelty": 0.82, "support": 0.77, "grounded_novelty": 0.63, "utility": 0.0, "unsupported_rate": 0.15},
    "rag":                {"n": 12, "diversity": 0.99, "novelty": 0.64, "support": 0.95, "grounded_novelty": 0.61, "utility": 0.0, "unsupported_rate": 0.02}
  },
  "comparisons": {
    "graph vs rag": {"n": 12, "wins": 9, "losses": 3, "ties": 0, "needed": 10, "median_diff": 0.03},
    "graph vs control": {"n": 12, "wins": 12, "losses": 0, "ties": 0, "needed": 10, "median_diff": 0.25}
  },
  "verdict": "graph did NOT clearly beat rag on grounded novelty (9 of 12 prompts; 10 needed)",
  "control_verdict": "graph beat control on grounded novelty in 12 of 12 prompts",
  "generate_verdict": "graph+generate did NOT clearly beat graph on grounded novelty (6 of 12 prompts; 10 needed)",
  "dpp_verdict": "graph+generate+dpp did NOT clearly beat graph+generate on grounded novelty (5 of 12 prompts; 10 needed)",
  "support_check": {"rag": 0.95, "control": 0.41, "gap": 0.54, "min_gap": 0.1, "valid": true, "probe_drop": 0.31, "probes": 180},
  "caveats": ["utility counts only the English markers ..."]
}
```

What each column means (per idea, then averaged over the arm):
- **novelty**: `1 − (the share of the idea's word trigrams that occur in the source)`, how far it travels
  from the source's wording.
- **support**: for each sentence of four or more words with two or more key terms, the share of its key
  terms' IDF weight held by terms the source contains. Key terms are words longer than five characters,
  compared by stem (folded, first six characters), so an inflection the source does not use is not an
  invention. A word every paragraph has weighs little; a term the source lacks weighs the most.
- **grounded_novelty**: novelty × support. It is the one the verdicts compare. It is high only for an idea
  that leaves the source's wording while its terms stay in the source.
- **diversity, utility, unsupported_rate**: reported, in no verdict.
  - diversity: distinct trigrams over total, pooled.
  - utility: English reasoning markers.
  - unsupported_rate: the share of judged sentences with support below 0.5.

**`comparisons`** lists each pre-declared pair, prompt by prompt:
- a **win** is a prompt where the first arm's grounded novelty exceeds the second's by more than 0.005, a
  **loss** the reverse, and a **tie** anything closer;
- `needed` is the fewest wins out of `n` that a one-sided sign test at 5 % accepts: 10 of 12, and no number
  below five prompts.

**The verdicts.**
- `verdict` (graph vs rag, the headline);
- `control_verdict` (graph vs control);
- `generate_verdict` (graph+generate vs graph: does the slate add to grounded context);
- `dpp_verdict` (the dpp arm vs graph+generate);
- `lightrag_verdict` (graph vs the LightRAG baseline, only when that arm ran).

Each reads one of:
- `"<X> beat <Y> on grounded novelty in <w> of <n> prompts"`;
- `"<X> did NOT clearly beat <Y> on grounded novelty (<w> of <n> prompts; <k> needed)"`;
- `"<X> vs <Y>: too few prompts to decide (…)"`;
- `"not measured: support does not separate rag from control on this source"`;
- `"insufficient data"` when an arm is missing or empty.

**`support_check`** is the instrument check. `rag` answers from source passages and `control` from nothing,
so `rag`'s mean support must exceed `control`'s by at least 0.10. When it does not, support measures nothing
on this source, and every verdict reads "not measured". `probe_drop` is information: the mean support lost
when each judged sentence's first key term is replaced by an invented one.

**`caveats`** lists, in plain sentences, what this run could not measure:
- a failed support check;
- an unchecked one (no `rag` or no `control` arm);
- utility, when no arm's ideas contain one of its English markers.

The verdict strings do not change with them, so a verdict must always be read with its caveats.

**The evaluator's order (0.13.1).** Check that the drafts show the order Step 2 asked for:

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"
"$PY" -m kg_engine.harness evaluator-order "$EXP/ideation_outputs.json"
```

It prints `{"verified": true|false, "drafts": {...}, "problems": [...]}`. `verified` is true when:
- the control draft predates the graph draft, which predates the final outputs;
- the final outputs carry both drafts' answers unchanged.

When it is false, this run cannot show that control was written blind to the graph, or the graph arms blind to
the rag passages. Log and report that, with the `problems`. It gates nothing (§4). If you rerun the evaluator
(Step 2) for any reason, rerun this check on the new files.

---

## Step 3b — the blind judge (only with `--judge`)

Skip this step unless the arguments held `--judge`. It reads every idea the way a careful reader would, which
the lexical score cannot. One judge per prompt sees that prompt's ideas from every arm, plus two controls, each
idea with passages retrieved from the source for it. The judge scores each idea for **grounded** (its claims
hold in its evidence) and **useful** (specific enough to test or apply), then ranks them.

Judges never score novelty. Evidence retrieved for an idea's own words cannot show that the idea restates the
source in other words. Three pilots fixed this method; the plugin's `docs/fusion/EXPERIMENT.md` records them
(option D, and "novelty and paraphrase").

**Cost.** Each judge reads a packet of about 35,000–40,000 tokens, so 12 prompts cost about 1.5 million tokens
on top of the experiment. Tell the user so before launching the judges.

1. **Write the controls** with the Write tool, two per prompt, to
   `${CLAUDE_PROJECT_DIR}/.kg/experiment/judge-<RUN>/private/controls.json` as
   `{"decoys": [...], "positives": [...]}`, one string per prompt, in prompt order. Before writing a prompt's
   pair, Read that prompt's file in the rag folder.
   - **decoy**: a plausible idea of two to four sentences, in the prompts' language and the arms' register.
     Its central support is invented: it cites a study, an organisation or a figure that the source does not
     contain. Do not copy an arm's idea.
   - **positive control**: a plausible idea of two to four sentences whose facts are real. Every figure and
     name it cites comes from that prompt's rag passages, drawn from at least two different documents. Any
     relation it draws between them is stated as a hypothesis.
   - Neither control mentions the graph, its edges or candidates, the passages or a tool, so the judges cannot
     tell the controls from the arms by their form.
2. **Build the packets** (Bash → harness):

   ```bash
   PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
   export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
   EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"; J="$EXP/judge-<RUN>"
   "$PY" -m kg_engine.harness judge-packets "$EXP/ideation_outputs.json" "$EXP/prompts-<RUN>.json" \
     "${user_config.source_path}" "$J/private/controls.json" "$J"
   ```

   - **Exit 0:** the packets are in `$J/packets/`.
   - **Exit 3:** a control failed its check, and the printed JSON names the prompt and the reason. The reasons
     are: a decoy with nothing invented; or a positive control that cites something the source lacks, cites
     fewer than two of its figures or names, has a fact missing from its evidence, or draws on one document
     only.
   - **On exit 3:** rewrite those controls once and run the command again. If it exits 3 a second time, skip
     the judges, record the judge as "not measured: the controls failed their checks", and go to Step 4.
3. **Launch the judges.** Make one `Task(subagent_type: "kg-judge", …)` call per packet, all in one message so
   they run in parallel. Give each judge only its packet path and its verdict path:
   `Packet: <$J/packets/NN.md>. Verdict file: <$J/verdicts/NN.json>.`
   - Never tell a judge which arm is which, what the experiment tests, or that controls exist.
   - Never put anything from `$J/private/` into a judge's prompt.
4. **Aggregate** (Bash → harness), once every judge has returned:

   ```bash
   PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
   export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
   EXP="${CLAUDE_PROJECT_DIR}/.kg/experiment"; J="$EXP/judge-<RUN>"
   "$PY" -m kg_engine.harness judge-aggregate "$J" "$EXP/ideation_outputs.json" > "$EXP/judge_score-<RUN>.json"
   cat "$EXP/judge_score-<RUN>.json"
   ```

   It prints:
   - **`checks`**, three validity checks; if any fails, every judge verdict reads "not measured: the judge failed
     its validity checks (…)":
     - V1: the decoy was the least grounded item;
     - V3: the positive control scored 4 or more;
     - V1 and V3 must each hold in as many prompts as the sign test needs, 10 of 12;
     - V2: the arms' mean grounded score beat the decoys' by 1.0 or more.
   - **The verdicts**, keyed like the lexical ones (`verdict`, `control_verdict`, `generate_verdict`,
     `dpp_verdict`, `lightrag_verdict`). Each is decided on the judges' rankings by the same sign test.
   - **`means`**: grounded and useful per arm and per control. Also `mean_rank`, `first_by_label` (position
     balance) and `words`.
   - **`problems`**: a missing or malformed verdict drops its prompt, and is listed here.

---

## Step 4 — append to the log (then return, win or lose — §4)

Render the harness JSON as a Markdown table and append it, with the verdicts, the support check, the prompt
file and a UTC timestamp, to `${CLAUDE_PROJECT_DIR}/.kg/PROGRESS.md` (create the file with an
`# Experiment log` header if absent). Use a heredoc so the run is reproducible from the log:

```bash
PROGRESS="${CLAUDE_PROJECT_DIR}/.kg/PROGRESS.md"; mkdir -p "${CLAUDE_PROJECT_DIR}/.kg"
[ -f "$PROGRESS" ] || printf '# Experiment log\n\n' > "$PROGRESS"
{
  printf '\n## kg-experiment (Stage 8, method 0.12.0) — %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'Prompts: %s (%s): %s\n\n' "$N_PROMPTS" "$PROMPT_SOURCE" "$PROMPT_FILE"   # e.g. "12 (drafted from the graph): <path>"
  printf '| condition | n | novelty | support | grounded_novelty | diversity | utility | unsupported_rate |\n'
  printf '|-----------|---|---------|---------|------------------|-----------|---------|------------------|\n'
  # one row per condition, values pulled from the harness JSON above
  printf '| control | %s | %s | %s | %s | %s | %s | %s |\n' "$c_n" "$c_nov" "$c_sup" "$c_gn" "$c_div" "$c_util" "$c_unsup"
  printf '| graph | %s | %s | %s | %s | %s | %s | %s |\n' "$g_n" "$g_nov" "$g_sup" "$g_gn" "$g_div" "$g_util" "$g_unsup"
  printf '| graph+generate | %s | %s | %s | %s | %s | %s | %s |\n' "$gg_n" "$gg_nov" "$gg_sup" "$gg_gn" "$gg_div" "$gg_util" "$gg_unsup"
  printf '| graph+generate+dpp | %s | %s | %s | %s | %s | %s | %s |\n' "$gd_n" "$gd_nov" "$gd_sup" "$gd_gn" "$gd_div" "$gd_util" "$gd_unsup"
  printf '| rag | %s | %s | %s | %s | %s | %s | %s |\n' "$r_n" "$r_nov" "$r_sup" "$r_gn" "$r_div" "$r_util" "$r_unsup"
  # OPTIONAL row — emit only if the lightrag arm was present in the harness table (else skip it):
  [ -n "$lr_n" ] && printf '| lightrag | %s | %s | %s | %s | %s | %s | %s |\n' "$lr_n" "$lr_nov" "$lr_sup" "$lr_gn" "$lr_div" "$lr_util" "$lr_unsup"
  printf '\n**Verdict (graph vs rag):** %s\n' "$VERDICT"
  printf '\n**Control verdict:** %s\n' "$CONTROL_VERDICT"
  printf '\n**Generate verdict (graph+generate vs graph):** %s\n' "$GEN_VERDICT"
  printf '\n**DPP verdict:** %s\n' "$DPP_VERDICT"
  # OPTIONAL — only when the harness emitted a lightrag_verdict:
  [ -n "$LIGHTRAG_VERDICT" ] && printf '\n**LightRAG verdict:** %s\n' "$LIGHTRAG_VERDICT"
  printf '\n**Support check:** rag %s, control %s, gap %s (needs 0.10); probe drop %s\n' "$S_RAG" "$S_CONTROL" "$S_GAP" "$S_DROP"
  # one line per entry of the harness's "caveats", verbatim; none when the list is empty:
  printf '\n**Caveat:** %s\n' "$CAVEAT_1"
  # the evaluator-order check of Step 3: "verified", or "not verified: <problems>"
  printf '\n**Evaluator order:** %s\n' "$ORDER"
  # OPTIONAL — only when Step 3b ran: the judge's checks, means and verdicts, from judge_score-<RUN>.json
  if [ -n "$J_RAN" ]; then
    printf '\n**Judge (blind; grounded and useful, not novelty):** %s prompts judged; V1 %s of %s, V2 gap %s, V3 %s of %s; valid: %s\n' \
      "$J_N" "$J_V1" "$J_N" "$J_GAP" "$J_V3" "$J_N" "$J_VALID"
    printf '\n| item | grounded | useful | mean rank |\n|---|---|---|---|\n'
    printf '| %s | %s | %s | %s |\n' "$J_ITEM" "$J_GROUNDED" "$J_USEFUL" "$J_RANK"   # one row per item of "means"
    printf '\n**Judge verdict (graph vs rag):** %s\n' "$J_VERDICT"
    printf '\n**Judge control verdict:** %s\n' "$J_CONTROL_VERDICT"
    printf '\n**Judge generate verdict:** %s\n' "$J_GEN_VERDICT"
    printf '\n**Judge DPP verdict:** %s\n' "$J_DPP_VERDICT"
  fi
} >> "$PROGRESS"
```

(Each Bash call is a fresh shell: set those variables in the same block, from the harness JSON. Write the
caveat lines out, one per entry, or leave them out when `caveats` is empty.)

Then print a one-paragraph summary to the user:

- **When Step 3b ran and the judge's checks passed** (`valid: true`), the judge's `verdict` is the headline.
  Give it first, verbatim, with its wins out of the prompts and the arms' grounded and useful means. Then give
  the lexical verdicts below as a second reading.
- **When the judge did not run, or reads "not measured",** the lexical `verdict` stays the headline. If the
  judge ran, say why it is not measured.
- The lexical `verdict`, verbatim, with its wins and losses out of the prompts, and the arms' grounded
  novelty, novelty and support.
- When the evaluator-order check was not verified, say so, with its `problems`: the arms' blinding is not
  shown for this run.
- Every entry of `caveats`, verbatim, right after the verdict: each names something whose values in this run
  are not a result.
- The `control_verdict`, `generate_verdict` and `dpp_verdict`, verbatim.
- If the optional `lightrag` arm ran: the `lightrag_verdict` — whether `graph` beat the **published GraphRAG
  baseline**, the strongest comparison available (beating LightRAG, not just flat `rag`, is what shows
  grounding-with-falsification earns its keep against real graph retrieval).
- The **caveat from Step 0** if `falsification_counters.failed_or_rejected_edges == 0`: a graph with no
  recorded failures (§1.7) makes `graph` look cleaner than it has earned; recommend running `/kg-ground` with
  the adversarial grounder before trusting a `graph`-wins verdict.
- Path to the appended log: `${CLAUDE_PROJECT_DIR}/.kg/PROGRESS.md`, and to the saved prompt file.

**Execution proceeds regardless of the verdict (§4).** A "did NOT clearly beat" or a "not measured" result is
a legitimate, logged outcome — it is *negative information* about the pipeline itself, not an error. Do not
retry, re-shuffle to fish for a win, or hide the row. Report it and stop.
