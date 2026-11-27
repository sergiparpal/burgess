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
   (47 tools, namespaced `mcp__plugin_burgess_burgess__*`). `server.py` (the `KGEngine` facade +
   FastMCP tool surface) is the trust boundary. The engine is **never installed**: it resolves via
   `PYTHONPATH=<plugin>/scripts` (see `.mcp.json`), so engine edits need no rebuild; the
   provisioned venv holds only dependencies.
2. **Language layer** — 10 slash commands (`commands/kg-*.md`), 8 subagents (`agents/`), the
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
| `evidence.py` | Sources and levels (0.21.0, 0.22.0): the level/role/marks vocabulary, the engine's own fetch and fixed HTML→text rule, the `evidence/` registry with its integrity check, the project `Policy` (required level, the notes' levels, building from notes), the `support:` segment, and the level veto on `failed` |
| `scrub.py` | Egress PII/secret scrubbing (§1.9) with consistent placeholders |
| `pack.py` | Domain-pack contract/loader/coverage |
| `boundary.py` | The write boundary: strict payload validation → dispositions (span-present, never-forge-a-verdict, dedup, flood cap) |
| `canon.py` | Canonical layer: human-editable Markdown notes, crash-safe single-writer I/O, git-as-rollback, lease lock |
| `groundaudit.py` | Crash-safe append-only grounding-audit log (the trust root for verdicts) |
| `reconciler.py` | Out-of-band-edit sweep: mtime/size pre-filter + full re-hash, forged-verdict re-quarantine |
| `canonmerge.py` | Semantic git merge driver for canon notes (never forges a verdict) |
| `projector.py` | Derived layer: canon → `graph.json` + `index.sqlite` + Leiden communities (leidenalg, else igraph's own Leiden since 0.19.4, label propagation only without igraph) + precomputed ranks |
| `generate.py` | The seven structural discovery mechanisms + the convergence tally |
| `operations.py` | The four endo operations (collapse/explode/regroup/open), writing via the propose lane |
| `advisory_geometry.py` | Advisory hybrid-descriptor DPP ordering over `kg_generate` candidates (behind `divergence.dpp`, default off) |
| `pathing.py` | The grounded-only path algorithm behind `kg_explain_path` |
| `waves.py` | Deterministic resolver for `/burgess:kg-build`'s extraction wave size |
| `buildplan.py` | `/burgess:kg-build`'s typed arguments and subset, resolved for `kg_build_plan` (no shell step), the canon nodes a section names, for `kg_section`, the digests and ledger lines of the sections an extraction wrote no edge from, and the units of a section and the ledger lines of the text an extraction read (0.26.0) |
| `export.py` (+ `templates/graph_html.py`) | Render `graph.html` + `GRAPH_REPORT.md` from the derived layer |
| `harness.py` | Deterministic measurement: agreement, specificity, ideation, convergence |
| `evalsheet.py` | `/burgess:kg-eval`'s labeling sheet as data (0.28.0): the seeded sample, the fill from an annotator's JSON, the score; `scripts/f4_probe.py` prints it |
| `measure.py` | The steps of `/burgess:kg-eval` and `/burgess:kg-experiment` run in the engine (0.28.0, `kg_eval`, `kg_experiment`): a run's folder under `.kg/`, the copies its agents read, the log entries written from the saved results |
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
- **Derived** = disposable projection at `<data_dir>/derived/{graph.json,index.sqlite}` (data dir: since
  0.23.0 the project's own folder under `$KG_DATA`, `projects/<folder-name>-<hash>/`
  (`envconfig.resolve_project_data_dir`), falling back to `<project>/.kg-data`). It contains nothing the
  canon does not; never hand-edit it — reproject. Through 0.22.4 every project shared `$KG_DATA/derived/`, so
  opening another project rebuilt the index and the `/burgess:kg-generate` ledger kept whichever project ran
  last; the first start of 0.23.0 copies over, file by file, what that shared folder held for the project
  (`server.adopt_shared_derived`: the index when it was built from this canon, the ledger when it tracks this
  canon's nodes) and leaves the shared folder as it was.
- **Notes per project** (0.23.0): the plugin's `source_path` is one value for every project, because Claude
  Code keeps plugin options per user and ignores a project's settings for them. A project names its own notes
  in its policy (`evidence.Policy.notes_path`, `/burgess:kg-sources policy notes_path=…`), a path inside the
  project only, so a cloned repository cannot point the engine at files outside itself; `none` gives it no
  notes. `_SourceResolver.notes_path()` is the one place the engine, the hook and `kg_engine.paths` (the
  command-text helper) read it.

Frontmatter key order is fixed (load-bearing for byte-identical canon): `id`, `label`,
`node_type`, `file_type`, the three axes, `created_at`/`updated_at`, `edges:`. Edge ids are
deterministic — `e_{slug(source)}__{slug(relation)}__{slug(target)}` — always recomputed, never
trusted from disk. An edge's `source` and `target` are node ids: the write boundary stores them as
the slugs its node ids and edge ids already use, so an endpoint an extractor wrote as a label
(`Meta RADAR`) lands as `meta-radar`. The projection resolves the label-form endpoints an older
canon or a hand edit still holds (§3.5). Node timestamps are excluded from the content hash so metadata churn doesn't
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
generators (`generate._live_undirected`), answer a query (`kg_context`'s answer lane), count as a
live relation in `kg_agenda`'s detectors and its edgeless-communities crossing test, or make a node a
hub for the adversarial grounder (`kg_ground_plan`, 0.8.0; 0.7.0 counted every edge there, so a node
whose claims had all been rejected could still be attacked as a hub). A surface left
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
  chars), `empty-source`/`empty-relation`/`empty-target`, `self-loop` (both endpoints slug to one
  node, 0.5.2), `write-lane-hypothesis` (`kg_write` only, 0.5.1), `rate-limited-flood` (per-payload
  budget `max(64, kb·20)`), `truncated-payload` (`complete=false`), `schema-invalid`.

Only `truncated-payload` and `schema-invalid` are `retryable=true` (transport); everything else is
semantic — fix the item, don't resend it. Every **non-deterministic edge must carry a verbatim
source span** (normalized substring check: whitespace collapsed, case-folded, curly quotes/dashes
folded). The full contract, reason strings and worked examples:
`skills/burgess/references/contract.md`.

Nodes carry no `collapses-into-*` quarantine — a re-emitted node id is deduped and ACCEPTED. But a
node already holding a verdict (`grounded`/`rejected`/`failed`/`obsolete`) keeps its **body** across
that merge: a `Node` has no `span` or `notes` field, so `kg_ground` restates a promoted node's support
*in the body* (`grounding span: …` and the file that holds it, `grounding source: …`, or
`citation: …`), and since 0.16.1 the verdict's note too (`verdict (<state>): …`). An incoming body
would otherwise blank the very evidence the verdict rests on (`canon._merge_into_existing`). Label and
`node_type` still update. To revise a grounded node's prose, edit the canon note.

`kg_propose(payload)` is the **hypothesized write lane**: it forces `provenance=hypothesized`,
refuses text claims (`propose-lane-text-claim`), requires no span, and preserves
`authored_by=deterministic` for genuine discovery mechanisms. Same validator, same forge guards.
The refusal runs both ways: `kg_write` REJECTS an item claiming `provenance=hypothesized`
(`write-lane-hypothesis`, 0.5.1), because the validator keeps such an item without its span and
checks nothing. Every edge `kg_write` accepts is therefore span-verified; `kg_propose` reaches
the shared validator through kg_write's internal `lane="proposal"`.
The `kg_operate` mechanisms are those discovery mechanisms and they do claim it: their structural edges
carry `authored_by=deterministic`, while a node whose `label`/`body` came from the caller stays `agent` —
structure is computed, language is authored.

An optional `idempotency_key` makes a re-sent identical write a true no-op (verbatim cached replay);
`kg_write` also reuses a signature-keyed canon baseline across calls so parallel build waves don't
re-parse the whole canon per write.

### 3.4 Verdict monopoly

Only `kg_ground(target_id, verdict, kind, note, support_span, support_note, lead, refuted_by)` sets epistemic
states. `verdict ∈ {grounded, rejected, failed, obsolete}`. Promoting a `hypothesized` item to
`grounded` **requires support**, which upgrades provenance: `support_span` (verbatim, span-verified)
→ `span-present`, or `support_note` (external citation) → `inferred`; neither →
`hypothesis-needs-support`. A proposal into a node that is rejected, failed or obsolete is not promoted
(`hypothesis-into-non-live-node`, 0.17.1): the node's verdict settles its star. A support span also
records the file it is in (0.16.1): an edge that names no declared source takes the first file that
holds the span as its `source_file`, and a node gets a `grounding source:` paragraph. A verdict's
`note` goes to an edge's `notes`, or to a node's body as `verdict (<state>): …` (0.16.1; through
0.16.0 a node's note was dropped). A `rejected` edge may carry a `lead` (0.9.0): the edge its span
does state instead, checked against the pack and appended to the notes as `lead: <head> <relation> <tail>`. It sets
no state: `/burgess:kg-build --leads` has an extractor write it as an ordinary `unverified` claim, whose notes open
with `lead (from <rejected-edge-id>)`, and the next `/burgess:kg-ground` judges it. A lead belongs to the rejection
that recorded it (0.11.1): a verdict that changes the edge's state and records no lead of its own appends
`lead: none`, which withdraws it, so a lead whose rejection was overturned is never offered again. Every legitimate transition appends one record to the append-only audit
ledger `<project>/.kg-ground-audit.jsonl` (with a `.ckpt` sidecar for O(1) recovery).

**A claim whose passage left its file (0.27.0, `KGEngine._span_gone`).** An edge with a span of its own whose file
is among the sources but no longer holds that span (a sentence deleted or rewritten) is judged again on the text
as it reads now, and takes one of two verdicts. `grounded` with a `support_span`, the passage that states it now,
which must lie in a file the graph is built from (`_reanchor`): its `span` and `source_file` move there, the old
span stays in its notes as a `span was:` segment, and a grounded claim keeps its `verdict_at`. Or `obsolete`,
superseded, which leaves live topology without becoming negative memory. A live claim whose passage is gone is
never rejected (`span-gone-not-rejected`), since a rejection would bar it for good if the sentence came back;
`obsolete` is refused on a claim whose span still verifies, on one with no span of its own, and on a rejected or
failed claim. A claim whose file is not among the sources (`_own_file`: moved, renamed, another notes folder) takes
no verdict but `failed`. A re-anchor is the only way a judged claim's span moves: a `kg_write` re-emit of it is
quarantined (`collapses-into-known-verdict`, §3.3), and the reconciler polices states, not spans. The grounder's
view ranks the claim's file by the claim's own words, which a sentence rewritten in other words may not use, so it
also shows the paragraphs of the claim's file written or rewritten since it was last judged (`new_text`, 0.28.3,
`_new_text_view`), read from the ledger of sections read (§3.4) whatever their words: a unit no read record holds,
in a section a build has read, or one an extraction first read after the claim's last verdict. Before `obsolete` the
grounder also asks once with words of its own (`terms`, ranked over that file whatever its level), and `kg_ground`
refuses `obsolete` with `terms-not-asked` until it has (0.28.3, `_obsolete_terms_not_asked`). A move found that way
is held for a second grounder, as support found after any request is (below).

**External sources (0.21.0, `evidence.py`).** Through 0.20.2 every verdict was judged against the configured
sources, the user's own notes, so `grounded` meant "my notes say it", and the only outside support was a
`support_note` the engine could not check. `kg_source_add` registers an outside text: the engine fetches the
bytes itself (stdlib urllib, a generic User-Agent; never WebFetch, whose answer is a model's paraphrase of the
page) or reads a local `.md`/`.txt`/`.html` file, extracts the text by a fixed stdlib rule (since 0.23.1 only a
page's `<main>`, without sidebars, recommendation lists or sharing blocks, and a bot check is refused as
`fetch-blocked`), and writes the copy
`ext-<slug>-<hash>.md`, a record `<stem>.source.json` and the raw bytes under `raw/` into
`<project>/evidence/`. PDF is refused, as for the configured sources. The record carries a **level** (1 reviewed,
2 institutional, 3 editorial, 4 author or community, 5 unfiltered), a **role** (primary, secondary, tertiary),
**marks** (interest, corrected, retracted, superseded), the certified `retrieved_at`, the claimed `published`, the
`authors` the page declares (0.25.1: every `citation_author`, else Dublin Core's creators, else `author`; at most
20, with `authors_total`), and
the sha256 of the copy: a copy whose bytes no longer match is left out and reported, so a hand edit never
becomes a span the engine vouches for. The design razor carries over: **the level measures the filter a text
passed, never the truth of a claim**. The grounder still judges only whether a passage states a claim, and the
level bounds what may be used: support must lie in a configured source or a usable copy (level 1–4, neither
retracted nor superseded; `support-not-usable` otherwise); a `failed` names in `refuted_by` the counter-edge
whose span refutes the claim (required once any source is registered) and the level vetoes it, never decides
it (`evidence.failed_veto`): an unusable source refutes nothing, the configured sources and an external copy
never fail each other (the clash stays a visible dispute), and a lower level never fails a higher one. A
`support_note` is recorded as `citation (unchecked): …`. The copies are verification-only: `SourceSet(extra=…)`
appends them for span checks, the R3 staleness scan, `kg_ground_item`'s evidence and the source digests (so a
registered source the policy accepts wakes the pins waiting for one), while `concat`, which feeds extraction planning, coverage and
the specificity corpus, stays the configured sources alone. The directory is durable user data, not engine
state.

**Every source has a level (0.22.0).** Through 0.21.0 the configured sources sat outside the scale, so notes of
unknown level verified an idea as a reviewed paper did and could not be failed by it, and a graph could not be
built from level-1 sources. The project's `Policy` (`evidence/policy.json`, `kg_source_policy`) now gives each
configured file a level (`notes_level`, 4 unless set per file with `kg_source_set`), sets `required_level`, the
worst level that may still support or refute (4 by default; 1 = only peer-reviewed), and `build_from_notes`. A
registered copy with `build` is content like a note: `SourceSet(content=…)` puts it in `concat`, and
`_SourceResolver.resolve()` / `verify()` build the content set (what extraction reads) and the verification set
(the content, then the evidence-only files, the notes among them when they are not built) from the policy and the
registry. The veto is one rule for every source (a lower level never fails a higher one), so a reviewed paper may
fail a claim only the notes support. A claim whose best support is not usable can be grounded on another
passage (`support_span` on a span-present edge, recorded as a `support: {json}` segment, so the claim keeps the
span it was extracted from), or left unverified and recorded with `kg_record_unsupported`, never rejected for its
level: a rejection is negative memory, and "not at this level" is not "not supported". `kg_ground_item` labels
every passage with its source and adds `support_context`, the usable sections sharing the claim's words. A
non-default policy joins the source signature; verdicts already given keep their state, and `kg_source_list`
names those whose support is no longer usable. Since 0.22.1 a waiting item wakes only when a file usable now was
not usable when it was recorded (the record keeps the usable files' sha256), and when no source at all is usable
`kg_ground_plan` leaves the hypotheses and the hub attacks out as `blocked`, keeping the extracted claims. Since
0.22.3 a re-examination flag records the changed files that raised it (`files`), and `kg_context` holds back a flag
while every one of them is unusable: the projector keeps the flags, and the facade, which knows the policy, passes
the usable files to the reader. Since 0.22.4 a flag is answered by the item's next verdict, whatever it is: the flag
stores the grounding audit log's size when it was raised (`audit_mark`), and a record for the item beyond it drops
the flag at the next projection. `kg_ground_plan` queues the open flags on rejected items for grounders, marked
`reexamine`, and `kg_ground_item` gives each the sections of the files that raised it. A node or span-less edge is
flagged only where a paragraph of the changed text shares `projector.BEARING_WORDS` (3, since 0.24.5; 2 from 0.22.4)
of the words of what it claims (`Projector._bearing_files`, `groundplan.rank_units`: the rule its grounder's context
is ranked by), so a flag stands only where its grounder will be shown such a passage. The same bar wakes an item
waiting for a source (`KGEngine.WAKE_WORDS`), and both count words, not spellings (`groundplan.word_groups`).

**Finding sources (0.24.0).** `/burgess:kg-sources find` suggests outside sources for the items waiting for one,
the claims a grounder recorded as unsupported (`kg_record_unsupported`). `kg_source_find` lists them with what
they claim, their words, what their grounder looked for, and the searches already logged. `kg-scout` subagents
(language layer) write the queries, for and against, and search two places: OpenAlex, the scholarly catalogue,
through the engine (`kg_source_search`, `evidence.openalex_search`: one GET with the query, no key, no contact
address, a query the §1.9 scrub would change refused before anything leaves), and the web (WebSearch). The
engine reads each candidate page itself (`kg_source_probe`: fetch, bot check, the paragraphs that share the most
of the search words, verbatim), so a scout never quotes a WebFetch paraphrase. Who wrote a work comes from the
engine too (0.25.1): a probe gives the authors the page declares and a catalogue result its first three, and a
scout names authors from those only, never from memory. Every search, read and proposal
goes to the search ledger beside the canon (`.kg-source-searches.jsonl`; the scouts log their web searches with
`kg_source_record_search`). The user picks; each pick goes through `kg_source_add`, which records the items the
page was found for (`found_for`, from `for_items` and from the ledger by URL, DOI or title). A level stays a
proposal (`evidence.level_hint` from the catalogue's venue and type) and a stance the scout's reading of one
passage: verdicts come only from `/burgess:kg-ground`. The same release narrows the wake rule: a usable file a
waiting item was not judged against wakes it only when the file was found for it or bears on it
(`KGEngine._new_source_wakes`, the paragraph rule above, with three shared words since 0.24.4), where through
0.23.1 any such file woke every waiting item.

**Ideas attacked (0.25.0).** `/burgess:kg-sources find` searches for and against, and its scouts record each proposal's stance. A source a proposal says `refutes` an idea, or one registered `against_items`, is recorded in `found_against` (`KGEngine._found_items`) and does not wake the idea to be grounded. `kg_ground_plan` lists the live `[diverge]` pins with such a usable source and no attack since in `pin_attacks` (`_pin_attacks`). Stage 2 gives them to the adversarial grounder, which judges them on `kg_ground_item`'s `against_context`.

The adversarial contract says what refutes an idea: its own mechanism failing for its purpose, or the contrary of it. A limit or a refuted neighbour is recorded with `kg_record_attack`. A refutation writes the counter-edge and `kg_ground(failed, refuted_by)` on the pin, which the engine always holds (`_hold_refutation`). A second grounder confirms it from the plan's `confirm` batch: a `failed` is permanent, so the attacker alone never decides it. A pin is never a hub, so through 0.24.7 no idea was ever attacked.

**A grounding judged again (0.24.7).** A node a promotion grounded (`KGEngine._promoted`: a `grounding span:` paragraph or an unchecked citation in its body) can be judged again on request: `/burgess:kg-ground --reexamine <its id>` queues it (only with a focus), and its grounder gets `grounded_on`, the passage it rests on. The grounder contract says what grounds a node: its mechanism and what makes it this claim, never a neighbouring one (the mechanism for another purpose, a narrower version, one ingredient). A `[diverge]` pin found to rest on a neighbouring claim has its support withdrawn (`kg_ground(verdict="unverified")`, `_withdraw_support`): it goes back to unverified and hypothesized, audited, recorded unsupported, with its old support kept in the body as a `verdict (unverified): support withdrawn` paragraph. It is the one tool path that writes `unverified`, and only from `grounded`, so the reconciler's guard against erasing a failure (`_restore_erased_negative`) is untouched.

**Passages across languages (0.24.6).** Every excerpt `kg_ground_item` hands a grounder is chosen by the item's own
words, so a source in another language matches it only through words both languages spell alike. Two views bridge
that, and the language work stays in the language layer:
- `search_context`: a source found for the item, ranked by the words its scout searched with. They were chosen
  before any passage was judged, by someone who does not judge.
- `requested_context`: one request per item (`terms`, at most 8 words in the source's language), recorded in
  `.kg-ground-requests.jsonl`. Since 0.28.2 it is due before an item a usable source was found for is recorded
  unsupported: `kg_record_unsupported` answers `terms-not-asked` until one is on record against the sources as
  they are (`KGEngine._terms_not_asked`), except for an item with a held verdict open. Left to the grounder, the
  request was never made in a run built for it.

The ranking stays the engine's and deterministic; only the words come from a model. The new risk is a search run
until something fits, which the verbatim-span check does not catch. So a grounded verdict with support given after a
request is held (`KGEngine._hold_or_confirm`). `kg_ground_plan` queues the item last, marked `confirm`, in a batch
of its own. The second grounder sees only the held passage and its section, and cannot search. A hold is answered
by the item's next verdict or an unsupported record past its byte marks (`_open_holds`). The engine cannot tell
grounders apart; `/burgess:kg-ground` gives each held item to a new launch. Embeddings were considered and left
out: they would bring geometry into the evidence a verdict rests on, which the design razor keeps them out of.

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
source-payload hash so they refresh whenever the source set moves — neither ever mutates a verdict
(re-grounding stays a `kg_ground` decision); since 0.22.4 `kg_ground_plan` reads the second to queue its
rejected items for a second look:
- **R3 stale verdicts** (`stale_verdicts`) — a `grounded`/`failed` **span-present** edge whose stored
  span no longer verifies against its source file (the evidence *shrank*). Since 0.27.0 `kg_ground_plan` does
  not read this list: it finds the live claims whose passage left their file itself (`span_gone`, §3.4), with
  spans of any non-hypothesized provenance, and the obsolete ones that come back.
- **R3-mirror re-examinable verdicts** (`reexaminable_verdicts`) — a `failed`/`rejected` item (nodes and
  **span-less** items included) that was judged against a source set which has since **grown or changed**
  (non-monotonic evidence), filtered to items whose text overlaps the changed source (`source_file_sigs`
  tracks the per-file baseline). Since 0.14.4 an edge that quotes a span from a configured file is flagged
  only when that file changes (`span-file-changed-since-judged`): it was judged on its own span. Nodes and
  span-less items keep the source-set rule (`source-set-changed-since-judged`), since 0.22.4 by paragraph: a
  paragraph of a changed file must share three of the words of what the item claims (two through 0.24.4), never its verdict notes. Self-clearing on the item's
  next verdict, whatever it is (0.22.4: a record in the grounding audit log beyond the flag's `audit_mark`;
  through 0.22.3 only when the item left the negative states); surfaced in `kg_context.advisory` and the
  `GRAPH_REPORT`, and queued for grounders by `kg_ground_plan`. The divergence side mirrors it: `failed`-fated brief discards are surfaced as
  `reexaminable_discards` on a source change with an explicit un-seal lever (never auto-un-sealed).

Staleness (`is_stale()`) is content-driven, independent of git state: a cheap canon-dir
`(count, newest-mtime)` pre-gate, then an authoritative per-file content-hash comparison that is
stat-gated (only files whose size/mtime moved are re-parsed). A schema-outdated db (missing the
generative-rank or `owner` columns) heals via full rebuild, and so does one built under other
`PROJECTION_RULES` (a value recorded in its meta, bumped when a change to how rows are derived must
reach every index). That second trigger exists because a stat-unchanged note is rebuilt from its
index rows rather than re-read, so without it an upgrade would never reach those rows. The rules
currently include endpoint resolution: an edge endpoint that is not a node id but whose slug is one
names that node, never a phantom node of its own. Reads call `_ensure_projected()`
first; a reprojection failure degrades gracefully (`projection_degraded` flag, empty-schema
fallback) — writes never pass through that seam.

**Searching the index (0.11.5).** `kg_context(query=…)` and `query_graph(text=…)` match **search words**,
not substrings. A search word is a content word as `/burgess:kg-build` counts them (`buildplan._words`: casefolded,
accents dropped, the Spanish and English function words gone, at least three characters unless a number),
plus a two-character letter-digit code such as `N4`. Only the first 12 count (`_QUERY_TERM_CAP`, which bounds
the per-row work), and `query_terms` shows which. A word matches across a plural ending
(`buildplan._forms`). An edge offers the words of its span, its relation and both endpoints' ids and labels;
a node offers its id and label. Matches rank by the summed rarity weight of the shared words,
log(1 + N/df) over the rows searched, then by how many are shared, then in the surface's order without a
query (`kg_context`: grounded first, provenance, confidence, id; the grounded-before-unverified split stays
ahead of relevance). The rarity weight is the IDF `related_nodes` already ranks names by, so a common word
that no function-word list knows still counts for little. The search reads every row of a lane once: about
5 ms on the 221-edge field canon and about 100 ms on 10 000 edges, well inside the hook's 5 s cap. A span is
split into words only when some form of a term occurs in it as a substring, which loses no match because a
word's forms are its prefixes. `kg_context` reports `items_total`/`hypotheses_total` (every edge that
qualified, so a reader sees what the budget left out) and `query_terms`; `query_graph(text=…)` reports
`query_terms` and `matched`. Through 0.11.4 the query was a substring `LIKE` over ids, relation and span,
ranked by confidence and id. On the field canon «¿En qué condiciones se puede retirar la revisión humana del
código?» matched 61 edges, 37 of them through «del», and the edge the question was about came 24th of the 61
behind a budget that held 18.

### 3.6 Egress scrub (§1.9)

`kg_scrub` redacts **secrets always** (private keys, cloud/API tokens, JWT/Bearer, keyword=value,
high-entropy fallbacks) plus **PII per sensitivity** (`low` = secrets only; `medium` adds
EMAIL/PHONE/SSN/CC/IP/CREDURL; `high` adds PERSON/ADDRESS) with **consistent placeholders**
(`⟦CATEGORY:N⟧`) so relational structure survives — one placeholder namespace across the whole
session. `kg_write` **restores** placeholders to the original text before span verification and
persisting: the scrub protects egress; the canon stores the original. `redactions` counts the
distinct redacted values the returned text holds, including values an earlier call already minted,
so it is 0 exactly when `scrubbed` equals the input; an identity entry (a literal `⟦CAT:N⟧` already in
the prose) is not a redaction. The high-entropy fallbacks over-redact on purpose: a URL path segment
such as `practical_mutation_testing_tse_2021` can come back as a `SECRET`, which costs nothing because
`kg_write` restores it, while a URL can carry a real token.

Under `/burgess:kg-build` the egress point is `kg_section` (0.5.0): it serves each extractor its one section
through the same session scrub, so no section text reaches the orchestrator at all. Through 0.4.6 the
orchestrator read the whole document to copy sections out of it, which sent the unscrubbed text to
the model before any scrub ran. The session scrub is serialized by a lock, so a wave of extractors
asking at once keeps one placeholder per value.

## 4. The generative layer

`kg_generate` runs seven deterministic structural mechanisms over the derived graph (default set:
`bridge`, `seed`, `compression`; `all` adds the rest):

1. **bridge** — connect strong-but-separate hubs across communities. A pair ranks on the sum of its
   endpoints' strengths: `spec_betweenness` when the gate is on, else `(structural_bridge + 1e-6·degree) ×
   specificity`. The specificity factor arrived in 0.16.0: before it, a graph with no structural bridge was
   ranked by degree alone, against §4. No node takes more than two slots of the slate (`ENDPOINT_CAP`), so
   one hub cannot take them all.
2. **seed** — non-adjacent pairs with a positive common-neighbour residual `c − E[c|d]`
   ("abnormally connectable for their distance").
3. **compression** — a dense community earns a proposed `compression` node (+ `collapses_into`
   edges) only when an MDL screen shows a description-length saving and the cluster isn't vague;
   the label is left blank for the language layer. The candidate carries its `members` and the `id`
   `kg_operate collapse` would give them (`model.compression_id`), so the language layer writes the
   scored star, not a lone node.
4. **regroup** — re-run Leiden at a different resolution; pairs that flip from intra- to
   cross-community are bridges invisible under the prior partition. Ranked on bridge's endpoint
   strengths, with the same two-slot cap.
5. **transplant** — import a hub's dominant relation pattern into the community with the highest
   absorption capacity.
6. **ensemble** — the edges a second construction wrote between two nodes not adjacent in ours (from
   `/burgess:kg-perturb`); degrades to `regroup` without a second graph, and says so. The second construction
   is built **key-free, in-session**: its extractor reads each section with `kg_section(..., construction=<name>,
   source=<second source>)`, which carries the graph's own known nodes so it writes a concept under the graph's
   id, and `kg_write(..., construction=<name>, source=<second source>)` routes the same span-verified boundary
   to a separately-named alternate canon under `<project>/.kg/constructions/<slug>/`;
   `kg_generate(second_construction=<name>)` (or a pre-built `second_graph` path) projects + cross-generates
   against it — no API key, no `backend` extra. Since 0.19.0 a candidate keeps the second construction's
   relation and direction, and its `passage` (the span it was written from, with `in_source`); `kg_propose`
   keeps a passage that verifies against the graph's own sources at the head of the proposal's notes, and
   `kg_ground_item` shows it to the grounder. A passage is context, never a span: only one in the graph's own
   sources can support grounding, so an outside document counts only once it is added to the sources and
   built. A pair whose second-graph edge records no relation is still a plain `bridges`. Since 0.19.1 the
   payload's `ensemble` says how each of the second construction's live edges fared (repeated here, pair
   joined here by another edge, known failure, an end missing here, untyped, new), and
   `/burgess:kg-perturb` checks the primary across the build with `kg_metrics(digest=true)`: counts and a
   sha256 of the canon's notes. Counts alone would miss a misrouted write, because the second reading
   writes the graph's own ids and so rewrites the graph's nodes instead of adding any. The headless
   `backend.py` stays available for out-of-session / CI builds.
7. **periphery** — low-degree sources get a `bridges` edge to their max-connectability anchor —
   the periphery the hub-seeking mechanisms ignore.

An unjudged hypothesized edge is live topology: only `NON_LIVE_STATE_VALUES` are excluded from the ranks.
So a generation run before `/burgess:kg-ground` ranks over the last one's proposals. `kg_generate` counts
them in `unjudged_hypotheses` and says so in `note` (0.16.0). That is a warning, not a gate: the inversion
never gatekeeps generation.

Each candidate carries an advisory `convergence` count — how many distinct mechanisms
independently proposed the same edge, tallied pre-truncation. The two-slot cap is part of
a mechanism's own list, so a pair a mechanism capped out does not count as proposed by it. It is a grounding-queue ranking
prior, never folded into `score`, and only reorders the queue once `harness convergence` shows
clean band separation. Candidates route through `kg_propose`; the four endo operations
(`kg_operate`: collapse/explode/regroup/open) persist through the same lane. `kg_absorption`
scores, per node grounded from a hypothesis, how long it stayed perturbing before the graph
renormalized (`fertile | absorbed | isolated`). Since 0.16.1 it scores only a tracked node the graph
holds as grounded, and counts live edges only. Every other tracked node is listed in `not_scored`
with its state, or `absent`. Since 0.17.0 `kg_record_generation` writes the ledger it reads.

Since 0.17.0 compression offers nothing an earlier generation proposed. It leaves out a community a
live compression node was already proposed over (at least half of the other members already have a
`collapses_into` edge into it, in any state), and a candidate whose id (a function of its members) is
already a node, in any state; `kg_generate` lists both in `compression_skipped`. On the field graph of
2026-11-15 all four compression candidates were of these kinds.

## 5. The MCP tool surface (47 tools)

Full signatures and return shapes: `skills/burgess/references/tools.md`.

- **Read/query (16):** `kg_ping`, `kg_scrub`, `kg_metrics`, `kg_status` (projection-free
  status + section coverage, where a span counts toward the file its edge's `source_file` names, as
  span verification does, and so does each `also stated:` passage an edge written again keeps beside its
  first one (0.23.1), + the engine-resolved `source`), `kg_build_plan` (the `/burgess:kg-build` plan:
  files, sections at each file's heading level, per-section coverage, the sections an extraction
  recorded as holding no edge while their text and the pack's types are unchanged, the sections it leaves
  out (0.23.1: a reference list, a publisher's back matter, an empty section; `--all` plans them), the
  covered sections whose text changed since their extraction (0.26.0: `changed`, any paragraph, list item
  or table row no record of the read-section ledger holds; `--again <file>` marks every covered section
  of the file; a file built before the ledger gets a `baseline`, its current text taken as the text its
  extraction read), the claims whose span the source no longer holds (`spans_gone`), the wave size; it
  reads the typed arguments and the option text it is handed, so the command needs no shell; with
  `--leads`, the sections holding the leads rejected claims carry), `kg_section`
  (one planned section, cut and egress-scrubbed for the extractor that asks for it, with the canon
  nodes the section names, so the extractor can reuse their ids, on request its pending leads
  with their spans, and for a changed section the units no extraction read and the claims already written
  from it; the extraction's `kg_write` then records the read), `kg_ground_plan` (the `/burgess:kg-ground`
  queue, every unverified edge and hypothesized node, as `{id, kind}` items in batches for parallel
  grounders, a queued node in one batch with the queued edges that touch it (0.17.1), plus the wave size and the hubs no adversarial pass has attacked since their last grounded
  claim, read from the `counter-edge (adversarial pass, hub <id>)` mark on each counter-edge and from the
  attack ledger `kg_record_attack` writes, and the count of pending leads; a claim's time is its
  `verdict_at`, when it entered its state, which a re-verdict that keeps the state keeps, 0.10.2; it leaves
  out a `[diverge]` pin recorded unsupported against the current sources and pin, 0.20.1, unless the record
  predates node evidence, 0.20.2; with `reexamine`, it also queues the rejected hypothesized nodes the focus
  names, 0.20.2),
  `kg_ground_item` (one queued item's evidence: the edge, whether its span still verifies, its nodes
  and the excerpt of the source around the span, a long table's rows under its header, so a grounder
  reads no file; for an edge with no span, a proposal, the source sections where both its ends are
  discussed, located by the spans of their live edges, 0.18.0, and for a `/burgess:kg-perturb` proposal the
  passage a second reading wrote it from, with its excerpt, 0.19.0; for a node, the source sections that share
  the most of its words, rare words weighing more, each with an excerpt, since a node has no span to locate
  its text by, 0.20.2), `query_graph` (every filter applies to nodes and edges alike; `text` finds nodes and
  edges by what they say, edgeless nodes included), `get_node`,
  `get_neighbors`,
  `shortest_path` (never routes through a non-live edge — §3.2), `kg_explain_path`
  (grounded-edges-only chain + advisory `leap`; capped at
  `pathing.MAX_EXPLAIN_NODES` distinct nodes — its closure is quadratic in that count, so an uncapped
  model-supplied list would outrun the handler watchdog), `kg_context`
  (budgeted, falsification-aware; grounded `items[]` never mixed with `hypotheses[]`; a query ranks its
  matches by the rarity weight of the words they share, grounded first, and `items_total` says what the
  budget left out — the search is described in §3.5), `kg_agenda`
  (structural suggested questions, `answerable_now` vs `blocked_on_grounding`), `kg_export`
  (offline `graph.html` + `GRAPH_REPORT.md`; the three axes on independent visual channels). Once rendered, a
  view stays current (0.15.0): every projecting read re-renders each view that exists and is older than
  `graph.json` or was rendered by an older engine (0.15.1), unless the projection is degraded. A read never
  creates a view. An `inferred` edge is drawn lighter in any state (0.15.1).
- **Write/ground (10):** `kg_write`, `kg_propose`, `kg_ground` (the verdict monopoly),
  `kg_rename` (strict), `kg_merge` (deliberate merge; negative information sticky), `kg_operate`,
  `kg_record_attack` (0.10.0: an adversarial attack that wrote no counter-edge, with its falsifying
  question, so the plan stops offering that hub; it writes only the attack ledger and sets no state),
  `kg_record_edgeless_section` (0.14.0: a `/burgess:kg-build` section whose extraction wrote no edge, with the
  extractor's note on why, keyed by the digests of the section's text and of the pack's types, so the build
  plan stops offering it while both are unchanged; since 0.14.1 also a section whose every relation is an
  edge the canon already holds with a verdict, and only a section whose current text `kg_section` served
  since the engine started; since 0.26.0 a covered section the plan offered again as `changed` records its
  read in the read-section ledger instead; it writes only those two ledgers and sets no state), `kg_record_generation` (0.17.0: one `/burgess:kg-generate` run, which advances the absorption
  ledger's generation counter and tracks each node the run proposed at its live degree, so the command needs no
  shell; it writes only `derived/generations.json`, refuses a file it cannot read as a ledger, and sets no
  state), `kg_record_unsupported` (0.20.1: a `[diverge]` pin a grounder judged and left `unverified` for want
  of support, with its note, keyed by the signatures of the sources and of the pin, so the ground plan leaves
  it out until either changes or a focus names it; it refuses anything but an unverified `[diverge]`-pinned
  hypothesis, writes only the unsupported-pin ledger and sets no state).
- **Sources (4, 0.21.0 / 0.22.0):** `kg_source_add` (register an outside text: the engine fetches or reads it,
  copies it into `evidence/` with its level, role and marks, and `preview=true` shows what to propose a level
  from without writing; `build` also extracts it), `kg_source_list` (the registry, the notes with their levels,
  the policy, its problems, and what grounded claims rest on: the notes and external sources by level, or
  unchecked citations), `kg_source_set` (change a source's or a note's record, or `build`; a copy is never
  rewritten), `kg_source_policy` (the required level, the notes' default level, whether the notes are built).
  They write only the evidence directory and set no state (§3.4).
- **Finding sources (4, 0.24.0):** `kg_source_find` (the items waiting for a source, read-only),
  `kg_source_search` (OpenAlex searched through the engine, logged), `kg_source_probe` (a candidate page read by
  the engine, verbatim passages, logged), `kg_source_record_search` (a scout's web searches and proposals). They
  write only the source-search ledger and set no state.
- **Generative reads (2):** `kg_generate`, `kg_absorption`.
- **The commands' own steps (3, 0.28.0):** `kg_eval` (a step of `/burgess:kg-eval`: `sample` copies into
  `.kg/eval/<run>/` the documents the edges cite and the plugin's contract, and writes the seeded sheets;
  `score`, `agreement`, `specificity`, `validate_pack`; `log` appends the entry written from the saved results),
  `kg_experiment` (a step of `/burgess:kg-experiment`: `start`, `rag`, `score`, `judge_packets`, `judge_score`,
  `log`) and `kg_perturb_plan` (`/burgess:kg-perturb`'s argument classified and its construction named). Through
  0.27.0 these were Bash blocks that started the plugin's Python from the plugin's folder, which
  `permissions.blockReadsOutsideWorkingDirectories` refuses without a person (§10). They write only under the
  project's `.kg/` and set no state; only the opt-in LightRAG arm keeps a shell step.
- **Divergence surface (8):** `kg_diverge_init`, `kg_diverge_ingest`, `kg_diverge_remember`,
  `kg_diverge_parents`, `kg_diverge_metrics`, `kg_diverge_recall`, `kg_diverge_materialize`,
  `kg_diverge_export` (0.19.6: writes every idea of the brief's current session, with the explanation it
  was ingested with and what the user did with it, to one Markdown file under the brief's state folder;
  it sets no state, and nothing reads the file back).

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
- **Monitor** (`monitor.py`): flags `collapsing` on mean-cosine above the cold-start threshold until
  the baseline fills — per embedder family, `monitor.default_cos_threshold`: 0.55 `hash`, 0.67
  `static`, pinnable as `engine.monitor_cos_threshold` — / entropy 0.50 (≥3 occupied niches) /
  relative baseline+0.15 with ceiling 0.80 (rolling window 5, min baseline 2); `under_generation`
  below 0.6× the per-generation target; the variety-erosion early warning fires at ≥1.5×
  novelty-decay acceleration sustained 2 generations. Under `static` mean cosine tracks idea length
  about as much as sameness, so the similarity signal separates a same-mechanism batch from a
  healthy one only weakly (measured 2026-11-20; see DECISIONS).
- **Memory** (`memory.py`): durable pins/discards/comparisons per brief; informative A-vs-B pair
  selection; diverse-parent selection (pins always in, discards never). Comparisons feed only the
  pair selection (a decided pair is not asked again) and `recall`'s tallies; neither the slate nor
  the parents read them. The pairs come from the slate, but when no chosen pair names an idea of the
  current round, the last one gives way to the most informative undecided pair that does (0.19.7):
  the slate is archive-wide, and in the 2026-11-20 field session it stayed the same for three rounds
  whose questions never reached a new idea. The parents are every pin plus at least
  `MIN_DIVERSE_PARENTS` = 2 elites whatever `k` says, drawn by D² sampling (`diversity.d2_sampling`,
  the k-means++ seeding rule) from a generator keyed by seed and `meta.cycles`, so the same call
  within a round returns the same parents and the next round draws again. The max-min walk it
  replaced is fixed for fixed pins: it bred from the same two outliers round after round.
- **State** (`state.py`): project-local under `.kg/diverge/<brief-slug>/`. `meta.json`,
  `axes.json`, `session.json`, `materialized.json` and `memory/` are durable; the `session/` dir
  (MAP-Elites archive, candidate records, `embeddings.npz`/`mech_embeddings.npz` vector stores,
  the Voronoi partition, and since 0.20.0 the cliché map `cliches.json`) is **session-ephemeral**: a
  new session id wipes it. The knowledge graph,
  not the archive, is the durable store. An export, `ideas-<brief-slug>-<session>.md`, sits beside the
  durable files; nothing in the engine reads it.

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

**Session context.** `kg_diverge_init` returns the resolved `axes` (name, type, range, the open
axis), `unit_of_generation` and `candidates_per_generation` beside the session id and paths, and
`kg_diverge_recall` returns the same context plus `session_id` and `seed` from the engine's state.
The agent writes descriptors from that and resumes after a compaction from `recall`, with no file to
open: a Bash read outside the project prompts the user, and in the 2026-11-19 field run such reads
left a round waiting.

**Export** (`export_ideas.py`, `kg_diverge_export`, 0.19.6). A candidate may carry an `explanation`:
the two or three plain lines, with an example, that the agent shows the user. The record keeps it and a
slate item returns it. It is never embedded, so the same ideas with and without explanations land,
score and slate identically (tested). Each record also notes its `batch` (one non-empty ingest,
numbered like `meta.cycles` after it) and `slated_in`, the batches whose slate showed it. The export
writes every record of the current session with its text, explanation, descriptor, operator and
parents, those batches, and the user's pins, discards, comparisons and materializations. The file goes
under the brief's state folder, one per session, never in the project root: in the field the project
folder is the source folder, and a directory source is every top-level `.md`, so an export there would
come back through `/burgess:kg-build` as a source document. The engine never writes a path the agent
names, because an MCP tool's write passes no permission check. Copying the file elsewhere is a single
command that asks. Near-duplicates the ingest set aside were never recorded, so they are not in it.

**Cliché map** (0.20.0). Before generating, the agent maps the obvious answers to the brief: those it
generates away from (`avoided`, its O_train) and those it sets aside to check the ideas against at the
end (`held_out`, its O_test). It sends the map with the first ingest; the engine numbers it `o1, o2, …`
and keeps it in `session/cliches.json`. Nothing in the geometry reads it: the slate, the parents and the
monitor come out the same with or without it (tested). `recall` returns it, and the export lists it with,
for each held-out cliché, the three ideas nearest to it by cosine in the session's embedding space
(`originality.nearest_ideas`, measurement only — I5). The avoided ones get no distance, since they
steered the generation. Round 1 shows the avoided ones; the held-out ones stay unshown until the end, so
the user's choices cannot steer the ideas away from them.

**Cycle response** (`kg_diverge_ingest`): `slate`, `slate_ids`, `ask_pairs`, `ask_policy`, `monitor`,
`slate_mechanism_novelty`, `open_axis` (+ `surface_mechanism_gap` when the probe is on, + `cliches_stored`
when the call sent a cliché map). `slate_ids`
is the id list of the slate items and honours neither pins nor discards — **not** breeding parents;
it was named `parents` before 0.4.0, which invited exactly that misread. The empty-generation
response carries every key with neutral values, `monitor.variety_erosion` included. A slate item
carries the `explanation` its idea was ingested with, when it has one.

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
write-boundary durability quarantine that backs `/burgess:kg-generate` negative memory). The sync only
reads verdicts; issuing them stays `kg_ground`'s monopoly. Since 0.20.0 the same door carries mapped
clichés, on request (`cliche_ids`), as `cliche-<brief>-<id>` nodes with a `[cliche]` line in the body
instead of the `[diverge] pinned` one. The grounder treats them as ordinary hypotheses: grounded with
support, `rejected` without. The ledger keeps them under `_cliches`, which the fate sync skips, so a
cliché never joins the brief's discards.

**Advisory DPP over `/burgess:kg-generate`** (`advisory_geometry.py`, behind `divergence.dpp`, default
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
Extending it also changes the digest of its types that keys each edgeless-section record, so the next build
plans every section recorded with no edge again: a section that held nothing writable may hold an edge of the
new type. 0.8.0 added `enables` this way, and 0.29.0 the two signed effect relations `increases` and
`decreases`, whose sign is in the name, so the canon format did not change.
`python -m kg_engine.pack validate pack/pack.yaml [source]` checks the contract and, with a
source, coverage in both directions (did the pack capture the source's defined terms; is the
glossary grounded in the source). Schema detail: `skills/burgess/references/pack-schema.md`;
divergence templates ship as pack fragments under `pack/domains/`.

## 8. Language layer

- **Commands** (9): `/burgess:kg-build` (wave-parallel extraction), `/burgess:kg-ground` (the grounding loop),
  `/burgess:kg-generate`, `/burgess:kg-perturb`, `/burgess:kg-query`, `/burgess:kg-eval`, `/burgess:kg-experiment`, `/burgess:kg-view`,
  `/burgess:kg-diverge`. Each reads its arguments from `$ARGUMENTS` (see *Environment contract*).
- **Subagents** (8): `kg-extractor` (one per planned section, whose text it fetches with
  `kg_section`; emits `kg_write` payloads, and records a section it wrote no edge from with
  `kg_record_edgeless_section`),
  `kg-grounder` (verdicts on the merits), `kg-adversarial-grounder` (tries to falsify survivors;
  counter-edges typed `attacked_by`, `confounded_by` or `collapses_into`, plus `failed` verdicts),
  `kg-generator` (phrases structural candidates — language only, never structure),
  `kg-annotator` (label passes for precision/agreement),
  `kg-evaluator` (the blind multi-arm ideation experiment), `kg-judge` (one blind verdict per
  prompt for `/burgess:kg-experiment --judge`), `kg-scout` (0.24.0, `/burgess:kg-sources find`: searches
  OpenAlex through the engine and the web, reads candidates through the engine, proposes, never registers or
  judges).
  - The three measurement subagents (`kg-annotator`, `kg-evaluator` and `kg-judge`) declare
    `omitClaudeMd: true` (0.13.2). Claude Code starts them without the user, project and local
    CLAUDE.md files and without its auto-memory index, which it hands a subagent by default. A session
    that saves a run's results in its memory would otherwise tell the next run's blind agents what the
    last one found. Managed policy files still reach them.
  - The two grounders (`kg-grounder`, `kg-adversarial-grounder`) declare it too (0.13.4), so a verdict
    rests on the source and the contract, never on what a session's memory says about the claim.
  - So does `kg-extractor` (0.14.2). Since 0.14.0 a section its extraction writes nothing from is recorded
    and skipped by later builds, so a note that talks an extractor out of a relation keeps that relation
    out of the graph for good, where no grounder can catch it. The generator still gets the project's
    instructions: what it writes is a hypothesis the grounders filter.
  - So does `kg-scout` (0.24.0): its queries leave the machine, and the user's instructions and memory hold
    names, paths and project names a query must never carry.
- **Skill**: `skills/burgess/SKILL.md` is the operating guide; `references/` holds the
  load-on-demand contracts (write contract, tool shapes, pack schema, divergence operators, judge
  rubric, axis inference).
- **Hook**: `hooks/precontext.mjs` (PreToolUse on Grep/Glob/Read, 8 s cap) pipes the tool payload
  to `precontext.py`, which injects a small grounded-context block (budget 800 tokens, ≤6 grounded
  items, ≤3 advisory bridges, a falsification counter) so the session queries the graph before the
  filesystem. It fails silent on every error path, bails if the derived index doesn't exist,
  declares a 15 s lease TTL (so a SIGKILLed hook can't wedge writers), and size-gates synchronous
  reprojection at 400 notes. Above that it serves the index only while it is fresh, and injects
  nothing while it is stale, until the server's next read reprojects (0.10.1). It also stays silent
  (0.11.9) for the measurement subagents, `kg-evaluator`, `kg-annotator` and (0.13.0) `kg-judge`,
  which must work blind; it recognises them by the `agent_type` Claude Code puts in a subagent's hook
  input. And it stays silent for any Read, Grep or Glob of the project's `.kg/`, where Burgess keeps
  its working files.

## 9. Runtime: provisioning and supervision

- **Provisioning**: the SessionStart hook runs `hooks/provision.mjs` (async, 600 s cap), which
  finds a system Python ≥ 3.10 and hands off to `scripts/bootstrap.py --background --reconcile` — a
  detached worker that builds the engine venv (`uv sync` if available, else stdlib `venv`+`pip`),
  stamp-gated on a hash of `pyproject.toml` + interpreter ABI so it's a no-op when current. The hash
  leaves out `[project]`'s version line (0.11.10), so a release that changes no dependency leaves the
  venv current and the first session after an update starts without a rebuild. Venv
  precedence: `--venv` > `$KG_ENGINE_VENV` > `$CLAUDE_PLUGIN_DATA/.venv` > `<repo>/.venv` (dev).
  On Windows `uv sync` gets `--python` set to the interpreter running bootstrap, unless the user set
  `UV_PYTHON` (0.19.2). A Windows venv's `python.exe` is a copy of its base interpreter's launcher,
  and uv otherwise prefers its own managed CPython, whose launcher is unsigned. Smart App Control
  refused that launcher on the field machine, while one copied from the python.org interpreter
  started. A build that fails leaves `provision.failed` beside the log (JSON `{at, error}`, one line
  naming the step and the cause, and the refused file when Application Control refused it), removed
  by the next provision that ends ready.
  The stamp is written as soon as the core imports verify; the advisory leidenalg/divergence probes
  run after it, so they never hold readiness back. On Windows the worker gets a windowless console
  of its own (`CREATE_NO_WINDOW`, not `DETACHED_PROCESS`): its children (`uv`, the probe
  interpreters) inherit it, so no window opens and their output reaches `provision.log`, which is
  opened for atomic appends (`FILE_APPEND_DATA`) because two workers write it on every cold start.
  `--reconcile` runs the once-per-session canon reconcile after the venv is ready — but only in a
  folder that already holds a project: at least one canon note, or a non-empty audit ledger
  (`bootstrap._holds_project`). The hook fires in every folder a session opens, so an empty
  `canon/` counts as no project, and `Reconciler.scan` itself returns without writing anything
  when there is nothing to reconcile (no note, no audit record, no baseline or ledger).
- **No footprint in unused folders**: Claude Code also starts the MCP server in every folder a
  session opens, so the engine's `Canon` is lazy (`ensure_layout=False`). Building it, and every
  read, leaves the project untouched. The vault's layout (the `canon/` dir and the
  `.git/info/exclude` patterns for the runtime files) is created by the first write, in
  `Canon.acquire_lock`, before the lease file exists, or by a reconcile sweep about to persist,
  which is how a fresh clone (whose exclude file is never cloned) gets its patterns. Pinned by
  `tests/test_fix_session_start.py`.
- **Supervision**: `.mcp.json` starts `scripts/launch_server.mjs`, a Node parent that always
  spawns successfully, then supervises the Python engine: capped exponential backoff (200 ms → 5 s),
  max 5 restarts per 60 s window. A crash during startup heals once and retries; a crash after the
  engine served `initialize` exits cleanly so the client reconnects with a fresh handshake. The engine
  signals that it is serving with a readiness marker. The supervisor names a fresh file in `KG_DATA`
  for each spawn and hands its path over in `KG_READY_MARKER`, so sessions that share
  `CLAUDE_PLUGIN_DATA` never read or remove each other's markers (0.11.2; until then all engines
  shared one). A supervisor removes markers older than an hour as it starts. Logs:
  `<KG_DATA>/server.log`.
- **The connect window**: Claude Code gives a stdio MCP server `MCP_TIMEOUT` ms (30 s by default;
  `.mcp.json` has no per-server startup timeout) to answer `initialize`, then marks it failed for the
  session, never retries it by itself, and kills it; on Windows the processes the launcher started
  directly die with it (job objects). So the launcher never builds
  in its own process: on a cold or stale venv it asks for a background build (`bootstrap.py
  --background`, without `--reconcile`; the worker serializes with the hook's on the provision lock)
  and waits for the stamp only until `MCP_TIMEOUT` minus a 10 s engine-start reserve. Ready by then,
  the engine starts in the same session; otherwise the launcher exits with a message, shown under
  `/mcp`, that names `provision.log` and says to reconnect once the build is done (or to start
  Claude Code with `MCP_TIMEOUT=600000`). The early-failure heal follows the same rule. A stale venv is
  never launched while it is being rebuilt in place. Since 0.19.2 the wait ends as soon as a
  `provision.failed` written after the launcher started appears. The launcher then reports that the
  build failed, with its cause, and says waiting longer will not help. When a build is still running at
  the deadline after an earlier failure, the message says what failed last time instead of calling it
  a first-session setup.
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
| `KG_DATA` | Engine data root (`server.log`, model cache; each project's derived layer in `projects/<name>-<hash>/` since 0.23.0); falls back to `CLAUDE_PLUGIN_DATA`, else `<project>/.kg-data` |
| `KG_PACK_PATH` | Domain pack path; else `<plugin>/pack/pack.yaml`, else `<project>/pack/pack.yaml` |
| `KG_SOURCE_PATH` | The source document (file, dir, or glob of `.md`/`.txt`); set from the required `source_path` userConfig, one value for every project; a project's policy `notes_path` overrides it (0.23.0) |
| `KG_ENGINE_VENV` | Explicit venv override |
| `KG_READY_MARKER` | Set by the supervisor for each engine it spawns: where that engine writes its readiness marker. Not a user setting; an engine started without it writes none |
| `KG_MAX_EDGES_PER_KB` | Write flood-cap rate (default 20/KB, floor 64) |
| `KG_HANDLER_TIMEOUT` | Watchdog for a wedged tool handler (unset/0 disables) |
| `KG_DIVERGE_EMBEDDER` / `KG_DIVERGE_HOME` / `KG_DIVERGE_DEBUG` | Divergence embedder provider / state-dir override / tracebacks |
| `KG_LIGHTRAG` (+ `KG_LIGHTRAG_QUERY_MODE`, `OPENAI_API_KEY`) | Opt-in LightRAG experiment arm |
| `KG_BACKEND_MODEL` / `KG_BACKEND_MAX_TOKENS` | Headless backend knobs |
| `CLAUDE_PLUGIN_OPTION_*` | userConfig reads: `SOURCE_PATH`, `SENSITIVITY` (default `medium`), `METRICS_MODE` (default `structure_only`); `EXTRACT_WAVE_SIZE` (default 6) only through `python -m kg_engine.waves` — `/burgess:kg-build` hands it to `kg_build_plan` from its own text instead |

All env reads pass through one cleaner that drops empty values, unsubstituted `${…}` placeholders,
and bare `/.venv` sentinels.

Claude Code sets the `CLAUDE_PLUGIN_OPTION_*` variables for hooks and MCP servers only. A command's
Bash shell never has them, so `/burgess:kg-build` takes `extract_wave_size` from its own text: Claude Code
fills the `${user_config.…}` placeholder there when the command loads, and leaves it unfilled when
the option is unset. Since 0.5.0 the command passes that text to `kg_build_plan`, so the engine
resolves the wave size without holding a setting for it, and `/burgess:kg-build` runs no shell at all: in
auto mode Claude Code ignores a command's `Bash` permission (and its `Task` one), so a shell step
there goes to the classifier and can stop the build on a prompt, while the MCP tools a command
declares keep their grant. Commands read their arguments from `$ARGUMENTS`, the raw typed text, and never
from the numbered placeholders: Claude Code counts those from 0 (2.1.202 and 2.1.316 alike), and
empties (2.1.202) or leaves unfilled (2.1.316) one with no argument behind it.

### On-disk map

Nothing under `<project>/` below exists until Burgess first writes there (see "No footprint in
unused folders" above). The data dir is created at engine start; it lands inside the project only
in a bare dev launch without `KG_DATA` (`<project>/.kg-data`).

```text
<project>/                      the user's project
  canon/<id>.md                 source of truth (git-tracked, kgcanon merge driver)
  .kg-session-lock(.q/)         single-writer lease + its FIFO waiter queue (gitignored)
  .kg-ground-audit.jsonl(.ckpt) verdict audit ledger (gitignored engine state)
  .kg-reconcile-state.json      reconciler cache (gitignored)
  .kg-hub-attacks.jsonl         attacks that wrote no counter-edge (gitignored engine state, 0.10.0)
  .kg-edgeless-sections.jsonl   build sections an extraction wrote no edge from (gitignored engine state, 0.14.0)
  .kg-read-sections.jsonl       the text each build extraction read, unit by unit (gitignored engine state, 0.26.0)
  .kg-unsupported-pins.jsonl    [diverge] pins judged unsupported (gitignored engine state, 0.20.1)
  .kg-source-searches.jsonl     /burgess:kg-sources find searches, reads, proposals (gitignored engine state, 0.24.0)
  .kg-ground-requests.jsonl     grounders' own passage requests and the verdicts held for confirmation (gitignored engine state, 0.24.6)
  .kg/diverge/<brief>/          divergence state (durable memory + ephemeral session/)
  .kg/constructions/<slug>/     /burgess:kg-perturb second construction (alt canon/ + derived/; ephemeral)
<data dir>/                     $KG_DATA (or <project>/.kg-data, already one per project)
  projects/<name>-<hash>/       one project's own data (0.23.0, envconfig.resolve_project_data_dir)
    derived/                    graph.json, index.sqlite, generations.json, graph.html, GRAPH_REPORT.md
    content/                    kg_engine.paths source: a copy of the files a build reads, when it reads registered sources
  derived/                      the shared derived layer of 0.22.4 and earlier, left as it was
  .venv/                        provisioned engine venv
  models/                       embedder cache (via HF_HOME)
  server.log                    supervisor + engine log, for every project
```

## 10. Measurement (never gates)

Every metric measures; none gates the pipeline — verdicts run on their own advisory thresholds.

Since 0.28.0 the commands run these measurements in the engine, through `kg_eval` and `kg_experiment` (§5): the
same functions, with the same seeds, so a number is the command line's number on the same files. Under the setting
`permissions.blockReadsOutsideWorkingDirectories`, Claude Code asks the person before any Bash command that names
a path outside the project or that its parser cannot analyse, and the auto mode's classifier may not answer for
them; the same setting blocks `Read` and `Grep` outside the project, so a `/burgess:kg-eval` run copies the
documents its annotators read and the contract into its folder under `.kg/eval/`. Only the opt-in LightRAG arm of
`/burgess:kg-experiment` still runs a CLI from the shell. The command lines themselves stay for a development
checkout and CI, run with the engine's own interpreter, which `scripts/engine_python.mjs` prints by the launcher's
own rule
(`_engine_resolve.mjs`: `KG_ENGINE_VENV`, else `<plugin data>/.venv`, else `<plugin root>/.venv`; the
bootstrap pointer, else the platform's conventional path). A source argument may be one file or a folder of
`.md`/`.txt` documents; the CLIs read it as `SourceSet(path).concat`, the projector's own input, so the
specificity gate's IDF corpus is the projector's. In an installed copy (under `plugins/cache`) `/burgess:kg-eval`
below target records the pack/extractor refinements it would make; only a development checkout edits them
and re-extracts (0.11.4).

- `python -m kg_engine.harness agreement` — nominal Krippendorff's α across independent coders;
  reliable at **α ≥ 0.67**, below that the grounding signal stays advisory.
- `python -m kg_engine.harness specificity` — the bridge-metric gate: specificity-weighted
  betweenness earns `gate_on=true` only when the generality confound is detected (raw-betweenness
  leaders vaguer than average), leaderboard rank-churn > 0.2, and specificities actually spread.
  Until then plain degree is the honest advisory.
- `python -m kg_engine.harness ideation` — scores each experiment arm (control / graph /
  graph+generate / graph+generate+dpp / rag / lightrag) and compares the pre-declared pairs prompt by
  prompt (0.12.0, `docs/fusion/EXPERIMENT.md`). Per idea:
  - **grounded novelty**: novelty × support;
  - **support**: the share of a sentence's key-term IDF weight held by the source, terms compared by stem,
    so an invented term costs the most.
  - A pair is won at the one-sided sign test's 5 % level: 10 of 12 prompts, as in D1.
  - The headline is graph vs rag, then graph vs control, graph+generate vs graph, the dpp arm vs
    graph+generate, and graph vs lightrag.
  - An instrument check (rag's support at least 0.10 above control's) gates every such verdict.
  - Diversity and utility are reported outside the verdicts, and `caveats` name what could not be measured.
  - `harness rag-slices` builds the `rag` arm's context deterministically (BM25 over the source's paragraphs),
    so the kg-evaluator needs no shell.
- `python -m kg_engine.harness evaluator-order` (0.13.1) — checks that the kg-evaluator's two drafts show its
  order:
  - the control draft is written before any graph call, and the graph draft before any rag file is read;
  - each draft predates the next file, and the final outputs carry both drafts' answers unchanged.

  The command logs a failure as a caveat; it gates nothing.
- `python -m kg_engine.harness judge-packets` and `judge-aggregate` (0.13.0, `scripts/kg_engine/judge.py`) — the
  deterministic half of the blind judge, run by `/burgess:kg-experiment --judge`:
  - one packet per prompt, holding every arm's idea, a decoy and a positive control, each with its own BM25
    evidence, in a seeded order that rotates per prompt. The label mapping stays in `private/`.
  - Both controls are checked before any judge runs: the decoy must cite something the source lacks, and the
    positive control must carry real facts from two documents.
  - `judge-check` (0.25.2) runs the same rules on the whole source first. Without two documents that each hold
    a figure or name a control can cite, no positive control can pass. The demo is one document, so on it the
    command skips the judge before writing any control.
  - The `kg-judge` verdicts are aggregated with the pilots' rules: V1–V3 first, then the pairs, decided on
    the judges' rankings by the sign test.
  - The judges score grounded and useful, never novelty (`docs/fusion/EXPERIMENT.md`, option D).
- Every harness count and the projector's node specificity read words as runs of Unicode letters
  (0.11.8; through 0.11.7 only ASCII letters, which cut "revisión" to "revisi"). `PROJECTION_RULES` "3"
  rebuilds an index built under the old reading.
- `python -m kg_engine.harness convergence` — promotes the mechanism-convergence tally from
  advisory to queue-reordering only if edges proposed by ≥2 mechanisms ground at a rate more than
  0.10 above single-mechanism edges (with enough samples per band).
- `scripts/f4_probe.py` — extraction-precision probe over `kg_engine.evalsheet` (0.28.0): sample edges, label them
  `correct | fabricated | vague | wrong_type` + `span_found` (the annotator writes its labels as JSON,
  which `fill` writes into the sheet), score against the advisory **0.70 precision gate**; also reports
  the astrology rate (fabricated+vague) and confidence calibration. The sample is the extraction: since
  0.25.2 it leaves out the proposals still in the hypothesized lane, which carry `INFERRED` like an
  extracted edge but are the generator's (`--include-hypothesized` keeps them).
- `python -m kg_engine.harness writers` — splits a labeled sample by who wrote each edge (an extraction,
  a lead pass, an adversarial pass) and by the verdict it holds now. The canon keeps edges from every
  build, so `/burgess:kg-eval` checks a refinement against the current contract before it recommends one.
  `harness legacy-log` notes a pre-0.11.7 `PROGRESS.md` that the source still reads; the measurement log
  now lives in `<project>/.kg/`.
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
