# Burgess — architecture reference

This document is self-contained: it describes Burgess as it is, from its own source. The engine
source under `scripts/kg_engine/` remains the final authority — when this prose and the code
disagree, the code wins; grep it rather than guessing. File references name modules, not line
numbers.

Burgess is a Claude Code plugin fusing two engines around one trust boundary:

- a **convergence engine** that grows source documents into a rigorously grounded, queryable
  knowledge graph;
- a **divergence engine** that turns any brief into a diverse, non-cliché slate of ideas.

One sentence resolves every design dispute: **embeddings measure dispersion, never truth.**

## 1. Two layers, one boundary

1. **Deterministic Python engine** — `scripts/kg_engine/`, exposed as the `burgess` MCP server
   (27 tools, namespaced `mcp__plugin_burgess_burgess__*`). `server.py` (the `KGEngine` facade +
   FastMCP tool surface) is the trust boundary. The engine is **never installed**: it resolves via
   `PYTHONPATH=<plugin>/scripts` (see `.mcp.json`), so engine edits need no rebuild; the
   provisioned venv holds only dependencies.
2. **Language layer** — 9 slash commands (`commands/kg-*.md`), 6 subagents (`agents/`), the
   operating-guide skill (`skills/burgess/SKILL.md` + on-demand `references/`). All LLM work
   happens here; agents hand structured JSON back across the MCP boundary. The engine stays
   rule-bound: it validates, projects, measures and orders — it never invents content and never
   trusts a claim it cannot check.

The workflow the commands implement: **build → ground → generate → ground → query → eval →
experiment**, plus the standalone **diverge** lane. Generation is offensive (it emits into a
`hypothesized` lane, never gates on a metric); grounding is the only defensive filter and the only
verdict path.

## 2. Engine module map (`scripts/kg_engine/`)

| Module | Role |
|---|---|
| `model.py` | Core data model: the three axes (enums), `Node`/`Edge`, span verification/normalization, frontmatter Markdown I/O, shared vocabularies (`VERDICT_STATES`, `FAILURE_STATES`, `NON_LIVE_STATE_VALUES`, `MIN_SPAN_CHARS`) |
| `envconfig.py` | Stdlib-only leaf: env-value cleaning + project/data/source/pack resolution rules |
| `atomicio.py` | Stdlib-only leaf: crash-safe atomic writes (temp + fsync + replace) |
| `graphio.py` | Version-robust NetworkX node-link (de)serialization for `graph.json` |
| `sources.py` | `SourceSet`: resolve a file/dir/glob of `.md`/`.txt` into ordered `{basename → text}`, source-aware span verification, `##` section splitting |
| `scrub.py` | Egress PII/secret scrubbing (§1.9) with consistent placeholders |
| `pack.py` | Domain-pack contract/loader/coverage |
| `boundary.py` | The write boundary: strict payload validation → dispositions (span-present, never-forge-a-verdict, dedup, flood cap) |
| `canon.py` | Canonical layer: human-editable Markdown notes, crash-safe single-writer I/O, git-as-rollback, lease lock |
| `groundaudit.py` | Crash-safe append-only grounding-audit log (the trust root for verdicts) |
| `reconciler.py` | Out-of-band-edit sweep: mtime/size pre-filter + full re-hash, forged-verdict re-quarantine |
| `canonmerge.py` | Semantic git merge driver for canon notes (never forges a verdict) |
| `projector.py` | Derived layer: canon → `graph.json` + `index.sqlite` + Leiden communities + precomputed ranks |
| `generate.py` | The seven structural discovery mechanisms + the convergence tally |
| `operations.py` | The four endo operations (collapse/explode/regroup/open), writing via the propose lane |
| `advisory_geometry.py` | Advisory hybrid-descriptor DPP ordering over `kg_generate` candidates (behind `divergence.dpp`, default off) |
| `pathing.py` | The grounded-only path algorithm behind `kg_explain_path` |
| `waves.py` | Deterministic resolver for `/kg-build`'s extraction wave size |
| `export.py` (+ `templates/graph_html.py`) | Render `graph.html` + `GRAPH_REPORT.md` from the derived layer |
| `harness.py` | Deterministic measurement: agreement, specificity, ideation, convergence |
| `backend.py` | Headless API-key extraction for CI (same boundary as the interactive flow) |
| `lightrag_arm.py` | Optional LightRAG comparison arm (experiment-only, opt-in) |
| `dirlock.py` | Atomic-mkdir directory lock with heartbeat liveness (used by bootstrap) |
| `server.py` | `KGEngine` facade + the FastMCP tool surface — the trust boundary |
| `divergence/` | The divergence engine (§6) — import-firewalled from epistemic state |

## 3. The convergence spine

### 3.1 Canon vs derived

