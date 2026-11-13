"""0.15.0: a rendered view stays current.

Field report (2026-11-13). After a grounding pass, the user asked whether `/burgess:kg-view` had to be run again
after every change to see it in graph.html. Through 0.14.5 it did. The graph.html in the user's browser had
been rendered on 2026-11-10, and 48 canon notes had changed since: a new source document, two merges, the
day's builds and grounding passes. None of it was in the view, and nothing said so.

The engine now re-renders each view that exists and is older than the projection's graph.json, on every read
that projects (`_ensure_projected` → `_refresh_views` → `export.refresh_views`):

- a write projects nothing, so it re-renders nothing; the first read that projects after it does;
- a projection the PreToolUse hook made, through its own projector, is caught up by the server's next read;
- a read never creates a view, and a view the user deleted stays deleted;
- a degraded projection (failed or contended) re-renders none, and a render that fails never fails the read;
- `kg_export` renders each view it was asked for once.

`/burgess:kg-build`, its leads mode and `/burgess:kg-ground` end with such a read, and the texts say so.
"""
from __future__ import annotations

import ast
import json
import logging
import os
from pathlib import Path

import pytest

from kg_engine import export
from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUNDS = edge_id("compression", "grounds", "claim")
ATTACK = edge_id("betweenness", "attacked_by", "generality-confound")
ATTACK_KEY = ("betweenness", "attacked_by", "generality-confound")
_DATA_PREFIX = "window.__KG_DATA__ = "


def _flat(text: str) -> str:
    return " ".join(text.split())


def _build(engine):
    engine.kg_write({"edges": [
        {"source": "compression", "target": "claim", "relation": "grounds",
         "span": "A compression stands in for many observations and grounds the claims beneath it",
         "provenance": "span-present", "authored_by": "agent"},
        {"source": "betweenness", "target": "generality-confound", "relation": "attacked_by",
         "span": "Betweenness is confounded by the generality confound",
         "provenance": "span-present", "authored_by": "agent"}]})
    engine.kg_ground(GROUNDS, "grounded")


def _views(engine):
    """The two views, by the names the user opens them by (not the module's constants, so a run against
    0.14.5 shows which of these tests pin behavior it already had)."""
    d = engine.projector.derived
    return d / "graph.html", d / "GRAPH_REPORT.md"


def _age(*paths, by_s: int = 60):
    """Move the files' times into the past, so "older than graph.json" never rests on a clock tick."""
    for p in paths:
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns - by_s * 10**9, st.st_mtime_ns - by_s * 10**9))


def _html_states(engine) -> dict:
    """(source, relation, target) -> epistemic_state, from the data graph.html inlines."""
    text = _views(engine)[0].read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith(_DATA_PREFIX))
    data = json.loads(line[len(_DATA_PREFIX):].rstrip().rstrip(";"))
    return {(link["source"], link["relation"], link["target"]): link["epistemic_state"] for link in data["links"]}


def _rendered(engine):
    """Both views, rendered now and then aged: a projection after this point leaves them behind."""
    engine.kg_export("all")
    html, report = _views(engine)
    _age(html, report)
    return html, report


# ---- the field case: a change, then a read ---------------------------------------------------------

def test_the_first_read_after_a_change_re_renders_both_views(engine):
    _build(engine)
    html, report = _rendered(engine)
    assert _html_states(engine)[ATTACK_KEY] == "unverified"
    assert "Falsification memory (§1.7 — never pruned): 0" in report.read_text(encoding="utf-8")

    engine.kg_ground(ATTACK, "failed")
    # a write never projects (defense #6), so it re-renders nothing
    assert _html_states(engine)[ATTACK_KEY] == "unverified"

    engine.kg_context("")                     # the first read that projects
    assert _html_states(engine)[ATTACK_KEY] == "failed"
    text = report.read_text(encoding="utf-8")
    assert "Falsification memory (§1.7 — never pruned): 1" in text
    assert "betweenness --attacked_by--> generality-confound` [failed]" in text
    projected = engine.projector.graph_path.stat().st_mtime_ns
    assert html.stat().st_mtime_ns >= projected and report.stat().st_mtime_ns >= projected


def test_a_new_edge_reaches_the_view_through_any_projecting_read(engine):
    _build(engine)
    _rendered(engine)
    engine.kg_write({"edges": [{"source": "entropy", "target": "arrow-of-time", "relation": "grounds",
                                "span": "Entropy grounds the arrow of time",
                                "provenance": "span-present", "authored_by": "agent"}]})
    assert ("entropy", "grounds", "arrow-of-time") not in _html_states(engine)
    engine.get_node("entropy")                # get_node projects like every read behind `_proj`
    assert _html_states(engine)[("entropy", "grounds", "arrow-of-time")] == "unverified"


def test_a_projection_the_hook_made_is_caught_up_by_the_next_read(engine, source_path):
    _build(engine)
    _rendered(engine)
    engine.kg_ground(ATTACK, "failed")
    # The PreToolUse hook projects through its own read-only projector, which renders nothing.
    hook = KGEngine.read_only_projector(engine.project_dir, engine.data_dir, source_path=source_path,
                                        pack_path=PACK)
    hook.project()
    assert _html_states(engine)[ATTACK_KEY] == "unverified"
    assert not engine.projector.is_stale()    # so the server's next read projects nothing...
    engine.kg_context("")
    assert _html_states(engine)[ATTACK_KEY] == "failed"   # ...and still renders past the hook's projection


# ---- what a read never does ------------------------------------------------------------------------

