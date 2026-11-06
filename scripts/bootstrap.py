#!/usr/bin/env python3
"""Cross-platform, self-provisioning bootstrap for the Burgess engine venv.

This is the single source of truth for building the engine's virtualenv. It is
invoked three ways, all idempotent and safe to re-run:

* by the plugin's ``SessionStart`` hook (``hooks/provision.mjs`` — the single
  cross-platform launcher since review-r5; ``provision.sh``/``provision.ps1`` remain
  as dev shims that exec it) right after the plugin is installed/loaded — see
  ``--background`` below;
* by the MCP launcher (``scripts/launch_server.mjs``) as a foreground last-resort if
  the server is spawned before the background provision has finished (graceful catch-up);
* by a developer from a shell (``python scripts/bootstrap.py``).

What it does — adapted to this repo's runtime model:

* creates a venv and installs the engine's **dependencies** (``uv sync
  --no-install-project`` when ``uv`` is on PATH, else stdlib ``venv`` + ``pip``).
  Unlike the sibling ``creativity-amplifier`` plugin, ``kg_engine`` itself is *not*
  imported from the venv's site-packages — it resolves via ``PYTHONPATH=<repo>/scripts``
  (see ``.mcp.json``), so only the dependencies in ``pyproject.toml`` must land here.
* records the resolved venv interpreter path in ``<venv>/engine-python.txt`` so the
  launchers find it on any OS without hard-coding ``bin/python`` vs ``Scripts\\python.exe``.
* with ``--reconcile`` (set by the detached SessionStart worker), runs the canon
  reconcile (§1.8) after the venv is ready — the once-per-session full re-hash that
  re-quarantines mtime-spoofed forged verdicts. Best-effort, never fatal.

Where the venv lives (first match wins):

1. ``--venv PATH``                  (explicit; passed by the MCP launcher)
2. ``$KG_ENGINE_VENV``              (explicit override)
3. ``$CLAUDE_PLUGIN_DATA/.venv``    (installed via marketplace — persists across plugin
                                     updates; the recommended location)
4. ``<repo>/.venv``                 (developer fallback: ``--plugin-dir .`` / shell — the
                                     same venv ``uv sync`` from the repo root builds)

Idempotency & robustness:

* A content stamp (hash of ``pyproject.toml`` — the dependency source of truth — plus the
  backing interpreter's minor version + platform + arch) lets a fast path skip work when the
  venv is current, and forces a rebuild when a plugin update changes dependencies OR a
  same-path interpreter swap would leave its compiled wheels ABI-mismatched. (Engine
  *source* edits need no rebuild: ``kg_engine`` is read live off ``PYTHONPATH``, never
  installed.)
* An atomic lock dir serializes concurrent provisions (the SessionStart worker, extra
  terminals, the launcher racing the hook) so two builds never clobber a venv.
* ``--background`` re-spawns a fully detached worker and returns in milliseconds, so
  even a Claude Code without ``async`` hook support never blocks on the install.

Launch with any system Python >= 3.10:

    python  scripts/bootstrap.py        # Windows (or:  py scripts/bootstrap.py)
    python3 scripts/bootstrap.py        # macOS / Linux
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import venv
from pathlib import Path

# Stdlib-only leaf modules: importable with a bare system Python BEFORE the venv deps exist
# (kg_engine/__init__ is import-light), and bootstrap runs as ``python scripts/bootstrap.py``
# so scripts/ is sys.path[0] and ``import kg_engine.atomicio`` resolves. envconfig.clean is the
# single home of the env-value cleaner (review-r5: five hand-synced copies, two sentinel sets).
from kg_engine import dirlock
from kg_engine.atomicio import atomic_write_text, fsync_dir
from kg_engine.envconfig import clean as _clean

SCRIPT_DIR = Path(__file__).resolve().parent      # <repo>/scripts
REPO_ROOT = SCRIPT_DIR.parent                     # <repo>
PYPROJECT = REPO_ROOT / "pyproject.toml"          # the dependency source of truth

MIN_PY = (3, 10)                    # matches pyproject's requires-python = ">=3.10"
PTR_NAME = "engine-python.txt"      # interpreter pointer, written inside the venv dir
STAMP_NAME = "install.stamp"        # content hash of the install inputs
# Ownership sentinel stamped BESIDE the venv dir BEFORE any bin/lib lands (bootstrap FALLO 1). It
# marks "THIS provisioner started building here", so a dir populated but carrying NO completion marker
# (engine-python.txt / install.stamp) can be told apart from a user's foreign venv: sentinel-present →
# our own interrupted build (its except-cleanup never finished) → reclaim and rebuild; sentinel-absent →
# genuinely foreign → refuse. Without it, a kill between "venv populated" and "_write_markers" left an
# unmarked, unowned dir that wedged the venv path until a human deleted it.
#
# It lives as a SIBLING of the venv dir (``<venv>.burgess-venv-owner``), NOT inside it — crash-report
# v0.2.4 "anyio wedge", hole B. The failure/interrupt cleanup does ``rmtree(venv_dir)``, and an in-place
# ``uv``/``pip`` upgrade can recreate the venv dir wholesale; either op, if interrupted mid-flight, would
# destroy a sentinel kept INSIDE the venv while leaving a populated husk behind — the exact state that
# wedges. A sibling token survives any operation on the venv dir's contents, so the next run always
# recognises the husk as ours and rebuilds clean. Mirrors ``_lock_dir``, beside the venv for the same
# "a half-built venv can't shadow it" reason. See ``_owner_sentinel`` for the lifecycle (claimed before
# mutation; cleared on a verified success or a clean failure, so a live token means "interrupted build").
OWNER_NAME = ".burgess-venv-owner"
LOCK_NAME = ".kg-provision.lock"    # atomic lock dir, kept beside the venv
STALE_LOCK_SECS = 30 * 60           # treat a lock older than this as abandoned
# Heartbeat cadence must stay well under STALE_LOCK_SECS so a healthy holder is never
# judged stale and stolen; the poll interval is how often a waiter re-checks the lock.
HEARTBEAT_SECS = STALE_LOCK_SECS / 4
POLL_SECS = 2.0                     # how often a foreground waiter re-checks the lock
LOG_NAME = "provision.log"          # where the detached worker logs
SCHEMA = "1"                        # bump to force every venv to rebuild
# Every provisioning subprocess is bounded. Without this, a child that never returns — a dead NFS/network
# mount, an AV scanner holding the unsigned `_c_leiden` DLL, a stalled index fetch — blocks do_install
# forever WHILE `_heartbeat_pulse` keeps the provision lock fresh from another thread. The lock therefore
# never ages past STALE_LOCK_SECS and `pid_probe` still sees the hung PID alive, so no later session can
# reclaim it: every subsequent provision waits out its full deadline and returns EXIT_STILL_PROVISIONING,
# and the venv never builds. That is the field-reported venv-wedge class, reached without any crash.
# A timeout raises TimeoutExpired, which do_install's `except BaseException` cleanup converts into the
# ordinary interrupted-build path (husk removed, sentinel kept, lock released) — recoverable next run.
# Generous enough that a cold, no-wheel, source-building install on a slow link still finishes
# (review-r11).
INSTALL_TIMEOUT_SECS = 30 * 60      # `uv sync` / `pip install` — may compile wheels on a slow link
PROBE_TIMEOUT_SECS = 60             # in-venv import probes (mandatory verify + advisory soft probes)
RECONCILE_TIMEOUT_SECS = 120        # the post-install canon reconcile sweep
# Provisioning process exit codes, named once (review-r5: the meanings lived only in prose here
# and again in launch_server.mjs's comments). launch_server treats any non-zero as "not ready";
# the distinct values make the logs say WHY.
EXIT_OK = 0
EXIT_BUILD_FAILED = 1        # an install step failed (see provision.log)
EXIT_STILL_PROVISIONING = 2  # a foreign in-flight build outlasted the wait deadline
EXIT_PY_TOO_OLD = 3          # no interpreter >= MIN_PY to build with

# Modules the engine must be able to import for the MCP server to come up. The igraph dep
# imports as ``igraph``; pyyaml as ``yaml``. ``kg_engine`` resolves off PYTHONPATH. (Git is
# used only via the ``git`` CLI through subprocess in canon.py — no ``import git`` — so the
# ``git`` module is intentionally absent here and from [project.dependencies].)
#
# ``leidenalg`` is deliberately NOT in this MANDATORY set. It installs fine, but its unsigned
# native ``_c_leiden`` DLL can be blocked from LOADING by Windows Smart App Control /
# Application Control (reputation-based — igraph's DLL loads, leidenalg's may not). At runtime
# it is already OPTIONAL: ``projector._leiden`` wraps the import in try/except and degrades to
# label propagation. So a blocked-but-installed leidenalg must not abort provisioning — it is
# checked separately by ``probe_leidenalg`` (a soft probe that reports status and never fails).
_VERIFY_IMPORTS = (
    "import mcp, pydantic, networkx, igraph, yaml, kg_engine; "
    "print('[bootstrap] core imports OK')"
)


# --------------------------------------------------------------------------- #
# Path resolution
# --------------------------------------------------------------------------- #
# (the env-value cleaner ``_clean`` is imported at the top, from its kg_engine.envconfig home)


def resolve_venv_dir(explicit: str | None = None) -> Path:
    """Where the engine venv should live, by priority (see module docstring)."""
    chosen = _clean(explicit)
    if chosen:
        return Path(chosen).expanduser().resolve()

    override = _clean(os.environ.get("KG_ENGINE_VENV"))
    if override:
        return Path(override).expanduser().resolve()

    plugin_data = _clean(os.environ.get("CLAUDE_PLUGIN_DATA"))
    if plugin_data:
        return (Path(plugin_data).expanduser() / ".venv").resolve()

    return (REPO_ROOT / ".venv").resolve()


def venv_python(venv_dir: Path) -> Path:
    """Path to the venv's interpreter for the current OS."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


