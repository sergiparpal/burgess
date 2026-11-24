# Reference: tools & CLIs

Load on demand. The MCP **tool surface** — the thirty-six graph tools (§1), then the eight divergence-surface
tools (§1B) — then the deterministic **CLI surface**
(`f4_probe.py`, `kg_engine.pack`, `kg_engine.harness`, `kg_engine.divergence`). Every name, signature, and
return shape below
mirrors `scripts/kg_engine/server.py` + `scripts/kg_engine/projector.py` (+ `scripts/kg_engine/divergence/`
for §1B). Nothing here is invented — if a
field is missing, grep the engine source, don't guess. Every tool is also wrapped by a uniform
transport-error envelope: a RAISED internal exception (not a deliberate domain `{ok:false}` disposition)
returns `{"ok": false, "error": "<message>", "error_kind": "<ExceptionType>"}` and is logged, so a tool
call never crashes the session; success returns and domain `{ok:false}` results pass through unchanged.

---

## 1 · MCP tool surface

A plugin-bundled MCP server's tools are namespaced `mcp__plugin_<plugin>_<server>__<tool>` — here both the
plugin and the server are named `burgess`, so every tool is `mcp__plugin_burgess_burgess__<tool>`
(use this exact form in agent `tools:` / command `allowed-tools:` grants). These **thirty-six** are the **only**
graph tools — the verify/read tools (§1.1–§1.11, including `kg_merge` §1.5b and the read-only egress
`kg_explain_path` §1.10b) plus the four generative-layer tools (§1.12–§1.15)
plus the read-only `kg_agenda` (§1.16), `kg_export` (§1.17), the projection-free `kg_status` (§1.18), and
the `/burgess:kg-build` pair `kg_build_plan` (§1.19) and `kg_section` (§1.20), the `/burgess:kg-ground` pair
`kg_ground_plan` (§1.21) and `kg_ground_item` (§1.22), `kg_record_attack` (§1.23), the mark an
adversarial attack leaves when it writes no counter-edge, `kg_record_edgeless_section` (§1.24), the mark an
extraction leaves on a section it wrote no edge from, `kg_record_generation` (§1.25), the record a
`/burgess:kg-generate` run leaves in the absorption ledger, and `kg_record_unsupported(target_id, kind="node", note)`
(§1.26), the mark a grounder leaves on a `[diverge]` pin it judged and found no support for, and the
sources tools `kg_source_add` (§1.27), `kg_source_list` (§1.28) and `kg_source_set` (§1.29), which register
outside texts with an epistemic level so grounders can cite verbatim spans from them (0.21.0), and
`kg_source_policy` (§1.30), the project's evidence policy (0.22.0), and the four tools of
`/burgess:kg-sources find` (0.24.0): `kg_source_find` (§1.31), the items waiting for a source; `kg_source_search`
(§1.32), the scholarly catalogue searched through the engine; `kg_source_probe` (§1.33), a candidate page read by
the engine; and `kg_source_record_search` (§1.34), the scout's web searches and proposals.
The eight **divergence-surface** tools (§1B) complete the server's **forty-four**.
There is no `kg_build` / `kg_query` /
`kg_project` MCP tool — those are slash commands (`/burgess:kg-build`, …) that *orchestrate* these tools.

Mutation tools (`kg_write`, `kg_propose`, `kg_ground`, `kg_rename`, `kg_merge`) write the **canon** (human-editable Markdown,
the single source of truth) — `kg_propose` (§1.12) is the hypothesized write lane and `kg_operate` (§1.14) writes
through it. `kg_record_attack` (§1.23) writes only the attack ledger beside the canon, and
`kg_record_edgeless_section` (§1.24) only the edgeless-section ledger, never the canon, and
`kg_record_generation` (§1.25) only the absorption ledger in the derived dir, and `kg_source_add` /
`kg_source_set` / `kg_source_policy` (§1.27, §1.29, §1.30) only the project's `evidence/` directory, and
`kg_source_search` / `kg_source_probe` / `kg_source_record_search` (§1.32–§1.34) only the source-search ledger
beside the canon. Read tools (`get_node`, `get_neighbors`, `shortest_path`, `kg_explain_path`, `query_graph`, `kg_context`) and the
generative reads (`kg_generate` §1.13, `kg_absorption` §1.15) read the **derived** layer; they call
`_ensure_projected()` first, which reprojects only if `index.sqlite`/`graph.json` is missing or
`projector.is_stale()` — a content-driven check (a cheap per-note `(name, size, mtime)` signature pre-gate,
then an authoritative per-node content-hash comparison), regardless of git HEAD, so an uncommitted edit
still reprojects. The derived layer contains nothing the canon does not (§1.2) and never prunes failure
memory (§1.7). A reprojection that raises does not crash the read: it is logged, `projection_degraded` is set,
an empty-schema derived layer is materialised, and the tool serves canon-derived/empty data with that flag
merged into its result (a list-returning read like `get_neighbors` can't carry the flag, so it returns `[]`).
Writes never pass through this seam.

### 1.1 `mcp__plugin_burgess_burgess__kg_ping()`

Health check / config probe. No args.

```json
{"name": "burgess", "version": "<__version__>", "metrics_mode": "structure_only",
 "sensitivity": "medium", "pack_loaded": true}
```

`pack_loaded` is `true` only when `pack/pack.yaml` validated as a `PackContract` at startup. `metrics_mode`
is `structure_only` by default (centrality stays advisory; the specificity-weighted bridge metric is gated,
§1.4/§1.6).

### 1.2 `mcp__plugin_burgess_burgess__kg_scrub(text=None)`

The §1.9 **egress scrub**. Redacts **secrets (always)** + **PII (per `sensitivity`)** with **CONSISTENT
placeholders** (`⟦SECRET:1⟧`, `⟦EMAIL:1⟧`, …) before any text is handed to a subagent for semantic work.
Pass `text` to scrub a snippet, or omit to scrub the configured source. It accumulates the session
placeholder→original mapping so that `kg_write` then **RESTORES** placeholder spans to the **ORIGINAL** text
for the canon — the boundary stores the restored original span, so the scrub protects the egress, not the
local canon.

```json
{"scrubbed": "<text with placeholders>", "redactions": 0, "sensitivity": "medium", "categories": []}
```

- `scrubbed` — the text the subagent should see (original where nothing matched).
- `redactions` — count of distinct redacted values `scrubbed` holds, whether this call minted their
  placeholders or an earlier one did (placeholders are consistent across the session, so a later
  section reuses `⟦SECRET:1⟧`). It is 0 exactly when `scrubbed` equals the input. A literal `⟦CAT:N⟧`
  already present in the prose is protected, not redacted, and is not counted. (Before 0.4.6 only the
  placeholders minted by this call counted, so a reused one reported 0.)
- `sensitivity` — the engine's configured sensitivity (`kg_ping().sensitivity`); gates which PII categories
  are redacted (secrets are always redacted).
- `categories` — sorted distinct redaction categories present (e.g. `["EMAIL", "SECRET"]`), `[]` when none.

For the no-PII demo source (`examples/source.md`), `kg_scrub` is a **no-op**: `redactions: 0`,
`categories: []`, and `scrubbed` equals the source verbatim.

### 1.3 `mcp__plugin_burgess_burgess__kg_write(payload: dict, idempotency_key: str | None = None, construction: str | None = None, source: str | None = None)`

The boundary (§1.5). Validates an extraction payload, writes ACCEPTED/DEMOTED nodes & edges to the canon,
quarantines or rejects the rest. `payload` is the write contract (see `references/contract.md` / the shared
contract): `{nodes:[…], edges:[…], complete:true}`. **`complete` MUST be `true`** or the whole payload is
REJECTED as `truncated-payload`.

`kg_write` is the **text-claim lane**: every edge it accepts carries a span verified against the source. An
item that claims `provenance: "hypothesized"` is REJECTED with reason `write-lane-hypothesis`
(`retryable: false`), and the rest of the payload is written; the response then also carries
`refused_hypotheses: N`. It mirrors `kg_propose`'s `propose-lane-text-claim` (§1.12). A relation inferred
across sentences is `inferred`, still with its verbatim span; a proposal goes to `kg_propose`. (Before 0.5.1
the boundary accepted such an item with its span dropped and unchecked.)

An edge whose `source` and `target` slug to one node is REJECTED `self-loop` (0.5.2), in every lane.
`placeholders` (0.6.1, present only when non-empty) lists the NEW notes this write created untyped. Each is a
node an edge named that the payload did not declare and the canon did not hold, so it has no node_type and no
body. Declaring it in a later payload, with the same id, fills it in. Call it with the payload alone: `source` without `construction` raises a `ValueError` before anything is written,
which the transport envelope returns as `{ok: false, error, error_kind: "ValueError"}`.

`also_stated` (0.23.1, present only when non-empty) lists the edges the canon already held, unverified, that this
write quoted another passage for. Such an edge keeps the span it was first written with, while its stored span
still verifies, and the new passage is kept in its notes as an `also stated: {"span", "source_file"}` segment
(at most 8). Coverage (`kg_status`, `kg_build_plan`) counts those passages too, so every section that wrote the
edge stays covered. Through 0.23.0 the later passage replaced the span, and the section that wrote it first
showed as not covered: re-extracting it only moved the loss (field build of 2026-11-22, Copilot §35). A passage
is its words and its file, so the same sentence quoted from another file is another passage. Two writes still
update the edge as before, carrying the kept passages: the same passage written again (an extractor restating
its own edge, with a new confidence or notes), and any write once the stored span no longer verifies, whose
new passage re-anchors the edge.

`construction` (optional) routes this SAME key-free, span-verified write to a separately-named **second
construction**'s alternate canon under `<project>/.kg/constructions/<slug>/` instead of the primary canon —
the in-session second construction `/burgess:kg-perturb` cross-generates against (§9/§15, `kg_generate`'s
`second_construction`). `source` names the second source document so spans verify against IT. Omit both for
the normal primary-canon write (byte-for-byte unchanged).

```json
{
  "dispositions": {"ACCEPTED": 3, "DEMOTED": 1, "QUARANTINED": 0, "REJECTED": 2},
  "details": [
    {"kind": "edge", "id": "e_generality-confound__attacked-by__specificity",
     "disposition": "ACCEPTED", "reason": "", "retryable": false},
    {"kind": "edge", "id": "e_x__grounds__y",
     "disposition": "REJECTED", "reason": "span-not-in-source", "retryable": false}
  ],
  "written_nodes": ["generality-confound", "specificity", "compression"],
  "receipt": "rcpt_3f2a…",
  "rolled_back": false,
  "error": null
}
```

- `dispositions` — counts keyed by every `Disposition` value: `ACCEPTED | DEMOTED | QUARANTINED | REJECTED`.
- `details[]` — one per validated item: `kind` (`node`|`edge`), `id` (the derived edge id
  `e_{source}__{relation}__{target}`, or `null`), `disposition`, `reason` (e.g. `no-supporting-span`,
  `span-not-in-source`, `span-not-in-named-source` (R4: span present in the corpus but not in the edge's
  named `source_file`), `truncated-payload`, `schema-invalid`, `forged-verdict-stripped`,
  `human-claim-stripped`, `undeclared-node-type`, `undeclared-edge-type`), `retryable` (**`false`** for SEMANTIC rejections — no-span,
  span-not-in-source; **`true`** for TRANSPORT — truncation, schema-invalid).
- `written_nodes[]` — node ids actually committed (includes boundary-auto-created placeholder source nodes).
- `rolled_back` / `error` — `rolled_back` is `true` (and `error` carries the failure message) when the multi-file canon write could not commit and was rolled back.
- `receipt` — a deterministic token: a short hash over the SORTED set of the payload's target ids (node ids +
  derived edge ids) **and each item's content-bearing fields** (a node's `label`/`body`/`node_type`/three axes/
  `confidence`; an edge's `span`/`note`/`confidence`/axes/`source_file`), so a same-ids payload whose TEXT
  changed (e.g. a corrected span) yields a DIFFERENT `receipt`. Same payload → same `receipt`, across restarts.
- `idempotency_key` (optional arg) — re-sending an identical write (same payload ⇒ same `receipt`) with the
  same key after a lost transport response is a TRUE no-op: the cached response is replayed VERBATIM with
  `idempotent_replay: true` (no re-validation, no second write). A reused key with a DIFFERENT payload is NOT
  replayed (a logged caller error; the new write is processed). A rolled-back batch is never cached, so a
  transient failure is still retryable.

A write may never set a non-`unverified` state or claim parser/human authorship: such payloads are
**DEMOTED** — any verdict or `obsolete` is reset to `unverified` (`forged-verdict-stripped`); `human` →
`agent` (`human-claim-stripped`); `deterministic` → `agent` (`deterministic-claim-stripped`, so an
extractor can't dodge span-present by self-declaring parser authorship). None are accepted as-is.

### 1.4 `mcp__plugin_burgess_burgess__kg_ground(target_id, verdict, kind="edge", note="", support_span="", support_note="", lead="", refuted_by="")`

**The ONLY path that may set a verdict** (§1.4/§1.8). Stamps the epistemic_state and appends a `ground.audit`
record so the reconciler treats the transition as legitimate.

- `target_id: str` — an edge id (default `kind="edge"`) or node id (`kind="node"`).
- `verdict: str` — one of `VALID_VERDICTS = {grounded, rejected, failed, obsolete}` (lower-cased internally).
- `kind: str = "edge"` — `edge` or `node`.
- `note: str = ""` — appended to the edge's `notes` (e.g. the rejection reason `vague` for a generality-confound
  edge that is "true" only because it is generic/unfalsifiable, §1.6). With `kind="node"` it is kept in the
  node's body as the paragraph `verdict (<state>): <note>` (0.16.1): a Node has no notes field, and through
  0.16.0 its note was dropped.
- `support_span: str = ""` / `support_note: str = ""` — **promotion support** (Stage 8). To move a
  `hypothesized` edge to `grounded` you MUST supply one, and it **upgrades the edge's provenance**:
  `support_span` (a verbatim source substring, span-verified) → `span-present`; `support_note` (an external
  citation, no span) → `inferred`. Ignored for non-hypothesized edges and for any verdict other than `grounded`.
  A support span also records its file (0.16.1). An edge that names no declared source takes the file that
  holds the span as its `source_file` (since 0.21.0: a configured source first, else the usable registered copy
  of the highest level); one that names a declared source keeps it. A node's body gets a
  `grounding source: <file>` paragraph after its `grounding span:` one. A `support_note` is recorded as
  `citation (unchecked): <note>` (0.21.0; `citation: ` before) and the return says `"support":
  "unchecked-citation"`; a span promotion returns `"support_source"`, the file's class and level.
  **Since 0.22.0 `support_span` also grounds an edge that already carries its span** on another passage: it
  must lie in a usable source, the edge keeps the span it was extracted from, and the notes gain the segment
  `support: {"span": …, "source_file": …}`, which `kg_ground_item` and the report read as its best support.
  Under a strict policy that is how a claim the notes state is verified on a reviewed source.
- `refuted_by: str = ""` (0.21.0) — with `verdict="failed"`: the id of the counter-edge (`attacked_by`,
  `confounded_by` or `collapses_into`, touching the claim, with a span) whose span refutes the claim. Required
  once any external source is registered (`failed-needs-refuted-by`), so the engine knows where the refuting
  span lies; appended to the notes (a node's body) as `refuted by: <id>` and echoed as `"refuted_by"`. Refused:
  `refuted-by-not-found`, `refuted-by-not-a-counter-edge`, `refuted-by-is-the-claim`, `refuted-by-unrelated`,
  and the level veto below.

**Levels of sources (0.21.0; every source since 0.22.0).** Spans verify against the configured sources and the
registered external copies (§1.27). Every source has a level, the notes too (the policy's `notes_level`, 4 unless
set per file, §1.30). The level measures the filter the text passed, never the truth of a claim, so it only
decides what may be used, under the project's `required_level`:
- support (a promotion span, a `support_span`, or the best support of a non-hypothesized edge being grounded)
  must lie in a usable source: at or above the required level (4 by default), neither unfiltered, retracted nor
  superseded. Otherwise `support-not-usable`, with `"source"` (the file), `"source_level"`, `"required_level"` and
  `"unusable"` (`unfiltered`, `retracted`, `superseded`, `below-required-level`). A promotion records the usable
  file of the highest level that holds its span.
- a `failed` is vetoed (`evidence.failed_veto`) when the refuting span lies in an unusable source
  (`failed-by-unusable-source`) or when the refutation has a lower level than the claim's best usable support
  (`failed-by-lower-level`), whichever kind of source each is: a reviewed paper may fail a claim only the notes
  support. Through 0.21.0 the notes and an external source never failed each other
  (`failed-across-own-and-external`, removed). A refusal returns `claim_source`, `refuting_source` and a `hint`;
  the counter-edge stands as a visible dispute. With no source registered, a `failed` without `refuted_by`
  behaves as through 0.20.2.
- `lead: str = ""` (0.9.0) — with `verdict="rejected"` on an edge only: the edge the rejected span does state
  instead, `"<head-id> <relation> <tail-id>"` (`groundplan.parse_lead`: the ids slugged, the relation a pack
  edge type; a new node gets a new slug id). Appended to the notes after `note` as the segment
  `lead: <head> <relation> <tail>`, and echoed as `"lead"` in the return. `/burgess:kg-build --leads` writes it (§1.19).
  A malformed lead, an undeclared relation, a self-loop, a lead that repeats the rejected edge, or a lead with
  another verdict or `kind="node"` is refused before any state change. So is a lead on an edge with no span,
  such as a proposal (0.18.0): `--leads` writes a lead from the rejected edge's span, and that edge has none.
  Name the edge in the note instead. A lead belongs to the rejection that
  recorded it (0.11.1): a verdict that changes an edge's state and records no lead of its own withdraws the
  lead the notes held, by appending `lead: none` after `note`, and returns it as `"lead_withdrawn"`. A verdict
  that keeps the state keeps the lead, and a lead it records replaces the old one.

```json
{"ok": true, "key": "e_generality-confound__attacked-by__specificity",
 "from": "unverified", "to": "grounded", "by": "agent"}
```

A promoted hypothesis adds `"provenance_upgraded_to": "span-present" | "inferred"` to the success return.
On failure: `{"ok": false, "error": "invalid verdict 'maybe'"}` / `"invalid kind 'Node'; expected node|edge"` / `"node not found"` / `"edge not found"`.
Promotion-specific refusals: `hypothesis-needs-support` (grounding a `hypothesized` edge with neither
`support_span` nor `support_note`), `support-span-not-in-source`, `support-span-too-short`, and
`hypothesis-into-non-live-node` (0.17.1). The last one refuses grounding a `hypothesized` edge whose source or
target is a node in a rejected, failed or obsolete state, with any support. It returns `"node"` and
`"node_state"`, and the edge is rejected instead. An edge with a span is judged on its span, whatever its nodes.
For an edge, also sets `verdict_by` (always `agent` via this tool — a human verdict cannot be forged
through the tool surface) and `verdict_at`. A verdict that keeps the edge's state (0.10.2) re-confirms it and
leaves both as they are, so they record who put the edge in its state and when. Its `note` and `lead` are
still appended, and the audit log records the call. Note: the return `key` for a node verdict is
`node:<id>`; for an edge it is the edge id.

**Withdrawing a pin's grounding (0.24.7, `KGEngine._withdraw_support`).** `verdict="unverified"`, `kind="node"`, with
a `note` saying what the passage lacks. It is not a verdict state: the one path back from `grounded` for a
`[diverge]` pin, which a grounder never rejects for want of support. It is accepted only for a grounded node that
carries the `[diverge] pinned` marker and a promotion's support (a `grounding span:` paragraph or an unchecked
citation). Otherwise it answers `withdraw-not-allowed`, and `withdraw-node-only` for an edge, which has `rejected`
for the same case. `withdraw-needs-note` is the answer without a note.
- The state goes back to `unverified`, and the provenance to `hypothesized`.
- The support paragraphs leave the claim and are kept as one paragraph, `verdict (unverified): support withdrawn
  (0.24.7): <note> It rested on «<span>» (<file>).` A verdict paragraph never counts as the node's words.
