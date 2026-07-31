"""The MCP server (§2.4): the graphify-shaped tool surface + our grounding semantics.

Tool logic lives in the importable `KGEngine` facade so it is unit-testable without an MCP client;
the FastMCP wrappers are thin. Elicitation requests always declare a default applied if unanswered,
so the flow never stalls (§2.4, §4).
"""
from __future__ import annotations

import contextlib
import copy
import functools
import hashlib
import json
import logging
from collections import Counter, OrderedDict
import math
import os
import re
import shutil
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, envconfig
from .canon import Canon
from .groundaudit import GroundAuditLog
from .model import (
    AuthoredBy,
    DEFAULT_MAX_EDGES_PER_KB,
    Disposition,
    Edge,
    EpistemicState,
    FAILURE_STATES,
    FAILURE_STATE_VALUES,
    GROUNDABLE_STATES,
    MIN_SPAN_CHARS,
    Node,
    Provenance,
    UNDECLARED_TYPE,
    edge_id,
    normalize_text,
    slug,
    utcnow,
)
from .projector import Projector
from .reconciler import GROUND_AUDIT, Reconciler
from .scrub import Scrubber
from .sources import SourceSet, split_sections

# Module logger. The engine had no logging seam, so silent `except Exception: pass` fallbacks were
# invisible to an operator. Stays quiet by default (no handler attached) per the library convention; an
# operator opts in via standard logging config. The MCP tool envelope and the index fallbacks log here.
logger = logging.getLogger("kg_engine")

# Single source of truth shared with the reconciler's policed set (model.GROUNDABLE_STATES), so the
# states kg_ground may stamp and the states the reconciler re-quarantines can never drift apart.
VALID_VERDICTS = {s.value for s in GROUNDABLE_STATES}
# The known verdict actors, derived from the AuthoredBy enum (mirroring how VALID_VERDICTS derives from
# GROUNDABLE_STATES) so the clamp tracks the model instead of an inline literal that can drift.
VALID_ACTORS = {a.value for a in AuthoredBy}
# The dispositions that mean "this item persisted to the canon" — derived from the Disposition enum
# (like the two sets above) for kg_write's rollback re-bucketing and the materialize ledger, which
# previously re-typed the two names as raw string literals (review-r5).
PERSISTED_DISPOSITIONS = (Disposition.ACCEPTED.value, Disposition.DEMOTED.value)
# A materialized divergence pin becomes PERMANENT negative memory for its brief (folded into the brief's
# discards by _sync_materialized_fates) ONLY when it is actively FALSIFIED. A pin that is merely REJECTED
# (no verbatim span in the CURRENT source) is the EXPECTED state of a genuinely novel idea awaiting sources
# — not a failure — so it must stay recoverable, never auto-discarded. This is a DELIBERATELY NARROWER set
# than the global model.FAILURE_STATES ({REJECTED, FAILED}, which must NOT be redefined): FAILURE_STATES
# governs projector pruning and the write-boundary durability quarantine (/kg-generate negative memory) and
# is untouched here. Verdict neutrality is likewise untouched — the verdict a pin receives is unchanged and
# identical to a non-pin's; only THIS diverge-brief-local, state-keyed discard CONSEQUENCE is narrowed.
MATERIALIZED_DISCARD_STATES = {EpistemicState.FAILED}
# The "not found" read shape, defined once for the engine's degraded-miss and the MCP wrapper's
# plain-miss (review-r5: the literal lived in two places). Callers copy before mutating.
_NOT_FOUND = {"error": "not found"}

# Absolute filesystem paths (Windows drive/UNC, or a POSIX path of >=2 segments) — redacted from any
# error string before it crosses the §1.9 egress boundary back to the session, so a raw exception can't
# leak a vault path. A bare "/" or a single-segment "/x" or a mid-word "and/or" is deliberately NOT
# matched (over-redaction of prose), only path-shaped runs.
_ABS_PATH_RE = re.compile(
    # Windows drive path (C:\… / C:/…) or \\server\share UNC. The `X:[\/]` / `\\` anchor is strong
    # enough that it essentially never opens a prose run, so consume the whole line-bounded tail —
    # SPACES AND ALL (`C:\Users\John Smith\vault\x.md`) — rather than stopping at the first space and
    # leaking the rest of the path. A username with a space is the common Windows case, and this
    # plugin targets Windows; over-redacting a few trailing words on the same line is the safe
    # direction for an egress scrubber (review: spaced-Windows-path egress leak). Bounded by EOL/quote.
    r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n\"'`]*"
    # POSIX absolute path (>=2 segments). A directory segment may contain internal spaces
    # (`/home/john doe/…`) — absorbed ONLY while the segment is still closed by a `/`, so the (sensitive)
    # username dir is redacted rather than left dangling, while the leading-`/`-plus-separator shape
    # still keeps bare prose ("and/or", a lone "/x") out.
    r"|/(?:[^\s\"'`/]+(?: [^\s\"'`/]+)*/)+[^\s\"'`/]*")


def _scrub_error_text(msg, *, sensitivity: str = "medium") -> str:
    """Scrub an error string before it crosses the §1.9 egress boundary back to the session: redact
    absolute filesystem paths AND run the same secret/PII egress scrub `kg_scrub` applies, so a raw
    exception can't leak a vault path or quote un-scrubbed canon content. Uses a THROWAWAY `Scrubber`
    (the session's accumulated egress placeholder namespace is never polluted by error text) and degrades
    to the best partial result if scrubbing itself raises — the error-reporting path must NEVER itself
    raise. This is the single chokepoint both the tool envelope and the handler `{e}` interpolations route
    through."""
    try:
        text = str(msg)
    except Exception:  # noqa: BLE001 — an un-str-able error must not crash the error path
        return "<unprintable error>"
    try:
        text = _ABS_PATH_RE.sub("<path>", text)
    except Exception:  # noqa: BLE001 — path redaction is best-effort
        pass
    try:
        text = Scrubber(sensitivity).scrub(text)[0]
    except Exception:  # noqa: BLE001 — the secret/PII scrub is best-effort; keep the path-redacted text
        pass
    return text


# Filesystem-safe slug for a NAMED alternate canon — the /kg-perturb "second construction" (§9/§15).
# Mirrors divergence/state._path_slug's collision-safe rule (a clean ASCII name round-trips unchanged;
# a lossy slug gets a short hash suffix so two distinct names can never share one dir), but is
# REIMPLEMENTED here rather than imported: the write/verdict path must stay import-firewalled from
# kg_engine.divergence (I3, firewall-tested), even lazily. `construction=None` (every existing caller)
# never reaches this, so a normal write still loads zero divergence code (test_i3_runtime_...).
_CONSTRUCTION_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _construction_slug(name: str, fallback: str = "construction") -> str:
    raw = str(name)
    s = _CONSTRUCTION_SLUG_RE.sub("-", raw.strip()).strip("-_.")
    if s == raw:
        return s  # already a clean slug: unchanged
    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{s or fallback}-{suffix}"

# Precedence used when kg_merge dedups two edges that collide on one canonical id (§1.4/§1.7). The
# winning epistemic_state is whichever ranks higher: failed/rejected are sticky NEGATIVE INFORMATION
# (never pruned, §1.7) so they dominate any positive state; then grounded > unverified; `obsolete`
# (a lifecycle state, not a verdict) ranks lowest. The merged state is therefore ALWAYS a state one of
# the two real edges already held — the merge can never forge or upgrade a verdict.
_MERGE_STATE_RANK = {
    EpistemicState.FAILED: 4,
    EpistemicState.REJECTED: 3,
    EpistemicState.GROUNDED: 2,
    EpistemicState.UNVERIFIED: 1,
    EpistemicState.OBSOLETE: 0,
}
# Tie-break (and span-less provenance) order: a verbatim span (span-present) beats an asserted
# inference, which beats a structural guess (hypothesized). Used to keep the cited span + its verdict
# paired on a state tie, never to invent evidence.
_MERGE_PROV_RANK = {
    Provenance.SPAN_PRESENT: 2,
    Provenance.INFERRED: 1,
    Provenance.HYPOTHESIZED: 0,
}

# ---- transport/cancellation hardening (the robustness pass) ----------------------------------------
# A rotating server log so the whole class of stdio-transport/cancellation crash is finally debuggable:
# nothing was persisted before, so a server that "disconnected" left no trace. Lives under KG_DATA next
# to provision.log; the Node supervisor (launch_server.mjs) appends its (re)launch/exit/backoff events to
# the SAME file (Python owns rotation — the supervisor's lines are a few per restart, so they ride along).
SERVER_LOG_NAME = "server.log"
SERVER_LOG_MAX_BYTES = 2_000_000
SERVER_LOG_BACKUP_COUNT = 3
# Distinct non-zero exit codes so the supervisor's logs say WHY the engine died (both are "unexpected",
# so both trigger a relaunch — see launch_server.mjs restartDecision).
EXIT_CRASH = 70         # an exception escaped the serve loop
EXIT_WATCHDOG = 71      # a handler wedged past KG_HANDLER_TIMEOUT and the watchdog forced a fresh process
# A handler that runs longer than this is treated as wedged (a deadlocked write, a runaway projection) and
# the watchdog forces a clean process exit so the supervisor relaunches — never a half-dead "Running…"
# state. Generous by default: the legitimately-slow paths are a cross-process lease wait (capped at
# canon.LOCK_ACQUIRE_TIMEOUT = 30s) plus a projection, both far under this. 0 disables the watchdog.
# This budget is NOT a substitute for bounding caller-supplied work: a handler whose cost is
# superlinear in a model-supplied argument must cap that argument itself, or it turns the watchdog into
# a remote kill switch (pathing.MAX_EXPLAIN_NODES is the worked example — review-r11).
DEFAULT_HANDLER_TIMEOUT = 300.0
# Idempotency: bound the in-memory replay cache so a long-lived server can't grow it without limit.
_WRITE_CACHE_MAX = 256
# Upper bound on distinct NAMED second constructions alive in one session (§9/§15). Names come straight
# from the LLM, and each mints a live sub-engine + an on-disk canon under .kg/constructions/, so an
# unbounded map is a slow resource-exhaustion vector. Normal use is ONE; refuse (never silently evict —
# eviction + the session-fresh wipe below would discard a half-built construction) past this (review-fix).
_MAX_CONSTRUCTIONS = 8


def _hard_exit(code: int) -> None:
    """Terminate THIS process immediately, without running interpreter / DLL-detach teardown.

    Why not a plain ``os._exit`` (BURGESS_BUG_kg_context_hang, failure #2): when the watchdog trips
    because a handler wedged INSIDE a native-extension load — a numpy/OpenBLAS import that deadlocked on
    the Windows loader lock — ``os._exit`` routes through ``ExitProcess``, which needs that SAME loader
    lock to run DLL-detach teardown, so it deadlocks too. The process then never dies, the supervisor
    never sees the exit (so never lets the client reconnect), and a 300s watchdog silently becomes an
    hours-long hang. So force a kill that touches NO teardown path:
      - Windows: ``TerminateProcess(GetCurrentProcess(), code)`` — no DLL detach, never takes the loader lock.
      - POSIX:   ``SIGKILL`` — uncatchable, immediate, no atexit/teardown.
    Both preserve the observable outcome the Node supervisor keys on (a non-clean child exit → it lets the
    client reconnect with a fresh ``initialize`` handshake). ``os._exit`` stays as a last-ditch fallback
    for the (unexpected) case where the OS primitive itself can't be issued."""
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Declare the handle types so the current-process PSEUDO-handle ((HANDLE)-1) isn't truncated
            # to a 32-bit int on 64-bit Windows (ctypes' default int marshalling would sign-lose it).
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel32.TerminateProcess(kernel32.GetCurrentProcess(), ctypes.c_uint(code))
        else:
            import signal
            os.kill(os.getpid(), signal.SIGKILL)
    except Exception:  # noqa: BLE001 — if the hard kill can't be issued, fall through to os._exit
        pass
    # Belt-and-braces: SIGKILL / TerminateProcess terminate before reaching here; this only runs if the
    # OS primitive above raised or (impossibly) returned — still leave, just via the softer path.
    os._exit(code)


# The canonical env-value cleaner (empty / ${...} placeholder / bare sentinel → unset). The rule
# itself is single-homed in envconfig (review-r5) — shared with bootstrap, the PreToolUse hook, and
# the lightrag arm; launch_server.clean is its declared JS mirror.
_clean_env = envconfig.clean_env


def resolve_data_dir() -> Path:
    """The engine data dir (where the derived layer + server.log live), resolved exactly as a
    KGEngine would: ``KG_DATA`` if set, else ``<project>/.kg-data`` — the rule lives in
    ``envconfig.resolve_data_dir``, shared with the PreToolUse hook (review-r5). Used to place the
    server log BEFORE the engine is constructed, so even an engine-construction error is captured."""
    return envconfig.resolve_data_dir(envconfig.resolve_project(os.getcwd()))


def server_log_path(data_dir=None) -> Path:
    return (Path(data_dir) if data_dir else resolve_data_dir()) / SERVER_LOG_NAME


# A readiness MARKER the Node supervisor (launch_server.mjs) reads to tell a POST-INIT crash from a
# STARTUP crash without relying solely on a wall-clock proxy: it is written as the stdio serve loop comes
# up (the lifespan __aenter__, AFTER imports + engine construction succeed) and its mtime, newer than the
# child's spawn time, proves THIS engine began serving. Lives under the SAME KG_DATA dir both sides resolve
# (resolve_data_dir <-> serverLogDir in the launcher).
READY_MARKER_NAME = ".engine-ready"


def ready_marker_path(data_dir=None) -> Path:
    return (Path(data_dir) if data_dir else resolve_data_dir()) / READY_MARKER_NAME


def write_ready_marker(data_dir=None) -> None:
    """Stamp the readiness marker (best-effort; a failure must never block serving)."""
    try:
        p = ready_marker_path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"pid={os.getpid()} t={time.time():.3f}\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 — the marker is advisory; never fail startup on it
        pass


def clear_ready_marker(data_dir=None) -> None:
    """Remove the readiness marker on a clean shutdown (best-effort). The supervisor also clears it on
    each (re)spawn, so a leftover from a hard crash can never be mistaken for the next child's marker."""
    try:
        ready_marker_path(data_dir).unlink()
    except OSError:
        pass


@contextlib.asynccontextmanager
async def readiness_lifespan(_server=None):
    """FastMCP lifespan: write the readiness marker as the stdio serve loop starts, clear it on exit.

    __aenter__ runs after the transport is established and right BEFORE the session begins reading the
    buffered ``initialize`` request — and crucially AFTER module import + ``build_engine_from_env``, so a
    broken-venv import/construction error (a genuine STARTUP failure) never reaches here and stays
    correctly classified by the supervisor's wall-clock fallback. RESIDUAL GAP: the few milliseconds
    between this point and ``initialize`` actually being answered are attributed to "serving", so a crash
    in that sliver is treated as post-init — acceptable since no engine code runs there (MCP handles the
    handshake) and the alternative (a true on-initialize hook) does not exist in this FastMCP."""
    write_ready_marker()
    try:
        yield {}
    finally:
        clear_ready_marker()


_EXCEPTHOOKS_INSTALLED = False


