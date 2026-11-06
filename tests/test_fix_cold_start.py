"""Pins for the Windows cold-start defect fixed in 0.4.3.

What happened on a fresh 0.4.2 install on Windows 11 (the timeline is in the 0.4.3 CHANGELOG entry):

1. The SessionStart hook's detached worker ran ``uv sync``, and Windows opened a VISIBLE console window
   for it. A worker created with DETACHED_PROCESS has no console, so every console program it starts gets
   a new one; uv's output went to that window instead of ``provision.log``, and closing the window killed
   uv with STATUS_CONTROL_C_EXIT (3221225786).
2. The MCP launcher found no venv and ran the build in its own process. Claude Code gives an MCP server
   MCP_TIMEOUT ms (30 s by default) to answer ``initialize``; the build took longer, the client gave up
   and tore the launcher down mid-install. That left the provision lock held by a dead pid and a
   half-built venv, and the session had no kg_* tools.

Pinned here:

- the launcher never builds in its own process: on a cold venv it asks for a background build
  (``--background``, without ``--reconcile``) and only waits;
- it waits only while an engine launched at the end of the wait could still connect (MCP_TIMEOUT minus a
  startup reserve), then exits with a message that names the log and how to reconnect;
- a build that lands inside the window is launched in the same session, and a warm venv starts no build;
- a heal that cannot finish inside the window exits instead of relaunching;
- the worker gets a windowless console of its own (no DETACHED_PROCESS), and on Windows its children's
  output reaches the worker's log (the Windows-only test repeats the measurement);
- two workers appending to provision.log at once never overwrite each other's lines;
- the advisory import probes run after the venv is sealed, so they no longer hold readiness back, and a
  probe that times out is not reported as a missing dependency;
- ``--background`` reconciles only when asked, and the SessionStart hook is the caller that asks.

The end-to-end tests run the SHIPPED launcher against a fake plugin root: a stand-in ``bootstrap.py``
that records how it is called and "builds" on request, and a stand-in engine that records each launch.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_LAUNCH_MJS = REPO / "scripts" / "launch_server.mjs"
_PROVISION_MJS = REPO / "hooks" / "provision.mjs"
_BOOT_PATH = REPO / "scripts" / "bootstrap.py"

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("kg_bootstrap_cold_start", _BOOT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bootstrap = _load_bootstrap()


def _node(body: str) -> dict:
    """Import the shipped launcher in a node ESM harness and return the JSON line it prints."""
    script = f"import * as L from {json.dumps(_LAUNCH_MJS.as_uri())};\n" + body
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------------------------------- #
# The connect window and the wait (pure helpers, fake clock)
# --------------------------------------------------------------------------------------------------- #
@needs_node
def test_connect_window_follows_mcp_timeout():
    out = _node(r"""
const t = (v) => L.connectTimeoutMs(v === undefined ? {} : { MCP_TIMEOUT: v });
process.stdout.write(JSON.stringify({
  unset: t(), set: t("120000"), quoted: t('"60000"'), junk: t("soon"), zero: t("0"), negative: t("-5"),
  dflt: L.provisionDeadline(1000, {}) - 1000,
  raised: L.provisionDeadline(1000, { MCP_TIMEOUT: "600000" }) - 1000,
  tiny: L.provisionDeadline(1000, { MCP_TIMEOUT: "4000" }) - 1000,
  reserve: L.CONNECT.ENGINE_START_RESERVE_MS, def: L.CONNECT.DEFAULT_TIMEOUT_MS,
}));
""")
    assert out["def"] == out["unset"] == 30000, "Claude Code's default when MCP_TIMEOUT is unset"
    assert out["set"] == 120000 and out["quoted"] == 60000
    assert out["junk"] == out["zero"] == out["negative"] == 30000
    # the wait stops early enough for the engine to import and answer before the client gives up
    assert 0 < out["dflt"] == 30000 - out["reserve"]
    assert out["raised"] == 600000 - out["reserve"], "a raised MCP_TIMEOUT buys a first session a longer wait"
    assert out["tiny"] == 0, "a window shorter than the reserve leaves no time to wait, not negative time"


@needs_node
def test_wait_polls_up_to_the_deadline_and_never_past_it():
    out = _node(r"""
