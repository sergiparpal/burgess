# FUSION_PLAN.md — A New Plugin Fusing Sproutgraph × Cambrian (Clean Repo, Read-Only Donors)

**What this is:** A self-contained execution plan for building a **brand-new Claude Code plugin** that fuses the convergence engine of **Sproutgraph** and the divergence engine of **Cambrian** into one tool covering the full creative cycle.
**Executor:** A coding agent (Claude Code CLI) running autonomously, stage by stage.
**Repository model:** This plan lives at the root of a **fresh, empty repository** (the plan file is its only initial content). The two source plugins are **donors, never patients**: they are read from and copied from, and **never modified in any way** — no commits, no branches, no config edits, not even stray cache files left behind. Donor integrity is enforced automatically at every stage gate (Invariant I11).
**Human role:** Answer a short kickoff questionnaire (Stage 0) and, at most, one brief multiple-choice question per stage if the agent is genuinely blocked. Every question ships with a recommended default and a short timeout, after which the default applies and execution continues. There are **no mandatory human review checkpoints**: every gate that would normally be a human review is an automated test suite or a pre-declared decision rule (Section 14).
**This document is the contract.** If any instruction here conflicts with what the agent finds in the actual donor code, the agent records the discrepancy in `INVENTORY.md`, adapts the task to reality, and preserves the *invariants* (Section 4) — the invariants win over everything, including this plan's own task descriptions.

> **Editorial note (2026-07-09), added after the fact.** This plan is a **historical record** of how Burgess
> was built. Both donor repositories have since been **retired and unpublished** by their author, so the
> provisioning steps below that clone them from GitHub can no longer be executed. The pinned donor checkouts
> recorded in `scripts/donor_pins.json` are the surviving copies, and the I11 donor-integrity gate still runs
> against them. Decision Rule **D5 (upstream drift)** is retired as a consequence — see the annotation at §14.
> Apart from the removal of the donor URLs and that one marked annotation, the document is preserved as written.

---

## 1. Mission

Build one plugin from two donors by the same author — both of which were, when this plan was written, live and untouched independent projects (see the editorial note above):

- **Sproutgraph** — the *convergence* donor. Grows source documents into a grounded, queryable knowledge graph. Every non-deterministic edge must quote a verbatim span from the source and survive re-checking, or it is rejected. It guarantees fidelity to the source, never truth about the world.
- **Cambrian** — the *divergence* donor. Turns any creative brief into a diverse, non-cliché slate of ideas using a local, server-less Python engine (MAP-Elites + geometric novelty + DPP selection) that keeps the LLM from collapsing to the mean. The human steers and selects in chat.

The new plugin inherits Sproutgraph's architecture as its spine (canon/derived split, MCP trust boundary, grounding loop, experiment harness) and absorbs Cambrian's engine as a **firewalled divergence subsystem below the grounding boundary**: its geometry governs how ideas are generated and presented, and it never gains any authority over what counts as grounded.

One sentence that resolves every design dispute in this plan: **embeddings measure dispersion, never truth.**

**Naming:** The plugin's final name is decided by kickoff question Q1. Until then this plan uses the placeholder **NewPlugin**; the agent substitutes the chosen name in the manifest, module namespaces, and docs during Stage 1.

---

## 2. Source Material & Read-Only Rules

### 2.1 Directory layout

All three repositories sit side by side under one parent directory:

```
<parent>/
├── NewPlugin/       ← this repo (starts containing only FUSION_PLAN.md)
├── Sproutgraph/     ← donor, read-only
└── Cambrian/        ← donor, read-only
```

If a donor sibling is missing at Stage 0, the agent clones it into the parent directory. Cloning creates a local copy and modifies nothing upstream. (As written, this step cloned each donor from its GitHub URL; both repositories have since been retired, so the local checkouts pinned in `scripts/donor_pins.json` are now the only copies.)

### 2.2 Read-only enforcement (Invariant I11)

Donors are consulted and copied from — **never altered**:

- No file creation, edit, or deletion inside `../Sproutgraph` or `../Cambrian`. No `git` write operations there (no commit, branch, checkout of other refs, stash, tag, config).
- Runs that could drop artifacts (test caches, `__pycache__`, build files) never execute inside donor trees. Donor test baselines are run on a **temporary copy** (e.g., `cp -r ../Sproutgraph /tmp/sg-baseline`) or, at minimum, with `PYTHONDONTWRITEBYTECODE=1` and `pytest -p no:cacheprovider`.
- **Automated cleanliness gate, run before every stage commit:** for each donor, `git -C <donor> status --porcelain` is empty **and** `git -C <donor> rev-parse HEAD` equals the SHA recorded at Stage 0. Any deviation fails the gate; the agent restores cleanliness (delete strays it caused) and records the incident in `BLOCKERS.md`.

> **Editorial note (2026-07-29), added after the fact.** The gate as written above is a *proxy*: it
> enforced "the donor never changed at all" in order to guarantee "the fusion never wrote to the
> donor". The proxy held only while the donors stayed retired. Cambrian has since been republished
> and resumed active development, moving many commits past its pin, so the proxy began failing on
> every Burgess commit while the invariant it stands for remained perfectly intact — the fusion is
> finished and cannot retroactively write anywhere. `scripts/check_donors_clean.py` now enforces the
> weaker, still-true statement: each pinned Stage-0 commit **still exists and is reachable from the
> donor's `HEAD`**, so the exact tree that was copied from remains recoverable and every
> `ATTRIBUTION.md` claim stays checkable. Donor working-tree cleanliness and an unmoved `HEAD` are no
> longer asserted; a live repository has neither, and neither says anything about what the fusion did.
> An *unreachable* pin is still a hard failure — that is the case where provenance really is lost.
> The sibling checkouts were also renamed to lowercase (`../sproutgraph`, `../cambrian`) and the pins
> updated to match.

