"""A candidate id is a PRIMARY KEY, so the engine must reject collisions loudly.

One id keys every downstream store at once: the archive's ``elite_id``, the candidate
record store, the surface and mechanism embedding stores, pins/discards, and the slate's
``embedding_ref``. Two candidates sharing an id therefore both "win" a niche while only
the LAST record survives in the store — so an existing niche silently ends up pointing at
a different idea's text, coords and embedding, and the slate can render the same item
twice. Dedup does not catch this: it compares *text*, not ids.

Both halves are covered here: the batch-local collision (two candidates in one
generation) and the cross-generation one (a later cycle, or a fresh agent that restarted
its ``c-0001`` counter, reusing an id under different text). Re-submitting a candidate
VERBATIM stays legal — that is a harmless no-op dedup drops.
"""

from __future__ import annotations

import pytest

from kg_engine.divergence import config, pipeline, selftest
from kg_engine.divergence.config import ConfigError
from kg_engine.divergence.state import State


def _generic():
    return config.load_generic_axes().to_dict()


def _init(project, home):
    """Init the project and return ``(axes, candidates_per_generation)``."""
    axes = _generic()
    pipeline.init_project(project, axes, seed=0, home=home, session="s1")
    return axes, int(State(project, home=home).read_meta()["candidates_per_generation"])


def test_duplicate_id_within_a_batch_is_rejected(home):
    axes, n = _init("dup", home)
    cands = selftest.diverse_candidates(n, gen=0)
    cands[-1]["id"] = cands[0]["id"]  # two DIFFERENT ideas, one id
    with pytest.raises(ConfigError):
        pipeline.ingest("dup", cands, axes, seed=0, home=home)


def test_duplicate_id_names_the_offender(home):
    # The operator has to know WHICH id collided; a bare "duplicate id" is unactionable
    # in a twelve-candidate generation.
    axes, n = _init("dupname", home)
    cands = selftest.diverse_candidates(n, gen=0)
    cands[-1]["id"] = cands[0]["id"]
    with pytest.raises(ConfigError, match=cands[0]["id"]):
        pipeline.ingest("dupname", cands, axes, seed=0, home=home)


def test_id_reuse_across_generations_with_new_text_is_rejected(home):
    # The cross-generation twin: gen 1 reuses a gen-0 id under different text. Left
    # unguarded, that overwrites the archived idea the id names while the niche it is
    # already elite of keeps pointing at it.
    axes, n = _init("reuse", home)
    gen0 = selftest.diverse_candidates(n, gen=0)
    pipeline.ingest("reuse", gen0, axes, seed=0, home=home)
    victim = gen0[0]["id"]
    assert victim in State("reuse", home=home).read_candidates()

    later = selftest.diverse_candidates(n, gen=1)
    assert later[0]["text"] != gen0[0]["text"]  # genuinely a different idea
    later[0]["id"] = victim
    with pytest.raises(ConfigError, match=victim):
        pipeline.ingest("reuse", later, axes, seed=0, home=home)


def test_verbatim_resubmission_is_allowed(home):
    # Same id, byte-identical text: not a collision, just a no-op the dedup pass drops
    # (identical text embeds to cosine 1.0 > tau). Rejecting it would break a legitimate
    # retry of a generation whose previous submission failed part-way.
    axes, n = _init("verbatim", home)
    first = selftest.diverse_candidates(n, gen=0)
    pipeline.ingest("verbatim", first, axes, seed=0, home=home)

    res = pipeline.ingest("verbatim", first, axes, seed=0, home=home)  # must not raise
    assert res["slate"], "the archive from generation 0 is still slated"

    store = State("verbatim", home=home).read_candidates()
    for c in first:
        if c["id"] in store:  # survivors only; dedup may have dropped near-twins
            assert store[c["id"]]["text"] == c["text"]  # unchanged, not rewritten


def test_archive_never_names_one_elite_from_two_niches(home):
    # The structural consequence the guards exist to protect: after an ACCEPTED ingest,
    # no id is the elite of two niches, and every elite resolves to a record holding the
    # text that was actually submitted under that id.
    axes, n = _init("ok", home)
    submitted = selftest.diverse_candidates(n, gen=0)
    pipeline.ingest("ok", submitted, axes, seed=0, home=home)

    st = State("ok", home=home)
    elite_ids = [n["elite_id"] for n in st.read_archive()["niches"].values() if n["elite_id"]]
    assert elite_ids, "fixture should place at least one elite"
    assert len(elite_ids) == len(set(elite_ids)), "one id is the elite of two niches"

    store = st.read_candidates()
    text_by_id = {c["id"]: c["text"] for c in submitted}
    for eid in elite_ids:
        assert eid in store, f"elite {eid} has no candidate record"
        assert store[eid]["text"] == text_by_id[eid], f"elite {eid} names another idea's text"