function run(readyAt, deadline) {
  let t = 0, checks = 0;
  const sleeps = [];
  const ok = L.waitUntilReady({
    isReady: () => { checks++; return readyAt !== null && t >= readyAt; },
    deadline, now: () => t, sleep: (ms) => { sleeps.push(ms); t += ms; }, pollMs: 1000,
  });
  return { ok, sleeps, checks, t };
}
process.stdout.write(JSON.stringify({
  never: run(null, 2500), soon: run(1500, 20000), atDeadline: run(2500, 2500), already: run(0, 0),
}));
""")
    assert out["never"] == {"ok": False, "sleeps": [1000, 1000, 500], "checks": 4, "t": 2500}, (
        "the last sleep is trimmed to the deadline")
    assert out["soon"]["ok"] is True and out["soon"]["t"] == 2000, "noticed at the first poll after it lands"
    assert out["atDeadline"]["ok"] is True, "a build that lands exactly at the deadline still counts"
    assert out["already"] == {"ok": True, "sleeps": [], "checks": 1, "t": 0}


@needs_node
def test_a_heal_that_misses_the_window_exits_instead_of_relaunching():
    """heal() returning false = the forced rebuild is still running at the connect deadline. Relaunching
    would start an engine on a venv the worker may be rewriting in place, for a client about to give up."""
    out = _node(r"""
import { EventEmitter } from "node:events";
let t = 1e6;
const children = [], pending = [];
let exitCode = null, healCalls = 0;
const sup = L.createSupervisor({
  spawnEngine: () => { const c = new EventEmitter(); children.push(c); return c; },
  exit: (code) => { exitCode = code; },
  heal: () => { healCalls++; return false; },
  now: () => t, schedule: (fn, ms) => pending.push([fn, ms]), log: () => {},
  servedInit: () => false, clearMarker: () => {},
});
sup.start();
t += 300; children[0].emit("exit", 1, null);   // an import error during STARTUP -> the one-time heal
process.stdout.write(JSON.stringify({ spawns: children.length, heal: healCalls, pending: pending.length, exitCode }));
""")
    assert out == {"spawns": 1, "heal": 1, "pending": 0, "exitCode": 1}


# --------------------------------------------------------------------------------------------------- #
# The shipped launcher, end to end, against a fake plugin root
# --------------------------------------------------------------------------------------------------- #
_FAKE_BOOTSTRAP = r'''
"""Stand-in for scripts/bootstrap.py: records every call, "builds" only when asked to in the background."""
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
venv = Path(args[args.index("--venv") + 1])
with open(os.environ["FAKE_BOOT_CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if "--check" in args:
    sys.exit(0 if (venv / "install.stamp").exists() else 1)
if "--background" in args:
    delay = float(os.environ["FAKE_BUILD_SECS"])
    if delay >= 0:  # a detached build that lands `delay` seconds from now
        detach = {"creationflags": 0x08000200} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, __file__, "--land", str(delay), "--venv", str(venv)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **detach)
    sys.exit(0)
if "--land" in args:
    time.sleep(float(args[args.index("--land") + 1]))
    venv.mkdir(parents=True, exist_ok=True)
    (venv / "engine-python.txt").write_text(sys.executable, encoding="utf-8")
    (venv / "install.stamp").write_text("fake", encoding="utf-8")
    sys.exit(0)
sys.exit(99)  # anything else would be a build in the launcher's own process
'''

_FAKE_ENGINE = r'''
import os, sys
with open(os.environ["FAKE_ENGINE_LAUNCHES"], "a", encoding="utf-8") as f:
    f.write("launched\n")
sys.exit(int(os.environ.get("FAKE_ENGINE_EXIT", "0")))
'''


def _hermetic_env(**extra: str) -> dict:
    """The test process's env minus anything that would steer the launcher at a real plugin."""
    drop = ("KG_", "CLAUDE_", "MCP_TIMEOUT", "PYTHONPATH")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    env.update(extra)
    return env