def test_a_read_never_creates_a_view(engine):
    _build(engine)
    engine.kg_context("")
    engine.kg_ground(ATTACK, "failed")
    engine.kg_context("")
    html, report = _views(engine)
    assert not html.exists() and not report.exists()


def test_only_the_views_that_exist_are_kept_current(engine):
    _build(engine)
    engine.kg_export("html")                  # the user asked for the HTML alone
    html, report = _views(engine)
    _age(html)
    engine.kg_ground(ATTACK, "failed")
    engine.kg_context("")
    assert _html_states(engine)[ATTACK_KEY] == "failed"
    assert not report.exists()


def test_a_view_the_user_deleted_stays_deleted(engine):
    _build(engine)
    html, report = _rendered(engine)
    report.unlink()
    engine.kg_ground(ATTACK, "failed")
    engine.kg_context("")
    assert _html_states(engine)[ATTACK_KEY] == "failed"
    assert not report.exists()


def test_a_current_view_is_not_re_rendered(engine):
    _build(engine)
    engine.kg_export("all")
    html, report = _views(engine)
    before = (html.stat().st_mtime_ns, report.stat().st_mtime_ns)
    engine.kg_context("")
    engine.get_node("compression")
    engine.query_graph(epistemic_state="unverified")
    assert (html.stat().st_mtime_ns, report.stat().st_mtime_ns) == before


# ---- failures stay contained -----------------------------------------------------------------------

@pytest.mark.parametrize("how", ["failed", "contended"])
def test_a_degraded_projection_re_renders_no_view(engine, monkeypatch, how):
    _build(engine)
    html, report = _rendered(engine)
    before = (html.read_bytes(), report.read_bytes())
    engine.kg_ground(ATTACK, "failed")
    if how == "failed":
        def boom(*_a, **_k):
            raise RuntimeError("projection blew up")
        monkeypatch.setattr(engine.projector, "project", boom)
    else:                                     # another session holds the canon lease
        monkeypatch.setattr(engine.projector.canon, "try_acquire_lock", lambda *_a, **_k: False)
    out = engine.kg_context("")
    assert "projection_degraded" in out
    assert (html.read_bytes(), report.read_bytes()) == before
    monkeypatch.undo()
    engine.kg_context("")                     # the next healthy read catches up
    assert _html_states(engine)[ATTACK_KEY] == "failed"


def test_a_render_that_fails_never_fails_the_read(engine, monkeypatch, caplog):
    _build(engine)
    html, _report = _rendered(engine)
    before = html.read_bytes()
    engine.kg_ground(ATTACK, "failed")

    def boom(_engine):
        raise OSError("disk full")
    monkeypatch.setattr(export, "build_html", boom)
    with caplog.at_level(logging.WARNING, logger="kg_engine"):
        out = engine.kg_context("")
    assert out["items"] and "projection_degraded" not in out
    assert html.read_bytes() == before        # the old view stays
    assert "could not re-render the graph views" in caplog.text


def test_kg_export_renders_each_view_it_was_asked_for_once(engine, monkeypatch):
    _build(engine)
    _rendered(engine)
    engine.kg_ground(ATTACK, "failed")        # both views are now behind the next projection
    calls = []
    real_html, real_report = export.build_html, export.build_report
    monkeypatch.setattr(export, "build_html", lambda e: calls.append("html") or real_html(e))
    monkeypatch.setattr(export, "build_report", lambda e: calls.append("report") or real_report(e))
    out = engine.kg_export("all")
    assert out["ok"] and sorted(calls) == ["html", "report"]
    assert _html_states(engine)[ATTACK_KEY] == "failed"


def test_refresh_views_reports_what_it_rendered(engine):
    _build(engine)
    assert export.refresh_views(engine) == []           # nothing rendered yet: nothing to keep current
    html, report = _rendered(engine)
    assert export.stale_views(engine) == ["html", "report"]
    assert export.refresh_views(engine) == ["html", "report"]
    assert export.stale_views(engine) == []


# ---- the texts -------------------------------------------------------------------------------------

def _tool_doc(name: str) -> str:
    tree = ast.parse((REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name \
                and any(ast.unparse(d).startswith("mcp.tool") for d in node.decorator_list):
            return ast.get_docstring(node) or ""
    raise AssertionError(f"no MCP tool {name}")


def test_the_kg_export_description_says_a_view_stays_current():
    doc = _flat(_tool_doc("kg_export"))
    assert "Once rendered, a view stays current" in doc
    assert "Only `/burgess:kg-view` creates one." in doc


def test_kg_view_says_the_views_follow_the_graph():
    text = _flat((REPO / "commands" / "kg-view.md").read_text(encoding="utf-8"))
    assert "**Once rendered, a view stays current (0.15.0).**" in text
    assert "A read never creates a view" in text
    assert "4. Tell the user the views now follow the graph" in text


def test_every_build_and_grounding_pass_ends_with_a_projecting_read():
    build = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
    step2 = _flat(build.split("### 2. Force / confirm the derived projection", 1)[1].split("### 3.", 1)[0])
    assert "The projection also brings the graph views `/burgess:kg-view` rendered up to date" in step2
    leads = _flat(build.split("## Leads mode", 1)[1].split("\n## ", 1)[0])
    assert ("4. **Confirm the projection:** call `mcp__plugin_burgess_burgess__kg_context(budget=300)`, as a "
            "build's step 2 does.") in leads
    assert "5. **Report:**" in leads
    ground = _flat((REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
                   .split("## Stage 3", 1)[1].split("\n## ", 1)[0])
    assert "also brings the graph views `/burgess:kg-view` rendered up to date (0.15.0)" in ground