# --------------------------------------------------------------------------- #
# Idempotency: content stamp
# --------------------------------------------------------------------------- #
def _running_identity() -> str:
    """The ABI identity (minor version + platform + arch) of the interpreter running THIS process."""
    return f"{sys.version_info[0]}.{sys.version_info[1]}\0{sys.platform}\0{platform.machine()}"


def _interp_identity(python_exe=None) -> str:
    """The ABI identity of `python_exe` — the VENV's interpreter, not whatever interpreter happens to be
    running bootstrap. Querying the venv python (not sys.*) makes the stamp track the interpreter that
    actually ABI-binds the wheels, so a DIFFERENT bootstrapping/checking interpreter (e.g. a system-Python
    upgrade between sessions, or uv picking its own python to build the venv) computes the SAME stamp the
    build wrote — no spurious full rebuild of a still-valid venv (review-M7). Falls back to the running
    interpreter when no venv python is available yet (the first build, before the venv exists)."""
    if python_exe is not None:
        code = ("import sys,platform;"
                "print(f'{sys.version_info[0]}.{sys.version_info[1]}'+chr(0)+sys.platform+chr(0)+platform.machine())")
        try:
            out = subprocess.run([str(python_exe), "-c", code], capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return _running_identity()


def compute_stamp(interp_identity: "str | None" = None) -> str:
    """Hash the inputs whose change should trigger a rebuild.

    ``pyproject.toml`` is the declared source of the engine's dependencies (``uv.lock`` is
    gitignored and so never ships in the plugin payload, and ``kg_engine`` is read off
    PYTHONPATH rather than installed, so engine source edits do not require a rebuild).

    The backing interpreter's identity (minor version + platform + arch) is folded in too:
    the venv's compiled wheels (pydantic-core, igraph, leidenalg) are ABI-bound to the
    interpreter that built them, so a same-path interpreter swap that leaves pyproject
    untouched — an unversioned stdlib-venv symlink re-pointed, a pyenv re-point, a moved
    arch — would otherwise keep the stamp matching while ``import`` crashes on a wheel
    ABI mismatch. Hashing the interpreter identity forces a clean rebuild instead.

    `interp_identity` should be the VENV interpreter's identity (see ``_interp_identity``); when omitted
    it falls back to the running interpreter — used only before any venv exists (review-M7).
    """
    ident = interp_identity if interp_identity is not None else _running_identity()
    h = hashlib.sha256()
    h.update(SCHEMA.encode())
    h.update(ident.encode())
    h.update(b"\0")
    h.update(PYPROJECT.name.encode())
    h.update(b"\0")
    h.update(PYPROJECT.read_bytes() if PYPROJECT.exists() else b"")
    return h.hexdigest()


def _current_stamp(venv_dir: Path) -> str:
    """The stamp to compare an existing venv against: hashed with the VENV interpreter's identity (not
    the running one), so a different checking interpreter computes the same stamp the build wrote (M7)."""
    py = venv_python(venv_dir)
    return compute_stamp(_interp_identity(py if py.exists() else None))


def is_ready(venv_dir: Path, stamp: str) -> bool:
    """True when the venv already satisfies the current stamp."""
    py = venv_python(venv_dir)
    ptr = venv_dir / PTR_NAME
    stamp_file = venv_dir / STAMP_NAME
    if not (py.exists() and ptr.exists() and stamp_file.exists()):
        return False
    try:
        return stamp_file.read_text(encoding="utf-8").strip() == stamp
    except OSError:
        return False


def venv_current(venv_dir: Path) -> bool:
    """True when the venv is provisioned and current right now.

    Recomputes the stamp against the VENV interpreter's identity on every call (review-M7),
    so a fresh check after another builder lands the venv compares equal.

    Cheap pre-check FIRST (review-low/perf): if the interpreter pointer / stamp markers are not
    even present yet there is nothing to compare, so return False WITHOUT computing the expensive
    ``_current_stamp`` — which spawns the venv interpreter (``_interp_identity``). A foreground
    ``_wait_for_lock`` poll re-checks readiness every ``POLL_SECS`` while another builder works,
    and the markers only appear once that build finishes, so this keeps the wait loop from
    re-spawning the interpreter on every 2s tick.
    """
    py = venv_python(venv_dir)
    if not (py.exists() and (venv_dir / PTR_NAME).exists() and (venv_dir / STAMP_NAME).exists()):
        return False
    return is_ready(venv_dir, _current_stamp(venv_dir))


# --------------------------------------------------------------------------- #
# Lock (atomic mkdir; steals abandoned locks)
# --------------------------------------------------------------------------- #
# The implementation lives in the kg_engine.dirlock LEAF (review-r5): it was a second ~250-line
# lock inside the installer, parallel-by-design to canon.LeaseLock and kept correct only by
# keep-in-sync comments; it now has one home with its own unit-test surface. These thin wrappers
# keep bootstrap's venv-dir-keyed call shape (and the tests' seams) unchanged.


def _lock_dir(venv_dir: Path) -> Path:
    # Beside the venv, not inside it, so a half-built venv can't shadow the lock.
    return venv_dir.parent / LOCK_NAME


def _heartbeat_file(venv_dir: Path) -> Path:
    return dirlock.heartbeat_file(_lock_dir(venv_dir))


def heartbeat(venv_dir: Path) -> None:
    """Stamp the provision lock as alive (the install loop pulses this so a slow but healthy
    build is never mistaken for an abandoned lock and stolen)."""
    dirlock.heartbeat(_lock_dir(venv_dir))


def try_acquire(venv_dir: Path) -> bool:
    return dirlock.try_acquire(_lock_dir(venv_dir), stale_secs=STALE_LOCK_SECS)


def release(venv_dir: Path) -> None:
    dirlock.release(_lock_dir(venv_dir))


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #
def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
        timeout: float | None = None) -> None:
    """Run a provisioning step, checked and BOUNDED. `timeout` is required in spirit: every caller passes
    one (see the *_TIMEOUT_SECS constants for why an unbounded child wedges provisioning permanently)."""
    print(f"[bootstrap] $ {' '.join(str(c) for c in cmd)}", flush=True)
    subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None, env=env, timeout=timeout)