def _install_excepthooks() -> None:
    """Route uncaught exceptions (main thread AND worker threads) through the logger so the rotating
    file captures the full traceback instead of it vanishing to an unread stderr. Idempotent."""
    global _EXCEPTHOOKS_INSTALLED
    if _EXCEPTHOOKS_INSTALLED:
        return
    prev = sys.excepthook

    def _hook(exc_type, exc, tb):
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            logger.critical("uncaught exception", exc_info=(exc_type, exc, tb))
        prev(exc_type, exc, tb)

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        def _thook(args):
            logger.critical("uncaught exception in thread %s",
                            getattr(args, "thread", None),
                            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        threading.excepthook = _thook
    _EXCEPTHOOKS_INSTALLED = True


def configure_logging(data_dir=None, *, level=logging.INFO) -> Path | None:
    """Attach a rotating file handler to the root logger (capturing ``kg_engine`` at INFO and the
    ``mcp`` library at WARNING) writing to ``<data_dir>/server.log``, and install the uncaught-exception
    hooks. Best-effort: a logging-setup failure must never stop the server from coming up, so any error
    is swallowed and None returned. Idempotent — a prior kg-server handler is replaced, so repeated calls
    (e.g. in tests) don't accumulate handlers or duplicate lines. Returns the log path on success."""
    try:
        path = server_log_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        for h in list(root.handlers):
            if getattr(h, "_kg_server_log", False):
                root.removeHandler(h)
                try:
                    h.close()
                except Exception:  # noqa: BLE001 — closing a stale handler must never raise here
                    pass
        handler = RotatingFileHandler(path, maxBytes=SERVER_LOG_MAX_BYTES,
                                      backupCount=SERVER_LOG_BACKUP_COUNT, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [pid %(process)d]: %(message)s"))
        handler.setLevel(level)
        handler._kg_server_log = True  # type: ignore[attr-defined]  # marker for idempotent replace
        root.addHandler(handler)
        # Records propagate to the root handler; raise each logger's own level so the records are emitted
        # (the root level only gates records logged directly on root, not propagated ones).
        logging.getLogger("kg_engine").setLevel(level)
        logging.getLogger("mcp").setLevel(logging.WARNING)
        _install_excepthooks()
        return path
    except Exception:  # noqa: BLE001 — logging setup is best-effort; never block server startup on it
        return None


class _Watchdog:
    """A daemon thread that force-exits the process if a single MCP handler runs longer than `timeout`.

    FastMCP runs sync tools directly on the event loop (no thread offload), so a wedged handler — a
    deadlocked write, a runaway projection — blocks the whole loop and the client just sees "Running…"
    forever with no recovery. This observer thread (it never touches the handler, only watches a
    monotonic start stamp the tool envelope updates) breaks that: on timeout it dumps every thread's
    stack to the log and exits, so the Node supervisor relaunches a FRESH process. Crash-safe canon I/O
    (atomic temp+replace, the reclaimable lease) makes a hard exit recoverable; idempotent write receipts
    make a lost in-flight response harmless to retry.

    `on_trip` is injected so tests can assert a trip WITHOUT killing the test process (default
    `_hard_exit` — a teardown-free kill, because a wedged native import can deadlock `os._exit`)."""

    def __init__(self, timeout: float, *, on_trip=None, poll: float | None = None):
        self.timeout = float(timeout)
        self._poll = poll if poll is not None else max(1.0, self.timeout / 10.0)
        self._on_trip = on_trip or (lambda: _hard_exit(EXIT_WATCHDOG))
        self._lock = threading.Lock()
        self._name: str | None = None
        self._started: float = 0.0
        self._depth = 0
        # A multi-file canon write (kg_rename/kg_merge/kg_write) marks a CRITICAL section: a force-exit
        # mid-batch would leave the mutation half-applied (rename/merge are not crash-atomic across files).
        # When a handler overruns while `_critical` is set, the watchdog grants ONE grace extension before
        # tripping, so a slow (e.g. network-vault) atomic batch isn't killed mid-write (review:
        # watchdog-force-exit-mid-multi-file-write). Bounded to a single extension per handler span.
        self._critical = 0
        self._extended = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enter(self, name: str) -> None:
        with self._lock:
            self._depth += 1
            if self._depth == 1:
                self._name, self._started = name, time.monotonic()
                self._extended = False

    def begin_critical(self) -> None:
        with self._lock:
            self._critical += 1

    def end_critical(self) -> None:
        with self._lock:
            self._critical = max(0, self._critical - 1)

    def exit(self) -> None:
        with self._lock:
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._name, self._started = None, 0.0

    def overdue(self, now: float | None = None) -> "tuple[str, float] | None":
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._depth > 0 and self._name is not None:
                elapsed = now - self._started
                if elapsed > self.timeout:
                    # A multi-file canon write in flight: grant ONE grace extension (reset the clock) so a
                    # slow atomic batch isn't force-killed mid-write, leaving a half-applied rename/merge.
                    if self._critical > 0 and not self._extended:
                        self._extended = True
                        self._started = now
                        return None
                    return self._name, elapsed
        return None

    def start(self) -> "_Watchdog":
        if self.timeout <= 0 or self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name="kg-watchdog", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            hit = self.overdue()
            if hit:
                name, elapsed = hit
                self._trip(name, elapsed)
                return

    def _trip(self, name: str, elapsed: float) -> None:
        stacks = []
        for tid, frame in sys._current_frames().items():
            stacks.append(f"--- thread {tid} ---\n" + "".join(traceback.format_stack(frame)))
        logger.critical("watchdog: handler %r exceeded %.0fs (ran %.0fs); forcing a fresh process so "
                        "the supervisor relaunches.\n%s", name, self.timeout, elapsed, "\n".join(stacks))
        # FLUSH (don't logging.shutdown()) before the trip: the default on_trip is a hard kill
        # (_hard_exit — SIGKILL/TerminateProcess), which bypasses the interpreter's atexit flush, so the
        # critical record must be pushed to disk NOW. shutdown() would CLOSE every handler process-wide —
        # harmful to a still-running process and to the test suite.
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:  # noqa: BLE001 — a flush hiccup must not stop the trip
                pass
        self._on_trip()


# The active watchdog, set by main(). The tool envelope (_tool_result) feeds it without changing any
# wrapper signature (so the manifest scrape and FastMCP schema are untouched); None disables feeding.
_WATCHDOG: "_Watchdog | None" = None

# The active engine, set by _register(). The module-scope tool envelope has no engine reference, so it
# reads the CONFIGURED sensitivity from here to scrub raised-exception messages at the operator's chosen
# tier (not a hardcoded 'medium') before they cross the §1.9 egress — mirroring the engine's own
# _scrub_error path (review: error-envelope-ignores-configured-sensitivity). None → default 'medium'.
_ACTIVE_ENGINE: "KGEngine | None" = None


def _active_sensitivity() -> str:
    eng = _ACTIVE_ENGINE
    return eng.sensitivity if eng is not None else "medium"


class _SourceResolver:
    """Resolves the configured source path to a SourceSet, memoized on the aggregate
    (resolved-file-list, mtime) signature so an added/removed/edited file is picked up while the
    resolve+read stays off the hot path. Held by KGEngine (kg_scrub/kg_write span verification + the
    projector wiring) and constructed afresh for the read-only PreToolUse-hook projector, so both read
    the IDENTICAL source bytes. A single configured file is a one-entry SourceSet, byte-identical to the
    prior single-blob path."""

    def __init__(self, source_path=None):
        self.source_path = Path(source_path) if source_path else None
        self._cache: "tuple[tuple, SourceSet] | None" = None  # (signature, SourceSet) memo

    def resolve(self) -> SourceSet:
        """The current SourceSet (memoized on the file signature). Named `resolve` — the old name
        `set()` read as a mutator when it is the getter (review-r5)."""
        sig = SourceSet.signature(self.source_path)
        if self._cache is None or self._cache[0] != sig:
            self._cache = (sig, SourceSet(self.source_path))
        return self._cache[1]

    def text(self) -> str:
        return self.resolve().concat

    def set_path(self, source_path) -> None:
        """Re-point at a new source (and drop the memo) IN PLACE, so a holder of .resolve/.text —
        e.g. the already-wired projector — sees the change without being reconstructed."""
        self.source_path = Path(source_path) if source_path else None
        self._cache = None


def _wire_projector(canon, derived_dir, *, sources, pack_get, metrics_mode) -> Projector:
    """The SINGLE construction site for a Projector's source-corpus + specificity-seed + metrics wiring,
    shared by the writer engine (KGEngine.__init__) and the read-only PreToolUse hook
    (KGEngine.read_only_projector). Routing both through here means a hook-triggered projection computes
    the SAME IDF/specificity gate, spec_betweenness, and R3 stale-verdict scan as the server — it can
    never write a degraded empty-corpus derived layer the server then serves as fresh (finding:
    precontext-bypasses-facade). `sources` is a _SourceResolver; `pack_get` is a ZERO-ARG loader that
    may return None — a callable (not the pack itself) so the hook's common fast path (fresh index →
    kg_context only) never loads the pack at all; the projector evaluates the seeds lambda only inside
    a real projection (review-r6: hook-import-tax — load_pack pulls pydantic+yaml)."""
    return Projector(canon, derived_dir, metrics_mode=metrics_mode,
                     source_text=sources.text, source_set=sources.resolve,
                     specificity_seeds=lambda: dict(getattr(pack_get(), "specificity_seeds", {}) or {}))


def _load_pack_or_none(pack_path):
    """Load the pack at `pack_path`, or None when the path is absent/nonexistent or the pack is
    invalid — a bad pack must DEGRADE (no vocabulary enforcement, no specificity seeds), never crash
    the server or the read-only hook projector (review-r5: this try/except lived in both
    constructors)."""
    if not (pack_path and Path(pack_path).exists()):
        return None
    # Deferred import (review-r6: hook-import-tax): pack.py pulls pydantic (~75ms) + yaml for its
    # schema models; the read-only hook must reach this only when a projection actually needs seeds.
    from .pack import load_pack
    try:
        return load_pack(pack_path)
    except Exception:  # noqa: BLE001 — a bad pack must not crash engine construction
        return None


class EdgeOwnerUnreadable(Exception):
    """Raised by `_owner_of_edge` when no PARSEABLE note owns an edge id but a CORRUPT note textually
    references it — so `kg_ground` can report "node unreadable" (surfacing the corruption to the
    operator) instead of a misleading "edge not found" (review-low). Carries the offending note path."""


class KGEngine:
    """Stateful facade over canon + boundary + projector + reconciler + scrubber."""

    def __init__(self, project_dir, data_dir=None, *, source_path=None, pack_path=None,
                 sensitivity="medium", metrics_mode="structure_only",
                 max_edges_per_kb=DEFAULT_MAX_EDGES_PER_KB):
        self.project_dir = Path(project_dir)
        self.data_dir = Path(data_dir) if data_dir else (self.project_dir / envconfig.DATA_DIRNAME)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.canon = Canon(self.project_dir)
        self.reconciler = Reconciler(self.canon)
        # §1.8 grounding-audit log — the forge-detection WRITER half (the reconciler is the reader). A
        # collaborator, not inline, so the crash-safe append/truncate protocol is unit-testable.
        self._audit_log = GroundAuditLog(self.canon.root / GROUND_AUDIT)
        # The configured source: a single file (back-compat), or a DIRECTORY / GLOB of .md/.txt (R4).
        # Resolution + memo live in _SourceResolver, shared verbatim with the read-only PreToolUse hook.
        self._sources = _SourceResolver(source_path)
        # Load the pack BEFORE constructing the projector so its specificity_seeds are wired through the
        # SAME _wire_projector seam the read-only hook uses — no construction-site drift between the two
        # (finding: precontext-bypasses-facade). The resolved PATH is kept alongside the loaded pack so
        # the kg_diverge_* tools can hand the SAME pack to divergence axes resolution instead of it
        # re-reading KG_PACK_PATH from env — which, unset in a dev launch, silently sent the engine and
        # the divergence tools to DIFFERENT domain configs in one process (review-r5: pack split-brain).
        self.pack_path = Path(pack_path) if (pack_path and Path(pack_path).exists()) else None
        self.pack = _load_pack_or_none(self.pack_path)
        # The projector reads source/specificity lazily, once per real reprojection, off the hot path.
        self.projector = _wire_projector(self.canon, self.data_dir / envconfig.DERIVED_DIRNAME,
                                         sources=self._sources, pack_get=lambda: self.pack,
                                         metrics_mode=metrics_mode)
        self.scrubber = Scrubber(sensitivity)
        self._scrub_map: dict[str, str] = {}  # accumulated egress placeholder -> original (§1.9)
        self.sensitivity = sensitivity
        self.metrics_mode = metrics_mode
        self.max_edges_per_kb = max_edges_per_kb
        # Reason string the last reprojection failed with (None when projection is healthy). Reads serve
        # the existing/empty derived layer with this flag set rather than raising (defense: a projection
        # hiccup degrades a read, it never crashes a tool — see _ensure_projected).
        self._projection_degraded: str | None = None
        # Idempotency: an in-memory LRU of {idempotency_key → kg_write response} so re-sending an
        # identical write (after a lost transport response) is a TRUE no-op that returns the SAME receipt
        # and counts, not a second pass. Bounded by _WRITE_CACHE_MAX; lost on restart, but the
        # payload-derived `receipt` + id-dedup keep a post-restart retry safe regardless (§1.4).
        self._write_cache: "OrderedDict[str, dict]" = OrderedDict()
        # Canon-baseline cache for kg_write (the server-side twin of backend-1/server-16): the MCP path
        # re-parsed the ENTIRE canon once per kg_write call, making a parallel /kg-build wave
        # O(sections × notes). Holds {id: Node} keyed by the projector's cheap dir signature; after a
        # successful write only the touched notes are re-read (their exact post-merge state). Any
        # out-of-band writer — another process, kg_ground/kg_rename/kg_merge, a hand edit — moves the
        # cheap signature and the next call re-parses in full: the same invalidation primitive the
        # projector itself trusts (review-r4: kg_write-reparses-canon-per-call).
        # (cheap-sig, {id: Node}, {note_name: (size, mtime_ns)}) — the stat map lets _refresh_baseline
        # re-read exactly the notes that moved (ours OR a concurrent foreign writer's) so the cached
        # nodes always match the stored signature (review-low: partial-refresh stale-as-fresh).
        self._baseline_cache: "tuple[str, dict[str, Node], dict[str, tuple[int, int]]] | None" = None
        # §9/§15 — NAMED alternate canons (the /kg-perturb "second construction"): lazily-built,
        # cached sub-engines rooted under <project>/.kg/constructions/<slug>/, one per construction
        # name. The PRIMARY canon (`construction=None` everywhere else) is never in this map, so the
        # default write path is byte-for-byte unchanged. See _construction_engine.
        self._constructions: "dict[str, KGEngine]" = {}

    # ---- source set (for span verification) — delegate to the shared resolver
    def source_set(self) -> SourceSet:
        """The resolved {basename → text} view over the configured source(s) (R4), memoized off the hot
        path. A single configured file is a one-entry SourceSet, byte-identical to the prior path."""
        return self._sources.resolve()

    def source_text(self) -> str:
        """The configured source(s) concatenated — feeds the flood-budget size and the projector's IDF
        corpus. Span verification itself is per-file via source_set().verifies, not this blob."""
        return self._sources.text()

    def _source_signature(self) -> str:
        """sha256 of the current source payload (the SourceSet concat), matching
        ``projector._source_hash`` — the divergence-side twin of the graph advisory's source-change
        pre-gate (Stage 5, re-examinable verdicts). ``""`` when no source is configured. Used to stamp
        the source a materialized-pin failure was fated against, so a later source change can surface it
        as re-examinable on the brief side exactly as the graph side surfaces failed/rejected items."""
        try:
            payload = self.source_set().concat
        except Exception:  # noqa: BLE001 — a source-read hiccup degrades to "" (no signature), never crashes the sync
            return ""
        return hashlib.sha256(payload.encode()).hexdigest() if payload else ""

    @property
    def source_path(self):
        """The configured source Path (or None), backed by the shared resolver. Kept as a settable
        attribute for back-compat: the headless backend reads `.name`, and a test re-points it — the
        setter mutates the resolver in place so the already-wired projector follows."""
        return self._sources.source_path

    @source_path.setter
    def source_path(self, value) -> None:
        self._sources.set_path(value)

    @classmethod
    def read_only_projector(cls, project_dir, data_dir, *, source_path=None, pack_path=None,
                            metrics_mode="structure_only", lease_ttl=None) -> Projector:
        """A Projector wired IDENTICALLY to a live engine's (same source corpus + specificity seeds +
        metrics_mode) but over a no-side-effect Canon(ensure_layout=False) — for the read-only PreToolUse
        hook. Goes through the SAME _wire_projector seam as __init__, so the hook can never project a
        degraded (empty-corpus) derived layer the server then serves as fresh (finding:
        precontext-bypasses-facade). The pack is loaded LAZILY, memoized, on first projection — the
        hook fires on every Grep/Glob/Read and its common path (fresh index → kg_context) never needs
        the pack, so it must not pay load_pack's pydantic+yaml import (review-r6: hook-import-tax); a
        missing or bad pack still degrades to no specificity seeds, exactly as __init__ does.
        ``lease_ttl`` shortens the canon lease for callers that can be SIGKILLed mid-projection (the
        hook's 5s cap — review-r4: hook-kill-wedges-windows-writers) — a constructor seam instead of
        the reach-through ``proj.canon.lock.ttl`` mutation the hook used to do (review-r5)."""
        canon = Canon(project_dir, ensure_layout=False)
        if lease_ttl is not None:
            canon.lock.ttl = float(lease_ttl)
        pack_get = functools.lru_cache(maxsize=1)(lambda: _load_pack_or_none(pack_path))
        return _wire_projector(canon, Path(data_dir) / envconfig.DERIVED_DIRNAME,
                               sources=_SourceResolver(source_path), pack_get=pack_get,
                               metrics_mode=metrics_mode)

    # ---- tools -----------------------------------------------------------
    def kg_ping(self) -> dict:
        return {"name": "burgess", "version": __version__,
                "metrics_mode": self.metrics_mode, "sensitivity": self.sensitivity,
                "pack_loaded": self.pack is not None}

    def kg_scrub(self, text: str | None = None) -> dict:
        """Egress scrub (§1.9): redact secrets (always) + PII (per sensitivity) with CONSISTENT
        placeholders before any text is handed to a subagent for semantic work. Accumulates the local
        placeholder->original mapping so kg_write can restore spans to the original for the canon (the
        scrub protects the egress, not the local canon). Pass `text` to scrub a snippet, or omit to scrub
        the configured source. Returns the scrubbed text the subagent should see."""
        src = text if text is not None else self.source_text()
        scrubbed, mapping = self.scrubber.scrub(src)
        self._scrub_map.update(mapping)
        # Identity entries (a literal ⟦CAT:N⟧ already present in the source prose, mapped to itself so
        # restore leaves it alone — scrub-2/M4) are protection bookkeeping, not redactions: keep them
        # out of the reported count and category list so the response reflects real redactions only.
        real = {k: v for k, v in mapping.items() if v != k}
        return {"scrubbed": scrubbed, "redactions": len(real),
                "sensitivity": self.sensitivity, "categories": sorted({k.split(":")[0].strip("⟦") for k in real})}

    def _restore_fn(self):
        """The §1.9 span-restore: map placeholder spans back to the original before span verification,
        but ONLY when a scrub happened this session (else None — verify the span as written)."""
        return (lambda s: Scrubber.restore(s, self._scrub_map)) if self._scrub_map else None

    def _scrub_error(self, msg) -> str:
        """Scrub a handler's error string (a `{e}` exception interpolation — a corrupt-node parse error
        quoting un-scrubbed canon content, an OSError carrying a vault path) to the SAME §1.9 egress
        standard `kg_scrub` applies, before it is returned to the session. Uses the engine's configured
        sensitivity; never raises (see `_scrub_error_text`)."""
        return _scrub_error_text(msg, sensitivity=self.sensitivity)

    @contextlib.contextmanager
    def _critical_write(self):
        """Mark a multi-file canon-mutation region as CRITICAL for the watchdog: while it is held, a
        handler that overruns the watchdog timeout is granted ONE grace extension before the force-exit,
        so a slow atomic batch (network vault, contended fsync) isn't killed mid-write leaving a
        half-applied rename/merge (review: watchdog-force-exit-mid-multi-file-write). Best-effort — a
        missing/disabled watchdog is a no-op."""
        wd = _WATCHDOG
        if wd is not None:
            wd.begin_critical()
        try:
            yield
        finally:
            if wd is not None:
                wd.end_critical()

    _LOCKED_ERROR = "canon vault is locked by another live session"

    def _try_writer_lease(self) -> bool:
        """Take the single-writer lease with the bounded-BLOCKING acquire — the shared preamble of
        every canon-mutating handler (kg_ground/kg_rename/kg_merge; review-r5: the pattern and its
        rationale were triplicated). Acquire the lease FIRST, then read canon state FRESH under it:
        reading before locking let a concurrent cross-process writer be clobbered by a stale
        in-memory copy (lost update, F17/L5). The lease then stays held across the whole audit +
        write (+ unlink + commit) sequence so the records and their compensating truncate are atomic
        w.r.t. other writers (server-3); write_one/write_nodes re-acquire re-entrantly.
        Bounded-BLOCKING (never try_acquire_lock): a verdict/rename/merge is a WRITER, so brief
        cross-process contention (the detached reconcile worker, a headless backend holding the
        lease for one note) must SERIALIZE cleanly instead of failing outright; the 30s budget stays
        well under the watchdog timeout (review: writers-use-nonblocking-lock). Returns False when
        the vault stays held past the budget — the caller returns its own
        ``{ok: False, error: _LOCKED_ERROR, ...}`` shape."""
        try:
            self.canon.acquire_lock()
            return True
        except RuntimeError:
            return False

    def _commit_paths(self, touched, removed_id: str, message: str) -> None:
        """Best-effort git stage + commit of exactly ONE mutation's paths — shared by kg_rename and
        kg_merge (review-r5: the block was duplicated verbatim, comments included). Stage only the
        rewritten notes + the removed note, never a whole-tree `git add -A` re-scan (server-9), and
        scope the COMMIT to the same pathspec — a bare `git commit` would sweep any externally-staged
        files in the user's project repo into an engine commit (review:
        unscoped-commit-sweeps-staged-index)."""
        from .canon import _git, _git_ok
        if not _git_ok(self.canon.root):
            return
        paths = [str(self.canon.node_path(n.id)) for n in touched]
        paths.append(str(self.canon.node_path(removed_id)))
        _git(self.canon.root, "add", "--", *paths, check=False)
        _git(self.canon.root, "commit", "-m", message, "--allow-empty", "--", *paths, check=False)

    def _canon_baseline(self) -> "dict[str, Node]":
        """The {id: Node} canon baseline for kg_write's dedup/flood seeding, cached on the projector's
        cheap dir signature. The signature is computed BEFORE the parse: if a foreign writer lands
        mid-parse, the stored signature is already stale and the next call re-parses — the failure
        direction is always a redundant re-parse, never a stale baseline served as fresh."""
        stat_map = self.projector._cheap_stat_map()          # one stat sweep feeds both the sig and the map
        sig = self.projector._sig_of_stat_map(stat_map)
        cache = self._baseline_cache
        if cache is not None and cache[0] == sig:
            return cache[1]
        nodes = {n.id: n for n in self.canon.all_nodes()}
        self._baseline_cache = (sig, nodes, stat_map)
        return nodes

    def _refresh_baseline(self, written_ids) -> None:
        """Keep the canon-baseline cache warm after a write WITHOUT re-parsing the whole canon — and
        WITHOUT the previous stale-as-fresh hazard. The old version re-read only the ids WE wrote and
        stored a fresh aggregate signature, so a CONCURRENT foreign writer landing in the window since
        write_nodes released the lease (its note not in `written_ids`) got folded into the signature but
        NOT into `nodes`, and the next _canon_baseline then served that stale cache as fresh (review-low).
        Diff the per-note stat map instead: re-read EVERY note whose (size, mtime) moved since the cache
        was built (ours OR foreign), drop vanished notes — so the cached nodes always match the stored
        signature. `written_ids` is now only an unused hint (the stat diff subsumes it). Any hiccup drops
        the cache; correctness never depends on it (the next call falls back to a full parse)."""
        cache = self._baseline_cache
        if cache is None:
            return
        try:
            _old_sig, nodes, old_map = cache
            new_map = self.projector._cheap_stat_map()
            if new_map == old_map:
                return                                   # nothing moved (e.g. a true no-op write)
            _nid = lambda name: name[:-3] if name.endswith(".md") else name  # noqa: E731 — note file is <id>.md
            for name, st in new_map.items():
                if old_map.get(name) != st:              # changed or newly-appeared note -> re-read it
                    nid = _nid(name)
                    nodes[nid] = self.canon.read_node(nid)
            for name in old_map.keys() - new_map.keys():  # a note that vanished -> drop it
                nodes.pop(_nid(name), None)
            self._baseline_cache = (self.projector._sig_of_stat_map(new_map), nodes, new_map)
        except Exception:  # noqa: BLE001 — cache maintenance must never fail a write
            self._baseline_cache = None

    @staticmethod
    def _append_note(existing: str, addition: str) -> str:
        """Append `addition` to a notes field with the load-bearing ` | ` separator (the field is later
        parsed/displayed); names the separator once."""
        return (existing + " | " if existing else "") + addition

    @staticmethod
    def _payload_receipt(payload: dict) -> str:
        """A deterministic receipt token for a write payload: a short hash over the SORTED set of
        canonical ids the payload targets AND their content-bearing fields (node label/body/type/axes;
        edge span/notes/confidence/axes). Same payload → same receipt, independent of dedup status or
        process restarts — so a lost transport response is harmless: re-sending the identical payload
        yields the identical `receipt`, and "did my write land?" becomes a cheap retry rather than an
        out-of-band read of the canon dir. Folding the content in (not just the ids) is what lets the
        idempotency replay branch tell a genuine retry (identical content) apart from a same-ids payload
        whose text CHANGED (e.g. a corrected span) — the latter must be processed, not silently replayed
        (review: receipt-id-only-drops-content-correction)."""
        items = []
        for n in (payload or {}).get("nodes") or []:
            n = n or {}
            nid = n.get("id") or n.get("label") or ""
            content = {k: n.get(k) for k in
                       ("label", "body", "node_type", "file_type", "provenance", "authored_by",
                        "epistemic_state", "confidence") if k in n}
            items.append("node:" + slug(str(nid)) + "|"
                         + json.dumps(content, sort_keys=True, ensure_ascii=True, default=str))
        for e in (payload or {}).get("edges") or []:
            e = e or {}
            eid = edge_id(str(e.get("source", "")), str(e.get("relation", "")),
                          str(e.get("target", "")))
            content = {k: e.get(k) for k in
                       ("span", "notes", "note", "confidence", "confidence_score", "provenance",
                        "authored_by", "epistemic_state", "source_file") if k in e}
            items.append("edge:" + eid + "|"
                         + json.dumps(content, sort_keys=True, ensure_ascii=True, default=str))
        digest = hashlib.sha1("\n".join(sorted(items)).encode("utf-8")).hexdigest()
        return f"rcpt_{digest[:16]}"

    # ---- named alternate canons (the /kg-perturb "second construction", §9/§15) ----------
    def _construction_root(self, construction: str) -> Path:
        """On-disk root of a NAMED alternate canon — a SIBLING of the divergence base
        (`<project>/.kg/diverge`) under the gitignored `.kg/` runtime tree (§12 open-q: keep the two
        concerns in separate dirs). `.kg/` is gitignored but DURABLE on disk (it does not delete itself
        between sessions), so session-ephemerality is enforced by `_construction_engine`, which wipes a
        stale root the first time a construction is materialized in a session (review-fix: M1)."""
        return self.project_dir / ".kg" / "constructions" / _construction_slug(construction)

    def _new_construction_engine(self, root: Path, source) -> "KGEngine":
        """Build a fresh sub-engine rooted at a construction dir with git COMMITS DISABLED — the dir
        lives under the parent repo's worktree, so a commit would `git add` the ephemeral construction
        canon into the user's tracked history (§9/§15, review-fix: H1). Everything else is the full
        primary write path (boundary → canon → projector)."""
        root.mkdir(parents=True, exist_ok=True)
        eng = KGEngine(root, source_path=source, pack_path=self.pack_path,
                       sensitivity=self.sensitivity, metrics_mode=self.metrics_mode,
                       max_edges_per_kb=self.max_edges_per_kb)
        eng.canon.git_enabled = False  # H1: never commit an ephemeral construction into the parent repo
        return eng

    def _construction_engine(self, construction: str, source=None) -> "KGEngine":
        """Lazily create + cache a `KGEngine` bound to a SEPARATELY-NAMED alternate canon under
        `<project>/.kg/constructions/<slug>/` — the key-free, in-session "second construction" the
        `/kg-perturb` exo move cross-generates against (§9/§15). The PRIMARY canon is never touched;
        this mirrors `divergence/state.py`'s per-name store rule (perturb-fix finding 5).

        The crux (perturb-fix §6.3): it reuses the FULL primary write path — boundary → canon →
        projector — rooted at the alternate dir (git-disabled, H1), so the session's OWN `kg-extractor`
        can populate a second construction with **no API key** (the "LLM is the session" model, §2.2),
        and spans verify against the construction's OWN `source`.

        Session-ephemerality + staleness (review-fix: M1). `.kg/` persists on disk across sessions, so
        the FIRST materialization of a name this session WIPES any stale root left by a dead session —
        making the store genuinely session-fresh rather than silently merging yesterday's structure. A
        same-session re-point to a DIFFERENT `source` (an edited second source under the same name) also
        rebuilds from scratch; re-passing the SAME source (a per-section build wave) keeps the engine and
        its resolver memo. `source=None` is a projection-only resolve — keep the configured source (spans
        are verified + stored at write time, never re-verified; the projector degrades on an empty
        corpus)."""
        name = str(construction)
        eng = self._constructions.get(name)
        if eng is None:
            if len(self._constructions) >= _MAX_CONSTRUCTIONS:
                raise ValueError(
                    f"too many second constructions this session (limit {_MAX_CONSTRUCTIONS}); reuse an "
                    "existing construction name instead of minting new ones")
            root = self._construction_root(name)
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)  # M1: drop a stale prior-session build
            eng = self._new_construction_engine(root, source)
            self._constructions[name] = eng
        elif source is not None and eng.source_path != Path(source):
            # the second source CHANGED mid-session (an edited doc under the same name): rebuild from
            # scratch so stale nodes/edges from the old source don't merge with the new (M1). Re-pointing
            # the resolver alone would keep the old structure. `source=None` never reaches here, so a
            # projection-only resolve keeps the configured source and the built structure intact.
            root = self._construction_root(name)
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            eng = self._new_construction_engine(root, source)
            self._constructions[name] = eng
        return eng

    def kg_write(self, payload: dict, *, message: str = "kg_write", existing_nodes=None,
                 idempotency_key: str | None = None, construction: str | None = None,
                 source=None) -> dict:
        """Validate an extraction payload at the boundary and write accepted/demoted items.

        `existing_nodes` is the canon baseline used for dedup + rate-limit seeding; it defaults to the
        signature-cached parse in `_canon_baseline` (a full parse only when the canon dir actually
        changed out-of-band). The headless backend threads its own incrementally-maintained baseline
        so it doesn't re-parse the entire canon once per section (backend-1/server-16).

        **Idempotency (a lost response is harmless).** The response always carries a deterministic
        `receipt` derived from the payload (`_payload_receipt`). If `idempotency_key` is supplied and was
        seen before in this process WITH THE SAME PAYLOAD (same receipt), the cached response is returned
        VERBATIM with `idempotent_replay: True` — no re-validation, no second write — so a client that
        retries after a dropped transport result gets the IDENTICAL receipt + dispositions instead of a
        confusing all-deduped second pass. If the same key is reused with a DIFFERENT payload (a caller
        contract violation), the new write is NOT silently dropped: it is processed normally and re-caches
        the key (a warning is logged). Validation is never weakened: a mismatching/first-seen key validates
        and writes normally. Idempotency is also intrinsic without a key — kg_write dedups by canonical id,
        so a re-send creates no duplicates regardless (§1.4).

        **Second construction (§9/§15).** `construction` (a name) routes this SAME key-free, span-verified
        write to a separately-named alternate canon (`_construction_engine`) instead of the primary one,
        and `source` names the second source document the spans are verified against. This is how
        `/kg-perturb` builds its exo "second construction" in-session with no API key. `construction=None`
        (every other caller) is the unchanged primary-canon path."""
        if construction:
            # Route to the named alternate canon's own engine — full boundary → canon → projector,
            # rooted elsewhere. The sub-engine computes its own baseline (never the primary's
            # existing_nodes) and uses its own idempotency cache.
            return self._construction_engine(construction, source).kg_write(
                payload, message=message, idempotency_key=idempotency_key)
        if source is not None:
            # `source` only names the second construction's own source; without `construction` it would be
            # silently dropped (the primary source is fixed at startup). Refuse loudly rather than no-op on
            # a caller that thinks it is re-pointing the primary source (review-fix: L3/server-5).
            raise ValueError("`source` is only valid together with `construction` (it names the second "
                             "construction's source document); omit it for a primary-canon write")
        receipt = self._payload_receipt(payload)
        if idempotency_key:
            cached = self._write_cache.get(idempotency_key)
            if cached is not None:
                if cached.get("receipt") == receipt:
                    self._write_cache.move_to_end(idempotency_key)
                    # Deep-copy so the replayed receipt's nested `dispositions`/`details`/`written_nodes`
                    # do NOT alias the cached objects — a caller mutating a replay can't corrupt the cache.
                    return {**copy.deepcopy(cached), "idempotent_replay": True}
                # same key, DIFFERENT payload: a caller error. Don't replay a stale receipt and silently
                # drop this write — process it normally (it re-caches the key below).
                logger.warning("idempotency_key %r reused with a different payload; processing the new "
                               "write instead of replaying the cached receipt", idempotency_key)
        # if egress scrubbing happened this session, restore placeholder spans to the original before
        # span verification, and store the original in the canon (§1.9).
        restore = self._restore_fn()
        if existing_nodes is None:
            # cached parse keyed on the canon dir signature (see _canon_baseline) — a wave of
            # kg_write calls re-parses only the notes each write touched, not the whole canon.
            existing_nodes = list(self._canon_baseline().values())
        existing_edges = [e for n in existing_nodes for e in n.edges]
        # Deferred import (review-r6: hook-import-tax): boundary pulls pydantic (~75ms), which only
        # this write path needs — the read-only PreToolUse hook imports this module on every
        # Grep/Glob/Read and must not pay for it. Same pattern as generate/advisory_geometry/export.
        from .boundary import merge_results_into_nodes, validate_payload
        results = validate_payload(payload, pack=self.pack, source_text=self.source_text(),
                                   sources=self.source_set(),
                                   existing=existing_edges,
                                   existing_node_ids={n.id for n in existing_nodes},
                                   restore=restore, max_edges_per_kb=self.max_edges_per_kb)
        nodes = merge_results_into_nodes(results)
        with self._critical_write():
            info = self.canon.write_nodes(list(nodes.values()), message=message) if nodes else None
        rolled_back = bool(info and info.rolled_back)
        summary: dict = {d.value: 0 for d in Disposition}
        for r in results:
            summary[r.disposition.value] += 1
        # CONTRACT (F10/M4): the dispositions summary and written_nodes are built from PRE-write
        # ValidationResults; if the batch ROLLED BACK nothing persisted. Re-bucket the would-have-been
        # ACCEPTED/DEMOTED counts into a `rolled_back` bucket and empty written_nodes so the payload can
        # never contradict `rolled_back: True`. Backend consumers: when rolled_back is True,
        # written_nodes is [] and the accepted/demoted counts must NOT be trusted/accumulated.
        written = list(nodes)
        if rolled_back:
            summary["rolled_back"] = sum(summary.get(d, 0) for d in PERSISTED_DISPOSITIONS)
            for d in PERSISTED_DISPOSITIONS:
                summary[d] = 0
            written = []
        else:
            # keep the canon-baseline cache warm: fold the just-written notes back in (their exact
            # post-merge state) so the NEXT kg_write skips the full canon re-parse. A rollback restored
            # files (mtimes moved), so its stale cache self-invalidates via the signature instead.
            if written:
                self._refresh_baseline(written)
        out = {
            "dispositions": summary,
            "details": [{"kind": r.kind, "id": getattr(r.item, "id", None), "disposition": r.disposition.value,
                         "reason": r.reason, "retryable": r.retryable} for r in results],
            "written_nodes": written,
            "rolled_back": rolled_back,
            # scrub like every sibling error-return (883/926/1065/1113/1218/1276): info.error is str(e)
            # of the canon write fault and can embed an absolute vault path; the _tool_result envelope
            # only scrubs RAISED exceptions, never a returned dict, so an unscrubbed path would cross the
            # §1.9 egress boundary (review-r7).
            "error": (self._scrub_error(info.error) if rolled_back else None),
            "receipt": receipt,
        }
        # Cache the response under the idempotency key (bounded LRU) so an exact retry replays it verbatim.
        # Do NOT cache a rolled-back batch: a rollback is a transient failure (e.g. an I/O error), and a
        # retry should be allowed to actually write, not replay the failure.
        if idempotency_key and not rolled_back:
            # Snapshot a deep copy so the returned `out` (which the caller may mutate) and the cached
            # receipt never share nested structures.
            self._write_cache[idempotency_key] = copy.deepcopy(out)
            self._write_cache.move_to_end(idempotency_key)
            while len(self._write_cache) > _WRITE_CACHE_MAX:
                self._write_cache.popitem(last=False)
        return out

    def kg_propose(self, payload: dict, *, message: str = "kg_propose",
                   construction: str | None = None, source=None) -> dict:
        """Write hypothesized candidates through the boundary (PLAN Stage 1: the propose lane).

        A thin, explicit alias over `kg_write` that keeps the two write lanes legible at the call site:
        every item is forced to `provenance=hypothesized`, and any item that arrives explicitly claiming
        a text-claim provenance (`span-present`/`inferred`) is REFUSED with reason `propose-lane-text-claim`
        rather than silently re-lanned — text claims belong on `kg_write`, proposals belong here. The
        accepted items then transit the SAME boundary (`validate_payload`), so the hypothesized-lane rules
        (no span required, forged verdicts demoted, failure-collapse quarantined, pack vocabulary enforced)
        apply uniformly.

        `construction`/`source` route the propose lane to a named alternate canon exactly like `kg_write`
        (§9/§15), for writing hypothesized edges into a second construction; `construction=None` is the
        unchanged primary-canon path."""
        if construction:
            return self._construction_engine(construction, source).kg_propose(payload, message=message)
        if source is not None:
            raise ValueError("`source` is only valid together with `construction` (it names the second "
                             "construction's source document); omit it for a primary-canon propose")
        payload = dict(payload or {})
        refused: list[dict] = []

        def _lane(items, kind):
            kept = []
            for it in (items or []):
                it = dict(it or {})
                prov = it.get("provenance")
                if prov in (Provenance.SPAN_PRESENT.value, Provenance.INFERRED.value):
                    refused.append({"kind": kind,
                                    "id": it.get("id") or it.get("source") or it.get("label"),
                                    "disposition": Disposition.REJECTED.value,
                                    "reason": "propose-lane-text-claim", "retryable": False})
                else:
                    it["provenance"] = Provenance.HYPOTHESIZED.value  # force the lane
                    kept.append(it)
            return kept

        clean = {"nodes": _lane(payload.get("nodes"), "node"),
                 "edges": _lane(payload.get("edges"), "edge")}
        if "complete" in payload:
            clean["complete"] = payload["complete"]
        out = self.kg_write(clean, message=message)
        # fold the call-site refusals into the same response shape kg_write returns
        out["details"] = refused + out["details"]
        out["dispositions"][Disposition.REJECTED.value] = (
            out["dispositions"].get(Disposition.REJECTED.value, 0) + len(refused))
        out["propose_lane"] = True
        out["refused_text_claims"] = len(refused)
        return out

    def kg_ground(self, target_id: str, verdict: str, *, by: str = "agent", kind: str = "edge",
                  note: str = "", support_span: str = "", support_note: str = "") -> dict:
        """Apply a grounding verdict (the ONLY path that may set a verdict state). Stamps the verdict
        and appends an audit record so the reconciler treats the transition as legitimate (§1.8).

        **Promotion of a hypothesis requires support (PLAN Stage 8 / §1.2-3).** A `hypothesized` edge
        may become `grounded` ONLY when a grounder supplies support, which UPGRADES its provenance:
        `support_span` (a verbatim substring of the source) → `span-present`; `support_note` (an external
        citation, no span) → `inferred`. Without either, grounding a hypothesis to `grounded` is refused
        with `hypothesis-needs-support` — generated ideas become grounded knowledge only by earning it.
        The same gate applies to a hypothesized NODE (a compression node / primitive from the propose
        lane): it too earns grounding only with support, restated into the node body (a Node has no span
        field). `support_*` are ignored for non-hypothesized items and for any verdict other than `grounded`.

        `note` is appended to the EDGE's `notes` and is **edge-only**: a Node has no notes field, so a
        `note` passed with `kind='node'` is ignored (the verdict's audit record still captures `by`)."""
        # Strip/normalize inputs like kg_rename/kg_merge do, so a stray-whitespace verdict (" grounded ")
        # isn't mis-classified as invalid and a stray-whitespace `kind` is canonicalized before dispatch.
        verdict = verdict.strip().lower()
        if verdict not in VALID_VERDICTS:
            return {"ok": False, "error": f"invalid verdict {verdict!r}"}
        # `kind` selects the dispatch branch; reject anything outside {node,edge} up front (mirroring the
        # verdict clamp) so a typo'd `kind` (e.g. 'Node', 'edges', '') can't fall through the else into the
        # edge path and surface a misleading 'edge not found' for what was meant as a node verdict.
        kind = kind.strip()
        if kind not in ("node", "edge"):
            return {"ok": False, "error": f"invalid kind {kind!r}; expected node|edge"}
        # `by` is provenance, not a free-text field: clamp to the known actors so a stray value can't
        # masquerade as a verdict author (the MCP tool surface already pins this to "agent").
        by = by if by in VALID_ACTORS else "agent"
        state = EpistemicState(verdict)
        promoted_to = None
        # Lease-first read-modify-write; the full rationale (F17/L5, server-3,
        # writers-use-nonblocking-lock) lives once on _try_writer_lease.
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR}
        try:
            if kind == "node":
                # Canonicalize the node id like kg_rename/kg_merge (`slug`) so a non-canonical id doesn't
                # yield a false "node not found". Edge ids already arrive canonical from reads, so the edge
                # branch below deliberately does NOT slug `target_id`.
                target_id = slug(target_id)
                if not self.canon.exists(target_id):
                    return {"ok": False, "error": "node not found"}
                try:
                    node = self.canon.read_node(target_id)  # corrupt/invalid-UTF-8 note → structured error (F13/L1)
                except Exception as e:  # noqa: BLE001 — surface as a structured error, not an MCP exception
                    return {"ok": False, "error": self._scrub_error(f"node unreadable: {e}")}
                # the hypothesized→grounded promotion gate applies to NODES too: kg_operate writes
                # hypothesized compression nodes/primitives via the propose lane, so a generated node must
                # earn grounding with support, not become grounded knowledge for free (mirrors the edge
                # gate; decided BEFORE any state change so a refusal leaves the node untouched).
                if node.provenance == Provenance.HYPOTHESIZED and state == EpistemicState.GROUNDED:
                    promoted_to, err = self._promote_hypothesis_node(node, support_span, support_note)
                    if err:
                        return {"ok": False, "error": err}
                frm = node.epistemic_state.value
                node.epistemic_state = state
                key = f"node:{node.id}"
            else:
                try:
                    node = self._owner_of_edge(target_id)
                except EdgeOwnerUnreadable as e:
                    return {"ok": False, "error": self._scrub_error(f"node unreadable: {e}")}
                if node is None:
                    return {"ok": False, "error": "edge not found"}
                edge = next(e for e in node.edges if e.id == target_id)
                # the hypothesized→grounded promotion gate: a span-less proposal earns grounding only with
                # support, which upgrades its provenance. Decided BEFORE any state change so a refusal leaves
                # the edge untouched (no audit record, no write).
                if edge.provenance == Provenance.HYPOTHESIZED and state == EpistemicState.GROUNDED:
                    promoted_to, err = self._promote_hypothesis(edge, support_span, support_note)
                    if err:
                        return {"ok": False, "error": err}
                frm = edge.epistemic_state.value
                edge.epistemic_state = state
                edge.verdict_by = by
                edge.verdict_at = utcnow()
                if note:
                    edge.notes = self._append_note(edge.notes, note)
                key = edge.id
            # Append the audit record BEFORE persisting the verdict (a CRASH between the two leaves an
            # audit record with no state change — harmless, unconsumed — rather than a verdict with no
            # audit record, which the reconciler would re-quarantine), and truncate it back on a caught
            # write failure so an orphan record can't inflate _forged's count (server-3). The crash-safe
            # offset/truncate dance lives in GroundAuditLog.audited_write, shared with kg_rename.
            err_holder: dict = {}

            def _attempt():
                try:
                    self.canon.write_one(node)
                    return True, None
                except Exception as e:  # noqa: BLE001 — surface as a structured error, not an MCP exception
                    err_holder["error"] = self._scrub_error(f"write failed: {e}")
                    return False, None

            self._audit_log.audited_write([(key, frm, verdict, by)], _attempt)
            if err_holder:  # the transition never happened; its record was truncated
                return {"ok": False, "error": err_holder["error"]}
            out = {"ok": True, "key": key, "from": frm, "to": verdict, "by": by}
            if promoted_to:  # a hypothesis was promoted — its provenance was upgraded (PLAN Stage 8)
                out["provenance_upgraded_to"] = promoted_to
            return out
        finally:
            self.canon.release_lock()

    def _promote_support(self, *, verify, apply_span, apply_note, support_span, support_note):
        """The shared §1.2-3 / PLAN-Stage-8 hypothesized→grounded promotion SKELETON (review-r5: the
        edge and node gates were ~80% identical twins): a span-less proposal earns grounding only
        with support, which UPGRADES its provenance. `support_span` (a verbatim source substring,
        placeholder-restored first) must verify via `verify` and meet MIN_SPAN_CHARS → span-present;
        else `support_note` (an external citation) → inferred; neither → `hypothesis-needs-support`.
        The `apply_*` callbacks mutate the item in place ONLY after the checks pass, so a refusal
        leaves it untouched (no state change, no audit, no write). Returns (promoted_to, None) on
        success, (None, error) on refusal."""
        restore = self._restore_fn()
        if support_span and support_span.strip():
            check = restore(support_span) if restore else support_span
            if not verify(check):
                return None, "support-span-not-in-source"
            if len(normalize_text(check).replace(" ", "")) < MIN_SPAN_CHARS:
                return None, "support-span-too-short"
            apply_span(check)
            return Provenance.SPAN_PRESENT.value, None
        if support_note and support_note.strip():
            apply_note(support_note.strip())
            return Provenance.INFERRED.value, None
        return None, "hypothesis-needs-support"

    def _promote_hypothesis(self, edge, support_span: str, support_note: str):
        """The EDGE promotion gate over `_promote_support`. Source-aware (R4): the span verifies
        against the edge's named source if it has one, else any declared source — the
        not-in-ANY-source contract is unchanged (support-span-not-in-source); a promotion span just
        has to exist SOMEWHERE. Support lands on the edge's own fields: the span becomes `edge.span`
        (now citable), a citation is appended to `edge.notes`."""
        def apply_span(check):
            edge.span = check
            edge.provenance = Provenance.SPAN_PRESENT        # upgraded: now citable
        def apply_note(note):
            edge.provenance = Provenance.INFERRED            # upgraded: asserted via external citation
            edge.notes = self._append_note(edge.notes, f"citation: {note}")
        return self._promote_support(
            verify=lambda s: self.source_set().verifies(s, source_file=edge.source_file),
            apply_span=apply_span, apply_note=apply_note,
            support_span=support_span, support_note=support_note)

    def _promote_hypothesis_node(self, node, support_span: str, support_note: str):
        """The NODE promotion gate over `_promote_support` (a generated compression node / primitive
        from the propose lane). A Node has no `span`/`notes` field, so the support is restated into
        the node BODY (the only persisted free-text — body prose may restate cited spans) rather
        than a stray span attr; the span verifies against ANY declared source."""
        def apply_span(check):
            node.body = self._append_body(node.body, f"grounding span: {check}")
            node.provenance = Provenance.SPAN_PRESENT        # upgraded: now citable
        def apply_note(note):
            node.body = self._append_body(node.body, f"citation: {note}")
            node.provenance = Provenance.INFERRED            # upgraded: asserted via external citation
        return self._promote_support(
            verify=lambda s: self.source_set().verifies(s),
            apply_span=apply_span, apply_note=apply_note,
            support_span=support_span, support_note=support_note)

    @staticmethod
    def _append_body(existing: str, addition: str) -> str:
        """Append `addition` as its own paragraph to a node body, preserving any existing prose."""
        existing = (existing or "").rstrip("\n")
        return (existing + "\n\n" if existing else "") + addition

    def _owner_of_edge(self, edge_id: str) -> Node | None:
        # O(1) lookup via the derived index (id -> source) instead of an O(N) full-canon scan per
        # kg_ground call, which made draining the grounding queue quadratic (server-2). The index is
        # read-only here; on a miss (just-written edge not yet projected, or no index) fall back to a
        # scan so correctness never depends on derived freshness.
        #
        # Do NOT _ensure_projected() here (review-M3): every prior kg_ground bumps node.updated_at, so
        # is_stale() returns True on the next call and _ensure_projected would run a full
        # betweenness/gate reproject — making a /kg-ground drain O(N * V*E), exactly the quadratic the
        # index was added to remove. Correctness doesn't need freshness: a just-written edge the index
        # hasn't seen is found by the canon-scan fallback below.
        try:
            src = self.projector.owner_of_edge(edge_id)
            if src and self.canon.exists(src):
                node = self.canon.read_node(src)
                if any(e.id == edge_id for e in node.edges):
                    return node
        except Exception as e:  # noqa: BLE001 — index trouble must never break grounding; fall back
            logger.debug("edge-owner index lookup failed (%s); falling back to full canon scan", e)
        # Scan by note path (not all_nodes(), which silently DROPS a note that fails to parse): a
        # corrupt note owning this edge would otherwise make us return None and report a misleading
        # "edge not found", masking the real corruption. Remember an unreadable note that textually
        # references the id and, if the edge is found nowhere parseable, surface it as unreadable
        # (mirrors the node branch's "node unreadable"; review-low).
        unreadable: "Path | None" = None
        for p in self.canon.note_paths():
            try:
                n = self.canon.read_node(p.stem)
            except Exception:  # noqa: BLE001 — a corrupt note must not blind the scan to the rest
                try:
                    if edge_id in p.read_text(encoding="utf-8", errors="replace"):
                        unreadable = unreadable or p
                except OSError:
                    pass
                continue
            if any(e.id == edge_id for e in n.edges):
                return n
        if unreadable is not None:
            raise EdgeOwnerUnreadable(str(unreadable))
        return None

    def _audit_path(self) -> Path:
        """The grounding-audit log path. Thin accessor (the durability protocol lives in GroundAuditLog);
        kept because tests read the raw audit bytes through it."""
        return self._audit_log.path

    def _rewrite_endpoints(self, edge, old: str, new: str):
        """Rewrite an edge's old→new endpoints, recompute its deterministic id from the new endpoints,
        and report the integration-1 migration. Returns (changed, migration | None) where migration =
        (new_id, state_value) iff the id actually CHANGED and the edge is in a policed (verdict-or-
        obsolete) state — the load-bearing record that preserves grounding/failure memory across a
        rename, kept in ONE place so the two rename loops can never drift apart."""
        old_eid = edge.id
        if edge.source == old:
            edge.source = new
        if edge.target == old:
            edge.target = new
        edge.id = edge_id(edge.source, edge.relation, edge.target)  # keep id consistent with endpoints
        changed = edge.id != old_eid
        migration = ((edge.id, edge.epistemic_state.value)
                     if changed and edge.epistemic_state in GROUNDABLE_STATES else None)
        return changed, migration

    def kg_rename(self, old_id: str, new_id: str, *, message: str = "kg_rename") -> dict:
        """Rename a node and rewrite every edge endpoint referencing it (single-canonical-edge safe)."""
        old, new = slug(old_id), slug(new_id)
        # Lease FIRST, then read the canon fresh under it and compute the migration set + touched
        # notes before write_nodes (the rationale lives on _try_writer_lease; the rename-specific
        # hazard: reading before locking let a concurrent verdict on a SIBLING edge of a touched node
        # be clobbered by this rename's stale verbatim write — a lost update of grounding memory the
        # reconciler can't recover, F17/L5).
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR, "old": old, "new": new}
        try:
            if not self.canon.exists(old):
                return {"ok": False, "error": "node not found"}
            if self.canon.exists(new):
                return {"ok": False, "error": "target id exists"}
            try:
                node = self.canon.read_node(old)  # corrupt/invalid-UTF-8 note → structured error (F13/L1)
            except Exception as e:  # noqa: BLE001 — surface as a structured error, not an MCP exception
                return {"ok": False, "error": self._scrub_error(f"node unreadable: {e}"),
                        "old": old, "new": new}
            # A rename recomputes edge ids (and the node id), but the kg_ground audit record + reconciler
            # baseline are keyed by those ids. Collect every policed-state (verdict OR obsolete) item whose
            # id CHANGES so we can write a migrating audit record for the NEW id — otherwise the reconciler
            # sees a verdict at an id with no audit record and re-quarantines it, silently erasing the
            # grounding/failure memory (integration-1).
            migrations: list[tuple[str, str]] = []  # (new_key, state_value)
            if node.epistemic_state in GROUNDABLE_STATES:
                migrations.append((f"node:{new}", node.epistemic_state.value))
            node.id = new
            for e in node.edges:
                _, mig = self._rewrite_endpoints(e, old, new)
                if mig:
                    migrations.append(mig)
            node.edges = self._dedup_rename_edges(node.edges)
            touched = [node]
            for other in self.canon.all_nodes():
                if other.id == old:
                    continue
                node_changed = False
                for e in other.edges:
                    changed, mig = self._rewrite_endpoints(e, old, new)
                    node_changed |= changed
                    if mig:
                        migrations.append(mig)
                if node_changed:
                    other.edges = self._dedup_rename_edges(other.edges)
                    touched.append(other)
            # Emit the migrating audit records (compensated by truncation if the batch rolls back, like
            # kg_ground), then write the corrected nodes VERBATIM (merge=False): merging would
            # re-introduce each note's pre-rename edges (different id -> not deduped) and leave dangling
            # old endpoints. The offset/truncate dance lives in GroundAuditLog.audited_write, shared with
            # kg_ground; here the failure SIGNAL is info.rolled_back from write_nodes, not a caught exception.
            def _attempt():
                info = self.canon.write_nodes(touched, message=message, commit=False, merge=False)
                return (not info.rolled_back), info

            records = [(new_key, EpistemicState.UNVERIFIED.value, state, "agent")
                       for new_key, state in migrations]
            with self._critical_write():
                info = self._audit_log.audited_write(records, _attempt)
            if info.rolled_back:
                # the batch rolled back — do NOT unlink the old note, or the node would be lost entirely
                # (its migrating audit records were already truncated by GroundAuditLog.audited_write).
                # scrub: info.error can embed an absolute vault path (str of the write fault), and the
                # _tool_result envelope never scrubs a returned dict — mirror the sibling branch below (review-r7).
                return {"ok": False, "error": self._scrub_error(f"rename rolled back: {info.error}"),
                        "old": old, "new": new}
            try:
                self.canon.node_path(old).unlink(missing_ok=True)
            except OSError as e:  # the new note already landed; surface a structured error, not a raw raise
                return {"ok": False, "old": old, "new": new, "touched": [n.id for n in touched],
                        "error": self._scrub_error(f"rename wrote '{new}' but could not remove old '{old}': {e}")}
            self._commit_paths(touched, old, message)
            return {"ok": True, "old": old, "new": new, "touched": [n.id for n in touched]}
        finally:
            self.canon.release_lock()

    @staticmethod
    def _merge_edge_pair(a: Edge, b: Edge) -> Edge:
        """Coalesce two edges that collide on ONE canonical id into a single edge — the dedup step of
        kg_merge — deterministically and WITHOUT forging, upgrading, or inventing a verdict/span.

        The merged epistemic_state is whichever of the two ranks higher (failed/rejected sticky as
        never-pruned negative information §1.7, else grounded > unverified), so the state is ALWAYS one
        a real edge already held. The verbatim span and verdict note are kept non-empty (never invented),
        and the verdict attribution (`verdict_by`/`verdict_at`) travels WITH the winning state so a
        grounded/failed edge is never left as a verdict floating over empty support (§1.8). The function
        is order-insensitive: swapping (a, b) yields the same merged edge."""
        ra, rb = _MERGE_STATE_RANK[a.epistemic_state], _MERGE_STATE_RANK[b.epistemic_state]
        if ra != rb:
            hi, lo = (a, b) if ra > rb else (b, a)
        else:
            # same state — keep the record carrying real evidence so its span + verdict stay paired.
            hi, lo = ((a, b) if _MERGE_PROV_RANK[a.provenance] >= _MERGE_PROV_RANK[b.provenance]
                      else (b, a))
        state = hi.epistemic_state
        # Keep a non-empty verbatim span, preferring the winning-state edge's (the span its verdict
        # cited). A surviving real span IS span-present; otherwise keep the stronger spanless provenance.
        span = hi.span or lo.span
        if span:
            provenance = Provenance.SPAN_PRESENT
        else:
            provenance = (a.provenance if _MERGE_PROV_RANK[a.provenance] >= _MERGE_PROV_RANK[b.provenance]
                          else b.provenance)
        verdict_by, verdict_at = ((hi.verdict_by, hi.verdict_at)
                                  if state in GROUNDABLE_STATES else (None, None))
        return Edge(source=hi.source, target=hi.target, relation=hi.relation,
                    provenance=provenance, authored_by=hi.authored_by, epistemic_state=state,
                    span=span, source_file=hi.source_file or lo.source_file,
                    confidence=hi.confidence, confidence_score=hi.confidence_score,
                    verdict_by=verdict_by, verdict_at=verdict_at, notes=(hi.notes or lo.notes))

    def _dedup_rename_edges(self, edges: "list[Edge]") -> "list[Edge]":
        """Coalesce edges that collide on ONE canonical id AFTER a rename rewrote their endpoints —
        the dedup half of kg_rename, mirroring `_rewrite_dedup_edges` (which serves kg_merge) but on
        edges whose ids were ALREADY recomputed by `_rewrite_endpoints`. Two edges can only collide on
        an id iff they share a source, and a note holds only its own source's edges, so a collision is
        always within ONE note — this dedup is per-note. Collisions coalesce via the negative-info-
        sticky, never-forging `_merge_edge_pair`, so a grounding verdict / §1.7 failure memory survives a
        rename instead of being silently dropped by the downstream `{e.id: e}` collapse (review-r8-1).

        UNLIKE kg_merge's `_rewrite_dedup_edges`, self-loops are NOT dropped: a rename that yields
        `new→new` (from a pre-rename `old→old` self-relation, or an `old→new`/`new→old` edge) is a
        legitimate distinct edge, not the merge artifact of collapsing two nodes into one."""
        survivors: "dict[str, Edge]" = {}
        for e in edges:
            prev = survivors.get(e.id)
            survivors[e.id] = e if prev is None else self._merge_edge_pair(prev, e)
        return list(survivors.values())

    def _rewrite_dedup_edges(self, edges: "list[Edge]", frm: str, into: str, report: dict):
        """Rewrite every `frm`→`into` endpoint on a node's edge list, recompute each deterministic id,
        DROP self-loops (a rewrite that collapsed source==target), and DEDUP edges that now share one
        canonical id via `_merge_edge_pair`. Two edges can only collide on an id iff they share a source
        (edge_id is a function of source), and a node file holds only its own source's edges — so a
        collision is always within ONE file, which is why this dedup is per-node. Mutates `report`'s
        counters and returns (deduped_edges, changed)."""
        survivors: dict[str, Edge] = {}
        changed = False
        for e in edges:
            rewritten = (e.source == frm) or (e.target == frm)
            if e.source == frm:
                e.source = into
            if e.target == frm:
                e.target = into
            e.id = edge_id(e.source, e.relation, e.target)
            if rewritten:
                report["edges_rewritten"] += 1
                changed = True
            if e.source == e.target:  # the rewrite collapsed an endpoint pair into a self-loop
                # Negative information is NEVER pruned (§1.7): a failed/rejected edge lying directly
                # between the two merged nodes must survive the merge as a degenerate self-loop so its
                # verdict + span stay in falsification_counters. Only a positive/unverified self-loop is
                # discarded (review: merge-selfloop-drops-negative-info). A preserved negative self-loop
                # falls through to the survivors/dedup path below (its migrating audit record is emitted
                # by kg_merge's precisely-sized `migrations` set, since its id changed).
                if e.epistemic_state not in (EpistemicState.FAILED, EpistemicState.REJECTED):
                    report["self_loops_dropped"].append(e.id)
                    changed = True
                    continue
                changed = True
            prev = survivors.get(e.id)
            if prev is None:
                survivors[e.id] = e
            else:
                survivors[e.id] = self._merge_edge_pair(prev, e)
                report["edges_deduped"].append(
                    {"id": e.id, "state": survivors[e.id].epistemic_state.value})
                changed = True
        return list(survivors.values()), changed

    def kg_merge(self, from_id: str, into_id: str, *, message: str = "kg_merge") -> dict:
        """Merge node `from_id` INTO `into_id`: rewrite every edge endpoint referencing `from_id` to
        `into_id`, dedup edges that then collide on one canonical id (negative-info-sticky, never forging
        a verdict), drop the self-loops the rewrite creates, and RETIRE `from_id`. A DELIBERATE merge —
        deliberately a distinct verb from kg_rename, which stays strict (errors on a target collision) so
        a name clash can never silently fold two concepts together. Operates on the CANON only (never the
        projection seam); the reconciler re-attaches surviving verdicts to their new ids (§1.8)."""
        frm, into = slug(from_id), slug(into_id)
        if frm == into:
            return {"ok": False, "error": "cannot merge a node into itself", "from": frm, "into": into}
        # Lease FIRST, then read everything fresh under it — same ordering as kg_rename/kg_ground
        # (the rationale lives on _try_writer_lease, F17/L5).
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR, "from": frm, "into": into}
        try:
            if not self.canon.exists(frm):
                return {"ok": False, "error": "source node not found", "from": frm, "into": into}
            if not self.canon.exists(into):
                return {"ok": False, "error": "target node not found", "from": frm, "into": into}
            try:
                from_node = self.canon.read_node(frm)   # corrupt/invalid-UTF-8 note → structured error
                into_node = self.canon.read_node(into)
            except Exception as e:  # noqa: BLE001 — surface as a structured error, not an MCP exception
                return {"ok": False, "error": self._scrub_error(f"node unreadable: {e}"),
                        "from": frm, "into": into}
            # Typing safety: keep `into`'s node_type/label, but REFUSE a merge that would silently
            # overwrite one DECLARED type with a different one — a wrong merge must not corrupt typing.
            # An undeclared-type placeholder on either side is not a conflict (it carries no commitment).
            if (from_node.node_type != into_node.node_type
                    and from_node.node_type != UNDECLARED_TYPE
                    and into_node.node_type != UNDECLARED_TYPE):
                return {"ok": False, "error": "node_type conflict — refusing to merge",
                        "from_type": from_node.node_type, "into_type": into_node.node_type,
                        "from": frm, "into": into}

            others = [n for n in self.canon.all_nodes() if n.id not in (frm, into)]
            # Snapshot every (edge_id, state) present BEFORE the rewrite. We emit a migrating audit
            # record ONLY for a surviving policed edge whose (id, state) is NEW — i.e. its verdict now
            # sits where the audit history can't justify it (the rewrite changed its id, OR a dedup
            # lifted the state at an existing id). An edge whose (id, state) is unchanged already has its
            # baseline record, so we leave no spurious spendable record behind (mirrors kg_rename's
            # precisely-sized migration set; §1.8).
            pre_states = {(e.id, e.epistemic_state.value)
                          for n in [from_node, into_node, *others] for e in n.edges}

            report = {"edges_rewritten": 0, "edges_deduped": [], "self_loops_dropped": []}
            # `into` absorbs its own edges PLUS every edge sourced at `from` (all of which rewrite onto
            # `into`); rewrite + dedup the combined list as one file.
            into_node.edges, _ = self._rewrite_dedup_edges(
                list(into_node.edges) + list(from_node.edges), frm, into, report)
            touched = [into_node]
            for n in others:
                n.edges, changed = self._rewrite_dedup_edges(n.edges, frm, into, report)
                if changed:
                    touched.append(n)

            migrations = [(e.id, e.epistemic_state.value)
                          for e in (into_node.edges + [e for n in others for e in n.edges])
                          if e.epistemic_state in GROUNDABLE_STATES
                          and (e.id, e.epistemic_state.value) not in pre_states]
            records = [(eid, EpistemicState.UNVERIFIED.value, state, "agent")
                       for eid, state in migrations]

            def _attempt():
                # merge=False: every endpoint is already rewritten + deduped, so re-merging would
                # re-introduce the pre-rewrite edges (different id → not deduped) — same posture as
                # kg_rename. The failure SIGNAL is info.rolled_back, not a caught exception.
                info = self.canon.write_nodes(touched, message=message, commit=False, merge=False)
                return (not info.rolled_back), info

            with self._critical_write():
                info = self._audit_log.audited_write(records, _attempt)
            if info.rolled_back:
                # the batch rolled back — do NOT unlink `from` (its migrating records were already
                # truncated by audited_write); the graph is left exactly as it was.
                # scrub: info.error can embed an absolute vault path (str of the write fault), and the
                # _tool_result envelope never scrubs a returned dict — mirror the sibling branch below (review-r7).
                return {"ok": False, "error": self._scrub_error(f"merge rolled back: {info.error}"),
                        "from": frm, "into": into}
            try:
                self.canon.node_path(frm).unlink(missing_ok=True)  # retire the now-empty source node
            except OSError as e:
                return {"ok": False, "from": frm, "into": into, "touched": [n.id for n in touched],
                        "error": self._scrub_error(f"merge wrote '{into}' but could not remove old '{frm}': {e}")}
            self._commit_paths(touched, frm, message)
            return {"ok": True, "from": frm, "into": into, "touched": [n.id for n in touched],
                    "edges_rewritten": report["edges_rewritten"],
                    "edges_deduped": report["edges_deduped"],
                    "self_loops_dropped": report["self_loops_dropped"],
                    "nodes": len(others) + 1,
                    "edges": sum(len(n.edges) for n in others) + len(into_node.edges)}
        finally:
            self.canon.release_lock()

    def kg_metrics(self) -> dict:
        # When the derived index is already fresh, serve counts from it with O(1) SQL instead of
        # re-parsing the whole canon (server-3). kg_metrics is not itself a projection trigger, so when
        # the index is stale we fall back to the authoritative canon parse rather than forcing a project.
        try:
            if self.projector.db_path.exists() and not self.projector.is_stale():
                con = self.projector._ro()
                try:
                    n = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                    e = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                    by_state = dict(con.execute(
                        "SELECT epistemic_state, COUNT(*) FROM edges GROUP BY epistemic_state"))
                finally:
                    con.close()
                return {"nodes": n, "edges": e, "edges_by_epistemic_state": by_state}
        except Exception as e:  # noqa: BLE001 — any index hiccup falls back to the canon parse below
            logger.debug("metrics index read failed (%s); falling back to canon parse", e)
        nodes = self.canon.all_nodes()
        edges = [e for n in nodes for e in n.edges]
        by_state = dict(Counter(e.epistemic_state.value for e in edges))  # same idiom as kg_status
        return {"nodes": len(nodes), "edges": len(edges), "edges_by_epistemic_state": by_state}

    def _coverage(self, edges) -> dict:
        """Which configured source files / `##` sections already have at least one ANCHORED (span-present)
        edge — the resume signal: a section with no covered span hasn't been extracted yet. Reads the
        source text (cheap, memoized) + the canon spans only; never the derived layer."""
        try:
            texts = self.source_set().texts  # {basename → raw_text} (a property)
        except Exception as e:  # noqa: BLE001 — a source-read hiccup degrades coverage, never crashes kg_status
            return {"files": [], "sections": [], "note": f"source unavailable ({type(e).__name__})"}
        # DEDUP the normalized spans (many edges re-cite the same span) so the scan below is bounded by
        # DISTINCT spans, then INVERT the matching: walk each span once, marking the file + every section
        # it anchors and SKIPPING anything already covered, so a covered section/file is never re-scanned
        # and the loop short-circuits once a file is fully covered. Identical result to the old per-section
        # `any(sp in body for sp in spans)` (covered iff some span is a substring), without the
        # files×sections×spans worst case.
        spans = {s for s in (normalize_text(e.span) for e in edges if e.span and e.span.strip()) if s}
        files, sections = [], []
        for fname, raw in texts.items():
            # the SAME `##` unit /kg-build extracts per subagent — the rule is single-homed in
            # sources.split_sections (review-r5), shared with the headless backend's slicer.
            secs = split_sections(raw, preamble_title="(preamble)")
            norm_bodies = [normalize_text(body) for _title, body in secs]
            covered_flags = [False] * len(secs)
            norm_file = normalize_text(raw)
            file_covered = False
            remaining = len(secs)  # sections still uncovered
            for sp in spans:
                if file_covered and remaining == 0:
                    break  # nothing left to discover in this file
                if not file_covered and sp in norm_file:
                    file_covered = True
                if remaining:
                    for i, nb in enumerate(norm_bodies):
                        if not covered_flags[i] and sp in nb:
                            covered_flags[i] = True
                            remaining -= 1
            for (title, _body), covered in zip(secs, covered_flags):
                sections.append({"file": fname, "title": title, "covered": covered})
            files.append({"file": fname, "covered": file_covered,
                          "sections": len(secs), "covered_sections": sum(covered_flags)})
        return {"files": files, "sections": sections}

    def _source_info(self) -> dict:
        """The engine-resolved source — the single source of truth for /kg-build's Step 0 (FALLO 3).

        The MCP server process receives the configured source via ``KG_SOURCE_PATH`` (from
        ``.mcp.json``'s ``${user_config.source_path}``) and dequotes/resolves it here; the model's Bash
        tool shell does NOT (the host injects userConfig options only into the server process env). So a
        command that resolved the path from a shell env var read it as EMPTY and silently fell back to
        ``examples/source.md`` — ignoring a REQUIRED, configured ``source_path``. Exposing the already-
        resolved path here lets /kg-build read it from this tool instead of the (absent) env var, and lets
        it fail loud when nothing is configured rather than building the demo corpus by surprise.

        ``path`` is the configured/resolved path string (or None when nothing is configured — the demo
        fallback only fires when it exists under the project); ``exists`` is True iff it resolves to at
        least one readable ``.md``/``.txt`` file; ``files`` is the ordered basename list (R4). It echoes
        the user's OWN declared config back to their OWN session — no canon content crosses here."""
        sp = self.source_path
        if sp is None:
            return {"path": None, "exists": False, "files": []}
        try:
            files = self.source_set().basenames
        except Exception as e:  # noqa: BLE001 — a source-read hiccup still reports the path, never crashes kg_status
            return {"path": str(sp), "exists": False, "files": [],
                    "note": f"source unreadable ({type(e).__name__})"}
        return {"path": str(sp), "exists": bool(files), "files": files}

    def kg_status(self) -> dict:
        """A cheap, projection-FREE status + coverage probe (resume a partial build after any transport
        hiccup without grepping the filesystem). Reads ONLY the canon (and the source text for coverage) —
        it never triggers or refreshes the derived layer, so it is safe and instant even mid-build while a
        projection would be expensive. Reports node/edge counts, edges by epistemic state, the
        still-`unverified` grounding-queue size, the engine-resolved `source` (path + files — /kg-build's
        source of truth, FALLO 3), and which source files/`##` sections already have an anchored edge.
        `derived_present` is a path-existence check only (no db open); `projection_degraded` echoes any
        last reprojection failure (a read, not this probe, sets it)."""
        nodes = self.canon.all_nodes()
        edges = [e for n in nodes for e in n.edges]
        by_state = dict(Counter(e.epistemic_state.value for e in edges))
        nodes_by_state = dict(Counter(n.epistemic_state.value for n in nodes))
        return {
            "ok": True,
            "version": __version__,
            "nodes": len(nodes),
            "edges": len(edges),
            "edges_by_epistemic_state": by_state,
            "nodes_by_epistemic_state": nodes_by_state,
            "unverified_edges": by_state.get(EpistemicState.UNVERIFIED.value, 0),
            "source": self._source_info(),
            # `coverage` embeds free source text: `sections[].title` is a `##` heading read VERBATIM off
            # the raw (unscrubbed) source file, so unlike every other kg_status field it can carry a
            # secret across the §1.9 egress boundary. The extractor only ever sees the kg_scrub-ed source;
            # this read must not be the hole that hands it the original. Scrub it like every sibling read
            # (get_node/kg_context/query_graph/explain_path) — `title` is in _EGRESS_TEXT_KEYS (review-r11).
            "coverage": self._scrub_egress(self._coverage(edges)),
            "derived_present": self.projector.db_path.exists(),
            "projection_degraded": self._projection_degraded,
        }

    def _failure_ids(self, G=None) -> set:
        """Forward edge ids in failure memory (rejected/failed). The generators also check the reverse,
        so forward ids suffice for invariant 5 (PLAN §13: failure memory binds generation).

        When the caller already loaded the derived graph (kg_generate/kg_operate both do, right before
        calling this), pass it in to derive the ids from the in-memory edges instead of re-parsing the
        whole canon (server-6). The index keeps failure memory (§1.7 never prunes it), so the set is
        identical; EpistemicState subclasses str, so the string compare matches."""
        if G is not None:
            fail = {s.value for s in FAILURE_STATES}
            return {d.get("id") for _, _, d in G.edges(data=True) if d.get("epistemic_state") in fail}
        return {e.id for e in self.canon.all_edges() if e.epistemic_state in FAILURE_STATES}

    def kg_generate(self, mechanism: str = "bridge", k: int = 10, second_graph: str | None = None,
                    dpp: bool | None = None, second_construction: str | None = None) -> dict:
        """Generate hypothesized candidates from the derived graph (PLAN Stage 3 — the generative
        engine). Projects if stale, reads precomputed ranks O(1), dispatches to the chosen mechanism(s)
        (`bridge|seed|compression|regroup|transplant|ensemble`, or `all`/`default`), and returns ranked
        candidates. **READ-ONLY** — it never writes the canon; `/kg-generate` routes the candidates
        through the propose lane (`kg_propose`). Generate offensively; grounding judges later.

        FUSION Stage 5: when `dpp` is true (default: the pack's `divergence.dpp` flag, shipped OFF),
        the SAME candidate set is reordered by hybrid-descriptor DPP (one semantic axis + graph-
        structural axes, judge-bounded quality) and a `divergence_advisory` block labels the slate.
        Purely advisory (I5): never adds/drops/mutates a candidate; grounding output is snapshot-
        proven bit-identical flag on vs off; any advisory failure keeps the donor ordering (I9)."""
        from .generate import run_generators
        self._ensure_projected()
        G = self.projector.load_graph()
        corpus = self.projector._corpus()
        failures = self._failure_ids(G)
        gate_on = int(next((G.nodes[n].get("gate_on", 0) for n in G.nodes()), 0) or 0)  # `or 0`: tolerate gate_on=None
        G2, note = None, ""
        # §9/§15: a NAMED in-session second construction — project its alternate canon to a graph.json
        # and cross against it. Key-free (the session's kg-extractor built it via kg_write(construction=…)).
        # An explicit `second_graph` PATH (the pre-built escape hatch, §11) takes precedence.
        if second_construction and not second_graph:
            try:
                second_graph = str(self._project_construction(second_construction))
            except Exception as e:  # noqa: BLE001 — an unbuilt/failed construction degrades to regroup, never crashes
                # Scrubbed for the same §1.9 reason as the load failure below (the message can name a path).
                note = (f"second_construction could not be built ({self._scrub_error(e)}); "
                        "ensemble degraded to regroup")
        if second_graph and not note:
            try:
                G2 = self._second_graph(second_graph)
            except Exception as e:  # noqa: BLE001 — a bad second graph degrades, never crashes
                # Scrub the exception: it can carry the caller-supplied `second_graph` path, and `note`
                # is an _EGRESS_TEXT_KEYS field whose _scrub_egress pass does secrets/PII only, NOT path
                # redaction — so route it through _scrub_error to strip an absolute path (§1.9).
                note = f"second_graph could not be loaded ({self._scrub_error(e)}); ensemble degraded to regroup"
        if not note and G2 is None and mechanism in ("ensemble", "all"):
            note = "no second construction supplied; ensemble degraded to regroup (run /kg-perturb to supply one)"
        cands = run_generators(G, mechanism, pack=self.pack, corpus=corpus, failures=failures,
                               k=k, second_graph=G2)
        payload = {"mechanism": mechanism, "k": int(k), "gate_on": gate_on,
                   "count": len(cands), "candidates": [c.to_dict() for c in cands],
                   "note": note}
        use_dpp = dpp
        if use_dpp is None:
            from .advisory_geometry import pack_dpp_default
            use_dpp = pack_dpp_default(self.pack)
        if use_dpp and len(payload["candidates"]) > 1:
            try:
                from .advisory_geometry import order_candidates
                ordered, advisory = order_candidates(payload["candidates"], G)
                payload["candidates"] = ordered
                payload["divergence_advisory"] = advisory
            except Exception as e:  # noqa: BLE001 — the advisory layer must never break generation (I9)
                # Scrub: the embedder-load failure can carry a HuggingFace cache path (~/.cache/...), and
                # `note` is egress'd through _scrub_egress which does secrets/PII only, NOT path redaction
                # (§1.9) — so route it through _scrub_error like the sibling notes above (review-fix).
                payload["note"] = ((payload["note"] + "; ") if payload["note"] else "") + \
                    f"divergence.dpp advisory ordering unavailable ({self._scrub_error(e)}); donor ordering kept"
        # Echo projection_degraded like the sibling reads so a caller can tell "no candidates because the
        # graph is genuinely empty" from "no candidates because projection failed/was contended"
        # (review: generative-reads-omit-degraded-flag). Scrubbed like the sibling reads: candidate
        # `label`/`rationale` strings embed canon labels (§1.9, review-r4: egress-label-gap).
        return self._with_degraded(self._scrub_egress(payload))

    def _second_graph(self, path: str):
        """Load a SECOND construction's graph.json into a NetworkX graph (raises on failure)."""
        from .generate import load_second_graph
        return load_second_graph(path)

    def _project_construction(self, construction: str) -> Path:
        """Project a NAMED second construction's alternate canon to its own `derived/graph.json` and
        return that path — the in-session, key-free `second_graph` source for `kg_generate(ensemble)`
        (§9/§15). The construction must have been BUILT first via `kg_write(..., construction=<name>)`;
        an absent or empty construction raises (kg_generate catches it and degrades to `regroup`, so a
        typo or a not-yet-built name never silently cross-generates against an empty graph)."""
        root = self._construction_root(construction)
        if not root.exists():
            raise FileNotFoundError(
                f"construction {construction!r} does not exist — build it first with "
                f"kg_write(..., construction={construction!r})")
        eng = self._construction_engine(construction)
        if not eng.canon.note_paths():
            raise ValueError(
                f"construction {construction!r} is empty — build it first with "
                f"kg_write(..., construction={construction!r})")
        eng._ensure_projected()
        # _ensure_projected never raises — a failed/contended projection sets _projection_degraded and
        # leaves an EMPTY graph.json behind (_ensure_degraded_db). Surface that here so kg_generate
        # degrades to `regroup` with a note, instead of silently cross-generating against an empty second
        # graph the caller can't distinguish from a real one (review-fix: L2/server-4).
        if eng._projection_degraded:
            raise RuntimeError(
                f"construction {construction!r} failed to project ({eng._projection_degraded})")
        path = eng.projector.graph_path
        if not path.exists():
            raise FileNotFoundError(f"construction {construction!r} failed to project a graph.json")
        return path

    def kg_ensemble_graph(self, path: str) -> dict:
        """Load and summarise a SECOND construction's graph.json (PLAN Stage 7 — the §9/§15 ensemble /
        perturb path). Confirms a second construction projected before cross-generating against it via
        kg_generate(mechanism="ensemble", second_graph=<path>). Returns {ok, nodes, edges, path} or
        {ok: False, error}."""
        try:
            G2 = self._second_graph(path)
        except Exception as e:  # noqa: BLE001 — a missing/bad second graph is a structured error
            return {"ok": False, "error": str(e), "path": path}
        return {"ok": True, "path": path, "nodes": G2.number_of_nodes(), "edges": G2.number_of_edges()}

    def kg_absorption(self) -> dict:
        """Score the absorption window of grounded-from-hypothesized nodes (§14, PLAN Stage 5): how long
        each stayed perturbing before the graph renormalised. Reads the current derived graph plus the
        generation timeline at `derived/generations.json` — a `{generation: int, tracked: {id:
        {introduced_at, introduced_degree, mechanism}}}` ledger the /kg-generate command appends to.
        Returns per-node {half_life, status ∈ fertile|absorbed|isolated} so the slate can prefer the
        fertile middle. With no ledger yet, returns an empty result with a note (never an error)."""
        from .harness import absorption
        self._ensure_projected()
        try:
            data = json.loads(self.projector.graph_path.read_text(encoding="utf-8")) \
                if self.projector.graph_path.exists() else {"nodes": [], "links": []}
        except (ValueError, OSError):
            data = {"nodes": [], "links": []}
        hist_path = self.projector.derived / "generations.json"
        history, now = {}, None
        if hist_path.exists():
            try:
                blob = json.loads(hist_path.read_text(encoding="utf-8"))
                if isinstance(blob, dict):
                    history = blob.get("tracked", {}) if "tracked" in blob else blob
                    now = blob.get("generation")
            except (ValueError, OSError):
                history = {}
        result = absorption(data, history, now=now)
        summary = {s: sum(1 for v in result.values() if v["status"] == s)
                   for s in ("fertile", "absorbed", "isolated")}
        return self._with_degraded({"tracked": len(result), "summary": summary, "nodes": result,
                "note": ("" if history else
                         "no generations.json yet — run /kg-generate to start tracking the absorption window")})

    def kg_operate(self, op: str, *, target: str | None = None, label: str = "", body: str = "",
                   members=None, k: int | None = None) -> dict:
        """Run one of the four endo operations (§8, PLAN Stage 4), persisting the result through the
        propose lane. collapse → compression node + collapses_into edges; explode → latent facet
        children; regroup → §8 re-partition bridges; open → a new primitive + attachment points. The
        write goes through kg_propose, so it lands hypothesized/unverified with no span — never a
        verdict, never a forged text anchor."""
        from . import operations as ops
        op = (op or "").lower()
        fn = ops.DISPATCH.get(op)
        if fn is None:
            return {"ok": False, "error": f"unknown op {op!r}; expected collapse|explode|regroup|open"}
        self._ensure_projected()
        G = self.projector.load_graph()
        if op == "collapse":
            payload, info = fn(G, target=target, members=members, label=label, body=body)
        elif op == "explode":
            payload, info = fn(G, target=target, k=k, label=label, body=body)
        elif op == "regroup":
            payload, info = fn(G, failures=self._failure_ids(G), k=k or ops.DEFAULT_REGROUP_K)
        else:  # open
            payload, info = fn(G, label=label, body=body, k=k or ops.DEFAULT_OPEN_POINTS)
        if not payload or not (payload.get("nodes") or payload.get("edges")):
            return {"ok": False, "op": op, "error": "no structure to operate on", "info": info}
        result = self.kg_propose(payload, message=f"kg_operate:{op}")
        result.update({"ok": True, "op": op, "info": info})
        return result

    # ---- read surface (projects if stale, then reads precomputed ranks)
    def _ensure_projected(self) -> None:
        """Project-if-stale on the read path — and NEVER raise. A projection failure (a sqlite hiccup, a
        native-dep blowup in community detection, a corrupt derived db) must DEGRADE a read, not crash the
        tool: log it, remember the reason in `_projection_degraded`, and make sure an empty-schema'd
        derived layer exists so the read tools return canon-empty data with the degraded flag instead of
        blowing up on a missing table. Writes never come through here — kg_write/kg_propose/kg_ground/
        kg_rename touch only the canon — so projection can never block or fail a write (defense #6)."""
        try:
            report = None
            if not self.projector.db_path.exists() or self.projector.is_stale():
                report = self.projector.project()
            # A cold-start reproject that could NOT take the canon lease (another process holds it) bails
            # out having synthesized an EMPTY/stale derived layer and returns contended=True. Surface that
            # as a degraded read so an empty result is not mistaken for a genuinely empty graph — it
            # self-heals on the next uncontended read (review: contended-projection-looks-empty).
            if report is not None and getattr(report, "contended", False):
                self._projection_degraded = ("projection contended: another process holds the canon lease; "
                                             "serving an empty/stale derived layer (refreshes on next read)")
            else:
                self._projection_degraded = None
        except Exception as e:  # noqa: BLE001 — a projection failure degrades the read, never crashes it
            # Scrub the reason before it is stored: _with_degraded splices this string into ~10 read
            # tools' return dicts, and a projection error frequently carries an absolute vault/data path
            # (e.g. sqlite `unable to open database file: …/derived/index.sqlite`). Route it through the
            # same §1.9 egress path-redaction the tool-envelope uses so it can't leak across the boundary
            # (review: _projection_degraded path leak — the class review-r7 fixed for info.error).
            self._projection_degraded = f"{type(e).__name__}: {self._scrub_error(e)}"
            logger.warning("projection failed (%s); serving degraded derived layer", e, exc_info=True)
            self._ensure_degraded_db()

    def _ensure_degraded_db(self) -> None:
        """Best-effort: guarantee a schema'd (possibly empty/stale) derived layer exists so a read after a
        projection failure returns data instead of crashing on a missing table. Mirrors the projector's
        cold-contended path (an idempotent CREATE TABLE IF NOT EXISTS + an empty graph.json)."""
        try:
            import networkx as nx
            # import from the owning leaves directly (review-r5: these used to be re-imported
            # THROUGH the projector, hiding where they live)
            from .atomicio import atomic_write_text
            from .graphio import node_link_data
            if not self.projector.db_path.exists() or self.projector._schema_outdated():
                self.projector._connect().close()
            if not self.projector.graph_path.exists():
                atomic_write_text(self.projector.graph_path, json.dumps(node_link_data(nx.MultiDiGraph())))
        except Exception as e:  # noqa: BLE001 — purely defensive; a read that still can't project errors via _tool_result
            logger.debug("could not materialise a degraded derived layer (%s)", e)

    def _with_degraded(self, result):
        """Annotate a dict read result with the projection-degraded reason, when set, so a caller can tell
        "the derived layer is stale/unavailable" apart from a genuinely empty graph. Non-dict results
        (lists, None) pass through untouched."""
        if isinstance(result, dict) and self._projection_degraded:
            result = {**result, "projection_degraded": self._projection_degraded}
        return result

    # Free-text fields of a read result that may quote canon/source content (a verbatim edge span, a
    # verdict note, a node body). kg_write deliberately stores the ORIGINAL (un-scrubbed) span in the
    # canon (§1.9 restore protects the egress, not the local canon), so a secret that was scrubbed BEFORE
    # extraction lives in the canon span — and must be re-scrubbed on the READ path before it crosses back
    # to the model. Structural fields (ids/relation/type/axes) are deliberately excluded so referential
    # integrity is preserved (review: reads-return-canon-spans-unscrubbed).
    # `label` is included: it is extracted free text like the body, and identity lives in the slug id
    # (which stays untouched), so scrubbing it costs no referential integrity. `question` (kg_agenda)
    # and `rationale` (kg_generate candidates) are derived FROM labels, so they must be covered too or
    # the same secret round-trips through a differently-named field (review-r4: egress-label-gap).
    # `title` is kg_status's coverage section heading — raw source text, hence scrubbable free text
    # like the rest of these (review-r11).
    _EGRESS_TEXT_KEYS = frozenset({"span", "notes", "note", "body", "support_note",
                                   "label", "question", "rationale", "title"})

    def _scrub_egress(self, obj):
        """Re-run the §1.9 egress scrub over the free-text fields of a read result before it returns to
        the session, so a secret restored into a canon span can't round-trip to the model on a read. Uses
        a THROWAWAY Scrubber at the engine's configured sensitivity (never pollutes the session's
        write-restore map `_scrub_map`); a no-op on ordinary conceptual text (nothing matches). Recurses
        through nested dicts/lists (items[]/hypotheses[]/edges[]/…)."""
        scrubber = Scrubber(self.sensitivity)

        def _walk(x):
            if isinstance(x, dict):
                return {k: (scrubber.scrub(v)[0]
                            if (k in self._EGRESS_TEXT_KEYS and isinstance(v, str) and v)
                            else _walk(v))
                        for k, v in x.items()}
            if isinstance(x, list):
                return [_walk(v) for v in x]
            return x

        return _walk(obj)

    @property
    def projection_degraded(self) -> "str | None":
        """The last reprojection-failure reason (None when projection is healthy) — the public form
        of `_projection_degraded`, so the MCP wrappers that surface the flag never reach into a
        private attribute of the facade (review-r5)."""
        return self._projection_degraded

    @property
    def _proj(self) -> Projector:
        """The lazy-projection read seam: ensure the derived layer is fresh, then return the projector.
        The single edit point for the projection trigger every pure read delegate goes through."""
        self._ensure_projected()
        return self.projector

    def get_node(self, node_id: str) -> dict | None:
        res = self._proj.get_node(node_id)
        # On a degraded (empty/stale) derived layer a real canon node looks like a genuine miss; surface
        # the flag on the miss too so a caller can tell "not found" from "couldn't project" (review-M2).
        if res is None and self._projection_degraded:
            return {**_NOT_FOUND, "projection_degraded": self._projection_degraded}
        return self._with_degraded(self._scrub_egress(res))

    def get_neighbors(self, node_id: str, relation: str | None = None) -> list:
        # Returns a LIST, which can't carry the projection_degraded flag without changing the tool's
        # shape; the degraded state is observable via the sibling reads (get_node/kg_context/query_graph/
        # kg_status) that DO carry it. _ensure_projected (via _proj) still degrades-not-raises here.
        return self._scrub_egress(self._proj.get_neighbors(node_id, relation=relation))

    def shortest_path(self, source: str, target: str):
        return self._scrub_egress(self._proj.shortest_path(source, target))

    def explain_path(self, nodes: list[str]) -> dict:
        """Trace the associative chain connecting `nodes` over GROUNDED edges only (read-only
        egress, §2). The algorithm — the grounded-only view, deterministic BFS, and the
        nearest-neighbour walk — lives in the pure `pathing` module (review-r5: it was the one
        large inline algorithm in this facade); this method wires the derived graph in and applies
        the facade's egress policy: re-scrub the grounded spans (a secret restored into a canon
        span must not round-trip to the model — review: reads-return-canon-spans-unscrubbed) and
        mirror shortest_path's `projection_degraded` surfacing so an empty result is never
        confused with a degraded projection."""
        from .pathing import explain_grounded_path
        result = explain_grounded_path(self._proj.load_graph(), nodes)
        return self._with_degraded(self._scrub_egress(result))

    def query_graph(self, **kw) -> dict:
        return self._with_degraded(self._scrub_egress(self._proj.query_graph(**kw)))

    def kg_context(self, query: str | None = None, budget: int = 2000) -> dict:
        return self._with_degraded(self._scrub_egress(self._proj.kg_context(query, budget=budget)))

    def kg_agenda(self, *, limit: int = 5) -> dict:
        # scrubbed like the sibling reads: the agenda's question strings embed canon labels (§1.9)
        return self._with_degraded(self._scrub_egress(self._proj.kg_agenda(limit=limit)))

    def kg_export(self, kind: str = "all") -> dict:
        """Render the human-facing artifacts (R1): a self-contained `graph.html` + `GRAPH_REPORT.md` under
        the derived dir. Read-only — projects-if-stale, then consumes only the derived layer; never writes
        the canon and never `_atomic_write`s graph.json/index.sqlite."""
        self._ensure_projected()
        from . import export as _export
        # DELIBERATE, justified path egress (like `_source_info`'s echo of the user's own config): the
        # returned `html_path`/`report_path` are absolute so /kg-view can tell the user WHERE to open the
        # self-contained graph.html — the artifact is unusable without its path, and it lives under the
        # user's own CLAUDE_PLUGIN_DATA. So this is intentionally NOT run through _scrub_error's
        # path-redaction (contrast _projection_degraded / kg_generate notes, which are error text a user
        # never needs). Kept explicit so it isn't mistaken for the §1.9 leak class.
        return self._with_degraded(_export.export(self, kind=kind))

    # ---- divergence surface (FUSION Stages 3-4) --------------------------
    # These live on the facade like every other tool (the module docstring's "the FastMCP wrappers
    # are thin" contract — review-r5: materialize + the fate sync were ~150 lines of real logic in
    # closures inside _register, reachable only by scraping the registered tool table). kg_engine.
    # divergence is imported LAZILY inside each body so this module's import graph stays
    # divergence-free (I3, firewall-tested).

    def _diverge_home(self) -> Path:
        # The USER project, never the plugin data dir: divergence session state is
        # git-friendly project state, like canon — not a cache. The resolution rule
        # (KG_DIVERGE_HOME override first) is single-homed in state.base_dir (review-r5:
        # a hardcoded project path here split a KG_DIVERGE_HOME user's pins/discards
        # between the CLI and these MCP tools, I8).
        from kg_engine.divergence.state import base_dir
        return base_dir(self.project_dir)

    def _sync_materialized_fates(self, project: str) -> list:
        """Unified negative memory (FUSION Stage 4, I8): grounding FALSIFICATIONS flow BACK
        into the brief's discard store. For every materialized pin, read the CURRENT
        epistemic state of its graph items from canon (reads only — verdicts remain
        kg_ground's monopoly); any candidate whose node/edge was actively FALSIFIED
        (`failed`, i.e. in MATERIALIZED_DISCARD_STATES) is added to this brief's discards,
        so no future slate or parent pool ever re-proposes it. Idempotent; fates are
        stamped in materialized.json.

        A merely UNSUPPORTED pin (`rejected` — no verbatim span in the current source) is
        the expected state of a genuinely novel idea awaiting sources, NOT a failure, so it
        is left recoverable and never auto-discarded (that is why the check is against the
        narrow MATERIALIZED_DISCARD_STATES, not the global FAILURE_STATES). Verdict neutrality
        is preserved: the verdict a pin receives is unchanged and identical to a non-pin's —
        only this state-keyed discard consequence was narrowed. Accepted trade-off: a diverge
        pin rejected specifically for being vague/unfalsifiable (the generality confound, §1.6)
        also no longer auto-discards, so a similar idea may reappear in a later slate; the user
        remains the real selector and can discard it in one tap, and burying good novel ideas is
        the primary risk this guards against. (This sync is diverge-brief-scoped and does NOT
        touch /kg-generate negative memory — the write-boundary durability quarantine — which
        still rejects unsupported hypothesized edges into FAILURE_STATES exactly as before.)"""
        from kg_engine.divergence.session import Session as _DSession

        sess = _DSession(project, home=self._diverge_home())
        state = sess.state
        ledger = state.read_materialized()
        if not ledger:
            return []
        try:
            domain = sess.domain
        except Exception:  # no axes snapshot yet — nothing to sync into
            return []
        # The source the fates in this sync are judged against — stamped on each newly-folded entry so a
        # LATER source change can surface it as re-examinable on the brief side (Stage 5, the divergence
        # mirror of the graph R3-mirror). Computed once, off the per-entry loop.
        current_source_sig = self._source_signature()
        newly_discarded: list = []
        changed = False
        for cid, entry in ledger.items():
            if cid in ("_edges", "_source_sig") or not isinstance(entry, dict):
                continue  # reserved ledger keys, OR a non-dict value from a corrupt/older ledger — skip
                          # it rather than AttributeError on entry.get() and fail the whole call (the
                          # read-only siblings _reexaminable_discards/_unseal_discards already guard this).
            if entry.get("fate") in FAILURE_STATE_VALUES:
                # Already folded. A pre-Stage-5 entry has a `fate` but no `fate_source_sig`; stamp the
                # CURRENT source as its baseline ONCE so a LATER source change can surface it as
                # re-examinable — otherwise it stays PERMANENTLY non-re-examinable (review-r8-14).
                # Mirrors the graph cold-start rule (establish a baseline now, diff against it later): the
                # sig equals `current` right after backfill, so this never causes a false surface.
                if (entry.get("fate") == EpistemicState.FAILED.value
                        and "fate_source_sig" not in entry and current_source_sig):
                    entry["fate_source_sig"] = current_source_sig
                    changed = True
                continue  # already folded into discards
            # An entry the user EXPLICITLY un-sealed against the CURRENT source stays out of discards
            # until the source changes again (or they re-ground the still-`failed` graph item) — otherwise
            # this very sync would re-fold it and silently undo the un-seal (Stage 5). A source change
            # moves the signature, lifting the guard, so a still-falsified pin re-folds (and re-surfaces
            # as re-examinable) exactly as before. Read-only otherwise; never touches a verdict.
            if entry.get("unsealed_source_sig") and entry.get("unsealed_source_sig") == current_source_sig:
                continue
            failed_state = None
            # Both loops below tolerate ANY read fault on a referenced note, not just FileNotFoundError
            # (§1.2, and the posture of every other read_node call site: _owner_of_edge, kg_ground,
            # kg_rename, kg_merge, _refresh_baseline, projector._full_note_for_terms all catch broadly).
            # A note that is malformed rather than MISSING — a hand-edit that broke the frontmatter, a
            # BOM, a CR-only file — raises ValueError from node_from_markdown, and a ledger id that is
            # not a clean slug raises ValueError from node_path. Narrowing to FileNotFoundError let one
            # such note escape through _tool_result and turn the WHOLE kg_diverge_recall /
            # kg_diverge_metrics call into {ok: False}, instead of skipping that one entry. An unreadable
            # note simply yields no fate this sync; the next one retries it (review-r12).
            for node_id in entry.get("nodes", ()):
                try:
                    node = self.canon.read_node(node_id)
                except Exception:  # noqa: BLE001 — one bad note must not fail the whole fate sync
                    continue
                if node and node.epistemic_state in MATERIALIZED_DISCARD_STATES:
                    failed_state = node.epistemic_state.value
            for ref in entry.get("edges", ()):
                owner, ref_edge_id = ref.get("owner"), ref.get("id")
                try:
                    node = self.canon.read_node(owner) if owner else None
                except Exception:  # noqa: BLE001 — one bad note must not fail the whole fate sync
                    continue
                for e in (node.edges if node else ()):
                    if e.id == ref_edge_id and e.epistemic_state in MATERIALIZED_DISCARD_STATES:
                        failed_state = e.epistemic_state.value
            if failed_state:
                state.add_discard(domain, cid)
                entry["fate"] = failed_state
                # Record the source this failure was fated against (Stage 5). Kept ON THE LEDGER ENTRY
                # only — the returned `newly_discarded` record shape is UNCHANGED ({candidate, fate}), so
                # existing callers/tests that dict-compare it stay green.
                entry["fate_source_sig"] = current_source_sig
                newly_discarded.append({"candidate": cid, "fate": failed_state})
                changed = True
        if changed:
            state.write_materialized(ledger)
        return newly_discarded

    def _reexaminable_discards(self, project: str) -> list:
        """The divergence mirror of the graph R3-mirror advisory (Stage 5): materialized-pin failures
        (`fate == "failed"`) that were fated against a source set which has since CHANGED, so the brief's
        permanent negative memory (I8) deserves a re-look. SURFACE-ONLY — it removes nothing and clears
        no fate (that is the explicit un-seal lever); the discard stays sealed until the user un-seals it.
        Empty when no source is configured. An entry fated before this feature (no `fate_source_sig`) is
        not surfaced on the FIRST post-upgrade sync — there is no baseline source to diff against — but
        `_sync_materialized_fates` then backfills its baseline to the current source, so a subsequent
        source change surfaces it normally (a one-projection lag, not a false burst)."""
        from kg_engine.divergence.session import Session as _DSession

        sess = _DSession(project, home=self._diverge_home())
        ledger = sess.state.read_materialized()
        if not ledger:
            return []
        current = self._source_signature()
        if not current:
            return []  # no source configured → nothing to re-examine (mirror the graph advisory)
        out: list = []
        for cid, entry in ledger.items():
            if cid in ("_edges", "_source_sig") or not isinstance(entry, dict):
                continue
            if (entry.get("fate") == EpistemicState.FAILED.value
                    and "fate_source_sig" in entry
                    and entry.get("fate_source_sig") != current):
                out.append({"candidate": cid, "fate": entry["fate"],
                            "reason": "source-set-changed-since-judged"})
        return out

    def _unseal_discards(self, project: str, candidate_ids: list) -> list:
        """The EXPLICIT un-seal lever (Stage 5): for each named candidate THAT IS CURRENTLY
        RE-EXAMINABLE (a materialized `fate == "failed"` pin whose source set has changed since it was
        fated — exactly the set `_reexaminable_discards` surfaces), drop it from the brief's discards
        (return it to the proposal pool) and clear its `fate` in materialized.json so it can be
        re-materialized / re-grounded against the new source. Records `unsealed_source_sig` so the next
        fate-sync does NOT immediately re-fold the still-`failed` graph item (see _sync_materialized_fates).
        NEVER auto-invoked and NEVER touches a graph verdict.

        A requested cid that is NOT currently re-examinable — a genuine user discard, an unknown id, or a
        failed pin whose source has not changed — is IGNORED, never revived: the brief's permanent negative
        memory (I8) stays sealed outside the surfaced set, and the return list is the candidates ACTUALLY
        un-sealed, not merely the ones requested (review-r8-6)."""
        from kg_engine.divergence.session import Session as _DSession

        # coerce a bare string so reexamine="c1" un-seals "c1", not the chars "c"+"1" (review-r8-11)
        if isinstance(candidate_ids, str):
            candidate_ids = [candidate_ids]
        requested = {str(c) for c in (candidate_ids or [])}
        # gate on the advisory's current re-examinable set — the lever's ONLY licensed inputs.
        allowed = {d["candidate"] for d in self._reexaminable_discards(project)}
        targets = requested & allowed
        if not targets:
            return []
        sess = _DSession(project, home=self._diverge_home())
        state = sess.state
        try:
            domain = sess.domain
        except Exception:  # no axes snapshot yet — no discard namespace to un-seal from
            return []
        current_source_sig = self._source_signature()
        ledger = state.read_materialized()
        unsealed: list = []
        changed = False
        for cid in sorted(targets):
            state.remove_discard(domain, cid)  # return to the proposal pool (locked read-modify-write)
            entry = ledger.get(cid) if isinstance(ledger, dict) else None
            if isinstance(entry, dict):
                entry.pop("fate", None)          # clear the failure fate — re-open for re-grounding
                entry.pop("fate_source_sig", None)
                entry["unsealed_source_sig"] = current_source_sig
                changed = True
            unsealed.append(cid)
        if changed:
            state.write_materialized(ledger)
        return unsealed

    def kg_diverge_materialize(self, project: str, candidate_ids=None,
                               node_type: str = "claim", edges=None) -> dict:
        """Materialize PINNED ideas into the graph — the EXPLICIT action (nothing enters the
        graph implicitly; kickoff Q5). Each pinned candidate becomes a node in the hypothesized
        lane via the propose door (kg_propose -> kg_write -> boundary): it lands
        `provenance=hypothesized, epistemic_state=unverified`, carrying its full lineage in the
        node body. `candidate_ids` defaults to every pin with a live session record; a pin from
        an ENDED session has no record left (I10) and is reported as skipped. Optional `edges`
        transit the SAME boundary (claimed verdicts stripped, text-claim provenance refused)."""
        from kg_engine.divergence.session import Session as _DSession

        sess = _DSession(project, home=self._diverge_home())
        state = sess.state
        domain = sess.domain
        spec = sess.spec
        open_axis = spec.primary_axis
        session_id = state.read_session().get("session_id", "")
        pins = state.read_pins(domain)
        cand_store = state.read_candidates()

        wanted = [str(c) for c in candidate_ids] if candidate_ids is not None else list(pins)
        results: list[dict] = []
        nodes_payload: list[dict] = []
        node_for_cid: dict[str, str] = {}
        for cid in wanted:
            if cid not in pins:
                results.append({"candidate": cid, "status": "refused",
                                "reason": "not-pinned: materialization is an explicit "
                                          "action on PINNED ideas only"})
                continue
            rec = cand_store.get(cid)
            if not rec or not rec.get("text"):
                results.append({"candidate": cid, "status": "skipped",
                                "reason": "no-session-record: geometry state is session-"
                                          "ephemeral (I10) — re-ingest this idea in the "
                                          "current session, then materialize"})
                continue
            text = str(rec["text"]).strip()
            descriptor = rec.get("descriptor") or {}
            mechanism = str(descriptor.get(open_axis.name, "")) if open_axis else ""
            operator = str((rec.get("genealogy") or {}).get("operator_id", ""))
            node_id = f"idea-{slug(project)}-{slug(cid)}"
            label = text if len(text) <= 80 else text[:77] + "..."
            lineage = (f"[diverge] pinned candidate={cid} brief={project} "
                       f"session={session_id} mechanism={mechanism!r} operator={operator}")
            nodes_payload.append({"id": node_id, "label": label, "node_type": node_type,
                                  "body": f"{text}\n\n{lineage}\n"})
            node_for_cid[cid] = node_id

        edges_payload: list[dict] = []
        for e in (edges or []):
            e = dict(e or {})
            # candidate_id is OUR routing key (ledger mapping), not a boundary field —
            # the boundary's extra="forbid" would rightly reject it as schema-invalid.
            e.pop("candidate_id", None)
            marker = (f"[diverge] pinned brief={project} session={session_id}")
            e["notes"] = f"{e.get('notes', '')} {marker}".strip()
            edges_payload.append(e)

        if not nodes_payload and not edges_payload:
            return {"ok": True, "materialized": 0, "results": results}

        out = self.kg_propose({"nodes": nodes_payload, "edges": edges_payload},
                              message="kg_diverge_materialize")

        by_id = {d.get("id"): d for d in out.get("details", [])}
        ledger = state.read_materialized()
        for cid, node_id in node_for_cid.items():
            detail = by_id.get(node_id, {})
            status = detail.get("disposition", "UNKNOWN")
            results.append({"candidate": cid, "status": status, "node": node_id,
                            "reason": detail.get("reason", "")})
            if status in PERSISTED_DISPOSITIONS:
                entry = ledger.setdefault(cid, {"nodes": [], "edges": []})
                if node_id not in entry["nodes"]:
                    entry["nodes"].append(node_id)
                entry["session"] = session_id
        for e, raw in zip(edges_payload, edges or []):
            eid = edge_id(e.get("source", ""), e.get("relation", ""), e.get("target", ""))
            detail = by_id.get(eid, {})
            if detail.get("disposition") in PERSISTED_DISPOSITIONS:
                cid = str((raw or {}).get("candidate_id", "")) or "_edges"
                entry = ledger.setdefault(cid, {"nodes": [], "edges": []})
                ref = {"id": eid, "owner": e.get("source", "")}
                if ref not in entry["edges"]:
                    entry["edges"].append(ref)
                entry["session"] = session_id
        state.write_materialized(ledger)

        materialized_count = sum(1 for r in results if r.get("status") in PERSISTED_DISPOSITIONS)
        result = {"ok": bool(any(out.get("dispositions", {}).get(d, 0) for d in PERSISTED_DISPOSITIONS)),
                  "materialized": materialized_count,
                  "results": results, "propose": out}
        # Advisory only (never a disposition, a return-field change, or a ledger write): if a source is
        # already configured, remind the operator that grounding these hypothesized pins against THAT source
        # will (correctly) leave a genuinely novel idea `unverified` — a novel idea has no in-source span by
        # construction — until supporting sources are gathered. The intended path is to add sources for the
        # pins worth promoting, not to read the leftover `unverified` state as a failure. (Part C.)
        if self.source_path is not None and materialized_count:
            result["advisory"] = (
                "A source is already configured. Grounding these pins against it will correctly leave a "
                "genuinely novel idea `unverified` (novelty has no in-source span yet) — it is NOT falsified "
                "and stays recoverable in the lane. To promote a pin, gather supporting sources for it, then "
                "ground; only an actively-falsified pin folds back into this brief's discards.")
        return result