- **Canon** = source of truth: one human-editable Markdown file per node at
  `<project>/canon/<slug(id)>.md` — YAML frontmatter + free body; directed edges live in the
  source node's `edges:` block. The canon carries the grounding state. Full note format with an
  example: `skills/burgess/references/contract.md` §8.
- **Derived** = disposable projection at `<data_dir>/derived/{graph.json,index.sqlite}` (data dir:
  `$KG_DATA`, falling back to `<project>/.kg-data`). It contains nothing the canon does not; never
  hand-edit it — reproject.

Frontmatter key order is fixed (load-bearing for byte-identical canon): `id`, `label`,
`node_type`, `file_type`, the three axes, `created_at`/`updated_at`, `edges:`. Edge ids are
deterministic — `e_{slug(source)}__{slug(relation)}__{slug(target)}` — always recomputed, never
trusted from disk. Node timestamps are excluded from the content hash so metadata churn doesn't
force reprojection. The parser tolerates a leading BOM, skips malformed edge entries rather than
dropping the note, and coerces unknown enum values to safe defaults.

### 3.2 The three axes — orthogonal, never collapsed to one scalar

| axis | values | default |
|---|---|---|
| `provenance` | `span-present` \| `inferred` \| `hypothesized` | node `span-present`, edge `inferred` |
| `authored_by` | `deterministic` \| `agent` \| `human` | `agent` |
| `epistemic_state` | `unverified` \| `grounded` \| `rejected` \| `failed` \| `obsolete` | `unverified` |

A high-provenance edge can be unverified; a grounded edge can be inferred. A verifying span never
auto-promotes `inferred` → `span-present` on a write; only `kg_ground` promotion upgrades
provenance. Vocabulary sets used everywhere, single-homed in `model.py` so extending one can never
silently leave a consumer behind on the older form: `VERDICT_STATES = {grounded, rejected, failed}`;
`GROUNDABLE_STATES` adds `obsolete` (every state `kg_ground` may stamp); `FAILURE_STATES =
{rejected, failed}` — never pruned; `NON_LIVE_STATE_VALUES = FAILURE_STATE_VALUES ∪ {obsolete}`.

