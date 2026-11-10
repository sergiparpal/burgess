# Changelog

## 0.11.8 — 2026-11-10

Found while reviewing the first field `/kg-experiment`, on the Windows corpus with 0.11.7: eight Spanish
documents, 445,018 characters. Its numbers were right: `harness ideation` on a copy reproduced the score
file exactly. All three verdicts were negative, but the table said less than it seemed to, and the run
waited on the shell.

### Fixed

- **The hallucination guard was blind, and nothing said so.**
  - `unsupported_rate` was 0.0 in every arm. A sentence counts as supported when any of its first three long
    words occurs anywhere in the source, and a corpus that size holds nearly every ordinary word.
  - A sentence invented outright, "El sistema Zorblax de Quantifex redujo las reversiones un 93 % en 2019",
    passed, and so did an English version. On the 2,741-character demo corpus the same sentences are caught.
  - `harness ideation` now adds `guard_probe` and `caveats` to its output. The probe re-checks every
    sentence the guard judged, in every arm, with its first long word replaced by an invented one. When 90 %
    or more still pass, a caveat says the column was not measured, and that the verdicts' unsupported-claim
    check could not have caught an arm that invents things.
  - On the field run 140 of 143 passed. On the demo corpus, English ideas pass at about 0.57.
  - The rule itself is unchanged. What the verdict should measure is a separate decision.
- **utility measured nothing on a Spanish corpus.** Its markers are the English words `because`, `if`,
  `therefore`, `bridge` and `connect`, and since 0.11.4 the prompts are drafted in the corpus's language. When
  no arm's ideas contain one, a caveat now says the column is 0 everywhere and says nothing. It is not part of
  any verdict.
- **Words lost their letters outside ASCII.**
  - The tokenizer behind every harness count and the projector's node specificity was
    `[A-Za-z][A-Za-z0-9_-]{1,}`. So "revisión" counted as "revisi", "Ámbito" as "mbito" and "más" not at
    all. That happened in every idea and in 214 of the graph's 425 node labels.
  - Words are now runs of Unicode letters. On ASCII text the two patterns find the same words.
  - Re-scored, the field run's numbers moved by at most 0.007 and its verdicts held.
  - Re-projected, 158 node specificities changed. The specificity gate, the top ten weighted bridges and
    `kg_generate`'s slate stayed the same.
  - `PROJECTION_RULES` is now "3", so an index built by an older plugin is rebuilt once.
- **The evaluator needed the shell.**
  - The kg-evaluator had `Read`, `Grep` and `Bash` but no `Write`, so it wrote its files through heredocs.
    Two of 25 KB failed to parse.
  - It built the `rag` arm with its own retrieval script, which crashed twice on the Windows console's cp1252
    encoding. No later run could reproduce the passages it picked.
  - In all: 14 shell calls and 9 approvals. One approval waited 26 minutes.
  - New `python -m kg_engine.harness rag-slices PROMPTS SOURCE OUT_DIR [BUDGET_TOKENS]` builds the `rag` arm's
    context the same way on every run. It uses BM25 over the source's paragraphs, with accents folded and no
    stopword list. It takes the best passages within the 2000-token budget the graph arm's `kg_context` call
    gets, and writes one Markdown file per prompt plus an `index.json`.
  - `/kg-experiment` runs it in a new Step 1b, after it has saved the prompts.
  - The evaluator now has `Read` and `Write` and its three MCP tools, and no shell or `Grep`.
- **The evaluator's procedure contradicted its blinding.**
  - It opened with "get to know the source", grepping and reading it, before the control pass that must use
    no file. The field evaluator wrote its control answers first anyway.
  - Control now comes first, before any tool call. Each other arm answers from its own context only, and the
    `rag` arm from its file of passages.
- **The two generate arms could get different slates.**
  - `graph+generate` took `kg_context`'s stored `hypotheses[]` when the graph held any. The DPP arm reorders a
    `kg_generate` call's candidates and could not reorder those, while the `dpp_verdict` assumes one set.
  - Both arms now take their slate from one `kg_generate(mechanism="all", k=12)` call.
  - The field run did this already, because its graph held no proposals.
- **"k=12 ignored".** The field run read `kg_generate`'s 51 candidates as `k` being ignored. `k` is per
  mechanism (12 bridge, 12 periphery, 11 regroup, 10 transplant, 4 compression, 2 seed); the tool description
  now says so.
- **Smaller fixes to `/kg-experiment`:**
  - Step 0 prints the run's timestamp, which names its files, and probes the optional LightRAG arm.
  - When that arm is available, the command runs its helper itself, since the evaluator has no shell.
  - The prompt file is written with `Write`.
  - The log entry gains the `graph+generate+dpp` row, the DPP verdict and the caveats.
- `docs/COMMANDS.md` still said that the default prompts are the demo's on any corpus. Since 0.11.4 they are
  drafted from the user's graph.

### Tests

- `tests/test_fix_experiment_measurement.py` (36 tests):
  - **the evaluator:** has exactly `Read`, `Write` and its three MCP tools, and no bash block. It writes its
    control answers before any tool call, answers the `rag` arm from its file of passages, reads its JSON back,
    and takes both generate slates from `kg_generate`.
  - **the command:**
    - Step 0 prints the run and probes LightRAG, and the prompt file is written with `Write`;
    - Step 1b runs `rag-slices` before the evaluator, and adds the LightRAG answers only in its second block;
    - the log and the summary carry the caveats and the DPP verdict.
  - **`kg_generate`:** its description says `k` is per mechanism.
  - **the tokenizer:**
    - keeps accented words whole and finds ASCII words exactly as before;
    - node specificity reads an accented label whole;
    - `PROJECTION_RULES` is "3".
  - **the caveats:**
    - the field case (an invented sentence passes a large source) is reported blind, while the demo corpus
      catches it and is not;
    - the probe judges the same sentences as the guard;
    - the utility caveat appears only when no arm uses a marker;
    - a caveat never changes a verdict.
  - **`rag-slices`:**
    - folds accents and ranks the matching passage first, keeping a heading with its paragraph;
    - cuts long paragraphs without losing a word, and keeps to the budget;
    - writes one file per prompt and an index, with no scores in what the evaluator reads;
    - reads prompts as the LightRAG arm does;
    - refuses to write into the source folder, and errors cleanly on bad input;
    - gives the same bytes under two hash seeds, and prints on a cp1252 console.
  - **Against 0.11.7:** 34 fail. The other 2 check that ASCII text tokenizes as before.
- `tests/test_fix_field_eval_experiment.py`: the evaluator leaves the "every block that runs Python resolves
  it first" check, since it has no shell. The LightRAG `--source` check moves to the command, which now runs
  that helper.
- 1863 → 1898 passed, 3 skipped.

## 0.11.7 — 2026-11-10

Found while reviewing the first field `/kg-eval`, on the Windows corpus with 0.11.6. Its numbers were right:
precision 0.84 and α 0.901 both check out against its CSVs. But three things went wrong around them.

### Fixed

- **The log became a source document.**
  - Since 0.11.4, `/kg-eval` and `/kg-experiment` appended their results to `PROGRESS.md` at the top of the
    project. The source can be the project folder itself, as it is on the Windows corpus, and every `.md` at
    the top of a source folder is one of its documents.
  - So the log became a ninth document, and the source grew from 84 sections to 85. The next `/kg-build`
    would have extracted it. `/kg-experiment`'s `rag` arm and its scoring would have read it as source.
  - Both commands now write `.kg/PROGRESS.md`. `SourceSet` never reads a dot folder, not even through a
    recursive glob.
  - New `python -m kg_engine.harness legacy-log PROJECT SOURCE` prints a note when an earlier version's log
    is still one of the source documents. Both commands run it first:
    - `/kg-eval` passes the note on and goes on;
    - `/kg-experiment` passes it on and stops, because the run would take that log for source.
  - Burgess never moves or deletes the old file. That is the user's call.
- **The annotators needed the shell.**
  - The annotator had `Read`, `Grep` and `Bash`, and was told to write the CSV with Bash. All three passes
    also searched the documents with shell `grep` and `sed`.
  - In a setup that asks before every shell command, they cost the user 74 approvals (34, 28 and 12), plus 7
    from the command itself. Each annotator worked six or seven minutes, and for 51 of the run's 56 minutes
    one of them was waiting.
  - The annotator now has `Read`, `Grep` and `Write`. It writes its labels as one JSON object,
    `{edge_id: {verdict, span_found, notes}}`.
  - New `f4_probe.py fill SHEET LABELS` writes the labels into the sheet with the csv module's quoting. It
    takes the file whole or not at all: a missing row, an edge the sheet lacks, a verdict outside the
    vocabulary or a `span_found` other than yes/no leaves the sheet unchanged and lists the problems.
  - `/kg-eval` fills each sheet before it scores it or computes α.
- **The advice did not hold for the current plugin.**
  - The run recommended four extractor rules: a precondition is `enables`, a bias of a figure is
    `confounded_by`, the case grounds the principle, and so on. The extractor has carried them since 0.8.0
    to 0.11.0.
  - Of the 13 edges labeled other than `correct`:
    - 9 were first-build extractions from 2026-11-07, before 0.8.0;
    - 3 were counter-edges from adversarial passes;
    - 1 was a lead written before 0.11.0.

    Grounding had already rejected 11 of them.
  - New `python -m kg_engine.harness writers LABELS PROJECT` reads each labeled edge in the canon. It splits
    the sample by writer (`extractor`, `lead`, `counter-edge`, `proposal`, from the mark its notes open with)
    and by the verdict the edge holds now, and it lists the edges labeled other than `correct`.
  - The canon does not record which plugin version wrote an edge. So, before recommending a refinement,
    `/kg-eval` now reads the current contract: `agents/extractor.md` and `pack/pack.yaml`, or
    `agents/adversarial-grounder.md` for a counter-edge. When the rule is already there, it says that the edge
    predates the rule.
- **The log block left the model's text to the shell.** `/kg-eval` appended through an unquoted heredoc, so a
  backtick in the model's text, such as a relation name in code format, would have run as a command. The text
  now goes through a quoted heredoc, and only the date and the graph path are expanded. The field run escaped
  its backticks by hand.
- `docs/COMMANDS.md` still described the graph path from before 0.11.4, and said that `/kg-eval` always
  re-extracts. It now says that an installed plugin only recommends.

### Tests

- `tests/test_fix_eval_log_and_annotator.py` (46 tests):
  - **the log:** no user-facing text points the log at the top of the project; both commands append under
    `.kg/` and run `legacy-log` in their first block;
  - **`legacy-log`:** notes a log the source reads and leaves it byte for byte; stays silent for a one-file
    source, another folder, or a log under `.kg/`;
  - **`SourceSet`:** reads a top-level `PROGRESS.md` (the field case) but never `.kg/`;
  - **the annotator:** has exactly `Read`, `Grep` and `Write`, no bash block, and a JSON example that `fill`
    accepts; every pass writes its own labels file, and `/kg-eval` fills before it reads;
  - **`fill`:** keeps every other column and the row order; the problems it refuses leave the sheet unchanged;
  - **`writers`:** sorts the five writers and three states out of a seeded canon, skips an unlabeled row,
    names an edge the canon no longer holds, and refuses a project with no canon without laying one out;
  - **`/kg-eval`:** checks a refinement against the current contract;
  - **the extractor:** the four rules the field run recommended are in it;
  - **the log block:** run in bash, it keeps backticks and `$HOME` as written.
  - **Against 0.11.6:** 22 fail. The other 24 are checks that already held there: the files that never
    named the old path, the `SourceSet` behaviour and the extractor rules.
- `tests/test_fix_field_eval_experiment.py`: the log path moves under `.kg/`. The annotator leaves the
  "every block that runs Python resolves it first" check, since it has no shell.
- 1818 → 1863 passed, 3 skipped.

## 0.11.6 — 2026-11-10

Found while checking the re-run of the field `/kg-query` on 0.11.5. To find the source's hypothesis codes, the
session searched `query_graph(text="h1 h2 … h20")`. The engine searched only `h1` to `h12`, as its
`query_terms` showed. The answer did not suffer, since it reached H16 through other edges. But nothing told the
model that a search has a word limit.

### Fixed

- **The word limit of a search is now stated.**
  - `kg_context(query=…)` and `query_graph(text=…)` search on the first 12 search words and drop the rest. The
    limit (`_QUERY_TERM_CAP`) bounds the work per row, and it stays.
  - `/kg-query` now says so, in the `kg_context` step and the `query_graph(text=…)` step. It also says to split
    a longer list, such as `H1` to `H20`, over several searches, and to check `query_terms` in each result.
  - `tools.md` (§1.7 and §1.11), `docs/ARCHITECTURE.md` §3.5 and both tool descriptions state the limit too.
    A `query_terms` list shorter than the words asked for means the rest were dropped.

### Tests

- `tests/test_fix_query_word_limit.py` (4 tests):
  - the field search keeps `h1` to `h12`;
  - `/kg-query`, the tool reference, the architecture document and both tool descriptions state the limit,
    each with the number taken from the constant, so the text cannot drift from the engine.
  - **Against 0.11.5:** 3 fail. The fourth is the engine-side guard, which holds there too.
- 1814 → 1818 passed, 3 skipped.

## 0.11.5 — 2026-11-10

Found while reviewing a `/kg-query` on the Windows corpus (425 nodes, 221 edges). The question was «¿En qué
condiciones se puede retirar la revisión humana del código?». The answer was faithful: all 55 edges it cited
match the graph, spans included. But `kg_context` had given it 18 edges, of which it used 5. So it read
`canon/` through the shell 19 times, each command waited for the user's approval, and the run took two hours.

### Fixed

- **`kg_context` did not rank by relevance.**
  - A query was only a filter. Every run of three or more characters was a term, matched as a substring of
    the edge's ids, relation and span. «del» matched 37 of the 61 hits, inside «modelo» as well. «revisión»
    and «código» never matched the accent-free ids (`retirar-revision`), and node labels were not searched.
  - The fill then ordered the hits by state, the extractor's confidence (0.7/0.6/0.5) and id. The edge the
    question was about, `comprobadores-deterministas --enables--> retirar-revision` (0.6), came 24th, and
    the 2000-token budget held 18.
  - A query now matches **search words**. They are `/kg-build`'s content words: case, accents and plural
    endings are ignored, and Spanish and English function words are dropped. Two-character codes such as
    `N4` count too.
  - An edge matches on its span, its relation, and both endpoints' ids and labels. Matches rank by the rarity
    weight of the words they share, the IDF `/kg-build` already ranks node names by. Grounded edges still
    come before unverified ones, and a tie keeps the old order.
  - On a copy of the field index that edge now comes first. 9 of the 19 edges that fit are ones the answer
    cited.
- **Nothing said what the budget left out.**
  - `kg_context` now returns `items_total` and `hypotheses_total`: every edge that qualified for each lane.
    On the field question, 19 of 43 fit.
  - It also returns `query_terms`, the words it searched on.
  - `/kg-query` asked the model to "note if you were truncated", which it could only guess.
- **No read tool found a node by what it says.**
  - `query_graph` gains `text`. It keeps the nodes whose id or label, and the edges whose span, relation or
    endpoints, share a search word with it, ranked the same way, and returns `query_terms` and `matched`
    counts.
  - It also finds nodes with no edge yet, which `kg_context` cannot return. The field session grepped
    `^label:` in `canon/` for those.
- **`/kg-query` misread an axis.**
  - It said that an edge with `authored_by: agent` "has not yet been confirmed by a verdict". Every
    extracted edge is agent-authored for life. `epistemic_state` is the verdict, so a grounded edge has one.
    The session went to the canon to check `verdict_by`.
  - The text also called every span a substring of `examples/source.md`, instead of the configured source.
  - It also forbade presenting "an inferred edge" as fact, although a grounded edge with inferred
    provenance is one. It now says "unverified".
- **`/kg-query` now says which tool finds what.**
  - When `items_total` exceeds what the model got, it raises `budget` or narrows the question.
  - The model answers from the tools and does not read `canon/` through the shell, which in many setups
    waits for the user's approval at every command.
  - `query_graph(text=…)` goes in the documents' language. A first headless run translated its text into
    English, after an English example in the command, and matched 2 nodes on the Spanish canon.
- **Checked headless on a copy of the field canon.** `/kg-query` asked the same question with these changes,
  with Bash denied by default.
  - **First run:** 9 tool calls in 40 s, and no shell command tried. It saw 19 of 43 matches and called
    `kg_context` again with a larger budget.
  - **Second run, after the language note:** 6 tool calls in 31 s. Its `query_graph` text was in Spanish and
    matched 39 nodes. It presented the edgeless ones, such as `no-retirar-revision-hoy`, as concepts with no
    verified claim.
  - Both runs left the canon byte-identical.

### Changed

- **The cost of a query.** `kg_context` now reads every edge of the lane once and ranks it in Python. That
  takes about 5 ms on the field canon and about 100 ms on 10 000 edges.
  - The PreToolUse hook gets the same ranking for its Grep pattern or file name.
  - `buildplan._fold` drops combining marks with one `str.translate` instead of a per-character loop. That
    loop was half the cost of a search. The output is unchanged, checked over every code point.
- **Edge cases.**
  - A query made only of spaces is now no query, as an empty one was.
  - A query made only of function words now matches nothing. Through 0.11.4, «del» matched every edge that
    contained it.
- **`/kg-experiment`.** Its graph arm calls `kg_context(query=<prompt>)`, so that arm's context is now ranked
  by relevance too. A run made with 0.11.4 is not comparable on that arm.

### Tests

- `tests/test_fix_query_relevance.py` (28 tests):
  - **What a query matches:** function words; words inside other words; accents and case; endpoint labels;
    plurals; letter-digit codes; Cyrillic; a blank query.
  - **Ranking:**
    - relevance comes before confidence and id (the field case in miniature);
    - rarer words, then more words, rank first;
    - grounded edges still come first, and equal matches keep the old order;
    - a full rebuild gives the same ranking;
    - the hypothesis lane is ranked too.
  - **Totals:** the counts, the order without a query, and the term cap.
  - **`query_graph(text=…)`:** it finds edgeless nodes, `limit` keeps the true count, it combines with the
    other filters, and without text nothing changes.
  - **The MCP tools:** signatures and fields; positional calls still work.
  - **`_fold`:** the same string as before over every code point.
  - **Text:** `/kg-query` and `tools.md`.
  - **Against 0.11.4:** 23 fail. The other 5 hold there too: Cyrillic matching, plus four guards (grounded
    first, the tie order, determinism, `_fold`).
- `test_review_r6.py` F6 and `test_review_r9.py` L10 pinned the SQL shape of the old `LIKE` clause. They now
  pin the same regressions through the new term extractor: at most 12 terms, and Cyrillic terms are
  extracted.
- 1786 → 1814 passed, 3 skipped.

## 0.11.4 — 2026-11-10

Found when the user asked what else to try on the Windows corpus. `/kg-eval` and `/kg-experiment`, and the
two subagents they drive, were written for a development checkout. On an installed plugin they would have
failed or measured the wrong thing. The user had not run either yet.

### Fixed

- **The commands named an interpreter that does not exist on Windows.**
  - Every Python step named `/home/sergi/Burgess/.venv/bin/python`, a checkout on no user's machine, or
    `${CLAUDE_PLUGIN_DATA}/.venv/bin/python`. On Windows the venv's interpreter is
    `.venv\Scripts\python.exe`.
  - The new `scripts/engine_python.mjs` prints the interpreter by the launcher's own rule
    (`_engine_resolve.mjs`). Every Bash block that runs the engine resolves it first, since each Bash call
    is a fresh shell. On the user's machine it prints the interpreter the launcher logs.
  - The operating guide's CLI reference (`tools.md` §2) and `pack-schema.md` carried the same paths.
- **Paths that are never filled in.**
  - Claude Code fills in only the exact `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` and
    `${CLAUDE_PROJECT_DIR}` tokens (read from the 2.1.316 binary). The commands used `${VAR:-default}`
    forms, which reach the shell untouched.
  - So `/kg-eval` looked for its graph in `<project>/.kg-data/derived/graph.json` and would have told the
    user to run `/kg-build` first, and `/kg-experiment` wrote its outputs under `/tmp`.
  - `/kg-generate` had the same form: its absorption ledger would have landed in `<project>/.kg-data/derived`,
    where `kg_absorption` never looks. It is fixed here too.
  - Each path is now an exact token: the derived graph and the ledger in `${CLAUDE_PLUGIN_DATA}/derived`;
    `PROGRESS.md` and the run's files in the project, under `.kg/eval/` and `.kg/experiment/`.
- **A source that is a folder.**
  - The configured source can be a folder of documents; the Windows corpus is eight in one. The commands
    read the repo's `examples/source.md` instead.
  - `harness specificity` and the LightRAG arm read the path with `read_text`, which fails on a folder.
    They now read it as `SourceSet(path).concat`, the projector's own input, so the specificity gate's IDF
    corpus is the projector's for a folder too. A single file reads byte for byte as before.
  - `harness ideation` takes the source as a second path, so the evaluator no longer pastes the corpus into
    its JSON.
  - The LightRAG arm keyed its index rebuild on `stat()` of the path, which misses an in-place edit inside a
    folder. It now uses the per-document signature.
  - The annotator reads the document that each row's `source_file` names.
- **The experiment's default prompts were about the demo corpus.**
  - On any other corpus they asked about concepts the graph does not hold, every arm answered from the
    model's prior, and the verdict measured nothing.
  - They are now used only when the source is the plugin's own `examples/source.md`. Otherwise the command
    drafts 12 prompts of the same kinds from the user's graph (`kg_agenda` and `kg_context`), in the
    corpus's language. It saves them under `.kg/experiment/` and shows them, and a rerun can pass that file
    to repeat the experiment.
- **Below target, `/kg-eval` edited the plugin and rebuilt the canon.**
  - Its auto-iterate loop edited `pack.yaml` and `agents/extractor.md` and re-ran `/kg-build`. In an
    installed copy that edits one version's cache, which every project shares and the next update replaces,
    and it rewrites the user's canon.
  - Now an installed copy (under `plugins/cache`) records the refinements it would make. Only a development
    checkout edits and re-extracts.