### 2.3 Provenance pinning

At Stage 0 the agent records each donor's `HEAD` SHA in `BASELINE.md`. All ported code is attributed to `repo URL @ SHA` in `ATTRIBUTION.md`. If upstream donors evolve during development, **this build does not chase them** — it is pinned to the Stage-0 SHAs (Decision Rule D5).

### 2.4 Code-Not-README rule (mandatory)

Donor READMEs are rich but have drifted before (known example: Sproutgraph's README states "733 tests green" in the intro and "496 passed" in its Development section — at most one is current). Therefore:

- **Ground truth is donor code and donor test suites, never prose.** Before porting or reimplementing any described behavior, locate the actual implementation and read it.
- Every path, constant, tool name, and count in this plan marked **(verify)** is a README-derived expectation. Stage 0 replaces each with a confirmed fact in `INVENTORY.md`.

### 2.5 Capsule architecture of the donors (expectations to verify in Stage 0)

**Sproutgraph** (verify all):
- Deterministic Python engine at `scripts/kg_engine/`; tests under `tests/`; run with `uv run pytest tests/ -q`.
- MCP server (FastMCP) exposing ~20 tools; write boundary: non-deterministic writes go through `kg_write` (hypothesized lane) and verdicts are produced **only** by `kg_ground`. A reconciler re-quarantines forged `grounded` edges. A span-staleness re-grounding queue exists (R3 mechanism, `projector.py`).
- Canon = one human-editable `.md` file per node (git-mergeable, semantic merge driver); Derived = NetworkX/SQLite, regenerable.
- Provenance / `authored_by` / epistemic-state axes on edges; states include at least `hypothesized`, `grounded`, `failed`, `rejected`. Negative information (failed/rejected edges, falsification counters) is kept forever.
- Slash commands: `/kg-build`, `/kg-ground`, `/kg-query`, `/kg-eval`, `/kg-experiment`, `/kg-generate`, `/kg-perturb`, `/kg-view`. Six subagents (extractor, grounder, adversarial-grounder, generator, annotator, evaluator).
- `/kg-generate`: seven structural discovery mechanisms (bridge, seed, compression, regroup, transplant, ensemble, periphery) proposing into the hypothesized lane.
- `/kg-experiment`: blind multi-arm harness (arms like `control | graph | graph+generate | rag`, optionally `lightrag`).
- Embeddings deliberately removed (former sqlite-vss path deleted; `with_embeddings` metrics mode inert).
- Provisioning: SessionStart hook → `hooks/provision.mjs` → OS launcher (`provision.sh` / `provision.ps1`) → `scripts/bootstrap.py`; `uv` preferred, `venv`+`pip` fallback; venv in the plugin's persistent data dir; non-blocking.
- Domain pack: `pack.yaml` declared vocabulary.

**Cambrian** (verify all):
- Server-less: one skill (`/cambrian:ideate`), no MCP server, no subagents. The LLM parts (variation generation, skeptical judge prefilter) are done by the main agent; the math is a local CLI engine: `python -m cambrian_engine`.
- Engine: model2vec static embedder (`potion-multilingual-128M`, 256-dim, CPU, torch-free); MAP-Elites archive over behavior descriptors; k-NN geometric novelty; DPP slate selection; anti-collapse monitor (Shannon entropy + mean pairwise cosine).
- Judge decoupled from diversity: geometry owns novelty; the judge only filters validity with bounded influence (weight ≈ 0.3; fitness multiplier clipped to ≈ [0.7, 1.3]).
- Anti-cliché: maps ~6 "obvious answers" per brief, generates away from them, measures held-out.
- Mechanism-first generation (each idea tagged with its generating mechanism).
- Human is the selector: pins, discards, A-vs-B; preference memory under `~/.cambrian/<project>/`.
- Per-domain YAML descriptor templates. Selftest gates: variety gate, DPP-beats-first-N (shuffled, seed-averaged), null check vs random subset.
- Same provisioning chain pattern as Sproutgraph.

---

## 3. Target Architecture (what "done" looks like)

### 3.1 The fused pipeline

1. `/kg-ideate <brief>` — pure divergence, **no graph and no source document required**. Cliché map → mechanism-first generation (by the agent) → embed → MAP-Elites bins → DPP slate (by the engine) → pins/discards in chat, with the anti-collapse monitor watching.
2. Pinned ideas can be **materialized** into the graph as `hypothesized` nodes/edges via `kg_write` only, carrying `provenance: generated`, the generating mechanism in `authored_by`, and a `pinned` annotation. No source ⇒ they simply wait.
3. When a source exists, `/kg-ground` tries to win spans for them. Verdicts come **only** from `kg_ground`. Failures join the unified negative memory.
4. `/kg-generate` output (all seven structural mechanisms) flows through the same geometry — embed → **hybrid** descriptor bins (semantic axis + graph-structural axes) → DPP — before presentation. Entirely advisory, behind a config flag.
5. `/kg-experiment` gains a `graph+generate+dpp` arm; a pre-declared rule (D1) decides the flag's default from blind results. The fusion is measured, not assumed.

### 3.2 What is taken, transformed, or left behind

| Piece | Fate in NewPlugin | Note |
|---|---|---|
| Sproutgraph engine, MCP boundary, commands, agents, harness, canon/derived model | **Take (vendored)** | The spine. Ported at Stage 1 under the new name; full donor test suite must pass in the new repo. |
| `kg_ground` verdict monopoly + span-present write boundary | **Untouchable semantics** | Ported verbatim in behavior; divergence code never touches it. |
| Cambrian engine (embedder, MAP-Elites, novelty, DPP, monitor, judge bounds, cliché) | **Take (vendored, firewalled)** | Becomes `divergence/` library inside the engine. |
| Cambrian embeddings | **Transform** | Derived, regenerable, firewalled state. Never in canon; never importable from grounding code; never in the DB `kg_query` reads. |
| MAP-Elites archive persistence | **Transform** | Session-ephemeral. The graph is the durable archive; MAP-Elites only organizes a round. |
| Cambrian judge (bounded fitness) | **Take** | Cheap plausibility prefilter in the divergent lane; the grounder remains the strong judge. |
| Cambrian per-domain YAML descriptors | **Merge** | Into `pack.yaml`: one domain-pack format (extraction vocabulary + behavior axes). |
| `~/.cambrian/<project>` state model | **Transform** | Project-local `.kg/ideate/` (git-friendly, consistent with canon philosophy). Optional importer for old Cambrian state. |
| Cambrian discards + Sproutgraph failed/rejected | **Unify** | One negative-memory store; both generation paths must consult it. |
| One provisioning chain | **Take once** | The two donors' chains are near-identical; port Sproutgraph's, extend deps for model2vec. |
| MCP server vs server-less CLI | **MCP wins as spine** | Trust boundary enforced at the MCP layer; a thin dev CLI may remain (kickoff Q4). |
| Different-family embedder (model2vec, not Claude-family) | **Untouchable** | The diversity judge must not share lineage with the generator. |
| Donor repos themselves | **Left behind, intact** | No deprecation notices, no upstream PRs, no pushes. Their futures are the author's business, out of scope. |

---

## 4. Non-Negotiable Invariants

Each invariant is enforced by a test (or automated gate) that must exist **before** the feature it guards, and must be green at every stage commit from its introduction onward.

- **I1 — Verdict monopoly.** Only `kg_ground` produces `grounded` verdicts. No code path under `divergence/` can set or upgrade an epistemic state to `grounded`, directly or indirectly.
- **I2 — Span-present boundary.** No span-less `grounded` edge can be created from any code path. Attempts are rejected by the write boundary; the reconciler re-quarantines forgeries.
- **I3 — Import firewall.** No module in the grounding/verdict/reconciler path imports (transitively) from the `divergence` package. Enforced by an import-graph test (AST scan or import-linter config).
- **I4 — DB isolation.** The SQLite database read by `kg_query` contains no embedding/vector tables or columns. Divergence vectors live only in session-scoped storage (memory or `.kg/ideate/`), never in canon, never in the query DB.
- **I5 — Advisory ceiling.** DPP ordering, novelty scores, cliché distances, bin coordinates, monitor readings, and pin priority influence *what is proposed and in what order* — never *what is true*. Grounding output on a fixture corpus is bit-identical with the geometry flag on vs off (snapshot test).
- **I6 — Judge bounds preserved.** The divergent-lane judge keeps Cambrian's bounded influence (weight and fitness-clip constants **as found in Cambrian's code** — **(verify)**; README suggests weight 0.3, clip [0.7, 1.3]). It can demote within a slate; it cannot empty the slate below a diversity floor.
- **I7 — Different-family embedder.** The embedder is model2vec (or the successor pinned in Cambrian's code), never a Claude/Anthropic-family model.
- **I8 — Negative memory is sticky and consulted.** Human discards and grounding failures live in one store; nothing in that store is re-proposed as a candidate or reused as a MAP-Elites parent.
- **I9 — Graceful degradation.** If the embedding model is unavailable (offline, download failure), divergence features fail with a clear message; every convergence capability works untouched.
- **I10 — Archive ephemerality.** No MAP-Elites archive file persists across sessions. Only pins, discards, and session metadata persist (project-local).
- **I11 — Donor repos untouched.** The cleanliness gate of Section 2.2 (empty `git status --porcelain`, unchanged `HEAD` in both donors) passes at every stage commit. *(2026-07-29: now enforced as Stage-0-commit reachability — see the editorial note at §2.2.)*

---

## 5. Explicit Non-Goals (do not build, even if it seems like an obvious improvement)

1. **No semantic retrieval for grounding.** Never use embeddings to find/suggest spans, rank evidence, or shortcut `kg_ground`. This is the embedding-as-truth trap; it is out of scope permanently, not deferred.
2. No new verdict pathways, no "fast-track grounding" for pinned ideas.
3. No modifications of any kind to the donor repos (I11), no deprecation notices for them, no upstream PRs or issues.
4. No pushing anywhere: the agent commits locally in NewPlugin; publishing (remote, marketplace listing) is the human's step after the plan completes.
5. No PKM/editing features for canon beyond what Sproutgraph has.
6. No persistence of MAP-Elites archives (I10).
7. No swap of the embedder to an API-based or Claude-family model (I7).
8. No "improvements" to grounding/reconciler semantics while porting — behavior-preserving port first; ideas go to `BLOCKERS.md` as `REJECTED-BY-PLAN` or `FUTURE`.

---

## 6. Agent Operating Protocol

### 6.1 Autonomy contract

- Execute stages **in order**; within a stage, tasks in order unless independence is obvious.
- A stage is complete only when **all** its exit criteria pass — including the I11 cleanliness gate. Then commit (6.4) and update `PLAN_STATE.md`.
- Never skip an exit criterion silently. If one cannot be met, follow the blocker protocol (6.5).

### 6.2 State files (all in `docs/fusion/`, committed in NewPlugin)

- `PLAN_STATE.md` — stage-by-stage status (template in Appendix A). **First read on any session resume**: find the first stage not `DONE`, re-verify its entry criteria, continue.
- `INVENTORY.md` — the concept→actual-donor-code map from Stage 0; updated whenever reality diverges from a **(verify)** expectation.
- `ATTRIBUTION.md` — per ported area: donor URL @ SHA, source paths, license note.
- `DECISIONS.md` — every kickoff answer, every default applied on timeout, every judgment call, one-line rationale each.
- `BLOCKERS.md` — deferred/rejected items and why.
- `BASELINE.md` — donor HEAD SHAs, pre-fusion test counts and timings.

### 6.3 TDD for invariants

For every invariant I1–I10: write the enforcing test first, watch it fail where a failure is expressible pre-implementation, then implement until green. Invariant tests live in `tests/fusion/` and run in the default suite from the moment they exist. I11 is a scripted gate (`scripts/check_donors_clean.sh` + `.ps1` or a cross-platform Python script) invoked before every commit.

### 6.4 Commit discipline

- One commit per stage minimum (splitting a big stage into 2–3 coherent commits is fine; see Stages 1 and 3).
- Conventional Commits format; templates given per stage. Body lists exit criteria with ✅.
- Full test suite green and I11 gate green before every commit. Never force-push. All work on `main` of NewPlugin (it is a fresh repo; no branch ceremony needed) unless the human said otherwise in kickoff.

### 6.5 Blocker protocol

1. Try **three distinct approaches** (not three retries of one). Log attempts in `BLOCKERS.md`.
2. Still blocked and the decision is genuinely the user's → ask **one** concise multiple-choice question via the built-in AskUserQuestion tool. Max 1 question per stage beyond Stage 0's questionnaire; the recommended option first, marked "(Recommended)"; one-line consequence per option.
3. AskUserQuestion has a short timeout (~60s). **On timeout or "you decide": apply the recommended default, record it in `DECISIONS.md`, continue.** Execution never stalls on an unanswered question.
4. Blocked, non-critical, no later stage depends on it → `BLOCKERS.md` as `DEFERRED`, continue.
5. Blocked and critical with no viable default (expected: never) → stop at a clean commit boundary, write a precise handoff note at the top of `PLAN_STATE.md`, end the session.

### 6.6 Environment prerequisites (verify in Stage 0)

Python ≥3.11 **(verify against donors' pins)**, `git`, `uv` (fallback `python -m venv` + `pip`), network access for pip/model download at provisioning time (I9 is the offline story). Cross-platform paths only (`pathlib`); no POSIX-only assumptions outside the sh/ps1 launchers.

### 6.7 How the human launches this plan (for reference)

```bash
mkdir NewPlugin && cd NewPlugin && git init
# put this file at the repo root as FUSION_PLAN.md  (the repo's only initial content)
# optional but recommended — donors as siblings (the agent will clone them if absent).
# NOTE: both donor repos have since been retired; these clone steps no longer resolve.
git -C .. clone <Sproutgraph>
git -C .. clone <Cambrian>
claude
> Read FUSION_PLAN.md and execute it stage by stage, starting at Stage 0.
> Follow its Agent Operating Protocol exactly. It is the contract.
```

Resuming later (new session): same instruction — the agent reads `docs/fusion/PLAN_STATE.md` and continues from the first non-DONE stage.

---

## 7. Stage 0 — Bootstrap, Donor Pinning, Inventory & Kickoff

**Goal:** Verified ground truth, pinned donor provenance, and all human decisions front-loaded, so Stages 1–6 run without anyone.

**Entry criteria:** Agent is in the NewPlugin repo (contains this file; git initialized).

**Tasks:**
1. Ensure donor siblings exist at `../Sproutgraph` and `../Cambrian`; clone from the GitHub URLs if absent. Record both HEAD SHAs in `BASELINE.md`. Run the I11 cleanliness check once now (must pass trivially) and install it as the pre-commit gate script in NewPlugin.
2. Create `docs/fusion/` with all state files (6.2), `.gitignore` (Python, venv, `.kg/ideate/` session leftovers in fixtures, etc.).
3. **Donor baselines without pollution:** copy each donor to a temp dir (or run with `-p no:cacheprovider` + `PYTHONDONTWRITEBYTECODE=1`) and run its full test suite. Record exact counts, skips, wall time in `BASELINE.md`. Pre-existing failures are recorded and never chased (D4). Resolve the 733-vs-496 discrepancy by trusting `pytest` output.
4. **Build `INVENTORY.md` from donor code** (not READMEs). Minimum entries, each with donor + file path + symbol:
   - Sproutgraph: write-boundary implementation; verdict creation site(s) in `kg_ground`'s path; reconciler quarantine logic; span-staleness queue (R3 / `projector.py`); the actual MCP tool list (count them); epistemic-state constants; provenance/`authored_by`/annotation fields; negative-memory representation (falsification counters); the seven mechanisms' entry points and how candidates surface to chat; `/kg-experiment` arms, blind protocol, scoring/aggregation, seed handling; `pack.yaml` schema + loader; provisioning chain files and persistent data dir; plugin manifest / marketplace layout; how a plugin is loaded locally for development (**verify current mechanism in Claude Code docs**).
   - Cambrian: engine module layout (`cambrian_engine` **(verify)**); embedder id + dims; MAP-Elites, k-NN novelty, DPP, monitor thresholds; judge weight/clip constants; cliché mapper; descriptor YAML schema; selftest implementation; `~/.cambrian/` state layout; skill definition.
   - Licenses: confirm both donors are MIT **(verify LICENSE files)**; note attribution requirements. NewPlugin ships MIT + `ATTRIBUTION.md` crediting both donors with URL @ SHA (same author, but provenance is hygiene).
5. **Kickoff questionnaire** via AskUserQuestion — full text in Appendix B (5 questions, recommended defaults, timeout ⇒ defaults; all recorded in `DECISIONS.md`).
6. Scaffold the repo skeleton (empty dirs + manifest stub under the chosen name; no ported code yet). Commit.

**Exit criteria:** Donor SHAs pinned; baselines recorded; `INVENTORY.md` has no unverified **(verify)** item that Stages 1–6 depend on; questionnaire answered or defaulted; I11 gate installed and green; commit made.

**Commit:** `chore(fusion): stage 0 — donor pinning, baselines, code inventory, kickoff decisions`

---

## 8. Stage 1 — Foundation Vendoring (Sproutgraph Parity Under the New Name)

**Goal:** NewPlugin is, functionally, Sproutgraph — engine, MCP server, commands, agents, provisioning, tests — under its own name, from copied code, donors untouched.

**Entry criteria:** Stage 0 `DONE`.

**Tasks:**
1. Copy the Sproutgraph codebase areas identified in `INVENTORY.md` into NewPlugin (engine → `scripts/kg_engine/`, MCP config, `commands/`, `agents/`, hooks/provisioning chain, `pack.yaml`, tests). Copy means `cp` out of the donor — never `mv`, never editing in place.
2. Rename plugin identity everywhere the inventory says identity lives (manifest, marketplace metadata, data-dir naming, user-visible strings). Keep `/kg-*` command names per kickoff Q2. Record every renamed surface in `ATTRIBUTION.md` alongside its source path @ SHA.
3. Bring the full vendored test suite green inside NewPlugin (`uv run pytest -q`), matching Stage-0 baseline counts (minus tests that are donor-repo-specific, e.g. tests asserting the old plugin name — adapt those and list each adaptation).
4. Provisioning smoke test on a clean venv via both `uv` and pip paths; verify the plugin loads locally in Claude Code per the mechanism confirmed in Stage 0, and that `/kg-build → /kg-ground → /kg-query` round-trips on a tiny fixture document.
5. Add LICENSE (MIT) + `ATTRIBUTION.md`.

**Exit criteria:** Vendored suite green at baseline parity (deviations listed and justified); provisioning smoke green; local plugin load + kg round-trip green; I11 gate green.

**Commit(s):** split allowed — `feat(foundation): vendor Sproutgraph engine and boundary (1a)` · `feat(foundation): commands, agents, provisioning, identity (1b)`. Single-commit template: `feat(foundation): Sproutgraph parity under NewPlugin identity (baseline-matched)`

---

## 9. Stage 2 — Firewall First, Then Port the Divergence Engine

**Goal:** Cambrian's math lives inside NewPlugin as an isolated library, and the isolation is enforced by tests that predate the port.

**Entry criteria:** Stage 1 `DONE`.

**Tasks:**
1. **Firewall tests first** (`tests/fusion/test_divergence_firewall.py`), written before any porting:
   - **I3:** import-graph scan proving no grounding/verdict/reconciler module (per `INVENTORY.md` paths) transitively imports the divergence package. Assert over the real module graph, not a hardcoded list, so the test passes trivially now and meaningfully after the port.
   - **I4:** schema assertion over the `kg_query` DB (no vector/embedding tables or columns) plus a runtime probe that divergence storage writes only under session temp or `.kg/ideate/`.
   - **I1/I2 (adversarial, additive):** attempts to create a `grounded` state or a span-less grounded edge via public write APIs are rejected; the reconciler re-quarantines a hand-forged one. Extend the vendored boundary tests rather than duplicating them.
2. **Port the engine** from `../Cambrian` into `scripts/kg_engine/divergence/` as a pure library (no I/O side effects at import time): embedder wrapper (model2vec), `map_elites`, `novelty` (k-NN), `dpp`, `monitor` (entropy + mean pairwise cosine), `judge_bounds`, `cliche`, descriptor loading. Port Cambrian's unit tests to `tests/fusion/divergence/` with adapted imports; preserve deterministic seeding. Keep constants exactly as found in Cambrian's code (I6, I7); cite source file+line in `ATTRIBUTION.md`.
3. **Provisioning:** add model2vec + numeric deps to the bootstrap chain; model artifact cached in the persistent data dir; lazy-import divergence deps so the core imports cleanly without them (**I9** test: simulate missing model → divergence raises a clear, actionable error; core kg tools smoke-pass).
4. **I10 test:** after a full divergence round in a temp project, assert no archive artifact exists outside the session scope.

**Exit criteria:** Ported Cambrian tests green under new paths; firewall/adversarial/degradation tests green; full suite green; provisioning smoke green on both dependency paths; I11 gate green.

**Commit:** `feat(divergence): port Cambrian engine behind grounding firewall (I1–I4, I6, I7, I9, I10 enforced)`

---

## 10. Stage 3 — `/kg-ideate`: Standalone Divergence (Cambrian Parity)

**Goal:** Full Cambrian user experience inside NewPlugin, working in a project with **no graph and no source document**.

**Entry criteria:** Stage 2 `DONE`.

**Tasks:**
1. New command (name per kickoff Q3; default `/kg-ideate`) implementing the loop: brief intake → cliché map (~6 obvious answers, agent-generated, held out) → mechanism-first variation generation by the agent → engine call for embed → bins → novelty → DPP slate → present slate with mechanism labels and why-picked one-liners → pins / discards / A-vs-B in chat → iterate, monitor watching; on collapse trip, regenerate under diversity pressure automatically (advisory notice, no question).
2. Engine invocation: as a library through the MCP layer, with a thin dev CLI kept or dropped per kickoff Q4 — either way, chat-side logic stays thin; math stays in `divergence/`.
3. **State:** `.kg/ideate/<brief-slug>/` in the user's project (`session.json`, `pins.jsonl`, `discards.jsonl`). Explicitly not `~/.cambrian`. Optional one-shot importer `--import-cambrian [path]` mapping old preference memory into the new layout (best-effort; log unmapped fields; reading `~/.cambrian` is read-only by nature).
4. Merge Cambrian's per-domain descriptor YAML into the vendored `pack.yaml` schema (one loader, two sections: extraction vocabulary + behavior axes). Ship Cambrian's domain templates as pack fragments (copied, attributed).
5. Port the **selftest** as pytest marks + a `--selftest` command path: variety gate (thresholds as found in donor code), DPP-beats-first-N over shuffled orderings averaged across seeds, null check vs a random subset of equal size.
6. Graphless guarantee test: the command runs end-to-end (scripted pins) in a fixture project containing no `.kg` graph and no sources.

**Exit criteria:** Selftest green; scripted e2e session green; graphless test green; state files project-local only; full suite green; I11 gate green.

**Commit(s):** split allowed — `feat(ideate): divergence round-trip (3a)` · `feat(ideate): chat loop, packs, selftest (3b)`. Single-commit template: `feat(ideate): standalone divergence command with Cambrian parity`
**Fallback:** if the stage exceeds ~2 sessions of effort, split as above and continue; no question needed.

---

## 11. Stage 4 — Pin Materialization & Unified Negative Memory

**Goal:** Divergence output can enter the graph — through the front door only. *(The kind of step that would normally get a human review; here it is gated by the adversarial suite below.)*

**Entry criteria:** Stage 3 `DONE`.

**Tasks:**
1. **Materialization:** an explicit action (default per kickoff Q5) turning pinned ideas into nodes/edges **via `kg_write` exclusively**, with `provenance: generated`, mechanism in `authored_by`, `epistemic_state: hypothesized`, a `pinned` annotation, and a reference back to the brief/session. Works with or without sources present.
2. **Unified negative memory:** merge ideate discards into the store that holds `failed`/`rejected` (single source of truth per `INVENTORY.md`). Both `/kg-ideate` and `/kg-generate` consult it: nothing in it is re-proposed or used as a MAP-Elites parent (**I8** tests on both paths).
3. **Pin priority:** pinned hypotheses may be *ordered first* in the grounding queue. Verdict-neutrality test: on a fixture corpus, grounding outcomes (verdicts, spans, failure records) for an edge are identical whether or not it is pinned.
4. **Adversarial suite:** from the ideate/materialization path, attempt to (a) set `grounded`, (b) write a span-less grounded edge, (c) smuggle vectors into canon or the query DB, (d) bypass `kg_write`. All rejected; the reconciler re-quarantines a forged artifact planted by the test.
5. **E2E:** brief → ideate → pin → materialize → add a source doc → `/kg-ground` → at least one span won and one failure recorded into negative memory → the discarded sibling is never re-proposed in a follow-up ideate round.

**Exit criteria:** Adversarial suite green; verdict-neutrality green; e2e green; full suite green; I11 gate green.

**Commit:** `feat(fusion): pins enter the hypothesized lane; unified negative memory (I1, I2, I5, I8 verified adversarially)`

---

## 12. Stage 5 — Advisory Geometry over `/kg-generate` (Flagged)

**Goal:** The seven structural mechanisms get Cambrian's diversity discipline — purely advisory, behind a flag.

**Entry criteria:** Stage 4 `DONE`.

**Tasks:**
1. Config flag `divergence.dpp` in the pack/config schema, **default off** (Stage 6's rule may flip it).
2. Pipeline: mechanism candidates → embed → **hybrid descriptors**: one semantic axis (embedding novelty vs session archive) + graph-structural axes computed from the derived graph (e.g., communities touched, graph distance between endpoints, epistemic-state mix of the neighborhood — pick 2–3 that are cheap and already computable per `INVENTORY.md`) → MAP-Elites binning → DPP slate → present with the same labeling as `/kg-ideate`.
3. **Hybrid cliché map:** union of brief-level semantic clichés and the top-K highest-degree `grounded` hubs (the graph's "center"). Document in code comments the design intuition: the periphery mechanism and cliché-distance are two views of the same away-from-center pressure.
4. **I5 snapshot test:** on a fixture corpus, run generate→ground with flag off and flag on; assert grounding artifacts (verdicts, spans, canon writes, negative memory) are **bit-identical**; only candidate presentation/ordering may differ.
5. Performance budget test (tunable constants, actuals recorded in `DECISIONS.md`): embedding ≤200 candidates and DPP selection each complete within single-digit seconds on CPU.

**Exit criteria:** Snapshot invariance green; descriptor unit tests green; perf budget met; full suite green (flag off and on); I11 gate green.

**Commit:** `feat(generate): advisory DPP slate with hybrid graph+semantic descriptors, behind divergence.dpp (I5 snapshot-enforced)`

---

## 13. Stage 6 — Experiment, Rule-Based Decision & First Release

**Goal:** Measure the fusion blind, apply the pre-declared rule, ship the first release of NewPlugin. *(Another would-be human checkpoint, governed instead by D1.)*

**Entry criteria:** Stage 5 `DONE`.

**Tasks:**
1. Add arm `graph+generate+dpp` to `/kg-experiment`, reusing the vendored harness's blind protocol, scoring, and aggregation exactly (per `INVENTORY.md`).
2. Run the experiment per Decision Rule D1. Write `docs/fusion/EXPERIMENT.md`: setup, seeds, per-arm results, rule applied, outcome. Set `divergence.dpp` default accordingly. Either outcome is a valid release: the structural fusion ships regardless; only the flag's default is being decided.
3. Docs: README for NewPlugin written from scratch (identity, install via its own future marketplace path, `/kg-ideate` + flag docs, architecture summary, honest "what this does not guarantee" section in the spirit of both donors); CHANGELOG; migration guide for users of either donor (state importer, command mapping); credit + links to both donor repos (their URLs above) as the plugin's lineage. Test counts in the README are generated from `pytest` output — never hand-written (the 733/496 lesson).
4. Version per kickoff Q6 (default `0.1.0`) in manifest and engine metadata; final full-suite run; create annotated tag locally. Pushing to a remote, creating the GitHub repo, and marketplace publication are the human's steps — list them precisely in the final handoff note.

**Exit criteria:** Experiment executed and D1 applied; docs complete; suite green; I11 gate green (donors end exactly as they began); tag created locally; `PLAN_STATE.md` marks all stages `DONE` with the handoff note.

**Commits:** `feat(experiment): graph+generate+dpp arm + rule-based flag decision` · `docs(release): first release docs, lineage, migration guides` · local tag.

---

## 14. Pre-Declared Decision Rules (no human judgment required)

- **D1 — DPP flag default.** Run the vendored harness's standard fixture corpus on arms `graph+generate` vs `graph+generate+dpp` with **N = 5 seeds** (or the harness's own convention if it defines one — the harness convention wins). Flip `divergence.dpp` default to **on** iff the dpp arm's median blind score strictly exceeds the baseline arm's median **and** it wins on ≥ 4 of 5 seeds **and** no seed regresses by more than the harness's noise band (if none is defined, use 5% of the baseline median). Otherwise the default stays **off** and `EXPERIMENT.md` says so plainly. Total experiment wall time capped at 60 minutes; if exceeded, halve seeds to the harness minimum and note it.
- **D2 — Constant conflicts.** If donor code constants differ from this plan's README-derived values (judge weight/clip, monitor thresholds, embedder id): **code wins**, plan text is annotated in `INVENTORY.md`, no question asked.
- **D3 — Naming collisions.** If a proposed name (command, module, table) collides with an existing symbol, prefix with `divergence_`/`ideate_` and record in `DECISIONS.md`; no question asked.
- **D4 — Flaky donor-baseline tests.** Tests already failing at the Stage-0 donor baselines never block a stage commit; new failures always do.
- **D5 — Upstream drift.** ~~Donor repos are read at the Stage-0 SHAs. If a donor's remote gains new commits mid-build, ignore them; note the fact in `BASELINE.md`. Re-syncing is a post-release, human-initiated decision.~~
  > **[RETIRED 2026-07-09]** Both donor repositories have been unpublished by their author. There is no
  > upstream left to drift, and the "post-release, human-initiated" re-sync this rule deferred has been
  > foreclosed rather than taken. D5 governs nothing and requires nothing; the ID is kept, struck through,
  > so the historical record and every citation of it still resolve. Donor *integrity* is unaffected and
  > still enforced — that was always I11, not D5. See `DECISIONS.md`, "Decision Rule D5 retired".

---

## 15. Risk Register

| Risk | Mitigation |
|---|---|
| **Embedding creep** — "we have vectors, let's do semantic span retrieval" | Non-Goal 1 + I3/I4 firewall tests exist (Stage 2) before the temptation does. Any such idea → `BLOCKERS.md` as `REJECTED-BY-PLAN`. |
| Accidentally dirtying a donor (caches, temp files, editor artifacts) | I11 gate at every commit; baselines run on temp copies; donor paths never passed to writing tools. |
| Vendoring misses files → subtle breakage | Stage 1 parity gate: full donor test suite must pass in NewPlugin at baseline counts, deviations enumerated. |
| Model download unavailable at provision time | I9: cached artifact, lazy imports, clear error, core untouched; tested in Stage 2. |
| DPP/embedding too slow on big candidate sets | Stage 5 perf budget; cap candidate set; fall back to novelty-only ordering above the cap (advisory anyway). |
| Losing Cambrian's lightness | Stage 3 graphless guarantee: ideate runs with no graph, no sources, no setup beyond the plugin. |
| Doc drift (the 733/496 lesson) | Code-not-README rule (2.4); README counts generated from `pytest` output in Stage 6. |
| Suite runtime bloat | Mark experiment/selftest-heavy tests with a pytest mark excluded from the default run; full run required at stage commits. |
| Agent over-asks / stalls on questions | 6.5: one question per stage max, mandatory defaults, timeout ⇒ default. |

---

## 16. Definition of Done (first release)

- [ ] All stages `DONE` in `PLAN_STATE.md`; every exit criterion checked off in commit bodies.
- [ ] Both donor repos bit-identical to their Stage-0 state (I11 final check) — read and copied from, never modified.
- [ ] Invariant suite I1–I10 green in the default test path; I11 gate scripted and green.
- [ ] Stage-1 parity: vendored Sproutgraph suite green at baseline counts under the new identity.
- [ ] `/kg-ideate` delivers Cambrian parity (selftest green) with project-local state and no graph required.
- [ ] Pins materialize only through `kg_write`; adversarial suite green; verdict neutrality proven.
- [ ] `/kg-generate` geometry snapshot-proven advisory, behind `divergence.dpp`.
- [ ] `graph+generate+dpp` measured blind; D1 applied; `EXPERIMENT.md` written.
- [ ] Docs, CHANGELOG, migration guides, `ATTRIBUTION.md` with donor URLs @ SHAs.
- [ ] Local tag created; handoff note lists exactly what the human should create/push/publish.

---

## Appendix A — `PLAN_STATE.md` template

```markdown
# Fusion Plan State
Last updated: <ISO date> · Session: <n>
Handoff note: <empty unless stopping mid-plan>

| Stage | Status | Commit(s) | Notes |
|---|---|---|---|
| 0 Bootstrap + pinning | TODO/IN-PROGRESS/DONE | <sha> | |
| 1 Foundation vendoring | TODO | | |
| 2 Firewall + divergence port | TODO | | |
| 3 kg-ideate | TODO | | |
| 4 Materialization + neg. memory | TODO | | |
| 5 Generate geometry | TODO | | |
| 6 Experiment + release | TODO | | |
```

## Appendix B — Kickoff questionnaire (ask via AskUserQuestion; timeout ⇒ defaults; free-text answers accepted)

1. **Plugin name?** `Burgess` (Recommended — the Burgess Shale is where the Cambrian explosion's forms were preserved in stone: divergence + grounding in one word) · Use this repo directory's name · Type a custom name.
2. **Command prefix?** Keep `/kg-*` (Recommended — continuity for donor users) · Rename to a prefix derived from the plugin name.
3. **Divergence command name?** `/kg-ideate` (Recommended) · `/kg-diverge` · `/kg-cambrian`.
4. **Keep a thin dev CLI entry (`python -m kg_engine.divergence`)?** Yes (Recommended: zero-cost, aids debugging) · No (MCP/library only).
5. **Pin materialization trigger?** Explicit action per pin/batch (Recommended: nothing enters the graph implicitly) · Auto-materialize on pin when a graph exists.
6. **First version?** `0.1.0` (Recommended: new project, honest maturity signal) · `1.0.0` (signals the merged scope is complete).

*(Six questions; AskUserQuestion may batch them across up to two calls if needed. Defaults apply per question independently on timeout.)*

## Appendix C — Glossary (for a fresh session with zero context)

**Canon** — human-editable markdown files, one per node; the source of truth. **Derived** — regenerable NetworkX/SQLite projections of canon. **Span** — verbatim quote from a source document that an edge must carry to be `grounded`. **Hypothesized lane** — where unverified nodes/edges live until grounding. **`kg_write` / `kg_ground`** — the only doors: free-form writes enter as hypothesized; verdicts come only from grounding. **Reconciler** — re-quarantines forged grounded edges. **Negative memory** — permanently kept failed/rejected/discarded material, consulted to avoid re-proposing. **MAP-Elites** — archive keeping the best idea per behavior-descriptor bin, forcing coverage of the space. **DPP** — determinantal point process; selects a slate that is jointly diverse, not just individually novel. **k-NN novelty** — distance to nearest neighbors in embedding space. **Collapse monitor** — entropy + mean-pairwise-cosine tripwire against mode collapse. **Cliché map** — the "obvious answers" region to generate away from. **Mechanism-first** — every idea is tagged with the generative mechanism that produced it. **Vendoring** — copying donor code into this repo (with attribution), rather than depending on or modifying the donors. **BVSR** — blind variation, selective retention: Cambrian is the variation half; grounding (or the human, when no source exists) is the retention half.
