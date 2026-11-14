"""0.15.1: an inferred edge is drawn lighter, whatever its state.

Field report (2026-11-13). Looking at graph.html, the user asked why the view showed no hypothesized (faint) or
inferred (mid) nodes and no hypothesized (dotted) lines. The field canon has none of those: its 463 nodes are
span-present, and nothing came through the propose lane. But 35 of its 261 edges are `inferred` (19 grounded,
16 rejected), and the view drew them exactly like span-present ones. The line showed the edge's state alone
(colour and dash), and only an unverified hypothesized edge had a line of its own. So the provenance axis was
invisible on edges, against the view's rule that the three axes sit on independent channels.

An edge's provenance now has its own channel, the line's opacity, as a node's has its fill's. An inferred edge
is drawn at `PALETTE.edgeAlpha.inferred`, in every state. Colour, width and dash stay the state's.

For that to reach the field view, a view an older engine rendered is now stale too. The field views were
rendered by 0.14.5 after the day's last projection, and 0.15.0 re-rendered a view only when the projection
moved past it. Each view records the version that rendered it, and the next read re-renders one an older
engine made. A view a newer engine made is left alone.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kg_engine import __version__, export
from kg_engine.model import FAILURE_STATE_VALUES, edge_id
from kg_engine.templates.graph_html import HTML_TEMPLATE

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _block(text: str, opener: str) -> str:
    """`opener` and the brace-balanced block that follows it, from `text`."""
    start = text.index(opener)
    i, depth = text.index("{", start), 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError(f"unbalanced block after {opener!r}")


def _styles(cases: list) -> list:
    """Run the template's own `edgeStyle` under node, for each (epistemic_state, provenance)."""
    script = "\n".join([
        f"var FAILURE_STATES = {json.dumps(sorted(FAILURE_STATE_VALUES))};",
        _block(HTML_TEMPLATE, "var PALETTE = {") + ";",
        _block(HTML_TEMPLATE, "function edgeStyle(l) {"),
        f"var cases = {json.dumps(cases)};",
        "console.log(JSON.stringify(cases.map(function (c) {"
        " return edgeStyle({ epistemic_state: c[0], provenance: c[1] }); })));",
    ])
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


STATES = ["grounded", "rejected", "failed", "unverified"]


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_an_inferred_edge_is_lighter_in_every_state_and_nothing_else_changes():
    cases = [[s, p] for s in STATES for p in ("span-present", "inferred")]
    got = dict(zip(map(tuple, cases), _styles(cases)))
    for state in STATES:
        present, inferred = got[(state, "span-present")], got[(state, "inferred")]
        assert present["alpha"] == 1
        assert inferred["alpha"] == 0.4
        # the state's channel is untouched: same colour, width and dash
        assert {k: v for k, v in inferred.items() if k != "alpha"} == \
               {k: v for k, v in present.items() if k != "alpha"}


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_the_states_keep_their_lines():
    grounded, rejected, unverified, hypothesized = _styles(
        [["grounded", "span-present"], ["rejected", "inferred"], ["unverified", "span-present"],
         ["unverified", "hypothesized"]])
    assert grounded["color"] == "#2e7d32" and grounded["dash"] == []
    assert rejected["color"] == "#c62828" and rejected["dash"] == []
    assert unverified["color"] == "#9e9e9e" and unverified["dash"] == [6, 4]
    # a hypothesized edge keeps its dotted blue line while unverified, at full opacity
    assert hypothesized == {"color": "#1565c0", "width": 1.2, "dash": [2, 4], "alpha": 1}


def test_the_draw_loop_applies_the_opacity_per_edge_and_resets_it():
    t = HTML_TEMPLATE
    loop = _block(t, "links.forEach(function (l) {\n      if (!showFailed")
    assert "ctx.globalAlpha = style.alpha;" in loop
    # reset before the nodes are drawn, so a node's fill opacity never inherits an edge's
    after = t[t.index(loop) + len(loop):]
    assert after.lstrip(");\n ").startswith("ctx.setLineDash([]); ctx.globalAlpha = 1;")


def test_the_legend_shows_the_edge_channel_from_the_palette():
    t = HTML_TEMPLATE
    assert '<div class="ax">provenance — edge line opacity</div>' in t
    # 0.15.2 pairs a pale red line with this swatch (tests/test_fix_inferred_legend_red.py)
    assert '<span class="sw" id="sw-inferred"></span>' in t and "inferred (lighter, in any state)</li>" in t
    assert 'document.getElementById("sw-inferred").style.opacity = PALETTE.edgeAlpha.inferred;' in t


