"""dirlock — an atomic-mkdir directory lock with heartbeat liveness, steal-with-re-validation,
and token-checked release. A stdlib-only LEAF (the same constraint as ``atomicio``: bootstrap
imports this with a bare system Python, before any venv dependency exists).

Extracted from ``bootstrap.py`` in review-r5: it was a second, ~250-line lock implementation
living inside the installer, parallel-by-design to ``canon.LeaseLock`` (the lease-FILE twin that
guards canon writes) and kept correct only by keep-in-sync comments. The two protocols remain
deliberately separate — the mkdir-dir lock here works with zero dependencies and guards a whole
venv build; the CAS lease file there guards brief canon writes under a TTL — but the mkdir side
now has ONE home with its own unit-test surface instead of being re-derived inside bootstrap.

The parallel-by-design pairs with ``canon.LeaseLock``, stated once here:
  - steal discipline: sideline atomically (``os.replace``), RE-VALIDATE the exact dir moved
    aside, restore it when the holder proves live (``LeaseLock._reclaim_stale``);
  - release ownership re-check via a nonce token, so a falsely-stolen holder never deletes the
    thief's fresh lock on its way out (F15);
  - pid-probe semantics: cross-host or host-less records assume-alive; same-host records are probed
    on BOTH platforms — ``os.kill(pid, 0)`` on POSIX, ``OpenProcess`` (``_win_pid_alive``) on Windows,
    since ``os.kill(pid, 0)`` there is CTRL_C_EVENT, not an existence check (FALLO 2).

Every function takes the LOCK DIR path itself; the caller owns where that lives (bootstrap keys
it beside the venv, so a half-built venv can never shadow its own lock).
"""
from __future__ import annotations

import os
import shutil
import socket
import time
import uuid
from pathlib import Path

# The owner token this process wrote into each lock it currently holds, keyed by the lock dir
# path. release() only rmtrees a lock whose ``info`` still carries OUR token — so a holder that
# was falsely stolen (suspend/resume past the staleness window) never deletes the thief's fresh
# lock (mirrors canon.LeaseLock.release's ownership re-check, F15). Cleared on release; a token
# surviving here for a lock we no longer own simply never matches the info.
_OWNED_TOKENS: dict[str, str] = {}
_HOST = socket.gethostname()

# Grace window protecting the brief just-mkdir'd, info-less window of a healthy acquirer: between
# ``lock.mkdir()`` and the ``info`` write in ``try_acquire`` the dir has no ``info`` record, so
# ``parse_info`` -> {} -> ``pid_probe`` reads pid=0 -> "dead" -> stealable, and a racer would steal a
# perfectly-healthy lock a peer just claimed (two concurrent venv builds). An info-less lock younger
# than this is treated as a mid-acquire holder (NOT stealable); only past the grace is it a genuine
# crash-orphan that never got its info written and may be reclaimed (review: info-less-window steal).
_INFO_GRACE_SECS = 5.0

# Bounded retry for the Windows sharing-violation case on the two directory renames below. Both
# `release` and `_steal` move the LIVE lock dir aside with os.replace while every waiting
# provisioner is polling it — `try_acquire` -> `is_stealable` -> `parse_info` OPENS `lock/info` on
# each poll, and Python's open() does not grant FILE_SHARE_DELETE, so on Windows renaming a
# directory whose files are held open raises PermissionError (ERROR_SHARING_VIOLATION). The reader
# closes within microseconds; retrying is what turns that into a non-event.
#
# The budget is deliberately SHORTER than the 5s used by atomicio._replace_with_retry and
# canon._replace_lockfile, because the cost of giving up differs: there, a lost rename fails a WRITE
# (canon.write_nodes rolls back a whole build wave), so the deadline is sized to outlast an AV hold.
# Here, giving up leaks a lock that the next acquirer's pid_probe reclaims in milliseconds — so the
# budget is sized to outlast a normal reader window without stalling process exit, since `release`
# runs from bootstrap's `finally` as the session ends.
_REPLACE_TIMEOUT = 2.0     # seconds — deadline, not an attempt count
_REPLACE_BACKOFF = 0.02    # initial sleep; doubles per attempt
_REPLACE_BACKOFF_MAX = 0.2