@pytest.fixture
def fake_plugin(tmp_path):
    root = tmp_path / "root"
    (root / "scripts" / "kg_engine").mkdir(parents=True)
    (root / "scripts" / "bootstrap.py").write_text(_FAKE_BOOTSTRAP, encoding="utf-8")
    (root / "scripts" / "kg_engine" / "__init__.py").write_text("", encoding="utf-8")
    (root / "scripts" / "kg_engine" / "server.py").write_text(_FAKE_ENGINE, encoding="utf-8")
    return root


class Launch:
    """One run of the shipped launcher against the fake root, and what it left behind."""

    def __init__(self, tmp_path: Path, root: Path):
        self.data = tmp_path / "data"
        self.venv = self.data / ".venv"
        self.calls_file = tmp_path / "boot-calls.jsonl"
        self.launches_file = tmp_path / "engine-launches.txt"
        self.root = root

    def ready_venv(self) -> None:
        self.venv.mkdir(parents=True)
        (self.venv / "engine-python.txt").write_text(sys.executable, encoding="utf-8")
        (self.venv / "install.stamp").write_text("fake", encoding="utf-8")

    def run(self, *, mcp_timeout_ms: int, build_secs: float, engine_exit: int = 0):
        env = _hermetic_env(
            CLAUDE_PLUGIN_ROOT=str(self.root), CLAUDE_PLUGIN_DATA=str(self.data), KG_DATA=str(self.data),
            KG_ENGINE_VENV=str(self.venv), PYTHONPATH=str(self.root / "scripts"),
            MCP_TIMEOUT=str(mcp_timeout_ms), FAKE_BUILD_SECS=str(build_secs),
            FAKE_BOOT_CALLS=str(self.calls_file), FAKE_ENGINE_LAUNCHES=str(self.launches_file),
            FAKE_ENGINE_EXIT=str(engine_exit),
        )
        t0 = time.monotonic()
        self.result = subprocess.run([NODE, str(_LAUNCH_MJS)], env=env, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, timeout=60)
        self.elapsed = time.monotonic() - t0
        return self.result

    @property
    def calls(self) -> list[list[str]]:
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text(encoding="utf-8").splitlines()]

    @property
    def background_calls(self) -> list[list[str]]:
        return [c for c in self.calls if "--background" in c]

    @property
    def launches(self) -> int:
        if not self.launches_file.exists():
            return 0
        return len(self.launches_file.read_text(encoding="utf-8").splitlines())

    def venv_arg(self, call: list[str]) -> Path:
        return Path(os.path.realpath(call[call.index("--venv") + 1]))


@needs_node
def test_cold_launch_hands_the_build_off_and_gives_up_cleanly(tmp_path, fake_plugin):
    run = Launch(tmp_path, fake_plugin)
    r = run.run(mcp_timeout_ms=11_500, build_secs=-1)  # a 1.5 s window; the build never lands

    assert r.returncode == 1
    # one background build requested, for the right venv, without the hook's sweep...
    assert len(run.background_calls) == 1
    (bg,) = run.background_calls
    assert bg[:1] == ["--background"] and "--reconcile" not in bg
    assert run.venv_arg(bg) == Path(os.path.realpath(run.venv))
    # ...and no build in the launcher's own process: every call was a probe or a hand-off
    assert all({"--check", "--background"} & set(c) for c in run.calls), run.calls
    # it waited for the window, not for the build
    assert 1.4 <= run.elapsed < 15, run.elapsed
    assert run.launches == 0, "no engine is launched on a venv that is not ready"
    # the explanation goes where the user looks (/mcp shows stderr) and where it lasts (server.log)
    assert "still being set up in the background" in r.stderr
    assert "/mcp" in r.stderr and "MCP_TIMEOUT" in r.stderr
    assert str(run.data / "provision.log") in r.stderr
    assert "venv not ready inside the connect window" in (run.data / "server.log").read_text(encoding="utf-8")
    assert r.stdout == "", "nothing but JSON-RPC may reach stdout"


