"""Burgess divergence engine (ported from Cambrian, firewalled below grounding).

Deterministic, domain-agnostic diversity engine that owns the anti-convergence
math for the `/kg-diverge` flow: embeddings, MAP-Elites archive, geometric
novelty, DPP diverse selection, an anti-collapse monitor, and local preference
memory.

The LLM parts (variation operators, the skeptical judge prefilter) are performed
by the agent, not here. This package never judges novelty: geometry owns
diversity, the judge only filters validity/on-brief upstream.

Fusion invariants (FUSION_PLAN §4). The **import firewall (I3)** runs in BOTH
directions and is test-enforced in both (tests/fusion/test_divergence_firewall.py):
no grounding/verdict/reconciler module may import this package, and this package
may import only the stdlib, its numeric deps, its own siblings, and the two
capability-free engine leaves `atomicio`/`envconfig` — so nothing here can name
an `EpistemicState`, let alone write one. That is what makes the verdict monopoly
(**I1**: only `kg_ground` produces verdicts) unbreakable from the geometry side,
rather than merely unexercised. Its vectors never touch canon or the query DB
(I4), and everything it computes is advisory — embeddings measure dispersion,
never truth (I5).
"""

__version__ = "0.3.2"
