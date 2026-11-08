"""Regression pins for the 0.4.2 session-start defect: Burgess wrote into EVERY folder a session opened.

Claude Code starts a plugin's MCP server and fires its SessionStart hook in whatever folder a session
opens, whether or not Burgess is used there. Two automatic paths each left files behind, and the first
one defeated the guard of the second:

1. the MCP server built its engine at startup over an EAGER Canon, which created an empty ``canon/``
   and appended the runtime patterns to ``.git/info/exclude``;
2. the SessionStart reconcile (``bootstrap.maybe_reconcile``) ran wherever ``canon/`` was a directory,
   which after (1) meant everywhere, and ``Reconciler.scan()`` persisted its state file and the
   spend-ledger checkpoint unconditionally. Both were rewritten every session.

The pins below follow the acceptance criteria: building the engine writes nothing; the per-session
reconcile writes nothing over an empty ``canon/``; a real canon still gets its state and checkpoint
every session; the first ``kg_write`` lays the vault out (canon dir + git excludes). Around them sit the
safety edges the fix leans on: excludes land before the first runtime file, a fresh clone still gets
them, deleting every note still prunes the baseline (§1.8), and leftovers from older versions are left
exactly as they are, never rewritten or deleted.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kg_engine.canon import (
    CANON_SUBDIR,
    GROUND_AUDIT,
    HUB_ATTACKS,
    LOCK_NAME,
    LOCK_QUEUE_DIRNAME,
    RECONCILE_STATE_NAME,
    TRANSIENT_REAP_TTL,
    Canon,
)
from kg_engine.model import Node, node_to_markdown
from kg_engine.reconciler import Reconciler
from kg_engine.server import _register, build_engine_from_env

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
CKPT_NAME = f"{GROUND_AUDIT}.ckpt"
# Every pattern Canon._ensure_git_excludes promises a git-backed vault.
EXCLUDE_PATTERNS = [LOCK_NAME, f"{LOCK_QUEUE_DIRNAME}/", ".tmp-*", RECONCILE_STATE_NAME, f"{GROUND_AUDIT}*",
                    HUB_ATTACKS]


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("kg_bootstrap_session_start", REPO / "scripts" / "bootstrap.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bootstrap = _load_bootstrap()


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Drop inherited engine/plugin config: these tests are about what lands in the project dir, so
    nothing may resolve a source, pack or data dir from the developer's own session."""
    for key in list(os.environ):
        if key.startswith(("KG_", "CLAUDE_PLUGIN_OPTION_")) or key in ("CLAUDE_PROJECT_DIR",
                                                                      "CLAUDE_PLUGIN_DATA"):
            monkeypatch.delenv(key, raising=False)


class FakeMCP:
    """Captures the registered tool wrappers, so a test can run the rest of main() before mcp.run()."""

    def __init__(self):
        self.tools: dict = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _folder(tmp_path: Path, kind: str) -> Path:
    """A folder a session might open. `bare` has only `.git/info/` (so an exclude WOULD be created
    there, the case the criterion names); `git` is a real `git init`, which ships a template exclude
    file that must stay byte-identical."""
    p = tmp_path / "project"
    if kind == "bare":
        (p / ".git" / "info").mkdir(parents=True)
    else:
        p.mkdir()
        subprocess.run(["git", "-C", str(p), "init", "-q"], check=True)
    return p


