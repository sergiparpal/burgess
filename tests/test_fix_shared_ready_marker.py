"""0.11.2: each engine the supervisor spawns has a readiness marker of its own.

The supervisor (``scripts/launch_server.mjs``) tells a crash after the engine served ``initialize`` from a
crash during startup by the readiness marker the engine writes as its serve loop comes up. Through 0.11.1
every engine wrote one ``.engine-ready`` under ``KG_DATA``, and an installed plugin sets ``KG_DATA`` to
``CLAUDE_PLUGIN_DATA``: a single dir for every session on the machine, whatever its folder. On 2026-11-09 the
user's Windows machine ran two at once, a desktop session in another folder on 0.11.0 and the prueba-burgess
terminal session on 0.11.1, both logging to the same ``server.log``. So:

- a supervisor spawning its engine deleted the marker of another session's live engine, and an engine shutting
  down cleanly deleted whichever marker was there;
- a marker another session's engine had just written passed for this child's.

A crash in an engine's first ``EARLY_FAILURE_MS`` could then be read either way wrong: a post-init crash as a
startup failure (a venv rebuild nobody needed, then a relaunch onto a pipe the client had already handshaked),
or a startup failure as post-init (no self-heal). Nothing in that ``server.log`` had crashed yet: all 21 exits
were clean.

Now the supervisor names a fresh file for each spawn and hands its path over in ``KG_READY_MARKER``. The engine
writes and removes only that file, the supervisor reads and removes only that file, and a supervisor that
starts sweeps markers more than an hour old, which no exit can still need.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kg_engine import server as S

REPO = Path(__file__).resolve().parents[1]
_LAUNCH_MJS = REPO / "scripts" / "launch_server.mjs"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")

PER_SPAWN = re.compile(r"^\.engine-ready-\d+-[0-9a-f]{12}$")
LEGACY = ".engine-ready"                    # the one marker every engine shared through 0.11.1
OTHER = ".engine-ready-99999-0123456789ab"  # another session's per-spawn marker
TWO_HOURS = 2 * 60 * 60


def _serve_once(seen: list, data: Path) -> None:
    """Run the engine's real lifespan around one look at KG_DATA, as its serve loop would."""
    async def serve():
        async with S.readiness_lifespan():
            seen.append(sorted(p.name for p in data.iterdir()))
    asyncio.run(serve())


# ---- the engine ------------------------------------------------------------------------------------------

