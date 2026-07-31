"""A pin can outlive the idea it names, and ``parents`` must say so rather than breed
from nothing.

``init-project`` resets the geometry (archive / candidates / embeddings) on an axes
change but deliberately PRESERVES preference memory, so a pinned id can survive with no
candidate record behind it. ``select_parents`` always keeps pins, so such an id reaches
the parent list — and emitting it there with an empty ``text`` hands the agent a
contentless stepping stone to breed from. It belongs in a separate, optional report.
"""

from __future__ import annotations

from kg_engine.divergence import pipeline
from kg_engine.divergence.state import State


def _axes(open_name="mechanism", cat="form"):
    return {
        "domain": "d",
        "unit_of_generation": "idea",
        "axes": [
            {"name": cat, "type": "categorical"},
            {"name": open_name, "type": "open", "primary_novelty": True},
        ],
        "slate_size": 4,
        "candidates_per_generation": 6,
    }


def _cands(n, open_name="mechanism", cat="form"):
    return [
        {
            "id": f"c-{i:03d}",
            "text": f"idea {i}: a wholly separate proposal about topic {i}",
            "descriptor": {cat: f"v{i}", open_name: f"approach {i}"},
        }
        for i in range(n)
    ]


def _pinned_project(home):
    """A project with one pinned elite, ready for an axes-change reset."""
    axes = _axes()
    pipeline.init_project("p", axes, seed=1, home=home, session="s1")
    res = pipeline.ingest("p", _cands(5), axes, seed=1, home=home)
    victim = res["slate"][0]["id"]
    pipeline.remember("p", {"type": "pin", "id": victim}, home=home)
    return victim


def _reset_geometry(home):
    """Change the axes (same session) so init-project resets geometry, keeping memory."""
    axes2 = _axes(open_name="approach", cat="colour")
    out = pipeline.init_project("p", axes2, seed=1, home=home, session="s1")
    assert out["reset"] is True, "fixture must actually trip the geometry reset"


def test_parents_omit_pins_whose_record_was_reset(home):
    victim = _pinned_project(home)
    _reset_geometry(home)

    res = pipeline.parents("p", k=4, seed=1, home=home)
    assert all(p["id"] != victim for p in res["parents"]), (
        "a pin with no candidate record was emitted as a parent with empty text"
    )
    assert res["stale_pins"] == [victim]
    assert victim in res["stale_pins_note"] or "pinned id" in res["stale_pins_note"]


def test_pin_is_preserved_in_memory_after_a_reset(home):
    # Only its USE as a parent is suppressed; the pin itself is durable preference
    # memory and survives the reset (that is what makes it stale in the first place).
    victim = _pinned_project(home)
    _reset_geometry(home)

    assert victim in State("p", home=home).read_pins("d")
    assert victim in pipeline.recall("p", home=home)["pins"]


def test_no_stale_key_when_every_pin_still_resolves(home):
    # ABSENT, not an empty list: an optional key is a weaker promise to callers than a
    # key that is sometimes empty, and callers should not have to branch on the happy path.
    victim = _pinned_project(home)

    res = pipeline.parents("p", k=4, seed=1, home=home)
    assert any(p["id"] == victim and p["pinned"] for p in res["parents"])
    assert "stale_pins" not in res
    assert "stale_pins_note" not in res
