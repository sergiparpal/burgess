"""0.11.9 — the precontext hook stays silent for measurement subagents and for the project's `.kg/`.

Second field /kg-experiment, on 0.11.8 (Windows, 2026-11-10). The kg-evaluator worked without a shell for the
first time, and reported something itself: the PreToolUse hook on Grep/Glob/Read attached grounded edges to
four of its Reads. One was the prompt file, read before the control answers, which must see no context. The
other three were rag passage files (08, 11 and 12), whose arm must see the source's prose and nothing else.
The hook's query is a file's stem, so "prompts-<run>" and "08" matched edges as readily as a document title
does. 0.11.8 had widened the path by moving the rag arm's passages into files the evaluator Reads. The
kg-annotator reads the source documents it labels, and the attached edges carry the grounding verdicts that
it must not see.

Claude Code puts `agent_id` and `agent_type` in a hook's input when a subagent made the call (2.1.316's
schema). The hook now stays silent for the kg-evaluator and the kg-annotator, and for any Read, Grep or Glob
of the project's `.kg/`, where Burgess keeps its working files. Every other call is served as before.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
SRC = "## H\nEl centro une a, b y c.\n"
SPAN = "El centro une a, b y c"


def _load_hook():
    spec = importlib.util.spec_from_file_location("kg_precontext_blind", REPO / "hooks" / "precontext.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def world(vault: Path, tmp_path: Path, monkeypatch):
    src = tmp_path / "src.md"
    src.write_text(SRC, encoding="utf-8")
    data = tmp_path / "data"
    e = KGEngine(vault, data, source_path=src, pack_path=PACK)
    edges = [{"source": "centro", "target": t, "relation": "grounds", "span": SPAN, "source_file": "src.md"}
             for t in "abc"]
    nodes = [{"id": n, "label": n, "node_type": "claim", "body": n} for n in ("centro", *"abc")]
    out = e.kg_write({"nodes": nodes, "edges": edges, "complete": True})
    assert out["dispositions"]["REJECTED"] == 0, out
    for x in edges:
        assert e.kg_ground(edge_id(x["source"], "grounds", x["target"]), "grounded", note="t")["ok"]
    assert e.get_node("centro")  # a server read projects the index
    for key in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_OPTION_SOURCE_PATH",
                "CLAUDE_PLUGIN_OPTION_METRICS_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KG_PROJECT_DIR", str(vault))
    monkeypatch.setenv("KG_DATA", str(data))
    monkeypatch.setenv("KG_SOURCE_PATH", str(src))
    monkeypatch.setenv("KG_PACK_PATH", str(PACK))
    return vault, _load_hook()


def _inject(hook, monkeypatch, capsys, payload: dict) -> str:
    """What the hook attaches to the tool call `payload` describes ("" when it stays silent)."""
    raw = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    assert hook.main() == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


def _grep(**extra) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Grep", "tool_input": {"pattern": "centro"}, **extra}


def _read(path, **extra) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": str(path)}, **extra}


# --------------------------------------------------------------------------- who is calling

@pytest.mark.parametrize("agent_type", ["burgess:kg-evaluator", "burgess:kg-annotator", "kg-annotator"])
def test_a_measurement_subagent_gets_no_context(world, monkeypatch, capsys, agent_type):
    _, hook = world
    assert _inject(hook, monkeypatch, capsys, _grep(agent_id="a765e8f574013a418", agent_type=agent_type)) == ""


@pytest.mark.parametrize("extra", [
    {},                                                                    # the main session
    {"agent_id": "a1", "agent_type": "general-purpose"},                   # someone else's subagent
    {"agent_id": "a2", "agent_type": "burgess:kg-grounder"},               # a Burgess subagent that is not measuring
    {"agent_type": "burgess:kg-evaluator-notes"},                          # a name that only starts like one
], ids=["main", "general-purpose", "kg-grounder", "lookalike"])
def test_every_other_caller_is_served_as_before(world, monkeypatch, capsys, extra):
    _, hook = world
    assert "centro --grounds--> a" in _inject(hook, monkeypatch, capsys, _grep(**extra))


# --------------------------------------------------------------------------- what is read

def test_a_read_under_dot_kg_gets_no_context(world, monkeypatch, capsys):
    vault, hook = world
    # the stem would match: the same file name outside .kg/ is served
    assert "centro --grounds--> a" in _inject(hook, monkeypatch, capsys, _read(vault / "notes" / "centro.md"))
    for inside in (vault / ".kg" / "experiment" / "rag-20261110T224340Z" / "centro.md",
                   vault / ".kg" / "centro.md", vault / ".kg"):
        assert _inject(hook, monkeypatch, capsys, _read(inside)) == "", inside


def test_a_relative_path_is_read_against_the_sessions_folder(world, monkeypatch, capsys):
    vault, hook = world
    payload = _read(Path(".kg") / "eval" / "centro.csv", cwd=str(vault))
    assert _inject(hook, monkeypatch, capsys, payload) == ""
    payload = _read(Path("notes") / "centro.md", cwd=str(vault))
    assert "centro --grounds--> a" in _inject(hook, monkeypatch, capsys, payload)


def test_a_grep_or_glob_of_dot_kg_gets_no_context(world, monkeypatch, capsys):
    vault, hook = world
    assert _inject(hook, monkeypatch, capsys, _grep(tool_input={"pattern": "centro", "path": str(vault / ".kg")})) == ""
    assert _inject(hook, monkeypatch, capsys, {"tool_name": "Glob", "cwd": str(vault),
                                               "tool_input": {"pattern": ".kg/**/centro*"}}) == ""
    # elsewhere both are served
    assert "centro" in _inject(hook, monkeypatch, capsys, _grep(tool_input={"pattern": "centro", "path": str(vault)}))
    assert "centro" in _inject(hook, monkeypatch, capsys, {"tool_name": "Glob", "cwd": str(vault),
                                                           "tool_input": {"pattern": "centro*"}})


def test_only_the_projects_own_dot_kg_is_silent(world, monkeypatch, capsys, tmp_path):
    vault, hook = world
    for path in (tmp_path / "elsewhere" / ".kg" / "centro.md",   # another folder's .kg
                 vault / "notes.kg" / "centro.md",                # a name that only ends like it
                 vault / "centro.kg.md"):
        assert "centro --grounds--> a" in _inject(hook, monkeypatch, capsys, _read(path)), path


def test_a_payload_that_is_not_an_object_is_ignored(world, monkeypatch, capsys):
    _, hook = world
    raw = json.dumps(["Grep", {"pattern": "centro"}]).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    assert hook.main() == 0 and capsys.readouterr().out == ""


def test_the_rule_names_the_measurement_agents_the_plugin_ships():
    hook = _load_hook()
    for name in hook._BLIND_AGENTS:
        assert (REPO / "agents" / f"{name.removeprefix('kg-')}.md").read_text(encoding="utf-8").startswith(
            f"---\nname: {name}\n")