- `/kg-eval` first asks the engine for a fresh projection (`query_graph`), because every session on the
  machine shares the derived dir.

### Tests

- `tests/test_fix_field_eval_experiment.py` (66, most of them per-file checks):
  - every `${CLAUDE_*}` in commands, agents and skills is a token Claude Code fills in, with no default form;
  - no development path and no spelled-out venv interpreter;
  - every Bash block that runs the engine resolves the interpreter first;
  - what `/kg-eval`, `/kg-experiment`, both subagents and `/kg-generate` read and write;
  - `engine_python.mjs`: the pointer, the conventional path, `KG_ENGINE_VENV`, nothing provisioned, an
    unfilled token;
  - the harness reads a folder exactly as the projector does and a file byte for byte as before, and an
    empty folder is a clean error; `ideation` scores against a source given by path; the LightRAG signature
    sees an in-place edit inside a folder.
  - Against 0.11.3, 29 fail. The other 37 hold there too: per-file checks on texts that were already clean,
    plus two guards (a single file reads as before, and an embedded source still scores without a path).
- `tests/test_launchers.py` also runs `node --check` on `engine_python.mjs`.
- 1719 → 1786 passed, 3 skipped.

## 0.11.3 — 2026-11-10

Found while reviewing a `/kg-view` run on the Windows corpus: 425 nodes and 221 edges, of which 162 grounded,
58 rejected and 1 failed. `graph.html` matched the canon. `GRAPH_REPORT.md` had two gaps.

### Fixed

- **A list that stopped at its cap did not say so.**
  - The report lists at most 50 failed or rejected edges, 50 stale verdicts and 50 re-examinable verdicts. Each
    section header gives the total, but past 50 the list just stopped. On the corpus the falsification memory
    said 59 and listed 50.
  - Now a list that stops at 50 ends with a line saying how many more there are. The falsification list adds
    that `graph.html` draws them all.
- **Single-node communities buried the report.**
  - Every community had its own entry, and a node with no live edge is a community of its own. On the corpus
    172 of the 264 communities had a single node, and their entries made up most of the report.
  - Now they share one entry, after the other communities. It gives their count, the first 50 names and how
    many more there are, their axes, the edges inside them, and how many have degree 0. A hand-edited self-loop
    is the only edge one of them can hold, and the entry still shows it.
  - Nodes with no community keep their own entry, last, as before.

### Tests

- `tests/test_fix_report_caps.py` (10):
  - A falsification, stale or re-examinable list past 50 ends by saying how many more there are. A list of
    exactly 50 does not.
  - Single-node communities share one entry. It lists up to 50 names and says how many more there are, and it
    keeps a self-loop visible. Nodes with no community keep their own entry, last. Every node is counted once.
  - End to end, the real projector leaves the two endpoints of a failed edge in communities of their own, and
    the report groups them.
  - Against 0.11.2, 7 of the 10 fail. The other 3 pin what must not change: no closing line at exactly 50, no
    shared entry without single-node communities, and every node counted once.
- 1709 → 1719 passed, 3 skipped.

## 0.11.2 — 2026-11-09

Found while checking the Windows install after 0.11.1. Its `server.log` showed two sessions running engines at
once, a desktop session in another folder on 0.11.0 and the prueba-burgess terminal session on 0.11.1, both in
the same plugin data dir.

### Fixed

- **Sessions shared one readiness marker.**
  - The supervisor (`scripts/launch_server.mjs`) tells a crash after the engine served `initialize` from a crash
    during startup by a marker the engine writes as its serve loop comes up. After a post-init crash it exits, so
    the client reconnects. After a startup crash it rebuilds the venv once and relaunches in place.
  - Every engine wrote that marker as `.engine-ready` in `KG_DATA`, and an installed plugin sets `KG_DATA` to
    `CLAUDE_PLUGIN_DATA`, one dir for every session on the machine. A supervisor deleted the marker before each
    spawn, and an engine deleted it as it shut down cleanly, whichever session had written it. A marker another
    session's engine had just written passed for this one's.
  - So when another session started or stopped its engine at the wrong moment, a crash in an engine's first 20 s
    could be read either way wrong. A post-init crash could pass for a startup failure: a venv rebuild nobody
    needed, then a relaunch onto a connection the client had already set up. A startup failure could pass for a
    post-init crash, with no self-heal. It had not happened: all 21 exits in that log were clean.
  - Now the supervisor names a fresh file for each spawn and hands its path to the engine in `KG_READY_MARKER`.
    The engine writes and removes only that file. The supervisor reads it once the child has exited, then removes
    it. An engine started without a supervisor writes no marker.
  - A supervisor removes markers more than an hour old as it starts, the shared marker of earlier versions
    included. A marker only matters for an exit in its engine's first 20 s, and an old one is left only by an
    engine killed together with its supervisor.
  - Sessions still on 0.11.1 or earlier keep sharing their marker among themselves until they update. A 0.11.2
    session neither reads nor clears it, except to sweep it once it is an hour old.

### Tests

- `tests/test_fix_shared_ready_marker.py` (11):
  - The engine writes its marker only where its supervisor said, writes none without a supervisor, and leaves
    other engines' markers alone when it shuts down.
  - Each spawn gets a new marker in `KG_DATA`, and the loop reads and removes only the marker it handed that
    child. The sweep removes only readiness markers more than an hour old.
  - End to end, with the shipped launcher and a stand-in engine:
    - a fast crash after serving is post-init;
    - a startup failure stays one while another session's engine writes its marker, and gets its venv rebuild;
    - a supervisor leaves other sessions' fresh markers alone and sweeps stale ones.
  - `docs/ARCHITECTURE.md` names `KG_READY_MARKER`.
  - Against 0.11.1, with `READY_MARKER_ENV` replaced by its value in the test, all 11 fail. There the end-to-end
    startup failure is logged as `servedInit=true -> post-init-exit`.
- `tests/test_review_r5.py` pins `READY_MARKER_ENV` across Node and Python, in place of the old marker name.
- 1698 → 1709 passed, 3 skipped.

## 0.11.1 — 2026-11-09

On 0.11.0 the Windows corpus applied the user's decisions after re-judging its first pass. The re-judge had
rejected three grounded edges as `wrong-node`, each with a lead to a new node. The user ruled that each node
already named what its span names, and a grounder grounded the three edges again. Their leads stayed in their
notes.

### Fixed

- **An overturned lead could come back as pending.**
  - `kg_ground_plan` and `/kg-build --leads` read a rejected edge's lead from its notes. They took the newest
    `lead:` segment, whatever verdicts came after it.
  - So if a later re-judge rejected one of those three edges without a lead, as `vague` for instance, the plan
    would offer the lead the user had ruled out, and `/kg-build --leads` would write it. For
    `e_zalando__grounds__autonomia-n4-a-escala`, that lead names a node that duplicates the N4 claim.
  - Now a lead belongs to the rejection that recorded it. A verdict that changes an edge's state and records no
    lead of its own withdraws the lead the notes hold: `kg_ground` appends `lead: none` after the note, and
    returns the withdrawn lead as `lead_withdrawn`.
  - A verdict that keeps the state keeps the lead, as it has kept the time since 0.10.2. A lead that a verdict
    records still replaces the old one.
  - The three field edges need nothing done. Being grounded, their leads are not pending, and the next verdict
    that changes their state withdraws them.

### Tests

- `tests/test_fix_overturned_lead.py` (11):
  - The field case: an edge rejected with a lead, grounded again, then rejected without a lead offers no lead.
  - The verdict that overturns a rejection withdraws its lead, and so does any other change of state.
  - A lead overturned before 0.11.1, with no `lead: none` in its notes, is withdrawn when the edge is rejected
    again.
  - A re-confirmed rejection keeps its lead, and a new lead replaces the withdrawn one. A lead is withdrawn once,
    and a change of state with no lead to withdraw adds nothing to the notes.
  - `lead_of` reads `lead: none`, and the tool docstring and the references document it.
  - Against the 0.11.0 engine, with `LEAD_NONE` defined in the test, 8 of the 11 fail. The other 3 pin what
    stays the same.
- 1687 → 1698 passed, 3 skipped.

## 0.11.0 — 2026-11-09

On 0.10.2 the Windows corpus judged again the 142 grounded edges of its first pass, under the current
contract: first a sample of 20, then the other 122. 20 changed: 14 as `wrong-node`, 4 as `wrong-relation`, 1 as
`vague` and 1 as `no-support`. The 122 that stayed grounded kept their times, as 0.10.2 intended, so no attacked
hub came back. The pass also showed that grounders read `confounded_by` more widely than its definition.

### Changed

- **`confounded_by` is a confound that biases a figure.**
  - The relation table said "the inflated metric/value | the confound that inflates it". Grounders in several
    batches ratified eight `confounded_by` edges whose confound does not inflate the figure: equivalent mutants
    lower a mutation score, a denominator moves a usage figure both ways, and a share taken over comments
    instead of reviews counts something other than what it claims to.
  - The pack has no other relation for such confounds, so a literal reading would have rejected true claims as
    `wrong-relation`, with no lead.
  - The table that the extractor and the grounder share now reads "the biased metric/value | the confound that
    biases it", and says that a confound may inflate the figure, lower it, or make it count something else. The
    pack comment, its schema reference and the adversarial contract say the same.
  - The generality confound still inflates betweenness: inflation stays one case of a confound.

### Tests

- `tests/test_fix_confounded_by_bias.py` (10):
  - Both contracts' table row, and the sentence on a confound that lowers a figure or changes what it counts.
  - No contract or pack text says that a confound only inflates.
  - The pack comment and its schema reference agree.
  - The adversarial contract's worked counter-edge still reads the generality confound as inflation.
  - Against the 0.10.2 texts, all ten fail.
- 1677 → 1687 passed, 3 skipped.

## 0.10.2 — 2026-11-09

The Windows corpus converged on 0.10.1: 416 nodes and 203 edges, every edge with a verdict. But 142 of its 162
grounded edges were judged on 0.6.x/0.7.0, before the rules on tables and on what each node names. Judging
them again under the current contract would have reopened hubs that had already been attacked.

### Fixed

- **Re-confirming a claim reopened an attacked hub.**
  - `kg_ground_plan` leaves out a hub that an adversarial pass has attacked until one of its claims is
    grounded after the attack. It reads the time a claim was grounded from the edge's `verdict_at`.
  - `kg_ground` stamped `verdict_at` on every call. A verdict that kept a grounded claim grounded made that
    claim look newly grounded, so the next `/kg-ground` would attack the hub again with nothing new to find.
  - Now a verdict that leaves an edge's state unchanged keeps `verdict_by` and `verdict_at`, which record who
    put the edge in its state, and when. The verdict's note and lead are still appended, and the audit log
    still records the call at its own time. A change of state stamps both fields, as before.
- **Re-sealing a counter-edge moved its attack mark.** Re-sealing a rejected counter-edge with a lead moved
  the hub's attack mark to the time of the re-seal. If a claim had been grounded between the attack and the
  re-seal, the hub stayed out of the plan when it should have come back. The mark now keeps the time of the
  attack.

### Tests

- `tests/test_fix_same_state_reverdict.py` (9):
  - A re-confirmed claim keeps its hub out, whether a ledger record or counter-edges marked the attack.
  - The audit log records the re-verdict at its own time.
  - A change of state still stamps the time, and a claim grounded again after a rejection reopens its hub.
  - A re-sealed rejected edge or counter-edge keeps its time.
  - A re-confirmation keeps who put the edge in its state.
  - An edge in a verdict state with no time gets one.
  - Against the 0.10.1 engine, the five tests that pin the fix fail.
- 1668 → 1677 passed, 3 skipped.
- **Checked on a copy of the field canon:** we re-confirmed one grounded claim of `radar-meta` and one of
  `autonomia-n4-a-escala`. On 0.10.1 that put both hubs back in the plan. On 0.10.2 the plan stayed empty. The
  copy was deleted.

## 0.10.1 — 2026-11-08

The six merges on the Windows corpus went as planned: 410 nodes and 194 edges, every verdict kept. But a Grep
made right after them was shown the edges of two nodes the merges had retired.

### Fixed

- **The precontext hook showed a stale graph above 400 notes.** The hook on Grep, Glob and Read reads the
  derived index, and a write tool such as `kg_merge` leaves that index stale until the server's next read
  reprojects it. The hook reprojects by itself only up to 400 notes, because it is killed at 5 s. Above that it
  served the stale index without saying so. It now runs the projector's staleness check, which needs no
  projection and re-reads only the notes that changed. While the index is stale, the hook injects nothing, and
  it serves the index again once a server read has reprojected it. Up to 400 notes nothing changes: the hook
  reprojects as before.

### Tests

- `tests/test_fix_precontext_stale.py` (6): above the gate, a fresh index is served, and a stale one is not,
  after a merge, a verdict change or a source edit. An mtime-only touch keeps the context, and below the gate
  the hook still reprojects. Against the 0.10.0 hook, the three stale cases fail.
- 1662 → 1668 passed, 3 skipped.
- **Checked on a copy of the field canon** (410 notes): the hook served the fresh index, fell silent after a
  rename, and served the renamed node once a server read had reprojected. The 0.10.0 hook showed the retired id
  at the same step. A hook call took 0.13 s in WSL, against 0.08 s before. The copy was deleted.

## 0.10.0 — 2026-11-08

The fourth `/kg-ground` on the Windows corpus, the first on 0.9.0, judged the ten leads `/kg-build --leads` had
written, and grounded nine. It also showed two gaps. An attack that found nothing to write left no mark, so the
plan would have offered the same hub to an attack on every later pass. And two grounders ruled one span two ways,
one of them by a cue from the user's memory notes that no contract has.

### Added

- **`kg_record_attack(hub_id, question, reason)`.** The adversarial grounder calls it for each hub it attacked
  without writing a counter-edge, with the falsifying question its attack ended with and its decline tag
  (`no-span` or `vague`). The engine appends one line to `<project>/.kg-hub-attacks.jsonl`, and `kg_ground_plan`
  counts the record like a counter-edge judged at that time: the hub stays in `attacked_hubs` until it gains a
  newer grounded claim. The record sets no state. The ledger is git-excluded engine state, read fail-open, so
  losing it only offers those hubs again. The MCP surface goes from 31 to 32 tools.

### Fixed

- **A hub attacked without a counter-edge came back on every pass.** Since 0.8.0 the plan remembers an attack
  by the mark on each counter-edge, and 0.8.0 accepted that an attack with nothing to write leaves none. The
  0.9.0 leads made that common. The grounders had rejected both counter-edges on `escribir-codigo-parte-pequena`,
  one of them with a lead whose span is the source's own support for the hub. Once that lead was written and
  grounded, the plan offered the hub again. The re-attack searched eight documents, found nothing and, again,
  left no mark. The adversarial contract and `/kg-ground`'s template now ask for the record.
- **Grounders split on «por eso».** One grounder sealed «O puedes bajar la variedad del entorno hasta que el
  controlador que sí puedes construir sea suficiente. Por eso funcionan los robots industriales» as a `grounds`
  lead. The next one rejected that edge for `enables`. The relation block now says that a connective does not
  decide between the two: «por eso», «porque» or «así que» says that the HEAD explains the TAIL, and what the
  HEAD does for the TAIL decides. A reason to believe the TAIL is `grounds`; the means that makes it possible,
  or makes it work, is `enables`. The block's gloss of `grounds`, "the HEAD shows, or is why, the TAIL is true",
  let a causal «por eso» read as evidence. It now reads "a reason to think it is".
- **A memory note reached a grounder directly.** The grounder that sealed that lead had opened the user's note
  on grounder rules by itself. The note lists «porque», «por eso» and «muestra» as cues for `grounds`, a list no
  contract has. Claude Code gives every subagent the project's memory index, so a note can reach an agent even
  when the orchestrator pastes nothing into its prompt, the channel 0.8.1 closed. The grounder,
  adversarial-grounder and extractor contracts now say that their rules are the contract: an agent takes no rule
  from a note, and where a note disagrees with the contract, the contract wins.

### Changed

- The adversarial contract: item 5 and Output B say how the record marks a hub, and the bounded-run paragraph
  and the report no longer say that such a hub "carries no mark".
- `/kg-ground`'s Stage 3 summary counts the hubs recorded, and lists their falsifying questions.

### Tests

- `tests/test_fix_attack_record.py` (20): a record moves the plan to the next hub, and its hub comes back with
  a newer grounded claim. Also covered: the field case (rejected counter-edges, a claim grounded later, then
  the record), a focus, a record on a node that is not a hub yet, the ledger line, no state changed, every
  refusal, a damaged, lost or unreadable ledger, a plan that never creates the ledger, the git exclude, and the
  contract and command texts.
- `tests/test_fix_connective_and_notes.py` (3): the connective rule, the extractor's shortcut list, and the
  contract-first paragraph in all three contracts.
- 1639 → 1662 passed, 3 skipped. `tests/fusion/test_diverge_surface.py` counts 32 tools, and
  `tests/test_fix_session_start.py`'s excluded patterns include the ledger. A 0.8.1 test pinned an Output B
  sentence that now goes on.
- **Checked end to end:** one headless `/kg-ground`, in auto mode with Claude Code 2.1.316 and the plugin loaded
  from this tree. It ran on scratch copies of the two documents the cases cite, with seven field edges written
  fresh. The hub `escribir-codigo-parte-pequena` was set up as the field left it: its two counter-edges
  rejected, then three claims grounded after them, so the plan offered it.
  - **The grounder:** it rejected the robot span as `grounds` (`wrong-relation`, with the lead `enables`) and
    grounded it as `enables`. The control «…así que el techo de ahorro es modesto» stayed `grounds`, a reason to
    believe the claim.
  - **The adversarial grounder:** it found no counter-span in either document, wrote nothing, and recorded the
    attack with its falsifying question (`no-span`). The report counted "1 recorded with none". The next plan
    offered no hub and listed the hub in `attacked_hubs`.
  - **No shell command ran and no permission was denied.** Cost: $0.87. The copies were deleted.

## 0.9.0 — 2026-11-08

The third `/kg-ground` on the Windows corpus, the first on 0.8.1, went by the book: the queue is empty and
every hub has been attacked. Over three passes the grounders' reports had named thirteen leads, edges the
source does state under claims they rejected, two of them `enables` edges. None could be written, because
`/kg-build` skips every section that already has edges. A lead now has a path into the canon.

### Added

- **`kg_ground(..., lead=...)`.** A grounder that rejects a claim as `wrong-relation` or `wrong-node` passes the
  edge the span does state, as `"<head-id> <relation> <tail-id>"`. The engine checks the relation against the
  pack and appends `lead: <head> <relation> <tail>` to the rejected edge's notes. A bad lead is refused before
  the verdict changes anything.
- **`/kg-build --leads`.** The plan lists the pending leads by the section that holds each rejected span,
  covered or not, and the command launches one extractor per section. `kg_section(..., leads=True)` hands it
  the leads with their spans, and it writes each one as an `unverified` claim with the same span, declaring a
  new node unless the section's known nodes hold the concept. The edge's notes open with
  `lead (from <rejected-edge-id>)`, which marks the lead taken, so each lead is written once. The next
  `/kg-ground` judges it like any other claim.
- **`queue.leads_pending`** in `kg_ground_plan`. `/kg-ground` says how many leads wait, and its report tells
  you when to run `/kg-build --leads`.

### Changed

- The grounder passes a lead with every `wrong-relation` or `wrong-node` rejection whose span states another
  edge, and `/kg-ground`'s template says so.
- The extractor contract has a leads mode: write the section's leads and nothing else.
- A test from 0.8.1 pinned the report saying that nothing could write the leads. It now pins `/kg-build
  --leads`.

### Tests

- `tests/test_fix_leads_path.py` (29): reading and writing a lead, and every refusal; the plan grouping
  leads by section, a subset, an unlocated span; `kg_section`'s leads; a written lead taken by its mark,
  under its own id or another; a lead whose edge already exists; the latest of two leads; the typed line;
  the contract and command texts.
- 1610 → 1639 passed, 3 skipped. `tests/test_kg_ground_plan.py`'s exact queue now includes `leads_pending`.
- **Checked end to end,** headless in auto mode with Claude Code 2.1.316 and the plugin loaded from this tree,
  on scratch copies of two documents of the reporting corpus, with five of its field edges written fresh:
  - **`/kg-ground`:** 1 grounded, 4 rejected, each with its lead. The two preconditions filed as `grounds` led
    to `enables` edges, and the two test-cheating edges to a new `manipulacion-de-tests` node.
    `queue.leads_pending` read 4, and the report said to run `/kg-build --leads`.
  - **`/kg-build --leads`:** one wave of four extractors, one per section, each prompt carrying ids only. All
    four leads were written with their mark and the rejected edge's span. Two extractors running at once
    declared the same new node, which deduped to one. The plan then listed no lead.
  - **`/kg-ground` again:** all four lead edges were grounded.
  - **No pass ran a shell command or was denied a permission.** Cost: $0.59, $0.64 and $0.40. The copies were
    deleted.

## 0.8.1 — 2026-11-08

The second `/kg-ground` on the Windows corpus, the first on 0.8.0, ended the hub attack as planned: it
attacked the five hubs left, and the next plan offers none. It also showed three gaps in the texts the agents
read. The engine, the pack and the canon format do not change.

### Fixed

- **Grounders split on what a node names.** Two `defends_against` edges from one document mapped a narrower
  phrase onto the broad node for cheating on tests. One is a matrix row whose «Cubre» cell reads «Manipulación
  de tests» and whose «Falla por» cell names the cheating it misses; the other a bullet that says «Resuelve la
  manipulación de tests visibles». Grounders running in parallel rejected the first and grounded its twin. The
  extractor's contract has said since 0.6.0 never to reuse a node for a broader or narrower concept, and the
  grounder now checks the same rule: each end of an edge is the concept its span names. An edge that breaks it
  is rejected with a new reason, `wrong-node`. The rule says outright that one company's figures can still
  ground a general claim.
