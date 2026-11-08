"""0.10.1: above its reproject gate, the precontext hook injects nothing while the derived index is stale.

Field report on 0.10.0 (the Windows corpus, a canon of 410 notes). The PreToolUse hook on Grep/Glob/Read reads
the derived index, which a write tool such as `kg_merge` leaves stale until the server's next read reprojects
it. The hook reprojects by itself only up to 400 notes: it is killed at 5 s, and a projection's betweenness pass
cannot finish inside that on a large canon (review-r4). Above the gate it served the stale index. A Grep made
right after six `kg_merge` calls was shown the edges of `reward-hacking` and `sensibilidad-al-formato`, two
nodes those merges had retired, and the session took it for a bug. Now the hook runs the projector's own
staleness check, which needs no projection, and stays silent while the index is stale. It serves the index
again once the server's next read has reprojected it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest

from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
SRC = "## H\nEl centro une a, b y c.\n\nEl otro une x e y.\n"
CENTRO, OTRO = "El centro une a, b y c", "El otro une x e y"


def _load_hook():
    spec = importlib.util.spec_from_file_location("kg_precontext_stale", REPO / "hooks" / "precontext.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _edge(source: str, target: str, span: str) -> dict:
    return {"source": source, "target": target, "relation": "grounds", "span": span, "source_file": "src.md"}


@pytest.fixture
def world(vault: Path, tmp_path: Path, monkeypatch):
    src = tmp_path / "src.md"
    src.write_text(SRC, encoding="utf-8")
    data = tmp_path / "data"
    e = KGEngine(vault, data, source_path=src, pack_path=PACK)
    edges = [_edge("centro", t, CENTRO) for t in "abc"] + [_edge("otro", t, OTRO) for t in "xy"]
    nodes = [{"id": n, "label": n, "node_type": "claim", "body": n} for n in ("centro", "otro", *"abcxy")]
    out = e.kg_write({"nodes": nodes, "edges": edges, "complete": True})
    assert out["dispositions"]["REJECTED"] == 0 and out["dispositions"]["QUARANTINED"] == 0, out
    for x in edges:
        assert e.kg_ground(edge_id(x["source"], "grounds", x["target"]), "grounded", note="t")["ok"]
    assert e.get_node("centro")                                   # a server read projects the index
    for key in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_OPTION_SOURCE_PATH",
                "CLAUDE_PLUGIN_OPTION_METRICS_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KG_PROJECT_DIR", str(vault))
    monkeypatch.setenv("KG_DATA", str(data))
    monkeypatch.setenv("KG_SOURCE_PATH", str(src))
    monkeypatch.setenv("KG_PACK_PATH", str(PACK))
    return e, _load_hook(), src


def _context(hook, monkeypatch, capsys, *, gate: int, pattern: str = "centro") -> str:
    """What the hook injects for a Grep of `pattern`, with its reproject gate set to `gate` notes."""
    monkeypatch.setattr(hook, "_MAX_HOOK_REPROJECT_NOTES", gate)
    payload = json.dumps({"tool_name": "Grep", "tool_input": {"pattern": pattern}}).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8"))
    assert hook.main() == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


ABOVE = 1          # the canon has more notes than this: the hook may not reproject
BELOW = 10_000


def test_above_the_gate_a_fresh_index_is_served(world, monkeypatch, capsys):
    _, hook, _ = world
    assert "centro --grounds--> a" in _context(hook, monkeypatch, capsys, gate=ABOVE)


def test_above_the_gate_a_stale_index_is_not_served(world, monkeypatch, capsys):
    e, hook, _ = world
    assert e.kg_merge("a", "b")["ok"]                             # the field case: a node retired by a merge
    assert _context(hook, monkeypatch, capsys, gate=ABOVE) == ""  # 0.10.0 showed `centro --grounds--> a` here
    assert e.get_node("centro")                                   # the server's next read reprojects
    ctx = _context(hook, monkeypatch, capsys, gate=ABOVE)
    assert "centro --grounds--> b" in ctx and "--> a " not in ctx


def test_below_the_gate_the_hook_still_reprojects_itself(world, monkeypatch, capsys):
    e, hook, _ = world
    assert e.kg_merge("a", "b")["ok"]
    ctx = _context(hook, monkeypatch, capsys, gate=BELOW)
    assert "centro --grounds--> b" in ctx and "--> a " not in ctx


def test_a_verdict_change_is_not_served_stale(world, monkeypatch, capsys):
    e, hook, _ = world
    assert e.kg_ground(edge_id("centro", "grounds", "a"), "rejected", note="t")["ok"]
    assert _context(hook, monkeypatch, capsys, gate=ABOVE) == ""  # it would show the edge as still grounded


def test_an_mtime_only_touch_keeps_the_context(world, monkeypatch, capsys):
    e, hook, _ = world
    note = e.canon.node_path("centro")
    stat = note.stat()
    os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert "centro --grounds--> a" in _context(hook, monkeypatch, capsys, gate=ABOVE)


def test_a_source_edit_is_not_served_stale(world, monkeypatch, capsys):
    _, hook, src = world
    src.write_text(SRC + "\nOtra frase.\n", encoding="utf-8")
    assert _context(hook, monkeypatch, capsys, gate=ABOVE) == ""
