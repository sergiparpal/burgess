"""The crash-safe append-only grounding-audit log (§1.8) — the WRITER half of the forge-detection
contract whose READER half is ``reconciler._audit_counts``.

Each legitimate verdict transition appends one fsync'd ``{key, from, to, by, at}`` record (the log is
tamper-evidence). The offset/truncate dance lets a verdict's record be dropped if the accompanying canon
write fails, so a failed/rolled-back transition never leaves an ORPHAN record that would inflate the
reconciler's ``consumed`` tally and let a real forgery slip past (§1.8).

Extracted into this leaf (depends only on ``model.utcnow`` + the stdlib) so the durability protocol is
unit-testable without a full engine, and so the §1.8 writer has one home — separate from the KGEngine
facade and from the reconciler that reads it.

It does NOT acquire the canon lease: the caller (``kg_ground`` / ``kg_rename``) holds the lease across the
whole append + write + truncate sequence, so the record and the state change it justifies are atomic
w.r.t. other writers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .atomicio import atomic_write_text, fsync_dir
from .model import utcnow


class OrphanAuditError(RuntimeError):
    """A failed transition's compensating ``truncate`` could not complete, so an ORPHAN audit record
    survives in the log. Raised out of ``audited_write`` (never swallowed) so the caller surfaces a hard
    error instead of reporting a clean rollback — an un-truncatable orphan would otherwise inflate the
    reconciler's forge count and let a genuine out-of-band forgery slip past (§1.8)."""