@needs_node
def test_a_build_that_lands_inside_the_window_is_launched_in_the_same_session(tmp_path, fake_plugin):
    run = Launch(tmp_path, fake_plugin)
    r = run.run(mcp_timeout_ms=16_000, build_secs=1.0)  # a 6 s window; the build lands after ~1 s

    assert run.launches == 1, r.stderr
    assert r.returncode == 0, r.stderr  # the fake engine exits 0, which the supervisor treats as clean
    assert "still being set up" not in r.stderr
    assert len(run.background_calls) == 1
    assert run.elapsed < 15, run.elapsed


@needs_node
def test_a_warm_venv_launches_without_starting_a_build(tmp_path, fake_plugin):
    run = Launch(tmp_path, fake_plugin)
    run.ready_venv()
    r = run.run(mcp_timeout_ms=30_000, build_secs=-1)

    assert run.launches == 1, r.stderr
    assert r.returncode == 0, r.stderr
    assert run.background_calls == [], "a current venv must not spawn a worker on every connect"
    assert [c[0] for c in run.calls] == ["--check"]


@needs_node
def test_a_startup_crash_heals_in_the_background_and_exits_when_out_of_time(tmp_path, fake_plugin):
    """The real heal wiring in main(): the stamp is dropped so the worker cannot take its ready fast path,
    the rebuild goes to a background worker, and when it has not landed by the deadline the launcher
    reports and exits instead of relaunching onto the venv being rebuilt."""
    run = Launch(tmp_path, fake_plugin)
    run.ready_venv()
    r = run.run(mcp_timeout_ms=12_000, build_secs=-1, engine_exit=1)  # import error at startup; 2 s window

    assert r.returncode == 1
    assert run.launches == 1, "the broken engine is not relaunched while its venv is rebuilt"
    assert not (run.venv / "install.stamp").exists(), "the heal forced a real rebuild"
    assert len(run.background_calls) == 1 and "--reconcile" not in run.background_calls[0]
    assert "still being set up in the background" in r.stderr


# --------------------------------------------------------------------------------------------------- #
# bootstrap: the worker's console and its reconcile
# --------------------------------------------------------------------------------------------------- #
def test_worker_gets_a_windowless_console_of_its_own_not_none():
    DETACHED_PROCESS = 0x00000008
    assert bootstrap.WORKER_CREATIONFLAGS == bootstrap.CREATE_NEW_PROCESS_GROUP | bootstrap.CREATE_NO_WINDOW
    assert not bootstrap.WORKER_CREATIONFLAGS & DETACHED_PROCESS


@pytest.mark.skipif(os.name != "nt", reason="Windows console semantics")
def test_worker_children_get_no_window_and_write_to_the_worker_log(tmp_path):
    """The measurement behind WORKER_CREATIONFLAGS, kept as a regression test. A child spawned the way
    bootstrap.run spawns uv (no flags, no redirection) must neither open a window nor lose its output.
    Under the old DETACHED_PROCESS worker it got a new visible console and wrote into that instead."""
    child = ("import ctypes; k = ctypes.windll.kernel32; u = ctypes.windll.user32; h = k.GetConsoleWindow(); "
             "print('child-output visible=%s' % bool(h and u.IsWindowVisible(h)), flush=True)")
    worker = textwrap.dedent(f"""
        import subprocess, sys
        subprocess.run([sys.executable, "-c", {child!r}])
    """)
    log_path = tmp_path / "provision.log"
    with open(log_path, "ab", buffering=0) as log:
        p = subprocess.Popen([sys.executable, "-c", worker], stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, close_fds=True,
                             creationflags=bootstrap.WORKER_CREATIONFLAGS)
        assert p.wait(timeout=60) == 0
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "child-output visible=False" in text, text