- **The adversarial grounder wrote counters the source does not make.** Of the first ten counter-edges written
  in the field, the grounders rejected four. They rested on a premise the attacker supplied, on a figure the
  source gives as support, on a counter the source sets against another claim, or on a link between two
  documents. Its contract now says a counter-edge's span must itself set it against the claim it attacks, and
  a contradiction that no single span states goes in its report. Until now that lesson lived only in the
  user's memory notes.
- **A stale rule reached a grounder.** The orchestrator pasted rules from those notes into a grounder's prompt,
  among them "the pack has no `enables` relation", about twenty minutes after 0.8.0 was installed.
  `/kg-ground` never named `enables`, so nothing it read contradicted the note. It now names it, and says to
  send each grounder its item ids and nothing else: the rules are in the grounders' contracts.

### Added

- **Leads in the `/kg-ground` report.** For each `wrong-relation` or `wrong-node` rejection, the grounder names
  the edge its span does state, and the report lists them. In the field pass, two claims rejected as `grounds`
  state an `enables` edge, and nobody proposed it. Nothing writes leads yet: `/kg-build` skips every section
  that already has edges.

### Tests

- `tests/test_fix_node_scope_and_counters.py` (10): the node rule in the grounder, its exception for evidence
  about one case, and the leads it reports; the extractor's rule pointing at the check; the adversarial
  contract's new item and its numbering; the command sending ids and no rules, naming every reason the
  grounder contract defines, and listing the leads.
- 1600 → 1610 passed, 3 skipped.
- **Checked end to end,** headless in auto mode with Claude Code 2.1.316 and the plugin loaded from this tree,
  on scratch copies of three documents of the reporting corpus, with seven of its edges written fresh:
  - **First pass:** 3 grounded, 4 rejected.
    - Both edges onto the broad test-cheating node were rejected as `wrong-node`, each naming the narrower node
      its span names. The matrix row whose cell names its node's concept was grounded.
    - The precondition filed as `grounds` was rejected as `wrong-relation`, naming
      `verificacion-automatica enables autonomia-alta`.
    - The two edges that offer one company's figures as evidence for a general claim were grounded. The rule
      also rejected an edge whose node's label bundles Meta's figure with Vercel's, while its span cites only
      Meta's.
    - The orchestrator sent the template as written, and the report listed the four leads. With one of its
      claims rejected, the hub had two live claims left, so Stage 2 was skipped.
  - **Second pass,** with that last lead written as a Meta-only node: the edge was grounded. The adversarial
    grounder attacked the hub with one counter-edge, carrying the mark, whose span sits under the source's own
    «El mejor argumento contra cada conclusión». It failed nothing, and reported three contradictions between
    documents instead of writing them as edges. In the field, the same hub had drawn a counter-edge that the
    adversarial grounder itself rated the weakest: its span sets no word against the claim.
  - **No pass ran a shell command or was denied a permission.** Cost: $0.67, then $0.83. The copies were
    deleted.

## 0.8.0 — 2026-11-08

The first full `/kg-ground` on 0.7.0, on the Windows install's 8-file corpus, judged all 168 claims with no
shell command and no permission prompt. Its report showed four defects: the grounders, running in parallel,
split on two rules; a long table reached them without its header; `query_graph` answered a different question
in each half of its result; and the hub attack would have repeated on every pass. The pack gains one relation,
`enables`. The write boundary, the verdict rules and the canon format do not change.

### Why the grounders disagreed

- **The grounder had no definition of the relations.** The extractor writes each claim by a HEAD/TAIL table,
  but the grounder contract had none, and the pack's definitions are YAML comments that never reach a model.
  Four grounders accepted "X permite Y" (X makes Y possible) as `grounds`, and one rejected it.
- **A long table lost its header.** `kg_ground_item` cut the 60-line mechanism matrix of one document (8 346
  characters) down to the rows around each span. One grounder guessed what the columns meant and grounded
  three rows; another judged the fourth row "two bare cells" and rejected it. The command's grounder template
  also listed "a table cell" among the spans that state no relation.
- **They browsed the graph to calibrate.** Eight of the 14 grounders called `query_graph` 15 times, to see how
  other edges used a relation or to look for duplicates. Five of the answers, 62 to 89 KB, were saved to
  files, and four grounders searched them with Grep.

### Fixed

- **The hub attack would never have ended.** Hub degree counted every edge, including refuted ones and the
  adversarial grounder's own counter-edges, and nothing recorded an attack. On a copy of the canon, the next
  plan offered the five hubs just attacked, so each pass would have ended with about ten new unverified
  counter-edges against them. Now:
  - degree counts live claims only (`NON_LIVE_STATE_VALUES`, as on every other structural surface), and no
    counter-edge;
  - the adversarial grounder opens each counter-edge's notes with
    `counter-edge (adversarial pass, hub <hub-id>)`, the form it already wrote on all ten of that pass's
    counter-edges;
  - without a focus, the plan leaves out a hub whose counter-edge awaits its verdict, or whose newest
    counter-edge verdict is no older than its newest grounded claim, and lists it in `attacked_hubs`.

  Each pass attacks the next hubs down the list, and Stage 2 ends once every hub has been attacked. A focus
  still attacks the hubs it names: that is how you ask for a second attack. On the reporting canon, 4 of its 9
  hubs now count as attacked, and the next pass attacks the other 5. `conjunto-oculto` drops out, because two
  of its claims were rejected.
- **`query_graph` filters apply to both halves.** `node_type` and `epistemic_state` used to filter only the
  nodes, and `relation` only the edges.
  - `query_graph(epistemic_state="grounded")`, which `/kg-query` offered as the trustworthy subgraph, returned
    8 rejected edges among 50 on the reporting canon. It now returns 50 grounded ones.
  - A node type that does not exist returned 100 unrelated edges. It now returns nothing.
- **An excerpt cut out of a long table keeps the table's header and rule rows,** with a `…` line where rows
  were skipped. All four matrix rows of the reporting canon now arrive under `| Mecanismo | Cubre | … |`.
- **The adversarial contract taught the wrong direction and the wrong target.**
  - Its payload example wrote `specificity attacked_by generality-confound`, and its worked example
    `generality-confound confounded_by betweenness`: both reversed against the pack.
  - The worked example then grounded its own counter-edge `failed`, which records the counter-claim as false.

  This pass's adversarial grounder did neither. The examples now read victim first and fail the refuted claim.
- **The extractor said two things.** "Map it to the nearest pack relation" sat beside "leave the edge out
  instead of approximating it". It now says only to leave the edge out.

### Added

- **`enables`**, the pack's eleventh relation: HEAD = the precondition or means, TAIL = what it makes
  possible. `grounds` is now evidence or a reason, and no longer covers a precondition.
- **`attacked_hubs`** in `kg_ground_plan`'s result.

### Changed

- **The grounder judges by the extractor's relation table,** repeated word for word between `relation-roles`
  markers in both contracts. It also gets a rule for tables: a row states a relation when the table's header
  says what each cell is.
- **Neither grounder has `query_graph` any more.** The grounder judges from `kg_ground_item`, checks a
  suspected duplicate with `get_node`, and names duplicate pairs in its report. The adversarial grounder
  attacks the hubs its prompt lists and adds none of its own.
- **The adversarial grounder declares the nodes it creates,** with one of the pack's node types, which its
  contract now lists, instead of leaving untyped placeholders.
- **`/kg-ground` takes Stage 2's hubs from the last progress probe,** after the claims are judged, and skips
  Stage 2 when no hub is left. Its grounder template points at the relation table.
- **Every text that lists the relations lists `enables`,** and `grounds` reads "evidence or reason" in the
  pack, the extractor and the references.

### Tests

- **46 new tests in four files:**
  - `tests/test_fix_attack_once.py` (16): the mark, in the forms the field pass wrote; the attack rule; a
    pending and a judged attack; a hub coming back after a new grounded claim; the focus; counter-edges and
    every non-live state adding no degree; the contract examples.
  - `tests/test_fix_relation_rules.py` (18): `enables` accepted at the boundary; the two relation tables
    identical and complete; `grounds` against `enables`; the grounder's tools and table rule; the command
    template; every text that lists the relations listing all of them; the adversarial contract naming the
    pack's node types.
  - `tests/test_fix_table_header_excerpt.py` (6): the header kept far down a table and right under it; the
    cap; a header too wide for it; text with no rule row; `kg_ground_item` end to end.
  - `tests/test_fix_query_graph_filters.py` (6): each filter on both halves, combined filters, a node type
    that does not exist.
- 1554 → 1600 passed, 3 skipped.
- **Checked on a copy of the reporting canon:** the four matrix rows arrive under their header; all ten
  counter-edges are recognized; the next plan offers the five hubs not yet attacked; and the grounded query
  returns only grounded edges. The canon was left untouched.
- **Checked end to end,** headless in auto mode with Claude Code 2.1.316 and the plugin loaded from this tree,
  on `examples/source.md`:
  - **A `/kg-build`, then a `/kg-ground`:** 11 claims judged, 9 grounded and 2 rejected. Both rejected claims
    were `claim`'s, which left it 2 live claims, so it was no hub and Stage 2 was skipped.
  - **A short section added, with three claims about one node, then a second `/kg-ground`:** the three were
    grounded. The adversarial grounder attacked the node and wrote two counter-edges carrying the mark, victim
    first, and failed nothing, since the counter-span limits the claims without refuting them. The plan then
    listed the node under `attacked_hubs` and offered no hub; a focus on it still offered it.
  - **No pass ran a shell command or was denied a permission.** The adversarial grounder's one file read was
    the source, inside the project folder. Its first write typed a node `concept` and was quarantined, which
    is why its contract now lists the node types.
  - **Cost:** $0.80 for the build, then $0.60 and $0.71 for the two passes.

## 0.7.0 — 2026-11-07

`/kg-ground` no longer runs a shell command, so auto mode no longer stops it on permission prompts. Reported
from the Windows install after 0.6.1, on the canon of its 8-file corpus (168 unverified edges, 399 nodes): it
asked for permission over and over, as `/kg-build` did before 0.5.0. Two new engine tools plan the pass and
hand each grounder its evidence, and the grounders run in parallel waves. The write boundary, the verdict
rules and the canon format do not change.

### Why it asked

- **The queue came back as 300 000 characters.** The command listed it with `query_graph`, and the
  orchestrator asked for all of it (`limit=1000`). The answer held every edge and every node with its full
  text, and Claude Code saved it to a file.
- **The orchestrator read that file with Bash.** It wrote Python scripts to parse it. It then read the
  plugin's own agent files and engine source through Bash, to learn how `kg_ground` works; that read waited
  39 seconds for the user.
- **Auto mode sends every Bash command to its classifier.** It ignores a command's Bash permission (see
  0.5.0).

### Fixed

- **One grounder for the whole queue.** Stage 1 launched a single grounder to drain every item, although
  the grounder's contract caps a run at 20.
- **The grounder checked spans against the demo.** Its prompt named `examples/source.md` and told it to read
  the source whole: for the reporting corpus, 8 files and about 450 KB.

### Added

- **`kg_ground_plan(focus, configured_wave_size, batch_size)`**, the pass's Stage 0 in the engine. It returns
  the queue as `{id, kind}` items in batches, one batch per grounder, with the wave size, the hubs for the
  adversarial grounder and the configured source.
  - **The queue:** every `unverified` edge and every `unverified` hypothesized node.
  - **The order:**
    - `[diverge]` pins first;
    - then the other hypotheses;
    - then the edges their extractor marked weak (`AMBIGUOUS`, or a `confidence_score` under 0.5);
    - then the rest.

    Each group is in source order, so a batch covers contiguous text.
  - **`focus`** (the typed arguments) keeps the items that touch a node it names.
  - **On the reporting canon:** 16 602 characters, 14 batches of 12 in 3 waves, with its 7 weak edges first.
- **`kg_ground_item(target_id, kind)`**, one item's evidence, with no file read. The grounder gets:
  - the edge;
  - `span_in_source`, the engine's own check of whether its span still verifies;
  - its two nodes;
  - the excerpt of the source around the span.

  The excerpt is the paragraph and its neighbours, at most 3000 characters, or the rows around the span in a
  long table. Text goes through the session scrub, so a support span copied back from it restores and
  verifies. On the reporting canon, all 168 spans verified and had an excerpt, at about 4000 characters an
  item.
- **`kg_engine/groundplan.py`:** the deterministic parts: the batch and focus rules, the weak mark and the
  excerpt.
- The MCP surface goes from 29 to 31 tools.

### Changed

- **`/kg-ground` declares no Bash and runs no shell.** Its `allowed-tools` are `Task` and five engine tools.
  It says it needs no shell and no file access, and never to pull the queue through `query_graph`.
- **Grounders run in parallel waves:** one per batch, `wave_size` at a time. The `extract_wave_size` option
  now bounds both `/kg-build`'s extractors and `/kg-ground`'s grounders, and its description says so.
- **The grounder's contract.** It takes its batch's ids from the prompt and fetches each item with
  `kg_ground_item`. It judges from that evidence, and checks that a span states the relation in its
  direction, not its opposite. It reads the source only to relocate a stale span (Stage 0b).
- **The adversarial grounder** reads each attacked edge through `kg_ground_item`. It searches the configured
  source files its prompt lists, never `examples/source.md` outside the demo or the plugin's own files.
- **The extractor's own nodes are no longer queued.** Each names a concept the text uses, and the claims
  about it are its edges, which are queued. The plan counts them: 399 on the reporting canon.

### Tests

- **`tests/test_kg_ground_plan.py` (21 tests)** covers:
  - the excerpt: the paragraph and its neighbours, the cap, a span across paragraphs, a long table;
  - the batch, focus and order rules: pins, hypotheses, weak edges, then source order;
  - a verdicted item leaving the queue, and the waves and the option;
  - each item's evidence, a stale span, the session scrub round trip, and the refusals;
  - both tools through a real FastMCP;
  - the command and agent texts that wire it together.
- The tool-count pin goes to 31. 1533 → 1554 passed, 3 skipped.
- **The new tests cannot fail informatively on 0.6.1:** there, the file stops at import, because
  `kg_engine.groundplan` does not exist. The fix was checked end to end instead.
  - **Headless, in auto mode,** with Claude Code 2.1.316 and the plugin loaded from this tree, on
    `examples/source.md`: a `/kg-build`, then a `/kg-ground`. The grounder fetched all 10 items with
    `kg_ground_item` and grounded them, with no Bash, `Read` or `Grep` in the whole pass.
  - **A second pass, with one weak edge added so that `claim` became a hub.** The grounder rejected the edge
    (`wrong-relation`). The adversarial grounder attacked `claim` and wrote two counter-edges. Its one file
    read was the source, inside the project folder.
  - **Neither pass ran a shell command or was denied a permission.** The two passes cost $0.55 and $0.53.
  - **The plan and the evidence, on a copy of the reporting canon:** the queue and its 168 excerpts came back
    as described above, and the canon was left untouched.

## 0.6.1 — 2026-11-07

Patch release from the full `/kg-build` on 0.6.0 of the reporting install's 8-file corpus. The build ended with
399 nodes, 168 edges and about 8 duplicate groups, down from 19, but one node, `camel`, was an untyped
placeholder that two later sections refused to link to. The write boundary, grounding and the canon format do
not change.

### Fixed

- **An undeclared endpoint became an untyped node silently.** An extractor named `camel` in an edge without
  declaring it. The boundary wrote it, as documented, as a placeholder with no node_type and no body, and
  reported nothing. Later sections saw it in their `known_nodes` as an undeclared-type node, and two of them
  refused to link to it, because their contract said never to redeclare a known node.
  - `kg_write` now returns `placeholders`: the new notes it created untyped.
  - `kg_section` marks such a known node `untyped: true`.
  - The extractor's contract asks it to declare every node its edges name. When `placeholders` comes back, it
    re-sends its payload with the node declared.
  - A section that defines an `untyped` known node declares it with the same id, which fills in its type,
    label and body: the one exception to "never redeclare a known node".
  - `/kg-build`'s launch template and failure modes say the same.

### Tests

- **`tests/test_fix_untyped_placeholders.py` (6 tests)** covers:
  - the placeholder reported;
  - no report when the node is declared or already known;
  - the `untyped` mark in the next section, and declaring the node to fill it in and clear the mark, with its
    edge kept;
  - no mark on a typed node;
  - the contract's and the command's texts.
- **Verified against 0.6.0.** Run against the 0.6.0 engine, 3 of the 6 fail: the two new signals and the
  contract text. The other three pin that the signals do not misfire, and that declaring a placeholder fills
  it in. 1527 → 1533 passed, 3 skipped.

## 0.6.0 — 2026-11-07

`kg_section` now shows each extractor the nodes already in the canon that its section names, so later
sections reuse an id instead of coining a near-duplicate. Reported from the full `/kg-build` on 0.5.2 of the
reporting install's 8-file corpus (84 sections, 486 nodes). There, one concept written by two sections landed
under two ids about 19 times (`radar` / `meta-radar`, `pass-at-k` / `pass-k`, singular/plural pairs), and
102 nodes had no edge. The write boundary, grounding and the canon format do not change.

### Added

- **`known_nodes` in `kg_section`'s result:** up to 60 canon nodes whose name the section mentions, as
  `{id, label, node_type}`, most specifically named first. `known_nodes_more` counts the ones past the cap.
  - **Named:** at least half the content words of the node's id or label occur in the section, singular or
    plural, with accents and function words ignored.
  - **Order:** a rarity weight over the canon's names puts `radar` or `camel` ahead of `codigo`, then degree,
    then id, so the list is the same on every run.
  - **No merging:** it only decides what the extractor is shown. Nothing is merged automatically.
- **`buildplan.related_nodes`** is the match itself: deterministic and word-based, with no embeddings.

### Changed

- **The extractor's contract:**
  - reuse a known node's id only for the same concept;
  - never reuse it for a broader, narrower or merely related one;
  - create a new node when in doubt;
  - never redeclare a known node in `nodes[]`, because a redeclared node's label, node_type and body replace
    the ones in the canon. In the reported build, `meta-radar` changed type that way.
- **`/kg-build`'s launch template** passes the same rule on.

### Tests

- **`tests/test_known_nodes.py` (19 tests)** covers:
  - what counts as named: half the words, plurals, accents, numbers, function words;
  - the rarity order and the deterministic tie-breaks, and the cap and its count;
  - through `kg_section`: an empty canon, a later section seeing an earlier one's node, egress-scrubbed
    labels, an unreadable canon still serving the section, and one canon parse per wave;
  - the contract and template texts.
- **These tests cannot fail informatively on 0.5.2**, where the function does not exist. The match was
  measured offline instead, on copies of the reported build's canon and its 84 sections.
  - Two members of the build's 18 duplicate groups appear together in some section's list for 12 of them at
    a cap of 20, 14 at 40 and 16 at 60, and still 16 at 80; hence the cap of 60, about 1.5k tokens per
    extractor.
  - The two misses are a translation (`mutation-score` / `puntuacion-de-mutacion`) and synonyms with no word
    in common.
- **Checked end to end with Claude Code 2.1.316**, in auto mode and headless: a `/kg-build` of
  `examples/source.md` with the option set to 2, so three waves.
  - The first wave got no known nodes, from an empty canon.
  - In the second, §3 was shown two known nodes and reused `generality-confound` in its edges, and §4 reused
    `claim`. No extractor redeclared a known node.
  - Nothing ran Bash or read a file, and no permission was denied. The canon held 20 nodes and 11 edges, and
    the run cost $0.76.
- 1508 → 1527 passed, 3 skipped.

## 0.5.2 — 2026-11-07

Patch release from the first full `/kg-build` on 0.5.1: all 8 files of the reporting install's source, 84
sections and 819 items ACCEPTED in 14 waves, with no shell command and no permission prompt. Its report named
one engine gap and three gaps in the extractor's contract. The MCP tool surface and grounding do not change.

### Fixed

- **The write boundary accepted a self-loop.** One extractor wrote
  `h1-comprobadores-retiran-mas-revision survives h1-comprobadores-retiran-mas-revision` as a placeholder, at
  confidence 0.2. Its span verified, so nothing stopped it; it was the only self-loop among the build's 225
  edges.
  - The boundary now REJECTS an edge whose two endpoints slug to one node, with reason `self-loop`
    (`retryable: false`), in every lane.
  - `kg_merge`'s handling of the self-loops its own rewrite creates is unchanged.
