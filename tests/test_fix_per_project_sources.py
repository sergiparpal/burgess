"""0.23.0: each project has its own notes and its own engine data.

After phase 3 of the field test of 2026-11-22 the user asked why `source_path` is global when each project may
follow its own policy: in `prueba-burgess-n1` the 9 notes of `prueba-burgess` were listed as that project's own.
Claude Code keeps a plugin's options per user and ignores a project's settings for them (a cloned repository must
not choose what the plugin reads), and `${CLAUDE_PLUGIN_DATA}` is keyed by plugin, not by project, so every
project shared one derived layer too.

Now a project names its own notes in its policy (`notes_path`, inside the project only), each project keeps its
derived layer under `<KG_DATA>/projects/<key>/`, the first start copies over what the old shared folder held for
the project, and command text reaches the project's graph and source through `python -m kg_engine.paths`.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from kg_engine import envconfig
from kg_engine import evidence as ev
from kg_engine import paths
from kg_engine.server import KGEngine, _register, adopt_shared_derived, build_engine_from_env

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def rig(tmp_path):
    shared = tmp_path / "global-notes"
    shared.mkdir()
    (shared / "g.md").write_text("## Global\n\nThe global notes say alpha drives beta.\n", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    (project / "notas").mkdir()
    (project / "notas" / "n.md").write_text("## Own\n\nThe project's notes say gamma drives delta.\n",
                                            encoding="utf-8")
    eng = KGEngine(project, tmp_path / "data", source_path=shared, pack_path=PACK)
    return eng, tmp_path


# --------------------------------------------------------------------------- the notes path

def test_parse_notes_path_keeps_the_project_s_own_paths(tmp_path):
    (tmp_path / "notas").mkdir()
    (tmp_path / "canon").mkdir()
    assert ev.parse_notes_path("notas", tmp_path) == "notas"
    assert ev.parse_notes_path(str(tmp_path / "notas"), tmp_path) == "notas"      # absolute inside: relative
    assert ev.parse_notes_path(str(tmp_path), tmp_path) == "."
    assert ev.parse_notes_path("notas/*.md", tmp_path) == "notas/*.md"            # a glob may match nothing yet
    assert ev.parse_notes_path("default", tmp_path) == "" and ev.parse_notes_path("", tmp_path) == ""
    assert ev.parse_notes_path("NONE", tmp_path) == "none"
    for bad, code in (("../elsewhere", "notes-path-outside-project"), ("/etc", "notes-path-outside-project"),
                      ("canon", "notes-path-reserved"), ("Evidence/x", "notes-path-reserved"),
                      ("missing", "notes-path-not-found")):
        with pytest.raises(ev.EvidenceError) as e:
            ev.parse_notes_path(bad, tmp_path)
        assert e.value.code == code, bad


def test_a_project_reads_its_own_notes(rig):
    eng, tmp = rig
    assert eng.source_set().basenames == ["g.md"] and eng._source_info()["notes_from"] == "global"
    out = eng.kg_source_policy(notes_path="notas")
    assert out["ok"] and out["changed"] == ["notes_path"]
    assert (out["policy"]["notes_path"], out["policy"]["notes_from"]) == ("notas", "project")
    assert out["policy"]["notes_folder"] == str(eng.project_dir / "notas")
    assert eng.source_set().basenames == ["n.md"] and eng.verify_set().basenames == ["n.md"]
    assert [n["name"] for n in eng.kg_source_list()["notes"]] == ["n.md"]
    info = eng._source_info()
    assert info["path"] == str(eng.project_dir / "notas") and info["files"] == ["n.md"]
    assert eng.kg_build_plan("", "")["files"][0]["file"] == "n.md"


def test_none_gives_no_notes_and_default_goes_back(rig):
    eng, tmp = rig
    assert eng.kg_source_policy(notes_path="none")["policy"]["notes_from"] == "none"
    assert eng.source_set().basenames == [] and eng.notes_path is None
    assert "registered" in eng.kg_build_plan("", "")["error"]
    assert eng.kg_source_policy(notes_path="default")["policy"]["notes_from"] == "global"
    assert eng.source_set().basenames == ["g.md"]


def test_a_path_outside_the_project_is_refused(rig):
    eng, tmp = rig
    out = eng.kg_source_policy(notes_path=str(tmp / "global-notes"))
    assert not out["ok"] and out["error"] == "notes-path-outside-project"
    assert eng.evidence_policy().notes_path == ""


def test_a_stored_path_outside_the_project_is_ignored_and_reported(rig):
    eng, tmp = rig
    folder = eng.project_dir / "evidence"
    folder.mkdir()
    (folder / "policy.json").write_text(json.dumps({"notes_path": "../global-notes"}), encoding="utf-8")
    pol, problems = ev.load_policy(folder)
    assert pol.notes_path == "" and problems[0]["problem"] == "notes-path-outside-project"
    assert eng.source_set().basenames == ["g.md"]                       # the plugin's source_path applies


def test_a_policy_without_a_notes_path_keeps_its_fingerprint():
    pol = ev.Policy(required_level=2)
    assert "notes_path" not in pol.fingerprint()
    pol.notes_path = "notas"
    assert '"notes_path": "notas"' in pol.fingerprint() and not pol.is_default()


def test_the_hook_reads_the_same_notes(rig):
    eng, tmp = rig
    eng.kg_source_policy(notes_path="notas")
    proj = KGEngine.read_only_projector(eng.project_dir, tmp / "data", source_path=tmp / "global-notes",
                                        pack_path=PACK)
    assert proj._source_set().basenames == ["n.md"]          # the projector's wired verification set


def test_the_source_info_names_what_a_build_reads(rig):
    eng, tmp = rig
    folder = tmp / "downloads"
    folder.mkdir()
    (folder / "paper.md").write_text("## Paper\n\nA reviewed paper about epsilon.\n", encoding="utf-8")
    name = eng.kg_source_add(path=str(folder / "paper.md"), level=1, role="primary", build=True)["name"]
    eng.kg_source_policy(build_from_notes=False)
    info = eng._source_info()
    assert info["files"] == [name] and info["builds_from"] == "registered sources"


# --------------------------------------------------------------------------- one data dir per project

def test_the_project_key_is_stable_and_apart(tmp_path):
    a, b = tmp_path / "Proyecto A", tmp_path / "proyecto-b"
    key = envconfig.project_key(a)
    assert key == envconfig.project_key(str(a) + "/") and key.startswith("proyecto-a-") and len(key) == 23
    assert key != envconfig.project_key(b)


def test_the_data_dir_is_the_project_s_own(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    monkeypatch.delenv("KG_DATA", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    assert envconfig.resolve_project_data_dir(project) == project / envconfig.DATA_DIRNAME
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin"))
    expected = tmp_path / "plugin" / "projects" / envconfig.project_key(project)
    assert envconfig.resolve_project_data_dir(project, plugin_data_fallback=True) == expected   # the hook
    monkeypatch.setenv("KG_DATA", str(tmp_path / "plugin"))
    assert envconfig.resolve_project_data_dir(project) == expected                               # the server
    assert envconfig.resolve_data_dir(project) == tmp_path / "plugin"                            # server.log


def test_the_server_builds_each_project_apart(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA", str(tmp_path / "plugin"))
    engines = []
    for name in ("one", "two"):
        project = tmp_path / name
        project.mkdir()
        subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
        (project / "notes.md").write_text(f"## {name}\n\n{name} notes.\n", encoding="utf-8")
        eng = build_engine_from_env(project=str(project), source=str(project / "notes.md"), pack=str(PACK))
        assert eng.data_dir == tmp_path / "plugin" / "projects" / envconfig.project_key(project)
        engines.append(eng)
    assert engines[0].projector.db_path != engines[1].projector.db_path
    explicit = build_engine_from_env(project=str(tmp_path / "one"), data=str(tmp_path / "mine"),
                                     source=str(tmp_path / "one" / "notes.md"), pack=str(PACK))
    assert explicit.data_dir == tmp_path / "mine"


def _shared_index(tmp_path, project, nodes):
    """A shared derived layer as 0.22 left it: the index of `project`, whose canon holds `nodes`."""
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    eng = KGEngine(project, tmp_path / "root", pack_path=PACK)
    eng.kg_write({"nodes": [{"id": n, "label": n.replace("-", " "), "node_type": "claim"} for n in nodes]})
    eng.kg_context()                                   # projects into <root>/derived
    return tmp_path / "root"


def test_the_first_start_copies_what_the_shared_folder_held_for_the_project(tmp_path):
    mine = tmp_path / "mine"
    mine.mkdir()
    root = _shared_index(tmp_path, mine, ["alpha-node", "beta-node", "gamma-node"])
    (root / "derived" / "generations.json").write_text(
        json.dumps({"generation": 2, "tracked": {"other-x": {}, "other-y": {}}}), encoding="utf-8")
    target = root / "projects" / envconfig.project_key(mine)
    assert adopt_shared_derived(root, target, mine) == ["index.sqlite", "graph.json"]
    con = sqlite3.connect(target / "derived" / "index.sqlite")
    assert set(json.loads(con.execute("SELECT value FROM meta WHERE key='file_hashes'").fetchone()[0])) == {
        "alpha-node", "beta-node", "gamma-node"}
    con.close()
    assert adopt_shared_derived(root, target, mine) == []                 # once, never over a file it has
    assert (root / "derived" / "index.sqlite").exists()                   # the shared folder stays


def test_another_project_takes_only_its_own_ledger(tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    root = _shared_index(tmp_path, first, ["alpha-node", "beta-node"])
    other = tmp_path / "other"
    (other / "canon").mkdir(parents=True)
    for n in ("compression-x", "compression-y", "plain"):
        (other / "canon" / f"{n}.md").write_text("---\nid: x\n---\n", encoding="utf-8")
    (root / "derived" / "generations.json").write_text(
        json.dumps({"generation": 3, "tracked": {"compression-x": {}, "compression-y": {}}}), encoding="utf-8")
    target = root / "projects" / envconfig.project_key(other)
    assert adopt_shared_derived(root, target, other) == ["generations.json"]
    assert not (target / "derived" / "index.sqlite").exists()             # another canon's index: rebuilt


# --------------------------------------------------------------------------- kg_engine.paths, for command text

def test_paths_prints_the_project_s_graph_and_source(rig, capsys):
    eng, tmp = rig
    plugin = str(tmp / "plugin")
    assert paths.graph_path(eng.project_dir, plugin) == (
        tmp / "plugin" / "projects" / envconfig.project_key(eng.project_dir) / "derived" / "graph.json")
    assert paths.content_source(eng.project_dir, plugin, str(tmp / "global-notes")) == str(tmp / "global-notes")
    eng.kg_source_policy(notes_path="notas")
    assert paths.content_source(eng.project_dir, plugin, str(tmp / "global-notes")) == str(eng.project_dir / "notas")
    folder = tmp / "downloads"
    folder.mkdir()
    (folder / "paper.md").write_text("## Paper\n\nA reviewed paper about epsilon.\n", encoding="utf-8")
    name = eng.kg_source_add(path=str(folder / "paper.md"), level=1, role="primary", build=True)["name"]
    got = Path(paths.content_source(eng.project_dir, plugin, str(tmp / "global-notes")))
    assert got.name == "content" and sorted(q.name for q in got.iterdir()) == sorted(["n.md", name])
    eng.kg_source_policy(notes_path="none", build_from_notes=False)
    got = Path(paths.content_source(eng.project_dir, plugin, ""))
    assert sorted(q.name for q in got.iterdir()) == [name]                 # refreshed: the notes left
    assert paths.main(["graph", str(eng.project_dir), plugin]) == 0
    assert capsys.readouterr().out.strip().endswith("graph.json")


def test_the_command_texts_use_the_project_s_paths():
    for name in ("kg-eval.md", "kg-experiment.md"):
        text = (REPO / "commands" / name).read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_DATA}/derived" not in text, name
        assert '"${user_config.source_path}"' not in text.replace(
            'kg_engine.paths source "${CLAUDE_PROJECT_DIR}" "${CLAUDE_PLUGIN_DATA}" "${user_config.source_path}"', ""), name
    sources = _flat((REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8"))
    assert "**Give this project its own notes** (0.23.0): `policy notes_path=" in sources
    assert "`notes_path=none` for no notes" in sources


def test_the_policy_tool_describes_the_notes_path():
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn
            return deco

    mcp = FakeMCP()
    _register(mcp, object())
    doc = _flat(mcp.tools["kg_source_policy"].__doc__)
    assert "`notes_path` names THIS project's notes" in doc and "a path outside the project is refused" in doc