class GroundAuditLog:
    def __init__(self, path: "str | os.PathLike"):
        self.path = Path(path)
        # The §1.8 spend-ledger checkpoint lives in a SEPARATE sidecar that is atomically OVERWRITTEN each
        # sweep — never appended to the append-only forgery/verdict log. Appending a whole-ledger snapshot
        # per session grew the log superlinearly and forced every fresh reconciler to re-parse it; the
        # sidecar keeps checkpoint storage O(1) and leaves the log bounded by real verdict volume.
        self.checkpoint_path = self.path.with_name(self.path.name + ".ckpt")

    def size(self) -> int:
        """Byte size of the log (0 only if genuinely absent). Captured BEFORE an append so
        ``audited_write`` can truncate an orphan record back on a failed write.

        ONLY ``FileNotFoundError`` maps to 0 — the one legitimate empty case. A different ``OSError``
        (EIO/ESTALE/read-only remount) on an EXISTING, populated log must NOT be reported as 0: that
        false floor would let ``audited_write``'s compensating ``truncate(offset)`` wipe every prior
        record on a subsequent write failure (silently re-quarantining all legitimate verdicts). Let
        such errors propagate so ``audited_write`` aborts before appending instead."""
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def append(self, key: str, frm: str, to: str, by: str) -> None:
        """Append one durable ``{key, from, to, by, at}`` record (fsync'd: the log is tamper-evidence).
        Also fsyncs the parent directory so the FIRST append's directory entry (log-file creation) is
        durable across a crash, mirroring the canon's crash-safe write protocol (atomicio, fsync_dir) —
        losing the whole log would silently re-quarantine every legitimate verdict on the next sweep."""
        rec = {"key": key, "from": frm, "to": to, "by": by, "at": utcnow()}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())
        fsync_dir(self.path.parent)  # durable directory entry (a no-op on platforms rejecting dir fds)

    def truncate(self, offset: int) -> bool:
        """Truncate the log back to ``offset`` — undoes records appended for a write that then failed, so
        no orphan record survives. Returns True on success, False on OSError (read-only remount, ENOSPC
        on the metadata update, EIO, the log rotated out from under the open): the caller MUST treat a
        False as a surviving orphan, not a clean rollback (§1.8). Also fsyncs the parent directory so the
        size change is durable, consistent with ``append``/atomicio."""
        try:
            with open(self.path, "r+", encoding="utf-8") as f:
                f.truncate(offset)
                f.flush()
                os.fsync(f.fileno())
            fsync_dir(self.path.parent)
            return True
        except OSError:
            return False

    def write_checkpoint(self, consumed: dict, epistemic: dict) -> bool:
        """Atomically OVERWRITE the spend-ledger CHECKPOINT sidecar with a snapshot of the reconciler's
        ``consumed`` tally and ``epistemic`` baseline at the end of a sweep.

        The checkpoint lets the reconciler RECOVER the spend ledger from a durable source instead of
        replaying the whole log: the ``.kg-reconcile-state.json`` cache is git-ignored and fails open to
        ``{}`` on loss, so without a durable checkpoint deleting that cache resets ``consumed`` to empty
        while every historical record survives, letting a previously-grounded-then-demoted edge be
        re-forged and slip past the count check (§1.8).

        Written to a SEPARATE sidecar that is atomically overwritten each sweep — NOT appended to the
        append-only audit log. Appending one whole-ledger snapshot per session grew the log
        superlinearly and forced every fresh reconciler to re-parse it; overwriting a sidecar keeps
        checkpoint storage O(1) and leaves the forgery/verdict records in the log entirely untouched, so
        forge detection is unchanged. The atomic temp+replace means a crash mid-write leaves either the
        old checkpoint or the new one, never a torn one.

        Best-effort (returns False on OSError): a missing checkpoint only costs the recovery, never breaks
        a sweep, and the next sweep re-checkpoints. A stale checkpoint is only ever safe-HIGH (over-strict
        re-quarantine), never a missed forgery. The record carries an ``_ckpt`` marker for symmetry with
        the reader. ``ensure_ascii=True`` keeps the sidecar pure-ASCII (non-ASCII ids survive as \\u
        escapes)."""
        rec = {"_ckpt": 1, "consumed": consumed, "epistemic": epistemic, "at": utcnow()}
        try:
            atomic_write_text(self.checkpoint_path, json.dumps(rec, ensure_ascii=True) + "\n")
            return True
        except OSError:
            return False

    def last_checkpoint(self) -> "dict | None":
        """The checkpoint sidecar's ``{'consumed': {...}, 'epistemic': {...}}``, or None if the sidecar is
        absent/unreadable/corrupt. Recovery-only, called when the reconcile cache is missing; tolerates a
        single undecodable byte (``errors='replace'``) and a malformed body (returns None). The sidecar is
        overwritten each sweep, so it always holds the LATEST checkpoint."""
        try:
            blob = self.checkpoint_path.read_bytes()
        except OSError:  # FileNotFoundError included — any unreadable sidecar means "no checkpoint"
            return None
        try:
            rec = json.loads(blob.decode("utf-8", "replace"))
        except ValueError:
            return None
        if not isinstance(rec, dict) or "_ckpt" not in rec:
            return None
        consumed = rec.get("consumed")
        epistemic = rec.get("epistemic")
        return {
            "consumed": consumed if isinstance(consumed, dict) else {},
            "epistemic": epistemic if isinstance(epistemic, dict) else {},
        }

    def audited_write(self, records, attempt):
        """The crash-safe audit+write dance shared by the verdict-writing handlers (§1.8): capture the
        offset BEFORE appending so an orphan record can be dropped, append each ``(key, frm, to, by)``
        record, run the caller-supplied ``attempt()`` (which returns ``(ok, payload)``), and TRUNCATE the
        audit back iff the write signals failure — so a failed transition never leaves an orphan record
        that would inflate the reconciler's forge count and let a genuine forgery slip past. ``attempt``
        carries the failure SIGNAL from its closure (a caught exception in kg_ground, an
        ``info.rolled_back`` in kg_rename) rather than the helper assuming one, so both failure shapes
        route through the same truncate. Returns the payload ``attempt()`` produced.

        Crash/failure semantics: (1) PER-RECORD durability is the only hard guarantee — each ``append``
        is its own fsync'd write. (2) The BATCH (kg_rename's many migration records) is made consistent
        only by the caller-held lease PLUS this offset/truncate compensation — there is no group-atomic
        append. (3) The compensation covers BOTH a False from ``attempt()`` AND a throw inside the append
        loop itself (an ``append`` that fsync-fails on record N after N-1 are durable): the loop is
        guarded so either path truncates back to the captured offset before unwinding. (4) If the
        compensating truncate cannot complete, the orphan record(s) SURVIVE, so we raise
        ``OrphanAuditError`` rather than returning — the caller must not report a clean rollback (an
        un-truncatable orphan would let a later out-of-band replay defeat forge detection). The CALLER
        must hold the canon lease across this call so the append + write + truncate is atomic (this log
        never locks)."""
        offset = self.size()
        try:
            for key, frm, to, by in records:
                self.append(key, frm, to, by)
        except Exception:  # noqa: BLE001 — a mid-batch append failure must still compensate (§1.8)
            # an append threw after appending 0..N-1 records durably: truncate them back before
            # re-raising so the failure path never leaves un-compensated orphans.
            self._compensate_or_orphan(offset, "audit append failed")
            raise
        try:
            ok, payload = attempt()
        except Exception:  # noqa: BLE001 — a RAISED write (not the (ok, payload) signal) must also compensate
            # attempt() threw instead of returning a failure signal: truncate the just-appended records
            # the same way as the failure path so a thrown write never leaves orphan records that would
            # inflate the reconciler's consumed tally and let a later replay defeat forge detection (§1.8).
            # `if records`: with nothing appended there is no orphan to drop — and truncating an audit
            # log that this call never created (empty records + no prior verdicts) would raise a SPURIOUS
            # OrphanAuditError over a clean rollback, e.g. renaming a not-yet-grounded node (review-r8-4).
            if records:
                self._compensate_or_orphan(offset, "write raised")
            raise
        if not ok and records:
            # the write signalled failure: drop the just-appended record(s) (or raise — the caller must
            # never report a clean rollback over a surviving orphan, §1.8). Guarded by `records` for the
            # same reason as the raise path above: no append → no orphan → nothing to truncate.
            self._compensate_or_orphan(offset, "write failed")
        return payload

    def _compensate_or_orphan(self, offset: int, what: str) -> None:
        """Truncate the log back to ``offset`` or raise ``OrphanAuditError`` — the §1.8 compensation
        invariant stated ONCE for ``audited_write``'s three failure paths (review-r5: three hand-kept
        copies could drift when the next failure mode is added)."""
        if not self.truncate(offset):
            raise OrphanAuditError(
                f"{what} and orphan audit record(s) could not be truncated back to {offset}")


