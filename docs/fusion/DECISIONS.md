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
