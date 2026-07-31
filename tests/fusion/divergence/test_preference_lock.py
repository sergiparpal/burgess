"""Pins and discards are ONE invariant, so they must be guarded by ONE lock.

Three writers mutate the pair — ``add_pin`` (pinning drops the discard), ``add_discard``
(discarding drops the pin) and ``remove_discard`` (the Burgess-only un-seal lever, which
edits the discard list a pin may be racing on). Locking each *file* separately lets a
concurrent pin and discard of the same id take different locks, interleave their
read-modify-writes, and leave that id in both lists or in neither — "latest action wins"
silently stops holding, and with it the mutual exclusivity the propose lane relies on.
"""

from __future__ import annotations

import contextlib
import threading
import time

from kg_engine.divergence import state as state_mod
from kg_engine.divergence.state import State

DOMAIN = "d"


def _record_lock_targets(monkeypatch):
    """Swap ``_file_lock`` for a recorder; returns the list of targets it was given."""
    targets = []
    real = state_mod._file_lock

    @contextlib.contextmanager
    def recording(target, timeout=state_mod._LOCK_TIMEOUT):
        targets.append(target)
        with real(target, timeout=timeout):
            yield

    monkeypatch.setattr(state_mod, "_file_lock", recording)
    return targets


def test_pin_and_discard_take_the_same_lock(home, monkeypatch):
    st = State("p", home=home).ensure()
    targets = _record_lock_targets(monkeypatch)

    st.add_pin(DOMAIN, "x")
    st.add_discard(DOMAIN, "x")
    st.remove_discard(DOMAIN, "x")  # Burgess-only un-seal: same pair, same lock

    assert len(targets) == 3, "each writer must take the lock exactly once"
    assert len(set(targets)) == 1, f"three writers, {len(set(targets))} locks: {targets}"


def test_pin_then_discard_leaves_exactly_one_membership(home):
    st = State("p", home=home).ensure()
    for action in ("pin", "discard", "pin", "pin", "discard"):
        getattr(st, f"add_{action}")(DOMAIN, "x")
        pinned = "x" in st.read_pins(DOMAIN)
        discarded = "x" in st.read_discards(DOMAIN)
        assert pinned != discarded, f"after {action}: pinned={pinned} discarded={discarded}"
        assert pinned is (action == "pin"), "latest action must win"


def test_concurrent_pins_and_discards_stay_mutually_exclusive(home, monkeypatch):
    # Widen the read-modify-write window so the interleaving is exercised deterministically
    # rather than by luck. With one lock per FILE the two writers run concurrently: both
    # read an empty list, both append, then both strip the other's fresh entry and the id
    # ends up in NEITHER list. With the shared lock they serialize and exactly one wins.
    real_read_pins, real_read_discards = State.read_pins, State.read_discards

    def slow(fn):
        def wrapper(self, domain):
            time.sleep(0.02)
            return fn(self, domain)
        return wrapper

    monkeypatch.setattr(State, "read_pins", slow(real_read_pins))
    monkeypatch.setattr(State, "read_discards", slow(real_read_discards))

    st = State("p", home=home).ensure()
    for round_no in range(4):
        cid = f"x{round_no}"
        threads = [
            threading.Thread(target=st.add_pin, args=(DOMAIN, cid)),
            threading.Thread(target=st.add_discard, args=(DOMAIN, cid)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        pinned = cid in real_read_pins(st, DOMAIN)
        discarded = cid in real_read_discards(st, DOMAIN)
        assert pinned != discarded, (
            f"round {round_no}: id is in {'both' if pinned else 'neither'} list — "
            f"the pin/discard race left the invariant broken"
        )
