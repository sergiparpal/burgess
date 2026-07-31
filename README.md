# Burgess

**Turn conceptual prose into a source-anchored knowledge graph — then query it, challenge it, and propose new connections from its structure.**

Burgess is a Claude Code plugin for researchers, theorists, and technical writers developing conceptual frameworks in Markdown or plain text.

`/kg-build` extracts concepts and typed relationships from your documents. Every accepted relationship it extracts carries a verbatim source span. `/kg-ground` judges those candidates against the supplied text, and `/kg-query` answers from the graph while exposing provenance, grounding state, and recorded failures.

Burgess can also propose structural hypotheses with `/kg-generate`. These enter a separate, unverified lane with no supporting span and cannot become grounded without a source passage or external citation.

## Is Burgess a fit for your material?

Burgess currently works best with:

- conceptual or theory-heavy prose;
- explicit claims, definitions, metrics, operations, and failure modes;
- UTF-8 Markdown or plain text, preferably divided into sections;
- questions about what supports, attacks, bridges, confounds, approximates, or survives another concept.

The current release ships one **conceptual-theory domain pack**. Its node types are `compression`, `primitive`, `claim`, `metric`, `operation`, and `failure`; its relations are `grounds`, `attacked_by`, `reconciles_with`, `bridges`, `collapses_into`, `confounded_by`, `approximates`, `defends_against`, `projects`, and `survives`. Material outside that vocabulary may be mapped awkwardly, dropped by the extractor, or quarantined at the write boundary.

Burgess is not currently:

- a PDF ingestion or citation-management tool;
- a general-purpose ontology builder;
- a verifier of truth beyond the supplied sources;
- a prior-art or worldwide novelty checker.

## Install

```text
/plugin marketplace add sergiparpal/Burgess
/plugin install burgess@sergiparpal
```

For local development, point Claude Code at a checkout instead:

```bash
claude --plugin-dir /path/to/Burgess
```

Installation asks for a `source_path`: a Markdown/text file, a directory, or a glob naming the corpus the graph will be checked against. The current MCP server does not start without it. The other three settings have working defaults and can normally be left alone.

On first load a SessionStart hook provisions a local Python venv (Python ≥ 3.10; `uv` preferred, stdlib `venv`+`pip` fallback) in the plugin's persistent data directory. The engine dependencies are installed then. The [model2vec](https://github.com/MinishLab/model2vec) `potion-multilingual-128M` weights used by `/kg-diverge` are downloaded lazily the first time that workflow embeds candidates, then cached (~120 MB, CPU, torch-free).