def install_with_uv(venv_dir: Path, uv: str) -> None:
    """Install dependencies with uv (``uv sync --no-install-project``).

    Pin the environment location with ``UV_PROJECT_ENVIRONMENT`` and resolve from a dir
    that holds ``pyproject.toml``. In dev the project dir IS the repo root (with its
    ``uv.lock``); in an installed plugin we copy ``pyproject.toml`` next to the venv so
    uv has something to resolve. ``--no-install-project`` installs only the dependencies,
    never the ``kg_engine`` package (which is read off PYTHONPATH).
    """
    proj_dir = venv_dir.parent
    if PYPROJECT.resolve() != (proj_dir / "pyproject.toml").resolve():
        proj_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PYPROJECT, proj_dir / "pyproject.toml")
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv_dir)}
    print("[bootstrap] Installing dependencies with uv (sync --no-install-project)", flush=True)
    run([uv, "sync", "--no-install-project"], cwd=proj_dir, env=env, timeout=INSTALL_TIMEOUT_SECS)


def install_with_pip(venv_dir: Path) -> None:
    """Fallback when uv is absent: stdlib venv + pip install the project.

    ``pip install <repo>`` builds the ``kg-engine`` wheel via hatchling and installs its
    ``[project.dependencies]``. The bundled ``kg_engine`` lands in site-packages too, but
    is harmlessly shadowed at runtime by ``PYTHONPATH=<repo>/scripts``.
    """
    print("[bootstrap] uv not on PATH — using python -m venv + pip", flush=True)
    try:
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    except Exception as exc:  # ensurepip/venv unavailable on some distros
        raise SystemExit(
            f"[bootstrap] Could not create venv: {exc}\n"
            "[bootstrap] On Debian/Ubuntu you may need: sudo apt install python3-venv"
        )
    py = venv_python(venv_dir)
    if not py.exists():
        raise SystemExit(f"[bootstrap] venv interpreter not found at {py}")
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"],
        timeout=INSTALL_TIMEOUT_SECS)
    print("[bootstrap] Installing the engine + dependencies with pip", flush=True)
    run([str(py), "-m", "pip", "install", str(REPO_ROOT)], timeout=INSTALL_TIMEOUT_SECS)


