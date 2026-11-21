"""0.19.7: /burgess:kg-diverge keeps two diverse parents beside any number of pins, draws them again each
round, and asks about this round's ideas even when the slate does not change.

Field session andamiaje-ia-clasica (Windows, 2026-11-20/21, five rounds, 60 ideas, on 0.19.6):

* `kg_diverge_parents(project)` counted the pins toward the default k=4, so four pins left no room for a
  diverse parent. The agent raised k by hand: to 5 in round 3 on its own, then to pins + 2 at the user's
  request.
* The diverse parents came from the max-min walk away from the pins, which is fixed for a fixed set of
  pins: c2g and c2k in round 3 and again in round 4. Only a new pin (c4j) changed one of them in round 5.
* The slate is picked from the whole archive, and it was the same in rounds 2, 3 and 4. The ask pairs came
  only from the slate, so rounds 3 and 4 asked only about ideas of rounds 1 and 2, and none of the 24 ideas
  of those two rounds was ever compared.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from kg_engine.divergence import diversity, memory, pipeline
from kg_engine.divergence.state import State

REPO = Path(__file__).resolve().parents[1]
DIVERGE = (REPO / "commands" / "kg-diverge.md").read_text(encoding="utf-8")
SERVER = REPO / "scripts" / "kg_engine" / "server.py"

AXES = {"domain": "d", "unit_of_generation": "idea", "candidates_per_generation": 12, "slate_size": 4,
        "axes": [{"name": "form", "type": "categorical"},
                 {"name": "boldness", "type": "continuous", "range": [0.0, 1.0]},
                 {"name": "mechanism", "type": "open", "primary_novelty": True}]}
WORDS = ("tides orchards ledgers kites prisms anvils beacons mosaics embers compasses signals lanterns "
         "harbors glaciers looms quarries meadows sextants bellows cisterns dunes furnaces gardens hinges "
         "islands jetties kettles lattices mirrors nettles oars pulleys quivers rudders saddles thimbles "
         "umbrellas valves wagons yokes zithers acorns bridges canyons deltas engines fjords geysers").split()


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_PROJECT_DIR", raising=False)
    monkeypatch.setenv("KG_DIVERGE_HOME", str(tmp_path / "diverge-home"))


def _batch(tag: str, offset: int) -> list[dict]:
    """Twelve ideas in twelve distinct niches, with texts that share no word."""
    out = []
    for i in range(12):
        words = WORDS[(offset + 4 * i) % len(WORDS):][:4]
        out.append({"id": f"{tag}{i}", "text": " ".join(words),
                    "descriptor": {"form": f"f{i % 3}", "boldness": i / 11,
                                   "mechanism": f"{words[0]} {words[1]}"},
                    "genealogy": {"operator_id": "analogy", "parents": []}})
    return out


def _project(name: str = "brief") -> dict:
    pipeline.init_project(name, AXES, seed=1120, session="sess-1")
    res = pipeline.ingest(name, _batch("a", 0), AXES, seed=1120)
    assert len(State(name).read_candidates()) == 12, "fixture: every idea must be kept"
    return res


def _pin(name: str, ids: list[str]) -> None:
    for cid in ids:
        pipeline.remember(name, {"type": "pin", "id": cid})


def _split(res: dict) -> tuple[list[str], list[str]]:
    pinned = [p["id"] for p in res["parents"] if p["pinned"]]
    diverse = [p["id"] for p in res["parents"] if not p["pinned"]]
    return pinned, diverse


def _set_generation(name: str, generation: int) -> None:
    st = State(name)
    meta = st.read_meta()
    meta["cycles"] = generation
    st.write_meta(meta)


def _unit(*xs: float) -> list[float]:
    v = np.asarray(xs, dtype=np.float64)
    return list(v / np.linalg.norm(v))


# --------------------------------------------------------------------------- #
# 1. the parents keep two diverse elites beside any number of pins
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n_pins", [3, 4, 5])
def test_parents_keep_two_diverse_elites_beside_many_pins(n_pins):
    _project()
    pins = [f"a{i}" for i in range(n_pins)]
    _pin("brief", pins)

    pinned, diverse = _split(pipeline.parents("brief", seed=1120))

    assert pinned == pins
    assert len(diverse) == memory.MIN_DIVERSE_PARENTS == 2, (
        "the pins took every slot of the default k=4: no idea away from them was offered to breed from")
    assert not set(diverse) & set(pins)


@pytest.mark.parametrize("n_pins", [0, 1, 2])
def test_up_to_two_pins_the_default_still_gives_four_parents(n_pins):
    _project()
    _pin("brief", [f"a{i}" for i in range(n_pins)])

    pinned, diverse = _split(pipeline.parents("brief", seed=1120))

    assert len(pinned) == n_pins and len(pinned) + len(diverse) == 4


def test_an_explicit_k_above_the_floor_is_still_honoured():
    _project()
    _pin("brief", ["a0", "a1", "a2", "a3"])

    pinned, diverse = _split(pipeline.parents("brief", k=8, seed=1120))

    assert len(pinned) == 4 and len(diverse) == 4


def test_discards_stay_out_of_the_diverse_parents():
    _project()
    _pin("brief", ["a0", "a1", "a2", "a3"])
    for cid in ("a4", "a5", "a6", "a7", "a8", "a9"):
        pipeline.remember("brief", {"type": "discard", "id": cid})

    for generation in range(6):
        _set_generation("brief", generation)
        _, diverse = _split(pipeline.parents("brief", seed=1120))
        assert set(diverse) == {"a10", "a11"}


# --------------------------------------------------------------------------- #
# 2. the diverse parents are drawn again each round, reproducibly within one
# --------------------------------------------------------------------------- #
def test_the_same_round_returns_the_same_parents():
    _project()
    _pin("brief", ["a0", "a1"])

    first = pipeline.parents("brief", seed=1120)
    again = pipeline.parents("brief", seed=1120)

    assert first == again


def test_the_diverse_parents_change_between_rounds_with_the_same_pins():
    # Same archive, same pins; only the generation moves. The max-min walk of 0.19.6 returned the
    # same two outliers for every generation (field: c2g and c2k in rounds 3 and 4).
    _project()
    _pin("brief", ["a0", "a1"])

    draws = set()
    for generation in range(10):
        _set_generation("brief", generation)
        pinned, diverse = _split(pipeline.parents("brief", seed=1120))
        assert pinned == ["a0", "a1"] and len(diverse) == 2
        draws.add(frozenset(diverse))

    assert len(draws) > 1, "ten rounds with the same pins bred from the same two ideas every time"


# --------------------------------------------------------------------------- #
# 3. the draw itself
# --------------------------------------------------------------------------- #
def _orthogonal(n: int) -> np.ndarray:
    return np.eye(n, dtype=np.float64)


def test_d2_sampling_keeps_the_seeds_first_and_fills_to_k():
    vecs = _orthogonal(8)
    out = diversity.d2_sampling(vecs, 5, np.random.default_rng(3), seeds=[6, 2])

    assert out[:2] == [6, 2] and len(out) == 5 and len(set(out)) == 5


def test_d2_sampling_never_draws_an_exact_duplicate_while_another_row_is_left():
    # Row 4 duplicates the seed row 0; rows 1-3 are orthogonal to it.
    vecs = np.vstack([_orthogonal(4), _orthogonal(4)[0]])
    for s in range(40):
        out = diversity.d2_sampling(vecs, 4, np.random.default_rng(s), seeds=[0])
        assert 4 not in out
    # Once nothing else is left, the duplicate is the only row to draw, and the walk still fills k.
    full = diversity.d2_sampling(vecs, 5, np.random.default_rng(0), seeds=[0])
    assert sorted(full) == [0, 1, 2, 3, 4]


def test_d2_sampling_is_reproducible_for_one_generator_state_and_varies_across_states():
    vecs = _orthogonal(10)
    one = diversity.d2_sampling(vecs, 4, np.random.default_rng([7, 3]), seeds=[0])
    two = diversity.d2_sampling(vecs, 4, np.random.default_rng([7, 3]), seeds=[0])
    assert one == two
    draws = {tuple(diversity.d2_sampling(vecs, 4, np.random.default_rng([7, g]), seeds=[0]))
             for g in range(10)}
    assert len(draws) > 1


def test_select_parents_without_a_generator_is_still_the_max_min_walk():
    ids = [f"e{i}" for i in range(6)]
    emb = {cid: list(row) for cid, row in zip(ids, _orthogonal(6) + 0.1)}
    emb = {cid: list(np.asarray(v) / np.linalg.norm(v)) for cid, v in emb.items()}

    out = memory.select_parents(ids, emb, pins=["e0"], k=4)

    pool = ids[1:]
    combined = np.vstack([emb["e0"]] + [emb[i] for i in pool])
    walk = diversity.farthest_point_sampling(combined, 4, seeds=[0])
    assert out == ["e0"] + [pool[i - 1] for i in walk if i >= 1]


# --------------------------------------------------------------------------- #
# 4. one question brings in this round's ideas when the slate has none
# --------------------------------------------------------------------------- #
W = (0.5, 0.3, 0.2)


def _slate_and_fresh():
    emb = {"s0": _unit(1, 0, 0, 0, 0, 0), "s1": _unit(0, 1, 0, 0, 0, 0),
           "s2": _unit(0, 0, 1, 0, 0, 0), "s3": _unit(0, 0, 0, 1, 0, 0),
           "f0": _unit(0, 0, 1, 0, 0.1, 0), "f1": _unit(0, 0, 0, 0, 0, 1)}
    slate = [{"id": "s0", "fitness": 1.0, "novelty": 0.9}, {"id": "s1", "fitness": 1.0, "novelty": 0.8},
             {"id": "s2", "fitness": 1.0, "novelty": 0.1}, {"id": "s3", "fitness": 1.0, "novelty": 0.1}]
    fresh = [{"id": "f0", "fitness": 1.0, "novelty": 0.5}, {"id": "f1", "fitness": 1.0, "novelty": 0.5}]
    return slate, fresh, emb


def _ids(pairs):
    return [tuple(p[:2]) for p in pairs]


def test_a_slate_without_this_rounds_ideas_gives_up_its_second_question():
    slate, fresh, emb = _slate_and_fresh()
    old = memory.select_ask_pairs(slate, emb, [], max_pairs=2, weights=W)
    new = memory.select_ask_pairs(slate, emb, [], max_pairs=2, weights=W, fresh=fresh)

    assert all(a.startswith("s") and b.startswith("s") for a, b in _ids(old))
    assert _ids(new)[0] == _ids(old)[0]
    assert _ids(new)[1] == ("s2", "f0"), "the closest pair that names an idea of this round"
    assert "brings in an idea from this round" in new[1][2]


def test_pairs_that_already_name_this_rounds_idea_stay_as_they_were():
    slate, fresh, emb = _slate_and_fresh()
    # s1 is new this round and sits in the best slate pair (s0, s1): nothing to swap.
    fresh = fresh + [{"id": "s1", "fitness": 1.0, "novelty": 0.8}]

    assert (memory.select_ask_pairs(slate, emb, [], max_pairs=2, weights=W, fresh=fresh)
            == memory.select_ask_pairs(slate, emb, [], max_pairs=2, weights=W))


def test_the_swapped_in_pair_is_never_one_already_answered():
    slate, fresh, emb = _slate_and_fresh()
    answered = [{"type": "comparison", "winner": "f0", "loser": "s2"}]

    pairs = _ids(memory.select_ask_pairs(slate, emb, answered, max_pairs=2, weights=W, fresh=fresh))

    assert ("s2", "f0") not in pairs and ("f0", "s2") not in pairs
    assert any("f0" in p or "f1" in p for p in pairs)


def test_a_slate_with_every_pair_answered_still_asks_about_this_round():
    slate, fresh, emb = _slate_and_fresh()
    ids = [s["id"] for s in slate]
    answered = [{"type": "comparison", "winner": a, "loser": b}
                for i, a in enumerate(ids) for b in ids[i + 1:]]

    assert memory.select_ask_pairs(slate, emb, answered, max_pairs=2, weights=W) == []
    pairs = _ids(memory.select_ask_pairs(slate, emb, answered, max_pairs=2, weights=W, fresh=fresh))
    assert len(pairs) == 1 and ("f0" in pairs[0] or "f1" in pairs[0])


def test_no_questions_asked_for_means_none_returned():
    slate, fresh, emb = _slate_and_fresh()
    assert memory.select_ask_pairs(slate, emb, [], max_pairs=0, weights=W, fresh=fresh) == []


def test_an_ingest_whose_slate_left_out_the_round_asks_about_it(monkeypatch):
    r1 = _project()
    stuck = list(r1["slate_ids"])

    def same_slate(cyc, discards=None):
        return [pipeline._slate_item(cyc.cand_store[i]) for i in stuck], list(stuck)

    monkeypatch.setattr(pipeline, "_select_slate", same_slate)
    r2 = pipeline.ingest("brief", _batch("b", 2), AXES, seed=1120)

    assert r2["slate_ids"] == stuck
    first, second = _ids(r2["ask_pairs"])
    assert set(first) <= set(stuck)
    assert any(cid.startswith("b") for cid in second), (
        "the slate did not change, and neither question named an idea of this round")


def test_round_one_keeps_its_questions_on_the_slate():
    r1 = _project()
    assert all(set(p[:2]) <= set(r1["slate_ids"]) for p in r1["ask_pairs"])
    assert r1["ask_pairs"] and all("brings in" not in p[2] for p in r1["ask_pairs"])


# --------------------------------------------------------------------------- #
# 5. the command and the tools say so
# --------------------------------------------------------------------------- #
def _tool_doc(name: str) -> str:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name and any(
                ast.unparse(d).startswith("mcp.tool") for d in node.decorator_list):
            return _flat(ast.get_docstring(node) or "")
    raise AssertionError(f"no MCP tool {name}")


def test_the_parents_tool_says_what_it_returns():
    doc = _tool_doc("kg_diverge_parents")
    assert "at least two diverse archive elites however many pins there are" in doc
    assert "no need to raise k yourself" in doc
    assert "the next round draws again" in doc
    assert "DPP-sampled" not in doc, "the parents were never DPP-sampled"


def test_the_ingest_tool_says_a_question_can_name_an_idea_off_the_slate():
    doc = _tool_doc("kg_diverge_ingest")
    assert "even an idea the slate left out" in doc


def test_the_command_says_how_parents_and_questions_work():
    text = _flat(DIVERGE)
    assert "A pair can name an idea of this round that the slate left out" in text
    assert "Ask it by its id, as you explained it in the rest of the round" in text
    assert "every pin plus at least two diverse ideas, however many pins there are, so leave `k` alone" in text
    assert "they change from one round to the next even when the pins do not" in text
