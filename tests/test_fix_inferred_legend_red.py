"""0.15.2: the legend's inferred item shows a pale red line under the pale green one.

Field request (2026-11-14). Once 0.15.1 re-rendered the field view, the user asked for a pale red line under the
pale green one in the legend's inferred item. The item says an inferred edge is drawn lighter "in any state", but
its one swatch showed only the grounded colour, while 16 of the field's 35 inferred edges are rejected and drawn
pale red. The item now stacks the two lines, both painted from the palette at the inferred opacity, which is how
the canvas draws an inferred grounded and an inferred rejected edge.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from kg_engine import __version__, export
from kg_engine.model import FAILURE_STATE_VALUES
from kg_engine.templates.graph_html import HTML_TEMPLATE

NODE = shutil.which("node")
GREEN = '<span class="sw" id="sw-inferred"></span>'
RED = '<span class="sw" id="sw-inferred-failed"></span>'


def _block(text: str, opener: str) -> str:
    """`opener` and the brace-balanced block that follows it, from `text`."""
    start = text.index(opener)
    i, depth = text.index("{", start), 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError(f"unbalanced block after {opener!r}")


def test_the_inferred_item_stacks_a_pale_red_line_under_the_pale_green_one():
    t = HTML_TEMPLATE
    item = next(ln.strip() for ln in t.splitlines() if "inferred (lighter, in any state)" in ln)
    assert item == f'<li><span class="sw-pair">{GREEN}{RED}</span>inferred (lighter, in any state)</li>'
    # the pair's swatches are blocks, so the red line sits under the green one rather than beside it
    assert ".sw-pair .sw { display: block; margin: 0; }" in t
    assert ".sw-pair .sw + .sw { margin-top: 4px; }" in t


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_both_lines_are_painted_as_the_canvas_draws_an_inferred_edge():
    """The template's own paintLegend, against a stub document, beside its own edgeStyle."""
    script = "\n".join([
        f"var FAILURE_STATES = {json.dumps(sorted(FAILURE_STATE_VALUES))};",
        "var els = {};",
        "var document = { getElementById: function (id) { return els[id] || (els[id] = { style: {} }); } };",
        _block(HTML_TEMPLATE, "var PALETTE = {") + ";",
        _block(HTML_TEMPLATE, "function edgeStyle(l) {"),
        _block(HTML_TEMPLATE, "function paintLegend() {"),
        "paintLegend();",
        "console.log(JSON.stringify({ els: els, drawn: {"
        " grounded: edgeStyle({ epistemic_state: 'grounded', provenance: 'inferred' }),"
        " rejected: edgeStyle({ epistemic_state: 'rejected', provenance: 'inferred' }) } }));",
    ])
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    els, drawn = got["els"], got["drawn"]
    green, red = els["sw-inferred"]["style"], els["sw-inferred-failed"]["style"]
    assert (green["borderTopColor"], green["opacity"]) == \
           (drawn["grounded"]["color"], drawn["grounded"]["alpha"]) == ("#2e7d32", 0.4)
    assert (red["borderTopColor"], red["opacity"]) == \
           (drawn["rejected"]["color"], drawn["rejected"]["alpha"]) == ("#c62828", 0.4)
    # the span-present line stays at full opacity
    assert "opacity" not in els["sw-span-present"]["style"]


def test_a_view_0_15_1_rendered_gets_the_red_line_on_the_next_read(engine):
    """The field views carry the 0.15.1 mark and the one-line item; the first read after the update
    re-renders them."""
    engine.kg_write({"edges": [
        {"source": "compression", "target": "claim", "relation": "grounds",
         "span": "A compression stands in for many observations and grounds the claims beneath it",
         "provenance": "inferred", "authored_by": "agent"}]})
    engine.kg_export("all")
    d = engine.projector.derived
    html, report = d / "graph.html", d / "GRAPH_REPORT.md"
    old = html.read_text(encoding="utf-8").replace(f"Burgess {__version__}", "Burgess 0.15.1", 1)
    html.write_text(old.replace(RED, "", 1), encoding="utf-8")
    report.write_text(report.read_text(encoding="utf-8").replace(f"Burgess {__version__}", "Burgess 0.15.1", 1),
                      encoding="utf-8")
    assert export.stale_views(engine) == ["html", "report"]
    engine.kg_context("")                     # the projection is current: only the marks are behind
    assert RED in html.read_text(encoding="utf-8")
    assert export.rendered_by(html) == export.rendered_by(report) == \
           tuple(int(p) for p in __version__.split(".")[:3])