def test_the_engine_writes_its_marker_where_its_supervisor_said(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    marker = data / ".engine-ready-4242-00000000beef"
    monkeypatch.setenv("KG_DATA", str(data))
    monkeypatch.setenv(S.READY_MARKER_ENV, str(marker))
    seen: list = []
    _serve_once(seen, data)
    assert seen == [[marker.name]], "while serving, its own marker and nothing else"
    assert not marker.exists(), "a clean shutdown removes it"


def test_an_engine_started_without_a_supervisor_writes_no_marker(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("KG_DATA", str(data))
    monkeypatch.delenv(S.READY_MARKER_ENV, raising=False)
    seen: list = []
    _serve_once(seen, data)
    assert seen == [[]], "0.11.1 wrote the shared .engine-ready here, which no supervisor of this engine reads"


def test_an_engine_leaves_other_engines_markers_alone(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    for name in (LEGACY, OTHER):                     # live engines of other sessions, old and new
        (data / name).write_text("pid=1 t=0\n", encoding="utf-8")
    monkeypatch.setenv("KG_DATA", str(data))
    monkeypatch.setenv(S.READY_MARKER_ENV, str(data / ".engine-ready-4242-00000000beef"))
    _serve_once([], data)
    assert sorted(p.name for p in data.iterdir()) == [LEGACY, OTHER], (
        "0.11.1 overwrote the shared marker and then deleted it on a clean shutdown")


# ---- the supervisor's helpers ----------------------------------------------------------------------------

def _node(body: str) -> dict:
    """Import the shipped launcher in a node ESM harness and return the JSON line it prints."""
    script = f"import * as L from {json.dumps(_LAUNCH_MJS.as_uri())};\n" + body
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_each_spawn_gets_a_new_marker_in_kg_data(tmp_path):
    out = _node(f"""
const env = {{ KG_DATA: {json.dumps(str(tmp_path))} }};
process.stdout.write(JSON.stringify([L.newReadyMarker(env), L.newReadyMarker(env)]));
""")
    a, b = (Path(p) for p in out)
    assert a != b
    assert a.parent == b.parent == tmp_path
    assert PER_SPAWN.match(a.name) and PER_SPAWN.match(b.name), out


@needs_node
def test_the_loop_hands_each_child_its_marker_and_reads_and_removes_only_that_one():
    out = _node(r"""
import { EventEmitter } from "node:events";
let t = 1e6, n = 0;
const children = [], spawned = [], read = [], removed = [];
let exitCode = null;
const sup = L.createSupervisor({
  spawnEngine: (m) => { spawned.push(m); const c = new EventEmitter(); children.push(c); return c; },
  exit: (code) => { exitCode = code; },
  heal: () => true, now: () => t, schedule: (fn) => fn(), log: () => {},
  newMarker: () => `m${n++}`,
  servedInit: (m) => { read.push(m); return false; },
  clearMarker: (m) => { removed.push(m); },
});
sup.start();
t += 100; children[0].emit("exit", 1, null);   // a startup failure: the one heal, then a relaunch
t += 100; children[1].emit("exit", 0, null);   // the relaunched engine shuts down cleanly
process.stdout.write(JSON.stringify({ spawned, read, removed, exitCode }));
""")
    assert out == {"spawned": ["m0", "m1"], "read": ["m0", "m1"], "removed": ["m0", "m1"], "exitCode": 0}


@needs_node
def test_the_sweep_removes_only_stale_readiness_markers(tmp_path):
    fresh = tmp_path / ".engine-ready-123-aaaaaaaaaaaa"
    stale = tmp_path / ".engine-ready-456-bbbbbbbbbbbb"
    legacy = tmp_path / LEGACY
    unrelated = [tmp_path / n for n in ("server.log", ".engine-ready-notes", ".engine-ready-789-CCCCCCCCCCCC")]
    for p in (fresh, stale, legacy, *unrelated):
        p.write_text("x", encoding="utf-8")
    old = time.time() - TWO_HOURS
    for p in (stale, legacy, *unrelated):
        os.utime(p, (old, old))
    out = _node(f"process.stdout.write(JSON.stringify(L.sweepStaleReadyMarkers({json.dumps(str(tmp_path))})));")
    assert out == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([fresh.name, *(p.name for p in unrelated)])


# ---- the shipped launcher, end to end ----------------------------------------------------------------------

_FAKE_BOOTSTRAP = r'''
"""Stand-in for scripts/bootstrap.py: --check reads the stamp, --background records a build that never lands."""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
venv = Path(args[args.index("--venv") + 1])
with open(os.environ["FAKE_BOOT_CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if "--check" in args:
    sys.exit(0 if (venv / "install.stamp").exists() else 1)
sys.exit(0 if "--background" in args else 99)
'''

_FAKE_ENGINE = r'''
import os, sys
from pathlib import Path

marker = os.environ.get("KG_READY_MARKER", "")
with open(os.environ["FAKE_ENGINE_LAUNCHES"], "a", encoding="utf-8") as f:
    f.write(marker + "\n")
for other in filter(None, os.environ.get("FAKE_OTHER_MARKERS", "").split(os.pathsep)):
    Path(other).write_text("pid=1 t=0\n", encoding="utf-8")       # another session's engine coming up now
if marker and os.environ.get("FAKE_ENGINE_SERVES") == "1":
    Path(marker).write_text(f"pid={os.getpid()} t=0\n", encoding="utf-8")   # what readiness_lifespan does
sys.exit(int(os.environ.get("FAKE_ENGINE_EXIT", "0")))
'''


class Launch:
    """One run of the shipped launcher against a fake plugin root with a ready venv."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "root"
        (self.root / "scripts" / "kg_engine").mkdir(parents=True)
        (self.root / "scripts" / "bootstrap.py").write_text(_FAKE_BOOTSTRAP, encoding="utf-8")
        (self.root / "scripts" / "kg_engine" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "scripts" / "kg_engine" / "server.py").write_text(_FAKE_ENGINE, encoding="utf-8")
        self.data = tmp_path / "data"
        self.venv = self.data / ".venv"
        self.venv.mkdir(parents=True)
        (self.venv / "engine-python.txt").write_text(sys.executable, encoding="utf-8")
        (self.venv / "install.stamp").write_text("fake", encoding="utf-8")
        self.calls_file = tmp_path / "boot-calls.jsonl"
        self.launches_file = tmp_path / "engine-launches.txt"

    def run(self, *, engine_exit: int, serves: bool, others: tuple[Path, ...] = (), mcp_timeout_ms: int = 30_000):
        keep = {k: v for k, v in os.environ.items() if not k.startswith(("KG_", "CLAUDE_", "MCP_TIMEOUT", "PYTHONPATH"))}
        env = dict(keep, CLAUDE_PLUGIN_ROOT=str(self.root), CLAUDE_PLUGIN_DATA=str(self.data), KG_DATA=str(self.data),
                   KG_ENGINE_VENV=str(self.venv), PYTHONPATH=str(self.root / "scripts"), MCP_TIMEOUT=str(mcp_timeout_ms),
                   FAKE_BOOT_CALLS=str(self.calls_file), FAKE_ENGINE_LAUNCHES=str(self.launches_file),
                   FAKE_ENGINE_EXIT=str(engine_exit), FAKE_ENGINE_SERVES="1" if serves else "0",
                   FAKE_OTHER_MARKERS=os.pathsep.join(str(p) for p in others))
        self.result = subprocess.run([NODE, str(_LAUNCH_MJS)], env=env, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, timeout=60)
        return self.result

    @property
    def log(self) -> str:
        return (self.data / "server.log").read_text(encoding="utf-8")

    @property
    def markers_handed(self) -> list[str]:
        return self.launches_file.read_text(encoding="utf-8").splitlines()

    @property
    def background_calls(self) -> list[list[str]]:
        if not self.calls_file.exists():
            return []
        calls = [json.loads(line) for line in self.calls_file.read_text(encoding="utf-8").splitlines()]
        return [c for c in calls if "--background" in c]

    def markers_left(self) -> list[str]:
        return sorted(p.name for p in self.data.iterdir() if p.name.startswith(LEGACY))


@needs_node
def test_a_fast_crash_after_serving_is_read_as_post_init(tmp_path):
    run = Launch(tmp_path)
    r = run.run(engine_exit=70, serves=True)
    (handed,) = run.markers_handed
    assert Path(handed).parent == run.data and PER_SPAWN.match(Path(handed).name), handed
    assert "servedInit=true -> post-init-exit" in run.log, run.log
    assert r.returncode == 70, r.stderr
    assert run.background_calls == [], "a crash after serving heals nothing"
    assert run.markers_left() == [], "the supervisor removes the marker a crash leaves behind"


@needs_node
def test_another_session_coming_up_does_not_vouch_for_this_engine(tmp_path):
    """The engine fails at startup, writing no marker, while other sessions' engines write theirs. 0.11.1 took
    the shared marker for this child's and exited as after a post-init crash, with no self-heal."""
    run = Launch(tmp_path)
    others = (run.data / LEGACY, run.data / OTHER)
    r = run.run(engine_exit=1, serves=False, others=others, mcp_timeout_ms=11_500)  # a 1.5 s heal window
    assert "servedInit=false -> early-failure-heal" in run.log, run.log
    assert len(run.background_calls) == 1, "the startup failure gets its venv rebuild"
    assert r.returncode == 1 and "still being set up in the background" in r.stderr
    assert run.markers_left() == sorted(p.name for p in others), "and the other sessions keep their markers"


@needs_node
def test_a_supervisor_leaves_other_sessions_markers_alone(tmp_path):
    run = Launch(tmp_path)
    for name in (LEGACY, OTHER):                     # live engines of other sessions, old and new
        (run.data / name).write_text("pid=1 t=0\n", encoding="utf-8")
    r = run.run(engine_exit=0, serves=True)
    assert r.returncode == 0, r.stderr
    assert run.markers_left() == [LEGACY, OTHER], "0.11.1 deleted the shared marker before every spawn"


@needs_node
def test_a_supervisor_sweeps_stale_markers_as_it_starts(tmp_path):
    run = Launch(tmp_path)
    old = time.time() - TWO_HOURS
    for name in (LEGACY, OTHER):                     # left by engines killed together with their supervisors
        (run.data / name).write_text("pid=1 t=0\n", encoding="utf-8")
        os.utime(run.data / name, (old, old))
    r = run.run(engine_exit=0, serves=False)
    assert r.returncode == 0, r.stderr
    assert run.markers_left() == []
    assert "removed 2 stale readiness markers" in run.log, run.log


# ---- the docs ----------------------------------------------------------------------------------------------

def test_the_architecture_names_the_marker_variable():
    arch = " ".join((REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").split())
    assert "`KG_READY_MARKER`" in arch
    assert "`.engine-ready`" not in arch, "the single shared marker is gone"