def _snapshot(root: Path) -> dict:
    """Every entry under `root` mapped to (bytes, mtime_ns), dirs to None, so a created, deleted,
    rewritten or merely re-touched entry shows up as a difference. Git's own internals are skipped
    except `.git/info/exclude`, the one file under `.git/` the engine writes."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if rel.parts[0] == ".git" and rel.as_posix() != ".git/info/exclude":
            continue
        out[rel.as_posix()] = None if p.is_dir() else (p.read_bytes(), p.stat().st_mtime_ns)
    return out


def _exclude_patterns(project: Path) -> list[str]:
    exclude = project / ".git" / "info" / "exclude"
    return exclude.read_text(encoding="utf-8").split() if exclude.exists() else []


def _hand_written_note(project: Path, nid: str = "alpha") -> None:
    """A note placed on disk the way a clone, a merge or a hand edit would: no engine write, so no
    layout side effects."""
    notes = project / CANON_SUBDIR
    notes.mkdir(parents=True, exist_ok=True)
    (notes / f"{nid}.md").write_text(node_to_markdown(Node(id=nid, label=nid)), encoding="utf-8")


# --------------------------------------------------------------------------- criterion 1: startup


@pytest.mark.parametrize("kind", ["bare", "git"])
def test_building_the_engine_like_the_server_writes_nothing_into_the_project(tmp_path, kind):
    """main() → build_engine_from_env → _register, with the data dir OUTSIDE the project as
    KG_DATA puts it: no canon/, no runtime file, and `.git/info/exclude` neither created nor
    modified."""
    project = _folder(tmp_path, kind)
    before = _snapshot(project)

    engine = build_engine_from_env(project=str(project), data=str(tmp_path / "data"))
    _register(FakeMCP(), engine)

    assert _snapshot(project) == before
    assert not (project / CANON_SUBDIR).exists()


def test_read_tools_on_an_unused_folder_lay_nothing_out(tmp_path):
    """A session that only READS (or that a skill pings) must leave the folder as it found it: a
    missing canon dir globs as empty, and the lazy projection's lease is taken and released. The
    snapshot is taken BEFORE the engine exists, so an eager constructor fails this too."""
    project = _folder(tmp_path, "git")
    before = _snapshot(project)
    engine = build_engine_from_env(project=str(project), data=str(tmp_path / "data"))
    tools = FakeMCP()
    _register(tools, engine)

    for name, kwargs in (("kg_ping", {}), ("kg_status", {}), ("kg_context", {"query": "trust"}),
                         ("kg_agenda", {})):
        result = tools.tools[name](**kwargs)
        assert not (isinstance(result, dict) and "error_kind" in result), (name, result)

    assert _snapshot(project) == before


# --------------------------------------------------------------------------- criterion 4: first write


def test_first_kg_write_lays_out_the_canon_and_the_git_excludes(vault, source_path, tmp_path_factory):
    project = vault  # a git repo with an initial commit, nothing else
    engine = build_engine_from_env(project=str(project), data=str(tmp_path_factory.mktemp("data")),
                                   source=str(source_path), pack=str(PACK))
    assert not (project / CANON_SUBDIR).exists()
    assert not any(p in _exclude_patterns(project) for p in EXCLUDE_PATTERNS)

    engine.kg_write({"edges": [{"source": "degree", "target": "importance", "relation": "approximates",
                                "span": "Degree approximates importance", "authored_by": "agent"}]})

    assert (project / CANON_SUBDIR / "degree.md").exists()
    assert set(EXCLUDE_PATTERNS) <= set(_exclude_patterns(project))


def test_the_excludes_land_before_the_lease_file_exists(vault, source_path, tmp_path_factory, monkeypatch):
    """The point of laying out in acquire_lock: by the time the lease file (the first runtime file a
    write creates) appears, git already ignores it — a `git add -A` racing the write can't stage it."""
    engine = build_engine_from_env(project=str(vault), data=str(tmp_path_factory.mktemp("data")),
                                   source=str(source_path), pack=str(PACK))
    lock = engine.canon.lock
    seen = []
    real_acquire = lock.acquire

    def acquire(*args, **kwargs):
        seen.append(LOCK_NAME in _exclude_patterns(vault))
        return real_acquire(*args, **kwargs)

    monkeypatch.setattr(lock, "acquire", acquire)
    engine.kg_write({"edges": [{"source": "canon", "target": "trust", "relation": "grounds",
                                "span": "The canon grounds trust", "authored_by": "agent"}]})
    assert seen and all(seen)


def test_a_write_through_a_lazy_canon_writes_the_git_excludes(tmp_path):
    """The gap test_f37_write_through_read_only_canon_self_heals_dir left open: before 0.4.2 a lazy
    Canon's write recreated canon/ via _atomic_write_bytes but never wrote the excludes."""
    (tmp_path / ".git" / "info").mkdir(parents=True)
    c = Canon(tmp_path, ensure_layout=False)

    c.write_one(Node(id="x", label="x"))

    assert (tmp_path / CANON_SUBDIR / "x.md").exists()
    assert set(EXCLUDE_PATTERNS) <= set(_exclude_patterns(tmp_path))


# --------------------------------------------------------------------------- the sweep's own defense


@pytest.mark.parametrize("canon_dir", [True, False])
def test_a_sweep_with_nothing_to_reconcile_writes_nothing(tmp_path, canon_dir):
    """Reconciler.scan over an empty (or missing) canon, with no state and no audit: no state file,
    no checkpoint, no canon dir created, no exclude written."""
    project = _folder(tmp_path, "bare")
    if canon_dir:
        (project / CANON_SUBDIR).mkdir()
    before = _snapshot(project)

    report = Reconciler(Canon(project, ensure_layout=False)).scan(full_sweep=True)

    assert report.scanned == 0
    assert _snapshot(project) == before