- **Extractors passed `source` to `kg_write`.** Two calls were refused ("`source` is only valid together with
  `construction`") and had to be re-sent.
  - The refusal stays: it protects a caller who thinks it re-points the primary source.
  - The extractor's contract and `/kg-build`'s launch template now say to call `kg_write` with the payload
    alone.
- **The extractor's contract now carries the rules the build's orchestrator had to add to every launch
  prompt:**
  - Name ids in the source's own words and language, in lowercase ASCII with accents dropped, and never a
    translation. Wave 1 mixed `census-ai-adoption-rate` with `practica-mediana-eeuu`, and two spellings of one
    concept make two nodes. Every id of the reporting canon already follows that form (555 of 555).
  - An edge joins two different nodes.
  - An edge must read in the direction its span says, and a doubtful relation is left out rather than
    approximated.

### Tests

- **`tests/test_fix_self_loops_and_write_args.py` (7 tests)** covers:
  - the reported self-loop, rejected, and the rest of its payload still written;
  - endpoints compared as slugs (`Meta RADAR` → `meta-radar`);
  - the propose lane refusing a self-loop too;
  - the unchanged refusal of `source` without `construction`;
  - the extractor's and the command's texts.
- **Verified as real pins.** Run against the 0.5.1 engine, with `PYTHONPATH` at a worktree of `main`, 6 of
  the 7 fail. The other one pins the refusal that must not change. 1501 → 1508 passed, 3 skipped.

### In the reporting canon

The self-loop stays until `/kg-ground` rejects it, and so does the reversed
`criticas-de-terceros attacked_by evidencia-de-los-autores`. The near-duplicate ids that the report lists can
be joined with `kg_merge`.

## 0.5.1 — 2026-11-07

Patch release for a hole in the build's span guarantee, which the last `/kg-build` on 0.4.6 surfaced:
`kg_write` accepted an edge marked `hypothesized` without checking its span. The propose lane, the MCP tool
surface and grounding do not change.

### Fixed

- **`kg_write` accepted `hypothesized` edges with their span dropped and unchecked.** The boundary treats
  `provenance: hypothesized` as the proposal lane of the discovery mechanisms (`kg_propose`): it stores the
  item with an empty span and runs no span check. `kg_write` sent such an item down that lane as well, and
  the extractor's own contract invited it: "use `hypothesized` for a relation you genuinely inferred across
  sentences — it still needs a span".
  - In the reporting build, the §14 extractor marked both its edges `hypothesized`. Both were ACCEPTED, with
    no REJECTED or QUARANTINED signal; the only symptom was §14 staying uncovered.
  - On 0.5.0, an edge marked `hypothesized` was accepted even when its span was not in the source at all.
  - `kg_write` now REJECTS any item that claims `provenance: hypothesized`, with reason
    `write-lane-hypothesis` (`retryable: false`). It writes the rest of the payload and reports
    `refused_hypotheses: N`, the mirror of `kg_propose` refusing text claims (`propose-lane-text-claim`).
  - `kg_propose`, `kg_operate` and pin materialization are unchanged: they reach the shared validator through
    `kg_write`'s internal `lane="proposal"`.
  - The extractor's contract now says to use `inferred` for a relation inferred across sentences, still with
    a verbatim span, which the boundary verifies like a `span-present` one; never `hypothesized`. On
    `write-lane-hypothesis` it re-emits the item as `inferred` with its span, or drops it.
- **The extractor's contract names two span hazards the same build hit.** Markdown escapes such as `\[EX\]`
  stay as written, and a `−` minus sign is not a hyphen: only curly quotes and dashes are folded.

### Tests

- **`tests/test_fix_write_lane_hypothesis.py` (10 tests)** covers:
  - the §14 shape, refused and not written;
  - the rest of the payload still written;
  - the same claim as `inferred`, accepted and verified;
  - every edge `kg_write` accepts carrying a verified span;
  - `kg_propose` unchanged;
  - the second-construction write, the idempotent replay, and the real MCP tool layer;
  - the extractor's text.
- **Verified as real pins.** Run against the 0.5.0 engine, with `PYTHONPATH` at a worktree of `main`, 8 of
  the 10 fail. The other two pin what must not change: an `inferred` edge accepted and verified, and
  `kg_propose` writing the hypothesized lane. 1491 → 1501 passed, 3 skipped.

### An existing canon

An edge written this way before 0.5.1 stays in the canon: `hypothesized`, `unverified`, without a span. In
the reporting build that is one edge, `agent-isolation defends_against agent-credential-exposure`.
`/kg-ground` can reject it; grounding it would take real support, since `kg_ground` refuses to ground a
hypothesized edge without a support span or note.

## 0.5.0 — 2026-11-07

`/kg-build` no longer runs a shell command, so auto mode no longer stops it on permission prompts. Reported
from the Windows install after 0.4.6: every build asked for permission over and over, auto mode on, and
waited until it got it. Two new engine tools take over what the command did in Bash. The write boundary,
grounding and the canon format do not change.

### Why it asked

In auto mode Claude Code ignores the permissions a command declares for `Bash` and for launching subagents
(`Task`), because a tool-wide grant would let the model step around its classifier (read from the Claude
Code binary, 2.1.316). Every Bash command `/kg-build` ran went to the classifier, and the ones it did not
clear waited for the user. The session logs of the reporting install's two builds show it:

- Every long wait was a Bash command. Engine tools and subagent launches never waited for the user.
- In the first build (0.4.5), six Bash commands waited 2.5 to 11 minutes each, about 32 minutes in all. They
  were helper scripts the orchestrator wrote itself, to cut the document into section files and apply the
  scrub to them, because the command asked it to copy each section verbatim twice: into `kg_scrub`, then
  into the extractor's prompt.
- In the second (0.4.6), Step 0b waited 3.5 minutes, although the same script had passed in a second the
  time before.

### Added

- **`kg_build_plan(arguments, configured_wave_size)`**, the build's Step 0 in the engine. It returns the files
  to build, each file's numbered sections at its heading level, which sections are already covered, and the
  wave size.
  - It reads the typed `$ARGUMENTS` itself (`kg_engine.buildplan.parse_arguments`).
  - It takes the `extract_wave_size` option from the text Claude Code fills into the command
    (`${user_config.extract_wave_size}`), so the engine still reads no env var for it.
  - It refuses a subset that reaches past the configured source before any extractor runs, as Step 0b did,
    and also a same-named copy of a configured file kept elsewhere.
- **`kg_section(source_file, section)`**, one planned section, cut from the source and egress-scrubbed by the
  engine. The extractor calls it itself.
- The MCP surface goes from 27 to 29 tools.

### Changed

- **`/kg-build` declares no Bash and runs no shell.** Its `allowed-tools` are `Task` and five engine tools.
  It never reads the source or pastes section text into a prompt, it tells the user what it is about to
  build, and it resumes from the plan's coverage.
- **The extractor fetches its own section** with `kg_section`, now among its tools. Section text handed to
  it inline, and the direct-invocation path, still work.
- **Egress.** The orchestrator no longer reads the whole document. That read sent the unscrubbed text to the
  model before any scrub ran; the only section text that now leaves the engine is `kg_section`'s scrubbed
  output. The session scrub is serialized by a lock, so a wave of extractors asking at once keeps one
  placeholder per value.
- **The argument rules are code now, and unchanged but for one.** A trailing whole number is the wave size
  and the rest is the subset; quotes are dropped; two quoted parts are refused. The change: a line that is
  only a whole number is the wave size (`/kg-build 4`). Before, it was a subset that named no file.
- **Sections.** `sources.plan_sections` is what the plan numbers and `kg_section` serves; `split_sections`
  returns exactly what it did, from the same splitter.
  - Headings inside fenced code no longer count toward the `### ` rule (FALLO 4); Step 0b's `grep` counted
    them.
  - The plan's coverage is per planned section, `### ` subsections included. `kg_status`'s coverage is
    unchanged.

### Tests

- **`tests/test_kg_build_plan.py` (40 tests)** covers:
  - the argument and subset rules, and both tools called through a real FastMCP with what a model sends;
  - that a plan's section N is the text `kg_section` serves for N;
  - the scrub/restore round trip through `kg_section`, and a secret in a heading;
  - one placeholder per value under concurrent `kg_section` calls;
  - coverage per file and section, and the refusals;
  - the command and agent texts that wire it together.
- **The Bash tests of Step 0b now pin the same properties against the engine.**
  - `tests/test_fix_kg_build_paths.py` (9 → 12) and `tests/test_fix_kg_build_source.py` (7 → 13).
  - `tests/test_waves.py` (55 → 46): its 28-case Bash drift guard gives way to plan tests, since the
    resolver is now the only implementation.
  - `tests/test_fix_command_arguments.py` (76 → 78) fills in the command text as Claude Code does and hands
    it to the plan.
- The tool-count pin goes to 29. 1449 → 1491 passed, 3 skipped.
- **The new tests cannot fail informatively on 0.4.6**, because the tools they call did not exist there. The
  fix was checked end to end instead: a real `/kg-build` of `examples/source.md` with Claude Code 2.1.316 in
  auto mode, headless, the plugin loaded from this tree and the option set to 3.
  - It called only `kg_build_plan`, five extractor launches in waves of 3 and 2, `kg_metrics`, `kg_context`
    and a closing `kg_build_plan`; each extractor called only `kg_section` and `kg_write`.
  - Nothing ran Bash or read a file, and no permission was denied.
  - 34 items were ACCEPTED and none rejected, giving 20 nodes and 11 edges, and every section ended
    covered. The run took 74 s and cost $0.65.

## 0.4.6 — 2026-11-07

Patch release for three engine defects that the first real `/kg-build` on 0.4.5 surfaced. That build was
one 16-section Spanish document from an 8-file source folder, on the reporting Windows install. Each defect
was confirmed against a copy of that build's own canon before it was fixed, and re-run there after: the
broken numbers below are from the 0.4.5 engine on that copy, the fixed ones from this release. No change to
the MCP tool surface or to grounding.

### Fixed

- **Edges whose endpoints were labels never joined the graph.** 3 of the build's 39 edges named their
  endpoints by label (`Meta RADAR`, `componentes en masa`) while their id and owner used the slug. The
  extractor contract asks for ids; the boundary keyed each edge on the slug but stored the endpoints as
  given.
  - Effect on 0.4.5: the projection hung those edges on phantom nodes, 80 nodes instead of 75. So
    `get_neighbors` showed `meta-radar` 1 of its 2 edges and `componentes-en-masa` none, and degree and
    bridges undercounted. `kg_rename` and `kg_merge`, which matched endpoints exactly, would have left
    them dangling.
  - The boundary now stores endpoints as node ids.
  - The projector resolves the label-form endpoints an older canon or a hand edit still holds: an
    endpoint that is not a node id but whose slug is one names that node. That includes a node stored
    with a raw id from before node ids were slugged.
  - A new `PROJECTION_RULES` value in the index forces one full rebuild after the upgrade, because notes
    that did not change are rebuilt from their old index rows rather than re-read.
  - Rename and merge match endpoints by slug.
  - On the copy of the build: 75 nodes, no phantoms, and every edge visible from both ends. The canon
    files keep their label-form endpoints on disk until something rewrites them.
- **`kg_status` coverage counted a span toward every source file.** Three short spans of the built
  document also occur in another file of the folder (`Sin grupo de control.`). So three sections of that
  other file showed as covered although nothing had been built from it, and a resumed build guided by
  coverage would have skipped them. A span now counts toward a file the way the boundary verified it:
  toward the file its edge's `source_file` names when that is a declared source, and toward any file when
  the edge names none or an unknown one. On the copy, that file went from 3 of 18 sections covered to 0.
- **`kg_scrub` reported 0 redactions for a section that still held placeholders.** Placeholders are
  consistent across a session, and the count only included the ones the call itself minted. Sections 7, 9
  and 16 reused a placeholder an earlier section had minted, and came back holding `⟦SECRET:1⟧` with
  `redactions: 0` and `categories: []`, which reads as "the scrubbed text is the original". `redactions`
  now counts every redacted value the returned text holds, so it is 0 exactly when nothing changed; on
  the copy that held for all 16 sections. The redacted values themselves were three URL path fragments.
  That over-redaction is deliberate (a URL can carry a real token), and `kg_write` restores them.

### Tests

- **`tests/test_fix_engine_field_report.py` (12 tests)** covers:
  - the reused-placeholder count, and the "0 redactions ⇔ unchanged text" equivalence;
  - coverage per named file, while an edge with no known `source_file` still covers any file;
  - endpoints stored as ids, and label-form endpoints reaching neighbors and degree with no phantom
    nodes;
  - a well-formed canon left untouched, and a legacy raw id still found;
  - an index built under the old rules rebuilt exactly once with no canon change;
  - rename and merge rewriting a label-form endpoint.
- **The review-C2 test in `tests/test_fix_boundary_model.py`** now expects the stored source to be the
  node id, not the label. Its point (no phantom node, no rolled-back batch) is unchanged.
- **Verified as real pins.** Run against the 0.4.5 engine, 10 of the 12 fail. The other two pin the
  unchanged lenient coverage. 1437 → 1449 passed, 3 skipped.

## 0.4.5 — 2026-11-07

Patch release for how commands receive what you type after them, and for the `extract_wave_size` option,
which never reached `/kg-build`. Found right after 0.4.4, while checking how a file name with spaces would
reach `/kg-build`. Only the commands and their docs change, plus the wave-size test that mirrors
`/kg-build`'s Bash; the engine, the MCP tool surface and grounding do not.

### Fixed

- **Six commands read their arguments from the wrong placeholders.** `/kg-build`, `/kg-view`, `/kg-eval`,
  `/kg-generate`, `/kg-perturb` and `/kg-experiment` used `$1` and `$2` for their first and second
  arguments, but Claude Code counts those from 0, so `$1` is the second argument. This was read from its
  binary and confirmed with real runs on 2.1.316; 2.1.319 has the same code and 2.1.202 counts the same
  way. One argument worked by accident on current versions: an unfilled `$1` stays in the text, and Claude
  Code then appends the typed text. With two, every `$1` became the second argument: `/kg-build notes.md 4`
  asked for a source named `4`, and the path vanished from the prompt. Every command now reads
  `$ARGUMENTS`, the raw typed text, which means the same in every version, and says how to split it.
- **`/kg-build` takes a file name with spaces, quoted or not.** Quoted text is one argument. Unquoted, a
  trailing whole number is the wave size and the rest is the path, so `/kg-build Fábricas de software.md 4`
  works. A name that itself ends in a number must be quoted.
- **The `extract_wave_size` option never reached the build, and neither did a wave size typed after the
  path.** Step 0b resolved `${2:-${CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE:-6}}`, and none of its three
  levels could ever be set. Claude Code does not fill `${2}`, and bash's own `$2` is empty in the Bash tool.
  Claude Code passes the `CLAUDE_PLUGIN_OPTION_*` variables to hooks and MCP servers only. So every build
  ran in waves of 6, unless the orchestrator rewrote the line by hand. The option now reaches Step 0b as
  `${user_config.extract_wave_size}`, which Claude Code fills in when the command loads. This was checked
  with a real plugin command: a set option becomes its value, and an unset one stays as written, which
  resolves to 6. The typed wave size goes into a `WAVE_ARG` slot that the orchestrator fills.
- **`/kg-perturb` could silently degrade to `regroup`.** Its classification block began with
  `SECOND="$1"`, which is empty in the Bash tool. A second source that the orchestrator did not copy in by
  hand was therefore read as no second source. The block now starts from a `__SECOND__` slot, and stops if
  the slot is left unfilled.

### Changed

- **`docs/COMMANDS.md` explains how each command reads what you type.** Its `/kg-build` section now gives
  the 0.4.4 meaning of the argument: a subset inside the configured `source_path`, not any source. All its
  examples now work against one configured folder. The recursive-glob example is gone, because Step 0b does
  not recurse and the engine does not list subfolder files of a folder source.
- **The argument hint is now `[subset] [wave_size]`,** in the command, the README and the skill.
- **`/kg-generate` takes `k` on its own** (`/kg-generate 20`).
- **The decision and where the values come from are written down.** `docs/fusion/DECISIONS.md` records
  the decision, with its rejected alternatives. `docs/ARCHITECTURE.md`, `CLAUDE.md` and
  `kg_engine/waves.py` now say where the option and the arguments come from.

### Tests

- **`tests/test_fix_command_arguments.py` (76 cases).**
  - A model of Claude Code's substitution, pinned to the five expansions recorded from real runs.
  - Static pins: no command or skill text holds a numbered placeholder, and every command with an argument
    hint reads `$ARGUMENTS`.
  - Whatever is typed, only `$ARGUMENTS` changes in each command.
  - Step 0b and `/kg-perturb`'s block run as the orchestrator would, on Windows under Git Bash.
- **The drift guard in `tests/test_waves.py` now feeds the wave size through the two channels the command
  really has.** Before, it supplied bash's `$2` and the environment, which the real command never had, so
  it passed while every build used 6.
- **Verified as real pins.** Against the 0.4.4 commands, 34 of the 76 new cases fail, and so do all 28 of
  the drift guard's. The rest pin what was already right: the three commands that only ever read
  `$ARGUMENTS`, the skill texts, the recorded expansions, one-argument calls, and the default for an unset
  option. 1361 → 1437 passed, 3 skipped.

## 0.4.4 — 2026-11-07

Patch release for `/kg-build` over a source whose path holds spaces, and for what the command says about
`$1`. Found on the same Windows install as 0.4.3, on the first build after that update: the source folder
sat under `Documents\Proyectos personales\`, and most of its file names hold spaces and accents. Only the
`/kg-build` command and the docs change; the engine, the MCP tool surface and grounding do not.

### Fixed

- **Step 0b split every source path at its spaces.** The enumeration script ran `ls -1 $SOURCE` unquoted,
  there to expand a glob, so a single-file source whose path held a space resolved to nothing ("no .md/.txt
  source found"). It then looped with `for f in $FILES`, so every file of a directory source was cut into
  fragments before its sections were counted (`grep: personales/prueba: No such file or directory`). Paths
  like `Proyectos personales` or `OneDrive - Org` are ordinary on Windows. The script now keeps one path per
  line end to end: a file is taken whole, a glob is expanded as one pattern (`compgen -G`, with a Windows
  pattern's `\` turned into `/` first so its separators are not read as glob escapes), and the loop reads
  lines. Checked under Linux bash and under Git Bash on the reporting machine, the shell Claude Code runs
  there: the old script failed for a directory, a single file and a glob on both, and the new one lists
  every file and its sections.
- **A directory source skipped `.MD` and `.TXT` files that the engine counts.** The listing matched
  extensions case-sensitively and the engine's SourceSet does not. It now uses `-iname`, so a plain
  directory build enumerates exactly what `kg_status().source.files` lists.
- **The command presented `$1` as an override of the configured source.** `kg_write` verifies every span
  against the files of the configured `source_path` (the engine's SourceSet, keyed by basename), never
  against `$1`, so building a path outside it would have every edge REJECTED `span-not-in-source`; the STOP
  advice for a missing source suggested exactly that. `$1` is now documented as a subset of the configured
  source, and Step 0b checks every enumerated file against `source.files`, stopping before it launches an
  extractor for a file the engine does not list.

### Changed

- **The command and the docs say how to change `source_path` after install:** `claude plugin configure
  burgess@sergiparpal --values-stdin` with a JSON object on stdin (Claude Code 2.1.285 or later), or
  `/plugin` → *Configure options*, and then a restart, because the MCP server reads the value only when it
  starts. The subcommand was checked against the CLI on the reporting machine, and the README's PowerShell
  example was run end to end against a throwaway config there. Windows PowerShell 5.1 pipes text as ASCII,
  so an accented path (`C:/Users/José/Documentos/Información`) was saved as `Jos?`/`Informaci?n`, and the
  CLI still reported success. It was saved intact once `$OutputEncoding` was set to UTF-8 first, and the
  README and the command now say to do that. The TUTORIAL no longer suggests pointing `/kg-build` at an
  arbitrary document, and says that a file added to a configured folder is picked up without a restart
  (the engine re-resolves the source on every call, keyed on its files' signature).

### Tests

- `tests/test_fix_kg_build_paths.py` (9 tests) runs the command's actual Step 0b block, extracted from
  `commands/kg-build.md`, over a directory whose own path holds a space and whose files hold spaces, accents
  and an upper-case extension. It covers a directory, a single file, a glob, a quoted path, and a missing
  path that must still fail loud, and pins the directory listing against the engine's own SourceSet, the
  absence of the two splitting constructs from the code, and the `$1` and `source_path` wording. On Windows
  it runs under Git Bash, the shell Claude Code uses there; the `bash` on a Windows runner's PATH is the WSL
  stub, which is why `test_waves.py`'s bash checks skip there. Verified as real pins: 8 of the 9 **fail**
  against the 0.4.3 command, on Linux and on the reporting Windows machine; the ninth, the missing path,
  must behave the same before and after. 1352 → 1361 passed, 3 skipped.

## 0.4.3 — 2026-11-06

Patch release for the first session after an install or an update on Windows, where the Burgess MCP server
never connected. Found on the same Windows install as 0.4.2, right after reinstalling it: `/kg-build` reported
`plugin:burgess:burgess` failed ("connection timed out after 30000ms"), and the engine's venv was left half-built
with its provision lock held by a dead process. Three defects compounded; each was measured on that machine
before it was fixed, and the fix was run there end to end. No change to the MCP tool surface, to grounding, or
to anything a warm session does.

### Fixed

- **The MCP launcher built the venv inside Claude Code's connect window.** Claude Code gives a stdio MCP server
  `MCP_TIMEOUT` ms (30 s by default) to answer `initialize`, marks it failed for the session if it does not,
  and never retries it by itself; `.mcp.json` has no per-server startup timeout. On a cold venv,
  `launch_server.mjs` ran `bootstrap.py` in its own process, in the foreground, before starting the engine. A
  cold Windows build takes minutes, so the client gave up and tore the launcher down. Node's and the `py`
  launcher's job objects kill their direct children when they close, so `bootstrap.py` died at once, with no
  chance to clean up: the lock stayed held by a dead pid and the venv half-built, while `uv`, a level further
  down, kept installing into it for 13 s. Now the launcher never builds. On a cold or stale venv it asks for a
  background build (`bootstrap.py --background`), which outlives it (checked by killing the launcher's whole
  process tree mid-wait: the build finished and sealed), and waits only while an engine started at the end of
  the wait could still answer in time, `MCP_TIMEOUT` minus a 10 s reserve. Ready by then, the engine starts in
  the same session. Otherwise the launcher exits before the client's deadline with a message, shown under
  `/mcp`, that says the setup is still running, names `provision.log`, and says to reconnect from `/mcp` once it
  is done, or to start Claude Code with `MCP_TIMEOUT=600000` so a first session waits. The early-failure heal
  follows the same rule: a background rebuild, a wait within what is left of the window, and an exit instead of
  a relaunch onto a venv being rewritten.
- **The background build opened console windows on Windows, and closing one killed it.** The SessionStart
  worker was created with `DETACHED_PROCESS`, that is, with no console at all, so Windows opened a new visible
  console window for every console program it started: `uv`, and each interpreter it runs to check the venv,
  probe it and reconcile, at every session start. Their output went to those windows instead of
  `provision.log`, and a console program whose window is closed, or that gets Ctrl+C there, exits with
  `STATUS_CONTROL_C_EXIT` (3221225786): the exit code the first build on that machine died with, mid-`uv sync`,
  with nothing in the log to say why. The worker
  now gets a windowless console of its own (`CREATE_NO_WINDOW` without `DETACHED_PROCESS`). Its children
  inherit it, so no window opens and their output reaches `provision.log`. The console is the worker's alone, so
  closing the terminal Claude Code runs in still never reaches the build. Measured with probe children under
  both flag sets: a visible window and no output in the log before, neither after.
- **Two workers writing `provision.log` at once overwrote each other's lines on Windows.** POSIX `O_APPEND`
  writes at the end atomically; Windows' C runtime only emulates it with a seek and then a write. Measured on
  NTFS: two processes writing 3 000 lines each kept 5 024 and 5 322 of the 6 000. A cold start now runs two
  workers by design (the hook's and the launcher's), so the worker log is opened with `FILE_APPEND_DATA` and
  without `FILE_WRITE_DATA`, which makes Windows put every write at the end itself, children's writes through
  the inherited handle included: 6 000 of 6 000 in every run. A failure on that path falls back to the plain open.

### Changed

- **The advisory import probes run after the venv is sealed.** The stamp is what every waiter polls for, and the
  leidenalg and divergence probes ran before it while deciding nothing. Measured on Windows with a warm uv
  cache and a fresh venv: `uv sync` 1.0 s, core import check 2.2 s, leidenalg probe 0.2 s, divergence probe
  28.5 s on a first import (over its 60 s timeout in two other runs). The venv was usable at 3.5 s and declared
  ready at 32–63 s. With the probes after the seal, a cold first session on that machine connected in 6.0 s
  instead of failing. A probe interrupted after the seal can no longer delete a sealed venv.
- **A probe that times out is no longer reported as a missing dependency.** It says the import gave no answer
  within the timeout, which a first import on a cold machine can take, where it used to say "divergence deps
  unavailable … /kg-diverge degraded until provisioned".
- **`bootstrap.py --background` reconciles only when `--reconcile` is passed with it.** The SessionStart hook
  passes it, so the once-per-session sweep (§1.8) is unchanged. The launcher's builds do not, so a cold start
  does not sweep twice.
- **A worker that finds the build already done says so** ("Another setup just finished — engine ready."). That
  is how the second worker of a cold start usually leaves, and it used to print nothing, so its stanza in
  `provision.log` read like a worker that had died.

### Not changed

- **A first install with an empty uv cache can still outlast the first session's window.** Downloading the
  dependencies is network-bound. What changes is what the user gets: a message saying what is happening and
  what to do, a build that keeps going, and a reconnect that works, instead of a timeout and a wedged venv.
- **An install left half-built by 0.4.2 heals itself.** The next build reclaims the dead holder's lock (pid
  probe) and reuses or rebuilds the venv through the existing owner-sentinel path. Nothing to clean by hand.

### Tests

- `tests/test_fix_cold_start.py` (17 tests) runs the shipped launcher against a fake plugin root, a recording
  `bootstrap.py` and a recording engine. A cold launch asks for exactly one background build, without
  `--reconcile`, and never builds in its own process. It waits for the window and no longer, starts no engine on
  an unready venv, and exits 1 with the message on stderr and a line in `server.log`. A build that lands inside
  the window starts the engine in the same session, a warm venv starts no build, and a startup crash forces a
  background rebuild and exits when it does not land in time. On a fake clock, the window follows
  `MCP_TIMEOUT` and the wait never sleeps past its deadline. On the bootstrap side: the worker's creation flags,
  `--reconcile` forwarding, the hook as the caller that asks for the sweep, two concurrent appenders and their
  children keeping every line, the probes running after the seal, an interrupted probe keeping the venv, the
  timeout wording, and the waiter's log line. One test runs only on Windows and repeats the console
  measurement; its body, run on the reporting machine, passes with the shipped flags and fails with
  `DETACHED_PROCESS`. Verified as real pins: 15 of the 16 that run on Linux **fail** with the fix reverted; the
  16th pins the warm path, which must not change. 1336 → 1352 passed, 2 → 3 skipped.

## 0.4.2 — 2026-11-06

Single-bug patch release. With the plugin enabled, **every** Claude Code session left Burgess files in the
folder it opened — an empty `canon/`, `.kg-reconcile-state.json`, `.kg-ground-audit.jsonl.ckpt` and, in a git
repo, five lines in `.git/info/exclude` — even when nothing in the session used Burgess, and the two files
were rewritten every session. Found on a Windows install with leftovers in twelve folders, a home directory
and an Obsidian vault among them; the vault's auto-commit pushed the checkpoint to its remote, because on that
version (0.2.5) the exclude did not yet cover the `.ckpt` sidecar (fixed in 0.3.1).

Two automatic triggers, and the first one defeated the guard of the second. No change to the MCP tool
surface, to what grounding decides, or to the per-session full sweep in any folder that holds a canon.

### Fixed

- **The MCP server laid out a vault in whatever folder a session opened.** Claude Code starts every enabled
  plugin's MCP server at session start, `.mcp.json` passes `KG_PROJECT_DIR=${CLAUDE_PROJECT_DIR}`, and
  `main()` builds the engine before the first request. `KGEngine.__init__` constructed `Canon(project_dir)`
  with its default `ensure_layout=True`, which creates `canon/` and appends the runtime patterns to
  `.git/info/exclude`, so both appeared before any tool was called. The engine's `Canon` is now lazy, as the
  precontext hook's already was (F37): building the engine and every read leave the folder untouched, and the
  first write lays the vault out. `Canon.acquire_lock`, which every canon writer reaches (`write_one`,
  `write_nodes`, the server's `_try_writer_lease`), calls the new public `Canon.ensure_layout()` before the
  lease file exists, so the lease and every runtime file after it are already git-excluded when they first
  appear. `try_acquire_lock` deliberately does not: its other caller is the lazy projector, on the read path,
  where a query must never turn a folder into a vault.
- **…and that empty `canon/` switched the per-session reconcile on everywhere.** The SessionStart hook
  (`provision.mjs` → `bootstrap.py --background` → a detached `--reconcile` worker → `maybe_reconcile`) ran
  the sweep wherever `canon/` was a directory, which the first defect made true in every folder from the first
  session on. `Reconciler.scan()` then wrote the state file and the checkpoint unconditionally. The guard now
  asks whether the folder holds a project, meaning at least one canon note or a non-empty audit ledger
  (`bootstrap._holds_project`), and the sweep's `Canon` is lazy too. The full sweep itself is unchanged wherever
  there is a canon: it is what defeats mtime-spoofed forged verdicts (§1.8), so every project still gets it
  every session, state and checkpoint included.
- **The sweep wrote even with nothing to reconcile.** Defense in depth for anything that reaches `scan()` past
  a guard: with no note, no audit record and no baseline, spend ledger or file cache (not even one recovered
  from the checkpoint), it now returns without touching the disk. That is safe for §1.8 because an empty state
  reads back exactly like a missing one (`_load_state`'s fail-open default *is* the empty form), so skipping
  the write can never strand a stale baseline. A non-empty baseline (every note deleted since the last sweep)
  still takes the full sweep and is pruned and persisted (reconciler-1). The early return also skips the
  sweep's housekeeping, which deletes `.tmp-*` files older than an hour at the folder root. In a Burgess vault
  those are its own crash leftovers; in a home directory or an unrelated repo they are somebody else's, and
  until now the sweep ran there too.

### Changed

- **A fresh clone gets its exclude patterns from the first sweep or write, not from server startup.**
  `.git/info/exclude` is per-clone and never cloned. The eager server used to write it at startup; now the
  first session's reconcile writes it (the sweep lays the vault out before it persists its state), or the first
  write does. Either way it lands before the first runtime file, which is the property that matters.

### Not changed

- **Existing leftovers are left alone, never deleted.** An empty `canon/` counts as no project, so neither the
  hook nor the sweep writes to a folder that only carries the leftovers of an older version. To clean one by
  hand, in a folder that never held notes: remove the empty `canon/`, `.kg-reconcile-state.json`,
  `.kg-ground-audit.jsonl.ckpt` (only when no `.kg-ground-audit.jsonl` sits beside it) and the five Burgess
  lines in `.git/info/exclude`.
- **A bare dev launch without `KG_DATA` still puts the data dir at `<project>/.kg-data`**, where the Node
  supervisor and the server log both write before the engine exists. The installed plugin always sets
  `KG_DATA` to the plugin's data directory, so this never happens in a user's folder.

### Tests

- `tests/test_fix_session_start.py` pins the defect end to end: building the engine like the server (with the
  data dir outside the project) writes nothing and neither creates nor modifies `.git/info/exclude`; reads lay
  nothing out; `maybe_reconcile` over an empty `canon/` launches no sweep and writes nothing, and leaves old
  leftovers byte- and mtime-identical (a user's aged `.tmp-*` included); a real canon is still swept, state and
  checkpoint included; the first `kg_write` creates `canon/` and the excludes, and the excludes land before the
  lease file; a fresh clone gets them before the sweep writes its state; deleting every note still prunes the
  baseline; and `bootstrap`'s mirrored names and note rule agree with `canon`'s. Each hook test runs the real
  sweep in a subprocess and requires it to exit clean, so a crashed sweep can never pass for an empty one.
  Verified as real pins: 22 of the 26 **fail** with the fix reverted; the other four pin what must not
  change. 1310 → 1336 passed, 2 skipped.
- Three existing tests adjusted. `test_valid_json_non_dict_state_does_not_crash_scan` (F19) now seeds a note,
  as its null-sub-key sibling already did, because an empty vault no longer rewrites a corrupt state; that
  case has its own pin. `test_fate_sync_skips_a_malformed_note_instead_of_failing` lays the vault out before
  planting its malformed note by hand. The F37 docstrings describe the new lazy write path.

## 0.4.1 — 2026-08-01

Single-bug patch release, and the bug is one the test suite had already been reporting for a while in a form
nobody could act on: an intermittent `windows-latest` failure that passed on rerun. It was never the test.

### Fixed

- **A provision lock could outlive the process that owned it, on Windows.** Found as a CI flake —
  `test_concurrent_provisioners_run_one_build_and_none_starve` failing on `windows-latest` with "the provision
  lock outlived the wave", then passing on a rerun of the identical commit. It was not a flaky test.
  `dirlock.release` moves the live lock **directory** aside with `os.replace` before removing it, and every
  waiting provisioner has a file inside that directory open: each poll runs `try_acquire` → `is_stealable` →
  `parse_info`, which **opens `lock/info`**. Python's `open()` does not grant `FILE_SHARE_DELETE`, so on
  Windows that rename raises `PermissionError` (ERROR_SHARING_VIOLATION) — which `release` read as "already
  gone/reclaimed", dropping its ownership token and returning with the lock dir still there. The one process
  that could clean it up had just forgotten it owned it. Not a wedge: the leaked lock names an exited pid, so
  the next acquirer's `pid_probe` reclaims it in milliseconds — unless the OS had recycled that pid, in which
  case the next session waits out `STALE_LOCK_SECS` (**30 minutes**) in the least recoverable part of the
  install.
- **…and the same rename was unguarded on three more paths.** `_steal`'s reclaim (a violation abandons the
  steal for the round, costing the waiter a whole `POLL_SECS`) and both restore paths. The restore inside
  `release` is the one that mattered most: its existing fallback **deletes** the directory it could not put
  back, and that directory belongs to a successor who may be live — so retrying the transient is what keeps a
  sharing violation from escalating into destroying someone else's lock.

The repo already had this discipline in two places and `dirlock` never received it: `atomicio._replace_with_retry`
and `canon._replace_lockfile`, whose docstring names the identical mechanism ("concurrent waiters may have it
open for read; on Windows that raises PermissionError … because Python's `open()` does not grant
`FILE_SHARE_DELETE`"). Same shape as 0.4.0's through-line — a rule single-homed and then extended, with a
consumer left behind. `dirlock` now has its own local `_replace_with_retry`, kept local rather than imported
because the module's defining constraint is being a stdlib-only leaf importable by a bare system Python before
any venv exists (it already keeps a deliberate parallel copy of `_win_pid_alive` for the same reason).

Two things the retry deliberately does **not** do. Its budget is **2 s**, shorter than the 5 s used by
`atomicio`/`canon`, because the cost of giving up differs: there a lost rename fails a *write* and rolls back a
whole build wave, here it leaks a lock that self-heals — and `release` runs from bootstrap's `finally` as the
session exits, so the budget is bought with exit latency. And it retries **`PermissionError` only**: a
genuinely lost race surfaces as `FileNotFoundError`, which must back off immediately rather than sleep out a
budget waiting for a directory that is already gone.

### Tests

- Four pins in `tests/test_bootstrap.py` inject the sharing violation directly, so the regression fails on
  **every** platform instead of occasionally on one CI leg — the failure mode that let this ship was a real
  bug presenting as an unreliable test. They cover the release leak, the bounded degradation when the
  violation never clears (`release` must still not raise at exit), the steal path, and the guarantee that a
  lost race is not slowed by the retry budget. Verified as real pins: all four **fail** with the fix reverted.
  1306 → 1310 passed, 2 skipped.

## 0.4.0 — 2026-07-31

First tag since **v0.3.1**, and it therefore also carries everything in 0.3.2 below — that version was
declared in the manifests and written up here, but never tagged or released.

One theme runs through the whole release: **code that was internally consistent and disagreed with something
else.** Every defect below passed the full suite straight through, because no single consumer was wrong on
its own terms — a candidate id was a primary key nothing treated as one, three writers guarded one invariant
with two locks, and a live-topology vocabulary got extended while two readers stayed on the older form. That
is why the fixes come with pins rather than just patches: the failure mode is silence, not a stack trace.

One agent-facing contract change comes with them (`parents` → `slate_ids` on the ingest response), which is
what makes this a minor rather than a patch. No change to the 27-tool MCP surface's shape, no change to what
grounding decides, and nothing here can touch a verdict — the import firewall (I3) still holds in both
directions.

Six of the **divergence-lane** fixes were first made in [Cambrian](https://github.com/sergiparpal/cambrian)
after the Stage-0 pin (`ddca026`) and are reimplemented here against Burgess's own state layout. The
convergence-spine fixes are Burgess's own. The donor pin is unchanged:
it is a permanent Stage-0 identity, not a sync point (see README → *Lineage*).

### Fixed

- **`obsolete` was still live topology on two read surfaces.** `model.NON_LIVE_STATE_VALUES` (the failure
  states *plus* the superseded `obsolete`) is the single live-topology vocabulary, and review-fix L14 / r11
  moved `projector._live_subgraph`, `generate._live_undirected` and `kg_context`'s answer lane onto it — but
  `DerivedReader.shortest_path` and the `kg_agenda` builder kept filtering on the narrower failure-only set.
  On one graph that meant `degree(a) = 0`, zero `kg_context` items, and `shortest_path(a, b) → ['a', 'b']`:
  a path presenting connectivity every other surface called dead. In `kg_agenda` the same gap made a node's
  detector depend on *which* non-live state its other edge held — `rejected`/`failed` fired
  `hypothesized-only`, while `obsolete` dropped the node from the agenda entirely, because `deg` (read from
  the nodes table, computed *without* the obsolete edge) and the local `live` set disagreed about that one
  edge. The edgeless-communities crossing test had it too: a cluster reachable only through a superseded
  edge was not flagged as disconnected. `kg_context`'s falsification counter deliberately **stays** on the
  failure set — it counts refutations, and `obsolete` is a lifecycle transition, not negative information
  (§1.7). That exception is pinned, so nobody "consistently" widens it.
- **One malformed canon note failed the whole read.** `_sync_materialized_fates` caught only
  `FileNotFoundError` around `canon.read_node`, so a note that was *malformed* rather than missing (broken
  frontmatter, a BOM, a CR-only file) escaped through `_tool_result` and turned an entire
  `kg_diverge_recall` / `kg_diverge_metrics` call into `{ok: false}` instead of skipping one ledger entry.
  Every other `read_node` call site already caught broadly per §1.2 — *one bad note must not crash every
  read* — and this was the last outlier.
- **The canon merge driver dropped a verdict without saying so.** `canonmerge.merge_nodes` suppressed the
  node-level demotion note when `merged.epistemic_state` was already `unverified` — but `merged` starts as a
  deepcopy of *ours*, so the suppressed case was precisely the one where *theirs* held the verdict being
  dropped. The resolution was always correct (no verdict was ever forged); the operator just never saw the
  conflict. The mirrored edge branch always reported it.
- **An atomic write would have preserved the wrong file's mode on a symlink destination.** `atomicio` copies
  the destination's permissions onto the temp file before `os.replace`, but was reading them with `stat()` —
  the *target's* mode. `os.replace` replaces the **directory entry** at `path`, so when `path` is a symlink
  the entry that survives is a regular file and the link is gone; copying the target's mode would apply an
  unrelated file's permissions to the one just written. Latent rather than observed — it is identical to
  `stat()` for the regular files every engine caller passes — but `bootstrap.py` shares this module, so
  `follow_symlinks=False` now makes the code say what the replace actually does.

- **A duplicate candidate id inside one generation was absorbed, not rejected.** An id keys every downstream
  store at once — the archive's `elite_id`, the candidate record store, both embedding stores, pins/discards,
  and the slate's `embedding_ref`. Two candidates sharing one id therefore *both* won a niche while only the
  last record survived in the store, so one niche silently ended up pointing at a different idea's text,
  coords and embedding, and the slate could render the same item twice. Dedup could never catch it: dedup
  compares text, not ids. `_parse_candidates` now names the offending ids and rejects the batch.
- **…and the cross-generation twin was worse.** A later cycle — or a later session, where a fresh agent
  restarts its `c-0001` counter — could resubmit an old id under new text and overwrite that id's record
  while the niche it was already elite of kept pointing at it. An *existing* archive entry then quietly
  acquired a different idea's content. `_guard_id_reuse` runs before any embedding (a rejected batch costs
  no model work) and inside the project lock (so the store it reads is the store the write will use).
  Resubmitting a candidate **verbatim** stays legal: identical text embeds to cosine 1.0 and dedup drops it
  as the no-op it is, so only a text change is a collision.
- **Pins and discards are one invariant and were guarded by two locks.** `add_pin` locked `pins.json` while
  `add_discard` and `remove_discard` locked `discards.json` — yet every one of them mutates *both* files
  (pinning drops the discard, discarding drops the pin, un-sealing edits a list a pin may be racing on). A
  concurrent pin and discard of the same id took different locks, interleaved their read-modify-writes, and
  could leave that id in both lists or in neither. "Latest action wins" stopped holding silently, and with it
  the mutual exclusivity the propose lane relies on. All three writers now share one `_preference_lock`.
- **`recall` / `metrics` / `parents` could observe a cycle mid-write.** `ingest` rewrites archive +
  candidates + both embedding stores + meta together under `project_lock`; those three commands read several
  of the same files and read them unlocked, so a new `archive.json` could be paired with an old
  `candidates.json` — an elite whose record is not there yet. `State.project_read_lock` snapshots them under
  the same lock, with the same best-effort semantics (on timeout it proceeds, so a reader is never blocked
  for long by a writer) and a deliberate no-op on a project dir that does not exist: a read-only command must
  not materialize state as a side effect.
- **The empty-generation response KeyErrored on the path its own docstring called safe.** `_empty_cycle`
  promises a consumer "never KeyErrors on an empty generation", but it set the `variety_eroding` boolean
  without the `variety_erosion` detail dict every normal cycle carries. The code was wrong, not the
  docstring: the dict is now emitted with the same key set, slopes `None` (an empty generation has no
  survivor novelty to measure) and the persisted streak reported unchanged.
- **A pin could outlive the idea it names and be bred from anyway.** `init-project` resets the geometry on an
  axes change but deliberately preserves preference memory, and `select_parents` always keeps pins — so a
  pinned id with no candidate record reached the parent list and was emitted with an empty `text`: a
  contentless stepping stone. Those ids now go to an optional `stale_pins` / `stale_pins_note` pair instead.
  The keys are *absent*, not empty, on the happy path — an optional key is a weaker promise to callers than a
  key that is sometimes an empty list.
- **The judge rubric quoted a threshold the engine does not hold.** It named a "~40% over-filtering budget",
  a number that appears nowhere in the code; the actual knob is `under_generation_ratio = 0.6`. Prose quoting
  a number the code does not hold is a slow-motion drift bug, so the rubric now names the guard.

### Changed

- **The `mcp<2` cap is documented as load-bearing, and pinned like it.** Verified rather than assumed: mcp
  2.0.0 **removed** `mcp.server.fastmcp` and the `FastMCP` class entirely (the server API moved to
  `mcp.server.mcpserver`), so a bump past `mcp>=1.2,<2` raises `ModuleNotFoundError` at startup and drops
  every `kg_*` tool for the session. Adopting 2.x needs a real port of the tool surface and
  `readiness_lifespan`, not a version edit. The existing coverage guarded that import behind
  `pytest.importorskip`, so it would have **skipped** on exactly the bump that breaks production — the
  "coverage vanishes with the suite still green" hazard the CI config already calls out for the Node
  launcher tests. `tests/test_review_r12.py` now asserts the import path hard.
- **Dependabot no longer proposes mcp majors it can never land.** It runs weekly on pip, so it would keep
  opening a 2.x PR that CI correctly fails and a human correctly closes — recurring noise that trains
  everyone to skim the one file where skimming is most expensive. `.github/dependabot.yml` ignores
  `version-update:semver-major` for `mcp` **only**, deliberately not the whole dependency: 1.x minor and
  patch releases, security fixes included, must keep flowing, since 1.x is the line the engine is pinned to
  until the port happens. The entry carries the reason and comes out *as part of* that port — an
  unexplained suppressed dependency is the same "rule extended, consumer left behind" shape as the defects
  above.
- **The divergence lane no longer reads as foreign code.** A mechanical PEP 585/604 typing sweep
  (`Dict`/`List`/`Tuple`/`Set` → builtins, `Optional[X]` → `X | None`, `Union[A, B]` → `A | B`,
  `Sequence`/`Callable` → `collections.abc`) retired the Python 3.9-era `typing` imports inherited from the
  Cambrian donor, which were the last visible seam between the two halves of the fusion. Annotation-only and
  safe by construction: every touched module already carries `from __future__ import annotations` and none
  evaluate annotations at runtime (checked, not assumed), and the rewrite ran through a tokenizer that masks
  every string and comment token first — the diff contains zero comment lines. `scripts/bump_version.py` and
  `projector.py`'s `Callable` came along as the last holdouts outside the lane. `Any`/`NamedTuple`/
  `TYPE_CHECKING` stay on `typing`: no builtin form, a runtime base class, and a runtime flag respectively.
- **The boundary's node-lane flood charge is written in the shape it is documented as mirroring** — the same
  form as the edge lane. Behavior identical.

- **The ingest response field `parents` is now `slate_ids`** (breaking, agent-facing JSON). Those ids are the
  slate items: they honour neither pins nor discards, so a caller that read the name literally and bred from
  them skipped both of the user's levers. The `parents` **command** is the only source of parents; its
  `{"parents": [...]}` return, `genealogy.parents` in candidate payloads, and argparse's `parents=` kwarg all
  mean different things and are untouched. The local variable holding the ids was already called `slate_ids`.
- **The version is declared in six places and now something asserts they agree.**
  `tests/test_version_consistency.py` cross-checks all five declaration sites (both `.claude-plugin`
  manifests, `kg_engine`, `kg_engine.divergence`, `pyproject.toml`) — `kg_engine.divergence.__version__` was
  outside every existing gate — and `tests/test_e2e_generative.py` no longer compares against a hardcoded
  literal, which had made the test itself a seventh site to remember on every bump.
  `scripts/bump_version.py` rewrites all five at once, refuses to bump from an inconsistent state, and is a
  dry run unless `--write`. It is not a release driver: Burgess publishes to no package index, and the
  annotated tag and GitHub release are still cut by hand, so only the version-site sweep was worth taking.
  (An earlier draft of this entry claimed Burgess "cuts no GitHub release" — wrong, and corrected here:
  every version from 0.2.4 to 0.3.1 has one. 0.3.2 is the release that was written up and never tagged,
  which is why this tag carries it.)

### Dependencies

- **Four floor raises inside the existing major caps**, all green across the 3.10–3.14 matrix: `pydantic`
  `>=2` → `>=2.13.4`, `scikit-learn` `>=1.4` → `>=1.7.2`, `model2vec` `>=0.3` → `>=0.8.2`, and
  `anthropic` `>=0.77` → `>=0.120.1` in the `backend` extra. No upper bound moved — the caps are the part
  that is load-bearing.
- **`mcp` stays capped at `<2` and Dependabot no longer asks.** See *Changed* above; the ignore is scoped to
  major updates only, so 1.x security patches keep flowing.
- **The dependency comment column was realigned to 33.** Dependabot preserves whatever padding it finds, so
  the four floor raises split the trailing-comment column three ways (28 / 31 / 33). Whitespace only,
  verified with an empty `git diff -w` and a `tomllib` comparison of the parsed requirements — it will drift
  again on the next bump, which is a two-minute fix and not a reason to adopt a formatter this repo has
  deliberately never had.

### Docs

- `docs/ARCHITECTURE.md` §3.2 states the live-topology vocabulary as a contract: what
  `NON_LIVE_STATE_VALUES` is, the five surfaces that must agree on it, and the one deliberate exception.
  §3.5 no longer calls the rank subgraph "non-failed" (it is the *live* subgraph — failures *and*
  `obsolete`), §9 records the version-consistency gate and the load-bearing mcp pin, and §9/§11 carry the
  I11 donor gate as it actually behaves since 0.3.2: **reachability** of each pinned Stage-0 commit from its
  donor's `HEAD`, not a frozen `HEAD` or a clean donor working tree. README, `MIGRATION.md` and the
  `docs/fusion/` record were corrected when Cambrian was republished; ARCHITECTURE was the surface left
  behind.
- `docs/fusion/DECISIONS.md` records the asymmetry as a decision, since it is the one a future reader will
  want to "fix": the widening is the consequence, the **falsification counter not following it** is the
  decision. Consistency of vocabulary is not consistency of meaning.
- `CLAUDE.md` carries the mcp cap and the five version sites, the two things an agent could plausibly break
  by being helpful.

### Tests

- `tests/test_review_r12.py` pins all of the above — the non-live vocabulary itself, `shortest_path`, both
  `kg_agenda` gaps, the falsification-counter exception, the malformed-note skip, the merge-driver note, and
  the mcp import path — each with its control. Confirmed to be real pins: with the fixes stashed, exactly
  the six expected cases fail while the controls and the `rejected`/`failed` parametrizations stay green.
  1287 → 1306 passed, 2 skipped.

## 0.3.2 — 2026-07-30

Concurrency and supply-chain release. The headline is the **canon lease's FIFO handoff**: a CI flake that
looked like slow IO turned out to be starvation, and the measurement that found it — an ~11 ms critical
section against a 3.29 s wave, i.e. 96% of the wall time asleep with the lease *free* — is why the first fix
was thrown away rather than kept. The rest is the security posture now shared across all six plugin
repositories, and the I11 donor gate corrected to enforce the invariant instead of a proxy for it. No change
to the 27-tool MCP surface and no change to graph semantics — grounding output is untouched.

### Fixed

- **The single-writer lease starved its own waiters.** Every contender polled the lease on its own capped
  exponential backoff, which cost two things at once: a handoff took up to `LOCK_RETRY_MAX` (0.5 s) no
  matter how brief the write, and *nothing ordered the contenders*, so a writer could lose race after race
  until its `LOCK_ACQUIRE_TIMEOUT` expired and it surfaced the by-design locked-vault error. That is how the
  ten-writer wave test flaked on CI — three writers burning the whole budget while seven drained past them.
  The blocking acquire now waits in a **FIFO ticket queue** under `.kg-session-lock.q/` where only the
  *front* waiter polls the lease, which is what lets that poll be short (prompt handoff) without a
  thundering herd; the same wave drains in ~0.2 s at the production budget. Tickets are pure ordering: one
  never grants the lease and never bypasses `acquire()`'s O_EXCL/reclaim CAS, so a lost or forged ticket
  costs a waiter its place in line and nothing else (**F16** single-writer safety is untouched). An
  uncontended write — nearly every write, since a build wave funnels through the one server process — keeps
  a fast path that never touches the queue, and `try_acquire_lock` stays strictly non-blocking and unqueued.
- **…and the queue then starved them worse on Windows.** POSIX `unlink` succeeds with the file still open;
  Windows raises `ERROR_SHARING_VIOLATION` — the same hazard `_replace_lockfile` already exists for — and
  the front waiter's ticket is the *most-read file in the queue*, because every waiter behind it opens it to
  check liveness. So the one dequeue most likely to fail was precisely the one that parks everybody, and
  since tickets carried the lease's 120 s TTL that ghost blocked the queue far past the 30 s budget. Four
  changes, each measured against a simulation that fails ticket unlinks at a set rate: tickets carry their
  own short `LOCK_QUEUE_TICKET_TTL`, so a leaked one expires in seconds; liveness probes are throttled to
  ~1/s with position otherwise taken from the directory listing (probing every poll is what aimed the read
  pressure at the front ticket); ticket reads are **fail-closed**, since reaping a live waiter would push it
  to the *back* of the queue, a starvation amplifier strictly worse than the unfairness the queue removes;
  and a ticket proved dead yields its place whether or not the unlink lands, plus a `LOCK_QUEUE_STALL_SECS`
  valve that abandons the queue for the unfair loop if position stops improving. Gating that skip on the
  unlink landing — the first attempt — made queue *liveness* depend on deletion succeeding, and lost 8 of 10
  writes where deletes fail outright. The structural rule this leaves behind: **keep liveness on the rename
  side of the line.** Both locks already make progress depend on an atomic rename, with every following
  delete only cleaning a sideline; the ticket queue briefly inverted that, making a file's continued
  *existence* the blocking signal.
- **`_atomic_write` temporaries were counted as queue waiters.** `mkstemp` inherits the target's suffix and
  lands in the same directory, so a naive `*.json` listing saw `.tmp-XXXX.json` as a waiter ahead of the
  whole queue (`.` sorts before every digit) and then reaped it — deleting another waiter's in-flight write
  and silently degrading it. `_ticket_names` now excludes the `.tmp-*` prefix the canon already reserves for
  exactly this.
- **The I11 donor gate enforced a proxy that had stopped being true.** It asserted "each donor is frozen
  exactly where Stage 0 left it", which held only while both donors stayed retired — Cambrian has since been
  republished and resumed development, so the gate began failing on every commit while the invariant it
  protects (the fusion never wrote to a donor) stayed perfectly intact. The sibling checkouts were also
  renamed to lowercase, so the pinned relative paths stopped resolving at all. `check_donors_clean.py` now
  asserts that each pinned Stage-0 commit **still exists and is reachable from the donor's `HEAD`**, which
  keeps exactly what the invariant is for: the copied-from tree stays recoverable with `git show <sha>`, so
  every `ATTRIBUTION.md` claim remains checkable. An *unreachable* pin is still a hard failure — that is
  where provenance is genuinely lost. Donor working-tree cleanliness and an unmoved `HEAD` are deliberately
  no longer asserted; a live repository has neither, and neither says anything about what the fusion did.
- **A test regex could backtrack exponentially** (CodeQL `py/redos`, high). In `_registered_mcp_tools`'s
  `@mcp.tool()` scrape, `\s` also matches `\n`, so `\s*\n\s*` could split a run of newlines many equivalent
  ways, and nesting that in `(?:...)*` multiplied them — measured at 83 ms for 20 repetitions of the
  pathological input, quadrupling every two (~85 s extrapolated at 30). Rewritten with `[ \t]` for
  horizontal whitespace and every line break written explicitly: flat at ~0.02 ms. Both patterns scrape the
  identical set of 27 tools, verified by set comparison before the change. The exposure was never real — the
  input is this repo's own `server.py`, not attacker-controlled — but the pattern was genuinely vulnerable,
  so bounding it beats dismissing the alert.

### Changed

- **CI declares its own security posture.** `permissions: contents: read`, so the read-only guarantee lives
  in the file and survives a change to the repository-level setting; `concurrency` with `cancel-in-progress`,
  so a superseded push stops burning minutes; and `timeout-minutes` on every job, because without one a hung
  job holds a runner for the six-hour default. A `ci-complete` aggregating job gives the branch ruleset one
  stable name to require — naming the matrix legs would mean that dropping a Python version leaves an
  unsatisfiable required check blocking every merge. **Any new job that must gate merges has to join its
  `needs:` list.**
- **GitHub Actions are pinned to full commit SHAs**, never tags: a major tag such as `@v5` is mutable by
  whoever controls the action's repository, and the workflow would pick up the repoint on its next run with
  no diff here to show for it. Dependabot is enabled (weekly, five open PRs per ecosystem) and has since
  proposed `checkout` v7.0.1, `setup-python` v7.0.0 and `setup-node` v7.0.0, all merged.
- **`anthropic` is capped below its next major** (`>=0.77,<1`) — it was the only dependency left uncapped, so
  a fresh venv resolving from these constraints could pull a 1.0 that nothing here has been tested against.
  `leidenalg` moves to `>=0.12.0,<1`.
- `SECURITY.md` added, pointing at private advisory reporting and scoped to the MCP server, source-document
  ingestion, the provisioner and local state.
- README refocused on the current plugin workflow; the large fossils image dropped from the repo.

### Documented

- **Two new decision records** in `docs/fusion/DECISIONS.md`. The lease queue records the measured bug, the
  line the design must not cross (a ticket orders waiters but never authorizes one — the same shape of rule
  as I5's advisory ceiling), and the fact that the **first diagnosis was wrong**: the flake was read as
  slow-IO fsyncs and treated by raising the test's budget, a reading that does not survive instrumentation
  and is exactly the plausible wrong answer a future reader reaches for again.
- **The provision lock stays unordered, and that is now a checked claim.** The queue's sibling question was
  whether `dirlock` needed the same treatment, and the claim that it "has the same unfair-backoff shape" was
  wrong — it has no acquire loop at all, and the waiting lives in bootstrap's `_wait_for_lock` on a *fixed*
  2 s poll. The deeper reason the queue does not belong there: a canon waiter needs a **turn** (every writer
  must eventually write, so losing races exhausts its budget and fails the write, which is exactly how the
  flake presented), while a provisioning waiter needs an **outcome** — the venv being ready — and leaves on
  the `venv_current` check without ever taking the lock. Measured at 20 concurrent sessions: all 20 exit at
  2.02 s for a ~0 s build and 4.01 s for a 2 s build, one build, zero timeouts, with overhead independent of
  session count. The Windows failure above then settled it with evidence rather than structure: the queue's
  real cost was not its line count but acquiring a platform-specific failure class that needed a simulation
  harness and five CI samples to believe — a bad trade for the least recoverable part of the install.
- `CLAUDE.md` documents the branch-ruleset git workflow and the SHA-pinning rule, and its Donors section is
  corrected to the reachability gate. It previously described a rule that no longer exists, which would have
  told the next agent to expect a frozen donor `HEAD`.

### Tests

- `tests/test_fix_canon.py` pins the queue: arrival-order service, stale-ticket reaping, degradation when the
  queue is unavailable, leaked-ticket expiry on the ticket TTL, unreadable tickets respected rather than
  reaped, a dead-but-undeletable ticket yielding its place, the wedged-queue valve, `probe=False` opening no
  ticket, `.tmp-*` temporaries not counted as waiters, and an uncontended write never creating the queue at
  all. Each was checked to **fail** with only its own mechanism defeated; one was vacuous on the first
  attempt (a free lease let the writer take the fast path and skip the queue entirely) and was rewritten.
- `tests/test_bootstrap.py::test_concurrent_provisioners_run_one_build_and_none_starve` — N concurrent
  provisioners must produce exactly one build and leave no waiter sitting out its deadline. It drives real
  subprocesses rather than threads because `dirlock._OWNED_TOKENS` is module state, a sharing hazard that
  cannot exist across the separate processes this lock actually serializes. Confirmed non-vacuous: a lock
  that always grants runs 4 concurrent builds, and a build that never finishes leaves 3 waiters timed out.

## 0.3.1 — 2026-07-09

Correctness, robustness and performance sweep from an eleventh exhaustive review (**review-r11**). Two
HIGH findings, both §1.7 breaches reachable through ordinary tool use, and both with a working guard on
the sibling code path — which is what made them findable. No change to the 27-tool MCP surface. Pinned by
`tests/test_review_r11.py`, every test of which was mutation-verified to fail on the pre-fix tree.

### Fixed

- **HIGH — permanent negative memory could be laundered away.** `reconciler._restore_erased_negative`
  only fired when the current state was `unverified`, so a canon edit taking a `rejected`/`failed` edge
  *into* a groundable state (`rejected` → `grounded`) was detected as a forgery but reset to `unverified`
  rather than restored. The edge then dropped out of `failure_ids`, so the write boundary stopped
  quarantining re-proposals of the refuted claim — and since `unverified` became the new baseline, no
  later sweep could recover it. `_requarantine_state` now restores the failure baseline the forge
  overwrote. The two guards are the two halves of one rule: **an out-of-band edit may never be the thing
  that ends a falsification.**
- **HIGH — a grounded node's evidence was destroyed by a routine re-write.** A `Node` has no `span`
  field, so `_promote_hypothesis_node` restates its support in the node *body*. The edge lane quarantines
  a re-emit of a settled edge; the node lane had no such guard and simply overwrote the body, leaving
  `epistemic_state=grounded, provenance=span-present` with no span anywhere — the exact state the design
  exists to make unrepresentable. `canon._merge_into_existing` now refuses to let an incoming body blank a
  verdict-bearing node's evidence, mirroring the edge guard.
- **The divergence import firewall (I3) is now enforced in both directions, not just documented.** The
  existing test policed only "the verdict path may not import `divergence`". The converse rested on
  convention: a divergence module could `from ..canon import Canon` + `from ..model import EpistemicState`
  and stamp a verdict straight into a canon note, with the entire suite green (verified by mutation).
  `test_i3_divergence_cannot_reach_the_verdict_machinery` now polices the *capability* via an allowlist —
  divergence may import the stdlib, its numeric deps, its own siblings, and the two capability-free leaves
  `atomicio`/`envconfig`, nothing else in `kg_engine`. Without `model` there is no `EpistemicState` to
  assign; without `canon`/`boundary`/`server` there is nothing to write one to. Lazy imports count. This
  is what makes the verdict monopoly (I1) structurally true from the geometry side.
- **`kg_status` bypassed the §1.9 egress scrub.** Its `coverage.sections[].title` is a `##` heading read
  verbatim from the *unscrubbed* source, so a secret in a Markdown heading crossed the boundary intact —
  the one read tool not routed through `_scrub_egress`.
- **`kg_explain_path` could SIGKILL the engine.** Cost is quadratic in the caller-supplied `nodes` list
  (a BFS per pair over the grounded closure), which is unbounded: 400 nodes took ~10s, 1500 exceeded the
  300s `DEFAULT_HANDLER_TIMEOUT`, at which point the watchdog's `_hard_exit` kills the process. Capped at
  `pathing.MAX_EXPLAIN_NODES` (32), refused before any graph work.
- **A corrupt `consumed` value permanently disabled forge detection.** `_load_state` fails open on every
  other corruption class, but a non-int inside the spend ledger raised `TypeError` in `_drain_key_ledger`
  — before `_save_state` could heal the file, so every later sweep crashed too. Non-int values are now
  dropped on load (forgetting a *spend* over-quarantines; it can never miss a forgery).
- **`canonmerge` spuriously conflicted CRLF/BOM canon notes.** The edgeless/unparseable fast path handed
  raw text to `git merge-file`, where a Windows-saved note differs from its LF twin on every line. Both
  paths now normalize through the single-homed `model.normalize_note_text`.
- **The generators walked a different topology than the ranks they read.** `generate._live_undirected`
  excluded only the failure states while `projector._live_subgraph` also drops `obsolete` — while its own
  docstring claimed the two mirrored. Both now share `model.NON_LIVE_STATE_VALUES`.
- **`divergence._niche_slug` collapsed non-ASCII categorical values into one MAP-Elites niche.** Any value
  whose characters all fell outside `[a-z0-9]` slugged to the literal `none`, so on a non-Latin brief (the
  case the multilingual embedder exists to serve) two different ideas fought over one cell and
  one-elite-per-niche evicted the loser. Lossy slugs now carry a hash, as the sibling `state._path_slug`
  already did.
- **A hung provisioning subprocess wedged the venv permanently.** `bootstrap.run`, `_soft_probe` and
  `maybe_reconcile` had no timeout, while `_heartbeat_pulse` kept the provision lock fresh from another
  thread — so the lock never aged out, no later session could reclaim it, and the venv never built. All
  provisioning children are now bounded (`INSTALL_TIMEOUT_SECS` / `PROBE_TIMEOUT_SECS` /
  `RECONCILE_TIMEOUT_SECS`), and a timeout takes the ordinary interrupted-build cleanup path.
- `hooks/precontext.py:_clean` never received the `_dequote` fix its documented mirror `envconfig.clean`
  got, and `test_precontext_clean_mirrors_bootstrap` had no quoted rows — so it asserted an agreement that
  did not hold. Both fixed; the three implementations (engine, hook, and the `_engine_resolve.mjs` twin)
  are now verified in lock-step.
- The engine-written `.git/info/exclude` listed `.kg-ground-audit.jsonl` without a glob, leaving
  `groundaudit`'s `.ckpt` spend-ledger sidecar untracked — so `git add -A` committed per-machine runtime
  state into canon history.
- `Edge.__post_init__` did not sanitize a non-finite `confidence_score`, so a hand-edited
  `confidence_score: .nan` reached `json.dumps` and emitted a bare `NaN` literal, making `derived/graph.json`
  invalid JSON (RFC 8259) for strict external consumers.
- Three projector read helpers (`_schema_outdated`, `_read_meta`, `_read_prior_betweenness`) omitted
  `PRAGMA busy_timeout`, so a reader landing inside another session's exclusive schema-heal window
  degraded to a spurious full rebuild.
- The `edgeless-communities` agenda item chose its representative from an unordered `SELECT`, so a degree
  tie made a full rebuild and an incremental reproject of the byte-identical canon disagree.
- `export._bridge_set` omitted the `degree` tiebreak that `kg_context`'s bridge SQL uses, despite a comment
  claiming parity — a degree-differentiated tie straddling the top-N cutoff diverged between the two views.
- `lightrag_arm`'s `_load_prompts` sat outside the try, so a mistyped `--prompts` produced a traceback
  instead of the clean exit-3 the `kg-evaluator` subagent expects.
- `launch_server.mjs` had no `unhandledRejection`/`uncaughtException` handler; on Node ≥ 15 a stray
  rejection would silently take the supervisor — and the MCP server — down with nothing in `server.log`.
- Four test doubles for `_atomic_write` had a fixed `(path, text)` signature and would have raised
  `TypeError` where the test intended `OSError` — passing for the wrong reason.

### Changed

- **`kg_operate`'s discovery mechanisms now claim the authorship they actually have.** The boundary has
  always preserved `authored_by=deterministic` on the hypothesized lane "for a genuine discovery
  mechanism", but no mechanism ever set it, so every engine-derived item was recorded as `agent` and the
  axis carried less information than it promised. Structural edges are now `deterministic`; a node whose
  `label`/`body` came from the caller stays `agent`.
- CI now covers **both edges** of the supported Python range (3.10, 3.12, 3.13, 3.14). `requires-python`
  has no upper bound and this project's field crash reports have come from interpreters newer than
  anything CI tested.

### Performance

Measured on a synthetic canon; no behavioural change (the `/kg-generate` slate is byte-identical).

- **`kg_generate("all")` on an 800-node graph: 5.7s → 1.6s.** `_is_failure` built two `edge_id`s — six
  `slug()` calls — for every candidate pair in an O(n²) loop, even against an empty failure set (the common
  case before any adversarial grounding). It now short-circuits, and `slug()` — the engine's hottest pure
  function — is `lru_cache`d (2.2M hits at a 100% hit rate on that run).
- **Idempotent canon re-writes parse each note once, not twice.** `_merge_into_existing` already held the
  parsed on-disk node; it now returns its content hash instead of making `_write_batch` re-read and
  re-parse the same file for the no-op guard.
- **Batch canon writes fsync the canon directory once, not once per note** (802 fsyncs → 1 on a 400-node
  batch). Per-file content durability is unchanged; only the redundant directory-entry fsync is hoisted.

### Docs

- **`docs/COMMANDS.md`** — new complete command manual: every argument of all nine slash commands, what
  each option value means, and a worked example per case. Linked from the README's command table, which
  stays the summary.
- **README `Configuration` section** — the four install-time settings (`source_path`, `sensitivity`,
  `metrics_mode`, `extract_wave_size`) documented with their values, defaults, and what each controls,
  plus how `source_path` resolves a file, a directory, or a glob.
- **Decision Rule D5 (upstream drift) is retired.** Both donor repositories have been unpublished, so the
  rule's premise — an upstream that can gain commits — no longer holds, and its one open clause (a
  deferred re-sync) is foreclosed rather than exercised. The ID is kept and struck through at the
  definition site so its citations still resolve. Donor *integrity* is untouched: that was always **I11**,
  which still gates every commit. Dead donor-repo links removed from the README, `MIGRATION.md`,
  `ATTRIBUTION.md`, `BASELINE.md`, `FUSION_PLAN.md` and `scripts/donor_pins.json`; the surviving D5
  citations in `BASELINE.md` and `PLAN_STATE.md` now carry the retirement note.