- The transition is audited (`grounded` → `unverified`), so the reconciler sees a legitimate change.
- The pin is recorded unsupported against the current sources, as `kg_record_unsupported` would record it, so
  the plan leaves it out until a new source comes.
- The answer is `{ok, key, from: "grounded", to: "unverified", by, withdrawn: true, recorded_unsupported}`.

Through 0.24.6 nothing could take a grounding back. Two field pins rested on passages their own grounders had
noted fell short of the idea, and the only verdicts on offer would have rejected them.

**Held for a second grounder (0.24.6, `KGEngine._hold_or_confirm`).** A `grounded` verdict that brings support
(`support_span` or `support_note`), on an item whose grounder asked `kg_ground_item` for passages with its own
`terms` against the sources as they are now (§1.22), is checked like any other and then held. Nothing is written
but a `hold` record in `.kg-ground-requests.jsonl`, which keeps the span, the file it lies in, the words of the
search, the first grounder's note, and two marks: the grounding audit log's size and the unsupported ledger's.
The answer is `{ok: true, held: true, needs_confirmation: true, kind, target_id, terms, hint}`. Until the hold is
answered, `kg_ground_plan` queues the item only marked `confirm`, last and in a batch of its own (§1.21).
- **Confirmed:** the next `grounded` verdict with support on the item is the second grounder's. It applies,
  answers `confirmed: true` with `search_terms`, and adds a line saying how the support was found, in the edge's
  notes or as a `verdict (grounded):` paragraph of the node's body.
- **Declined:** another verdict on the item, or an unsupported record made after the hold (both read by byte
  offset past its marks, so a record from the same second does not count), answers it the other way. So does a
  change to the item itself.
- **What it guards against.** The engine checks that a cited passage is verbatim. Nothing checked that it was not
  picked out of a search run until something fitted. A request lets a grounder look in another language; the hold
  sends what that search found to a grounder who did not choose the words. The engine cannot tell one grounder
  from another, so `/burgess:kg-ground` gives a held item to a new launch, and the grounder's contract forbids
  confirming its own hold.

> Adversarial grounding (§1.7): the adversarial grounder writes counter-edges typed `attacked_by`,
> `confounded_by` or `collapses_into`, which stay `unverified` for the next pass's grounders, and calls
> `kg_ground(target_id=<the refuted claim's edge id>, verdict="failed", refuted_by=<the counter-edge id>)` only
> on a claim one of them genuinely refutes, never on its own counter-edge. Failed/rejected edges are NEGATIVE INFORMATION — never
> pruned, surfaced by `kg_context.falsification_counters`.

### 1.5 `mcp__plugin_burgess_burgess__kg_rename(old_id, new_id)`

Renames a node and rewrites every edge endpoint (`source`/`target`) referencing it, preserving the
single-canonical-edge rule. Both ids are slugged.

```json
{"ok": true, "old": "betweeness", "new": "betweenness",
 "touched": ["betweenness", "generality-confound", "specificity"]}
```

Failure: `{"ok": false, "error": "node not found"}` or `"target id exists"`. `ok` is `false` (with `error: "rename rolled back: …"`) if the multi-file write had to roll back.

`kg_rename` stays **strict** — `"target id exists"` is a refusal, never a silent merge. To collapse two
nodes that genuinely name the same concept, use `kg_merge` (below).

### 1.5b `mcp__plugin_burgess_burgess__kg_merge(from_id, into_id)`

The **deliberate node-merge** `kg_rename` refuses. Folds `from_id` into the existing `into_id` (both must
exist), rewrites every edge endpoint `from_id`→`into_id`, then RETIRES `from_id`. Where the rewrite makes
two edges share one canonical id they are **deduped** (never duplicated, never an error):

- **Negative information is sticky (§1.7):** if either edge is `failed` or `rejected`, the merged edge keeps
  that state — it is never pruned. Otherwise the stronger of `grounded` > `unverified` wins.
- The **verbatim span** and the stored **verdict note** are kept; provenance prefers `span-present`. No
  verdict or span is ever forged, upgraded, or invented — the merged state is always one a real edge held.
- **Self-loops** the rewrite creates (`source == target`) are dropped and reported — **except** a
  `failed`/`rejected` self-loop, which is PRESERVED (negative information is never pruned, §1.7): a refuted
  edge lying directly between the two merged concepts survives as a degenerate self-loop so its verdict +
  span stay in `falsification_counters`.

Keeps `into_id`'s `node_type`/`label`, and **refuses** (`"node_type conflict — refusing to merge"`) a merge
across two *different declared* node types so a wrong merge can't corrupt typing. A surviving verdict whose
edge id changed is re-keyed via the same id-migrating audit record as `kg_rename`, so it survives the
reconciler's §1.8 forgery sweep.

```json
{"ok": true, "from": "dpp", "into": "dpp-selection",
 "touched": ["dpp-selection", "collapse-toward-typical"],
 "edges_rewritten": 3, "edges_deduped": [{"id": "e_dpp-selection__defends-against__collapse-toward-typical", "state": "grounded"}],
 "self_loops_dropped": [], "nodes": 41, "edges": 87}
```

Failure: `{"ok": false, "error": "source node not found" | "target node not found" | "cannot merge a node into itself" | "node_type conflict — refusing to merge"}`; `ok` is `false` (`error: "merge rolled back: …"`) if the multi-file write rolled back — the graph is left untouched.

### 1.6 `mcp__plugin_burgess_burgess__kg_metrics(digest=False)`

Cheap summary counts straight off the canon (no projection).

```json
{"nodes": 24, "edges": 41, "edges_by_epistemic_state": {"unverified": 30, "grounded": 7, "failed": 4}}
```

`edges_by_epistemic_state` keys are whatever `EpistemicState` values are present
(`unverified|grounded|rejected|failed|obsolete`).

`digest=True` (0.19.1) adds `canon_digest`, a sha256 over the canon's note files, each one's name and bytes,
read from disk. Two equal digests mean not one note changed in between, which counts cannot say: a write
that rewrites a node's label or body leaves every count as it was. `/burgess:kg-perturb` compares counts and
digest before and after its second construction's build. That build writes the graph's own ids, so a write
that lost its `construction=` routing would rewrite the graph's nodes rather than add to them.

### 1.7 `mcp__plugin_burgess_burgess__query_graph(node_type=None, relation=None, epistemic_state=None, limit=50, text=None)`

Filtered read of the derived index. **Every filter applies to both halves** (0.8.0): `node_type` keeps the
nodes of that type and the edges that touch one; `relation` keeps the edges of that relation and the nodes
they touch; `epistemic_state` keeps the nodes and the edges in that state, each by its own state. Nodes are
**ordered by precomputed `degree` DESC** (the honest MVP advisory, §1.6), edges **by `id` ASC** (a
deterministic, byte-stable top-N), each half capped at `limit`. All filters optional.

`text` (0.11.5) searches by what nodes and edges say. Of what the other filters keep, it keeps the nodes whose
id or label, and the edges whose span, relation or endpoint ids and labels, share a search word with `text`.
It ranks them as `kg_context` ranks a query (§1.11), then in the order above. The result gains `query_terms`
(the words searched on, at most 12, as for `kg_context`) and `matched: {nodes, edges}` (how many matched before
`limit`). It is the one read
that finds a node by what it says when that node has no edge yet: `kg_context` returns edges only. Through
0.11.4 a reader that needed such a node had to grep `canon/`. Write `text` in the documents' language: the
match is on the words the graph holds, so a translated query finds little.

Through 0.7.0 `node_type`/`epistemic_state` filtered only the nodes and `relation` only the edges, so
`query_graph(epistemic_state="grounded")` returned rejected edges beside the grounded ones (8 of 50 on a
field canon) and a node-type query returned edges that touched none of its nodes. The claims are the edges:
an extractor's nodes are never verdicted, so `epistemic_state="grounded"` returns few or no nodes.

```json
{
  "nodes": [
    {"id": "compression", "label": "Compression", "node_type": "compression", "file_type": "prose",
     "provenance": "span-present", "authored_by": "agent", "epistemic_state": "unverified",
     "degree": 6, "community": 0, "bridge_communities": 2, "structural_bridge": 1}
  ],
  "edges": [
    {"id": "e_generality-confound__attacked-by__specificity", "source": "generality-confound",
     "target": "specificity", "relation": "attacked_by", "provenance": "span-present",
     "authored_by": "agent", "epistemic_state": "unverified",
     "span": "a more specific claim, when it holds, defeats a vaguer one", "source_file": "source.md",
     "confidence": "INFERRED", "confidence_score": 0.6}
  ]
}
```

Node rows carry precomputed rank columns: `degree`, `community` (Leiden membership, `-1` if none),
`bridge_communities` (count of distinct communities among neighbours), `structural_bridge` (`1` iff
`bridge_communities >= 2`). Because the read does `SELECT *`, rows also carry the Stage-2 generative
columns — `betweenness`, the confound-corrected `spec_betweenness`, per-node `specificity`, and `gate_on`
— trusted as a ranking signal only when the specificity gate is ON (§1.6); until then they are advisory.
Valid `node_type` filters are the pack's declared types
(`compression|primitive|claim|metric|operation|failure`); `relation` filters the declared edge types
(`grounds|attacked_by|reconciles_with|bridges|collapses_into|confounded_by|approximates|defends_against|projects|survives|enables`).

### 1.8 `mcp__plugin_burgess_burgess__get_node(node_id)`

One node row + its incident edges (both `source=` and `target=` matches).

```json
{
  "id": "specificity", "label": "Specificity", "node_type": "compression", "file_type": "prose",
  "provenance": "span-present", "authored_by": "agent", "epistemic_state": "unverified",
  "degree": 4, "community": 0, "bridge_communities": 1, "structural_bridge": 0,
  "edges": [
    {"id": "e_generality-confound__attacked-by__specificity", "source": "generality-confound",
     "target": "specificity", "relation": "attacked_by", "provenance": "span-present",
     "authored_by": "agent", "epistemic_state": "unverified", "span": "...", "source_file": "source.md",
     "confidence": "INFERRED", "confidence_score": 0.6}
  ]
}
```

Returns `{"error": "not found"}` when the id is unknown.

### 1.9 `mcp__plugin_burgess_burgess__get_neighbors(node_id, relation=None)`

A **list** (not a dict) of edge dicts incident to `node_id` (as `source` OR `target`), optionally filtered by
`relation`. Each element has the same shape as an edge row above. Empty list if the node has no incident edges.

### 1.10 `mcp__plugin_burgess_burgess__shortest_path(source, target)`

BFS over the derived edge list, treated as **undirected** (no centrality is computed).

```json
{"path": ["generality-confound", "specificity", "betweenness"]}
```

`{"path": ["x"]}` when `source == target`; `{"path": null}` when no path exists.

### 1.10b `mcp__plugin_burgess_burgess__kg_explain_path(nodes)`

**READ-ONLY egress** (§2). Traces the associative chain connecting `nodes` over **`grounded` edges only** —
`unverified`/`hypothesized`/`failed`/`rejected` edges are excluded entirely, so a returned chain is one that
has actually been verified. For >2 nodes the visiting order comes from a deterministic nearest-neighbour
walk (a TSP approximation, byte-stable across processes) over the grounded shortest-path closure; 2 nodes use a
deterministic sorted-neighbour BFS. Each hop carries its grounded `relation` + verbatim `span` for audit, and
`leap` (= path edge-count) is an **advisory** "creative-leap"/creative-distance signal — never a verdict,
never written, never a score.

```json
{"path": ["entropy", "time", "betweenness"],
 "edges": [{"source": "entropy", "target": "time", "relation": "grounds", "span": "Entropy grounds the arrow of time"}],
 "leap": 2, "grounded_only": true}
```

When no fully-grounded path exists: `{"path": [], "edges": [], "leap": null, "grounded_only": true,
"reason": "no fully-grounded path between <a> and <b>"}` — an honest absence (the concepts are joined only
through unverified/hypothesized/refuted links, or not at all), never an exception.

**At most 32 distinct nodes per call.** The grounded shortest-path closure costs one BFS per pair, so the
work is quadratic in the number of concepts you pass. Beyond the cap the tool refuses in the same empty
shape rather than wedging the engine: `{"path": [], "edges": [], "leap": null, "grounded_only": true,
"reason": "too many nodes: 80 (max 32)"}`.
Duplicates are deduped before the cap is applied. If you want to relate more concepts than that, ask a
narrower question — a 32-hop chain is already past what a person can read.

### 1.11 `mcp__plugin_burgess_burgess__kg_context(query=None, budget=2000)`

The **grounding-aware, provenance-carrying, token-budgeted** context tool — the one to call before reasoning
over the graph. Reads precomputed ranks **O(1)**; it **NEVER computes centrality in-request** (centrality is
precomputed off the hot path by the projector). `budget` (default `2000`, at most `100000`) caps approximate
tokens (`len(json)//4` per item).

`query` (optional) is a question in any language. Its **search words** are /burgess:kg-build's content words: case,
accents and plural endings are ignored, function words such as «del» or "the" are dropped, and two-character
letter-digit codes such as `N4` are kept. Only the first 12 search words count (`_QUERY_TERM_CAP`), and the
rest are dropped, so a longer list needs several calls. An edge matches when its span, its relation or either
endpoint's id or label holds one of them. Each word weighs log(1 + N/df) over the lane's N edges, so rare
words count most.
Through 0.11.4 the query was a substring `LIKE` over ids, relation and span. It matched «del» inside «modelo»,
never matched an accented word against an accent-free id, and the fill then ranked the hits by confidence
and id.

Fill order (best context first, until the budget is spent): **grounded edges first**, then with a query the
best match (summed word weight, then words matched), then `span-present` provenance before `inferred`, then
`confidence_score` DESC, then `id`. The grounded `items[]` and the hypothesized `hypotheses[]` lanes share
**one** running budget (§1.11): hypotheses fill only what the items lane left, and `approx_tokens` reports
the true total across both.

```json
{
  "items": [
    {"id": "e_compression__grounds__claim", "source": "compression", "target": "claim",
     "relation": "grounds", "provenance": "span-present", "authored_by": "agent",
     "epistemic_state": "grounded", "span": "...", "confidence": "INFERRED", "confidence_score": 0.82}
  ],
  "hypotheses": [
    {"id": "e_entropy__bridges__time", "source": "entropy", "target": "time", "relation": "bridges",
     "provenance": "hypothesized", "authored_by": "deterministic", "epistemic_state": "unverified",
     "span": "", "confidence": "AMBIGUOUS", "confidence_score": 0.5}
  ],
  "items_total": 37,
  "hypotheses_total": 1,
  "approx_tokens": 1840,
  "budget": 2000,
  "falsification_counters": {"failed_or_rejected_edges": 4},
  "advisory": {
    "signal": "structural-bridge",
    "note": "advisory heuristic, not a guarantee",
    "nodes": [
      {"id": "compression", "label": "Compression", "degree": 6, "bridge_communities": 2}
    ],
    "bridge_metric": {
      "gate_on": 0,
      "ranked_by": "structural_bridge",
      "note": "gated: spec_betweenness stays advisory; ranking by structural-bridge/degree (§1.6)",
      "nodes": [
        {"id": "compression", "label": "Compression", "degree": 6, "betweenness": 0.21,
         "spec_betweenness": 0.46, "specificity": 2.0}
      ]
    }
  }
}
```

- `items[]` — budget-trimmed **grounded/text-claim** edge records (note: `source_file` is omitted from context
  items, unlike `query_graph`/`get_node` edge rows).
- `hypotheses[]` — the **SEPARATE** hypothesized lane (Stage 8 query segregation): machine proposals from
  `/burgess:kg-generate`, `provenance=hypothesized`, never mixed into the grounded `items[]`. A hypothesis becomes a
  fact only after `kg_ground` promotes it with support (§1.4).
- `items_total`, `hypotheses_total` — every edge that qualified for each lane (that matched the query, when one
  was given). More than the lane holds means the budget left the rest out; through 0.11.4 nothing said so.
- `query_terms` — only with a query: the search words it was matched on, at most the first 12 of the query. A
  shorter list than the words you asked for means the rest were dropped. An empty list means the query held only
  function words, and it then matches nothing rather than everything.
- `approx_tokens` — tokens actually used across **both** lanes (`<= budget`).
- `falsification_counters.failed_or_rejected_edges` — count of edges in `FAILURE_STATES`
  (`rejected` + `failed`). **Memory of failures (§1.7): surfaced here, never pruned.** A non-zero counter is a
  signal that the graph already knows what was refuted; don't re-propose it.
- `advisory` — the **labelled structural-bridge** signal: `signal:"structural-bridge"`, an explicit
  `note:"advisory heuristic, not a guarantee"`, and up to 10 `nodes` with `structural_bridge=1` ordered by
  `degree` DESC. Treat as a hint, not a metric — the specificity-weighted bridge metric is GATED until the
  harness validates it (§1.4/§1.6). A structural bridge that is vague is the generality confound, not a real
  bridge.
- `advisory.bridge_metric` — the completed bridge metric (Stage 2): `gate_on` (`0`/`1`), `ranked_by`
  (`spec_betweenness` when the gate is ON, else `structural_bridge`), a `note`, and up to 10 `nodes` carrying
  **both** `betweenness` and the confound-corrected `spec_betweenness` so a reader sees the correction. Until
  the harness turns the gate on (`gate_on:1`), the trusted ranking stays the structural-bridge/degree advisory.
- `advisory.reexaminable_verdicts` / `_total` — the failed/rejected items judged against a source set that has
  since changed (R3-mirror). Since 0.22.3 each flag names in `files` the changed files whose words it shares.
  Flags are held back, with `advisory.reexaminable_held` — `{total, reason, required_level, hint}` — saying how
  many and why: while no source is usable under the project's policy (§1.30; reason `no-usable-source`, 0.22.2),
  and, for a flag with `files`, while every one of them is unusable (reason `raised-by-unusable-source`, 0.22.3),
  such as an unfiltered page, a retracted source, or a preprint under a policy requiring level 1. A flag from
  before 0.22.3 has no `files` and is held only when nothing is usable. Held flags stay stored and return as soon
  as one of their sources counts. The read-only hook, which knows no policy, filters nothing.
  Since 0.22.4 a flag lasts until its item is judged again, whatever the verdict: a verdict recorded in the
  grounding audit log after the flag was raised answers it, and a later change that bears on the item flags it
  anew. A fresh flag for an item already flagged adds the files that raised it. A node or span-less edge is
  flagged only when a paragraph of the changed text shares three of the words of what it claims (0.24.5; its
  label and body, or its two ends and span; all of them for a claim with fewer; numbers left out), the bar a
  waiting item is woken at. Words, not spellings: `test` and `tests` are one word. From 0.22.4 to 0.24.4 two
  words did, and on the field graph two English pages flagged 12 rejected edges on two generic words each
  (llm, tests, reward, meta, harness), all rejected again; a flag raised then stays until a verdict answers it.
  Through 0.22.3 any word of its label, body or notes anywhere in that text did: on the field
  graph an English preprint flagged 113 Spanish items, mostly through English words of the grounders' verdict
  notes, and it has a passage about 8 of them. The first read after the upgrade rebuilds the index
  (`PROJECTION_RULES` "5") and re-tests the flags stored before: a 0.22.3 flag against the files it names, an
  older one against the files changed after its item's last verdict. Each is kept, naming the files that bear on
  it, or dropped. `kg_ground_plan` queues the rejected ones for grounders (§1.21); this list is for reading. Through 0.22.3 a flag lasted until its item left
  the negative states, so a re-check that kept a rejection left it on every pass, and with the list capped at
  50 the same 50 of the field's 113 would have come back each time.

