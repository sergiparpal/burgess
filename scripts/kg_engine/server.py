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
import sqlite3
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, envconfig
from .canon import EDGELESS_SECTIONS, HUB_ATTACKS, UNSUPPORTED_PINS, Canon
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
    NON_LIVE_STATE_VALUES,
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
from .buildplan import (edgeless_records, parse_arguments, related_nodes, resolve_subset, section_digest,
                        vocabulary_digest)
from .scrub import Scrubber, placeholders_in
from .sources import SourceSet, plan_sections, split_sections
from .evidence import (CITATION_MARK, COUNTER_RELATIONS, NOTES_NONE, OWN, REFUTED_BY_MARK, VETO_HINTS as _VETO_HINTS,
                       EvidenceRegistry, Policy, evidence_dir, failed_veto, label as evidence_label,
                       level_unusable, load_policy, load_registry, note_label, registry_signature,
                       support_segment, supports_of, unusable_reason)
from .waves import explain_wave_size

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
# Ledger keys of materialized.json that are not candidate ids, so the fate sync and the re-examinable
# advisory skip them: unowned edges, the source signature, and (0.20.0) the materialized clichés, which
# are not ideas of the brief and never join its discards.
_LEDGER_RESERVED = ("_edges", "_source_sig", "_cliches")
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
# up (the lifespan __aenter__, AFTER imports + engine construction succeed), so its presence once the child
# has exited proves THIS engine began serving.
#
# One marker per spawn (0.11.2): the supervisor names a fresh file in KG_DATA for each child and hands its
# path over in KG_READY_MARKER. Through 0.11.1 every engine wrote one `.engine-ready` under KG_DATA, which
# an installed plugin points at CLAUDE_PLUGIN_DATA, one dir for every session on the machine. Sessions
# then deleted and passed off each other's markers, and a crash in an engine's first seconds could be
# classified either way wrong (the launcher's comment has the cases). An engine started without a
# supervisor has nobody to read a marker, so it writes none.
READY_MARKER_ENV = "KG_READY_MARKER"  # kept in sync with launch_server.mjs READY_MARKER_ENV


def ready_marker_path() -> "Path | None":
    """The marker path this engine's supervisor handed it, or None when it was started without one."""
    raw = envconfig.clean_env(READY_MARKER_ENV)
    return Path(raw) if raw else None


def write_ready_marker() -> None:
    """Stamp the readiness marker (best-effort; a failure must never block serving)."""
    try:
        p = ready_marker_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"pid={os.getpid()} t={time.time():.3f}\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 — the marker is advisory; never fail startup on it
        pass