The deterministic engine, graph storage, and embedding model run locally. `/kg-build` does hand source sections to Claude extractor subagents: each section is scrubbed for secrets and configured PII before that egress, then restored only when its source span is written to the local canon. See [Trust and privacy boundaries](#trust-and-privacy-boundaries).

## First workflow: build, ground, query

With `source_path` configured, the primary workflow is:

```text
/kg-build
/kg-ground
/kg-query "What grounds the concept of X, and what attacks it?"
/kg-view
```

1. **Build** — `/kg-build` extracts the configured source section by section. Accepted edges carry verbatim spans and begin `unverified`; the build never assigns verdicts.
2. **Ground** — `/kg-ground` is the only workflow that can assign a verdict. It checks the pending graph, challenges vague hubs, and retains rejected or falsified relationships as negative information.
3. **Query** — `/kg-query <question>` answers against the graph, leads with grounded relationships, quotes available spans, and labels unverified hypotheses separately. If the graph does not contain an answer, it says so.
4. **View** — `/kg-view` renders an offline `graph.html` and `GRAPH_REPORT.md`.

Builds are additive. To grow the corpus without reconfiguring the plugin, configure `source_path` as a directory or glob and add files that it resolves. Files with the same basename are deduplicated, so give every source a distinct filename.

For a longer, plain-language walkthrough, see [`TUTORIAL.md`](TUTORIAL.md). Every command and argument is documented in the [command manual](docs/COMMANDS.md).

## Propose connections from the graph

After building and grounding a graph:

```text
/kg-generate default 10
/kg-ground
/kg-query "Show the grounded relationships and unverified hypotheses around X"
```

`/kg-generate` uses seven deterministic structural mechanisms to propose typed connections and concepts. It does not discover evidence and does not judge truth. Every proposal begins with `provenance=hypothesized`, `epistemic_state=unverified`, and no span.

A proposal can be promoted to `grounded` only when `/kg-ground` supplies a verbatim passage from the configured source or an external citation. Supplying neither is refused by the engine. A citation is stored as `inferred`; Burgess records it but does not independently retrieve or validate it.

## Explore a brief without using the graph

`/kg-diverge` is a separate workflow for exploring an idea space:

```text
/kg-diverge <brief>
```

It builds a cliché map, generates candidates through different mechanisms, embeds them locally, and uses MAP-Elites, k-NN novelty, DPP slate selection, and an anti-collapse monitor to present a varied slate. You pin, discard, and compare candidates in chat. Materializing pins into the graph is a separate, explicit action; they enter as unverified hypotheses.

This workflow does not consume the configured source, but the current plugin installation still requires `source_path` so the Burgess MCP server can start. Its novelty values measure dispersion among candidates in the current exploration, not originality against prior art or the world.

## Other advanced workflows

- `/kg-perturb` builds or loads a second construction and cross-generates against it.
- `/kg-eval` measures extraction precision and grounding reliability.
- `/kg-experiment` runs the built-in multi-arm ideation comparison.

These are useful for interrogating the system or widening a mature graph; they are not required for the primary build → ground → query workflow.

## Trust and privacy boundaries

- **Source anchoring is not world truth.** A `span-present` grounded edge means the supplied source contains a passage supporting that relationship. Burgess does not establish that the source itself is correct.
- **External citations are recorded, not independently verified.** A generated hypothesis may be grounded with a citation note and promoted to `inferred`; the engine does not fetch or validate that citation.
- **The engine is local; language work crosses an egress boundary.** Deterministic processing, storage, graph metrics, and embeddings run locally. `/kg-build` sends scrubbed source sections to Claude extractor subagents.
- **Scrubbing protects egress, not the canon.** Secrets are always redacted before subagent egress; configured PII categories are redacted too. Matching placeholders are restored before spans are stored in the local canon.
- **Failure memory is retained, not immutable.** Rejected and failed items remain as negative information and block matching re-proposals. A deliberate later grounding pass can reconsider them when the source set changes.
- **Geometry is advisory.** Novelty, DPP order, cliché distance, archive bins, and bridge metrics influence what is proposed or shown first, never what is declared grounded.

One sentence resolves every design dispute in the codebase: **embeddings measure dispersion, never truth.**

## Configuration reference

Installing Burgess asks for **four settings**. Only `source_path` is required; the other three ship with working defaults. Claude Code stores them per installation. To change one, reconfigure the plugin from the `/plugin` interface and start a new session so the MCP server reads the new value.

| Setting | Required | Values | Default | What it controls |
| --- | --- | --- | --- | --- |
| `source_path` | **Yes** | a file, a directory, or a glob | — | The document(s) the running graph engine verifies against |
| `sensitivity` | No | `low` · `medium` · `high` | `medium` | How aggressively text is scrubbed before subagent egress |
| `metrics_mode` | No | `structure_only` · `with_embeddings` | `structure_only` | Which signal the graph's metrics use |
| `extract_wave_size` | No | `1`–`10` | `6` | How many extractors `/kg-build` runs concurrently |

### `source_path` — the running verification source *(required)*

Every extracted edge must quote a **verbatim span** from the configured source set, and the boundary verifies the span against the file it names. The `burgess` MCP server does not start until `source_path` is set.

| Form you enter | Resolves to | Notes |
| --- | --- | --- |
| A single **file** | Just that UTF-8 text file | An explicit file is read regardless of extension; Markdown or `.txt` is the supported format |
| A **directory** | Every `.md`/`.txt` directly inside it | **Not recursive.** Dotfiles are skipped |
| A **glob** | Every matching `.md`/`.txt` | Use a `**` segment to recurse into subdirectories |

```text
/home/me/notes/theory-of-change.md      a single document
C:\docs\source.md                       the same, on Windows
/home/me/research/notes                 every .md/.txt directly in that folder
/home/me/research/**/*.md               every .md at any depth below it
```

Rules worth knowing:

- Enter the bare path without surrounding quotes. Quotes are stripped defensively, but do not add them.
- Markdown and plain text only. No PDFs or media.
- Files are deduplicated by basename; the lexicographically first full path wins.
- A non-UTF-8, binary, or unreadable file in a directory/glob is skipped rather than decoded lossily.
- The running server's configured source is the write boundary's verification corpus. Passing a different path to `/kg-build` does **not** reconfigure that boundary; reconfigure `source_path` and start a new session before building a different corpus.

`/kg-build` resolves the default source through the engine. An unreadable configured path stops the build rather than silently falling back to the bundled demo corpus.

### `sensitivity` — what is redacted before subagent egress

| Value | Redacts | Choose it when |
| --- | --- | --- |
| `low` | Secrets only — API keys, tokens, credentials | The source is public or already clean |
| **`medium`** *(default)* | Secrets **+ structured PII**: emails, phone numbers, SSNs, credit-card numbers, IP addresses, credentialed URLs | The normal choice |
| `high` | Everything in `medium` **+ person-name and street-address heuristics** | The source contains people or addresses you do not want sent to a subagent |

Secrets are always scrubbed. `high` uses heuristics and may redact ordinary capitalized phrases. Absolute filesystem paths are always removed from engine error text, and the same secret/PII scrub is applied before an error reaches the transcript.

### `metrics_mode` — which signal graph metrics use

| Value | Effect |
| --- | --- |
| **`structure_only`** *(default)* | Graph structure is the signal: degree, betweenness, communities, and the specificity gate |
| `with_embeddings` | **Currently inert.** Kept for compatibility after removal of the former sqlite-vss candidate generator |

Leave this at `structure_only`. It has no bearing on `/kg-diverge`, whose embedder is selected separately.

### `extract_wave_size` — concurrent section extractors

`/kg-build` launches one extractor subagent per section. This setting changes how many isolated section extractors run concurrently:

| Value | Effect |
| --- | --- |
| `1`–`2` | Effectively serial; gentlest on rate limits |
| **`6`** *(default)* | A 19-section document builds in four waves: 6 + 6 + 6 + 1 |
| `8`–`10` | Faster on long sources, with more rate-limit and lock pressure |

An explicit second `/kg-build` argument overrides the configured wave size for that run. Values are clamped to `1`–`10`; non-numeric values or values below `1` fall back to `6`.

### Verify configuration

The status tools have no slash. Ask Claude in plain language:

```text
"Is the Burgess engine running?"    → kg_ping reports version, sensitivity, metrics_mode
"What source is configured?"        → kg_status reports the resolved source path and files
```

## Command cheat sheet

The primary workflow is **build → ground → query → view**. Generation, divergence, perturbation, evaluation, and experimentation are optional extensions. Arguments in `<angle brackets>` are required; those in `[square brackets]` are optional.

The full [command manual](docs/COMMANDS.md) documents every argument and worked example.

| Command | What it does | The detail in brackets |
| --- | --- | --- |
| `/kg-build [source_path] [wave_size]` | Extract a span-anchored graph from the configured source, one section per extractor | *Optional:* an orchestration path that should match the running server's configured source; concurrent sections per wave |
| `/kg-ground [query-or-node-filter]` | Drain the grounding queue, challenge hubs, and assign verdicts through the sole verdict path | *Optional:* limit the run to one topic or node area |
| `/kg-query <question>` | Answer from the grounded graph, with provenance and falsification counters attached | **Required:** your question |
| `/kg-view [html\|report\|all]` | Render the offline `graph.html` + `GRAPH_REPORT.md`; read-only — it never changes the graph | *Optional:* which artifact to render (defaults to both) |
| `/kg-generate [mechanism-set] [k]` | Propose unverified candidates from graph structure | *Optional:* `default`, `all`, or one of seven mechanisms; number of candidates |
| `/kg-diverge <brief> [domain-template] [reach]` | Explore a brief as a varied idea slate; optionally materialize selected pins as hypotheses | **Required:** your brief. *Optional:* domain axes and `conservative\|balanced\|wild` reach |
| `/kg-perturb [second_source_or_graph_json]` | Build or load a second construction and cross-generate against it | *Optional:* a second text source or pre-built `graph.json`; omission degrades to regrouping the current graph |
| `/kg-eval [graph.json]` | Measure extractor precision (Stage 4) and grounding reliability (Stage 7) | *Optional:* which `graph.json` to grade (defaults to the current derived graph) |
| `/kg-experiment [prompts_path]` | Blind multi-arm ideation experiment (control / graph / graph+generate / graph+generate+dpp / rag) | *Optional:* a file of test prompts (defaults to the built-in set) |

Remember: the status check (`kg_ping`) and the other behind-the-scenes MCP tools have **no** slash — just ask Claude for them in plain words.

## Architecture in six invariants

1. **Verdict monopoly** — only `kg_ground` produces verdicts; nothing in `kg_engine/divergence/` can set or upgrade an epistemic state (import-firewall-tested, adversarially attacked in the suite).
2. **Support boundary** — extracted agent edges without a verifiable source span are rejected; a hypothesized node or edge cannot be promoted to `grounded` without a verified source span or a recorded external citation. Forged verdicts are stripped at the boundary and re-quarantined by the reconciler.
3. **Advisory ceiling** — DPP order, novelty, cliché distance, bins, monitor readings influence *what is proposed and in what order*, never *what is true* (snapshot-tested: grounding output is bit-identical with the geometry flag on vs off).
4. **Different-family judge** — the diversity embedder (model2vec) never shares lineage with the generator (Claude), so the geometry can't just agree with the model that made the ideas.
5. **Session-ephemeral archives** — MAP-Elites archives never persist across sessions; only pins, discards, comparisons and session metadata do (project-local, git-friendly, under `.kg/diverge/`). The knowledge graph is the durable archive.
6. **Unified negative memory** — human discards and grounding failures live in one semantic store; neither generation path ever re-proposes from it.

The knowledge-graph spine: canon = one human-editable Markdown file per node (git-mergeable, semantic merge driver); derived = regenerable NetworkX/SQLite projections; MCP server (`burgess`, 27 tools) is the trust boundary; six subagents (extractor, grounder, adversarial-grounder, generator, annotator, evaluator) do the language work; the engine stays deterministic.

Those six are the load-bearing ones; the suite enforces eleven (`I1`–`I11`). The full, self-contained architecture reference — module map, data model, write-boundary contract, tool surface, divergence internals and constants, runtime and environment, and the invariants in full — is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## What this does not guarantee

In the spirit of both donors, honestly:

- **Grounding is a provenance judgment, never truth about the world.** A `span-present` grounded edge is supported by a verbatim passage in your source, which may itself be wrong. An `inferred` grounded hypothesis may instead carry an external citation supplied by the grounder; Burgess records that citation but does not independently validate it.
- **Novelty numbers are variety proxies.** `novelty` is k-NN distance to *this session's own ideas*; `originality` is distance to *the agent's own* guess at the clichés. Neither is novelty against prior art or the world.
- **The cliché map hedges cliché; it does not guarantee freshness.** "Obvious" is the model's notion of obvious.
- **The judge is bounded, not infallible.** Validity filtering is clipped to a [0.7, 1.3] multiplier at weight 0.3 — it can nudge, it cannot veto diversity; bad ideas can still reach you (that's the point: you are the selector).
- **The DPP presentation is advisory.** Whether it actually lifts downstream ideation was measured blind (see `docs/fusion/EXPERIMENT.md`); the shipped default follows that measurement, not our enthusiasm.

## Tests

<!-- test-count:begin -->
The suite currently reports: **1310 passed, 2 skipped** (`uv run --extra dev pytest tests/`).
<!-- test-count:end -->

This line is generated from pytest output, never hand-written. Run it yourself:

```bash
uv sync --extra dev   # or: pip install -e ".[dev]"
uv run pytest tests/
```

The fusion invariants live in `tests/fusion/` (import firewall, DB isolation, adversarial forge attempts, graceful degradation, archive ephemerality, snapshot invariance, verdict neutrality); the divergence engine's ported suite in `tests/fusion/divergence/`; the vendored convergence suite at `tests/`.

## Lineage

Burgess is a fusion of two MIT-licensed plugins by the same author:

- **Sproutgraph** — the convergence spine (engine, MCP boundary, commands, agents, experiment harness, canon/derived model), vendored at `17c4066`. Retired and no longer published; Burgess is its continuation.
- **Cambrian** — the divergence engine (embedder, MAP-Elites, novelty, DPP, monitor, judge bounds, cliché discipline), vendored at `a2adfa1`. Republished at [sergiparpal/cambrian](https://github.com/sergiparpal/cambrian) and developing on its own again; the vendored commit is still reachable from its `HEAD`, so every attribution claim below stays checkable against the public repository.

The donor pins are a permanent Stage-0 identity, not a sync point: Burgess does not track either donor's later work, and a donor resuming development changes nothing about what the fusion copied (invariant I11 asserts reachability of the pinned SHA, not a frozen `HEAD`).

Per-file attribution with SHAs and every adaptation: [`docs/fusion/ATTRIBUTION.md`](docs/fusion/ATTRIBUTION.md). Migrating from either donor: [`docs/MIGRATION.md`](docs/MIGRATION.md). How this plugin was built (the full fusion plan and its decision log): [`docs/fusion/`](docs/fusion/).

## License

MIT — see [LICENSE](LICENSE).
