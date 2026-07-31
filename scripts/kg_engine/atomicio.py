"""Crash-safe atomic file writes — a stdlib-only LEAF module.

Imported by the engine (``canon.py``, ``projector.py``) AND by the installer
(``bootstrap.py``), so it must depend on NOTHING beyond the standard library: bootstrap runs
while building the very venv the engine's third-party deps live in, before those deps are
importable. (``kg_engine.__init__`` is import-light — just ``__version__`` — so importing this
module never pulls in the heavy engine.)

The protocol is temp-file -> flush -> fsync -> ``os.replace``, so a reader ever sees either the
old file or the complete new one, never a torn write. ``fsync_dir`` additionally makes the
rename itself durable across a crash (the directory entry), not only the file contents.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

_REPLACE_TIMEOUT = 5.0    # seconds — a DEADLINE, matched to the lease lock's LOCK_REPLACE_RETRY_TIMEOUT
_REPLACE_BACKOFF = 0.05   # initial sleep; doubles per attempt, capped by _REPLACE_BACKOFF_MAX
_REPLACE_BACKOFF_MAX = 0.25


def _replace_with_retry(tmp: str, path: Path) -> None:
    """``os.replace(tmp, path)`` with a bounded retry for the Windows sharing-violation case.

    On Windows, replacing a destination another process holds open WITHOUT ``FILE_SHARE_DELETE`` raises
    ``PermissionError`` (ERROR_SHARING_VIOLATION): e.g. a lease-free canon reader (a second session, the
    per-session reconcile worker, the headless backend) mid-reading the note, or the AV/search indexer
    briefly opening the freshly-renamed file. The lease lock file already retries the same transient
    class to a ~5s deadline (``canon._acquire_lease_blocking`` / ``LOCK_REPLACE_RETRY_TIMEOUT``); mirror
    that DEADLINE here so a momentary concurrent open does not fail an otherwise-valid canon write —
    which, via ``canon.write_nodes``, would spuriously roll back the whole batch. Previously this capped
    at 5 attempts / ~0.5s total — an order of magnitude shorter than the lease lock's budget, so a brief
    AV/indexer hold (>0.5s, common on Windows) would roll back a full /kg-build wave that the lease file
    would have survived (review-fix). A no-op on POSIX, where ``os.replace`` over an open file succeeds."""
    deadline = time.monotonic() + _REPLACE_TIMEOUT
    backoff = _REPLACE_BACKOFF
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(backoff, _REPLACE_BACKOFF_MAX))
            backoff *= 2


def fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename into it is durable across a crash (best-effort; not all
    platforms/filesystems support directory fds)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# Back-compat alias for the pre-review-r5 underscore name: three modules consume this seam, so the
# `_` prefix mis-signalled "don't depend on me".
_fsync_dir = fsync_dir


def atomic_write_bytes(
    path: Path, data: bytes, *, mkparents: bool = True, fsync_dir: bool = True,
    durable: bool = True,
) -> None:
    """Write ``data`` to ``path`` atomically (temp + fsync + ``os.replace``).

    ``mkparents`` creates the parent directory first; ``fsync_dir`` fsyncs the parent after the
    rename so the directory entry is durable too. Callers that know the parent already exists
    and do not need directory durability (e.g. the bootstrap readiness pointer/stamp) pass both
    ``False`` to keep the write minimal.

    ``durable=False`` skips BOTH fsyncs (file and directory) while keeping the temp +
    ``os.replace`` atomicity: readers still never observe a torn file; only crash durability is
    given up. For state whose loss on a power cut is already an accepted outcome — the divergence
    session zone (I10) pays several fsync pairs per ingest for files that are wiped on the next
    session anyway (review-r6).
    """
    path = Path(path)
    if mkparents:
        path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            if durable:
                os.fsync(f.fileno())
        # Preserve the destination's existing permission bits across the inode-replacing os.replace.
        # mkstemp fixes the temp at 0o600, so without this every write would silently reset the canon
        # note (a "human-editable" vault file) to owner-only, stripping any group/other bit a user or
        # umask had granted. A brand-new file keeps the 0o600 default — a sensible private default for
        # potentially-sensitive scrubbed content, and there is no prior mode to preserve.
        # follow_symlinks=False (i.e. lstat): os.replace replaces the DIRECTORY ENTRY at `path`, so when
        # `path` is a symlink the entry that survives is a regular file and the link is gone. Copying the
        # TARGET's mode would then apply an unrelated file's permissions to the one we just wrote.
        # Identical to stat() for the regular files every engine caller passes; this only makes the
        # symlink case say what the replace actually does (bootstrap shares this module).
        try:
            os.chmod(tmp, os.stat(path, follow_symlinks=False).st_mode & 0o777)
        except OSError:
            pass  # destination absent (new file) or chmod unsupported — keep the mkstemp default
        _replace_with_retry(tmp, path)
        if durable and fsync_dir:
            # the public bool kwarg `fsync_dir` shadows the module function of the same name inside
            # this body — call the module-level alias to make the rename itself durable.
            _fsync_dir(path.parent)
    finally:
        # Best-effort cleanup: a failing unlink on the write-failure path (e.g. tmp already gone, or a
        # transient Windows sharing violation) must NOT mask the true exception propagating from the try.
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def atomic_write_text(
    path: Path,
    text: str,
    *,
    mkparents: bool = True,
    fsync_dir: bool = True,
    encoding: str = "utf-8",
    durable: bool = True,
) -> None:
    """Atomic text write — ``atomic_write_bytes`` over ``text.encode(encoding)``."""
    atomic_write_bytes(
        Path(path), text.encode(encoding), mkparents=mkparents, fsync_dir=fsync_dir,
        durable=durable,
    )