- Closed the v0.3.0 reference/user-facing doc gap: the tempered-divergence `reach` dial and the key-free
  second construction reached `TUTORIAL.md`, the README cheat sheet, and the subagent-facing
  `references/{contract,tools,pack-schema,axis_inference}.md`, which the feature commits had skipped.
- `kg_explain_path`'s 32-concept cap now also appears where a *caller* meets it — the `/kg-query` command
  body and the command manual — alongside the existing notes in `references/tools.md` and
  `ARCHITECTURE.md`. `references/contract.md` is the write contract and correctly stays silent on it.
- **The review-r11 engine changes reached the prose.** `ARCHITECTURE.md` still described a forged verdict
  as reset to `unverified`; it is now restored to the failure baseline the forge overwrote (`unverified`
  only when the item held no prior verdict). Its write-path section never stated the node-body durability
  rule — that a verdict-bearing node keeps the body carrying its `grounding span:` across a re-write —
  which `references/contract.md` documents.
- **Names corrected where a doc invented one.** `kg_operate` was written as a slash command
  (`/kg-operate`) in `ARCHITECTURE.md` and this changelog; there is no such command — it is a tool, called
  by `/kg-generate`. Two `server.py` comments called the divergence surface "six tools" (seven). The
  `kg_generate` tool description and the `Candidate` docstring both omitted `periphery`, a mechanism
  `_resolve_mechanisms` accepts directly, so a caller could not discover it. `references/tools.md`'s
  quick-map row for `kg_generate` had lost its `dpp=` parameter (the authoritative §1.13 entry kept it),
  and its cap-refusal example omitted the `edges`/`grounded_only` keys the tool really returns.