def _engine_env() -> dict:
    """Env for subprocessing into engine code: kg_engine resolves off PYTHONPATH, never installed."""
    return {**os.environ, "PYTHONPATH": str(SCRIPT_DIR)}


def verify_imports(py: Path) -> None:
    print("[bootstrap] Verifying core imports", flush=True)
    run([str(py), "-c", _VERIFY_IMPORTS], env=_engine_env(), timeout=PROBE_TIMEOUT_SECS)


def _is_functional_venv(venv_dir: Path) -> bool:
    """True when ``venv_dir`` has a working interpreter that imports the MANDATORY deps — a COMPLETE,
    usable environment (a user's ``uv sync`` / ``python -m venv`` result), NOT an interrupted husk.

    Used to REFUSE reclaiming (and rmtree-ing) a functional foreign venv even when a stranded owner
    sentinel sits beside it. The sibling sentinel OUTLIVES the venv (crash-report v0.2.4 hole B), so a
    token stranded past its husk — a hard kill mid-clear, a swallowed ``_clear_owner_sentinel``, or a
    user who ``rm -rf``'d the husk and rebuilt with the documented ``uv sync`` — must not by ITSELF
    authorise deleting whatever now occupies the path. An interrupted build of ours is never usable (a
    partial dependency graph), so a dir whose interpreter imports the core set is positive proof it is
    NOT our husk: never delete it (the never-delete-a-user-venv invariant, regressed 3x). A quiet,
    non-raising probe (not ``verify_imports``, which prints + raises); a missing interpreter or ANY
    import failure ⇒ genuinely-incomplete husk ⇒ reclaimable."""
    py = venv_python(venv_dir)
    if not py.exists():
        return False
    try:
        out = subprocess.run([str(py), "-c", _VERIFY_IMPORTS], capture_output=True,
                             env=_engine_env(), timeout=60)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _soft_probe(py: Path, snippet: str, parent_fail_msg: str) -> None:
    """Run an ADVISORY in-venv import probe that must never abort provisioning (review-r5: the
    two probes were structural copy-paste). A NON-checking subprocess (never ``run()``, which is
    ``check=True``); the in-venv import/DLL-load error is reported by the snippet itself, and a
    parent-side launch failure (OSError) by the except — either way provisioning proceeds.

    Bounded like every other provisioning child: a soft probe that HANGS (an AV scanner holding the
    unsigned `_c_leiden` DLL is the known case) would otherwise wedge do_install indefinitely while the
    heartbeat keeps the provision lock fresh. TimeoutExpired lands in the same swallow-and-report path as
    any other probe failure, because an advisory probe's verdict is never load-bearing (review-r11)."""
    try:
        subprocess.run([str(py), "-c", snippet], check=False, env=_engine_env(),
                       timeout=PROBE_TIMEOUT_SECS)
    except Exception as exc:  # noqa: BLE001 — an optional/blocked dep must never abort provisioning
        print(parent_fail_msg.format(exc=f"{type(exc).__name__}: {exc}"), flush=True)


def probe_leidenalg(py: Path) -> None:
    """Soft-probe the OPTIONAL ``leidenalg`` import in the freshly-built venv — advisory only.

    leidenalg installs fine but its unsigned native ``_c_leiden`` DLL can be blocked from
    LOADING by Windows Smart App Control / Application Control. At runtime that is already
    tolerated (``projector._leiden`` degrades to label propagation), so a blocked import must
    NOT abort the provision the way ``verify_imports`` would — this just reports which path the
    engine will take.
    """
    _soft_probe(py, (
        "try:\n"
        "    import leidenalg\n"
        "    print('[bootstrap] leidenalg OK (Leiden community detection enabled)')\n"
        "except Exception as e:\n"
        "    print('[bootstrap] leidenalg unavailable (' + type(e).__name__ + ': ' + str(e)\n"
        "          + '); using label-propagation fallback (projector._leiden)')\n"
    ), "[bootstrap] leidenalg unavailable ({exc}); "
       "using label-propagation fallback (projector._leiden)")


def probe_divergence(py: Path) -> None:
    """Soft-probe the divergence-layer deps (numpy / scikit-learn / model2vec) — advisory only.

    They are core deps in pyproject (wheel-only installs), but the divergence layer is
    OPTIONAL at runtime (I9): every import inside kg_engine.divergence is lazy/guarded and
    a missing dep degrades /kg-diverge with a clear error while every kg_* convergence tool
    keeps working. So, exactly like leidenalg, a missing/blocked divergence dep must never
    abort provisioning — this just reports which path the diverge flow will take.
    """
    _soft_probe(py, (
        "try:\n"
        "    import numpy, sklearn, model2vec\n"
        "    print('[bootstrap] divergence deps OK (numpy/sklearn/model2vec)')\n"
        "except Exception as e:\n"
        "    print('[bootstrap] divergence deps unavailable (' + type(e).__name__ + ': '\n"
        "          + str(e) + '); /kg-diverge will raise a clear error until provisioned;'\n"
        "          + ' convergence (kg_*) tools are unaffected (I9)')\n"
    ), "[bootstrap] divergence deps unavailable ({exc}); "
       "/kg-diverge degraded until provisioned; kg_* tools unaffected (I9)")


def _has_engine_marker(venv_dir: Path) -> bool:
    """True only when the dir carries an ENGINE-specific marker that bootstrap itself writes
    (``engine-python.txt`` / ``install.stamp``) — proof that THIS provisioner built it, so
    deleting it on failure is safe.

    A bare ``pyvenv.cfg`` deliberately does NOT qualify (bootstrap-1): EVERY venv has one,
    including a user's own venv that ``--venv`` / ``KG_ENGINE_VENV`` merely points at. Keying
    ownership on ``pyvenv.cfg`` would let a failed install ``rmtree`` a user's real venv. So we
    key strictly on the files bootstrap writes; a populated dir without one is treated as
    foreign user data and is never scaffolded into nor deleted.

    The COMPLETION markers here mean "a build finished and verified". The weaker
    ``OWNER_NAME`` sentinel (``_has_owner_sentinel``) means "a build STARTED here" — enough to
    reclaim an interrupted build, but never proof of a usable venv, so it is kept separate.
    """
    return (venv_dir / PTR_NAME).exists() or (venv_dir / STAMP_NAME).exists()


