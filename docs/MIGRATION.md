# Migrating to Burgess

Burgess vendors both donors at pinned SHAs (Sproutgraph @ `17c4066`, Cambrian @
`a2adfa1`). Sproutgraph has since been retired and is no longer published —
Burgess is its continuation. Cambrian was republished at
[sergiparpal/cambrian](https://github.com/sergiparpal/cambrian) and develops
independently again; Burgess does not track it, and the pin above stays fixed at
the tree the fusion copied. This guide maps what you had to what Burgess does.

## From Sproutgraph

Burgess **is** Sproutgraph at baseline parity, plus the divergence side. Nothing
you know changes:

- **Commands:** all eight `/kg-*` commands keep their names and semantics
  (`/kg-build`, `/kg-ground`, `/kg-query`, `/kg-eval`, `/kg-experiment`,
  `/kg-generate`, `/kg-perturb`, `/kg-view`). New: `/kg-diverge`.
- **Data:** the canon (`canon/*.md`), derived layer, audit ledger, reconcile
  state, and pack format are unchanged — an existing Sproutgraph project
  directory works as-is. The plugin/server identity is `burgess` (tool
  namespace `mcp__plugin_burgess_burgess__*`), and the plugin data dir is
  Burgess's own (a fresh venv provisions on first load).
- **pack.yaml:** unchanged schema, plus an OPTIONAL `divergence:` section
  (behavior axes for /kg-diverge + the `dpp` flag). Packs without it work
  untouched.
- **/kg-experiment:** the four donor arms are unchanged; a fifth
  `graph+generate+dpp` arm measures the advisory-DPP presentation.
- **New, opt-in:** `divergence.dpp: true` in the pack (or `dpp: true` per
  `kg_generate` call) presents generate slates in advisory-DPP order with
  geometry labels. Grounding behavior is bit-identical either way
  (snapshot-tested).

Uninstall/disable the Sproutgraph plugin before enabling Burgess in the same
project — they register the same `/kg-*` command names.

## From Cambrian

The engine, constants, and loop semantics are preserved; the packaging moved
into the graph plugin's trust boundary:

| Cambrian | Burgess |
|---|---|
| `/cambrian:ideate <brief>` | `/kg-diverge <brief>` |
| Skill drives a local CLI (`python -m cambrian_engine …` + tmp-file hand-offs) | Command drives MCP tools (`kg_diverge_init/ingest/remember/parents/metrics/recall/materialize`) — JSON in, JSON out |
| State in `~/.cambrian/<project>/` | Project-local `.kg/diverge/<brief-slug>/` (git-friendly) |
| MAP-Elites archive persists across sessions | **Session-ephemeral** (I10): a new session wipes the geometry archive; pins, discards and comparisons persist. The knowledge graph is the durable archive — pin what matters, materialize it. |
| `CAMBRIAN_EMBEDDER` / `CAMBRIAN_HOME` / `CAMBRIAN_DEBUG` | `KG_DIVERGE_EMBEDDER` / `KG_DIVERGE_HOME` / `KG_DIVERGE_DEBUG` |
| Domain configs `config/domains/*.yaml` | Pack fragments `pack/domains/*.yaml` (schema + engine-tuning defaults: `pack/domains/_schema.md`), or a `divergence:` section inside `pack.yaml` |
| `python -m cambrian_engine selftest` | `python -m kg_engine.divergence selftest` — the same correctness contract: variety gate (engine beats single-shot on mean pairwise distance +0.10, Vendi +0.5, and entropy; DPP beats first-N +0.01), null no-regression check, within-niche fitness check, collapse-trip-and-reversal, state files written (gate details: `skills/burgess/references/tools.md` §2.4) |
| — | New: pinned ideas can **materialize** into the graph's hypothesized lane and earn grounding (or permanent falsification, which auto-discards them from the brief) |

**Preference memory importer** (one-shot, read-only on the source):

```bash
python -m kg_engine.divergence import-cambrian --project <brief-slug> \
    [--from ~/.cambrian/<old-project>]
```

Pins, discards, and A-vs-B comparisons are mapped per domain into
`.kg/diverge/<brief-slug>/memory/`. Geometry files (`archive.json`,
`candidates.json`, `embeddings.json`, `mech_embeddings.json`,
`open_nicher.json`) are deliberately NOT imported — session-ephemeral by
design — and `meta.json`/`axes.json` are re-created by `kg_diverge_init`; the
importer reports both as `skipped` so nothing disappears silently. It is
read-only on the source and reports
`{ok, imported: {<domain>: {pins, discards, comparisons}}, skipped, errors}`.

The engine constants carried over unchanged, drift-guarded by tests: judge
fitness blended at weight 0.3 and clipped to a [0.7, 1.3] multiplier; monitor
thresholds mean-cosine 0.55 / entropy 0.50 / relative margin +0.15 with
ceiling 0.80; k-NN novelty k=5; DPP pool cap 200; open-axis Voronoi niching
24 cells frozen after 2×24 mechanisms; per-embedder near-duplicate taus
(static 0.93, hash 0.92, local 0.94); embedder `potion-multilingual-128M`.
The full constants table with per-domain overrides lives in
`pack/domains/_schema.md`; the tool-by-tool reference in
`skills/burgess/references/tools.md` §1B.