def clear_ready_marker() -> None:
    """Remove the readiness marker on a clean shutdown (best-effort). The supervisor removes it too once
    it has read the child's exit, so a leftover from a hard crash does not linger."""
    p = ready_marker_path()
    if p is None:
        return
    try:
        p.unlink()
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

    def __init__(self, source_path=None, evidence_dir=None, project_dir=None):
        self.source_path = Path(source_path) if source_path else None
        # The project's evidence directory (0.21.0): registered external copies, verification-only.
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        # The project (0.23.0), which a policy's notes path is relative to.
        self.project_dir = (Path(project_dir) if project_dir
                            else (self.evidence_dir.parent if self.evidence_dir else None))
        self._cache: "tuple[tuple, SourceSet] | None" = None  # (signature, SourceSet) memo
        self._ecache: "tuple[tuple, EvidenceRegistry, Policy, list] | None" = None  # (dir sig, registry, policy, problems)
        self._vcache: "tuple[tuple, SourceSet] | None" = None  # (signatures, verification set) memo

    def _evidence(self) -> "tuple[tuple, EvidenceRegistry, Policy, list]":
        """The registry and the policy (0.21.0 / 0.22.0), re-read only when a file of the evidence directory
        moved (`policy.json` lives there too). An absent directory is an empty registry and the defaults."""
        sig = registry_signature(self.evidence_dir)
        if self._ecache is None or self._ecache[0] != sig:
            pol, problems = load_policy(self.evidence_dir)
            self._ecache = (sig, load_registry(self.evidence_dir), pol, problems)
        return self._ecache

    def registry(self) -> EvidenceRegistry:
        return self._evidence()[1]

    def policy(self) -> Policy:
        return self._evidence()[2]

    def notes_path(self) -> "Path | None":
        """The notes this project reads (0.23.0): the policy's `notes_path`, a path inside the project, or no
        notes at all for `none`; with neither, the plugin's `source_path`, one value for every project, which is
        all Claude Code allows a plugin option to be."""
        value = self.policy().notes_path
        if not value:
            return self.source_path
        if value == NOTES_NONE or self.project_dir is None:
            return None
        return self.project_dir / value

    def notes_origin(self) -> str:
        """Where `notes_path()` comes from: `project` (the policy), `none` (the policy says no notes) or
        `global` (the plugin's source_path)."""
        value = self.policy().notes_path
        return "global" if not value else ("none" if value == NOTES_NONE else "project")

    def _split(self) -> "tuple[list, list]":
        """(the registered copies built into the graph, the other registered copies), as paths."""
        reg = self.registry()
        built = [reg.directory / name for name, rec in reg.records.items() if rec.build]
        other = [reg.directory / name for name, rec in reg.records.items() if not rec.build]
        return built, other

    def resolve(self) -> SourceSet:
        """The content set (memoized on the file signatures): what extraction, coverage and the specificity
        corpus read. The configured sources, unless the policy builds from registered sources only, then the
        registered copies marked `build` (0.22.0). Named `resolve` — the old name `set()` read as a mutator
        when it is the getter (review-r5)."""
        pol = self.policy()
        built, _other = self._split()
        path = self.notes_path() if pol.build_from_notes else None
        sig = (SourceSet.signature(path, built, exclude=self.evidence_dir), pol.build_from_notes, str(path))
        if self._cache is None or self._cache[0] != sig:
            self._cache = (sig, SourceSet(path, content=built, exclude=self.evidence_dir))
        return self._cache[1]

    def verify(self) -> SourceSet:
        """The verification set (0.21.0): the configured sources, then the text of every registered
        external source. What span checks, the R3 staleness scan, the grounder's evidence views and the
        source digests read. Its `concat` is the content set's, so the projector's specificity corpus is the
        same; a configured source that is not built (0.22.0) is still verified against, as evidence only.
        With nothing registered and the default policy it holds exactly what `resolve()` holds."""
        pol = self.policy()
        built, other = self._split()
        notes = self.notes_path()
        sig = (SourceSet.signature(notes, built + other, exclude=self.evidence_dir),
               self._ecache[0], pol.build_from_notes, str(notes))
        if self._vcache is None or self._vcache[0] != sig:
            self._vcache = (sig, SourceSet(notes, content=built, extra=other, exclude=self.evidence_dir,
                                           path_is_content=pol.build_from_notes))
        return self._vcache[1]

    def text(self) -> str:
        return self.resolve().concat

    def set_path(self, source_path) -> None:
        """Re-point at a new source (and drop the memo) IN PLACE, so a holder of .resolve/.text —
        e.g. the already-wired projector — sees the change without being reconstructed."""
        self.source_path = Path(source_path) if source_path else None
        self._cache = None
        self._vcache = None


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
    # The projector reads the VERIFICATION set (0.21.0): its R3 staleness scan must find a span grounded on a
    # registered external copy, and its source digest must move when one is registered. Its specificity
    # corpus is that set's `concat`, which is the configured sources alone, so the IDF never sees evidence.
    return Projector(canon, derived_dir, metrics_mode=metrics_mode,
                     source_text=sources.text, source_set=sources.verify,
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
        # LAZY layout: Claude Code builds this engine at session start (.mcp.json → main() →
        # build_engine_from_env) in whatever folder the session opened, Burgess used there or not. An eager
        # Canon left an empty canon/ + .git/info/exclude lines in every such folder — and that canon/ then
        # passed the SessionStart reconcile's "is there a project here?" guard, which wrote the reconcile
        # state + checkpoint beside it. The layout is now created by the first WRITE instead
        # (Canon.acquire_lock → ensure_layout, which every canon writer reaches); reads glob a missing
        # canon dir as empty, so a read-only session leaves the project untouched.
        self.canon = Canon(self.project_dir, ensure_layout=False)
        self.reconciler = Reconciler(self.canon)
        # §1.8 grounding-audit log — the forge-detection WRITER half (the reconciler is the reader). A
        # collaborator, not inline, so the crash-safe append/truncate protocol is unit-testable.
        self._audit_log = GroundAuditLog(self.canon.root / GROUND_AUDIT)
        # The configured source: a single file (back-compat), or a DIRECTORY / GLOB of .md/.txt (R4).
        # Resolution + memo live in _SourceResolver, shared verbatim with the read-only PreToolUse hook. It
        # also holds the project's registered external sources (0.21.0, `<project>/evidence/`).
        self._sources = _SourceResolver(source_path, evidence_dir(self.project_dir), self.project_dir)
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
        # Serializes the session scrub (the Scrubber's counters + _scrub_map). Since 0.5.0 a whole wave of
        # extractors calls kg_section at once. mcp 1.x runs a sync tool on the event loop, so those calls
        # already arrive one at a time; the lock keeps placeholder numbering and the restore map consistent
        # if a transport ever runs them on threads, where two values could otherwise share a placeholder.
        self._scrub_lock = threading.Lock()
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
        # (file, section_digest) of every section text kg_section served for extraction since this engine
        # started (0.14.1). kg_record_edgeless_section records only a section whose CURRENT text one of these
        # reads served: a record says an extraction read the section and found nothing to write. On 0.14.0
        # the build's orchestrator, which reads no section, offered to record 18 of them itself (field
        # report). Kept in memory like the write cache: after a restart a record waits for a new read.
        self._sections_read: "set[tuple[str, str]]" = set()

    # ---- source set (for span verification) — delegate to the shared resolver
    def source_set(self) -> SourceSet:
        """The resolved {basename → text} view over the configured source(s) (R4), memoized off the hot
        path. A single configured file is a one-entry SourceSet, byte-identical to the prior path."""
        return self._sources.resolve()

    def verify_set(self) -> SourceSet:
        """The configured sources plus every registered external copy (0.21.0), memoized: what a span is
        verified against (kg_write, kg_ground) and what kg_ground_item shows evidence from. Extraction and
        coverage keep reading `source_set()`, so a registered source is never extracted into the graph."""
        return self._sources.verify()

    def evidence_registry(self) -> EvidenceRegistry:
        """The project's registered external sources (0.21.0), memoized on the evidence directory."""
        return self._sources.registry()

    def evidence_policy(self) -> Policy:
        """The project's evidence policy (0.22.0, `evidence.Policy`): the defaults when there is none."""
        return self._sources.policy()

    def source_text(self) -> str:
        """The configured source(s) concatenated — feeds the flood-budget size and the projector's IDF
        corpus. Span verification itself is per-file via source_set().verifies, not this blob."""
        return self._sources.text()

    def _source_signature(self) -> str:
        """sha256 of the current source payload (the verification set's `full_concat`: the configured
        sources, then every registered external copy), matching ``projector._source_hash`` — the
        divergence-side twin of the graph advisory's source-change pre-gate (Stage 5, re-examinable
        verdicts). ``""`` when no source is configured. Used to stamp the source a materialized-pin failure
        was fated against, so a later source change can surface it as re-examinable on the brief side
        exactly as the graph side surfaces failed/rejected items, and by the unsupported-pin ledger (0.20.1):
        registering a source moves it, so the pins waiting for new sources come back (0.21.0). With nothing
        registered the payload is the configured concat, so a 0.20.2 ledger record still matches."""
        try:
            payload = self.verify_set().full_concat
            pol = self.evidence_policy()
        except Exception:  # noqa: BLE001 — a source-read hiccup degrades to "" (no signature), never crashes the sync
            return ""
        # A policy that changes what may support (0.22.0) is part of what an item was judged against, so a
        # change to it offers the waiting items again. The default policy adds nothing: a 0.21.0 record matches.
        if payload and not pol.is_default():
            payload += "\n" + pol.fingerprint()
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

    @property
    def notes_path(self) -> "Path | None":
        """The notes this project reads (0.23.0, `_SourceResolver.notes_path`): its policy's own folder, none,
        or the plugin's `source_path`."""
        return self._sources.notes_path()

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
                               sources=_SourceResolver(source_path, evidence_dir(project_dir), project_dir),
                               pack_get=pack_get, metrics_mode=metrics_mode)

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
        with self._scrub_lock:
            scrubbed, mapping = self.scrubber.scrub(src)
            self._scrub_map.update(mapping)
        # Count what this TEXT holds, not what this call minted. Placeholders are consistent across the
        # session (one per value), and scrub() returns only the pairs it created now, so a section whose
        # values had all been redacted by an EARLIER call came back with ⟦SECRET:1⟧ in its text and
        # `redactions: 0`, which reads as "the scrubbed text is the original" (field report on 0.4.5).
        # A placeholder counts when the session map sends it to another value. Identity entries (a literal
        # ⟦CAT:N⟧ already present in the source prose, mapped to itself so restore leaves it alone —
        # scrub-2/M4) are protection bookkeeping, not redactions, and stay out of the count and categories.
        real = {ph for ph in placeholders_in(scrubbed) if self._scrub_map.get(ph, ph) != ph}
        return {"scrubbed": scrubbed, "redactions": len(real),
                "sensitivity": self.sensitivity,
                "categories": sorted({ph.split(":")[0].strip("⟦") for ph in real})}

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

    # The reason kg_write refuses an item that claims the proposal lane: the mirror of kg_propose's
    # `propose-lane-text-claim`, so each write tool refuses the other tool's lane at its own door.
    _WRITE_LANE_HYPOTHESIS = "write-lane-hypothesis"

    @staticmethod
    def _split_write_lane(payload) -> "tuple[object, list[dict]]":
        """``(payload, refused)``: ``payload`` without the items that explicitly claim
        ``provenance=hypothesized``, and one REJECTED detail per item taken out.

        The boundary handles a hypothesized item as a discovery-mechanism PROPOSAL: it stores the item
        with an EMPTY span and runs no span check (contract §5a). That is right for `kg_propose`, and wrong
        when the item reached the text-claim lane: an extractor that marked an edge `hypothesized` (as
        its own contract invited, for a relation "inferred across sentences") had its span dropped and
        never verified, and the edge was ACCEPTED, so the build's span-support guarantee failed with no
        REJECTED or QUARANTINED signal (field report on 0.4.6: 2 of 61 edges, found only because their
        section stayed uncovered). Refusing it here keeps every edge kg_write accepts span-verified, and
        names the fix: re-emit the claim as `inferred` with its verbatim span, or propose it on purpose
        through kg_propose. A payload of any other shape passes through untouched, for validate_payload
        to judge."""
        if not isinstance(payload, dict):
            return payload, []
        refused: "list[dict]" = []
        out = dict(payload)
        for key, kind in (("nodes", "node"), ("edges", "edge")):
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            kept = []
            for it in items:
                if not (isinstance(it, dict) and it.get("provenance") == Provenance.HYPOTHESIZED.value):
                    kept.append(it)
                    continue
                try:
                    rid = (edge_id(it.get("source") or "", it.get("relation") or "", it.get("target") or "")
                           if kind == "edge" else (it.get("id") or slug(it.get("label") or "")))
                except Exception:  # noqa: BLE001 — a malformed item still gets its refusal, just no id
                    rid = None
                refused.append({"kind": kind, "id": rid, "disposition": Disposition.REJECTED.value,
                                "reason": KGEngine._WRITE_LANE_HYPOTHESIS, "retryable": False})
            out[key] = kept
        return out, refused

    def kg_write(self, payload: dict, *, message: str = "kg_write", existing_nodes=None,
                 idempotency_key: str | None = None, construction: str | None = None,
                 source=None, lane: str = "text-claim") -> dict:
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
        (every other caller) is the unchanged primary-canon path.

        **The text-claim lane (0.5.1).** `lane="text-claim"`, the default and the only lane the MCP tool
        exposes, refuses any item that claims `provenance=hypothesized` (REJECTED,
        `write-lane-hypothesis`, see `_split_write_lane`) and writes the rest, so every edge it accepts
        carries a verified span. `kg_propose` alone passes `lane="proposal"`, after forcing its items
        into that lane."""
        if lane not in ("text-claim", "proposal"):
            raise ValueError(f"unknown write lane {lane!r}: use 'text-claim' (kg_write) or 'proposal' "
                             "(kg_propose)")
        if construction:
            # Route to the named alternate canon's own engine — full boundary → canon → projector,
            # rooted elsewhere. The sub-engine computes its own baseline (never the primary's
            # existing_nodes) and uses its own idempotency cache.
            return self._construction_engine(construction, source).kg_write(
                payload, message=message, idempotency_key=idempotency_key, lane=lane)
        if source is not None:
            # `source` only names the second construction's own source; without `construction` it would be
            # silently dropped (the primary source is fixed at startup). Refuse loudly rather than no-op on
            # a caller that thinks it is re-pointing the primary source (review-fix: L3/server-5).
            raise ValueError("`source` is only valid together with `construction` (it names the second "
                             "construction's source document); omit it for a primary-canon write")
        refused: "list[dict]" = []
        if lane == "text-claim":
            payload, refused = self._split_write_lane(payload)
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
        # Spans verify against the configured sources AND the registered external copies (0.21.0), so a
        # counter-edge quoting a registered paper is span-present like any other; the flood budget stays
        # sized on the configured corpus (`source_text`).
        results = validate_payload(payload, pack=self.pack, source_text=self.source_text(),
                                   sources=self.verify_set(),
                                   existing=existing_edges,
                                   existing_node_ids={n.id for n in existing_nodes},
                                   restore=restore, max_edges_per_kb=self.max_edges_per_kb)
        nodes = merge_results_into_nodes(results)
        # The NEW notes this write creates untyped (0.6.1): a node an edge names that the payload does not
        # declare and the canon does not hold yet becomes a placeholder, with no node_type and no body. It
        # used to happen silently; in one field build (0.6.0) `camel` landed that way, and two later
        # extractors refused to link to an untyped node. Reported, the extractor can declare it at once.
        declared = {r.item.id for r in results if r.kind == "node" and r.written}
        known_ids = {n.id for n in existing_nodes}
        placeholders = sorted(nid for nid in nodes if nid not in declared and nid not in known_ids)
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
        if placeholders and not rolled_back:
            out["placeholders"] = placeholders
        if refused:
            # the lane refusals lead the details, and count as REJECTED, exactly as kg_propose folds its own
            out["details"] = refused + out["details"]
            out["dispositions"][Disposition.REJECTED.value] += len(refused)
            out["refused_hypotheses"] = len(refused)
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
        unchanged primary-canon path.

        An edge may carry `passage` (0.19.0): the `{"span", "source_file"}` an ensemble candidate came with,
        where a second construction read the edge. It is not the proposal's span. When the span verifies
        against a configured source (placeholders restored first, `MIN_SPAN_CHARS` met), the proposal's notes
        open with it (`groundplan.with_passage`), and `kg_ground_item` later shows the grounder that passage;
        otherwise nothing is kept. Either way the edge is written as any proposal is, and `passages` reports
        `recorded` ids and `not_recorded` ones with the reason. Only the engine opens notes with a passage:
        one an item's own notes open with is dropped (`_take_passage`)."""
        if construction:
            return self._construction_engine(construction, source).kg_propose(payload, message=message)
        if source is not None:
            raise ValueError("`source` is only valid together with `construction` (it names the second "
                             "construction's source document); omit it for a primary-canon propose")
        payload = dict(payload or {})
        refused: list[dict] = []
        passages: dict = {"recorded": [], "not_recorded": []}
        offered = False

        def _lane(items, kind):
            nonlocal offered
            kept = []
            for it in (items or []):
                it = dict(it or {})
                passage = it.pop("passage", None) if kind == "edge" else None
                offered = offered or passage is not None
                prov = it.get("provenance")
                if prov in (Provenance.SPAN_PRESENT.value, Provenance.INFERRED.value):
                    refused.append({"kind": kind,
                                    "id": it.get("id") or it.get("source") or it.get("label"),
                                    "disposition": Disposition.REJECTED.value,
                                    "reason": "propose-lane-text-claim", "retryable": False})
                else:
                    it["provenance"] = Provenance.HYPOTHESIZED.value  # force the lane
                    if kind == "edge":
                        self._take_passage(it, passage, passages)
                    kept.append(it)
            return kept

        clean = {"nodes": _lane(payload.get("nodes"), "node"),
                 "edges": _lane(payload.get("edges"), "edge")}
        if "complete" in payload:
            clean["complete"] = payload["complete"]
        out = self.kg_write(clean, message=message, lane="proposal")
        # fold the call-site refusals into the same response shape kg_write returns
        out["details"] = refused + out["details"]
        out["dispositions"][Disposition.REJECTED.value] = (
            out["dispositions"].get(Disposition.REJECTED.value, 0) + len(refused))
        out["propose_lane"] = True
        out["refused_text_claims"] = len(refused)
        if offered:
            out["passages"] = passages
        return out

    def _take_passage(self, item: dict, passage, passages: dict) -> None:
        """Open a proposed edge's notes with the passage it was handed, when that passage holds in a configured
        source (0.19.0); record the outcome in ``passages``. The item's own notes lose any passage segment they
        open with first, so the one a grounder is shown is always one this check let through."""
        from .groundplan import with_passage, without_passage

        if item.get("notes"):
            item["notes"] = without_passage(str(item["notes"]))
        if passage is None:
            return
        try:
            rid = edge_id(str(item.get("source") or ""), str(item.get("relation") or ""),
                          str(item.get("target") or ""))
        except Exception:  # noqa: BLE001 — a malformed edge still gets its outcome, just no id
            rid = None
        span = passage.get("span") if isinstance(passage, dict) else None
        name = passage.get("source_file", "") if isinstance(passage, dict) else None
        if not (isinstance(span, str) and span.strip() and isinstance(name, str)):
            passages["not_recorded"].append({"id": rid, "reason": "passage-malformed"})
            return
        restore = self._restore_fn()
        check = restore(span) if restore else span
        sources = self.source_set()
        if not sources.verifies(check, name):
            passages["not_recorded"].append({"id": rid, "reason": "passage-not-in-source"})
            return
        if len(normalize_text(check).replace(" ", "")) < MIN_SPAN_CHARS:
            passages["not_recorded"].append({"id": rid, "reason": "passage-too-short"})
            return
        held = SourceSet._key(name) if sources.has_file(name) else (sources.files_containing(check) or [""])[0]
        item["notes"] = with_passage(item.get("notes"), check, held)
        passages["recorded"].append(rid)

    def kg_ground(self, target_id: str, verdict: str, *, by: str = "agent", kind: str = "edge",
                  note: str = "", support_span: str = "", support_note: str = "", lead: str = "",
                  refuted_by: str = "") -> dict:
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
        A hypothesized edge into a node in a non-live state (rejected, failed, obsolete) is not promoted:
        `hypothesis-into-non-live-node`, naming the node and its state (0.17.1). The node's verdict settles
        its star, so such an edge is rejected instead.

        `note` is appended to an EDGE's `notes`. A Node has no notes field, so for `kind='node'` the note
        is added to the node's body as the paragraph `verdict (<state>): <note>` (0.16.1; through 0.16.0
        it was ignored).

        `lead` (0.9.0) goes with a `rejected` edge: the edge its span does state instead, typed
        `<head-id> <relation> <tail-id>` (`groundplan.parse_lead`), which `/kg-build --leads` later has an
        extractor write. It is appended to the notes as `lead: <head> <relation> <tail>`, after `note`. A
        lead that is malformed, names a relation the pack does not declare, joins a node to itself, or
        repeats the rejected edge is refused before any state change, like an unsupported promotion. So
        is a lead on an edge with no span, such as a proposal (0.18.0): `--leads` writes a lead from the
        rejected edge's span, and that edge has none.
        A lead belongs to the rejection that recorded it (0.11.1): a verdict that changes the edge's state
        and records no lead of its own withdraws the lead the notes hold, by appending `lead: none` after
        `note`, and returns it as `lead_withdrawn`.

        A verdict that leaves an edge's state where it was (0.10.2) re-confirms it: `verdict_by` and
        `verdict_at` keep saying who put the edge in that state and when, while `note` and `lead` are
        appended and the audit log records the re-verdict at its own time. `kg_ground_plan` reads
        `verdict_at` as when a claim was grounded, so a re-confirmed claim does not reopen a hub.

        **Levels of sources (0.21.0 external sources; 0.22.0 every source, under the project's policy).** Spans
        verify against the configured sources and the registered external copies, and the level decides only
        what may be used:
        - support (a promotion span, or the support of an edge being grounded) must lie in a usable source: at
          or above the policy's `required_level` (4 by default), neither unfiltered, retracted nor superseded.
          The notes have a level too (`notes_level`, 4 unless set per file). When every file that holds it is
          unusable the verdict is refused with `support-not-usable`, naming the file, its level and why. A
          promotion records the usable file of the highest level that holds its span.
        - an edge that carries its span can be grounded on another passage (0.22.0): `support_span` from a
          usable source, recorded in the notes as a `support:` segment beside the span it was extracted from.
        - `failed` names its refutation in `refuted_by`, the id of the counter-edge (`attacked_by`,
          `confounded_by` or `collapses_into`, touching the claim) whose span refutes it, and is required
          once any external source is registered: the engine must know where the refuting span lies. The
          level is a veto, never the winner (`evidence.failed_veto`): an unusable source refutes nothing;
          the configured sources and an external source never fail each other (`failed-across-own-and-
          external`: the counter-edge stands as a visible dispute, and the user corrects the note); a lower
          level cannot fail a higher one (`failed-by-lower-level`). The id is appended to the notes as
          `refuted by: <id>`.
        - a `support_note` promotion is recorded as `citation (unchecked): <note>`: the engine cannot check
          it. Registering the source and citing its span is how such support becomes checkable."""
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
        triple = None
        if lead and lead.strip():
            from .groundplan import parse_lead
            if kind != "edge" or verdict != "rejected":
                return {"ok": False, "error": "a lead goes with a rejected edge: the edge its span does state "
                                              "instead"}
            if self.pack is None:
                return {"ok": False, "error": "a lead needs the pack's relations, and no pack is loaded"}
            triple, problem = parse_lead(lead, self.pack.edge_types)
            if problem:
                return {"ok": False, "error": f"lead: {problem}"}
        # `by` is provenance, not a free-text field: clamp to the known actors so a stray value can't
        # masquerade as a verdict author (the MCP tool surface already pins this to "agent").
        by = by if by in VALID_ACTORS else "agent"
        state = EpistemicState(verdict)
        promoted_to = None
        withdrawn = None   # the lead this verdict withdraws (0.11.1): edge verdicts only
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
                corroboration = None
                # The level veto on a refutation (0.21.0), decided before any state change like every gate here.
                if state == EpistemicState.FAILED:
                    refusal = self._failed_refusal("node", node, refuted_by)
                    if refusal:
                        return {"ok": False, **refusal}
                # the hypothesized→grounded promotion gate applies to NODES too: kg_operate writes
                # hypothesized compression nodes/primitives via the propose lane, so a generated node must
                # earn grounding with support, not become grounded knowledge for free (mirrors the edge
                # gate; decided BEFORE any state change so a refusal leaves the node untouched).
                if node.provenance == Provenance.HYPOTHESIZED and state == EpistemicState.GROUNDED:
                    promoted_to, err = self._promote_hypothesis_node(node, support_span, support_note)
                    if err:
                        return {"ok": False, **err} if isinstance(err, dict) else {"ok": False, "error": err}
                frm = node.epistemic_state.value
                node.epistemic_state = state
                if state == EpistemicState.FAILED and refuted_by.strip():
                    node.body = self._append_body(node.body, REFUTED_BY_MARK + refuted_by.strip())
                # A node verdict keeps its note (0.16.1). A Node has no notes field, so the note goes in
                # the body, after any support the promotion put there, as the paragraph
                # `verdict (<state>): <note>`. Canon keeps a judged node's body when the node is written
                # again, so the note lasts as an edge's notes do. Through 0.16.0 the note was ignored for
                # a node: the field kg-ground of 2026-11-14 rejected two generated compression nodes with
                # a reason each, and both reasons were lost.
                if note and note.strip():
                    node.body = self._append_body(node.body, f"verdict ({verdict}): {note.strip()}")
                key = f"node:{node.id}"
            else:
                try:
                    node = self._owner_of_edge(target_id)
                except EdgeOwnerUnreadable as e:
                    return {"ok": False, "error": self._scrub_error(f"node unreadable: {e}")}
                if node is None:
                    return {"ok": False, "error": "edge not found"}
                edge = next(e for e in node.edges if e.id == target_id)
                if triple and edge_id(*triple) == edge.id:  # decided before any state change, like the gate below
                    return {"ok": False, "error": "lead: it repeats the edge being rejected"}
                # A lead is written from the rejected edge's span (`_lead_section`), so an edge with none, a
                # proposal, has no passage to give it (0.18.0). Through 0.17.1 such a lead was taken and then
                # sat in `/kg-build --leads`'s `leads_unlocated`, told its span had left the source. Since
                # 0.18.0 a grounder reads a proposal against the passages where its ends meet, so it may well
                # find another relation stated there, and the note is where that goes.
                if triple and not (edge.span and edge.span.strip()):
                    return {"ok": False, "error": "lead: this edge has no span, so /burgess:kg-build --leads "
                                                  "would have no passage to write the lead from. Reject it "
                                                  "without a lead, and name in the note the edge the passage "
                                                  "states"}
                # The level veto on a refutation (0.21.0): where the refuting span lies decides whether this
                # claim may be stamped failed at all.
                if state == EpistemicState.FAILED:
                    refusal = self._failed_refusal("edge", edge, refuted_by)
                    if refusal:
                        return {"ok": False, **refusal}
                # Support counts only from a usable source (0.21.0; since 0.22.0 under the project's policy, for
                # every source). A promotion is checked inside its gate below. An edge that already carries its
                # span may be grounded on another passage instead (0.22.0): a `support_span` from a usable
                # source, recorded beside the span it was extracted from. Under a strict policy that is how a
                # claim the notes state is verified by a reviewed source.
                corroboration = None
                if state == EpistemicState.GROUNDED and edge.provenance != Provenance.HYPOTHESIZED:
                    if support_span and support_span.strip():
                        restore = self._restore_fn()
                        check = restore(support_span) if restore else support_span
                        vs = self.verify_set()
                        if not vs.verifies(check):
                            return {"ok": False, "error": "support-span-not-in-source"}
                        if len(normalize_text(check).replace(" ", "")) < MIN_SPAN_CHARS:
                            return {"ok": False, "error": "support-span-too-short"}
                        problem = self._support_problem(check, vs)
                        if problem:
                            return {"ok": False, **problem}
                        corroboration = (check, self._support_file(check, "", vs))
                    elif edge.span and edge.span.strip():
                        held = self._edge_support(edge)
                        if held is not None and not self._usable_file(held):
                            return {"ok": False, **self._unusable_refusal(held)}
                # the hypothesized→grounded promotion gate: a span-less proposal earns grounding only with
                # support, which upgrades its provenance. Decided BEFORE any state change so a refusal leaves
                # the edge untouched (no audit record, no write).
                if edge.provenance == Provenance.HYPOTHESIZED and state == EpistemicState.GROUNDED:
                    # A proposal into a node that is not live is not promoted (0.17.1): the node's verdict
                    # settles its star. On the field graph of 2026-11-15 one grounder rejected a generated
                    # compression while another, in a parallel batch, grounded an edge into it.
                    dead = self._non_live_end(edge)
                    if dead:
                        return {"ok": False, "error": "hypothesis-into-non-live-node",
                                "node": dead[0], "node_state": dead[1]}
                    promoted_to, err = self._promote_hypothesis(edge, support_span, support_note)
                    if err:
                        return {"ok": False, **err} if isinstance(err, dict) else {"ok": False, "error": err}
                frm = edge.epistemic_state.value
                # A lead belongs to the rejection that recorded it (0.11.1). A verdict that changes the
                # state and records no lead of its own withdraws the lead the notes hold, so an overturned
                # lead cannot come back as pending: through 0.11.0, an edge rejected with a lead, grounded
                # again, then rejected once more without one offered its first lead again. A re-confirmation
                # keeps the lead, as it keeps the time (0.10.2); a lead it records replaces the old one.
                if edge.epistemic_state != state and not triple:
                    from .groundplan import lead_of
                    withdrawn = lead_of(edge.notes)
                # A verdict that leaves the state where it was re-confirms it (0.10.2). `verdict_by` and
                # `verdict_at` keep saying who put the edge in that state and when; the re-verdict's note
                # and lead go to the notes below, and the audit log records it at its own time. Through
                # 0.10.1 every call stamped them anew, and `kg_ground_plan` reads `verdict_at` as when a
                # claim was grounded: re-confirming a grounded claim of a hub an adversarial pass had
                # attacked made the claim look new, so the plan offered that hub to another attack with
                # nothing new to find. An edge in a verdict state with no `verdict_at`, which only a hand
                # edit leaves (the merge driver and the reconciler clear both fields only with `unverified`),
                # gets stamped, as any other verdict would stamp it.
                if not (edge.epistemic_state == state and edge.verdict_at):
                    edge.verdict_by = by
                    edge.verdict_at = utcnow()
                edge.epistemic_state = state
                if note:
                    edge.notes = self._append_note(edge.notes, note)
                if state == EpistemicState.FAILED and refuted_by.strip():
                    edge.notes = self._append_note(edge.notes, REFUTED_BY_MARK + refuted_by.strip())
                if corroboration:
                    edge.notes = self._append_note(edge.notes, support_segment(*corroboration))
                if triple:
                    from .groundplan import LEAD_MARK
                    edge.notes = self._append_note(edge.notes, LEAD_MARK + " ".join(triple))
                elif withdrawn:
                    from .groundplan import LEAD_NONE
                    edge.notes = self._append_note(edge.notes, LEAD_NONE)
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
                if promoted_to == Provenance.INFERRED.value:
                    out["support"] = "unchecked-citation"
                else:
                    held = edge.source_file if kind == "edge" else self._node_support_file(node)
                    if held:
                        out["support_source"] = self._source_side(held)
            if state == EpistemicState.FAILED and refuted_by.strip():
                out["refuted_by"] = refuted_by.strip()
            if kind == "edge" and corroboration:
                out["support_source"] = self._source_side(corroboration[1])
            if triple:
                out["lead"] = " ".join(triple)
            if withdrawn:
                out["lead_withdrawn"] = " ".join(withdrawn)
            return out
        finally:
            self.canon.release_lock()

    def _promote_support(self, *, verify, apply_span, apply_note, support_span, support_note):
        """The shared §1.2-3 / PLAN-Stage-8 hypothesized→grounded promotion SKELETON (review-r5: the
        edge and node gates were ~80% identical twins): a span-less proposal earns grounding only
        with support, which UPGRADES its provenance. `support_span` (a verbatim source substring,
        placeholder-restored first) must verify via `verify` and meet MIN_SPAN_CHARS → span-present;
        else `support_note` (an external citation) → inferred; neither → `hypothesis-needs-support`.
        A span that lies only in unusable external copies (level 5, retracted, superseded) is refused
        with `support-not-usable` (0.21.0), returned as a dict naming the file and why.
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
            problem = self._support_problem(check)
            if problem:
                return None, problem
            apply_span(check)
            return Provenance.SPAN_PRESENT.value, None
        if support_note and support_note.strip():
            apply_note(support_note.strip())
            return Provenance.INFERRED.value, None
        return None, "hypothesis-needs-support"

    def _non_live_end(self, edge) -> "tuple[str, str] | None":
        """`(node id, state)` of the first end of `edge` that is a node in a non-live state (rejected, failed
        or obsolete), or None. A missing or unreadable end is not one: the promotion gate only stops a
        proposal into a node that was judged not to stand (0.17.1)."""
        for end in (slug(edge.source), slug(edge.target)):
            if not self.canon.exists(end):
                continue
            try:
                node = self.canon.read_node(end)
            except Exception:  # noqa: BLE001 — an unreadable note is reported by other paths, not here
                continue
            if node.epistemic_state.value in NON_LIVE_STATE_VALUES:
                return end, node.epistemic_state.value
        return None

    def _promote_hypothesis(self, edge, support_span: str, support_note: str):
        """The EDGE promotion gate over `_promote_support`. Source-aware (R4): the span verifies
        against the edge's named source if it has one, else any declared source — the
        not-in-ANY-source contract is unchanged (support-span-not-in-source); a promotion span just
        has to exist SOMEWHERE. Support lands on the edge's own fields: the span becomes `edge.span`
        (now citable), a citation is appended to `edge.notes`.

        The span also records its file (0.16.1). An edge that names a declared source was verified
        against that file alone and keeps it. One that names none, or an unknown file, was verified
        against any source, so it takes the first file that holds the span, the same file whose
        excerpt kg_ground_item shows. Through 0.16.0 `source_file` stayed empty, so a promoted
        hypothesis was cited without its document (the two star edges the field kg-ground of
        2026-11-14 grounded)."""
        def apply_span(check):
            edge.span = check
            edge.provenance = Provenance.SPAN_PRESENT        # upgraded: now citable
            # The file the support rests on: the named one when it holds the span at a usable level, else
            # a configured source, else the usable external copy of the highest level (0.21.0).
            held = self._support_file(check, edge.source_file)
            if held:
                edge.source_file = held
        def apply_note(note):
            edge.provenance = Provenance.INFERRED            # upgraded: asserted via external citation
            edge.notes = self._append_note(edge.notes, f"{CITATION_MARK}{note}")
        return self._promote_support(
            verify=lambda s: self.verify_set().verifies(s, source_file=edge.source_file),
            apply_span=apply_span, apply_note=apply_note,
            support_span=support_span, support_note=support_note)

    def _promote_hypothesis_node(self, node, support_span: str, support_note: str):
        """The NODE promotion gate over `_promote_support` (a generated compression node / primitive
        from the propose lane). A Node has no `span`/`notes` field, so the support is restated into
        the node BODY (the only persisted free-text — body prose may restate cited spans) rather
        than a stray span attr; the span verifies against ANY declared source. The first file that
        holds the span follows it as a `grounding source: <file>` paragraph (0.16.1), as an edge
        records its `source_file`."""
        from .groundplan import GROUNDING_SOURCE_MARK, GROUNDING_SPAN_MARK

        def apply_span(check):
            node.body = self._append_body(node.body, f"{GROUNDING_SPAN_MARK}{check}")
            held = self._support_file(check)
            if held:
                node.body = self._append_body(node.body, f"{GROUNDING_SOURCE_MARK}{held}")
            node.provenance = Provenance.SPAN_PRESENT        # upgraded: now citable
        def apply_note(note):
            node.body = self._append_body(node.body, f"{CITATION_MARK}{note}")
            node.provenance = Provenance.INFERRED            # upgraded: asserted via external citation
        return self._promote_support(
            verify=lambda s: self.verify_set().verifies(s),
            apply_span=apply_span, apply_note=apply_note,
            support_span=support_span, support_note=support_note)

    # ---- every source in a verdict (0.21.0 external sources; 0.22.0 one level and one policy for all)

    def _source_side(self, name: "str | None", vs: "SourceSet | None" = None) -> dict:
        """What a file is to a verdict, with `usable` under the project's policy (0.22.0): a configured
        source's `evidence.note_label` (class "own", its level from the policy, 4 unless set), a registered
        copy's `evidence.label` (class "external"), or ``{"class": "none"}`` for no file or one not in the set."""
        vs = vs if vs is not None else self.verify_set()
        if not name or not vs.has_file(name):
            return {"class": "none"}
        key = SourceSet._key(name)
        pol = self.evidence_policy()
        if vs.is_extra(key):
            rec = self.evidence_registry().get(key)
            return evidence_label(rec, pol.required_level) if rec is not None else {"class": "none"}
        return note_label(pol, key)

    def _usable_file(self, name: str, vs: "SourceSet | None" = None) -> bool:
        """True iff a span lying in `name` may support or refute under the project's policy."""
        return bool(self._source_side(name, vs).get("usable"))

    def _support_problem(self, span: str, vs: "SourceSet | None" = None) -> "dict | None":
        """None when `span` lies in a usable source, or in no file at all (the span checks report that); else
        the `support-not-usable` refusal naming the first file that holds it, its level and why it cannot
        support under the policy."""
        vs = vs if vs is not None else self.verify_set()
        holders = vs.files_containing(span)
        if not holders or any(self._usable_file(h, vs) for h in holders):
            return None
        return self._unusable_refusal(holders[0], vs)

    def _unusable_refusal(self, name: str, vs: "SourceSet | None" = None) -> dict:
        side = self._source_side(name, vs)
        return {"error": "support-not-usable", "source": name, "unusable": side.get("unusable", "unregistered"),
                "source_level": side.get("level"), "required_level": self.evidence_policy().required_level,
                "hint": "this project accepts support only from sources at or above its required level that are "
                        "neither unfiltered, retracted nor superseded; cite a passage from a usable source "
                        "(kg_ground_item's support_context lists them) as support_span, or leave the item "
                        "unverified and record it with kg_record_unsupported"}

    def _support_file(self, span: str, source_file: str = "", vs: "SourceSet | None" = None) -> "str | None":
        """The file a support span rests on: the named file when it holds the span and is usable, else the
        usable file of the highest level that holds it (a configured source first among equals, 0.22.0), else
        the first file that holds it. None when no file holds it."""
        vs = vs if vs is not None else self.verify_set()
        holders = vs.files_containing(span)
        if not holders:
            return None
        named = SourceSet._key(source_file) if source_file else ""
        if named in holders and self._usable_file(named, vs):
            return named
        return self._best_of(holders, vs) or holders[0]

    def _best_of(self, files: "list[str]", vs: "SourceSet | None" = None) -> "str | None":
        """The usable file of the highest level among `files` (configured sources first among equals, then
        their order), or None when none is usable."""
        vs = vs if vs is not None else self.verify_set()
        usable = [(self._source_side(f, vs)["level"], 1 if vs.is_extra(f) else 0, i, f)
                  for i, f in enumerate(files) if self._usable_file(f, vs)]
        return min(usable)[3] if usable else None

    def _span_holder(self, span: "str | None", source_file: str = "", vs: "SourceSet | None" = None) -> "str | None":
        """The file a stored span lies in: its named file when that holds it, else the first file of the
        verification set that does (configured sources first). None for no span, or a span no file holds.
        `vs` lets a loop over the canon pass one verification set instead of re-statting the sources per item."""
        if not (span and span.strip()):
            return None
        vs = vs if vs is not None else self.verify_set()
        named = SourceSet._key(source_file) if source_file else ""
        if named and vs.has_file(named) and vs.verifies(span, named):
            return named
        held = vs.files_containing(span)
        return held[0] if held else None

    def _edge_support(self, edge, vs: "SourceSet | None" = None) -> "str | None":
        """The file an edge's support rests on now: the usable file of the highest level among the file of its
        own span and the files of the passages it was grounded on (`support:` segments, 0.22.0), else the first
        of those files (unusable), else None (no span the engine can place)."""
        vs = vs if vs is not None else self.verify_set()
        files = [h for h in [self._span_holder(edge.span, edge.source_file, vs)]
                 + [self._span_holder(span, name, vs) for span, name in supports_of(edge.notes)] if h]
        if not files:
            return None
        return self._best_of(files, vs) or files[0]

    def _node_support_file(self, node, vs: "SourceSet | None" = None) -> "str | None":
        """The file a node's support rests on: the usable file of the highest level among the files of its
        promotion spans (`grounding span:` / `grounding source:` paragraphs), else the first of them, or None."""
        from .groundplan import grounding_spans
        vs = vs if vs is not None else self.verify_set()
        files = [h for span, name in grounding_spans(node.body) if (h := self._span_holder(span, name, vs))]
        if not files:
            return None
        return self._best_of(files, vs) or files[0]

    def _claim_side(self, kind: str, item, vs: "SourceSet | None" = None) -> dict:
        """Where the support of a claim about to be failed lies, for the level veto. An edge: its best support
        (`_edge_support`; "none" with no span). A node: the file of its best promotion span; a node that is not
        a hypothesis was extracted from the configured sources, so it stands at their default level; a
        hypothesis with no span (a citation, or nothing yet) has no support to protect."""
        vs = vs if vs is not None else self.verify_set()
        if kind == "edge":
            return self._source_side(self._edge_support(item, vs), vs)
        held = self._node_support_file(item, vs)
        if held:
            return self._source_side(held, vs)
        if item.provenance not in (Provenance.HYPOTHESIZED, Provenance.INFERRED):
            side = note_label(self.evidence_policy(), "")
            side.pop("file", None)
            return side
        return {"class": "none"}

    def _failed_refusal(self, kind: str, item, refuted_by: str) -> "dict | None":
        """None when `item` may be stamped failed on the refutation `refuted_by` names, else the refusal (0.21.0).

        `refuted_by` is the counter-edge whose span refutes the claim. It is required once any external
        source is registered, so a refutation can never come from a file the engine did not place; with none
        registered a failed verdict without it is accepted as through 0.20.2 (the configured sources refuting
        themselves). When given it must be an existing counter-edge (`evidence.COUNTER_RELATIONS`) touching the
        claim, with a span the engine can place, and `evidence.failed_veto` must allow its source against the
        claim's: since 0.22.0 by level alone, for every source."""
        rid = (refuted_by or "").strip()
        if not rid:
            if self.evidence_registry():
                return {"error": "failed-needs-refuted-by",
                        "hint": "external sources are registered, so a failed verdict names the counter-edge "
                                "whose span refutes the claim (refuted_by=<its id>)"}
            return None
        try:
            owner = self._owner_of_edge(rid)
        except EdgeOwnerUnreadable as e:
            return {"error": self._scrub_error(f"refuted-by unreadable: {e}"), "refuted_by": rid}
        if owner is None:
            return {"error": "refuted-by-not-found", "refuted_by": rid}
        counter = next(e for e in owner.edges if e.id == rid)
        if counter.relation not in COUNTER_RELATIONS:
            return {"error": "refuted-by-not-a-counter-edge", "refuted_by": rid,
                    "hint": f"a refutation is an edge typed {', '.join(COUNTER_RELATIONS)}"}
        ends = {slug(item.source), slug(item.target)} if kind == "edge" else {item.id}
        if kind == "edge" and counter.id == item.id:
            return {"error": "refuted-by-is-the-claim", "refuted_by": rid}
        if not ({slug(counter.source), slug(counter.target)} & ends):
            return {"error": "refuted-by-unrelated", "refuted_by": rid,
                    "hint": "the counter-edge must touch the claim it refutes"}
        vs = self.verify_set()
        refuting = self._source_side(self._span_holder(counter.span, counter.source_file, vs), vs)
        claim = self._claim_side(kind, item, vs)
        code = failed_veto(claim, refuting)
        if code:
            return {"error": code, "refuted_by": rid, "claim_source": claim, "refuting_source": refuting,
                    "hint": _VETO_HINTS.get(code, "")}
        return None

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
        # Match by slug, the key `old` already is: an endpoint stored as a label ('Meta RADAR' for
        # meta-radar, written before 0.4.6 or by hand) names the same node, and an exact match missed it.
        if slug(edge.source) == old:
            edge.source = new
        if slug(edge.target) == old:
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
        distinct edge, not the merge artifact of collapsing two nodes into one. A rename only carries what
        the canon already holds; since 0.5.2 the write boundary refuses to create a self-loop (`self-loop`),
        so one here comes from an older canon, a hand edit, or kg_merge's preserved failure memory."""
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
            # by slug, the key `frm`/`into` already are (see _rewrite_endpoints): a label-form endpoint
            # names the same node
            rewritten = (slug(e.source) == frm) or (slug(e.target) == frm)
            if slug(e.source) == frm:
                e.source = into
            if slug(e.target) == frm:
                e.target = into
            e.id = edge_id(e.source, e.relation, e.target)
            if rewritten:
                report["edges_rewritten"] += 1
                changed = True
            if slug(e.source) == slug(e.target):  # the rewrite collapsed an endpoint pair into a self-loop
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

    def kg_metrics(self, digest: bool = False) -> dict:
        """Summary counts. ``digest=True`` adds ``canon_digest`` (``_canon_digest``, 0.19.1)."""
        out = self._metric_counts()
        if digest:
            out["canon_digest"] = self._canon_digest()
        return out

    def _canon_digest(self) -> str:
        """sha256 over the canon's note files, each one's name and bytes, in name order (0.19.1). Equal
        digests mean not one note changed in between, which counts cannot say.

        /burgess:kg-perturb checks that its second construction's build left the primary canon alone, and
        through 0.19.0 it compared node and edge counts. But since 0.19.0 that build writes the graph's own
        ids, and declares those nodes with a label and body from the second text. A write that lost its
        `construction=` routing would therefore land on the primary as deduped writes, and
        `_merge_into_existing` adopts an incoming label on any note and an incoming body on an unverified
        one. Counts stay identical. The field run of 2026-11-16 (20 nodes, all the graph's) left the canon byte-identical,
        but only its session's own Bash hash could show that; the field project has no git, so an overwrite
        there could not be undone. Read from disk, never from a cache, so a write the baseline cache has not
        seen still moves it. An unreadable note is hashed by name with a marker, so a note that vanishes
        or locks mid-read moves the digest instead of raising."""
        h = hashlib.sha256()
        for p in self.canon.note_paths():
            h.update(p.name.encode("utf-8") + b"\0")
            try:
                data = p.read_bytes()
            except OSError:
                h.update(b"\0unreadable\0")
                continue
            h.update(len(data).to_bytes(8, "big"))
            h.update(data)
        return h.hexdigest()

    def _metric_counts(self) -> dict:
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

    @staticmethod
    def _span_groups(edges, texts) -> "tuple[dict[str, set[str]], set[str]]":
        """``(named, anywhere)``: the distinct normalized spans of ``edges``, grouped the way the boundary
        VERIFIED them (SourceSet.verifies). An edge whose `source_file` names a declared basename counts
        toward THAT file only (``named[basename]``), and an empty or unknown one (a single-source canon
        written before R4, an agent typo) toward any file (``anywhere``), as the lenient check accepted
        it. Pooling every edge's span across files let a short span of one document ("Sin grupo de
        control.") mark a section of ANOTHER document covered, so a resumed build would have skipped that
        section (field report on 0.4.5). Shared by kg_status's coverage and kg_build_plan's."""
        named: dict[str, set[str]] = {}
        anywhere: set[str] = set()
        for e in edges:
            sp = normalize_text(e.span) if e.span and e.span.strip() else ""
            if not sp:
                continue
            key = SourceSet._key(e.source_file) if e.source_file else ""
            (named.setdefault(key, set()) if key in texts else anywhere).add(sp)
        return named, anywhere

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
        #
        named, anywhere = self._span_groups(edges, texts)
        files, sections = [], []
        for fname, raw in texts.items():
            spans = named.get(fname, set()) | anywhere
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
        sp = self.notes_path
        origin = self._sources.notes_origin()
        try:
            files = self.source_set().basenames
        except Exception as e:  # noqa: BLE001 — a source-read hiccup still reports the path, never crashes kg_status
            return {"path": str(sp) if sp else None, "notes_from": origin, "exists": False, "files": [],
                    "note": f"source unreadable ({type(e).__name__})"}
        if sp is None and not files:
            return {"path": None, "notes_from": origin, "exists": False, "files": []}
        # `path` is where the notes are, and `notes_from` says whose choice that is (0.23.0): the project's
        # policy or the plugin's source_path. `files` is what a build reads, the registered copies marked
        # `build` included, so under build_from_notes off it no longer pairs the notes folder with those copies.
        return {"path": str(sp) if sp else None, "notes_from": origin, "exists": bool(files), "files": files,
                "builds_from": ("notes" if self.evidence_policy().build_from_notes else "registered sources")}

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

    # ---- the /kg-build plan (0.5.0) ---------------------------------------
    _NO_SOURCE = ("no source is configured: name this project's notes with /burgess:kg-sources policy "
                  "notes_path=<a folder inside the project>, or set the plugin's source_path option, which "
                  "applies to every project, then restart Claude Code")

    def kg_build_plan(self, arguments: "str | None" = "",
                      configured_wave_size: "str | int | None" = None) -> dict:
        """What `/kg-build` builds: the files, their sections, which are already covered, and the wave
        size — Step 0 of the build, which through 0.4.6 ran as a Bash block. In auto mode Claude Code
        ignores a command's `Bash` permission, so that block (and the helper scripts orchestrators wrote
        around it) went to the classifier and could stop the build on a permission prompt; an MCP tool
        the command declares runs without one (field report on 0.4.6).

        ``arguments`` is the typed `$ARGUMENTS`, verbatim: ``buildplan.parse_arguments`` splits it into
        a subset and a wave size. ``configured_wave_size`` is the `extract_wave_size` option as the
        command's own text carries it (Claude Code fills `${user_config.extract_wave_size}` when the
        command loads, and leaves the placeholder when the option is unset, which reads as unset here).
        The engine still holds no wave-size setting of its own (tests/test_manifests.py): both values
        come in as arguments, resolved by ``waves.explain_wave_size``.

        Sections follow ``sources.plan_sections``, the rule ``kg_section`` serves them by, so section N
        here is the text an extractor asking for N receives. A section is ``covered`` when a span-present
        edge attributed to its file (or to no known file, as the lenient span check allows) quotes it,
        heading included. An uncovered section carries ``edgeless`` (0.14.0, ``{at, note}``) when the ledger
        records an extraction of it that wrote no edge (``kg_record_edgeless_section``) and the section's
        text and the pack's types are still the ones that extraction read. ``sections_uncovered`` counts the
        sections to extract, uncovered and not edgeless, and ``waves`` is theirs; ``sections_edgeless``
        counts the others. Read-only and projection-free, like kg_status: it reads the canon spans, the
        source and the ledger only, and section titles and notes leave through the egress scrub.

        ``ok: false`` means do not build, with ``error`` (and ``problems`` for a subset that reaches past
        the configured source) saying why: nothing configured, nothing readable, or a subset naming files
        outside it. A subset only narrows the configured source; it never replaces it.

        ``--leads`` first on the line (0.9.0) plans the leads mode instead (``_leads_plan``): ``mode:
        "leads"`` and ``leads[]``, the sections holding the spans of rejected edges whose leads no edge has
        taken yet, covered or not, for an extractor to write those leads and nothing else."""
        args = parse_arguments(arguments)
        cfg = envconfig.clean(str(configured_wave_size)) if configured_wave_size is not None else ""
        wave, origin = explain_wave_size(args.wave_size, cfg)
        source = self._source_info()
        out = {"ok": False, "arguments": arguments or "", "subset": args.subset or None,
               "wave_size": wave, "wave_size_from": origin, "source": source}
        if args.problem:
            return {**out, "error": args.problem}
        pol = self.evidence_policy()
        if not source["exists"]:
            if not pol.build_from_notes or source.get("notes_from") == "none":
                return {**out, "error": "this project builds only from registered sources (build_from_notes is "
                                        "off, or its notes path is none), and none is registered with build: "
                                        "/burgess:kg-sources add one"}
            if source["path"] is None:
                return {**out, "error": self._NO_SOURCE}
            if source.get("notes_from") == "project":   # 0.23.0: the project's own notes path
                return {**out, "error": f"this project's notes path ({pol.notes_path}) resolves to no readable "
                                        ".md/.txt file: /burgess:kg-sources policy notes_path=<folder> names "
                                        "another, or notes_path=default goes back to the plugin's source_path"}
            return {**out, "error": "the configured source_path resolves to no readable .md/.txt file"}
        texts = self.source_set().texts
        # What extraction reads (0.22.0): the configured files unless the policy builds from registered sources
        # only, then the registered copies marked `build`, in the content set's order.
        built = [self._evidence_dir() / n for n, r in self.evidence_registry().records.items() if r.build]
        declared = (SourceSet.resolve(self.notes_path, exclude=self._evidence_dir())
                    if pol.build_from_notes else []) + built
        skipped: "list[str]" = []
        if args.subset:
            names, problems = resolve_subset(args.subset, project_dir=self.project_dir, declared=declared)
            problems += [f"{n} is in the configured source but could not be read as UTF-8 text"
                         for n in names if n not in texts]
            if problems:
                return {**out, "error": problems[0] if len(problems) == 1
                        else f"{len(problems)} problems with the subset", "problems": problems}
        else:
            names = [p.name for p in declared if p.name in texts]
            skipped = [p.name for p in declared if p.name not in texts]
        if args.leads:
            return self._scrub_egress(self._leads_plan(out, names, texts, wave))
        named, anywhere = self._span_groups([e for n in self.canon.all_nodes() for e in n.edges], texts)
        records, vocabulary = self._edgeless_sections(), vocabulary_digest(self.pack)
        files, total, uncovered, edgeless = [], 0, 0, 0
        for name in names:
            level, secs = plan_sections(texts[name])
            spans = named.get(name, set()) | anywhere
            rows = []
            for s in secs:
                norm = normalize_text(s.text)
                row = {"section": s.index, "title": s.title or "(whole file)", "chars": len(s.text),
                       "covered": any(sp in norm for sp in spans)}
                record = None if row["covered"] else records.get((name, section_digest(s.text), vocabulary))
                if record:
                    row["edgeless"] = dict(record)
                rows.append(row)
            total += len(rows)
            uncovered += sum(1 for r in rows if not r["covered"] and "edgeless" not in r)
            edgeless += sum(1 for r in rows if "edgeless" in r)
            entry = {"file": name, "heading_level": level, "sections": rows}
            if level == 3:
                entry["note"] = "the sections are this file's ### subsections: its only ## heading is its title"
            elif len(secs) == 1 and not secs[0].title:
                entry["note"] = "no heading to split at: the whole file is one section"
            files.append(entry)
        plan = {**out, "ok": True, "files": files, "sections_total": total,
                "sections_uncovered": uncovered, "sections_edgeless": edgeless, "waves": -(-uncovered // wave)}
        if skipped:
            plan["skipped"] = skipped
            plan["note"] = "skipped files could not be read as UTF-8 text"
        return self._scrub_egress(plan)

    def kg_section(self, source_file: str, section: "int | str", leads: bool = False, *,
                   construction: str | None = None, source=None) -> dict:
        """One section of the configured source, cut and egress-scrubbed by the engine: what a
        `kg-extractor` launched by `/kg-build` extracts from (0.5.0). ``source_file`` is a basename and
        ``section`` a number, both from ``kg_build_plan``; the cut is ``sources.plan_sections``, the same
        rule the plan numbered by.

        The extractor asks for its own text, so the orchestrator never copies a section into a prompt.
        Through 0.4.6 it copied each one twice (into kg_scrub, then into the launch), and on a long
        document it reached for helper scripts in Bash rather than trust its copy, which in auto mode
        meant permission prompts; a copy that changed one character also cost the section its spans. The
        text here is the source's own bytes, heading line included, through the session scrub
        (``kg_scrub``): consistent placeholders, recorded so ``kg_write`` restores a placeholder span to
        the original. ``redactions``/``categories``/``sensitivity`` are kg_scrub's, for this text.

        ``leads=True`` (0.9.0, the extractor `/kg-build --leads` launches) adds ``leads``: the pending leads
        whose rejected edge's span lies in this section (``_section_leads``).

        A read without ``leads`` is what ``kg_record_edgeless_section`` asks for (0.14.1): the engine keeps the
        digest of the text it served, and records only a section whose current text was served. A leads read
        writes a rejected claim's leads, not the section, so it never stands behind a record.

        ``construction`` and ``source`` (0.19.0, together, as on the kg_write calls that build it) serve a
        section of `/kg-perturb`'s second construction instead: see ``_construction_section``."""
        if construction or source is not None:
            if not construction or not source:
                return {"ok": False, "error": "construction and source go together: name the second "
                                              "construction and its source document, as on its kg_write calls"}
            if leads:
                return {"ok": False, "error": "leads belong to the graph's own sources, not to a second "
                                              "construction: drop leads, or drop construction and source"}
            return self._construction_section(construction, source, source_file, section)
        texts = self.source_set().texts
        name = SourceSet._key(source_file or "")
        if name not in texts:
            return {"ok": False, "error": "not a configured source file: use a file name kg_build_plan "
                                          "listed", "source_file": name, "files": list(texts)}
        try:
            idx = int(section)
        except (TypeError, ValueError):
            return {"ok": False, "error": "section must be a section number kg_build_plan listed",
                    "source_file": name}
        level, secs = plan_sections(texts[name])
        if not 1 <= idx <= len(secs):
            return {"ok": False, "error": f"{name} has {len(secs)} section(s), so there is no section {idx}",
                    "source_file": name, "of": len(secs)}
        s = secs[idx - 1]
        if not leads:
            self._sections_read.add((name, section_digest(s.text)))
        scrubbed = self.kg_scrub(s.text)
        out = {"ok": True, "source_file": name, "section": idx, "of": len(secs), "heading_level": level,
               "title": self.kg_scrub(s.title)["scrubbed"] if s.title else "(whole file)",
               "text": scrubbed["scrubbed"], "redactions": scrubbed["redactions"],
               "categories": scrubbed["categories"], "sensitivity": scrubbed["sensitivity"]}
        out.update(self._known_nodes(s.text))
        if leads:
            out["leads"] = self._section_leads(name, idx, texts)
        return out

    def _construction_section(self, construction: str, source, source_file: str, section: "int | str") -> dict:
        """One section of a second construction's source (0.19.0), for the extractor `/kg-perturb` launches.

        The construction cuts and scrubs the text itself (its own kg_section), so its own kg_write restores
        the placeholders of the spans copied from it; the read is recorded there, never in this engine, so it
        can never stand behind an edgeless record of the graph's own build. ``known_nodes`` are THIS canon's:
        the graph's nodes the section names, so the extractor can write the same concept under the graph's id.
        The ensemble step pairs the two constructions by id alone. In the field test of 2026-11-16 the second
        reading, which saw no known nodes, gave 13 of its 39 nodes an id the graph had, so 18 of its 22 edges
        could not be compared at all (`atribucion-asimetrica-de-culpa → trinquete-de-controles` against the
        graph's `asimetria-de-culpa → trinquete`)."""
        eng = self._construction_engine(construction, source)
        out = eng.kg_section(source_file, section)
        if not out.get("ok"):
            return out
        text = plan_sections(eng.source_set().texts[out["source_file"]])[1][out["section"] - 1].text
        out.update(self._known_nodes(text))
        out["construction"] = construction
        return out

    def _edgeless_sections(self) -> "dict[tuple[str, str, str], dict]":
        """The sections the ledger records an extraction of that wrote no edge (`buildplan.edgeless_records`).
        Fail-open, like the attack ledger: a missing or unreadable ledger is no record, and a bad byte only
        spoils its line. Never creates the ledger or the canon directory (the plan is read-only)."""
        try:
            with open(self.canon.root / EDGELESS_SECTIONS, encoding="utf-8", errors="replace") as f:
                return edgeless_records(f)
        except OSError:
            return {}

    def kg_record_edgeless_section(self, source_file: str, section: "int | str", note: str) -> dict:
        """Record a `/kg-build` section whose extraction wrote no edge (0.14.0), so `kg_build_plan` stops
        offering it while its text and the pack's types stay the ones that extraction read.

        ``source_file`` and ``section`` are the plan's, as for ``kg_section``; ``note`` is the extractor's
        sentence on why the section held nothing to write (a list of sources, a glossary, a checklist, or a
        relation the canon already holds with a verdict, which ``kg_write`` quarantines). A section a
        span-present edge already quotes is refused: it is covered, and the plan never offers it.

        **A record needs a read (0.14.1).** It is refused unless a ``kg_section`` call (not a leads read)
        served the section's current text since this engine started. A record says that a read of that text,
        under the current pack, found nothing to write, and the digest it stores is of the text that read
        saw. On 0.14.0 the build's orchestrator, which reads no section, offered to record 18 sections
        itself, without an extractor reading any of them (field report).

        The record goes to the ledger beside the canon (``canon.EDGELESS_SECTIONS``), one fsync'd JSON line
        under the writer lease, keyed by the digests of the section's text and of the pack's types
        (``buildplan.section_digest`` and ``vocabulary_digest``). It sets no state: no node, edge or verdict
        changes, and the nodes the extraction wrote stay. Through 0.13.6 such a section left nothing behind,
        and every later build launched an extractor for it again (field report on 0.13.6)."""
        from .atomicio import fsync_dir
        from .buildplan import MAX_EDGELESS_NOTE_CHARS, edgeless_record
        texts = self.source_set().texts
        name = SourceSet._key(source_file or "")
        if name not in texts:
            return {"ok": False, "error": "not a configured source file: use a file name kg_build_plan "
                                          "listed", "source_file": name, "files": list(texts)}
        try:
            idx = int(section)
        except (TypeError, ValueError):
            return {"ok": False, "error": "section must be a section number kg_build_plan listed",
                    "source_file": name}
        _level, secs = plan_sections(texts[name])
        if not 1 <= idx <= len(secs):
            return {"ok": False, "error": f"{name} has {len(secs)} section(s), so there is no section {idx}",
                    "source_file": name, "of": len(secs)}
        note = " ".join((note or "").split())
        if not note:
            return {"ok": False, "error": "a record carries a note saying why the section held nothing to "
                                          "write", "source_file": name, "section": idx}
        if len(note) > MAX_EDGELESS_NOTE_CHARS:
            return {"ok": False, "error": f"the note is over {MAX_EDGELESS_NOTE_CHARS} characters",
                    "source_file": name, "section": idx}
        s = secs[idx - 1]
        title = s.title or "(whole file)"
        digest = section_digest(s.text)
        if (name, digest) not in self._sections_read:
            return {"ok": False, "error": "no kg_section call since the engine started served this section's "
                                          "current text, so no read stands behind the record: nothing "
                                          "recorded. Only the extractor that read the section records it",
                    "source_file": name, "section": idx}
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR, "source_file": name, "section": idx}
        try:
            # Read the spans fresh under the lease: an edge another extractor wrote a moment ago counts.
            named, anywhere = self._span_groups([e for n in self.canon.all_nodes() for e in n.edges], texts)
            norm = normalize_text(s.text)
            if any(sp in norm for sp in named.get(name, set()) | anywhere):
                return {"ok": False, "error": "a span-present edge already quotes this section, so it is "
                                              "covered and the plan does not offer it: nothing recorded",
                        "source_file": name, "section": idx}
            at = utcnow()
            path = self.canon.root / EDGELESS_SECTIONS
            line = edgeless_record(name, idx, title, digest, vocabulary_digest(self.pack), at, note)
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                fsync_dir(path.parent)
            except OSError as e:
                return {"ok": False, "error": self._scrub_error(f"section not recorded: {e}"),
                        "source_file": name, "section": idx}
        finally:
            self.canon.release_lock()
        return self._scrub_egress({"ok": True, "source_file": name, "section": idx, "title": title, "at": at})

    # ---- the /kg-ground plan (0.7.0) -------------------------------------------------------------------
    def kg_ground_plan(self, focus: "str | None" = "", configured_wave_size: "str | int | None" = None,
                       batch_size: "int | str | None" = None, reexamine: bool = False) -> dict:
        """What `/kg-ground` verdicts, in batches for parallel grounders: the grounding loop's Stage 0, which
        through 0.6.1 the orchestrator assembled from `query_graph`. On a real canon that call returned
        300 000 characters, which Claude Code saved to a file, and the orchestrator read it with scripts run
        through Bash, which auto mode stops on permission prompts (field report on 0.6.1).

        The queue holds every `unverified` edge, in any lane, and every `unverified` HYPOTHESIZED node (a
        /kg-diverge pin or a generated proposal). An extractor's unverified nodes stay out of it: each one
        names a concept the text uses, and the claims about it are its edges, which are queued. They are
        counted in `queue.extractor_nodes_not_queued`. `focus` (the command's `$ARGUMENTS`) keeps the items
        that touch a node it names, with the word rules of `buildplan`. The order is: `[diverge]`-pinned items
        first (the FUSION Stage 4 preference), then the other hypothesized ones, then the text edges their
        extractor marked weak (`groundplan.is_weak`, counted in `queue.weak_edges`), then the other text
        edges. Inside each group the order is the source's (file, then section), so one batch covers
        contiguous text. Items are `{id, kind}` only: an edge id already names its endpoints and relation
        (`e_<source>__<relation>__<target>`), and each grounder fetches what it judges with
        `kg_ground_item`.

        A queued node goes in one batch with the queued edges that touch it, node first, and a unit larger
        than `batch_size` is a batch of its own (0.17.1, `groundplan.node_star_batches`). So one grounder
        judges a generated compression together with its star.

        A `[diverge]` pin a grounder left unverified and recorded with `kg_record_unsupported` stays out of
        the queue while the sources and the pin are the ones it was judged against (0.20.1), counted in
        `queue.unsupported_waiting`. A change to either offers it again, and so does a `focus`, as for an
        attacked hub. Through 0.20.0 every pass judged every pin again. A record made before 0.20.2, when a
        node's grounder saw no source text, does not count: the pin is offered again once.

        `reexamine=True` (0.20.2, the command's `--reexamine`) also queues the REJECTED hypothesized nodes
        the focus names (all of them with no focus), each item marked `"reexamine": true`, counted in
        `queue.reexamine`. Through 0.20.1 a node was judged without any source text, so such a rejection
        rested on the spans other edges cited; this is how the user asks for those nodes to be judged
        again with the sections `kg_ground_item` now gives a node. A failed node is not offered: it was
        refuted by a counter-span, not judged unsupported.

        Every pass also queues the REJECTED items a source changed under since they were judged (0.22.4,
        `_open_reexaminations`): the projector's re-examination flags, all of them, after everything new, each
        marked `"reexamine": true` and counted in `queue.reexaminable`, in the focus like any item. A flag no
        usable file raised is held back, counted in `queue.reexaminable_held`, as `kg_context` holds it. A flag
        a verdict has answered since is left out, read from the grounding audit log without projecting, so
        the progress probe drops an item once a grounder has judged it again, whatever the verdict. A failed
        item is not queued: its refutation stands on a counter-edge's span, which a new source does not
        remove. Through 0.22.3 the command's Stage 0c asked the orchestrator to re-check these items, and the
        orchestrator never calls kg_ground.

        `configured_wave_size` is the `extract_wave_size` option as the command text carries it (the same
        channel as `kg_build_plan`): how many grounders run at once. `batch_size` is the items per grounder,
        1–20, default 12.

        `hubs` are the adversarial grounder's candidates: at most 5 nodes with 3 or more live claims, the
        most connected first. A claim is a live edge (`model.NON_LIVE_STATE_VALUES` is not live, as on every
        other structural surface) that is not itself a counter-edge (`groundplan.attacked_hub`). A node an
        adversarial pass has attacked, with no claim grounded since, is left out and listed in
        `attacked_hubs` instead (`groundplan.already_attacked`), so each pass attacks the next hubs down the
        list and Stage 2 ends once every hub has been attacked. An attack that wrote no counter-edge counts
        once the adversarial grounder records it with `kg_record_attack` (0.10.0): the record stands for a
        counter-edge judged at its time. A `focus` skips that memory: naming a concept is how a user asks
        for a second attack on it. Through 0.7.0 the degree counted every edge, refuted ones and the
        attack's own counter-edges included, so every pass offered the same hubs again (field report on
        0.7.0). Read-only; it never projects."""
        from .groundplan import (ATTACK_RECORDED, DEFAULT_BATCH_SIZE, DIVERGE_MARK, already_attacked,
                                 attacked_hub, clamp_batch_size, focus_matches, is_weak, item_signature,
                                 node_star_batches, waits_for_sources)

        size = clamp_batch_size(batch_size) if batch_size not in (None, "") else DEFAULT_BATCH_SIZE
        cfg = envconfig.clean(str(configured_wave_size)) if configured_wave_size is not None else ""
        wave, origin = explain_wave_size("", cfg)
        nodes = list(self._canon_baseline().values())
        focus = (focus or "").strip()
        in_focus = {n.id for n in nodes if focus_matches(focus, n.id, n.label)}
        texts = self.source_set().texts
        file_rank = {name: i for i, name in enumerate(texts)}
        sections: "dict[str, list[str]]" = {}

        def position(e) -> "tuple[int, int]":
            """(file rank, section index) of the section that holds the edge's span; unknown last."""
            name = SourceSet._key(e.source_file) if e.source_file else ""
            if name in texts and e.span and e.span.strip():
                if name not in sections:
                    sections[name] = [normalize_text(s.text) for s in plan_sections(texts[name])[1]]
                nspan = normalize_text(e.span)
                for i, norm in enumerate(sections[name]):
                    if nspan in norm:
                        return file_rank[name], i
                return file_rank[name], len(sections[name])
            return len(texts), 0

        seen: "set[str]" = set()
        items: "list[tuple[tuple, str, str]]" = []
        ends: "dict[str, tuple[str, str]]" = {}   # queued edge -> its two nodes, to batch a node with its star
        degree: "Counter[str]" = Counter()        # live claims per node
        newest_claim: "dict[str, str]" = {}       # node -> when its latest grounded claim was grounded
                                                  # (verdict_at; a re-confirmation keeps it, 0.10.2)
        attacks: "dict[str, list[tuple[str, str | None]]]" = {}   # hub -> (state, verdict_at) per counter-edge
        weak_edges = 0
        # Pins a grounder judged unsupported against these sources (0.20.1) wait for the sources to change.
        # A focus skips that memory, as it does for an attacked hub: naming a pin asks for a fresh look.
        unsupported = {} if focus else self._unsupported_pins()
        current_sig = self._source_signature() if unsupported else ""
        state = self._usable_state() if unsupported else {}
        unsupported_waiting = 0

        def waits(kind: str, item) -> bool:
            return waits_for_sources(unsupported.get((kind, item.id)), current_sig, item_signature(kind, item),
                                     usable=state.get("usable"), configured_sig=state.get("configured_sig"),
                                     configured=state.get("configured"))

        for n in nodes:
            for e in n.edges:
                if e.id in seen:
                    continue
                seen.add(e.id)
                hub = attacked_hub(e.notes)
                if hub is not None:
                    attacks.setdefault(hub, []).append((e.epistemic_state.value, e.verdict_at))
                elif e.epistemic_state.value not in NON_LIVE_STATE_VALUES:
                    for end in (slug(e.source), slug(e.target)):
                        degree[end] += 1
                        if e.epistemic_state == EpistemicState.GROUNDED and e.verdict_at:
                            newest_claim[end] = max(newest_claim.get(end, ""), e.verdict_at)
                if e.epistemic_state != EpistemicState.UNVERIFIED:
                    continue
                if focus and slug(e.source) not in in_focus and slug(e.target) not in in_focus:
                    continue
                pinned = DIVERGE_MARK in (e.notes or "")
                # A recorded item waits while the sources, the policy and the item are the ones it was judged
                # against: a pin (0.20.1), or since 0.22.0 an item the policy leaves without usable support.
                if unsupported and waits("edge", e):
                    unsupported_waiting += 1
                    continue
                hypothesized = e.provenance == Provenance.HYPOTHESIZED
                weak = not hypothesized and is_weak(e.confidence, e.confidence_score)
                weak_edges += weak
                items.append(((0 if pinned else 1, 0 if hypothesized else 1, 0 if weak else 1, position(e), e.id),
                              e.id, "edge"))
                ends[e.id] = (slug(e.source), slug(e.target))
        skipped = 0
        reexamined = 0
        for n in nodes:
            if (reexamine and n.epistemic_state == EpistemicState.REJECTED and n.id in in_focus
                    and n.provenance == Provenance.HYPOTHESIZED):
                # a rejection judged again on request (0.20.2), queued with the other hypotheses
                items.append(((1, 0, 1, (len(texts), 0), n.id), n.id, "node:reexamine"))
                reexamined += 1
                continue
            if n.epistemic_state != EpistemicState.UNVERIFIED or n.id not in in_focus:
                continue
            if n.provenance != Provenance.HYPOTHESIZED:
                skipped += 1
                continue
            pinned = DIVERGE_MARK in (n.body or "")
            if unsupported and waits("node", n):
                unsupported_waiting += 1
                continue
            items.append(((0 if pinned else 1, 0, 1, (len(texts), 0), n.id), n.id, "node"))
        # Rejected items a source changed under since they were judged (0.22.4, `_open_reexaminations`), after
        # everything new, each marked `reexamine` for a grounder to judge again. Through 0.22.3 the command's
        # Stage 0c left them to the orchestrator, which never calls kg_ground, and a confirmed rejection kept
        # its flag. One held back (every file that flagged it unusable, or nothing usable at all) is counted,
        # not queued. A failed item is not queued: it was refuted by a counter-edge whose span still stands.
        reexaminable = reexaminable_held = 0
        flags = self._open_reexaminations()
        if flags:
            usable_now = set(self._usable_files())
            edge_of = {e.id: e for n in nodes for e in n.edges}
            node_of = {n.id: n for n in nodes}
            queued_ids = {i for _, i, _ in items}
            for flag in flags:
                item_id, kind = flag.get("item_id"), flag.get("kind")
                item = edge_of.get(item_id) if kind == "edge" else node_of.get(item_id)
                if item is None or item.epistemic_state != EpistemicState.REJECTED or item_id in queued_ids:
                    continue
                if kind == "edge":
                    if focus and slug(item.source) not in in_focus and slug(item.target) not in in_focus:
                        continue
                elif item_id not in in_focus:
                    continue
                files = [f for f in (flag.get("files") or []) if f]
                if not (set(files) & usable_now if files else usable_now):
                    reexaminable_held += 1
                    continue
                hypothesized = item.provenance == Provenance.HYPOTHESIZED
                where = position(item) if kind == "edge" else (len(texts), 0)
                items.append(((2, 0 if hypothesized else 1, 1, where, item_id), item_id, f"{kind}:flagged"))
                if kind == "edge":
                    ends[item_id] = (slug(item.source), slug(item.target))
                queued_ids.add(item_id)
                reexaminable += 1
        items.sort(key=lambda row: row[0])
        # No source usable at all under the policy (0.22.1): a hypothesis can be neither grounded nor rejected for
        # its level, so judging it would only repeat the verdict-less outcome, and an attack could fail nothing.
        # Both are left out and counted in `blocked`. An extracted claim stays queued: its span can still be
        # rejected for what it says. On 2026-11-22 a policy requiring level 1, with only level-4 notes and a
        # level-4 preprint, would have sent 119 pins to 10 grounders for nothing.
        pol = self.evidence_policy()
        nothing_usable = not self._usable_files()
        blocked_items = 0
        if nothing_usable:
            kept = [row for row in items if row[2] == "edge" and row[0][1] == 1]
            blocked_items = len(items) - len(kept)
            items = kept
        # A queued node goes in one batch with the queued edges that touch it, node first (0.17.1): one
        # grounder judges a generated compression and its star together, instead of parallel grounders
        # rejecting the node while grounding an edge into it.
        planned = node_star_batches([{"id": i, "kind": k.split(":")[0], "reexamine": True} if ":" in k
                                     else {"id": i, "kind": k} for _, i, k in items], ends, size)
        # attacks that wrote no counter-edge (0.10.0), each counted like a counter-edge judged at its time
        for hub, times in self._hub_attacks().items():
            attacks.setdefault(hub, []).extend((ATTACK_RECORDED, at) for at in times)
        by_id = {n.id: n for n in nodes}
        eligible = [(nid, d) for nid, d in sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))
                    if d >= 3 and (not focus or nid in in_focus)]
        # a focus names what to attack, so it is how a user asks for a second attack: memory applies without one
        done = set() if focus else {nid for nid, _ in eligible
                                    if already_attacked(attacks.get(nid, []), newest_claim.get(nid))}
        hubs = [{"id": nid, "label": by_id[nid].label if nid in by_id else nid, "degree": d}
                for nid, d in eligible if nid not in done][:5]
        # Set whenever nothing is usable (0.22.2), even when nothing was left out because every such item was
        # already waiting: the field pass of 2026-11-22 read `blocked: null` under a policy no source met.
        blocked = None
        if nothing_usable:
            blocked = {"reason": "no-usable-source", "items": blocked_items, "hubs": len(hubs),
                       "required_level": pol.required_level,
                       "hint": f"no source is usable under this project's policy (it requires level "
                               f"{pol.required_level} or better): register one with /burgess:kg-sources add, or "
                               f"lower the required level with /burgess:kg-sources policy"}
            hubs = []
        reexamined = sum(1 for _, _, k in items if k == "node:reexamine")
        return self._scrub_egress({
            "ok": True, "focus": focus or None,
            "queue": {"edges": sum(1 for _, _, k in items if k == "edge"), "weak_edges": weak_edges,
                      "nodes": sum(1 for _, _, k in items if k == "node"),
                      # rejected hypothesized nodes queued to be judged again (0.20.2, `reexamine=True`)
                      "reexamine": reexamined,
                      # rejected items a source changed under since they were judged, queued to be judged
                      # again (0.22.4), and those held back because no file that flagged them is usable
                      "reexaminable": reexaminable, "reexaminable_held": reexaminable_held,
                      "extractor_nodes_not_queued": skipped,
                      # pins judged unsupported against these sources, left out until the sources change
                      # (0.20.1); always 0 with a focus, which offers them again
                      "unsupported_waiting": unsupported_waiting,
                      # leads rejected claims carry that no edge has taken yet (0.9.0): `/kg-build --leads`
                      # writes them; the whole canon's, whatever the focus
                      "leads_pending": len(self._pending_leads(nodes))},
            "batch_size": size, "wave_size": wave, "wave_size_from": origin,
            "batches": planned, "waves": -(-len(planned) // wave), "hubs": hubs,
            "attacked_hubs": [nid for nid, _ in eligible if nid in done],
            # the configured files, for the adversarial grounder that searches them for counter-spans
            "source": self._source_info(),
            # the usable registered external sources (0.21.0), which it may search too
            "evidence": self._evidence_info(),
            # what no usable source could settle (0.22.1): left out of the batches and the hubs, or None
            "blocked": blocked})

    def _open_reexaminations(self) -> "list[dict]":
        """The re-examination flags the last projection stored (`advisory.reexaminable_verdicts`, every one,
        not the 50 the advisory shows) that no verdict has answered since (0.22.4). Read without projecting, as
        the plan reads: a verdict recorded in the grounding audit log beyond a flag's mark answers it
        (`Projector._refilter_reexaminable`), so a progress probe drops what a grounder has just judged. A flag
        stored before 0.22.4 has no mark, and counts only the verdicts recorded after the projection that
        carried it wrote the index. Fail-open: no index, or an unreadable one, is no flag."""
        from .groundaudit import audit_key, read_audit_index
        from .projector import REEX_MARK
        proj = self.projector
        try:
            if not proj.db_path.exists():
                return []
            meta = proj._read_meta()
        except Exception:  # noqa: BLE001 — an index hiccup must not break the plan
            return []
        flags = [f for f in (meta.get("reexaminable_verdicts") or []) if isinstance(f, dict) and f.get("item_id")]
        if not flags:
            return []
        audit = read_audit_index(self.canon.root / GROUND_AUDIT)
        legacy = None
        nodes = edges = None
        cache: dict = {}
        out = []
        for flag in flags:
            kind, key = flag.get("kind"), audit_key(flag.get("kind"), flag["item_id"])
            mark = flag.get(REEX_MARK)
            if not isinstance(mark, int):
                if legacy is None:
                    since = proj._index_written_at(meta)
                    legacy = audit.mark_after(since) if since else audit.size
                mark = legacy
                if audit.judged_since(key, mark):
                    continue
                # Stored before 0.22.4 and not yet re-tested by a projection: tested here by the same rule
                # (`Projector._retest_before_0_22_4`), so the plan and the next projection agree.
                if nodes is None:
                    nodes = self._canon_baseline()
                    edges = {e.id: e for n in nodes.values() for e in n.edges}
                item = nodes.get(flag["item_id"]) if kind == "node" else edges.get(flag["item_id"])
                if item is None:
                    continue
                keep, files = proj._retest_before_0_22_4(flag, item, kind, nodes, self.verify_set(), audit, cache)
                if not keep:
                    continue
                flag = {k: v for k, v in flag.items() if k != "files"}
                if files:
                    flag["files"] = files
            if not audit.judged_since(key, mark):
                out.append(flag)
        return out

    def _reexamine_view(self, kind: str, item, scrub) -> "dict | None":
        """What `kg_ground_item` adds for an item flagged for re-examination that no verdict has answered yet
        (0.22.4), or None: `reason` (why it was flagged), `files` (the sources whose changed text bears on it,
        each with its level and `usable`; empty for a flag made before 0.22.3, which names none), and
        `context`, the usable sections of those files that share the most of the item's words (of every usable
        source for a flag that names none). An edge flagged because its own span's file changed has no
        `context` here: its own `context` is that file's text now. Through 0.22.3 a proposal re-checked this way
        came with the sections where its ends' spans lie, all in the notes it had been judged against, and
        nothing from the source that flagged it."""
        from .groundplan import node_terms
        from .projector import REEX_SPAN_FILE
        flag = next((f for f in self._open_reexaminations()
                     if f.get("item_id") == item.id and f.get("kind") == kind), None)
        if flag is None:
            return None
        vs = self.verify_set()
        names = [f for f in (flag.get("files") or []) if f]
        out = {"reason": flag.get("reason"), "files": [self._source_side(f, vs) for f in names], "context": None}
        if flag.get("reason") == REEX_SPAN_FILE:
            return out
        if kind == "node":
            terms = node_terms(item.label, item.body)
        else:
            nodes = self._canon_baseline()
            src, tgt = nodes.get(slug(item.source)), nodes.get(slug(item.target))
            words = " ".join(x for x in ((src.label if src else item.source), (tgt.label if tgt else item.target)) if x)
            terms = node_terms(words, item.span or "")
        usable = [f for f in names if self._usable_file(f, vs)]
        out["context"] = self._ranked_context(terms, scrub, files=set(usable) if names else None)
        return out

    def _usable_files(self, vs: "SourceSet | None" = None) -> "list[str]":
        """The files that may support or refute anything under the project's policy, in the set's order."""
        vs = vs if vs is not None else self.verify_set()
        return [n for n in vs.basenames if self._usable_file(n, vs)]

    def _usable_state(self, vs: "SourceSet | None" = None) -> dict:
        """What the unsupported-item ledger compares (0.22.1): `usable`, the sha256 of each usable file;
        `configured`, the sha256 of each configured file; `configured_sig`, the 0.20.x source signature of the
        configured files as they are now, so a record made before 0.22.1 can be read against them."""
        vs = vs if vs is not None else self.verify_set()
        texts = vs.texts
        digest = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
        configured = [n for n in texts if not vs.is_extra(n)]
        joined = "\n".join(texts[n] for n in configured)
        return {"usable": [digest(texts[n]) for n in self._usable_files(vs)],
                "configured": [digest(texts[n]) for n in configured],
                "configured_sig": digest(joined) if joined else ""}

    def _evidence_info(self) -> dict:
        """`{path, files, notes, required_level}` for the adversarial grounder (0.21.0): `files` are the usable
        registered external sources (`{name, level, level_name, role, title}`), `notes` the configured files
        with their level and whether they may refute (0.22.0). An unusable source refutes nothing, so it is not
        offered."""
        reg, pol, vs = self.evidence_registry(), self.evidence_policy(), self.verify_set()
        files = [{"name": r.name, "level": r.level, "level_name": evidence_label(r)["level_name"],
                  "role": r.role, "title": r.title}
                 for r in reg.records.values() if not unusable_reason(r, pol.required_level)]
        notes = [{"name": n, "level": lab["level"], "usable": lab["usable"]}
                 for n in vs.basenames if not vs.is_extra(n) for lab in [note_label(pol, n)]]
        return {"path": str(self._evidence_dir()), "files": files, "notes": notes,
                "required_level": pol.required_level}

    def _hub_attacks(self) -> "dict[str, list[str]]":
        """The attacks the ledger records by hub (`groundplan.attack_records`). Fail-open, like the
        reconcile cache: a missing or unreadable ledger is no record, and a bad byte only spoils its line.
        Never creates the ledger or the canon directory (the plan is read-only)."""
        from .groundplan import attack_records
        try:
            with open(self.canon.root / HUB_ATTACKS, encoding="utf-8", errors="replace") as f:
                return attack_records(f)
        except OSError:
            return {}

    def kg_record_attack(self, hub_id: str, question: str, reason: str = "no-span") -> dict:
        """Record an adversarial attack that wrote no counter-edge (0.10.0), so `kg_ground_plan` stops
        offering the hub until it gains a newer grounded claim, as a counter-edge's mark already does.

        `question` is the falsifying question the attack ended with (the adversarial contract's Output B),
        `reason` its decline tag: `no-span` (a counter is plausible but no span states it) or `vague`. The
        record goes to the ledger beside the canon (`canon.HUB_ATTACKS`), one fsync'd JSON line under the
        writer lease. It sets no state: no node, edge or verdict changes, so it cannot vouch for the hub,
        only say that an attack found nothing to write. Through 0.9.0 such an attack left nothing behind,
        and the plan offered the hub again on every pass (field report on 0.9.0)."""
        from .atomicio import fsync_dir
        from .groundplan import ATTACK_REASONS, MAX_QUESTION_CHARS, attack_record
        if not (hub_id or "").strip():
            return {"ok": False, "error": "name the hub the attack was on"}
        hub = slug(hub_id.strip())
        reason = (reason or "").strip().lower()
        if reason not in ATTACK_REASONS:
            return {"ok": False, "error": f"invalid reason {reason!r}; expected {'|'.join(ATTACK_REASONS)}",
                    "hub": hub}
        question = " ".join((question or "").split())
        if not question:
            return {"ok": False, "error": "an attack record carries the falsifying question the attack ended "
                                          "with", "hub": hub}
        if len(question) > MAX_QUESTION_CHARS:
            return {"ok": False, "error": f"the question is over {MAX_QUESTION_CHARS} characters", "hub": hub}
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR, "hub": hub}
        try:
            if not self.canon.exists(hub):
                return {"ok": False, "error": "node not found", "hub": hub}
            at = utcnow()
            path = self.canon.root / HUB_ATTACKS
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(attack_record(hub, at, reason, question) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                fsync_dir(path.parent)
            except OSError as e:
                return {"ok": False, "error": self._scrub_error(f"attack not recorded: {e}"), "hub": hub}
        finally:
            self.canon.release_lock()
        return {"ok": True, "hub": hub, "at": at, "reason": reason}

    def _unsupported_pins(self) -> "dict[tuple[str, str], dict[str, str]]":
        """The pins the ledger records as judged unsupported (`groundplan.unsupported_records`), keyed by
        (kind, id). Fail-open like `_hub_attacks`: a missing or unreadable ledger is no record, so the pins
        are offered again. Never creates the ledger (the plan is read-only)."""
        from .groundplan import unsupported_records
        try:
            with open(self.canon.root / UNSUPPORTED_PINS, encoding="utf-8", errors="replace") as f:
                return unsupported_records(f)
        except OSError:
            return {}

    def kg_record_unsupported(self, target_id: str, kind: str = "node", note: str = "") -> dict:
        """Record that a grounder judged a `[diverge]`-pinned hypothesis and left it `unverified` for want
        of support (0.20.1), so `kg_ground_plan` leaves it out until the sources or the pin change.

        Only an `unverified`, hypothesized item whose body (a node) or notes (an edge) carry the
        `[diverge] pinned` marker can be recorded: any other item gets a verdict from `kg_ground`, so this
        can never hide an ordinary proposal from the queue. `note` says what the grounder looked for and
        did not find. The record goes to the ledger beside the canon (`canon.UNSUPPORTED_PINS`), one
        fsync'd JSON line under the writer lease, with the signatures of the current sources and of the
        pin. It sets no state: no node, edge or verdict changes. Through 0.20.0 nothing recorded such a
        judgment, and every pass judged every pin again (field pass of 2026-11-21: 120 pins, about $2.50,
        all left unverified)."""
        from .atomicio import fsync_dir
        from .groundplan import (DIVERGE_MARK, MAX_UNSUPPORTED_NOTE_CHARS, item_signature,
                                 unsupported_record)
        kind = (kind or "").strip().lower()
        if kind not in ("node", "edge"):
            return {"ok": False, "error": f"invalid kind {kind!r}; expected node|edge"}
        if not (target_id or "").strip():
            return {"ok": False, "error": "name the pin you judged"}
        item_id = slug(target_id.strip()) if kind == "node" else target_id.strip()
        note = " ".join((note or "").split())
        if not note:
            return {"ok": False, "error": "a record carries a note on what you looked for and did not find",
                    "item": item_id}
        if len(note) > MAX_UNSUPPORTED_NOTE_CHARS:
            return {"ok": False, "error": f"the note is over {MAX_UNSUPPORTED_NOTE_CHARS} characters",
                    "item": item_id}
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR, "item": item_id}
        try:
            nodes = self._canon_baseline()
            item = None
            if kind == "node":
                item = nodes.get(item_id)
                marked = item is not None and DIVERGE_MARK in (item.body or "")
            else:
                item = next((e for n in nodes.values() for e in n.edges if e.id == item_id), None)
                marked = item is not None and DIVERGE_MARK in (item.notes or "")
            if item is None:
                return {"ok": False, "error": f"{kind} not found", "item": item_id}
            if item.epistemic_state != EpistemicState.UNVERIFIED or not self._recordable(kind, item, marked):
                return {"ok": False, "item": item_id,
                        "error": "only an unverified [diverge]-pinned hypothesis, an unverified edge whose span "
                                 "lies only in sources this project does not accept, or a hypothesis while the "
                                 "notes are below the required level can be recorded as unsupported; give any "
                                 "other item its verdict with kg_ground"}
            at = utcnow()
            path = self.canon.root / UNSUPPORTED_PINS
            line = unsupported_record(kind, item_id, at, self._source_signature(),
                                      item_signature(kind, item), note, usable=self._usable_state()["usable"])
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                fsync_dir(path.parent)
            except OSError as e:
                return {"ok": False, "error": self._scrub_error(f"record not written: {e}"), "item": item_id}
        finally:
            self.canon.release_lock()
        return {"ok": True, "item": item_id, "kind": kind, "at": at}

    def _recordable(self, kind: str, item, marked: bool) -> bool:
        """Whether an unverified item may wait for new sources (`kg_record_unsupported`): a `[diverge]` pin
        (0.20.1), or, since 0.22.0, an item the policy itself leaves without usable support, which a grounder
        must leave unverified rather than reject: an edge whose own span lies only in sources the project
        does not accept, or a hypothesis while the notes, at their default level, are below the required
        level. A rejection is permanent negative memory, and "not at this level" is not "not supported"."""
        if item.provenance == Provenance.HYPOTHESIZED and marked:
            return True
        if kind == "edge" and item.span and item.span.strip():
            held = self._edge_support(item)
            return held is not None and not self._usable_file(held)
        if item.provenance == Provenance.HYPOTHESIZED:
            pol = self.evidence_policy()
            return bool(level_unusable(pol.notes_level, [], pol.required_level))
        return False

    # ---- external sources (0.21.0, evidence.py) ----------------------------------------------------------

    def _evidence_dir(self) -> Path:
        return evidence_dir(self.project_dir)

    def _is_configured_source(self, p: Path) -> bool:
        try:
            target = p.resolve()
            return any(q.resolve() == target for q in SourceSet.resolve(self.notes_path))
        except OSError:
            return False

    def kg_source_add(self, url: str = "", path: str = "", level="", role: str = "", title: str = "",
                      published: str = "", marks="", derives_from: str = "", note: str = "",
                      preview: bool = False, build=False) -> dict:
        """Register an external source (0.21.0): the engine copies it into `<project>/evidence/` and records
        its level, so a grounder may cite a verbatim span from it.

        Exactly one of `url` (http/https: the engine fetches the bytes itself, never through WebFetch, whose
        answer is a model's paraphrase) or `path` (a local .md/.markdown/.txt copied verbatim, or .html/.htm
        by the fixed rule; relative to the project). PDF is refused: convert it to Markdown and register the
        file. `preview=true` fetches or reads it and returns the title, the date the page declares, its
        metadata and the first characters, writing nothing: what to propose a level and a role from.
        Otherwise `level` (1 reviewed, 2 institutional, 3 editorial, 4 author or community, 5 unfiltered)
        and `role` (primary | secondary | tertiary) are required; `marks` (interest, corrected, retracted,
        superseded), `published` (YYYY[-MM[-DD]]; else the page's own date when it declares one),
        `derives_from` (a registered source this one repeats), `title` and `note` (why this level) are
        optional. A copy whose text is already registered is refused (`already-registered`); a URL already
        registered with other text is accepted and named in `same_url_as`, so one of the two can be marked
        superseded. The level is recorded as set by the agent (`level_by`); only a hand edit of the sidecar
        says "human". `build=true` (0.22.0) also extracts the source into the graph like a configured source,
        so `/burgess:kg-build` plans its sections and its claims carry its level. Writes only the evidence
        directory: no node, edge or verdict changes."""
        from . import evidence as ev

        url, path = (url or "").strip(), (path or "").strip()
        if bool(url) == bool(path):
            return {"ok": False, "error": "give-url-or-path", "hint": "pass exactly one of url or path"}
        edir = self._evidence_dir()
        try:
            if url:
                got = ev.fetch(url)
                copy = ev.copy_from_bytes(got.data, got.content_type, got.charset, final_url=got.final_url)
                origin = "url"
            else:
                p = Path(path).expanduser()
                if not p.is_absolute():
                    p = self.project_dir / p
                if not p.is_file():
                    return {"ok": False, "error": "file-not-found", "path": str(p)}
                if self._is_configured_source(p):
                    return {"ok": False, "error": "already-a-configured-source", "path": str(p),
                            "hint": "the configured sources are the user's own notes, outside the scale"}
                if SourceSet._inside(p, edir):
                    return {"ok": False, "error": "already-in-evidence", "path": str(p),
                            "hint": "register the original, not a file inside the evidence directory"}
                copy = ev.copy_from_file(p)
                origin = "file"
        except ev.EvidenceError as e:
            return {"ok": False, "error": e.code, "detail": e.detail}
        if preview:
            return {"ok": True, "preview": True, "url": url, "path": path, **ev.preview(copy)}
        try:
            lvl = ev.parse_level(level)
            rl = ev.parse_role(role)
            mk = ev.parse_marks(marks)
            pub = ev.parse_published(published)
            bld = ev.parse_bool(build, "bad-build")
        except ev.EvidenceError as e:
            return {"ok": False, "error": e.code, "detail": e.detail}
        reg = self.evidence_registry()
        derives_from = (derives_from or "").strip()
        if derives_from and reg.get(derives_from) is None:
            return {"ok": False, "error": "derives-from-unknown", "derives_from": derives_from,
                    "registered": sorted(reg.records)}
        text_sha = hashlib.sha256(copy.text.encode("utf-8")).hexdigest()
        dup = next((r for r in reg.records.values() if r.sha256_text == text_sha), None)
        if dup is not None:
            return {"ok": False, "error": "already-registered", "name": dup.name}
        detected = ev.page_published(copy.meta)
        name_title = (title or copy.title or "").strip()
        rec = ev.EvidenceRecord(
            name=ev.make_name(name_title, url, Path(path).stem if path else "", text_sha), title=name_title,
            url=url, final_url=copy.final_url if url else "", origin=origin, retrieved_at=utcnow(),
            published=pub or detected, published_from="caller" if pub else ("page" if detected else ""),
            level=lvl, level_by="agent", role=rl, marks=mk, derives_from=derives_from,
            note=(note or "").strip(), content_type=copy.content_type, extractor=copy.extractor,
            sha256_raw=hashlib.sha256(copy.raw).hexdigest(), build=bld)
        same_url = sorted(r.name for r in reg.records.values()
                          if url and (r.url == url or (copy.final_url and r.final_url == copy.final_url)))
        # A fetched page, or a local HTML file, keeps its raw bytes: the extraction can be redone from them.
        keep_raw = origin == "url" or copy.extractor != ev.VERBATIM
        try:
            ev.store(edir, rec, copy.text, copy.raw if keep_raw else None, copy.raw_ext)
        except OSError as e:
            return {"ok": False, "error": self._scrub_error(f"write failed: {e}")}
        out = {"ok": True, "name": rec.name, "source": evidence_label(rec, self.evidence_policy().required_level),
               "chars": len(copy.text),
               "retrieved_at": rec.retrieved_at, "published_from": rec.published_from,
               "directory": str(edir)}
        if same_url:
            out["same_url_as"] = same_url
            out["hint"] = ("this URL was registered before with other text; if this copy replaces that one, "
                           "mark the old one superseded with kg_source_set")
        return out

    def kg_source_set(self, name: str, level=None, role: "str | None" = None, marks=None,
                      published: "str | None" = None, derives_from: "str | None" = None,
                      title: "str | None" = None, note: "str | None" = None, build=None) -> dict:
        """Change the record of a registered source (0.21.0): `level`, `role`, `marks` (the whole set: "" clears
        them), `published` ("" clears it), `derives_from` ("" clears it), `title`, `note`. A parameter left out
        is unchanged. The copy itself is never rewritten. A level set here is recorded as the agent's. A change
        bears on verdicts given from now on (a source marked retracted supports nothing any more); verdicts
        already given keep their state, and kg_source_list counts those resting on an unusable source.

        `name` may also be a configured file, one of the user's notes (0.22.0): its `level`, `role`, `marks`
        and `note` are kept in the project's policy (`policy.json`); a note with no record of its own stands
        at the policy's `notes_level`. `build` (true/false) applies to a registered source: whether it is
        extracted into the graph."""
        from . import evidence as ev

        reg = self.evidence_registry()
        key = SourceSet._key((name or "").strip())
        rec = reg.get(key)
        vs = self.verify_set()
        if rec is None and key and vs.has_file(key) and not vs.is_extra(key):
            return self._note_set(key, level=level, role=role, marks=marks, note=note,
                                  others={"published": published, "derives_from": derives_from, "title": title,
                                          "build": build})
        if rec is None:
            return {"ok": False, "error": "source-not-found", "name": name, "registered": sorted(reg.records),
                    "notes": [n for n in vs.basenames if not vs.is_extra(n)]}
        changed = []
        try:
            if level is not None and str(level).strip() != "":
                lvl = ev.parse_level(level)
                if lvl != rec.level:
                    rec.level, rec.level_by = lvl, "agent"
                    changed.append("level")
            if role is not None and role.strip():
                rl = ev.parse_role(role)
                if rl != rec.role:
                    rec.role = rl
                    changed.append("role")
            if marks is not None:
                mk = ev.parse_marks(marks)
                if mk != rec.marks:
                    rec.marks = mk
                    changed.append("marks")
            if published is not None:
                pub = ev.parse_published(published)
                if pub != rec.published:
                    rec.published, rec.published_from = pub, ("caller" if pub else "")
                    changed.append("published")
        except ev.EvidenceError as e:
            return {"ok": False, "error": e.code, "detail": e.detail}
        if derives_from is not None:
            df = derives_from.strip()
            if df and (df == rec.name or reg.get(df) is None):
                return {"ok": False, "error": "derives-from-unknown", "derives_from": df,
                        "registered": sorted(n for n in reg.records if n != rec.name)}
            if df != rec.derives_from:
                rec.derives_from = df
                changed.append("derives_from")
        for field_name, value in (("title", title), ("note", note)):
            if value is not None and value.strip() != getattr(rec, field_name):
                setattr(rec, field_name, value.strip())
                changed.append(field_name)
        if build is not None and str(build).strip() != "":
            try:
                bld = ev.parse_bool(build, "bad-build")
            except ev.EvidenceError as e:
                return {"ok": False, "error": e.code, "detail": e.detail}
            if bld != rec.build:
                rec.build = bld
                changed.append("build")
        required = self.evidence_policy().required_level
        if not changed:
            return {"ok": True, "name": rec.name, "changed": [], "source": evidence_label(rec, required)}
        rec.updated_at = utcnow()
        try:
            ev.write_record(self._evidence_dir(), rec)
        except OSError as e:
            return {"ok": False, "error": self._scrub_error(f"write failed: {e}")}
        out = {"ok": True, "name": rec.name, "changed": changed, "source": evidence_label(rec, required)}
        if "build" in changed:
            out["hint"] = ("run /burgess:kg-build to extract it" if rec.build else
                           "its claims already in the graph stay; it is no longer planned for extraction")
        return out

    def _note_set(self, name: str, *, level, role, marks, note, others: dict) -> dict:
        """`kg_source_set` on a configured file (0.22.0): the record lives in the project's policy."""
        import copy as _copy
        from . import evidence as ev

        given = [k for k, v in others.items() if v is not None and str(v).strip() != ""]
        if given:
            return {"ok": False, "error": "not-for-notes", "fields": given,
                    "hint": "a configured file takes level, role, marks and note; it is your own text"}
        pol = _copy.deepcopy(self.evidence_policy())
        before = dict(pol.notes.get(name) or {})
        entry = {"level": before.get("level", pol.notes_level), "role": before.get("role", ""),
                 "marks": list(before.get("marks", [])), "note": before.get("note", ""),
                 "updated_at": before.get("updated_at", "")}
        changed = []
        try:
            if level is not None and str(level).strip() != "":
                lvl = ev.parse_level(level)
                if lvl != entry["level"] or not before:
                    entry["level"] = lvl
                    changed.append("level")
            if role is not None and role.strip():
                rl = ev.parse_role(role)
                if rl != entry["role"]:
                    entry["role"] = rl
                    changed.append("role")
            if marks is not None:
                mk = ev.parse_marks(marks)
                if mk != entry["marks"]:
                    entry["marks"] = mk
                    changed.append("marks")
        except ev.EvidenceError as e:
            return {"ok": False, "error": e.code, "detail": e.detail}
        if note is not None and note.strip() != entry["note"]:
            entry["note"] = note.strip()
            changed.append("note")
        if changed:
            entry["updated_at"] = utcnow()
            pol.notes[name] = entry
            try:
                ev.write_policy(self._evidence_dir(), pol)
            except OSError as e:
                return {"ok": False, "error": self._scrub_error(f"write failed: {e}")}
        return {"ok": True, "name": name, "changed": changed, "source": note_label(pol, name)}

    def kg_source_policy(self, required_level=None, notes_level=None, build_from_notes=None,
                         notes_path=None) -> dict:
        """Read or change the project's evidence policy (0.22.0, `evidence.Policy`, `policy.json` in the
        evidence directory). With no argument it only reads.

        `required_level` (1-4) is the worst level that may still support or refute: 4, the default, accepts
        everything but unfiltered sources; 1 accepts only peer-reviewed ones, so the notes (level 4 unless set)
        only propose claims and a claim is verified on a reviewed source's passage. `notes_level` (1-5) is the
        level of a configured file with no record of its own. `build_from_notes` (true/false) says whether the
        configured sources are extracted; false, with registered sources added with `build`, builds a graph
        from those sources alone. A change bears on verdicts from now on. A looser policy offers again the items
        waiting for sources when it makes usable a file they were not judged against; a stricter one leaves them
        waiting (0.22.1). Verdicts already given keep their state, and `on_unusable_total` counts the grounded
        claims that no longer rest on a usable source.

        `notes_path` (0.23.0) names this project's own notes: a folder, file or glob inside the project, `none`
        for no notes, or `default` for the plugin's `source_path` (the same for every project: Claude Code keeps
        plugin options per user). A path outside the project, or one of the engine's folders, is refused."""
        import copy as _copy
        from . import evidence as ev

        pol = _copy.deepcopy(self.evidence_policy())
        changed = []
        try:
            if required_level is not None and str(required_level).strip() != "":
                v = ev.parse_required_level(required_level)
                if v != pol.required_level:
                    pol.required_level = v
                    changed.append("required_level")
            if notes_level is not None and str(notes_level).strip() != "":
                v = ev.parse_level(notes_level)
                if v != pol.notes_level:
                    pol.notes_level = v
                    changed.append("notes_level")
            if build_from_notes is not None and str(build_from_notes).strip() != "":
                v = ev.parse_bool(build_from_notes, "bad-build-from-notes")
                if v != pol.build_from_notes:
                    pol.build_from_notes = v
                    changed.append("build_from_notes")
            if notes_path is not None and str(notes_path).strip() != "":
                v = ev.parse_notes_path(notes_path, self.project_dir)
                if v != pol.notes_path:
                    pol.notes_path = v
                    changed.append("notes_path")
        except ev.EvidenceError as e:
            return {"ok": False, "error": e.code, "detail": e.detail}
        if changed:
            try:
                ev.write_policy(self._evidence_dir(), pol)
            except OSError as e:
                return {"ok": False, "error": self._scrub_error(f"write failed: {e}")}
        report = self._support_report()
        out = {"ok": True, "changed": changed,
               "policy": {"required_level": pol.required_level, "notes_level": pol.notes_level,
                          "build_from_notes": pol.build_from_notes, **self._notes_where()},
               "notes": self._notes_listing(), "on_unusable_total": report["on_unusable_total"],
               "problems": list(self._sources._evidence()[3])}
        return {**out, **self._usable_summary(pol)}

    def _notes_where(self) -> dict:
        """`notes_path` as the policy stores it ("" for the plugin's source_path), `notes_from` (`project`, `none`
        or `global`) and `notes_folder`, the path the notes are read from now, or None (0.23.0)."""
        where = self.notes_path
        return {"notes_path": self.evidence_policy().notes_path, "notes_from": self._sources.notes_origin(),
                "notes_folder": str(where) if where else None}

    def _usable_summary(self, pol: "Policy | None" = None) -> dict:
        """`usable_sources`, how many files may support or refute under the policy, and, when none may, a
        `warning` saying what that means and how to change it (0.22.1)."""
        pol = pol if pol is not None else self.evidence_policy()
        n = len(self._usable_files())
        out = {"usable_sources": n}
        if n == 0:
            out["warning"] = (f"no source is usable under this policy (it requires level {pol.required_level} or "
                              "better): nothing can be grounded or refuted until a source at that level is "
                              "registered or the required level is lowered, and /burgess:kg-ground leaves the "
                              "items that need support out of its queue until then")
        return out

    def _notes_listing(self) -> "list[dict]":
        """The configured files, each with its label under the policy, whether the user set its level, its
        size, and whether it is built into the graph (0.22.0)."""
        vs, pol = self.verify_set(), self.evidence_policy()
        return [{"name": n, **note_label(pol, n), "recorded": pol.note(n)["recorded"], "chars": len(vs.for_file(n)),
                 "built": n in vs.content_names}
                for n in vs.basenames if not vs.is_extra(n)]

    def kg_source_list(self) -> dict:
        """The sources and what the grounded claims rest on (0.21.0; the notes and the policy since 0.22.0).

        `sources` are the registered external sources with their records; `notes` the configured files with
        their level (the policy's `notes_level` unless set per file), whether they are usable under the policy
        and whether they are built into the graph; `policy` the project's evidence policy. `problems` and
        `unregistered` name what the registry leaves out and why.

        `support` counts grounded edges and nodes by where their best support lies: `own` (the notes) and
        `external`, each by level, `unchecked_citation` (a support_note promotion: provenance `inferred`, which
        the engine cannot check), and `unlocated` (a span no file holds now: R3 flags those). `on_unusable` lists
        the claims whose best support is no longer usable under the policy (a source since marked retracted, or
        below a required level raised since), and `external_items` / `unchecked_items` name the claims behind
        those counts (at most 50 each). Read-only."""
        reg, pol = self.evidence_registry(), self.evidence_policy()
        vs = self.verify_set()
        sources = []
        for rec in reg.records.values():
            sources.append({"name": rec.name, **evidence_label(rec, pol.required_level),
                            "retrieved_at": rec.retrieved_at, "published_from": rec.published_from,
                            "level_by": rec.level_by, "note": rec.note, "origin": rec.origin,
                            "build": rec.build, "chars": len(vs.for_file(rec.name))})
        by_level = Counter(str(rec.level) for rec in reg.records.values())
        return {"ok": True, "directory": str(self._evidence_dir()), "sources": sources,
                "by_level": dict(sorted(by_level.items())),
                "usable": sum(1 for rec in reg.records.values() if not unusable_reason(rec, pol.required_level)),
                "notes": self._notes_listing(),
                "policy": {"required_level": pol.required_level, "notes_level": pol.notes_level,
                           "build_from_notes": pol.build_from_notes, **self._notes_where()},
                "problems": list(reg.problems) + list(self._sources._evidence()[3]),
                "unregistered": list(reg.unregistered), "support": self._support_report(),
                **self._usable_summary(pol)}

    def _support_report(self) -> dict:
        """`kg_source_list`'s `support`: where each grounded claim's best support lies, and whether it is usable
        under the policy now."""
        cap = 50
        vs = self.verify_set()
        pol = self.evidence_policy()

        def bucket() -> dict:
            return {"own": {}, "external": {}, "unchecked_citation": 0, "unlocated": 0}

        counts = {"edges": bucket(), "nodes": bucket()}
        external_items, unchecked_items, on_unusable = [], [], []

        def tally(kind: str, item_id: str, side: "dict | None", inferred: bool) -> None:
            b = counts["edges" if kind == "edge" else "nodes"]
            if side is None or side.get("class") not in ("own", "external"):
                if inferred:
                    b["unchecked_citation"] += 1
                    if len(unchecked_items) < cap:
                        unchecked_items.append({"id": item_id, "kind": kind})
                else:
                    b["unlocated"] += 1
                return
            level = str(side.get("level", "?"))
            b[side["class"]][level] = b[side["class"]].get(level, 0) + 1
            if side["class"] == "external" and len(external_items) < cap:
                external_items.append({"id": item_id, "kind": kind, "source": side.get("file", ""), "level": level})
            if not side.get("usable"):
                on_unusable.append({"id": item_id, "kind": kind, "source": side.get("file", ""),
                                    "unusable": side.get("unusable", "")})

        for n in self._canon_baseline().values():
            if n.epistemic_state == EpistemicState.GROUNDED:
                held = self._node_support_file(n, vs)
                if held:
                    side = self._source_side(held, vs)
                elif n.provenance not in (Provenance.HYPOTHESIZED, Provenance.INFERRED):
                    side = note_label(pol, "")   # extracted from the configured sources, at their default level
                else:
                    side = None
                tally("node", n.id, side, n.provenance == Provenance.INFERRED)
            for e in n.edges:
                if e.epistemic_state != EpistemicState.GROUNDED:
                    continue
                held = self._edge_support(e, vs)
                tally("edge", e.id, self._source_side(held, vs) if held else None,
                      e.provenance == Provenance.INFERRED and not (e.span and e.span.strip()))
        for b in counts.values():
            b["own"] = dict(sorted(b["own"].items()))
            b["external"] = dict(sorted(b["external"].items()))
        return {**counts, "external_items": external_items, "unchecked_items": unchecked_items,
                "on_unusable": on_unusable[:cap], "on_unusable_total": len(on_unusable)}

    def kg_ground_item(self, target_id: str, kind: str = "edge") -> dict:
        """Everything a grounder judges ONE queued item by (0.7.0), so it never reads a file.

        For an edge: the edge itself (its span among the fields), `span_in_source`, which says whether the
        span still verifies against its file now (the engine's own check, so a stale span shows as false),
        its two endpoint nodes, and `context`, the excerpt of the source section that holds the span
        (``groundplan.span_excerpt``: the paragraph and its neighbours, at most 3000 characters; rows cut out
        of a long table keep the table's header rows, 0.8.0). An edge with no span, a proposal, has no
        `context` and gets `shared_context` instead (0.18.0, ``_shared_context``): the source sections where
        both its ends are discussed, with excerpts, and the sections where each end is. A proposal whose notes
        open with a passage (0.19.0: an ensemble edge a second construction read from the source, recorded by
        kg_propose) also gets `passage` (``_passage_view``): that span, `in_source`, and the excerpt around it;
        every other edge gets `passage: null`. For a node: the node and its incident edges. An item flagged for
        re-examination that no verdict has answered gets `reexamine` (0.22.4, `_reexamine_view`): the sections
        of the sources that flagged it. All free text leaves through the SESSION scrub, the same as kg_section,
        so a support span the grounder copies back to kg_ground, placeholders included, restores and verifies.
        Read-only."""
        if kind not in ("edge", "node"):
            return {"ok": False, "error": "kind must be 'edge' or 'node'", "target_id": target_id}
        nodes = self._canon_baseline()

        def scrub(text: "str | None") -> "str | None":
            return self.kg_scrub(text)["scrubbed"] if text else text

        def view(n) -> "dict | None":
            if n is None:
                return None
            return {"id": n.id, "label": scrub(n.label), "node_type": n.node_type,
                    "provenance": n.provenance.value, "epistemic_state": n.epistemic_state.value,
                    "body": scrub((n.body or "")[:600])}

        if kind == "node":
            n = nodes.get(target_id) or nodes.get(slug(target_id or ""))
            if n is None:
                return {"ok": False, "error": "node not found", "target_id": target_id}
            incident = [{"id": e.id, "source": e.source, "relation": e.relation, "target": e.target,
                         "epistemic_state": e.epistemic_state.value}
                        for m in nodes.values() for e in m.edges
                        if n.id in (slug(e.source), slug(e.target))][:20]
            return {"ok": True, "kind": "node", "node": view(n), "edges": incident,
                    "source_context": self._node_source_context(n, scrub),
                    "reexamine": self._reexamine_view("node", n, scrub)}
        try:
            owner = self._owner_of_edge(target_id)
        except EdgeOwnerUnreadable as e:
            return {"ok": False, "error": self._scrub_error(f"node unreadable: {e}"), "target_id": target_id}
        if owner is None:
            return {"ok": False, "error": "edge not found", "target_id": target_id}
        e = next(x for x in owner.edges if x.id == target_id)
        has_span = bool(e.span and e.span.strip())
        context = self._span_context(e.span, e.source_file, scrub) if has_span else None
        shared = None if has_span else self._shared_context(e, nodes, scrub)
        passage = None if has_span else self._passage_view(e, scrub)
        # Where usable support could be (0.22.0): an edge whose own support lies in a source the policy does
        # not accept, or a proposal none of whose shared sections is usable, also gets the usable sections that
        # share the most of its words, so a grounder can verify it on another passage without reading a file.
        support = None
        vs = self.verify_set()
        if has_span:
            held = self._edge_support(e, vs)
            needs = held is not None and not self._usable_file(held, vs)
        else:
            needs = not any(s.get("source", {}).get("usable") for s in (shared or {}).get("sections", []))
        if needs:
            from .groundplan import node_terms
            src, tgt = nodes.get(slug(e.source)), nodes.get(slug(e.target))
            words = " ".join(x for x in ((src.label if src else e.source), (tgt.label if tgt else e.target)) if x)
            support = self._ranked_context(node_terms(words, e.span or ""), scrub)
        return {"ok": True, "kind": "edge",
                "edge": {"id": e.id, "source": e.source, "relation": e.relation, "target": e.target,
                         "provenance": e.provenance.value, "authored_by": e.authored_by.value,
                         "epistemic_state": e.epistemic_state.value, "confidence": e.confidence,
                         "confidence_score": e.confidence_score, "source_file": e.source_file,
                         "span": scrub(e.span), "notes": scrub(e.notes)},
                "span_in_source": self.verify_set().verifies(e.span, e.source_file) if has_span else None,
                # Where the span lies (0.21.0): a configured source ("own") or a registered external copy,
                # with its level and whether it may support at all.
                "span_source": self._source_side(self._span_holder(e.span, e.source_file, vs), vs) if has_span else None,
                "support_source": self._source_side(self._edge_support(e, vs), vs) if has_span else None,
                "source_node": view(nodes.get(slug(e.source))), "target_node": view(nodes.get(slug(e.target))),
                "context": context, "shared_context": shared, "passage": passage, "support_context": support,
                # a rejected item a source changed under since it was judged (0.22.4), or None
                "reexamine": self._reexamine_view("edge", e, scrub)}

    def _section_index(self) -> dict:
        """The units of every section of the configured sources (`groundplan.text_units`: paragraphs, and the
        lines of a long table) with the forms of their content words (`groundplan.text_forms`), for
        `_node_source_context`. `sections` holds `(file, section, units, first unit index)` in source order;
        `forms` and `owner` run over every unit. Cached on the sources' signature: a pass asks for a node's
        sections once per node, and the field corpus is 445 000 characters."""
        from .groundplan import text_forms, text_units
        sig = self._source_signature()
        cached = getattr(self, "_section_index_cache", None)
        if cached is not None and cached[0] == sig:
            return cached[1]
        # Every USABLE source (0.21.0), under the project's policy since 0.22.0: a source that can support
        # nothing (level 5, retracted, superseded, or below the required level, the notes included) is never
        # shown to a grounder as evidence. The cache key, the source signature, moves with the policy.
        texts = self.verify_set().texts
        sections, forms, owner = [], [], []
        for fname in texts:
            if not self._usable_file(fname):
                continue
            for s in plan_sections(texts[fname])[1]:
                units = text_units(s.text)
                sections.append((fname, s, units, len(forms)))
                for a, b in units:
                    forms.append(text_forms(s.text[a:b]))
                    owner.append(len(sections) - 1)
        index = {"sections": sections, "forms": forms, "owner": owner}
        self._section_index_cache = (sig, index)
        return index

    def _node_source_context(self, node, scrub) -> dict:
        """What a grounder judges a node against (0.20.2): the source sections whose best paragraph shares the
        most of the node's words, rare words weighing more (`groundplan.rank_units`), at most `NODE_SECTIONS`,
        each with the words that paragraph shares (`matched`) and the excerpt around it, cut from the source
        text itself (`groundplan.unit_excerpt`). `terms` are the node's words, from its label and body without
        its lineage and verdict lines; `sections_total` counts every section with such a paragraph.

        The paragraph is what is scored, not the section: a long section uses many common words in unrelated
        paragraphs, and on the field corpus such sections outranked the one paragraph that states a cliché.

        Through 0.20.1 a node's grounder got only the node and its incident edges. A pin or a cliché has no
        edge, so it got no source text, and could find support only among the spans other edges already
        cited. The field pass of 2026-11-21 judged 120 pins and 6 clichés that way, and its report said so."""
        from .groundplan import node_terms
        return self._ranked_context(node_terms(node.label, node.body), scrub)

    def _ranked_context(self, terms: "list[str]", scrub, files: "set | None" = None) -> dict:
        """`{terms, sections, sections_total}`: the usable sections whose best paragraph shares the most of
        `terms`, rare words weighing more (`_node_source_context`'s rule, 0.20.2), each labelled with its
        `source` (0.22.0). Also a claim's `support_context` when its own support is not usable. `files`
        (0.22.4) keeps the sections of those files only: a re-examined item's `reexamine.context`."""
        from .groundplan import NODE_SECTIONS, rank_units, unit_excerpt

        index = self._section_index()
        best: "dict[int, tuple[float, int, list[str]]]" = {}
        for score, ui, matched in rank_units(index["forms"], terms):
            sec = index["owner"][ui]
            if files is not None and index["sections"][sec][0] not in files:
                continue
            best.setdefault(sec, (score, ui, matched))
        order = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))
        # The best sections overall, then (0.21.0) up to as many more from registered external copies, so a
        # source registered for this node is never crowded out by a large set of notes. With nothing
        # registered the list is the 0.20.2 one.
        vs = self.verify_set()
        picked = order[:NODE_SECTIONS]
        chosen = {sec for sec, _ in picked}
        picked += [row for row in order if row[0] not in chosen
                   and vs.is_extra(index["sections"][row[0]][0])][:NODE_SECTIONS]
        sections = []
        for sec, (_score, ui, matched) in picked:
            fname, s, units, first = index["sections"][sec]
            sections.append({"source_file": fname, "section": s.index,
                             "title": scrub(s.title) if s.title else "(whole file)",
                             "matched": [scrub(t) for t in matched],
                             "excerpt": scrub(unit_excerpt(s.text, units, ui - first)),
                             "source": self._source_side(fname, vs)})
        return {"terms": [scrub(t) for t in terms], "sections": sections, "sections_total": len(best)}

    def _span_context(self, span: str, source_file: str, scrub) -> "dict | None":
        """The excerpt of the source section that holds ``span`` (``groundplan.span_excerpt``), in
        ``source_file`` when that is a configured file, else in the first configured file that holds it:
        ``{source_file, section, title, excerpt}``, or None when no section does. What kg_ground_item shows
        around an edge's span, and around a proposal's passage (0.19.0)."""
        from .groundplan import span_excerpt

        vs = self.verify_set()   # a span may lie in a registered external copy (0.21.0)
        texts = vs.texts
        name = SourceSet._key(source_file) if source_file else ""
        for fname in ([name] if name in texts else list(texts)):
            for s in plan_sections(texts[fname])[1]:
                excerpt = span_excerpt(s.text, span)
                if excerpt is not None:
                    return {"source_file": fname, "section": s.index,
                            "title": scrub(s.title) if s.title else "(whole file)",
                            "excerpt": scrub(excerpt), "source": self._source_side(fname, vs)}
        return None

    def _passage_view(self, edge, scrub) -> "dict | None":
        """What kg_ground_item shows of the passage a proposal's notes open with (0.19.0): the span a second
        construction wrote the edge from, `in_source` (whether it verifies against the configured sources now,
        the engine's own check), and, when it does, the section and excerpt around it. None for a proposal
        with no passage."""
        from .groundplan import passage_of

        found = passage_of(edge.notes)
        if found is None:
            return None
        span, name = found
        held = bool(self.verify_set().verifies(span, name))
        out = {"span": scrub(span), "source_file": name, "in_source": held}
        context = self._span_context(span, name, scrub) if held else None
        if context:
            out.update(context)
        return out

    def _shared_context(self, edge, nodes: dict, scrub) -> dict:
        """What a grounder judges an edge with no span against (0.18.0): the source sections where both of
        its ends are discussed.

        An end is discussed where the span of one of its live edges lies (``_span_section``: the edge's
        named file, else the first configured file that holds it), and, for a node promoted from a
        proposal, where its own grounding span lies (``groundplan.grounding_spans``). A rejected, failed or
        obsolete edge does not count: its claim about the node does not stand. ``sections`` holds the
        sections where a span of each end lies, at most ``SHARED_SECTIONS``, nearest pair first
        (``nearest_pair``: the fewest paragraphs between a span of one end and a span of the other), each with
        ``pair_excerpts``' excerpts. ``sections_total`` counts every such section, and
        ``source_node_sections`` / ``target_node_sections`` list where each end is, in source order, at most
        ``END_SECTIONS`` each, with their totals. So an empty ``sections`` says two things apart: an end with
        no section is one the engine cannot place, and two ends that each have sections but share none are
        never discussed together.

        Through 0.17.1 a proposal came with its two nodes and no source text, so whether it was judged
        against the source depended on its grounder. On the field graph of 2026-11-15 three grounders
        looked the ends up with get_node and kg_context, and a fourth judged its twelve proposals on what
        kg_ground_item gave. The one proposal that grounded that day was found in the section where both of
        its ends are discussed."""
        from .groundplan import END_SECTIONS, SHARED_SECTIONS, grounding_spans, nearest_pair, pair_excerpts

        vs = self.verify_set()   # an end's live span may lie in a registered external copy (0.21.0)
        texts = vs.texts
        rank = {name: i for i, name in enumerate(texts)}
        ends = (slug(edge.source), slug(edge.target))
        spans: "dict[str, list[tuple[str, str, str]]]" = {end: [] for end in ends}
        for m in nodes.values():
            for x in m.edges:
                if (x.id == edge.id or x.epistemic_state.value in NON_LIVE_STATE_VALUES
                        or not (x.span and x.span.strip())):
                    continue
                touched = (slug(x.source), slug(x.target))
                for end in spans:
                    if end in touched:
                        spans[end].append((x.id, x.span, x.source_file))
        cache: dict = {}
        where: "dict[str, dict[tuple[int, int], tuple[str, object, list[str]]]]" = {}
        for end in spans:
            node = nodes.get(end)
            own = [("", span, name) for span, name in grounding_spans(node.body if node is not None else "")]
            found: "dict[tuple[int, int], tuple[str, object, list[str]]]" = {}
            for _id, span, name in own + sorted(spans[end]):
                hit = self._span_section(span, name, texts, cache)
                if hit is not None:
                    fname, s = hit
                    found.setdefault((rank[fname], s.index), (fname, s, []))[2].append(span)
            where[end] = found
        a, b = ends

        def entry(fname: str, s) -> dict:
            return {"source_file": fname, "section": s.index,
                    "title": scrub(s.title) if s.title else "(whole file)", "source": self._source_side(fname, vs)}

        shared = []
        for key in set(where[a]) & set(where[b]):
            fname, s, spans_a = where[a][key]
            pair = nearest_pair(s.text, spans_a, where[b][key][2])
            shared.append(((pair is None, pair[0] if pair else 0, key), fname, s, pair))
        shared.sort(key=lambda row: row[0])
        sections = []
        for _order, fname, s, pair in shared[:SHARED_SECTIONS]:
            excerpts = pair_excerpts(s.text, pair[1], pair[2]) if pair is not None else []
            sections.append({**entry(fname, s), "excerpts": [scrub(x) for x in excerpts]})
        return {"sections": sections, "sections_total": len(shared),
                "source_node_sections": [entry(*where[a][k][:2]) for k in sorted(where[a])][:END_SECTIONS],
                "source_node_sections_total": len(where[a]),
                "target_node_sections": [entry(*where[b][k][:2]) for k in sorted(where[b])][:END_SECTIONS],
                "target_node_sections_total": len(where[b])}

    def _known_nodes(self, text: str) -> dict:
        """``{known_nodes, known_nodes_more}`` for kg_section (0.6.0): the canon nodes whose name `text`
        mentions (``buildplan.related_nodes``), as ``{id, label, node_type}``, so the extractor can reuse
        an id instead of coining a near-duplicate of a concept another section already wrote.
        ``known_nodes_more`` counts the named nodes past the cap. Read from the kg_write baseline cache
        (one canon parse per change, not per section); labels leave through the egress scrub like every
        other read. Never fatal: a canon that cannot be read yields an empty list, and the section is
        still served."""
        try:
            nodes = list(self._canon_baseline().values())
        except Exception as e:  # noqa: BLE001 — the hint is optional; the section text is what matters
            logger.debug("known_nodes skipped: canon unreadable (%s)", e)
            return {"known_nodes": [], "known_nodes_more": 0}
        degree: "Counter[str]" = Counter()
        for n in nodes:
            for e in n.edges:
                degree[slug(e.source)] += 1
                degree[slug(e.target)] += 1
        shown, total = related_nodes(text, nodes, degree=degree)
        # `untyped` (0.6.1) marks a node with no pack type: a placeholder an edge created without declaring
        # it (a node declared with an off-pack type is QUARANTINED and never reaches the canon, so in practice
        # nothing else is untyped but a hand edit). The section that defines it may declare it, which is the
        # one case the contract allows redeclaring a known node.
        listed = [{"id": n.id, "label": n.label, "node_type": n.node_type,
                   **({"untyped": True} if n.node_type == UNDECLARED_TYPE else {})} for n in shown]
        return {"known_nodes": self._scrub_egress(listed), "known_nodes_more": total - len(shown)}

    # ---- leads (0.9.0) ----------------------------------------------------------------------------------
    def _pending_leads(self, nodes) -> "list[tuple[Edge, tuple[str, str, str]]]":
        """The leads still to write, as ``(rejected edge, (head, relation, tail))``: each rejected edge's
        latest lead (``groundplan.lead_of``), unless an edge's notes open with ``lead (from <its id>)``,
        which marks the lead taken, or the lead's own edge already exists in any state. So a lead is
        written once, and a lead edge rejected in turn is failure memory like any other. A lead that a
        later change of state withdrew (`lead: none`, 0.11.1) is not offered again."""
        from .groundplan import lead_from, lead_of
        edges: "dict[str, Edge]" = {}
        for n in nodes:
            for e in n.edges:
                edges.setdefault(e.id, e)
        taken = {lead_from(e.notes) for e in edges.values()} - {None}
        out = []
        for e in edges.values():
            if e.epistemic_state != EpistemicState.REJECTED or e.id in taken:
                continue
            lead = lead_of(e.notes)
            if lead is not None and edge_id(*lead) not in edges:
                out.append((e, lead))
        return out

    @staticmethod
    def _lead_section(edge, texts: dict, cache: dict) -> "tuple[str, object] | None":
        """``(file, section)`` holding a rejected edge's span, by the rule ``kg_ground_plan`` orders spans
        with (its named file, else any configured file); None when the span verifies in no section, which
        happens once the source changed under it. ``cache`` keeps each file's normalized sections."""
        return KGEngine._span_section(edge.span, edge.source_file, texts, cache)

    @staticmethod
    def _span_section(span: str, source_file: str, texts: dict, cache: dict) -> "tuple[str, object] | None":
        """``(file, section)`` holding ``span``: the section of ``source_file`` when that is a configured
        file, else of the first configured file that holds it; None when no section does. ``cache`` keeps
        each file's normalized sections across calls."""
        if not (span and span.strip()):
            return None
        name = SourceSet._key(source_file) if source_file else ""
        nspan = normalize_text(span)
        for fname in ([name] if name in texts else list(texts)):
            if fname not in cache:
                cache[fname] = [(s, normalize_text(s.text)) for s in plan_sections(texts[fname])[1]]
            for s, norm in cache[fname]:
                if nspan in norm:
                    return fname, s
        return None

    def _leads_plan(self, out: dict, names: "list[str]", texts: dict, wave: int) -> dict:
        """``kg_build_plan`` for ``--leads``: the pending leads of the files to build, grouped by the section
        that holds each rejected edge's span, one extractor per section. ``leads[]`` carries ids only (the
        rejected edge and the lead): the extractor reads each lead's span from ``kg_section(..., leads=True)``.
        A lead whose span no longer verifies in any section goes to ``leads_unlocated``: its rejected edge has
        to be grounded again against the changed source first."""
        nodes = list(self._canon_baseline().values())
        rank = {name: i for i, name in enumerate(names)}
        groups: "dict[tuple[str, int], dict]" = {}
        unlocated: "list[str]" = []
        cache: dict = {}
        for e, lead in self._pending_leads(nodes):
            named = SourceSet._key(e.source_file) if e.source_file else ""
            if named in texts and named not in rank:
                continue  # a file the subset leaves out
            where = self._lead_section(e, texts, cache)
            if where is None:
                unlocated.append(e.id)
                continue
            fname, s = where
            if fname not in rank:
                continue
            group = groups.setdefault((fname, s.index), {"source_file": fname, "section": s.index,
                                                         "title": s.title or "(whole file)", "leads": []})
            group["leads"].append({"from_edge": e.id, "lead": " ".join(lead)})
        ordered = [groups[k] for k in sorted(groups, key=lambda k: (rank[k[0]], k[1]))]
        plan = {**out, "ok": True, "mode": "leads", "leads": ordered,
                "leads_total": sum(len(g["leads"]) for g in ordered), "waves": -(-len(ordered) // wave)}
        if unlocated:
            plan["leads_unlocated"] = unlocated
            plan["note"] = "leads_unlocated: the rejected edge's span is no longer in the source"
        return plan

    def _section_leads(self, name: str, index: int, texts: dict) -> list:
        """The pending leads whose rejected edge's span lies in section ``index`` of ``name``, for the
        extractor ``/kg-build --leads`` launches: each with that span through the SESSION scrub (the
        placeholders of kg_section's own text, so the extractor finds it there and kg_write restores it)
        and whether each end is a node the canon already holds."""
        nodes = list(self._canon_baseline().values())
        ids = {n.id for n in nodes}
        cache: dict = {}
        out = []
        for e, (head, relation, tail) in self._pending_leads(nodes):
            where = self._lead_section(e, texts, cache)
            if where is None or where[0] != name or where[1].index != index:
                continue
            out.append({"from_edge": e.id, "head": head, "relation": relation, "tail": tail,
                        "head_known": head in ids, "tail_known": tail in ids,
                        "span": self.kg_scrub(e.span)["scrubbed"]})
        return out

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
        candidates: each mechanism's own top `k`, so `all` returns up to seven times `k` before
        `_dedup_candidates` merges the pairs two mechanisms both proposed (a field run read k=12 as a
        total and its 51 candidates as k ignored, 2026-11-10). **READ-ONLY** — it never writes the canon;
        `/kg-generate` routes the candidates through the propose lane (`kg_propose`). Generate
        offensively; grounding judges later.

        When compression runs, the payload carries `compression_skipped` (0.17.0): the live compression
        nodes whose communities it did not compress again, and the existing nodes candidates' ids named,
        with their states (`generate._compression_skip`). `note` names them.

        An ensemble candidate read off a second construction is that construction's own edge, and carries
        `passage` (0.19.0): the span it was written from, with `in_source`, whether that span verifies
        against the configured sources (`_annotate_passages`). The payload then counts them in `passages`,
        and `note` says when some passage lies outside the sources, where no grounder can check it. With a
        second construction the payload also carries `ensemble` (0.19.1, `generate.ensemble_tally`): how
        each of its live edges fared, and `note` says why when none of them is new here.

        FUSION Stage 5: when `dpp` is true (default: the pack's `divergence.dpp` flag, shipped OFF),
        the SAME candidate set is reordered by hybrid-descriptor DPP (one semantic axis + graph-
        structural axes, judge-bounded quality) and a `divergence_advisory` block labels the slate.
        Purely advisory (I5): never adds/drops/mutates a candidate; grounding output is snapshot-
        proven bit-identical flag on vs off; any advisory failure keeps the donor ordering (I9)."""
        from .generate import compression_skips, ensemble_tally, resolve_mechanisms, run_generators
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
            note = ("no second construction supplied; ensemble degraded to regroup "
                    "(run /burgess:kg-perturb to supply one)")
        cands = run_generators(G, mechanism, pack=self.pack, corpus=corpus, failures=failures,
                               k=k, second_graph=G2)
        # 0.16.0: an unjudged hypothesized edge is live topology (only failure memory and `obsolete` are
        # not), so the ranks this run read include every proposal not yet through /burgess:kg-ground. On the
        # field graph of 2026-11-14 one generation's 33 proposals turned the gate on, made radar-meta a
        # structural bridge of 10 communities and raised its betweenness 13-fold. Replayed, the next run
        # bridged radar-meta to 10 more nodes and seeded pairs whose shared neighbour was an unjudged
        # compression node. Said here, not gated: generation is never gatekept (the inversion).
        unjudged = sum(1 for _, _, d in G.edges(data=True)
                       if d.get("provenance") == Provenance.HYPOTHESIZED.value
                       and d.get("epistemic_state") == EpistemicState.UNVERIFIED.value)
        if unjudged:
            note = ((note + "; ") if note else "") + (
                f"{unjudged} hypothesized edge(s) are not judged yet and count as graph structure here, so "
                "these candidates were ranked partly on earlier proposals; run /burgess:kg-ground first to "
                "rank on the judged graph")
        payload = {"mechanism": mechanism, "k": int(k), "gate_on": gate_on,
                   "unjudged_hypotheses": unjudged,
                   "count": len(cands), "candidates": [c.to_dict() for c in cands],
                   "note": note}
        passages = self._annotate_passages(payload["candidates"])
        if passages:
            payload["passages"] = passages
            if passages["outside_source"]:
                payload["note"] = ((payload["note"] + "; ") if payload["note"] else "") + (
                    f"{passages['outside_source']} ensemble candidate(s) carry a passage that is not in the "
                    "configured sources; the grounder judges against those sources only, so such a passage "
                    "cannot support the edge (add its document to the sources and /burgess:kg-build it for "
                    "that)")
        # 0.19.1: how each of the second construction's edges fared, so a slate of few or no candidates
        # explains itself (generate.ensemble_tally). The field run of 2026-11-16 got 0 candidates, an empty
        # note, and a session that scripted over the canon to learn why.
        if G2 is not None and "ensemble" in resolve_mechanisms(mechanism):
            tally = ensemble_tally(G, G2, failures=failures)
            payload["ensemble"] = tally
            told = self._ensemble_note(tally, int(k))
            if told:
                payload["note"] = ((payload["note"] + "; ") if payload["note"] else "") + told
        # 0.17.0: compression leaves out a community a live compression node was already proposed over and a
        # candidate whose id is already a node (generate._compression_skip). Said here, so a run that
        # offers no compression is not read as finding no dense community, and so nobody drops by hand
        # what the engine already dropped (the second field run's session did, 2026-11-15).
        if "compression" in resolve_mechanisms(mechanism):
            skipped = compression_skips(G)
            payload["compression_skipped"] = skipped
            parts = []
            if skipped["already_compressed"]:
                parts.append("communities a live compression node was already proposed over ("
                             + ", ".join(skipped["already_compressed"]) + ")")
            if skipped["already_proposed"]:
                parts.append("candidates whose id is already a node ("
                             + ", ".join(f"{i}: {s}" for i, s in skipped["already_proposed"].items()) + ")")
            if parts:
                payload["note"] = ((payload["note"] + "; ") if payload["note"] else "") + \
                    "compression left out " + " and ".join(parts)
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

    @staticmethod
    def _ensemble_note(tally: dict, k: int) -> str:
        """The `note` clause for an ensemble tally (0.19.1): why nothing was proposed, or that the top-k cut
        left some of the second construction's new edges out. Empty otherwise."""
        if tally["new"] > k:
            return (f"the second construction wrote {tally['new']} edge(s) between nodes this graph does not "
                    f"join; ensemble returns its top {k} (raise k for the rest)")
        if tally["new"] or tally["untyped"]:
            return ""
        if not tally["edges"]:
            return "the second construction holds no live edge, so ensemble had nothing to cross"
        parts = []
        if tally["repeated"]:
            parts.append(f"already edges of this graph: {tally['repeated']}")
        if tally["joined_otherwise"]:
            parts.append(f"joining a pair this graph joins by another edge: {tally['joined_otherwise']}")
        if tally["known_failures"]:
            ids = tally["known_failure_ids"]
            parts.append(f"known failures: {tally['known_failures']} ("
                         + ", ".join(ids[:5]) + (", …" if tally["known_failures"] > 5 else "") + ")")
        if tally["ends_missing"]:
            parts.append(f"with an end this graph does not have: {tally['ends_missing']}")
        return (f"none of the second construction's {tally['edges']} edge(s) is new here — "
                + "; ".join(parts))

    def _annotate_passages(self, candidates: list) -> "dict | None":
        """Mark each candidate's `passage` (an ensemble edge read off a second construction, 0.19.0) with
        `in_source`: whether its span verifies against the configured sources, the only text a grounder
        judges against. The span leaves through the SESSION scrub, like kg_section's text, so the
        placeholders `kg_propose` is handed back restore before it checks the span. Returns
        ``{"in_source": n, "outside_source": m}``, or None when no candidate carries a passage."""
        counts = {"in_source": 0, "outside_source": 0}
        sources = None
        for c in candidates:
            p = c.get("passage")
            if not p:
                continue
            if sources is None:
                sources = self.source_set()
            span = p.get("span") or ""
            held = bool(sources.verifies(span, p.get("source_file") or ""))
            p["in_source"] = held
            p["span"] = self.kg_scrub(span)["scrubbed"]
            counts["in_source" if held else "outside_source"] += 1
        return counts if counts["in_source"] or counts["outside_source"] else None

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
        eng._ensure_projected(views=False)   # this projection feeds kg_generate, never a view (0.15.0)
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
        fertile middle. With no ledger yet, returns an empty result with a note (never an error).

        Only a tracked node the graph holds as grounded is scored, over live edges (0.16.1,
        `harness.absorption_window`). `not_scored` maps each other tracked node to its state, or to
        `absent` when the graph no longer holds it, and the note says how many there are. `tracked`
        still counts every record in the ledger."""
        from .harness import absorption_window
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
        result, not_scored = absorption_window(data, history, now=now)
        summary = {s: sum(1 for v in result.values() if v["status"] == s)
                   for s in ("fertile", "absorbed", "isolated")}
        if not history:
            note = "no generations.json yet — run /burgess:kg-generate to start tracking the absorption window"
        elif not_scored:
            note = (f"{len(not_scored)} tracked node(s) not scored: only a node the graph holds as grounded "
                    "has an absorption window. not_scored gives each one's state (unverified = not judged "
                    "yet, absent = no longer in the graph)")
        else:
            note = ""
        return self._with_degraded({"tracked": len(result) + len(not_scored), "summary": summary,
                                    "nodes": result, "not_scored": not_scored, "note": note})

    # Longest mechanism name the absorption ledger takes; the names are short words (`compression`).
    MAX_LEDGER_MECHANISM_CHARS = 40

    def kg_record_generation(self, nodes=None) -> dict:
        """Record one `/kg-generate` run in the absorption ledger (0.17.0): advance the generation counter
        and track each node the run proposed, so `kg_absorption` can later score how long it stayed
        perturbing (§14).

        ``nodes`` maps each node id the run's `kg_propose` ACCEPTED to the mechanism that proposed it
        (``{"compression-…-1772d76d": "compression"}``). Call it once per run, after the write, even with no
        node: the counter still advances, and it is the clock every tracked window is read against. A
        recorded node gets ``{introduced_at: <the new generation>, introduced_degree: <its live degree now>,
        mechanism}``. The degree counts the node's live edges in the canon (rejected, failed and obsolete
        ones left out), as `kg_absorption` counts it in the projection. An id the canon lacks, one already
        tracked, a node that is not a proposal (its provenance is not `hypothesized`) and an entry with no
        mechanism are skipped with the reason; the rest are recorded.

        The ledger is ``derived/generations.json``, the file `kg_absorption` reads, rewritten whole and
        atomically under the writer lease. A file this engine cannot read as a ledger is left as it is, and
        nothing is recorded. It sets no state: no node, edge or verdict changes.

        Through 0.16.1, Step 4 of `/kg-generate` was a sketch the session completed with a script of its own
        run through the Bash tool. That writes outside the project, so it asked the user every time: the
        second field run's write waited nine hours for the approval (2026-11-15)."""
        from collections import Counter
        from .atomicio import atomic_write_text
        if nodes is None:
            nodes = {}
        if not isinstance(nodes, dict):
            return {"ok": False, "error": "nodes maps each node id the run proposed to the mechanism that "
                                          "proposed it, e.g. {\"<id>\": \"compression\"}"}
        if not self._try_writer_lease():
            return {"ok": False, "error": self._LOCKED_ERROR}
        try:
            path = self.projector.derived / "generations.json"
            generation, tracked = 0, {}
            if path.exists():
                try:
                    blob = json.loads(path.read_text(encoding="utf-8"))
                except (ValueError, OSError) as e:
                    return {"ok": False, "error": self._scrub_error(
                        f"derived/generations.json is not a ledger this engine can read ({e}); nothing "
                        "recorded, and the file is left as it is")}
                if isinstance(blob, dict) and "tracked" in blob:
                    generation, tracked = blob.get("generation", 0), blob["tracked"]
                elif isinstance(blob, dict):
                    # The bare {id: record} shape kg_absorption also reads: its clock is its newest record.
                    tracked = blob
                    generation = max((r.get("introduced_at", 0) for r in blob.values() if isinstance(r, dict)),
                                     default=0)
                else:
                    tracked = None  # a list, a string, a number: not a ledger
                if not (isinstance(tracked, dict) and isinstance(generation, int)
                        and not isinstance(generation, bool) and generation >= 0):
                    return {"ok": False, "error": "derived/generations.json is not a ledger this engine can "
                                                  "extend ({generation: int, tracked: {id: record}}); nothing "
                                                  "recorded, and the file is left as it is"}
            new_generation = generation + 1
            live_degree: Counter = Counter()
            for e in self.canon.all_edges():
                if e.epistemic_state.value not in NON_LIVE_STATE_VALUES:
                    live_degree[slug(e.source)] += 1
                    live_degree[slug(e.target)] += 1
            recorded: dict = {}
            skipped: dict = {}
            for raw_id, raw_mechanism in nodes.items():
                nid = slug(str(raw_id))
                mechanism = " ".join(str(raw_mechanism or "").split())
                if not mechanism or len(mechanism) > self.MAX_LEDGER_MECHANISM_CHARS:
                    skipped[nid] = "give the mechanism that proposed it, in a word"
                elif nid in tracked:
                    since = tracked[nid].get("introduced_at") if isinstance(tracked[nid], dict) else None
                    skipped[nid] = f"already tracked since generation {since}"
                elif not self.canon.exists(nid):
                    skipped[nid] = "not in the canon"
                else:
                    try:
                        node = self.canon.read_node(nid)
                    except Exception as e:  # noqa: BLE001 — one unreadable note must not stop the record
                        skipped[nid] = self._scrub_error(f"unreadable: {e}")
                        continue
                    if node.provenance != Provenance.HYPOTHESIZED:
                        skipped[nid] = f"not a proposal: its provenance is {node.provenance.value}"
                    else:
                        recorded[nid] = {"introduced_at": new_generation,
                                         "introduced_degree": live_degree.get(nid, 0),
                                         "mechanism": mechanism}
            ledger = {"generation": new_generation, "tracked": {**tracked, **recorded}}
            try:
                atomic_write_text(path, json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            except OSError as e:
                return {"ok": False, "error": self._scrub_error(f"generation not recorded: {e}")}
        finally:
            self.canon.release_lock()
        return self._scrub_egress({"ok": True, "generation": new_generation, "tracked": len(ledger["tracked"]),
                                   "recorded": recorded, "skipped": skipped})

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
    def _ensure_projected(self, *, views: bool = True) -> None:
        """Project-if-stale on the read path — and NEVER raise. A projection failure (a sqlite hiccup, a
        native-dep blowup in community detection, a corrupt derived db) must DEGRADE a read, not crash the
        tool: log it, remember the reason in `_projection_degraded`, and make sure an empty-schema'd
        derived layer exists so the read tools return canon-empty data with the degraded flag instead of
        blowing up on a missing table. Writes never come through here — kg_write/kg_propose/kg_ground/
        kg_rename touch only the canon — so projection can never block or fail a write (defense #6).

        Then, with `views` and a projection that is not degraded, it brings the human-facing views up to
        date (0.15.0, `_refresh_views`). kg_export passes `views=False`, because it renders the views it was
        asked for anyway."""
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
        if views and not self._projection_degraded:
            self._refresh_views()

    def _refresh_views(self) -> None:
        """Re-render each view `/kg-view` rendered that the projection has moved past (0.15.0), or that an
        older engine rendered (0.15.1) — and NEVER raise. Through 0.14.5 a view changed only when the user
        ran `/kg-view` again. On the field project
        (2026-11-13) the graph.html in the user's browser was three days and 48 changed canon notes old.
        Now the first projecting read after a change re-renders it: every `/kg-build` and `/kg-ground` ends
        with one (`kg_context`). The rule and its anchor live in `export.refresh_views`.

        It is skipped on a degraded projection (failed or contended), so a view is never re-rendered from
        an empty or stale derived layer. It costs three file-time reads when nothing is stale, and a render
        when something is: about 20 ms for both views on the field canon of 463 notes. A render that fails
        is logged, the old view stays, and the read is served as if nothing had happened. The views are a
        convenience; the read is the work."""
        try:
            from . import export as _export   # deferred, like kg_export's: export pulls the HTML template
            _export.refresh_views(self)
        except Exception as e:  # noqa: BLE001 — a view that cannot be re-rendered never fails the read
            logger.warning("could not re-render the graph views (%s); they stay as they were", e,
                           exc_info=True)

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
        usable = self._usable_for_reading()
        out = self._with_degraded(self._scrub_egress(self._proj.kg_context(query, budget=budget, usable=usable)))
        return self._explain_held(out)

    def _usable_for_reading(self) -> "set | None":
        """The files the evidence policy accepts, for the readers that hold back what only unusable sources
        could settle (0.22.2, 0.22.3); None on a source hiccup, so the advisory shows as before rather than
        disappearing."""
        try:
            return set(self._usable_files())
        except Exception:  # noqa: BLE001 — never hide the advisory over a source-read problem
            return None

    def _explain_held(self, out: dict) -> dict:
        """Add the policy's level and a hint to `advisory.reexaminable_held`, set by the reader when it held flags
        back: while no source is usable (0.22.2), or, for a flag that records the files that raised it, while
        every one of them is unusable (0.22.3). On 2026-11-22 a policy requiring level 1 over level-4 sources
        still listed 113 rejected items flagged when a preprint was registered; under level 2 they showed again
        because one note counted, and a pass would have re-checked them against that note for nothing."""
        adv = out.get("advisory") if isinstance(out, dict) else None
        held = adv.get("reexaminable_held") if isinstance(adv, dict) else None
        if not isinstance(held, dict):
            return out
        level = self.evidence_policy().required_level
        held["required_level"] = level
        held["hint"] = ("no source is usable under this project's policy (it requires level "
                        f"{level} or better), so none of these verdicts can change; they return once a source at "
                        "that level is registered or the level is lowered"
                        if held.get("reason") == "no-usable-source" else
                        "these items were flagged only by sources the policy does not accept now (below level "
                        f"{level}, unfiltered, retracted or superseded), so re-checking them could change nothing; "
                        "each returns once one of its sources counts")
        return out

    def kg_agenda(self, *, limit: int = 5) -> dict:
        # scrubbed like the sibling reads: the agenda's question strings embed canon labels (§1.9)
        return self._with_degraded(self._scrub_egress(self._proj.kg_agenda(limit=limit)))

    def kg_export(self, kind: str = "all") -> dict:
        """Render the human-facing artifacts (R1): a self-contained `graph.html` + `GRAPH_REPORT.md` under
        the derived dir. Read-only — projects-if-stale, then consumes only the derived layer; never writes
        the canon and never `_atomic_write`s graph.json/index.sqlite. From then on the engine keeps each
        rendered view current (0.15.0, `_refresh_views`); `views=False` here because this call renders the
        views it was asked for."""
        self._ensure_projected(views=False)
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
            if cid in _LEDGER_RESERVED or not isinstance(entry, dict):
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
            if cid in _LEDGER_RESERVED or not isinstance(entry, dict):
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
                               node_type: str = "claim", edges=None, cliche_ids=None) -> dict:
        """Materialize PINNED ideas into the graph — the EXPLICIT action (nothing enters the
        graph implicitly; kickoff Q5). Each pinned candidate becomes a node in the hypothesized
        lane via the propose door (kg_propose -> kg_write -> boundary): it lands
        `provenance=hypothesized, epistemic_state=unverified`, carrying its full lineage in the
        node body. `candidate_ids` defaults to every pin with a live session record; a pin from
        an ENDED session has no record left (I10) and is reported as skipped. Optional `edges`
        transit the SAME boundary (claimed verdicts stripped, text-claim provenance refused).

        `cliche_ids` (0.20.0) carries clichés of the session's map through the same door, each as a
        `cliche-<brief>-<id>` node whose body ends with a `[cliche] …` line instead of the pin's
        `[diverge] pinned …` one. The grounder treats it as an ordinary hypothesis: grounded with
        support, rejected without. With `cliche_ids` and no `candidate_ids`, no pin goes in. A cliché
        materialization is kept apart in the ledger (`_cliches`), so a failed cliché never joins the
        brief's discards."""
        from kg_engine.divergence.session import Session as _DSession

        sess = _DSession(project, home=self._diverge_home())
        state = sess.state
        domain = sess.domain
        spec = sess.spec
        open_axis = spec.primary_axis
        session_id = state.read_session().get("session_id", "")
        pins = state.read_pins(domain)
        cand_store = state.read_candidates()

        if candidate_ids is not None:
            wanted = [str(c) for c in candidate_ids]
        else:
            wanted = list(pins) if cliche_ids is None else []
        results: list[dict] = []
        nodes_payload: list[dict] = []
        node_for_cid: dict[str, str] = {}
        node_for_cliche: dict[str, str] = {}
        if cliche_ids is not None:
            if isinstance(cliche_ids, str):
                cliche_ids = [cliche_ids]
            mapped = {str(c.get("id")): c for c in state.read_cliches()}
            for oid in [str(c) for c in cliche_ids]:
                c = mapped.get(oid)
                if not c or not str(c.get("text") or "").strip():
                    results.append({"cliche": oid, "status": "refused",
                                    "reason": "unknown-cliche: not in this session's cliché map"})
                    continue
                text = str(c["text"]).strip()
                node_id = f"cliche-{slug(project)}-{slug(oid)}"
                label = text if len(text) <= 80 else text[:77] + "..."
                lineage = (f"[cliche] id={oid} role={c.get('role', '')} brief={project} "
                           f"session={session_id}")
                nodes_payload.append({"id": node_id, "label": label, "node_type": node_type,
                                      "body": f"{text}\n\n{lineage}\n"})
                node_for_cliche[oid] = node_id
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
        for oid, node_id in node_for_cliche.items():
            detail = by_id.get(node_id, {})
            status = detail.get("disposition", "UNKNOWN")
            results.append({"cliche": oid, "status": status, "node": node_id,
                            "reason": detail.get("reason", "")})
            if status in PERSISTED_DISPOSITIONS:
                bucket = ledger.get("_cliches")
                if not isinstance(bucket, dict):
                    bucket = ledger["_cliches"] = {}
                entry = bucket.setdefault(oid, {"nodes": []})
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
        pins_in = sum(1 for r in results if "candidate" in r and r.get("status") in PERSISTED_DISPOSITIONS)
        cliches_in = materialized_count - pins_in
        if self.notes_path is not None and pins_in:
            result["advisory"] = (
                "A source is already configured. Grounding these pins against it will correctly leave a "
                "genuinely novel idea `unverified` (novelty has no in-source span yet) — it is NOT falsified "
                "and stays recoverable in the lane. To promote a pin, gather supporting sources for it, then "
                "ground; only an actively-falsified pin folds back into this brief's discards.")
        if cliches_in:
            result["cliche_advisory"] = (
                "A cliché is an ordinary hypothesis: /burgess:kg-ground grounds it when a source supports it "
                "and rejects it when none does, into the failure memory like any proposal. It never joins "
                "this brief's discards.")
        return result


# --------------------------------------------------------------------------- MCP wiring


def adopt_shared_derived(root: "str | Path", project_data: "str | Path", project: "str | Path") -> list:
    """Carry over, once, what the shared derived layer of 0.22 and earlier held for THIS project (0.23.0): the
    names of the files copied. Through 0.22.4 every project wrote `<KG_DATA>/derived/`, so it holds the index of
    the project last opened and the /burgess:kg-generate ledger of the project that last ran it, maybe two
    different projects. Each file goes where its content belongs:

    - `index.sqlite` and `graph.json` when the index was built from this canon (its notes and the canon's agree
      by 90% or more), so its re-examination flags survive the move; else this project's first read rebuilds;
    - `generations.json` when half or more of the nodes it tracks are in this canon.

    Copies, never moves: the shared folder stays as it was, for the other projects to take their part. Nothing
    is copied over a file the project already has. Fail-silent: a failure only means a rebuild."""
    root, project_data, project = Path(root), Path(project_data), Path(project)
    legacy, target = root / envconfig.DERIVED_DIRNAME, project_data / envconfig.DERIVED_DIRNAME
    adopted: list = []
    if not legacy.is_dir():
        return adopted
    try:
        here = {q.stem for q in (project / "canon").glob("*.md")}
    except OSError:
        return adopted
    if not here:
        return adopted
    try:
        target.mkdir(parents=True, exist_ok=True)
        old_db, new_db = legacy / envconfig.INDEX_DB_NAME, target / envconfig.INDEX_DB_NAME
        if old_db.is_file() and not new_db.exists():
            # a proper file URI (percent-encoded, `file:///C:/…` on Windows), read-only: the shared folder stays as it was
            src = sqlite3.connect(old_db.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                row = src.execute("SELECT value FROM meta WHERE key='file_hashes'").fetchone()
                notes = set(json.loads(row[0])) if row and row[0] else set()
                if notes and len(notes & here) / len(notes | here) >= 0.9:
                    dst = sqlite3.connect(str(new_db))
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                    adopted.append(envconfig.INDEX_DB_NAME)
                    graph = legacy / "graph.json"
                    if graph.is_file() and not (target / "graph.json").exists():
                        shutil.copy2(graph, target / "graph.json")
                        adopted.append("graph.json")
            finally:
                src.close()
        ledger = legacy / "generations.json"
        if ledger.is_file() and not (target / "generations.json").exists():
            tracked = (json.loads(ledger.read_text(encoding="utf-8")) or {}).get("tracked") or {}
            if tracked and sum(1 for nid in tracked if nid in here) * 2 >= len(tracked):
                shutil.copy2(ledger, target / "generations.json")
                adopted.append("generations.json")
    except Exception as e:  # noqa: BLE001 — a failed adoption only costs a rebuild, never the server
        logger.warning("could not carry over the shared derived layer (%s); this project rebuilds its own", e)
    if adopted:
        logger.info("carried over from the shared derived layer for this project: %s", ", ".join(adopted))
    return adopted


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
    # Each project has its own derived layer under the plugin's data dir (0.23.0); an explicit `data` (a CLI
    # flag) is taken as given, and with no KG_DATA KGEngine defaults to <project>/DATA_DIRNAME, its own already.
    root = _clean_env("KG_DATA")
    if not data and root:
        data = envconfig.resolve_project_data_dir(project)
        adopt_shared_derived(root, data, project)
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
        primary canon — the in-session "second construction" `/burgess:kg-perturb` cross-generates against
        (§9/§15). `source` names the second source document so spans verify against IT. Omit both for the
        normal primary-canon write.

        This is the TEXT-CLAIM lane: every edge it accepts carries a span verified against the source. An
        item claiming `provenance=hypothesized` is REJECTED with `write-lane-hypothesis` — use `inferred`
        (still with a verbatim span) for a relation inferred across sentences; proposals go to kg_propose."""
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
        exactly like kg_write (§9/§15); omit both for the primary canon.
        An edge may carry the `passage` object an ensemble candidate came with (copy it unchanged): when
        its span verifies against a configured source, the proposal's notes open with it and
        kg_ground_item shows it to the grounder; otherwise nothing is kept. It is never the proposal's
        span. `passages` reports the `recorded` edge ids and the `not_recorded` ones with the reason."""
        return engine.kg_propose(payload, construction=construction, source=source)

    @mcp.tool()
    @_tool_result
    def kg_ground(target_id: str, verdict: str, kind: str = "edge", note: str = "",
                  support_span: str = "", support_note: str = "", lead: str = "",
                  refuted_by: str = "") -> dict:
        """Apply a grounding verdict (grounded|rejected|failed|obsolete) to an edge or node. Verdicts
        applied via this tool are always attributed to the agent — a human verdict cannot be forged
        through the tool surface (§1.4). To PROMOTE a hypothesized edge OR node to grounded you MUST supply
        support, which upgrades its provenance: `support_span` (a verbatim source substring → span-present)
        or `support_note` (an external citation → inferred); without either, the promotion is refused with
        `hypothesis-needs-support`. A hypothesized edge into a rejected, failed or obsolete node is refused
        with `hypothesis-into-non-live-node`: reject it instead. `note` is appended to the edge's `notes`; for kind='node' it is kept
        in the node's body as the paragraph 'verdict (<state>): <note>' (a Node has no notes field), so
        say why there too. A promotion span also records the source file it is in (an edge's
        `source_file`, a node's 'grounding source:' paragraph). `lead`, with verdict='rejected' only: the edge
        the span does state instead, as '<head-id> <relation> <tail-id>' (a pack relation; a new node gets a
        new slug id), which `/burgess:kg-build --leads` writes from the rejected edge's span; a bad lead, or one
        on an edge with no span (a proposal), is refused before any state change. A
        verdict that changes an edge's state without a lead withdraws the lead its notes held (`lead: none`,
        returned as `lead_withdrawn`). A verdict that keeps an edge's state re-confirms it: the edge keeps
        the time it entered that state, and its lead.

        Levels: every source has one (the user's notes too, 4 unless set) and the project's policy says the
        worst level that may still support or refute (kg_source_policy). Support must lie in a USABLE source,
        else `support-not-usable`. An edge that already carries its span may be grounded on another passage:
        `support_span` from a usable source, recorded beside the span (how a claim the notes state is verified
        on a reviewed source under a strict policy). `failed` takes `refuted_by`, the id of the counter-edge
        (attacked_by / confounded_by / collapses_into, touching the claim) whose span refutes it; it is
        required once any external source is registered. The level vetoes, never decides: an unusable source
        refutes nothing (`failed-by-unusable-source`) and a lower level cannot fail a higher one
        (`failed-by-lower-level`); a refused failed leaves the counter-edge standing as a visible dispute. A
        support_note promotion is recorded as an unchecked citation."""
        return engine.kg_ground(target_id, verdict, by="agent", kind=kind, note=note,
                                support_span=support_span, support_note=support_note, lead=lead,
                                refuted_by=refuted_by)

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
    def kg_metrics(digest: bool = False) -> dict:
        """Summary counts: nodes, edges, edges by epistemic state. `digest=true` adds `canon_digest`, a
        sha256 of the canon's note files (names and bytes): two equal digests mean no note changed in
        between. /burgess:kg-perturb compares it across its second construction's build, because a write that
        lost its construction routing rewrites the graph's existing nodes without changing any count."""
        # The default call keeps 0.19.0's exact shape, so anything standing in for engine.kg_metrics with
        # the old no-argument signature (tests/test_resilience.py patches it) is called as before.
        return engine.kg_metrics(digest=True) if digest else engine.kg_metrics()

    @mcp.tool()
    @_tool_result
    def kg_status() -> dict:
        """Cheap, projection-FREE status + coverage probe — confirm build progress and RESUME a partial
        build after any transport hiccup without grepping the filesystem. Reads ONLY the canon (+ source
        text for coverage); never triggers/refreshes the derived layer. Returns node/edge counts, edges
        by epistemic state, the still-`unverified` grounding-queue size, the engine-resolved `source`
        (`{path, exists, files}` — /burgess:kg-build reads the source path from HERE, not a shell env var, so a
        configured source_path is never silently ignored), and which source files/`##` sections already
        have an anchored edge. Unlike kg_metrics it never opens the derived db."""
        return engine.kg_status()

    @mcp.tool()
    @_tool_result
    def kg_build_plan(arguments: str = "", configured_wave_size: str | int | None = "") -> dict:
        """Plan a /burgess:kg-build: the configured source files to build, each file's sections (numbered, with
        title, size and whether a span-present edge already covers them), and the wave size. Pass the
        command's typed `$ARGUMENTS` VERBATIM as `arguments` — the engine splits it: an optional subset
        (a file, folder or glob inside the configured source_path) and an optional trailing wave size —
        and the `extract_wave_size` option as the command text carries it as `configured_wave_size`.
        An uncovered section marked `edgeless` had an extraction that wrote no edge from it
        (kg_record_edgeless_section), and its text and the pack's types are unchanged since: it is not
        extracted again. `sections_uncovered` and `waves` count only the sections to extract.
        `ok: false` means do not build; `error`/`problems` say why. With `--leads` first on the line, the
        plan is `mode: "leads"`: `leads[]`, the sections holding the leads rejected claims carry, one
        extractor per section. Read-only, projection-free."""
        return engine.kg_build_plan(arguments, configured_wave_size)

    @mcp.tool()
    @_tool_result
    def kg_ground_plan(focus: str = "", configured_wave_size: str | int | None = "",
                       batch_size: int | None = None, reexamine: bool = False) -> dict:
        """Plan a /burgess:kg-ground: the grounding queue (every unverified edge, and every unverified
        HYPOTHESIZED node) as compact `{id, kind}` items in batches of `batch_size` (1-20, default 12), one
        batch per kg-grounder, `wave_size` grounders at a time, plus the `hubs` for the adversarial grounder
        (the nodes with the most live claims, leaving out the `attacked_hubs` an earlier pass attacked, with a
        counter-edge or a `kg_record_attack` record, and nothing grounded since). Order: [diverge] pins, other
        hypotheses, edges marked weak, the rest. A queued node shares one batch with the queued edges that
        touch it, node first, so one grounder judges a compression and its star. Pass
        the command's `$ARGUMENTS` as `focus` (it keeps the items touching a node it names) and the
        `extract_wave_size` option as the command text carries it. `queue.leads_pending` counts the leads
        rejected claims carry that `/burgess:kg-build --leads` has yet to write. `queue.unsupported_waiting`
        counts the [diverge] pins a grounder already judged unsupported against these sources; they stay out
        until the sources or the pin change, or a focus names them. `reexamine=true` (the command's
        `--reexamine`) also queues the rejected hypothesized nodes the focus names, each item marked
        `"reexamine": true` and counted in `queue.reexamine`: a node rejected before 0.20.2 was judged without
        source text. Every pass also queues, after everything new and marked `"reexamine": true`, the rejected
        items a source changed under since they were judged (`queue.reexaminable`, the flags kg_context lists,
        all of them), leaving out those no usable source flagged (`queue.reexaminable_held`). A grounder's new
        verdict on such an item, whatever it is, answers its flag, so the item leaves the plan. Read-only."""
        return engine.kg_ground_plan(focus, configured_wave_size, batch_size, reexamine=bool(reexamine))

    @mcp.tool()
    @_tool_result
    def kg_ground_item(target_id: str, kind: str = "edge") -> dict:
        """Everything needed to judge ONE queued item, so a grounder never reads a file. For an edge: its
        fields and span, `span_in_source` (does the span still verify now), its two endpoint nodes, and
        `context`, the excerpt of the source that holds the span. An edge with no span (a proposal) gets
        `shared_context` instead: up to 3 source sections where both its ends are discussed, located by the
        spans of their live edges, each with excerpts (`sections`, nearest pair first), and the sections
        where each end is discussed (`source_node_sections`, `target_node_sections`). A proposal from
        /burgess:kg-perturb may also carry `passage`: the span a second reading of the source wrote this
        very edge from, with `in_source` (does it verify now) and, when it does, the section and `excerpt`
        around it; any other edge has `passage: null`. For a node (`kind="node"`): the node, its incident
        edges, and `source_context`: the node's `terms` and up to 3 source `sections` that share the most of
        them, rare words weighing more, each with the words it shares (`matched`) and an `excerpt` of its part
        that uses most of them. A support_span for a node is copied verbatim from one of those excerpts.
        Every excerpt and section carries `source`: the notes (`class: own`) or a registered external source,
        with its `level` and whether it is `usable` under the project's policy; an unusable one cannot
        support. An edge's `span_source` / `support_source` say where its span and its best support lie, and an
        edge whose support is not usable (or a proposal none of whose shared sections is) gets
        `support_context`: usable sections sharing its words, from which a support_span may be copied.
        An item flagged because a source changed after it was rejected, and not judged since, gets `reexamine`:
        `reason`, `files` (the sources whose changed text shares its words, each with its level and `usable`)
        and `context`, the usable sections of those files that share the most of its words (`null` for an edge
        whose own span's file changed: its `context` is that file now). Every other item has `reexamine: null`.
        Text is egress-scrubbed with the session's placeholders. Read-only."""
        return engine.kg_ground_item(target_id, kind)

    @mcp.tool()
    @_tool_result
    def kg_record_attack(hub_id: str, question: str, reason: str = "no-span") -> dict:
        """Record an adversarial attack on a hub that wrote no counter-edge, because no span in the source
        sets itself against the hub or its claims. `question` is the falsifying question the attack ended
        with; `reason` is `no-span` or `vague`. `kg_ground_plan` then leaves the hub out of `hubs` (it is
        listed in `attacked_hubs`) until it gains a newer grounded claim, as a counter-edge's mark does.
        Writes only the attack ledger beside the canon: no node, edge or verdict changes."""
        return engine.kg_record_attack(hub_id, question, reason)

    @mcp.tool()
    @_tool_result
    def kg_record_unsupported(target_id: str, kind: str = "node", note: str = "") -> dict:
        """Record that you judged an item and left it `unverified` because no usable source supports it yet:
        a `[diverge]`-pinned hypothesis, an edge whose own span lies only in sources this project does not
        accept (below its required level), or a hypothesis while the notes are below the required level.
        Call it for each such item, with a `note` on what you looked for and did not find. `kg_ground_plan`
        then leaves it out (counted in `queue.unsupported_waiting`) until the sources, the policy or the item
        change, so the next pass does not judge it again for the same answer. Refused for any other item: it
        gets its verdict from kg_ground. Writes only the ledger beside the canon: no node, edge or verdict
        changes."""
        return engine.kg_record_unsupported(target_id, kind, note)

    @mcp.tool()
    @_tool_result
    def kg_source_add(url: str = "", path: str = "", level: str = "", role: str = "", title: str = "",
                      published: str = "", marks: str = "", derives_from: str = "", note: str = "",
                      preview: bool = False, build: bool = False) -> dict:
        """Register an external source so a grounder can cite a verbatim span from it. The ENGINE copies
        it into the project's evidence/ directory: give exactly one of `url` (http/https; the engine fetches
        the page itself; never pass WebFetch output, which is a model's paraphrase) or `path` (a local
        .md/.markdown/.txt, or .html; PDF is refused: convert it to Markdown and register that file).
        `preview=true` returns the title, the date the page declares, its metadata and the first characters
        without writing anything: propose the level and role from it and let the user confirm. Then call
        again with `level` (1 reviewed: peer-reviewed; 2 institutional: official statistics, standards,
        official documentation; 3 editorial: press or publishers with an editor; 4 author or community:
        preprints, blogs, docs and posts of a company, forums, Wikipedia; 5 unfiltered: no filter, or made
        to sell, persuade or rank, which supports and refutes nothing) and `role` (primary: the origin of
        the fact; secondary: analyses and cites primaries; tertiary: summarizes without the origin).
        Optional: `marks` (comma-separated: interest, corrected, retracted, superseded), `published`
        (YYYY[-MM[-DD]]), `derives_from` (a registered source this one repeats), `title`, `note` (why this
        level), `build` (true: also extract it into the graph like a configured source, so the graph can be
        built from such sources; /burgess:kg-build plans it). The level measures the filter the text passed,
        never whether a claim is true. Registering a source the policy accepts wakes the items waiting for new
        sources; one it does not accept leaves them waiting. Writes only the evidence directory."""
        return engine.kg_source_add(url=url, path=path, level=level, role=role, title=title,
                                    published=published, marks=marks, derives_from=derives_from, note=note,
                                    preview=bool(preview), build=bool(build))

    @mcp.tool()
    @_tool_result
    def kg_source_list() -> dict:
        """The registered external sources (name, title, url, level, role, marks, usable, build, dates), the
        user's notes with their level and whether they are usable and built, the project's `policy`, the
        files the registry leaves out and why (`problems`: an edited copy, a missing text, a bad policy;
        `unregistered`: a text with no record), and `support`: how many grounded edges and nodes rest on the
        notes and on external sources, each by level, or on an unchecked citation, with the claims whose
        support is no longer usable under the policy (`on_unusable`). Read-only."""
        return engine.kg_source_list()

    @mcp.tool()
    @_tool_result
    def kg_source_set(name: str, level: str | None = None, role: str | None = None, marks: str | None = None,
                      published: str | None = None, derives_from: str | None = None,
                      title: str | None = None, note: str | None = None, build: bool | None = None) -> dict:
        """Change a source's record: `level`, `role`, `marks` (the whole set, comma-separated; "" clears
        them), `note`, and for a registered source also `published` ("" clears it), `derives_from` ("" clears
        it), `title` and `build` (whether it is extracted into the graph). `name` is a registered source
        (`ext-….md`) or one of the user's configured notes (its basename): a note's record lives in the
        project's policy. Left out means unchanged. A copy itself is never rewritten. A change bears on
        verdicts from now on (a source marked retracted, superseded, or below the required level supports
        and refutes nothing); verdicts already given keep their state, and kg_source_list names those now
        resting on an unusable source."""
        return engine.kg_source_set(name, level=level, role=role, marks=marks, published=published,
                                    derives_from=derives_from, title=title, note=note, build=build)

    @mcp.tool()
    @_tool_result
    def kg_source_policy(required_level: int | None = None, notes_level: int | None = None,
                         build_from_notes: bool | None = None, notes_path: str | None = None) -> dict:
        """Read (no arguments) or change the project's evidence policy. `required_level` (1-4): the worst
        level that may still support or refute; 4 (default) accepts everything but unfiltered sources, 1
        only peer-reviewed ones, so the notes only propose and claims are verified on reviewed sources'
        passages. `notes_level` (1-5): the level of a note with no record of its own (default 4: a text by an
        author nobody reviewed). `build_from_notes` (true/false): whether the configured notes are extracted
        into the graph; false, with sources registered with `build`, builds a graph from those sources
        alone. A change applies to verdicts from now on. Only a looser policy that makes usable a file the
        waiting items were not judged against offers them again; a stricter one never does. `on_unusable_total`
        counts grounded claims that no longer rest on a usable source. `notes_path` names THIS project's notes:
        a folder, file or glob inside the project, `none` for no notes, or `default` for the plugin's
        source_path, which is the same for every project; a path outside the project is refused. The result's
        `policy` says where the notes are read from (`notes_from`: project, none or global; `notes_folder`)."""
        return engine.kg_source_policy(required_level=required_level, notes_level=notes_level,
                                       build_from_notes=build_from_notes, notes_path=notes_path)

    @mcp.tool()
    @_tool_result
    def kg_section(source_file: str, section: int, leads: bool = False,
                   construction: str | None = None, source: str | None = None) -> dict:
        """The text of ONE section to extract, cut from the configured source and egress-scrubbed by the
        engine: `source_file` and `section` come from kg_build_plan. Returns `text` (the section's heading
        line and body, verbatim but for ⟦CAT:N⟧ placeholders), its `title`, `of` (how many sections the
        file has), and `known_nodes`, the canon nodes the section names. Copy spans from `text` exactly,
        placeholders included — kg_write restores them to the original. `leads=true` (for
        `/burgess:kg-build --leads`) adds `leads`: the edges grounders found stated by spans of this section
        under claims they rejected, each with that span.
        `construction` + `source` (for /burgess:kg-perturb, the same two values as on every kg_write of that
        second construction) serve section `section` of that construction's source document instead
        (`source_file` is its basename), cut and scrubbed by the construction so its kg_write restores the
        placeholders, with `known_nodes` from the graph's own canon: write the same concept under the
        graph's id. Not with `leads`."""
        return engine.kg_section(source_file, section, leads, construction=construction, source=source)

    @mcp.tool()
    @_tool_result
    def kg_record_edgeless_section(source_file: str, section: int, note: str) -> dict:
        """Record that extracting ONE /burgess:kg-build section wrote no edge, because nothing in it states a
        relation the pack's types can carry (a list of sources, a glossary, a checklist), or because every
        relation it states is an edge the canon already holds with a verdict (kg_write QUARANTINED it as
        collapses-into-known-failure or collapses-into-known-verdict). For the extractor that read the
        section: refused unless kg_section served the section's current text since the engine started.
        `source_file` and `section` are the plan's, as for kg_section; `note` says in a sentence why.
        kg_build_plan then marks the section `edgeless` and leaves it out of the sections to extract, while
        its text and the pack's types stay the same. Refused for a section a span-present edge already
        quotes. Writes only the ledger beside the canon: no node, edge or verdict changes."""
        return engine.kg_record_edgeless_section(source_file, section, note)

    @mcp.tool()
    @_tool_result
    def kg_generate(mechanism: str = "bridge", k: int = 10, second_graph: str | None = None,
                    dpp: bool | None = None, second_construction: str | None = None) -> dict:
        """Generate hypothesized idea candidates from the graph's structure (PLAN Stage 3). Mechanisms:
        bridge (§2/§4), seed (§3 residual), compression (§7 new nodes), regroup (§8), transplant (§5),
        ensemble (§9), periphery (§5 low-degree sources) — or "all"/"default". `k` is per mechanism: each
        one surfaces its own top k, so "all" returns up to seven times k, fewer once duplicates merge.
        READ-ONLY: candidates are proposals (provenance=hypothesized, no span); route them through
        kg_propose. Generate offensively; kg_ground judges later.
        A compression candidate (kind "node") carries `members` and `id`: write the node under that id
        and one `collapses_into` edge from each member to it. `unjudged_hypotheses` counts the
        hypothesized edges not yet judged; they count as structure, so when it is above 0 the slate was
        ranked partly on earlier proposals and `note` says to run /burgess:kg-ground first.
        Compression never offers a community a live compression node was already proposed over (at
        least half of its other members have a collapses_into edge into it), nor a
        candidate whose id is already a node (judged or not): when compression runs,
        `compression_skipped` lists both ({already_compressed: [ids], already_proposed: {id: state}})
        and `note` names them. Hand on every candidate returned; there is nothing left to drop.
        For the `ensemble` exo move, supply EITHER `second_construction` (the NAME of an in-session
        second construction built via kg_write(..., construction=…) — projected here, key-free) OR
        `second_graph` (a path to a pre-built graph.json); with neither, ensemble degrades to `regroup`
        and says so. An ensemble candidate is the edge the second construction wrote between two nodes
        not adjacent here, with its relation and direction, and `passage`: the span it was written from,
        with `in_source` (does that span verify against the configured sources, which are all a grounder
        judges against); `passages` counts them. Pass `passage` on to kg_propose unchanged. A pair whose
        second-graph edge records no relation stays a plain `bridges` with no passage. With a second
        construction, `ensemble` says how each of its live edges fared (they sum to `edges`): `ends_missing`
        (an end not in this graph), `repeated` (this very edge is live here), `joined_otherwise` (the pair
        is joined here by another edge), `untyped`, `known_failures` with `known_failure_ids`, and `new`
        (proposed, before the top-k cut); `note` says why when nothing is new. Report it from there.
        `dpp` (FUSION Stage 5; default = the pack's `divergence.dpp` flag, shipped OFF)
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
        Reads derived/generations.json (written by /burgess:kg-generate). Prefer the fertile middle.
        Only a tracked node the graph holds as grounded is scored, and degrees count live edges only
        (rejected, failed and obsolete edges left out). `not_scored` maps every other tracked node to
        its state (unverified = not judged yet, rejected, failed, obsolete) or to `absent`."""
        return engine.kg_absorption()

    @mcp.tool()
    @_tool_result
    def kg_record_generation(nodes: dict[str, str] | None = None) -> dict:
        """Record one /burgess:kg-generate run in the absorption ledger that kg_absorption reads
        (derived/generations.json): advance the generation counter and track each node the run's
        kg_propose ACCEPTED, given as {"<node id>": "<mechanism that proposed it>"}, at its current live
        degree. Call it once per run, after the write, even with no node (the counter still advances). An
        id the canon lacks, one already tracked, a node whose provenance is not hypothesized and an entry
        with no mechanism are skipped with the reason. Returns {ok, generation, tracked, recorded,
        skipped}. Writes only the ledger: no node, edge or verdict changes."""
        return engine.kg_record_generation(nodes)

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
                    epistemic_state: str | None = None, limit: int = 50, text: str | None = None) -> dict:
        """Query nodes and edges by type, relation, or epistemic state; every filter applies to both halves
        (node_type: those nodes and the edges touching one; relation: those edges and the nodes they touch;
        epistemic_state: nodes and edges in that state). Nodes ranked by precomputed degree, edges by id.
        `text` also keeps only the nodes whose id or label, and the edges whose span, relation or endpoints,
        share a word with it (case, accents and function words ignored; rarer words weigh more), best match
        first, and adds `query_terms` (the words used: the first 12 at most, the rest are dropped) and
        `matched` (counts before `limit`). Use it to find a node by what it says, an edgeless one included;
        write it in the documents' language, since a translation finds little."""
        return engine.query_graph(node_type=node_type, relation=relation,
                                  epistemic_state=epistemic_state, limit=limit, text=text)

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
        """Grounding-aware, provenance-carrying, token-budgeted context for the session. A `query` keeps the
        edges whose span, relation or endpoint labels share a word with it (case, accents and function words
        ignored), grounded first and then best match first, and echoes the words in `query_terms` (the first
        12 at most; the rest are dropped).
        `items_total`/`hypotheses_total` count every edge that qualified: more than the lane holds means the
        budget left the rest out (raise `budget`, up to 100000, or narrow the query). While no source is usable
        under the project's evidence policy, `advisory.reexaminable_verdicts` comes back empty and
        `advisory.reexaminable_held` says how many items it holds back and why: none could change. A flag in
        that list lasts until its item's next verdict, whatever it is; `kg_ground_plan` queues the rejected
        ones for grounders, so a reader of this list re-verdicts nothing itself."""
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
        derived layer, writes only its two disposable artifacts; never forges a verdict or touches the canon.
        Once rendered, a view stays current: the engine re-renders it on the first read that projects the
        canon after a change, so the user reloads the page to see it. Only `/burgess:kg-view` creates one."""
        return engine.kg_export(kind)

    # ------------------------------------------------------------------------- #
    # Divergence surface (FUSION_PLAN Stage 3) — the /kg-diverge flow's eight tools (the eighth,
    # kg_diverge_export, since 0.19.6).
    #
    # Everything here sits BELOW the grounding boundary: these tools organize idea
    # candidates geometrically (embed → MAP-Elites → k-NN novelty → DPP slate →
    # anti-collapse monitor) and can never touch canon, verdicts, or the derived
    # DB (I1–I5: embeddings measure dispersion, never truth). State is project-
    # local and session-ephemeral (.kg/diverge, I4/I10). kg_engine.divergence is
    # imported LAZILY inside each body so this module's import graph stays
    # divergence-free (I3, firewall-tested) and a missing divergence dep degrades
    # only these eight tools with a clear error (I9) — never a kg_* tool.
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
        survive. Returns the resolved domain, session id, state paths and the resolved `axes`
        (name, type, range, which one is the open axis), `unit_of_generation` and
        `candidates_per_generation` — write every candidate's descriptor with exactly these axis
        names; there is no template file to open for them."""
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
                          seed: int = 0, cliches: dict | None = None) -> dict:
        """One divergence cycle: embed the generated candidates, near-dup dedup, place into the
        MAP-Elites archive, score geometric + mechanism novelty, and select a DPP-diverse slate.
        Each candidate: {"id", "text", "descriptor" {axis: value, ...}, optional "fitness" (the
        judge's bounded validity multiplier), optional "genealogy" {"operator_id", "parents"},
        "explanation" (the two or three plain lines, with a concrete example, that you show the
        user; the engine keeps it with the idea, returns it on later slates and prints it in
        kg_diverge_export, and never embeds it: the geometry reads "text" only)}.
        Returns the slate (with niche coords, novelty, why-picked signals), ask_pairs for A-vs-B,
        and the anti-collapse monitor verdict — `mon.collapsing: true` means REGENERATE with more
        diversity pressure (advisory notice to the user, no question). The ask_pairs come from the
        slate, except that one of them names an idea of this round whenever the round placed one
        and has an unanswered pair for it, even an idea the slate left out: ask it by its id, as
        you explained it with the rest of the round. Discarded ids are never
        re-slated. Purely advisory: nothing here can create graph state or verdicts.
        With the first ingest pass `cliches` = {"avoided": [...], "held_out": [...]}, the obvious
        answers you mapped before generating: the ones you generate away from, and the ones you set
        aside to check the ideas against at the end. The engine numbers them o1, o2, … (avoided
        first), keeps them for this session, returns them in kg_diverge_recall, prints them in
        kg_diverge_export with the ideas closest to each held-out one, and never lets them touch the
        geometry. The result then carries `cliches_stored`."""
        from kg_engine.divergence import config as dconfig
        from kg_engine.divergence import pipeline as dpipe
        return dpipe.ingest(project, candidates,
                            dconfig.resolve_axes_source(axes, pack_path=engine.pack_path),
                            seed=seed, home=engine._diverge_home(), cliches=cliches)

    @mcp.tool()
    @_tool_result
    def kg_diverge_remember(project: str, event: dict) -> dict:
        """Record a durable preference event: {"type": "pin"|"discard"|"comparison", ...}.
        Pins ({"type":"pin","id":...}) are strong stepping-stone signals and always future
        parents; discards ({"type":"discard","id":...}) are NEGATIVE MEMORY — dropped from
        every future slate and parent pool, persisted across sessions (I8); comparisons
        ({"type":"comparison","winner":...,"loser":...}) are the user's A-vs-B answers. The
        engine does NOT use comparisons to pick the slate or the parents: it only stops asking
        a pair already answered and tallies the answers in kg_diverge_recall (win counts and
        the winners' descriptor values). They reach the next round through you, when you
        generate. Never tell the user a comparison moved the slate.
        Pin and discard are mutually exclusive per id (latest wins)."""
        from kg_engine.divergence import pipeline as dpipe
        return dpipe.remember(project, event, home=engine._diverge_home())

    @mcp.tool()
    @_tool_result
    def kg_diverge_parents(project: str, k: int = 4, seed: int = 0) -> dict:
        """Parent set for the NEXT generation, honoring preference memory: every pin, never a
        discard (I8), and at least two diverse archive elites however many pins there are (fewer
        only when the archive has fewer). k is the total, and the set grows past it when needed to
        hold every pin and two diverse elites, so there is no need to raise k yourself.
        The diverse elites are drawn far from the pins and from each other, with a draw keyed by
        seed and the round: the same call in one round returns the same parents, and the next
        round draws again. Use these as the stepping stones the next round of variation
        operators mutates/combines."""
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

        It also returns the session context: `session_id` (the session the archive belongs to —
        the one kg_diverge_init last began or resumed), `seed`, and the resolved `axes`,
        `unit_of_generation` and `candidates_per_generation`, and the session's `cliches` when the
        first ingest stored them (each {id, text, role}; show a held_out one only when the session
        ends). After a compaction in the same chat, this one call restores what the next round
        needs; never read `.kg/diverge/` files for it.

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
                               edges: list | None = None,
                               cliche_ids: list | None = None) -> dict:
        """Materialize PINNED ideas into the graph — the EXPLICIT action (nothing enters the
        graph implicitly; kickoff Q5). Each pinned candidate becomes a node in the
        hypothesized lane via the propose door (kg_propose -> kg_write -> boundary): it lands
        `provenance=hypothesized, epistemic_state=unverified`, carrying its full lineage
        ([diverge] pinned / brief / session / mechanism / operator) in the node body. No
        source present? It simply WAITS in the lane — /burgess:kg-ground later promotes it only with
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
        `unverified` until supporting sources are added (Part C — never a disposition or verdict).
        `cliche_ids` (e.g. ["o1", "o4"]) carries clichés of this session's map (kg_diverge_ingest's
        `cliches`) as `cliche-<brief>-<id>` nodes in the same lane, only when the user asks. They
        need no pin, and with `cliche_ids` alone no pin goes in. /burgess:kg-ground judges a cliché
        like any proposal: grounded with support, rejected without; it never joins the brief's
        discards."""
        return engine.kg_diverge_materialize(project, candidate_ids=candidate_ids,
                                             node_type=node_type, edges=edges,
                                             cliche_ids=cliche_ids)

    @mcp.tool()
    @_tool_result
    def kg_diverge_export(project: str, brief: str = "") -> dict:
        """Write every idea of this brief's current session to one Markdown file the user keeps, and
        return its absolute `path`. Call it when the user ends the session or asks to save the ideas.
        Per idea, the file holds its text, the `explanation` it was ingested with, its descriptor, its
        operator and parents, the batch it arrived in and the batches whose slate showed it, and what
        the user did with it: pinned, discarded, compared, materialized into the graph. `brief` (the
        user's own words) heads the file. The engine writes it under .kg/diverge/<project>/, one file
        per session, and never in the project root, which may be the source folder that
        /burgess:kg-build reads. Nothing reads it back. Never assemble the file yourself, with Bash, a
        script, or by reading `.kg/diverge/` or the conversation transcript. `unexplained` lists ideas
        ingested without an `explanation`. Near-duplicates the ingest set aside were never kept, so
        they are not in it. When the session stored a cliché map, the file lists it and the result's
        `cliches` gives each one with its role; a held_out one carries `closest`, the ideas nearest
        to it by cosine similarity in this session's embedding space (advisory, it ranks nothing).
        Purely a record: it changes no state."""
        from kg_engine.divergence import export_ideas as dexport
        return dexport.export_ideas(project, brief=brief, home=engine._diverge_home())


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

    Best-effort: a genuinely-absent or broken dep must still DEGRADE gracefully — without leidenalg the
    projector runs igraph's own Leiden, and without igraph pure-Python label propagation
    (``projector.leiden_membership`` / ``_leiden``); every ``kg_*`` graph tool keeps working — so an import
    failure here is logged at INFO and swallowed, NEVER a startup failure. Ordered so numpy (the actual
    hang site) is imported first and alone, before igraph pulls it in transitively."""
    fallback = {"leidenalg": "projection will use igraph's built-in Leiden instead",
                "igraph": "projection will fall back to label propagation"}
    for name in ("numpy", "networkx", "igraph", "leidenalg"):
        try:
            __import__(name)
        except Exception as e:  # noqa: BLE001 — a missing/broken native dep must degrade, not block startup
            logger.info("preload: %s unavailable (%s: %s); %s", name, type(e).__name__, e,
                        fallback.get(name, "projection will fall back to the pure-Python path if needed"))


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