def _owner_sentinel(venv_dir: Path) -> Path:
    """Path to the ownership sentinel — a SIBLING of the venv dir, never inside it (crash-report
    v0.2.4, hole B). Keyed by the venv's name so sibling venvs under one parent don't collide, and
    kept beside the venv (like ``_lock_dir``) so an interrupted ``rmtree(venv_dir)`` or an in-place
    dependency-manager recreate can't destroy the very token the next run needs to reclaim the husk."""
    return venv_dir.parent / (venv_dir.name + OWNER_NAME)


def _has_owner_sentinel(venv_dir: Path) -> bool:
    """True when our ``OWNER_NAME`` sentinel exists beside the venv — proof that a bootstrap run began
    populating it (written before any bin/lib) and has NOT yet reached a terminal state. Distinguishes
    an interrupted build of ours (reclaimable) from a user's foreign venv (never touched); see
    ``do_install`` (FALLO 1) and ``_clear_owner_sentinel`` for the lifecycle."""
    return _owner_sentinel(venv_dir).exists()


def _claim_owner_sentinel(venv_dir: Path) -> None:
    """Stamp the ownership sentinel BEFORE populating the venv, so a kill mid-build leaves a token the
    NEXT run recognises as its own interrupted work (do_install reclaims it) rather than wedging on
    the foreign-venv guard. Durable (fsync_dir) so it survives the crash it exists to be read after.
    Written beside the venv (see ``_owner_sentinel``) so a wipe of the venv dir can't take it down."""
    _owner_sentinel(venv_dir).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        _owner_sentinel(venv_dir),
        f"pid={os.getpid()} t={time.time():.0f} building\n",
        mkparents=False,
        fsync_dir=True,
    )


def _clear_owner_sentinel(venv_dir: Path) -> None:
    """Drop the ownership sentinel once the build reaches a TERMINAL state — a verified success (after
    ``_write_markers``) or a clean failure (after the except-cleanup rmtree'd our venv). A LIVE sentinel
    then means exactly "a build started here and was interrupted before it could finish or clean up" —
    the only state ``do_install``'s reclaim branch acts on. Clearing on success is what keeps a healthy
    venv, or a user venv later placed at this path, from ever being seen as reclaimable now that the
    token is a sibling that outlives the venv dir (crash-report v0.2.4, hole B). Best-effort + durable
    (fsync the parent so a power cut can't resurrect the token onto a since-swapped venv)."""
    sentinel = _owner_sentinel(venv_dir)
    try:
        sentinel.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return
    fsync_dir(sentinel.parent)


@contextlib.contextmanager
def _heartbeat_pulse(venv_dir: Path):
    """Keep the provision lock alive across a slow source-build (a daemon thread pulsing
    ``heartbeat`` every HEARTBEAT_SECS) so a concurrent provisioner does not mistake a healthy
    long install for an abandoned lock and steal it (bootstrap-1). Extracted from do_install
    (review-r5) so the install body reads as guards -> install -> verify -> markers."""
    stop = threading.Event()

    def _pulse() -> None:
        while not stop.wait(HEARTBEAT_SECS):
            heartbeat(venv_dir)

    thread = threading.Thread(target=_pulse, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)


def _write_markers(venv_dir: Path, py: Path) -> None:
    """Finalize a VERIFIED venv: the interpreter pointer, then the stamp STRICTLY LAST.

    Single source of truth for the launchers, on every OS — forward slashes work in Git Bash,
    PowerShell, and cmd alike, so the recorded path is shell-agnostic. Both writes are atomic;
    the stamp lands only after verify_imports succeeded, so a matching stamp implies a verified
    venv (bootstrap-2) and a crash between pointer and stamp never fakes "ready". The stamp
    carries the BUILT venv's own interpreter identity (uv may have built with a different
    interpreter than the one running bootstrap), so a later --check under yet another
    interpreter compares equal and doesn't force a spurious rebuild (review-M7)."""
    atomic_write_text(venv_dir / PTR_NAME, py.as_posix(), mkparents=False, fsync_dir=False)
    atomic_write_text(
        venv_dir / STAMP_NAME,
        compute_stamp(_interp_identity(py)),
        mkparents=False,
        fsync_dir=False,
    )
    print(f"[bootstrap] Engine interpreter: {py.as_posix()}", flush=True)
    print(f"[bootstrap] Wrote {venv_dir / PTR_NAME}", flush=True)