# --------------------------------------------------------------------------- reading the log (0.22.4)

def audit_key(kind: str, item_id: str) -> str:
    """The key a verdict on an item is recorded under: an edge's id, ``node:<id>`` for a node (``kg_ground``)."""
    return f"node:{item_id}" if kind == "node" else item_id


class AuditIndex:
    """What a reader needs to tell whether an item was judged again after a given point of the log (0.22.4).

    The log is append-only, so a byte offset orders its records exactly, as no clock does: a verdict and a
    projection can fall in the same second, and the records are stamped to the second. ``size`` is the log's
    length in bytes, the point every later record lies beyond. ``last`` maps each key to the offset of its
    latest record, and ``last_at`` to its time. ``times`` lists ``(offset, at)`` in log order, to turn a moment
    into a point of the log for a re-examination flag raised before flags recorded one (``mark_after``)."""

    __slots__ = ("size", "last", "last_at", "times")

    def __init__(self, size: int = 0, last: "dict | None" = None, times: "list | None" = None,
                 last_at: "dict | None" = None):
        self.size = size
        self.last = last if last is not None else {}
        self.last_at = last_at if last_at is not None else {}
        self.times = times if times is not None else []

    def judged_since(self, key: str, mark: int) -> bool:
        """Whether the log holds a verdict on ``key`` recorded at or beyond ``mark``."""
        return self.last.get(key, -1) >= mark

    def mark_after(self, since: str) -> int:
        """The offset of the first record stamped after ``since`` (ISO-8601 UTC, to the second, as
        ``model.utcnow``), or ``size`` when there is none: a mark that counts only the verdicts recorded after
        that moment. A verdict stamped in that very second does not count, which errs on the side of judging
        an item once more."""
        for offset, at in self.times:
            if at > since:
                return offset
        return self.size


def read_audit_index(path: "str | os.PathLike") -> AuditIndex:
    """Index the log at ``path`` (0.22.4). Fail-open: a missing or unreadable log is an empty index, a bad
    line is skipped, and an old in-log checkpoint record (which carries no ``key``) is not a verdict."""
    last: dict = {}
    last_at: dict = {}
    times: list = []
    offset = 0
    try:
        with open(path, "rb") as f:
            for line in f:
                try:
                    rec = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    rec = None
                if isinstance(rec, dict) and isinstance(rec.get("key"), str) and "_ckpt" not in rec:
                    last[rec["key"]] = offset
                    last_at[rec["key"]] = str(rec.get("at") or "")
                    times.append((offset, last_at[rec["key"]]))
                offset += len(line)
    except OSError:
        return AuditIndex()
    return AuditIndex(offset, last, times, last_at)