# --------------------------------------------------------------------------- MCP wiring


def build_engine_from_env(*, project=None, data=None, source=None, pack=None) -> KGEngine:
    """Construct a KGEngine from environment config, with optional explicit overrides (CLI flags win
    over env). The resolution RULES — the `${user_config.*}` placeholder filter (an unsubstituted
    literal reads as unset, so the documented `examples/source.md` fallback still fires; review-r4:
    opt-skips-placeholder-filter), the source/pack precedence and project-relative defaults — are
    single-homed in ``envconfig`` (review-r5), shared with the PreToolUse hook and the lightrag arm,
    so the hook can never again resolve a DIFFERENT source/pack/metrics than the server. This
    function keeps only what is server-specific: the explicit-override layering and the flood rate
    limit; every caller (MCP server, headless backend) gets identical behavior."""
    project = project or envconfig.resolve_project(os.getcwd())
    data = data or _clean_env("KG_DATA")  # None → KGEngine defaults to <project>/DATA_DIRNAME
    src = envconfig.resolve_source(project, explicit=source)
    pack_path = envconfig.resolve_pack_path(project, explicit=pack)
    try:
        rate = float(os.environ["KG_MAX_EDGES_PER_KB"])
        if not math.isfinite(rate) or rate < 0:  # 'nan'/'inf'/negative would crash or disable the limiter
            rate = DEFAULT_MAX_EDGES_PER_KB
    except (KeyError, ValueError):
        rate = DEFAULT_MAX_EDGES_PER_KB
    return KGEngine(project, data, source_path=src, pack_path=pack_path,
                    sensitivity=envconfig.plugin_option("SENSITIVITY", "medium"),
                    metrics_mode=envconfig.plugin_option("METRICS_MODE", "structure_only"),
                    max_edges_per_kb=rate)