def test_the_view_carries_each_edges_provenance(engine):
    engine.kg_write({"edges": [
        {"source": "compression", "target": "claim", "relation": "grounds",
         "span": "A compression stands in for many observations and grounds the claims beneath it",
         "provenance": "span-present", "authored_by": "agent"},
        {"source": "entropy", "target": "arrow-of-time", "relation": "grounds",
         "span": "Entropy grounds the arrow of time", "provenance": "inferred", "authored_by": "agent"}]})
    engine.kg_ground(edge_id("entropy", "grounds", "arrow-of-time"), "grounded")
    engine.kg_export("html")
    html = (engine.projector.derived / "graph.html").read_text(encoding="utf-8")
    line = next(ln for ln in html.splitlines() if ln.startswith("window.__KG_DATA__ = "))
    links = json.loads(line[len("window.__KG_DATA__ = "):].rstrip().rstrip(";"))["links"]
    prov = {(lk["source"], lk["target"]): (lk["epistemic_state"], lk["provenance"]) for lk in links}
    assert prov[("entropy", "arrow-of-time")] == ("grounded", "inferred")
    assert prov[("compression", "claim")] == ("unverified", "span-present")


def test_kg_view_describes_the_edge_channel():
    text = _flat((REPO / "commands" / "kg-view.md").read_text(encoding="utf-8"))
    assert "an `inferred` edge's line is drawn lighter, whatever its state (0.15.1)" in text
    assert "After a plugin update, that read also re-renders a view an older version rendered" in text


# ---- a view an older engine rendered is re-rendered (0.15.1) -----------------------------------------
# 0.15.0 re-rendered a view only when the projection moved past it. A new template then reached an open view
# only with the next change to the graph: on the field project the views were rendered at 23:34, by 0.14.5,
# after the day's last projection, so 0.15.1's lighter inferred edges would not have shown on the next read.


CURRENT = tuple(int(p) for p in __version__.split(".")[:3])


def _rendered_views(engine):
    engine.kg_write({"edges": [
        {"source": "compression", "target": "claim", "relation": "grounds",
         "span": "A compression stands in for many observations and grounds the claims beneath it",
         "provenance": "inferred", "authored_by": "agent"}]})
    engine.kg_export("all")
    d = engine.projector.derived
    return d / "graph.html", d / "GRAPH_REPORT.md"


def _remark(path: Path, mark: "str | None"):
    """Rewrite the view's version mark (None: no mark, as before 0.15.1). The rewrite leaves the file newer
    than graph.json, so only the mark can make it stale."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        old = f'<meta name="generator" content="Burgess {__version__}">\n'
        new = "" if mark is None else f'<meta name="generator" content="Burgess {mark}">\n'
    else:
        old = f"<!-- Burgess {__version__} -->\n"
        new = "" if mark is None else f"<!-- Burgess {mark} -->\n"
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_each_view_records_the_engine_version_that_rendered_it(engine):
    html, report = _rendered_views(engine)
    assert f'<meta name="generator" content="Burgess {__version__}">' in html.read_text(encoding="utf-8")
    assert report.read_text(encoding="utf-8").splitlines()[0] == f"<!-- Burgess {__version__} -->"
    assert export.rendered_by(html) == CURRENT and export.rendered_by(report) == CURRENT
    assert export.stale_views(engine) == []


@pytest.mark.parametrize("mark", [None, "0.15.0", "0.14.5"])
def test_a_view_an_older_engine_rendered_is_re_rendered_on_the_next_read(engine, mark):
    html, report = _rendered_views(engine)
    for p in (html, report):
        _remark(p, mark)
    assert export.stale_views(engine) == ["html", "report"]
    engine.kg_context("")                     # the projection is current: only the marks are behind
    assert export.rendered_by(html) == CURRENT and export.rendered_by(report) == CURRENT
    assert "edgeAlpha" in html.read_text(encoding="utf-8")


def test_a_view_a_newer_engine_rendered_is_left_alone(engine):
    html, report = _rendered_views(engine)
    for p in (html, report):
        _remark(p, "99.0.0")
    before = (html.read_bytes(), report.read_bytes())
    engine.kg_context("")
    assert (html.read_bytes(), report.read_bytes()) == before
