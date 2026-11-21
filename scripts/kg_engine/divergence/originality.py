"""Advisory originality measurement: distance from an "obvious-set".

This module is **measurement only**. Unlike geometric novelty (which has no
external referent — see :mod:`novelty`), originality here is scored against a set
of *obvious* reference vectors (clichés / would-be prior-art anchors): how far an
idea sits from the nearest obvious one.

Hard boundary — load-bearing: originality is **never** wired into the selection
geometry (the DPP ``q`` / kernel in :mod:`diversity`), **never** gates the
self-test (it is excluded from ``ok``), and **never** steers the engine. The skill
uses the same idea at *generation* time (repel clichés); the engine only ever
*measures* it. Keeping it out of selection is what stops a cliché signal from
pruning variety.

Vectors are assumed **L2-normalized** (cosine similarity == dot product),
consistent with every embedder in :mod:`embed`.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def originality_scores(idea_vecs, obvious_vecs) -> dict[str, Any]:
    """Distance-to-obvious for each idea vector.

    For each idea, ``originality = 1 - max cosine similarity to any vector in
    ``obvious_vecs``. Higher == further from the obvious set. Both inputs are
    assumed L2-normalized so cosine is a plain dot product.

    Returns ``{"per_idea": [...], "slate_mean": float}``. Degenerate inputs are
    handled gracefully (no exception, no NaN): an empty ``obvious_vecs`` (no
    referent to be far from) yields ``0.0`` for every idea and a ``0.0`` mean; an
    empty ``idea_vecs`` yields an empty ``per_idea`` and a ``0.0`` mean. A single
    vector passed flat (1-D) is treated as one row, not silently dropped.
    """
    ideas = np.asarray(idea_vecs, dtype=np.float32)
    obvious = np.asarray(obvious_vecs, dtype=np.float32)
    # Promote a single flat vector to one row so it isn't read as "zero rows".
    if ideas.ndim == 1 and ideas.size:
        ideas = ideas.reshape(1, -1)
    if obvious.ndim == 1 and obvious.size:
        obvious = obvious.reshape(1, -1)
    n = ideas.shape[0] if ideas.ndim == 2 else 0
    # No ideas, or no obvious referent (or a malformed referent): zero result.
    if n == 0 or obvious.ndim != 2 or obvious.shape[0] == 0:
        return {"per_idea": [0.0] * n, "slate_mean": 0.0}
    sims = ideas @ obvious.T  # (n, m) cosine similarities (rows L2-normalized)
    max_sims = sims.max(axis=1)
    # Cosine is in [-1, 1] so 1 - max_sim is in [0, 2]; clip to bound the score if
    # the L2-normalization precondition is ever violated upstream.
    per_idea = np.clip(1.0 - max_sims, 0.0, 2.0)
    return {
        "per_idea": [round(float(x), 4) for x in per_idea],
        "slate_mean": round(float(per_idea.mean()), 4),
    }


def nearest_ideas(obvious_vecs, idea_vecs, idea_ids, k: int = 3) -> list[list[dict[str, Any]]]:
    """For each obvious vector, the ``k`` ideas closest to it: ``[{"id", "similarity"}, ...]``, most
    similar first, ties broken by id. Measurement only, like :func:`originality_scores`: the session's
    end reports it for the clichés it held out (0.20.0), and nothing selects or ranks with it.

    Both inputs are assumed L2-normalized. Degenerate inputs give empty lists, never an exception."""
    obvious = np.asarray(obvious_vecs, dtype=np.float32)
    ideas = np.asarray(idea_vecs, dtype=np.float32)
    if obvious.ndim == 1 and obvious.size:
        obvious = obvious.reshape(1, -1)
    if ideas.ndim == 1 and ideas.size:
        ideas = ideas.reshape(1, -1)
    m = obvious.shape[0] if obvious.ndim == 2 else 0
    ids = [str(i) for i in idea_ids]
    if (m == 0 or ideas.ndim != 2 or ideas.shape[0] == 0 or ideas.shape[0] != len(ids)
            or ideas.shape[1] != obvious.shape[1] or k <= 0):
        return [[] for _ in range(m)]
    sims = obvious @ ideas.T  # (m, n)
    out: list[list[dict[str, Any]]] = []
    for row in sims:
        order = sorted(range(len(ids)), key=lambda j: (-float(row[j]), ids[j]))[:k]
        out.append([{"id": ids[j], "similarity": round(float(row[j]), 2)} for j in order])
    return out