def _tool_result(fn):
    """Uniform transport-error envelope for every MCP tool (finding: mixed-error-architecture). A RAISED
    exception (e.g. a mid-read sqlite/networkx error escaping a pure-read tool, or a BrokenPipeError /
    EOFError / ConnectionResetError on the stdio transport — all `Exception` subclasses) becomes a
    structured {ok:False, error, error_kind} result + a logged traceback, instead of bubbling into the
    transport serve loop and killing the process. The next request is served normally. SUCCESS returns
    pass through UNCHANGED — including the deliberate {ok:False} DOMAIN dispositions (a locked vault, a
    refused verdict) and the reads' own shapes ({path:...}, {error:"not found"}, lists, None): transport
    ok/error and domain disposition are two ORTHOGONAL axes, so the envelope never collapses a domain
    result into a transport error (the never-stall contract, §2.4/§4).

    It deliberately catches `Exception`, NOT `BaseException`: an `asyncio.CancelledError`,
    `KeyboardInterrupt`, or `SystemExit` MUST propagate so cooperative cancellation / shutdown still
    works (swallowing a CancelledError would hang the framework's cancel of that one request). Per-request
    cancellation already aborts only that request — the mcp serve loop isolates each handler in its own
    task and returns tool errors as messages (raise_exceptions=False) — so a cancelled call never takes
    the loop down. functools.wraps keeps the wrapped signature so FastMCP still builds the right tool
    schema, and the manifest scrape still recognises the `def`."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        wd = _WATCHDOG
        if wd is not None:
            wd.enter(fn.__name__)
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — uniform transport envelope; a tool must never crash the call
            # Log the RAW exception locally (server.log is a local diagnostic, not egress), but SCRUB the
            # returned `error` so a raised exception can't leak an absolute path or un-scrubbed canon
            # content back across the §1.9 egress to the session. `error_kind` (the type name) is verbatim.
            logger.warning("MCP tool %s raised %s: %s", fn.__name__, type(e).__name__, e, exc_info=True)
            return {"ok": False, "error": _scrub_error_text(str(e), sensitivity=_active_sensitivity()),
                    "error_kind": type(e).__name__}
        finally:
            if wd is not None:
                wd.exit()
    return wrapper


def _register(mcp, engine: KGEngine) -> None:
    # Expose the engine to the module-scope tool envelope so it scrubs error egress at the CONFIGURED
    # sensitivity (review: error-envelope-ignores-configured-sensitivity).
    global _ACTIVE_ENGINE
    _ACTIVE_ENGINE = engine

    @mcp.tool()
    @_tool_result
    def kg_ping() -> dict:
        """Health check: returns the engine version and configuration."""
        return engine.kg_ping()

    @mcp.tool()
    @_tool_result
    def kg_scrub(text: str | None = None) -> dict:
        """Egress PII/secret scrub (§1.9): redact a snippet (or the source) with consistent placeholders
        before handing text to a subagent; the canon later restores spans to the original."""
        return engine.kg_scrub(text)

    @mcp.tool()
    @_tool_result
    def kg_write(payload: dict, idempotency_key: str | None = None,
                 construction: str | None = None, source: str | None = None) -> dict:
        """Validate an extraction payload at the boundary and write accepted/demoted nodes & edges. The
        response carries a deterministic `receipt` (a hash of the payload's target ids); pass an
        `idempotency_key` to make a retry of a write whose transport response was lost a TRUE no-op that
        replays the identical receipt + dispositions (`idempotent_replay: True`) instead of a second pass.
        Without a key the write is still idempotent by canonical id — a re-send creates no duplicates.

        `construction` (optional) routes this SAME key-free, span-verified write to a separately-named
        second construction's alternate canon under `<project>/.kg/constructions/<slug>/` instead of the
        primary canon — the in-session "second construction" `/kg-perturb` cross-generates against
        (§9/§15). `source` names the second source document so spans verify against IT. Omit both for the
        normal primary-canon write."""
        return engine.kg_write(payload, idempotency_key=idempotency_key,
                               construction=construction, source=source)

    @mcp.tool()
    @_tool_result
    def kg_propose(payload: dict, construction: str | None = None,
                   source: str | None = None) -> dict:
        """Propose hypothesized candidates (PLAN Stage 1: the propose lane). Forces every item to
        provenance=hypothesized (a discovery-mechanism proposal, no span needed) and REFUSES any
        span-present/inferred text claim with reason `propose-lane-text-claim` — text claims belong on
        kg_write. Candidates land `unverified`; only kg_ground (with support) can ever promote them.
        `construction`/`source` route the proposal to a named second construction's alternate canon
        exactly like kg_write (§9/§15); omit both for the primary canon."""
        return engine.kg_propose(payload, construction=construction, source=source)

    @mcp.tool()
    @_tool_result
    def kg_ground(target_id: str, verdict: str, kind: str = "edge", note: str = "",
                  support_span: str = "", support_note: str = "") -> dict:
        """Apply a grounding verdict (grounded|rejected|failed|obsolete) to an edge or node. Verdicts
        applied via this tool are always attributed to the agent — a human verdict cannot be forged
        through the tool surface (§1.4). To PROMOTE a hypothesized edge OR node to grounded you MUST supply
        support, which upgrades its provenance: `support_span` (a verbatim source substring → span-present)
        or `support_note` (an external citation → inferred); without either, the promotion is refused with
        `hypothesis-needs-support`. `note` is appended to the edge's `notes` and is **edge-only** — it is
        ignored for kind='node' (a Node has no notes field)."""
        return engine.kg_ground(target_id, verdict, by="agent", kind=kind, note=note,
                                support_span=support_span, support_note=support_note)

    @mcp.tool()
    @_tool_result
    def kg_rename(old_id: str, new_id: str) -> dict:
        """Rename a node and rewrite every edge endpoint referencing it. STRICT: refuses when `new_id`
        already exists (a name collision is never silently a merge — use kg_merge for that)."""
        return engine.kg_rename(old_id, new_id)

    @mcp.tool()
    @_tool_result
    def kg_merge(from_id: str, into_id: str) -> dict:
        """Deliberately MERGE node `from_id` into the existing node `into_id` (both must exist), then
        retire `from_id`. Rewrites every edge endpoint `from_id`→`into_id`; where that collides two edges
        on one canonical id they are DEDUPED — failed/rejected negative information is sticky and never
        pruned (§1.7), else grounded beats unverified, and the verbatim span + verdict note are kept;
        no verdict/span is ever forged, upgraded, or invented. Self-loops the rewrite creates are dropped.
        Keeps `into_id`'s node_type/label and REFUSES a merge across two different declared node_types.
        Returns the edges rewritten/deduped/dropped and the final counts."""
        return engine.kg_merge(from_id, into_id)

    @mcp.tool()
    @_tool_result
    def kg_metrics() -> dict:
        """Summary counts: nodes, edges, edges by epistemic state."""
        return engine.kg_metrics()

    @mcp.tool()
    @_tool_result
    def kg_status() -> dict:
        """Cheap, projection-FREE status + coverage probe — confirm build progress and RESUME a partial
        build after any transport hiccup without grepping the filesystem. Reads ONLY the canon (+ source
        text for coverage); never triggers/refreshes the derived layer. Returns node/edge counts, edges
        by epistemic state, the still-`unverified` grounding-queue size, the engine-resolved `source`
        (`{path, exists, files}` — /kg-build reads the source path from HERE, not a shell env var, so a
        configured source_path is never silently ignored), and which source files/`##` sections already
        have an anchored edge. Unlike kg_metrics it never opens the derived db."""
        return engine.kg_status()

    @mcp.tool()
    @_tool_result
    def kg_generate(mechanism: str = "bridge", k: int = 10, second_graph: str | None = None,
                    dpp: bool | None = None, second_construction: str | None = None) -> dict:
        """Generate hypothesized idea candidates from the graph's structure (PLAN Stage 3). Mechanisms:
        bridge (§2/§4), seed (§3 residual), compression (§7 new nodes), regroup (§8), transplant (§5),
        ensemble (§9), periphery (§5 low-degree sources) — or "all"/"default". READ-ONLY: candidates are
        proposals (provenance=hypothesized, no span); route them through kg_propose. Generate
        offensively; kg_ground judges later.
        For the `ensemble` exo move, supply EITHER `second_construction` (the NAME of an in-session
        second construction built via kg_write(..., construction=…) — projected here, key-free) OR
        `second_graph` (a path to a pre-built graph.json); with neither, ensemble degrades to `regroup`
        and says so. `dpp` (FUSION Stage 5; default = the pack's `divergence.dpp` flag, shipped OFF)
        reorders the SAME candidate set by hybrid-descriptor DPP and adds a `divergence_advisory` block
        with bins, semantic novelty and cliché-hub distances — advisory presentation only,
        verdict-invariant (I5)."""
        return engine.kg_generate(mechanism=mechanism, k=k, second_graph=second_graph, dpp=dpp,
                                  second_construction=second_construction)

    @mcp.tool()
    @_tool_result
    def kg_absorption() -> dict:
        """Absorption window (§14): for each grounded-from-hypothesized node, how long it stayed
        perturbing before the graph renormalised — {half_life, status ∈ fertile|absorbed|isolated}.
        Reads derived/generations.json (written by /kg-generate). Prefer the fertile middle."""
        return engine.kg_absorption()

    @mcp.tool()
    @_tool_result
    def kg_operate(op: str, target: str | None = None, label: str = "", body: str = "",
                   members: list[str] | None = None, k: int | None = None) -> dict:
        """The four endo operations (§8) that WRITE hypothesized structure via the propose lane:
        collapse (cluster→compression node + collapses_into), explode (node→latent facet children),
        regroup (persist §8 re-partition bridges), open (new primitive + attachment points). Everything
        lands hypothesized/unverified with no span — never a verdict, never a forged anchor.
        `members` names an explicit member set for collapse (else the cluster is inferred from target)."""
        return engine.kg_operate(op, target=target, label=label, body=body, members=members, k=k)

    @mcp.tool()
    @_tool_result
    def query_graph(node_type: str | None = None, relation: str | None = None,
                    epistemic_state: str | None = None, limit: int = 50) -> dict:
        """Query nodes/edges by type, relation, or epistemic state (ranked by precomputed degree)."""
        return engine.query_graph(node_type=node_type, relation=relation,
                                  epistemic_state=epistemic_state, limit=limit)

    @mcp.tool()
    @_tool_result
    def get_node(node_id: str) -> dict:
        """Fetch a node with its incident edges."""
        return engine.get_node(node_id) or dict(_NOT_FOUND)

    @mcp.tool()
    @_tool_result
    def get_neighbors(node_id: str, relation: str | None = None) -> list:
        """Edges incident to a node, optionally filtered by relation."""
        return engine.get_neighbors(node_id, relation)

    @mcp.tool()
    @_tool_result
    def shortest_path(source: str, target: str) -> dict:
        """Shortest path between two nodes over the derived graph."""
        out = {"path": engine.shortest_path(source, target)}
        # surface the degraded signal so an empty path isn't mistaken for "no path" (review-M2)
        if engine.projection_degraded:
            out["projection_degraded"] = engine.projection_degraded
        return out

    @mcp.tool()
    @_tool_result
    def kg_explain_path(nodes: list[str]) -> dict:
        """Trace the associative chain between concepts over GROUNDED edges only (read-only egress, §2).
        Returns the ordered `path`, the grounded `edges` used (relation+span, for audit), and an ADVISORY
        `leap` = path length signalling creative distance — never a verdict, never written, never a score.
        For >2 nodes the order comes from a deterministic nearest-neighbour walk (a TSP approximation,
        byte-stable across processes) over the grounded shortest-path closure.
        EMPTY (path=[], leap=null) with a `reason` when no fully-grounded path exists — informative: the
        concepts are joined only through unverified/hypothesized/refuted links, or not at all."""
        return engine.explain_path(nodes)

    @mcp.tool()
    @_tool_result
    def kg_context(query: str | None = None, budget: int = 2000) -> dict:
        """Grounding-aware, provenance-carrying, token-budgeted context for the session."""
        return engine.kg_context(query, budget)

    @mcp.tool()
    @_tool_result
    def kg_agenda(limit: int = 5) -> dict:
        """Read-only structural "suggested questions" (R6). Reads ONLY precomputed derived columns and
        returns ~limit structural gaps split into answerable_now[] (well-grounded neighbourhoods) vs
        blocked_on_grounding[] (orphans, hypothesized-only neighbourhoods, under-grounded hubs,
        disconnected clusters). Ranked by the honest gate-aware signal (mirrors kg_context). It suggests,
        never acts — asserts no edges, copies no spans, stamps no verdicts (measure-never-gate); a
        hypothesized-only neighbourhood surfaces as BLOCKED, never as answerable. Heuristic, not a guarantee."""
        return engine.kg_agenda(limit=limit)

    @mcp.tool()
    @_tool_result
    def kg_export(kind: str = "all") -> dict:
        """Render the human-facing artifacts (R1): a self-contained, offline `graph.html` (vanilla-JS force
        layout encoding the three axes on independent channels — epistemic_state→line, authored_by→border,
        provenance→fill; size=degree; failed/rejected edges drawn, never filtered) and a `GRAPH_REPORT.md`,
        under the derived dir. `kind ∈ {html, report, all}`. READ-ONLY — projects-if-stale, consumes only the
        derived layer, writes only its two disposable artifacts; never forges a verdict or touches the canon."""
        return engine.kg_export(kind)

    # ------------------------------------------------------------------------- #
    # Divergence surface (FUSION_PLAN Stage 3) — the /kg-diverge flow's seven tools.
    #
    # Everything here sits BELOW the grounding boundary: these tools organize idea
    # candidates geometrically (embed → MAP-Elites → k-NN novelty → DPP slate →
    # anti-collapse monitor) and can never touch canon, verdicts, or the derived
    # DB (I1–I5: embeddings measure dispersion, never truth). State is project-
    # local and session-ephemeral (.kg/diverge, I4/I10). kg_engine.divergence is
    # imported LAZILY inside each body so this module's import graph stays
    # divergence-free (I3, firewall-tested) and a missing divergence dep degrades
    # only these seven tools with a clear error (I9) — never a kg_* tool.
    # ------------------------------------------------------------------------- #
    @mcp.tool()
    @_tool_result
    def kg_diverge_init(project: str, axes: dict | str | None = None, seed: int = 0,
                        session: str | None = None) -> dict:
        """Begin (or resume) a divergence session for a brief. `project` is the brief slug — one
        state dir per brief under .kg/diverge/. `axes` may be an inline axes spec (dict, e.g. from
        axis inference), a path, a bundled domain-template name (e.g. "generic", "marketing"), or
        omitted — omitted prefers the pack's `divergence:` section, else the generic template.
        `session` follows I10: pass ONE id per chat session (e.g. a timestamp slug) — a new id wipes
        the ephemeral geometry archive; re-passing the same id resumes it; pins/discards always
        survive. Returns the resolved domain, session id, and state paths."""
        from kg_engine.divergence import config as dconfig
        from kg_engine.divergence import pipeline as dpipe
        # pack_path threads the ENGINE's resolved pack into axes resolution, so the divergence
        # domain config can never diverge from the pack the engine loaded (review-r5).
        out = dpipe.init_project(project, dconfig.resolve_axes_source(axes, pack_path=engine.pack_path),
                                 seed=seed, home=engine._diverge_home(), session=session)
        # Unified negative memory (I8): fold grounding failures of previously
        # materialized pins into this brief's discards before the round starts.
        fates = engine._sync_materialized_fates(project)
        if fates:
            out["materialized_failures_discarded"] = fates
        # R3-mirror (Stage 5): surface `failed`-fated discards whose source set has since changed as
        # RE-EXAMINABLE — a re-look candidate, never an auto-un-seal. Surface-only.
        reexaminable = engine._reexaminable_discards(project)
        if reexaminable:
            out["reexaminable_discards"] = reexaminable
        return out

    @mcp.tool()
    @_tool_result
    def kg_diverge_ingest(project: str, candidates: list, axes: dict | str | None = None,
                          seed: int = 0) -> dict:
        """One divergence cycle: embed the generated candidates, near-dup dedup, place into the
        MAP-Elites archive, score geometric + mechanism novelty, and select a DPP-diverse slate.
        Each candidate: {"id", "text", "descriptor" {axis: value, ...}, optional "fitness" (the
        judge's bounded validity multiplier), optional "genealogy" {"operator_id", "parents"}}.
        Returns the slate (with niche coords, novelty, why-picked signals), ask_pairs for A-vs-B,
        and the anti-collapse monitor verdict — `mon.collapsing: true` means REGENERATE with more
        diversity pressure (advisory notice to the user, no question). Discarded ids are never
        re-slated. Purely advisory: nothing here can create graph state or verdicts."""
        from kg_engine.divergence import config as dconfig
        from kg_engine.divergence import pipeline as dpipe
        return dpipe.ingest(project, candidates,
                            dconfig.resolve_axes_source(axes, pack_path=engine.pack_path),
                            seed=seed, home=engine._diverge_home())

    @mcp.tool()
    @_tool_result
    def kg_diverge_remember(project: str, event: dict) -> dict:
        """Record a durable preference event: {"type": "pin"|"discard"|"comparison", ...}.
        Pins ({"type":"pin","id":...}) are strong stepping-stone signals and always future
        parents; discards ({"type":"discard","id":...}) are NEGATIVE MEMORY — dropped from
        every future slate and parent pool, persisted across sessions (I8); comparisons
        ({"type":"comparison","winner":...,"loser":...}) are low-weight A-vs-B evidence.
        Pin and discard are mutually exclusive per id (latest wins)."""
        from kg_engine.divergence import pipeline as dpipe
        return dpipe.remember(project, event, home=engine._diverge_home())

    @mcp.tool()
    @_tool_result
    def kg_diverge_parents(project: str, k: int = 4, seed: int = 0) -> dict:
        """Diverse parent set for the NEXT generation: DPP-sampled archive elites honoring
        preference memory — pins always included, discards never (I8). Use these as the
        stepping stones the next round of variation operators mutates/combines."""
        from kg_engine.divergence import pipeline as dpipe
        return dpipe.parents(project, k=k, seed=seed, home=engine._diverge_home())

    @mcp.tool()
    @_tool_result
    def kg_diverge_metrics(project: str) -> dict:
        """Archive health for the session: niche occupancy/entropy, novelty trend, monitor
        calibration, open-axis (mechanism) partition status, and advisory series (variety
        erosion, surface-vs-mechanism gap when enabled)."""
        from kg_engine.divergence import pipeline as dpipe
        return dpipe.metrics(project, home=engine._diverge_home())

    @mcp.tool()
    @_tool_result
    def kg_diverge_recall(project: str, k: int = 10, reexamine: list | None = None) -> dict:
        """Preference memory for injection at session start: recent pins, discards, and
        comparison summaries for this brief — so a resumed brief generates AWAY from what
        the human already discarded and TOWARD what they pinned. Also syncs the fate of
        previously materialized pins: one whose graph item was FAILED by grounding joins
        this brief's discards (unified negative memory, I8).

        On a source change it surfaces `failed`-fated discards under `reexaminable_discards` (a re-look
        candidate list — the divergence mirror of the graph R3-mirror; SURFACE-ONLY, never auto-un-sealed).
        Pass `reexamine=[candidate_ids]` to EXPLICITLY un-seal those candidates: each is dropped from the
        brief's discards and its failure fate cleared so it returns to the proposal pool to be
        re-materialized / re-grounded against the new source. Un-sealing never changes a graph verdict."""
        from kg_engine.divergence import pipeline as dpipe
        # Explicit un-seal FIRST, so this call's recall/discard view reflects the un-sealed candidates.
        unsealed = engine._unseal_discards(project, reexamine) if reexamine else []
        out = dpipe.recall(project, k=k, home=engine._diverge_home())
        fates = engine._sync_materialized_fates(project)
        if fates:
            out["materialized_failures_discarded"] = fates
        if unsealed:
            out["reexamined_unsealed"] = unsealed
        reexaminable = engine._reexaminable_discards(project)
        if reexaminable:
            out["reexaminable_discards"] = reexaminable
        return out

    @mcp.tool()
    @_tool_result
    def kg_diverge_materialize(project: str, candidate_ids: list | None = None,
                               node_type: str = "claim",
                               edges: list | None = None) -> dict:
        """Materialize PINNED ideas into the graph — the EXPLICIT action (nothing enters the
        graph implicitly; kickoff Q5). Each pinned candidate becomes a node in the
        hypothesized lane via the propose door (kg_propose -> kg_write -> boundary): it lands
        `provenance=hypothesized, epistemic_state=unverified`, carrying its full lineage
        ([diverge] pinned / brief / session / mechanism / operator) in the node body. No
        source present? It simply WAITS in the lane — /kg-ground later promotes it only with
        support (span or citation) and may fail it into permanent negative memory.
        `candidate_ids` defaults to every pin with a live session record; a pin from an
        ENDED session has no record left (I10) — re-ingest it first (reported as skipped).
        Optional `edges` are extra propose-lane edges linking materialized ideas to existing
        nodes ({source, target, relation[, notes]}); they transit the SAME boundary: claimed
        verdicts are stripped, text-claim provenance is refused, unknown fields are rejected.
        Pinned items may be ORDERED FIRST in the grounding queue; being pinned never changes
        a grounding VERDICT (verdict neutrality, I5). When a source is already configured and at
        least one pin materialized, the result carries an advisory-only `advisory` string noting
        that grounding these pins against the existing source will correctly leave a novel idea
        `unverified` until supporting sources are added (Part C — never a disposition or verdict)."""
        return engine.kg_diverge_materialize(project, candidate_ids=candidate_ids,
                                             node_type=node_type, edges=edges)


def _preload_native_deps() -> None:
    """Import the heavy native projection deps (numpy, igraph, leidenalg) — and networkx — ONCE at
    startup, on the MAIN thread, BEFORE the asyncio serve loop / anyio worker threads exist.

    Load-bearing, not a mere warm-up (BURGESS_BUG_kg_context_hang, failure #1). The projector imports
    these LAZILY, deep inside ``_leiden``/``_ranks`` — so on a populated canon the FIRST read that
    projects (``kg_context``, ``query_graph``, any lazy-projecting read) triggers the very first
    ``import numpy`` from WITHIN an MCP handler, i.e. on the event-loop thread while anyio worker threads
    are already alive. On Windows that late native-extension load (numpy → OpenBLAS spawning threads) can
    DEADLOCK on the loader lock and never return; the handler hangs, and the watchdog's own force-exit
    then also blocks on that same lock (see ``_hard_exit``). Importing here — single-threaded, before any
    of that exists — both (a) removes the multi-second-to-forever hot-path stall and (b) sidesteps the
    loader-lock deadlock entirely: ``sys.modules`` is warm, so the projector's later lazy imports are pure
    cache hits that take no loader lock. This is the highest-impact / lowest-risk of the reported fixes.

    Best-effort: a genuinely-absent or broken dep must still DEGRADE gracefully — the projector falls back
    to pure-Python label propagation (``projector._leiden``) and every ``kg_*`` graph tool keeps working —
    so an import failure here is logged at INFO and swallowed, NEVER a startup failure. Ordered so numpy
    (the actual hang site) is imported first and alone, before igraph pulls it in transitively."""
    for name in ("numpy", "networkx", "igraph", "leidenalg"):
        try:
            __import__(name)
        except Exception as e:  # noqa: BLE001 — a missing/broken native dep must degrade, not block startup
            logger.info("preload: %s unavailable (%s: %s); projection will fall back to the pure-Python "
                        "path if needed", name, type(e).__name__, e)


def _start_watchdog() -> "_Watchdog | None":
    """Construct + start the handler watchdog from KG_HANDLER_TIMEOUT (default DEFAULT_HANDLER_TIMEOUT;
    0/negative/invalid disables it), and publish it for the tool envelope to feed. Returns it (or None)."""
    global _WATCHDOG
    try:
        timeout = float(os.environ.get("KG_HANDLER_TIMEOUT", DEFAULT_HANDLER_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_HANDLER_TIMEOUT
    if timeout <= 0:
        return None
    _WATCHDOG = _Watchdog(timeout).start()
    return _WATCHDOG


def main() -> None:
    # Configure the rotating server log + uncaught-exception hooks FIRST, before anything that can fail,
    # so even an engine-construction error lands in <KG_DATA>/server.log with a full traceback (the whole
    # transport-crash class was previously undiagnosable because nothing was persisted).
    configure_logging()
    logger.info("kg_engine.server starting (version=%s pid=%s)", __version__, os.getpid())
    # Pull the heavy native projection deps (numpy/igraph/leidenalg) into sys.modules NOW — on the main
    # thread, before the watchdog thread and the asyncio/anyio serve loop start — so the first read that
    # projects never triggers a late, cross-thread native import that can deadlock the Windows loader lock
    # (BURGESS_BUG_kg_context_hang, fix #1). Before _start_watchdog for a fully single-threaded import.
    _preload_native_deps()
    _start_watchdog()
    try:
        from mcp.server.fastmcp import FastMCP
        # The lifespan writes <KG_DATA>/.engine-ready as the serve loop comes up so the Node supervisor can
        # tell a post-init crash (exit clean -> client reconnects) from a startup crash (relaunch in place).
        mcp = FastMCP("burgess", lifespan=readiness_lifespan)
        engine = build_engine_from_env()
        _register(mcp, engine)
        # mcp.run() returns NORMALLY on a clean client disconnect (stdin EOF closes the stdio transport
        # and the serve loop exits) -> exit 0, and the supervisor does NOT relaunch (session ending). A
        # per-request cancellation does NOT reach here: the mcp serve loop isolates each handler and keeps
        # serving (see _tool_result). Only an UNEXPECTED exception escaping the loop is a crash.
        mcp.run()
    except KeyboardInterrupt:
        logger.info("server interrupted (SIGINT); shutting down cleanly")
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 — log EVERY way the serve loop can die before the process goes
        logger.critical("server crashed out of the serve loop; exiting %s so the supervisor relaunches",
                        EXIT_CRASH, exc_info=True)
        # SystemExit triggers normal interpreter shutdown (atexit -> logging flush), so no explicit
        # shutdown() here — that would close handlers before the `finally` line below is logged.
        raise SystemExit(EXIT_CRASH)
    finally:
        logger.info("server exiting (pid=%s)", os.getpid())


if __name__ == "__main__":
    main()
