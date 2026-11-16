"""0.19.2: on Windows the engine venv is built on the signed interpreter, and a failed build says so.

Field report (Windows 11, Smart App Control on, 2026-11-16). At 12:48 UTC Windows stopped trusting the engine
venv's ``python.exe``. That file is not the interpreter: on Windows a venv's ``python.exe`` is a copy of its base
interpreter's launcher, and uv had built the venv on its own managed CPython 3.12.13, whose launcher is
unsigned. bootstrap itself ran on the PSF-signed python.org 3.14.3, but ``uv sync`` was given no interpreter
and preferred its managed one. At 13:02 the next session could not start the venv's Python, so its readiness
check failed and a rebuild began. The rebuild installed every package, then the import check hit
``OSError: [WinError 4551]`` and the venv was removed. Five rebuilds failed the same way. Every launch reported
that the environment was "still being set up in the background", normal after an update, and suggested
MCP_TIMEOUT. The cause was only in provision.log. A venv built on the python.org interpreter started.

So, in this release:
- on Windows, ``uv sync`` builds the venv on the interpreter running bootstrap, unless the user set
  ``UV_PYTHON``; other platforms keep uv's choice;
- a failed build leaves ``provision.failed`` beside the log, one line naming the step and the cause, and a
  refusal by Application Control names the refused file; a provision that ends ready removes it;
- the MCP launcher stops waiting as soon as a build fails and reports that failure with its cause; while a
  build is still running after an earlier failure, it says what failed last time.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_BOOT_PATH = REPO / "scripts" / "bootstrap.py"
_LAUNCH_MJS = REPO / "scripts" / "launch_server.mjs"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("kg_bootstrap_signed_venv", _BOOT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bootstrap = _load_bootstrap()
BLOCKED = r"C:\Users\u\.claude\plugins\data\burgess-sergiparpal\.venv\Scripts\python.exe"


class _AppControlRefusal(OSError):
    """What Windows raises when Application Control refuses CreateProcess; POSIX OSErrors carry no winerror."""
    winerror = 4551


# --------------------------------------------------------------------------- the interpreter uv builds on


def _uv_cmd(monkeypatch, tmp_path, *, windows: bool, uv_python: "str | None" = None) -> list:
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\nname = 'x'\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    monkeypatch.setattr(bootstrap, "_is_windows", lambda: windows)
    if uv_python is None:
        monkeypatch.delenv("UV_PYTHON", raising=False)
    else:
        monkeypatch.setenv("UV_PYTHON", uv_python)
    seen = []
    monkeypatch.setattr(bootstrap, "run", lambda cmd, **kw: seen.append(list(cmd)))
    bootstrap.install_with_uv(tmp_path / "data" / ".venv", "uv")
    assert len(seen) == 1
    return seen[0]


def test_on_windows_uv_builds_the_venv_on_the_interpreter_running_bootstrap(monkeypatch, tmp_path, capsys):
    cmd = _uv_cmd(monkeypatch, tmp_path, windows=True)
    assert cmd == ["uv", "sync", "--no-install-project", "--python", sys.executable]
    assert f"Building the venv on this interpreter: {sys.executable}" in capsys.readouterr().out


def test_a_uv_python_the_user_chose_is_kept(monkeypatch, tmp_path):
    assert _uv_cmd(monkeypatch, tmp_path, windows=True, uv_python=r"C:\Python314\python.exe") == \
        ["uv", "sync", "--no-install-project"]


def test_elsewhere_uv_keeps_its_choice(monkeypatch, tmp_path):
    assert _uv_cmd(monkeypatch, tmp_path, windows=False) == ["uv", "sync", "--no-install-project"]


# --------------------------------------------------------------------------- the failure record


@pytest.fixture
def building(monkeypatch, tmp_path):
    """provision() on a venv that is not current, holding the lock, with do_install to be replaced."""
    venv_dir = tmp_path / "data" / ".venv"
    venv_dir.parent.mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "venv_current", lambda v: False)
    monkeypatch.setattr(bootstrap, "_wait_for_lock", lambda v, deadline: None)
    monkeypatch.setattr(bootstrap, "release", lambda v: None)
    return venv_dir


def _record(venv_dir: Path) -> dict:
    return json.loads((venv_dir.parent / bootstrap.FAILED_NAME).read_text(encoding="utf-8"))


def test_a_refused_program_fails_the_build_and_names_what_refused_it(monkeypatch, building, capsys):
    def refused(venv_dir):
        raise _AppControlRefusal(22, "Una directiva de Control de aplicaciones bloqueó este archivo", BLOCKED)

    monkeypatch.setattr(bootstrap, "do_install", refused)
    assert bootstrap.provision(building, wait_secs=0) == bootstrap.EXIT_BUILD_FAILED
    rec = _record(building)
    assert rec["error"] == ("Windows Application Control (Smart App Control or a WDAC policy) refused to run "
                            f"{BLOCKED} (WinError 4551)")
    assert rec["at"].endswith("Z")
    assert "Install step could not run: Windows Application Control" in capsys.readouterr().err


def test_a_refused_step_carries_the_program_it_started(monkeypatch):
    def refuse(cmd, **kw):
        raise _AppControlRefusal(22, "blocked")  # Windows names no file

    monkeypatch.setattr(bootstrap.subprocess, "run", refuse)
    with pytest.raises(OSError) as info:
        bootstrap.run([BLOCKED, "-c", "import mcp"], timeout=5)
    assert info.value.filename == BLOCKED
    assert bootstrap._failure_line(info.value).endswith(f"refused to run {BLOCKED} (WinError 4551)")


def test_a_failed_step_is_recorded_with_its_exit(monkeypatch, building):
    def failed(venv_dir):
        raise subprocess.CalledProcessError(1, [BLOCKED, "-c", bootstrap._VERIFY_IMPORTS])

    monkeypatch.setattr(bootstrap, "do_install", failed)
    assert bootstrap.provision(building, wait_secs=0) == bootstrap.EXIT_BUILD_FAILED
    assert _record(building)["error"] == f"failed (exit 1): the import check ({BLOCKED})"


def test_a_timed_out_step_is_recorded(monkeypatch, building):
    def slow(venv_dir):
        raise subprocess.TimeoutExpired(["uv", "sync", "--no-install-project"], 1800)

    monkeypatch.setattr(bootstrap, "do_install", slow)
    assert bootstrap.provision(building, wait_secs=0) == bootstrap.EXIT_BUILD_FAILED
    assert _record(building)["error"] == "timed out after 1800s: uv sync --no-install-project"


def test_a_refusal_with_a_message_is_recorded_and_still_exits(monkeypatch, building):
    def refuses(venv_dir):
        raise SystemExit("[bootstrap] refusing to provision into X: it already exists\n"
                         "[bootstrap] Point --venv at a dedicated path.")

    monkeypatch.setattr(bootstrap, "do_install", refuses)
    with pytest.raises(SystemExit):
        bootstrap.provision(building, wait_secs=0)
    assert _record(building)["error"] == ("refusing to provision into X: it already exists "
                                          "Point --venv at a dedicated path.")


def test_a_provision_that_ends_ready_removes_the_record(monkeypatch, tmp_path):
    venv_dir = tmp_path / "data" / ".venv"
    venv_dir.parent.mkdir(parents=True)
    (venv_dir.parent / bootstrap.FAILED_NAME).write_text('{"at": "x", "error": "y"}\n', encoding="utf-8")
    monkeypatch.setattr(bootstrap, "venv_current", lambda v: True)
    assert bootstrap.provision(venv_dir, wait_secs=0) == bootstrap.EXIT_OK
    assert not (venv_dir.parent / bootstrap.FAILED_NAME).exists()


def test_the_launcher_reads_the_record_bootstrap_writes():
    resolve = (REPO / "scripts" / "_engine_resolve.mjs").read_text(encoding="utf-8")
    assert f'export const PROVISION_FAILED_NAME = "{bootstrap.FAILED_NAME}";' in resolve


# --------------------------------------------------------------------------- the launcher


def _node(body: str) -> dict:
    script = f"import * as L from {json.dumps(_LAUNCH_MJS.as_uri())};\n" + body
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_the_wait_ends_as_soon_as_the_build_fails():
    out = _node(r"""