---

## 1A · The generative layer (§2–§14)

The four tools below are the *offensive* half (the inversion: **generate offensively, judge defensively**).
`kg_generate`/`kg_absorption` are read-only structural reads; `kg_propose`/`kg_operate` write through the
**hypothesized** lane only — they can never set a verdict or forge a text anchor. A candidate becomes grounded
knowledge solely when `kg_ground` (§1.4) promotes it with support.

### 1.12 `mcp__plugin_burgess_burgess__kg_propose(payload, construction=None, source=None)`

The **hypothesized write lane** (PLAN Stage 1). A thin, explicit alias over `kg_write` that forces every item
to `provenance=hypothesized` and **REFUSES** any item arriving with a text-claim provenance
(`span-present`/`inferred`) with reason `propose-lane-text-claim` — text claims belong on `kg_write`. Accepted
items transit the SAME `validate_payload`, so the hypothesized-lane rules apply (no span required; forged
verdicts demoted; failure-collapse `QUARANTINED/collapses-into-known-failure`; pack vocabulary enforced;
`authored_by=deterministic` **preserved** here, `human` demoted to `agent`). `construction`/`source` route the
proposal to a named second construction's alternate canon exactly like `kg_write` (§9/§15); omit both for the
primary canon.

Returns the `kg_write` shape plus two fields:

```json
{"dispositions": {"ACCEPTED": 2, "DEMOTED": 0, "QUARANTINED": 1, "REJECTED": 1},
 "details": [ … ], "written_nodes": [ … ], "rolled_back": false, "error": null,
 "propose_lane": true, "refused_text_claims": 1}
```

`refused_text_claims` counts the call-site `propose-lane-text-claim` refusals (folded into `details[]` and the
`REJECTED` count).

**An edge's `passage` (0.19.0).** An edge may carry the `passage` object an `ensemble` candidate came with
(`{"span", "source_file"}`, where a second construction read the edge; extra keys such as `in_source` are
ignored). It is never the proposal's span. The engine restores its placeholders and checks it against the
configured sources, as for a span: when it verifies there and meets `MIN_SPAN_CHARS`, the proposal's notes open
with the segment `passage: {"span": …, "source_file": …}` (JSON; the file is the one that holds it), and
`kg_ground_item` shows the grounder that passage (§1.22). Otherwise nothing is kept, and the edge is written as
any proposal is. Only the engine writes that segment: one an item's own notes open with is dropped. When any
edge carried a passage, the response adds `passages: {"recorded": [<edge ids>], "not_recorded": [{"id",
"reason"}]}`, the reason one of `passage-not-in-source`, `passage-too-short`, `passage-malformed`.

### 1.13 `mcp__plugin_burgess_burgess__kg_generate(mechanism="bridge", k=10, second_graph=None, dpp=None, second_construction=None)`

The **discovery engine** (PLAN Stage 3). **READ-ONLY** — projects if stale, reads precomputed ranks O(1),
dispatches to the chosen mechanism, and returns ranked candidates. It never writes; `/burgess:kg-generate` routes the
candidates through `kg_propose`.

- `mechanism` — `bridge` (§2/§4) | `seed` (§3 residual `c − E[c|d]`) | `compression` (§7 dense-cluster MDL) |
  `regroup` (§8 re-partition bridges) | `transplant` (§5 hub pattern) | `ensemble` (§9 cross two
  constructions) | `periphery` (§5 low-degree sources → max-connectability anchor; the periphery the
  hub-seeking mechanisms ignore), or `all`/`default`.
- `k: int = 10` — max candidates **per mechanism** (ranked). Each mechanism surfaces its own top `k`, so
  `all` returns up to seven times `k`, fewer once the pairs two mechanisms both proposed merge: on the
  Windows corpus `all` with `k=12` returned 51.
- `second_graph: str | None` — path to a **pre-built** second construction's `graph.json` for `ensemble`
  (the §11 escape hatch). Without a second construction, `ensemble`/`all` **degrades to `regroup`** and says
  so in `note` (run `/burgess:kg-perturb` to supply one).
- `second_construction: str | None` — the **name** of an in-session second construction built key-free via
  `kg_write(..., construction=<name>)`. The engine projects its alternate canon
  (`<project>/.kg/constructions/<slug>/`) here and cross-generates — no API key, no `backend` extra. Takes
  effect only when `second_graph` is not given (an explicit path wins); an absent/empty construction degrades
  to `regroup` with a `note`. This is what `/burgess:kg-perturb` uses for its in-session exo move (§9/§15).
- `dpp: bool | None = None` — the **advisory-DPP presentation** (I5). `None` falls back to the pack's
  `divergence.dpp` (default **off**). When ON and >1 candidate came back, the SAME candidate set is
  reordered by hybrid-descriptor DPP — one semantic axis (batch k-NN novelty over candidate embeddings)
  plus three graph-structural axes (`community` intra/cross, endpoint `graph_distance`, `grounded_mix` of
  the neighborhood) — and a `divergence_advisory` block is added: `{applied, order:"dpp", axes,
  bins, semantic_novelty, cliche_distance, cliche_hubs, pool, beyond_cap_kept_in_donor_order, note}`. `cliche_distance` is
  distance from the graph's "center" (the top-6 grounded-degree hubs — the structural cliché map);
  only the first 200 candidates enter the DPP pool (the rest keep mechanism order, reported via
  `beyond_cap_kept_in_donor_order`). **Advisory ceiling, snapshot-enforced:** same candidates, same
  scores, bit-identical grounding downstream; if the divergence deps are unavailable the deterministic
  mechanism ranking is kept and `note` says why (I9).

```json
{"mechanism": "bridge", "k": 10, "gate_on": 0, "unjudged_hypotheses": 0, "count": 2, "note": "",
 "candidates": [
   {"kind": "edge", "mechanism": "bridge", "source": "entropy", "target": "time", "relation": "bridges",
    "label": "", "node_type": "", "score": 0.81, "specificity": 2.1,
    "rationale": "cross-community pair, generality-controlled", "section": "§4", "convergence": 2}
 ]}
```

Each candidate is a `Candidate` dict: `{kind, mechanism, source, target, relation, label, node_type, score,
specificity, rationale, section, convergence}` (`provenance` is always `hypothesized`, never carried — the
propose lane forces it). `convergence` is **advisory** — the number of *distinct* mechanisms that
independently proposed the same edge (≥1); a grounding-queue ranking prior, never folded into `score` and
never written to the canon, harness-gated (`harness.convergence`) before it may reorder grounding.

A `kind:"node"` compression also carries `members` (sorted) and `id`, the id `kg_operate collapse` gives the same
members (`model.compression_id`). Write it as the star the MDL screen scored: the node under `id`, and one
`collapses_into` edge from each member to it. Both fields arrived in 0.16.0. Through 0.15.2 the members were
only in `rationale`, and the language layer had to make an id up.

Since 0.19.0, an `ensemble` candidate read off a second construction is the edge that construction wrote between
two nodes not adjacent here: its `relation` and direction are the second construction's, each such edge is
checked against failure memory on its own id, and it carries `passage`: `{"span", "source_file", "in_source"}`,
the span the edge was written from and whether that span verifies against the configured sources, the only text
a grounder judges against. The span leaves through the session scrub, so its placeholders restore when the
candidate goes on to `kg_propose` (§1.12) with its `passage` unchanged. The payload then adds `passages:
{"in_source": n, "outside_source": m}`, and `note` says when a passage lies outside the sources. A pair whose
second-graph edge records no relation (a pre-built graph.json that carries none) is still a plain `bridges`
with no `passage`. Through 0.18.1 every ensemble candidate was a `bridges` with no text; the field test of
2026-11-16 lost that way the one relation its second reading found (`tcp-ip-frente-a-osi grounds
regla-de-centralizacion`).

With a second construction, the payload also carries `ensemble` (0.19.1): how each of that construction's live
edges fared, in the order the step decides, the parts summing to `edges`:
- `ends_missing`: an end is not a node here, so the edge could not be compared;
- `repeated`: this very edge is live here, so the readings agree;
- `joined_otherwise`: the pair is joined here by another live edge, a disagreement ensemble does not propose;
- `untyped`: the edge records no relation, so its pair goes out as a plain `bridges`;
- `known_failures`: the edge or its reverse is in failure memory; `known_failure_ids` lists them, at most 20;
- `new`: what ensemble proposes, before its top-`k` cut.

When none is new, `note` says why. When the cut leaves new edges out, `note` says how many there were.
The second field run of 2026-11-16 got 0 candidates and an empty note, and its session scripted over the canon
to learn that 9 of the 10 edges were the graph's own and the tenth a known failure.

Since 0.16.0, bridge ranks a pair by the sum of its endpoints' strengths:
- With the gate on, a strength is `spec_betweenness`.
- With the gate off, it is `(structural_bridge + 1e-6·degree) × specificity`. Through 0.15.2 there was no
  specificity factor, so a graph with no structural bridge was ranked by degree alone.
- A bridge's `rationale` says which of these its strength came from.
- No node takes more than two slots of a `bridge` or `regroup` slate (`generate.ENDPOINT_CAP`). On the field graph
  of 2026-11-14 one hub took all ten.

`unjudged_hypotheses` counts the hypothesized edges still `unverified`. They count as live structure, so when it is
above 0 the ranks behind this slate include earlier proposals, and `note` says to run `/burgess:kg-ground` first.

Since 0.17.0, compression offers nothing an earlier generation proposed:
- It leaves out a community that a live compression node was already proposed over: a member whose
  `node_type` is `compression`, in any state but rejected, failed or obsolete, into which at least half of the
  other members already have a `collapses_into` edge, in any state. A new compression would ask those
  memberships again. A cluster that grew round an old compression, which was proposed over fewer of its
  members, can still be compressed, with the old node as a member.
- It leaves out a candidate whose `id` is already a node, judged or not. The id is a function of the members,
  so it is the same proposal: rejected, it is failure memory; grounded or unjudged, it is already proposed.
- When compression runs, the payload carries `compression_skipped`, `{"already_compressed": [<the live
  compression nodes>], "already_proposed": {"<id>": "<its state>"}}`, and `note` names them.
- On the field graph of 2026-11-15 all four compression candidates were of these kinds. Two held a compression
  grounded the day before, and two came back under the ids of the two it had rejected.

### 1.14 `mcp__plugin_burgess_burgess__kg_operate(op, target=None, label="", body="", members=None, k=None)`

The **four §8 endo operations** (PLAN Stage 4), each persisting its result **through the propose lane**
(`kg_propose`), so everything lands `hypothesized`/`unverified` with no span.

- `op` — `collapse` (cluster → a new compression node + `collapses_into` edges; `members` names an explicit
  member set, else the cluster is inferred from `target`) | `explode` (a node → latent facet children) |
  `regroup` (persist §8 re-partition bridges) | `open` (a new primitive + attachment points).
- `target`, `label`, `body`, `members`, `k` — operation-specific (see the docstrings); unused ones are ignored.

Returns the `kg_propose` shape with `{ok: true, op, info}` merged in. On a bad op or nothing to operate on:
`{"ok": false, "op": "collapse", "error": "no structure to operate on", "info": …}` or
`{"ok": false, "error": "unknown op 'foo'; expected collapse|explode|regroup|open"}`.

### 1.15 `mcp__plugin_burgess_burgess__kg_absorption()`

The **§14 absorption window** (PLAN Stage 5). For each node grounded *from* a hypothesis, scores how long it
stayed perturbing before the graph renormalised, so the slate can prefer the fertile middle. Reads the derived
graph plus the `derived/generations.json` ledger that `/burgess:kg-generate` records each run in, through
`kg_record_generation` (§1.25). No args.

```json
{"tracked": 4, "summary": {"fertile": 1, "absorbed": 1, "isolated": 0},
 "nodes": {"compression": {"half_life": 2.0, "status": "fertile"}},
 "not_scored": {"compression-gone-1a2b3c4d": "rejected", "compression-new-5e6f7a8b": "unverified"},
 "note": "2 tracked node(s) not scored: only a node the graph holds as grounded has an absorption window. …"}
```

`status ∈ fertile | absorbed | isolated`. With no ledger yet, `tracked` is `0` and `note` explains that
`/burgess:kg-generate` has not started tracking the window (never an error).

Only a tracked node the graph holds as `grounded` is scored, and its degrees count live edges only: rejected,
failed and obsolete edges are left out, as in every other structural signal (0.16.1). An edge lost since the
generation counts as no growth. `not_scored` maps every other tracked node to its state (`unverified` = not
judged yet, `rejected`, `failed`, `obsolete`) or to `absent` when the graph no longer holds it, and `tracked`
counts both. Through 0.16.0 every tracked node was scored over every edge, so a rejected compression read
`fertile`.

### 1.16 `mcp__plugin_burgess_burgess__kg_agenda(limit=5)`

**Read-only structural "suggested questions"** (R6). Reads ONLY precomputed derived columns (node ranks +
edge provenance/state) and returns ~`limit` structural gaps, split into two lanes that mirror `kg_context`'s
`items[]`/`hypotheses[]`:

```json
{"answerable_now": [{"detector": "well-grounded", "lane": "answerable_now", "focus": ["compression"],
                     "question": "'compression' is a well-grounded hub (degree 4, 4 grounded) — how do its neighbours (claim, …) interrelate?",
                     "signals": {"degree": 4, "structural_bridge": 1, "betweenness": 0.3, "spec_betweenness": 0.2, "specificity": 0.7}}],
 "blocked_on_grounding": [{"detector": "under-grounded-hub", "lane": "blocked_on_grounding", "focus": ["betweenness"],
                           "question": "Hub 'betweenness' (degree 5) is under-grounded — only 1/5 of its edges are grounded. Drain its unverified queue (/burgess:kg-ground) to trust it.", "signals": {…}}],
 "count": 2, "limit": 5, "gate_on": 0, "ranked_by": "structural_bridge",
 "note": "structural suggestions — a heuristic, not a guarantee. …"}
```

- **Detectors**: `orphan` (degree 0), `hypothesized-only` (every live edge a proposal — always **blocked**,
  never laundered into answerable), `under-grounded-hub`, `well-grounded` (the only **answerable_now** kind),
  `edgeless-communities` (a disconnected cluster). The `answerable_now` vs `blocked_on_grounding` split is the
  honesty move: a question you cannot ground-back-honestly surfaces as blocked.
- **Ranking** mirrors `kg_context`'s gate-aware switch — `spec_betweenness` **only** when `gate_on=1`, else the
  `structural_bridge`/degree advisory; **never** raw betweenness as lead. `ranked_by` reports which.
- **Read-only / measure-never-gate**: it asserts no edges, copies no spans, stamps no verdicts; the question
  text is session-time only and never written to the canon. It is a **heuristic, not a guarantee** — it
  suggests where to look or what to ground next; it never answers or acts. `limit` is clamped to `[1, 50]`.

### 1.17 `mcp__plugin_burgess_burgess__kg_export(kind="all")`

**Read-only human-facing render** (R1). Projects-if-stale, then consumes ONLY the derived layer (through the
shared `_agenda_reader()` seam) plus `kg_metrics`, and writes two **disposable** artifacts under the derived
dir. `kind ∈ {html, report, all}` (default `all`).

```json
{"ok": true, "kind": "all",
 "html_path": "…/derived/graph.html", "report_path": "…/derived/GRAPH_REPORT.md"}
```

- **`graph.html`** — a self-contained, fully-offline canvas force layout (no network, no `<script src>`, data
  inlined). The **three axes are on INDEPENDENT visual channels** (never one "confidence" colour):
  `epistemic_state`→edge line (solid grounded · dashed unverified · **red failed/rejected** · dotted
  hypothesized; failed/rejected are **drawn, never filtered** — §1.7), `authored_by`→node border,
  `provenance`→node fill opacity, and an `inferred` edge's line is drawn lighter in any state (0.15.1).
  **Node size = degree** (the honest advisory); the bridge highlight is
  gate-aware (`spec_betweenness` only when `gate_on=1`, else the structural-bridge advisory — size is never
  the bridge metric).
- **`GRAPH_REPORT.md`** — headline counts from `kg_metrics` (cannot drift), per-community axis breakdowns
  (single-node communities share one entry), the never-pruned falsification list, R3 stale verdicts, and R4
  per-source-file edge counts. A list longer than 50 shows the first 50 and says how many more there are.
- **Read-only / measure-never-gate**: consumes only the derived layer, writes only its two artifacts; never
  reads prose, never writes through `kg_write`/`kg_ground`, never `_atomic_write`s `graph.json`/`index.sqlite`
  (`projector.py` stays their sole writer). Cannot forge a verdict or bypass span-present. Also: CLI
  `python -m kg_engine.export html|report|all` and the `/burgess:kg-view` command.
- **A rendered view stays current (0.15.0).** Every read that projects the canon re-renders each view that
  exists and is older than the projection's `graph.json`, or that an older plugin version rendered (0.15.1;
  each view records its version): the first such read after a change or an update does it. Every
  `/burgess:kg-build` and `/burgess:kg-ground` ends with one (`kg_context`). A read never creates a view, and a
  degraded projection (failed or contended) re-renders none. A render that fails is logged and never fails
  the read.

### 1.18 `mcp__plugin_burgess_burgess__kg_status()`

A cheap, **projection-FREE** status + coverage probe. Reads ONLY the canon (and the source text for coverage);
it **never** triggers or refreshes the derived layer (unlike `kg_metrics`, which serves off the index when
fresh), so it is safe and instant even mid-build. Use it to confirm build progress and **resume a partial
build** after a transport hiccup without grepping the filesystem. No args.

```json
{
  "ok": true,
  "version": "<__version__>",
  "nodes": 113,
  "edges": 180,
  "edges_by_epistemic_state": {"unverified": 150, "grounded": 25, "failed": 5},
  "nodes_by_epistemic_state": {"unverified": 113},
  "unverified_edges": 150,
  "source": {"path": "/abs/path/source.md", "notes_from": "global", "exists": true, "files": ["source.md"],
             "builds_from": "notes"},
  "coverage": {
    "files": [{"file": "source.md", "covered": true, "sections": 19, "covered_sections": 12}],
    "sections": [{"file": "source.md", "title": "The boundary", "covered": true}]
  },
  "derived_present": true,
  "projection_degraded": null
}
```