_APPENDER = r'''
import importlib.util, subprocess, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("kg_bootstrap_appender", sys.argv[1])
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
tag, path = sys.argv[2], Path(sys.argv[3])
with boot._open_log_for_append(path) as log:
    for i in range(1500):
        log.write(f"{tag} worker {i:05d}\n".encode())
    # ...and through an inherited handle, the way uv writes through the worker's stdout
    subprocess.run([sys.executable, "-c",
                    "import sys\nfor i in range(1500): print('%s child %05d' % (sys.argv[1], i), flush=True)",
                    tag], stdout=log.fileno(), check=True)
'''


def test_concurrent_workers_never_overwrite_each_others_log_lines(tmp_path):
    """Two workers append to provision.log at once on every cold start (the hook's and the launcher's).
    On Windows a plain "ab" open lost 11-16 % of the lines in this exact shape; POSIX O_APPEND never
    does, so this is a real check on the Windows CI leg and a contract check elsewhere."""
    log = tmp_path / "provision.log"
    env = {**os.environ, "PYTHONPATH": str(REPO / "scripts")}
    procs = [subprocess.Popen([sys.executable, "-c", _APPENDER, str(_BOOT_PATH), tag, str(log)], env=env)
             for tag in ("A", "B")]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    lines = log.read_bytes().splitlines()
    assert [sum(line.startswith(t + b" ") for line in lines) for t in (b"A", b"B")] == [3000, 3000]
    assert len(lines) == 6000


def test_background_worker_reconciles_only_when_asked(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda cmd, **kw: seen.append((cmd, kw)))
    venv = tmp_path / "venv"
    bootstrap.spawn_background(venv, reconcile=True)
    bootstrap.spawn_background(venv)
    (swept, _), (plain, kw) = seen
    assert "--reconcile" in swept and "--reconcile" not in plain
    assert swept[-2:] == plain[-2:] == ["--venv", str(venv)]
    if os.name != "nt":
        assert kw["start_new_session"] is True
    else:
        assert kw["creationflags"] == bootstrap.WORKER_CREATIONFLAGS