- `/kg-experiment`'s own `description` advertised four arms; its body runs five (it omitted
  `graph+generate+dpp`). The README's provisioning note claimed a Python floor of 3.11, where
  `requires-python` and CI both say **3.10**. `TUTORIAL.md`'s cheat-sheet dropped `/kg-diverge`'s
  `domain-template` dial and `/kg-perturb`'s `graph.json` form, and now points at the command manual for
  the optional arguments it deliberately leaves out.

## 0.3.0 — 2026-07-08

Minor release. Feature-led: **tempered divergence** for `/kg-diverge` (a reach dial, a feasibility
coverage axis, and a coherence gate) and a **key-free, in-session second construction** for
`/kg-perturb`. Plus a correctness/robustness sweep from a second exhaustive review (review-r10) and an
honesty fix to the `graph.html` layout. No change to the 27-tool MCP surface.

### Added

- **Tempered divergence for `/kg-diverge` — a reach dial, a feasibility coverage axis, and a coherence
  gate.** The briefs skewed extravagant, sometimes absurd or cryptic; three distinct leaks, three
  language-layer fixes (no engine change — the engine still only measures dispersion, I5). A **reach
  dial** (`conservative|balanced|wild`, default `balanced`) caps divergence in *degree* (boldness band,
  operator mix, feasibility lean) but never in *kind* — the mechanism axis always spreads maximally, so
  every slate stays genuinely varied. A **feasibility coverage axis** in MAP-Elites keeps one elite per
  feasibility bin, so a bold idea can't evict a buildable one (a coverage guarantee, not a promise about
  the final six); it is now a default on **all three axis paths** — the omit-axes default (`pack.yaml`),
  the `generic.yaml` default, and the inferred-axes recipe (`axis_inference.md`), with the honest caveat
  to skip it where "buildable" is meaningless (names, taglines). A **coherence gate** in the judge rubric
  adds a one-line "why does the mechanism actually work?" test that separates bold-but-valid (keep) from
  incoherent (kill), and killing a broken idea no longer counts against the over-filtering budget. Plus a
  **de-obscure step**: each idea carries a plain "how it works in practice" clause + one concrete example,
  so bold ideas read clear, not cryptic.

