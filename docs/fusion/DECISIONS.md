# Decisions Log

Every kickoff answer, every default applied on timeout, every judgment call. One-line rationale each.

## Kickoff questionnaire (2026-07-02, answered live by user via AskUserQuestion)

- **Q1 Plugin name = `Burgess`** — user selected the recommended option; matches the pre-existing repo/GitHub name. (Burgess Shale: where the Cambrian explosion's forms were preserved — divergence + grounding in one word.)
- **Q2 Command prefix = keep `/kg-*`** — user selected recommended; continuity for donor users.
- **Q3 Divergence command = `/kg-diverge`** — **user's active choice over the recommended `/kg-ideate`.** Applied consistently: command file `commands/kg-diverge.md`; project-local session state under `.kg/diverge/<brief-slug>/`. Wherever FUSION_PLAN.md says `/kg-ideate` or `.kg/ideate/`, read `/kg-diverge` and `.kg/diverge/`.
- **Q4 Dev CLI = yes** — keep `python -m kg_engine.divergence`; zero-cost, aids debugging, lets the divergence selftest run outside MCP.
- **Q5 Materialization = explicit action** — user selected recommended; nothing enters the graph implicitly.
- **Q6 First version = `0.1.0`** — user selected recommended; honest maturity signal.

## Stage 0 judgment calls

- **Deleted stray `FUSION_PLAN.md:Zone.Identifier`** (WSL/NTFS download-zone metadata artifact, 25 bytes, not project content) and gitignored the pattern.
- **Baseline method:** donor suites run on pristine `git archive HEAD` copies inside the session scratchpad — donor trees never executed in (I11). Sproutgraph's `pyproject.toml` already sets `addopts = "-q"`; adding another `-q` yields `-qq` which suppresses the pytest summary line, so the canonical baseline invocation is `uv run --extra dev pytest tests/ -p no:cacheprovider` (single `-q` effective).
- **I11 gate implementation:** cross-platform Python script `scripts/check_donors_clean.py` reading pins from `scripts/donor_pins.json`; installed locally as `.git/hooks/pre-commit` (hook is local-only by git design; the script itself is committed and must be run before every stage commit per protocol §6.4).

## Inventory-driven adaptations (D2: code wins over plan prose)

- **"Hypothesized" is a provenance, not an epistemic state** (model.py:33-50). Everywhere the plan says materialized pins get `epistemic_state: hypothesized`, Burgess implements `provenance: hypothesized, epistemic_state: unverified` — the donor's actual hypothesized lane.
- **No `annotations` field exists on Edge/Node.** The Stage-4 "pinned annotation" rides `Edge.notes` (plus the diverge-session back-reference), per INVENTORY discrepancy 2.
- **D1 uses the harness's own convention** (per D1's escape clause): the vendored experiment harness defines no RNG seeds — its convention is 12 fixed ideation prompts + blind shuffle/de-shuffle by the evaluator. Stage 6 measures arms over that convention; the D1 thresholds (median comparison, win-rate, noise band) apply over the 12 prompts.
- **Materialization front door:** the donor's hypothesized-lane public entry is `kg_propose` (a thin forced-provenance wrapper over `kg_write`, server.py:675). Stage-4 materialization goes through the propose lane — this **is** the "via kg_write exclusively" requirement in donor terms.

## Stage 1 judgment calls

- **"Loads locally in Claude Code" verified deterministically:** `claude plugin validate ./ --strict` (the CLI's own loadability gate) + a real MCP stdio handshake through the plugin's actual launch chain (`node scripts/launch_server.mjs` with the `.mcp.json` env contract): initialize → serverInfo.name=`burgess` → tools/list = 20 tools → `kg_ping` returns name=burgess v0.1.0. An interactive `claude --plugin-dir` session is listed in the final human handoff (it requires the `source_path` userConfig prompt, which is inherently interactive).
- **Vendored donor CI workflow** (`.github/workflows/ci.yml`) — two vendored tests require it (`test_ci_matrix_covers_windows_and_macos`, `test_ci_test_job_sets_up_node`) and it is donor-agnostic. Keeping it preserves baseline parity without test adaptations.
- **Engine pip-package name `kg-engine` kept** (not donor identity — it names the `/kg-*` engine); description + versions updated to Burgess 0.1.0 (validate_plugin enforces plugin.json ↔ `kg_engine.__version__` agreement, which caught the initial miss).
- **uv.lock not committed** — donor convention (gitignored; provisioning locks per machine); Burgess follows it.

## Stage 2 judgment calls

- **Whole-engine port at Stage 2** (all 15 Cambrian modules incl. state/pipeline/selftest, not just the math listed in the stage's task): porting the full package + its 226 tests front-loads the port risk into the stage whose firewall tests exist for exactly that; Stage 3 builds only the command/skill layer on top.
- **Env identity surface renamed like Stage 1's:** `CAMBRIAN_EMBEDDER/HOME/DEBUG/EMBED_API*` → `KG_DIVERGE_*`. Constants untouched (I6/I7, D2).
- **Session semantics (I10):** session boundary = `init-project`'s `session` id. Omitted id ⇒ fresh auto id ⇒ geometry wiped (ephemeral by default); passing the persisted id ⇒ resume. The /kg-diverge command (Stage 3) passes one id per chat session. Durable across sessions: pins, discards, comparisons, axes snapshot, project meta identity, session.json. Ephemeral: archive, candidates, embeddings, mech_embeddings, open_nicher + geometry-coupled meta series (cycles, cos_window, novelty_window, erosion_streak, gap_log).
- **Divergence deps are core deps with lazy guarded imports** (plan Stage 2 task 3): installed by default so /kg-diverge works out of the box; I9 enforced by guarded imports + actionable errors + `test_core_engine_works_with_divergence_deps_blocked` (full write→ground→query round-trip in a process where numpy/sklearn/model2vec imports are blocked).
- **Domain templates live at `pack/domains/`** (pack fragments per plan §3.2/Stage 3); resolver prefers `KG_PACK_PATH/../domains` so wheel installs work, falls back to the repo layout for dev/tests.
- **Divergence engine version = 0.1.0** (`kg_engine.divergence.__version__`) — it is Burgess's component now; lineage recorded here and in ATTRIBUTION.md.

## Stage 4 judgment calls

- **Materializer builds payloads itself** (idea → node with lineage in body) rather than passing arbitrary payloads through — the tool surface cannot be used to inject states/spans; the optional `edges` parameter is the deliberate adversarial surface and transits the full boundary.
- **Cross-session pins can't self-materialize:** a pin from an ended session has no candidate record (I10 wiped it); the tool reports `skipped: no-session-record` with guidance to re-ingest. Alternative (persisting full pin records) rejected: it would recreate a durable idea archive outside the graph, against I10's spirit.
- **"Unified negative memory" concretized without embeddings-as-truth:** the two stores stay one SEMANTIC store with two enforcement points — (a) grounding failures of materialized pins flow back into the brief's discards via the fate-sync (canon reads only); (b) kg_generate consults graph failure memory end-to-end (fixture-proven). Free-text discards that never touched the graph have no graph identity to unify on, by design.
- **Pin priority = documentation-level ordering** (kg-ground.md instructs grounding `[diverge] pinned` items first). kg_agenda cannot see notes (derived schema has no notes column, correctly — I4-adjacent); adding one for ordering was rejected as schema creep. Verdict neutrality is test-enforced either way.

## Stage 5 judgment calls

- **`divergence.dpp` lives in the pack's `divergence:` section** (config-only sections now valid; `dpp` must be boolean), with a per-call `dpp:` override on the kg_generate tool (None → pack default). Shipped default **off**; Stage 6's D1 decides the release default.
- **Hybrid descriptors:** semantic axis = batch k-NN novelty (the batch IS the session archive here — in-memory only, I10); structural axes = community intra/cross, endpoint graph distance (d1..d5/unreachable), grounded-mix of the endpoint neighborhood — all read off the projector's derived graph. Cliché distance (to the top-6 grounded hubs' labels — the graph's center) is a reported advisory field, not an axis, mirroring /kg-diverge's originality semantics.
- **Full ordering via greedy DPP with k=n-1** (select_diverse short-circuits at k≥n) + judge-bounded quality (0.3/[0.7,1.3] — the I6 constants, reused not re-tuned). Above the 200-candidate cap: geometric prefix + donor order for the rest (risk-register fallback).
- **I5 snapshot method:** clocks frozen (model/server/groundaudit `utcnow`), two identical projects, flag off vs on → identical candidate SETS; identical canonical proposals; grounding artifacts compared bit-for-bit (canon tree digest, audit-log bytes, falsification counters). All equal.
- **Perf budget actuals (Stage 5.5):** embed(200 candidates) = **0.008s**, DPP(200) = **0.004s** on CPU with the hash embedder — budget (single-digit seconds each) met with 3 orders of magnitude of headroom; the live model2vec embedder adds one-time model load (~seconds) which the cap + I9 degradation cover.
- **"Flag off and on" suite coverage:** the shipped default (off) governs the whole vendored suite; every on-path is exercised explicitly by tests/fusion/test_generate_geometry.py (snapshot, advisory failure, cap fallback, per-call override).

## Post-release (publishing, on explicit user instruction)

- **Plan Non-Goal 4 (no pushing) was overridden by the user** ("Do these steps yourself") after the local tag existed — push, GitHub Release, marketplace add + install executed by the agent; recorded here because it supersedes the plan's default, not its intent (the human decided).
- **Required-config gating confirmed in production:** the burgess MCP server does not start while the required `source_path` userConfig is unset (the first two headless smokes proved the gate). Set at user scope to `~/.claude/burgess-demo-source.md` (a persistent copy of `examples/source.md`) so the server runs out of the box; per-project reconfiguration via `/plugin configure burgess@sergiparpal` is the intended real-use path.

## Materialized-pin fate: only FALSIFIED folds into the brief's discards (2026-07-05)

- **Decision:** a materialized `/kg-diverge` pin folds into its brief's **permanent** discards only when it is actively **FALSIFIED** (`epistemic_state=failed`); a merely **UNSUPPORTED** pin (`rejected` — no verbatim span in the current source) does **not** fold and stays recoverable in the lane. Concretely, `KGEngine._sync_materialized_fates` now keys the fold on a new, deliberately narrower module constant `server.MATERIALIZED_DISCARD_STATES = {EpistemicState.FAILED}` instead of the global `model.FAILURE_STATES = {REJECTED, FAILED}`.
- **Bug it fixes:** the fold treated `rejected` (the *expected* state of a genuinely novel idea — novelty has no in-source span **by construction**) identically to `failed`, so grounding a novel pin against the original source permanently discarded it *because it was novel* — defeating the "ideas simply wait in the lane until you add sources" promise.
- **Why in the *consequence*, not the *verdict* (the rejected alternative):** refusing the `rejected` verdict at the `kg_ground` door for `[diverge]`-lineage items (a mirror of the existing `hypothesis-needs-support` promotion refusal) would make the *verdict itself* provenance-dependent, fighting the load-bearing verdict-neutrality invariant and its test. Instead the verdict stays honest and identical to any non-pin item's; only the diverge-brief-local, **state-keyed** (never provenance-keyed) discard consequence is narrowed. `test_pin_rejected_verdict_is_provenance_neutral` guards that we did **not** take the rejected path.
- **Blast radius contained:** the global `FAILURE_STATES`/`FAILURE_STATE_VALUES` (projector no-prune, write-boundary durability quarantine, forged-verdict accounting) are untouched, so `/kg-generate` negative memory is unchanged — an unsupported *generate* proposal still goes `rejected → failure memory`. The fate-sync is the only site narrowed, and its idempotency guard still reads `FAILURE_STATE_VALUES` (harmless — it only skips already-stamped ledger entries).
- **Complementary soft change (grounder triage):** `agents/grounder.md` now tells the `kg-grounder` to **leave an unsupported `[diverge]`-lineage hypothesized edge `unverified`** (its already-sanctioned "later pass" fate) rather than stamp `rejected` — framed as *choosing not to verdict* (don't spend a rejection on an item that has no in-source span yet), never bending a verdict. This is a soft guarantee; the fate-sync narrowing (Part A) is the hard backstop that holds even if a `rejected` is stamped anyway.
- **Advisory (Part C):** `kg_diverge_materialize` returns an advisory-only `advisory` string when a source is configured and ≥1 pin materialized, reminding that grounding these pins against the existing source will correctly leave them `unverified` until sources are added. Never a disposition, verdict, or ledger write.
- **Accepted trade-off:** a diverge pin `rejected` specifically for being vague/unfalsifiable (the generality confound, §1.6) also no longer auto-discards, so a similar idea may reappear in a later slate. Preferable to the alternative: the user is the real selector and can discard it in one tap, and the primary risk to guard is *good novel ideas being buried*, not *weak ideas reappearing*.

## Re-examinable-verdicts advisory: a read-only R3-mirror for non-monotonic evidence (2026-07-05)

- **Decision:** add a **read-only** advisory — "re-examinable: the source set changed since this was judged" — that mirrors the existing R3 stale-verdict advisory in the OPPOSITE direction. R3 fires when a `grounded`/`failed` **span-present** edge's stored span **disappears** from the source; this mirror fires when a `failed`/`rejected` item was judged against a source set that has since **grown or changed**, so previously-negative memory may now be supportable. Evidence is non-monotonic; the old negative memory was monotonic. It covers what R3 cannot: **nodes** and **span-less items** (a falsified divergence pin is typically a span-less node). It **never mutates a verdict** and **never re-queues** anything — re-grounding stays an explicit `kg_ground` decision; it only closes the *discovery* gap (the gap was automation, not permission — `kg_ground` already allows `failed → grounded`).
- **Why a state-based sibling of R3, not a re-run of grounding:** cheaply deciding "does the new source *support* this failed idea" would require re-grounding every past failure on every source edit — expensive and contrary to "failures are permanent negative memory." Instead the flag is a coarse, honest signal: the item is in `{failed, rejected}` **and** the source set moved since it was judged. Read-only, self-clearing on re-ground — exactly the R3 contract.
- **Precision without touching the verdict path (the rejected alternative):** a per-verdict "source signature at judgement time" stamped inside `kg_ground` would fire the flag only for items judged against a now-stale corpus — but the natural place to stamp it is *inside the sacred single verdict path*. Rejected as out of scope. Instead the flag reuses the projection-level **source-hash pre-gate** (same as R3) and a **term-overlap noise filter** carries the relevance load: an item is flagged only when its own text shares a non-trivial term with the CHANGED source text (files whose per-file signature moved, tracked in projector meta as `source_file_sigs`). Auto-re-queue and per-verdict source markers are explicitly rejected/out-of-scope.
- **Divergence mirror surfaces, it does not silently un-seal:** the brief's negative memory (I8) is deliberately permanent. On a source change, `failed`-fated ledger entries are **surfaced** as `reexaminable_discards` (in `kg_diverge_init`/`kg_diverge_recall`) and the user gets an **explicit un-seal lever** (`kg_diverge_recall(..., reexamine=[cids])` → drop from discards + clear the fate). Auto-un-sealing is **not** implemented. The un-seal stamps `unsealed_source_sig` on the ledger entry so the very next fate-sync does not immediately re-fold the still-`failed` graph item (which would silently undo the un-seal) — the guard lifts when the source changes again.
- **New state lives only in projector meta and `materialized.json`** (free-form JSON stores): meta keys `reexaminable_verdicts` + `source_file_sigs`; ledger entry keys `fate_source_sig` + `unsealed_source_sig`. **No** model schema field, **no** `kg_ground` marker, **no** grounder-queue change, and R3 / the global `FAILURE_STATES` are untouched (added alongside). Bounded by `_REEXAMINABLE_CAP` (parallel to the stale-verdict cap) so it can never bust the kg_context token budget. Surfaced in `kg_context.advisory.reexaminable_verdicts` and a `## Re-examinable verdicts` GRAPH_REPORT section.

## Tempered divergence: the reach dial is a language-layer directive, never an engine cap (2026-07-08)

- **Decision:** `/kg-diverge` gains a **reach** dial (`conservative|balanced|wild`, default **`balanced`**) that caps divergence in **degree** — the `boldness` band, the operator mix, the `feasibility` lean — but never in **kind**: the `mechanism` axis always spreads maximally, so every slate is still made of genuinely different approaches. Reach is applied by the language layer when it assigns descriptors and chooses operators. **The engine is unchanged**; it still only measures dispersion over whatever candidates the session submits (I5).
- **Bug it fixes:** the briefs skewed extravagant, sometimes absurd or cryptic. Three distinct leaks — unbounded boldness, no buildable-idea guarantee, and no validity test — got three language-layer fixes, not one engine knob.
- **Why not cap in the engine (the rejected alternative):** a `reach` parameter on the archive or the DPP selector would make geometry decide *how bold an idea may be*, i.e. let the embedding space act on the content of a proposal rather than on its dispersion. That is precisely the advisory ceiling I5 exists to hold ("embeddings measure dispersion, never truth"). Keeping reach in the prompt layer means the geometry still sees only what it always saw: a batch of candidates to spread. No engine code changed, so I5's `dpp` on-vs-off snapshot holds untouched — reach adds no new geometry path to snapshot.
- **`feasibility` is a COVERAGE axis, not a filter:** MAP-Elites keeps one elite per feasibility bin, so a bold idea can never **evict** a buildable one. This is a coverage guarantee about the *archive*, not a promise about the final six — the slate is still chosen by DPP over what survives. Shipped as a default on **all three** axis paths (the omit-axes default in `pack.yaml`, the `generic.yaml` template, and the inferred-axes recipe in `axis_inference.md`), with the honest caveat that it is skipped where "buildable" is meaningless (names, taglines).
- **Coherence gate, and why killing a broken idea is free:** the judge rubric adds a one-line "why does the mechanism actually work?" test that separates *bold-but-valid* (keep) from *incoherent* (kill). Killing an incoherent idea deliberately does **not** count against the judge's ~40% over-filtering budget, which is scoped to cutting *valid* ideas for being unusual. Without that carve-out, fear of over-filtering would wave nonsense through as "the variety the engine needs" — trading coherence for a diversity statistic.
- **Accepted trade-off:** `balanced` is a default, so a user who wanted the prior maximal behavior must now say `wild`. Judged worth it — the prior default's failure mode (cryptic, unusable slates) cost more than one extra word. Coherence is enforced at **every** reach: `wild` means further-out, never incoherent.

## Key-free second construction: an alternate canon behind the SAME boundary (2026-07-08)

- **Decision:** `kg_write` and `kg_propose` take an optional `construction=<name>` (plus a companion `source=<path>` so spans verify against the second document). It routes the **same** payload through the **same** `validate_payload` — same dispositions, same verbatim-span rule — into a separately-named alternate canon under `<project>/.kg/constructions/<slug>/`, mirroring the per-name `.kg/diverge/<brief>/` store rule. `kg_generate` gains `second_construction=<name>`, which projects that alternate canon in-session and cross-generates (ensemble, §9).
- **Bug it fixes:** the exo "attack coverage" move needs a *second graph construction* to cross-generate against, and the only builder was the headless backend (`python -m kg_engine.backend extract`) — which requires the `anthropic` SDK **and** `ANTHROPIC_API_KEY`. So `/kg-perturb` was the one command that could not run in a stock install: it silently degraded to an internal `regroup`. Now a `kg-extractor` subagent builds the second construction with **no API key** — the session does the language work, the engine only validates and stores (§2.2).
- **Why reuse the boundary rather than add a lane (the rejected alternatives):** (a) the command's old "in-session alternative" note told the user to point `/kg-build` at a second `KG_PROJECT_DIR` — **impossible**, the running canon is fixed at server startup; it has been replaced with the real flow. (b) A separate, looser write path for constructions would create a second trust surface where spans are not verified. Routing through the identical boundary means a second construction is exactly as span-disciplined as the primary one, and no new forgery surface exists.
- **Session-ephemeral, and it took a High fix to make that true:** the store is rooted under the ephemeral `.kg/`, but `git rev-parse` walks *up* to the parent repo, so `_commit_batch` was `git add`/`commit`-ing `.kg/constructions/<slug>/canon/*.md` into the user's tracked history on any repo without `.kg/` gitignored (review-r10, High). Construction sub-engines now build with commits disabled (`Canon(git_enabled=False)`), and the store is **wiped fresh** on the first materialization each session (and rebuilt when re-pointed at a different second source) — making the "session-ephemeral" contract real instead of silently merging a stale prior build.
- **Blast radius contained:** the primary-canon default path (`construction=None`) is byte-for-byte unchanged. The pre-built `second_graph` path stays as the escape hatch, and the headless backend is kept for out-of-session / CI builds. Pinned in `tests/test_perturb_second_construction.py`.

## Decision Rule D5 retired: there is no upstream left to drift (2026-07-09)

- **Decision:** **D5 — Upstream drift** (FUSION_PLAN.md §14) is **retired**, effective with the removal of the donor repository links. Its ID is kept and struck through at the definition site rather than deleted, so the historical record and the existing citations of it (`BASELINE.md`, `PLAN_STATE.md`, `scripts/donor_pins.json`) still resolve to something that explains itself.
- **Why it is moot, not overridden:** D5 said donors are read at the Stage-0 SHAs, that mid-build upstream commits are ignored, and that "re-syncing is a post-release, human-initiated decision." Both donor repositories have now been unpublished by their author. The rule's premise — an upstream that can gain commits — no longer holds, and the one live clause it left open (the deferred re-sync) has been **foreclosed** rather than exercised. A rule whose trigger can never fire and whose reserved decision can never be taken is spent.
- **What D5 was never doing (and what still holds):** D5 governed *whether to chase upstream*. It never enforced donor **integrity** — that is **I11**, a separate, test-enforced invariant (`scripts/check_donors_clean.py`, installed as a pre-commit hook). I11 is untouched and still green: the pinned sibling checkouts must exist, sit at their pinned SHAs, and have clean working trees at every Burgess commit. Retiring D5 removes an option nobody can take; it removes no guarantee.
- **Consequence for the pins:** the Stage-0 SHAs (`17c4066`, `a2adfa1`) are now permanent by necessity rather than by policy — the local checkouts recorded in `scripts/donor_pins.json` are the only surviving copies of the donor code, and they are the sole referent of the SHAs cited throughout `ATTRIBUTION.md`. `donor_pins.json` therefore cites I11 alone.
- **Rejected alternative — delete D5 outright:** the pre-declared decision rules D1–D5 are a numbered, cited set; deleting one would silently renumber nothing but would strand the citations in `BASELINE.md`, `PLAN_STATE.md` and the pin file, and would erase the fact that chasing upstream was once a live, deliberately deferred option. Striking it through in place keeps the plan readable as the historical contract it is.

> **Amended (2026-07-31).** Cambrian was republished at https://github.com/sergiparpal/cambrian and has resumed development. Three claims above have lapsed; they are annotated rather than rewritten, because the entry records why D5 was retired *then*.
> - **"The rule's premise — an upstream that can gain commits — no longer holds"** is now true of Sproutgraph only. Cambrian's upstream exists again and sits many commits past `a2adfa1`, so the deferred re-sync is once more *possible* — it was never actually foreclosed, only unreachable. **D5 stays retired anyway**, on the narrower and durable ground that it was a build-time rule and the build is finished: re-syncing is ungoverned, not forbidden. The verdict survives; one of its two supports did not.
> - **The I11 description in "What D5 was never doing"** ("must exist, sit at their pinned SHAs, and have clean working trees") is superseded. `scripts/check_donors_clean.py` now asserts only that each pinned SHA remains **reachable** from its donor's `HEAD` — the weaker statement that is still true of a live repository and still protects the historical fact I11 exists for. See the §2.2 annotation in `FUSION_PLAN.md`.
> - **"Permanent by necessity"** applies to Sproutgraph's pin alone. `a2adfa1` is reachable from the public Cambrian repository, so `ATTRIBUTION.md`'s claims are publicly checkable again with `git show a2adfa1`; `17c4066` still resolves only against the local sibling checkout. Both pins remain permanent — now by policy for Cambrian, by necessity for Sproutgraph.

## The single-writer lease hands off FIFO: ordering waiters, never authorizing them (2026-07-30)

- **Decision:** `Canon._acquire_lease_blocking` waits in a **FIFO ticket queue** (`.kg-session-lock.q/`, `LOCK_QUEUE_*` in `canon.py`) instead of every contender polling the lease on its own capped backoff. A waiter takes a ticket stamped with its arrival, and **only the front waiter polls the lease** — which is what lets that poll be short (prompt handoff) without a thundering herd. An uncontended write keeps a fast path that never touches the queue, and `try_acquire_lock` stays strictly non-blocking and unqueued.
- **Bug it fixes:** the contended-wave test flaked on CI with three of ten writers burning the entire `LOCK_ACQUIRE_TIMEOUT` and surfacing the by-design locked-vault error while the other seven drained past them. Instrumenting the wave found the critical section is **~11 ms**, so ten of them is 0.11 s of work — against a 3.29 s wave, i.e. **96% of the wall time asleep with the lease FREE**. Two defects, one cause: handoff cost up to `LOCK_RETRY_MAX` (0.5 s) however brief the write, and nothing ordered the contenders, so a waiter could lose race after race until its budget expired. After the change the same wave drains in **~0.2 s** at the production budget, and still fits in ~4.3 s (7× headroom) under a pathological 100 ms-per-fsync penalty. The Windows hardening below spends some of that margin on ticket heartbeats — the wave is ~16× faster than the 3.29 s baseline rather than the ~25× measured before it — which is the price of the leak backstop, paid in a place that had margin to spare.
- **The first fix was wrong, and measurement is what said so:** the flake was initially read as slow-IO fsyncs eating the budget, and treated by raising the *test's* budget to 120 s. That diagnosis does not survive instrumentation — 11 ms of work cannot consume 30 s, and the wave was idle, not busy. The real fault was starvation. Recorded because the plausible-sounding wrong diagnosis is the one a future reader will reach for again.
- **The line ordering may never cross:** a ticket **never grants the lease** and never bypasses `acquire()`'s O_EXCL/reclaim CAS, which remains the sole serializer (**F16**). A lost, duplicated or forged ticket therefore costs a waiter its place in line and nothing else. That separation is what licenses every method in the queue to degrade silently on an `OSError`, and it is the same shape of rule as the divergence razor (**I5**, geometry orders proposals but never decides truth): here, tickets order waiters but never authorize a writer.
- **Rejected alternatives:** (a) *just raise the budget* — treats the symptom, leaves a wave 96% idle, and a waiter can still be passed over indefinitely; (b) *shorten `LOCK_RETRY_MAX` / add jitter* — cuts the waste but orders nothing, so starvation survives; (c) *make `try_acquire_lock` respect the queue* — it would then fail whenever any writer is waiting, stalling the lazy projector's read path, which is exactly what that non-blocking seam exists to protect; (d) *queue on every acquire* — taxes the overwhelmingly common uncontended write (a build wave funnels through the ONE server process) for a benefit only contention uses.
- **What the queue then cost on Windows:** it went red on `windows-latest` because progress depended on a **delete** — see the addendum to the next entry for the mechanism and the structural lesson. Containing it added `LOCK_QUEUE_TICKET_TTL` (a leaked ticket expires in seconds, not on the lease's TTL), probe throttling, fail-closed ticket reads, and `LOCK_QUEUE_STALL_SECS`, a valve that abandons the queue for the unfair loop if position stops improving. The valve is the load-bearing one: fairness is an optimization and must never make a writer do **worse** than the pre-queue behavior.
- **Accepted trade-offs:** a fresh arrival gets one un-queued fast-path attempt and can therefore barge, but only by landing inside the sub-poll window where the lease is free and the front waiter is between polls — after one miss every writer in a wave is ordered. Ordering is by **wall clock**, so cross-host skew degrades fairness (never correctness). A waiter must keep heartbeating its ticket or lose its place, which is precisely what reclaims a leaked one. And under any queue pathology fairness is surrendered, deliberately, to keep the write.
- **Pinned in:** `tests/test_fix_canon.py` — arrival-order service, stale-ticket reaping, the unavailable-queue degradation, leaked-ticket expiry on the ticket TTL, unreadable tickets respected rather than reaped, a dead-but-undeletable ticket yielding its place, the wedged-queue valve, `probe=False` opening no ticket, `.tmp-*` atomic-write temporaries not counted as waiters, and an uncontended write never creating the queue at all. Each was checked to **fail** with only its own mechanism defeated; one was vacuous on the first attempt (a free lease let the writer take the fast path and never enter the queue) and was rewritten.

## The provision lock stays unordered: its waiters need an outcome, not a turn (2026-07-30)

- **Decision:** the FIFO ticket queue that made `canon.LeaseLock`'s blocking acquire fair is **deliberately not ported** to `kg_engine/dirlock.py` or to bootstrap's `_wait_for_lock`. Provisioning keeps its unordered fixed `POLL_SECS = 2.0` poll. The two locks stay parallel-by-design in their *steal/release* discipline (dirlock's module header) and deliberately divergent in their *wait* discipline.
- **What prompted it:** the contended-wave CI flake fixed in the canon lease made the same question fair game for the installer's lock twin — and the claim that dirlock "has the same unfair-backoff shape" was made in passing and is **wrong**. dirlock has no acquire loop at all: it exposes only the single non-blocking `try_acquire`, and the waiting lives in bootstrap's `_wait_for_lock`, which polls on a *fixed* 2s interval, not exponential backoff. Recorded here so the correction is not re-derived from scratch.
- **Why they are not the same problem:** a canon waiter wants a **turn** — every writer must eventually write, so a writer that keeps losing races exhausts `LOCK_ACQUIRE_TIMEOUT` and fails its write (that is exactly how the flake presented: three of ten writers erroring out while seven drained past them). A provisioning waiter wants an **outcome** — the venv being ready. When the builder finishes, every waiter leaves on the `venv_current` check without ever taking the lock, so losing the mkdir race costs a loser nothing. Ordering waiters who do not need turns buys nothing and delays them.
- **The scale gap points the same way:** the canon critical section is ~11 ms against a handoff that cost up to `LOCK_RETRY_MAX` (0.5 s) — 45× overhead, which is what made the wave 96% idle. The provision critical section is a venv build (seconds to minutes) against a ≤2 s poll. Measured with the real `_wait_for_lock` at 20 concurrent sessions: all 20 exit at **2.02 s** for a ~0 s build and **4.01 s** for a 2 s build, with exactly one build and zero timeouts. The overhead is one poll interval and is **independent of session count** — there is no pile-up to fix.
- **Why not port it anyway (the rejected alternative):** a ticket queue would force waiters to take turns they do not need, making provisioning strictly slower, and would add tickets, heartbeats, stale-reaping and a degradation path to a module whose defining constraint is that it is a **stdlib-only leaf importable by a bare system Python before any venv exists** (dirlock's header). More machinery and more latency in the least recoverable part of the install, to fix a starvation mode that cannot occur there.
- **Also rejected — test readiness before attempting the lock:** it looks like it would spare the waiters that take the free lock only to re-check and release, but `venv_current` spawns the venv interpreter (`_interp_identity`) while `try_acquire` is one `mkdir`. Attempting the cheap thing first is already the right order, and `venv_current`'s own cheap pre-check exists precisely to keep the 2 s poll from re-spawning that interpreter.
- **Pinned in:** `tests/test_bootstrap.py::test_concurrent_provisioners_run_one_build_and_none_starve` — N concurrent provisioners must produce exactly one build and leave no waiter sitting out its deadline. It uses real subprocesses rather than threads because `dirlock._OWNED_TOKENS` is module state, a sharing hazard that cannot exist across the separate processes this lock actually serializes. The test is what keeps "unordered is correct here" a checked claim rather than an assumption.
- **Addendum — the queue then failed on Windows, which settles the question harder than the argument above did (same day):** the ticket queue shipped to the canon lease turned `main` red on the `windows-latest` leg, with the wave test failing exactly as it had before the queue existed. POSIX `unlink` succeeds while a file is still open; Windows raises `ERROR_SHARING_VIOLATION` — the hazard `_replace_lockfile` already existed for — and the FRONT waiter's ticket is the most-read file in the queue, since every waiter behind it opens it to check liveness. So the one `dequeue` most likely to fail was precisely the one that parks everybody, and the ghost then blocked the queue for the ticket's whole TTL. Containing it took a second round (`LOCK_QUEUE_TICKET_TTL`, throttled probes, fail-closed ticket reads, and a stall valve) — and the first attempt at that round still gated the skip on the unlink landing, which made queue *liveness* depend on deletion succeeding: with deletes failing outright, 8 of 10 writes lost their whole budget and failed.
- **What that adds to the decision:** the cost of the queue was not the ~120 lines it looked like — it was acquiring a platform-specific failure class that needed a second fix round, a simulation harness, and five CI samples to believe. That is a defensible price for the canon lease, where starvation was a measured, reproducible flake losing real writes. It is a bad price for `dirlock`, which has no such starvation to fix, and where the blast radius is the **least recoverable part of the install**: a provisioning lock that wedges leaves a user with no engine at all, and `dirlock` cannot even import a helper library to dig itself out. The original reasoning ("waiters need an outcome, not a turn") is unchanged; this is the first hard evidence of what porting it would have *cost*.
- **The structural lesson, and why neither existing lock has this exposure:** both `LeaseLock` and `dirlock` make progress depend on an atomic **rename** — `os.replace(lock, sidelined)` frees the contended path, and every following `rmtree`/`unlink` only cleans the sideline (`ignore_errors=True` throughout `dirlock`), so a delete that never lands leaks an orphan for the age-gated sweep and blocks nobody. The ticket queue inverted that: a ticket's continued **existence** was the blocking signal, so progress depended on a **delete** — the one file operation Windows does not promise. `dirlock`'s single delete on a live path (`try_acquire`'s cleanup after a failed `info` write) fails safe the same way: the lock is left info-less, becomes stealable past `_INFO_GRACE_SECS`, and is reclaimed by `_steal`'s rename. Any future lock work in this repo should keep liveness on the rename side of that line.

## `obsolete` is not live topology — but the falsification counter does not follow (2026-07-31)

- **Decision:** `model.NON_LIVE_STATE_VALUES` (`FAILURE_STATE_VALUES ∪ {obsolete}`) is the **single live-topology vocabulary**, and every surface that decides *what the graph structurally is* reads it: `projector._live_subgraph` (degree/community/betweenness/spec_betweenness), `DerivedReader.shortest_path`, `generate._live_undirected`, `kg_context`'s answer lane, and `kg_agenda`'s detectors plus its edgeless-communities crossing test. `kg_context`'s **falsification counter stays on the narrower `FAILURE_STATES`**. The asymmetry is the decision; the widening is just its consequence.
- **Why the counter must not follow:** the two sets answer different questions. Live topology asks *is this relation still standing?* — a refuted edge and a superseded one are both **not standing**, so neither may confer centrality, carry a path, or answer a query. The falsification counter asks *what did grounding refute?* — and `obsolete` is a **lifecycle transition, not negative information** (§1.7). Folding it in would inflate the falsification record with edges nothing ever attacked, and the counter is the surface a reader trusts to say how hard the graph has been tested. The "consistency" argument for widening it is the trap: consistency of *vocabulary* is not consistency of *meaning*.
- **Bug it fixes:** review-fix L14 / r11 moved three surfaces onto the non-live set and left two behind on the failure-only set, which the full suite passed straight through because each consumer was internally consistent. On one graph that produced `degree(a) = 0`, zero `kg_context` items, and `shortest_path(a, b) → ['a','b']` — a path asserting connectivity every other surface called dead, which is exactly what the L13 fix prevents for `failed`/`rejected` and was never extended when `obsolete` joined. In `kg_agenda` the gap made a node's **detector depend on which non-live state its other edge held**: `rejected`/`failed` fired `hypothesized-only`, `obsolete` dropped the node from the agenda entirely — because `deg` (read from the nodes table, computed *without* the obsolete edge) and the builder's local `live` set disagreed about that one edge.
- **The shape, which is the reusable part:** all of it is *a rule that was single-homed and then extended, with a consumer left behind on the older form*. Single-homing the vocabulary in `model.py` is what makes the next extension mechanical, but it does not by itself find the consumers that re-derived the set locally — those have to be swept. The same shape produced the `_sync_materialized_fates` §1.2 gap (`FileNotFoundError` where every sibling call site had already widened to a broad catch) in the same review.
- **Rejected alternatives:** (a) *widen the counter for symmetry* — see above; it corrupts the meaning of the one number that reports falsification effort; (b) *keep `obsolete` live and drop it only from centrality* — the pre-L14 state, and the reason the surfaces disagreed in the first place: a superseded relation invisible as an answer but still conferring betweenness is an undocumented split; (c) *let each surface own its own filter* — that is precisely the defect, five times over.
- **Pinned in:** `tests/test_review_r12.py` — the vocabulary premise itself (`obsolete` is non-live but **not** a failure state), `shortest_path`, both `kg_agenda` gaps, the crossing test, and `test_falsification_counter_still_counts_failures_only`, which exists so nobody "consistently" widens the exception. Each has a control proving a genuinely live edge still carries a path and still joins communities; the `rejected`/`failed` parametrizations stay green throughout.

> **Addendum (2026-07-31) — the rename side of the line needs a retry to hold.** The structural lesson above
> ("keep liveness on the rename side") is right and unchanged, but it was stated as though a rename always
> lands. On Windows it does not: `dirlock.release` and `_steal` move the live lock **directory** aside while
> every waiting provisioner has `lock/info` open (each poll runs `try_acquire` → `is_stealable` →
> `parse_info`), and Python's `open()` grants no `FILE_SHARE_DELETE`, so the rename raises
> ERROR_SHARING_VIOLATION. `release` read that as "already reclaimed" and returned with the lock still
> present — the leak this addendum records. It surfaced as a `windows-latest` CI flake that passed on rerun.
> The fix is the retry discipline `atomicio._replace_with_retry` and `canon._replace_lockfile` already
> applied and `dirlock` never received; the budget is deliberately shorter (2 s) because giving up here leaks
> a self-healing lock rather than failing a write. **What this does not change:** the reason the ticket queue
> was not ported. That decision rests on provisioning waiters needing an *outcome, not a turn*, and on the
> blast radius of a wedged installer — both untouched. If anything it sharpens the point: even the rename
> path, the one Windows *does* promise, needed hardening to be dependable there.

## A vault comes into being on its first write, never on a session start (2026-11-06)

- **Decision:** nothing Burgess starts on its own (the MCP server at session start, the SessionStart reconcile) may create anything in the project dir. The engine's `Canon` is lazy (`ensure_layout=False`). The layout (`canon/` plus the `.git/info/exclude` patterns) is created by `Canon.ensure_layout()`, called from `acquire_lock` (every canon writer, before the lease file exists) and from `Reconciler.scan` once the sweep has something to persist. "Is there a project here?" means **at least one canon note, or a non-empty audit ledger** (`bootstrap._holds_project`); an empty `canon/` is not a project. A sweep with nothing to reconcile (no note, no audit record, and no baseline, ledger or file cache even after checkpoint recovery) writes nothing at all.
- **Bug it fixes:** Claude Code starts a plugin's MCP server and fires its SessionStart hook in **every** folder a session opens. The eager `Canon()` in `KGEngine.__init__` left an empty `canon/` and the exclude lines everywhere, and the reconcile's guard ("`canon/` is a directory") was therefore true everywhere, so the sweep wrote `.kg-reconcile-state.json` and the `.ckpt` beside them every session. The first trigger defeated the second one's guard. Field report: leftovers in twelve folders, one of them pushed to a remote by a vault's auto-commit.
- **Why `acquire_lock` and not `try_acquire_lock`:** the non-blocking acquire's other caller is the lazy projector on the READ path, including the precontext hook's read-only canon (F37), and a query must never turn a folder into a vault. Every writer reaches `acquire_lock`, the reconciler's correction included (it takes the lease non-blockingly, then writes through `write_one`), and the memo makes every call after the first free.
- **Why the sweep lays out too:** `.git/info/exclude` is per-clone and never cloned. The eager server used to write it at startup for a fresh clone that arrived with notes; now the first sweep writes it, before its state file.
- **Rejected alternatives:** (a) *build the `KGEngine` on the first tool call* (the field report's broader option): `_register` closes over a constructed engine, so this rewrites the tool surface for nothing once construction has no side effects; (b) *delete the leftovers*: they sit in folders Burgess does not own, and counting an empty `canon/` as no project is enough; (c) *keep the "is a directory" guard and rely on the sweep's own check*: every polluted folder would still spawn the engine interpreter every session; (d) *skip the sweep only when the state FILE is absent* (the report's literal wording): a sweep that got past the guard would then rewrite the leftovers' empty state and checkpoint. An empty or unreadable state carries no information (`_load_state`'s fail-open default is the empty form), so it counts as none; (e) *import the predicate from `canon`*: impossible, because the guard runs under the bare system Python and `canon`'s model module needs yaml. The two names and the note rule are mirrored in `bootstrap.py` and pinned against the engine, under the same stdlib-leaf constraint `dirlock` lives with.
- **Accepted trade-offs:** a corrupt state file in a vault with nothing to reconcile is no longer rewritten until a sweep has work to do (F19's test now seeds a note, as its sibling already did). A vault whose notes are all gone but whose audit ledger remains is still swept, and that sweep recreates an empty `canon/`, as the eager server always did. A bare dev launch without `KG_DATA` still puts the data dir at `<project>/.kg-data`.
- **Pinned in:** `tests/test_fix_session_start.py`. Of its 26 tests, 22 fail with the fix reverted; the other four pin what must not change (a real canon is still swept and checkpointed, deleting every note still prunes the baseline, and the excludes still precede the lease file). Each hook test runs the real sweep in a subprocess and requires a clean exit, so a crashed sweep cannot pass for an empty one.

## The launcher waits for a build; it never runs one (2026-11-06)

- **Decision:** `launch_server.mjs` never builds the engine venv in its own process. On a cold or stale venv it asks for a background build (`bootstrap.py --background`, no `--reconcile`), polls for the stamp, and stops polling at `MCP_TIMEOUT` minus a 10 s engine-start reserve (`CONNECT`). Ready by then, the engine starts in the same session; not ready, the launcher exits 1 with a message naming `provision.log` and the way back (reconnect from `/mcp`, or `MCP_TIMEOUT=600000`). The early-failure heal follows the same rule and exits rather than relaunch onto a venv being rewritten. On Windows the background worker gets a windowless console of its own instead of none, and opens its log for atomic appends. The advisory import probes run after the stamp, not before it.
- **Bug it fixes:** the first session after reinstalling 0.4.2 on Windows never got its MCP server. The launcher found no venv and ran `bootstrap.py` in the foreground; Claude Code abandoned the server at 30 s and tore the launcher down. Node's and the `py` launcher's job objects kill their direct children when they close (measured: a `py` child of a killed `node` stopped within 0.1 s, its own child kept running), so `bootstrap.py` died with no chance to clean up: the provision lock stayed held by a dead pid and the venv half-built, while `uv`, a level further down, kept installing into it for 13 s. Before that, the hook's own worker had already lost its build: created with `DETACHED_PROCESS`, it had no console, Windows gave its `uv` a new visible window, and that `uv` ended with `STATUS_CONTROL_C_EXIT`, the code a console program gets when its window is closed or receives Ctrl+C, with none of its output in `provision.log`.
- **Why the window is the budget:** documented Claude Code behavior, checked rather than assumed: `MCP_TIMEOUT` is the only startup-timeout knob (`.mcp.json`'s `timeout` is per tool call), a stdio server that fails to connect is marked failed and only `/mcp` → Reconnect restarts it, and a SessionStart hook has no documented ordering against MCP connects. So nothing a launcher does after the deadline can produce a connection; the only choice is whether the user then sees an explanation or a bare timeout, and whether the build survives. Claude Code passes its environment to the servers it spawns, so a user who raises `MCP_TIMEOUT` raises the launcher's budget with it.
- **Why the probes moved:** the stamp is what every waiter polls, and the probes decide nothing. Measured on that machine with a warm uv cache: `uv sync` 1.0 s, core verify 2.2 s, leidenalg probe 0.2 s, divergence probe 28.5 s (over its 60 s timeout in two other runs). Readiness went from 32–63 s to 3.5 s, and a cold first session went from failing to connecting in 6.0 s. A cold uv cache is still network-bound and can still miss the window; that case now ends in the message, with the build intact.
- **Why two workers write the log, and what that cost:** on a cold start both the hook and the launcher ask for a build; one builds, the other waits on the lock and leaves when the venv is current (the unordered wait recorded above handles any number of them). Windows' C runtime emulates `O_APPEND` with a seek and a write, so two workers lost 11–16 % of 6 000 lines between them; `FILE_APPEND_DATA` without `FILE_WRITE_DATA` makes each write land at the end, children's writes through the inherited handle included (6 000 of 6 000, every run). The second worker also logs the way it usually leaves now: a stanza that stopped at "Target venv" read as a worker that had crashed, and was first diagnosed as one.
- **Rejected alternatives:** (a) *answer `initialize` from Node and proxy the engine afterwards*: the transparent-restart design this launcher's header already defers. It would duplicate the engine's capabilities and protocol negotiation in Node, and it only helps if the client honours `tools/list_changed` for a server that started with no tools, which nothing documented guarantees. (b) *build synchronously in the SessionStart hook*: no documented ordering against the MCP connect, and it would hold every session start for minutes. (c) *keep the foreground build, bounded by the window*: killing a builder mid-install is exactly the defect. (d) *tell users to raise `MCP_TIMEOUT`*: the plugin cannot set it, so it stays an option in the message and the docs, not the fix. (e) *`CREATE_NO_WINDOW` on every child instead of on the worker*: measured to work only if each call site also passes explicit handles, since a child given its own console writes to that console. One flag on the worker covers every child, future ones included. (f) *keep `DETACHED_PROCESS` for isolation*: the new console belongs to the worker alone (`GetConsoleProcessList` lists only the worker), so closing Claude Code's terminal still never reaches it, and `CREATE_NEW_PROCESS_GROUP` still keeps Ctrl+C out.
- **Accepted trade-offs:** a first install with an empty uv cache usually needs one reconnect. A stale venv is not launched while it is rebuilt, so that session fails instead of running on half-swapped packages. Every cold start runs two workers, and the second one costs a 2 s poll. The heal gets what is left of the window instead of five minutes; a heal that needs longer completes in the background for the next connect. A probe that times out now says so instead of reporting the deps unavailable, and it no longer delays anything.
- **Pinned in:** `tests/test_fix_cold_start.py`, which runs the shipped launcher against a fake plugin root (a recording `bootstrap.py`, a recording engine). 15 of the 16 tests that run on Linux fail with the fix reverted; the 16th pins the warm path, which must not change. The Windows-only test repeats the console measurement, and its body was run on the reporting machine: it passes with the shipped flags and fails with `DETACHED_PROCESS` (empty log). The log-append test checks every line across two writers and their children; its failure under the old open is Windows-only and was measured there.

## Commands read `$ARGUMENTS`; plugin options reach them as `${user_config.*}` (2026-11-07)

- **Decision:** no command or skill text uses a numbered argument placeholder. Every command puts `$ARGUMENTS`, the raw typed text, where it needs its arguments, and says how to split it: quoted text is one argument, and each command adds a rule for the cases it can tell apart (`/kg-build`: a trailing whole number is the wave size and the rest is the path; `/kg-generate`: a whole number is `k`; the one-path commands take the whole line). A value a Bash block needs is written into it by the orchestrator, into a named slot (`SRC`, `WAVE_ARG`, `__SECOND__`), never through bash's own positional parameters. `/kg-build` takes the `extract_wave_size` option from its own text, through a `${user_config.extract_wave_size}` placeholder in Step 0b.
- **Bug it fixes:** read from the Claude Code binary and confirmed with real runs (2.1.316; the reporting Windows install's 2.1.319 carries the same code, and its older 2.1.202 counts the same way): `$N` is `$ARGUMENTS[N]`, counted from 0. The commands used `$1`/`$2` for the first and second arguments. On 2.1.316 one argument worked by accident (`$1` stayed unfilled and Claude Code, having filled nothing, appended `ARGUMENTS: <text>`), but with two, as in `/kg-build notes.md 4`, the documented way to set a wave size, every `$1` became `4` and the path disappeared from the prompt. 2.1.202 empties an unfilled `$N` instead and counts that as a substitution, so there even a single argument was erased from the command text. The wave size had a second, independent break. Step 0b read `${2:-${CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE:-6}}`, but `${2}` is not a placeholder Claude Code fills, bash's own `$2` is empty in the Bash tool, and Claude Code exports `CLAUDE_PLUGIN_OPTION_*` to hooks and MCP servers only. So the script resolved 6 for every build, whatever the option or the argument said, unless the orchestrator rewrote the line itself. `/kg-perturb`'s `SECOND="$1"` had the same flaw: run as written, it classified every perturbation as `degrade`.
- **Why `$ARGUMENTS` and not 0-based `$0`/`$1`:** the commands were written for a numbering they did not get, and the versions checked do not even agree on an unfilled `$N` (left as typed, or emptied). `$ARGUMENTS` is the one placeholder that means the same thing in all of them.
- **Why the option goes through the text:** `${user_config.KEY}` is documented for skill and agent content (non-sensitive options only), and it is the only channel from an option to a command's Bash. Unset, it stays as written, because the schema's `default` is not applied. In Step 0b that unfilled placeholder sits inside single quotes, is not a number, and resolves to the default like any other invalid value. A Claude Code that does not fill it gives a build 6, which is what every build got before.
- **Rejected alternatives:** (a) *0-based `$0`/`$1`*: see above. (b) *named arguments* (`arguments:` in the frontmatter, filled as `$name`): one more feature whose absence on some version leaves text unfilled, for no gain over `$ARGUMENTS`. (c) *expose the wave size through `kg_status`*: the engine deliberately reads no orchestration knob (`tests/test_manifests.py`), and the build would depend on the MCP server for a number the host already holds. (d) *keep bash `$1`/`$2` and pass them as script arguments*: the Bash tool runs a command string, so there are no script arguments to pass. (e) *a sentinel for `WAVE_ARG` like `/kg-perturb`'s `__SECOND__`*: a forgotten wave size costs speed, while a forgotten second source silently changes the result, so only the second earns a hard stop.
- **Accepted trade-offs:** the split is done by the orchestrator, not by code, so it is specified in each command, and the tests pin the text and the Bash blocks rather than executing the split. For `/kg-build`, a name that itself ends in a number must be quoted, or the number is read as the wave size. The option's value is written into the Bash block verbatim, inside single quotes, so a quote in that value would break the block; it is the user's own setting, and the failure is loud.
- **Pinned in:** `tests/test_fix_command_arguments.py` and the rewritten drift guard in `tests/test_waves.py`.
  - `test_fix_command_arguments.py` holds a model of the substitution, pinned to the five expansions recorded on 2026-11-07, plus static pins on every command and skill text. It also runs Step 0b and `/kg-perturb`'s block as the orchestrator would.
  - The drift guard now feeds the wave size through the two channels the command really has; before, it supplied bash's `$2` and the environment, which the real command never had.
  - Against the 0.4.4 commands, 34 of the 76 new cases fail, and so do all 28 of the drift guard's. The cases that pass pin what was already right: the three commands that only ever read `$ARGUMENTS`, the skill texts, the recorded expansions, one-argument calls, and the default for an unset option.

## Edge endpoints are node ids; the projection resolves the ones that are not (2026-11-07)

- **Decision:** the write boundary stores an edge's `source` and `target` as slugs (`merge_results_into_nodes`). That is the canonical key its node ids, edge ids, owner file and dedup already use. The projector resolves every endpoint that is not a node id but whose slug is one to that id (`Projector._resolve_endpoints`). It does so after the per-note hashes are taken, and without mutating the parsed nodes. `PROJECTION_RULES`, recorded in the index meta, makes an index built under other rules rebuild in full once (`_index_outdated`). `_schema_outdated` stays columns-only, for the contention heal. `kg_rename` and `kg_merge` match endpoints by slug.
- **Bug it fixes:** the first real build on 0.4.5, one 16-section document, left 3 of its 39 edges with label-form endpoints (`Meta RADAR`, `componentes en masa`). The extractor contract says ids, and the boundary keyed each edge on the slug but stored its endpoints as given. The projection then added them as phantom nodes: 80 nodes instead of 75, on a copy of that canon. So `get_neighbors`, degree and bridges missed those edges, `_owner_rank` ranked their natural owner foreign, and rename and merge, matching exactly, would have left them dangling.
- **Why resolve on read as well as normalize on write:** the canon is human-editable, and older canons already hold label-form endpoints. Rewriting the user's notes to heal them would be a migration nobody asked for. Resolution maps an endpoint only to an id with the same slug, so the edge id, which is built from the slugs, cannot change. A well-formed canon comes back as the identical list, and its `graph.json` bytes are unchanged.
- **Why match against EXISTING ids rather than slug on read:** a node stored with a raw id (`id: FEP`, from before node ids were slugged on write) is still the node `fep` names. Blindly slugging endpoints on read would disconnect it.
- **Why a rules version:** the incremental parse rebuilds a stat-unchanged note from its index rows instead of re-reading it, so a fix to how rows are derived never reaches an untouched note. Columns already had this problem, and `_schema_outdated` solves it for them; the rules version is the same full-rebuild trigger for derivation. It stays out of `_schema_outdated` because the contention branch uses that check to decide its in-place heal, which can fix columns but never rows.
- **Rejected alternatives:** (a) *slug endpoints in `Edge.__post_init__`*: every Edge construction would change shape, tests and hand-edited raw ids included, and a raw-id node would lose its edges. (b) *a reconciler migration that rewrites label-form endpoints in the canon*: it writes into the user's notes for a defect the projection can absorb. (c) *resolve at parse time in `node_from_markdown`*: a single note has no view of the other node ids. (d) *reject label-form endpoints at the boundary*: it would lose a span-verified edge over a spelling the engine can normalize.
- **Accepted trade-offs:**
  - Canon files written by 0.4.5 keep their label-form endpoints on disk until a write touches them. Every reader that goes through the projection sees ids. Readers of the raw canon outside the projector still see the labels, except rename and merge.
  - A dangling target, one that no node has the slug of yet, is left as written, exactly as before.
  - The first read after the upgrade rebuilds the index once.
- **Pinned in:** `tests/test_fix_engine_field_report.py`, together with the scrub-count and coverage fixes from the same field report.
  - Run against `main`'s engine, with `PYTHONPATH` pointing at a worktree of `main`, 10 of its 12 tests fail. The other two pin that an edge with no known `source_file` still covers any file.
  - The review-C2 test in `tests/test_fix_boundary_model.py` now expects the stored source to be the node id.

## /kg-build plans and cuts its sections in the engine, and runs no shell (2026-11-07)

- **Decision:** `/kg-build` declares `Task` and five engine tools, and no `Bash`. Two new MCP tools do what its Step 0b Bash block and its orchestrator did:
  - `kg_build_plan(arguments, configured_wave_size)` returns the files, each file's numbered sections at its heading level, their coverage, and the wave size. The typed `$ARGUMENTS` are split by `buildplan.parse_arguments`, not by the orchestrator.
  - `kg_section(source_file, section)` serves one planned section, cut and egress-scrubbed by the engine. The extractor calls it itself, so no section text passes through the orchestrator.
  - Both number sections through `sources.plan_sections`, which shares one splitter (`sources._chunks`) with `split_sections`.
- **Bug it fixes:** in auto mode every `/kg-build` asked for permission over and over, and waited until it was given (field report on 0.4.6). Read from the Claude Code binary (2.1.316): in auto mode the permission check skips every allow rule that could bypass the classifier, which covers a tool-wide `Bash` rule and an `Agent`/`Task` rule from any source, a command's `allowed-tools` included. So each Bash call went to the classifier. The reporting install's session logs show what that cost:
  - every long wait was a Bash command; engine tools and subagent launches never waited for the user;
  - the 0.4.5 build waited about 32 minutes on six helper scripts the orchestrator had written itself, to cut sections into files and scrub them, rather than copy each section verbatim twice;
  - the 0.4.6 build waited 3.5 minutes on Step 0b, which had passed in a second the time before.
- **Why engine tools, not a narrower shell grant:** in auto mode Claude Code drops broad Bash rules (and, in some configurations, every Bash rule), so any shell step depends on the classifier. The MCP tools a command declares keep their grant. In the 0.4.5 log, `kg_scrub` (declared) answered at once, while `get_neighbors` (not declared) took 5–6 s through the classifier.
- **Why the extractor fetches its own text:** it removes the double copy, and with it both the drift that cost a section its spans and the helper scripts written to avoid that drift. It also closes an egress gap: to copy sections, the orchestrator read the whole raw document, which sent the unscrubbed text to the model before any scrub ran.
- **Why the argument split moved into code:** the 0.4.5 decision kept it in each command's text, interpreted by the orchestrator. For `/kg-build` it is now deterministic and tested. One rule changed: a line that is only a whole number is the wave size, where before it was a subset that named no file. The other commands keep their own split.
- **Revisits 0.4.5's rejected alternative (c), the wave size through `kg_status`:**
  - Its first reason holds. The engine reads no orchestration knob: the command passes the option's filled-in text as an argument, and `build_engine_from_env` still reads nothing for it (`tests/test_manifests.py`).
  - Its second reason, that the build would depend on the MCP server for a number the host already holds, no longer applies: the build depends on the server for its plan anyway.
- **Rejected alternatives:**
  - (a) *Narrower Bash rules for the Step 0b script:* stripped or classifier-reviewed in auto mode like any other, and they do nothing for the scripts an orchestrator improvises.
  - (b) *Tell the orchestrator not to write scripts, but keep the copy-twice design:* the reason it wrote them, byte-exact copies of long sections, would remain.
  - (c) *Recommend bypass-permissions mode:* it removes every protection to fix one command.
  - (d) *Grow `kg_status` into the plan:* `kg_status` is the argument-free cheap probe whose `##`-level coverage other callers read, while a plan needs the typed arguments.
- **Accepted trade-offs:**
  - Subagent launches still go through the classifier in auto mode, a few seconds each. The `Task` grant is stripped by design, and in the measured builds no launch waited for the user.
  - The preamble before a file's first heading is still not extracted, as with Step 0b.
  - Headings inside fenced code no longer count toward the `###` rule; Step 0b's `grep` counted them.
  - `kg_status`'s coverage stays at `##` level, so for a `###` file it can differ from the plan's.
  - The new tests cannot fail on 0.4.6 in an informative way: the tools they call did not exist. The fix was
    checked end to end instead: a real `/kg-build` of the demo with Claude Code 2.1.316 in auto mode, headless,
    ran no Bash and no file read, was denied no permission, and accepted all 34 items.
- **Pinned in:** `tests/test_kg_build_plan.py`; `tests/test_fix_kg_build_paths.py` and `tests/test_fix_kg_build_source.py`, rewritten from Step 0b's Bash to the engine; `tests/test_waves.py`; `tests/test_fix_command_arguments.py`; and the 29-tool count in `tests/fusion/test_diverge_surface.py`.

## kg_write refuses the hypothesized lane (2026-11-07)

- **Decision:** `kg_write`, the text-claim lane, REJECTS every item that claims `provenance=hypothesized`, with reason `write-lane-hypothesis` (`retryable: false`), and writes the rest of the payload (`KGEngine._split_write_lane`).
  - `validate_payload` stays lane-agnostic.
  - `kg_propose` reaches it through `kg_write(lane="proposal")`, the only caller of that lane.
  - The extractor's contract says `inferred`, never `hypothesized`, for a relation inferred across sentences.
- **Bug it fixes:** the validator handles a hypothesized item as a discovery-mechanism proposal: it stores it with an empty span and checks nothing (§5a). That is right for `kg_propose`, and it was also what `kg_write` did.
  - The extractor's contract told it to use `hypothesized` for an inferred relation "that still needs a span". In the 0.4.6 field build, two edges were therefore ACCEPTED with their spans silently dropped.
  - On 0.5.0, an edge marked `hypothesized` was accepted even with a span that is nowhere in the source: the one way past the span invariant through `kg_write`, with no REJECTED or QUARANTINED signal.
- **Why refuse, not re-lane:** re-laning a hypothesized item to `inferred` after verifying its span would have the boundary choose a provenance the caller did not claim, and the boundary never moves provenance (`inferred` is not auto-promoted to `span-present` either). A refusal names the mistake, and the extractor's retry policy says how to fix it.
- **Why nodes too:** the lane is `kg_propose`'s for both kinds. A node extracted from the text is `span-present` or `inferred`. Labeled `hypothesized`, it would also meet `kg_ground`'s promotion gate, which asks a hypothesized item for support it was never meant to need.
- **Why at `kg_write`, not in `validate_payload`:** `kg_propose`, `kg_operate` and pin materialization all go through the validator, and its hypothesized-lane rules (span ignored, failure-collapse quarantine, deterministic authorship preserved) are right for them. As with `kg_propose`, the tool that receives an item decides which lanes it accepts.
- **Rejected alternatives:**
  - (a) *Quarantine instead of reject:* a QUARANTINED item persists, and a span-less text claim should not.
  - (b) *Keep accepting, but verify the span when one is supplied:* `hypothesized` would then mean two things, depending on which tool was called.
  - (c) *Fix only the extractor's text:* the guarantee would still rest on every caller's prompt.
  - (d) *Drop hypothesized items inside `validate_payload`:* that breaks the propose lane.
- **Accepted trade-offs:**
  - A caller that wrote `hypothesized` through `kg_write` on purpose must now call `kg_propose`. No caller in the repo did.
  - An existing span-less hypothesized edge stays in a canon until `/kg-ground` rejects it or real support grounds it.
- **Pinned in:** `tests/test_fix_write_lane_hypothesis.py`. Run against the 0.5.0 engine, 8 of its 10 tests fail; the other two pin that `inferred` is accepted and verified, and that `kg_propose` still writes the hypothesized lane.

## The write boundary refuses a self-loop (2026-11-07)

- **Decision:** `_validate_edge` REJECTS an edge whose `source` and `target` slug to one node, with reason `self-loop` (`retryable: false`), in every lane.
  - The rule sits next to the degenerate-endpoint checks (`empty-source`/`empty-relation`/`empty-target`), before span verification.
  - The extractor's contract also says it: an edge joins two different nodes.
- **Bug it fixes:** in the first full build on 0.5.1, an extractor wrote `h1-comprobadores-retiran-mas-revision survives h1-comprobadores-retiran-mas-revision` as a placeholder, at confidence 0.2. Its span verified, so the boundary ACCEPTED it: the one self-loop in a 225-edge canon.
- **Why reject:** none of the pack's relations states a claim about a concept and itself, so such an edge is an extraction slip, not a claim the text makes. The engine already treats self-loops that way elsewhere:
  - `kg_merge` drops the unverified self-loops its rewrite creates;
  - the projector leaves them out of degree.
- **Why every lane:** a generator has no business proposing one either, and one rule is easier to state than two.
- **Why slugs:** endpoints are node ids since 0.4.6, and a label-form endpoint (`Meta RADAR`) names the node its slug keys (`meta-radar`), so the comparison uses the key the canon itself uses.
- **Unchanged:**
  - `kg_merge` keeps a failed/rejected self-loop its rewrite creates, as failure memory (§1.7).
  - `kg_rename` carries an existing self-loop over; its docstring now says where one can still come from.
  - Neither passes through `validate_payload`.
- **Rejected alternatives:**
  - (a) *Quarantine:* a QUARANTINED item persists, and a self-loop carries no claim worth keeping.
  - (b) *Drop it silently:* the extractor and the report would never learn about the slip.
  - (c) *Fix only the extractor's text:* the boundary would still accept the next one.
  - (d) *Text-claim lane only:* a self-loop proposal is just as empty.
- **Accepted trade-offs:**
  - A self-loop already in a canon stays until `/kg-ground` rejects it.
  - A future pack relation that is reflexive by nature would need this rule revisited.
- **Pinned in:** `tests/test_fix_self_loops_and_write_args.py`. Run against the 0.5.1 engine, 6 of its 7 tests fail; the other pins the unchanged refusal of `source` without `construction`.

## kg_section shows the extractor the canon nodes its section names (2026-11-07)

- **Decision:** `kg_section` returns `known_nodes` along with the section's text: up to 60 canon nodes whose NAME the section mentions, as `{id, label, node_type}`, plus `known_nodes_more` for the ones past the cap (`buildplan.related_nodes`).
  - **Named:** at least half the content words of the node's id or label occur in the section, singular or plural, accents and function words ignored.
  - **Order:** the rarity-weighted share of the name found (an IDF over the canon's names), then the weight found, then degree, then id.
  - **The contract:** the extractor reuses a known id only for the same concept, creates a new node when in doubt, and never redeclares a known node.
- **Problem it addresses:** each extractor named its nodes without seeing the canon. In a full build of an 8-file corpus (0.5.2, 84 sections, 486 nodes), one concept written by two sections landed under two ids about 19 times (`radar` / `meta-radar`, `pass-at-k` / `pass-k`, singular/plural pairs), and 102 nodes had no edge. Those pieces join only through a later `kg_merge`.
- **Why lexical, not embeddings:** the match only decides what an extractor is SHOWN; whether two names are one concept stays the extractor's judgment, and the engine never guesses identity. A word match is deterministic, explainable and free. Embeddings measure dispersion, never truth, and identity is a truth question.
- **Why a rarity weight and a cap of 60:** in that build's own canon, a section names a median of 107 nodes by the half-the-words rule, mostly through words every other name shares (`revision`, `agente`). Measured offline on its 84 sections, two members of a duplicate group appear together in some section's list for:
  - 12 of the 18 groups at a cap of 20;
  - 14 at 40;
  - 16 at 60;
  - still 16 at 80.

  The two misses are a translation (`mutation-score` / `puntuacion-de-mutacion`) and synonyms with no word in common. Sixty entries cost about 1.5k tokens per extractor.
- **Why "never redeclare":** the canon merge lets an incoming node's label, node_type and body replace the existing ones. In that build, `meta-radar` changed from `primitive` to `operation` because a second section declared it again.
- **Rejected alternatives:**
  - (a) *Show every node:* ~9k tokens per extractor at 486 nodes, growing with the canon, and a list that long is skimmed, not read.
  - (b) *Have the orchestrator pass ids in the launch prompt:* the copy-through-the-prompt problem 0.5.0 removed.
  - (c) *Merge near-duplicates at write time:* the boundary would be guessing identity, and a wrong merge silently joins two concepts, which is worse than a duplicate.
  - (d) *Run extractors serially so each sees all earlier nodes:* gives up the parallel waves.
- **Accepted trade-offs:**
  - Extractors in the same wave cannot see each other's nodes, so the first wave gains nothing.
  - Synonyms and translations still slip through to `kg_merge`.
  - The match is for scripts with word boundaries (`[^\W_]+`), which fits this corpus but not, say, unsegmented CJK.
- **Pinned in:** `tests/test_known_nodes.py`. Checked end to end on the demo in waves of 2: the second wave was shown the first wave's nodes and reused `generality-confound` and `claim`, without redeclaring either.

## An untyped placeholder is reported, and the section that defines it declares it (2026-11-07)

- **Decision:**
  - `kg_write` returns `placeholders`: the NEW notes it created untyped, each a node an edge named that the payload did not declare and the canon did not hold.
  - `kg_section` marks such a known node `untyped: true`.
  - The extractor's contract asks it to declare every node its edges name, to re-send its payload with the node declared when `placeholders` comes back, and to declare an `untyped` known node when its section defines it. That is the one exception to "never redeclare a known node".
- **Problem it addresses:** in a full build on 0.6.0, one extractor named `camel` in an edge without declaring it. The boundary wrote it as a placeholder, with no node_type and no body, and said nothing. Later sections saw an undeclared-type node in their `known_nodes`, and two of them refused to link to it.
- **Why not reject the undeclared endpoint:** the edge itself is span-verified, and the placeholder rule is documented and relied upon. Rejecting it would throw away a verified claim over a missing declaration that a later write can supply. Reporting it keeps the claim and names the fix.
- **Why the exception is safe:** a placeholder has nothing to lose: no type, no body, and a label that is only its id. The canon merge that makes redeclaring a typed node dangerous (its label, node_type and body are replaced) is exactly what fills a placeholder in.
- **Not covered:** a node declared with an off-pack type is QUARANTINED and never written, so an untyped node in the canon is a placeholder or a hand edit.
- **Pinned in:** `tests/test_fix_untyped_placeholders.py`. Run against the 0.6.0 engine, 3 of its 6 tests fail: the two new signals and the contract text. The other three pin that the signals do not misfire, and that declaring a placeholder fills it in.

## /kg-ground plans its queue and hands out evidence in the engine, and runs no shell (2026-11-07)

- **Decision:** `/kg-ground` declares `Task` and five engine tools, and no `Bash`. Two new MCP tools do what its orchestrator and its grounders did by hand:
  - `kg_ground_plan(focus, configured_wave_size, batch_size)` returns the queue as `{id, kind}` items in batches (one per grounder, `wave_size` grounders at a time), plus the hubs for the adversarial grounder and the configured source.
  - `kg_ground_item(target_id, kind)` returns one item's evidence: the edge, `span_in_source` (the engine's own check, now), its two nodes, and the excerpt of the source section that holds the span (`groundplan.span_excerpt`). Free text goes through the session scrub.
  - The grounder judges from that evidence and reads no file. The exception is relocating a stale span (Stage 0b), whose text is gone.
- **Bug it fixes:** in auto mode, `/kg-ground` asked for permission over and over (field report on 0.6.1, the failure `/kg-build` had before 0.5.0).
  - Its orchestrator listed the queue with `query_graph(epistemic_state="unverified", limit=1000)`. On a canon of 168 unverified edges and 399 nodes that came back as 300 000 characters, which Claude Code saved to a file.
  - The orchestrator then parsed that file with Python scripts, and read the plugin's own engine source to learn `kg_ground`, all through Bash.
- **Two more flaws, fixed with it:**
  - One grounder was asked to drain the whole queue; batches now spread it over parallel grounders, within the grounder's 20-item cap.
  - The grounder's prompt checked spans against `examples/source.md`, the demo, and had it read the source files whole: about 450 KB for the reporting corpus.
- **The queue's scope, decided with the user:** every `unverified` edge, and only the HYPOTHESIZED nodes (`/kg-diverge` pins, generated proposals). An extractor's node names a concept the text uses, and the claims about it are its edges, which are queued; grounding 399 such nodes one by one would multiply the work for little gain. They are counted (`extractor_nodes_not_queued`), never hidden.
- **Why an excerpt and not the section:** a grounder judges whether a span states a relation, and in which direction; that takes the sentence and its neighbours. One section of the reporting corpus is 44 000 characters. The excerpt is the paragraph and its neighbours up to 3000 characters, and the rows around the span for a long table.
- **The order:** `[diverge]` pins first, as FUSION Stage 4 asks, then the other hypotheses, then the text edges their extractor marked weak (`confidence: AMBIGUOUS`, or a `confidence_score` under 0.5; `groundplan.is_weak`), then the rest.
  - **Weak first:** they are the claims likeliest to be rejected, so a pass cut short has judged them. In the field canon, 7 of the 168 edges are weak.
  - **Source order inside each group:** a batch then covers contiguous text, so one grounder sees related claims together.
  - **Not by score alone:** sorting every edge by its score would scatter each batch across the corpus. Most scores sit between 0.5 and 0.7, so the order would add little.
- **Rejected alternatives:**
  - (a) *Page `query_graph`:* it does not filter edges by state, and every page still carries full spans and bodies.
  - (b) *Keep one grounder, raise its cap:* serial, and one context for hundreds of judgments.
  - (c) *Give grounders the section through `kg_section`:* that needs a section number the edge does not carry, and whole sections are too long.
  - (d) *A source-search tool for the adversarial grounder:* it still searches the source files with Grep/Read inside the project folder, which needs no shell. Left for when a source lives outside it.
- **Accepted trade-offs:**
  - Subagent launches still go through the classifier in auto mode, as in `/kg-build`.
  - The adversarial grounder still reads source files.
  - The wave size is the `extract_wave_size` option, now described as bounding both commands.
- **Pinned in:** `tests/test_kg_ground_plan.py`, and the 31-tool count in `tests/fusion/test_diverge_surface.py`.
  - Against the 0.6.1 engine the test file stops at import, because `kg_engine.groundplan` does not exist, so it cannot fail informatively there.
  - **Checked on a copy of the field canon:** the plan is 16 602 characters instead of 300 000: 14 batches of 12 in 3 waves, the 7 weak edges first. All 168 spans verified and had an excerpt.
  - **Checked end to end:** a headless `/kg-build` and two `/kg-ground` passes of the demo, in auto mode with Claude Code 2.1.316. They ran no shell command and were denied no permission. The adversarial grounder's one file read was the source, inside the project folder.

## A precondition is `enables`, not `grounds`, and the grounder judges by the extractor's relation table (2026-11-08)

- **Decision:** the pack gains an eleventh relation, `enables`: HEAD = the precondition or means, TAIL = what it makes possible. `grounds` becomes evidence or a reason, and stops being "evidence/foundation". The grounder contract repeats the extractor's HEAD/TAIL table word for word, between `relation-roles` markers, so a claim is judged by the rule it was written under. The grounder also gets a rule for tables, and loses `query_graph`.
- **Bug it fixes:** the first full `/kg-ground` on 0.7.0 (406 nodes, 168 claims) ran 14 grounders in parallel, and they split on two rules (field report on 0.7.0).
  - **"X permite Y" as `grounds`:** four grounders accepted it, one rejected it. The grounder contract defined no relation; the pack's per-type definitions are YAML comments that never reach a model, and the extractor's table did not reach the grounders. The pack had no relation for a precondition, and the extractor contract said both "map it to the nearest pack relation" and "leave the edge out instead of approximating it", so «permite» claims were filed under `grounds`.
  - **Table rows:** three rows of a 60-line matrix (8 346 characters) were grounded, and a fourth from the same matrix was rejected as "two bare cells". `span_excerpt` cut the table to the rows around each span and dropped the header that names the columns (`| Mecanismo | Cubre | … |`), so each grounder guessed what the columns meant. The command's grounder template also listed "a table cell" among the spans that state no relation.
  - **Browsing to calibrate:** eight grounders called `query_graph` 15 times to see how other edges used a relation, or to look for duplicates. Five answers, 62 to 89 KB, were saved to files, and four grounders searched them with Grep.
- **Why a relation and not only a stricter `grounds`:** that corpus is about practice, and "what makes X possible" is among its central claims. Under a strict `grounds` and no relation for them, extractors would have to drop those claims.
- **Why the table is repeated rather than served by the engine:** the extractor's table is the live lever (the pack comments say so), and moving it into the engine would change how the extractor gets it too. A test keeps the two copies identical and covering every pack relation, and another checks that every text listing the relations lists all of them.
- **The table rule:** a row states a relation when the table's header says what each cell is. The excerpt now keeps the header and rule rows on top of the rows it kept, with a `…` line where it skipped rows, and leaves them out only when the header alone is too wide for the cap.
- **Rejected alternatives:**
  - (a) *Settle the two rules in the grounders' prompts:* the command gives each grounder its item ids and nothing else, and the rule belongs where every pass reads it.
  - (b) *Keep `query_graph` for the grounder, fixed:* even filtered, a listing of a real canon runs to tens of kilobytes, and the other edges' verdicts are not the grounder's rule. A suspected duplicate is checked with `get_node`.
  - (c) *Define the relations in `pack.yaml` as data:* a schema change for every pack and both contracts, for the same effect as the pinned copy.
- **Accepted trade-offs:**
  - The verdicts already given stand, including the edges the two splits decided either way: an edge with a verdict leaves the queue.
  - The pack-schema note that every edge type is grounded in a sentence of `examples/source.md` now holds for the first ten: `enables` comes from the field corpus, and the demo source does not change.
- **Pinned in:** `tests/test_fix_relation_rules.py` and `tests/test_fix_table_header_excerpt.py`.
  - **Checked on a copy of the field canon:** all four matrix rows now arrive under `| Mecanismo | Cubre | I/D/R | … |`.

## A hub is attacked once until it gains a grounded claim (2026-11-08)

- **Decision:** `kg_ground_plan` ranks hubs by their live claims: no edge in `model.NON_LIVE_STATE_VALUES`, the set every other structural surface reads, and no counter-edge. The adversarial grounder opens each counter-edge's notes with `counter-edge (adversarial pass, hub <hub-id>)`, read by `groundplan.attacked_hub`. Without a focus, the plan leaves out a hub whose counter-edge still awaits its verdict, or whose newest counter-edge verdict is no older than its newest grounded claim (`groundplan.already_attacked`), and lists it in a new `attacked_hubs` field. `/kg-ground` takes Stage 2's hubs from the last progress probe, and skips Stage 2 when none is left.
- **Bug it fixes:** the hub attack would never have ended (field report on 0.7.0).
  - The degree counted every edge, refuted ones and the attack's own counter-edges included, and nothing recorded an attack. On a copy of the canon, the next plan offered the same five hubs the pass had just attacked. Each pass would have ended with about ten new unverified counter-edges against them, and the queue would never have emptied.
  - It also broke an invariant the architecture states: a refuted relation confers no degree on any structural surface. A node whose three claims were all rejected still qualified as a hub.
- **Why a mark in the notes:** it follows the `[diverge] pinned` lineage marker the plan already reads, and needs no new tool, field or file. The form is the one the adversarial grounder wrote on all ten of that pass's counter-edges, so they count with no migration.
- **Why the verdict times:** `verdict_at` already exists on every judged edge. A pending counter-edge means the attack is still being judged; a judged one counts until the hub gains a newer grounded claim, after which the hub can be attacked again.
- **Why a focus skips the memory:** the user guide says a focused `/kg-ground compression` is how to ask for a second attack on a concept you do not trust, so naming a hub attacks it.
- **Fixed with it:** the adversarial contract taught the reverse of the pack. Its payload example read `specificity attacked_by generality-confound`, its worked example `generality-confound confounded_by betweenness`, and that example then grounded its own counter-edge `failed`, which records the counter-claim as false. The field pass's adversarial grounder did none of this; the examples now read victim first and fail the refuted claim. The adversarial grounder also stops adding hubs of its own from `kg_context` or `query_graph`: it attacks the ones its prompt lists.
- **Rejected alternatives:**
  - (a) *A ledger of attacks in `.kg/`, written by a new tool:* exact, including hubs attacked with no counter-edge, but a new tool and a new state file, and its loss would bring the repeats back silently.
  - (b) *Fix only the degree:* the same hubs still lead the ranking (radar-meta keeps 7 live claims), so the attack still repeats.
  - (c) *Skip Stage 2 when the queue holds only counter-edges:* the final probe of every pass has an empty queue, so it would skip every attack.
- **Accepted trade-offs:**
  - A hub the adversarial grounder could not attack (no counter-span, so no counter-edge) carries no mark and may be offered again. The contract asks it to say so.
  - A claim grounded in the same pass as the attack's verdict may be counted as already attacked. The hub comes back with its next grounded claim.
  - A counter-edge without the mark leaves its hub looking unattacked, as everything did before 0.8.0.
- **Pinned in:** `tests/test_fix_attack_once.py`, which runs the dead-claim case over every state in `NON_LIVE_STATE_VALUES`.
  - **Checked on a copy of the field canon:** all ten counter-edges are recognized. Four of the nine hubs count as attacked; the next plan offers the other five. `conjunto-oculto` drops out, because two of its claims were rejected.
  - **Checked end to end:** in a headless `/kg-ground` of the demo, in auto mode with Claude Code 2.1.316, the adversarial grounder wrote its two counter-edges with the mark, victim first, and failed nothing. The plan then left the attacked node out of `hubs` and listed it in `attacked_hubs`. In the pass before, a node whose two rejected claims left it with two live ones was no hub, and Stage 2 was skipped. No pass ran a shell command or was denied a permission.
  - **Found by that check:** asked now to declare the nodes it creates, the adversarial grounder typed one `concept`, which the pack does not declare, and the write was quarantined. Its contract now lists the pack's node types.

## `query_graph` applies every filter to both nodes and edges (2026-11-08)

- **Decision:** `node_type` keeps the nodes of that type and the edges that touch one; `relation` keeps the edges of that relation and the nodes they touch; `epistemic_state` keeps the nodes and the edges in that state, each by its own state.
- **Bug it fixes:** through 0.7.0 `node_type` and `epistemic_state` filtered only the nodes, and `relation` only the edges, so the two halves of one answer replied to different questions (field report on 0.7.0).
  - `query_graph(epistemic_state="grounded")`, which `/kg-query` presented as the trustworthy subgraph, returned 8 rejected edges and 1 unverified among 50 on the field canon.
  - A grounder that asked for `node_type="hypothesis"`, a type that does not exist, got 0 nodes and 100 unrelated edges, 62 KB.
- **Why it is safe:** every caller that existed before it, in the commands, agents and tests, gives at most one filter. A `node_type` or `epistemic_state` filter returns the nodes it returned before, and a `relation` filter the edges; only the other half changes, to match. The extractor's nodes are never verdicted, so a state filter returns few or no nodes, and `/kg-query` now says so.
- **Pinned in:** `tests/test_fix_query_graph_filters.py`.
  - **Checked on a copy of the field canon:** `epistemic_state="grounded"` now returns 50 grounded edges, and `node_type="hypothesis"` returns nothing.

## Each end of an edge is the concept its span names, and the grounder checks it (2026-11-08)

- **Decision:** the grounder contract gets the rule the extractor's has had since 0.6.0 for reusing a known node. Each end of an edge is the concept its span names, and a span that states the relation for something narrower or broader than one of the nodes does not ground the edge to that node. The grounder rejects such an edge with a new reason, `wrong-node`, and names the concept the span does name. For each `wrong-relation` or `wrong-node` rejection it also names the edge the span does state, and `/kg-ground`'s report lists these as leads for an extractor.
- **Bug it fixes:** grounders split on endpoint scope (field report on 0.8.0).
  - Two `defends_against` edges of «Retirar revisión humana» mapped a narrower phrase onto the broad node `hacer-trampas-con-los-tests` («aprobar los tests sin resolver el problema real»). One is the §5 matrix row «Tests protegidos | Manipulación de tests», whose «Falla por» cell reads «Trampas sin tocar tests»; the other is the §6 bullet «Resuelve la manipulación de tests visibles». Grounders running in parallel rejected the first and grounded the second.
  - The 0.8.0 orchestrator then asked the user whether `defends_against` holds when the span covers only part of the target. The extractor's contract already said no.
- **Why the rule speaks of what each node names:** a `grounds` edge's HEAD is often one company's figures, offered as evidence for a general claim. That is how evidence works, and a rule framed as "the span must cover the whole target" would reject it. The contract says so in one sentence.
- **Why a new reason and not `wrong-relation`:** the relation may be right while a node is not. The report breaks rejections down by reason, and the lead of a `wrong-node` rejection is a node to create.
- **Rejected alternatives:**
  - (a) *A partial defense still defends:* most defenses are partial, but the graph would then say that protected tests defend against cheating on tests at large, while the source's own row names the cheating they miss.
  - (b) *Leave it to the extractor's rule:* the field canon was built under that rule and still reused the broad node. The grounder is the defensive filter.
- **Accepted trade-offs:**
  - Verdicts already given stand: on the field canon, `e_escenarios-reservados__defends-against__hacer-trampas-con-los-tests` stays grounded until someone re-verdicts it.
  - A node whose label bundles two facts can no longer ground through a span that names one of them; the lead is to split it.
  - Leads are reported, not written: `/kg-build` skips every section that already has edges, so no command acts on them yet.
- **Pinned in:** `tests/test_fix_node_scope_and_counters.py`.
  - **Checked end to end:** a headless `/kg-ground`, in auto mode with Claude Code 2.1.316, over seven field edges written fresh on scratch copies of their documents. Both edges onto `hacer-trampas-con-los-tests` were rejected as `wrong-node`, and the matrix row whose cell names its node's concept was grounded. The two edges that offer one company's figures for the general claim were grounded. An edge whose node label bundles Meta's figure with Vercel's was rejected, with the lead to split the node.

## A counter-edge needs the source's own counter, and /kg-ground hands its grounders ids, not rules (2026-11-08)

- **Decision:** the adversarial contract gains an item: a counter-edge's span, read in its excerpt, must set itself against the claim it attacks. A contradiction that no single span states goes in the report, not into an edge, and a hub with no such span gets a falsifying question. `/kg-ground` now names `enables` in its own text, and tells the orchestrator to send each grounder its item ids and nothing else, because the grounders' contracts hold the rules.
- **Bug it fixes:** rules lived in the user's memory notes instead of the contracts (field report on 0.8.0).
  - Of the first ten counter-edges written in the field, the grounders rejected four. They rested on a premise the attacker supplied, on a figure the source gives as support, on a counter the source sets against a different claim, or on a link between two documents. Each stays in the negative-information memory for good, counted with the refuted claims. The lesson then lived only in the user's notes, and the orchestrator pasted it into the next adversarial prompt.
  - The same notes carried two grounder rules into a grounder's prompt, with "the pack has no `enables` relation". That line was written under 0.7.0 and pasted about twenty minutes after 0.8.0 was installed. `/kg-ground`'s text never named `enables`, so nothing the orchestrator read contradicted the note. The re-verdicts it ran rejected two claims that state an `enables` edge, and nobody proposed the edge.
- **Why the contracts:** a rule in one batch's prompt makes that batch judge differently from the others, the split 0.8.0's single relation table exists to prevent. And a rule recalled from an earlier session can predate the contract it contradicts.
- **Accepted trade-offs:**
  - A hub with no counter-span carries no mark and may be offered again, as in 0.8.0; the stricter rule makes that more likely. A falsifying question writes nothing, so it has nowhere to carry the mark, and a counter-edge written only to mark a hub would cost a permanent rejected edge.
  - The orchestrator still holds whatever its session remembers. The command can only say where the rules are.
- **Pinned in:** `tests/test_fix_node_scope_and_counters.py`.
  - **Checked end to end:** on the same copies, the adversarial grounder attacked the field hub `aprobacion-humana-se-erosiona` with one counter-edge whose span sits under the source's «El mejor argumento contra cada conclusión». It reported three contradictions between documents instead of writing them. The orchestrator sent both templates as written.

## A rejected claim carries a lead, and /kg-build --leads writes it (2026-11-08)

- **Decision:** when a grounder rejects a claim as `wrong-relation` or `wrong-node`, it passes the edge the span does state to `kg_ground` as `lead="<head-id> <relation> <tail-id>"`. The engine checks the relation against the pack and appends `lead: <head> <relation> <tail>` to the rejected edge's notes. `kg_build_plan("--leads")` lists the pending leads by the section that holds each rejected span. `/kg-build --leads` launches one extractor per section, and `kg_section(..., leads=True)` hands it the leads with their spans. The extractor writes each lead as an ordinary `unverified` claim, its notes opening with `lead (from <rejected-edge-id>)`, and the next `/kg-ground` judges it. `kg_ground_plan` counts what waits in `queue.leads_pending`.
- **Gap it closes:** the grounding loop converged on the field canon, but over three passes the grounders' reports had named thirteen leads, and none could be written (field report on 0.8.1). Among them were two `enables` edges, the relation the 0.8.0 pack added, and the narrower `manipulacion-de-tests` node. `/kg-build` skips every section that already has edges, and a lead lived only in a report and the user's memory notes.
- **Why the rejected edge's notes:** they are canon, so a lead survives a reprojection, and the engine already reads marks there: `[diverge] pinned` and the adversarial mark. The canon format does not change. A lead sets no state, so the verdict monopoly is untouched.
- **Why an extractor writes it:** a lead often names a node the canon lacks. Choosing that node's id, type and label against the section's `known_nodes` is extraction, and a grounder that wrote it would also be judging its own proposal. Its span is the rejected edge's own, since a lead is by definition what that span states.
- **Why "taken" is a mark, not an id:** the extractor may reuse a known node for the lead's new end, so the edge it writes need not have the lead's id. A lead counts as taken once an edge's notes open with `lead (from <its rejected edge>)`, or once the lead's own edge exists in any state. Each lead is so written once, and a lead edge rejected in turn is failure memory like any other.
- **Rejected alternatives:**
  - (a) *Re-extract the whole section:* it rewrites every edge of the section, a changed span reopens its verdict, and the extractor may miss the lead again.
  - (b) *Let the grounder write the lead:* it breaks the judge's single responsibility, and without the section's `known_nodes` it coins near-duplicates, the failure that produced `manipulacion-de-tests` in the first place.
  - (c) *The propose lane (`kg_propose`):* a lead has a verbatim span, so it is no hypothesis. It would enter `hypothesized` and need a promotion it does not need.
  - (d) *A ledger in `.kg/`:* engine state rather than canon, lost on a clean, and one more file that says what the canon could.
- **Accepted trade-offs:**
  - A lead its extractor declines (the text does not state it) is offered again on the next `/kg-build --leads`. The command re-launches its section at most once in a run.
  - A lead whose rejected span left the source is reported in `leads_unlocated` and not written: the claim has to be judged again first.
  - Leads recorded before 0.9.0 are prose in reports and notes; the engine cannot read them. A one-time pass can re-stamp those rejected edges with a lead, verdict unchanged.
  - Leads the adversarial grounder names without a span, and contradictions between documents, stay in the reports.
- **Pinned in:** `tests/test_fix_leads_path.py`.
  - **Checked end to end:** three headless passes, in auto mode with Claude Code 2.1.316, over five field edges written fresh on scratch copies of their documents. `/kg-ground` rejected four with a lead each. `/kg-build --leads` wrote all four through one extractor per section, with ids only in the prompts, and the next `/kg-ground` grounded them. No pass ran a shell command or was denied a permission.

## An attack that writes no counter-edge is recorded, so its hub is not offered again (2026-11-08)

- **Decision:** a new tool, `kg_record_attack(hub_id, question, reason)`. The adversarial grounder calls it for each hub it attacked where `kg_write` accepted no counter-edge (its contract's Output B), with the falsifying question its attack ended with and its decline tag, `no-span` or `vague`. The engine appends one fsync'd JSON line, `{hub, at, reason, question}`, to `<project>/.kg-hub-attacks.jsonl` (`canon.HUB_ATTACKS`) under the writer lease. `kg_ground_plan` reads the ledger fail-open (`groundplan.attack_records`), and `groundplan.already_attacked` counts each record as a counter-edge judged at the time of the record. A focus still skips the memory.
- **Bug it fixes:** a hub whose attack found nothing was offered to an attack on every later pass (field report on 0.9.0).
  - The grounders had rejected both counter-edges on `escribir-codigo-parte-pequena`. One of them got a lead whose span is the source's own support for the hub («Solo el 21 % pasa más de media semana escribiendo código nuevo»), and the next pass grounded that lead. Its newest grounded claim was then newer than its marks, so the plan offered it again. That is the rule working: a new claim can be attacked.
  - The re-attack searched eight documents and wrote nothing, so it left no mark. Nothing would ever have changed that, and every later `/kg-ground` would have attacked the hub again for nothing, on Opus.
  - 0.8.0 accepted this as a trade-off for a rare case (see "A hub is attacked once until it gains a grounded claim", above). The 0.9.0 leads make it common: an attacker that misreads the source's support as a counter gets its counter-edge rejected with a lead, and that lead becomes a grounded claim on the hub, which reopens it.
- **Why a ledger beside the canon:** the record says what the engine did, not what the source says, as the verdict audit log does. The canon has no place for it that costs nothing:
  - a counter-edge written only to carry the mark is a permanent rejected edge (0.8.1's reason);
  - a line in the hub node's body would enter what `kg_ground_item` shows a grounder as the concept the node names, which the `wrong-node` check reads, and what search and context read;
  - a node field would change the canon format, its merge driver and the reconciler, for a fact that is not about the source.
- **Why this reverses 0.8.0's rejected alternative (a):** that one rejected "a new tool and a new state file, and its loss would bring the repeats back silently". The field shows that the repeat is now the common case, so the tool pays for itself. And losing the ledger brings back only 0.9.0's behaviour, which shows up in the open: the plan offers the hub, and the command reports that it attacked it. 0.9.0 rejected a ledger for leads because the canon could hold them (the rejected edge's notes); an attack that wrote nothing has no edge to hold it.
- **Rejected alternatives:**
  - (a) *Leave a hub out when its newest claim is a lead taken from its own counter-edge:* it fixes the field case only. A hub that gains a claim from a new build, and whose re-attack finds nothing, would still come back on every pass.
  - (b) *Have the orchestrator record the attack:* it would have to read the record out of the adversarial grounder's report. The grounder knows which hubs it attacked, and why it wrote nothing.
  - (c) *Write the falsifying question through `kg_propose`:* a question is not a claim. It would enter the grounding queue, and no grounder could ever ground it.
- **Accepted trade-offs:**
  - The record depends on the adversarial grounder calling the tool. A hub whose attack skips it is offered again, as in 0.9.0.
  - A record vouches for nothing: the hub's claims keep their verdicts, and a focused `/kg-ground <hub>` attacks it again.
  - The ledger is per machine, like the audit log: a clone without it offers those hubs to one more attack.
  - A record names the hub's id at the time, as the counter-edge mark does, so after `kg_rename` or `kg_merge` it no longer applies to the renamed hub.
  - Hubs attacked before 0.10.0 without a counter-edge have no record. The field hub `escribir-codigo-parte-pequena` is one, so the first 0.10.0 pass attacks it once more, unless a record is written for it by hand from the last report's question.
- **Pinned in:** `tests/test_fix_attack_record.py`.
  - **Checked end to end:** a headless `/kg-ground`, in auto mode with Claude Code 2.1.316, over the field hub set up as the field left it (its counter-edges rejected, then three claims grounded after them) on scratch copies of its document. The adversarial grounder found no counter-span, wrote nothing, and called `kg_record_attack` with its question. The next plan listed the hub in `attacked_hubs` and offered none. No pass ran a shell command or was denied a permission.

## A connective does not decide between `grounds` and `enables`, and each contract is its agent's rulebook (2026-11-08)

- **Decision:** the relation block that the extractor and grounder contracts share now glosses `grounds` as evidence or a reason to believe ("the span offers the HEAD as what shows the TAIL is true, or as a reason to think it is"), and `enables` as what makes the TAIL possible or makes it work. It says that a connective does not decide between the two, with the field span as its example. The extractor's shortcut list says the same. The grounder, adversarial-grounder and extractor contracts each open with "**Your rules are this contract.**": a project's memory notes can reach the agent, an agent takes no rule from them, and where a note disagrees with the contract, the contract wins.
- **Bug it fixes:** grounders ruled one span two ways (field report on 0.9.0).
  - The span was «O puedes bajar la variedad del entorno hasta que el controlador que sí puedes construir sea suficiente. Por eso funcionan los robots industriales». The grounder that re-stamped the pre-0.9.0 leads sealed `bajar-la-variedad-del-entorno grounds robot-industrial`, because «por eso» gives a reason. The next pass's grounder rejected that edge as `wrong-relation`, for `enables`, since lowering the variety is the means that makes the robots work. It noted that the block's gloss, "the HEAD shows, or is why, the TAIL is true", also fits «por eso».
  - The first grounder had opened the user's memory note on grounder rules by itself. Its prompt was a one-time custom task, not the `/kg-ground` template, which says "Do not read files". The note lists «porque», «por eso» and «muestra» as cues for `grounds`, a list no contract has. Claude Code attaches the project's memory index to every subagent, so a note can reach an agent with nothing pasted into its prompt. 0.8.1 closed only the orchestrator's channel.
- **Why the HEAD's role, not the connective:** «por eso», «porque» and «así que» introduce an explanation either way. It can be a reason to believe a claim, as in «…así que el techo de ahorro es modesto», grounded in the field as `grounds`. Or it can be the means that makes a thing work. A rule that "the TAIL of `grounds` must be a claim node" was considered and dropped: on the field canon, 9 grounded `grounds` edges have a failure or an operation as their TAIL, most of them evidence that a failure happens («muestran que ocurre»). That rule would have reversed sound verdicts.
- **Why a line in each contract:** the note was corrected too, with the user's approval, but the plugin cannot see a user's notes, and the next stale one would look like a plugin bug again.
- **Rejected alternatives:**
  - (a) *Cue words per relation in the contract:* a list of cues is what went stale, and a connective fits both relations.
  - (b) *Forbid agents to read files:* the adversarial grounder must read the sources, the `/kg-ground` grounder template already says "Do not read files", and an agent still sees the memory index.
- **Accepted trade-offs:**
  - An agent may still open a note. The contract can only say which one wins.
  - The headless extraction backend (`kg_engine.backend`) has its own short prompt, with no relation table, and is unchanged.
- **Pinned in:** `tests/test_fix_connective_and_notes.py`.
  - **Checked end to end:** in the same run, the grounder rejected the robot span as `grounds` (`wrong-relation`, lead `enables`), grounded it as `enables`, and kept «…así que el techo de ahorro es modesto» as `grounds`.

## Above its reproject gate, the precontext hook serves only a fresh index (2026-11-08)

- **Decision:** `hooks/precontext.py` runs the projector's `is_stale()` on every call. Up to `_MAX_HOOK_REPROJECT_NOTES` (400) notes it reprojects a stale index, as before. Above that it injects nothing while the index is stale, and serves the index again once the server's next read has reprojected it.
- **Bug it fixes:** the hook showed retired nodes (field report on 0.10.0). On a canon of 410 notes, a Grep made 13 s after six `kg_merge` calls was shown the edges of `reward-hacking` and `sensibilidad-al-formato`, two nodes those merges had retired, while `get_node` no longer found them. The session took the hook for a copy that is never updated.
  - Write tools leave the derived index stale until the server's next read reprojects it (`_ensure_projected`). The hook reprojects by itself only up to 400 notes, because it is killed at 5 s, and a projection's betweenness pass cannot finish inside that on a large canon (review-r4: hook-reprojects-doomed-on-large-canons). Above the gate it served the stale index, "the same one-projection-lag the server already tolerates elsewhere".
  - The field canon crossed the gate in its first `/kg-ground`, when the first hub attack's counter-edges took it from 399 notes to 406. From then on, after any verdict, merge or rename, the hook could show a node that no longer exists or a verdict that has changed, without saying so. Its own comment names that harm: "a raw kg_context read off a stale projection would inject obsolete provenance / epistemic labels".
- **Why silence:** the hook is best-effort context, and its contract is to fail silent. A stale block carries wrong values for the labels it exists to report, provenance and epistemic state, and nothing in it says it is stale. Silence costs a few Greps without context, until any server read reprojects.
- **Why `is_stale()` is affordable there:** it computes no centrality. Its pre-gate is O(dir-listing), and past it only the notes whose stat moved are re-parsed (review-r6). An mtime-only touch re-arms the pre-gate, so the hook does not fall silent for one.
- **Rejected alternatives:**
  - (a) *Raise or re-base the gate:* the server reprojected the 410-note canon in 0.3 s in WSL, so the gate is conservative for a sparse canon. But a gate measured on Linux does not bound the cost on Windows, where the hook is killed, and a canon past any gate would still be served stale.
  - (b) *Label the block as stale:* it would still put retired ids and old verdicts in front of the session, with nothing better to act on.
  - (c) *Reproject after every write:* writes stay fast by design ("Writes never pass through this seam"), and a `/kg-ground` pass writes many times.
- **Accepted trade-offs:**
  - Above the gate, after a write, the hook stays silent until a server read reprojects. A session that only greps files gets no context until then.
  - A source edit silences it the same way, since the source signature is part of `is_stale()`.
- **Pinned in:** `tests/test_fix_precontext_stale.py`.
  - **Checked on a copy of the field canon** (410 notes): the hook served the fresh index, fell silent after a rename, and served the renamed node once a server read had reprojected. The 0.10.0 hook showed the retired id at the same step. A hook call took 0.13 s in WSL, against 0.08 s before. The copy was deleted.

## A re-verdict that keeps an edge's state keeps the time the edge entered it (2026-11-08)

- **Decision:** when `kg_ground` applies the state an edge already has, it leaves `verdict_by` and `verdict_at` as they are. Those two fields now record who put the edge in its state and when. The re-verdict's note and lead are still appended to the notes, and the audit log still records the call at its own time. A change of state stamps both fields, as before. An edge that is in a verdict state with no `verdict_at` gets stamped.
- **Bug it fixes:** re-confirming a claim reopened an attacked hub (field report on 0.10.1).
  - `kg_ground_plan` leaves out a hub an adversarial pass has attacked until one of its claims is grounded after the attack (0.8.0; 0.10.0 extended this to attacks the ledger records). It reads the time a claim was grounded from `verdict_at`, and `kg_ground` stamped that field on every call. So a verdict that kept a grounded claim grounded made it look newly grounded, and the next `/kg-ground` would attack the hub again with nothing new to find.
  - The Windows corpus converged on 0.10.1 with every edge verdicted. But 142 of its 162 grounded edges carry a `verdict_at` from before the v0.8.1 tag, and 136 from before v0.8.0. Its first pass ran on 0.6.x/0.7.0, before `enables` existed and before the rules on tables and on what each node names. One of those edges, `escenarios-reservados defends_against hacer-trampas-con-los-tests`, was re-judged by hand that day and rejected as `wrong-node`. Re-judging the rest under the current contract is the natural next step, and a random sample of 20 of them touched four attacked hubs. On a scratch copy of that canon, re-confirming one claim of `radar-meta` and one of `autonomia-n4-a-escala` put both hubs back in the plan.
  - The same stamp moved a counter-edge's attack mark. Re-sealing a rejected counter-edge with a lead, as the 0.9.0 lead backfill did, moved the mark to the time of the re-seal. A claim grounded between the attack and the re-seal was then hidden, and the hub stayed out of the plan when it should have come back.
- **Why the fields, not the plan:** the hub memory is the only reader of `verdict_at`, and what it needs is the time an edge entered its state: for a claim, when it was grounded; for a counter-edge, when the attack was judged. R3 and its mirror key on spans and on the source set, not on this time. The plan sees only the canon, so telling a re-confirmation apart from a state change there would need the audit log or a new field.
- **Why the re-confirmer is not recorded on the edge:** `verdict_by` and `verdict_at` describe one event, the one that set the state. A human who re-confirms an agent's verdict through the Python API is recorded in the audit log, and the edge keeps `agent`. That understates the verdict and never overstates it. The MCP surface attributes every verdict to the agent anyway.
- **Rejected alternatives:**
  - (a) *Read each claim's last transition into `grounded` from the audit log in the plan:* the plan would gain a second source of truth. That log is engine state, read fail-open, and lost on a fresh clone, where the hubs would then reopen.
  - (b) *A new `grounded_at` field:* it changes the canon format, the merge driver and the reconciler for one reader.
  - (c) *Leave it, and re-attack:* a re-verdict is the only way to judge an edge again under a changed contract, and every reopened hub costs an adversarial pass on Opus that has nothing new to find.
- **Accepted trade-offs:**
  - Existing times are not rewritten. A counter-edge the 0.9.0 lead backfill re-sealed keeps its later mark.
  - A human re-confirmation does not show on the edge.
- **Pinned in:** `tests/test_fix_same_state_reverdict.py`. Against the 0.10.1 engine, the five tests that pin the fix fail and the four controls pass.
  - **Checked on a copy of the field canon:** the same two re-confirmations left the plan's `hubs` empty. The copy was deleted.

## `confounded_by` is a confound that biases a figure, whichever way (2026-11-09)

- **Decision:** the relation table that the extractor and the grounder share reads `confounded_by` as "the biased metric/value | the confound that biases it". A confound may inflate the figure, lower it, or make it count something other than what it claims to. The pack comment, its schema reference (`skills/burgess/references/pack-schema.md`) and the adversarial contract say the same.
- **Field report on 0.10.2:** the 142 first-pass grounded edges of the Windows corpus were judged again under the current contract, and 20 changed. Grounders in several batches ratified eight `confounded_by` edges whose confound does not inflate the figure: equivalent mutants lower a mutation score, a denominator moves a usage figure both ways, and a share taken over comments instead of reviews misstates what review finds. Each of those grounders noted that the table said "inflated", and ratified anyway, reading the relation as "distorts". The pack has no other relation for such a confound.
- **Why widen it, not reject them:** taken literally, the eight would be `wrong-relation` with no lead, since no pack relation fits, and true, specific claims about why a figure misleads would leave the graph. A confound biases an estimate in either direction. "Inflates" described the case Burgess was built around, the generality confound that inflates betweenness, and that case stays.
- **Rejected alternatives:**
  - (a) *Keep "inflates" and judge the eight again:* they would be rejected with no lead.
  - (b) *A second relation for a confound that lowers a figure:* the direction belongs to the confound, and its span states it. It is not a different kind of claim, and the extractor would have to choose between two relations for one notion.
  - (c) *File them under `attacked_by`:* `attacked_by` is a more specific claim that defeats a vaguer one, not a bias in a measurement.
- **Accepted trade-offs:**
  - The eight field edges were ratified under the old wording and are not judged again: they match the new one.
  - The table still says nothing about a limit on precision, such as a small sample, which biases nothing. The one field edge that names one also names a missing randomization.
- **Pinned in:** `tests/test_fix_confounded_by_bias.py`. Against the 0.10.2 texts, all ten tests fail.

## A lead belongs to the rejection that recorded it (2026-11-09)

- **Decision:** a verdict that changes an edge's state and records no lead of its own withdraws the lead the edge's notes hold. `kg_ground` appends the segment `lead: none` after the verdict's note, `groundplan.lead_of` reads it as "no lead", and the call returns the withdrawn lead as `lead_withdrawn`. A verdict that keeps the state keeps the lead, and a lead a verdict records replaces the old one, as before.
- **Field report on 0.11.0:** the re-judge of the first pass rejected three grounded edges as `wrong-node`, each with a lead to a new node. The user ruled that each node already named what its span names, and a grounder grounded the three again. Their leads stayed in their notes, and `lead_of` returned the newest `lead:` segment whatever came after it. So a later rejection without a lead would have put an overturned lead back in `leads_pending`, and `/kg-build --leads` would have written a node the user had ruled a duplicate. Nothing had triggered it yet: `/kg-ground` never judges a grounded edge again, so only a hand-run re-judge could.
- **Why a change of state:** a lead is the edge the span states instead, according to the rejection that recorded it. When the edge leaves `rejected`, that rejection is overturned, and its lead goes with it. Re-entering `rejected` is a new rejection, which carries its own lead or none. A re-confirmation is not a new rejection: since 0.10.2 it keeps the edge's time, and it keeps the lead too, since a grounder who confirms a rejection without naming a lead has not said the old one is wrong.
- **Why a segment in the notes:** the lead lives in the notes (0.9.0), and the notes mark no verdict boundaries. A segment written at the change keeps the canon self-describing and needs no audit-log lookup. It also covers leads overturned before 0.11.1: the next change of state withdraws them, and that is the verdict that would otherwise have revived them.
- **Rejected alternatives:**
  - (a) *Count a lead only when it ends the notes:* every verdict's note would retire a lead, a re-confirmation's included, and a verdict with no note would leave an overturned lead in force.
  - (b) *Any verdict without a lead withdraws it:* a re-confirmation would drop a lead nobody had ruled out.
  - (c) *A structured lead field on the edge:* a schema change for a patch, and the existing notes would still have to be read.
  - (d) *Delete the old lead from the notes:* the notes are the edge's verdict history, and `kg_ground` only ever appends to them.
- **Accepted trade-offs:**
  - The three field edges keep their overturned leads in their notes, with no `lead: none`, until their next change of state. Being grounded, they are not pending meanwhile.
  - `lead: none` is a reserved segment. A lead whose head is a node called `none` still reads as a lead, since it has three words.
- **Pinned in:** `tests/test_fix_overturned_lead.py`. Against the 0.11.0 engine, with `LEAD_NONE` defined in the test, 8 of its 11 tests fail; the other 3 pin what stays the same.

## Each engine has its own readiness marker (2026-11-09)

- **Decision:** the supervisor names a fresh readiness-marker file in `KG_DATA` for each engine it spawns (`.engine-ready-<supervisor pid>-<12 hex digits>`) and hands its path to the engine in `KG_READY_MARKER`.
  - The engine writes the file as its serve loop comes up and removes it when it shuts down cleanly. The supervisor reads it once the child has exited, then removes it.
  - An engine started without `KG_READY_MARKER` writes no marker.
  - A supervisor removes markers more than an hour old as it starts, the single `.engine-ready` of earlier versions included.
- **Bug it fixes:** sessions shared one marker. The supervisor exits after a crash once the engine has served `initialize`, because a relaunch would sit uninitialized on a connection the client has already set up. A crash during startup gets one venv rebuild and a relaunch in place instead. The marker is what tells the two apart, and through 0.11.1 every engine wrote it as `.engine-ready` in `KG_DATA`. An installed plugin sets `KG_DATA` to `CLAUDE_PLUGIN_DATA`, one dir for every session on the machine, whatever its folder.
  - A supervisor deleted the marker before each spawn, and an engine deleted it as it shut down cleanly, whichever session had written it. A marker another session's engine had just written passed for this one's.
  - So a crash in an engine's first 20 s (`EARLY_FAILURE_MS`) could be read either way wrong when another session started or stopped its engine meanwhile. A post-init crash could pass for a startup failure, with a venv rebuild nobody needed and a relaunch onto a dead connection: the case the marker was added to prevent. A startup failure could pass for a post-init crash, with no self-heal.
  - Found on 2026-11-09 while checking the Windows install after 0.11.1. Its `server.log` showed a desktop session in another folder on 0.11.0 and the prueba-burgess terminal session on 0.11.1 running engines at once. No crash had hit it: all 21 exits in that log were clean.
- **Why a path the supervisor hands over, not the engine's pid:** on Windows the venv's `python.exe` is a launcher that starts the real interpreter as its own child. On the user's machine that day, the supervisor (`node.exe` 33352) spawned `.venv\Scripts\python.exe` as 34792, which started uv's CPython 3.12 as 496. The engine's marker said `pid=496`, and the supervisor only knew 34792. A name the supervisor chooses needs no pid, and no mtime comparison against the spawn time either, so the 2 s clock slack goes.
- **Why a sweep, and why an hour:** a per-spawn name is never reused. So a marker left by an engine killed together with its supervisor, with nobody left to read it, would stay for good. A marker only decides how an exit in its engine's first 20 s is read, so one an hour old matters to nobody. Sessions of 0.11.1 or earlier clear their shared marker before each spawn, so sweeping a stale one takes nothing from them either.
- **Rejected alternatives:**
  - (a) *Keep one marker and check the pid written in it:* a spawn and a clean shutdown would still delete other sessions' markers, and on Windows the pid in the marker is not the child's.
  - (b) *A data dir per session:* every session shares what else `KG_DATA` holds: the venv, the logs and the derived index, which the server and the hook reproject when it does not match their canon. Only the marker needed splitting.
  - (c) *Drop the marker and keep only the 20 s window:* a fast post-init crash would again be relaunched onto a dead connection, the case the marker was added for.
- **Accepted trade-offs:**
  - Sessions still on 0.11.1 or earlier keep sharing their single marker among themselves until they update.
  - A marker left by a hard kill stays until a supervisor starts more than an hour later.
- **Pinned in:** `tests/test_fix_shared_ready_marker.py`. Against 0.11.1, with `READY_MARKER_ENV` replaced by its value in the test, all 11 fail; there the end-to-end startup failure is logged as `servedInit=true -> post-init-exit`.

## The report says what it leaves out (2026-11-10)

- **Decision:** `GRAPH_REPORT.md` keeps its cap of 50 items per list, and a list that stops at the cap ends with a line saying how many more there are. Single-node communities share one entry after the other communities, which lists up to 50 names the same way.
- **Gaps it closes:** found on 2026-11-10 while reviewing a `/kg-view` run on the Windows corpus (425 nodes, 221 edges: 162 grounded, 58 rejected, 1 failed).
  - The falsification memory header said 59, and the list stopped at 50 without a word. The canon and `graph.html` kept all 59, so nothing was pruned, but the report read as if it listed them all. §1.7 never prunes negative information, and a view that drops part of it silently understates it.
  - A node with no live edge is a community of its own, and each community had its own entry of five lines. 172 of the 264 communities had one node, so their entries made up most of the report.
- **Why keep the cap:** a large graph can carry thousands of rejected edges, and the report is a summary. `graph.html` draws every edge and the canon holds every verdict.
- **Why 50 names in the shared entry, not the 8-name preview the other communities get:** the nodes with no live edge are the ones nothing connects yet, which reads best as a list. 50 is the cap the other lists already use, and the entry says how many more there are.
- **Why the shared entry keeps an edge line:** an edge inside a one-node community is a self-loop. Every write lane rejects one, but a hand-edited canon can still carry it, and through 0.11.2 the community's own entry showed it.
- **Rejected alternatives:**
  - (a) *Drop the cap:* the report would grow without bound on a large graph.
  - (b) *Leave single-node communities out of the report:* those nodes would vanish from it, and the entries would no longer add up to the node count.
  - (c) *Keep one entry per single-node community but shorter:* still one line per unconnected node, 172 on the corpus.
- **Pinned in:** `tests/test_fix_report_caps.py`. Against 0.11.2, 7 of its 10 tests fail; the other 3 pin what must not change.

## The measurement commands run on an installed plugin (2026-11-10)

- **Decision:** `/kg-eval` and `/kg-experiment`, and the annotator and evaluator they drive, run wherever the plugin is installed, Windows included.
  - Every path comes from a token Claude Code fills in: `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}` and `${user_config.source_path}`.
  - The engine's interpreter comes from `scripts/engine_python.mjs`, the launcher's own rule, and every Bash block that runs the engine resolves it first.
  - A source may be a folder of documents. The harness and the LightRAG arm read it as the projector does, as `SourceSet(path).concat`.
  - `/kg-experiment` drafts its prompts from the user's graph unless the source is the demo corpus, and saves them so a rerun can reuse them.
  - Below target, an installed copy of `/kg-eval` records the refinements it would make instead of editing itself and rebuilding the canon. A development checkout iterates as before.
- **What it fixes:** found on 2026-11-10, when the user asked what else to try on the Windows corpus. Neither command had been run there; as written, both would have failed or measured the wrong thing.
  - Every Python step named `/home/sergi/Burgess/.venv/bin/python` or `${CLAUDE_PLUGIN_DATA}/.venv/bin/python`. Neither exists on the user's machine; on Windows the interpreter is `.venv\Scripts\python.exe`.
  - `${VAR:-default}` paths are never filled in, so `/kg-eval` would have looked for its graph in `<project>/.kg-data` and told the user to run `/kg-build`, `/kg-experiment` would have written under `/tmp`, and `/kg-generate`'s absorption ledger would have landed where `kg_absorption` never looks.
  - The source was the repo's `examples/source.md`, and the harness CLI read its path with `read_text`, which fails on the user's folder of eight documents.
  - The 12 default prompts name the demo's concepts. On another corpus every arm answers them from the model's prior.
- **Why a resolver script, not a path in the text:** the launcher's rule has three levels of precedence (`KG_ENGINE_VENV`, the plugin data venv, the plugin root's venv) and a per-platform fallback after the bootstrap pointer. Spelling it out in Markdown forks it, and a fork is how `.venv/bin/python` got there. The script takes the plugin data dir as an argument because a command's Bash steps cannot count on plugin variables in their environment.
- **Why exact tokens:** read from the 2.1.316 binary. The plugin loader replaces exactly `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` and, for a local session, `${CLAUDE_PROJECT_DIR}`; a `${X:-default}` form reaches the shell as typed.
- **Why recommend instead of iterate in an installed copy:** the copy under `plugins/cache` belongs to one version, every project on the machine shares it, and the next update replaces it. Re-extraction rewrites the user's canon, and a measurement must not change what it measures.
- **Why drafted prompts are saved:** the experiment's verdict compares arms over one fixed prompt set. A drafted set is written to `.kg/experiment/` and recorded in `PROGRESS.md`, so the run can be repeated on the same prompts.
- **Rejected alternatives:**
  - (a) *Spell `.venv\Scripts\python.exe` for Windows in the text:* a second copy of the launcher's rule, which would drift like the first.
  - (b) *Keep the demo prompts as the default and ask users for their own:* on the user's corpus the default is the path taken, and it measures nothing.
  - (c) *Let an installed copy refine a project-local pack:* the engine reads its pack from the plugin (`KG_PACK_PATH` in `.mcp.json`), so a project copy would change nothing the extractor sees.
- **Pinned in:** `tests/test_fix_field_eval_experiment.py`. Against 0.11.3, 29 of its 66 tests fail; the other 37 are per-file checks on texts that were already clean, plus two guards.

## A query finds the edges it is about (2026-11-10)

- **Decision:** `kg_context(query=…)` and the new `query_graph(text=…)` match **search words** and rank by relevance.
  - A search word is a `/kg-build` content word (`buildplan._words`: casefolded, accents dropped, Spanish and English function words gone, at least three characters unless a number), plus a two-character letter-digit code such as `N4`. Words match across a plural ending (`buildplan._forms`).
  - An edge offers its span, relation and both endpoints' ids and labels; a node offers its id and label.
  - Matches rank by the summed rarity weight of the shared words, log(1 + N/df) over the rows searched, then by how many are shared, then in the surface's order without a query. In `kg_context`, grounded before unverified stays ahead of relevance.
  - `kg_context` reports `items_total`, `hypotheses_total` and `query_terms`; `query_graph(text=…)` reports `query_terms` and `matched`.
  - `/kg-query` says which tool finds what, that `epistemic_state` is the verdict and `authored_by` only the author, that spans come from the configured source, and that the answer comes from the tools, not from reading `canon/` through the shell.
- **What it fixes:** found on 2026-11-10 while reviewing a `/kg-query` on the Windows corpus. The answer was faithful, but it took two hours: 19 shell reads of `canon/`, each waiting for the user's approval.
  - The old query was a filter: every run of three or more characters, as a substring of the edge's ids, relation and span. «del» matched 37 of the 61 hits, inside «modelo» too. «revisión» never matched the accent-free id `retirar-revision`, and labels were not searched.
  - The fill then took the hits by the extractor's confidence and by id. The edge the question was about came 24th; the budget held 18, of which the answer used 5. Nothing said 43 were left out.
  - `query_graph` could not find a node by what it says, so the session grepped `^label:`.
  - `/kg-query` said an agent-authored edge "has not yet been confirmed by a verdict", which sent the session to check `verdict_by` in the canon.
- **Why words, not substrings:** a substring cannot tell «del» from «modelo», and SQLite's `LIKE` cannot fold accents. The ids are accent-free by the extractor contract, so an accented question never met them.
- **Why rarity weights, not a longer function-word list:** the list covers Spanish and English, and a corpus in another language, or a common content word such as «puede», would still flood the ranking. The IDF lets every common word count for little. It is the weight `buildplan.related_nodes` already ranks node names by, so the engine keeps one notion of a specific word. The sum is rounded to nine places, so two platforms' `log` cannot reorder a tie.
- **Why grounded first still beats relevance:** `items[]` is the grounded lane. A strongly matching unverified edge is a candidate, and a reader of `/kg-query` leads with facts. The hypothesis lane stays separate, as before.
- **Why rank in Python, not in the index:** the match is on folded words, which SQLite cannot compute, and the weights need each term's frequency over the whole lane. Precomputing words per row would change the derived schema and force a rebuild of every index. A search reads each row of a lane once: about 5 ms on the field canon and about 100 ms on 10 000 edges, inside the hook's 5 s cap.
  - Two shortcuts keep it there. `buildplan._fold` drops combining marks with one `str.translate`; the output is the same, checked over every code point. A row's text is split into words only when some form of a term occurs in it as a substring, which skips no match because a word's forms are its prefixes.
- **Rejected alternatives:**
  - (a) *Keep `LIKE` and add stopwords:* still substrings, still no accents, still no ranking.
  - (b) *Rank relevance ahead of the grounded split:* weakly matching grounded facts would trail strongly matching candidates in the lane `/kg-query` presents as fact.
  - (c) *SQLite FTS5 with `remove_diacritics`:* a new virtual table in the derived schema, a rebuild of every index, and a second tokenizer that would disagree with `/kg-build`'s words.
  - (d) *Embeddings:* the razor holds; embeddings measure dispersion, never truth, and a convergence read stays rule-bound.
  - (e) *Expose `verdict_by`, node bodies and verdict notes through `get_node`:* the derived layer omits them by design, and the answer does not need them. `/kg-query` now says a canon note is for the question "why this verdict?".
- **Checked:** two headless `/kg-query` runs on a copy of the field canon, with Bash denied, answered from 9 and 6 tool calls in 40 and 31 s and tried no shell command. The first wrote its `query_graph` text in English, following an English example in the command, and matched 2 nodes. The command now says to write it in the documents' language, and the second run's Spanish text matched 39 nodes.
- **Pinned in:** `tests/test_fix_query_relevance.py`. Against 0.11.4, 23 of its 28 tests fail; the other 5 are Cyrillic matching and four guards. `test_review_r6.py` F6 and `test_review_r9.py` L10 now pin their regressions through the new term extractor.
- **0.11.6, the word limit is stated:** a search uses its first 12 search words (`_QUERY_TERM_CAP`), and through 0.11.5 only `query_terms` showed it. On the field re-run, /kg-query searched `query_graph(text="h1 h2 … h20")` and got h1–h12 without being told why. `/kg-query`, `tools.md`, `docs/ARCHITECTURE.md` and both tool descriptions now state the limit and say to split a longer list over several searches. The limit itself stays, since it bounds the per-row work (review-r6). Pinned in `tests/test_fix_query_word_limit.py`, which ties each stated number to the constant: against 0.11.5, 3 of its 4 tests fail, and the fourth is the engine-side guard.

## The measurement log stays out of the source, and the annotators need no shell (2026-11-10)

- **Decision:** `/kg-eval` and `/kg-experiment` keep everything they write under the project's `.kg/`.
  - Their log is `.kg/PROGRESS.md`.
  - The annotator reads with `Read` and `Grep` and writes its labels as one JSON file with `Write`. It has no shell.
  - `/kg-eval` checks a refinement against the current contract before recommending it.
  - Three deterministic helpers back this:
    - `f4_probe.py fill` writes labels into a sheet;
    - `harness writers` splits a labeled sample by who wrote each edge and by its verdict;
    - `harness legacy-log` notes an earlier version's log that the source still reads.
- **What it fixes:** found on 2026-11-10, in the first field `/kg-eval` (0.11.6, Windows). Its numbers were right: precision 0.84 and α 0.901 both check out against its CSVs.
  - **The log was in the source.** 0.11.4 put the log at `<project>/PROGRESS.md`. The user's source is the project folder, and `SourceSet` reads every `.md` at the top of a source folder. So the log became a ninth document, and the source grew from 84 sections to 85. The next `/kg-build` would have extracted it, and `/kg-experiment`'s `rag` arm and its scoring would have read it as source.
  - **The annotators used the shell.** The annotator had `Read, Grep, Bash`, and its contract said to write the CSV with Bash; its search step even showed a shell `grep`. All three passes read the documents through `grep` and `sed`. Under the user's `blockReadsOutsideWorkingDirectories`, every one of those calls waited for an approval: 74 from the annotators, plus 7 from the command. Each annotator worked six or seven minutes, and for 51 of the run's 56 minutes one of them was waiting.
  - **The advice was stale.** The session recommended four extractor rules that `agents/extractor.md` has carried since 0.8.0–0.11.0. The 13 edges labeled other than `correct` were 9 first-build extractions from before 0.8.0, 3 counter-edges written by adversarial passes and 1 lead written before 0.11.0. Grounding had already rejected 11 of them.
- **Why `.kg/`:** `SourceSet` skips dot entries, and a recursive glob does not descend into a dot folder, so nothing under `.kg/` is ever a source document, whatever the source is. The run's scratch files already lived in `.kg/eval/` and `.kg/experiment/`.
- **Why a note, not a move:** Burgess does not move or delete what it finds in a user's folder. The old log may have been edited, kept on purpose, or already moved.
  - `/kg-experiment` stops on the note: its `rag` arm and its harness read every source document, so the run would take an earlier run's results for source.
  - `/kg-eval` goes on: its annotators read only the documents their rows cite, so the old log reaches it only as one section of the specificity step's corpus.
- **Why JSON and `fill`, not a CSV written by the annotator:** the csv module quotes; a model writing CSV by hand does not always. The labels' notes quote Spanish spans with commas, double quotes and «». A misquoted CSV shifts columns without an error, and `score` would take the shifted cells as labels. A malformed JSON fails at `fill`, which refuses the whole file, so the annotator rewrites it.
  - Without a shell, the annotator needs at most one approval, for its one `Write`, and none in the user's mode.
- **Why `writers` reads the canon:** the marks that tell a counter-edge (`groundplan.ATTACK_MARK`) and a lead (`LEAD_FROM_MARK`) from an extraction live in an edge's notes, which the derived layer omits by design. The canon is read with `ensure_layout=False`, so the read lays nothing out.
- **Why check the contract instead of dating each edge:** the canon does not record which plugin version wrote an edge. Adding that would be a new field on every edge, a canon schema change. The contract check needs nothing new: if the rule an error breaks is already in the contract, the edge predates it.
- **Why a quoted heredoc for the log:** through 0.11.6 the block appended through `<<EOF`, so a backtick in the model's text, such as a relation in code format, ran as a command. The field session escaped its backticks by hand. Now only the date and the graph path are expanded, by `printf`.
- **Rejected alternatives:**
  - (a) *Have `SourceSet` skip a file named `PROGRESS.md`:* a user's own document may have that name. A filename rule would also silently change the projector's input, its signatures and its coverage.
  - (b) *Move the old log into `.kg/` automatically:* see "Why a note".
  - (c) *Keep Bash and tell the annotator to read only with `Read` and `Grep`:* writing the CSV would still need the shell, and the field annotators had `Grep` and still reached for shell `grep`.
  - (d) *Let the annotator write the CSV with `Write`:* see "Why JSON".
  - (e) *Add writer and verdict columns to the sheet:* the annotators read the sheet, and a verdict column would unblind them.
  - (f) *Add the writer to `graph.json`:* it would change the derived schema and the index's table for one measurement.
- **Checked:** `writers` and `legacy-log` were run read-only on the field data, and the run wrote nothing to the project.
  - `writers` reproduced the split found by hand:
    - by writer: extractor 54 of 63 correct, lead 10 of 11, counter-edge 3 of 6;
    - by verdict: grounded 59 of 61, rejected 8 of 19;
    - the same 13 edges listed.
  - `legacy-log` named the field's `PROGRESS.md`.
- **Checked end to end:** a headless `/kg-build`, then `/kg-eval`, on the demo source copied into a scratch project that is its own source, with an old `PROGRESS.md` planted at its top.
  - Each annotator made two `Read`s and one `Write`, and no shell call. `fill` took all three files at the first try.
  - The command ran 5 shell steps and had no permission denial.
  - Its first step printed the note, and the answer passed it on. The old file kept its bytes, and the new log landed in `.kg/PROGRESS.md` with its backticks as written.
  - Cost: $0.94.
- **Pinned in:** `tests/test_fix_eval_log_and_annotator.py`. Against 0.11.6, 22 of its 46 tests fail. The other 24 already held there: the files that never named the old path, the `SourceSet` behaviour and the extractor rules. `tests/test_fix_field_eval_experiment.py` moves its log path under `.kg/`, and the annotator leaves its "resolves Python first" check, since it has no shell.

## The experiment says which columns measured nothing, and its evaluator needs no shell (2026-11-10)

- **Decision:** `/kg-experiment` keeps its verdict rules and makes the run around them honest and repeatable.
  - `harness ideation` adds `guard_probe` and `caveats`: a plain sentence for each column that could not tell the arms apart in the run. The verdict strings do not change with them.
  - The tokenizer behind every harness count and the projector's node specificity reads Unicode letters. `PROJECTION_RULES` "3" rebuilds an index built under the ASCII one.
  - `harness rag-slices` builds the `rag` arm's passages deterministically: BM25 over the source's paragraphs, accents folded, within the graph arm's 2000-token budget. The command runs it in Step 1b, and the LightRAG helper too when that arm is enabled.
  - The kg-evaluator has `Read`, `Write` and its three MCP tools: no shell and no `Grep`. It writes every control answer before any tool call, answers each other arm from that arm's context only, and takes both generate slates from one `kg_generate` call.
- **What it fixes:** found on 2026-11-10, in the first field `/kg-experiment` (0.11.7, Windows; eight Spanish documents, 445,018 characters). The numbers were right: the score file reproduced exactly from a copy. All three verdicts were negative.
  - **unsupported_rate was 0.0 in every arm and measured nothing.** The guard calls a sentence supported when any of its first three long words occurs anywhere in the source. "El sistema Zorblax de Quantifex redujo las reversiones un 93 % en 2019" passed, and so did an English version; on the 2,741-character demo corpus both are caught.
  - **utility was 0.0 everywhere.** Its markers are English, and since 0.11.4 the prompts are drafted in the corpus's language.
  - **The tokenizer cut words at their first letter outside ASCII.** "revisión" scored as "revisi", in every idea and in 214 of 425 node labels.
  - **The evaluator used the shell for everything a file tool or the engine could do.** It had no `Write`, so it wrote through heredocs, and two of 25 KB failed to parse. It built the `rag` arm with its own retrieval script, which crashed twice on cp1252. That made 14 shell calls and 9 approvals; one waited 26 minutes.
  - **Its procedure opened by reading the source**, before the control pass that must use no file.
- **Why caveats, not a new guard:** a stricter lexical guard changes what the experiment measures. Requiring every key term to occur in the source would count a genuinely novel term as unsupported, and novelty is what the experiment rewards. Which comparison the headline verdict should make is open, and so is how support should be judged. The control arm's novelty is measured against a source it never sees, while the graph arm's spans are verbatim quotes of it; on the field run control won novelty on 12 of 12 prompts, and graph beat rag on 11 of 12. Until that is decided, the harness keeps the rules and says when one of them could not act.
- **Why this probe:** it is the run's own sentences, so it needs no word list and works in any language. Replacing each sentence's first long word with an invented one turns it into the arm's own claim about one invented thing, and the guard's job is to catch exactly that. The 0.9 threshold sits between the field run (0.979) and English ideas on the demo corpus (0.83 for ideas written from its text, 0.27 for ideas written without it, 0.57 pooled), where the guard did tell the two sets apart (0.08 against 0.54).
- **Why BM25:** it is the standard flat-retrieval baseline, deterministic, and needs no stopword list (IDF discounts the words every passage has) or stemmer, so it is equally naive in any language. Query terms are summed in sorted order so the floating-point sum, and so the ranking, never depends on the hash seed. Passages are paragraphs: a heading stays with the paragraph after it, and a paragraph longer than 1,200 characters is cut at line, then word boundaries, so no line the evaluator reads is long. The files hold no scores; the D1 run found numbers in a generator's context leaking into its ideas.
- **Why one `kg_generate` slate for both generate arms:** the `dpp_verdict` compares one candidate set in two orders (I5). `kg_context`'s stored `hypotheses[]` come from earlier `/kg-generate` runs, and the DPP arm's `kg_generate(dpp=true)` call cannot reorder them.
- **Why the tokenizer change is safe:** on ASCII text the two patterns find the same words. On the field graph, re-projected under both, 158 node specificities changed (median 0.3 %), while the specificity gate (off, churn 0.0, the same top five), the top ten weighted bridges and `kg_generate(all, k=12)`'s 51 candidates in order did not. The field ideation numbers moved by at most 0.007, and no verdict changed.
- **Rejected alternatives:**
  - (a) *Add Spanish utility markers:* every corpus language would need its own list, and utility is in no verdict. The caveat is enough.
  - (b) *Keep the evaluator's `Grep` for the rag arm:* retrieval by the model is what made the arm unrepeatable, and reading the source for any other arm gives it context the comparison does not account for.
  - (c) *A fresh generator subagent per prompt, as the D1 run used, for real blindness:* it changes the method and costs twelve subagents. It belongs with the verdict decision.
  - (d) *Make `rag-slices` an MCP tool so its step needs no approval:* a new tool on the trust boundary for one measurement. The command already runs shell steps, and this adds one.
    - *Addendum (2026-11-26):* reversed. Under `permissions.blockReadsOutsideWorkingDirectories` a shell step that
      names the plugin's folder needs a person every time, and the auto mode cannot answer for them; see "The
      measurement commands run their steps in the engine" (2026-11-26).
  - (e) *Stem or lemmatize for retrieval:* language-specific, and the `rag` arm is meant to be naive.
- **Checked:** on copies of the field data, read-only.
  - The new harness flags the field run: 140 of 143 probes passed, and utility had no marker.
  - `rag-slices` on the twelve field prompts found 7 to 14 passages each, from all eight documents. For the selection-bias prompt the first passage is the source's own paragraph on it.
- **Not checked end to end:** the headless `/kg-experiment` could not start, because the CLI's login had expired.
- **Pinned in:** `tests/test_fix_experiment_measurement.py`. Against 0.11.7, 34 of its 36 tests fail; the other 2 check that ASCII text tokenizes as before. `tests/test_fix_field_eval_experiment.py` drops the evaluator from its "resolves Python first" check and moves its LightRAG `--source` check to the command.

## Measurement subagents read blind (2026-11-11)

- **Decision:** the PreToolUse precontext hook injects nothing:
  - into a call made by the `kg-evaluator` or the `kg-annotator` subagent. It reads the caller from the hook input's `agent_type`, the part after the plugin prefix.
  - into a Read, Grep or Glob whose target lies under the project's `.kg/`.
  - Every other call is served as before.
- **What it fixes:** found on 2026-11-10 by the kg-evaluator itself, in the second field `/kg-experiment` (0.11.8, Windows).
  - Four of its fourteen Reads came back with grounded edges and the failure counter attached:
    - the prompt file, read before the control answers that must see no context;
    - the `rag` arm's passage files 08, 11 and 12.
  - The hook's query is the file's stem, and "prompts-<run>" and "08" matched edges. 0.11.8 had widened the path by turning the `rag` arm's context into files the evaluator reads.
  - The kg-annotator reads the source documents it labels, and the edges attached there carry the grounding verdicts that `/kg-eval` keeps from it (0.11.7: a verdict column would unblind it).
- **Why by agent type:** Claude Code's hook input carries `agent_id` and `agent_type` when a subagent made the call, and neither on the main thread. That is its documented way to tell the two apart (2.1.316's input schema). A plugin's agent type is `<plugin>:<name>`, so the rule compares the name after the last colon, and the plugin prefix does not matter. Only the two measurement agents are named:
  - The hook's injection is the plugin's design for exploration, and the user's other subagents and Burgess's grounders get no less than before. Whether a grounder should judge with graph context attached is a separate question that no field report has raised.
- **Why also `.kg/`:** it covers a Claude Code too old to name the caller, and a main session reading a run's files.
  - Everything under `.kg/` is Burgess's own working state: prompts, `rag` passages, eval sheets and labels, the log, the divergence archives. It is never the project's knowledge, so context attached there is noise at best.
  - Only the project's own `.kg/` counts. A relative path resolves against the session's folder, and a Glob's pattern counts by its literal head.
- **Rejected alternatives:**
  - (a) *Silence the hook for every subagent:* it would change what other plugins' and the user's own subagents see, for a problem only measurement has.
  - (b) *Tell the evaluator to ignore attached context:* it cannot unsee it, and the control answers are written after the prompt file is read.
  - (c) *Give the evaluator its prompts in the brief instead of a file:* the `rag` passages would still be files, and the annotator's documents too.
  - (d) *An environment switch the command sets:* a slash command cannot set the environment of the hooks its subagents trigger.
- **Checked:**
  - The hook input schema (`agent_id` and `agent_type`) was read from the Claude Code 2.1.316 binary.
  - The field run's evaluator transcript shows the four attachments and which Reads they rode on.
  - The Windows install runs 2.1.322.
- **Pinned in:** `tests/test_fix_precontext_blind_reads.py`. Against 0.11.8, 8 of its 13 tests fail. The other 5 check calls that were already served.

## A release that only bumps the version leaves the engine venv current (2026-11-11)

- **Decision:** `bootstrap.compute_stamp` hashes `pyproject.toml` without `[project]`'s version line, and with its line endings made LF. `SCHEMA` goes to "2".
- **What it fixes:** found on 2026-11-11, in the first Windows session after the 0.11.9 update.
  - Its MCP server connected after 29,554 ms, against Claude Code's 30 s `MCP_TIMEOUT` default. The launcher found the venv stale and waited 18 s for a rebuild (`stampFresh` → `waitUntilReady`), and the engine then took 11 s to answer.
  - The rebuild installed nothing (`uv sync`: "Checked 57 packages"). The stamp had hashed the whole file, and the version line is the one line every release changes.
  - Read-only on that machine, `bootstrap.py --check` passed with the 0.11.9 copy and failed with the 0.11.8 one.
  - Over the 30 s, the session starts without the Burgess tools until the user reconnects the server in `/mcp`.
- **Why only the version line:** it is the only part of the file that changes without changing what the venv installs.
  - `kg_engine` is read off PYTHONPATH. With uv it is never installed (`uv sync --no-install-project`).
  - The pip fallback does install a copy into site-packages, but `PYTHONPATH=<plugin>/scripts` shadows it and nothing reads its metadata. So an older copy left there by a version-only release is never run.
  - Every other line stays in the hash, `[tool.*]` tables included, even where they do not affect the install. A false rebuild costs a slow first session; a missed one costs a broken engine.
  - The table scope follows `bump_version.py`'s own discipline: only the `[project]` table's `version` key is dropped. A header of either form moves the cursor, so an array of tables cannot inherit `[project]`.
- **Why LF:** the Windows marketplace clone checks text files out with CRLF. A clone made with other git settings would otherwise change the stamp without changing a byte that matters.
- **Why bump SCHEMA:** the hashed content changes for every existing venv anyway. "2" says so where the next reader looks, and keeps a stamp written the old way from ever matching. The cost is one more rebuild, on the first session after this update. From then on, a release with the same dependencies starts without one.
- **Rejected alternatives:**
  - (a) *Hash only `dependencies` and `requires-python`, parsed with `tomllib`:* `tomllib` is not in Python 3.10, which bootstrap supports, and a parsed subset can miss an input such as the build system or an extra.
  - (b) *Raise the launcher's wait or the engine-start reserve:* the window is Claude Code's `MCP_TIMEOUT`, not ours, and the rebuild had nothing to do.
  - (c) *Accept the previous release's stamp during a transition:* the old stamp hashed a version we cannot know, so there is nothing to compare.
- **Checked:** `bootstrap.py --check` on the Windows venv, read-only, with the 0.11.8 and 0.11.9 copies, and the timings in `provision.log`, `server.log` and the session's MCP log.
- **Pinned in:** `tests/test_fix_stamp_ignores_version.py`. Against 0.11.9, 5 of its 14 tests fail. The other 9 check inputs that already moved the stamp.

## The experiment compares grounded novelty prompt by prompt, behind an instrument check (2026-11-11)

- **Decision:** `harness ideation` scores each idea's grounded novelty (novelty × support) and decides each
  pre-declared pair prompt by prompt with a one-sided sign test at 5 %. The headline is graph vs rag. An
  instrument check (rag's support ≥ control's + 0.10) gates every verdict. The method, its revision before
  scoring and its retroactive results are in `docs/fusion/EXPERIMENT.md` ("Stage 8 method, 0.12.0").
- **What it fixes:** three field runs (2026-11-10/11, Windows, eight Spanish documents) gave the same negative
  headline under a rule that could not give another:
  - graph had to match control's novelty, measured from a source control never sees;
  - the guard was blind on a large corpus;
  - pooled single numbers let 0.003 decide.
- **Why graph vs rag as the headline:** both arms get the same source and budget, and the command's own text
  had called rag "the honest comparison". Control stays as a second verdict on the same measure.
- **Why novelty × support:** it rewards leaving the source's wording without leaving its terms. Control pays
  for inventing, and rag for copying.
- **Why support by stem, over the whole source, weighted by IDF:** decided before any field scoring, on the demo
  corpus and synthetic Spanish sentences.
  - **Whole words:** a single unused inflection ("compararía") took the highest weight and read as invention.
  - **One paragraph:** requiring the terms to meet in one paragraph penalized ideas that link two parts of the
    source, which the graph arm exists to produce.
  - IDF still makes an invented term cost the most. The probe measured 0.155–0.162 of support lost per invented
    term on the field runs.
- **Why the sign test:** D1 already decided per prompt (10 of 12). The test makes that threshold a stated
  significance level, and makes "too few prompts" explicit below five.
- **Why an instrument check, and why it decides "not measured":** a support score that cannot tell rag from
  control cannot carry a verdict that depends on it. Saying so is the honest outcome, and through 0.11.x a
  "did NOT clearly beat" stood in that place.
- **Result:** the check failed on all three field runs (gaps 0.048, 0.022, 0.049). On this corpus an
  uninformed writer uses the source's vocabulary for 92–94 % of its key-term weight. Every verdict reads "not
  measured". The prompt-by-prompt counts are recorded but are not verdicts: graph vs rag 9, 7 and 8 of 12;
  graph+generate vs graph 10, 6 and 12 of 12.
- **Rejected alternatives:**
  - (a) *Keep the 0.11.x rule with caveats (0.11.8):* it stays structurally negative.
  - (b) *Local co-occurrence support:* biased against connecting ideas (see the revision); it would need its own
    protocol, declared before new runs.
  - (c) *Lower the check's 0.10 after seeing 0.05:* that would fit the instrument to the data.
  - (d) *A blinded LLM judge now:* it is the next step, but it is not deterministic, it costs about twelve
    subagents a run, and the user chose the lexical method first.
- **Pinned in:** `tests/test_fix_grounded_novelty.py`. `tests/test_fix_experiment_measurement.py` moves its
  0.11.8 blind-guard pins onto the replacement. `tests/fusion/test_experiment_arm.py` and
  `tests/test_harness.py` follow the new rule and keys.

## Blind subagents start without the project's instructions and memory (2026-11-11)

- **Decision:** `kg-evaluator`, `kg-judge` and `kg-annotator` declare `omitClaudeMd: true` in their frontmatter.
  Claude Code then starts them without the user, project and local CLAUDE.md files and without its auto-memory
  index (`MEMORY.md`); managed policy files still reach them. The judge's prompt no longer says how the ideas
  were written or that controls exist.
- **What it fixes:** found on 2026-11-11 while reviewing the first field `/kg-experiment` on 0.13.1 (Windows).
  - Claude Code hands every subagent those files and the memory index by default, in an `instructions`
    attachment. The field session saves each run's results in its memory.
  - In the first judged run (0.13.0), all twelve judges and both evaluator passes received the index line "5
    runs of the 5-arm ideation on the Spanish prompts…: graph never beat control".
  - In the first 0.13.1 run, the evaluator received the judges' verdict: "graph loses to rag 3/9, beats control
    11/1".
  - The pilots' judges, started from the development session, received the repository's CLAUDE.md and that
    session's memory index. In the third pilot the index reported the first pilot's "decoy caught 12/12".
  - The annotators get the same index, which names an edge and how the three coders of an earlier eval
    labelled it.
  - Separately, 0.13.0's judge prompt said "some were written with help, some without, and two are controls
    planted to check you". The command forbids telling a judge that controls exist, and the pilots' prompts
    said only that the judge did not know who wrote the ideas or how. The release's byte-for-byte check covered
    the packets and the aggregation, not the prompt.
- **Why the frontmatter key:** it is Claude Code's own switch for an agent "that takes everything it needs from
  the delegation prompt", read from a plugin agent's file. Claude Code's built-in Explore and web-fetch agents
  use it, and so does Anthropic's claude-test plugin. It removes the memory index along with the instruction
  files.
- **Why only the measurement agents:** the extractor, the grounders and the generator may follow a project's
  CLAUDE.md. Whether stale memory notes should keep reaching the grounders (2026-11-08) is a separate decision,
  not taken here.
- **Rejected alternatives:**
  - (a) *Ask the session not to save results in memory:* the memory belongs to the user's session, its index
    already holds the results, and a command's rule does not bind other sessions.
  - (b) *Tell the blind agents to ignore their context:* they cannot unsee it (as in 0.11.9's (b)).
  - (c) *Turn auto memory off:* a user setting, not the plugin's, and it leaves the CLAUDE.md files in place.
- **Checked:** headless on Claude Code 2.1.316 and 2.1.321, with a throwaway plugin holding copies of the three
  agent files and of the judge without the key. The project had a CLAUDE.md marker and a memory marker.
  - The judge without the key received both markers in its `instructions` attachment and named both.
  - The three agents received no attachment, named neither, and their transcripts hold neither.
  - The Windows install runs 2.1.322, whose binary carries the key.
- **What it leaves on record:** the first judged run's verdict stands as recorded, with these caveats.
  `docs/fusion/EXPERIMENT.md` says what each pilot and run could see.
- **Pinned in:** `tests/test_fix_blind_memory.py`. Against 0.13.1, 2 of its 3 tests fail. The third pins that
  the other agents keep the project's instructions.

## Commands are named the way Claude Code runs them, and --judge states its field cost (2026-11-12)

- **Decision:** every text a user or the model reads names a command in full: `/burgess:kg-build`, not
  `/kg-build`. That covers:
  - the current docs: README, TUTORIAL, CLAUDE.md, `docs/COMMANDS.md`, MIGRATION and ARCHITECTURE;
  - the command files, the operating-guide skill and its references, and `plugin.json`'s option descriptions;
  - the engine's MCP tool descriptions, and the strings it returns or prints.

  The cost of `--judge` is restated from the field.
- **What it fixes:** found on 2026-11-11 around the clean `--judge` replication (Windows, Claude Code 2.1.322).
  - `/kg-experiment --judge` answered "Unknown command: /kg-experiment", and `/burgess:kg-experiment --judge`
    ran. Every command the field sessions ran, in every transcript, was in the full form.
  - The plugin named its commands in the short form, and the field session copied it. In its messages to the
    user it wrote the short form 105 times and the full form 4 times, so its advice to "run /kg-ground" led to
    the error.
  - The command, the README and the command reference said `--judge` costs about 1.5 million tokens for 12
    prompts. That was the third pilot's count, and its judges were general-purpose agents started from the
    development session with its tools and instructions.
  - The field's kg-judges end with 60,000–80,000 tokens of context each. Twelve came to 815,072 and 827,891 on
    two runs, counted the same way. Of what a run processes, about 0.8 million tokens are new and about 1.3
    million are read back from the prompt cache.
- **What keeps the short form, and why:**
  - code comments, and docstrings no model reads: nobody types a command from them;
  - the historical records (CHANGELOG entries before 0.13.3, `docs/fusion/*`), which keep what was written then;
  - the subagents' prompts. None tells the user what to type, and the measurement agents' text stays as the
    experiment measured it.
  - the header `## /kg-eval — <date>` that `/kg-eval` writes to its log. The earlier entries share that format,
    and `tests/test_fix_eval_log_and_annotator.py` pins it.
- **The command reference's contents:** GitHub drops `/` and `:` from a heading's anchor, so a
  `/burgess:kg-build` heading lands at `#burgesskg-build`. The links now point there.
- **Rejected alternatives:**
  - (a) *Fix only the README and the command reference:* the session tells the user what to type from the
    command files, the skill and the engine's messages, so the error would come back from there.
  - (b) *Name both forms:* the short one does not run on the field's Claude Code, so a doc that offers it invites
    the error.
  - (c) *Rename every mention, comments and records included:* a comment names a command for a developer, and a
    record keeps its words.
- **Pinned in:** `tests/test_fix_command_names_and_judge_cost.py`. Against 0.13.2, 6 of its 7 tests fail. The
  seventh pins that only the log header keeps the short form.

## Grounders start without the project's instructions and memory (2026-11-12)

- **Decision:** `kg-grounder` and `kg-adversarial-grounder` declare `omitClaudeMd: true`, as the measurement
  agents have since 0.13.2. Claude Code starts them without the user, project and local CLAUDE.md files and
  without its auto-memory index; managed policy files still reach them.
- **What it fixes:** the 0.13.2 entry left the grounders as a separate decision. Found on 2026-11-12 (Windows,
  0.13.3):
  - `/burgess:kg-ground tasas-radar` asked a grounder for a fresh verdict on a grounded edge that the
    2026-11-10 eval had flagged. The session's brief gave the edge's id only. The project has no CLAUDE.md, so
    the grounder's `instructions` attachment held the memory index alone, and its line on that eval read
    "tasas-radar edge flagged as confounded_by by all 3 coders". The verdict agreed with them.
  - The same day, attacking `radar-meta`, the adversarial grounder justified writing `confounded_by` with that
    note.
  - On 2026-11-08 a grounder opened the user's memory note on grounder rules by itself and applied a cue no
    contract had (the entry on connectives, 2026-11-08).
- **Why it takes nothing a verdict needs:** the rules the user settled live in the grounder's contract:
  `enables` versus `grounds`, the 0.11.0 confound rule, a table row read under its header, and each end being
  what its span names. The command has sent ids, not rules, since 0.8.1. What the memory adds is what earlier
  passes and evals concluded, which a fresh verdict must not lean on.
- **Why not the extractor and the generator:** they write candidates that only a grounder can promote, and a
  project's CLAUDE.md may say how its sources are to be read.
- **What it does not stop:** a grounder with Read could still open a memory note whose path it knew, as one did
  on 2026-11-08. Without the index it is not given the path, and the `/burgess:kg-ground` brief tells
  `kg-grounder` not to read files.
- **Rejected alternatives:**
  - (a) *Tell the grounder to ignore its context:* it cannot unsee it (0.11.9's (b), 0.13.2's (b)).
  - (b) *Ask the session to keep verdicts out of its memory:* the memory belongs to the user's session, and its
    index already holds them.
- **What it leaves on record:** the re-judged edge's verdict (`rejected`, `wrong-relation`, with a
  `confounded_by` lead) stands on its own reasoning, which follows the 0.11.0 rule. It does not confirm the
  coders independently.
- **Pinned in:** `tests/test_fix_grounders_without_memory.py`. Against 0.13.3, 2 of its 3 tests fail. The third
  pins the premise that the contract carries the settled rules.

## The attack brief names the weapons the adversarial contract names (2026-11-12)

- **Decision:** `/burgess:kg-ground`'s brief asks the adversarial grounder for counter-edges typed by the weapon
  their span states: `attacked_by`, `confounded_by` or `collapses_into`, as its contract defines them. The
  command's account of the attack stage, its report line, the agent's description and opening, ARCHITECTURE.md
  and the skill say the same.
- **What it fixes:** the brief said "Write attacked_by counter-edges (relation: attacked_by)", while the contract
  (its step 2b) lets the pack vocabulary name the weapon. On 2026-11-12 the grounder attacked `radar-meta` on 0.13.3
  and again on 0.13.4.
  - Both times it wrote a `confounded_by` counter-edge: Meta grading its own system, then RADAR's low and medium
    complexity making the compared populations unlike.
  - It explained the departure each time, and both edges were grounded.
  - That morning an `attacked_by` edge stating such a bias had been rejected as `wrong-relation`, and its lead
    re-wrote it as `confounded_by`.
- **Why the contract wins:** a grounder judges a counter-edge by the relation its span states, and rejects it as
  `wrong-relation` otherwise. The user's 0.11.0 rule files any bias of a figure under `confounded_by`. A brief that
  asks for `attacked_by` alone invites counter-edges the next pass rejects, or a departure every report must
  explain.
- **What does not change:** a hub's attack mark is the `counter-edge (adversarial pass, hub <id>)` opening of the
  notes, read whatever the relation (`groundplan.attacked_hub`). A grounded counter-edge of any weapon keeps its
  hub attacked.
- **Pinned in:** `tests/test_fix_attack_brief_weapons.py`. Against 0.13.4, 2 of its 6 tests fail. The other 4 pin
  what already held: the contract's weapons, the pack's declarations, and the mark for each weapon.
- **Finished in 0.13.6 (2026-11-12):** the first attack on 0.13.5 followed the new brief. It wrote one
  `confounded_by` counter-edge on `radar-meta` and had no departure to explain.
  - A sweep after it found six places 0.13.5 had missed, all describing counter-edges as `attacked_by` alone:
    the command's invariants, the contract's item 3, the skill's `contract.md` and `tools.md` references,
    `/burgess:kg-query`'s "enumerate adversarial edges", and a comment in `projector.py`. They now name the three
    weapons or say "counter-edge".
  - Some of them also read as if the counter-edge itself were stamped `failed`, against the contract's item 4.
    The references and item 3 now put `failed` only on a claim a counter-edge genuinely refutes.
  - The same test file pins the rest of the text: it has 9 tests, and against 0.13.5 the 3 new ones fail.

## A section an extraction wrote no edge from is recorded, so later builds skip it (2026-11-12)

- **Decision:** a new tool, `kg_record_edgeless_section(source_file, section, note)`.
  - **Who calls it.** The extractor, when it finishes a `/burgess:kg-build` section without writing an edge from
    it, whether it wrote nodes or nothing at all. Its note says in a sentence why.
  - **What the engine does.** It refuses a section that a span-present edge already quotes. Otherwise it appends
    one fsync'd JSON line, `{file, section, title, text_sha256, vocabulary_sha256, at, note}`, to
    `<project>/.kg-edgeless-sections.jsonl` (`canon.EDGELESS_SECTIONS`) under the writer lease.
  - **What the plan does.** `kg_build_plan` reads the ledger fail-open (`buildplan.edgeless_records`). It marks
    an uncovered section `edgeless` while a record matches three things: its file, the digest of its normalized
    text, and the digest of the pack's node and edge type names.
  - **The counts.** `sections_uncovered` and `waves` count only the sections to extract, and `sections_edgeless`
    the others.
- **Bug it fixes:** every build extracted again the sections that hold nothing (field report on 0.13.6).
  - **The first build.** The build that made the field canon, on 2026-11-07, extracted all 84 sections of eight
    documents, and 19 of its extractors wrote no edge. They were the six «Fuentes» lists, a vocabulary, a
    checklist and eleven others. Six of the extractors sent a `kg_write` with no node and no edge, two sent none,
    and eleven wrote nodes alone (the vocabulary wrote ten).
  - **Coverage is the build's only memory,** and a section with no edge never gets covered. So on 2026-11-12 a
    plain build planned 18 of those sections again, three waves of extractors to read the same text. The 19th
    had gained an edge since.
  - **Only the session's memory note stopped it.** The session asked the user, who chose to launch none. A
    session without that note would have launched all 18.
- **Why a ledger beside the canon:** as with the attack ledger (0.10.0), the record says what the engine did, not
  what the source says.
  - A marker node or edge would enter the graph as a claim about the source.
  - A mark in the source document would edit the user's text.
- **Why the extractor records it:** the extractor knows whether it found nothing, or had its edges rejected.
  Only the first deserves a record. That is 0.10.0's reason for rejecting its alternative (b). The engine's check
  catches the one mistake it can see: a section already covered.
- **Why two digests:** a record has to stop applying when what the extraction read changes.
  - **The text.** A new paragraph can state a relation. The digest is taken over the normalized text that
    coverage reads, so a section that only moved to another number keeps its record.
  - **The pack's types.** A type added later can make a relation in the section writable. Until 0.8.0 added
    `enables`, a span saying what makes something possible had no relation to go under. Only the type names
    count, in any order, so a change to the glossary or to the divergence settings brings no section back.
- **Rejected alternatives:**
  - (a) *Infer it from `kg_section` calls:* a section that was served but is still uncovered may be one whose
    extractor failed, stopped, or had every edge rejected. Recording it would hide a section that holds edges.
  - (b) *Have the orchestrator record it from the extractor's report:* the orchestrator would read the reason out
    of a report, as 0.10.0 found for attacks. It would also be the orchestrator's first write tool.
  - (c) *A skip list the user keeps:* the user would have to name the sections and keep the list in step with the
    source. And it is not what happened: the extraction ran and found nothing.
  - (d) *A flag to extract the recorded sections again:* nothing in the field asks for it. Deleting the ledger
    does it, and a changed text or pack does it by itself.
- **Accepted trade-offs:**
  - The record depends on the extractor calling the tool. A section whose extractor skips it is offered again,
    as in 0.13.6, and re-launched at most once in a run.
  - A record vouches for nothing. Another extraction might find an edge the recorded one missed. The first of the
    three field builds of 2026-11-07 had `kg_write` accept edges from at least eight of these sections, two
    «Fuentes» lists among them. That canon was emptied before the second build, and no grounder judged those
    edges.
    Neither a new extractor contract nor a new model ends a record. Deleting the ledger does.
  - The ledger is per machine, like the attack ledger: a clone without it extracts those sections once more.
  - Sections extracted before 0.14.0 have no record. On the field canon, the first plain build after the update
    extracts the 18 sections once more, and each extractor records its own.
  - The headless backend (`kg_engine.backend`) extracts every section on every run. It neither reads nor writes
    the ledger.
- **Pinned in:** `tests/test_fix_edgeless_sections.py` (29 tests). Against 0.13.6 the file cannot be imported:
  the tool, the ledger and the digests are all new.
  - **Checked end to end:** one headless `/burgess:kg-build`, in auto mode with Claude Code 2.1.316, on a
    scratch document of three sections: an argued paragraph, a glossary and a list of sources. The argued
    section's extractor wrote one `enables` edge. The other two wrote nothing and recorded their sections. The
    next plan had nothing left to extract. No permission was denied and no shell command ran.

## A record of an edgeless section needs a read, and a judged relation leaves its section to record (2026-11-13)

- **Decision:** two rules around `kg_record_edgeless_section`, one in the engine and one in the extractor's
  contract.
  - **A record needs a read.** The engine keeps in memory the digest of every section text that `kg_section`
    served since it started (`KGEngine._sections_read`), leads reads aside. `kg_record_edgeless_section` refuses
    a section whose current text is not among them, with "no read stands behind the record". The digest it
    stores is the one that read saw.
  - **A judged relation is nothing new.** The extractor records a section when every edge it wrote came back
    QUARANTINED as `collapses-into-known-failure` or `collapses-into-known-verdict`, and names the edge in the
    note. It neither retries that edge nor renames an end to get past the check.
  - **The orchestrator never records.** `/burgess:kg-build` says that only the extractor that read a section
    records it, and that the orchestrator never calls the tool or offers to.
- **Bugs it fixes** (field report on 0.14.0, its first plain build, 2026-11-13):
  - **An offer to record unread sections.**
    - The plan listed 18 sections, last read on 2026-11-07, a day before 0.8.0 added `enables`.
    - The orchestrator loaded the tool through ToolSearch and offered the user to record all 18 itself. The
      user did not choose it.
    - Each record would have paired the section's text with a pack it was never read under. That is the case
      the vocabulary digest exists to rule out.
    - When the 18 were read, four of them gave an edge, one of them an `enables` edge.
  - **A section offered forever.**
    - Del LLM §3 restates `mecanismo defends_against deficit-del-modelo`. That edge was rejected on 2026-11-09,
      as vague, from §2's span.
    - The quarantine left §3 uncovered, and 0.14.0's "not after rejections" left it unrecorded.
    - The orchestrator's report said that every plan would list it again.
- **Why the engine checks for a read:** text alone did not hold.
  - 0.14.0's contract already gave the record to the extractor, and the build command does not declare the
    tool. The orchestrator found it and offered it anyway.
  - MCP tells the engine nothing about who calls, so a read is the one fact the engine can tie a record to. The
    check is cheap and rule-bound.
  - **Keyed by the text's digest,** so a record attests the text that was read. A source edited between the
    read and the record waits for a new read.
  - **Leads reads do not count.** A leads read writes a rejected claim's leads, and the contract already keeps
    leads mode from recording.
  - **In memory,** like the write cache. After a restart, a record waits for the extractor to read its section
    again.
- **Why the extractor records a judged relation's section:**
  - A quarantine against a judged edge is final (`retryable: false`). The edge is already in the canon, with
    its verdict and its own span, so a new read can only propose it again.
  - Unlike a rejection, nothing the extractor can fix makes the edge writable.
  - The note names the edge, so the record hides nothing.
- **Rejected alternatives:**
  - (a) *Text only:* 0.14.0's text already implied the rule and did not stop the offer.
  - (b) *Tell the orchestrator from an extractor by the caller:* MCP gives the server no caller identity, and
    the subagents share their session's server.
  - (c) *Persist the reads:* a read from another session or another day would then vouch for a record that no
    read in this run stands behind.
  - (d) *Count the judged edge as coverage of the section:* coverage is the spans that quote a section. A
    quarantined edge quotes nothing, and the judged edge's span lies in another section.
  - (e) *Have `kg_write` record the section when it quarantines a judged edge:* the write does not know the
    section, and the extractor may still have other relations to write from it. The decision stays the
    extractor's, as 0.14.0 put it.
  - 0.14.0's alternative (a), inferring a record from reads, stays rejected. A read is now necessary for a
    record, not sufficient.
- **Accepted trade-offs:**
  - The check cannot tell the orchestrator from an extractor. An orchestrator that called `kg_section` first
    would pass. The command forbids recording, and such a call would at least be a read of the text.
  - An engine restart between an extractor's read and its record costs one more read.
  - A section recorded for a judged relation stays out of the plan if that edge's verdict later changes. Nothing
    is lost, because the edge keeps its own span, and a re-judgment works on the edge, not on the section.
- **Pinned in:** `tests/test_fix_edgeless_record_rules.py` (14 tests). Against 0.14.0, 10 of them fail. The 4
  that pass pin what 0.14.0 already did: a reader's record, the order of the errors, and the record after either
  quarantine.
  - **Checked end to end:** one headless `/burgess:kg-build`, in auto mode with Claude Code 2.1.316, on a
    scratch project that reproduced the field case.
    - The project had three sections: a premise, a glossary restating it, and a list of sources. Its canon held
      the premise's edge as rejected.
    - The glossary's extractor wrote the judged edge again, which was quarantined as
      `collapses-into-known-failure`. It then recorded its section, naming the edge.
    - The sources' extractor recorded its section.
    - The orchestrator never called the record tool, and the next plan had nothing left to extract.
    - No permission was denied and no shell command ran.

## The extractor starts without the project's instructions and memory (2026-11-13)

- **Decision:** `kg-extractor` declares `omitClaudeMd: true`.
  - Claude Code starts it without the user, project and local CLAUDE.md files, and without the auto-memory index.
  - Its contract says that its facts come from the section and from `kg_write`'s answers. It sends a relation
    even when it believes the canon holds it.
- **Bug it fixes** (field report on 0.14.1, 2026-11-13):
  - The plan held one section, Del LLM §3, whose one relation the canon holds as rejected. The session's memory
    index said so, in a line written after the previous build.
  - The extractor read the section, then, "by my notes", sent no `kg_write` and recorded the section. Its note
    could not name the edge, because no quarantine had returned its id.
  - The note was right. A wrong or stale one would have kept a writable relation out of the graph for good.
- **Why the extractor now, when 0.13.4 left it out:** 0.13.4 kept the extractor and the generator on the
  project's instructions, because they write candidates and the grounders filter them.
  - 0.14.0 broke that premise for the extractor. An extraction that writes nothing is recorded, and the plan
    stops offering the section.
  - An omission is therefore final in a way a bad candidate is not, and no grounder ever sees it.
- **Why not the generator:** it writes into the hypothesized lane, and every hypothesis goes through grounding.
  Nothing it writes ends a section's extraction.
- **Rejected alternatives:**
  - (a) *Text only.* 0.10.0's contract already said not to take a rule from a note. The field extractor took a
    fact, not a rule, and the index came with its launch, unasked.
  - (b) *Have the engine refuse a record that no `kg_write` from the same read preceded.* Most edgeless sections
    (bibliographies, glossaries) rightly send no write, so the engine cannot tell a skip from a section with
    nothing in it.
  - (c) *Keep the memory and have the orchestrator write notes that say nothing about sections.* The notes are
    the field session's own, written by a model, and Burgess cannot police them.
- **Accepted trade-offs:**
  - Extraction guidance in a project's CLAUDE.md no longer reaches the extractor. Nothing in Burgess relies on
    it: extraction follows the pack and the contract.
  - Managed policy files still reach the extractor, as they reach the grounders.
  - A note can still be opened with `Read`, though the extractor no longer receives the index that points to
    it.
- **Pinned in:** `tests/test_fix_extractor_without_memory.py` (5 tests). Against 0.14.1, 3 of them fail. The 2
  that pass pin the generator's boundary and the premise that the build's brief carries what an extraction
  needs.
  - **Checked end to end:** one headless `/burgess:kg-build`, in auto mode with Claude Code 2.1.316, on 0.14.1's
    field case, with a note planted in the project's memory telling an extractor to skip the write.
    - The main session's transcript carried the memory index with the note. Neither extractor's did.
    - The glossary's extractor sent the judged edge, got the quarantine back, and recorded its section with
      the edge's id.

## The lease is reclaimed only from a stale record, never from a read that found nothing (2026-11-13)

- **Decision:** `LeaseLock.acquire()` decides with the record it read.
  - Staleness is judged on that record (`_rec_stale(rec)`), never on a re-read through `is_stale()`.
  - After a lost create race, a read that finds no record is retried, not reclaimed.
  - A lock file that holds no record (empty or not JSON) is respected while it is younger than
    `LOCK_UNPARSEABLE_GRACE` (5 s), as an unreadable ticket already was (`_ticket_orphaned`). An older one is a
    crash leftover and is reclaimed.
- **Bugs it fixes** (found through the flaky wave test, 2026-11-13):
  - **Two writers inside the lease.**
    - O_EXCL creates the lock file empty, and the record lands a moment later.
    - A contender that lost the create race read the empty file as "no record" and went to `_reclaim_stale`.
      There the moved-aside file still read as nothing, so the contender dropped it and created its own lock,
      and both writers held the lease.
    - Measured on 30 waves of 10 writers: 47 overlaps, up to 5 writers inside at once.
  - **A lease left behind for a TTL.** This is the flaky test.
    - `is_stale()` re-read the lock. When the holder had just released, that read found nothing and called it
      stale.
    - The reclaim then moved aside the next holder's fresh lock and found it live. If that holder finished in
      the meantime, its release found no lock of its own, and the restore put back a record whose writer was
      gone.
    - A foreign holder cannot be pid-probed, so every waiter sat out the lease's 120 s TTL. That is the two
      minutes the failing CI legs ran long.
    - With both windows widened, every wave stalled for one TTL. After the fix none did.
- **What the July FIFO decision took for granted:** that entry left "acquire()'s O_EXCL/reclaim CAS" as the
  sole serializer, and that stays true. But the CAS was only as sound as the reads that sent a lock to
  reclaim, and two of them said nothing about staleness. The FIFO queue made the wave fast enough that both
  windows mattered less often, and it never could have closed them.
- **Why not more:**
  - (a) *Raise the test's budget past the TTL.* The wave would pass by waiting the leaked lease out, and the
    overlaps would stay. July's entry already records this wrong first diagnosis for this same test.
  - (b) *OS file locks (`flock`, `LockFileEx`).* They would end staleness altogether. But they are a port of
    the lease, they don't hold across hosts on network filesystems, and the CAS design is sound once it only
    acts on stale records.
  - (c) *An atomic create, through a hard link from a temporary file.* It would remove the empty window, but
    not the re-read, and it needs a fallback where hard links are missing. Respecting a young unparseable file
    covers both create paths with no new filesystem call.
- **Accepted trade-offs:**
  - A crash between O_EXCL and the record write now costs 5 s instead of nothing.
  - The reclaim of a genuinely stale record keeps its move-aside-and-check shape, so a stale lock with two
    reclaimers can still race as before. It needs a holder already past its TTL or dead.
  - In the wave, a contender that lost the create race now waits one poll, about 10 ms at the queue's front,
    instead of reclaiming.
- **Pinned in:** `tests/test_fix_lease_handoff.py` (6 tests). Against 0.14.2, 5 of them fail. The one that
  passes pins the reclaim of an old unparseable file, which 0.14.2 already did.
  - The wave test now waits 30 s past the writers' budget, and on a stuck writer it prints the lock record, the
    tickets and where each writer waits.

## A span-backed edge is re-examinable only when its own file changes (2026-11-13)

- **Decision:** the R3-mirror re-examinable advisory treats a negative verdict on an edge that quotes a span
  from a configured source file (`Projector._span_file`) by that file alone.
  - Such an edge is flagged only when its own file's text changed, with the new reason
    `span-file-changed-since-judged` (`REEX_SPAN_FILE`).
  - Nodes, span-less edges and spans attributed to no configured file keep the source-set rule:
    `source-set-changed-since-judged`, through the term-overlap filter.
  - On every re-filter, a stored source-set flag on a span-backed edge is dropped.
  - `PROJECTION_RULES` "4" makes the first read after the upgrade rebuild the index, which runs that re-filter.
- **Bug it fixes** (field report on 0.14.3, 2026-11-13):
  - The user added «Síntesis - Fábricas de software.md», a 12 KB synthesis of the corpus's own topic, and the
    projection flagged all 62 negative verdicts.
  - All 62 were span-backed edges from the eight unchanged documents (46 span-present, 16 inferred, every one
    with a span and a source file). No Síntesis write collided with any of them.
  - The term-overlap filter fires on a single shared word, which made it noise on a topical addition.
  - Stage 0c then asks the orchestrator to reconsider each flagged item, and a flag lasts while its item stays
    negative.
- **Why the item's own file:**
  - A span-backed verdict judges what that span states in its file. A new or edited file elsewhere cannot change
    that.
  - A new file that restates a rejected relation is caught on the extraction side. Writing the same edge id is
    quarantined `collapses-into-known-failure`, and since 0.14.1 the extractor records its section and names
    the edge.
  - Span-less items (divergence pins, the advisory's motivating case) have no file to tie them to, so they keep
    the source-set rule.
- **Rejected alternatives:**
  - (a) *A stronger overlap threshold* (several shared terms, or both endpoint labels). It would still be a guess
    about relevance, and it would keep flagging span-backed verdicts for files that cannot bear on them.
  - (b) *Per-section change detection.* It needs a per-section baseline in the meta and a span-to-section lookup
    on every projection. The file-level rule fixes the field case, and the finer one can come if file edits
    prove noisy.
  - (c) *Clearing the flags by deleting the derived layer.* That is a workaround for one machine, and the next
    topical addition would raise them again.
- **Accepted trade-offs:**
  - **An edit to a document flags each of its negative edges.** The file still holds every span, so the term
    filter cannot narrow the set. This is deliberate: the context a verdict read may have changed.
  - **Flags are still sticky.** A flag lasts until its item leaves `{failed, rejected}`. A re-confirmed rejection
    keeps its time (0.10.2), so nothing records the re-look. It now arises only for edits to the item's own
    file.
  - **Stage 0c is still done by the orchestrator, which reads the project's notes,** not by a grounder without
    memory (0.13.4).
- **Pinned in:** `tests/test_fix_reexaminable_own_file.py` (7 tests). Against 0.14.3 all 7 fail.
  - **Checked on field data:** a scratch copy of the Windows project held its canon, its nine sources and the
    derived index 0.14.3 built (rules "3", 62 flags). The 0.14.4 engine's first read through `kg_context`
    rebuilt the index (rules "4"). It left 0 flags and 0 stale verdicts, with the falsification memory still
    at 62.

## A claim about a concept is not that concept, and a lead's new end is never its other end (2026-11-13)

- **Decision:** the extractor's contract and `/burgess:kg-build --leads`'s brief say three things.
  - A node whose label states something about a thing is a claim, and the thing is another node. A claim's id
    is reused only when the edge's end is that whole statement.
  - In leads mode, a new end (`head_known` or `tail_known` false) is never the lead's other end, and never a
    claim about the end.
  - In leads mode, a `self-loop` rejection is not dropped. The extractor declares the lead's own id for the new
    end and re-sends.
- **Bug it fixes** (field report on 0.14.4, 2026-11-13):
  - The lead `producto-hecho-al-100-por-agentes attacked_by agentes-multiplican-errores` named a new head. The
    grounder had rejected the generic `agente` as `wrong-node`.
  - 0.9.0's rule for a new end is to look in `known_nodes` for the same concept under another id. The extractor
    took the claim node `producto-100-por-agentes-deficiente` («El producto hecho al 100 % por agentes suele ser
    deficiente») for the product. Its edge turned the claim's own reason into an attack on it, and the next pass
    rejected it as `wrong-relation`.
  - That pass left a lead whose head is the same new product and whose tail is that claim. The same
    substitution there makes a self-loop, which `kg_write` rejects in every lane. The contract said to drop a
    self-loop, so the lead would have stayed pending for good.
- **Why the contract and not the engine:**
  - The engine already refuses the one outcome nobody can judge: a self-loop is REJECTED in every lane, and
    that stays.
  - Reusing a known id for a lead's new end is the extractor's call by design. `known_nodes` only decides what
    the extractor is shown. A grounder names an end by slug and may not know the id the canon holds for the same
    concept, so a mapping is often right.
- **Rejected alternatives:**
  - (a) *Have `kg_write` take a lead's ids verbatim and refuse any other.* It would duplicate a node whenever
    the grounder's slug differs from the canon's id for the same concept, the case the lookup exists for.
  - (b) *Have `kg_write` refuse a lead edge that puts a `claim` node on a new end.* A claim node is the right end
    when the lead's new end is itself a statement the canon already holds under another id. The engine cannot
    tell the two apart, and a type check would miss a node of another type that states something about the end.
  - (c) *Have the grounder name the canon's id for every end.* It names a new end because it judged that no node
    in the canon is it. That judgment is the signal the extractor now honors.
  - (d) *A leads-only rejection reason with its own hint, such as `lead-self-loop`.* The contract now gives the
    recovery for `self-loop` in leads mode, and a new reason would add engine surface for one text rule.
- **Accepted trade-offs:**
  - The rule is text, so a model can still break it. A substitution that makes no self-loop lands `unverified`,
    and grounding rejects it as `wrong-node` or `wrong-relation`, as it did here, at the cost of one cycle.
  - Whether a node is a claim about the end is judged on its label and body, and a terse label can hide it. The
    declared `node_type` helps but does not settle it.
- **Pinned in:** `tests/test_fix_claim_is_not_its_subject.py` (6 tests). Against 0.14.4, the 4 text tests fail.
  The 2 that pass pin the engine premise: the self-loop leaves the lead pending, and the lead's own id takes it.
  - **Checked end to end:** one headless `/burgess:kg-build --leads`, in auto mode with Claude Code 2.1.316, on
    a scratch copy of the Síntesis with the field's §8 state written fresh and two leads pending.
    - The sonnet extractor declared `producto-hecho-al-100-por-agentes` as a new `primitive`, because "the known
      node of that name is the claim, not the product itself", and wrote both leads: 3 ACCEPTED.
    - The next plan had no leads left, and no permission was denied.

## A rendered view stays current (2026-11-13)

- **Decision:** the engine re-renders each human-facing view, `graph.html` and `GRAPH_REPORT.md`, that exists and
  is older than the projection's `graph.json`. It does so on every read that projects the canon
  (`_ensure_projected` → `_refresh_views` → `export.refresh_views`).
  - A read never creates a view: `/burgess:kg-view` does, once, and a view the user deleted stays deleted.
  - A degraded projection (failed or contended) re-renders none, so a view is never rendered from an empty or
    stale derived layer.
  - A render that fails is logged, the old view stays, and the read is served.
  - `kg_export` renders the views it was asked for once: its own projection skips the refresh (`views=False`).
  - `/burgess:kg-build --leads` now ends with `kg_context`, as a build's step 2 and `/burgess:kg-ground`'s Stage 3
    already did. Every build and grounding pass therefore ends with a read that projects.
- **Request it answers** (field project on 0.14.5, 2026-11-13):
  - After a grounding pass, the user asked whether `/burgess:kg-view` had to be run again after every change to
    see it in the view. It did.
  - The `graph.html` the user had open was rendered on 2026-11-10, and 48 canon notes had changed since.
  - The user asked for the view to regenerate on its own.
- **Why the read path, and why `graph.json`'s file time:**
  - A view is a render of the derived layer. Only a projection changes that layer, and projections run on reads:
    a write never projects (defense #6). So a read that projects is the first moment a view can show a change.
  - Only a projection writes `graph.json`, and it skips the write when nothing changed (the up-to-date check
    returns first). Two fallbacks create an empty `graph.json` when it is missing, and both are degraded reads,
    which re-render nothing. So a view older than `graph.json` was rendered from a projection that has since been
    replaced.
  - The same test covers projections made elsewhere. The PreToolUse hook projects through its own read-only
    projector and renders nothing, and the server's next read finds the view older and catches it up.
  - The check is three file-time reads on each projecting read. The render costs about 20 ms for both views on
    the field canon of 463 notes, against about 86 ms for the incremental projection before it (Linux, scratch
    copy).
- **Rejected alternatives:**
  - (a) *A final `kg_export` step in each command that changes the graph.* It depends on the model following
    the step and costs a tool call per run. It also misses changes made outside those commands, such as a merge
    asked for in conversation or `/burgess:kg-diverge`'s materialization.
  - (b) *Render on the write path.* A write never projects (defense #6). Projecting on each write is the per-call
    cost review-M3 removed from the grounding drain.
  - (c) *A background thread that renders once writes go quiet.* It would project inside the same process as
    the session's own calls, under a single-writer lease whose handoff 0.14.3 had to fix.
  - (d) *A content stamp in each view, such as a hash of `graph.json`.* It needs its own storage, and a read of
    it on every read. The file time needs neither, and `graph.json` is already written exactly when the derived
    layer changes.
  - (e) *Have the plan tools project.* `kg_build_plan` and `kg_ground_plan` read the canon on purpose. Making
    them project would put a projection on every progress probe, for the view's sake. The commands' existing
    projecting reads, plus one `kg_context` in leads mode, reach the same end.
  - (f) *Create the views on any read.* A project that never asked for a view would get files in the shared data
    dir, and a deleted view would come back.
- **Accepted trade-offs:**
  - The views live in the plugin's data dir, which every project shares (`KG_DATA=${CLAUDE_PLUGIN_DATA}`). Like
    `graph.json` and the index, they now follow whichever project last projected. That was already true of the
    derived layer; through 0.14.5 the views stayed behind instead.
  - A change made outside a command reaches the views at the next read that projects, not at once.
    `/burgess:kg-view` still renders on demand.
  - A browser does not reload a local file by itself, so the user reloads the page.
  - File times decide staleness. A system clock stepped back could hold a re-render until the next projection.
- **Pinned in:** `tests/test_fix_views_stay_current.py` (15 tests). Against 0.14.5, 12 fail. The 3 that pass
  pin what 0.14.5 already did: a read creates no view, a current view is left alone, and `kg_export` renders
  once.

## An edge's provenance is its line's opacity, and an older engine's view is stale (2026-11-13)

- **Decision:**
  - `graph.html` draws an `inferred` edge lighter (`PALETTE.edgeAlpha.inferred`, 0.4), in every state. The
    state keeps colour, width and dash.
  - Each view records the engine version that rendered it. `export.stale_views` treats a view that an older
    engine rendered, or one with no mark, as stale, like one older than `graph.json`. A view that a newer engine
    rendered is left alone.
- **Request it answers** (field project on 0.15.0, 2026-11-13):
  - The user asked why the view showed no hypothesized or inferred nodes and no hypothesized lines.
  - The canon has none of those, but 35 of its 261 edges are `inferred` (19 grounded, 16 rejected). The view drew
    them exactly like span-present ones, and the user asked for them to be told apart.
- **Why opacity:**
  - The state already holds colour (green, red, grey, blue), width (failed thicker) and dash (unverified dashed,
    unverified hypothesized dotted). Any of those would mix the two axes: a dash for `inferred` cannot coexist
    with the dash of `unverified`.
  - Opacity was free on edges, and it is what a node's provenance already uses. So provenance reads the same way
    on both.
- **Why the version mark:**
  - 0.15.0 re-rendered a view only when the projection moved past it.
  - The field views were rendered by 0.14.5 after the day's last projection, so a new template would have reached
    them only with the next build or grounding pass.
  - A view's look is part of what "current" means, so an update re-renders it once, on the first read that
    projects.
  - A newer engine's view is left alone. Otherwise two sessions on different versions would each re-render it on
    every read, undoing the other.
- **Rejected alternatives:**
  - (a) *A thinner line for `inferred`.* Width already separates failed from grounded from unverified. A thin
    failed edge would read as a grounded one.
  - (b) *Opacity for every edge provenance, hypothesized faint as on nodes.* An unverified proposal's dotted blue
    line is how a `/burgess:kg-generate` user finds the proposals, and a faint dotted line nearly vanishes.
  - (c) *Compare the view's time with the template file's.* Whether an update rewrites a file's time is the
    installer's business, not the engine's. The mark says which version rendered the view, whatever the times.
  - (d) *Re-render whenever the mark differs.* Two open sessions on different versions would undo each other on
    every read.
- **Accepted trade-offs:**
  - A judged hypothesized edge is still drawn like a span-present one (green or red, full opacity). No field
    canon has one yet. Giving it a look of its own is a separate decision about how proposals should read once
    judged.
  - A view rendered by an older engine while a newer session is open keeps the older look until the newer
    engine's next projecting read.
  - Each projecting read now reads the first 512 bytes of each view, besides three file times.
- **Pinned in:** `tests/test_fix_inferred_edges_distinct.py` (11 tests). Against 0.15.0, 10 fail. The one that
  passes pins the premise: the view's data already carried each edge's provenance.
  - **Checked visually:** a scratch graph with both provenances in each state, screenshotted with headless
    Chromium.

## One node cannot take a generation's slate, and a compression is written as its star (2026-11-14)

- **Decision:**
  - With the gate off, a node's bridging strength is `(structural_bridge + 1e-6·degree) × specificity`. With the
    gate on it stays `spec_betweenness`.
  - No endpoint takes more than `generate.ENDPOINT_CAP` (2) slots of a `bridge` or `regroup` slate. The selection
    walks the ranked list in order, so the first k it keeps are the same whatever the run's k.
  - A bridge's rationale names what its strength came from.
  - `kg_generate` returns `unjudged_hypotheses`, the hypothesized edges still `unverified`. When it is above 0,
    `note` says the slate was ranked partly on earlier proposals and to run `/burgess:kg-ground` first.
  - A compression candidate carries `members` and `id`, the id `kg_operate collapse` writes for the same members.
    The rule moved from `operations` to `model.compression_id`. kg-generator and `/burgess:kg-generate` write the
    node under that id, with one `collapses_into` edge from each member.
- **Field run it answers** (0.15.2, 2026-11-14): the first `/burgess:kg-generate` on the field graph, default set,
  k=10.
  - All 10 bridges hung off radar-meta. No node was a structural bridge, so the gate-off strength was degree alone,
    and a pair's score sums its two ends'. The node with the most links paired with the top node of every other
    community, though its specificity (1.74) was below the graph mean (2.81).
  - After the write, the run's 33 unjudged proposals had turned the gate on and made radar-meta a bridge of 10
    communities. Replayed on a copy, the next run bridged radar-meta to ten more nodes, seeded pairs of a
    compression's members through the unjudged compression node, and proposed compressing each compression again.
  - The compression candidates carried their members only in `rationale`, and no id. The session read the
    engine's source to find the collapse id rule and the star shape.
- **Why weight the fallback by specificity:** §4 says no candidate ranks high merely for being generic. The gate
  decides whether `spec_betweenness` is trusted, and with it off, the fallback had no generality control at all.
  A degree leader is confounded by generality just as a betweenness leader is. With no specificity spread the
  factor is a constant, so the old order stands where specificity says nothing.
- **Why a cap, and why always:**
  - A sum of endpoint strengths lets the strongest node pair with every other strong node before any pair
    without it.
  - That happens with the gate on as well: the replayed second run had the gate on and gave the same node all ten
    bridges again.
  - Two slots let a hub show as a hub and leave the rest of the slate to other pairs.
  - The cap is inside the mechanism, not applied to the surfaced slate. Above 400 nodes a mechanism runs at the
    surfaced k, so capping after the cut would leave a short slate.
- **Why a warning, not a gate:** generation is never gatekept (the inversion, PLAN §1.2). An unjudged proposal is
  live structure by design: the absorption window reads the degree of a new node, and `kg_agenda` flags a
  hypothesized-only neighbourhood. The user decides whether to ground first.
- **Rejected alternatives:**
  - (a) *Only say it in the rationale.* The slate would stay ten spokes of one hub.
  - (b) *Weight the pair score by the pair's specificity (the min of its two ends).* That leaves the gate-on and
    gate-off strengths built differently. A node-level weight mirrors `spec_betweenness`.
  - (c) *Exclude unjudged hypothesized edges from the ranks.* That changes what live topology means for every
    structural surface (degree, communities, agenda, absorption). It is a separate decision.
  - (d) *Have the engine build the star payload itself.* The language layer would still have to add the label,
    body and notes. With `members` and `id` it builds the star verbatim, as it uses an edge's endpoints verbatim.
- **Accepted trade-offs:**
  - A pair that a mechanism capped out does not count toward `convergence` as proposed by it.
  - Transplant still takes its one hub, by design, and picks it by degree.
  - A compression is proposed again over its own star once the star is live. Replayed with the four stars grounded,
    the next compression run proposed compressing each community again, with the compression node among the
    members. Not addressed here.
- **Pinned in:** `tests/test_fix_generate_diversity.py` (16 tests). Against 0.15.2, with the old id rule inlined,
  12 fail. The 4 that pass pin what must not change: the order with no specificity spread, a shorter run keeping
  what a longer one keeps first, an edge candidate's dict, and the field canon's compression ids.

## A verdict keeps its reason and its file, and absorption scores only what was grounded (2026-11-14)

- **Decision:**
  - `harness.absorption_window` scores a tracked node only when the derived graph holds it as `grounded`, with
    degrees over live edges (`model.NON_LIVE_STATE_VALUES` left out). Every other tracked node goes to
    `not_scored` with its state, or `absent` when the graph no longer holds it. `harness.absorption` is the scored
    half. `kg_absorption` returns both, its `tracked` counts both, and its note says how many were not scored.
  - `kg_ground` keeps a node verdict's `note` in the node's body, as the paragraph `verdict (<state>): <note>`.
  - A support span records its file. `SourceSet.files_containing` gives the files that hold the span, in source
    order. An edge that names no declared source takes the first one as its `source_file`, and a promoted node's
    body gets a `grounding source: <file>` paragraph.
- **Field run it answers** (0.15.2, 2026-11-14): the `/burgess:kg-ground` that judged the first field
  generation's 37 items. It grounded 2 of the 33 edges and 2 of the 4 compression nodes, and rejected the rest
  for no support.
  - `kg_absorption`, called by the session for its report, scored all four compressions `fertile` at the degree
    each was born with. Two had been rejected, and so had 19 of their 21 star edges.
  - The grounders rejected two compression nodes with a reason each. The node branch of `kg_ground` ignored
    `note`, so the session wrote the reasons into its report and its memory, the only places they survived.
  - The two grounded star edges had their span and no `source_file`, so they were cited without their document.
- **Why only grounded nodes:** the window is defined over nodes grounded from a hypothesis (§14).
  - A rejected node is negative memory, not a perturbation the graph is absorbing.
  - An unjudged node has not earned a window yet.
  - Scoring both made a rejected compression read as the productive middle.
- **Why live edges:** every other structural signal reads live topology: degree, communities, betweenness and
  the generators' adjacency. A rejected star edge is the graph refusing a member's reduction, not absorbing the
  node.
- **Why a lost edge is no growth, not a rebased baseline:** the ledger records only the degree at introduction,
  not which of those edges were later rejected. A shrunk node reads as no growth, so it stays `fertile` while a
  live edge remains and turns `isolated` with none.
- **Why the body for a node's note:** a Node has no notes field, and the body is already where its support goes.
  Canon keeps a judged node's body when the node is written again, so the reason lasts.
- **Why the first file:** a span is verbatim in every file that holds it. The first in source order is the file
  whose excerpt `kg_ground_item` shows, so a later re-judgment reads the excerpt the record names. An edge that
  names a declared file was verified against that file alone, so it keeps it.
- **Rejected alternatives:**
  - (a) *A `notes` field on Node.* That is a canon schema change, touching the merge driver, the reconciler and the
    projector, to hold one sentence the body already can.
  - (b) *A `support_file` parameter on `kg_ground`.* The grounder would have to name a file that the engine
    already finds.
  - (c) *An absorption status for a rejected or unjudged node.* That folds the epistemic axis into the absorption
    status, and the axes are never collapsed into one.
  - (d) *Backfilling the two field star edges' `source_file`.* No command rewrites a past verdict's fields, and
    both edges verify as before.
- **Accepted trade-offs:**
  - The introduced degree still counts edges that were later rejected, so a node has to regain them before growth
    counts.
  - Edges promoted before 0.16.1 keep an empty `source_file`.
  - A span that several files hold is recorded under the first of them.
  - Two pins in `tests/test_fix_server.py` held the old edge-only note on purpose. They were rewritten to pin the
    new contract, with the same purpose.
  - The canon now holds the name of the file a promotion's span came from. The I5 snapshot fixture had given its
    two arms the same corpus under different file names, so it now names both copies alike, each in its own
    folder. Its assertion is unchanged.
- **Pinned in:** `tests/test_fix_absorption_and_verdict_records.py` (14 tests) and the two rewritten pins. Against
  0.16.0, 11 of the 14 fail, and so do both pins. The 3 that pass pin what must not change: a blank note adds
  nothing, an edge that names a declared file keeps it, and a citation promotion records no file.

## Compression offers nothing an earlier generation proposed, and the absorption ledger is the engine's (2026-11-15)

- **Decision:**
  - `generate._compression_skip` leaves out a community that passed the §7 screens in two cases:
    - a live compression node among its members was already proposed over at least half of the other members,
      each of which has a `collapses_into` edge into it, in any state;
    - its id, a function of its members (`model.compression_id`), is already a node of the graph, in any state.
  - `generate.compression_skips` reports both cases from the same walk. `kg_generate` returns them as
    `compression_skipped` whenever compression runs, and names them in `note`.
  - `kg_record_generation(nodes)` is a new tool, making 34. It advances the generation counter of
    `derived/generations.json` and tracks each node a run's `kg_propose` accepted, at its live degree in the
    canon. It skips, with the reason, an id the canon lacks, one already tracked, a node that is not a
    hypothesized proposal, and an entry with no mechanism. It writes atomically under the writer lease and
    refuses a file it cannot read as a ledger.
  - `/burgess:kg-generate` Step 4 calls the tool. The command holds no Bash and says it needs no shell.
- **Field run it answers** (0.16.1, 2026-11-15): the second field `/burgess:kg-generate`, default set, k=10.
  - Compression offered four candidates. Two came back under the ids of the two compressions rejected the day
    before. The other two each held a compression grounded that day, with 6 of 7 and 5 of 5 of the other
    members already proposed into it.
  - The session dropped the first pair by hand, citing failure memory, and wrote a rule in its memory to do so
    every run. It wrote the second pair: 2 nodes and 14 star edges that re-ask rejected memberships against new
    ids.
  - The ledger step was the run's one Bash call. It writes outside the project, so it waited nine hours for the
    user's approval. The first field run had needed 12 approvals.
- **Why the id rule:** the same id is the same proposal.
  - A rejected one is failure memory. The boundary would quarantine its star edges as known failures, and the
    canon would keep the judged body.
  - A grounded or unjudged one is already proposed.
- **Why "proposed over at least half":**
  - What made the nested compressions redundant is that their stars asked memberships already asked. The old
    node's `collapses_into` edges, in any state, are exactly those questions.
  - At half, a new star would ask as many old questions as new ones.
  - Only a live node counts, because a rejected compression stands for nothing.
- **Why not any compression node in the community:** the first draft did that.
  - The same field graph, with its 24 unjudged proposals live, had two clusters of 21 and 18 members that had
    merged round the old compressions, which had been proposed over a handful of them.
  - The draft left out both. That would stop compression from ever summarising a cluster that grew round an
    earlier one.
- **Why a tool and not a better shell snippet:** the ledger is engine state that the engine reads.
  - A session-written script writes it from outside the engine. It drifts: two runs, two scripts. Writing outside
    the project always asks the user.
  - It follows `kg_record_attack` (0.10.0) and `kg_record_edgeless_section` (0.14.0): a record the language layer
    asks the engine to keep.
- **Rejected alternatives:**
  - (a) *Leave compression nodes out of a community's members and screen the rest.* The rest is the old
    compression's member set, so it would offer the same cluster again under a new id.
  - (b) *Let the language layer drop them, as the field session did.* The engine holds the ids, and a rule kept
    in a session's memory drifts from release to release.
  - (c) *Have `kg_propose` record the generation itself.* The propose lane also serves `/burgess:kg-diverge` pins
    and `kg_operate`, and a generation is one `/burgess:kg-generate` run.
- **Accepted trade-offs:**
  - A candidate over a grown cluster holds the old compression as a member. Its star then asks whether the old
    compression reduces to the new one.
  - A compression proposed over exactly half of the other members still holds the community.
  - The check counts star edges in any state, so a member whose membership was rejected counts as asked.
  - Two pins were rewritten. One held the command's ledger path, which is now the engine's. The other counted 33
    tools.
- **Pinned in:** `tests/test_fix_generation_ledger_and_compression_filter.py` (20 tests) and the two rewritten
  pins.
  - Against 0.16.1, 18 of the 20 fail, and both pins. The grown-cluster test fails there only because
    `compression_skips` is new.
  - The 2 that pass pin what must not change: the fixture's baseline, and a rejected compression node not
    holding its community.

## A proposed node is judged with its star, and a proposal into a node that does not stand is not promoted (2026-11-15)

- **Decision:**
  - `groundplan.node_star_batches` builds the plan's batches.
    - A queued node, the queued edges that touch it, and any queued node those edges reach make one unit, with
      its nodes first.
    - A unit is never split. It starts a new batch when it does not fit, and is a batch of its own when it is
      larger than the batch size.
    - A queue with no node is cut exactly as `batches` cuts it.
  - The promotion gate refuses to ground a `hypothesized` edge whose source or target node is rejected, failed or
    obsolete. The refusal is `hypothesis-into-non-live-node`, naming the node and its state.
  - The grounder's contract says to judge a node before its star.
- **Field run it answers** (0.17.0, 2026-11-15): the `/burgess:kg-ground` of the second field generation.
  - 25 of the 26 items were rejected for no support, all correctly.
  - The plan's batches split one compression's star across all three batches. In the same second, batch 1
    rejected the node and batch 3 grounded `varios-llm-… collapses_into` it, on an outside citation (Knight &
    Leveson 1986, which is in the corpus, and Eckhardt & Lee 1985, which is not).
  - That grounded edge made `varios-llm-…` a hub again, and the adversarial grounder found nothing new.
- **Why batch by node:**
  - A compression is a proposal of a node and its star. The star's edges mean nothing if the node does not stand.
  - Judged in parallel, the node and its edges come apart. Judged by one grounder, the node's verdict reaches its
    edges.
  - Nodes first, because the batch order is the order a grounder works in.
- **Why refuse the promotion, not cascade the node's verdict:**
  - Verdicts are set item by item, through `kg_ground` only. A node's rejection setting its edges' states would
    be a verdict nobody issued.
  - The refusal keeps every verdict explicit. The grounder rejects the edge itself, with a note.
- **Why only proposals:**
  - An edge with a span states its relation in the source. If such an edge points into a rejected node, the
    conflict is the node's verdict to revisit, not the span's.
- **Rejected alternatives:**
  - (a) *Cascade a node's rejection to its incoming proposals.* That is a verdict nobody issued.
  - (b) *Refuse to reject a node that has grounded edges into it.* The node may truly not stand, and the edge may
    be the mistake, as on the field graph.
  - (c) *Run batches holding nodes before the others.* That needs two waves and still splits a star longer than
    a batch.
- **Accepted trade-offs:**
  - A unit larger than the batch size makes one longer batch.
  - An edge grounded into a node that is rejected later, in the same batch, is not caught. The contract's "node
    first" order is what prevents it.
  - The field edge grounded on 2026-11-15 stays grounded until it is re-judged.
- **Pinned in:** `tests/test_fix_node_with_its_star.py` (14 tests).
  - Against 0.17.0, 11 fail.
  - The 3 that pass pin a proposal into a live node, in both states, and a text edge into a rejected node.

## A proposal is judged against the passages where its ends meet (2026-11-15)

- **Decision:**
  - For an edge with no span, `kg_ground_item` returns `shared_context`: the source sections where both of its
    ends are discussed, at most three, nearest pair first, each with excerpts, and the sections where each end
    is discussed, at most twelve each, with totals.
  - An end is discussed where the span of one of its live edges lies. A node promoted on a support span is also
    where that span lies (`groundplan.grounding_spans`).
  - Sections are ranked by the fewest paragraphs between a span of one end and a span of the other
    (`groundplan.nearest_pair`). A section's excerpts fit in 3000 characters together (`groundplan.pair_excerpts`).
  - `kg_ground` refuses a lead on an edge with no span.
  - The grounder's contract says how to judge a proposal against `shared_context`.
- **Field run it answers** (0.17.1, 2026-11-15): the `/burgess:kg-ground` of the fourth field generation.
  - 40 proposals in four batches: 39 rejected for no support, one grounded.
  - Three grounders looked the ends up with `get_node` and `kg_context`. The fourth judged its twelve proposals
    on what `kg_ground_item` gave, the two nodes and no source text.
  - The proposal that grounded was promoted on a span of the one section where both of its ends are discussed.
- **Why the spans of the ends' edges:**
  - A span is verbatim and checked at the boundary, so it says where the source discusses a node. A label is a
    paraphrase, and a search for it finds the word, not the concept.
  - The engine already holds them. Placing an end costs a pass over the canon's edges and the source's sections.
- **Why live edges only:**
  - A rejected edge's claim about the node does not stand, so its span need not be about that node.
- **Why the nearest pair first, and three sections:**
  - A relation between two concepts is stated where both are named, so the closest two mentions are the likeliest
    support.
  - A hub is discussed in nine sections of the field corpus. Three sections of 3000 characters keep a batch of
    twelve proposals within a grounder's reading.
- **Why refuse a lead on an edge with no span:**
  - `/burgess:kg-build --leads` writes a lead from the rejected edge's span. A proposal has none, so its lead went
    to `leads_unlocated`, reported as a span that had left the source.
  - With passages to read, a grounder may find another relation between a proposal's ends. Until such a lead can
    be written, the note is where it goes.
- **Rejected alternatives:**
  - (a) *Let the grounder read or search the source for a proposal.* That brings back the file reads 0.7.0 took
    out, and the judging still depends on how hard a grounder looks.
  - (b) *Search the source for the two nodes' labels.* A label is the extractor's paraphrase, so the search
    misses the concept and finds the word.
  - (c) *Excerpt every section where either end is discussed.* That is too much text for a batch: one hub alone
    is discussed in nine sections.
  - (d) *Record the passage's span on a rejected proposal, so its lead can be written.* That puts a span on a
    `hypothesized` edge through the verdict path. It needs a decision of its own.
- **Accepted trade-offs:**
  - A section that discusses both ends where neither has an edge is not found. The engine knows a concept's place
    only through its spans.
  - An end with no live span edge, as with most compression nodes, is not placed. The grounder falls back to the
    node bodies and `get_node`.
  - A call on a proposal takes about 40 ms more.
  - Another relation found in a proposal's passage is kept only in a note until (d) is decided.
- **Pinned in:** `tests/test_fix_hypothesis_shared_context.py` (17 tests).
  - Against 0.17.1, all 17 fail.

## A contract example never names a pending field claim (2026-11-15)

- **Decision:**
  - The grounder's "No lead" example is a proposal against `examples/source.md`: `generality-confound bridges
    specificity`, whose §1 states `generality-confound attacked_by specificity`.
  - No agent-facing text names the field pair 0.18.0 used.
- **Field run it answers** (0.18.0, 2026-11-15): the one-edge re-judge of
  `andamiaje-rivaliza-con-fine-tuning bridges o1-sin-prompting`.
  - The orchestrator gave the grounder only the id. The contract's example gave it the pair and a reading:
    `§5 states … attacked_by …, not bridges`.
  - The grounder rejected the edge with that lead, and said its note matched the contract's example.
- **Why:** every grounder of a corpus reads the contract. An example drawn from a claim of that corpus that is
  still pending pre-decides it, for the re-judge and for the lead's grounding after it.
- **Where the line is:**
  - A field case already decided, and generalized into a rule, may still illustrate the rule. Examples are the
    relation table's Spanish passages, and the lead `tests-protegidos defends_against manipulacion-de-tests`,
    which is grounded on the field graph.
  - A pending claim may not.
- **Rejected alternatives:**
  - (a) *Re-run the re-judge.* Rejecting `bridges` holds without the example. The lead's own grounding, on a clean
    contract, tests `attacked_by`.
  - (b) *Remove every field-derived example.* The decided ones carry rules the field taught, and none of them
    pre-decides anything pending.
- **Pinned in:** `tests/test_fix_neutral_proposal_example.py` (3 tests). Against 0.18.0, 2 fail.

## A second reading keeps its relation and its passage, and reads with the graph's ids (2026-11-16)

- **Decision:**
  - The ensemble step proposes, for each pair a second construction joins and ours does not, the edge that
    construction wrote: its relation, its direction, and `passage`, the span it was written from
    (`generate._second_reading`, `Candidate.passage`). Each such edge is checked against failure memory on its
    own id. A pair whose second-graph edge records no relation is still a plain `bridges`, as before.
  - `kg_generate` marks each passage `in_source`: whether it verifies against the configured sources. It counts
    them in `passages`, and `note` says when some lie outside the sources. The span leaves through the session
    scrub.
  - `kg_propose` takes an edge's `passage` and checks it against the configured sources, as a span is checked.
    When it holds, the proposal's notes open with `passage: {"span", "source_file"}` (`groundplan.with_passage`).
    Otherwise nothing is kept. Only the engine writes that segment: one an item's own notes open with is
    dropped. `passages` reports what was recorded.
  - `kg_ground_item` shows a proposal's passage, `in_source` and the excerpt around it (`passage`). The grounder
    judges it as it judges an extractor's span, and may copy it as `support_span`.
  - `kg_section(..., construction=, source=)` serves a section of the second construction's source. The
    construction cuts and scrubs it, and the section comes with the graph's own known nodes. The second
    reading's extractor writes a concept under the graph's id, and declares it in the construction's canon.
  - `/burgess:kg-perturb`, the extractor, generator and grounder contracts, the batch prompt, the tool
    reference, the README and the tutorial say what a second reading can and cannot ground.
- **Field run it answers** (0.18.1, 2026-11-16): the first `/burgess:kg-perturb`. It re-read
  `fronteras-de-centralizacion.md`, one of the nine sources the graph was built from.
  - The second construction had 39 nodes and 22 edges. 13 of its node ids were the graph's, so 4 of its edges
    could be compared, and 3 of those the graph already held grounded.
  - The fourth, `tcp-ip-frente-a-osi grounds regla-de-centralizacion`, read off «TCP/IP frente a OSI es el caso
    canónico. … Ganó el que acordó menos.», became `regla-de-centralizacion bridges tcp-ip-frente-a-osi` with
    no text.
  - Its ends' own edges lie in different sections, so `shared_context` was empty. The grounder rejected it
    `no-support`, and its note said the source never ties the case to the rule. The section around the passage
    restates the rule in its first line.
  - A targeted extraction wrote the `grounds` edge the same day.
- **Why the second construction's own edge:**
  - The relation is what the second reading found. `bridges` says only that a pair is joined, and the pack
    excludes evidence from it, so a `grounds` the reading had found could not hold as one.
  - The passage is where the reading found it. Without it the grounder can only look where the two ends' other
    edges lie, and a relation the graph lacks is often stated elsewhere.
- **Why in the notes, written by the engine:**
  - A proposal still carries no span: the propose lane stays span-less, and a proposal is promoted only on
    support a grounder supplies.
  - Notes already hold the engine's marks (`lead:`, `lead (from …)`), and the canon keeps everything the
    derived layer shows.
  - The span is checked before it is written and again when it is shown, so what a grounder reads is text of
    the source. The JSON segment keeps a span that holds ` | ` or quotes whole.
- **Why the graph's ids:**
  - The ensemble step pairs the constructions by id alone. A concept coined anew leaves every edge on it
    uncompared: 18 of the 22 edges in the field test.
  - Naming is not the blind spot a second reading is for. What it relates, and how, still comes from its own
    reading.
- **Where the line is:**
  - Only a passage in the graph's own sources can support grounding. A document outside them counts once it is
    added to the sources and built. Until then its passages are dropped at `kg_propose` and named in the report.
- **Rejected alternatives:**
  - (a) *Let the grounder judge against the second document, as an external citation.* That would ground edges
    on a document the graph's sources do not hold. Adding the document to the sources does the same and keeps
    every edge checkable against them. The user agreed (2026-11-16).
  - (b) *Store the passage as the proposal's span.* The hypothesized lane is span-less by design, and a span is
    what a grounder supplies to promote.
  - (c) *A side ledger of passages in the derived layer.* Derived holds nothing the canon does not.
  - (d) *Have the language layer quote the passage in its note.* Nothing would check it, and a copy that drifts
    by a character no longer verifies.
  - (e) *A new tool for known nodes.* `kg_section` already serves a section with its known nodes. With
    `construction` and `source` it serves the second document the same way, scrubbed by the construction that
    restores its spans.
  - (f) *Let a rejected proposal with a passage carry a lead.* That changes the lead path and needs its own
    decision. Another relation found in the passage still goes in the note.
- **Accepted trade-offs:**
  - A second reading that reuses the graph's ids is less independent in its naming.
  - In an `all` run, a typed `bridges` from the ensemble step that the bridge mechanism also proposes keeps the
    bridge mechanism's candidate, without the passage. `/burgess:kg-perturb` runs the ensemble step alone.
  - A proposal's notes open with a JSON segment.
- **Pinned in:** `tests/test_fix_perturb_second_reading.py` (28 tests).
  - Against 0.18.1 the module does not import, because the passage helpers do not exist, so all 28 fail.

## The leak check reads a digest, and the ensemble step says how each edge fared (2026-11-16)

- **Decision:**
  - `kg_metrics(digest=true)` adds `canon_digest`: a sha256 over the canon's note files, each one's name and
    bytes, in name order, read from disk (`KGEngine._canon_digest`). Without `digest` the answer is as before.
  - `/burgess:kg-perturb` reads counts and digest before its extractor starts and after it returns. Both must
    be unchanged. If either moved, it stops before cross-generating and does not ground. The check needs no
    Bash.
  - With a second construction, `kg_generate` carries `ensemble` (`generate.ensemble_tally`): how each of the
    construction's live edges fared, in the order the step decides, the parts summing to `edges`.
    - `ends_missing`: an end is not a node here.
    - `repeated`: this very edge is live here.
    - `joined_otherwise`: the pair is joined here by another live edge.
    - `untyped`: the edge records no relation.
    - `known_failures`: the edge or its reverse is in failure memory; `known_failure_ids` lists them.
    - `new`: what the step proposes, before its top-`k` cut.
  - `note` says why when none is new, and how many new edges the cut left out.
  - The command reports from the tally, skips the generator when there is no candidate, and never re-derives
    the outcome from the canon.
- **Field run it answers** (0.19.0, 2026-11-16): the second `/burgess:kg-perturb`. It re-read «Síntesis -
  Fábricas de software.md», one of the graph's own sources.
  - The extractor read each section with the graph's known nodes, and took the graph's id for all 20 of its
    nodes. Its 10 edges all repeated the graph's own: 9 grounded, and `base-de-conocimientos enables
    fabrica-industrial`, which the graph had rejected `wrong-node`.
  - `kg_generate(ensemble)` returned no candidate and an empty note. The session ran two scripts over the canon
    to learn why; one waited 15 minutes on approval.
  - The session hashed the canon with Bash before and after the build, because its notes said counts could miss
    a leak (11 and 26 minutes on approval). The hash was identical.
  - The run took 68 minutes. The extractor took one of them, and the cross-generation a second.
- **Why a digest:**
  - Since 0.19.0 the brief has the second reading declare the graph's own nodes with a label and body of its
    own. A write that lost its routing lands on those nodes as deduped writes. `_merge_into_existing` adopts an
    incoming label on any note and an incoming body on an unverified one, so labels and bodies change and no
    count moves. This was verified on a test canon: label and body replaced, `kg_metrics` identical.
  - The field project has no version control, so such a rewrite could not be undone there.
  - A digest of every note sees any change at all, whatever made it.
- **Why from disk:** the baseline cache is keyed on file stats, so a write it has not seen could slip past a
  digest built from it. The check runs twice per perturb. Reading the notes is about a megabyte on the field
  canon.
- **Why the tally:** a second reading of one of the graph's own sources mostly confirms the graph. Its report
  has to say so, and say why nothing was proposed, from what the engine decided rather than from a script over
  the canon.
- **Rejected alternatives:**
  - (a) *Keep counts, and stop the second reading declaring known nodes; the construction would copy them from
    the graph.* A misrouted write would then add only edges, which counts see. But a re-emit of an existing
    unverified edge still replaces its span and notes without moving a count. And the check would rest on the
    brief being followed, which is the very thing it checks.
  - (b) *Hash the canon in the command with Bash,* as the field session did. That takes an approval per call,
    and the shell differs between Windows and Unix.
  - (c) *Refuse an unrouted write while a construction is being built.* The engine cannot tell an unrouted write
    from an ordinary one. Any such state would lock the primary for the whole session.
  - (d) *Propose a `joined_otherwise` edge as a candidate.* §9 defines the step as structure between nodes not
    adjacent here. A second relation on a joined pair is another mechanism, and needs its own decision. It is
    counted, so the report shows the disagreement.
- **Accepted trade-offs:**
  - The digest moves on any change to a note, including another session's legitimate write during the build.
    The command then stops and tells the user, who can tell the two apart.
  - `untyped` counts edges, while an untyped pair yields one `bridges`.
- **Pinned in:** `tests/test_fix_perturb_leak_check.py` (14 tests).
  - Against 0.19.0 the module does not import, because `ensemble_tally` does not exist, so all 14 fail.

## On Windows the venv is built on the setup's own Python, and a failed build says so (2026-11-16)

- **Decision:**
  - On Windows, `bootstrap.install_with_uv` passes `--python <sys.executable>` to `uv sync`
    (`_uv_python_pin`). That is the interpreter running bootstrap, which the launcher and the hook found
    and `provision` checked to be ≥ 3.10. A `UV_PYTHON` the user set is kept. Other platforms keep uv's
    choice.
  - A failed build leaves `provision.failed` beside `provision.log`: JSON `{at, error}`, one line naming the
    step and its cause (`_failure_line`). An Application Control refusal (WinError 4551) is named as such,
    with the refused file, which `bootstrap.run` now attaches since Windows' error carries none. Any OSError
    during a build is caught and recorded, no longer a bare traceback. `_ok_with_reconcile`, the one
    success exit, removes the record.
  - `launch_server.mjs` ends its wait as soon as a record written after its own start appears
    (`waitUntilReady`'s `failed`), and reports the failure with its cause. At the deadline with an older
    record, it says a build is running but the last one failed, and what failed.
- **Field run it answers** (0.19.1, 2026-11-16, Windows 11 with Smart App Control on):
  - The engine venv had been built by uv on its managed CPython 3.12.13 (python-build-standalone), while
    bootstrap ran on the PSF-signed python.org 3.14.3. A Windows venv's `python.exe` is a copy of its base
    interpreter's launcher, here an unsigned 45 KB file.
  - At 12:48 UTC Smart App Control refused that file, which had run the engine for days. The Code
    Integrity log shows no cached verdict, a cloud lookup, and a fail.
  - At 13:02 the next session's readiness check could not run the venv's interpreter, so it fell back to
    the running interpreter's identity, the stamp mismatched, and a rebuild began. It failed at the import
    check with WinError 4551 and removed the venv. Four more rebuilds created fresh venvs on 3.12.13 and
    failed the same way.
  - Each launch said the setup was "still being set up in the background", normal after an update, and
    suggested `MCP_TIMEOUT`. The field session first suggested raising it, then found the cause in
    `provision.log` and the event log. A uv venv built on the python.org interpreter started.
  - The 0.19.1 update was not the trigger: the session before ran 0.19.1 on the existing venv with no
    rebuild.
- **Why the setup's own interpreter:**
  - It is the interpreter the setup already chose and checked. uv's preference for its managed Python
    silently put a different one, with a different launcher, under the engine.
  - On Windows the venv's `python.exe` is that interpreter's launcher, so the venv is exactly as trusted
    as the Python the user installed. That is signed for the python.org installer.
  - Elsewhere a venv's interpreter is the base one itself, so nothing is gained by overriding uv there.
- **Why a record file:** the build runs in a detached worker whose exit code reaches nobody. The launcher
  already polls the data folder for the stamp, so one more file read is the whole channel. Removed on
  success, a record always means no build has succeeded since.
- **Rejected alternatives:**
  - (a) *Detect WinError 4551 and only then retry on the setup's interpreter.* That adds a second path a
    test can only fake. The first build would still land on the unsigned launcher, and stay there until
    Windows' verdict flips.
  - (b) *Rebuild every existing Windows venv now.* A venv that works would cost every Windows user a
    rebuild, and a first session that cannot connect, for a risk that has hit one machine. It moves on its
    next rebuild instead.
  - (c) *Run the base interpreter with the venv's packages instead of the venv's `python.exe`.* A venv is
    found through `pyvenv.cfg` beside its executable, and emulating that is a larger change than choosing
    the interpreter.
  - (d) *Raise the launcher's wait.* The build had not been slow: it failed. A longer wait only delays the
    message.
- **Accepted trade-offs:**
  - On the field machine the venv moves from Python 3.12 to 3.14. The lock has win_amd64 wheels for cp314
    or abi3 for every compiled package, so nothing compiles. Whether Smart App Control lets those DLLs load
    is known only once the build runs there. If it does not, the record names the refused file.
  - A record that cannot be written costs only the launcher's explanation; the build's outcome is the same.
- **Pinned in:** `tests/test_fix_windows_signed_venv.py` (14 tests).
  - Against 0.19.1 all 14 fail: the platform helper they patch does not exist there, nothing writes the
    record, and the launcher's wait has no failure to end on.

## Leiden through igraph when leidenalg cannot load, and kg-diverge shows the whole round (2026-11-19)

- **Decision:**
  - `projector.leiden_membership(undirected, seed, resolution)` runs leidenalg's
    `RBConfigurationVertexPartition` when leidenalg loads and runs. Otherwise it runs igraph's built-in
    `community_leiden(objective_function="modularity")` at the same resolution, with igraph's generator
    swapped for a private `random.Random(seed)` and restored afterwards.
  - `projector._leiden` (seed 42) and `generate._repartition` (seed 7, resolution 4.0) both call it. Each
    keeps its label-propagation fallback for an engine where igraph itself cannot run.
  - The bootstrap probe and the engine's preload log name igraph's Leiden as the fallback.
  - `/burgess:kg-diverge` step 7, after the slate, lists every other idea ingested that round in two or
    three plain lines with an example, and invites pinning any idea of the round.
- **Field run it answers** (0.19.2–0.19.3, 2026-11-16 to 11-19, the first field `/burgess:kg-diverge`, on
  Windows with Smart App Control on):
  - At the engine starts of 11-18 at 12:13 and 15:25, the preload logged "leidenalg unavailable
    (ImportError: DLL load failed while importing _c_leiden …)", and every projection would have used label
    propagation.
  - After the 0.19.3 rebuild leidenalg loaded again. Smart App Control decides per file and per lookup, in
    either direction. The canon did not change in between, so the field graph kept its Leiden communities.
  - The session's step 7 showed six of twelve ideas per round. Round 2 showed the rest as a one-line table,
    the user could not tell what they were about, and one pin went to an idea never explained. From round 3
    the session explained every idea on its own initiative.
  - 0.19.3 recorded its test count from the Windows run (2254 passed, 4 skipped) instead of Linux (2255, 3).
- **Why igraph's Leiden:** igraph's DLL is a core import, so it loads wherever the engine starts at all.
  Its Leiden optimizes the same objective, and on the karate club it finds the partition leidenalg finds.
  Label propagation is a different algorithm: the communities it draws, and every rank, bridge and
  generation built on them, would change whenever Windows changed its mind about one file.
- **Why the whole round:** the slate is the engine's diverse pick for attention, not a filter on what the
  user may keep. An idea the user cannot read cannot be pinned on purpose. Earlier rounds' ideas are not
  repeated.
- **Rejected alternatives:**
  - (a) *Always use igraph's Leiden and drop leidenalg.* That would redraw every installation's
    communities, since the implementations differ in their random draws, for a failure seen on one
    machine.
  - (b) *Remember a failed leidenalg import for the life of the process.* A module-level flag leaks between
    engines and tests; the retried import costs little.
  - (c) *Show the rest of a round only when the user asks.* The user cannot ask about ideas they have not
    seen.
- **Accepted trade-offs:**
  - Where leidenalg cannot load, communities come from a second implementation and can differ in detail
    from leidenalg's.
  - A round's message grows by about six short paragraphs.
- **Pinned in:** `tests/test_fix_leiden_igraph_fallback.py` (7 tests) and `tests/test_fix_diverge_presents_rest.py`
  (2 tests).
  - Against 0.19.3, 6 of the 9 fail. The 3 that pass pin what 0.19.3 already did: the result with
    leidenalg, the last resort without igraph, and two cliques, which label propagation also separates.

## kg-diverge reads plugin files by path and resumes from recall; the cold-start threshold is the embedder's own (2026-11-20)

- **Decision:**
  - `/burgess:kg-diverge` names every plugin file it uses by `${CLAUDE_PLUGIN_ROOT}`:
    `skills/burgess/references/{operators,axis_inference,judge_rubric}.md` and the templates under
    `pack/domains/` and `pack/domains/examples/`. It says to open them with the Read tool, never with Bash,
    and never to read `.kg/diverge/` files.
  - `kg_diverge_init` returns the resolved `axes`, `unit_of_generation` and `candidates_per_generation`.
    `kg_diverge_recall` returns the same, plus `session_id` and `seed`, from the engine's own state. Step 8
    gains "After a compaction": call recall first, keep its seed, and never re-init with another session id.
  - The monitor's cold-start similarity threshold resolves like `dedup_tau`. `engine.monitor_cos_threshold`
    now defaults to `null`, meaning the embedder family's own value, `monitor.default_cos_threshold`: 0.55
    for `hash`, 0.67 for `static`. A domain can still pin a number.
  - `kg_diverge_remember`'s description and step 7 say what comparisons do: the engine only stops asking a
    pair already answered and tallies the answers for recall. Neither the slate nor the parents read them.
    Step 7 also says a slate brings earlier ideas back, and that a repeat is no reason to discard.
- **Field run it answers** (0.19.4, 2026-11-19, Windows session 6cedf547: 3 rounds, 48 ideas,
  `research_hypotheses`, `/effort max`):
  - All 19 Bash and PowerShell calls waited for the user's approval. Seven of them hunted for or read
    plugin files: find, ls, cat and sed on `operators.md` and `research_hypotheses.yaml`. Another read
    `axes.json` and `pins.json` after a compaction. Those seven waited 5757 s in all, including 845 s and
    4604 s before the first round, while the user was away.
  - The command had named `references/operators.md` and `pack/domains/...` as relative paths, which lead
    nowhere from the project. The first field session had found the same files with Glob and Read, which
    asked nothing; this one used Bash.
  - The first batch scored a mean cosine of 0.5807 against the absolute 0.55 (`calibrated: false`). The
    session regenerated, and told the user the twelve "hablaban de mutación con las mismas palabras". They
    were twelve distinct mechanisms. The fourth batch scored 0.581 and passed against the calibrated 0.6855.
  - The session explained a lost idea's return by «las comparaciones pesan poco en la selección». It
    suggested discarding two ideas because they kept coming back («si no quieres verla más», «que ya ha
    salido tres veces»); one of them was the parent of two later ideas. The user discarded nothing.
- **Measurements behind 0.67** (potion-multilingual-128M, WSL, the engine's own embedder and
  `mean_pairwise_cosine`; the harness reproduced all 11 field values to four decimals):
  - Field generations of both sessions, 12 ideas of 55–90 words each, all healthy: 0.45–0.58, mean 0.52.
    The calibrated limits the monitor reached from the third generation: 0.62–0.70.
  - Batches written for the measurement, twelve variations of one mechanism each:
    - 57–61 words per idea: 0.56 and 0.62;
    - 13–28 words per idea: 0.36–0.55 (six batches, Spanish and English).
  - The healthy field ideas cut to their first 25 words: 0.26–0.41.
  - Two healthy batches translated to English: 0.53 and 0.54.
  - The same healthy batch with the brief restated at the start of every idea: 0.77.
  - The selftest's samey fixtures: 0.89 and 0.90.
  - So under potion, mean cosine follows idea length about as much as sameness. At equal length a
    same-mechanism batch scores about 0.05–0.15 above a healthy one, and the ranges overlap.
- **Why 0.67:**
  - It is what the calibrated rule computes from a typical healthy baseline: the field mean, 0.52, plus the
    margin, 0.15. The first generation is then judged as the third will be, and the same similarity no
    longer gets opposite verdicts in rounds 1 and 4 of one session.
  - 0.55 sat inside the healthy range, so it fired on a narrow brief's long ideas and not on a short
    collapse.
- **Why paths and returned axes, not more search hints:**
  - A path that resolves needs no search. Claude Code fills `${CLAUDE_PLUGIN_ROOT}` in command text (as
    `/burgess:kg-eval` relies on; seen in the field as `C:/Users/…/burgess/0.13.2/…`), and in the field sessions
    that used them, Read and Glob asked nothing for plugin files.
  - The axes are engine state, and a compaction loses them along with the session id and the seed. One
    recall call restores all of it, with no file to read.
- **Rejected alternatives:**
  - (a) *Keep 0.55 and let the agent overrule an uncalibrated flag by inspecting the mechanisms.* That puts
    the judge back over the geometry that the monitor exists to keep independent.
  - (b) *Measure similarity over the `mechanism` strings, or normalize it by length.* Both may separate
    sameness better under potion, but each needs its own calibration and changes what the monitor
    measures. That is more than a patch.
  - (c) *Serve the reference texts through an MCP tool.* The Read tool already reads plugin files without a
    prompt; a resolvable path was the missing piece.
  - (d) *Make the slate read comparisons, so that the old wording becomes true.* The slate is the DPP's
    diverse pick. Letting answers steer it is a design change, not a wording fix.
- **Accepted trade-offs:**
  - Under `static`, a same-mechanism batch of long ideas (0.56–0.62) is no longer flagged at cold start.
    The calibrated rule misses most of those too: only the most similar (0.624) clears the lowest field
    limit (0.622). A template-like collapse (0.89) is still flagged.
  - `local` (bge-small) keeps 0.55 for lack of measurements, though the selftest's docstring already
    expects it to misfire there.
  - An axis's meaning still lives in the template's comments. Reading them is a Read at a given path.
- **Pinned in:** `tests/test_fix_diverge_paths_coldstart.py` (16 tests).
  `tests/fusion/divergence/test_engine_config.py` now expects the `null` default.
  - Against 0.19.4, 14 of the 16 fail. The 2 that pass pin what 0.19.4 already did: recall on a project
    never inited, and a comparison leaving the next slate alone. Two of the 14, the calibrated rule and
    the template-like collapse, fail there only because the monitor's helper took no embedder.

## kg-diverge saves every idea through the engine, beside the brief's state and never in the project root (2026-11-20)

- **Decision:**
  - A candidate may carry an `explanation`: the two or three plain lines, with an example, that the agent
    shows the user. The record keeps it, a slate item returns it, and nothing in dedup, placement, novelty,
    the slate, the parents or the monitor reads it. Geometry still runs on `text` alone.
  - Each record notes its `batch` (one non-empty ingest, numbered like `meta.cycles` after it) and
    `slated_in`, the batches whose slate showed it. Both live in the session zone, and only the export
    reads them.
  - New tool `kg_diverge_export(project, brief)` (35 in all) and CLI `export`. It writes every record of
    the current session to `.kg/diverge/<brief>/ideas-<brief>-<session>.md` and returns the path. Per idea
    the file holds the text, the explanation, the descriptor, the operator and parents, the slates, and the
    user's pins, discards, comparisons and materializations. It changes no state, and nothing reads the
    file back.
  - `/burgess:kg-diverge` writes the explanation when it generates (step 4, "Layer 3"), presents it in step
    7, and calls the export in a new step 11. It never builds the file itself. A copy elsewhere is one
    command that asks for permission.
- **Field runs it answers** (both field sessions, Windows, 2026-11-16 to 11-19 and 2026-11-19):
  - At the end of each the user asked for every idea in a Markdown file, each one explained. The session
    saved that as a feedback note: take the texts from `session/candidates.json`, and recover the examples
    of earlier rounds from the transcript.
  - On 2026-11-19 the session read the store and its own transcript with Bash scripts, and wrote a 37 KB
    generator script that embedded the texts, then ran it with Bash. A heredoc attempt failed with
    ENAMETOOLONG. Ten prompts, about two hours of waiting. The explanations of the rounds before the two
    compactions existed only in the transcript.
  - 0.19.5 told the command never to read `.kg/diverge/`, so the feedback note and the command now
    contradicted each other, and no sanctioned way to export was left.
- **Why the engine writes the file:**
  - The first session's file was 111 KB for 86 ideas. Written by the agent, every byte is model output.
    That is what drove the field session to a script, and after a compaction the agent no longer has the
    early rounds anyway.
  - The engine holds every idea already. With the explanation stored at ingest, nothing has to be dug out
    of a conversation.
- **Why there, and nowhere the agent names:**
  - In the field the project folder IS the source folder (`source_path`), and a directory source is every
    `.md` at its top level (`SourceSet.resolve`). An export in the project root would be read by the next
    `/burgess:kg-build` as a source document, and the session's ideas would come back as spans that ground
    claims: hypotheses laundered into evidence, the reverse of the propose-lane rule. The dot-directory is
    skipped by both the directory resolution and a recursive glob (tested).
  - An MCP tool's write passes no permission check, unlike a Write or a Bash command. A tool that wrote to
    any path the model gave could plant a file in, say, a `.claude/commands/` folder. A fixed place under
    the engine's own state folder keeps the tool's reach where it already was.
  - One file per session id: a second export in a session replaces it with a superset, and a later session
    cannot overwrite an earlier one's.
- **Rejected alternatives:**
  - (a) *`kg_diverge_recall` returns every idea and the agent writes the file with Write.* That costs the
    file's size in output, and the explanations of compacted rounds are still lost.
  - (b) *The engine writes to the user's Downloads folder, or to a path the agent passes.* That is a write
    outside every permission check, decided by the model (above). The user's Downloads habit is served by
    one copy that asks.
  - (c) *Write the export into the project folder, where the user looks.* That is source laundering
    (above).
  - (d) *Store explanations as a `kg_diverge_remember` event.* Preference memory is durable, so
    explanations would outlive the records they explain (I10). It would also take twelve more calls per
    round.
  - (e) *Record the near-duplicates the ingest drops, so the export holds literally every idea sent.* The
    ingest has never kept them, and the tool description says so. Recording them is a change to the
    ingest contract, not to the export.
- **Accepted trade-offs:**
  - The file's own labels ("Batch", "pinned", "beat", "lost to") are English, like every view the engine
    renders. The ideas, explanations and brief are in the user's words.
  - The brief is not engine state: the agent passes it, and without it the file has no heading quote.
  - Ideas ingested before 0.19.6 have no explanation or batch. The export lists them first and names them in
    `unexplained`; it does not rebuild them.
- **Pinned in:** `tests/test_fix_diverge_export.py` (12 tests). `tests/fusion/test_diverge_surface.py` counts
  35 tools.
  - Against 0.19.5, 11 of the 12 fail. The one that passes pins what 0.19.5 already did: it ignored the
    field, so an explanation could not move an idea.

## kg-diverge keeps two diverse parents, draws them again each round, and asks about the round's ideas (2026-11-21)

- **Decision:**
  - `kg_diverge_parents` returns every pin plus at least `memory.MIN_DIVERSE_PARENTS` = 2 diverse elites.
    `k` is still the total, but it grows to the pins plus two when it is smaller than that. Fewer come
    back only when the archive has fewer elites to offer.
  - The diverse elites are drawn by `diversity.d2_sampling`, the k-means++ seeding rule, from
    `np.random.default_rng([seed, meta.cycles])`. Each pick is drawn with probability proportional to its
    squared cosine distance from the nearest idea already chosen, the pins first. Without a generator
    `memory.select_parents` is still the max-min walk, which the ported donor suite pins.
  - `memory.select_ask_pairs(fresh=...)`: when none of the chosen pairs names an idea of this round, the
    last chosen pair gives way to the most informative unanswered pair that does. The other side of that
    pair comes from the slate or from this round. With fewer pairs than asked for, it is appended instead.
    The ingest passes the round's survivors that hold a niche, minus discards.
  - `/burgess:kg-diverge` step 7 asks such a pair by the idea's id, as it was explained in the rest of the
    round. Step 8 says to leave `k` alone.
- **Field run it answers** (andamiaje-ia-clasica, Windows, 2026-11-20/21, on 0.19.6, five rounds, 60 ideas):
  - The pins went 2, 3, 4, 5 over rounds 2 to 5. The agent passed `k=5` in round 3 on its own, then the pins
    plus two at the user's request. With the default, round 4 would have had no diverse parent at all.
  - The diverse parents were c2g and c2k in rounds 3 and 4. In round 5, after a new pin, they were c2g and
    c1k. Every one of the 60 ideas held a niche of its own with fitness 1.0, so the walk had nothing but the
    fixed geometry to go on.
  - The slate was c1d c2k c2g c2e c1k c2n in rounds 2, 3 and 4; in round 5 c5c replaced c2n. The questions
    of rounds 3 and 4 were c1d-vs-c2e, c1d-vs-c2n, c2e-vs-c1k and c1d-vs-c2g, so the 24 ideas of those
    rounds were never compared. c1d was in five of the eight questions the user answered.
- **Why a floor, not a new meaning for `k`:**
  - Reading `k` as the number of diverse parents would change what every caller gets. The floor changes
    nothing with up to two pins, the common case that the donor tests cover, and adds only when pins crowd
    the default. Two is what the default already gives with two pins, and what the field agent kept by
    itself.
- **Why D² sampling:**
  - It keeps the purpose of the walk, distance from the pins and from each other, while a different far
    idea can come up each round. Uniform sampling would drop that purpose. A k-DPP sample is the textbook
    choice, but it needs an eigendecomposition of the elite kernel to pick two ideas. D² is the standard
    randomized form of the max-min walk, with the same seeds-first contract.
  - Keyed by the seed and `meta.cycles`, so it persists nothing. The same call within a round returns the
    same parents, and the agent may call twice. The slate stays deterministic (`select_diverse`,
    review-r8-19). The parents affect which stepping stones are offered, never what is true (I5).
- **Why one fresh question, not a fresh slate:**
  - The slate is the archive-wide diverse pick by design, and when it does not change that is a reading too:
    the round's ideas did not widen the spread. The questions are where the stuck slate hurt, because the
    user could compare only old ideas.
  - Only the last pair gives way, and only when no chosen pair names a fresh idea. So round 1, whose slate is
    all new, and a round whose slate already brings a new idea into a question are unchanged (tested).
  - Fresh items are niche holders only. A state prune always keeps elites, so a question never names an idea
    the store may drop before the user answers.
- **Rejected alternatives:**
  - (a) *Read `k` as the number of diverse parents.* It changes every caller (above).
  - (b) *Rotate the diverse parents away from ideas already bred from.* The genealogy is what the agent
    declares, and a session that does not fill it in would keep the old behaviour.
  - (c) *Reserve slate places for this round's ideas.* That changes what the slate is and how it is picked.
    The command already explains every idea of the round, and the export keeps all of them.
  - (d) *Make both questions name new ideas.* The slate pair still compares the ideas the engine finds most
    spread out. One question out of two is enough to end the drought.
- **Accepted trade-offs:**
  - The diverse parents of a round are no longer the two most extreme ideas, only far ones. Two sessions
    with the same seed and the same history still get the same parents.
  - A fresh question may name an idea that is not on the slate. The command explains every idea of the
    round, so the agent asks it by id.
  - NumPy may change a Generator's streams between versions. Reproducibility holds within one install, and
    a session needs no more. The tests pin properties, not particular picks.
  - The export's English labels, a 0.19.6 trade-off, stay as they are.
- **Pinned in:** `tests/test_fix_diverge_parents_and_pairs.py` (24 tests).
  - Against 0.19.6, 17 of the 24 fail. The 7 that pass pin what must not change: four parents with up to two
    pins, an explicit larger `k`, the same parents twice within a round, the max-min walk without a
    generator, and round 1's questions on its own slate.

## kg-diverge says at the end of every round what reaches the graph (2026-11-21)

- **Decision:**
  - `/burgess:kg-diverge` step 7 ends every round with one line on what reaches the graph: nothing goes in
    unless the user asks; when they ask, the pinned ideas go in, and any other idea they name is pinned
    first.
  - The command's *Materializing pins* note says how to carry an idea that is not pinned: pin it with
    `kg_diverge_remember`, then materialize it. It also says what that pin does besides: it is a parent of
    every later round of the brief, and it lifts the idea's discard (pin and discard are exclusive per id;
    the latest event wins). And it says that an idea in the graph comes back in every `/burgess:kg-ground`
    pass while it stays `unverified`.
  - Step 7's pin bullet named `/burgess:kg-generate`'s propose lane as the way into the graph. It now says
    the pins are the only ideas that can go in, when the user asks, through the materialize note.
  - The engine is unchanged: `kg_diverge_materialize` still takes pins only.
- **Sessions it answers** (two test sessions, Windows, 2026-11-21, on 0.19.7; the developer's WSL session
  answered every round at the user's request):
  - Each session had five rounds and 60 ideas, and five pins at the end. When the user asked to carry them
    into the graph, 10 nodes went in.
  - The user then asked whether the ideas had gone into the graph as candidates, and later why only 10 of
    the 120 could. No round had said that nothing enters the graph unless the user asks, or that only pins
    can be carried.
  - The user asked for all 120. The other 110 had to be pinned first, which made all 60 ideas of each brief
    parents and lifted the six discards of those sessions. The command said nothing about that path or its
    cost. The next `/burgess:kg-ground` judged all 120, at about $2.55, and left them `unverified`. Every
    later pass will judge them again.
- **Why every round:** pinning is a per-round choice, so the reminder sits where the choice is made, next to
  the pin and discard prompts. The user asked for it at the end of every round. One line is the cost.
- **Rejected alternatives:**
  - (a) *Materialize the pins at the end of the session unless the user says no.* The user chose the reminder
    over it on 2026-11-21. It would reverse the kickoff's Q5 decision that nothing enters the graph
    implicitly, and every session's pins would join every later `/burgess:kg-ground` pass.
  - (b) *Say it only when the session ends.* By then the pins are chosen, and the user asked for every round.
  - (c) *Let `kg_diverge_materialize` take ideas that are not pinned.* The pin is the explicit selection, and
    pinning first makes the side effects visible: a new parent and a lifted discard.
- **Accepted trade-offs:** one more line in every round's presentation.
- **Pinned in:** `tests/test_fix_diverge_graph_notice.py` (6 tests).
  - Against 0.19.7, 4 of the 6 fail: the round notice, the pin bullet, the materialize note and the user
    docs. The 2 that pass pin the engine path the text now promises. An idea the user names is refused
    until pinned and accepted after. Pinning a discarded idea lifts the discard and makes it a parent.

## kg-diverge keeps its cliché map, opens with the avoided clichés, and can carry the map into the graph (2026-11-21)

- **Decision:**
  - The first `kg_diverge_ingest` takes the agent's cliché map as `cliches`, `{"avoided": [...],
    "held_out": [...]}`: the O_train and O_test of step 3. The engine numbers it `o1, o2, …` (avoided first),
    keeps it in `session/cliches.json`, and returns it from `kg_diverge_recall`. A new session id wipes it
    with the archive (I10).
  - Nothing in the geometry reads the map. The slate, the ask pairs, the monitor and the parents come out the
    same with or without it (tested).
  - Round 1 opens with the avoided clichés, by id. The held-out ones stay unshown until the session ends.
  - `kg_diverge_export` adds a `## Clichés` section. For each held-out cliché, the result's `cliches` carries
    `closest`: the three ideas nearest to it by cosine in the session's embedding space, from
    `originality.nearest_ideas`, which is measurement only. The command shows them at the end.
  - `kg_diverge_materialize(project, cliche_ids=[...])` carries clichés through the same door, on the user's
    word, as `cliche-<brief>-<id>` nodes whose body ends with a `[cliche]` line. A call with `cliche_ids` and
    no `candidate_ids` carries no pins. The ledger keeps clichés under `_cliches`, which the fate sync and the
    re-examinable advisory skip.
  - The grounder contract names the `[cliche]` node an ordinary hypothesis: grounded with support, `rejected`
    without.
- **Sessions it answers** (three test sessions, Windows, 2026-11-21, on 0.19.7 and 0.19.8; the developer's
  WSL session answered every round at the user's request):
  - Step 3 already made the agent map about six clichés, but nothing made it show them. Two sessions listed
    the three they avoided in round 1. The third named one cliché in passing, at the end of round 1.
  - The map lived only in the conversation, so none of the four exported idea files held it.
  - The user asked for the avoided clichés to open every session, and for the clichés to be able to go into
    the graph at the end.
- **Why the held-out clichés wait for the end** (the user's choice): they are the check. Once the user has
  seen them, the pins and comparisons can steer the ideas away from them, and the distance at the end would
  then measure that steering rather than the generation.
- **Why only the held-out ones get a distance:** the avoided ones steered the generation, so a distance to
  them would only grade the steering. Step 3 already says never to validate against O_train.
- **Why an unsupported cliché is rejected** (the user's choice): a pin is a new idea, so having no span is
  what makes it new, and the grounder leaves it unverified. A cliché claims what is usual. If the sources do
  not say it, that is information, and rejecting it also takes it out of every later grounding pass.
- **Why a parameter of the same door, not a new tool:** `kg_diverge_materialize` is documented as the only
  door from divergence into the graph. A second tool would be a second door, and the tool count would change
  everywhere it is stated.
- **Rejected alternatives:**
  - (a) *Show all six clichés in round 1.* The user chose to keep the held-out ones for the end (above).
  - (b) *Leave an unsupported cliché unverified, like a pin.* The user chose rejection (above).
  - (c) *Ingest the clichés as candidates.* They would enter the archive, the novelty scores and the slate,
    the very geometry the map exists to stay away from.
  - (d) *Store the map in the brief's durable memory.* Each session maps its own clichés, and the export and
    the materialization happen in the session that made them.
- **Accepted trade-offs:**
  - `closest` uses the session's own embedder, so it measures how near the texts lie in that space, not
    whether an idea is the cliché. An embedder that differs from the session's, or fails to load, gives
    `closest: []` and never fails the export.
  - The map dies with the session, like the ideas (I10).
  - Nothing forces the agent to send the map: the command tells it to, and a session without one simply has
    no Clichés section.
- **Pinned in:** `tests/test_fix_diverge_cliches.py` (26 tests).
  - Against 0.19.8, 23 fail. The 3 that pass pin what must not change: no `cliches` key without a map, a new
    session starts without one, and `kg_diverge_materialize` with no `cliche_ids` still carries every pin.

## An unsupported pin waits for the sources to change instead of being judged on every pass (2026-11-21)

- **Decision:**
  - New tool `kg_record_unsupported(target_id, kind, note)`, 36 in all. A grounder calls it for each
    `[diverge]` pin it leaves `unverified` for want of support. It appends `{kind, item, at, source_sig,
    item_sig, note}` to `.kg-unsupported-pins.jsonl` beside the canon, under the writer lease, and sets no
    state.
  - The record is refused for anything but an unverified hypothesized item with the `[diverge] pinned` marker.
  - `kg_ground_plan` leaves a pin out while its latest record's source signature (`_source_signature`, the
    sha256 of the sources' contents) and item signature (`groundplan.item_signature`: a node's label and body,
    or an edge's ends, relation, span and notes) match the current ones. Each such pin is counted in
    `queue.unsupported_waiting`.
  - A `focus` skips the ledger, as it skips the attack memory for hubs. The ledger reads fail-open, so a lost
    one only offers the pins again.
  - The grounder contract and `/burgess:kg-ground`'s Stage 1 template say to record. The command reports the
    waiting pins, and says that a focus asks for a fresh look.
- **Field graph it answers** (Windows, 2026-11-21, on 0.20.0):
  - The user carried all 120 ideas of two test sessions into the graph. The contract leaves an unsupported
    pin unverified instead of rejecting it, which is right for a new idea, but nothing recorded that judgment.
  - The pass over the 120 ran ten grounders, cost $2.55, and left all 120 unverified. The ten judged in an
    earlier pass were judged again for the same answer. Every later pass, for any other reason, would have
    paid that again.
- **Why the source signature, not a time or a pass count:** an unsupported pin can only change answer when
  the evidence changes, which means the sources or the pin itself. Waiting a fixed number of passes would
  still repeat a judgment that nothing could have changed.
- **Why a record tool, not `kg_ground(verdict="unverified")`:** `kg_ground` is the verdict monopoly, and
  "unverified" is the absence of a verdict. A `kg_record_*` tool that writes only a ledger is the pattern of
  `kg_record_attack` (0.10.0), `kg_record_edgeless_section` (0.14.0) and `kg_record_generation` (0.17.0), and it
  leaves the verdict paths and their audit untouched.
- **Rejected alternatives:**
  - (a) *Re-queue only the pins whose terms the changed text shares* (the 0.14.4 rule for span-less
    rejected items). It is sharper, but it would need the changed text at plan time, and one more judgment
    per pin per source change is affordable.
  - (b) *Let the orchestrator record the pins its grounders left unverified.* The judgment is the
    grounder's, and the orchestrator only has the grounder's report of it.
  - (c) *Reject unsupported pins after N passes.* That puts a new idea into the failure memory only for being
    new, which the triage rule exists to prevent.
- **Accepted trade-offs:**
  - Any change to any source, even an unrelated one, offers every recorded pin again, once.
  - A pin judged before 0.20.1 has no record, so the first pass after the update judges it once more.
- **Pinned in:** `tests/test_fix_ground_unsupported_pins.py` (17 tests). Against 0.20.0 the file does not
  even import, since the helpers and the tool are new. `tests/fusion/test_diverge_surface.py` now counts 36
  tools, and `tests/test_kg_ground_plan.py`'s queue shape gains `unsupported_waiting`.

## A node's grounder reads the source sections that share its words, and a rejected node can be judged again (2026-11-21)

- **Decision:**
  - `kg_ground_item(kind="node")` adds `source_context` to the node and its incident edges. It holds the node's
    `terms` (`groundplan.node_terms`: the label and body without lineage lines or verdict paragraphs) and up to
    `NODE_SECTIONS` = 3 source `sections`, each `{source_file, section, title, matched, excerpt}`.
    - The units scored are paragraphs (`groundplan.text_units`), and the lines of a table longer than an
      excerpt. A unit must share at least two of the terms, and a term weighs log(units / units that use it)
      (`groundplan.rank_units`). A section ranks by its best unit.
    - The excerpt is that unit with its neighbours, cut by offset from the source text itself
      (`groundplan.unit_excerpt`), so a span copied from it verifies.
    - The index is cached on the sources' signature.
  - An unsupported-pin record carries `evidence: 2`, and `waits_for_sources` honours only that version. The
    0.20.1 records, made by grounders that saw no source text, offer their pins again once.
  - `kg_ground_plan(reexamine=True)`, the command's `--reexamine`, also queues the rejected hypothesized nodes
    the focus names, all of them with no focus. Each item is `{id, kind: "node", reexamine: true}`, counted in
    `queue.reexamine`. A `failed` node is not offered.
  - The grounder contract reads `source_context` for a node and stamps its verdict on a `re-examine` item
    although its `from` is a verdict. `kg_ground` already allows that transition.
- **Field pass it answers** (Windows, 2026-11-21, on 0.20.1):
  - The pass over 120 pins recorded all 120 as unsupported. Its report said: "they searched the spans of edges
    already in the graph, not the full source files. So 'unsupported' means no extracted claim states the idea;
    a passage no edge cites could still exist." The code confirmed it: a node's evidence was `{node, edges}`.
  - Earlier that day the 6 clichés of `memoria-fabrica-agentes` had been judged the same way. One, o3, grounded
    on a passage an edge happened to cite. Five were rejected, permanently.
- **Why words, not spans:** the 0.18.0 `shared_context` places an edge's ends by the spans of their live edges.
  A pin or a cliché has no edge and no span, so the only handle on its text is its own words.
- **Why paragraphs, not sections:** I checked the draft by hand on the field corpus (9 documents, 93 sections,
  1655 units).
  - Scoring whole sections with a +1 inverse frequency let long sections win. They held many common words
    ("escriben", "mantienen", "junto") in unrelated paragraphs, and the passage that states cliché o3 did not
    make the top three.
  - Scored by paragraph, without the +1, o3's first section is Síntesis §Arquitectura with «El «Brain» guarda la
    memoria del proyecto y las decisiones de arquitectura previas…».
  - The hidden-test-suite pin's first section holds «la batería visible sube y la oculta no».
  - Cliché o2 (a vector store queried by RAG) gets the table row «Memoria … herr: bases vectoriales · patrón:
    RAG».
  - From WSL a call took 1.3 s, almost all of it in stat calls on `/mnt/c`. The scoring itself took about
    26 ms per node.
- **Why a version in the record, not a wiped ledger:** the ledger is engine state that a clone may not have,
  and the plan already reads it fail-open. A version says what the judgment saw, so a later change to the
  evidence can stale the records the same way.
- **Why `--reexamine` is explicit:** a rejection is permanent negative memory, and re-opening one is the user's
  call, the same as naming a hub to attack again. Detecting the old rejections automatically would mean
  stamping evidence into the §1.8 audit log, whose records back forge detection, for a one-time repair.
- **Rejected alternatives:**
  - (a) *Let a node's grounder read the source files.* The contract keeps grounders off files so that every
    batch judges the same scrubbed excerpts, and the excerpt is the check.
  - (b) *Give a node every section that names any of its words.* On the field corpus that is most sections. The
    rarity weighting, the two-word floor and the paragraph unit keep it to the ones that discuss the node.
  - (c) *Re-open the old rejections automatically.* See above: it needs an audit-log format change.
- **Accepted trade-offs:**
  - Words match by form (`buildplan._forms`: plurals folded), not by meaning. A node phrased in other words than
    its source gets weaker sections, and the grounder still judges what the excerpt states.
  - The first pass after the update judges every unverified pin once more, about 2.50 USD on the field graph.
- **Pinned in:** `tests/test_fix_ground_node_evidence.py` (16 tests).
  - `tests/test_fix_ground_unsupported_pins.py` now checks that a record without an evidence version no longer
    waits.
  - `tests/test_kg_ground_plan.py`'s queue shape gains `reexamine`.

## External sources with an epistemic level: the level vetoes a verdict, never decides one (2026-11-21)

- **Decision:**
  - `kg_source_add` (`evidence.py`) registers an outside text. The engine fetches a URL itself (stdlib urllib,
    a generic User-Agent) or reads a local `.md`/`.markdown`/`.txt` (verbatim) or `.html` file, extracts the text
    by a fixed stdlib `html.parser` rule (`html-text/1`), and writes `ext-<slug>-<8 hex>.md`, its record
    `<stem>.source.json` and, for a fetched page or HTML file, the bytes under `raw/`, into `<project>/evidence/`.
    PDF is refused. `preview=true` returns what to propose a level from and writes nothing.
  - The record holds a **level** (1 reviewed, 2 institutional, 3 editorial, 4 author or community, 5 unfiltered),
    a **role** (primary, secondary, tertiary), **marks** (interest, corrected, retracted, superseded),
    `retrieved_at` (the one date the engine certifies), `published` with `published_from` (`page` or `caller`),
    `level_by` (always `agent` through the tool), and the sha256 of the raw bytes and of the copy.
  - `SourceSet(path, extra=…, exclude=…)` appends the registered copies after the configured sources. The
    per-file views (`texts`, `verifies`, `files_containing`, `has_file`) see them; `concat` and `normalized` stay
    the configured corpus, and `full_concat` covers both. `_SourceResolver.verify()` builds that set; the
    projector, `kg_write`'s boundary, `kg_ground` and `kg_ground_item` read it, while `kg_build_plan`,
    `kg_section`, coverage and the specificity corpus keep reading the configured sources.
  - `kg_ground`: support (a promotion span, or the span of a non-hypothesized edge being grounded) must lie in a
    configured source or a usable copy (level 1–4, neither retracted nor superseded), else `support-not-usable`.
    A promotion records the named file if usable, else the first configured source, else the usable copy of the
    highest level. A `support_note` is recorded as `citation (unchecked): …` and returns
    `support: unchecked-citation`.
  - `kg_ground(verdict="failed", refuted_by=<counter-edge id>)`: required once any source is registered. The
    counter-edge must exist, be typed `attacked_by` / `confounded_by` / `collapses_into`, touch the claim and
    carry a span the engine can place. `evidence.failed_veto` then refuses `failed-by-unusable-source`,
    `failed-across-own-and-external` and `failed-by-lower-level`. The id is appended as `refuted by: <id>`.
  - `kg_source_list` reports the registry, its `problems` and `unregistered` files, and `support`: grounded edges
    and nodes by where their support lies (`own`, `external` by level, `unchecked_citation`, `unlocated`), with
    the claims resting on a source since marked unusable. `kg_source_set` changes a record, never the copy.
  - `kg_ground_item` adds `span_source` and labels every external excerpt with `source`; a node's
    `source_context` adds up to 3 sections from usable copies after its best 3. `kg_ground_plan` adds
    `evidence`, the usable copies, for the adversarial grounder's search.
  - `/burgess:kg-sources` (`add` with a preview and the user's confirmation, `list`, `set`) is the command; it
    may call only the three tools. The grounder and adversarial-grounder prompts and `/burgess:kg-ground`'s
    Stage 2 template carry the levels and `refuted_by`.
- **Origin:** the user asked for a command that finds sources able to verify, positively or negatively, what
  the graph leaves unverified, with sources classified by epistemic level, and pasted a five-level pyramid
  (peer-reviewed, institutional, journalism, opinion and community, noise) to improve. Two follow-ups the same
  day settled the rules: whether the higher level should win a contradiction, and, in a side chat the user
  agreed with, whether the newer source should win between equals. The user approved building it with my
  recommendations («Sí, empieza»). The search itself is the next step: this release registers the sources the
  user names.
- **Why a level, a role and marks, not one scale:** the pyramid ranked by kind of publication, but what a source
  is worth depends on the claim. A maintainer's post is the best source for "the maintainer announced X"; in AI
  the primary literature is arXiv; a vendor's documentation is the authority on what its product does, not on
  whether it is better. So the level says only what filter the text passed, the role how far it is from the fact,
  and the marks what qualifies it. The three stay separate, like the canon's three axes. The user's notes sit
  outside the scale (`own`): through 0.20.2 every `grounded` meant "my notes say it".
- **Why the level vetoes and never decides** (the user proposed "the higher level wins"): the level is the
  weakest field in the record (an agent proposes it, a click confirms it), while a span is checked letter by
  letter. A source of a higher level can be outdated, retracted or simply wrong (in the 2015 psychology
  replication project about 36 % of the results replicated). Many apparent contradictions differ in scope,
  time or definition, which `reconciles_with` exists to record. And a `failed` is negative memory that is never
  pruned, while an error in a view is only a wrong order. So a veto removes what a refutation may do and the
  text still has to refute the claim.
- **Why the notes and an external source never fail each other:** "do my notes say it?" and "does outside
  evidence support it?" are two questions. Overwriting the first with the second would erase what the notes
  say. The clash stays a visible counter-edge, and correcting the note is the user's call (R3 then flags the
  verdict whose span left). The user accepted this through the side chat.
- **Why the engine fetches:** WebFetch answers a prompt about a page with a small model, so a span copied from
  its answer would be verbatim of a paraphrase. A copy the engine made, with its hash, is what makes an outside
  span checkable. The extraction is stdlib-only because Smart App Control blocks unsigned native code on the
  user's Windows machine (sklearn, 2026-11-16).
- **Why copies are never extracted:** they are evidence for items the graph already has. Extracting a paper
  would flood the graph with its content and move the specificity corpus.
- **Rejected alternatives:**
  - (a) *One reliability score per source.* It collapses the filter, the distance from the fact and the
    qualifications into one number the claim's type would contradict.
  - (b) *The higher level wins a contradiction* (the user's first proposal). See above. Its ordering survives as
    the default order of a dispute in the views, planned with the clash classification.
  - (c) *The newer source wins between equals* (the side chat). It fits one kind of clash, a fact that changed,
    and that is `obsolete`, not `failed`. It fails for facts that do not change (history, attribution, a given
    experiment's result), for copies, for results that alternate, and for unclear dates. Planned with the clash
    classification, with three refinements: supersession recorded on the claim, not the source; publication
    dates compared, never the retrieval date; the newer source primary for the new state or of an equal or
    higher level.
  - (d) *Let a hand edit of a copy count.* It would let anyone forge a span the engine vouches for.
- **Accepted trade-offs:**
  - `level_by` is `agent` for everything registered through the tool, since the tool surface cannot prove a
    human chose it; the command asks the user to confirm before registering.
  - The HTML rule is simple: navigation and footers go, boilerplate inside the body stays. A page the rule reads
    badly can be saved as `.md` and registered as a file.
  - Some sites refuse a generic User-Agent; the fallback is the same.
  - Registering any source wakes every waiting pin, so the next pass judges them all once more against the
    larger corpus.
- **Open:** the search for sources (`find`), and the clash classification with `obsolete` and the dispute view.
- **Pinned in:** `tests/test_fix_external_sources.py` (42 tests). `tests/fusion/test_diverge_surface.py` counts
  39 tools; `tests/test_fix_command_names_and_judge_cost.py` counts 10 commands.

## Every source has a level, the notes included, and the project sets the level it requires (2026-11-21)

- **Decision:**
  - `evidence.Policy`, kept as `<project>/evidence/policy.json` and set with `kg_source_policy`: `required_level`
    (1–4, default 4), the worst level that may still support or refute; `notes_level` (1–5, default 4), the level
    of a configured file with no record of its own; per-file records `{level, role, marks, note}` set with
    `kg_source_set(<note basename>)`; `build_from_notes` (default true). A malformed file is reported and the
    defaults apply.
  - `evidence.level_unusable` adds `below-required-level`; `note_label` labels a configured file (class `own`)
    like a registered copy; `failed_veto` is one rule for every source (unusable refutes nothing, a lower level
    never fails a higher one). `failed-across-own-and-external` is removed.
  - `EvidenceRecord.build`: a registered copy extracted like a note. `SourceSet(content=…, path_is_content=…)`
    separates content (`concat`) from evidence-only files; `_SourceResolver.resolve()` is the content set
    (the notes if `build_from_notes`, then the copies with `build`), and `verify()` the content followed by the
    evidence-only files. `kg_build_plan` lists the content set's files.
  - `kg_ground(grounded, support_span=…)` on a span-present edge records `support: {"span", "source_file"}` in its
    notes; `_edge_support` is the usable file of the highest level among its span's and those passages'.
    Grounding refuses `support-not-usable` with `source_level` and `required_level`.
  - `kg_ground_item` labels every passage with `source`, adds `support_source`, and `support_context` (usable
    sections ranked by the claim's words) when the claim's support is not usable or a proposal has no usable
    shared section. The section index holds usable files only.
  - `kg_record_unsupported` also accepts an unverified edge whose span lies only in unusable sources, and a
    hypothesis while the notes' default level is below the required one; the plan leaves out any recorded item
    whose record still matches. A non-default policy's fingerprint joins `_source_signature`.
  - `kg_source_list` adds `notes`, `policy`, `support.own` by level, and `on_unusable` for claims whose best
    support is no longer usable. The grounder gets step 1e (support elsewhere, or unverified and recorded, never
    rejected for its level); the adversarial grounder, `/burgess:kg-ground` and `/burgess:kg-sources` (a `policy`
    action, note levels, `build`) carry the model.
- **Origin:** after 0.21.0 the user asked what sense it made that notes of unknown level verify an idea like a
  source, and whether a graph could be built from level-1 sources alone with `/burgess:kg-sources`. Both pointed at
  a flaw: `grounded` still meant fidelity to the notes, the notes ranked above every source and were shielded
  from them, and registered sources were never extracted. I proposed this model and doing it before the search;
  the user approved («Sí, el modelo primero»).
- **Why the notes stand at 4:** a personal synthesis is a text by an author nobody reviewed, which is level 4's
  definition, even when it cites reviewed papers; those papers can be registered themselves.
- **Why the uniform veto reverses the 2026-11-21 side-chat decision:** that decision kept the notes out of reach
  because the notes had no level. Once they have one, a special rule for them is the inconsistency the user
  objected to. The answer «Sí, el modelo primero» approved the model as proposed, with this change flagged.
- **Why corroboration is a notes segment, not a second span field:** an edge's id is its triple, so a second
  edge cannot carry the support; a new canon field would touch the model, the merge driver and the reconciler.
  The JSON segment survives ` | ` inside a span, as the 0.19.0 passage does, and canon keeps a verdict edge's notes.
- **Why "unverified and recorded" instead of `rejected`:** a rejection is permanent negative memory meaning no
  source states the claim. Under a strict policy the notes do state it, below the level, so rejecting would
  record a falsehood and spend a verdict the next registered paper could not reopen.
- **Rejected alternatives:**
  - (a) *Notes that propose but never verify, always.* It discards the notes' value in every project that does
    not want a strict level; the policy makes it a choice.
  - (b) *Keep the notes out of reach and only report the level.* That is 0.21.0's inconsistency.
  - (c) *A second span field on edges for corroboration.* See above.
- **Accepted trade-offs:**
  - Verdicts given under a looser policy keep their state; `on_unusable` names them, and re-judging them is the
    user's call.
  - `support_context` adds up to three usable sections to items whose own support is not usable, so a strict
    pass reads more text per item.
  - An extracted node has no span of its own: for the veto it stands at the notes' default level.
- **Open:** the search for sources (`find`), and the clash classification with `obsolete`.
- **Pinned in:** `tests/test_fix_source_policy.py` (18 tests); `tests/test_fix_external_sources.py` updated to the
  uniform veto and the labels; `tests/fusion/test_diverge_surface.py` counts 40 tools.

## Nothing usable, nothing queued; waiting items wake only for new usable evidence; a formula once (2026-11-22)

- **Decision:**
  - `kg_ground_plan`: when no file is usable under the policy, the hypotheses (pins, proposals, re-examined nodes)
    and the hubs are left out and reported as `blocked: {reason: "no-usable-source", items, hubs,
    required_level, hint}`. Extracted claims stay queued. The queue counts count what is queued.
  - The unsupported-item ledger keeps `usable`, the sha256 of each file usable when the record was made.
    `groundplan.waits_for_sources` makes an item wait while every file usable now was usable then. A record
    without the list (0.20.1–0.22.0) whose `source_sig` equals the configured sources' current 0.20.x signature
    stands for those files; any other keeps the signature rule.
  - The HTML rule becomes `html-text/2`: `annotation` / `annotation-xml` are skipped, invisible math operators
    (U+2061–U+2064) dropped, and a zero-width space dropped inside `<math>`. A copy keeps its rule in its record.
  - `kg_source_policy` and `kg_source_list` return `usable_sources` and, with none, a `warning`; the commands
    `/burgess:kg-ground` and `/burgess:kg-sources` pass both on.
- **Field run it answers** (Windows, 2026-11-22, session a00131d8, on 0.22.0): `list`, `add` of a level-4 arXiv
  preprint, `policy required=1`. All three behaved as designed, and the user approved the fixes («Sí,
  prepárala»). A read-only engine over the project showed that no file was usable, yet the plan queued 119 pins
  in 10 batches. Registering the preprint, usable at the time, had changed the source signature, and the
  stricter policy changed it again instead of putting them back to sleep. The copy of the preprint held its
  formulas twice (36 LaTeX annotations, 30 commands left in the text).
- **Why a set of usable hashes, not a signature:** a signature changes on every change, including those that can
  only remove support. What can make an unsupported item supported is a file that is usable now and was not
  then: a new or edited source, or a looser policy. A subset test says exactly that.
- **Why old records are read against the notes:** the 120 field records were made on 0.20.x against the notes
  alone, all usable under the default policy of the time. When the notes still give that signature, the record
  stands for them. Without this, the fix would have left the field state as it was.
- **Why extracted claims stay queued when nothing is usable:** a grounder can still reject a span that does not
  state its relation. Only the items whose outcome is already fixed (a hypothesis cannot be grounded and may not
  be rejected for its level) are left out.
- **Rejected alternatives:**
  - (a) *Leave out every item when nothing is usable.* It would skip the rejections a grounder can still make.
  - (b) *Use a formula's `alttext` (LaTeX) instead of its rendering.* It reads worse in prose (`15$\times$`), and
    an excerpt should read like the page.
- **Accepted trade-offs:** subscripts and superscripts still flatten in plain text (`R^t=Et(Pt,Bt)`). A copy made
  on 0.22.0 keeps its doubled formulas until it is registered again.
- **Pinned in:** `tests/test_fix_no_usable_source.py` (13 tests).

## While no source is usable, the plan says so and the re-examination list is held back (2026-11-22)

- **Decision:**
  - `kg_ground_plan` sets `blocked` whenever no file is usable under the policy, with `items` and `hubs` possibly
    0, instead of only when it left something out.
  - The facade's `kg_context` (`_hold_reexamination`) empties `advisory.reexaminable_verdicts` while no file is
    usable and adds `advisory.reexaminable_held: {total, reason: "no-usable-source", required_level, hint}`. The
    projector's stored flags are untouched, so they return as soon as a file counts again.
  - `/burgess:kg-ground` Stage 0c reports a held list and re-checks none of it.
- **Field pass it answers** (Windows, 2026-11-22, session f79656a4, on 0.22.1). The project required level 1 and
  every source was level 4. The plan queued nothing, kept the 119 pins waiting, and the command launched no
  grounder. The user approved these fixes («Sí, prepárala»). Two gaps:
  - the plan read `blocked: null` although the command text says it is set whenever no source is usable;
  - `kg_context` listed 113 rejected items flagged when a preprint was registered under level 4. The agent
    rightly re-checked none of them, but they would have shown on every pass.
- **Why hold at read time instead of dropping the flags:** the flags were right when raised, since the preprint
  was usable then, and they are what makes the 113 items come back when the user lowers the level. The
  projector raises and keeps them without knowing the policy; the facade, which knows it, decides whether they
  can matter now.
- **Rejected alternatives:**
  - (a) *Raise re-examination flags only from usable changed text.* It would also stop flagging when a source
    is registered under a strict policy that is later loosened, since the text is then no longer "changed".
  - (b) *Drop the flags when the policy tightens.* The same loss on loosening.
- **Accepted trade-off:** while some source is usable, a flag raised by a source the policy now rejects still
  shows. That is the residual of not tracking which file raised each flag.
- **Pinned in:** `tests/test_fix_held_reexamination.py` (4 tests).

## A re-examination flag remembers the sources that raised it; the policy texts say what wakes a waiting item (2026-11-22)

- **Decision:**
  - `Projector._reexaminable_verdicts` records in each new flag `files`, the changed files whose words the item
    shares (for a span-backed edge, its own file). `_refilter_reexaminable` carries them.
  - `DerivedReader._read_reexaminable_advisory(con, usable)` holds back a flag whose `files` are all outside
    `usable`, and a flag without `files` (made before 0.22.3) only when `usable` is empty. It returns the shown list,
    its total and `{total, reason}` for what it held. `kg_context` takes `usable` from the facade, which knows the
    policy, and the facade adds `required_level` and a hint. The read-only hook passes nothing and filters nothing.
  - The texts that still said any policy change wakes the waiting items now state the 0.22.1 rule: the
    `kg_source_policy` and `kg_source_add` descriptions, `/burgess:kg-sources` (with a rule never to say otherwise),
    `tools.md`, COMMANDS, README and ARCHITECTURE.
- **Field test it answers** (Windows, 2026-11-22, session 976557d4, on 0.22.2, phase 1 of my test plan). The
  project was left at `required_level` 2 with the Síntesis note at level 2. A read-only check over a fresh copy of
  the Windows index showed two things. The 119 pins still waited, correctly. But the 113 legacy flags, raised by the
  level-4 preprint, were listed again because one note counted, so the next pass would have re-checked them
  against that note for nothing. The session also told the user the policy change would bring back the 119: it was
  repeating the stale tool description. The user approved the fixes («Sí, prepárala»).
- **Why per-flag provenance and not a policy-aware raise:** raising flags only from usable text would lose the
  re-check when a source registered under a strict policy is later accepted, since its text is then no longer
  "changed". Recording the files and deciding at read time keeps the flag for the day its source counts.
- **Accepted trade-off:** the field's 113 flags are legacy, with no `files`, so under level 2 they still show. The
  practical answer there is to restore the earlier policy. A one-off migration would need the changed text of that
  day, which the derived layer no longer has.
- **Pinned in:** `tests/test_fix_reexamination_provenance.py` (6 tests). `test_fix_held_reexamination.py` and
  `test_fix_reexaminable_own_file.py` follow the new flag shape and rule.

## A re-examination is answered by the item's next verdict, and the grounders do it with the text that raised it (2026-11-22)

- **Decision:**
  - A flag stores `audit_mark`, the grounding audit log's size in bytes when it was raised
    (`Projector._reexaminable_verdicts(mark=)`). `_refilter_reexaminable` drops a flag when the log holds a record
    for its item beyond that mark (`groundaudit.read_audit_index`, `AuditIndex.judged_since`), whatever the
    verdict. A flag stored before 0.22.4 gets the mark of the first record after the previous projection wrote
    the index: the new meta `projected_at`, or the index file's mtime on an older index
    (`Projector._index_written_at`). The mark is never shown: the advisory's entries keep their shape.
  - A fresh flag for an item already flagged merges its `files` into the carried flag and keeps the earlier
    mark. Through 0.22.3 the fresh flag was dropped.
  - `kg_ground_plan` queues every open flag on a `rejected` item, after everything new, as `{id, kind,
    reexamine: true}`, counted in `queue.reexaminable`. Held flags are counted in `queue.reexaminable_held`.
    `failed` items are not queued. The plan reads the stored flags and the audit log (`_open_reexaminations`) and
    still never projects, so the progress probe drops an item a grounder has just judged.
  - `kg_ground_item` adds `reexamine: {reason, files, context}` (`_reexamine_view`). `context` is
    `_ranked_context` restricted to the flag's usable files, or over every usable source for a flag that names
    none. It is `null` for a span-file flag, whose own `context` is the changed file.
  - A node or span-less edge is flagged only where a paragraph of a changed file shares two of the words of
    what it claims (`Projector._claim_words`: `groundplan.node_terms` of its label and body, or of its ends'
    labels and span, without digits; `_bearing_files`: `groundplan.rank_units` over `text_units`), the rule its
    grounder's context is ranked by. Through 0.22.3 one shared `_content_terms` word anywhere in the changed text
    sufficed, and the terms included the edge notes and the node's verdict paragraphs.
  - `PROJECTION_RULES` goes to "5", so the first read rebuilds the index. The rebuild re-tests every flag
    stored without a mark, once (`_retest_before_0_22_4`, also run by the plan on a not yet rebuilt index). A
    0.22.3 flag is tested against the files it names. An older flag is tested against the files whose
    modification time is after its item's last audit record (`SourceSet.file_times`). Each is kept with the
    files that bear on it, or dropped. A flag no file can be found for is kept as it was.
  - `/burgess:kg-ground` Stage 0 reads `kg_context` first, which projects, so a source registered since the
    last pass flags its items before the plan is read; Stages 0b and 0c read that advisory.
  - `/burgess:kg-ground` Stage 0c only reports: the counts, the held part with its hint, and the failed items.
  - The grounder contract stamps a verdict on every re-examined item, rejected again included, with a note
    naming what it re-read. It never records one as unsupported.
- **Field review it answers** (Windows, 2026-11-22, session 7de5e817, on 0.22.3, phase 2 of my test plan):
  - The user moved the policy to `required_level` 4, so all 10 sources count: 119 pins queued, and 113 flags
    listed (105 span-less generated edges and 8 nodes, all `rejected`, none with `files`).
  - Reproduced in a temp rig: a flagged item re-stamped `rejected` stayed flagged on every later projection,
    because `_refilter_reexaminable` dropped a flag only when the item left `{failed, rejected}`.
  - With `_REEXAMINABLE_CAP` 50 and a stable order, the same 50 would have come back every pass, and the other
    63 would never have shown.
  - Stage 0c told the orchestrator to re-verdict via `kg_ground`, which the command neither allows nor does. The
    orchestrator also reads the user's memory notes, which 0.13.4 kept from the grounders.
  - `kg_ground_item` gave a span-less proposal its `shared_context`, where its ends' spans lie. That is the
    notes, which it had already been judged against. A preprint registered without `build` holds no span, so
    a re-check would never have shown the grounder the text that flagged the item.
  - The user approved the fix («Sí, prepárala»).
  - A field check over a copy of the project with the first draft then showed the preprint in the re-check
    context of only 10 of the 113. The flags came from single words, mostly English words of the grounders'
    own verdict notes ("source" 50, "neither" 35, "context", "untested"). The claims' own words left 77, nearly
    all through "meta" or "llm" alone, and a paragraph sharing two of them left 10, the same 10 whose context
    showed the preprint; leaving numbers out (one matched only "11" and "14") left 8. So the raise rule changed
    in the same release: a flag the grounder would get no new
    passage for costs a re-check that cannot change anything, and with an English paper per phase-3 source it
    would have come back for most of the graph each time.
- **Why the audit log and not a timestamp or a canon fingerprint:**
  - The log is append-only, so a byte offset orders a projection and a verdict exactly. Their timestamps are
    to the second, and in one second a test can reject an item, register a source and project.
  - A same-state re-verdict keeps `verdict_at` by design (0.10.2, the hub-attack memory reads it), so `verdict_at`
    cannot tell a re-confirmation.
  - A fingerprint of the notes would also move for edits that are not verdicts, and would not move for a
    verdict given with no note.
- **Why the plan and not Stage 0c:** the command never calls `kg_ground` (its invariant, and its `allowed-tools`).
  The grounders judge without the user's memory (0.13.4), in parallel, in batches, and with the same contract as
  every other item. Stage 0b already routes stale verdicts to a grounder for the same reason.
- **Accepted trade-offs:**
  - Words, not meaning: a source in another language than the graph's reaches only the items it shares words
    with. On the field graph the English preprint has a passage about 8 rejected items and 11 of the 119 pins.
    The grounder could not judge the others against it either: it reads what the ranking gives it.
  - An older flag is re-tested by file times. A file copied with an old time is never a candidate, and a flag
    raised by it alone is kept as it was.
  - A flag stored before 0.22.4 counts only verdicts recorded after the index was last written, so a re-check made
    between its raise and that write is not counted, and the item is judged once more.
  - A verdict stamped between a source change and the projection that notices it does not answer the fresh flag
    that projection raises. That costs one extra re-check, never a lost one.
  - A `failed` flag stays listed, unqueued, until the clash rules (planned with `obsolete` and dates) decide what
    a new source may do to a refutation.
- **Pinned in:** `tests/test_fix_reexamination_answered.py` (25 tests). `tests/test_kg_ground_plan.py` gains the
  two queue counts. `test_fix_ground_node_evidence.py` and `test_fix_held_reexamination.py` follow the reworded
  command and grounder texts, and `test_review_r8.py`'s body-terms test names two body words, as the paragraph
  rule asks.

## Each project has its own notes and its own engine data (2026-11-22)

- **Decision:**
  - `evidence.Policy.notes_path` holds a project's own notes. It is `""` for the plugin's `source_path`, `none` for
    no notes, or else a path relative to the project, inside it.
    - `parse_notes_path` refuses `notes-path-outside-project`, `notes-path-reserved` (`canon`, `evidence`, `.kg`,
      `.kg-data`, `.git`, `.claude`) and `notes-path-not-found`; a glob may match nothing yet.
    - `load_policy` checks a stored value the same way (`notes_path_problem`). A bad one is reported in `problems`
      and ignored, and the plugin's `source_path` applies.
    - `fingerprint()` includes the path only when it is set, so a 0.22 policy keeps its signature.
  - `_SourceResolver.notes_path()` is the one place the notes path is read: by `resolve()` and `verify()` (and their
    memo signatures), the facade's `notes_path` property, the build plan's declared files, the configured-source
    check and the materialization advisory.
    - The PreToolUse hook builds the same resolver, so it reads the same notes.
    - `_source_info` reports `notes_from` (`project`, `none` or `global`) and `builds_from`.
    - `kg_source_policy(notes_path=)` sets the path. Its `policy`, and `kg_source_list`'s, carry `notes_path`,
      `notes_from` and `notes_folder`.
  - `envconfig.resolve_project_data_dir` gives each project `<KG_DATA>/projects/<project_key>`, where the key is the
    folder name folded to `[a-z0-9-]`, then 12 hex of the sha256 of the normalized absolute path.
    - The server (`build_engine_from_env`), the hook and the LightRAG arm use it.
    - An explicit `--data`, or the `<project>/.kg-data` fallback, is taken as given.
    - `server.log` stays at the root, where the Node launcher writes it too.
  - `adopt_shared_derived` copies, once and file by file, what the shared `<KG_DATA>/derived/` holds for the
    project:
    - the index and `graph.json` when the index's notes and the canon agree by Jaccard ≥ 0.9;
    - `generations.json` when half or more of its tracked ids are canon nodes.
    - It never overwrites, never moves, and fails silent.
  - `kg_engine.paths` (`graph`, `data-dir`, `source`) gives command text the project's own paths. `source` prints the
    notes path when the build reads the notes alone; otherwise it refreshes a copy of the content files in
    `<project data>/content/` and prints that folder. `/burgess:kg-eval` and `/burgess:kg-experiment` set `GRAPH` and
    `SRC` with it.
- **What it answers** (2026-11-22, after phase 3 of the field test):
  - The user asked why `source_path` is global when each project may follow its own policy. In `prueba-burgess-n1`
    the 9 notes of `prueba-burgess` were listed as that project's notes.
  - The Claude Code docs (checked by the claude-code-guide agent) settle it. `pluginConfigs` is "User or managed",
    and "Claude Code ignores project and local entries because it substitutes these values into plugin hook, MCP,
    and LSP configurations, and a cloned repository must not be able to supply them". `claude plugin configure` has
    no scope flag. `${CLAUDE_PLUGIN_DATA}` is keyed by plugin id, not by project.
  - The user approved the change after phase 3 («Sí, después», then «Sí, empieza»).
- **Why the policy and not a settings file:**
  - The project already owns its policy (`<project>/evidence/policy.json`).
  - The documented per-project channel is `${CLAUDE_PROJECT_DIR}`, which the engine has as `KG_PROJECT_DIR`.
  - Keeping the path inside the project carries over Claude Code's reason to ignore project values: a cloned
    repository cannot make the engine read, extract and quote files outside itself.
- **Why copy file by file:**
  - The field's shared folder held `n1`'s index (it was the last project opened) and `prueba-burgess`'s generation
    ledger (written on 11-15), so no single owner exists for that folder.
  - Checked on copies of the field data: `n1` took `index.sqlite` and `graph.json`; `prueba-burgess` took
    `generations.json`; a second run copied nothing.
- **Accepted trade-offs:**
  - Re-examination flags in a shared index that belonged to another project are lost for this one. That is moot in
    the field: none was open.
  - `server.log` stays shared, as before.
  - The project key changes if the folder is moved or renamed, which costs one rebuild.
- **Pinned in:** `tests/test_fix_per_project_sources.py`. `test_fix_field_eval_experiment.py`,
  `test_fix_experiment_measurement.py` and `test_fix_eval_log_and_annotator.py` follow the `kg_engine.paths` lines.

## Bot checks refused, the online date, a repeated edge keeps its passage, page furniture left out (2026-11-23)

- **Decision:**
  - `evidence.blocked_page` refuses an HTML copy as `fetch-blocked`, before the preview, when:
    - its title is one of `_CHALLENGE_TITLES`; or
    - it is under 2000 characters and holds one of `_CHALLENGE_PHRASES`.
    - Its hint is the way around: save the page from a browser and register the file. Markdown and text files
      are never checked.
  - `_DATE_KEYS` puts `citation_online_date` first. `page_published` never returns a future date when the page
    declares an earlier one.
  - `KGEngine._keep_first_passages` runs in `kg_write` before the canon write. An incoming edge the canon holds
    unverified, whose stored span still verifies, takes the stored span, file, confidence, authorship and notes.
    - The incoming passage becomes an `also stated:` segment (`evidence.also_segment`, `ALSO_MAX` 8).
    - `_span_groups`, and with it every coverage reading, counts those segments.
    - `kg_write` reports the edges in `also_stated`.
    - A passage is its words and its file: the same sentence quoted from another file is another passage, so
      both files' sections count.
    - The same passage written again updates the edge as through 0.23.0, its confidence and notes included, and
      the kept segments are carried over. That is an extractor restating its own edge, not a second section.
    - A stored span that no longer verifies is replaced, which re-anchors the edge, and the kept segments that
      still verify are carried over. An incoming edge without a span never blanks a stored one.
  - `HTML_EXTRACTOR` "html-text/3":
    - a page with a `<main>` or `role="main"` gives only that element's text;
    - `aside` joins `_SKIP`;
    - an element whose role is navigation, complementary, contentinfo, search or banner is left out, and so is one
      whose class or id matches `_FURNITURE_RE` (recommend…, related-articles/content/subjects…, share, social…,
      breadcrumbs, cookies, adverts, sponsors, promos, newsletter, comments, subscribe).
    - Layout words such as `sidebar` are excluded, because Springer's article container is `eds-l-with-sidebar`.
  - `buildplan.skip_reason` marks a section `reference-list`, `back-matter` (which matches the Copilot article's
    "Data Availibility Statement" too) or `empty` (no letter or digit below its heading). `kg_build_plan` leaves
    such a section out of `sections_uncovered`, counts it in `sections_skipped`, and plans it anyway under `--all`
    (`BuildArguments.every`).
  - `adopt_shared_derived` opens the legacy index read-only and immutable, unless its write-ahead log holds data.
  - `Projector._retest_before_0_22_4` also tests a file whose modification time falls in the verdict's own
    second, since both clocks are to the second.
    - Such a file can keep a flag, by bearing on its item, but never drops one. A flag is dropped only when
      a file changed after the verdict for certain and none bears on it.
    - `>` had left that file out, so with another file changed later, a flag from before 0.22.3 was tested
      against that one alone and dropped.
    - A plain `>=`, tried first, dropped instead the flag of `test_fix_reexaminable_own_file.py`'s upgrade
      test, whose files share the verdict's second. A tie must not count as a change.
- **What it answers:** phase 3 of the field test (2026-11-22, `prueba-burgess-n1`), and the follow-up check of
  0.23.0.
  - Springer served the Windows engine a 210-character "Client Challenge" for three articles, previewed as
    `ok: true`. From WSL the same URLs gave the full article.
  - The proposed date was the issue's, 2027-04.
  - Copilot §35 lost its coverage to §53's re-write of the same edge. That was noted in the field since 2026-11-07.
  - Of the build's 137 sections, 95 were recorded edgeless.
  - 0.23.0's migration left `-shm`/`-wal` files in the shared folder.
  - The CI run on `main` after the 0.23.0 merge failed on macOS in
    `test_fix_reexamination_answered.py::test_a_0_22_3_flag_is_retested_against_the_files_it_names`. Locally
    it failed 1 run in 20. A replay that logged each step showed the clock tie above. With the fix, both tests
    pass 40 runs out of 40. A test with pinned clocks covers the tie both ways, and fails on `>` and on a
    plain `>=`.
  - The user approved the patch («Sí, prepárala»).
- **Measured on the field's two articles:**
  - `html-text/3` drops 20 sections (48 → 39, 89 → 78), among them the 13 000-character "Registered Reports".
  - The skip rule leaves out 37 more, so 80 of the 137 sections get extracted.
  - Applied to the copies already registered, the rule leaves out 43.
  - None of the 41 sections that held edges matches.
  - All 76 canon spans that quote the two copies are still in the `html-text/3` text.
- **Why empty, not short:** the first draft also left out a section under 60 characters. The full suite then
  failed on its notes fixtures: `## Argumento` holds one sentence of 49 characters, and an edge quotes it. On the
  field's articles, the 16 sections between 1 and 59 characters were all page furniture: "Navigation", the
  "Similar content" cards ("Article 21 August 2026"), "Associated Content". `html-text/3` no longer copies them,
  so leaving out short sections bought nothing on new copies and risked a one-line note. The user's notes have no
  section under 60 characters, so nothing measured changes there.
- **Why the build plan, not the copy, for references and back matter:** a copy stays the page's own text, so a
  passage in a bibliography can still be verified. Leaving those sections out of a build only spares the extractor
  runs, and `--all` undoes it.
- **Accepted trade-offs:**
  - The furniture names are heuristics. A site that names its article body with one of them would lose text, and
    `--all` cannot bring a left-out block back into a copy. The way back is a re-registration from a saved page.
  - Springer puts the article header before `<main>`: the `<h1>`, "Published: 03 November 2026", the volume and
    "Cite this article". `html-text/3` leaves it out. The record keeps the title and the date, the copy still
    opens with the title, and none of the 76 spans was in it.
  - Under `back-matter`, an article's Funding and competing-interest sections are no longer read by an extractor.
    In phase 3 they told the agent that the interest mark was not needed; that check now rests on the preview.
- **Pinned in:** `tests/test_fix_source_intake_and_build_noise.py`.

## Burgess suggests sources: /burgess:kg-sources find (2026-11-23)

- **Decision:**
  - `/burgess:kg-sources find [focus] [n]` suggests outside sources for the items waiting for one, the items a
    grounder recorded with `kg_record_unsupported` that still wait.
  - **Who does what.** The language layer searches and proposes. The engine lists, searches the catalogue, reads
    pages and logs. The user picks, and the existing `add` registers.
  - **Four tools (40 → 44):**
    - `kg_source_find` (read-only): the items, with `text`, `terms`, `looked_for` (the grounder's note, now kept by
      `groundplan.unsupported_records`) and the searches already logged. The never-searched come first.
    - `kg_source_search`: OpenAlex through the engine (`evidence.openalex_search`). One GET with `search`,
      `per_page` and `select`, the generic User-Agent, no key and no contact address. A query that the §1.9 scrub
      would change, or that holds a placeholder, is refused before anything is sent (`query-refused`).
    - `kg_source_probe`: the engine fetches a candidate, refuses a bot check, and returns the page's metadata, a
      `level_hint` and the paragraphs that share the most of the scout's terms (`evidence.best_passages`, the
      0.20.2 ranking, the paragraph alone, at most 900 characters).
    - `kg_source_record_search`: the scout's web searches (empty ones too) and its proposals.
  - **Every search, read and proposal goes to `.kg-source-searches.jsonl`**: engine state beside the canon,
    gitignored, git-excluded, and read fail-open.
  - **The scout.** A new `kg-scout` agent has WebSearch and the three engine tools, and no WebFetch, Bash or Read.
    It runs on `model: sonnet` with `omitClaudeMd: true`.
    - It writes one or two queries for and one against, in English when the item is in Spanish.
    - It proposes up to three candidates per item, each with a level, a role, a stance and a verbatim passage.
    - It never registers and never judges.
  - **Registration.** `kg_source_add(for_items=)` records `found_for`, plus the page's `doi`. The engine adds the
    items the ledger ties to the page: a probe or proposal by URL or DOI, a catalogue result by DOI or URL, or a
    proposal by its exact title. That way a page saved from a browser still finds its item.
  - **The wake rule narrows.** `groundplan.waits_for_sources(wakes=)` lets a usable file an item was not judged
    against wake it only when the file was found for it or bears on it (`KGEngine._new_source_wakes`: `found_for`,
    or the 0.22.4 paragraph rule). The plan and `kg_source_find` share it.
  - **Level hints** (`evidence.level_hint`): a journal or conference article (`conference-paper` included) 1, a
    standard 2, a book 3, a preprint, repository copy or thesis 4, a report or anything else none, and a retracted
    work none. A hint is a proposal the user confirms.
- **What it answers:**
  - The user's request of 2026-11-21 for Burgess to suggest sources. 0.21.0–0.23.1 shipped the registry, levels
    and policy, and the user said the registry alone was not what they asked for.
  - The design was proposed on 2026-11-21 and again on 2026-11-23, and approved («Sí, adelante»).
- **Checked:**
  - On 2026-11-23, from WSL, WebSearch works for this account in Spain despite the "US-only" in its description.
  - The engine's fetch reaches OpenAlex, Crossref and arXiv without a key.
  - OpenAlex without a key shares a $0.10 daily budget per IP at $0.001 a search, so about 100 searches. Its notice
    asks agents to send the user's email for a key; the engine never does.
  - A smoke run on a copy of `prueba-burgess`:
    - `kg_source_find` lists 119 waiting items in 0.1 s;
    - a search returns 5 works in 0.5 s;
    - a probe of an ICLR page returns its passages in 0.9 s;
    - the ledger holds both.
    - It showed OpenAlex typing an ICLR paper `conference-paper`, which the level hint first missed.
- **Why the scout starts without CLAUDE.md and memory:** its queries leave the machine, and the user's
  instructions and memory notes hold names, paths and project names that a query must never carry. The Windows
  memory notes have also carried stale rules into subagents before.
  `tests/test_fix_grounders_without_memory.py` and `tests/test_fix_blind_memory.py` record the decision.
- **Why OpenAlex in the engine and WebSearch in the scout:**
  - The catalogue's facts (venue type, work type, DOI, retraction) are what a level is proposed from, and a
    deterministic call can be logged and refused.
  - Institutional and editorial sources (levels 2–3) are not in the catalogue, so the web search covers them.
  - Pages are read only by the engine, so a passage is the page's own text.
- **Accepted trade-offs:**
  - A source in another language than an item shares no words with it. A source added by hand, without `find`,
    does not wake such an item, and a focus reaches it.
  - Through 0.23.1 every new usable file woke every waiting item, at about 3.75 USD per pass in the field.
  - The OpenAlex budget is shared by the network. A spent budget (`search-budget`) leaves the web search.
  - WebSearch on the user's Windows install is not yet checked; the field test will show it.
- **Pinned in:** `tests/test_feat_source_find.py`.

## The find focus reads the item's text (2026-11-23)

- **Decision:** `kg_source_find` matches its focus against what the item claims (`_claim_text`: a node's label
  and body without lineage lines, an edge's ends, relation and span) and its id (an edge's: its two ends' ids),
  with `groundplan.focus_matches`: every focus word, singular or plural, accents ignored. The grounding focus
  (`kg_ground_plan`) keeps id and label.
- **What it answers:** the first field run of `find` (2026-11-23, `prueba-burgess`, 119 waiting pins).
  - `find compresión 3` returned nothing. Through 0.24.0 the focus read the id and the label only.
  - A pin's id is `idea-<brief>-<candidate>`, and its label is its first 80 characters, cut. The one pin about
    compression (`idea-atasco-fabrica-agentes-c1a`) had the label "…vigilar la ratio de compresió...".
  - The agent fell back to no focus and offered three replies; no scout ran.
  - The user approved the fix («Sí, prepárala»).
- **Why not the ground focus too:** it names nodes, and a grounding pass takes every edge touching a named node.
  A word in a node's body would widen it beyond what the user named.
- **Pinned in:** `tests/test_fix_find_focus_reads_text.py`.

## A scout owes every item three searches (2026-11-23)

- **Decision:**
  - `kg_source_record_search` answers `missing`: the required searches (`KGEngine.REQUIRED_SEARCHES`: OpenAlex
    for, OpenAlex against, web for) the ledger does not hold for the item in the last two hours
    (`FIND_RUN_WINDOW_S`).
    - A logged search counts whatever it found, and a failed catalogue search counts as tried.
    - A `search-budget` refusal in the window moves the two catalogue searches to the web.
  - The scout runs what is missing and records it before it reports.
  - The scout's prompt makes the three searches unconditional, per item, and tells it to read a work's own page
    (arXiv or DOI) when it saw the work only through another page.
  - The command reports an item whose scout still lacks a search.
- **What it answers:**
  - The field run of 2026-11-23 (`find`, six waiting ideas of `prueba-burgess`, on 0.24.1). Two scouts with three
    items each ran 9 searches: no `against` search for any item, and a web search for two. The scout given one item
    an hour earlier had run all three.
  - The first run left DeLoop, a paper on agents stuck in loops, unread: the scout had seen it only through a
    summary.
  - The user approved the fix («Sí, prepárala»).
- **Why the engine checks and not only the prompt:** the prompt already asked for the against search, and the
  scouts skipped it when they had more items. The ledger knows what was searched, so the answer to the record is a
  check the scout cannot overlook. The window keeps a search run earlier the same day valid.
- **Pinned in:** `tests/test_fix_scout_runs_every_search.py`.

## A rate limit is not a spent budget (2026-11-23)

- **Decision:** every catalogue request goes through `evidence._openalex_get`.
  - It sends one request at a time (a module lock), at least `OPENALEX_SPACING_S` (1.1 s) after the last one.
  - After an HTTP 429 it waits `Retry-After` (or 2 s, at most 10 s) and retries once.
  - It raises `search-budget` only on HTTP 402, or on a 429 whose `X-RateLimit-Remaining-USD` is 0.
  - A 429 again after the pause is `search-rate-limited`, with the budget left in its detail.
  - `openalex_search` returns the works and `openalex_budget(headers)` (`remaining_usd`, `limit_usd`, `reset_s`).
    `kg_source_search` reports it as `budget`, its ledger record keeps `budget_left_usd`, and `kg_source_find`
    reports the last of the day as `openalex_budget_left_usd`.
  - `_missing_searches` owes a failed catalogue stance to the web with the same stance. Through 0.24.2 a failed
    search counted as tried.
  - The scout's prompt and the command say the daily budget ran out only on `search-budget`.
- **What it answers:**
  - The field run of 2026-11-23 15:01 CET (`find 3`, `prueba-burgess`, on 0.24.2). Three of six catalogue
    searches drew HTTP 429 while others succeeded around them. 0.24.2 mapped 402, 403 and 429 to `search-budget`.
    The scout dropped the catalogue, and the report told the user the daily limit had run out.
  - A diagnostic request from the same network at 15:05 read `X-RateLimit-Remaining-USD: 0.084` of `0.1` (10
    credits a search, 1000 a day, 840 left).
  - The user approved the fix («Sí, prepárala»).
- **Why serialize in the engine:** the scouts call the tool in parallel, and one engine serves the whole session.
  A lock in the engine is the only place that sees every catalogue request.
- **Why owe a failed stance to the web:** the purpose of the three searches is that each item has a search for and
  against that actually ran. A failed catalogue search did not run.
- **Pinned in:** `tests/test_fix_openalex_rate_limit.py`.

## A new source wakes an item by three shared words (2026-11-23)

- **Decision:**
  - `KGEngine._new_source_wakes` passes `need=KGEngine.WAKE_WORDS` (3) to `Projector._bearing_files`, which now
    takes it.
  - `groundplan.rank_units(…, need=2)` gains the parameter, and its default keeps the 0.22.4 re-examination rule
    as it was.
  - An item with fewer words needs all of them.
  - `found_for` still wakes an item whatever its words.
- **What it answers:** the field's first full loop (2026-11-23, `prueba-burgess`, on 0.24.3).
  - `/burgess:kg-sources find` found an English design-pattern page for the Spanish idea c1l. The user
    registered it (`found_for: [c1l]`).
  - The next `/burgess:kg-ground` queued 16 ideas. c1l woke by `found_for`; its own Spanish words share no
    paragraph with the page. 15 others woke by the paragraph rule, each on exactly two words: cognates or generic
    words (agentes/agents, planes/plan, tests, local, token, final, persona, detector).
  - The grounders recorded all 15 as unsupported again. c1l was grounded on the page's passage.
  - The user approved the fix («Sí, prepárala»).
- **Why three, and why only here:** a paragraph that states an item's claim in its own language shares many of
  its words, so three loses nothing measured. Two is met by chance across languages. The re-examination rule
  keeps two for now: it was not what this run tripped on, and a change there would move flags the user has
  already reviewed.
- **Pinned in:** `tests/test_fix_wake_needs_three_words.py`.

## A source flags a rejection for review by three shared words (2026-11-23)

- **Decision:**
  - `Projector._reexaminable_verdicts` passes `need=projector.BEARING_WORDS` (3) to `_bearing_files` for a node and
    a span-less edge. `KGEngine.WAKE_WORDS` is now `BEARING_WORDS`, so one constant holds both bars.
  - `groundplan.rank_units` counts words, not spellings. `word_groups` makes terms that share a form
    (`buildplan._forms`) one word, and the bar is that many words (`need = min(need, words)`). The score is
    unchanged, so passages rank as before.
  - `kg_source_add` diffs `_waiting_items()` before and after it writes a copy. It reports `comes_back` (each
    item's `why`: `found_for`, `words` with the shared words, `no-words`, `other`; at most 30), `comes_back_total`
    and `still_waiting`. The command names each item with that reason and no other.
  - `PROJECTION_RULES` stays "5". A flag stored before 0.24.5 stays until a verdict answers it, and only new flags
    meet the new bar. The legacy re-test of pre-0.22.4 flags keeps the default of two.
- **What it answers:** the field test of 0.24.4 (2026-11-23, `prueba-burgess`).
  - The user registered the arXiv abstract of Sentry, found for c1j by the fourth `find` run (the ledger match
    gave `found_for`).
  - The plan queued c1j alone, then 4 rejected edges flagged on two generic words each (llm with tests or
    reward). The grounder rejected all four again.
  - The engine's own `_reexaminable_verdicts` on a copy reproduces exactly those 4. For the two «Instant software
    factories» copies it gives the 8 that were re-stamped rejected on 2026-11-22. At three words: 0 and 0.
  - Counting spellings: under the two-word rule, 3 of the 7 extra pins Sentry would have woken shared one word
    in two spellings (demo/demos, tests/test, versiones/version).
  - The registering agent said c1j came back "because it shares words with the source". `found_for` had
    brought it back.
  - The user approved the fix («Sí, prepárala»).
- **Why three for the review too:** the grounding audit log (581 records) holds 4 verdicts that went from
  rejected to grounded, and each one was asked for by hand: the 2026-11-09 re-judge and the `--reexamine cliche`
  of 2026-11-21. No automatic flag ever turned one around, while 28 re-checks confirmed a rejection. A paragraph
  that supports a rejected claim in its own language shares many of its words.
- **What is not explained:** on the same copy, the current code raises 9 flags when the H3 page is registered (8
  on two words, 1 on three), and four replays agree: fresh engines, one engine, parallel reads, the real
  `kg_source_add`. On the field the plan after that registration showed `reexaminable: 0`. Under the new bar it
  would raise 1.
- **Pinned in:** `tests/test_fix_reexamine_needs_three_words.py`.

## A grounder reaches another language, and a second grounder confirms what its own search found (2026-11-24)

- **Decision:**
  - `kg_ground_item` gives an item a registered usable source was found for (`found_for`) `search_context`: that
    source's sections ranked by the words of every search its scout logged for it (both stances), through
    `_ranked_context` with a `files` filter. The ranking stays the engine's; the words came from the scout before
    any judging.
  - `kg_ground_item(…, terms=…)` is the grounder's own request: at most `GROUND_TERMS_MAX` (8) content words,
    which answer `requested_context`. One per item while the item, the sources and the policy are unchanged
    (`_current_request`: `item_signature` + `_source_signature`). It is recorded in the new ledger
    `.kg-ground-requests.jsonl` (`canon.GROUND_REQUESTS`, git-excluded). A refusal records nothing.
  - `kg_ground` holds a `grounded` verdict that brings support on an item with a current request
    (`_hold_or_confirm`), after the support checks and before any state change. It writes only a `hold` record:
    the span, its file, the words, the first note, and byte marks of the audit log and of the unsupported ledger.
  - `kg_ground_plan` queues a held item only as `{id, kind, confirm: true}`, last, in batches of its own
    (`queue.confirm`).
  - The next grounded verdict with support is the confirmation (`confirmed: true`, a line in the notes or body).
    Another verdict, an unsupported record past the mark, or a change to the item answers the hold the other way.
  - `kg_ground_item` gives a held item `confirm` (the span, its section, the words) and refuses `terms` for it.
  - The grounder contract and `/burgess:kg-ground` say when to ask, how to report a hold, that a confirm batch
    goes to a new launch, and that the report lists these items apart.
- **What it answers:**
  - The user's question of 2026-11-24 (can English sources verify Spanish ideas?) and the analysis that
    followed. The verdict always crossed languages, since the grounder reads both. The passages it was shown did
    not, because the engine ranked them by the item's own spelling.
  - A missed paragraph is silent: the grounder records the item unsupported, and no field run would show it. So
    waiting for a field miss, which I had first advised, could never settle it.
  - The user approved safeguards 1, 2, 4 and 5 of the proposal («Sí, prepárala»):
    1. pre-recorded words;
    2. one capped, recorded request;
    3. (left out) section titles plus a related-work rule;
    4. a second grounder;
    5. the report.
- **Why not translate, and why not embeddings:**
  - A translated source is a paraphrase: the verbatim-span rule, the reason the engine refuses WebFetch,
    forbids citing it. Translating the idea risks changing the nuance under judgment.
  - Multilingual embeddings would bring geometry into the evidence a verdict rests on, which the design razor
    («embeddings measure dispersion, never truth») and the I3 firewall keep out. They would also add a model of
    hundreds of megabytes.
  - Letting the grounder choose the words keeps the language work in the language layer, and the engine
    deterministic.
- **What the safeguards cannot do:** the engine cannot tell one subagent from another, so the separation of the
  second grounder rests on `/burgess:kg-ground` (a new launch, a batch of its own) and on the grounder's contract.
  A grounder that broke both could confirm its own hold. The marks are byte offsets because ledger records are
  stamped to the second: in the first smoke run, a pin recorded unsupported in the very second of its hold read as
  answered.
- **Pinned in:** `tests/test_feat_grounder_search_terms.py`.

## A grounding judged again on request, and a pin's support withdrawn rather than rejected (2026-11-24)

- **Decision:**
  - The grounder contract gains **What grounds a node**. A passage grounds a node only when it states the
    mechanism AND what makes the node this claim (purpose, trigger, scope, object). Neighbouring claims do not
    ground: the mechanism for another purpose, without its trigger, a narrower or weaker version, one
    ingredient. A neighbouring claim leaves a pin unverified and recorded, a rejection for any other node, and
    never `failed`.
  - The contract also gains **A grounded node judged again**. The section is neutral: it names no field item
    (0.18.1: an example naming a pending field pair primed its verdict).
  - `kg_ground_plan(reexamine=True)` with a focus also queues the GROUNDED nodes a promotion grounded
    (`KGEngine._promoted`: a `grounding span:` paragraph or an unchecked citation) that the focus names. Never
    without a focus, so `--reexamine` alone keeps its 0.20.2 meaning.
  - `kg_ground_item` gives such a node `grounded_on`: its spans, each with the section around it, and its
    citations.
  - `kg_ground(verdict="unverified")` routes to `_withdraw_support`, for a grounded node with the `[diverge]`
    marker and a promotion's support, and with a note. It sets `unverified` and `hypothesized` and turns the
    support paragraphs into one `verdict (unverified): support withdrawn (0.24.7): <note> It rested on …`
    paragraph. It audits `grounded → unverified`, and records the pin unsupported through `_append_unsupported`,
    now shared with `kg_record_unsupported`.
  - Refusals: `withdraw-node-only`, `withdraw-needs-note`, `withdraw-not-allowed` (a cliché or a compression
    takes `rejected`).
- **What it answers:**
  - The 0.24.6 field test (2026-11-24). The grounder of c2c recorded it unsupported because the Banu paper
    states the quorum mechanism for another purpose.
  - Two pins, c1l (H3) and c1j (Sentry), had been grounded on passages each grounder noted fell short.
  - The user asked to look into judging them again («Sí, míralo»), then approved this design («Sí, prepárala»).
- **Why `unverified` and not `rejected`:**
  - The pin triage rule: a `[diverge]` pin without support waits for sources. A rejection is permanent
    negative memory, and in the brief it would bury a novelty the user pinned.
  - `obsolete` says the span left its source, which is not the case here.
  - The withdrawal is the one tool path that writes `unverified`, and only from `grounded`. The reconciler's
    guard against erasing a failure by a move to `unverified` (`_restore_erased_negative`) is untouched, and its
    comment says so.
- **Why on request only:** a grounding the user has seen and relied on should not change under them. A pass that
  judged every grounding again would also spend a grounder per grounded node on every run.
- **Pinned in:** `tests/test_feat_withdraw_support.py`.

## A source found against an idea leads to an attack, and a refutation is confirmed by a second grounder (2026-11-24)

- **Decision:**
  - The evidence record gains `found_against`. `KGEngine._found_items` splits the ledger's matches by proposal
    stance: an item whose matching proposals all say `refutes` was found against, and any other match was found
    for. `kg_source_add(against_items=…)` names them by hand, the caller's lists win over the ledger, and one id in
    both is refused (`item-for-and-against`). The answer gives `found_against` and, when the copy is usable,
    `to_attack`. An item found against is not woken to be grounded on the copy.
  - `kg_ground_plan` gains `pin_attacks` (`_pin_attacks`): live `[diverge]` pins with a usable source found
    against them that no attack has answered. An attack record (`groundplan.attack_record(…, sources)`) and a
    held refutation store the sources they answered, so a later source is a new one whatever the clock says. The
    first version compared timestamps, and a test registering a source in the second of the last attack missed
    it.
  - `kg_ground_item` gives `against_context`: `_search_context(…, against=True)` over the sources found against.
  - `kg_ground(failed)` on a `[diverge]` pin is always held (`_hold_refutation`, `verdict: "failed"`). The
    second grounder's `failed` confirms it; an unsupported record or a new grounding declines it. Held verdicts
    are queued to be confirmed whatever the item's state, so a grounded pin's held refutation is queued too.
  - The adversarial contract gains "Attacking an idea", with what refutes an idea and Output A or
    `kg_record_attack`. The grounder contract gains the confirmation of a refutation. The scout contract says
    `refutes` now sends the item to be attacked. `/burgess:kg-ground` gives the ideas to Stage 2 and their
    confirmations to a later wave.
- **What it answers:**
  - The user asked whether the loop works end to end (2026-11-24). It did for support, but a source found
    against an idea led nowhere. The scout of 2026-11-23 had proposed Boettiger & Hastings 2012 (level 1) with
    the stance `refutes` for c2e. This entry first named it «Brett et al. 2012», as that scout had: a wrong
    attribution, corrected with 0.25.1 (below).
  - The engine already accepted `failed` on a pin (`_claim_side` of a span-less hypothesis is `none`, so the
    level veto lets a usable source fail it). What was missing was the routing and the rules.
  - The user approved the five parts («Sí, prepárala»).
- **Why held, always:** a refutation is permanent negative memory, and in the divergence brief it seals the
  idea. Only an adversarial grounder, which goes looking for a refutation, gives one. A second grounder who did
  not choose the attack is the same safeguard 0.24.6 gave support found by a grounder's own search.
- **Fusion tests touched:** `tests/fusion/test_materialization.py` and `test_fix_ground_unsupported_pins.py`
  failed a pin in one call. They now hold and confirm it (`_refute`), and what they check (the fate flowing back
  to the brief, a verdicted pin not recordable) is unchanged.
- **Pinned in:** `tests/test_feat_attack_ideas.py`.
- **Also settled the same day:** the user kept the strict reading of what grounds a node (0.24.7). A pin is
  grounded only when a source states the whole idea; partial support stays in the withdrawal or unsupported
  notes.

## The CI gate checks every test leg, not the matrix's summary (2026-11-24)

- **Decision:** `ci-complete` keeps its first step, which fails on a `failure`, `cancelled` or `skipped` in
  `needs.*.result`, and gains a second.
  - The second step lists the run's jobs, the latest attempt of each (`gh api
    repos/<repo>/actions/runs/<run_id>/jobs?filter=latest`), and fails unless every job named `engine tests…`
    concluded `success`. It also fails when it finds no such job, so renaming the test job cannot open the gate,
    and when the API call fails (the default `bash -eo pipefail`).
  - The job gains `permissions: actions: read`, at job level, since the workflow's `contents: read` leaves every
    other scope at none.
  - It is a CI-only change, with no version bump and no release.
- **What it answers:** PR #153 (0.25.0, 2026-11-24).
  - The macOS leg never ran: «The job was not acquired by Runner of type hosted even after multiple attempts»,
    while GitHub reported limited macOS arm64 capacity. It was cancelled after 15 minutes, with no steps.
  - `ci-complete`'s first step was skipped, so the matrix's summary result read as success. The gate passed, and
    auto-merge merged the PR at 18:01 CET.
  - The user reported «un check cancelado en la CI», then approved the fix («Sí, prepáralo»).
- **Checked against real runs:** by hand, the same logic fails the #153 run (1 of 6 legs cancelled) and passes the
  0.24.7 run (6 of 6). A re-run of only the failed leg counts its latest attempt, so the gate opens once it passes.
- **A passing API error is asked again.**
  - On this fix's own PR (#154), a re-run of the gate met `gh: Server Error (HTTP 502)`. The step failed closed,
    as designed, and blocked the merge on GitHub's hiccup.
  - The step now asks up to five times (10, 20, 30 and 40 s apart, within the job's 5 minutes) before failing.
  - The same PR also showed two re-run habits of GitHub. «Re-run failed jobs» skips a leg that timed out, which
    counts as cancelled, not failed. A leg cut by its timeout does show in `needs.*.result`; one that never got a
    runner does not.
- **Addendum (2026-11-25): a leg that has just ended is asked again.**
  - What happened on PR #156 (0.25.2, run 45624514550): the Windows leg ended at 13:43:12Z and `ci-complete`
    started at 13:43:14Z. Its query at 13:43:16Z still gave that leg no conclusion, so the step read `none`. All six
    legs were green, and the gate shut.
  - Why: `needs` releases the gate the moment the last leg ends, before the jobs API records that leg's
    conclusion. The retry above covered API errors only.
  - The change: the step asks again, within the same five answers and spacing, while a leg has no conclusion and
    none has failed. A failed or cancelled leg ends the wait at once. A leg still without a conclusion on the fifth
    answer counts as not succeeded, so the gate still fails closed.
  - Unblocking #156 took a re-run by the user, since this WSL token cannot re-run workflows (403). The user re-ran
    all jobs (eleven minutes); «Re-run failed jobs» would have re-run `ci-complete` alone. On that second attempt
    the gate again started two seconds after the Windows leg ended (14:42:15Z, 14:42:17Z) and read its conclusion:
    the race does not strike every time.
- **Pinned in:** `tests/test_fix_ci_gate_every_leg.py`. It checks the step's configuration, and runs its script as
  GitHub does (`bash -eo pipefail`, with a stub `gh` and `sleep`) for these cases:
  - a passing leg set, a cancelled leg, a failed leg, a leg with no conclusion, and none;
  - an API that fails twice and then answers;
  - an API that never answers;
  - since the addendum: a leg with no conclusion twice and then green, one that never concludes, a failed leg
    beside a pending one (no wait), and a server error followed by a pending leg and then green.

## Who wrote a work comes from the page or the catalogue, never from memory (2026-11-24)

- **Decision:**
  - The page parser keeps every name of each author tag (`_Extractor.authors`). `evidence.html_page` returns the
    first family the page uses: every `citation_author`, else `dc.creator` / `dcterms.creator`, else the generic
    `author`. `meta` still keeps the first value of each tag, and the copy's text is unchanged (`html_text` is
    `html_page` without the authors).
  - `Copy.authors`, and `evidence.page_authors` gives `authors` (at most `AUTHORS_MAX`, 20) and `authors_total`.
    The preview and `kg_source_probe` return them. The record keeps them (`EvidenceRecord.authors` and
    `authors_total`, checked on load; a record from before 0.25.1 has none), `kg_source_add`'s answer gives them
    back and `kg_source_list` shows them.
  - `OPENALEX_SELECT` asks for `authorships`, and each catalogue result gives its first three authors
    (`SEARCH_AUTHORS`, `evidence.openalex_authors`) with `authors_total`. The ledger's record of a search is
    unchanged.
  - The scout contract gains "Who wrote it": a work's authors only from a probe's or a catalogue result's
    `authors`, else its title, venue and year, never from memory; its JSON candidate carries `authors`.
    `/burgess:kg-sources` names authors from the preview's `authors` (or as the excerpt prints them) and from the
    scout's `authors`, and its rules forbid inventing an author.
- **What it answers:**
  - On the field run of 2026-11-23 a scout proposed a level-1 paper against c2e and wrote «Brett et al. (2012, J.
    R. Soc. Interface)». The paper is Boettiger & Hastings 2012 (DOI 10.1098/rsif.2012.0125). The probe had
    returned no author, so the names came from the scout's memory.
  - The orchestrator showed the user only the title and the venue that day. Notes taken from the scout's report
    kept its names, and on 2026-11-24 they reached the user and the 0.25.0 entry above. The registration that
    evening matched the paper by its title and DOI, which were right, and its session noticed the mismatch.
  - The user approved the fix («Sí, prepárala»).
- **Why the engine, and not only a rule:** a rule alone leaves a scout no author to give, and a user wants to know
  who wrote a candidate. A page's own tags and the catalogue are records; a model's memory of a citation is not.
  No level, wake or verdict reads the authors.
- **Not done:** a source registered before 0.25.1 keeps no authors, and registering the same text again is
  refused (`already-registered`).
- **Pinned in:** `tests/test_fix_authors_from_the_page.py`.

## Three findings of an end-to-end run: the eval sample, the judge's controls, two `kg-sources` rules (2026-11-25)

- **What it answers:** on 2026-11-25 the user asked for an end-to-end test of every command. It ran headless on
  their Windows install (0.25.1, Claude Code 2.1.331), in a scratch project built from the demo plus two short
  sections. `/kg-eval` and `/kg-experiment` were run in WSL on a copy of that canon, because of the read block
  below. It cost $17.81 in 24 calls. Most commands worked as designed. Three findings had small fixes, and the
  user approved them as 0.25.2 («Sí, prepárala»).
- **Decision 1: the Stage 4 sheet leaves out proposals.**
  - What `f4_probe.py sheet` did: it kept every edge whose `confidence` is not `EXTRACTED`. A proposal of
    `/kg-generate` or `/kg-perturb` carries `INFERRED` like an extracted edge.
  - What the run showed: after both commands ran, 17 of the 34 sampled edges were proposals still in the
    hypothesized lane. The annotators marked 13 of them fabricated, and PRECISION read 0.47. `harness writers`
    gave the extractor's own edges as 15 of 15 correct.
  - What follows: in a development checkout, a precision under 0.70 would have sent the command iterating on the
    pack and the extractor, and nothing there can change a proposal. `/kg-ground` judges proposals. Field
    measurements were exposed too: the field graph has had 100+ generated edges since 2026-11-14.
  - The change: the sheet drops `provenance: hypothesized` before its seeded shuffle and prints how many it
    dropped. A graph with no proposals samples exactly as before. `--include-hypothesized` keeps them.
  - `summary` splits its judged count into proposals and the extraction to sample. The Stage 7 sheets follow the
    same rule.
  - A proposal the grounding promoted to span-present stays in the sample: it is a grounded claim of the graph.
    `edge_writer` reads it as an extraction, as before.
- **Decision 2: `judge-check SOURCE` before the judge.**
  - What `check_controls` requires: a positive control that cites two or more figures or names of the source,
    from at least two documents. A name is a capitalised word that does not open a sentence and whose lowercase
    form is outside the source's 400 commonest lowercase words.
  - Why that failed on the demo: it is one document of 254 distinct lowercase words, so nearly every word counts
    as common.
  - What the run showed: `/kg-experiment --judge` on the demo, the corpus its 12 default prompts are written for,
    wrote its controls twice. `judge-packets` refused them twice (exit 3), and only then did the command skip
    the judge.
  - The change: `judge.control_capacity` applies those same rules to the source as a whole, and the new harness
    command prints the result as JSON, always with exit 0 (`judge_possible`, `problems`, a few examples per
    document). It reads at most 50 distinct terms per document, with a bounded look-behind. The 9-document
    field corpus takes 0.5 s.
  - `/kg-experiment` runs it in Step 0's existing block, so no new shell call is added. With `--judge` and
    `judge_possible` false, the command tells the user before Step 1, writes no controls, skips Step 3b, and logs
    the judge as not measured.
  - It is a necessary condition only. Each prompt's controls are still checked by `judge-packets`.
- **Decision 3: one rule for a level in doubt, one definition of `interest`.**
  - The scout proposes "the higher number" (the weaker level) when unsure between two levels. The `add` step of
    `/kg-sources` said "the lower one". On the run, the scout chose 3 between 2 and 3, and `add` chose 3 between
    3 and 4. The command now says "the higher number, the weaker level, as the scout does".
  - The command's list of marks and `evidence.py` define `interest` as "the author gains if the claim holds: a
    vendor about its product". The `add` step said to mark it when an author speaks "about its own product,
    method or result", which every primary study does. Twice the step followed the narrow reading and gave a
    reason the broad sentence did not admit: on the field run of 2026-11-24, and on this run.
  - The step now points at the definition: a vendor or a company about its own product, service or method, and
    not a study for reporting its own result. The mark is informational only (not in `UNUSABLE_MARKS`).
    Registered records keep their marks; `set <name> marks=` changes one.
- **Not done, offered separately** (larger, or a decision for the user):
  - **The read block.** The user's Windows settings set `permissions.blockReadsOutsideWorkingDirectories`. Under
    it, every Bash block of `/kg-eval` (4 denials on the run, no measurement), `/kg-perturb` Step 1 (2 denials;
    the agent classified the path by hand) and, by the same first block, `/kg-experiment` asks the person
    before it runs. Those blocks read the plugin's cache and data folders, outside the project, and use
    `$(…)`, `${…}` or `case`, which Claude Code's parser does not analyse. The fix is to move those steps into
    the engine, as 0.5.0 and 0.7.0 did for `/kg-build` and `/kg-ground`.
  - **An edited section is never extracted again.** A section counts as `covered` once any span-present edge
    quotes it (`kg_build_plan`). So a claim added to a section that was already built is never extracted, and
    no argument changes that. The fix would record each section's text digest at extraction and plan a section
    again when its text changes.
  - **Agents disagree on two grounded edges.** The annotators labeled `wrong_type` a counter-edge built on a
    limitation, and a lead that turned the author's italic *grounds* into `enables` by the pack's definition.
    Which one decides, the author's relation word or the pack's definition, and whether a limitation counts as
    an attack, is the user's call.
  - Minor: field names and plan sections shown to the user; perturb's table showing "§9"; a same-wave duplicate
    concept never offered for a merge; a passing TLS failure on law.cornell.edu (the same fetch worked minutes
    later from the same Python).
- **Pinned in:** `tests/test_fix_eval_sample_leaves_out_proposals.py`, `tests/test_fix_judge_check.py`,
  `tests/test_fix_sources_rules_agree.py`.

## A built section whose text changed is read again, for what is new (2026-11-25)

- **What it answers:** the second finding of the end-to-end run of 2026-11-25, offered separately in the entry
  above.
  - On that run a sentence stating a new claim was added inside a section already built, and `/kg-build` said
    all six sections were built and launched nothing.
  - A section counted as `covered` once any span-present edge quoted it (`kg_build_plan`), nothing kept the text
    its extraction had read, and no argument read a covered section again. A claim added to a built section
    could never reach the graph.
  - Edgeless sections did not have this gap: since 0.14.0 their record is keyed by the digest of the text, so an
    edited one comes back.
  - The user approved the design with its two recommendations («Sí, así»): a baseline plus `--again` for what was
    built before, and the deleted-sentence case left for a separate change.
- **Decision 1: each extraction records the text it read, unit by unit.**
  - The ledger is `canon.READ_SECTIONS` (`.kg-read-sections.jsonl` beside the canon): engine state, git-excluded
    and gitignored like the other ledgers. Each line holds a section's file, number, title and text digest,
    the digests of its units, the time, and who wrote it.
  - A unit (`buildplan.section_units`) is a paragraph, a list item, a table row or a heading line, without the
    section's own heading line. Its digest (`unit_digest`, 16 hex digits) is of the normalized text, so a
    re-wrapped paragraph is the same unit.
  - Units, not the section's digest, so that the extractor can be handed only what is new. With one digest per
    section a changed section would be read again whole, and an extractor reading old text again writes its own
    variants of claims already there.
  - The record is made where an extraction ends. Under `/kg-build` an extractor reads its section with
    `kg_section` and sends one `kg_write`, so `kg_write` records each section `kg_section` served this engine
    that one of its spans quotes (`by: "write"`). An extractor whose section held nothing new calls
    `kg_record_edgeless_section`, which for a covered section now records the read (`by: "record"`) instead of
    refusing.
  - Not at the `kg_section` read itself: an extractor that read and then stopped would leave the new text
    recorded as read, and nothing would offer it again.
- **Decision 2: the plan offers a covered section again for any unit no record of its file holds.**
  - The test is against every unit any record of the file holds, not against one earlier version of the section,
    so a paragraph moved to another section, a split section or a merged one is not new.
  - The row carries `changed` (`{new_units, of, since}`), `sections_changed` counts these, and `waves` covers
    them with the uncovered ones.
  - `kg_section` hands that section's extractor `changed.new`, the new units, and `changed.written`, the claims
    already written from the section. The extractor contract («A section read again») has it write only what is
    new.
  - A claim written again dedups and keeps its state. An unverified claim whose old span is gone takes the new
    span (0.23.1). A judged one comes back QUARANTINED, which is final.
  - The pack's vocabulary does not count. The edgeless record is keyed by it, because a new type can make a
    section with no relation writable. Here it would send every built section back after any pack change.
- **Decision 3: what was built before has a baseline, and `--again` reads it.** This was the user's first choice,
  the recommended one.
  - A file the ledger holds no record of (built before 0.26.0, by the headless backend, or with the ledger lost)
    gets one at its first plan. Its covered sections' current text is recorded as the text their extraction
    read (`by: "baseline"`), and the plan reports it (`baseline`). An edit made before that moment goes unseen.
  - The plan writes this record and nothing else, so it is no longer read-only. It takes the lease without
    waiting: a held lease answers `not_recorded` and leaves the baseline to the next plan.
  - The first record of a file lays the same baseline for the file's other covered sections (`_record_reads`).
    Without that, a write landing in a file whose baseline the plan could not take would make every other built
    section of the file look new in full, and the next build would read them all again.
  - `/kg-build --again <file>` marks every covered section of the file `changed`, whole: for a file the user
    edited before the update. It needs a file, since without one it would read the whole source again, and it
    does not go with `--leads`.
  - The alternative, no baseline, would have had the plan only count the sections without a record. Then nothing
    built before 0.26.0 would ever be noticed until `--again` read it, at one extractor per section.
- **Decision 4: a deleted or rewritten sentence is counted, not judged here.** This was the user's second choice.
  - Facts first. An unverified claim whose span is gone is rejected by its grounder (`span_in_source` false),
    unless an extraction of the new text writes it again first. A grounded one keeps its verdict and a span the
    notes no longer hold, and nothing flags it.
  - Changing that needs a verdict, and only `kg_ground` sets one, so it is a separate change: `/kg-ground` would
    examine such a claim again, to mark it `obsolete` or ground it on the new passage.
  - Until then the plan counts them (`spans_gone`: `grounded`, `unverified`, up to 10 grounded ids), and the build
    names the grounded ones.
  - Addendum (2026-11-26): done in 0.27.0, see the entry of that date. «Nothing flags it» was wrong: the R3
    advisory listed such a claim, and the command's Stage 0b routed it to a grounder whose remedies did not work.
- **Considered, not done:**
  - A per-section baseline, for any covered section none of whose units a record holds. A one-paragraph section
    with a sentence appended has exactly that shape, so the baseline would have hidden the commonest edit.
  - Telling changed sections by the files' modification times. A time is per file, not per section, and edges
    carry no time of writing.
- **Pinned in:** `tests/test_fix_changed_sections.py`; the covered-section record in
  `tests/test_fix_edgeless_sections.py`; the command texts in `tests/test_fix_source_intake_and_build_noise.py`.


## A claim whose passage left its file is judged again: moved to the passage that states it, or obsolete (2026-11-26)

- **What it answers:** the case decision 4 of the 0.26.0 entry left for a separate change. The user approved the
  design with its three recommendations («Sí, así»).
  - Facts first, checked on 0.26.0 with a probe before any change:
    - A grounded claim whose sentence was rewritten or deleted kept its verdict on text that was gone. The R3
      advisory listed it (`stale_verdicts`, `span-no-longer-in-source`), and Stage 0b of `/kg-ground` had a
      grounder search the source files. Its remedy for a claim that had moved, a `kg_write` re-emit with the new
      span, comes back QUARANTINED `collapses-into-known-verdict` (review-C1, in the boundary since the foundation),
      so the span never moved and the flag stayed. Review r7 (2026-07-04) had pinned that remedy as the working
      one; it pinned only the text. Its remedy for a claim whose text was gone was a rejection. And
      `kg_ground(grounded)` with no passage re-confirmed the claim on the gone text.
    - An unverified claim whose span was gone was rejected by its grounder (step 1a, `no-support: span not in
      source`), permanent negative memory: had the sentence come back, the claim's re-extraction would have been
      quarantined `collapses-into-known-failure`.
    - `obsolete` was accepted on any edge, and no agent gave it.
    - On 2026-11-25 the field project had no such claim (`spans_gone` none on its copy).
- **Decision 1: the plan finds the claims itself, and both live states are judged again.**
  - `KGEngine._span_gone`: a claim with a span of its own (any provenance but hypothesized; the field holds 19
    grounded `inferred` edges with spans, which R3, span-present only, does not list) whose own file is among the
    sources and no longer holds the span. Read live by the plan, as `spans_gone` is, not from the projection's R3
    list.
  - A grounded one is queued after everything new, as a re-examination is; an unverified one stays where it was,
    since it is new work anyway. Both are marked `span_gone` and counted in `queue.spans_gone`.
  - `kg_ground_item` gives `span_gone`: the old span, the sections of its file now ranked by the claim's words
    whatever the file's level (`_file_context`: a passage that states a claim is where it is stated, and its
    support is checked when it is grounded), the files that hold the old span word for word (`elsewhere`), and
    the `also stated:` passages that still verify (`also_present`).
- **Decision 2: two answers, and the engine holds them.**
  - `grounded` with `support_span`, the passage that states the claim now (`_reanchor`). It must verify in a file
    the graph is built from, its own file first (`passage-not-in-built-sources`): the span is where the notes
    state the claim, and a claim that only a paper states any more is no longer one the notes make. The moved
    claim must rest on usable support. Its `span` and `source_file` move; the old span stays in the notes as
    `span was:` (`evidence.span_was_segment`); a grounded claim keeps its `verdict_at`, as any re-confirmation
    does since 0.10.2, so its hub is not reopened.
  - `obsolete`, superseded: out of live topology, not negative memory (DECISIONS 2026-07-31), kept in the canon.
  - A live claim whose passage is gone is never rejected (`span-gone-not-rejected`), and `grounded` with no passage
    is refused (`span-gone-needs-passage`). A refutation (`failed`) is about the claim, not its passage, and stays
    open.
  - A rejected claim a source changed under (0.22.4) is often one whose passage is gone. It gets `span_gone` too,
    and may be rejected again, staying negative memory, or grounded on a passage, which moves it like any other.
    Without the view its grounder would have found no text at all: the flag's own `context` is null for a claim
    flagged by its span's file, and its span `context` is null once the span is gone.
  - In the engine and not only in the contract: the rejection was a contract rule that grounders followed, and a
    rule a note carries from an earlier session can outlive a contract change (0.10.0).
  - The move is the verdict path's. A judged claim's span can move nowhere else: the boundary quarantines its
    re-emit, and that guard is right for an ordinary rebuild. The reconciler polices states, not spans, and is
    checked against a move.
- **Decision 3: `obsolete` only where a passage left its file** (the third recommendation). Refused on a span that
  still verifies (`obsolete-span-still-present`), on an edge with no span of its own (`obsolete-needs-a-span`), and
  on a rejected or failed claim (`obsolete-not-for-negative-memory`): negative memory stays what it is, as the design
  left rejected and failed claims whose sentence is deleted out of this change. Nodes are unchanged. Three pins used
  `obsolete` as an ordinary change of state and now meet the rule: `test_fix_overturned_lead` (a rejection followed
  by `obsolete`; `grounded` stands in, and a new test pins the refusal), `test_fix_attack_once` (the sentence goes
  first) and R3's own test in `test_grounding` (cleared with `obsolete` instead of a rejection).
- **Decision 4: an obsolete claim comes back** (the second recommendation, `_obsolete_returns`).
  - When its span verifies again (an edit undone, a copy restored), or when an extraction has read, since its last
    verdict, a paragraph of its own file that no read of that file held before, and that paragraph shares
    `BEARING_WORDS` (3) of the claim's words. Queued after everything new, marked `reexamine`, counted in
    `queue.obsolete_returned`. Any verdict answers it.
  - The read ledger, not the projector's re-examination flags: the per-file test of a flag (0.14.4) is one word
    shared with the whole changed file, so every edit of a file would bring back all of its obsolete claims. The
    ledger knows which paragraphs are new to a build (`read_units`' `first`), and three words in one paragraph is
    the bar flags and wakes use since 0.24.5. A baseline is not a read.
  - A read and a verdict are ordered by the audit log's offset, which each read record now carries
    (`audit_mark`), not by their times: both are stamped to the second, and a build's read can fall in the
    verdict's second. A record from 0.26.0 falls back to its time, and one in the verdict's second does not count.
  - Its own file only, as designed: a claim moved to another file and rewritten there stays obsolete.
- **Decision 5: a claim whose file is not among the sources is not judged.**
  - Counted per file in `files_missing`, the whole canon's whatever the focus, and refused every verdict but
    `failed` (`span-file-not-among-sources`). A moved or renamed file, or another notes folder, looks the same as
    every sentence of a file deleted at once, and judging that would mark a whole file obsolete.
  - `_own_file`: a claim naming no file belongs to the one file the graph is built from when there is exactly one
    (a project from before files were recorded; R3's own test is such a claim), and to none among several. A name
    not among the sources is never mapped to another file, even with a single file: that is what a configuration
    change looks like.
- **Decision 6: the grounder loses `Read`, `Grep` and `kg_write`.** Their only use was Stage 0b's remedy. Its
  contract already said it reads no file and writes no node.
- **Considered, not done:**
  - Moving a span without a grounder when the old span is in another built file word for word, or when an `also
    stated:` passage still verifies: that changes what a verdict rests on unread. `elsewhere` and `also_present`
    put both in front of the grounder instead.
  - Keeping the passage a build writes for a judged claim, at its quarantined re-emit. The grounder finds the
    passage in `span_gone.sections` itself, and a new kind of record in the write path would have served only
    this.
- **Pinned in:** `tests/test_fix_gone_spans.py`; updated pins in `tests/test_review_r7.py`,
  `tests/test_fix_overturned_lead.py`, `tests/test_fix_attack_once.py`, `tests/test_grounding.py`,
  `tests/test_kg_ground_plan.py`, `tests/test_fix_changed_sections.py` and
  `tests/test_fix_node_scope_and_counters.py` (the grounder brief no longer says that `span_in_source` false means
  a rejection).

## The measurement commands run their steps in the engine, and their agents read only inside the project (2026-11-26)

- **What it answers:** the third finding of the end-to-end run of 2026-11-25, "the read block", offered separately
  in that day's entry. The user chose it from the open items and approved the design with its three
  recommendations («Sí, así»).
  - Facts first, read from the Claude Code 2.1.332 binary and the run's transcripts:
    - Under `permissions.blockReadsOutsideWorkingDirectories`, a Bash command that names a path outside the working
      directories asks the person, and so does one the shell parser cannot analyse: a `case`, a `${…}`, a `$(…)`,
      quoted text. The answer is a `safetyCheck` with `classifierApprovable: false` (circuit breaker
      `outsideReadsBlocked`), so the auto mode's classifier cannot give it; in a `-p` run it is a denial.
    - Every Bash block of /kg-eval, /kg-experiment and /kg-perturb named the plugin's folder (`engine_python.mjs`,
      `PYTHONPATH`) or used those constructs. On the run, /kg-eval was refused four times and measured nothing (the
      session then tried PowerShell, refused the same way), and /kg-perturb's Step 1 twice, its path classified by
      hand. /kg-experiment's first block is the same.
    - The setting also blocks the file tools outside the working directories (`outsideFileToolReadsBlocked`). Two
      such reads remained once the shell was gone. The annotators read the source, which is the `content/` copy in
      the plugin's data folder for a project built from registered sources (`kg_engine.paths source`), and the
      plugin's option or `examples/source.md` otherwise. And /kg-eval's contract check read
      `${CLAUDE_PLUGIN_ROOT}/agents/extractor.md` and its siblings.
- **Decision 1: three engine tools run the steps** (the first recommendation): `kg_eval(step, run, graph,
  iterations)` and `kg_experiment(step, run, prompts, prompt_source, judge_note)`, one step per call, and
  `kg_perturb_plan(arguments)`. The server goes from 44 tools to 47; one tool per command, not one per step.
  - The functions the command lines print, with their seeds. `kg_engine.evalsheet` holds `f4_probe.py`'s sample,
    fill and score as data (the script is its command line now, its output unchanged). `kg_engine.measure` calls
    `harness` and `judge` as their `_cmd_*` do, on the path `kg_engine.paths source` gives (`paths.write_content`,
    shared). The tests compare each step with the command line on the same files.
  - Nothing prints: an MCP stdio server speaks its protocol on stdout.
  - They write only under `<project>/.kg/`, never the canon or a verdict; `sample` re-projects, as any read does.
    A `run` must match `RUN_RE` before it names a folder.
  - This reverses the 2026-11-10 rejection (d), "a new tool on the trust boundary for one measurement". Its premise
    was that a shell step costs an approval at worst; under the read block it costs a person at every step. The
    tools carry no new capability: they read what the server reads already, and write scratch under `.kg/`.
- **Decision 2: the LightRAG arm keeps its Bash step** (the second recommendation). It is opt-in (`KG_LIGHTRAG=1`,
  the package, `OPENAI_API_KEY`), sends the whole source to OpenAI with the user's key and costs money: the
  approval the read block asks for is worth having there, and moving it would put a third-party upload inside the
  trust boundary. `start` reports its availability from the engine's environment, which the launcher passes whole,
  as the `KG_DIVERGE_*` knobs need.
- **Decision 3: the annotators read a copy** (the third recommendation). `sample` copies into
  `.kg/eval/<run>/source/` the documents of the verification set, so every document an edge can cite, exactly as the
  engine reads them, and into `contract/` the running plugin's three contract files. Not passages served by the
  engine: the annotator's method, whole documents searched for a verbatim span, stays as it was and independent of
  the engine's retrieval.
- **Decision 4: a run has its own folder, and the engine writes the log.**
  - `.kg/eval/<run>/` holds the three sheets of one seeded sample, the labels, the saved results and `run.json`. A
    `sample` naming the run is a development checkout's next pass: it removes the run's labels, so a pass never
    scores an earlier pass's file, which the flat `.kg/eval/` of 0.27.0 allowed. The log records the best pass.
  - The entries are rendered from the saved results in the shell blocks' format, with a `run:` line added. The
    `/kg-eval` header keeps the bare name, the one exemption since 0.13.3, now held by `measure.py`. The model
    supplies only `iterations` (kg-eval) or `prompt_source` and `judge_note` (kg-experiment); through 0.27.0 it
    copied every number into shell variables by hand, about sixty for an experiment.
  - /kg-experiment's score step keeps the outputs and their drafts as `ideation_outputs*-<run>.json` (`copy2`, so
    the order check's times hold), which the field run of 2026-11-11 did by hand.
- **Decision 5: /kg-perturb's argument is planned by the engine.** `kg_perturb_plan` takes `$ARGUMENTS` verbatim,
  strips its quotes, resolves a relative path against the project and refuses a path that names no file. That
  keeps the guard of the old `__SECOND__` slot: an argument left unfilled names no file, so it never passes for "no
  second source". The construction is named by the block's rule (lowercased, each other run a hyphen, `second`
  when nothing is left), and `own_source` says whether the file is one of the graph's own sources.
- **Considered, not done:**
  - A tool per step, fourteen in all: the same work, with a surface every session lists.
  - Narrower or simpler Bash: any command that names the plugin's folder asks under the read block, whatever its
    shape.
  - Advising `/add-dir` for the plugin's folders: it would open every read there to every agent, and the settings
    are the user's.
  - Having the annotators read `evidence/` in place: only registered copies live there, and the notes can lie
    outside the project.
- **Not changed:** the skill's `references/` are read from the plugin's folder; whether Claude Code lets a skill read
  its own folder under the setting is for a live run to show. A development checkout's iteration (4.5) still edits
  the plugin's pack, outside the project.
- **Pinned in:** `tests/test_fix_commands_without_shell.py`; updated pins in `tests/test_fix_command_arguments.py`
  (perturb's path classified by the engine; the Bash runner helpers removed), `tests/test_fix_eval_log_and_annotator.py`,
  `tests/test_fix_field_eval_experiment.py`, `tests/test_fix_experiment_measurement.py`,
  `tests/test_fix_evaluator_order.py`, `tests/test_fix_judge_check.py`, `tests/test_fix_blind_judge.py`,
  `tests/test_fix_perturb_second_reading.py`, `tests/test_fix_eval_sample_leaves_out_proposals.py`,
  `tests/test_fix_command_names_and_judge_cost.py` (the log header's exemption moves to the engine) and the 47-tool
  count in `tests/fusion/test_diverge_surface.py`.