def _plant_old_leftovers(project: Path) -> None:
    """Exactly what 0.2.x–0.4.1 left in a folder it was never used in, plus an aged `.tmp-*` file of
    the USER's that the sweep's housekeeping (which reaps `.tmp-*` older than TRANSIENT_REAP_TTL at
    the vault root) must not take for its own."""
    (project / CANON_SUBDIR).mkdir()
    # One line, unlike _save_state's indent=0 output, so a rewrite shows up in the bytes as well.
    (project / RECONCILE_STATE_NAME).write_text('{"files": {}, "epistemic": {}, "consumed": {}}',
                                                encoding="utf-8")
    (project / CKPT_NAME).write_text(
        '{"_ckpt": 1, "consumed": {}, "epistemic": {}, "at": "2026-07-01T00:00:00Z"}\n', encoding="utf-8")
    users_tmp = project / ".tmp-user-download"
    users_tmp.write_text("not Burgess's", encoding="utf-8")
    aged = os.path.getmtime(users_tmp) - TRANSIENT_REAP_TTL * 2
    os.utime(users_tmp, (aged, aged))


def test_a_sweep_leaves_old_leftovers_exactly_as_they_are(tmp_path):
    project = _folder(tmp_path, "git")
    _plant_old_leftovers(project)
    before = _snapshot(project)

    Reconciler(Canon(project, ensure_layout=False)).scan(full_sweep=True)

    assert _snapshot(project) == before  # not rewritten, not deleted, the user's .tmp-* not reaped


def test_a_corrupt_state_in_an_empty_vault_is_neither_crashed_on_nor_rewritten(tmp_path):
    """F19's companion: the fail-open read still holds (no crash), but with nothing to reconcile the
    sweep no longer rewrites the file. It heals on the first sweep that has work to do
    (test_valid_json_non_dict_state_does_not_crash_scan seeds a note for exactly that)."""
    project = _folder(tmp_path, "bare")
    (project / RECONCILE_STATE_NAME).write_text("[1, 2, 3]", encoding="utf-8")
    before = _snapshot(project)

    Reconciler(Canon(project, ensure_layout=False)).scan(full_sweep=True)  # must not raise

    assert _snapshot(project) == before


def test_deleting_every_note_still_prunes_and_persists_the_baseline(tmp_path):
    """The early return must never strand a stale baseline (reconciler-1): a deleted-then-recreated
    edge would inherit it and a forged verdict would slip past `last == current`. A sweep that
    STARTS with a baseline always runs, prunes it and persists the result, notes or not."""
    project = _folder(tmp_path, "git")
    writer = Canon(project)
    writer.write_one(Node(id="alpha", label="alpha"))
    writer.write_one(Node(id="beta", label="beta"))
    recon = Reconciler(Canon(project, ensure_layout=False))
    recon.scan(full_sweep=True)
    assert set(recon._load_state()["epistemic"]) == {"node:alpha", "node:beta"}

    for p in (project / CANON_SUBDIR).glob("*.md"):
        p.unlink()
    recon.scan(full_sweep=True)

    pruned = json.loads((project / RECONCILE_STATE_NAME).read_text(encoding="utf-8"))
    assert pruned["epistemic"] == {} and pruned["files"] == {}


# --------------------------------------------------------------------------- criterion 3: a real canon


def test_a_sweep_over_a_real_canon_still_writes_state_and_checkpoint(tmp_path):
    project = _folder(tmp_path, "git")
    Canon(project).write_one(Node(id="alpha", label="alpha"))

    Reconciler(Canon(project, ensure_layout=False)).scan(full_sweep=True)

    assert (project / RECONCILE_STATE_NAME).exists()
    ckpt = json.loads((project / CKPT_NAME).read_text(encoding="utf-8"))
    assert "node:alpha" in ckpt["epistemic"]


def test_a_fresh_clone_gets_its_excludes_before_the_sweep_writes_state(tmp_path, monkeypatch):
    """`.git/info/exclude` is per-clone and never cloned, and the server no longer writes it at
    startup. A clone that arrives with notes therefore gets its excludes from the first session's
    sweep, before that sweep writes the state cache next to the notes."""
    project = _folder(tmp_path, "git")
    _hand_written_note(project)
    assert RECONCILE_STATE_NAME not in _exclude_patterns(project)
    seen = []
    real_save = Reconciler._save_state

    def save(self, state):
        seen.append(RECONCILE_STATE_NAME in _exclude_patterns(project))
        return real_save(self, state)

    monkeypatch.setattr(Reconciler, "_save_state", save)
    Reconciler(Canon(project, ensure_layout=False)).scan(full_sweep=True)

    assert seen == [True]
    assert set(EXCLUDE_PATTERNS) <= set(_exclude_patterns(project))
    assert (project / CKPT_NAME).exists()


# --------------------------------------------------------------------------- criterion 2: the hook