- **`/kg-perturb` now builds its second construction key-free, in-session.** The exo "attack coverage"
  move needs a *second graph construction* to cross-generate against, and the only builder was the
  headless backend (`python -m kg_engine.backend extract`) — which requires the `anthropic` SDK **and**
  `ANTHROPIC_API_KEY`, so `/kg-perturb` was the one command that could not run in a stock install (it
  silently degraded to an internal `regroup`). The write path now accepts an optional
  `construction` name (`kg_write`/`kg_propose`) that routes the SAME span-verified boundary to a
  separately-named alternate canon under `<project>/.kg/constructions/<slug>/` (mirroring the
  `.kg/diverge/<brief>/` per-name store rule), so a `kg-extractor` subagent builds the second
  construction with **no API key** — the session does the language work, the engine only validates +
  stores (§2.2). `kg_generate` gains `second_construction=<name>`, which projects that alternate canon
  in-session and cross-generates; the pre-built `second_graph` path stays as the escape hatch. The
  primary-canon default path (`construction=None`) is byte-for-byte unchanged, and the headless backend
  is kept for out-of-session / CI builds. The old, non-functional "in-session alternative" note in the
  command (point `/kg-build` at a second `KG_PROJECT_DIR` — impossible, the running canon is fixed at
  startup) is replaced with the real flow. Pinned in `tests/test_perturb_second_construction.py`.

### Fixed

- **Correctness + robustness sweep from a second exhaustive review (review-r10).** 29 findings across the
  engine and language layer, each pinned (`tests/test_review_r10.py`, key ones mutation-verified). Highlights:
  - **High — a second construction no longer commits into the user's git history.** The `/kg-perturb`
    construction sub-engine is rooted under the ephemeral `.kg/`, but `git rev-parse` walks *up* to the
    parent repo, so `_commit_batch` was `git add`/`commit`-ing `.kg/constructions/<slug>/canon/*.md` into
    the user's tracked history on any repo without `.kg/` gitignored. Construction sub-engines now build
    with commits disabled (`Canon(git_enabled=False)`); the store is also **wiped fresh** on the first
    materialization each session (and rebuilt when re-pointed at a different second source), making the
    "session-ephemeral" contract real instead of silently merging a stale prior build.
  - **Reconciler — an out-of-band demote of a `failed`/`rejected` edge to `unverified` no longer erases
    §1.7 negative memory.** The verdict monopoly policed forged verdicts written *in*; it now also
    **restores** a negative verdict edited *out* to `unverified` (no tool path produces `unverified`, and
    the merge precedence makes failure states sticky, so the transition is anomalous).
  - **Windows lease safety — canon's `_win_pid_alive` no longer over-reclaims a live lease.** It had
    drifted from its hardened dirlock twin to a fail-*unsafe* form that read any transient `OpenProcess`
    error as "process dead"; realigned to fail-safe (dead only on `ERROR_INVALID_PARAMETER`), plus the
    matching host-less `_pid_probe` guard.
  - **Section splitter is fenced-code aware** — a `## ` line inside a ` ``` ` block is no longer parsed as
    a heading (was corrupting the extraction unit + per-section IDF for any source with such a fence).
  - **Projection durability + determinism** — the schema-heal now invalidates `meta` in the same
    transaction as the table DROP/CREATE, so a crash in the repopulation window leaves `is_stale()` True
    instead of serving a committed-empty "fresh" index; and `graph.json` node/link order is now a stable
    sort of content keys, so incremental rowid churn can't make a byte-identical canon emit a
    differently-ordered graph.
  - **§1.7 consistency** — `shortest_path` and `_live_subgraph` now both exclude `failed`/`rejected` (and
    `_live_subgraph` also `obsolete`), so a refuted/superseded edge can neither carry a live path nor
    confer centrality while being invisible as an answer.
  - Plus: egress-scrub the `divergence.dpp` advisory failure note (a HuggingFace cache path could leak);
    a MISSING continuous descriptor value bins to the neutral **middle**, not the far-fetched extreme, so
    the new `feasibility` coverage guarantee holds when a descriptor omits it; the node flood lane gets its
    own higher floor so a small source no longer silently caps the canon at 64 nodes; `query_graph` floats
    bare materialized pins to the front of the grounding queue; `source=` without `construction=` is
    refused rather than dropped; the `kg-grounder` is granted `kg_write` so the Stage 0b span-relocation
    remedy is executable; the `/kg-ground` stop-gate consults unverified **nodes**, not just the edges-only
    count; and several smaller CLI / cross-platform / resource-cleanup hardenings.

- **`graph.html` no longer lets falsified edges fake a connected graph.** `failed`/`rejected` edges are
  still **drawn** (§1.7 — negative memory is never pruned), but they no longer exert any force in the
  force-directed layout, so a refuted relation can no longer spring its two endpoints together and give
  the false impression that the graph is more connected than its *valid* edges make it. This brings the
  one remaining geometric surface into line with `projector._live_subgraph`, which already excludes the
  identical edges from every centrality rank (degree / betweenness / community / bridge) — node **size**
  was therefore already honest and is unchanged. A new legend **checkbox** (default on) can hide the red
  edges entirely for a valid-only view. Pinned in `tests/test_export.py`
  (`test_failed_edges_exert_no_layout_force`, `test_failed_edge_toggle_hides_from_draw_only`).

## 0.2.6 — 2026-07-07

Patch release. A broad correctness/robustness sweep from an exhaustive codebase review — two
higher-severity fixes plus a batch of edge-case hardening. No API or tool-surface change (the
27-tool surface is unchanged); every change is a bug fix with a pinned regression test
(`tests/test_review_r9.py`). Suite: 1160 passed, 2 skipped.

### Fixed

- **The canon git merge driver silently destroyed legitimate, locally-audited verdicts.** Its
  edge/node `epistemic_state` resolution demoted to `unverified` on ANY disagreement, base-unaware —
  so a routine same-note merge in which only one side carried an audited `grounded`/`failed` verdict
  (the other unchanged from the merge base) erased it, including never-pruned §1.7 failure memory. It
  is now a base-aware 3-way like the scalar fields beside it: a one-sided verdict is kept, and only a
  genuine two-sided conflict demotes. Forge-safety is unchanged — a verdict with no local audit record
  is still re-quarantined by the reconciler's full sweep.

- **Provisioning could delete a user-owned venv.** The venv-reclaim branch treated "a stranded owner
  sentinel beside a populated, markerless dir" as proof of ownership and `rmtree`'d it — so a token
  left behind past its husk (a hard kill mid-cleanup, or a `rm -rf .venv` followed by the documented
  `uv sync`) could delete a brand-new working venv. Reclaim now refuses any dir whose interpreter
  imports the core deps: a functional venv is never our incomplete husk (the never-delete-a-user-venv
  invariant).

- **Egress path-leak holes (§1.9).** Absolute filesystem paths could cross the boundary back to the
  session: the path-redaction regex stopped at the first space (leaking the tail of
  `C:\Users\John Smith\…` and `/home/john doe/…`), and the projection-degraded reason and a
  `kg_generate` note were not scrubbed at all. All three are closed.

- **Windows line endings corrupted canon notes.** A hand-edited note saved CRLF injected stray `\r`
  into stored bodies (and defeated the idempotent-no-op content hash, churning git); a CR-only note
  vanished from every read entirely. Line endings are now normalized at the single parse chokepoint.

- **A source-only edit never refreshed the derived advisories.** The staleness gate was canon-only, so
  editing the source document while the canon stayed byte-identical never reprojected — freezing the R3
  stale-verdict / re-examinable advisories and specificity ranks in their own edit-then-query workflow.
  A cheap source signature now triggers the reproject.

- **Edge-case hardening batch:** the DPP ideation slate no longer duplicates a candidate on a
  non-finite score; the ideation harness tolerates malformed (non-string) inputs instead of crashing;
  the `kg_context` query tokenizer is Unicode-aware (non-Latin queries keep multi-word matching); the
  cross-process venv lock closes an info-less-window steal race, never `rmtree`s a re-validated live
  holder, and fails cleanly on a read-only filesystem; the Windows PID-liveness probe fails safe; the
  SessionStart hook and the launcher resolve a relative `KG_ENGINE_VENV` identically; the supervisor's
  self-heal is bounded so it can't block session teardown; and several defensive guards land
  (absorption divide-by-zero, corrupt-ledger / corrupt-owner-note tolerance, a clear scikit-learn
  import error, incremental cross-owner edge agreement, a warm baseline cache that detects concurrent
  foreign writers, and consistent `n_edges` reporting).

## 0.2.5 — 2026-07-07

Patch release. One provisioning fix from a crash report; no API or tool-surface change
(the 27-tool surface is unchanged).

### Fixed

- **An interrupted plugin auto-upgrade could STILL wedge the engine venv, even with the
  0.2.4 self-heal.** 0.2.4 stamps an ownership sentinel (`.burgess-venv-owner`) before any
  mutation so an interrupted build is reclaimed rather than refused — but it kept that
  sentinel **inside** the venv dir, and the failure/interrupt cleanup does
  `rmtree(venv_dir)` (and an in-place `uv`/`pip` upgrade can recreate the venv wholesale).
  If that wipe was itself interrupted mid-flight it destroyed the sentinel while leaving a
  populated, markerless husk behind — exactly the state the sentinel exists to make
  reclaimable — so the foreign-venv guard refused it forever and the MCP server crash-looped
  on the missing transitive dep (e.g. `anyio`, `ModuleNotFoundError`). **The reclaim token
  was stored in the one directory the crash-cleanup wipes** (crash-report v0.2.4 "anyio
  wedge", hole B). Fixed by moving the ownership sentinel to a **sibling** of the venv
  (`<venv>.burgess-venv-owner`, beside the lock), so a wipe/recreate of the venv dir can no
  longer destroy it; the next provision then lands in the existing reclaim branch and
  rebuilds clean. The sibling token is now **cleared on a verified success or a clean
  failure** (and kept only while an interrupted build's husk is still present), so a healthy
  venv — or a user venv later placed at that path — is never mistaken for reclaimable and the
  never-delete-a-user-venv guard is preserved (`bootstrap.do_install`,
  `_owner_sentinel` / `_clear_owner_sentinel`).

## 0.2.4 — 2026-07-07

Patch release. One provisioning fix from a crash report; no API or tool-surface change
(the 27-tool surface is unchanged).

### Fixed

- **An interrupted plugin auto-upgrade wedged the engine venv, crash-looping the MCP
  server.** When a plugin update changes dependencies the install stamp goes stale, so
  `bootstrap.do_install` upgrades the existing venv **in place** — `uv sync` uninstalls the
  old wheels before reinstalling the new ones. A hard kill during that swap (the plugin's
  process tree being torn down mid-upgrade) could leave the venv missing a transitive
  dependency (e.g. `anyio`, pulled in by `mcp`), so the server died on `ModuleNotFoundError`
  at startup and relaunched until it hit the crash-loop cap — every `kg_*` tool absent for
  the session. The 0.2.3 self-heal sentinel (`.burgess-venv-owner`, FALLO 1) that lets an
  interrupted build be reclaimed was only stamped on the **fresh-build** path, so an
  interrupted **in-place upgrade** — which also strips the completion markers — left a
  populated, markerless, ownerless dir that the foreign-venv guard refused forever. Fixed by
  claiming the ownership sentinel **before any mutation on both paths** (fresh build and
  in-place upgrade), so an interrupted upgrade now lands in the existing reclaim branch and
  is rebuilt clean on the next provision instead of wedging (`bootstrap.do_install`).

## 0.2.3 — 2026-07-07

Patch release. Bug-fix batch from a Windows startup/provisioning report (no tool-surface
change — the 27-tool surface is unchanged; `kg_status()` gains one additive `source` field).

### Fixed

- **A hard-killed provision wedged the engine venv permanently (no MCP server until a
  human deleted `.venv`).** If the provisioner was force-killed after populating
  `$CLAUDE_PLUGIN_DATA/.venv` but before writing its completion markers
  (`engine-python.txt` / `install.stamp`), the leftover was a populated but unmarked venv.
  Every later start's foreign-venv guard then refused to provision into it — a permanent
  wedge, since the guard can't tell an interrupted build of ours from a user's own venv.
  Fixed by stamping an ownership sentinel (`.burgess-venv-owner`) **before** any bin/lib
  lands, so the next run recognises its own interrupted build and rebuilds clean, while a
  genuinely foreign dir (no sentinel, no marker) is still refused and never deleted
  (`bootstrap.do_install`). (FALLO 1.)
- **A crashed provisioner's lock blocked startup for up to 30 minutes on Windows.** The
  provision lock (and the canon session lease) could only reclaim a dead holder's lock by
  PID-liveness on POSIX; on Windows `os.kill(pid, 0)` is `CTRL_C_EVENT` (not an existence
  check), so the probe was skipped and a crashed holder was only reclaimed once its
  heartbeat aged past the 30-minute stale window. Added an `OpenProcess`-based Windows
  liveness probe (`dirlock._win_pid_alive`, mirrored in `canon._pid_probe`), so a dead
  holder on the same host is reclaimed in milliseconds on Windows too. (FALLO 2.)
- **`/kg-build` ignored a configured `source_path` and silently built the demo corpus.**
  Step 0 resolved the source from `CLAUDE_PLUGIN_OPTION_SOURCE_PATH` in the model's Bash
  shell, but the host injects userConfig options only into the MCP server process — that
  env var is empty in the tool shell — so a required, configured `source_path` was missed
  and the command fell back to `examples/source.md`. `kg_status()` now exposes the
  engine-resolved source (`source: {path, exists, files}`), and `/kg-build` reads the path
  from there and **fails loud** instead of building the demo by surprise. (FALLO 3.)
- **`/kg-build` collapsed a `### `-structured file into one section.** The section
  enumeration assumed level-2 `## ` headings; a file whose only `## ` is its title but
  whose content is `### ` subsections was extracted as a single whole-file section,
  weakening span-isolation. Step 0 now detects each file's dominant heading level (falls
  back to `### ` when the sole `## ` is a title) and warns when a file yields 0–1 level-2
  sections. (FALLO 4.)

## 0.2.2 — 2026-07-07

Patch release. Fixes a Windows/Py3.14 projection hang and adds nothing else — no
API or tool-surface changes (the 27-tool surface is unchanged).

### Fixed

- **`kg_context` (and any lazy-projecting read) could hang for HOURS on Windows/Py3.14
  instead of failing.** Two chained defects. (1) The projector imports the heavy native
  deps (`numpy` → OpenBLAS, `igraph`, `leidenalg`) **lazily**, deep inside
  `projector._leiden`, so on a populated canon the *first* read that projects triggered
  the very first `import numpy` **from inside an MCP handler** — i.e. on the event-loop
  thread while anyio worker threads were already alive. That late, cross-thread native
  load could deadlock the Windows loader lock and never return. (2) When the 300s handler
  watchdog then tripped, its `os._exit(71)` routed through `ExitProcess`, which needs that
  **same** loader lock to run DLL-detach teardown — so the force-exit deadlocked too, the
  process never died, the supervisor never relaunched, and 300s became ~4h of silent hang.
  Fixed at the root: the server now **pre-loads numpy/networkx/igraph/leidenalg once at
  startup on the main thread, before the watchdog and serve loop start**
  (`server._preload_native_deps`), so the projector's later lazy imports are pure
  `sys.modules` cache hits that take no loader lock — and the watchdog's force-exit is now
  a **teardown-free hard kill** (`server._hard_exit`: `TerminateProcess` on Windows,
  `SIGKILL` on POSIX) that can't be blocked by a wedged native import. Both stay
  best-effort/graceful (a missing native dep still degrades to the pure-Python
  label-propagation fallback). Pinned by the `#7b`/`#7c` cases in
  `tests/test_resilience.py`.

## 0.2.1 — 2026-07-06

Patch release. Fixes a `source_path` configuration bug and adds nothing else — no
API or tool-surface changes.

### Fixed

- **A quoted `source_path` silently resolved to nothing.** A source path the user
  wrapped in quotes reached the engine (`KG_SOURCE_PATH`) and the `/kg-build` bash
  (`CLAUDE_PLUGIN_OPTION_SOURCE_PATH`) with the literal surrounding quotes intact,
  so `Path('"C:\\dir\\file.md"')` pointed at a nonexistent quote-wrapped path and
  the engine degraded to an empty source with no error. (The doubled backslashes
  shown in the settings UI are only Claude Code's JSON rendering of the stored
  value — the substituted env value carries single backslashes; the quotes were
  the real breakage.) The canonical env-value cleaner (`envconfig._dequote`,
  applied in `clean()` — the single home the server, headless backend,
  `/kg-perturb`, and the PreToolUse hook all route through), its declared JS twin
  (`_engine_resolve.dequote`), and the `/kg-build` file-enumeration bash now peel
  matched surrounding quote pairs **repeatedly**, so even a double-wrapped
  `""path""` collapses to the bare path. Only symmetric pairs peel — an interior or
  mismatched quote stays part of the path. The `source_path` userConfig description
  now also asks for the bare path without quotes. Pinned by
  `tests/test_fix_source_path_quotes.py`.

