"""kg_engine — the deterministic graph engine for the Burgess Claude Code plugin.

Submodules (the full map; review-r5 completed a 9-of-22 partial list):
  model       three axes, Node/Edge, span verification, frontmatter I/O, shared vocabularies
  envconfig   stdlib leaf: env-value cleaner + project/data/source/pack resolution rules
  atomicio    stdlib leaf: crash-safe atomic writes (temp+fsync+replace, Windows retry)
  dirlock     stdlib leaf: atomic-mkdir directory lock (heartbeat, steal-with-re-validation) for bootstrap
  graphio     node-link JSON <-> NetworkX helpers shared by projector/generate/harness
  sources     SourceSet (file|dir|glob), source-aware span verification, `##` section splitting
  scrub       egress PII/secret scrubbing with consistent placeholders
  pack        domain pack + glossary contract/loader/coverage
  boundary    P_write validation -> dispositions (span-present, never-forge-a-verdict, dedup)
  canon       crash-safe Markdown canon I/O, git-as-rollback, lease lock
  groundaudit the crash-safe append-only grounding-audit log (§1.8 writer half)
  reconciler  P_reconcile: mtime/size pre-filter + full sweep, OOB-verdict re-quarantine
  canonmerge  semantic git merge driver for canon notes (never forges a verdict)
  projector   canon -> node-link graph.json + SQLite + Leiden + ranks + kg_context/kg_agenda
  pathing     the pure algorithm behind kg_explain_path (deterministic BFS over the derived graph)
  generate    structural idea candidates (bridge|seed|compression|regroup|transplant|ensemble|periphery)
  operations  the four endo operations (collapse|explode|regroup|open) via the propose lane
  advisory_geometry  hybrid-descriptor DPP ordering for kg_generate (advisory, I5)
  waves       bounded-parallel extraction wave planning for /kg-build
  export      graph.html + GRAPH_REPORT.md render of the derived layer
  harness     annotation agreement, specificity metric, ideation scoring
  backend     headless API extraction for CI (same boundary as the interactive flow)
  lightrag_arm  optional LightRAG comparison arm (experiment-only)
  server      the MCP server (KGEngine facade + FastMCP tool surface)
  divergence  the MAP-Elites/DPP ideation engine (own package; import-firewalled, I3)
"""

__version__ = "0.4.1"
