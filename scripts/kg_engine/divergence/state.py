"""File-based local state for a divergence project (FUSION_PLAN Stage 2/3).

State is **project-local and git-friendly**: the base directory is
``<project>/.kg/diverge`` (project root = ``KG_PROJECT_DIR``, else the cwd),
overridable with the ``KG_DIVERGE_HOME`` environment variable (used by the
test suite to isolate runs). Explicitly not the donor's ``~/.cambrian``.

Geometry state is **session-ephemeral (invariant I10)**: the MAP-Elites
archive and everything derived from embeddings live under ``session/`` and
are wiped when a new session begins (``begin_session``). Only pins, discards,
comparisons, and project/session metadata are durable — in the fused plugin
the knowledge graph, not the archive, is the durable memory. Layout::

    <home>/<project-slug>/
        meta.json                 # project metadata              (durable)
        axes.json                 # snapshot of the resolved axes (durable)
        session.json              # active session id + start    (durable)
        session/                  # I10: wiped on session change
            archive.json          # MAP-Elites: niche_id -> niche record
            candidates.json       # id -> candidate record (genealogy kept)
            embeddings.npz        # id -> embedding vector (binary npz; review-r6 — was .json)
            mech_embeddings.npz   # id -> mechanism-axis embedding (binary npz)
            open_nicher.json      # open-axis Voronoi partition
        tmp/                      # scratch dir for the skill's hand-off files
        memory/<domain>/
            comparisons.jsonl     # appended preference events   (durable)
            pins.json             # pinned "stepping stone" ids  (durable)
            discards.json         # negative memory              (durable)

Preferences are namespaced per domain so switching domains keeps memories
separate.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..atomicio import atomic_write_bytes, atomic_write_text
from .config import ConfigError

_log = logging.getLogger(__name__)


class StateError(ConfigError):
    """A persisted state file is corrupt/unreadable. Subclasses ConfigError so existing handlers
    keep catching it (review-r5: ConfigError's own docstring promises "the axes spec is malformed",
    which read untrue when raised for a corrupt archive/candidates file)."""


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Tolerant JSONL read: skip blank lines, skip corrupt lines (an interrupted append) and COUNT
    them — the ONE recovery policy shared by ``State.read_comparisons`` and the Cambrian importer
    (review-r5: two hand-synced copies agreed only by coincidence). Raises OSError like
    ``read_text`` (the importer catches it; State callers pre-check existence)."""
    records: list[dict[str, Any]] = []
    corrupt = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            corrupt += 1
    return records, corrupt

DEFAULT_HOME_ENV = "KG_DIVERGE_HOME"
PROJECT_DIR_ENV = "KG_PROJECT_DIR"

_PATH_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Best-effort cross-process lock (atomic mkdir works on every target OS) used to
# serialize read-modify-write on the small per-domain files (pins). Tuned for the
# realistic "two /ideate sessions on one project" race, not high contention.
_LOCK_TIMEOUT = 10.0   # seconds to wait for the lock before proceeding anyway
_LOCK_STALE = 60.0     # a lock dir older than this is assumed abandoned (crash)
_LOCK_POLL = 0.05
# Orphaned atomic-write temp files older than this are swept on State.ensure().
_STALE_TEMP_SECS = 3600.0


def _path_slug(name: str, fallback: str = "default") -> str:
    """Filesystem-safe slug for a project or domain id.

    A name that is already a valid slug round-trips unchanged, so existing state
    dirs (the common case: plain ASCII ids) are preserved exactly. When slugging is
    *lossy* — characters were replaced/stripped, or a non-ASCII-only id reduces to
    ``fallback`` — distinct names could otherwise collide on one slug and silently
    merge state (e.g. every non-ASCII id -> ``"default"``, or ``"proj A"`` and
    ``"proj-A"`` -> the same dir). In that case we append a short hash of the raw
    name so different ids can never share a directory.
    """
    raw = str(name)
    s = _PATH_SLUG_RE.sub("-", raw.strip()).strip("-_.")
    if s == raw:
        return s  # already a clean slug: unchanged, backward-compatible
    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{s or fallback}-{suffix}"


