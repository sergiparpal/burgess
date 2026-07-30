"""The canonical layer (§1.2): human-editable Markdown notes, crash-safe single-writer I/O.

- single-file writes: temp-file + atomic os.replace
- multi-file mutations: snapshot every touched file's bytes, write-all-then-one-commit; on any write
  failure restore the in-memory snapshot (same on git and non-git vaults — git is used only for the
  success-path commit, never for rollback)
- a reclaimable lease lock so a dead/expired session never wedges the vault
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .atomicio import atomic_write_bytes, atomic_write_text, fsync_dir
from .model import (
    Edge,
    EpistemicState,
    GROUNDABLE_STATES,
    Node,
    UNDECLARED_TYPE,
    node_content_hash,
    node_from_markdown,
    node_to_markdown,
    slug,
    utcnow,
)

LOCK_NAME = ".kg-session-lock"
CANON_SUBDIR = "canon"
# Refresh the lease this many times per TTL while a long batch is in flight (write_nodes), so the
# lease stays comfortably fresh inside the TTL window and a concurrent session never judges it stale.
HEARTBEAT_REFRESHES_PER_TTL = 3
# Bounded-retention housekeeping for the transient dotfiles the I/O paths can leave in the canon dir
# (perf/housekeeping gap). Keep at most this many `.{name}.unreadable-*.bak` per note (newest first) so
# the F28 recoverability intent is honored while the rest are pruned; reap crash-leftover `.tmp-*` and
# sidelined lock files (`.kg-session-lock.stale-*`/`.release-*`) only once they are older than this many
# seconds — long past any live atomic-write/lock-reclaim window — so the reaper never races a write.
BACKUP_RETENTION_PER_NOTE = 3
TRANSIENT_REAP_TTL = 3600.0
# Bounded wait for the single-writer lease before a WRITER gives up. A parallel /kg-build wave funnels
# every kg_write through the ONE single-threaded MCP server process (FastMCP runs sync tools directly on
# the event loop, so the brief write critical section is already serialized there), so the lease is only
# ever genuinely contended ACROSS processes — the detached per-session reconcile worker
# (`bootstrap --reconcile`) or the headless backend racing a server write. Each holder keeps the lease
# only for its own brief write, so a writer that finds it taken retries with exponential backoff and
# serializes cleanly instead of failing outright. Capped so a genuinely wedged LIVE foreign holder
# surfaces as the locked-vault error rather than hanging forever. A DEAD holder on the SAME host is
# reclaimed immediately via staleness inside acquire() (its pid no longer probes alive on POSIX or, since
# FALLO 2, via OpenProcess on Windows), so it is never waited on; only a CROSS-HOST holder's pid can't be
# probed, so such a dead holder is only seen stale once its lease TTL lapses — a writer may wait up to this budget meanwhile,
# then surface the error, and a later attempt reclaims it. Since the blocking acquire became FIFO-fair
# (LOCK_QUEUE_* below) a waiter spends its budget on the writes genuinely AHEAD of it rather than on lost
# races, which is what makes this default comfortable for a full max-size (10) wave on ordinary hardware
# — but it is a budget, not a guarantee, and a pathological runner can still outlast it; tests override
# it per Canon (e.g. 0 to assert the old immediate-fail, or generous where the point is serialization).
LOCK_ACQUIRE_TIMEOUT = 30.0
# Backoff for the UNFAIR fallback loop (only reached when the ticket queue below is unavailable) and for
# the lease-file rename-aside retry (LOCK_REPLACE_RETRY_TIMEOUT).
LOCK_RETRY_INITIAL = 0.05
LOCK_RETRY_MAX = 0.5
# FIFO ticket queue for the BLOCKING writer acquire. Before it every contender polled the lease on its
# own capped backoff, which cost two things. (a) Handoff took up to LOCK_RETRY_MAX even though the
# critical section is ~10ms: a measured 10-writer wave spent 96% of its wall time ASLEEP with the lease
# free (3.29s wall for 0.11s of work). (b) Nothing ordered the contenders, so a waiter could lose race
# after race — on a loaded CI runner three writers of a ten-writer wave burned the entire 30s budget and
# surfaced the by-design locked-vault error while seven others drained past them. A ticket makes order of
# ARRIVAL the order of service, which bounds the tail wait at "the writes actually ahead of me"; polling
# the lease only from the FRONT is what lets that poll be short (prompt handoff) with no thundering herd.
LOCK_QUEUE_DIRNAME = f"{LOCK_NAME}.q"
LOCK_QUEUE_POLL_MIN = 0.01  # front of the queue: this IS the per-writer handoff latency a wave pays
LOCK_QUEUE_POLL_MAX = 0.25  # far back: the writers ahead must drain first, so poll cheaply
# A ticket must be refreshed this often to keep its place, and this is the WINDOWS backstop. POSIX
# unlink succeeds with the file still open, so a waiter's dequeue always lands there; on Windows it
# raises ERROR_SHARING_VIOLATION while any other process holds the file open (the same reason
# _replace_lockfile exists) — and the FRONT waiter's ticket is the most-read file in the queue, since
# every waiter behind it reads it to check liveness. So the one dequeue most likely to fail is exactly
# the one that parks everybody. Tickets therefore carry their OWN short TTL instead of the lease's
# 120s: a leaked ticket stops being refreshed the moment its owner takes the lease, so it goes stale
# in seconds and the next waiter reaps it, rather than blocking the queue for the whole lease TTL.
LOCK_QUEUE_TICKET_TTL = 5.0
LOCK_QUEUE_PROBE_SECS = 1.0   # how often a waiter re-validates the tickets AHEAD of it (see below)
LOCK_QUEUE_DEQUEUE_RETRY = 0.05  # brief retry so the common Windows unlink collision still lands
# Liveness valve: if our position has not improved in this long, stop trusting the queue and finish on
# the unfair loop. Ordering is an optimization and must never be able to make a writer do WORSE than
# the pre-queue behavior — so any way the queue can stall (a filesystem where the reaping unlink never
# lands, a pathology not yet imagined) costs fairness, never the write. Deliberately BELOW one ticket
# TTL: waiting out a ghost is itself a stall, and degrading beats waiting. It cannot cost the fairness
# that matters, because the regime fairness exists for — many contenders with ~10ms critical sections —
# improves position every few milliseconds and can never approach this. It trips only where one writer
# ahead runs long (fairness is moot: the wait is real work) or the queue is genuinely wedged. Chosen on
# measurement: under a synthetic filesystem where EVERY ticket unlink fails, 15s and 8s still spent the
# budget and failed writes, while this drains the same 10-writer wave in ~6s with none lost.
LOCK_QUEUE_STALL_SECS = 4.0
# Bounded retry budget for the lease-file rename-aside CAS (release + stale-reclaim). On Windows,
# os.replace() on the lock file fails with a sharing violation (PermissionError/ERROR_SHARING_VIOLATION)
# while ANOTHER session momentarily holds it open for read — which the spinning waiters in
# _acquire_lease_blocking do constantly. The reader closes within milliseconds, so retry briefly instead
# of treating a transient violation as "gone": a release() that gives up leaves the lock file in place,
# and because that orphaned record names a foreign host (never pid-probed stale, only TTL-stale) it would
# block every waiter for the full TTL — far past LOCK_ACQUIRE_TIMEOUT — surfacing as a spurious
# locked-vault error for a whole parallel wave. Kept well under the acquire budget; in practice it
# succeeds on the first attempt or two (there are always reader-free windows between the waiters' backoff
# sleeps). Same fail-closed posture as the lock reader/heartbeat (a transient IO error never "succeeds").
LOCK_REPLACE_RETRY_TIMEOUT = 5.0
# Grounding audit log (kg_ground tamper-evidence). Defined here — the lowest layer that must keep it
# out of git — and re-exported by reconciler so server/tests have one source of truth.
GROUND_AUDIT = ".kg-ground-audit.jsonl"
# The reconciler's mtime/size pre-filter cache — named here for the same reason as GROUND_AUDIT
# (the cleanup/git-exclude patterns below reference it) and consumed by reconciler's default
# state_path (review-r5: the filename was re-typed in both files).
RECONCILE_STATE_NAME = ".kg-reconcile-state.json"


# --------------------------------------------------------------------------- git helpers


# Hardening shared by every git invocation (this is the lowest layer, like GROUND_AUDIT above): bound
# the wait, DETACH stdin so git can never block on a credential/identity prompt, and disable terminal
# prompts + the optional .git/index lock. A git call in the detached MCP server process must never be
# able to wedge a tool handler — a wedged handler exceeds KG_HANDLER_TIMEOUT and the supervisor
# force-exits the engine (exit 71). 5s is generous for the only commands we run (rev-parse/add/commit
# on a local repo).
_GIT_TIMEOUT_S = 5.0


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=check,
            timeout=_GIT_TIMEOUT_S, stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (subprocess.TimeoutExpired, OSError):
        # A hung or unspawnable git degrades to a NON-ZERO result instead of hanging/raising. Every
        # production caller passes check=False and reads .returncode, so this reads as "git
        # unavailable": _git_ok -> False (skip the best-effort commit), never a wedged handler.
        return subprocess.CompletedProcess(["git", "-C", str(repo), *args], 1, "", "")


def _git_ok(repo: Path) -> bool:
    return (repo / ".git").exists() or _git(repo, "rev-parse", "--git-dir", check=False).returncode == 0


# --------------------------------------------------------------------------- lease lock (§Stage 1)


@dataclass
class LeaseLock:
    path: Path
    ttl: float = 120.0
    pid: int = 0
    host: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.pid:
            self.pid = os.getpid()
        if not self.host:
            self.host = socket.gethostname()

    def _read(self) -> dict | None:
        # The LIVE lock: share the one reader, but fail CLOSED on an unexpected OSError (e.g.
        # PermissionError) so an unreadable HELD lock is never misread as "no record"/free. Only
        # FileNotFoundError (absent) and ValueError (corrupt) read as None here (tolerant defaults False).
        return self._read_path(self.path)

    def _owned_by_self(self, rec: dict) -> bool:
        return rec.get("pid") == self.pid and rec.get("host") == self.host

    def _rec_stale(self, rec: dict | None, now: float) -> bool:
        """Staleness of a specific record (no re-read), so the reclaim path can re-validate the exact
        record it moved aside rather than whatever is at the path now."""
        if rec is None:
            return True
        if (now - rec.get("heartbeat_at", 0)) > rec.get("ttl", self.ttl):
            return True
        return not _pid_probe(rec.get("pid", 0), rec.get("host", ""), self.host)

    def is_stale(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self._rec_stale(self._read(), now)

    def acquire(self, now: float | None = None) -> bool:
        """Acquire if absent, stale, or already held by us. Returns True on success.

        Every transition is a compare-and-swap so two sessions can't both believe they hold the lock:
        the absent case uses an atomic O_EXCL create; a STALE lock is reclaimed by atomically renaming
        it aside (only one racer can move a given inode) and then O_EXCL-creating a fresh one. A blind
        overwrite of a stale lock (the old behavior) let two racers that both observed it stale each
        write and both return True (canon-4).
        """
        now = time.time() if now is None else now
        rec = self._read()
        if rec is None:
            if self._try_exclusive_create(now):
                return True
            rec = self._read()  # lost the create race; re-evaluate below
        if rec is not None and self._owned_by_self(rec):
            self._write(now)  # refresh our own lock (re-acquire is idempotent)
            return True
        if rec is not None and not self.is_stale(now):
            return False  # held by another live session
        # stale (or vanished after our read): reclaim atomically.
        if not self._reclaim_stale(now):
            return False
        if self._try_exclusive_create(now):
            return True
        rec2 = self._read()  # lost the recreate race to a fresh acquirer; honor theirs unless it's us
        return bool(rec2 and self._owned_by_self(rec2))

    def _reclaim_stale(self, now: float) -> bool:
        """Rename the stale lock aside and clear it, so acquire() can O_EXCL-create a fresh one.

        Returns True when the path is free to recreate (we moved-and-dropped the stale record, or it
        had already vanished), False when we must abandon the acquire (a move failure, or the record
        turned out to be LIVE after we moved it). Rename the stale lock aside — only ONE racer can move
        a given inode, so exactly one wins the right to recreate; a racer whose rename fails (someone
        already moved/removed it) falls through and competes on the O_EXCL.
        """
        sidelined = self.path.with_name(f"{self.path.name}.stale-{self.pid}-{int(now * 1000)}")
        try:
            _replace_lockfile(self.path, sidelined)  # retry transient Windows sharing violations
        except FileNotFoundError:
            return True  # already reclaimed/removed; just try to create
        except OSError:
            return False  # persisted past the retry budget — lose this acquire and let the caller retry
        # Re-validate the record we actually moved: if the owner refreshed its heartbeat in the
        # window between our is_stale() read and this move, we just sidelined a LIVE lock. Put it
        # back and lose the race rather than steal it (closes the residual reclaim TOCTOU).
        moved = self._read_path(sidelined, tolerant=True)
        if moved is not None and not self._rec_stale(moved, now):
            # Restore the live record. A transient OSError on the reverse rename (EIO/ENOSPC/EPERM —
            # os.replace cannot raise on an existing target or EXDEV here, same parent dir) would
            # otherwise orphan the live owner's only record at the sidelined path and leave self.path
            # empty, so the live owner silently loses its lease until its NEXT acquire() re-O_EXCLs it.
            # Don't blind-`pass`: fall back to writing the record's content back to self.path so the
            # canonical path is never left empty, then drop the sideline. The reaper sweeps any leak.
            self._restore_or_copy_back(sidelined, moved)
            return False
        try:
            os.unlink(sidelined)
        except OSError:
            pass
        return True

    def _restore_or_copy_back(self, sidelined: Path, rec: dict) -> bool:
        """Put a sidelined-but-LIVE lock record back at self.path. Try the atomic reverse rename first;
        on a transient OSError (EIO/ENOSPC/EPERM) fall back to copying the record's content to self.path
        (so the live owner's canonical path is never left empty) and dropping the sideline. Returns True
        if self.path ends up holding the live record. Best-effort throughout — on total failure the live
        owner re-O_EXCLs the path on its next acquire() and the reaper sweeps the sideline."""
        try:
            os.replace(sidelined, self.path)
            return True
        except OSError:
            pass
        # rename failed transiently — write the record's content back so self.path isn't left empty
        try:
            _atomic_write(self.path, json.dumps(rec))
            try:
                os.unlink(sidelined)
            except OSError:
                pass
            return True
        except OSError:
            return False

    @staticmethod
    def _read_path(p: Path, *, tolerant: bool = False) -> dict | None:
        """Parse the JSON lock record at `p`; a missing (FileNotFoundError) or corrupt (ValueError) file
        reads as "no record". The LIVE lock reader (_read) fails CLOSED on any OTHER OSError — an
        unreadable HELD lock must never be misread as free. The SIDELINED reclaim re-read passes
        tolerant=True: it just moved the file aside, so a transient OSError there means "treat as gone"
        and proceed (the move already serialized racers)."""
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
        except OSError:
            if tolerant:
                return None
            raise

    def _record(self, now: float) -> dict:
        return {"pid": self.pid, "host": self.host,
                "acquired_at": now, "ttl": self.ttl, "heartbeat_at": now}

    def _try_exclusive_create(self, now: float) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._record(now)))
        return True

    def _write(self, now: float) -> None:
        _atomic_write(self.path, json.dumps(self._record(now)))

    def heartbeat(self, now: float | None = None) -> None:
        # A heartbeat is BEST-EFFORT: lease correctness comes from the TTL + the CAS acquire/reclaim,
        # not from any single refresh landing. So a transient read/write OSError (most often a Windows
        # sharing violation while another process momentarily holds the lock file open) must NOT
        # propagate: heartbeat() is called mid-batch by write_nodes, and a raw OSError there would
        # trigger a spurious full-batch rollback of otherwise-healthy writes. A missed refresh is
        # harmless — the next one, or the still-valid TTL, covers it.
        try:
            rec = self._read()
            # Refresh, never acquire: a heartbeat extends a lock we BELIEVE we hold as of the read below.
            # If the record is gone (rec is None) or owned by someone else, do nothing — blind-writing a
            # fresh self-owned record here would be an un-CAS'd acquisition that could steal a path a
            # successor reclaimed after our lease lapsed. This is a read-check-then-write, NOT a CAS: a
            # residual TOCTOU remains if OUR OWN lease goes TTL-stale in the check→write gap (e.g. a long
            # GC/suspend pause) and a successor reclaims in that instant — narrow, and bounded because we
            # heartbeat every ttl/3. Full acquisition safety comes solely from acquire()'s O_EXCL/reclaim
            # CAS (F16); the heartbeat is a best-effort TTL extension, not a correctness guarantee.
            if rec is None or not self._owned_by_self(rec):
                return
            now = time.time() if now is None else now
            merged = dict(rec)
            merged.update({"pid": self.pid, "host": self.host, "ttl": self.ttl, "heartbeat_at": now})
            merged.setdefault("acquired_at", now)
            _atomic_write(self.path, json.dumps(merged))
        except OSError:
            return

    def release(self) -> None:
        # Read-then-unlink would be a TOCTOU: if our lease lapsed past TTL and a successor reclaimed the
        # path between our _read() and the unlink, a plain unlink(self.path) would delete THEIR lock.
        # Mirror acquire()'s reclaim discipline — rename our lock aside (only one racer can move a given
        # inode), confirm the MOVED record is still ours, then unlink it; if the path was already
        # reclaimed (our rename moved someone else's record, or the record changed under us) put it back
        # and leave the successor's lock untouched (F15).
        rec = self._read()
        if not (rec and self._owned_by_self(rec)):
            return
        sidelined = self.path.with_name(f"{self.path.name}.release-{self.pid}-{int(time.time() * 1000)}")
        try:
            _replace_lockfile(self.path, sidelined)  # retry transient Windows sharing violations
        except (FileNotFoundError, OSError):
            return  # already gone/reclaimed (or a persistent IO error) — nothing of ours to release
        moved = self._read_path(sidelined, tolerant=True)
        if moved is not None and self._owned_by_self(moved):
            try:
                os.unlink(sidelined)
            except OSError:
                pass
            return
        # we moved a foreign/changed record aside (a successor reclaimed the path) — restore it
        try:
            os.replace(sidelined, self.path)
        except OSError:
            try:
                os.unlink(sidelined)
            except OSError:
                pass

    # ---- FIFO ticket queue (fairness for the BLOCKING acquire — see LOCK_QUEUE_DIRNAME)
    #
    # These are pure ORDERING: a ticket never grants the lease and never bypasses acquire()'s
    # O_EXCL/reclaim CAS, so a lost, duplicated or forged ticket costs a waiter its place in line and
    # nothing else. Single-writer safety (F16) stays entirely with acquire(); that separation is what
    # makes it safe for every method here to degrade silently on an OSError.

    @property
    def queue_dir(self) -> Path:
        return self.path.with_name(LOCK_QUEUE_DIRNAME)

    def enqueue(self, now: float | None = None) -> Path | None:
        """Take a ticket for the blocking acquire; None when the queue is unavailable (read-only vault,
        permissions) so the caller degrades to the unfair backoff loop rather than failing a WRITE over
        what is only a fairness optimization.

        The name embeds the arrival stamp zero-padded, so a plain lexical sort of the directory IS
        arrival order, with a host/pid/random tail to keep two same-microsecond arrivals distinct and
        totally ordered. Ordering is by WALL CLOCK: cross-host clock skew therefore degrades fairness
        (a skewed waiter queues early or late) but never correctness, per the note above. Written via
        _atomic_write so a concurrent reader never sees a half-written ticket and reaps it as corrupt
        (mkparents creates the queue dir, fsync makes the entry visible to the other waiters)."""
        now = time.time() if now is None else now
        tag = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in f"{self.host}-{self.pid}")
        ticket = self.queue_dir / f"{int(now * 1_000_000):020d}-{tag}-{os.urandom(4).hex()}.json"
        try:
            _atomic_write(ticket, json.dumps(self._ticket_record(now)))
            return ticket
        except OSError:
            return None

    def _ticket_record(self, now: float) -> dict:
        """A lease record carrying the ticket's OWN short TTL — see LOCK_QUEUE_TICKET_TTL for why a
        ticket must expire far sooner than the lease it is queueing for."""
        rec = self._record(now)
        rec["ttl"] = LOCK_QUEUE_TICKET_TTL
        return rec

    def dequeue(self, ticket: Path) -> None:
        """Give up our place. Retried briefly because THIS unlink is the one most likely to fail on
        Windows: we are normally the front of the queue (we just took the lease), and every waiter
        behind us reads our ticket to check whether we are still live, so the file is often open
        elsewhere at exactly this moment (ERROR_SHARING_VIOLATION). The retry budget is deliberately
        tiny — this runs on the hot path, right before the write the lease was taken for — because
        the real guarantee is LOCK_QUEUE_TICKET_TTL: a ticket we never manage to remove stops being
        refreshed here and goes stale in seconds, so it parks the queue briefly instead of forever."""
        deadline = time.monotonic() + LOCK_QUEUE_DEQUEUE_RETRY
        while True:
            try:
                ticket.unlink()
                return
            except FileNotFoundError:
                return  # already gone (reaped as stale while we held it) — nothing to do
            except OSError:
                if time.monotonic() >= deadline:
                    return  # the TTL backstop takes it from here
                time.sleep(0.005)

    def _ticket_names(self) -> list[str]:
        """The queue's ticket names in arrival (lexical) order.

        Excludes the `.tmp-*` atomic-write temporaries, which land IN this directory: mkstemp inherits
        the target's suffix, so writing `<stamp>-…json` first creates `.tmp-XXXX.json` beside it. A
        naive `*.json` listing would (a) count that half-written file as a live waiter AHEAD of the
        whole queue — `.` sorts before every digit — and then (b) find it unparseable, judge it stale
        and UNLINK it, destroying another waiter's in-flight write out from under its os.replace and
        silently degrading that writer to the unfair path. `.tmp-*` is already reserved for exactly this
        across the canon (notes() and reap_transient_files both special-case it)."""
        return sorted(p.name for p in self.queue_dir.iterdir()
                      if p.name.endswith(".json") and not p.name.startswith(".tmp-"))

    def queue_position(self, ticket: Path, now: float | None = None, *, probe: bool = True) -> int:
        """How many waiters sit ahead of `ticket` — 0 means it is our turn to attempt the lease — or
        -1 when our own ticket is gone (reaped while we stalled) and the caller must rejoin.

        With `probe` (the default) the tickets ahead are re-validated and the stale ones reaped, so a
        waiter that crashed mid-wait cannot park the queue behind it. Staleness is the lease's own
        rule (`_rec_stale`), now against the ticket's short LOCK_QUEUE_TICKET_TTL.

        With `probe=False` the position comes from the directory listing ALONE — no ticket is opened.
        Callers probe about once a second (LOCK_QUEUE_PROBE_SECS) and take the cheap path otherwise,
        which matters on Windows: reading a ticket holds it open, and Python's open() does not grant
        FILE_SHARE_DELETE, so a waiter reading the ticket ahead of it makes that ticket's owner's own
        dequeue fail with a sharing violation. Probing on every poll aimed that read pressure squarely
        at the FRONT ticket — the one every other waiter re-reads and the one whose leak parks the
        whole queue. Throttling the probe cuts that collision window by ~100x while costing at most
        LOCK_QUEUE_PROBE_SECS of extra wait behind a ticket that is already dead.

        Reads are fail-CLOSED, matching the live-lock reader (_read): only a ticket that is genuinely
        ABSENT counts as gone. One that is present but unreadable — the transient sharing violation
        above, or a corrupt record — is respected as live rather than reaped, because reaping it would
        push a healthy waiter to the BACK of the queue (it re-enqueues on -1), which is a starvation
        amplifier strictly worse than the unfairness this queue exists to remove. Such a ticket is
        still reclaimed once it ages past the TTL, judged by mtime since we cannot read its record."""
        now = time.time() if now is None else now
        try:
            names = self._ticket_names()
        except OSError:
            return -1  # queue dir vanished/unreadable — rejoin (or degrade) rather than assume front
        if ticket.name not in names:
            return -1
        ahead_names = names[:names.index(ticket.name)]
        if not probe:
            return len(ahead_names)
        ahead = 0
        for name in ahead_names:
            p = self.queue_dir / name
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue  # its owner dequeued between the listing and here — genuinely not ahead
            except (ValueError, OSError):
                # Present but unreadable. Never jump or reap what we cannot PROVE is dead; only an
                # ORPHAN (older than the ticket TTL by mtime) is reclaimable without reading it.
                if self._ticket_orphaned(p, now):
                    self._reap_ticket(p)
                    continue
                ahead += 1
                continue
            if self._rec_stale(rec, now):
                # PROVED dead, so it never holds a place — whether or not we manage to delete it.
                # Making the skip conditional on the unlink made queue LIVENESS depend on deletion
                # succeeding: where unlink persistently fails, a dead ticket could never be cleared
                # and parked every writer until its budget ran out. Ordering is advisory; the lease
                # CAS is what actually serializes, so at worst two waiters both think they are front
                # and one loses the O_EXCL race.
                self._reap_ticket(p)
                continue
            ahead += 1
        return ahead

    def _ticket_orphaned(self, p: Path, now: float) -> bool:
        """Whether an UNREADABLE ticket has aged past the ticket TTL by mtime — the only evidence of
        death available when its record cannot be parsed. Unstattable reads as NOT orphaned (fail
        closed: never reclaim on the strength of a second failed syscall)."""
        try:
            return (now - p.stat().st_mtime) > LOCK_QUEUE_TICKET_TTL
        except OSError:
            return False

    @staticmethod
    def _reap_ticket(p: Path) -> None:
        """Best-effort removal of a ticket already proved dead. Deliberately returns nothing: no
        caller may condition queue progress on the unlink landing (see queue_position)."""
        try:
            p.unlink()
        except OSError:
            pass

    def heartbeat_ticket(self, ticket: Path, now: float | None = None) -> None:
        """Refresh a WAITING ticket so it keeps its place: tickets expire on the short
        LOCK_QUEUE_TICKET_TTL, so an unrefreshed one is reaped within seconds. That is deliberate —
        it is what reclaims a ticket whose owner could not delete it (Windows) — and it means a live
        waiter MUST keep refreshing. Best-effort like the lease heartbeat: a missed refresh costs at
        most our place in line, never correctness."""
        now = time.time() if now is None else now
        try:
            _atomic_write(ticket, json.dumps(self._ticket_record(now)))
        except OSError:
            pass


def _replace_lockfile(src: Path, dst: Path) -> None:
    """os.replace(src, dst) for the lease file, resilient to transient Windows sharing violations.

    The rename-aside CAS (release/_reclaim_stale) moves `self.path` while concurrent waiters may have it
    open for read; on Windows that raises PermissionError (ERROR_SHARING_VIOLATION) because Python's
    open() does not grant FILE_SHARE_DELETE. The reader closes within milliseconds, so retry within a
    bounded budget rather than mistaking the violation for a free path. FileNotFoundError propagates
    IMMEDIATELY (the source is genuinely gone — already reclaimed), and a persistent OSError is re-raised
    after the budget so the caller's own except clause still degrades gracefully (the TTL is the backstop).
    """
    deadline = time.monotonic() + LOCK_REPLACE_RETRY_TIMEOUT
    backoff = LOCK_RETRY_INITIAL
    while True:
        try:
            os.replace(src, dst)
            return
        except FileNotFoundError:
            raise
        except OSError:
            now = time.monotonic()
            if now >= deadline:
                raise
            time.sleep(min(backoff, deadline - now))
            backoff = min(backoff * 2, LOCK_RETRY_MAX)


def _win_pid_alive(pid: int) -> bool:
    """Windows liveness probe via ``OpenProcess`` + ``GetExitCodeProcess`` (ctypes — stdlib). A
    running pid → True, a pid that no longer exists → False, a pid owned by another account → True
    (assume alive). Any ctypes/loader hiccup → True (fail SAFE: never reclaim a lock we can't PROVE
    is dead). This is the parallel-by-design twin of ``dirlock._win_pid_alive`` — the two locks keep
    their own copies (see dirlock's module header) but share the identical Windows probe (FALLO 2)."""
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_INVALID_PARAMETER = 87
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # DEAD only on ERROR_INVALID_PARAMETER (87 = no such process). Every other failure fails SAFE
            # to alive: ERROR_ACCESS_DENIED (5) is a live process owned by another account, and a TRANSIENT
            # error (ERROR_NOT_ENOUGH_MEMORY, handle exhaustion, AV interference) against a genuinely-live
            # canon-lease holder must NOT be read as dead and let its lease be reclaimed. This is byte-for-
            # byte the hardened dirlock._win_pid_alive logic — the two probes are parallel-by-design and were
            # ONE-WAY drifted (dirlock hardened, this twin left on the fail-UNSAFE `== ACCESS_DENIED` form,
            # which read 87 AND every transient error as dead → over-reclaim a live lease, review-fix).
            return ctypes.get_last_error() != ERROR_INVALID_PARAMETER
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 — a ctypes/loader failure must never over-reclaim a live lease
        return True


def _pid_probe(pid: int, host: str, my_host: str) -> bool:
    """True if the pid is (possibly) alive. A pid on another host is treated as alive; a same-host pid
    is probed on BOTH platforms — os.kill(pid, 0) on POSIX, OpenProcess (_win_pid_alive) on Windows.
    (FALLO 2: os.kill(pid, 0) on Windows is CTRL_C_EVENT, not a no-op existence check, so the probe
    used to be skipped there and a crashed holder's lease was reclaimed only once its TTL lapsed.)"""
    if not pid:
        return False
    if host and host != my_host:
        return True
    if not host:
        return True  # an old/corrupt record with a pid but no host can't be probed — assume alive
                     # (mirrors dirlock.pid_probe; otherwise a coincidental same-numbered LOCAL pid or a
                     #  truly-remote holder would be mis-probed against THIS host, review-fix)
    if os.name == "nt":
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    except OSError:
        return False


# --------------------------------------------------------------------------- atomic write

# The crash-safe write protocol (temp + fsync + os.replace + dir-fsync) lives in the stdlib-only
# `atomicio` leaf module so the engine and the installer share one implementation. canon's old
# mkdir + dir-fsync behavior is exactly atomicio's defaults (mkparents/fsync_dir both True). These
# module-level names keep `canon._atomic_write` / `canon._atomic_write_bytes` available for the
# in-package callers and tests that reference them through this module.
_atomic_write_bytes = atomic_write_bytes
_atomic_write = atomic_write_text


# --------------------------------------------------------------------------- Canon


@dataclass
class RollbackInfo:
    rolled_back: bool
    error: str = ""


class Canon:
    """Markdown canon rooted at a project dir; notes live under <project>/canon/."""

    def __init__(self, project_dir: str | os.PathLike, *, ensure_layout: bool = True,
                 git_enabled: bool = True):
        self.root = Path(project_dir)
        # git_enabled=False makes _commit_batch a no-op for a vault that lives UNDER a parent repo's
        # worktree but must never be committed into it — the /kg-perturb "second construction", rooted at
        # <project>/.kg/constructions/<slug>/. There `_git_ok` would discover the PARENT repo (rev-parse
        # walks up) and commit the ephemeral construction canon into the user's tracked history (§9/§15,
        # review-fix: H1). The atomic note writes + snapshot rollback are unaffected (they work on git and
        # non-git vaults alike), so a construction is still crash-safe, just never committed.
        self.git_enabled = git_enabled
        self.notes_dir = self.root / CANON_SUBDIR
        # Resolve the notes dir ONCE — node_path() runs the vault-prefix check 4-5×/node/batch and was
        # re-running notes_dir.resolve() (a syscall) on every call. The path is fixed for this Canon's
        # lifetime, so cache the resolved form here and reuse it (perf #17).
        self._notes_dir_resolved = self.notes_dir.resolve()
        self.lock = LeaseLock(self.root / LOCK_NAME)
        self._lock_depth = 0  # re-entrancy guard so nested writes don't deadlock the single-writer lease
        # Bounded wait a WRITER tolerates for the lease before raising (cross-process contention only —
        # see LOCK_ACQUIRE_TIMEOUT). Per-instance so a test can shorten/zero it; the lazy projector's
        # try_acquire_lock() is unaffected and stays strictly non-blocking.
        self.lock_acquire_timeout = LOCK_ACQUIRE_TIMEOUT
        # ensure_layout=False lets a READ-ONLY consumer (e.g. the precontext PreToolUse hook, which runs
        # on every Grep/Glob/Read) construct a Canon for kg_context reads WITHOUT the constructor side
        # effects: the canon-dir mkdir and the .git/info/exclude rewrite (_ensure_git_excludes re-reads
        # that file on every call). Reads over a missing notes_dir just glob empty; a write through such
        # an instance still self-heals the dir via _atomic_write_bytes' parent mkdir. Default True keeps
        # the original eager-layout behavior for every writer (server/backend/reconciler).
        if ensure_layout:
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_git_excludes()

    def _ensure_git_excludes(self) -> None:
        """Keep transient runtime files (session lock, temp files, reconcile state) out of git in ANY
        git-backed vault, so `git add -A` / stash-as-rollback never commit or discard them — without
        relying on the user having authored a .gitignore."""
        git_dir = self.root / ".git"
        if not git_dir.is_dir():
            return  # not a standard repo (worktree/submodule/no-git) — best-effort only
        info = git_dir / "info"
        exclude = info / "exclude"
        # The grounding audit log is runtime tamper-evidence, NOT canon content: it must never be
        # committed by `git add -A` nor swept by a rollback. (Even with the snapshot-scoped rollback
        # below it is untouched, but excluding it keeps it out of commits and out of `stash -u`.)
        # GLOB the audit log: groundaudit writes a `<log>.ckpt` spend-ledger sidecar beside it, and a
        # pattern without the wildcard matches only the exact name — leaving the sidecar untracked, so
        # `git add -A` commits per-machine runtime state into canon history and `git stash -u` discards
        # it. The repo's own .gitignore already globs; the engine-written exclude (which is what a USER's
        # vault gets) did not (review-r11).
        # The lease's ticket queue is per-session runtime state exactly like the lease itself, and it is
        # a DIRECTORY, so it needs its own trailing-slash pattern (LOCK_NAME matches the lock file only).
        patterns = [LOCK_NAME, f"{LOCK_QUEUE_DIRNAME}/", ".tmp-*", RECONCILE_STATE_NAME,
                    f"{GROUND_AUDIT}*"]
        try:
            info.mkdir(parents=True, exist_ok=True)
            current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            missing = [p for p in patterns if p not in current.split()]
            if missing:
                with open(exclude, "a", encoding="utf-8") as f:
                    if current and not current.endswith("\n"):
                        f.write("\n")
                    f.write("\n".join(missing) + "\n")
        except OSError:
            pass

    # ---- single-writer lease (re-entrant within this process)
    def acquire_lock(self) -> None:
        """Bounded-BLOCKING writer acquire (raises RuntimeError when the vault stays held past the
        budget). Public like its counterpart ``release_lock`` and the non-blocking
        ``try_acquire_lock`` — three sibling modules consume this seam, so the old underscore name
        mis-signalled "don't depend on me" (review-r5)."""
        if self._lock_depth == 0 and not self._acquire_lease_blocking():
            raise RuntimeError("canon vault is locked by another live session")
        self._lock_depth += 1

    def _acquire_lease_blocking(self) -> bool:
        """Acquire the single-writer lease, waiting in a FIFO ticket queue while it is held by ANOTHER
        live session, so near-simultaneous writers SERIALIZE cleanly instead of one failing outright
        (a full parallel /kg-build wave's brief writes, or the detached reconcile worker racing a
        server write — see LOCK_ACQUIRE_TIMEOUT for why contention is only ever cross-process).

        LeaseLock.acquire() is idempotent for the OWNING process (same pid → re-acquire returns True on
        the first attempt), so the server's own serialized writes take the fast path below and never
        queue; only a foreign LIVE holder makes us wait, and it keeps the lease just for its own brief
        write. A foreign DEAD holder on the SAME host is reclaimed by acquire() itself (staleness via
        pid-probe), not by waiting; a cross-host (or Windows) dead holder can't be pid-probed, so it is
        seen stale only once its lease TTL lapses — the writer may wait up to the budget first, then a
        later attempt reclaims it. Returns False only after the whole `lock_acquire_timeout` budget
        elapses (a wedged live, or not-yet-TTL-stale cross-host dead, foreign holder), which the caller
        surfaces as the locked-vault error. Only writers reach this; try_acquire_lock() stays strictly
        non-blocking so the lazy projector never stalls a read behind a write."""
        deadline = time.monotonic() + self.lock_acquire_timeout
        # Fast path: free, or already ours. Nearly every write is uncontended (a wave funnels through the
        # ONE server process), so that case must not pay a single extra syscall for fairness — the queue
        # is touched only after a real miss. The cost is that a fresh arrival gets this one un-queued
        # attempt and can therefore barge past the queue, but only by landing inside the sub-poll window
        # where the lease is free AND the front waiter is between polls; once a wave has missed once,
        # every writer in it is queued and strictly ordered.
        try:
            if self.lock.acquire():
                return True
        except OSError:
            pass  # see the fail-closed note in _acquire_lease_unfair
        if time.monotonic() >= deadline:
            return False  # a zeroed budget keeps the pre-retry immediate-fail behavior exactly
        ticket = None
        try:
            while True:
                if time.monotonic() >= deadline:
                    return False
                if ticket is None:
                    ticket = self.lock.enqueue()
                    if ticket is None:
                        # No queue available (read-only vault, permissions): fall back to the unfair
                        # backoff loop rather than fail a write over a fairness optimization.
                        return self._acquire_lease_unfair(deadline)
                    last_hb = last_probe = last_progress = time.monotonic()
                    best_pos = -1
                # Re-validate the tickets ahead only about once a second; the rest of the time the
                # position comes from the listing alone. See queue_position: opening a ticket blocks
                # its owner's own dequeue on Windows, and the front ticket is the one every waiter
                # would otherwise re-read on every poll.
                probe = (time.monotonic() - last_probe) >= LOCK_QUEUE_PROBE_SECS
                pos = self.lock.queue_position(ticket, probe=probe)
                if probe:
                    last_probe = time.monotonic()
                if pos < 0:
                    ticket = None  # reaped under us (a stall past our TTL) — rejoin at the back
                    continue
                if best_pos < 0 or pos < best_pos:
                    best_pos, last_progress = pos, time.monotonic()
                elif (time.monotonic() - last_progress) > LOCK_QUEUE_STALL_SECS:
                    return self._acquire_lease_unfair(deadline)  # queue wedged — see LOCK_QUEUE_STALL_SECS
                if pos == 0:
                    try:
                        if self.lock.acquire():
                            return True
                    except OSError:
                        pass
                now = time.monotonic()
                if now >= deadline:
                    return False
                # Keep our place: a ticket that stops being refreshed goes stale within
                # LOCK_QUEUE_TICKET_TTL, which is exactly what reclaims a LEAKED one.
                if (now - last_hb) > (LOCK_QUEUE_TICKET_TTL / HEARTBEAT_REFRESHES_PER_TTL):
                    self.lock.heartbeat_ticket(ticket)
                    last_hb = now
                # Front of the queue polls tightly (that interval IS the wave's per-writer handoff cost);
                # everyone else scales back, since by definition they cannot be served until the writers
                # ahead of them drain.
                time.sleep(min(max(pos, 1) * LOCK_QUEUE_POLL_MIN, LOCK_QUEUE_POLL_MAX, deadline - now))
        finally:
            if ticket is not None:
                self.lock.dequeue(ticket)

    def _acquire_lease_unfair(self, deadline: float) -> bool:
        """The pre-queue acquire: poll the lease on bounded exponential backoff until `deadline`. Kept
        as the degradation path for a vault where the ticket queue can't be created — it still
        serializes contended writers, it just gives up the FIFO ordering and the prompt handoff."""
        backoff = LOCK_RETRY_INITIAL
        while True:
            try:
                if self.lock.acquire():
                    return True
            except OSError:
                # A transient filesystem error while acquiring under contention — most often a Windows
                # sharing violation (PermissionError) when another writer momentarily holds the lock file
                # open for its own read/rename/O_EXCL-create. Treat it as "didn't get the lease this
                # attempt" and retry within the budget instead of crashing the write; this is the same
                # fail-closed posture as the lock reader (an error never reads as "free"). If it persists
                # past the deadline the caller surfaces the locked-vault error rather than the raw OSError.
                pass
            now = time.monotonic()
            if now >= deadline:
                return False
            time.sleep(min(backoff, deadline - now))
            backoff = min(backoff * 2, LOCK_RETRY_MAX)

    def release_lock(self) -> None:
        self._lock_depth -= 1
        if self._lock_depth <= 0:
            self._lock_depth = 0
            self.lock.release()

    # Back-compat aliases for the pre-review-r5 underscore names (external pins may hold them).
    _acquire_lock = acquire_lock
    _release_lock = release_lock

    def try_acquire_lock(self) -> bool:
        """Non-raising acquire for best-effort callers (the lazy projector): take the single-writer
        lease if free/ours, else return False so the caller can serve what it has instead of blocking
        or crashing. Re-entrant within this process like acquire_lock.

        Deliberately does NOT queue (see LOCK_QUEUE_DIRNAME): it is a single opportunistic attempt, so
        it can only ever take a lease that is free at that instant — it never waits, and therefore can
        never be the thing that starves a queued writer for long. Making it respect the queue would
        instead make it fail whenever any writer is waiting, stalling the read path it exists to serve."""
        if self._lock_depth == 0:
            try:
                if not self.lock.acquire():
                    return False
            except OSError:
                # acquire() reads/creates the lock file and can raise OSError (most often a Windows
                # sharing violation while another writer momentarily holds it open). For this NON-raising
                # best-effort path that must read as "didn't get the lease this attempt" — the same
                # fail-closed posture as the blocking writer (_acquire_lease_blocking) — never crash the
                # read tool that triggered the lazy reproject; the caller serves the stale derived layer.
                return False
        self._lock_depth += 1
        return True

    @staticmethod
    def _assert_no_slug_collision(node_id: str, existing: "Node", p: Path) -> None:
        """Refuse a write whose target file already holds a DIFFERENT node id — two ids that slug to
        the same filename would silently merge into one note. One place so write_one's check and the
        batch merge raise the identical message."""
        if existing.id != node_id:
            raise ValueError(
                f"node id slug collision: {node_id!r} and {existing.id!r} both map to {p.name}")

    def _check_slug_collision(self, node: "Node") -> None:
        """Two distinct ids that slug to the same filename would silently merge into one note.
        Detect and refuse rather than corrupt either node."""
        p = self.node_path(node.id)
        if not p.exists():
            return
        try:
            existing = node_from_markdown(p.read_text(encoding="utf-8"), fallback_id=node.id)
        except Exception:
            # An UNREADABLE existing note at the target path. With fallback_id=node.id we cannot tell
            # whether it is the node's OWN corrupt file (the common self-heal case — overwrite-to-repair
            # must keep working) or a distinct/foreign note that would be silently destroyed. Be
            # conservative: back up its raw bytes BEFORE the write proceeds so the overwrite is never
            # lossy, then allow the write (F28). The backup is a dotfile, so note_paths() ignores it.
            self._backup_unreadable(p)
            return
        self._assert_no_slug_collision(node.id, existing, p)

    @staticmethod
    def _backup_unreadable(p: Path) -> None:
        """Preserve the raw bytes of an unreadable note about to be overwritten, under a dotfile sibling
        (hidden from note_paths()), so a foreign/corrupt note is recoverable rather than lost."""
        try:
            data = p.read_bytes()
        except OSError:
            return  # cannot read the bytes at all — nothing to preserve, let the write proceed
        backup = p.with_name(f".{p.name}.unreadable-{int(time.time() * 1000)}.bak")
        try:
            _atomic_write_bytes(backup, data)
        except OSError:
            pass  # best-effort backup; never block the self-heal write on it

    # ---- paths
    def node_path(self, node_id: str) -> Path:
        """Resolve a node id to its canon file, confined to the vault (§Stage 9 hardened resolver).

        `slug()` already strips path separators, dots, and control bytes, so traversal is structurally
        impossible; this is the explicit belt-and-suspenders vault-prefix check (logical chroot): a
        null byte is rejected outright and the resolved path must stay under the canon dir.
        """
        if "\x00" in str(node_id):
            raise ValueError("null byte in node id")
        notes_dir = self._notes_dir_resolved  # cached at __init__ (perf #17) — fixed for this Canon
        p = (notes_dir / f"{slug(node_id)}.md").resolve()
        if p != notes_dir and notes_dir not in p.parents:
            raise ValueError(f"path escapes canon vault: {node_id!r}")
        return p

    def exists(self, node_id: str) -> bool:
        return self.node_path(node_id).exists()

    # ---- read
    def read_node(self, node_id: str) -> Node:
        p = self.node_path(node_id)
        return node_from_markdown(p.read_text(encoding="utf-8"), fallback_id=node_id)

    def note_paths(self) -> list[Path]:
        """Canon note files, excluding the `.tmp-*.md` atomic-write temporaries (a crash between
        mkstemp and os.replace can leave one behind; globbing `*.md` would otherwise treat it as a
        phantom node — canon-5). One place so every reader (here + reconciler) filters identically."""
        return [p for p in sorted(self.notes_dir.glob("*.md")) if not p.name.startswith(".")]

    def reap_transient_files(self, *, now: float | None = None) -> int:
        """Bounded-retention housekeeping for the transient dotfiles the I/O paths leave behind, so a
        long-lived vault does not grow them without limit. Best-effort and idempotent: a failed unlink
        is swallowed and retried next sweep. Returns the count removed.

        - `.{name}.unreadable-*.bak` (F28 self-heal backups): keep the newest BACKUP_RETENTION_PER_NOTE
          per note (so a foreign/corrupt note stays recoverable — the F28 intent) and prune the rest.
        - crash-leftover `.tmp-*` (atomic-write temporaries), sidelined locks
          (`.kg-session-lock.stale-*`/`.release-*`) and abandoned lease tickets
          (`.kg-session-lock.q/*.json`): prune only once older than TRANSIENT_REAP_TTL — well past any
          live atomic-write, lock-reclaim or lease-wait window — so the reaper never races a write.

        Designed to be wired into the reconciler's periodic full sweep (which already walks the canon
        dir); it lives here because Canon owns the transient-file naming. The lock sidelines sit under
        `root`, the backups/temps under `notes_dir`."""
        now = time.time() if now is None else now
        removed = 0

        def _unlink(p: Path) -> None:
            nonlocal removed
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass  # best-effort — a vanished/locked file is retried next sweep

        def _aged(p: Path) -> bool:
            try:
                return (now - p.stat().st_mtime) > TRANSIENT_REAP_TTL
            except OSError:
                return False  # cannot stat -> leave it for next sweep

        # group `.{name}.unreadable-<ms>.bak` by the note they back up; the <ms> stamp sorts oldest-first.
        backups: dict[str, list[Path]] = {}
        try:
            for p in self.notes_dir.glob(".*.unreadable-*.bak"):
                stem = p.name[1:p.name.rindex(".unreadable-")]  # strip leading dot + ".unreadable-...bak"
                backups.setdefault(stem, []).append(p)
        except OSError:
            backups = {}
        for paths in backups.values():
            for stale in sorted(paths, key=lambda q: q.name)[:-BACKUP_RETENTION_PER_NOTE]:
                _unlink(stale)

        # crash-leftover atomic-write temporaries (notes_dir) and sidelined lock records (root), TTL-gated.
        for p in self.notes_dir.glob(".tmp-*"):
            if _aged(p):
                _unlink(p)
        for pat in (".tmp-*", f"{LOCK_NAME}.stale-*", f"{LOCK_NAME}.release-*"):
            for p in self.root.glob(pat):
                if _aged(p):
                    _unlink(p)
        # Crash-leftover lease tickets. Their owner drops them in a finally, and a crashed owner's is
        # reaped by the next waiter that queues behind it, so this only catches the vault where nobody
        # ever contends again — TTL-gated like the sidelines so it can never race a LIVE waiter.
        for p in self.root.glob(f"{LOCK_QUEUE_DIRNAME}/*.json"):
            if _aged(p):
                _unlink(p)
        return removed

    def parse_note(self, p: Path) -> "Node | None":
        """Parse ONE note file under the canon's tolerance policy: an unreadable/malformed note
        returns None instead of raising (one bad note must not crash every read, §1.2). The single
        home of the per-file rule — all_nodes and the projector's stat-gated incremental parse
        (review-r6) both consume it, so they can never disagree on which files count as nodes."""
        try:
            return node_from_markdown(p.read_text(encoding="utf-8"), fallback_id=p.stem)
        except Exception:  # noqa: BLE001 — one unreadable/malformed note must not crash every read
            return None

    def all_nodes(self) -> list[Node]:
        return [n for p in self.note_paths() if (n := self.parse_note(p)) is not None]

    def all_edges(self) -> list[Edge]:
        return [e for n in self.all_nodes() for e in n.edges]

    # ---- single-file atomic write
    def write_one(self, node: Node) -> None:
        node.updated_at = utcnow()
        self.acquire_lock()
        try:
            self._check_slug_collision(node)
            _atomic_write(self.node_path(node.id), node_to_markdown(node))
        finally:
            self.release_lock()

    # ---- multi-file mutation with snapshot-restore rollback
    def write_nodes(self, nodes: list[Node], *, message: str, commit: bool = True,
                    merge: bool = True) -> RollbackInfo:
        """Write a batch of nodes, then one commit. With `merge` (default) incoming edges are merged
        into existing notes (single-canonical-edge rule); with `merge=False` each node is written
        verbatim (used by kg_rename, which has already rewritten every endpoint and must NOT re-merge
        the pre-rename edges back in). On any WRITE failure restore the pre-batch in-memory byte
        snapshot of every touched file (same on git and non-git vaults), so a partial batch never
        persists (§Stage 1). The commit is OUTSIDE the rollback scope and best-effort: once the atomic
        writes have durably landed, a git failure (unset user.name/email, a rejecting hook, index.lock
        contention) must NOT revert the already-fsynced canon — mirror kg_rename (write, then check=False
        add/commit)."""
        self.acquire_lock()
        try:
            snapshot = {}
            try:
                # snapshot every target file BEFORE writing so a non-git/pre-commit vault can still roll
                # back. INSIDE the rollback try: a present-but-unreadable note (permission error, or a
                # transient Windows sharing violation) then returns RollbackInfo, not a raw exception, to
                # the boundary — no write has happened yet, so restoring the partial snapshot of untouched
                # files is a safe no-op.
                for n in nodes:
                    p = self.node_path(n.id)
                    snapshot[p] = p.read_bytes() if p.exists() else None
                self._write_batch(nodes, merge)
            except Exception as e:  # noqa: BLE001 — rollback must catch everything
                return self._rollback(str(e), snapshot)
            # The writes have durably landed; the commit is OUTSIDE the rollback try (F2).
            if commit:
                self._commit_batch(message, snapshot)
            return RollbackInfo(rolled_back=False)
        finally:
            self.release_lock()

    def _write_batch(self, nodes: list[Node], merge: bool) -> None:
        """The write half of write_nodes — everything INSIDE the rollback scope (review-r5: the
        heartbeat cadence and merge/no-op logic were inlined between the snapshot and the commit,
        burying the one thing that must stay obvious there: the rollback boundary).

        Throttles the lease heartbeat: each heartbeat is a full durable lock rewrite
        (mkstemp+fsync+replace+dir-fsync), and lease correctness comes from the TTL + CAS
        acquire/reclaim, NOT cadence — so refresh at most once per ttl/HEARTBEAT_REFRESHES_PER_TTL
        (a long batch stays comfortably fresh inside the TTL window; a sub-interval batch
        heartbeats once).

        Fsyncs the canon directory ONCE for the whole batch rather than once per note. Every note lives
        directly under the flat `canon/` dir (`node_path`), and a single directory fsync after the last
        `os.replace` makes ALL of the batch's renames durable — the per-file dir fsync was redundant work
        on the same inode: 802 fsyncs costing 1.39s of a 3.58s 400-node batch, most visible on /kg-build
        waves. Per-FILE durability is unchanged (each `atomic_write_text` still fsyncs its own contents
        before the rename); only the directory-entry fsync is hoisted. A crash mid-batch is already
        handled by the snapshot rollback, and the batch is not atomic across files either way
        (review-r11)."""
        hb_interval = self.lock.ttl / HEARTBEAT_REFRESHES_PER_TTL
        last_hb = time.monotonic()
        self.lock.heartbeat()  # one refresh up front, then only when hb_interval has elapsed
        wrote_any = False
        for node in nodes:
            now_mono = time.monotonic()
            if (now_mono - last_hb) > hb_interval:
                # refresh the lease while a long batch is in flight so a concurrent session can't
                # judge it stale (TTL) and steal the lock mid-write, breaking single-writer.
                self.lock.heartbeat()
                last_hb = now_mono
            # On the merge path `_merge_into_existing` already parsed the on-disk note and handed back its
            # content hash, so the no-op guard below costs no second read+YAML-parse of the same file.
            merged, pre_hash = self._merge_into_existing(node) if merge else (node, None)
            p = self.node_path(merged.id)
            # Idempotent no-op guard: if the note already on disk is byte-identical to what we
            # would write EXCEPT for created_at/updated_at, skip both the write and the
            # updated_at bump. Otherwise an idempotent re-run (edges all deduped, source nodes
            # re-written) would rewrite each note with a fresh timestamp — non-byte-stable canon
            # and timestamp-only commits. Compare a content hash that ignores the timestamps
            # (model.node_content_hash — the same rule the projector's staleness gate consumes).
            if p.exists():
                if pre_hash is None:
                    # The no-merge path (kg_rename) never parsed the note; do it here. An unreadable
                    # note falls through to the write, exactly as before.
                    try:
                        pre_hash = self._content_hash(node_from_markdown(
                            p.read_text(encoding="utf-8"), fallback_id=merged.id))
                    except Exception:  # noqa: BLE001 — unreadable existing note: fall through to write
                        pre_hash = None
                if pre_hash is not None and pre_hash == self._content_hash(merged):
                    continue  # real content unchanged — leave the note (and its timestamp) as-is
            merged.updated_at = utcnow()
            _atomic_write(p, node_to_markdown(merged), fsync_dir=False)
            wrote_any = True
        if wrote_any:
            # One directory fsync for the whole batch — see the docstring. Best-effort like the
            # per-write one (`atomicio.fsync_dir` swallows OSError on filesystems that refuse it).
            fsync_dir(self._notes_dir_resolved)

    def _commit_batch(self, message: str, snapshot: dict) -> None:
        """The best-effort git tail of write_nodes, AFTER the writes durably landed: a non-zero git
        exit (unset user.name/email, a rejecting hook, index.lock contention) must NOT revert the
        already-fsynced canon (F2) — everything here is check=False and outside the rollback scope.

        Stage only this batch's paths (`snapshot` already knows them): `git add -A` would rescan the
        whole working tree per boundary batch. No --allow-empty: an idempotent/no-op batch (deduped
        edges, an identical re-write) would otherwise force an EMPTY commit that pollutes vault
        history — a no-op commit exits non-zero, which check=False ignores harmlessly. The COMMIT is
        scoped to the same pathspec (a bare `git commit` would record the WHOLE staged index,
        including any unrelated file another process staged concurrently)."""
        if not self.git_enabled:
            return  # an ephemeral vault under a parent repo (second construction) — never commit (H1)
        if not (snapshot and _git_ok(self.root)):
            return
        paths = [str(p) for p in snapshot]
        _git(self.root, "add", "--", *paths, check=False)
        _git(self.root, "commit", "-m", message, "--", *paths, check=False)

    @staticmethod
    def _content_hash(node: Node) -> str:
        """Content hash of a note excluding timestamps — model.node_content_hash, the ONE rule this
        and projector._file_hash both consume (review-r5: their agreement is load-bearing and used
        to rest on two byte-identical copies). Used by write_nodes to detect an idempotent no-op
        re-write so it does not churn the note's updated_at (and thus its bytes / git history) when
        nothing real changed."""
        return node_content_hash(node)

    def _merge_into_existing(self, node: Node) -> "tuple[Node, str | None]":
        """Apply the single-canonical-edge rule: merge incoming edges into an existing note.

        Returns `(merged, pre_hash)` where `pre_hash` is the content hash of the note AS IT WAS ON DISK,
        or None when there was no existing note. `_write_batch`'s idempotent-no-op guard needs exactly
        that hash and used to obtain it by reading and YAML-parsing the same file a SECOND time — 0.41s
        of a 0.75s idempotent 400-node re-write, on the commonest path there is (every extractor edge-write
        whose source node already exists, and every idempotent /kg-build re-run). We already hold the
        parsed pre-merge node here, so hash it before the mutation below destroys it (review-r11)."""
        p = self.node_path(node.id)
        if not p.exists():
            return node, None
        # Parse the existing note once here and fold the slug-collision check in, so the batch path
        # never double-parses. An unreadable existing note is backed up and the parse error re-raised
        # (the merge path then rolls back the batch); a readable note whose id differs raises the
        # slug-collision ValueError via the shared check.
        try:
            cur = node_from_markdown(p.read_text(encoding="utf-8"), fallback_id=node.id)
        except Exception:
            self._backup_unreadable(p)  # preserve foreign/corrupt bytes before anything overwrites them
            raise
        self._assert_no_slug_collision(node.id, cur, p)
        # Snapshot the on-disk identity BEFORE `cur` is mutated in place into the merged result.
        pre_hash = self._content_hash(cur)
        # key by the canonical edge id (the slug) — the same key the boundary dedup and disk use, so
        # all three layers agree on what "one edge" is (boundary-1 / §1.4).
        by_id = {e.id: e for e in cur.edges}
        for e in node.edges:
            prev = by_id.get(e.id)
            # verdict-durability defense-in-depth (review-C1, §1.8): never silently downgrade a
            # verdict-bearing edge back to `unverified` on a merge. The write boundary already
            # quarantines such re-emits, so in normal flow this never fires; it protects any direct
            # write_nodes(merge=True) caller. The reconciler's LEGITIMATE demote-to-unverified goes
            # through write_one (no merge), so it is unaffected; kg_ground stamps a non-`unverified`
            # state, so its merges don't trip this either.
            if (prev is not None and prev.epistemic_state in GROUNDABLE_STATES
                    and e.epistemic_state == EpistemicState.UNVERIFIED):
                # Preserve not just the verdict state but the evidence it rests on. The reachable path
                # is a kg_propose re-proposal of an already-grounded edge (the hypothesized lane skips
                # the verdict_ids check, boundary.py — grounded structure is deduped, not quarantined, so
                # only FAILURE_STATES bind generation), whose bare incoming object would otherwise revert
                # a PROMOTED hypothesis's provenance (e.g. back to `hypothesized`), blank its support
                # span, and drop the verdict notes — the citation / falsification rationale §1.7 must
                # survive forever. Carry ALL of prev's verdict-associated fields — state, attribution,
                # provenance, span, notes, AND the source_file / confidence / confidence_score /
                # authored_by that the grounding rests on — so the stored edge stays a consistent
                # grounded/rejected/failed object, not a verdict floating over blanked evidence: dropping
                # source_file in particular breaks re-grounding in multi-file (R4) setups (review-r8-2).
                e.epistemic_state = prev.epistemic_state
                e.verdict_by = prev.verdict_by
                e.verdict_at = prev.verdict_at
                e.provenance = prev.provenance
                e.span = prev.span
                e.notes = prev.notes
                e.source_file = prev.source_file
                e.confidence = prev.confidence
                e.confidence_score = prev.confidence_score
                e.authored_by = prev.authored_by
            by_id[e.id] = e  # incoming wins (already validated)
        cur.edges = list(by_id.values())
        # Verdict-durability, NODE lane (§1.7, review-r11) — the exact analogue of the edge guard above.
        # A node's grounding evidence lives in its BODY: a Node has no `span` field, so
        # server._promote_hypothesis_node restates the support as `grounding span: …` / `citation: …`
        # appended to `node.body`. An ordinary re-emit of the same node id (the same /kg-generate
        # mechanism run twice, an extractor restating a node in a later section) is deduped-ACCEPTED by
        # the boundary — nodes have no `_durability_quarantine` — so an unguarded overwrite would leave
        # `epistemic_state: grounded, provenance: span-present` with the span it rests on GONE. The
        # verdict would float over blanked evidence, the precise state the edge guard exists to prevent.
        # `cur.epistemic_state` (not the incoming one) is the test: kg_ground persists via write_one, so
        # it never reaches this merge path and can never be blocked by its own verdict.
        if node.body and cur.epistemic_state not in GROUNDABLE_STATES:
            cur.body = node.body
        # A bare edge-only write carries a placeholder Node(id=src) whose label DEFAULTS to the id
        # (Node.__post_init__ sets label=id when blank, so `node.label` is never falsy — the old
        # `node.label or cur.label` was a no-op that clobbered a rich human label with the bare id).
        # Only adopt an incoming label that is genuinely richer than the id (mirror the node_type
        # 'undeclared-type' guard just below).
        if node.label and node.label != node.id:
            cur.label = node.label
        if node.node_type and node.node_type != UNDECLARED_TYPE:
            cur.node_type = node.node_type
        return cur, pre_hash

    def _rollback(self, error: str, snapshot: dict | None = None) -> RollbackInfo:
        """Undo a failed batch by restoring ONLY the files it touched, from the pre-batch snapshot.

        This is the same scoped restore on both git and non-git vaults. A repo-wide `git reset --hard
        HEAD` (the old git path) would also discard unrelated UNCOMMITTED work — most importantly the
        grounding verdicts kg_ground writes via write_one without a commit, plus in-progress hand
        edits — silently reverting them to their last committed state. Scoping to `snapshot` keeps the
        rollback confined to this batch and never disturbs anything else in the working tree.
        """
        restore_errors: list[str] = []
        if snapshot:
            for p, original in snapshot.items():
                # Guard each per-file restore so a SECOND I/O fault (after the write fault that
                # triggered this rollback) never propagates out of write_nodes: the boundary must
                # always receive a RollbackInfo, never a raw exception. Accumulate any restore failure
                # into the returned error so it is surfaced rather than swallowed.
                try:
                    if original is None:
                        p.unlink(missing_ok=True)  # file was newly created by this batch -> remove it
                        # fsync the parent so the dirent REMOVAL is as durable as the create it reverses
                        # (atomic_write_bytes dir-fsyncs after os.replace). Without this, a crash right
                        # after rollback can resurrect the just-deleted note's dirent, leaving a phantom
                        # node the projector treats as real — the restore branch below is already durable.
                        fsync_dir(p.parent)
                    else:
                        # atomic + fsynced restore, consistent with the rest of the module — a crash mid
                        # rollback must not leave a half-written note (review-low: rollback non-atomic).
                        _atomic_write_bytes(p, original)
                except Exception as ex:  # noqa: BLE001 — rollback must never raise out of write_nodes
                    restore_errors.append(f"{p.name}: {ex}")
        if restore_errors:
            error = f"{error}; rollback restore failures: {'; '.join(restore_errors)}"
        return RollbackInfo(rolled_back=True, error=error)