- `unverified_edges` — the still-`unverified` grounding-queue size (the `/burgess:kg-ground` backlog).
- `source` — the **engine-resolved** source (`{path, notes_from, exists, files, builds_from}`): `path` is where
  the notes are read from (or `null` when there are none): the project's own `notes_path` (0.23.0, §1.30) when
  `notes_from` is `project`, else the plugin's `source_path` the server resolved (`global`); `none` says the
  project has no notes. `files` are the ordered basenames a build reads (R4), the registered copies marked
  `build` included, and `exists` is true iff there is at least one. `builds_from` is `notes`, or
  `registered sources` when the policy builds from those alone; through 0.22.4 `path` named the plugin's
  folder even then, beside files that are not in it. `/burgess:kg-build` reads the
  source from the ENGINE (this block, which `kg_build_plan` §1.19 also returns), never from a shell env
  var — the host injects userConfig only into the server process, so a Bash-shell env-var read would
  silently miss a configured `source_path` and build the demo by surprise.
- `coverage` — which source files / `##` sections already have at least one ANCHORED (span-present) edge:
  `files[]` (`{file, covered, sections, covered_sections}`) and per-section `sections[]`
  (`{file, title, covered}`). A section with no covered span hasn't been extracted yet — the **resume**
  signal. A span counts toward a file the way the boundary verified it: toward the file its edge's
  `source_file` names when that is a declared source, and toward any file when the edge names none or
  an unknown one. (Before 0.4.6 every span counted toward every file, so a short span shared by two
  documents marked a section of the other one covered.) If the source can't be read it degrades to
  `{"files": [], "sections": [], "note": "source unavailable (…)"}`.
- `derived_present` — a path-existence check on the derived db only (no db open).
- `projection_degraded` — echoes the last reprojection failure (a read sets it, never this probe); `null` when
  healthy.

Unlike `kg_metrics` (§1.6) this NEVER opens the derived db. Granted to `/burgess:kg-build` for node/edge counts and
the grounding queue; the build's own resume probe is `kg_build_plan` (§1.19), whose coverage is per planned
section.

### 1.19 `mcp__plugin_burgess_burgess__kg_build_plan(arguments="", configured_wave_size="")`

The `/burgess:kg-build` plan (0.5.0): which files and sections to build, which are already covered, and the wave
size. It is the build's Step 0, which through 0.4.6 ran as a Bash block; in auto mode Claude Code ignores a
command's `Bash` permission, so that block could stop a build on a permission prompt, while an MCP tool the
command declares runs without one. **Read-only and projection-free**: it reads the canon spans, the
source and the edgeless-section ledger (§1.24) only.

- `arguments` — the command's typed `$ARGUMENTS`, **verbatim**; the engine splits it
  (`buildplan.parse_arguments`). Empty → the whole configured source. A trailing whole number after a space
  is the wave size and the rest is the subset, so an unquoted name with spaces works. A line that is only a
  whole number is the wave size. Matched surrounding quotes are dropped, repeatedly; quote a name that
  itself ends in a number. Two separately quoted parts are refused.
- `configured_wave_size` — the `extract_wave_size` option as the command text carries it: Claude Code fills
  `${user_config.extract_wave_size}` when the command loads, and leaves the placeholder when the option is
  unset, which reads as unset. The engine has no wave-size setting of its own.
- The **subset** narrows the configured source and never replaces it: a file, folder or glob, relative to
  the project folder unless absolute, resolved like `source_path` itself (`SourceSet.resolve`); a bare name
  or name glob (no folder part) that is no path there is matched against the configured basenames. A subset that reaches
  a file outside the configured source (or a same-named copy elsewhere) is refused, because none of its
  spans could verify.

```json
{
  "ok": true,
  "arguments": "Fábricas de software.md 4",
  "subset": "Fábricas de software.md",
  "wave_size": 4,
  "wave_size_from": "argument",
  "source": {"path": "C:/docs/fuente", "exists": true, "files": ["Fábricas de software.md", "notas.md"]},
  "files": [
    {"file": "Fábricas de software.md", "heading_level": 2,
     "sections": [{"section": 1, "title": "Resumen", "chars": 2778, "covered": false}]}
  ],
  "sections_total": 16,
  "sections_uncovered": 15,
  "sections_edgeless": 1,
  "sections_skipped": 0,
  "waves": 4
}
```

- `skipped` on a section (0.23.1, `buildplan.skip_reason`) — left out of `sections_uncovered`: `reference-list`
  (titled References, Bibliography, Referencias…), `back-matter` (a publisher's Rights and permissions, Cite this
  article, Author information, Funding, Competing interests…) or `empty` (no letter or digit below its heading,
  as a heading followed at once by its subheadings; a short section is planned, since one line can state an
  edge). On the field's two papers they were 37 of the 117 sections a new copy holds (43 of the 137 in the
  copies registered before 0.23.1), each read by an extractor that found no edge; none of the 41 sections that
  held edges matches. `--all` as the first word of `arguments` plans them too.

- `files[].sections[]` — the sections ONE extractor each receives, numbered from 1 in file order; the same
  numbering `kg_section` serves (`sources.plan_sections`). `heading_level` is 2 for `## ` sections, or 3
  when the file's only `## ` heading is its title and two or more `### ` subsections carry the content
  (FALLO 4); a `note` says so. The text before a file's first heading is not a section; a file with no
  heading at that level is one section titled `(whole file)`. Headings inside fenced code never count.
- `covered` — a span-present edge quotes the section (heading included), counted the way the boundary
  verified the span: toward the file its edge's `source_file` names, or toward any file when it names none
  or an unknown one.
- `edgeless` (0.14.0, `{at, note}`) — on an uncovered section the ledger records an extraction of that wrote
  no edge (§1.24), while the section's text and the pack's types are the ones that extraction read. A build
  does not extract it again.
- `sections_uncovered` counts the sections to extract, neither covered nor edgeless, and `waves` is theirs
  (÷ `wave_size`, rounded up): the work left, the resume signal. `sections_edgeless` counts the edgeless ones.
- `wave_size_from` — `argument`, `option`, or `default` (nothing usable at the chosen level: unset, an
  unfilled placeholder, not a whole number, below 1). Validation and clamping (1–10, default 6) are
  `waves.explain_wave_size`'s.
- `skipped` (+ `note`) — files of the configured folder that could not be read as UTF-8 text.
- Titles and notes leave through the egress scrub (§1.9); the plan never carries section text.

`ok: false` means **do not build**, with `error` (and `problems[]` for a subset) saying why: no
`source_path` configured, nothing readable at it, two quoted parts, or a subset reaching past the
configured files. The `source`, `wave_size` and `arguments` fields are present either way.

**`--leads` first on the line (0.9.0)** plans the leads mode instead: the leads `kg_ground` recorded on rejected
edges (§1.4), for extractors to write. The rest of the line still reads as a subset and a wave size.

```json
{"ok": true, "mode": "leads", "arguments": "--leads", "wave_size": 6, "wave_size_from": "default",
 "leads": [{"source_file": "Retirar revisión humana.md", "section": 5, "title": "Mecanismos",
            "leads": [{"from_edge": "e_tests-protegidos__defends-against__hacer-trampas-con-los-tests",
                       "lead": "tests-protegidos defends_against manipulacion-de-tests"}]}],
 "leads_total": 1, "waves": 1}
```

- `leads[]` — one entry per section, in source order: the section that holds each rejected edge's span (the
  file its `source_file` names, else any configured file), covered or not. Ids only: the extractor reads each
  lead's span from `kg_section(..., leads=True)` (§1.20).
- **Pending** means: the rejected edge's latest lead (`groundplan.lead_of`), unless an edge's notes open with
  `lead (from <that edge's id>)` (`groundplan.lead_from`), or the lead's own edge exists in any state. So each
  lead is written once. A lead that a later change of state withdrew (`lead: none`, 0.11.1) is not pending.
- `leads_unlocated` (+ `note`) — rejected edges whose span no longer verifies in any section: the claim has to be
  grounded again against the changed source first.

### 1.20 `mcp__plugin_burgess_burgess__kg_section(source_file, section, leads=False, construction=None, source=None)`

One section of the configured source, **cut and egress-scrubbed by the engine**: what a `kg-extractor`
launched by `/burgess:kg-build` extracts from (0.5.0). `source_file` is a basename and `section` a number, both from
`kg_build_plan`. The extractor calls it itself, so no section text ever passes through the orchestrator.

```json
{"ok": true, "source_file": "Fábricas de software.md", "section": 2, "of": 16, "heading_level": 2,
 "title": "Evidencia", "text": "## Evidencia\nSin grupo de control. Clave ⟦SECRET:1⟧ en la nota.\n",
 "redactions": 1, "categories": ["SECRET"], "sensitivity": "medium"}
```

- `text` — the section's heading line and body, the source's own text but for the session scrub
  (`kg_scrub`, §1.2): consistent placeholders, recorded so `kg_write` restores a placeholder span to the
  original. Copy spans from it exactly, placeholders included.
- `title` — scrubbed the same way, so its placeholders match the heading line's.
- `redactions` / `categories` / `sensitivity` — `kg_scrub`'s, for this text.
- `known_nodes` (0.6.0) — up to 60 canon nodes whose NAME the section mentions, as `{id, label,
  node_type}`, so the extractor can reuse an id another section wrote instead of coining a near-duplicate.
  - **What counts as named** (`buildplan.related_nodes`): at least half the content words of the node's id or
    label occur in the section, singular or plural, accents and function words ignored.
  - **Order:** the rarity-weighted share of the name found (an IDF over the canon's names, so `radar`
    outweighs `codigo`), then the weight found, then degree, then id.
  - **What it does not do:** it only decides what the extractor is shown. Whether a concept is the same stays
    the extractor's call, and nothing is merged automatically.
  - **Egress:** labels pass the egress scrub.
- `known_nodes_more` — how many more nodes the section names past the cap.
- `untyped: true` on a known node (0.6.1) — it has no pack type: a placeholder an edge created without
  declaring it (an off-pack type is QUARANTINED and never written). The contract lets the section that
  defines it declare it, the one exception to "never redeclare a known node".
- `leads` (0.9.0, only with `leads=True`) — the pending leads (§1.19) whose rejected edge's span lies in this
  section, as `{from_edge, head, relation, tail, head_known, tail_known, span}`. The span passes the session
  scrub, so it matches `text`'s placeholders; `head_known`/`tail_known` say whether the canon holds that node.

`ok: false` with `error` for a file that is not a configured source file (`files[]` lists the configured
basenames), or a section number that is not 1…`of`. The session scrub is serialized (a lock), so a wave of
extractors asking at once keeps one placeholder per value.

A read without `leads` is what lets its extractor record the section as edgeless (§1.24, 0.14.1): the engine
keeps the digest of the text it served, in memory, until it stops.

`construction` + `source` (0.19.0, both or neither, never with `leads`) serve a section of `/burgess:kg-perturb`'s
second construction instead: the same two values the extractor passes on every `kg_write` of that construction,
and `source_file`, its source's basename. The construction cuts and scrubs the text itself, so its own
`kg_write` restores the placeholders, and records the read on its own side: it never stands behind an edgeless
record of the graph's build. `known_nodes` are the graph's own nodes the section names, so the second reading
writes the same concept under the graph's id; the ensemble step pairs the two constructions by id alone. The
response adds `construction`. Through 0.18.1 the second reading read the whole file and saw no known node: in
the field test of 2026-11-16 it gave 13 of its 39 nodes an id the graph had, and 18 of its 22 edges could not
be compared.

### 1.21 `mcp__plugin_burgess_burgess__kg_ground_plan(focus="", configured_wave_size="", batch_size=None, reexamine=False)`

The `/burgess:kg-ground` plan (0.7.0): what the grounding loop verdicts, in batches for parallel grounders. It
replaces listing the queue through `query_graph`, which on a real canon came back as 300 000 characters,
was saved to a file, and was read with scripts that auto mode stopped on permission prompts.
**Read-only and projection-free.**

- **The queue:** every `unverified` edge (any lane) and every `unverified` HYPOTHESIZED node (a `/burgess:kg-diverge`
  pin or a generated proposal). The extractor's own unverified nodes are not queued: each names a concept the
  text uses, and the claims about it are its edges. They are counted in `queue.extractor_nodes_not_queued`.
- **`queue.unsupported_waiting` (0.20.1):** the `[diverge]` pins a grounder judged unsupported against the
  current sources and recorded with `kg_record_unsupported` (§1.26). They stay out of the batches until the
  sources or the pin change; a `focus` offers them again, and the count is then 0. A record made before 0.20.2
  does not count, since its grounder saw no source text: those pins come back once.
- **`reexamine=True` (0.20.2):** `/burgess:kg-ground --reexamine` also queues the REJECTED hypothesized nodes the
  focus names (all of them with no focus), each item `{id, kind: "node", reexamine: true}`, counted in
  `queue.reexamine`. A node rejected through 0.20.1 was judged without source text, so this is how the user asks
  for it to be judged again against its `source_context` (§1.22). A `failed` node is not offered, since it was
  refuted by a counter-span. The grounder stamps its verdict even though the item's `from` is that rejection.
- **`queue.reexaminable` (0.22.4):** the rejected items a source changed under since they were judged, the flags
  `kg_context` lists (§1.11), every one rather than the 50 it shows, queued after everything new as `{id, kind,
  reexamine: true}`, in the focus like any item. A flag a verdict has answered since is left out, so the progress
  probe drops an item once a grounder has judged it again, whatever the verdict; the plan reads the audit log
  for that, and still never projects. One held back, because every file that flagged it is unusable or nothing
  is, is counted in `queue.reexaminable_held`. A `failed` item is not queued: an adversarial grounder refuted it
  with a counter-edge, whose span a new source does not remove. Through 0.22.3 the command's Stage 0c asked the
  orchestrator, which never calls `kg_ground`, to re-check these items itself.
- **A grounding judged again (0.24.7):** with `reexamine=True` AND a focus, the plan also queues the grounded nodes
  a promotion grounded (`KGEngine._promoted`) that the focus names, marked `reexamine: true` and counted in
  `queue.reexamine`. Never without a focus: `--reexamine` alone judges no grounding again.
- **`queue.confirm` (0.24.6):** the items with a grounded verdict held for a second grounder, because its support
  came after the grounder's own search (§1.4, §1.22). Each is queued only this way, last, in batches of their own
  as `{id, kind, confirm: true}`, so no grounder judges its own hold in the same launch. It leaves the plan once a
  verdict or an unsupported record answers it. With nothing usable, the held items are counted in `blocked`.
- **`queue.leads_pending` (0.9.0):** the leads rejected claims carry that no edge has taken yet (§1.19),
  for `/burgess:kg-build --leads`. The whole canon's, whatever the focus.
- **The order:** `[diverge] pinned` items first, then the other hypothesized ones, then the text edges their
  extractor marked weak (`confidence: AMBIGUOUS`, or a `confidence_score` under 0.5; counted in
  `queue.weak_edges`), then the other text edges. Inside each group the order is the source's (file, then the
  section that holds the span), so one batch covers contiguous text.
- **A node comes with its star (0.17.1):**
  - A queued node goes in one batch with the queued edges that touch it, and any queued node those edges reach
    (`groundplan.node_star_batches`), nodes first.
  - Such a unit is never split. It starts a new batch when it does not fit, and is a batch of its own when it is
    larger than `batch_size`.
  - A queue with no node is cut as before.
  - On 0.17.0 a generated compression and its star edges sat in three batches judged in parallel, and one
    grounder rejected the node while another grounded an edge into it.
- **An item is `{id, kind}`:** an edge id already names its endpoints and relation
  (`e_<source>__<relation>__<target>`); the grounder fetches the rest with `kg_ground_item`. An item judged
  again carries `reexamine: true` as well.
- `focus` — the command's typed `$ARGUMENTS`: keeps the items that touch a node it names (every content word
  of the focus among the node's id or label words, singular or plural, accents ignored). Empty = everything.
- `configured_wave_size` — the `extract_wave_size` option as the command text carries it, the same channel as
  `kg_build_plan`: how many grounders run at once (default 6, clamped 1–10).
- `batch_size` — items per grounder, 1–20 (the grounder's per-run cap), default 12.

```json
{"ok": true, "focus": null,
 "queue": {"edges": 168, "weak_edges": 7, "nodes": 0, "reexamine": 0, "reexaminable": 0,
           "reexaminable_held": 0, "confirm": 0, "extractor_nodes_not_queued": 399, "unsupported_waiting": 0,
           "leads_pending": 0},
 "batch_size": 12, "wave_size": 6, "wave_size_from": "default",
 "batches": [[{"id": "e_meta-radar__approximates__riesgo", "kind": "edge"}]],
 "waves": 3,
 "hubs": [{"id": "radar-meta", "label": "RADAR de Meta", "degree": 9}],
 "attacked_hubs": [],
 "source": {"path": "C:/docs/fuente", "exists": true, "files": ["Fábricas de software.md"]}}
```

- `hubs` — the adversarial grounder's candidates: up to 5 nodes (within the focus) with 3 or more live claims,
  the most connected first. `degree` counts live claims only: a refuted or obsolete edge
  (`NON_LIVE_STATE_VALUES`, as on every structural surface) does not count, and neither does a counter-edge.
- `attacked_hubs` — the nodes left out of `hubs` because an adversarial pass attacked them and none of their
  claims was grounded since (0.8.0), most connected first. A counter-edge is one whose `notes` open with
  `counter-edge (adversarial pass, hub <hub-id>)`, the mark the adversarial grounder writes. A hub counts as
  attacked while one of its counter-edges awaits a verdict, or when the newest counter-edge verdict is no
  older than its newest grounded claim. Both times are `verdict_at`, when the edge entered its state: since
  0.10.2 a re-verdict that keeps an edge's state moves neither, so re-confirming a claim does not reopen its
  hub. An attack that wrote no counter-edge counts once the adversarial grounder records it with `kg_record_attack`
  (§1.23, 0.10.0), as a counter-edge judged at the time of the record. So each pass attacks the next hubs down the list, and Stage 2 ends
  once every hub has been attacked. A `focus` skips this memory (and leaves `attacked_hubs` empty): naming a
  concept is how a user asks for a second attack on it. Through 0.7.0 nothing recorded an attack and the
  degree counted every edge, so every pass offered the same five hubs and left ten new unverified
  counter-edges behind.
- `source` — the configured source, as in `kg_status`, for the adversarial grounder's searches.
- `evidence` (0.21.0) — `{path, files: [{name, level, level_name, role, title}], notes: [{name, level, usable}],
  required_level}`: the usable registered external sources (§1.27), which the adversarial grounder may search
  too, and the notes with their level and whether they may refute (0.22.0). An unusable source refutes nothing
  and is not listed in `files`.
- `blocked` (0.22.1) — `null`, or, whenever no source at all is usable under the project's policy (since 0.22.2
  even when nothing was left out, every such item being already waiting), `{reason: "no-usable-source", items,
  hubs, required_level, hint}`: the hypotheses (pins, proposals, re-examined
  nodes) left out of the batches, since no source can ground them and none may be rejected for its level, and
  the hubs left out, since an attack could fail nothing. The batches keep the extracted claims, whose spans can
  still be rejected for what they say; the queue counts count what is queued. On 2026-11-22 a policy requiring
  level 1 over level-4 notes and a level-4 preprint would otherwise have sent 119 pins to 10 grounders.
- An item leaves the plan once it carries a verdict, so calling it again between waves is the progress probe.

### 1.22 `mcp__plugin_burgess_burgess__kg_ground_item(target_id, kind="edge", terms="")`