def base_dir(project_dir: "str | Path | None" = None) -> Path:
    """Project-local state home: ``<project>/.kg/diverge`` unless overridden — THE single rule for
    where a brief's state lives (review-r5: the MCP tools' ``_diverge_home`` used to hardcode the
    project path, so a ``KG_DIVERGE_HOME`` user got pins/discards split between CLI and server).

    ``KG_DIVERGE_HOME`` (tests, power users) always wins; else the explicit ``project_dir`` (the
    server passes its resolved ``engine.project_dir``); else ``KG_PROJECT_DIR`` (set for the MCP
    server by .mcp.json) or the cwd.
    """
    env = os.environ.get(DEFAULT_HOME_ENV)
    if env:
        return Path(env).expanduser()
    project = project_dir or os.environ.get(PROJECT_DIR_ENV) or os.getcwd()
    return Path(project).expanduser() / ".kg" / "diverge"


def _atomic_write(path: Path, text: str, *, durable: bool = True) -> None:
    """Crash-safe write via the shared ``kg_engine.atomicio`` protocol (review-r5). This module used
    to carry its own temp+fsync+replace copy that "mirrored" atomicio's guarded cleanup — but lacked
    its bounded ``os.replace`` retry for the transient Windows sharing-violation class, so divergence
    state writes could fail where a canon write would have succeeded. One implementation now; the I3
    firewall is directional (verdict path must not import divergence), so this import is legal.
    ``durable=False`` (the I10 session zone) skips the fsyncs but keeps atomicity — see atomicio."""
    atomic_write_text(path, text, durable=durable)


def _steal_stale_lock(lock: Path) -> None:
    """Atomically reclaim a presumed-abandoned lock dir.

    ``os.replace`` of a directory is atomic, so exactly one racer wins the rename
    and removes it; the losers get an ``OSError`` and simply re-attempt the
    ``mkdir``. This avoids the stat-then-``rmdir`` TOCTOU where two processes both
    observe the lock as stale, both delete it, and both proceed — one possibly
    deleting a *fresh* lock a third process just created.
    """
    sidelined = lock.with_name(f"{lock.name}.stale-{os.getpid()}")
    try:
        os.replace(lock, sidelined)
    except OSError:
        return  # another racer won the steal (or it vanished); just retry mkdir
    shutil.rmtree(sidelined, ignore_errors=True)


@contextlib.contextmanager
def _file_lock(target: Path, timeout: float = _LOCK_TIMEOUT):
    """Best-effort cross-process lock guarding a read-modify-write on ``target``.

    Uses an atomic ``mkdir`` of a sibling ``<name>.lock`` directory (atomic on
    POSIX and Windows). Steals a lock older than ``_LOCK_STALE`` (a crashed
    holder). If the lock can't be acquired within ``timeout`` we proceed anyway
    rather than deadlock — the protected section is then no worse than the
    historical unlocked behavior (and is logged at WARNING for diagnosis).
    """
    lock = target.parent / (target.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout)
    acquired = False
    while True:
        try:
            lock.mkdir()
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            if age > _LOCK_STALE:
                _steal_stale_lock(lock)
                continue
            if time.monotonic() >= deadline:
                _log.warning("lock not acquired within %.1fs; proceeding "
                             "unlocked on %s", timeout, target)
                break  # give up; proceed unlocked
            time.sleep(_LOCK_POLL)
        except OSError:
            # A transient FS error rather than "already held": on Windows a name
            # that another racer is mid-rmdir on can report a sharing/pending-delete
            # error instead of FileExistsError. Back off briefly and retry rather
            # than letting the read-modify-write crash.
            if time.monotonic() >= deadline:
                _log.warning("lock unavailable (transient FS errors); proceeding "
                             "unlocked on %s", target)
                break
            time.sleep(_LOCK_POLL)
    try:
        yield
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                lock.rmdir()


