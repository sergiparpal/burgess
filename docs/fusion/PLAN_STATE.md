# Fusion Plan State
Last updated: 2026-07-02 · Session: 1
Handoff note: **ALL STAGES DONE AND PUBLISHED.** The publishing steps were originally reserved for the human (plan §5.4); the human explicitly instructed the agent to execute them, and they are complete:

1. ✅ **Pushed:** `main` (2906cac..179fed8) + annotated tag `v0.1.0` → https://github.com/sergiparpal/Burgess
2. ✅ **GitHub Release created:** https://github.com/sergiparpal/Burgess/releases/tag/v0.1.0 (notes from CHANGELOG 0.1.0).
3. ✅ **Marketplace live + installed:** `claude plugin marketplace add sergiparpal/Burgess` → `claude plugin install burgess@sergiparpal` (user scope). Component inventory verified: 10 skills, 6 agents, 2 hooks, 1 MCP server (~1.5k always-on tokens).
4. ✅ **Production smoke through the INSTALLED plugin** (real headless Claude Code sessions in a scratch project): SessionStart hook auto-provisioned the venv into the plugin data dir (divergence deps probe OK); `kg_ping` → `{version: 0.1.0, pack_loaded: true, …}`; `kg_diverge_init` → project-local `.kg/diverge/<brief>/` state with session.json + ephemeral session/ zone. Note: the MCP server correctly does NOT start until the REQUIRED `source_path` userConfig is set — it was set at user scope to `~/.claude/burgess-demo-source.md` (a copy of examples/source.md); reconfigure per project with `/plugin configure burgess@sergiparpal` for real use.
5. Donors remain untouched and pinned (I11 green at and after every commit); ~~re-syncing to any future upstream Sproutgraph/Cambrian commits is a post-release decision (D5)~~.

> **D5 is retired (2026-07-09).** Both donor repositories have been unpublished, so there is no upstream
> to re-sync from and no post-release decision left to take. Donor *integrity* is unaffected — that is
> I11, which still runs green against the local sibling checkouts. See `DECISIONS.md`.
>
> **Amended (2026-07-31).** Cambrian is published again (https://github.com/sergiparpal/cambrian) and has
> resumed development; Sproutgraph remains unpublished. D5 stays retired — the build is over, so no
> build-time rule applies — and I11 now asserts that each pinned SHA is *reachable* from its donor's
> `HEAD`, not that the donor still sits at it. See `DECISIONS.md`.

| Stage | Status | Commit(s) | Notes |
|---|---|---|---|
| 0 Bootstrap + pinning | DONE | 2906cac | Donors pinned (Sproutgraph 17c4066, Cambrian a2adfa1); baselines 731+2s / 240+selftest; kickoff answered live (all 6); INVENTORY complete, 8 discrepancies documented; I11 gate installed |
| 1 Foundation vendoring | DONE | 7bf43db | 731+2 at exact baseline parity under burgess identity; provisioning smoke uv+pip; validate --strict; MCP load (20 tools); engine round-trip green |
| 2 Firewall + divergence port | DONE | ad2a318 | Firewall tests first (I1-I4) then port: 15 modules, 226 tests; I9+I10 suites; 973 passed + 2 skipped; provisioning incl. divergence deps; dev CLI selftest ok |
| 3 kg-diverge (plan: "kg-ideate") | DONE | e9c9d79 | 6 kg_diverge_* MCP tools; commands/kg-diverge.md + 3 references; pack.yaml divergence: section (one format); import-cambrian; graphless e2e green; 979 passed + 2 skipped |
| 4 Materialization + neg. memory | DONE | 7579798 | kg_diverge_materialize (27 tools): propose lane only; fate-sync folds grounding failures into discards (I8 both paths); adversarial suite; verdict neutrality; e2e; 989 passed + 2 skipped |
| 5 Generate geometry | DONE | c3aa127 | divergence.dpp flag (default off) + per-call override; hybrid axes + grounded-hub cliché map + DPP order; I5 snapshot bit-identical (frozen clocks); perf 0.008s/0.004s per 200; 997 passed + 2 skipped |
| 6 Experiment + release | DONE | df34bf3 + (release commit) | graph+generate+dpp arm + dpp_verdict; blind 12-prompt run per pre-declared D1 → ALL criteria fail → default stays OFF (EXPERIMENT.md); README/CHANGELOG/MIGRATION; README count generated from pytest (1000 passed, 2 skipped); tag v0.1.0 local |

## Definition of Done (plan §16) — final check

- [x] All stages DONE; every exit criterion checked off in commit bodies.
- [x] Both donor repos bit-identical to Stage-0 state (I11 green at every commit incl. this one).
- [x] Invariant suite I1–I10 green in the default test path; I11 gate scripted (`scripts/check_donors_clean.py`) and green.
- [x] Stage-1 parity: vendored Sproutgraph suite green at baseline counts under the new identity.
- [x] `/kg-diverge` delivers Cambrian parity (selftest green: variety gate, DPP-beats-first-N, null check, collapse reversal) with project-local state and no graph required.
- [x] Pins materialize only through the propose door; adversarial suite green; verdict neutrality proven.
- [x] `/kg-generate` geometry snapshot-proven advisory, behind `divergence.dpp`.
- [x] `graph+generate+dpp` measured blind; D1 applied (default stays off); EXPERIMENT.md written.
- [x] Docs: README (counts generated from pytest), CHANGELOG, docs/MIGRATION.md, ATTRIBUTION.md with donor URLs @ SHAs, LICENSE (MIT).
- [x] Local annotated tag v0.1.0; this handoff note lists exactly what the human creates/pushes/publishes.