def do_install(venv_dir: Path) -> Path:
    if not PYPROJECT.exists():
        raise SystemExit(f"[bootstrap] pyproject.toml not found at {PYPROJECT}")
    uv = shutil.which("uv")
    if uv:
        print(f"[bootstrap] Found uv at {uv} — using it for a faster install", flush=True)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    # Whether the dir was absent or EMPTY before we touched it — i.e. WE are populating it THIS run. On
    # failure such a dir is safe to rmtree even if the install died before any marker exists (a partial
    # pre-config scaffold). Without this, a scaffold we created and then failed on would be neither cleaned
    # (no marker yet) nor buildable next run (the foreign guard would see a populated markerless dir),
    # wedging the venv path until a human deletes it (bootstrap).
    try:
        empty_or_absent = not venv_dir.exists() or not any(venv_dir.iterdir())
    except OSError:
        empty_or_absent = False
    # A PRE-EXISTING, populated dir is FOREIGN — refuse — UNLESS it is unambiguously ours: it carries an
    # engine COMPLETION marker (a prior build of ours) OR our OWNER sentinel (a build we STARTED here; a
    # bare pyvenv.cfg does NOT make it ours, see _has_engine_marker). A user's own venv that --venv /
    # KG_ENGINE_VENV points at has neither, so it is still refused BEFORE we scaffold anything — we never
    # pollute user data with bin/lib nor (below) rmtree it (bootstrap-1/4).
    preexisting_foreign = (
        (not empty_or_absent)
        and not _has_engine_marker(venv_dir)
        and not _has_owner_sentinel(venv_dir)
    )
    if preexisting_foreign:
        raise SystemExit(
            f"[bootstrap] refusing to provision into {venv_dir}: it already exists and is not an "
            f"engine venv (no {PTR_NAME} / {STAMP_NAME} / {OWNER_NAME}). Point --venv / "
            f"KG_ENGINE_VENV at a dedicated path.")
    # A populated dir carrying our OWNER sentinel but NO completion marker is an INTERRUPTED build of ours:
    # either a fresh build killed between "venv populated" and "_write_markers" (its except-cleanup never
    # ran — FALLO 1), or an in-place upgrade whose venv-dir wipe/recreate was interrupted mid-flight, or an
    # except-cleanup rmtree preempted part-way — all of which strip the completion markers while the SIBLING
    # sentinel survives (crash-report v0.2.4, hole B: the token lives beside the venv, so a wipe of the venv
    # dir can't take it down). It is unambiguously ours and NOT a usable venv: wipe it and rebuild clean
    # rather than layering a fresh install over a partial dependency graph. This is the wedge fix: without a
    # surviving token such a dir was foreign forever. (A dir WITH a completion marker but a stale stamp is a
    # legit prior build — left untouched here so install_with_uv updates it in place, exactly as before.)
    # ...UNLESS the dir is a FUNCTIONAL venv (interpreter imports the mandatory deps): a stranded sibling
    # sentinel (hole B: the token outlives the venv, so a hard kill mid-clear, a swallowed clear, or a
    # user `rm -rf .venv` + `uv sync` rebuild can leave the token beside a brand-new foreign venv) must
    # NOT rmtree a working environment. Our own interrupted build is never functional (partial deps), so
    # a functional dir is either foreign or an already-usable prior build — either way, fall through and
    # let install_with_uv update it IN PLACE (non-destructive), exactly as a completion-marker-bearing
    # venv is handled, rather than deleting it (review: reclaim rmtrees a user venv — the never-delete
    # invariant that regressed 3x).
    if ((not empty_or_absent) and _has_owner_sentinel(venv_dir)
            and not _has_engine_marker(venv_dir) and not _is_functional_venv(venv_dir)):
        print(f"[bootstrap] Reclaiming an interrupted prior build at {venv_dir}", flush=True)
        shutil.rmtree(venv_dir, ignore_errors=True)
        empty_or_absent = True
    # WE are (re)populating this dir FROM SCRATCH this run iff it is now empty/absent; such a dir is safe to
    # rmtree on failure even before any marker exists.
    ours_to_clean = empty_or_absent
    # Claim ownership FIRST — before any bin/lib is mutated — on BOTH build paths (crash-report 2026-07-07):
    #   * a fresh/reclaimed build (empty_or_absent): a kill mid-build leaves a dir the reclaim branch above
    #     recognises as ours next run; AND
    #   * an IN-PLACE UPGRADE of a completion-marker-bearing venv whose stamp went stale because a plugin
    #     update changed dependencies (the 0.2.2->0.2.3 deps-changed case). install_with_uv upgrades that
    #     existing venv IN PLACE, which must UNINSTALL the old wheels before reinstalling; a hard kill during
    #     that swap — or during this function's except-cleanup rmtree — can strip the completion markers and
    #     leave a populated, markerless dir. WITHOUT this sentinel that leftover is indistinguishable from a
    #     user's foreign venv, so every later run REFUSES it (preexisting_foreign) and the venv path wedges
    #     until a human deletes it — meanwhile the half-swapped venv is missing a transitive dep (e.g. `anyio`
    #     uninstalled-but-not-reinstalled) and the MCP server crash-loops on ImportError.
    # Claiming here is safe on both paths: any genuinely foreign dir was already refused above, so at this
    # point the dir is unambiguously ours to write into. WITH the sentinel — stamped BESIDE the venv so a
    # wipe/recreate of the venv dir can't destroy it (crash-report v0.2.4, hole B) — an interrupted upgrade
    # lands in the reclaim branch on the next provision and is rebuilt clean instead of wedging (FALLO 1 net,
    # now covering the in-place-upgrade path too). The success/clean-failure paths clear it (see
    # _clear_owner_sentinel), so a LIVE token means precisely "an interrupted build is still sitting here".
    _claim_owner_sentinel(venv_dir)

    with _heartbeat_pulse(venv_dir):
        try:
            if uv:
                install_with_uv(venv_dir, uv)
            else:
                install_with_pip(venv_dir)
            py = venv_python(venv_dir)
            if not py.exists():
                raise SystemExit(f"[bootstrap] venv interpreter not found at {py}")
            verify_imports(py)
            # Optional, never fatal: the soft probes report whether Leiden / the divergence deps
            # are loadable, or which fallback the engine will take. They swallow all failures.
            probe_leidenalg(py)
            probe_divergence(py)
        except BaseException:
            # A failed/interrupted install leaves a venv with an interpreter but a partial
            # dependency graph that the next run would silently "reuse". Remove it so the next
            # provision rebuilds clean — but ONLY when it is genuinely ours: WE created/reclaimed
            # the dir THIS run (ours_to_clean) OR it carries an engine marker from a prior build
            # (engine-python.txt / install.stamp) OR it carries our OWNER sentinel — which, since
            # _claim_owner_sentinel now runs before this try on BOTH the fresh and in-place-upgrade
            # paths, is present for every dir that reaches here. A pre-existing populated dir WITHOUT
            # a marker OR our sentinel is foreign and was already refused above, so we never reach here
            # for one — but the re-check keeps the rmtree from ever touching such a dir even if that
            # guard changed. A bare pyvenv.cfg never qualifies (bootstrap-1). The lock lives BESIDE the
            # venv (_lock_dir), so this never deletes the lock this process still holds. (Even if this
            # cleanup is skipped or a HARD kill preempts it, the OWNER sentinel we stamped makes the
            # leftover reclaimable next run — FALLO 1, now covering the in-place-upgrade path too.)
            if ours_to_clean or _has_engine_marker(venv_dir) or _has_owner_sentinel(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)
                # Drop the reclaim token ONLY once the venv is fully gone. If the rmtree succeeded there is
                # no husk to reclaim, so a lingering sibling token would be a hazard — it could later
                # reclaim (and rmtree) a user venv placed at this same path. But if the rmtree was preempted
                # or left anything behind (Windows sharing violation, a HARD kill mid-walk), the venv dir
                # still exists as a populated husk: KEEP the token so the next run reclaims it (hole B). The
                # success path below clears the token unconditionally — a sealed venv is never a husk.
                if not venv_dir.exists():
                    _clear_owner_sentinel(venv_dir)
            raise

    _write_markers(venv_dir, py)
    # Verified + sealed: drop the reclaim token so this healthy venv (and any user venv later placed at this
    # path) is never mistaken for an interrupted build. Now that the token is a sibling that outlives a wipe
    # of the venv dir, a stale one would otherwise be a live hazard (crash-report v0.2.4, hole B).
    _clear_owner_sentinel(venv_dir)
    return py