def _new_token() -> str:
    return uuid.uuid4().hex


def _replace_with_retry(src: Path, dst: Path) -> None:
    """``os.replace(src, dst)`` retrying ONLY the Windows sharing violation.

    PermissionError alone is retried. Every other OSError propagates immediately and unchanged, so
    the callers' existing ``except OSError`` arms keep their current meaning and timing: a
    FileNotFoundError in ``_steal`` is a genuinely lost race (another racer already moved the dir)
    and must back off NOW rather than sleep out a budget waiting for a dir that is gone. A no-op on
    POSIX, where renaming a directory with open files inside succeeds.

    A persistent violation still raises after the deadline — the callers degrade from there exactly
    as they did before this retry existed (a leaked lock stays reclaimable via the pid probe and the
    staleness window; it is never a wedge)."""
    deadline = time.monotonic() + _REPLACE_TIMEOUT
    backoff = _REPLACE_BACKOFF
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            now = time.monotonic()
            if now >= deadline:
                raise
            time.sleep(min(backoff, _REPLACE_BACKOFF_MAX, deadline - now))
            backoff *= 2


def _info_record(token: str) -> str:
    # host+pid drive the liveness probe; the nonce token proves ownership across a stolen lock.
    return f"pid={os.getpid()} host={_HOST} token={token} t={time.time():.0f}\n"


def heartbeat_file(lock: Path) -> Path:
    return lock / "heartbeat"


def parse_info(lock: Path) -> dict[str, str]:
    """Parse the ``info`` record inside lock dir ``lock`` into a {key: value} map.

    Works on the live lock OR a sidelined copy, so the steal/release re-checks re-read the
    exact dir they moved aside. Missing/unreadable -> {}.
    """
    try:
        text = (lock / "info").read_text("utf-8")
    except OSError:
        return {}
    rec: dict[str, str] = {}
    for tok in text.split():
        key, sep, val = tok.partition("=")
        if sep:
            rec[key] = val
    return rec


def _win_pid_alive(pid: int) -> bool:
    """Windows liveness probe via ``OpenProcess`` + ``GetExitCodeProcess`` (ctypes — stdlib, so this
    stays importable with a bare system Python before any venv dep). Mirrors the POSIX ``os.kill(pid,
    0)`` semantics used below: a running pid → True, a pid that no longer exists → False, a pid we
    lack the rights to open (another user) → True (exists, assume alive).

    This is the FALLO 2 fix: on Windows ``os.kill(pid, 0)`` is CTRL_C_EVENT (it would interrupt the
    target), so the probe used to be skipped there and a crashed provisioner's lock could only be
    reclaimed once its heartbeat aged past ``STALE_LOCK_SECS`` (30 min). OpenProcess gives a real,
    cheap existence check, so a dead holder is reclaimed in milliseconds on Windows too. Any ctypes /
    loader hiccup returns True (fail SAFE: never steal a lock we cannot PROVE is dead). Its POSIX twin
    in ``canon._pid_probe`` carries the identical helper (the two locks are parallel-by-design)."""
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
            # No handle. ONLY ERROR_INVALID_PARAMETER (87) definitively means "no such process" → dead.
            # Every other failure fails SAFE to alive: ERROR_ACCESS_DENIED (5) is a live process owned by
            # another account (POSIX EPERM), and a transient error (e.g. ERROR_NOT_ENOUGH_MEMORY) against a
            # genuinely-live provisioner PID must NOT be read as dead and let its lock be stolen — the
            # module's "never over-steal a lock we cannot PROVE is dead" invariant (review-low).
            return ctypes.get_last_error() != ERROR_INVALID_PARAMETER
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                # A still-running process reports STILL_ACTIVE; anything else is a real exit code, so
                # the handle refers to an already-terminated (not-yet-freed) process → dead.
                return code.value == STILL_ACTIVE
            return True  # couldn't read the exit code → assume alive (never over-steal)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 — a ctypes/loader failure must never over-steal a live lock
        return True


