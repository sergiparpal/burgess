# Changelog

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