# --------------------------------------------------------------------------- #
# Reconcile (§1.8) — re-attach/re-quarantine verdicts after the venv is ready
# --------------------------------------------------------------------------- #
# The two vault names the reconcile guard reads, mirrored from kg_engine.canon (CANON_SUBDIR and
# GROUND_AUDIT). canon cannot be imported here: this guard runs under the bare system Python, before the
# venv exists, and canon's model module needs yaml. tests/test_fix_session_start.py pins both names and
# the note rule in _holds_project against the engine, so the mirror cannot drift silently.
_CANON_SUBDIR = "canon"
_GROUND_AUDIT = ".kg-ground-audit.jsonl"


def _holds_project(project: Path) -> bool:
    """Whether ``project`` already holds a Burgess project: at least one canon note, or a non-empty
    grounding-audit ledger (a vault whose notes were all deleted still has verdict history to
    reconcile against). An EMPTY canon/ is not a project. That includes the empty canon/ that older
    versions left in every folder a session opened; it is left where it is, never deleted.

    The note test is Canon.note_paths()'s rule: ``*.md`` minus dotfiles (the ``.tmp-*`` atomic-write
    temporaries). ``any()`` stops at the first note, so a large canon costs one directory read."""
    try:
        if any(not p.name.startswith(".") for p in (project / _CANON_SUBDIR).glob("*.md")):
            return True
    except OSError:
        pass  # an unreadable canon dir is not evidence of a project; fall through to the ledger
    try:
        return (project / _GROUND_AUDIT).stat().st_size > 0
    except OSError:
        return False


def maybe_reconcile(venv_dir: Path) -> None:
    """Run the canon reconcile via the engine python; best-effort, never fatal.

    A FULL sweep here is deliberate: the per-file mtime/size pre-filter is only a
    within-session optimisation, and the once-per-session full re-hash is what actually
    defeats mtime-spoofed forged verdicts (§1.8).

    Runs ONLY where a Burgess project already exists (_holds_project). The SessionStart hook fires
    in every folder a session opens, Burgess used there or not, and the old guard ("canon/ is a
    directory") passed everywhere once the server's eager Canon had created an empty canon/ at
    startup: the sweep then wrote its state file and checkpoint into home dirs, Obsidian vaults and
    unrelated repos, every session. Skipped silently, too, before anything is built.
    """
    project = _clean(os.environ.get("CLAUDE_PROJECT_DIR"))
    if not project or not _holds_project(Path(project)):
        return
    py = venv_python(venv_dir)
    if not py.exists():
        return
    snippet = (
        "import os\n"
        "from kg_engine.canon import Canon\n"
        "from kg_engine.reconciler import Reconciler\n"
        # ensure_layout=False: Reconciler.scan lays the vault out itself, and only once it has
        # something to persist, so a canon emptied between the guard above and this sweep (or a
        # guard/sweep disagreement) still leaves the folder untouched.
        "rep = Reconciler(Canon(os.environ['CLAUDE_PROJECT_DIR'], ensure_layout=False))"
        ".scan(full_sweep=True)\n"
        "if rep.requarantined:\n"
        "    print(f\"[burgess] reconcile re-quarantined {len(rep.requarantined)} \"\n"
        "          f\"forged verdict(s)\")\n"
    )
    try:
        # Bounded: a reconcile that hangs (an unreadable canon on a dead mount) must not hold the
        # provision lock open forever — the sweep is best-effort and re-runs next session (review-r11).
        subprocess.run([str(py), "-c", snippet], check=False, env=_engine_env(),
                       timeout=RECONCILE_TIMEOUT_SECS)
    except (OSError, subprocess.TimeoutExpired):
        pass


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _ok_with_reconcile(venv_dir: Path, reconcile: bool) -> int:
    """The single success post-condition: on any successful provision, reconcile if asked (§1.8)."""
    if reconcile:
        maybe_reconcile(venv_dir)
    return EXIT_OK


def _wait_for_lock(venv_dir: Path, deadline: float) -> int | None:
    """Wait until we hold the provision lock or the venv is otherwise current.

    Returns EXIT_OK when another builder finished while we waited (caller must still
    reconcile), EXIT_STILL_PROVISIONING when the wait deadline passed without the venv becoming
    ready, or None once the lock is acquired (caller proceeds to build). Keep release in the
    caller's finally — this helper never releases.
    """
    while not try_acquire(venv_dir):
        # re-evaluate readiness against the VENV interpreter's identity each iteration (M7): once
        # another builder lands the venv, _current_stamp queries that interpreter and matches.
        # Check readiness BEFORE the deadline so a just-finished build returns ready, not 2.
        if venv_current(venv_dir):
            print("[bootstrap] Another setup just finished — engine ready.", flush=True)
            return EXIT_OK
        if time.time() >= deadline:
            # We gave up waiting and the venv is NOT ready. Return NON-zero (review-low: wait-deadline):
            # a legitimately long cold source-build (igraph/leidenalg from sdist) can outlast the
            # deadline, and EXIT_OK here would tell the launcher "ready" and launch the server
            # against an unprovisioned venv. Distinct from EXIT_BUILD_FAILED.
            print(
                "[bootstrap] Another setup is still in progress past the wait deadline; "
                "it will finish in the background. Try again shortly.",
                flush=True,
            )
            return EXIT_STILL_PROVISIONING
        time.sleep(POLL_SECS)
    return None