def pid_probe(rec: dict[str, str]) -> bool:
    """True if the lock's recorded holder is (possibly) alive. Mirrors canon._pid_probe: a pid on
    another host (or no host recorded) is treated as alive; on the same host the pid is probed —
    ``os.kill(pid, 0)`` on POSIX, ``_win_pid_alive`` (OpenProcess) on Windows (FALLO 2: the probe is
    no longer skipped on Windows, so a crashed holder is reclaimed in ms rather than after the 30-min
    stale window)."""
    try:
        pid = int(rec.get("pid", "0"))
    except ValueError:
        pid = 0
    if not pid:
        return False
    host = rec.get("host", "")
    if host and host != _HOST:
        return True
    if not host:
        return True  # an old info record without a host can't be probed — assume alive
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


def lock_age(lock: Path) -> float:
    """Seconds since the holder last proved it is alive.

    Liveness is judged by the heartbeat file (refreshed by the holder's work loop, see
    ``heartbeat``), NOT by the lock-dir mtime: a long job (a cold igraph/leidenalg source
    build) can outlast the staleness window without ever touching the dir, and stealing a
    *live* holder's lock lets two jobs clobber the same target. Fall back to the dir
    mtime when no heartbeat has landed yet (the brief window right after mkdir).
    """
    hb = heartbeat_file(lock)
    try:
        return time.time() - hb.stat().st_mtime
    except OSError:
        try:
            return time.time() - lock.stat().st_mtime
        except OSError:
            return 0.0


def is_stealable(lock: Path, stale_secs: float) -> bool:
    """Whether the existing lock may be reclaimed: either its liveness signal has aged past
    ``stale_secs``, OR a cheap PID-liveness probe shows the recorded holder is dead on this
    host (mirrors canon.LeaseLock._rec_stale: TTL OR a failed os.kill probe). The probe makes
    a crashed holder reclaimable in milliseconds instead of the full staleness window.

    A lock whose heartbeat AND dir mtime are both unreadable reads as age 0 — NOT stealable:
    at the live path that is the brief just-mkdir'd window of a healthy acquirer (contrast
    ``is_stealable_sidelined``)."""
    if lock_age(lock) > stale_secs:
        return True
    rec = parse_info(lock)
    if not rec:
        # No info record yet: either a healthy acquirer mid-``try_acquire`` (between ``lock.mkdir()`` and
        # the info write) or a crash-orphan that never wrote one. Protect the acquire window — only an
        # info-less lock older than the grace is stealable, so a racer can't steal a lock a peer just
        # claimed (review: info-less-window steal). Past the grace it is a genuine orphan, reclaim it.
        return lock_age(lock) > _INFO_GRACE_SECS
    return not pid_probe(rec)


def is_stealable_sidelined(lock: Path, stale_secs: float) -> bool:
    """Staleness re-check against a SPECIFIC (already sidelined) lock dir, by its own
    heartbeat/dir mtime and PID probe — so the reclaim path re-validates the exact dir it
    moved aside rather than whatever now sits at the live path. Unlike ``is_stealable``, a
    dir that VANISHED under us reads as stealable — there is nothing live left to protect."""
    hb = heartbeat_file(lock)
    try:
        age = time.time() - hb.stat().st_mtime
    except OSError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return True  # vanished under us — nothing live to protect
    if age > stale_secs:
        return True
    rec = parse_info(lock)
    if not rec:
        # Same info-less grace as is_stealable: a lock sidelined mid-acquire (its info not yet written)
        # keeps its fresh mtime through os.replace, so a young info-less sideline is a live mid-acquire
        # holder to RESTORE, not a stale orphan to reclaim (review: info-less-window steal).
        return age > _INFO_GRACE_SECS
    return not pid_probe(rec)