def test_background_flag_forwards_reconcile(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(bootstrap, "spawn_background",
                        lambda venv_dir, *, reconcile=False: asked.append(reconcile) or 0)
    venv = str(tmp_path / "venv")
    assert bootstrap.main(["--background", "--venv", venv]) == 0
    assert bootstrap.main(["--background", "--reconcile", "--venv", venv]) == 0
    assert asked == [False, True]


# --------------------------------------------------------------------------------------------------- #
# bootstrap: what holds a venv back from being "ready"
# --------------------------------------------------------------------------------------------------- #
def _fake_install(vd, *a, **k):
    """An install that leaves what a real one leaves for the cleanup paths to look at."""
    py = bootstrap.venv_python(vd)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!stub\n", encoding="utf-8")
    (vd / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")


@pytest.fixture
def stubbed_install(tmp_path, monkeypatch):
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install)
    monkeypatch.setattr(bootstrap, "verify_imports", lambda py: None)
    return tmp_path / "venv"


def test_advisory_probes_run_after_the_venv_is_sealed(stubbed_install, monkeypatch):
    """The stamp is what every waiter polls for. A probe ahead of it held the venv back for 28-60 s on
    Windows while deciding nothing, and the launcher waiting on it has only its connect window."""
    venv_dir = stubbed_install
    seen = []

    def probe(name):
        def run(py):
            seen.append((name, (venv_dir / bootstrap.STAMP_NAME).exists(),
                         (venv_dir / bootstrap.PTR_NAME).exists(), bootstrap._has_owner_sentinel(venv_dir)))
        return run

    monkeypatch.setattr(bootstrap, "probe_leidenalg", probe("leidenalg"))
    monkeypatch.setattr(bootstrap, "probe_divergence", probe("divergence"))
    bootstrap.do_install(venv_dir)
    # (name, stamp written, pointer written, reclaim token still live)
    assert seen == [("leidenalg", True, True, False), ("divergence", True, True, False)]


def test_a_probe_interrupted_after_the_seal_keeps_the_venv(stubbed_install, monkeypatch):
    """Before the reorder an interrupt during a probe landed in the install's cleanup, which deletes the
    venv. A sealed venv is usable; nothing after the seal may take it down."""
    venv_dir = stubbed_install
    monkeypatch.setattr(bootstrap, "probe_leidenalg", lambda py: None)

    def interrupted(py):
        raise KeyboardInterrupt

    monkeypatch.setattr(bootstrap, "probe_divergence", interrupted)
    with pytest.raises(KeyboardInterrupt):
        bootstrap.do_install(venv_dir)
    assert (venv_dir / bootstrap.STAMP_NAME).exists()
    assert bootstrap.venv_python(venv_dir).exists()


def test_a_probe_that_times_out_is_not_reported_as_missing(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "PROBE_TIMEOUT_SECS", 0.01)  # shorter than any interpreter start-up
    bootstrap.probe_divergence(Path(sys.executable))
    bootstrap.probe_leidenalg(Path(sys.executable))
    out = capsys.readouterr().out
    assert "divergence deps: no answer from the import probe within 0.01s" in out
    assert "does not mean they are missing" in out
    assert "leidenalg: no answer from the import probe within 0.01s" in out
    assert "unavailable" not in out, "no answer is not a failed import"
    # with no timeout message, a timeout keeps the generic wording (test_review_r11 pins the swallow)
    bootstrap._soft_probe(Path(sys.executable), "import time; time.sleep(30)", "unavailable ({exc})")
    assert "unavailable (TimeoutExpired" in capsys.readouterr().out


def test_a_waiter_that_finds_the_build_done_says_so(tmp_path, monkeypatch, capsys):
    """The usual way the second worker of a cold start leaves: it takes the lock the builder just freed
    and finds the venv current. That path used to print nothing, so its log stanza ended at
    "Target venv" and read as a worker that had died."""
    states = iter([False, True])  # not current at the start; current once the lock is ours
    monkeypatch.setattr(bootstrap, "venv_current", lambda vd: next(states))
    monkeypatch.setattr(bootstrap, "_wait_for_lock", lambda vd, deadline: None)  # the lock was free
    monkeypatch.setattr(bootstrap, "release", lambda vd: None)
    monkeypatch.setattr(bootstrap, "do_install", lambda vd: pytest.fail("a current venv is not rebuilt"))
    assert bootstrap.provision(tmp_path / "venv", wait_secs=5) == bootstrap.EXIT_OK
    assert "Another setup just finished" in capsys.readouterr().out


@needs_node
def test_the_session_start_hook_is_the_caller_that_asks_for_the_sweep(tmp_path, fake_plugin):
    calls = tmp_path / "boot-calls.jsonl"
    env = _hermetic_env(CLAUDE_PLUGIN_ROOT=str(fake_plugin), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
                        FAKE_BOOT_CALLS=str(calls), FAKE_BUILD_SECS="-1")
    r = subprocess.run([NODE, str(_PROVISION_MJS)], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    recorded = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert len(recorded) == 1
    assert recorded[0][:2] == ["--background", "--reconcile"]
    assert Path(os.path.realpath(recorded[0][-1])) == Path(os.path.realpath(tmp_path / "data" / ".venv"))
