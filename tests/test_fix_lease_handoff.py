"""0.14.3: the lease is reclaimed only from a stale record, never from a read that finds nothing.

Found through a flaky CI test. `test_full_wave_of_concurrent_writers_all_commit_none_corrupted` failed now and
then on GitHub's Ubuntu runners with "a writer deadlocked on the lease": the failing leg ran about two minutes
longer, the lease's 120 s TTL. Seen on 2026-11-07, 2026-11-08 and 2026-11-13.

`LeaseLock.acquire()` sent a lock to `_reclaim_stale` on two reads that said nothing about staleness:
- **After a lost create race.** O_EXCL creates the lock file empty and writes the record a moment later. A
  contender that read the empty file took it for a vanished lock, moved it aside and dropped it, and both
  writers then held the lease. Measured on 30 waves of 10 writers: 47 times a writer found another one inside
  the lease, and up to 5 were inside at once.
- **On a re-read.** `is_stale()` read the lock again. When its holder had released in between, the re-read
  found nothing and called that stale, and the reclaim moved the next holder's fresh lock aside. If that
  holder finished and released before the reclaim put its record back, its release found no lock of its own,
  and the record put back named a writer that was gone. Every waiter then sat out the lease's TTL. This is
  the flaky test: with the two windows widened, every wave stalled for one TTL.

Now acquire() judges the record it read. A read that finds no record is retried, and an unparseable lock file is
reclaimed only once it is older than `LOCK_UNPARSEABLE_GRACE`, as an unreadable ticket already was.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from kg_engine import canon as canon_mod
from kg_engine.canon import LOCK_NAME, LOCK_UNPARSEABLE_GRACE, Canon, LeaseLock
from kg_engine.model import Node


def _wave(vault: Path, *, ttl: float | None = None, n: int = 10) -> "tuple[float, list[str]]":
    """Run one wave of `n` foreign-session writers; return its wall time and any errors."""
    canons = []
    for i in range(n):
        c = Canon(vault)
        c.lock.host = f"writer-host-{i}"
        if ttl is not None:
            c.lock.ttl = ttl
        c.lock_acquire_timeout = 30.0
        canons.append(c)
    start, errors = threading.Barrier(n), []

    def writer(i: int, c: Canon) -> None:
        try:
            start.wait()
            info = c.write_nodes([Node(id=f"n{i}", label=f"N{i}", body=f"body {i}")], message=f"wave {i}")
            if info.rolled_back:
                errors.append(f"writer {i} rolled back: {info.error}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer {i} raised {type(e).__name__}: {e}")

    t0 = time.monotonic()
    threads = [threading.Thread(target=writer, args=(i, c), daemon=True) for i, c in enumerate(canons)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "a writer is still waiting after 60 s"
    return time.monotonic() - t0, errors


# ---- the two reads that said nothing ---------------------------------------------------------------

def test_an_empty_young_lock_file_is_a_create_in_flight_and_is_respected(tmp_path: Path):
    p = tmp_path / LOCK_NAME
    p.write_text("", encoding="utf-8")                 # O_EXCL done, the record not written yet
    contender = LeaseLock(p, ttl=120, host="contender-host")
    assert contender.acquire() is False                # 0.14.2 moved it aside and took the lease
    assert p.read_text(encoding="utf-8") == ""         # untouched: the creator writes into this inode
    p.write_text("not json", encoding="utf-8")
    assert contender.acquire() is False                # damaged but young: still respected


def test_an_unparseable_lock_file_older_than_the_grace_is_reclaimed(tmp_path: Path):
    p = tmp_path / LOCK_NAME
    p.write_text("", encoding="utf-8")
    old = time.time() - LOCK_UNPARSEABLE_GRACE - 1
    os.utime(p, (old, old))                            # a crash between O_EXCL and the write
    contender = LeaseLock(p, ttl=120, host="contender-host")
    assert contender.acquire() is True
    assert json.loads(p.read_text(encoding="utf-8"))["host"] == "contender-host"


def test_acquire_judges_the_record_it_read_not_a_re_read(tmp_path: Path, monkeypatch):
    # The holder's live record is read; then the holder releases before any second look. 0.14.2's
    # is_stale() re-read found nothing, called it stale, and reclaimed.
    p = tmp_path / LOCK_NAME
    holder = LeaseLock(p, ttl=120, host="holder-host")
    assert holder.acquire()
    live = json.loads(p.read_text(encoding="utf-8"))
    contender = LeaseLock(p, ttl=120, host="contender-host")
    reads = iter([live, None, None, None])
    monkeypatch.setattr(contender, "_read", lambda: next(reads))
    reclaims: list = []
    monkeypatch.setattr(contender, "_reclaim_stale", lambda now: reclaims.append(now) or True)
    assert contender.acquire() is False
    assert reclaims == []


def test_a_read_that_finds_the_lock_gone_after_a_lost_create_is_retried(tmp_path: Path, monkeypatch):
    # The create race is lost, and by the next read the winner has released: retry, never reclaim.
    p = tmp_path / LOCK_NAME
    contender = LeaseLock(p, ttl=120, host="contender-host")
    monkeypatch.setattr(contender, "_read", lambda: None)
    monkeypatch.setattr(contender, "_try_exclusive_create", lambda now: False)
    reclaims: list = []
    monkeypatch.setattr(contender, "_reclaim_stale", lambda now: reclaims.append(now) or True)
    assert contender.acquire() is False
    assert reclaims == []


# ---- the wave --------------------------------------------------------------------------------------

def test_a_wave_never_has_two_writers_inside_the_lease(tmp_path: Path, monkeypatch):
    inside, peak, lock = [0], [0], threading.Lock()
    real = Canon._write_batch

    def counted(self, nodes, merge):
        with lock:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        try:
            time.sleep(0.002)                          # some work inside, as a merge and an fsync take
            return real(self, nodes, merge)
        finally:
            with lock:
                inside[0] -= 1

    monkeypatch.setattr(Canon, "_write_batch", counted)
    for k in range(5):
        vault = tmp_path / f"wave-{k}"
        vault.mkdir()
        _, errors = _wave(vault)
        assert not errors, errors
    assert peak[0] == 1, f"{peak[0]} writers were inside the lease at once"   # 0.14.2: up to 5


def test_a_widened_handoff_never_leaves_a_lease_behind(tmp_path: Path, monkeypatch):
    # Widen the two windows the races need: the moment between O_EXCL and the record write, and the moment
    # between moving a lock aside and putting it back. 0.14.2 stalled every such wave for one TTL.
    def slow_create(self, now):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        time.sleep(0.03)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._record(now)))
        return True

    real_replace = canon_mod._replace_lockfile

    def slow_replace(src, dst):
        real_replace(src, dst)
        if ".stale-" in Path(dst).name:
            time.sleep(0.05)

    monkeypatch.setattr(LeaseLock, "_try_exclusive_create", slow_create)
    monkeypatch.setattr(canon_mod, "_replace_lockfile", slow_replace)
    ttl = 6.0                                          # headroom for a slow runner; a leak costs >= ttl
    for k in range(2):
        vault = tmp_path / f"wave-{k}"
        vault.mkdir()
        wall, errors = _wave(vault, ttl=ttl)
        assert not errors, errors
        assert wall < ttl * 0.8, f"the wave took {wall:.2f}s: a lease was left behind for its TTL"
        assert not (vault / LOCK_NAME).exists()
        assert {n.id for n in Canon(vault).all_nodes()} == {f"n{i}" for i in range(10)}