def heartbeat(lock: Path) -> None:
    """Stamp the lock as alive. Called periodically by the holder's work loop so a slow but
    healthy job is never mistaken for an abandoned lock and stolen.

    If the heartbeat write fails (read-only fs, ENOSPC, AV/permission hiccup), touch the
    lock dir as a backstop so ``lock_age``'s fallback path still advances for a live holder
    instead of freezing at the mkdir-time mtime and getting the live job stolen (review-low).
    """
    hb = heartbeat_file(lock)
    try:
        if hb.exists():
            os.utime(hb, None)
        else:
            hb.write_text(f"pid={os.getpid()} t={time.time():.0f}\n", "utf-8")
    except OSError:
        try:
            os.utime(lock, None)
        except OSError:
            pass


def _reap_stale_orphans(lock: Path, stale_secs: float) -> None:
    """Sweep crash-orphaned ``<lock>.stale-*`` / ``<lock>.release-*`` sideline dirs.

    Reap only STALE orphans (mtime older than ``stale_secs``). A FRESH sideline may be the
    IN-FLIGHT dir of a CONCURRENT stealer/releaser (names are unique by pid+time_ns, so a
    fresh one isn't ours and isn't a crash orphan yet). rmtree-ing it out from under that
    racer would make its own re-validation see the dir "vanished" and STEAL a lock it meant
    to RESTORE — destroying a live holder. Gating on age spares the live racer while still
    reaping genuine crash orphans (the unique names already prevent ENOTEMPTY collisions).
    """
    now = time.time()
    for pattern in (f"{lock.name}.stale-*", f"{lock.name}.release-*"):
        for orphan in lock.parent.glob(pattern):
            try:
                if (now - orphan.stat().st_mtime) <= stale_secs:
                    continue  # too fresh — may be a concurrent racer's in-flight sideline
            except OSError:
                continue  # vanished/unreadable under us — nothing to reap
            shutil.rmtree(orphan, ignore_errors=True)


def _steal(lock: Path, stale_secs: float) -> bool:
    """Atomically reclaim a presumed-stale lock; True iff the caller may retry its mkdir.

    Renaming a directory is atomic, so exactly one racer moves the stale lock aside (the
    loser finds it already gone and backs off) — rmtree+mkdir alone is not atomic together.
    The sideline name is collision-proof (pid + time_ns): a crash between os.replace() and
    rmtree() orphans a non-empty sideline, and a reused name would hit ENOTEMPTY on
    os.replace (masked as a lost race) and never reclaim; ``_reap_stale_orphans`` sweeps the
    genuinely-old ones first. After the move, RE-VALIDATE the exact dir we moved: if the
    holder refreshed its heartbeat between our staleness read and the move, we just
    sidelined a LIVE lock — put it back and lose the race rather than destroy a live job
    (closes the reclaim TOCTOU, mirroring LeaseLock._reclaim_stale).
    """
    _reap_stale_orphans(lock, stale_secs)
    sidelined = lock.parent / f"{lock.name}.stale-{os.getpid()}-{time.time_ns()}"
    try:
        # Retry the Windows sharing violation (a peer polling `info` mid-steal): without it the
        # reclaim is abandoned for this round and the waiter re-loops a whole POLL_SECS later.
        _replace_with_retry(lock, sidelined)
    except OSError:
        return False  # lost the steal race; caller re-loops and waits
    if not is_stealable_sidelined(sidelined, stale_secs):
        try:
            # Retried too: a peer's handle on the file we just moved aside (it follows the file, not
            # the path) can block putting a LIVE holder's lock back. The documented failure below is
            # ENOTEMPTY from a third racer, which is NOT a PermissionError and so still fails fast.
            _replace_with_retry(sidelined, lock)
        except OSError:
            # A third racer created ``lock`` in the gap, so the restore failed. The dir we hold was JUST
            # re-validated as a LIVE holder — never rmtree it (that destroys a live holder's lock mid-job,
            # review-low). Leave it as a ``.stale-*`` sideline: ``_reap_stale_orphans`` collects it only
            # once it genuinely ages past ``stale_secs`` (a live holder's heartbeat lands in ``lock``,
            # now the racer's dir, so the sideline ages and is reaped harmlessly). Abandon our steal.
            pass
        return False
    shutil.rmtree(sidelined, ignore_errors=True)
    return True


