# Attribution

Burgess is a fusion of two MIT-licensed donor plugins by the same author. Code was **copied** (vendored) at the pinned SHAs below, never moved or modified upstream.

**Sproutgraph** has since been **retired and unpublished** by its author; Burgess is its continuation, and its pinned SHA resolves only against the local sibling checkout recorded in `scripts/donor_pins.json`. **Cambrian** was **republished** at [sergiparpal/cambrian](https://github.com/sergiparpal/cambrian) and has resumed development; its pinned SHA is still reachable from that repository's `HEAD`, so the claims in this file can be checked against the public tree with `git show a2adfa1`. Either way the MIT notices are retained below: the licence obligation survives the repositories, and the pinned SHAs — not the donors' current `HEAD`s — remain the identity of the vendored code.

| Donor | Pinned SHA | License |
|---|---|---|
| Sproutgraph (convergence spine) | `17c406632bb547a4abca3a824d9ffdc577e83891` | MIT (Copyright (c) 2026 Sergi Parpal) |
| Cambrian (divergence engine) | `a2adfa1d8b83c52ba17a79382811ea82012f8f99` | MIT (Copyright (c) 2026 sergiparpal) |

## Ported areas

### Stage 1 — Sproutgraph foundation (all from Sproutgraph @ `17c4066`, copied via `git archive`)

| Burgess path | Donor path | Adaptations |
|---|---|---|
| `scripts/kg_engine/**` (21 modules + templates) | `scripts/kg_engine/**` | identity strings only (`sproutgraph→burgess` in `__init__.py` docstring, `server.py` kg_ping name + `FastMCP("burgess")`, `backend.py` system prompt, `templates/graph_html.py` titles); `__version__` 0.6.1→0.1.0 |
| `scripts/{bootstrap.py, launch_server.mjs, _engine_resolve.mjs, canon_merge_driver.mjs, validate_plugin.py, f4_probe.py}` | same paths | identity strings (`[burgess]` log prefixes, `PLUGIN_NAME="burgess"`, `skills/burgess/SKILL.md` required path) |
| `commands/*.md` (8) | `commands/*.md` | tool-namespace prefix `mcp__plugin_sproutgraph_sproutgraph__` → `mcp__plugin_burgess_burgess__`; prose identity |
| `agents/*.md` (6) | `agents/*.md` | same namespace + prose identity |
| `hooks/{hooks.json, provision.mjs, provision.sh, provision.ps1, precontext.mjs, precontext.py}` | same paths | statusMessage + injected-context header identity |
| `skills/burgess/**` | `skills/sproutgraph/**` | directory + skill `name:` renamed; namespace prefix; prose identity |
| `pack/{pack.yaml, glossary.md}` | same paths | none |
| `tests/**` (51 files) | `tests/**` | identity strings only: `test_manifests.py` `_NS` namespace prefix; `test_fix_server.py` test-server name; no logic/count changes — suite green at baseline parity (731 passed, 2 skipped) |
| `.mcp.json` | `.mcp.json` | server key `sproutgraph→burgess` |
| `.claude-plugin/{plugin.json, marketplace.json}` | same paths | name `burgess`, version `0.1.0`, fused description; userConfig schema unchanged |
| `pyproject.toml` | `pyproject.toml` | version 0.1.0, description identity; package name `kg-engine` and all dependency pins unchanged |
| `.gitattributes`, `.github/workflows/ci.yml`, `examples/source.md` | same paths | `.gitattributes` merge-driver name unchanged (`kgcanon`); CI identical (it is donor-agnostic) |

Not vendored (donor-specific): `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `ARCHITECTURE.md`, `PROGRESS.md`, `images/`, `LICENSE` (Burgess has its own MIT), `.claude/settings.local.json` (untracked donor-local), `uv.lock` (untracked in donor by design — generated per machine).

### Stage 2 — Cambrian divergence engine (all from Cambrian @ `a2adfa1`, copied via `git archive`)

| Burgess path | Donor path | Adaptations |
|---|---|---|
| `scripts/kg_engine/divergence/*.py` (15 modules) | `skills/ideate/scripts/cambrian_engine/*.py` | package rename `cambrian_engine` → `kg_engine.divergence`; env prefix `CAMBRIAN_*` → `KG_DIVERGE_*` (incl. `KG_DIVERGE_EMBED_API*`); identity prose. **All algorithmic constants preserved verbatim** (I6/I7): judge weight `QUALITY_WEIGHT=0.3` (`pipeline.py`), fitness clip `lo=0.7, hi=1.3` (`diversity.bounded_quality`), monitor thresholds 0.55/0.50/0.15/0.80, k-NN k=5, ref cap 500, DPP pool 200, open niches 24×2 freeze, dedup taus, embedder id `minishlab/potion-multilingual-128M` — drift-guarded by ported `test_engine_config.py::test_defaults_match_module_constants`. |
| `scripts/kg_engine/divergence/state.py` | `cambrian_engine/state.py` | **transform (plan §3.2 + I10):** base dir `~/.cambrian` → project-local `<project>/.kg/diverge` (env `KG_DIVERGE_HOME` override); geometry files (archive/candidates/embeddings/mech_embeddings/open_nicher) moved into the session-ephemeral `session/` zone; new `session.json` + `begin_session()` (new id ⇒ wipe geometry + drop geometry-coupled meta series; pins/discards/comparisons/axes survive). |
| `scripts/kg_engine/divergence/pipeline.py` | `cambrian_engine/pipeline.py` | `init_project` gains `session=` (auto-generates a fresh id when omitted) and reports `session_id`/`new_session`. |
| `scripts/kg_engine/divergence/embed.py` | `cambrian_engine/embed.py` | I9 hardening: `model2vec` import + `from_pretrained` wrapped in `ConfigError` with actionable messages (hash fallback, provisioning pointer, "kg_* unaffected"); model artifact cached under `$KG_DATA/models` via `HF_HOME` when unset. |
| `scripts/kg_engine/divergence/config.py` | `cambrian_engine/config.py` | `generic_axes_path()` resolves domain templates beside the configured pack (`KG_PACK_PATH/../domains/`) with repo-layout fallback `pack/domains/`. |
| `pack/domains/**` (generic + _schema + 3 examples) | `skills/ideate/config/domains/**` | identity strings only; shipped as pack fragments per plan Stage 3 table. |
| `tests/fusion/divergence/*.py` (23 files, 226 tests) | `tests/*.py` | import/env renames; `test_bootstrap.py` NOT ported (its subject, Cambrian's own provisioning chain, is not vendored — Burgess uses Sproutgraph's chain per plan §3.2, deps extended); `test_init_reset.py` adapted to the session contract (re-init tests pass an explicit resume `session=`; new `test_new_session_wipes_geometry_keeps_pins`). |
| `scripts/bootstrap.py` (extension) | — | `probe_divergence` soft probe added beside `probe_leidenalg` (advisory, never fails provisioning — I9). |
| `pyproject.toml` (extension) | `skills/ideate/scripts/requirements.txt` | donor pins mirrored exactly: `numpy>=1.26,<3`, `scikit-learn>=1.4,<2`, `model2vec>=0.3,<0.9` (pyyaml already present). |

Stage-2 fix in vendored Sproutgraph tests: `test_rfix_server.py` bare `from conftest import` became ambiguous with two conftests in-tree → explicit-path load of the sibling conftest (no logic change); `test_e2e_generative.py` release-gate literal `0.6.1` → `0.1.0`.

### Stage 3 — /kg-diverge surface (adapting Cambrian @ `a2adfa1` chat-side material)

| Burgess path | Donor path | Adaptations |
|---|---|---|
| `commands/kg-diverge.md` | `skills/ideate/SKILL.md` + `references/loop.md` (folded) | rewritten for the MCP surface: the interpreter-location/bootstrap dance and tmp-file hand-offs are replaced by the six `kg_diverge_*` tools taking JSON directly; the loop's semantics (cliché map O_train/O_test, mechanism-first two-layer generation, descriptor discipline, validity-only prefilter, pins/discards/A-vs-B contract, monitor reactions incl. under_generation + variety_eroding, gap summary) preserved verbatim in spirit and constants |
| `skills/burgess/references/{operators,judge_rubric,axis_inference}.md` | `skills/ideate/references/*` | identity renames; `config/domains/` → `pack/domains/` path |
| `scripts/kg_engine/server.py` (+6 tools) | — (new, wrapping the ported pipeline) | `kg_diverge_init/ingest/remember/parents/metrics/recall`; lazy divergence imports (I3); state home forced to `<project>/.kg/diverge` |
| `scripts/kg_engine/divergence/importer.py` + `import-cambrian` CLI | — (new) | one-shot preference-memory importer from `~/.cambrian/<project>` (read-only on source; geometry + meta deliberately skipped and reported — I10) |
| `pack/pack.yaml` `divergence:` section + `pack.py` shape validator + `config.resolve_axes_source`/section-unwrap | `config/domains/_schema.md` concepts | one domain-pack format: extraction vocabulary + behavior axes in one file; deep validation stays in the divergence package (I3) |