class State:
    """Handle to one project's on-disk state."""

    def __init__(self, project: str, home: Path | None = None):
        self.project = project
        self.base = Path(home).expanduser() if home else base_dir()
        self.root = self.base / _path_slug(project)

    # -- paths -------------------------------------------------------------- #
    @property
    def meta_path(self) -> Path:
        return self.root / "meta.json"

    @property
    def axes_path(self) -> Path:
        return self.root / "axes.json"

    @property
    def materialized_path(self) -> Path:
        """Durable ledger of pins that entered the graph (candidate_id -> graph ids).
        Written by kg_diverge_materialize; read by the failed-fate sync that folds
        grounding failures back into this project's discard memory (I8). Durable —
        it maps BRIEF state to GRAPH state, and both survive the session."""
        return self.root / "materialized.json"

    def read_materialized(self) -> dict[str, Any]:
        return self.read_json(self.materialized_path, {}) or {}

    def write_materialized(self, data: dict[str, Any]) -> None:
        self.write_json(self.materialized_path, data)

    @property
    def session_dir(self) -> Path:
        """I10 ephemeral zone: every geometry artifact (the MAP-Elites archive and
        everything derived from embeddings) lives here and here only, so wiping one
        directory is provably wiping the whole archive."""
        return self.root / "session"

    @property
    def session_path(self) -> Path:
        return self.root / "session.json"

    @property
    def archive_path(self) -> Path:
        return self.session_dir / "archive.json"

    @property
    def candidates_path(self) -> Path:
        return self.session_dir / "candidates.json"

    @property
    def embeddings_path(self) -> Path:
        """Binary npz vector store (review-r6). The pre-npz pretty-JSON shape re-parsed and rewrote
        tens of MB of float reprs per ingest inside the project lock at large archives; values on
        disk are float64, so the round-trip is exact. `_legacy_embeddings_json` is read as a
        fallback so a session written by an older engine still loads."""
        return self.session_dir / "embeddings.npz"

    @property
    def _legacy_embeddings_json(self) -> Path:
        return self.session_dir / "embeddings.json"

    @property
    def mech_embeddings_path(self) -> Path:
        return self.session_dir / "mech_embeddings.npz"

    @property
    def _legacy_mech_embeddings_json(self) -> Path:
        return self.session_dir / "mech_embeddings.json"

    @property
    def open_nicher_path(self) -> Path:
        return self.session_dir / "open_nicher.json"

    @property
    def tmp_dir(self) -> Path:
        """Per-project scratch dir for the skill's hand-off files (axes.json,
        candidates.json, event.json). Inside the state home so they never clutter
        the user's cwd and can't collide across concurrent sessions."""
        return self.root / "tmp"

    def memory_dir(self, domain: str) -> Path:
        return self.root / "memory" / _path_slug(domain)

    def comparisons_path(self, domain: str) -> Path:
        return self.memory_dir(domain) / "comparisons.jsonl"

    def pins_path(self, domain: str) -> Path:
        return self.memory_dir(domain) / "pins.json"

    def discards_path(self, domain: str) -> Path:
        return self.memory_dir(domain) / "discards.json"

    # -- lifecycle ---------------------------------------------------------- #
    def exists(self) -> bool:
        return self.meta_path.exists()

    def ensure(self) -> "State":
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._sweep_stale_temps()
        return self

    def _sweep_stale_temps(self) -> None:
        """Remove orphaned atomic-write temp files. A crash between ``mkstemp``
        and ``os.replace`` leaves a ``.tmp-*`` file behind; sweep old ones so they
        don't accumulate. Best-effort: races and errors are ignored."""
        cutoff = time.time() - _STALE_TEMP_SECS
        try:
            entries = list(self.root.glob(".tmp-*"))
        except OSError:
            return
        for p in entries:
            with contextlib.suppress(OSError):
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()

    def paths(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "meta": str(self.meta_path),
            "axes": str(self.axes_path),
            "session_dir": str(self.session_dir),
            "archive": str(self.archive_path),
            "candidates": str(self.candidates_path),
            "embeddings": str(self.embeddings_path),
            "mech_embeddings": str(self.mech_embeddings_path),
            "open_nicher": str(self.open_nicher_path),
            "tmp": str(self.tmp_dir),
        }

    # -- session lifecycle (I10) --------------------------------------------- #
    # Geometry-coupled meta series: tied to the archive the monitor calibrated
    # against, so they die with it (both on session change and on axes re-init).
    GEOMETRY_META_KEYS = ("cycles", "cos_window", "novelty_window",
                          "erosion_streak", "gap_log")

    def read_session(self) -> dict[str, Any]:
        return self.read_json(self.session_path, {}) or {}

    def begin_session(self, session_id: str) -> bool:
        """Enforce I10: a NEW session id wipes the ephemeral geometry zone.

        Idempotent for the active session (same id -> nothing wiped), so a
        command may re-run init to resume within one session. Durable state
        (pins, discards, comparisons, meta identity, axes) is never touched;
        the geometry-coupled meta series are dropped alongside the archive
        they calibrated against. Returns True when a wipe happened."""
        sid = str(session_id)
        current = self.read_session()
        if current.get("session_id") == sid:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            return False
        shutil.rmtree(self.session_dir, ignore_errors=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        meta = self.read_meta()
        dropped = False
        for key in self.GEOMETRY_META_KEYS:
            dropped = meta.pop(key, None) is not None or dropped
        if dropped:
            self.write_meta(meta)
        self.write_json(self.session_path,
                        {"session_id": sid, "started_at": time.time()})
        return True

    def reset_geometry(self) -> None:
        """Delete this project's geometric state — the MAP-Elites archive, candidate
        records, embeddings (surface AND the parallel mechanism store), and the frozen
        open-axis nicher — so the project can be re-initialized under a NEW axes
        geometry without mixing stale niche keys with new ones. Preference memory
        (pins/discards/comparisons, namespaced per domain) is deliberately left intact.
        Best-effort: a missing file is not an error."""
        for path in (self.archive_path, self.candidates_path,
                     self.embeddings_path, self.mech_embeddings_path,
                     # legacy pre-npz vector files (review-r6): an older session's leftovers must
                     # not shadow a fresh geometry via the tolerant fallback read.
                     self._legacy_embeddings_json, self._legacy_mech_embeddings_json,
                     self.open_nicher_path):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)

    def project_lock(self, timeout: float = _LOCK_TIMEOUT):
        """Cross-process lock serializing a whole-project read-modify-write cycle.

        ``ingest`` (and an axes-changing ``init``) read the archive/candidates/
        embeddings/meta, mutate them, and write them back; without serialization two
        concurrent cycles on one project would clobber each other (a lost generation).
        Same best-effort ``mkdir`` lock as the pin/discard guard — on timeout it
        proceeds unlocked rather than deadlock. The lock dir sits beside the state
        files as ``<root>/.project.lock``."""
        return _file_lock(self.root / ".project", timeout=timeout)

    def project_read_lock(self, timeout: float = _LOCK_TIMEOUT):
        """The same lock, taken for a multi-file READ (``metrics`` / ``parents`` / ``recall``).

        Those commands read several files that ``ingest`` rewrites together (archive +
        candidates + embeddings + meta). Reading unlocked could catch a cycle mid-write and
        mix a new ``archive.json`` with an old ``candidates.json`` — an elite whose record
        isn't there yet. Same best-effort semantics as :meth:`project_lock`: on timeout it
        proceeds anyway, so a reader can never be blocked for long by a writer.

        A no-op when the project dir doesn't exist: there is no cycle to be inconsistent
        with, and a read-only command must not create state as a side effect (the lock dir
        would otherwise materialize the project root)."""
        if not self.root.exists():
            return contextlib.nullcontext()
        return _file_lock(self.root / ".project", timeout=timeout)

    # -- generic json helpers ---------------------------------------------- #
    def read_json(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            # Empty file (e.g. an interrupted write) — treat as absent rather
            # than crash the command; the next write repopulates it.
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # A non-empty but corrupt state file is surfaced as a clean,
            # operator-facing error instead of a raw traceback.
            raise StateError(
                f"state file {path} is corrupt ({exc}); remove it (or restore a "
                f"backup) and retry"
            ) from exc

    def write_json(self, path: Path, obj: Any, *, durable: bool = True,
                   compact: bool = False) -> None:
        """``compact=True`` drops the indent/whitespace for big machine-only stores — values and key
        order (sort_keys) are identical, only bytes shrink. ``durable=False`` skips the fsyncs for
        the I10 session zone (loss on a crash is already an accepted outcome there); the atomic
        temp+replace still means a reader never sees a torn file (review-r6)."""
        text = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                          indent=None if compact else 2,
                          separators=(",", ":") if compact else None)
        _atomic_write(path, text, durable=durable)

    # -- vector stores (npz; review-r6) -------------------------------------- #
    def _read_vector_store(self, path: Path, legacy_json: Path) -> dict[str, list[float]]:
        """id -> vector store, npz-backed. ``.tolist()`` of the float64 rows returns the identical
        Python floats ``json.loads`` produced from the legacy file, so consumers (and the
        write/read == roundtrip) are unchanged. Falls back to the legacy pretty-JSON file so a
        session written by an older engine still reads; the next write lands the npz and removes
        the legacy file."""
        if path.exists():
            import io

            import numpy as np
            try:
                with np.load(io.BytesIO(path.read_bytes())) as z:
                    # keys are stored with a "v:" prefix — see _write_vector_store.
                    return {k[2:]: z[k].tolist() for k in z.files}
            except Exception as exc:  # noqa: BLE001 — corrupt zip/npy: mirror read_json's posture
                raise StateError(
                    f"state file {path} is corrupt ({exc}); remove it (or restore a "
                    f"backup) and retry"
                ) from exc
        return self.read_json(legacy_json, {}) or {}

    def _write_vector_store(self, path: Path, legacy_json: Path,
                            embeddings: dict[str, list[float]]) -> None:
        import io

        import numpy as np
        buf = io.BytesIO()
        # Candidate ids are caller-supplied strings; the "v:" prefix keeps any id (e.g. a literal
        # "file") from colliding with np.savez's own parameter names while round-tripping verbatim.
        np.savez(buf, **{f"v:{k}": np.asarray(v, dtype=np.float64)
                         for k, v in embeddings.items()})
        # Session zone (I10): atomic but not durable — see write_json.
        atomic_write_bytes(path, buf.getvalue(), durable=False)
        with contextlib.suppress(OSError):
            legacy_json.unlink(missing_ok=True)

    # -- typed accessors ---------------------------------------------------- #
    def read_meta(self) -> dict[str, Any]:
        return self.read_json(self.meta_path, {}) or {}

    def write_meta(self, meta: dict[str, Any]) -> None:
        self.write_json(self.meta_path, meta)

    def read_axes(self) -> dict[str, Any] | None:
        return self.read_json(self.axes_path, None)

    def write_axes(self, axes: dict[str, Any]) -> None:
        self.write_json(self.axes_path, axes)

    # Session-zone (I10) writers pass durable=False: these files are wiped on the next session
    # anyway, so per-cycle fsync pairs bought durability for data whose loss is an accepted
    # outcome; atomicity (never a torn read) is kept. Durable stores (meta/axes/session/pins/
    # discards/materialized) keep the full fsync protocol (review-r6).
    def read_archive(self) -> dict[str, Any]:
        return self.read_json(self.archive_path, {}) or {}

    def write_archive(self, archive: dict[str, Any]) -> None:
        self.write_json(self.archive_path, archive, durable=False)

    def read_candidates(self) -> dict[str, Any]:
        return self.read_json(self.candidates_path, {}) or {}

    def write_candidates(self, candidates: dict[str, Any]) -> None:
        # compact: the largest JSON store (full idea texts + genealogy), machine-only.
        self.write_json(self.candidates_path, candidates, durable=False, compact=True)

    def read_embeddings(self) -> dict[str, list[float]]:
        return self._read_vector_store(self.embeddings_path, self._legacy_embeddings_json)

    def write_embeddings(self, embeddings: dict[str, list[float]]) -> None:
        self._write_vector_store(self.embeddings_path, self._legacy_embeddings_json, embeddings)

    def read_mech_embeddings(self) -> dict[str, list[float]]:
        return self._read_vector_store(self.mech_embeddings_path,
                                       self._legacy_mech_embeddings_json)

    def write_mech_embeddings(self, embeddings: dict[str, list[float]]) -> None:
        self._write_vector_store(self.mech_embeddings_path,
                                 self._legacy_mech_embeddings_json, embeddings)

    def read_open_nicher(self) -> dict[str, Any] | None:
        """Persisted open-axis nicher: cold-start accumulation or frozen centroids."""
        return self.read_json(self.open_nicher_path, None)

    def write_open_nicher(self, data: dict[str, Any]) -> None:
        # compact: the pre-freeze accumulation buffer is up to freeze_factor*k raw vectors.
        self.write_json(self.open_nicher_path, data, durable=False, compact=True)

    # -- memory (namespaced by domain) ------------------------------------- #
    def append_comparison(self, domain: str, event: dict[str, Any]) -> None:
        path = self.comparisons_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        # Single O_APPEND write (not buffered text I/O): under POSIX O_APPEND each
        # write lands atomically at end-of-file, so concurrent appenders can't
        # interleave a short line. read_comparisons also tolerates a torn line.
        data = line.encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

    def read_comparisons(self, domain: str) -> list[dict[str, Any]]:
        path = self.comparisons_path(domain)
        if not path.exists():
            return []
        # Shared tolerant reader: a truncated/corrupt line (an interrupted append) is skipped so a
        # single bad record can't poison every future read of this domain.
        return read_jsonl(path)[0]

    def read_pins(self, domain: str) -> list[str]:
        return self.read_json(self.pins_path(domain), []) or []

    def write_pins(self, domain: str, pins: list[str]) -> None:
        self.write_json(self.pins_path(domain), pins)

    @contextlib.contextmanager
    def _preference_lock(self, domain: str):
        """One lock covering BOTH preference files for a domain.

        Pins and discards are a single invariant, not two: every writer here mutates both
        files (pinning drops the discard, discarding drops the pin, un-sealing edits the
        discard list a pin may be racing on). Locking each file separately let a concurrent
        pin and discard of one id take different locks, interleave their read-modify-writes,
        and leave that id in both lists or in neither — "latest action wins" silently stops
        holding. The pins path is the arbitrary but stable choice of lock target; what
        matters is that all three writers agree on one.
        """
        path = self.pins_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock(path):
            yield

    def add_pin(self, domain: str, candidate_id: str) -> list[str]:
        # Lock the read-modify-write so two concurrent invocations can't each read
        # the same list and clobber the other's pin (pins are "never dropped").
        with self._preference_lock(domain):
            pins = self.read_pins(domain)
            if candidate_id not in pins:
                pins.append(candidate_id)
                self.write_pins(domain, pins)
            # Pins and discards are mutually exclusive (latest action wins): pinning
            # an id the user previously discarded un-discards it.
            self._remove_discard(domain, candidate_id)
            return pins

    def read_discards(self, domain: str) -> list[str]:
        return self.read_json(self.discards_path(domain), []) or []

    def write_discards(self, domain: str, discards: list[str]) -> None:
        self.write_json(self.discards_path(domain), discards)

    def add_discard(self, domain: str, candidate_id: str) -> list[str]:
        # Locked read-modify-write, mirroring add_pin. A discard is the negative of
        # a pin; the two are mutually exclusive (latest action wins), so discarding
        # an id also drops it from pins — hence the SHARED lock covering both files
        # (see _preference_lock), not one lock per file.
        with self._preference_lock(domain):
            discards = self.read_discards(domain)
            if candidate_id not in discards:
                discards.append(candidate_id)
                self.write_discards(domain, discards)
            self._remove_pin(domain, candidate_id)
            return discards

    def remove_discard(self, domain: str, candidate_id: str) -> list[str]:
        """Un-seal (the explicit inverse of ``add_discard``): drop a candidate from this domain's
        discards so it returns to the proposal pool. Locked read-modify-write, mirroring ``add_discard``.
        Does NOT re-pin it (pin/discard mutual exclusivity is a latest-action rule; un-sealing is neither
        a pin nor a discard). No-op if the id isn't discarded. Used by the re-examinable un-seal lever.
        Takes the SHARED preference lock (see ``_preference_lock``): un-sealing edits the discard list
        a concurrent pin of the same id is also about to rewrite."""
        with self._preference_lock(domain):
            discards = self.read_discards(domain)
            if candidate_id in discards:
                self.write_discards(domain, [d for d in discards if d != candidate_id])
            return self.read_discards(domain)

    def _remove_pin(self, domain: str, candidate_id: str) -> None:
        # Deliberately UNLOCKED: called only from inside _preference_lock, and the mkdir
        # lock is not re-entrant — taking it again here would deadlock against its holder.
        pins = self.read_pins(domain)
        if candidate_id in pins:
            self.write_pins(domain, [p for p in pins if p != candidate_id])

    def _remove_discard(self, domain: str, candidate_id: str) -> None:
        # Deliberately UNLOCKED: called only from inside _preference_lock, and the mkdir
        # lock is not re-entrant — taking it again here would deadlock against its holder.
        discards = self.read_discards(domain)
        if candidate_id in discards:
            self.write_discards(domain, [d for d in discards if d != candidate_id])