One queued item's evidence, so a grounder verdicts it without reading a file (0.7.0). **Read-only**, except that
a `terms` request is recorded (0.24.6).

```json
{"ok": true, "kind": "edge",
 "edge": {"id": "e_meta-radar__approximates__riesgo", "source": "meta-radar", "relation": "approximates",
          "target": "riesgo", "provenance": "span-present", "authored_by": "agent",
          "epistemic_state": "unverified", "confidence": "INFERRED", "confidence_score": 0.5,
          "source_file": "doc.md", "span": "El RADAR de Meta mide el riesgo de cada cambio", "notes": ""},
 "span_in_source": true,
 "source_node": {"id": "meta-radar", "label": "Meta RADAR", "node_type": "metric", "body": "…"},
 "target_node": {"id": "riesgo", "label": "riesgo", "node_type": "failure", "body": "…"},
 "context": {"source_file": "doc.md", "section": 1, "title": "Riesgo", "excerpt": "…"}}
```

- `span_in_source` — the engine's own check, now: does the span still verify against its file? `false` is a
  stale or broken span; `null` for a span-less (hypothesized) edge. Registered external copies count (0.21.0).
- `span_source` (0.21.0) — where the span lies: a configured source's label (`class: "own"`, `file`, its
  `level` and `level_name` from the policy, `role`, `marks`, `usable`), a registered external source's label
  (`class: "external"`, the same plus `title`, `url`, `published`, `build`), `{"class": "none"}` when no file holds
  it; `null` for a span-less edge. Since 0.22.0 every `context`, `shared_context` section, `passage` and section
  carries its file's label as `source`, the notes included.
- `support_source` (0.22.0) — where the edge's best support lies: the usable file of the highest level among its
  span's file and the passages it was grounded on (`support:` segments); `null` for a span-less edge.
- `support_context` (0.22.0) — `{terms, sections, sections_total}`, the usable sections that share the most of
  the edge's words (its two ends' labels and its span), as a node's `source_context` is ranked. Present when the
  edge's best support is not usable, or for a proposal none of whose shared sections is usable; `null`
  otherwise. A grounder copies a `support_span` from one of its excerpts.
- `context` — the excerpt of the source section that holds the span (`groundplan.span_excerpt`), or `null`.
  It is the paragraph and its neighbours, at most 3000 characters, and for a long table the rows around the
  span under the table's header and rule rows, with a `…` line where rows were skipped (0.8.0: before, a row
  reached the grounder without the header that names its columns).
- `shared_context` — for an edge with no span, a proposal, in place of `context` (0.18.0); `null` for an edge
  with a span. It holds the source sections where both ends are discussed. An end is discussed where the span
  of one of its live edges lies (its named file, else the first configured file that holds it), and a node
  promoted on a support span is also where that span lies. A rejected, failed or obsolete edge does not count.

  ```json
  "shared_context": {
    "sections": [{"source_file": "doc.md", "section": 2, "title": "Mecanismos",
                  "excerpts": ["…the passage from one end's span to the other's…"]}],
    "sections_total": 1,
    "source_node_sections": [{"source_file": "doc.md", "section": 2, "title": "Mecanismos"}],
    "source_node_sections_total": 1,
    "target_node_sections": [{"source_file": "doc.md", "section": 2, "title": "Mecanismos"},
                             {"source_file": "doc.md", "section": 4, "title": "Costes"}],
    "target_node_sections_total": 2}
  ```

  - `sections` lists at most 3 sections, nearest pair first: the fewest paragraphs between a span of one end
    and a span of the other. `sections_total` counts them all.
  - Each section's `excerpts` fit in 3000 characters together. When the paragraphs from one span to the other
    fit, they are one excerpt, widened with their neighbours. Otherwise each span gets its own excerpt of up to
    1500 characters.
  - `source_node_sections` and `target_node_sections` list where each end is discussed, in source order, at
    most 12 each, with their totals.
  - An empty `sections` means one of two things. If both ends have sections, the source never discusses the
    two together. If an end has none, the engine could not place it.
- `passage` — for a proposal from `/burgess:kg-perturb` whose notes open with a passage (0.19.0, kept by
  `kg_propose`, §1.12): the span a second reading of the source wrote this very edge from, as `{span,
  source_file, in_source}`, plus `section`, `title` and `excerpt` when `in_source` is true (the engine's own
  check, now). `null` for every other edge. The grounder judges it as it judges an extractor's span and may
  copy it as `support_span`; `shared_context` still comes with it.
- `reexamine` (0.22.4) — for a rejected or failed item flagged because a source changed after it was judged
  (§1.11), and not judged again since: `{reason, files, context}`. `null` for every other item.
  - `files` are the sources whose changed text shares the item's words, each with its label (`usable` among
    them). A flag made before 0.22.3 names none, and `files` is then empty.
  - `context` is `{terms, sections, sections_total}`, ranked as a node's `source_context` is, over the usable
    sections of those files, or of every usable source when the flag names none.
  - An edge flagged because its own span's file changed (`span-file-changed-since-judged`) has `context: null`
    here: its own `context` is that file's text now.
  - Through 0.22.3 a proposal re-checked this way came with the sections where its ends' spans lie, all in the
    notes it had been judged against, and nothing from the source that flagged it.
- For `kind="node"`: `{node, edges, source_context, reexamine}`, the node with its body (where a `[diverge]` marker shows),
  up to 20 incident edges, and `source_context` (0.20.2): `{terms, sections, sections_total}`.
  - `terms` are the node's content words, from its label and body without its lineage lines (`[diverge] …`,
    `[cliche] …`) and verdict paragraphs.
  - `sections` holds up to 3 source sections, ranked by their best paragraph (a long table counts line by line):
    one that shares at least two of the terms, each term weighing log(paragraphs / paragraphs that use it), so
    a word nearly every paragraph uses weighs almost nothing. Each is `{source_file, section, title, matched,
    excerpt}`, with the words that paragraph shares and the excerpt around it, cut from the source text itself.
  - A node has no span to locate its text by, so this is its evidence: the grounder copies a `support_span`
    verbatim from an excerpt that states the node's claim. Through 0.20.1 a node got only itself and its edges.
    A pin or a cliché has none, so its grounder could only search the spans other edges cited, as the field
    pass of 2026-11-21 reported.
  - The section index is cached on the sources' signature.
  - Registered external copies (0.21.0): the index also holds every usable copy, and after the best 3 sections
    come up to 3 more from external copies, so a source registered for a node is never crowded out by the
    notes. Since 0.22.0 the index holds only usable files under the policy (the notes too: below a required
    level they are left out), and every section carries `source`, its label.