def try_acquire(lock: Path, stale_secs: float) -> bool:
    """One non-blocking acquire attempt: mkdir the lock, stealing it first when stealable.

    On success the lock carries this process's ``info`` record (pid/host/nonce token) and a
    seeded heartbeat, and ``release`` becomes able to prove ownership. On any contention or
    hiccup, False — the caller re-loops/waits.
    """
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False  # unwritable/read-only FS: degrade to a clean "not ready" (caller re-loops/exits),
                      # never a raw PermissionError traceback out of provisioning (review-low).
    token = _new_token()
    try:
        lock.mkdir()
    except FileExistsError:
        if not is_stealable(lock, stale_secs):
            return False
        if not _steal(lock, stale_secs):
            return False
        try:
            lock.mkdir()
        except OSError:
            return False
    except OSError:
        return False  # a non-FileExistsError mkdir failure (read-only/permission-denied FS) is a clean
                      # "not ready", not a crash — mirror the parent.mkdir guard above (review-low).
    try:
        (lock / "info").write_text(_info_record(token), "utf-8")
        _OWNED_TOKENS[str(lock)] = token
    except OSError:
        # The info write failed (ENOSPC, a transient AV/permission hold). Do NOT return success
        # holding an UNOWNED lock: without the token, release() can't remove it (it leaks until
        # the staleness window), and with no `info` record pid_probe reads pid=0, so a concurrent
        # acquirer judges this just-acquired lock dead and STEALS it mid-job — two jobs clobbering
        # one target, the exact race this lock prevents. Abandon cleanly so the caller re-loops.
        shutil.rmtree(lock, ignore_errors=True)
        return False
    heartbeat(lock)  # seed liveness immediately so a just-acquired lock is never stale
    return True


def release(lock: Path) -> None:
    """Release the lock — but ONLY if it is still the one THIS process acquired.

    Mirror canon.LeaseLock.release's ownership re-check (F15): a holder that was falsely
    stolen (laptop suspend/resume spanning the staleness window froze its heartbeat) must not
    rmtree the thief's brand-new lock on its way out. We rename the lock aside (only one
    mover wins), confirm the MOVED ``info`` still carries our token, and only then remove
    it; otherwise we put it back untouched.
    """
    token = _OWNED_TOKENS.get(str(lock))
    if token is None:
        return  # we never recorded ownership of this lock — leave it alone
    sidelined = lock.parent / f"{lock.name}.release-{os.getpid()}-{time.time_ns()}"
    try:
        # THE leak site. A bare os.replace here made the release a no-op whenever a peer had
        # `lock/info` open on Windows: the OSError was read as "already reclaimed", the token was
        # dropped, and the lock dir outlived the process that owned it — reclaimable only via the
        # next acquirer's pid probe, or after STALE_LOCK_SECS if that pid had been recycled.
        _replace_with_retry(lock, sidelined)
    except OSError:
        _OWNED_TOKENS.pop(str(lock), None)
        return  # already gone/reclaimed — nothing of ours to release
    if parse_info(sidelined).get("token") == token:
        shutil.rmtree(sidelined, ignore_errors=True)
        _OWNED_TOKENS.pop(str(lock), None)
        return
    # We moved a foreign/changed lock aside (a successor reclaimed the path) — restore it.
    try:
        # Retried for the same reason, and it matters most here: the fallback below DESTROYS the dir
        # it could not put back, and that dir belongs to a successor who may be live. Retrying the
        # transient is what keeps a sharing violation from escalating into deleting someone's lock.
        _replace_with_retry(sidelined, lock)
    except OSError:
        shutil.rmtree(sidelined, ignore_errors=True)
    _OWNED_TOKENS.pop(str(lock), None)