That last set is **what is not live topology**, and every structural surface reads it: a refuted
relation and a superseded one are both dead, so neither may confer degree/community/betweenness
weight (`projector._live_subgraph`), carry a path (`DerivedReader.shortest_path`), be walked by the
generators (`generate._live_undirected`), answer a query (`kg_context`'s answer lane), or count as a
live relation in `kg_agenda`'s detectors and its edgeless-communities crossing test. A surface left
on the narrower failure-only set presents connectivity every other surface calls dead — which is
exactly what `shortest_path` and `kg_agenda` did after `obsolete` joined the vocabulary, and what
`tests/test_review_r12.py` now pins. Nodes are never dropped, only edges: an attacked hub whose
relations are all refuted still ranks honestly at degree 0.

The **one deliberate exception**: `kg_context`'s falsification counter stays on `FAILURE_STATES`. It
counts refutations, and `obsolete` is a lifecycle transition, not negative information (§1.7). That
exception is pinned too, so nobody "consistently" widens it.

### 3.3 The write path

`kg_write(payload)` → `boundary.py` validation → per-item disposition:

- **ACCEPTED** — valid, span verifies, type declared; written `unverified`.
- **DEMOTED** — written with an axis stripped: `forged-verdict-stripped` (any non-`unverified`
  state reset), `human-claim-stripped`, `deterministic-claim-stripped` (a write can't self-declare
  parser authorship to skip the span check).
- **QUARANTINED** — structurally valid but untrusted: `undeclared-node-type` /
  `undeclared-edge-type` (off-pack), `collapses-into-known-failure` (identity or reverse already
  in `FAILURE_STATES` — failure memory binds re-extraction), `collapses-into-known-verdict`.
- **REJECTED** — not written: `no-supporting-span`, `span-not-in-source` (fabrication),
  `span-not-in-named-source` (mis-attributed `source_file`), `span-too-short` (< 4 non-space
  chars), `empty-source`/`empty-relation`/`empty-target`, `rate-limited-flood` (per-payload
  budget `max(64, kb·20)`), `truncated-payload` (`complete=false`), `schema-invalid`.

Only `truncated-payload` and `schema-invalid` are `retryable=true` (transport); everything else is
semantic — fix the item, don't resend it. Every **non-deterministic edge must carry a verbatim
source span** (normalized substring check: whitespace collapsed, case-folded, curly quotes/dashes
folded). The full contract, reason strings and worked examples:
`skills/burgess/references/contract.md`.

Nodes carry no `collapses-into-*` quarantine — a re-emitted node id is deduped and ACCEPTED. But a
node already holding a verdict (`grounded`/`rejected`/`failed`/`obsolete`) keeps its **body** across
that merge: a `Node` has no `span` field, so `kg_ground` restates a promoted node's support *in the
body*, and an incoming body would otherwise blank the very evidence the verdict rests on
(`canon._merge_into_existing`). Label and `node_type` still update. To revise a grounded node's
prose, edit the canon note.

`kg_propose(payload)` is the **hypothesized write lane**: it forces `provenance=hypothesized`,
refuses text claims (`propose-lane-text-claim`), requires no span, and preserves
`authored_by=deterministic` for genuine discovery mechanisms. Same validator, same forge guards.
The `kg_operate` mechanisms are those discovery mechanisms and they do claim it: their structural edges
carry `authored_by=deterministic`, while a node whose `label`/`body` came from the caller stays `agent` —
structure is computed, language is authored.

An optional `idempotency_key` makes a re-sent identical write a true no-op (verbatim cached replay);
`kg_write` also reuses a signature-keyed canon baseline across calls so parallel build waves don't
re-parse the whole canon per write.

### 3.4 Verdict monopoly

Only `kg_ground(target_id, verdict, kind, note, support_span, support_note)` sets epistemic
states. `verdict ∈ {grounded, rejected, failed, obsolete}`. Promoting a `hypothesized` item to
`grounded` **requires support**, which upgrades provenance: `support_span` (verbatim, span-verified)
→ `span-present`, or `support_note` (external citation) → `inferred`; neither →
`hypothesis-needs-support`. Every legitimate transition appends one record to the append-only audit
ledger `<project>/.kg-ground-audit.jsonl` (with a `.ckpt` sidecar for O(1) recovery).

The **reconciler** (`reconciler.py`) polices the canon for out-of-band edits: an
`epistemic_state` sitting in a groundable state with no matching audit record is a **forged
verdict**, and its fields are cleared and re-quarantined. The state it is reset *to* is the
failure baseline the forge overwrote, falling back to `unverified` only when the item held no
prior verdict (`_requarantine_state`) — otherwise a forge *over* a failure
(`rejected` → hand-edited `grounded` → re-quarantined `unverified`) would launder the failure
away: the item drops out of `failure_ids`, the boundary stops quarantining re-proposals of the
refuted claim, and no later sweep can recover it. Its twin, `_restore_erased_negative`, catches
the same erasure attempted directly (`failed`/`rejected` → `unverified`). The two guards are the
two halves of one rule: **an out-of-band edit may never be the thing that ends a falsification**
(§1.7). Forge detection is *counting*, not set-membership — each legitimate transition consumes
exactly one audit record, defeating replay. State cache: `<project>/.kg-reconcile-state.json` (fails open). `rejected` and
`failed` edges are permanent negative memory — never pruned, surfaced in
`kg_context.falsification_counters`.

### 3.5 The derived layer

`projector.py` builds, under `<data_dir>/derived/`:

- **`graph.json`** — NetworkX node-link JSON. Advisory ranks (degree, Leiden `community`,
  `betweenness`, specificity-weighted `spec_betweenness`) are computed over the **live subgraph**
  (`NON_LIVE_STATE_VALUES` edges excluded — failures *and* `obsolete`; §3.2), but the stored graph
  and tables stay complete: failure memory is drawn, never filtered.
- **`index.sqlite`** — `nodes` (label, type, axes, degree, community, `structural_bridge`,
  betweenness, `spec_betweenness`, `specificity`, `gate_on`), `edges` (id PK, endpoints, relation,
  axes, span, `source_file`, confidence, and **`owner`** — the canon note the edge is persisted
  in, so incremental diffs key on the owning file, not on `source`), and a `meta` table
  (cheap signature, per-file stats/hashes, and the two read-only source-change advisories below).

Two **read-only** source-change advisories ride in `meta`, computed off the hot path and gated on a
source-payload hash so they refresh whenever the source set moves — neither ever mutates a verdict or
re-queues anything (re-grounding stays a `kg_ground` decision):
- **R3 stale verdicts** (`stale_verdicts`) — a `grounded`/`failed` **span-present** edge whose stored
  span no longer verifies against its source file (the evidence *shrank*).
- **R3-mirror re-examinable verdicts** (`reexaminable_verdicts`) — a `failed`/`rejected` item (nodes and
  **span-less** items included) that was judged against a source set which has since **grown or changed**
  (non-monotonic evidence), filtered to items whose text overlaps the changed source (`source_file_sigs`
  tracks the per-file baseline). Self-clearing on re-ground; surfaced in `kg_context.advisory` and the
  `GRAPH_REPORT`. The divergence side mirrors it: `failed`-fated brief discards are surfaced as
  `reexaminable_discards` on a source change with an explicit un-seal lever (never auto-un-sealed).

Staleness (`is_stale()`) is content-driven, independent of git state: a cheap canon-dir
`(count, newest-mtime)` pre-gate, then an authoritative per-file content-hash comparison that is
stat-gated (only files whose size/mtime moved are re-parsed). A schema-outdated db (missing the
generative-rank or `owner` columns) heals via full rebuild. Reads call `_ensure_projected()`
first; a reprojection failure degrades gracefully (`projection_degraded` flag, empty-schema
fallback) — writes never pass through that seam.

### 3.6 Egress scrub (§1.9)

`kg_scrub` redacts **secrets always** (private keys, cloud/API tokens, JWT/Bearer, keyword=value,
high-entropy fallbacks) plus **PII per sensitivity** (`low` = secrets only; `medium` adds
EMAIL/PHONE/SSN/CC/IP/CREDURL; `high` adds PERSON/ADDRESS) with **consistent placeholders**
(`⟦CATEGORY:N⟧`) so relational structure survives — one placeholder namespace across the whole
session. `kg_write` **restores** placeholders to the original text before span verification and
persisting: the scrub protects egress; the canon stores the original.

## 4. The generative layer

`kg_generate` runs seven deterministic structural mechanisms over the derived graph (default set:
`bridge`, `seed`, `compression`; `all` adds the rest):

1. **bridge** — connect strong-but-separate hubs across communities.
2. **seed** — non-adjacent pairs with a positive common-neighbour residual `c − E[c|d]`
   ("abnormally connectable for their distance").
3. **compression** — a dense community earns a proposed `compression` node (+ `collapses_into`
   edges) only when an MDL screen shows a description-length saving and the cluster isn't vague;
   the label is left blank for the language layer.
4. **regroup** — re-run Leiden at a different resolution; pairs that flip from intra- to
   cross-community are bridges invisible under the prior partition.
5. **transplant** — import a hub's dominant relation pattern into the community with the highest
   absorption capacity.
6. **ensemble** — bridges present in one construction's structure but not a second's (from
   `/kg-perturb`); degrades to `regroup` without a second graph, and says so. The second construction
   is built **key-free, in-session**: `kg_write(..., construction=<name>, source=<second source>)`
   routes the same span-verified boundary to a separately-named alternate canon under
   `<project>/.kg/constructions/<slug>/`, and `kg_generate(second_construction=<name>)` (or a pre-built
   `second_graph` path) projects + cross-generates against it — no API key, no `backend` extra. The
   headless `backend.py` stays available for out-of-session / CI builds.
7. **periphery** — low-degree sources get a `bridges` edge to their max-connectability anchor —
   the periphery the hub-seeking mechanisms ignore.

Each candidate carries an advisory `convergence` count — how many distinct mechanisms
independently proposed the same edge, tallied pre-truncation. It is a grounding-queue ranking
prior, never folded into `score`, and only reorders the queue once `harness convergence` shows
clean band separation. Candidates route through `kg_propose`; the four endo operations
(`kg_operate`: collapse/explode/regroup/open) persist through the same lane. `kg_absorption`
scores, per node grounded from a hypothesis, how long it stayed perturbing before the graph
renormalized (`fertile | absorbed | isolated`).

## 5. The MCP tool surface (27 tools)

Full signatures and return shapes: `skills/burgess/references/tools.md`.

- **Read/query (12):** `kg_ping`, `kg_scrub`, `kg_metrics`, `kg_status` (projection-free
  status + section coverage + the engine-resolved `source` — the build-resume probe and
  `/kg-build`'s source-of-truth for the configured `source_path`), `query_graph`, `get_node`, `get_neighbors`,
  `shortest_path` (never routes through a non-live edge — §3.2), `kg_explain_path`
  (grounded-edges-only chain + advisory `leap`; capped at
  `pathing.MAX_EXPLAIN_NODES` distinct nodes — its closure is quadratic in that count, so an uncapped
  model-supplied list would outrun the handler watchdog), `kg_context`
  (budgeted, falsification-aware; grounded `items[]` never mixed with `hypotheses[]`), `kg_agenda`
  (structural suggested questions, `answerable_now` vs `blocked_on_grounding`), `kg_export`
  (offline `graph.html` + `GRAPH_REPORT.md`; the three axes on independent visual channels).
- **Write/ground (6):** `kg_write`, `kg_propose`, `kg_ground` (the verdict monopoly),
  `kg_rename` (strict), `kg_merge` (deliberate merge; negative information sticky), `kg_operate`.
- **Generative reads (2):** `kg_generate`, `kg_absorption`.
- **Divergence surface (7):** `kg_diverge_init`, `kg_diverge_ingest`, `kg_diverge_remember`,
  `kg_diverge_parents`, `kg_diverge_metrics`, `kg_diverge_recall`, `kg_diverge_materialize`.

Every tool is wrapped in a uniform transport-error envelope (`{ok:false, error, error_kind}` on a
raised exception), so a tool call never crashes the session.

## 6. The divergence engine (`scripts/kg_engine/divergence/`)

A local, server-less ideation engine: the language layer generates and judges candidates; the
engine owns the anti-convergence math. Pipeline per cycle (`kg_diverge_ingest`): embed →
near-duplicate dedupe → MAP-Elites niche placement → k-NN novelty → DPP slate selection, with an
anti-collapse monitor reading every round.

- **Embedder** (`embed.py`, selected by `KG_DIVERGE_EMBEDDER`): `static` (default) = model2vec
  `minishlab/potion-multilingual-128M` — 256-dim, CPU/numpy, torch-free, ~120 MB, lazily
  downloaded and cached (`$HF_HOME`, pointed at `$KG_DATA/models` when unset); `hash` =
  deterministic 512-dim char-n-gram vectorizer (tests/offline — never silently auto-selected);
  `local` = sentence-transformers `bge-small-en-v1.5` (384-dim, needs torch). All embedders
  return L2-normalized vectors; widths may not mix within a project. The embedder never shares
  lineage with the generator (Claude), so the geometry can't just agree with the model that made
  the ideas.
- **Archive** (`archive.py`): MAP-Elites over the resolved descriptor axes — categorical axes
  bucket by value, continuous axes bin over their range (default 5 bins), and the one `open`
  (mechanism) axis is niched geometrically by a frozen-Voronoi partition: 24 cells, k-means
  fit-once-then-frozen after 2×24 = 48 mechanisms accumulate (deterministic cold start before
  that).
- **Novelty** (`novelty.py`): mean k-NN cosine distance (k=5) to the session's own ideas — a
  variety proxy with no external referent, and documented as such.
- **Slate** (`diversity.py`): greedy MAP inference over a DPP kernel (farthest-point fallback),
  pool capped at 200 elites. Judge fitness enters as a bounded quality term: affine-rescaled,
  clipped to a [0.7, 1.3] multiplier, blended at weight 0.3 — it sharpens within-niche ordering
  and can never prune variety.
- **Monitor** (`monitor.py`): flags `collapsing` on mean-cosine 0.55 (absolute fallback) /
  entropy 0.50 (≥3 occupied niches) / relative baseline+0.15 with ceiling 0.80 (rolling window 5,
  min baseline 2); `under_generation` below 0.6× the per-generation target; the variety-erosion
  early warning fires at ≥1.5× novelty-decay acceleration sustained 2 generations.
- **Memory** (`memory.py`): durable pins/discards/comparisons per brief; informative A-vs-B pair
  selection; diverse-parent selection (pins always in, discards never).
- **State** (`state.py`): project-local under `.kg/diverge/<brief-slug>/`. `meta.json`,
  `axes.json`, `session.json`, `materialized.json` and `memory/` are durable; the `session/` dir
  (MAP-Elites archive, candidate records, `embeddings.npz`/`mech_embeddings.npz` vector stores,
  the Voronoi partition) is **session-ephemeral**: a new session id wipes it. The knowledge graph,
  not the archive, is the durable store.

**Candidate ids are primary keys.** One id keys the archive's `elite_id`, the candidate record store,
both embedding stores, pins/discards, and the slate's `embedding_ref`, so the contract is: **unique
within a batch, and unique for the life of a project unless resubmitted verbatim.** A batch-local
duplicate is rejected by `_parse_candidates`; an id already recorded under *different* text is
rejected by `_guard_id_reuse` (before embedding, inside the project lock). A byte-identical
resubmission is not a collision — dedup drops it as a no-op. Without both guards a niche silently
acquires another idea's text/coords/embedding, and dedup cannot see it: dedup compares text, not ids.

**Locking** (all three are the same best-effort atomic-`mkdir` lock, which proceeds unlocked on
timeout rather than deadlock — a divergence command must never hang):

| Lock | Guards |
|---|---|
| `State.project_lock` | the whole-project read-modify-write of `ingest` (and an axes-changing `init`) |
| `State.project_read_lock` | the multi-file reads of `recall` / `metrics` / `parents`, so none of them can pair a new `archive.json` with an old `candidates.json`. A no-op when the project dir does not exist — a read-only command must not materialize state |
| `State._preference_lock` | pins **and** discards together for one domain. `add_pin`, `add_discard` and `remove_discard` each mutate *both* files, so one lock per file let a concurrent pin and discard of an id interleave and land it in both lists or neither |

**Cycle response** (`kg_diverge_ingest`): `slate`, `slate_ids`, `ask_pairs`, `ask_policy`, `monitor`,
`slate_mechanism_novelty`, `open_axis` (+ `surface_mechanism_gap` when the probe is on). `slate_ids`
is the id list of the slate items and honours neither pins nor discards — **not** breeding parents;
it was named `parents` before 0.4.0, which invited exactly that misread. The empty-generation
response carries every key with neutral values, `monitor.variety_erosion` included.

**`parents` command response**: `{"parents": [{id, text, coords, niche_id, novelty, pinned}]}`, plus
optional `stale_pins` / `stale_pins_note` — pinned ids with no candidate record, which happens
because an axes change resets the geometry while preserving preference memory. They are reported
rather than emitted as parents with empty `text`, and the keys are absent (not empty) when every pin
resolves.

**Materialization** (`kg_diverge_materialize`) is the only door from divergence into the graph:
pinned ideas become nodes via the propose lane exclusively (`provenance=hypothesized`,
`epistemic_state=unverified`, `authored_by=agent`, full `[diverge]` lineage in the body). A
`materialized.json` ledger tracks their fate; on the next `init`/`recall`, any materialized pin
whose canon record was actively **falsified** (`failed`) is folded into the brief's discards — a
merely-unsupported (`rejected`) pin, the expected state of a novel idea with no in-source span yet,
stays recoverable and is never auto-discarded. Grounding **falsifications** and human discards are
one negative memory, and neither generation path re-proposes from it. The fold keys on a
deliberately narrower `server.MATERIALIZED_DISCARD_STATES` = {`failed`} — distinct from the global
`FAILURE_STATES` = {`rejected`, `failed`} (which still governs projector no-prune and the
write-boundary durability quarantine that backs `/kg-generate` negative memory). The sync only
reads verdicts; issuing them stays `kg_ground`'s monopoly.

**Advisory DPP over `/kg-generate`** (`advisory_geometry.py`, behind `divergence.dpp`, default
off): the same candidate set is reordered by a hybrid-descriptor DPP — one semantic axis (batch
k-NN novelty) plus community/graph-distance/grounded-mix structural axes — and labelled with
niche bins, semantic novelty, and distance to the graph's "center" (the top-6 grounded-degree
hubs, the structural cliché map). Snapshot-enforced advisory: same candidates, same scores,
bit-identical grounding downstream.

Constants above are the engine's shipped defaults, drift-guarded by tests; per-domain overrides go
in the axes spec's `engine:` block (`pack/domains/_schema.md` has the full table).

## 7. The domain pack

`pack/pack.yaml` declares the vocabulary of one theory: `domain`, `version`, `node_types`,
`edge_types` (both non-empty, unique, disjoint), `glossary` (term → definition),
`specificity_seeds` (term → IDF-like float), and an optional `divergence:` section (descriptor
axes + the `dpp` flag + engine overrides). Types outside the pack quarantine as
`undeclared-*-type`; extending the pack — never editing the quarantine bucket — is how they clear.
`python -m kg_engine.pack validate pack/pack.yaml [source]` checks the contract and, with a
source, coverage in both directions (did the pack capture the source's defined terms; is the
glossary grounded in the source). Schema detail: `skills/burgess/references/pack-schema.md`;
divergence templates ship as pack fragments under `pack/domains/`.

## 8. Language layer

- **Commands** (9): `/kg-build` (wave-parallel extraction), `/kg-ground` (the grounding loop),
  `/kg-generate`, `/kg-perturb`, `/kg-query`, `/kg-eval`, `/kg-experiment`, `/kg-view`,
  `/kg-diverge`.
- **Subagents** (6): `kg-extractor` (one per `##` section; emits `kg_write` payloads),
  `kg-grounder` (verdicts on the merits), `kg-adversarial-grounder` (tries to falsify survivors;
  `attacked_by` edges + `failed` verdicts), `kg-generator` (phrases structural candidates —
  language only, never structure), `kg-annotator` (label passes for precision/agreement),
  `kg-evaluator` (the blind multi-arm ideation experiment).
- **Skill**: `skills/burgess/SKILL.md` is the operating guide; `references/` holds the
  load-on-demand contracts (write contract, tool shapes, pack schema, divergence operators, judge
  rubric, axis inference).
- **Hook**: `hooks/precontext.mjs` (PreToolUse on Grep/Glob/Read, 8 s cap) pipes the tool payload
  to `precontext.py`, which injects a small grounded-context block (budget 800 tokens, ≤6 grounded
  items, ≤3 advisory bridges, a falsification counter) so the session queries the graph before the
  filesystem. It fails silent on every error path, bails if the derived index doesn't exist,
  declares a 15 s lease TTL (so a SIGKILLed hook can't wedge writers), and size-gates synchronous
  reprojection at 400 notes (above that it serves the existing index).

## 9. Runtime: provisioning and supervision

- **Provisioning**: the SessionStart hook runs `hooks/provision.mjs` (async, 600 s cap), which
  finds a system Python ≥ 3.10 and hands off to `scripts/bootstrap.py --background` — a detached
  worker that builds the engine venv (`uv sync` if available, else stdlib `venv`+`pip`),
  stamp-gated on a hash of `pyproject.toml` + interpreter ABI so it's a no-op when current. Venv
  precedence: `--venv` > `$KG_ENGINE_VENV` > `$CLAUDE_PLUGIN_DATA/.venv` > `<repo>/.venv` (dev).
  `--reconcile` runs the once-per-session canon reconcile after the venv is ready.
- **Supervision**: `.mcp.json` starts `scripts/launch_server.mjs`, a Node parent that always
  spawns successfully, heals the venv in the foreground if provisioning hasn't finished, then
  supervises the Python engine: capped exponential backoff (200 ms → 5 s), max 5 restarts per
  60 s window. A crash during startup heals once and retries; a crash after the engine served
  `initialize` (signalled by the `.engine-ready` marker) exits cleanly so the client reconnects
  with a fresh handshake. Logs: `<KG_DATA>/server.log`.
- **CI/structural gates**: `scripts/validate_plugin.py` (stdlib-only: manifest JSON validity,
  4-file version agreement across plugin.json/marketplace/pyproject/`kg_engine.__version__`,
  every declared component file exists); `scripts/check_donors_clean.py` (invariant I11, installed
  as the pre-commit hook: each donor checkout exists and its pinned Stage-0 commit is still
  **reachable** from that donor's `HEAD` — see §11).
- **Version sites**: the version is declared in five places, and `tests/test_version_consistency.py`
  asserts they agree — including `kg_engine.divergence.__version__`, which sits outside
  `validate_plugin.py`'s four-file check. It parses the sites independently of
  `scripts/bump_version.py` (a guard sharing a parser with the tool it guards only proves the parser
  is self-consistent). `bump_version.py` rewrites all five at once, refuses to bump from an
  inconsistent state, and is a dry run unless `--write`.
- **Dependency pins**: `mcp>=1.2,<2` is **load-bearing**, not conservatism. mcp 2.0.0 removed
  `mcp.server.fastmcp` and the `FastMCP` class outright (the server API moved to
  `mcp.server.mcpserver`), so a bump past the cap raises `ModuleNotFoundError` at startup and every
  `kg_*` tool disappears for the session. Adopting 2.x needs a real port of the tool surface and
  `readiness_lifespan`, not a version edit. `tests/test_review_r12.py` pins the import path with a
  hard assertion rather than `importorskip`, which would have *skipped* on exactly the bump that
  breaks production, and `.github/dependabot.yml` ignores mcp **major** updates only — 1.x
  minor/patch releases, security fixes included, must keep flowing.

### Environment contract

| Variable | Meaning |
|---|---|
| `KG_PROJECT_DIR` | Project dir (canon, audit ledger, reconcile state, `.kg/diverge` live here); falls back to `CLAUDE_PROJECT_DIR` |
| `KG_DATA` | Engine data dir (derived layer, `server.log`, model cache); falls back to `CLAUDE_PLUGIN_DATA`, else `<project>/.kg-data` |
| `KG_PACK_PATH` | Domain pack path; else `<plugin>/pack/pack.yaml`, else `<project>/pack/pack.yaml` |
| `KG_SOURCE_PATH` | The source document (file, dir, or glob of `.md`/`.txt`); set from the required `source_path` userConfig |
| `KG_ENGINE_VENV` | Explicit venv override |
| `KG_MAX_EDGES_PER_KB` | Write flood-cap rate (default 20/KB, floor 64) |
| `KG_HANDLER_TIMEOUT` | Watchdog for a wedged tool handler (unset/0 disables) |
| `KG_DIVERGE_EMBEDDER` / `KG_DIVERGE_HOME` / `KG_DIVERGE_DEBUG` | Divergence embedder provider / state-dir override / tracebacks |
| `KG_LIGHTRAG` (+ `KG_LIGHTRAG_QUERY_MODE`, `OPENAI_API_KEY`) | Opt-in LightRAG experiment arm |
| `KG_BACKEND_MODEL` / `KG_BACKEND_MAX_TOKENS` | Headless backend knobs |
| `CLAUDE_PLUGIN_OPTION_*` | userConfig reads: `SOURCE_PATH`, `SENSITIVITY` (default `medium`), `METRICS_MODE` (default `structure_only`), `EXTRACT_WAVE_SIZE` (default 6) |

All env reads pass through one cleaner that drops empty values, unsubstituted `${…}` placeholders,
and bare `/.venv` sentinels.

### On-disk map

```text
<project>/                      the user's project
  canon/<id>.md                 source of truth (git-tracked, kgcanon merge driver)
  .kg-session-lock(.q/)         single-writer lease + its FIFO waiter queue (gitignored)
  .kg-ground-audit.jsonl(.ckpt) verdict audit ledger (gitignored engine state)
  .kg-reconcile-state.json      reconciler cache (gitignored)
  .kg/diverge/<brief>/          divergence state (durable memory + ephemeral session/)
  .kg/constructions/<slug>/     /kg-perturb second construction (alt canon/ + derived/; ephemeral)
<data dir>/                     $KG_DATA (or <project>/.kg-data)
  derived/                      graph.json, index.sqlite, generations.json, graph.html, GRAPH_REPORT.md
  .venv/                        provisioned engine venv
  models/                       embedder cache (via HF_HOME)
  server.log                    supervisor + engine log
```

## 10. Measurement (never gates)

Every metric measures; none gates the pipeline — verdicts run on their own advisory thresholds.

- `python -m kg_engine.harness agreement` — nominal Krippendorff's α across independent coders;
  reliable at **α ≥ 0.67**, below that the grounding signal stays advisory.
- `python -m kg_engine.harness specificity` — the bridge-metric gate: specificity-weighted
  betweenness earns `gate_on=true` only when the generality confound is detected (raw-betweenness
  leaders vaguer than average), leaderboard rank-churn > 0.2, and specificities actually spread.
  Until then plain degree is the honest advisory.
- `python -m kg_engine.harness ideation` — scores pooled outputs per experiment arm (control /
  graph / graph+generate / graph+generate+dpp / rag / lightrag) on diversity, novelty, utility,
  unsupported rate; a win requires no regression (0.05 slack on the hallucination guard) plus a
  strict gain on diversity or novelty.
- `python -m kg_engine.harness convergence` — promotes the mechanism-convergence tally from
  advisory to queue-reordering only if edges proposed by ≥2 mechanisms ground at a rate more than
  0.10 above single-mechanism edges (with enough samples per band).
- `scripts/f4_probe.py` — extraction-precision probe: sample edges, hand-label
  `correct | fabricated | vague | wrong_type` + `span_found`, score against the advisory
  **0.70 precision gate**; also reports the astrology rate (fabricated+vague) and confidence
  calibration.
- `python -m kg_engine.divergence selftest` — the divergence engine's offline correctness
  contract (variety gate, DPP-beats-first-N, null no-regression, collapse reversal; gate details
  in `skills/burgess/references/tools.md` §2.4).

## 11. The invariants

The eleven fusion invariants, all test-enforced (`tests/fusion/`):

- **I1 — verdict monopoly**: only `kg_ground` produces verdicts.
- **I2 — span-present boundary**: no span-less grounded edge can exist; forged verdicts are
  stripped at the boundary and re-quarantined by the reconciler.
- **I3 — import firewall** (both directions): no grounding/verdict/reconciler module may import
  `divergence/`, even lazily; and no module under `divergence/` may import anything in `kg_engine`
  beyond its own siblings and the capability-free leaves `atomicio`/`envconfig`. It therefore cannot
  name an `EpistemicState`, let alone set one — which is what makes I1 structurally true from the
  geometry side rather than merely unexercised.
- **I4 — DB isolation**: no vector schema anywhere the graph query tools read.
- **I5 — advisory ceiling**: geometry affects what is proposed and in what order, never what is
  true; grounding output is snapshot-tested bit-identical with `divergence.dpp` on vs off.
- **I6 — bounded judge**: fitness clipped to [0.7, 1.3] at weight 0.3 — it can nudge ordering,
  never veto diversity.
- **I7 — different-family judge**: the diversity embedder never shares lineage with the generator.
- **I8 — unified negative memory**: human discards and grounding failures live in one store;
  neither generation path re-proposes from it.
- **I9 — graceful degradation**: every `kg_*` graph tool works with divergence deps blocked.
- **I10 — session-ephemeral archives**: geometry dies with the session; only pins, discards,
  comparisons and session metadata persist.
- **I11 — donors untouched**: the fusion never wrote to a donor. `scripts/check_donors_clean.py`
  asserts what preserves that historical fact — each pinned Stage-0 commit still **exists and is
  reachable from its donor's `HEAD`**, so the copied-from tree stays recoverable with
  `git show <sha>` and every `ATTRIBUTION.md` claim stays checkable. A frozen `HEAD` and a clean
  donor working tree are deliberately *not* asserted: they were a proxy that held only while both
  donors stayed retired, and Cambrian has since been republished and resumed development. An
  **unreachable** pin is still a hard failure — that is where provenance is genuinely lost.

The historical decision record (how these were chosen, the blind-experiment rule D1, per-file
attribution) lives in `docs/fusion/` — that directory documents the project's history and is the
one place donor references belong.

## 12. Tests

- `tests/` — the convergence suite; files named `test_fix_*`, `test_rfix_*`, `test_review_*` pin
  regressions from past reviews and stay green.
- `tests/fusion/` — the eleven invariants above, including adversarial forge attempts and the
  bit-identical grounding snapshot.
- `tests/fusion/divergence/` — the divergence engine suite (including the selftest e2e, marker
  `selftest`).
- `tests/conftest.py` — a git-backed temp canon (`vault`), a configured `engine` (KGEngine), and
  the real `pack`.

Run: `uv run pytest tests/` (no network needed; the README carries the generated count).