def provision(venv_dir: Path, *, wait_secs: float, reconcile: bool = False) -> int:
    """Ensure the venv is current. Foreground; returns a process exit code."""
    if venv_current(venv_dir):  # compare against the VENV interpreter's identity (review-M7)
        print(f"[bootstrap] Engine already provisioned at {venv_dir}", flush=True)
        return _ok_with_reconcile(venv_dir, reconcile)

    if sys.version_info < MIN_PY:
        sys.stderr.write(
            f"[bootstrap] Need Python >= {MIN_PY[0]}.{MIN_PY[1]} to build the engine, "
            f"but this interpreter is {sys.version.split()[0]} ({sys.executable}).\n"
            "[bootstrap] Install Python 3.10+ (python.org / your package manager / "
            "`winget install Python.Python.3.12`) and start a new session.\n"
        )
        return EXIT_PY_TOO_OLD

    # Serialize against any other provisioner (the SessionStart worker, more terminals,
    # the launcher racing the background hook).
    deadline = time.time() + max(0.0, wait_secs)
    waited = _wait_for_lock(venv_dir, deadline)
    if waited == EXIT_OK:
        return _ok_with_reconcile(venv_dir, reconcile)
    if waited == EXIT_STILL_PROVISIONING:
        return EXIT_STILL_PROVISIONING

    try:
        if venv_current(venv_dir):  # re-check now that we hold the lock
            return _ok_with_reconcile(venv_dir, reconcile)
        do_install(venv_dir)
        print("[bootstrap] Done.", flush=True)
        return _ok_with_reconcile(venv_dir, reconcile)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # A failed OR TIMED-OUT pip/uv/venv command: in the foreground catch-up path (the launcher
        # racing the background build) show a clean, actionable line instead of a raw
        # traceback. The detached worker logs the same to provision.log.
        # A timeout is the interrupted-build path, not a distinct outcome: do_install's cleanup already
        # removed the husk and kept the owner sentinel, so the next session rebuilds. Report it as such —
        # TimeoutExpired carries `cmd` but no `returncode` (review-r11).
        log_path = venv_dir.parent / LOG_NAME
        if isinstance(exc, subprocess.TimeoutExpired):
            what = f"timed out after {exc.timeout:.0f}s"
        else:
            what = f"failed (exit {exc.returncode})"
        sys.stderr.write(
            f"[bootstrap] Install step {what}: "
            f"{' '.join(str(c) for c in exc.cmd)}\n"
            f"[bootstrap] See {log_path} for details, then start a new session.\n"
        )
        return EXIT_BUILD_FAILED
    finally:
        release(venv_dir)


def spawn_background(venv_dir: Path) -> int:
    """Re-spawn a fully detached worker and return immediately (non-blocking).

    Always spawn — even on a warm session where the venv is already current — because
    the worker also runs the per-session reconcile (§1.8). When the venv is ready the
    worker's ``is_ready`` fast path means it reconciles and exits in milliseconds.
    """
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    log_path = venv_dir.parent / LOG_NAME
    try:
        log = open(log_path, "ab", buffering=0)
    except OSError:
        log = subprocess.DEVNULL  # type: ignore[assignment]

    kwargs: dict = {}
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = (
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()),
             "--reconcile", "--venv", str(venv_dir)],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    finally:
        # The detached child inherited its own dup of the log fd; close the PARENT's copy so it doesn't
        # leak for the parent's lifetime (review-nit). DEVNULL is the int -1 sentinel, not a file object.
        if hasattr(log, "close"):
            try:
                log.close()
            except OSError:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision the Burgess engine venv.")
    parser.add_argument("--venv", default=None, help="explicit venv directory")
    parser.add_argument(
        "--background",
        action="store_true",
        help="spawn a detached worker and return immediately (used by the hook)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 0 iff the venv is provisioned and current (matches the stamp), "
        "non-zero otherwise; prints nothing to stdout. Used by the MCP launcher to "
        "detect a STALE venv (old interpreter present but deps changed).",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="run the canon reconcile (§1.8) once the venv is ready",
    )
    parser.add_argument(
        "--wait",
        type=float,
        # Default >= STALE_LOCK_SECS (+margin) so ONE foreground run can both wait out a
        # live build AND reclaim a dead one: a hard-killed holder's heartbeat freezes, so
        # try_acquire() can only steal the lock once its age passes STALE_LOCK_SECS (1800s).
        # A shorter deadline (the old 1200s) would fire BEFORE the lock became stealable and
        # return 0 without building — silently dropping every kg_* tool for that session.
        default=STALE_LOCK_SECS + 60.0,
        help="seconds a foreground run waits for an in-flight provision",
    )
    args = parser.parse_args(argv)

    venv_dir = resolve_venv_dir(args.venv)

    if args.check:
        # Freshness probe for the launcher: silent on stdout (it shares stdout with the
        # JSON-RPC channel), exit code carries the answer. 0 == ready & current.
        return 0 if venv_current(venv_dir) else 1

    print(
        f"[bootstrap] System Python: {sys.version.split()[0]} ({sys.executable})",
        flush=True,
    )
    print(f"[bootstrap] Target venv: {venv_dir}", flush=True)

    if args.background:
        return spawn_background(venv_dir)
    # The detached worker (spawned by --background) and the default/manual path are both
    # foreground here — the worker is just this same foreground provision, re-invoked
    # detached with --reconcile, so there is no separate worker-only entrypoint flag.
    return provision(venv_dir, wait_secs=args.wait, reconcile=args.reconcile)


if __name__ == "__main__":
    raise SystemExit(main())