- `grounded_on` (0.24.7) — for a grounded node a promotion grounded: `{spans, citations, rule}`, each span with
  its `source_file` and `context` (the section around it, as an edge's span gets). It is what its grounder judges
  when the user asks for the grounding to be judged again.
- **Across languages (0.24.6), for either kind.** Every excerpt above is chosen by the item's own words, so a
  source in another language matches it only through words both languages spell alike. Through 0.24.5 that was
  all a grounder had, and an English source found for a Spanish pin could keep its key paragraph out of view.
  - `search_context` — for an item a registered usable source was found for (`found_for`, §1.26): that source's
    sections ranked by the words of every search the scout logged for the item (§1.32, both stances), as
    `{terms, sections, sections_total, files}`. Those words were chosen before any passage was judged, by
    someone else. Absent when no such source or no such search exists.
  - `terms` — the grounder's own request: at most 8 content words (`GROUND_TERMS_MAX`), in the source's
    language. It answers `requested_context`, the usable sections that share the most of them, ranked as
    `source_context` is, with `repeated` and a `note`. One request per item while the item and the sources (and
    the policy) are what they are now (`_current_request`): asking again gives back the first words and
    sections. Every request goes to `.kg-ground-requests.jsonl`. Refusals: `terms-too-many` (with `max`),
    `terms-empty`, and `terms-not-allowed` for an item with a held verdict. A refusal records nothing.
  - **A held verdict.** After a request, a grounded verdict that brings support (`support_span` or
    `support_note`) is held (§1.4, `needs_confirmation`): `kg_ground_plan` queues the item last, marked
    `confirm` (§1.21), and `kg_ground_item` then gives it `confirm`: `{span, support_note, context, terms,
    held_at, rule}`, the passage the first grounder cited with the section around it and the words its search
    used. The first grounder's note is kept in the ledger and not shown, since it would anchor the second one.
- All free text leaves through the SESSION scrub (`kg_scrub`), so a `support_span` copied back to `kg_ground`,
  placeholders included, restores and verifies.
- `ok: false` for an unknown id, or a `kind` other than `edge`/`node`.

### 1.23 `mcp__plugin_burgess_burgess__kg_record_attack(hub_id, question, reason="no-span")`

The mark an adversarial attack leaves when it writes no counter-edge (0.10.0), because no span in the source
sets itself against the hub or one of its claims. The adversarial grounder calls it once per such hub, with
the falsifying question its attack ended with (its contract's Output B). `kg_ground_plan` (§1.21) counts the
record like a counter-edge judged at the time of the record: the hub stays out of `hubs`, in
`attacked_hubs`, until it gains a newer grounded claim. Through 0.9.0 such an attack left nothing behind, so
the plan offered that hub to every later pass, and each attack searched the source for nothing again.

- `hub_id` — the node attacked (slugged); it must exist.
- `question` — the falsifying question, up to 2000 characters, whitespace collapsed.
- `reason` — the decline tag: `no-span` (a counter is plausible, but no span states it) or `vague` (the hub is
  unfalsifiably general).

```json
{"ok": true, "hub": "escribir-codigo-parte-pequena", "at": "2026-11-08T10:30:00+00:00", "reason": "no-span"}
```

- It appends one fsync'd JSON line, `{hub, at, reason, question}`, to `<project>/.kg-hub-attacks.jsonl`, under
  the writer lease. It sets no state: no node, edge or verdict changes, so a record vouches for nothing. It
  only says that this attack found nothing to write.
- The ledger is engine state, not canon. It is git-excluded like the audit log, and read fail-open: a lost or
  unreadable ledger only offers those hubs again, and a damaged line is skipped.
- `ok: false` for an empty or unknown hub, a reason outside the two, or an empty or overlong question; nothing
  is written then.

### 1.24 `mcp__plugin_burgess_burgess__kg_record_edgeless_section(source_file, section, note)`

The mark an extraction leaves on a `/burgess:kg-build` section it wrote no edge from (0.14.0), because nothing
in the section states a relation the pack's types can carry: a list of sources, a glossary, a checklist. The
extractor calls it once, when it finishes such a section, whether it wrote nodes or nothing at all. It also
calls it when every edge it wrote came back QUARANTINED as `collapses-into-known-failure` or
`collapses-into-known-verdict` (0.14.1): the canon already holds that relation with a verdict, so the section
holds nothing new to write, and the note names the edge. `kg_build_plan` (§1.19) then marks the section
`edgeless` and leaves it out of the sections to extract. Through 0.13.6 such a section left nothing behind, so
every later build launched an extractor to read the same text and find nothing again.

**A record needs a read (0.14.1).** The engine keeps, in memory, the digest of every section text `kg_section`
(§1.20) served since it started, leads reads aside. It refuses a record for a section whose current text no
such read served, so only the extractor that read the section records it. The build's orchestrator reads no
section and never records one. On 0.14.0 it offered to record 18 sections itself, which no extractor had read
under the current pack. After an engine restart, a record waits for a new `kg_section` read.

- `source_file`, `section` — the plan's, as for `kg_section` (§1.20).
- `note` — why the section held nothing to write, in a sentence: up to 500 characters, whitespace collapsed.

```json
{"ok": true, "source_file": "Fábricas de software.md", "section": 16, "title": "Fuentes",
 "at": "2026-11-13T10:30:00+00:00"}
```

- It appends one fsync'd JSON line, `{file, section, title, text_sha256, vocabulary_sha256, at, note}`, to
  `<project>/.kg-edgeless-sections.jsonl`, under the writer lease.
- **What a record applies to:** the file, and the digests of the section's normalized text and of the pack's
  node and edge type names. A record follows its section to another number, and stops applying once the text
  says something else or the pack's types change: a new type can make a relation in the section writable.
- It sets no state: no node, edge or verdict changes, and the nodes the extraction wrote stay.
- The ledger is engine state, not canon. It is git-excluded like the attack ledger, and read fail-open: a lost or
  unreadable ledger only offers those sections again, and a damaged line is skipped. Deleting it re-offers
  every recorded section.
- `ok: false` for a file that is not a configured source file, a section number that is not one of the file's,
  an empty or overlong note, a section whose current text no `kg_section` call served (no read stands behind
  the record), or a section a span-present edge already quotes (it is covered); nothing is written then.

### 1.25 `mcp__plugin_burgess_burgess__kg_record_generation(nodes=None)`

The record a `/burgess:kg-generate` run leaves in the absorption ledger (0.17.0), the file `kg_absorption`
(§1.15) reads. It advances the generation counter and tracks each node the run proposed. The command calls it once
per run, after the kg-generator's `kg_propose`, even when the run wrote no node: the counter is the clock every
tracked node's window is read against.

- `nodes: dict | None` — each node id the run's `kg_propose` ACCEPTED, mapped to the mechanism that proposed
  it: `{"compression-compression-…-1772d76d": "compression"}`.

```json
{"ok": true, "generation": 3, "tracked": 7,
 "recorded": {"compression-a-1a2b3c4d": {"introduced_at": 3, "introduced_degree": 5, "mechanism": "compression"}},
 "skipped": {"compression-old-5e6f7a8b": "already tracked since generation 1"}}
```

- A recorded node gets `{introduced_at, introduced_degree, mechanism}`: the generation this call opens, and the
  node's live degree now, counted in the canon over its edges that are not rejected, failed or obsolete, as
  `kg_absorption` counts the degree it compares with.
- `skipped` gives the reason for each id left out: `not in the canon`, `already tracked since generation N`,
  `not a proposal: its provenance is …` (only a hypothesized node is a generation's), or a missing mechanism.
- The ledger is `derived/generations.json`, `{"generation": N, "tracked": {id: record}}`, rewritten whole and
  atomically under the writer lease. The bare `{id: record}` shape `kg_absorption` also reads is extended, with
  its newest `introduced_at` as the counter.
- `ok: false`, with nothing recorded and the file left as it is, for a ledger this engine cannot read or extend,
  for `nodes` that is not a map, or while another writer holds the lease.
- It sets no state: no node, edge or verdict changes.
- Through 0.16.1 the command's Step 4 was a sketch. Each session wrote its own merge script and ran it through
  the Bash tool, which writes outside the project and so asks the user every time: on 2026-11-15 the second
  field run's write waited nine hours for the approval.

---

### 1.26 `mcp__plugin_burgess_burgess__kg_record_unsupported(target_id, kind="node", note)`

The mark a grounder leaves on a `[diverge]` pin it judged and left `unverified` for want of support (0.20.1).
The grounder calls it once per such pin, with a note on what it looked for and did not find. `kg_ground_plan`
(§1.21) then leaves the pin out of its batches, counted in `queue.unsupported_waiting`, while the sources and
the pin are the ones it was judged against. A change to the sources (the signature of their contents) or to
the pin (its label and body, or an edge's ends, relation, span and notes) offers it again. So does a `focus`,
as for an attacked hub. Through 0.20.0 nothing recorded the judgment, so every pass judged every pin again:
the field pass of 2026-11-21 ran ten grounders over 120 pins, about 2.50 USD, and left all 120 unverified.

- `target_id` — the pin's node id (slugged) or edge id, exactly as the batch listed it.
- `kind` — `node` (the default; a materialized pin is a node) or `edge`.
- `note` — what was looked for and not found, up to 2000 characters, whitespace collapsed.

```json
{"ok": true, "item": "idea-cold-brew-launch-c3", "kind": "node", "at": "2026-11-21T16:30:00+00:00"}
```

- Only an `unverified`, hypothesized item whose body (a node) or notes (an edge) carry the `[diverge] pinned`
  marker can be recorded. Anything else, an ordinary proposal included, gets its verdict from `kg_ground`, so
  the record can never hide an item from the queue that a verdict should settle.
- It appends one fsync'd JSON line, `{kind, item, at, source_sig, item_sig, note}`, to
  `<project>/.kg-unsupported-pins.jsonl`, under the writer lease. It sets no state: no node, edge or verdict
  changes.
- The ledger is engine state, not canon, git-excluded like the attack ledger and read fail-open: a lost or
  unreadable ledger only offers those pins to one more grounder.
- `ok: false` for an unknown item or kind, an empty or overlong note, or an item that is not an unverified
  `[diverge]` pin; nothing is written then.
- Registering an external source (§1.27) changes the source signature. Through 0.22.0 that offered every waiting
  pin again, and so did any change of the policy (§1.30), whose fingerprint joins the signature whenever it
  differs from the defaults. Since 0.22.1 only a usable file the item was not judged against does, as below, and
  since 0.24.0 only such a file that was found for the item or bears on it.
- Since 0.22.0 two more kinds of item may be recorded, both ones the policy leaves without usable support, which
  a grounder leaves `unverified` rather than rejects: an edge whose span lies only in sources the project does
  not accept, and a hypothesis while the notes, at their default level, are below the required level. The plan
  leaves out any item whose latest record still matches, pin or not.
- Since 0.22.1 a record also keeps `usable`, the sha256 of each file usable when it was made, and an item waits
  while every file usable now was usable then (`groundplan.waits_for_sources`). So a new or edited usable file,
  or a looser policy, offers it again, while registering a source the policy does not accept, removing one, or
  a stricter policy does not. A record made before 0.22.1 has no list: when its `source_sig` is the signature of
  the configured sources as they are now, it stands for them; otherwise the signatures must match, as before.
- **Since 0.24.0 such a file wakes only the items it bears on** (`KGEngine._new_source_wakes`): the items its
  record says `/burgess:kg-sources find` looked for it for (`found_for`, §1.27), and the items with a paragraph
  in it that shares their words (the 0.22.4 paragraph rule, `Projector._bearing_files`): a paragraph must share
  three of its words (0.24.4, `KGEngine.WAKE_WORDS`; all of them for an item with fewer). Two, the
  re-examination rule's bar until 0.24.5, woke 15 of the field's Spanish pins for an English page found for one:
  each shared exactly two cognates or generic words with it (agentes/agents, planes/plan, tests, local, token).
  Words, not spellings (0.24.5, `groundplan.word_groups`): `test` and `tests` are one word. Through 0.23.1 any new
  usable file woke every waiting item: in the field one source would have sent all 119 waiting pins of a project
  back to a grounder. A source in another language than an item shares no words with it, so one registered by
  hand for it is reached with a `focus`. The record now keeps the grounder's `note`, which §1.31 shows.

---

### 1.27 `mcp__plugin_burgess_burgess__kg_source_add(url="", path="", level="", role="", title="", published="", marks="", derives_from="", note="", preview=False, build=False, for_items="")`

Register an external source (0.21.0, `evidence.py`): the engine copies an outside text into
`<project>/evidence/` and records its epistemic level, so a grounder can cite a verbatim span from it. Through
0.20.2 the only outside support was a `support_note`, a citation the engine could not check. **The level
measures the filter the text passed before it was published, never whether a claim is true.**

- Exactly one of `url` (http/https) or `path` (a local file, relative to the project). The engine fetches the
  bytes itself, with a generic User-Agent that says nothing about the user, and extracts the text by a fixed
  rule (stdlib `html.parser`: headings become `##`/`###` lines, list items `- ` lines, table rows `a | b`
  lines; scripts, styles, navigation, footers and forms are dropped; since 0.22.1, `html-text/2`, also a formula's
  MathML annotations and invisible operators, so `15×` is copied once rather than as `15×\times`; since 0.23.1,
  `html-text/3`, a page with a `<main>` gives only that part, and sidebars (`<aside>`, `role=complementary`),
  recommendation lists, related-content, sharing, cookie and comment blocks are left out, so a journal page's
  "Similar content", "Explore related subjects" or "Share this article" never become sections). A copy keeps the
  rule it was made with in its record's `extractor`. **Never register WebFetch output**: it is
  a small model's answer about the page, not the page. A local `.md`/`.markdown`/`.txt` is copied verbatim;
  `.html`/`.htm` is extracted by the same rule. PDF is refused (`pdf-not-supported`): convert it to Markdown
  and register that file.
- A site's bot check is refused (0.23.1, `fetch-blocked`, at the preview already): an HTML page titled like one
  ("Client Challenge", "Just a moment…", "Attention Required! | Cloudflare"…) or a short one that says what such
  a page says ("verify you are human", "captcha"…). `detail` says which, and `hint` the way around: save the page
  from a browser as `.html` and register the file. On 2026-11-22 Springer served the engine on Windows such a page
  for every article, which 0.23.0 previewed as `ok: true`.
- `published` comes from the page when the caller gives none: the online date first (`citation_online_date`),
  then the issue's (`citation_publication_date`) and the others, never a date still to come when an earlier one
  is declared (0.23.1; the field's Copilot paper went online on 2026-11-03 for an April 2027 issue).
- `preview=True` — fetch or read it and return `{title, chars, content_type, extractor, published, meta,
  final_url, excerpt}` (the first 1500 characters) without writing anything: what the command proposes a level
  and role from. `meta` holds the page's `citation_*`, `dc.*`, `og:*` and `article:published_time` values.
- `level` — required: `1` reviewed (peer review), `2` institutional (official statistics, standards, official
  documentation, university textbooks), `3` editorial (press with corrections, edited books), `4` author or
  community (preprints, code, changelogs, company docs and blogs, forums, Wikipedia), `5` unfiltered (no
  filter, or made to sell, persuade or rank). Also `"N3"` or the names.
- `role` — required: `primary` (the origin of the fact), `secondary` (analyses and cites primaries),
  `tertiary` (summarizes without the origin).
- `marks` — comma-separated, from `interest`, `corrected`, `retracted`, `superseded`. A level-5 source, and a
  retracted or superseded one, supports and refutes nothing.
- `published` — `YYYY`, `YYYY-MM` or `YYYY-MM-DD`; when empty the date the page declares is kept, with
  `published_from: "page"`. `retrieved_at` is the one date the engine certifies.
- `derives_from` — a registered source this one repeats (so it is not independent of it); `title`; `note`
  (why this level).
- `build` (0.22.0) — `true` also extracts the source into the graph like a configured source:
  `kg_build_plan` lists it, `kg_section` serves it, the specificity corpus counts it, and its claims carry its
  level. With the policy's `build_from_notes` off, such sources are all that is extracted.

```json
{"ok": true, "name": "ext-study-of-degree-8c40b8d9.md",
 "source": {"class": "external", "file": "ext-study-of-degree-8c40b8d9.md", "level": 1, "level_name": "reviewed",
            "role": "primary", "marks": [], "usable": true, "title": "Study of degree",
            "url": "https://example.org/paper", "published": "2023-04-02"},
 "chars": 172, "retrieved_at": "2026-11-21T20:00:00+00:00", "published_from": "page",
 "directory": "/path/to/project/evidence"}
```

- Per source the directory holds the copy (`ext-<slug>-<8 hex of its sha256>.md`), its record
  (`<same stem>.source.json`: level, `level_by`, role, marks, dates, url, `sha256_raw`, `sha256_text`,
  extractor) and, for a fetched page or a local HTML file, the bytes as received under `raw/`. The `ext-`
  prefix keeps a copy from sharing a basename with a configured source.
- `level_by` is always `agent` through this tool; only a hand edit of the record says `human`.
- A copy is **never extracted**: `kg_build_plan`, `kg_section`, coverage and the specificity corpus read the
  configured sources only. It is used for span verification (`kg_write`, `kg_ground`, the R3 staleness scan),
  the grounder's evidence (`kg_ground_item`), the adversarial grounder's search (`kg_ground_plan`'s
  `evidence`), and the source signature that wakes waiting pins.
- `for_items` (0.24.0) — the ids of the waiting items `/burgess:kg-sources find` found the page for,
  comma-separated. The engine adds the items its search ledger shows the page was read (§1.33) or proposed
  (§1.34) for, or found by a catalogue search (§1.32) for: by URL, by DOI, or for a proposal by its exact title,
  so a page saved from a browser still finds its item. The record keeps them in `found_for`, with the page's
  `doi`, and the result names them in `found_for`: they, and the items with a paragraph in the source that shares
  three of their words, wake for the next `/burgess:kg-ground` (§1.26). `item-not-found` for an id the graph does not hold.
- `comes_back` (0.24.5) — the waiting items the registration wakes: those waiting for a source before the copy
  was written and not after (`KGEngine._waiting_items`), each with `id`, `kind` and `why`: `found_for` (the copy
  was found for it), `words` (a paragraph of the copy shares three of its words, listed once each in `words`),
  `no-words` (it has no words to test, so any new usable source wakes it), or `other`. At most 30, with
  `comes_back_total`; `still_waiting` counts the items that keep waiting. Empty when the copy is not usable. The
  command reports these reasons and no others: through 0.24.4 the result had only `found_for`, and on the field
  an agent told the user that an item found for the copy came back because it shared words with it.
- Refusals: `give-url-or-path`, `url-not-http`, `fetch-failed` (with the HTTP status or reason), `too-large`
  (over 5 MB), `undecodable`, `no-text` (the page needs JavaScript: save its text as `.md` and register the
  file), `pdf-not-supported`, `content-type-not-supported`, `file-type-not-supported`, `file-not-found`,
  `already-a-configured-source`, `already-in-evidence`, `bad-level`, `bad-role`, `bad-marks`,
  `bad-published`, `derives-from-unknown`, and `already-registered` (the same text, with its `name`). A URL
  registered before with other text is accepted and named in `same_url_as`, so the old copy can be marked
  superseded.

---

### 1.28 `mcp__plugin_burgess_burgess__kg_source_list()`

The registered external sources and what the grounded claims rest on (0.21.0). Read-only.

- `sources[]` — each one's `name`, label (`level`, `level_name`, `role`, `marks`, `usable`, `unusable`, `title`,
  `url`, `published`, `derives_from`), `retrieved_at`, `published_from`, `level_by`, `note`, `origin`, `build` and
  `chars`; `by_level` and `usable` count them.
- `notes[]` (0.22.0) — each configured file's `name`, label (`level`, `level_name`, `role`, `marks`, `usable`),
  `recorded` (whether the user set its level), `chars` and `built`; `policy` — `{required_level, notes_level,
  build_from_notes}` (§1.30); `usable_sources` (0.22.1) — how many files may support or refute, with a
  `warning` when none may.
- `problems[]` — records left out, with `problem`: `text-edited` (the copy no longer matches its sha256, so the
  engine no longer vouches for it: register the source again instead of editing the copy), `text-missing`,
  `name-mismatch`, `sidecar-malformed`, `sidecar-unreadable`, or a field's parse error. `unregistered[]` — text
  files in the directory that no record claims; they are ignored.
- `support` — `edges` and `nodes`, each `{own: {level: n}, external: {level: n}, unchecked_citation, unlocated}`
  (`own` by level since 0.22.0): grounded claims whose best support lies in the configured sources or in
  external copies, by level, in a `support_note` (an `inferred` promotion the engine cannot check), or in a span
  no file holds now. `external_items`, `unchecked_items` (at most 50 each) and `on_unusable` (claims whose best
  support is no longer usable under the policy: a source since marked retracted, or below a required level
  raised since; with `on_unusable_total`) name them.

---

### 1.29 `mcp__plugin_burgess_burgess__kg_source_set(name, level=None, role=None, marks=None, published=None, derives_from=None, title=None, note=None)`

Change a registered source's record (0.21.0). A parameter left out is unchanged; `marks` replaces the whole set
(`""` clears it), and `published` / `derives_from` take `""` to clear. The copy itself is never rewritten. A
level set here is recorded as the agent's. Returns `{ok, name, changed: [fields], source: <label>}`; refusals
`source-not-found` (with `registered`), `bad-level`, `bad-role`, `bad-marks`, `bad-published`,
`derives-from-unknown`. A change bears on verdicts from now on: a source marked retracted or superseded
supports and refutes nothing. Verdicts already given keep their state, and `kg_source_list` names those now
resting on an unusable source.

Since 0.22.0 `name` may also be a configured file (one of the user's notes, by basename): its `level`, `role`,
`marks` and `note` are kept in the policy (§1.30); the fields only a registered source has are refused
(`not-for-notes`). `build=True/False` (a registered source only) sets whether it is extracted; the return then
carries a `hint` (run `/burgess:kg-build`, or: its claims already in the graph stay).

---

### 1.30 `mcp__plugin_burgess_burgess__kg_source_policy(required_level=None, notes_level=None, build_from_notes=None, notes_path=None)`

Read (no argument) or change the project's evidence policy (0.22.0, `evidence.Policy`), kept as
`<project>/evidence/policy.json`. Through 0.21.0 the notes sat outside the scale, so notes of unknown level
verified an idea as a peer-reviewed paper did and could not be failed by it, and a graph could not be built from
level-1 sources.

- `required_level` (1–4) — the worst level that may still support or refute. `4` (the default) accepts
  everything but unfiltered sources; `1` only peer-reviewed ones: the notes then only propose claims, and a claim
  is verified on a usable passage (`support_span`, §1.4) or left `unverified` and recorded (§1.26).
- `notes_level` (1–5) — the level of a configured file with no record of its own (default `4`: a text by an author
  nobody reviewed). Per-file levels are set with `kg_source_set` (§1.29).
- `build_from_notes` (bool) — whether the configured sources are extracted; `false`, with sources registered
  with `build`, builds a graph from those sources alone. The notes are still verified against, as evidence only,
  so the spans of claims extracted from them earlier stay valid.
- `notes_path` (0.23.0) — THIS project's notes: a folder, file or glob inside the project, stored relative to it;
  `none` for no notes at all; `default` for the plugin's `source_path`. Claude Code keeps a plugin's options per
  user and ignores a project's settings for them (a cloned repository must not choose what the plugin reads), so
  the plugin's `source_path` is one value for every project, and this is how a project reads its own. A path
  outside the project (`notes-path-outside-project`), one of the engine's folders (`canon`, `evidence`, `.kg`,
  `.git`, `.claude`: `notes-path-reserved`) or a path that does not exist (`notes-path-not-found`; a glob may
  match nothing yet) is refused. A stored value that lies outside the project, from a hand edit or a cloned
  repository, is reported in `problems` and ignored: the plugin's `source_path` applies. The notes are what a
  build extracts and what spans are verified against, so the change takes effect at once. The result's
  `policy` carries `notes_path`, `notes_from` (`project`, `none` or `global`) and `notes_folder` (the path read
  now, or `null`), and so does `kg_source_list`'s (§1.28).

```json
{"ok": true, "changed": ["required_level"],
 "policy": {"required_level": 1, "notes_level": 4, "build_from_notes": true, "notes_path": "",
            "notes_from": "global", "notes_folder": "C:/docs/notes"},
 "notes": [{"name": "notes.md", "class": "own", "file": "notes.md", "level": 4, "level_name": "author-or-community",
            "role": "", "marks": [], "usable": false, "unusable": "below-required-level", "recorded": false,
            "chars": 1290, "built": true}],
 "on_unusable_total": 198, "problems": []}
```

- A change bears on verdicts from now on: verdicts already given keep their state, and `on_unusable_total` counts
  the grounded claims that no longer rest on a usable source (`kg_source_list` names them). A looser policy that
  makes usable a file the waiting items were not judged against offers them again; a stricter one never does
  (0.22.1, §1.26). With the defaults the source signature is 0.21.0's.
- `usable_sources` (0.22.1) — how many files may support or refute under the policy; when none may, `warning`
  says so and that `/burgess:kg-ground` leaves the items that need support out (§1.21's `blocked`) until a source
  at the required level is registered or the level is lowered.
- A malformed `policy.json` is reported in `problems` and the defaults apply. Refusals: `bad-required-level`,
  `bad-level`, `bad-build-from-notes`, and the three `notes-path-*` above.

### 1.31 `mcp__plugin_burgess_burgess__kg_source_find(focus="", limit=6)`

The items waiting for an outside source, for `/burgess:kg-sources find` (0.24.0): every item a grounder recorded with
`kg_record_unsupported` (§1.26) that still waits, because no usable source it was not judged against was found
for it or bears on it. The user asked on 2026-11-21 for Burgess to *suggest* sources that could settle what the
graph cannot; 0.21.0–0.23.1 built the registry, the levels and the policy, and this is the suggestion. Read-only.

```json
{"ok": true, "focus": "", "waiting_total": 119, "never_searched": 119, "limit": 6, "required_level": 4,
 "openalex_searches_today": 0, "query_max_chars": 200,
 "items": [{"id": "idea-atasco-fabrica-agentes-c1a", "kind": "node",
            "text": "Comprimir el historial de acciones del agente y vigilar la ratio de compresión: …",
            "terms": ["comprimir", "historial", "acciones", "agente", "vigilar", "ratio", "compresión"],
            "looked_for": "Looked for … Closest: …", "waiting_since": "2026-11-22T17:28:00+00:00",
            "searched": [], "proposed": []}]}
```

- `openalex_budget_left_usd` (0.24.3) — what OpenAlex said was left of the network's free daily budget at the
  last catalogue search today, or `null`.
- `focus` keeps the items where every word of it occurs in what the item claims (`text`) or in its id (an edge's:
  its two ends'), singular or plural, accents ignored (the word rules of §1.21). Through 0.24.0 it read only the
  id and the label, and a pin's label is cut at 80 characters: in the field `find compresión 3` found nothing,
  because the one pin about compression had the label "…vigilar la ratio de compresió...". The grounding focus
  (§1.21) still names nodes by id and label. `limit` is 1–20.
- The order: the items never searched first, then the ones searched longest ago (the search ledger, §1.32).
- `text` is what the item claims (a node's label and body without its lineage lines and verdict paragraphs; an
  edge's ends, relation and span), `terms` its content words, `looked_for` its grounder's note, `searched` the
  last 8 searches logged for it and `proposed` the last 6 candidates proposed for it. Egress-scrubbed.
- With nothing recorded, `note` says that an item waits once a grounder judged it and recorded that no usable
  source supports it; with records but nothing waiting, that the new sources are to be judged first.

---

### 1.32 `mcp__plugin_burgess_burgess__kg_source_search(query, item_id="", stance="for", results=8)`

Search OpenAlex, the open catalogue of scholarly works, through the engine (0.24.0). Only the query leaves the
machine: one GET to `api.openalex.org/works` with `search`, `per_page` and `select`, the engine's generic
User-Agent, no key and no contact address. (OpenAlex invites agents to send the user's email to get a key; the
engine never does.) Without a key every request from one network shares a free daily budget, about 100 searches
(checked 2026-11-23).

```json
{"ok": true, "backend": "openalex", "query": "stigmergy software agents coordination", "stance": "for", "count": 1,
 "results": [{"title": "Stigmergy in software teams", "doi": "10.1234/stig.2025.7", "url": "https://example.org/stig",
              "oa_url": "", "published": "2025-03-04", "type": "article", "venue": "Journal of Coordination",
              "venue_type": "journal", "retracted": false, "cited_by": 12, "abstract": "Agents coordinate …",
              "level_hint": 1, "level_hint_reason": "an article in a journal: level 1 when the venue is peer-reviewed"}]}
```

- `level_hint` comes from the catalogue's facts (`evidence.level_hint`): a journal or conference article 1, a
  preprint or repository copy 4, a book 3, a retracted work none. It is a proposal the user confirms or corrects.
- `abstract` is rebuilt from OpenAlex's inverted index, at most 1200 characters. It is not a registered copy:
  only a registered page can carry a span.
- Every search is logged in `<project>/.kg-source-searches.jsonl` (engine state, git-excluded, read fail-open)
  with its item, stance, count and the results' titles, DOIs and URLs.
- `query-refused`: an empty or overlong query (over 200 characters), or one holding what the §1.9 scrub would
  redact (a secret, a personal detail, a ⟦CAT:N⟧ placeholder): nothing is sent. `item-not-found` for an unknown
  item. `search-failed`: anything else.
- **Pacing (0.24.3, `evidence._openalex_get`):** the engine runs one catalogue request at a time, at least 1.1 s
  after the last one, and after an HTTP 429 waits (`Retry-After`, or 2 s, at most 10 s) and retries once.
  - `budget` is what the answer's headers say of the network's free daily budget: `remaining_usd`, `limit_usd`,
    `reset_s`. The search's ledger record keeps `budget_left_usd`, and §1.31 reports the last one of the day.
  - `search-budget` only when OpenAlex says the budget is spent: HTTP 402, or a 429 whose
    `X-RateLimit-Remaining-USD` is 0.
  - `search-rate-limited`: a 429 again after the pause, with budget left.
  - Through 0.24.2 every 429 was read as a spent budget. On the field run of 2026-11-23 three of a scout's six
    catalogue searches drew one while the headers said 0.084 USD of 0.10 USD was left, the scout dropped the catalogue,
    and the report said the daily limit had run out.

---

### 1.33 `mcp__plugin_burgess_burgess__kg_source_probe(url, item_id="", terms="")`

Read a candidate page for an item without registering it (0.24.0). The engine fetches it as `kg_source_add` does
(§1.27; never WebFetch, whose answer is a model's paraphrase of a page) and returns what to judge it by.

```json
{"ok": true, "url": "https://example.org/stig", "final_url": "https://example.org/stig", "title": "Stigmergy in software teams",
 "doi": "10.1234/stig.2025.7", "published": "2025-03-04", "venue": "Journal of Coordination", "publisher": "",
 "site": "", "chars": 210, "extractor": "html-text/3", "level_hint": 1,
 "level_hint_reason": "declares a journal or conference (Journal of Coordination): level 1 when it is peer-reviewed",
 "passages": [{"text": "Agents coordinate through stigmergy when each trace …", "matched": ["stigmergy", "repository"]}],
 "terms": ["stigmergy", "repository", "traces"]}
```

- `passages` are the 3 paragraphs that share the most of `terms` (the scout's search words, in the page's
  language) and of the item's own words, rare words weighing more (`evidence.best_passages`, the rule of
  §1.22's node sections), each cut from the page as the engine would copy it, at most 900 characters.
- `registered_as` names a registered copy of the same page (same bytes, URL or DOI).
- Refusals: `fetch-blocked` (a site's bot check, with the hint to save the page from a browser and add the
  file), `pdf-not-supported`, `fetch-failed`, `no-text`, and the other refusals of §1.27's fetch.
- Every read is logged for its item, ok or not, so registering the page later (§1.27) records the item in
  `found_for` and wakes it.

---

### 1.34 `mcp__plugin_burgess_burgess__kg_source_record_search(item_id, searches=None, proposed=None, note="")`

Log for an item what the engine did not see (0.24.0): the scout's web searches and the candidates it proposes.

- `searches` — `[{query, stance, results}]`: each web search, `stance` for or against, `results` the number of
  hits looked at, 0 for an empty search. Empty searches are logged too: what was searched and found nothing is
  part of the record.
- `proposed` — `[{url, title, doi, level, stance}]`: the candidates the scout proposes. `kg_source_add` matches a
  page registered later to these by URL, DOI or exact title.
- `note` — what the scout found, or why nothing.

```json
{"ok": true, "item": "idea-atasco-fabrica-agentes-c1a", "searches": 1, "proposed": 1,
 "missing": ["openalex against"],
 "hint": "run the missing searches for this item, then record them (searches only: the proposals are logged already)"}
```

- `missing` (0.24.2) — the required searches the log does not hold for this item in the last two hours, as
  `"<backend> <stance>"`: the catalogue for and against, and the web for (`KGEngine.REQUIRED_SEARCHES`). A logged
  search counts whatever it found. A catalogue search that failed is owed to the web with the same stance (0.24.3;
  through 0.24.2 it counted as tried, so an item whose catalogue search against was refused got none). When
  OpenAlex refused for want of budget in that window, both catalogue searches are owed to the web.
  The scout runs what is missing and records it before it reports the item. On the field run of 2026-11-23 two
  scouts with three items each ran no against search for any of the six, and the web search for two.
- `item-not-found`, or a refusal naming the malformed search or candidate; nothing is written then.

## 1B · The divergence surface (`kg_diverge_*`) — eight tools

The divergence engine (`scripts/kg_engine/divergence/` — embedder, MAP-Elites archive, k-NN novelty, DPP
slates, anti-collapse monitor) runs inside the same MCP server as eight tools. They sit **below the
grounding boundary**: geometry affects what is proposed and in what order, never what is true (I5); nothing
under `divergence/` can set or upgrade an epistemic state (I3, import-firewalled); and every `kg_*` graph
tool keeps working when the divergence deps are blocked (I9) — a `kg_diverge_*` call then returns a
provisioning error to relay verbatim.

**State layout** — project-local under `.kg/diverge/<project-slug>/` (base dir: `$KG_DIVERGE_HOME` if set,
else `$KG_PROJECT_DIR`, else cwd):

```text
meta.json  axes.json  session.json  materialized.json     durable
session/                                                  EPHEMERAL (I10)
  archive.json          MAP-Elites niches + counts
  candidates.json       id -> candidate record
  embeddings.npz        surface vectors (binary npz)
  mech_embeddings.npz   open-axis/mechanism vectors (npz)
  open_nicher.json      the open-axis Voronoi partition
  cliches.json          the session's cliché map (0.20.0; read by nothing in the geometry)
memory/<domain-slug>/                                     durable
  pins.json  discards.json  comparisons.jsonl
```

**Session rule (I10):** `kg_diverge_init` with a NEW (or omitted) `session` id wipes `session/` plus the
geometry-coupled meta series (cycle count, cosine/novelty windows, erosion streak, gap log); re-passing the
SAME id resumes it. Pins, discards, comparisons and the `materialized.json` ledger always survive — the
knowledge graph, not the archive, is the durable store.

### 1B.1 `kg_diverge_init(project, axes=None, seed=0, session=None)`

Begin/resume a divergence session for a brief. `axes` resolves by cascade: an inline axes dict → a path or
shipped template name (`pack/domains/*.yaml`, `pack/domains/examples/*.yaml`) → `None`, which prefers the
pack's `divergence:` section and falls back to `pack/domains/generic.yaml`. Also syncs materialized fates
(see §1B.7): any previously materialized pin whose canon node/edge was actively **falsified** (`failed`) is
folded into this brief's **discards** (unified negative memory, I8) and reported; a merely-unsupported
(`rejected`) pin — the expected state of a novel idea with no in-source span yet — stays recoverable in the
lane and is **not** discarded.

```json
{"ok": true, "domain": "generic", "reset": false, "session_id": "sess-…", "new_session": true,
 "axes": [{"name": "angle", "type": "categorical"}, {"name": "scope", "type": "categorical"},
          {"name": "form", "type": "categorical"},
          {"name": "boldness", "type": "continuous", "range": [0.0, 1.0]},
          {"name": "feasibility", "type": "continuous", "range": [0.0, 1.0]},
          {"name": "mechanism", "type": "open", "primary_novelty": true}],
 "unit_of_generation": "idea", "candidates_per_generation": 12,
 "paths": {"state_dir": "…/.kg/diverge/cold-brew-launch"}, "materialized_failures_discarded": []}
```

`axes` is the resolved geometry: write every candidate's `descriptor` with exactly these names (the
`open` axis is the mechanism). There is no template file to open for it.

### 1B.2 `kg_diverge_ingest(project, candidates, axes=None, seed=0, cliches=None)`

One divergence cycle: embed → near-duplicate dedupe → MAP-Elites placement → k-NN novelty → DPP slate,
with the monitor reading the round. Candidate shape (see `/burgess:kg-diverge` step 6):
`{id, text, explanation?, descriptor: {<axis>: value, …, mechanism: "…"}, fitness?, genealogy: {operator_id, parents}}`.
`explanation` (0.19.6) is the two or three plain lines, with a concrete example, that you show the user. The
record keeps it, a slate item returns it, and `kg_diverge_export` prints it; it is never embedded, so it
cannot move an idea. Each record also notes its `batch` and the batches whose slate showed it (`slated_in`),
for the export.

`cliches` (0.20.0), sent with the first ingest, is the cliché map of `/burgess:kg-diverge` step 3:
`{"avoided": [text, …], "held_out": [text, …]}`, at most six of each, one plain sentence each. The engine
numbers them `o1`, `o2`, … (avoided first), stores them in `session/cliches.json` (replacing any earlier map
of the session), and adds `cliches_stored` to the result. Nothing in the geometry reads them: the slate, the
parents and the monitor are the same with or without them (tested). A malformed map is an error, raised
before any state is touched.

```json
{"slate": [{"id": "c3", "text": "…", "coords": {"angle": "…"}, "niche_id": "…", "novelty": 0.41,
            "mechanism_novelty": 0.38, "fitness": 0.8}],
 "ask_pairs": [["c3", "c7"]], "ask_policy": "refine",
 "monitor": {"collapsing": false, "under_generation": false, "variety_eroding": false,
             "mean_cosine": 0.34, "entropy": 0.82},
 "slate_ids": ["c3", "c7"], "slate_mechanism_novelty": 0.44,
 "open_axis": {"frozen": false, "n": 9}}
```

**Candidate ids are PRIMARY KEYS** — they key the archive, both embedding stores, and preference memory.
Unique **within a batch**, and unique **for the life of the project** unless you resubmit a candidate
byte-for-byte (a verbatim retry is a harmless no-op that dedup drops). Reusing an id under different text
is a hard error: it would silently rewrite the archived idea that id already names. Prefix ids with the
generation (`g2-c3`) rather than restarting a counter each round.

Field honesty: `slate_ids` is the id list of the slate items, NOT breeding parents — it honors neither
pins nor discards, so never breed from it; use `kg_diverge_parents` for that. `novelty` is mean k-NN
cosine distance (k=5) to THIS SESSION's own ideas — a variety proxy,
never originality against the world; `mechanism_novelty` is the same for the open-axis value. `ask_pairs`
come from the slate, except that when no slate pair names an idea of this round, the last pair gives way
to one that does — possibly an idea the slate left out (0.19.7). `monitor`
flags are advisory notices (react per `/burgess:kg-diverge` step 9). When the axes set `engine: {gap_probe: true}`
the result also carries a `surface_mechanism_gap` block (measurement only).

### 1B.3 `kg_diverge_remember(project, event)`

Append one durable preference event: `{"type": "pin", "id": …}` · `{"type": "discard", "id": …}` ·
`{"type": "comparison", "winner": …, "loser": …}`. Pins are the strongest signal (always parents, recalled
across sessions, materializable); a discard is durable negative memory (never re-slated, never bred from;
re-pinning un-discards). A comparison does not move the slate or the parents: the engine only stops
asking a pair already answered and tallies the answers in `kg_diverge_recall` (`win_counts`,
`preferred_values`). The answers reach the next round through the generator. Returns `{ok, type, …}`.

### 1B.4 `kg_diverge_parents(project, k=4, seed=0)`

Stepping stones for the next generation — pins ALWAYS included, discards NEVER, and at least two diverse
archive elites however many pins there are, fewer only when the archive has fewer (0.19.7). `k` is the
total, and the set grows past it when needed to hold every pin and two diverse elites, so leave it alone.
The diverse elites are drawn far from the pins and from each other, keyed by `seed`
and the generation: within a round the same call returns the same parents, and the next round draws
again. Returns `{"parents": [{id, text, coords, niche_id, novelty, pinned}]}`. This `parents` is
the real one (the ingest response's `slate_ids` is not). An optional `stale_pins` + `stale_pins_note` pair
appears when a pinned id has no candidate record — an axes change resets the geometry but keeps preference
memory, so the pin survives its idea. Drop those ids; there is nothing to breed from. The keys are absent
(not empty) when every pin resolves.

### 1B.5 `kg_diverge_metrics(project)`

Archive health: `{entropy, mean_cosine, coverage, n, mechanism_spread, mechanism_n, open_axis}` (+
`gap_log` when the gap probe is on).

### 1B.6 `kg_diverge_recall(project, k=10, reexamine=None)`

The brief's preference memory, for injection into generation: `{domain, preferences, pins, discards,
summary: {n_comparisons, win_counts, preferred_values}}`, plus the session context: `session_id` (the
session the archive belongs to, the one `init` last began or resumed), `seed`, `axes`,
`unit_of_generation`, `candidates_per_generation` and the session's `cliches` (each `{id, text, role}`;
each key left out when the state has none). Show a `held_out` cliché only when the session ends. After a
compaction in the same chat this one call restores what the next round needs; never read `.kg/diverge/`
files for it. Like `init`, it first syncs materialized fates
(I8) — generate AWAY from `discards`, FROM `pins`. On a source change it also surfaces `failed`-fated
discards under `reexaminable_discards` (the divergence mirror of the graph R3-mirror; SURFACE-ONLY, never
auto-un-sealed). Pass `reexamine=[candidate_ids]` to EXPLICITLY un-seal those candidates — each drops from
`discards` and has its failure fate cleared, returning to the proposal pool (reported under
`reexamined_unsealed`); un-sealing never changes a graph verdict.

### 1B.7 `kg_diverge_materialize(project, candidate_ids=None, node_type="claim", edges=None, cliche_ids=None)`

The **explicit door** from divergence into the graph — the ONLY way an idea leaves `.kg/diverge/`.
Materializes pinned ideas (`candidate_ids` defaults to all pins) as nodes routed **exclusively through the
propose lane** (`kg_propose` → the same boundary as every write):

- Only **pinned** candidates with a live session record materialize; a non-pinned id is `refused`
  (`not-pinned`); a pin whose session record is gone (I10) is `skipped` (`no-session-record` — re-ingest it
  first). To carry an idea the user names that is not pinned, pin it first with `kg_diverge_remember`;
  that pin also makes it a parent of every later round and lifts its discard (latest event wins).
- Node id `idea-<project-slug>-<candidate-slug>`; the body carries the full lineage:
  `[diverge] pinned candidate=<id> brief=<project> session=<id> mechanism=<open-axis value>
  operator=<genealogy.operator_id>`.
- The boundary forces `provenance=hypothesized`, `epistemic_state=unverified`, `authored_by=agent` — a
  materialized pin earns promotion only via `kg_ground` with support, like any hypothesis.
- Optional `edges` link the new nodes to existing ones and transit the same boundary (text-claim provenance
  refused, forged verdicts stripped).
- The `materialized.json` ledger maps each candidate to its written nodes/edges; only if grounding later
  **falsifies** one (`failed`) does the next `init`/`recall` auto-discard it from the brief (I8) — a
  merely-unsupported (`rejected`) pin, the expected state of a novel idea with no in-source span yet, stays
  recoverable in the lane. The sync only *reads* verdicts — verdicts stay `kg_ground`'s monopoly.
- When a source is already configured and ≥1 pin materialized, the result carries an advisory-only
  `advisory` string (grounding these novel pins against the existing source will correctly leave them
  `unverified` until sources are added) — never a disposition, verdict, or ledger write.
- **Clichés (0.20.0).** `cliche_ids` (e.g. `["o1", "o4"]`) carries clichés of the session's map through the
  same door, on the user's word. Each becomes `cliche-<project-slug>-<id>`, its body ending with
  `[cliche] id=<id> role=<avoided|held_out> brief=<project> session=<id>`. An id not in the map is `refused`
  (`unknown-cliche`). A cliché needs no pin, and a call with `cliche_ids` and no `candidate_ids` carries no
  pins. Its results carry `cliche` instead of `candidate`. The ledger keeps it under `_cliches`, which the
  fate sync skips, so a failed cliché never joins the brief's discards. The grounder treats it as an
  ordinary hypothesis — grounded with support, `rejected` without (the user's choice, 2026-11-21) — and the
  result says so in `cliche_advisory`.

```json
{"ok": true, "materialized": 2,
 "results": [{"candidate": "c3", "status": "materialized", "node": "idea-cold-brew-launch-c3"},
             {"candidate": "c9", "status": "skipped", "reason": "no-session-record"}],
 "advisory": "A source is already configured. Grounding these pins will correctly leave a novel idea unverified…",
 "propose": {"dispositions": {"ACCEPTED": 2}, "…": "…"}}
```

### 1B.8 `kg_diverge_export(project, brief="")`

Writes every idea of the brief's **current session** to one Markdown file and returns where (0.19.6). Call
it when the user ends the session or asks to save the ideas; never assemble the file yourself (Bash, a
script, a Write of the whole text, or reading `.kg/diverge/` or the transcript — in the 2026-11-19 field
run that took ten permission prompts and about two hours).

- Per idea: its text, its `explanation`, its descriptor (the open axis first), operator and parents, the
  batch it arrived in and the batches whose slate showed it (or "never on the slate"), and what the user
  did with it: pinned, discarded, beat / lost to in a comparison, in the graph as a materialized node.
  `brief` heads the file. A pin from an earlier session is named without text: its record ended with
  that session (I10).
- When the session stored a cliché map, a `## Clichés` section lists it before the ideas, and the result's
  `cliches` gives each `{id, text, role[, closest][, node]}`. Only a `held_out` cliché carries `closest`:
  the three ideas nearest to it by cosine similarity in this session's embedding space (the cliché embedded
  with the session's own embedder). The avoided ones steered the generation, so a distance to them would
  only grade the steering. Advisory: it ranks nothing, and an embedder that differs from the session's or
  fails to load gives `closest: []` instead of an error. `node` names a materialized cliché.
- The file is `.kg/diverge/<brief-slug>/ideas-<brief-slug>-<session>.md`: one per session (a second
  export in the same session replaces it), never in the project root. A directory source is every
  top-level `.md`, so in a project that is its own source folder an export there would be read by
  `/burgess:kg-build` as a source document. The engine never writes a path you name; to put the file
  elsewhere, copy it with one command, which asks the user once.
- Changes no state, and nothing reads the file back. Near-duplicates the ingest set aside were never
  recorded, so they are not in it. A project never inited, or whose session id was replaced, raises an
  error that says so.

```json
{"ok": true, "path": "C:\\…\\.kg\\diverge\\cold-brew-launch\\ideas-cold-brew-launch-sess-20261120-ab12.md",
 "ideas": 36, "batches": 3, "pinned": ["c1e", "c3a"], "discarded": ["c2g"], "comparisons": 4,
 "unexplained": [], "session_id": "sess-20261120-ab12", "bytes": 28114}
```

`unexplained` lists ideas ingested without an `explanation`. The CLI twin is
`python -m kg_engine.divergence export --project <slug> [--brief "…"]`.

### Engine constants (drift-guarded by tests)

- **Embedder** (`KG_DIVERGE_EMBEDDER`): `static` (default) = model2vec `minishlab/potion-multilingual-128M`
  — 256-dim, CPU/numpy, torch-free, ~120 MB, lazily downloaded, cached under `$HF_HOME` (pointed at
  `$KG_DATA/models` when unset); `hash` = deterministic 512-dim char-n-gram vectorizer (tests/offline
  escape hatch — an unavailable static model raises with instructions, it never silently degrades);
  `local` = sentence-transformers `BAAI/bge-small-en-v1.5` (384-dim, needs torch). Embedding widths may
  not mix within a project.
- **Geometry:** k-NN novelty `k=5`; near-duplicate cosine tau per embedder (static 0.93, hash 0.92,
  local 0.94); DPP pool cap 200; novelty-reference cap 500; open-axis Voronoi niches 24, partition frozen
  once 2×24 = 48 mechanisms accumulate; continuous axes bin 5 by default.
- **Judge bounds:** fitness blended at weight 0.3, affine-rescaled and clipped to a [0.7, 1.3] multiplier —
  it sharpens within-niche ordering, it can never prune variety.
- **Monitor:** mean-cosine threshold 0.55 (absolute fallback) / entropy threshold 0.50 (≥3 occupied
  niches) / relative flag at baseline+0.15 with absolute ceiling 0.80, rolling window 5, min baseline 2;
  variety-erosion sensor: window 5, fires at ≥1.5× decay acceleration for 2 consecutive generations;
  `under_generation` below 0.6× the per-generation target.
- Per-domain overrides live in the axes spec's `engine:` block — schema + defaults table in
  `pack/domains/_schema.md`.
- **Env:** `KG_DIVERGE_EMBEDDER` (provider), `KG_DIVERGE_HOME` (state base override),
  `KG_DIVERGE_DEBUG` (tracebacks).

---

## 2 · Deterministic CLI surface

Run via Bash, with the engine's own interpreter. `scripts/engine_python.mjs` prints it, resolved the way the
plugin's launcher resolves it (`.venv\Scripts\python.exe` on Windows, `.venv/bin/python` elsewhere); each Bash
call is a fresh shell, so resolve it in the same call that uses it:

```bash
PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1
export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts"
```

(In a development checkout, `uv run` from the repo root works too.) The `kg_engine.*` module CLIs require
that `PYTHONPATH`; `f4_probe.py` is a standalone script. A source path may be one file or a folder of
`.md`/`.txt` documents; the CLIs read it the way the projector does. None of these gate the pipeline — each
prints a number + verdict; the orchestration logs it and proceeds (§4).

### 2.1 `f4_probe.py` — extraction precision scorer

Operates on a derived `graph.json` (NetworkX node-link; reads `links` or `edges`). Four subcommands.

```bash
python scripts/f4_probe.py summary "$GRAPH"                     # shape of the graph
python scripts/f4_probe.py sheet   "$GRAPH" --n 80 --out labels.csv   # sample edges to label
python scripts/f4_probe.py fill    labels.csv labels.json       # write an annotator's labels into the sheet
python scripts/f4_probe.py score   labels.csv                  # precision / astrology / span-support
```

- **`summary <graph.json>`** — prints node/edge counts, nodes by `file_type`, edges by `confidence`
  (`EXTRACTED|INFERRED|AMBIGUOUS`), top relations, the `INFERRED` `confidence_score` distribution
  (min/median/max), and the count of *judged* edges (`INFERRED+AMBIGUOUS`) — the precision-relevant slice.
- **`sheet <graph.json> --n <N> --out <csv>`** — random-samples (seed 42) up to `N` non-`EXTRACTED` edges into
  a CSV with columns `edge_id, source_label, target_label, relation, confidence, confidence_score,
  source_file, verdict, span_found, notes`. Add `--include-extracted` to also sample deterministic edges.
  An annotator then labels every row:
  - `verdict` ∈ **`correct | fabricated | vague | wrong_type`** (the only allowed labels).
  - `span_found` ∈ **`y | n`** (the span-present check).
- **`fill <labels.csv> <labels.json>`** (0.11.7) — writes an annotator's labels into the sheet. The labels
  file is one JSON object, `{"<edge_id>": {"verdict": …, "span_found": "y"|"n", "notes": …}}`, which the
  annotator writes with Claude Code's Write tool: it has no shell. The fill is all or nothing. A row with no
  entry, an entry for an edge the sheet lacks, a verdict outside the vocabulary or a `span_found` other than
  yes/no leaves the sheet unchanged and lists the problems.
- **`score <labels.csv>`** — reads rows with a filled `verdict` and prints:
  - `PRECISION (correct / labeled)` — **exit gate is `>= 0.70`**.
  - `astrology rate (fabricated+vague)` — the grounding risk, measured.
  - `span-support rate (span_found=y)` — the span-present rate.
  - verdict breakdown, precision per relation (n>=3), and confidence calibration (mean `confidence_score` for
    correct vs incorrect; a gap `>= 0.10` means the score tracks correctness, else it is "vocabulary, not
    grounding").

`vague` is the generality confound made measurable: a relation "true" only because it is generic/unfalsifiable.

### 2.2 `python -m kg_engine.pack` — pack validation + glossary coverage

```bash
python -m kg_engine.pack validate pack/pack.yaml            # PackContract validation only
python -m kg_engine.pack validate pack/pack.yaml examples/source.md   # validate + coverage
python -m kg_engine.pack coverage pack/pack.yaml examples/source.md   # coverage (source required)
```

`validate` loads the YAML as a `PackContract` (Pydantic, `extra="forbid"`; `node_types`/`edge_types` must be
non-empty + unique). On success prints `PACK OK: domain=… node_types=N edge_types=M glossary=K`; on failure
`PACK INVALID: <error>` to stderr (exit 1). If a source path is given (always for `coverage`), also prints
`coverage(...)`:

```
PACK OK: domain='conceptual theory' node_types=6 edge_types=10 glossary=12
  source_defined_terms: 10
  glossary_terms: 12
  source_terms_in_glossary: 10
  source_coverage: 1.0
  glossary_grounded_in_source: 1.0
```

- `source_coverage` — fraction of the source's *defined terms* (bold/`code`/quoted phrases) present in the
  glossary.
- `glossary_grounded_in_source` — fraction of glossary terms that actually occur in the source (don't invent
  vocabulary the source never uses).

### 2.3 `python -m kg_engine.harness` — agreement · specificity · ideation · convergence · writers · legacy-log · rag-slices

Deterministic measurement over data the subagents produce. The first four read/write JSON: if the optional
path is missing, each falls back to a built-in demo and notes it on stderr. `writers` and `legacy-log`
(0.11.7) and `rag-slices` (0.11.8) take their paths as required arguments and have no demo.

Words are runs of Unicode letters (0.11.8). Through 0.11.7 the tokenizer that feeds IDF, node specificity
and ideation scoring knew only ASCII letters, so "revisión" counted as "revisi" and "más" not at all.

#### `agreement [label_sets.json]`

Nominal **Krippendorff's alpha** across independent coders. **Input JSON is a LIST of coder dicts**, one per
coder, mapping `unit_id -> label`; units rated by `<2` coders are ignored. Labels are the f4_probe verdict
vocabulary `correct | fabricated | vague | wrong_type`.

```json
[
  {"e1": "correct", "e2": "vague", "e3": "correct"},
  {"e1": "correct", "e2": "vague", "e3": "fabricated"}
]
```

Prints `krippendorff_alpha: <a>` and `verdict: RELIABLE (>=0.67)` or `BELOW THRESHOLD — grounding signal stays
advisory`. Threshold **`>= 0.67`** = reliable inter-annotator agreement.

#### `specificity [graph.json] [source.md]`

The **bridge-metric gate** (§1.4/§1.6). Compares specificity-weighted betweenness vs raw degree vs raw
betweenness over the derived graph, using IDF seeds from the source corpus (or a demo corpus). Args default to
`derived/graph.json` and the demo corpus. Emits JSON:

```json
{
  "n": 24,
  "mean_specificity": 1.42,
  "specificity_spread": 1.9,
  "betweenness_leader_specificity": 0.91,
  "top_raw_betweenness": ["system", "idea", "specificity"],
  "top_specificity_weighted": ["specificity", "betweenness", "reconciler"],
  "rank_churn": 0.4,
  "generality_confound_detected": true,
  "gate_on": true,
  "verdict": "specificity-weighting earns its place — gate ON"
}
```

`gate_on` is `true` only when the generality confound is detected (raw-betweenness leaders are vaguer than
average), rank churn `> 0.2`, **and** the node specificities actually spread (a degenerate corpus where every specificity is equal keeps the gate closed). Until this returns `gate_on:true` on real data, the specificity-weighted
bridge metric stays advisory and `kg_context` exposes only the structural-bridge heuristic. (Graphs with
`< 3` nodes return `{"gate_on": false, "reason": "graph too small", "n": …}`.)

#### `ideation [outputs.json] [source]`

Scores the value-of-the-graph experiment (method 0.12.0, pre-declared in `docs/fusion/EXPERIMENT.md`).
**Input JSON**: one list of ideas per arm, idea *k* answering prompt *k*:

```json
{
  "outputs": {
    "control": ["A is connected to B.", "…"],
    "graph":   ["A bridges B and C because entropy grounds time.", "…"],
    "rag":     ["A relates to B somehow.", "…"]
  },
  "source": "<full source text, used only when no source path is given>"
}
```

(`source` optional; if the top-level object isn't `{outputs, source}` it is treated as the
outputs-by-condition map directly. A source path as the second argument wins, and its documents are indexed
one at a time.)

**Per idea:**
- **novelty**: 1 − the share of its word trigrams that occur in the source.
- **support**: for each sentence of four or more words with two or more key terms (words longer than five
  characters, compared by stem: folded, first six characters), the share of its terms' IDF weight held by
  terms the source contains. IDF is in BM25 form over the source's paragraphs, and a term the source lacks
  has the highest weight. An idea's support is the mean over its sentences, and 0 with none.
- **grounded novelty**: novelty × support.

**Per arm**, the `table` gives `n, diversity, novelty, support, grounded_novelty, utility, unsupported_rate`.
`unsupported_rate` is the share of sentences with support below 0.5.

**Pairs:**
- `comparisons` gives, per pre-declared pair, the prompt-by-prompt wins, losses and ties (a difference within
  0.005 is a tie), the wins `needed` and the median difference.
- `needed` is the fewest wins out of `n` that a one-sided sign test at 5 % accepts: 10 of 12, none below five
  prompts.
- The verdicts: `verdict` (graph vs rag, always present: "insufficient data" without both), `control_verdict`
  (graph vs control), `generate_verdict` (graph+generate vs graph), `dpp_verdict` (graph+generate+dpp vs
  graph+generate) and `lightrag_verdict` (graph vs lightrag). Each reads:
  - `"<X> beat <Y> on grounded novelty in <w> of <n> prompts"`;
  - `"<X> did NOT clearly beat <Y> on grounded novelty (<w> of <n> prompts; <k> needed)"`;
  - a too-few-prompts sentence;
  - `"not measured: …"`.

**`support_check`** (`{rag, control, gap, min_gap, valid, probe_drop, probes}`) is the instrument check.
`rag`'s mean support must exceed `control`'s by 0.10, or support measures nothing on this source, and every
verdict reads "not measured". `probe_drop` is information: the mean support lost when each judged sentence's
first key term is replaced by an invented one.

**`caveats`** is a list of plain sentences naming what this run could not measure:
- a failed support check;
- an unchecked one, without a `rag` or `control` arm;
- utility, when no arm uses an English marker.

The verdicts do not change with them.

Through 0.11.x the verdict needed graph ≥ control on novelty, measured from a source control never sees. Its
any-of-three-words guard let 140/143, 171/173 and 181/181 invented-word probes through on the Windows corpus.

#### `rag-slices <prompts> <source> <out_dir> [budget_tokens]` (0.11.8)

Builds the `rag` arm's context for `/burgess:kg-experiment`, the same way on every run. For each prompt it ranks the
source's paragraphs by **BM25** against the prompt, with accents folded and no stopword list or stemming, and
takes the best while they fit in `budget_tokens` (default 2000, the graph arm's `kg_context` budget, at four
characters a token). A heading stays with the paragraph after it, and a paragraph longer than 1,200
characters is cut at line, then word boundaries.
- It writes `01.md`, `02.md`, … (one per prompt, the passages best first, no scores) and `index.json`
  (each file's prompt, and its passages' documents, scores and lengths) into `out_dir`.
- `prompts` is read like `lightrag_arm`'s: a JSON array, a `{"prompts": [...]}` object, or one per line.
- It refuses an `out_dir` the source reads its documents from, where the files would become documents.
- It prints how many passages each prompt got, and from how many documents.

Through 0.11.7 the kg-evaluator subagent retrieved this context itself. On the Windows corpus it wrote a
retrieval script and ran it through a shell, and no later run could reproduce what it picked.

#### `evaluator-order <outputs>` (0.13.1)

Checks that the kg-evaluator wrote its two drafts in order, beside `outputs`:
- `<outputs>.control.json`, holding the control answers, before its first graph call;
- `<outputs>.graph.json`, holding control and the three graph-based arms, before it read any rag passage.

`verified` is true when each file predates the next and `outputs` carries both drafts' answers unchanged.
Otherwise `problems` names what failed: a missing or unreadable draft, an answer that changed, or the files
out of order. It prints JSON and always exits 0; `/burgess:kg-experiment` logs a failure as a caveat.

#### `judge-packets <outputs> <prompts> <source> <controls> <out_dir>` and `judge-aggregate <judge_dir> [outputs]` (0.13.0)

The deterministic half of `/burgess:kg-experiment --judge`, in `scripts/kg_engine/judge.py`.

**`judge-packets`** writes one packet per prompt to `out_dir/packets/NN.md`.
- A packet holds every arm's idea and the two controls from `controls` (`{"decoys": [...], "positives": [...]}`),
  labelled A, B, …, in a seed-7 order rotated by one position per prompt.
- Each item carries its own evidence, under the third pilot's rule:
  - sentences are split into clauses at `, ; :` and before a coordinating conjunction;
  - each clause's four best BM25 passages are taken in rounds;
  - then one passage is added for each figure or name of the item that the source holds and the evidence still
    lacks;
  - an item carries at most 20,000 characters.
- The mapping from labels to items goes to `out_dir/private/mapping.json`.
- First it checks both controls of every prompt. The decoy must cite a name or figure the source lacks. The
  positive control must cite nothing the source lacks, hold two or more of its figures or names, carry all of
  them in its own evidence, and draw them from at least two documents.
- If a control fails, it exits 3 and writes no packet. The failures are printed and saved in
  `private/checks.json`.

**`judge-aggregate`** reads the `kg-judge` verdicts in `judge_dir/verdicts/NN.json`, each shaped like
`{"scores": {"A": {"grounded": 1-5, "useful": 1-5}, …}, "ranking": [...], "notes": "..."}`, and prints JSON.
- **`checks`:**
  - V1: the decoy is the least grounded item;
  - V3: the positive control scores 4 or more;
  - V1 and V3 must each hold in the prompts the sign test needs, 10 of 12;
  - V2: the arms' mean grounded score beats the decoys' by 1.0.
- **The verdicts**, keyed like `harness ideation`'s, decided on the judges' rankings. Each reads "not measured"
  when a check fails or fewer than five prompts were judged.
- **Reported alongside:** `means`, `mean_rank`, `first_by_label`, `words` and `problems`. A missing or malformed
  verdict drops its prompt.

#### `convergence [generation_labels.json]`

The **convergence gate** for `kg_generate`'s advisory tally. Input: labeled generated edges, each with its
`convergence` count (distinct mechanisms that proposed it) and its grounding outcome. Compares the grounding
rate of the HIGH band (`convergence >= 2`) vs the LOW band (`== 1`); `gate_on` is `true` only when the high
band grounds at a rate more than **0.10** above the low band with enough samples per band. Until then the
tally stays a display-only prior — it never reorders the grounding queue.

#### `writers <labels.csv> <project>` (0.11.7)

Splits a filled f4_probe sheet two ways, reading each labeled edge in the project's canon.
- **By writer**, from the mark its notes open with:
  - `extractor`: a `/burgess:kg-build` extraction;
  - `lead`: written by `/burgess:kg-build --leads` from a grounder's lead;
  - `counter-edge`: an adversarial pass of `/burgess:kg-ground`;
  - `proposal`: `/burgess:kg-generate`.
- **By the grounding verdict** each edge holds now.

It prints labeled / correct / precision per row, then lists the edges labeled other than `correct`, each
with its writer and verdict.

The canon keeps every edge since its first build and does not record which plugin version wrote one. So an
error in the sample shows how its writer worked then. `/burgess:kg-eval` checks a refinement against the current
contract before recommending it.

#### `legacy-log <project> <source>` (0.11.7)

Prints a note when a `PROGRESS.md` at the top of the project is one of the source's documents, and nothing
otherwise.
- Through 0.11.6, `/burgess:kg-eval` and `/burgess:kg-experiment` kept their log there. Since 0.11.7 they write
  `<project>/.kg/PROGRESS.md`, which `SourceSet` never reads.
- A source folder's top-level `.md`/`.txt` files are its documents. So an old log in the source would be
  extracted by `/burgess:kg-build` and read as source by `/burgess:kg-experiment`.
- It never moves or deletes the file.

### 2.4 `python -m kg_engine.divergence` — the divergence engine, no MCP needed

The same engine the `kg_diverge_*` tools call, as a CLI (dev/debug; `/burgess:kg-diverge` uses the tools):

```bash
python -m kg_engine.divergence init-project --project <slug> --axes <dict|path|template> [--seed N] [--session ID]
python -m kg_engine.divergence ingest   --project <slug> --candidates <json> --axes <…> [--seed N]
python -m kg_engine.divergence recall   --project <slug> [--k 10]
python -m kg_engine.divergence remember --project <slug> --event <json>
python -m kg_engine.divergence parents  --project <slug> [--k 4] [--seed N]
python -m kg_engine.divergence metrics  --project <slug>
python -m kg_engine.divergence export   --project <slug> [--brief "…"]  # every idea of the session → .md (§1B.8)
python -m kg_engine.divergence paths    --project <slug>          # print resolved state paths
python -m kg_engine.divergence selftest [--live] [--seed N]       # exit 1 on failure
python -m kg_engine.divergence import-cambrian --project <slug> [--from <dir>]
```

**`selftest`** is the engine's offline correctness contract (hash embedder unless `--live`; also run by the
suite's `selftest`-marked e2e test). `ok` requires ALL of:

- **variety gate** — the engine beats a single-shot baseline on mean pairwise distance (margin +0.10) AND
  Vendi score (margin +0.5) AND niche entropy; the DPP slate beats taking the first N (margin +0.01,
  averaged over 3 seeds); on a uniform pool the DPP does not regress below a random subset (eps 0.02,
  50 trials); a higher within-niche fitness wins its niche (and swapping flips the elite);
- **collapse reversal** — a deliberately samey generation trips `collapsing: true`, and the next diverse
  one recovers with a lower mean cosine;
- **files written** — the session state files all exist afterwards.

`import-cambrian` maps a pre-fusion project's preference memory (pins, discards, comparisons — per domain,
read-only on the source, default `~/.cambrian/<project>` or `$CAMBRIAN_HOME`) into
`.kg/diverge/<slug>/memory/`. Geometry files and `meta.json`/`axes.json` are deliberately NOT imported
(session-ephemeral by design; re-created by `init`) and are reported as `skipped` so nothing disappears
silently. Report: `{ok, source, target, imported: {<domain>: {pins, discards, comparisons}}, skipped,
errors}`.

---

## 3 · Quick map

| You want to… | Use |
|---|---|
| check the server is up / pack loaded | `kg_ping()` |
| write extracted nodes/edges | `kg_write(payload)` (boundary, §1.5) |
| set a verdict (grounded/rejected/failed/obsolete) | `kg_ground(...)` — the **only** way |
| fix a node id everywhere | `kg_rename(old, new)` (strict — refuses if `new` exists) |
| merge two nodes that name the same concept | `kg_merge(from, into)` (dedups edges, keeps negative info) |
| cheap counts (`digest=true` adds a hash of the whole canon) | `kg_metrics(digest=?)` |
| projection-free status / resume a partial build | `kg_status()` |
| browse by type/relation/state, ranked by degree | `query_graph(...)` |
| find nodes and edges by what they say (edgeless nodes too) | `query_graph(text=...)` |
| one node + its edges | `get_node(id)` |
| a node's edges (list) | `get_neighbors(id, relation=?)` |
| connect two nodes (structural) | `shortest_path(a, b)` |
| connect concepts over GROUNDED edges only (+ advisory leap) | `kg_explain_path(nodes)` |
| budgeted, grounding-aware context, best match first (+ failures + bridges) | `kg_context(query=?, budget=?)` |
| propose hypothesized candidates (the offensive lane) | `kg_propose(payload)` |
| generate structural idea candidates (read-only) | `kg_generate(mechanism=?, k=?, second_graph=?, dpp=?, second_construction=?)` |
| run a §8 endo operation (collapse/explode/regroup/open) | `kg_operate(op, …)` |
| score the §14 absorption window | `kg_absorption()` |
| record a `/burgess:kg-generate` run in the absorption ledger | `kg_record_generation(nodes)` |
| start/resume a divergence session for a brief | `kg_diverge_init(project, axes=?, session=?)` |
| run one divergence cycle (embed → slate → monitor) | `kg_diverge_ingest(project, candidates, …)` |
| record a pin / discard / A-vs-B answer | `kg_diverge_remember(project, event)` |
| diverse stepping stones (pins in, discards out) | `kg_diverge_parents(project)` |
| archive health / gap log | `kg_diverge_metrics(project)` |
| recall a brief's pins/discards/comparisons | `kg_diverge_recall(project)` |
| carry pinned ideas, or mapped clichés, into the hypothesized lane | `kg_diverge_materialize(project, …)` |
| save every idea of a diverge session to a file | `kg_diverge_export(project, brief)` |
| score extraction precision | `f4_probe.py summary|sheet|fill|score` |
| who wrote the sampled edges, and their verdicts | `kg_engine.harness writers` |
| validate the pack / glossary coverage | `kg_engine.pack validate|coverage` |
| inter-annotator agreement | `kg_engine.harness agreement` |
| bridge-metric gate verdict | `kg_engine.harness specificity` |
| value-of-the-graph experiment | `kg_engine.harness ideation` |
| the rag arm's passages for an ideation run | `kg_engine.harness rag-slices` |
| divergence engine offline correctness contract | `kg_engine.divergence selftest` |
