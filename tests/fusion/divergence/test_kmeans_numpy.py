"""The open-axis k-means runs on numpy alone (0.19.3).

``FrozenVoronoiNicher.fit`` used ``sklearn.cluster.KMeans`` until 0.19.3. On a Windows
install with Smart App Control on, importing ``sklearn.cluster`` loads compiled modules
that Application Control refused, and the refusal hung the engine on the one ingest that
crosses the freeze threshold (a /burgess:kg-diverge session at 62 ideas, 2026-11-18). These
tests pin the replacement: deterministic, sound on separable data, total on degenerate
data, and free of any sklearn import.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from kg_engine.divergence.archive import FrozenVoronoiNicher, kmeans

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def _blobs(seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    means = np.array([[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]])
    pts = np.concatenate([m + rng.normal(scale=0.3, size=(40, 3)) for m in means])
    return pts, means


def test_same_seed_same_centers():
    x, _ = _blobs()
    assert np.array_equal(kmeans(x, 3, seed=7), kmeans(x, 3, seed=7))


def test_recovers_separated_clusters():
    x, means = _blobs()
    centers = kmeans(x, 3, seed=0)
    # every true mean has a fitted center within the blob's noise
    for m in means:
        assert np.min(np.linalg.norm(centers - m, axis=1)) < 0.3


def test_degenerate_data_still_returns_k_finite_rows():
    x = np.ones((10, 4))  # every point identical: k-means++ has zero distances to sample from
    centers = kmeans(x, 3, seed=0)
    assert centers.shape == (3, 4)
    assert np.all(np.isfinite(centers))


def test_k_bounds():
    x, _ = _blobs()
    assert kmeans(x[:5], 5, seed=0).shape == (5, 3)
    with pytest.raises(ValueError):
        kmeans(x[:5], 6, seed=0)
    with pytest.raises(ValueError):
        kmeans(x[:5], 0, seed=0)


def test_fit_clamps_k_and_unit_normalizes():
    x, _ = _blobs()
    nicher = FrozenVoronoiNicher.fit(x[:4], k=32, seed=0)
    assert nicher.k == 4
    assert np.allclose(np.linalg.norm(nicher.centroids, axis=1), 1.0, atol=1e-5)


def test_fit_imports_no_sklearn():
    """The freeze must not depend on sklearn being importable: block it and fit anyway."""
    code = textwrap.dedent(
        """
        import sys, importlib.abc

        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "sklearn" or name.startswith("sklearn."):
                    raise ImportError("blocked by test: " + name)
                return None

        sys.meta_path.insert(0, Block())
        import numpy as np
        from kg_engine.divergence.archive import FrozenVoronoiNicher
        x = np.random.default_rng(0).normal(size=(64, 8))
        n = FrozenVoronoiNicher.fit(x, k=32, seed=1116)
        assert n.k == 32 and not any(m.startswith("sklearn") for m in sys.modules)
        print("ok")
        """
    )
    env = dict(os.environ, PYTHONPATH=str(SCRIPTS) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("ok")