let t = 0, polls = 0;
const ready = L.waitUntilReady({
  isReady: () => false, deadline: 20_000, failed: () => ++polls >= 3,
  now: () => t, sleep: (ms) => { t += ms; }, pollMs: 1_000,
});
process.stdout.write(JSON.stringify({ ready, waitedMs: t, polls }));
""")
    assert out == {"ready": False, "waitedMs": 2000, "polls": 3}


@needs_node
def test_a_record_counts_as_this_launchs_failure_only_from_its_start(tmp_path):
    (tmp_path / "provision.failed").write_text(json.dumps({"at": "2026-11-16T13:02:40Z", "error": "boom"}),
                                               encoding="utf-8")
    out = _node(f"""
const f = L.readBuildFailure({json.dumps(str(tmp_path))});
const none = L.readBuildFailure({json.dumps(str(tmp_path / "nowhere"))});
process.stdout.write(JSON.stringify({{ at: f.at, error: f.error, before: L.failedSince(f, f.mtimeMs - 1),
  after: L.failedSince(f, f.mtimeMs + 1), none }}));
""")
    assert out == {"at": "2026-11-16T13:02:40Z", "error": "boom", "before": True, "after": False, "none": None}


_FAKE_BOOTSTRAP = r'''
"""Stand-in for scripts/bootstrap.py: a background build that fails `FAKE_FAIL_SECS` from now (never if < 0)."""
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
venv = Path(args[args.index("--venv") + 1])
if "--check" in args:
    sys.exit(0 if (venv / "install.stamp").exists() else 1)
if "--background" in args:
    secs = float(os.environ["FAKE_FAIL_SECS"])
    if secs >= 0:
        detach = {"creationflags": 0x08000200} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, __file__, "--fail", str(secs), "--venv", str(venv)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach)
    sys.exit(0)
if "--fail" in args:
    time.sleep(float(args[args.index("--fail") + 1]))
    record = {"at": "2026-11-16T13:02:40Z", "error": os.environ["FAKE_FAIL_ERROR"]}
    venv.parent.mkdir(parents=True, exist_ok=True)
    (venv.parent / "provision.failed").write_text(json.dumps(record), encoding="utf-8")
    sys.exit(1)
sys.exit(99)
'''

REFUSED = ("Windows Application Control (Smart App Control or a WDAC policy) refused to run "
           f"{BLOCKED} (WinError 4551)")


def _launch(tmp_path: Path, *, mcp_timeout_ms: int, fail_secs: float) -> "tuple[subprocess.CompletedProcess, float, Path]":
    root = tmp_path / "root"
    (root / "scripts" / "kg_engine").mkdir(parents=True)
    (root / "scripts" / "bootstrap.py").write_text(_FAKE_BOOTSTRAP, encoding="utf-8")
    (root / "scripts" / "kg_engine" / "__init__.py").write_text("", encoding="utf-8")
    (root / "scripts" / "kg_engine" / "server.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    drop = ("KG_", "CLAUDE_", "MCP_TIMEOUT", "PYTHONPATH")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    env.update(CLAUDE_PLUGIN_ROOT=str(root), CLAUDE_PLUGIN_DATA=str(data), KG_DATA=str(data),
               KG_ENGINE_VENV=str(data / ".venv"), PYTHONPATH=str(root / "scripts"),
               MCP_TIMEOUT=str(mcp_timeout_ms), FAKE_FAIL_SECS=str(fail_secs), FAKE_FAIL_ERROR=REFUSED)
    t0 = time.monotonic()
    r = subprocess.run([NODE, str(_LAUNCH_MJS)], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=60)
    return r, time.monotonic() - t0, data


@needs_node
def test_a_build_that_fails_during_the_wait_is_reported_as_failed(tmp_path):
    r, elapsed, data = _launch(tmp_path, mcp_timeout_ms=30_000, fail_secs=0.5)  # a 20 s window

    assert r.returncode == 1
    assert elapsed < 12, f"the wait should end when the build fails, not at the window's end ({elapsed:.1f}s)"
    assert f"could not be built: {REFUSED}." in r.stderr
    assert str(data / "provision.log") in r.stderr and "will not help" in r.stderr
    assert "still being set up" not in r.stderr
    assert f"venv build failed (2026-11-16T13:02:40Z): {REFUSED}" in (data / "server.log").read_text(encoding="utf-8")
    assert r.stdout == "", "nothing but JSON-RPC may reach stdout"


@needs_node
def test_a_build_still_running_after_a_failure_says_what_failed_last_time(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    old = data / "provision.failed"
    old.write_text(json.dumps({"at": "2026-11-16T13:02:40Z", "error": REFUSED}), encoding="utf-8")
    past = time.time() - 600
    os.utime(old, (past, past))
    r, _, _ = _launch(tmp_path, mcp_timeout_ms=11_500, fail_secs=-1)  # a 1.5 s window; this build never ends

    assert r.returncode == 1
    assert "A build is running in the background, but the last one failed (2026-11-16T13:02:40Z)" in r.stderr
    assert REFUSED in r.stderr and "fix that cause first" in r.stderr
    assert "normal on the first session" not in r.stderr
