"""Multi-file reads take the project lock, so no command observes a cycle mid-write.

``ingest`` rewrites archive + candidates + surface embeddings + mechanism embeddings +
meta together under ``project_lock``. ``recall`` / ``metrics`` / ``parents`` each read
several of those files; reading unlocked can catch that rewrite in flight and pair a new
``archive.json`` with an old ``candidates.json`` — an elite whose record is not there
yet. Each read path must therefore snapshot under the same lock (best-effort: on timeout
it proceeds anyway, so a reader is never blocked for long by a writer).
"""

from __future__ import annotations

import contextlib

from kg_engine.divergence import pipeline
from kg_engine.divergence.state import State


def _axes():
    return {
        "domain": "d",
        "unit_of_generation": "idea",
        "axes": [
            {"name": "form", "type": "categorical"},
            {"name": "mechanism", "type": "open", "primary_novelty": True},
        ],
        "slate_size": 4,
        "candidates_per_generation": 6,
    }


def _cands(n):
    return [
        {
            "id": f"c-{i:03d}",
            "text": f"idea {i}: a wholly separate proposal about topic {i}",
            "descriptor": {"form": f"f{i}", "mechanism": f"approach {i}"},
        }
        for i in range(n)
    ]


def _count_read_locks(monkeypatch):
    """Wrap ``State.project_read_lock`` with a counter; returns the (mutable) count list."""
    entered = []
    real = State.project_read_lock

    def counting(self, *args, **kwargs):
        @contextlib.contextmanager
        def wrapper():
            entered.append(self.project)
            with real(self, *args, **kwargs):
                yield
        return wrapper()

    monkeypatch.setattr(State, "project_read_lock", counting)
    return entered


def _seeded_project(home):
    axes = _axes()
    pipeline.init_project("p", axes, seed=0, home=home, session="s1")
    pipeline.ingest("p", _cands(5), axes, seed=0, home=home)


def test_recall_metrics_parents_snapshot_under_one_lock(home, monkeypatch):
    _seeded_project(home)
    entered = _count_read_locks(monkeypatch)

    pipeline.recall("p", home=home)
    assert len(entered) == 1, "recall read comparisons/pins/discards/candidates unlocked"

    pipeline.metrics("p", home=home)
    assert len(entered) == 2, "metrics read archive/embeddings/meta unlocked"

    pipeline.parents("p", k=4, seed=0, home=home)
    assert len(entered) == 3, "parents read archive/embeddings/candidates/pins unlocked"


def test_read_lock_is_a_noop_on_a_project_that_does_not_exist(home):
    # A read-only command must not materialize state as a side effect: the lock dir would
    # otherwise create the project root, and there is no cycle to be inconsistent with.
    st = State("never-created", home=home)
    assert not st.root.exists()
    with st.project_read_lock():
        pass
    assert not st.root.exists()