@pytest.fixture
def engine_python(monkeypatch):
    """Point maybe_reconcile at THIS interpreter (it has the engine's deps), so a sweep the guard
    lets through really runs and really writes, and record the exit code of each sweep it launches,
    so a test can tell "the guard skipped" from "the sweep ran and wrote nothing" — and a sweep that
    CRASHED (and so wrote nothing) can never pass for one that ran clean."""
    launched = []
    real_run = bootstrap.subprocess.run

    def run(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if len(argv) > 2 and argv[1] == "-c" and "Reconciler" in argv[2]:
            launched.append(result.returncode)
        return result

    monkeypatch.setattr(bootstrap, "venv_python", lambda _venv: Path(sys.executable))
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    return launched


def test_session_reconcile_skips_a_folder_with_an_empty_canon(tmp_path, monkeypatch, engine_python):
    project = _folder(tmp_path, "bare")
    (project / CANON_SUBDIR).mkdir()
    before = _snapshot(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    bootstrap.maybe_reconcile(tmp_path / "venv")

    assert engine_python == []
    assert _snapshot(project) == before  # no state file, no checkpoint, no exclude


def test_session_reconcile_leaves_old_leftovers_untouched(tmp_path, monkeypatch, engine_python):
    project = _folder(tmp_path, "git")
    _plant_old_leftovers(project)
    before = _snapshot(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    bootstrap.maybe_reconcile(tmp_path / "venv")

    assert engine_python == []
    assert _snapshot(project) == before


def test_session_reconcile_still_sweeps_a_real_canon(tmp_path, monkeypatch, engine_python):
    """§1.8: the once-per-session full sweep is what defeats mtime-spoofed forged verdicts, so a
    project with a canon must keep getting it, state and checkpoint included."""
    project = _folder(tmp_path, "git")
    _hand_written_note(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    bootstrap.maybe_reconcile(tmp_path / "venv")

    assert engine_python == [0]
    assert (project / RECONCILE_STATE_NAME).exists()
    ckpt = json.loads((project / CKPT_NAME).read_text(encoding="utf-8"))
    assert "node:alpha" in ckpt["epistemic"]
    assert set(EXCLUDE_PATTERNS) <= set(_exclude_patterns(project))


def test_session_reconcile_runs_on_verdict_history_without_notes(tmp_path, monkeypatch, engine_python):
    """Every note deleted, the audit ledger still there: still a project (its baseline has to be
    pruned), so the sweep runs."""
    project = _folder(tmp_path, "git")
    record = {"key": "node:alpha", "from": "unverified", "to": "grounded", "by": "agent",
              "at": "2026-07-01T00:00:00Z"}
    (project / GROUND_AUDIT).write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    bootstrap.maybe_reconcile(tmp_path / "venv")

    assert engine_python == [0]
    assert (project / RECONCILE_STATE_NAME).exists()


def test_the_session_sweep_itself_never_lays_out_an_unused_folder(tmp_path, monkeypatch, engine_python):
    """Defense in depth: even when the guard says yes (here forced), the swept Canon is lazy and an
    empty sweep writes nothing, so a guard/sweep disagreement can't bring the defect back."""
    project = _folder(tmp_path, "bare")
    before = _snapshot(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(bootstrap, "_holds_project", lambda _p: True)

    bootstrap.maybe_reconcile(tmp_path / "venv")

    assert engine_python == [0]  # the sweep really ran, and ran clean ...
    assert _snapshot(project) == before  # ... and created nothing: no canon/, no state, no exclude


def test_the_guard_mirrors_the_engine_names():
    """bootstrap cannot import canon (the bare system Python has no yaml), so it mirrors the names."""
    assert bootstrap._CANON_SUBDIR == CANON_SUBDIR
    assert bootstrap._GROUND_AUDIT == GROUND_AUDIT


@pytest.mark.parametrize("name", ["alpha.md", ".tmp-1a2b.md", ".alpha.md.unreadable-1.bak", "notes.txt",
                                  "README", "Upper.MD"])
def test_the_guard_counts_notes_exactly_like_canon(tmp_path, name):
    """The guard's note test must agree with Canon.note_paths() on every name, on every platform
    (both glob `*.md`, so they share the filesystem's case rule)."""
    (tmp_path / CANON_SUBDIR).mkdir()
    (tmp_path / CANON_SUBDIR / name).write_text("x", encoding="utf-8")
    expected = bool(Canon(tmp_path, ensure_layout=False).note_paths())
    assert bootstrap._holds_project(tmp_path) is expected


def test_the_guard_reads_an_empty_ledger_as_no_project(tmp_path):
    (tmp_path / GROUND_AUDIT).write_bytes(b"")
    assert bootstrap._holds_project(tmp_path) is False
    (tmp_path / GROUND_AUDIT).write_text("{}\n", encoding="utf-8")
    assert bootstrap._holds_project(tmp_path) is True