## 0.2.0 — 2026-07-06

Feature + hardening release. Adds the **re-examinable-verdicts advisory** (a
read-only R3-mirror that flags `failed`/`rejected` items — nodes and span-less
items included — whose source set has since grown, so old negative memory may now
be supportable) with its divergence-side mirror and explicit un-seal lever. Also
lands the 2026-07-05 exhaustive review (review-r8, 23 findings), the
novel-`/kg-diverge`-pin grounding fix, and a test-import repair so the documented
`pytest tests/` command reproduces the reported suite count. No breaking API or
tool-surface changes; the 27-tool surface is unchanged (`kg_diverge_recall` gains
an optional `reexamine` parameter).

### Fixed

- **2026-07-05 exhaustive review (review-r8) — 23 findings across the engine, all
  landed with mutation-caught regression pins in `tests/test_review_r8.py`.**
  - **`kg_rename` silently dropped a grounding verdict** (high): an endpoint
    rewrite that collapsed two of a node's edges onto one canonical id persisted a
    duplicate id (no dedup, unlike `kg_merge`), and the downstream `{e.id: e}`
    collapse kept the wrong edge. It now coalesces collisions via `_merge_edge_pair`
    (negative-info-sticky, verdict-preserving) while keeping legitimate `new→new`
    self-loops.
  - **Re-proposing a grounded edge dropped its provenance metadata**: the
    hypothesized-lane dedup is correct (only `FAILURE_STATES` bind generation — a
    grounded edge is live structure, not a refutation), but `canon._merge_into_existing`
    preserved only state/span, blanking `source_file`/`confidence`/`confidence_score`/
    `authored_by`. It now carries all of the grounded edge's evidence.
  - **`node_content_hash` churn**: a body with a trailing `\n` (normal LLM output)
    hashed differently from its own disk round-trip, defeating canon's idempotent-
    no-op write guard so every re-run rewrote the note. The hash now folds the body
    the same way the disk round-trip does.
  - **`groundaudit` spurious `OrphanAuditError`**: an empty-records rollback against
    a not-yet-created audit log raised a false §1.8 durability breach (nothing was
    appended → no orphan). Compensation is now guarded on `records`.
  - **Re-examinable-verdicts term filter read body-less shells**: a source-only
    change projects via the incremental (shell) arm, so the filter saw no node
    body / edge notes and a body-only distinguishing term never re-surfaced a
    falsified item. It now re-reads the full note from canon for the small
    candidate set. The overlap tokenizer is also unicode-aware (was ASCII-only, so
    the whole advisory went silent on a non-Latin source), and a renamed
    identical-content source file is no longer mistaken for newly-added evidence.
  - **`kg_diverge_recall(reexamine=...)` un-sealed too much**: it revived ANY named
    cid — a genuine user discard, an unknown id, or a still-valid failure — and a
    bare-string argument iterated character-by-character. It now un-seals only the
    currently re-examinable set and reports only what was actually un-sealed;
    pre-feature `failed` ledger entries get a backfilled baseline so a later source
    change can surface them.
  - **Egress-scrub gaps**: the backend scrubbed only the section body, egressing the
    raw `## heading` (PII/secret) in the prompt; the optional `lightrag` arm shipped
    the raw source to OpenAI unscrubbed. Both now scrub before egress.
  - **Deterministic derived layer**: a cross-owner `edge_id` collision (hand-edited
    foreign-source edge duplicating a natural one) resolved by node iteration order,
    so full vs incremental projection disagreed; resolution is now deterministic
    (natural owner wins). A leading UTF-8 BOM no longer folds the first `##` section
    into the preamble, and a contended cold-start projection can no longer clobber a
    real `graph.json` with an empty placeholder (exclusive create).
  - **Smaller hardening**: `_payload_receipt` now includes `file_type` (a
    file_type-only change no longer replays as a no-op); `harness.absorption`
    tolerates a non-dict history and `_score_condition` no longer character-scores a
    bare-string condition value; `provision.mjs` no longer leaves an empty PATH
    element (CWD on the probe search path); `validate_plugin` anchors the
    `__version__` scan; `select_diverse(seed=)` is documented as a deterministic
    no-op; `kg_diverge_metrics` reports `mean_cosine_n` (the subsample size above the
    novelty cap); and the launcher's synchronous cold-start catch-up has a hard
    ceiling so a wedged install can't block session startup indefinitely.
- **The review-r8 backend-scrub pin made the suite red under the *documented*
  command.** `test_r8_7_backend_scrubs_section_title` used `from tests.test_backend
  import _FakeClient` — the only `from tests.` import in the whole suite. It resolves
  only when the repo root is on `sys.path`, which `python -m pytest` adds (cwd) but the
  console-script `uv run pytest tests/` that the README/CLAUDE.md document does **not**;
  pytest puts `tests/` on the path, not the repo root, so the run failed with
  `ModuleNotFoundError: No module named 'tests'`. It now imports the sibling module
  top-level (`from test_backend import _FakeClient`), matching every other test, so the
  documented command reproduces the documented `1101 passed, 2 skipped`.

### Added

- **Re-examinable-verdicts advisory (R3-mirror) for non-monotonic evidence.**
  Grounding verdicts are permanent negative memory and the grounder never
  revisits them; the only source-change reaction (the R3 stale-verdict advisory)
  fired one direction — a `grounded`/`failed` span-present edge whose span
  *disappeared*. A new **read-only** mirror flags the opposite case: a
  `failed`/`rejected` item — **nodes and span-less items included, which R3
  cannot cover** — that was judged against a source set which has since **grown
  or changed**, so it may now be supportable and deserves a re-look. It **never
  mutates a verdict and never re-queues** (re-grounding stays a `kg_ground`
  decision); a term-overlap filter keeps only items the changed source actually
  mentions. Surfaced in `kg_context.advisory.reexaminable_verdicts` and a
  `## Re-examinable verdicts` GRAPH_REPORT section (new projector meta keys
  `reexaminable_verdicts` + `source_file_sigs`; no model schema change; R3 and
  the global `FAILURE_STATES` untouched). The divergence side mirrors it:
  `failed`-fated brief discards are surfaced as `reexaminable_discards` on a
  source change, with an **explicit** un-seal lever
  `kg_diverge_recall(project, reexamine=[candidate_ids])` (never auto-un-sealed).
  Pinned in `tests/test_reexaminable_verdicts.py` (9 tests) and
  `tests/fusion/test_materialization.py` (4 new tests).

### Fixed

- **Grounding no longer permanently buries novel `/kg-diverge` pins.**
  `_sync_materialized_fates` folded a materialized pin into its brief's
  **permanent** discards whenever its canon item reached the global
  `FAILURE_STATES` (`{rejected, failed}`) — so grounding a genuinely novel pin
  against the original source (which yields `rejected`: no in-source span, the
  *expected* state of novelty) discarded it **for being novel**. A new, narrower
  `server.MATERIALIZED_DISCARD_STATES = {failed}` now keys the fold: only an
  actively **falsified** pin discards; a merely **unsupported** pin stays
  recoverable in the lane until sources are added. Verdict neutrality is
  preserved (the change is in the diverge-brief-local *consequence*, not the
  verdict); the global `FAILURE_STATES` and the write-boundary durability
  quarantine backing `/kg-generate` negative memory are untouched. The
  `kg-grounder` prompt now leaves unsupported `[diverge]`-lineage edges
  `unverified` (triage), and `kg_diverge_materialize` returns an advisory-only
  note when a source is already configured. Pinned in
  `tests/fusion/test_materialization.py` (5 new tests, mutation-verified).

## 0.1.2 — 2026-07-04

Hardening release: the full 2026-07 review trilogy — maintainability
(review-r5), performance (review-r6), and correctness (review-r7) — plus a
documentation pass that makes the docs self-contained and drift-free against
the engine source. No user-facing API or tool-surface changes.

### Changed

- **2026-07 maintainability review (review-r5)**: ~45 findings applied — single
  homes for duplicated logic (`envconfig`, `dirlock`, `pathing`,
  `sources.split_sections`, failure-state vocabulary, `node_content_hash`, the
  derived-layer reader), decompositions of the largest functions (reconciler
  `scan`, divergence ingest, canon `write_nodes`, `run_generators`, bootstrap
  install), and clarity renames. Pinned in `tests/test_review_r5.py`
  (23 tests, including JS↔Python env-resolution parity).
- **2026-07 performance review (review-r6)**: lazy heavy imports (server import
  ~190 ms → ~60 ms), binary `.npz` divergence vector stores (legacy `.json`
  still read, migrated on next write), capped mechanism-spread computation,
  lazy-row farthest-point selection, stat-gated incremental canon parsing,
  glossary term cap + SQL LIMIT, and fsync skipped for session-ephemeral state.
  Pinned in `tests/test_review_r6.py`.

### Fixed

- **2026-07 correctness review (review-r7)**: 7 verified findings fixed and
  pinned in `tests/test_review_r7.py` (21 tests):
  - `model.py` frontmatter regex: the closing-fence `\s*` greedily ate the
    body's first-line indentation, making `node_from_markdown`∘`node_to_markdown`
    lossy (a 4-space code block lost its first line) and silently defeating
    canon's idempotent-no-op write guard (`node_content_hash` mismatch →
    spurious rewrite + timestamp-only commit). Now horizontal-whitespace-only.
  - `server.py` egress: `kg_write`, `kg_rename`, and `kg_merge` returned the
    canon rollback reason (`info.error`) unscrubbed, leaking an absolute vault
    path across the §1.9 boundary that every sibling error-return scrubs (the
    `_tool_result` envelope scrubs raised exceptions, not returned dicts). All
    three now route through `_scrub_error`.
  - `export.py`: chained `.replace()` rescanned the inlined data payload, so a
    node label equal to the `__KG_FAILURE_STATES_JSON__` sentinel corrupted the
    graph.html JSON. Now a single-pass `re.sub` that never rescans replacements.
  - `harness.py`: the `ideation`/`convergence`/`specificity` CLIs crashed with
    an uncaught `AttributeError`/`TypeError` on a malformed top-level JSON shape
    (array/scalar) instead of the clean exit-2 usage error `agreement` emits.
  - `generate.py`: `run_generators` was defined twice; the duplicate shadowed
    the first def and the review-r5 module-level helpers (`_convergence_tally`,
    `_dedup_candidates`, `_edge_key`), leaving them dead. The duplicate is
    removed so the module-level helpers are live and testable in isolation.
  - `agents/evaluator.md` / `commands/kg-experiment.md`: granted `kg_generate`,
    which the kg-evaluator is instructed to call for the graph+generate+dpp arm.
  - `commands/kg-ground.md` Stage 0b: the stale-verdict remedy prescribed
    `kg_ground(grounded, support_span=…)`, which is a no-op for a span-present
    edge (support_* only promote hypothesized items), so the flag never cleared;
    it now relocates the span via `kg_write` (a canon edit that re-opens
    grounding).
- Completed the I5 clock freeze in the test suite: canon's `utcnow` binding
  leaked wall time into the frozen-clock snapshot tests.

### Docs

- **`docs/ARCHITECTURE.md`** — new self-contained architecture reference
  written from the engine source (module map, data model, boundary
  dispositions, verdict path, derived layer, divergence internals with the
  shipped constants, tool surface, env contract, provisioning/supervision,
  invariants). The documentation no longer relies on either donor's docs.
- `references/tools.md`: new §1B documenting the seven `kg_diverge_*` tools
  (parameters, return shapes, `.kg/diverge/` state layout, session
  ephemerality, engine constants) and §2.4 for the
  `python -m kg_engine.divergence` CLI incl. the selftest gates and importer
  report; `kg_generate`'s `dpp` parameter and `divergence_advisory` block
  documented; the harness section now covers all four subcommands
  (`convergence` was missing) and the full ideation arm list.
- `references/pack-schema.md`: the optional `divergence:` pack section is now
  part of the documented `PackContract` (shape-check vs deep-validation split
  per the I3 firewall); `pack/domains/_schema.md` stale pre-fusion paths
  (`config/domains/…`) corrected to `pack/domains/…`.
- `docs/MIGRATION.md` made self-contained: the selftest gates/margins, importer
  report shape, and every carried-over engine constant are stated in-file
  instead of deferring to "the donor's" values.
- SKILL.md: stale hand-written test count removed (the README's generated count
  is the single home), the `graph+generate+dpp` experiment arm added, and the
  references index now lists all six reference files.
- Donor-relative phrasings scrubbed from `commands/kg-generate.md`,
  `commands/kg-experiment.md`, and `references/contract.md`.
- `FUSION_PLAN.md` relocated from the repo root to `docs/fusion/`, joining the
  rest of the fusion decision record.
- **2026-07-04 doc drift-audit** (full doc↔source audit, adversarially
  verified): corrected six stale claims — the vendored Sproutgraph engine
  module count 20 → 21 (`docs/fusion/ATTRIBUTION.md`, `docs/fusion/INVENTORY.md`,
  and this changelog's 0.1.0 spine entry; the donor @`17c4066` has 21 top-level
  `.py` files, matching the sibling Cambrian "15 modules" convention);
  `references/contract.md`'s core-tool count "eleven" → "sixteen" (`server.py`
  exposes 16 core + 4 generative graph tools); `references/tools.md`'s
  `kg_generate` `divergence_advisory` block, now documented as the parallel
  `bins`/`semantic_novelty`/`cliche_distance` arrays plus
  `beyond_cap_kept_in_donor_order` that `advisory_geometry.py` returns (not a
  `candidates` list); and a missing `Bash` grant in `/kg-ground`'s frontmatter,
  whose Stage-0 note runs `python -m kg_engine.harness convergence`.

## 0.1.1 — 2026-07-03

Patch release: every finding from the 2026-07 full-codebase review (review-r4;
regression-tested in `tests/test_review_r4.py`), plus a stale-doc scrub and a
CLAUDE.md repo guide.

### Fixed

- **BOM tolerance**: a canon note hand-saved with a UTF-8 BOM (Windows
  Notepad's default) failed the frontmatter parse and silently vanished from
  every read — including its §1.7 failure memory. `node_from_markdown` now
  strips a leading U+FEFF at the single parse chokepoint.
- **Stale-edge leak on incremental reprojection**: the per-note edge diff was
  keyed on `source`, so a hand-edited note carrying an edge whose `source:`
  names another node leaked a stale `index.sqlite` row after the edge was
  removed (graph.json, rebuilt in full, disagreed). The edges table now
  carries an `owner` column (the persisting note); diff/delete key on it, a
  pre-`owner` DB reads as schema-outdated and heals via full rebuild, and
  `owner_of_edge` resolves the owning file rather than assuming
  `source == owner`.
- **§1.9 egress gaps**: the read-path re-scrub now covers `label`, kg_agenda
  `question` strings and kg_generate `rationale`s (ids stay untouched);
  kg_agenda and kg_generate route through `_scrub_egress` like the sibling
  reads; `kg_scrub` no longer counts identity (literal-placeholder) entries as
  redactions.
- A SIGKILLed PreToolUse hook could hold the canon lease past the writers'
  30 s budget on Windows (no pid probe there): the hook now declares a 15 s
  lease TTL and size-gates its synchronous reprojection (>400 notes serve the
  existing index instead of burning the 5 s cap on every read, forever).
- The divergence `ingest` now parses candidates and warm-loads the embedder
  BEFORE taking the project lock, so the first-use ~120 MB model download can
  no longer outlive the lock's 60 s staleness window and get it stolen
  mid-cycle.
- `backend.run()`'s post-run projection is guarded: a projection failure is
  recorded as `projection_error` in the summary instead of masking the run's
  own exception from the `finally`.
- `export._bridge_set` tie-breaks by id ASCENDING among equal
  `spec_betweenness`, matching kg_context's `ORDER BY … id ASC`.
- `advisory_geometry`'s `grounded_mix` counts incoming edges too
  (`G.edges(node)` is out-only on a MultiDiGraph).
- `build_engine_from_env` filters unsubstituted `${…}` values from
  `CLAUDE_PLUGIN_OPTION_*` reads, like every other env read.
- Divergence `_atomic_write` guards its temp-file cleanup so an unlink failure
  can't mask the real write error (parity with `atomicio`).

### Changed

- `run_generators` size-gates the exact convergence tally at
  `FULL_TALLY_MAX_NODES` (400): above it, mechanisms run at the surfaced `k`
  instead of materializing O(V²) candidates; the surfaced slate is identical.
- `kg_write` now reuses a cheap-signature-keyed canon baseline across calls
  (the server-side twin of backend-1), so a parallel `/kg-build` wave no
  longer re-parses the whole canon per write; any out-of-band write
  invalidates it.
- Depend on `igraph` directly (the `python-igraph` name is a deprecated PyPI
  alias for the same package).

### Docs

- Scrubbed the stale references to the donor's `ARCHITECTURE.md` (deliberately
  not vendored — see ATTRIBUTION.md) from SKILL.md, `references/contract.md`
  and two engine comments; the contract.md note on provenance demotion now
  states what `boundary.py` actually does (provenance is left exactly as
  declared). Added `CLAUDE.md` (repo guide for Claude Code).

### Tests

- New `tests/test_review_r4.py` regression file (12 tests) covering all of the
  above; the divergence-firewall pre-port guard now fails loudly instead of
  silently passing if the package stops resolving; a `sys.modules` stub leak,
  a duplicated helper, a byte-identical duplicate test, a module-level
  `sys.path` mutation and a vacuous sleep-based "writer blocks" assertion were
  cleaned up; `test_alpha_threshold_semantics` now actually tests the
  reliability threshold (and documents Krippendorff's rare-category zero).


## 0.1.0 — first release (2026-07-02)

Burgess 0.1.0 is the first release of the fused plugin: Sproutgraph's grounded
knowledge-graph convergence engine and Cambrian's diversity-preserving
divergence engine, one MCP trust boundary, one domain-pack format.

### The spine (vendored from Sproutgraph @ `17c4066`)

- Deterministic graph engine (`scripts/kg_engine/`, 21 modules): canon/derived
  split, span-present write boundary, `kg_ground` verdict monopoly, reconciler
  re-quarantine, span-staleness advisory, egress scrub, experiment harness.
- 8 slash commands, 6 subagents, SessionStart provisioning chain (uv + pip
  fallback), PreToolUse grounded-context injection, offline graph.html export.
- Full donor test suite green at exact baseline parity (731 passed, 2 skipped)
  before any fusion work landed.

### The divergence engine (vendored from Cambrian @ `a2adfa1`)

- `kg_engine/divergence/` (15 modules + importer): model2vec static embedder
  (`potion-multilingual-128M`; deterministic hash embedder for tests/offline),
  MAP-Elites archive with CVT open-axis niching, k-NN geometric novelty, greedy
  DPP slate selection with farthest-point fallback, anti-collapse monitor
  (entropy + mean pairwise cosine) with variety-erosion early warning, bounded
  judge influence (weight 0.3, fitness clip [0.7, 1.3] — donor constants,
  drift-guarded), advisory originality/gap probes, per-domain descriptor axes.
- All donor engine tests ported and green (226 tests).

### New in the fusion

- **`/kg-diverge`** — standalone divergence with no graph and no source
  required: cliché map (held-out split), mechanism-first generation, DPP slates
  with honest novelty semantics, pins/discards/A-vs-B, monitor reactions.
  Engine exposed as six `kg_diverge_*` MCP tools; project-local state under
  `.kg/diverge/` (explicitly not `~/.cambrian`); session-ephemeral geometry
  (a new session wipes the archive; pins/discards/comparisons survive).
- **Pin materialization** (`kg_diverge_materialize`) — the explicit door from
  divergence into the graph: pins become `provenance=hypothesized,
  epistemic_state=unverified` nodes via the propose lane exclusively, with full
  `[diverge]` lineage; promotion still requires support; verdict-neutral pin
  priority in the grounding queue.
- **Unified negative memory** — grounding failures of materialized pins flow
  back into the brief's discards automatically; neither `/kg-diverge` nor
  `/kg-generate` ever re-proposes from the failure store.
- **Advisory DPP over `/kg-generate`** — behind `divergence.dpp` (pack flag +
  per-call override): hybrid descriptors (semantic novelty + community /
  graph-distance / grounded-mix axes), grounded-hub cliché map, judge-bounded
  DPP ordering. Snapshot-enforced advisory: grounding output is bit-identical
  flag on vs off.
- **`graph+generate+dpp` experiment arm** + `dpp_verdict` in the harness; the
  shipped `divergence.dpp` default was decided by the pre-declared blind rule
  D1 (see `docs/fusion/EXPERIMENT.md`).
- **One domain-pack format** — `pack.yaml` carries the extraction vocabulary
  AND an optional `divergence:` section (behavior axes + flags); Cambrian's
  domain templates ship as pack fragments under `pack/domains/`.
- **State importer** — `python -m kg_engine.divergence import-cambrian` maps an
  old `~/.cambrian` project's pins/discards/comparisons into `.kg/diverge/`
  (read-only on the source).

### Invariants, enforced by tests before the features they guard

Verdict monopoly (I1), span-present boundary (I2), import firewall (I3), DB
isolation — no vector schema anywhere the query tools read (I4), advisory
ceiling with bit-identical grounding snapshots (I5), donor judge bounds (I6),
different-family embedder (I7), sticky + consulted negative memory (I8),
graceful degradation — every kg_* tool works with divergence deps blocked (I9),
session-ephemeral archives (I10), donors untouched (I11 — gate scripted and
green at every commit).
