"""Regression pins for the 2026-07 review round (review-r7).

Each test corresponds to one verified finding from the exhaustive review and fails against the
pre-fix code:

  1. server.py — kg_write/kg_rename/kg_merge returned the canon rollback error (``info.error``)
     UNSCRUBBED, leaking an absolute vault path across the §1.9 egress boundary that every sibling
     error-return scrubs. The _tool_result envelope only scrubs RAISED exceptions, never a returned
     dict, so these three were real leaks.
  2. model.py — the frontmatter regex's ``\\s*`` after the closing fence greedily ate the body's
     first-line indentation, making node_from_markdown∘node_to_markdown lossy and silently defeating
     canon's idempotent-no-op write guard (node_content_hash mismatch).
  3. export.py — chained ``.replace()`` rescanned the inlined data payload, so a node label equal to
     the ``__KG_FAILURE_STATES_JSON__`` sentinel corrupted the graph.html JSON.
  4. generate.py — ``run_generators`` was defined twice; the second def shadowed the first plus the
     review-r5 module-level helpers, leaving them dead. The fix removes the duplicate.
  5. harness.py — the ideation/convergence/specificity CLIs crashed with an uncaught
     AttributeError/TypeError on a malformed top-level JSON shape instead of a clean exit-2.
  6. agents/evaluator.md — the kg-evaluator's tools grant omitted kg_generate, which /kg-experiment
     instructs it to call for the graph+generate+dpp arm.
  7. commands/kg-ground.md — Stage 0b prescribed ``kg_ground(grounded, support_span=...)`` to relocate
     a stale span-present span, but kg_ground ignored support_span for non-hypothesized items, so the
     remedy was a no-op and the stale flag never cleared. (0.27.0: the kg_write re-emit this review put in
     its place never worked either, since the boundary quarantines a re-emit of a judged claim; since 0.27.0
     the plan queues such claims and kg_ground moves their span, tests/test_fix_gone_spans.py.)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_engine import generate, harness
from kg_engine.canon import RollbackInfo
from kg_engine.harness import convergence, ideation, specificity
from kg_engine.model import (
    FAILURE_STATE_VALUES,
    Node,
    node_content_hash,
    node_from_markdown,
    node_to_markdown,
)

_REPO = Path(__file__).resolve().parents[1]
_SPAN = "A compression stands in for many observations"  # verbatim in tests/conftest.py SOURCE


# --- 1. server egress: rollback error must be scrubbed ------------------------------------------

def _leaky_rollback(path_error: str):
    return lambda *a, **k: RollbackInfo(rolled_back=True, error=path_error)


def test_r7_write_rollback_error_is_scrubbed(engine, monkeypatch):
    # a canon write fault whose str() embeds an absolute path (EACCES/ENOSPC/EROFS on the atomic temp)
    leak = "[Errno 13] Permission denied: '/secret/vault/canon/.tmp-abc123.md'"
    monkeypatch.setattr(engine.canon, "write_nodes", _leaky_rollback(leak))
    out = engine.kg_write({"edges": [{"source": "compression", "target": "betweenness",
                                      "relation": "grounds", "span": _SPAN}]})
    assert out["rolled_back"] is True
    assert "/secret/vault" not in out["error"]      # absolute path must NOT cross the egress
    assert "<path>" in out["error"]                 # redacted by _scrub_error
    assert "Permission denied" in out["error"]      # the reason survives


def test_r7_rename_rollback_error_is_scrubbed(engine, monkeypatch):
    # reach the rolled-back branch of kg_rename: a grounded edge means the audit log exists and the
    # rename emits a migration record, so audited_write compensates instead of orphaning.
    engine.kg_write({"edges": [{"source": "compression", "target": "betweenness",
                                "relation": "grounds", "span": _SPAN}]})
    assert engine.kg_ground(target_id="e_compression__grounds__betweenness", verdict="grounded")["ok"]
    leak = "[Errno 28] No space left on device: '/secret/vault/canon/compaction.md'"
    monkeypatch.setattr(engine.canon, "write_nodes", _leaky_rollback(leak))
    out = engine.kg_rename("compression", "compaction")
    assert out["ok"] is False
    assert "/secret/vault" not in out["error"]
    assert "<path>" in out["error"] and "rename rolled back" in out["error"]


def test_r7_merge_rollback_error_is_scrubbed(engine, monkeypatch):
    engine.kg_write({"nodes": [{"id": "compression", "node_type": "compression", "label": "Compression"},
                               {"id": "compaction", "node_type": "compression", "label": "Compaction"},
                               {"id": "betweenness", "node_type": "metric", "label": "Betweenness"}],
                     "edges": [{"source": "compression", "target": "betweenness",
                                "relation": "grounds", "span": _SPAN}]})
    assert engine.kg_ground(target_id="e_compression__grounds__betweenness", verdict="grounded")["ok"]
    leak = "[Errno 28] No space left on device: '/secret/vault/canon/compaction.md'"
    monkeypatch.setattr(engine.canon, "write_nodes", _leaky_rollback(leak))
    out = engine.kg_merge("compression", "compaction")
    assert out["ok"] is False
    assert "/secret/vault" not in out["error"]
    assert "<path>" in out["error"] and "merge rolled back" in out["error"]


# --- 2. model.py frontmatter round-trip preserves body leading whitespace -----------------------

@pytest.mark.parametrize("body", [
    "    code line 1\n    code line 2",  # a 4-space markdown code block
    "   hello",
    "\tindented",
    "normal body",
    "",
    "a\n    b",
    "line\n\nwith blank",
])
def test_r7_frontmatter_roundtrip_preserves_leading_whitespace(body):
    n = Node(id="x", label="X", node_type="note", body=body)
    assert node_from_markdown(node_to_markdown(n)).body == body


def test_r7_leading_whitespace_note_hits_noop_write_guard(canon):
    # the downstream consequence: the on-disk re-parse must hash-equal the incoming node, or
    # Canon._write_batch's idempotent-no-op guard never fires (spurious rewrite + timestamp churn).
    n = Node(id="idem-ws", label="Idem", node_type="note", body="    indented first line\n    second")
    reparsed = node_from_markdown(node_to_markdown(n))
    assert node_content_hash(reparsed) == node_content_hash(n)


# --- 3. export.py: a sentinel-valued label must not corrupt the inlined JSON ---------------------

def _data_line_obj(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.strip().startswith("window.__KG_DATA__"))
    payload = line.split("window.__KG_DATA__ =", 1)[1].rsplit(";", 1)[0].strip()
    return json.loads(payload)  # must not raise


def test_r7_export_sentinel_label_yields_valid_json(engine):
    engine.kg_write({"nodes": [{"id": "compression", "node_type": "compression",
                                "label": "__KG_FAILURE_STATES_JSON__"}],
                     "edges": [{"source": "compression", "target": "betweenness",
                                "relation": "grounds", "span": _SPAN}]})
    engine.kg_export("html")
    html = (engine.projector.derived / "graph.html").read_text(encoding="utf-8")
    obj = _data_line_obj(html)  # would raise json.JSONDecodeError pre-fix
    labels = {n["id"]: n.get("label") for n in obj["nodes"]}
    assert labels["compression"] == "__KG_FAILURE_STATES_JSON__"  # preserved verbatim, not rewritten
    assert "__KG_FAILURE_STATES_JSON__" not in html.replace(  # the real placeholder was substituted
        '"__KG_FAILURE_STATES_JSON__"', "")  # (ignore the one occurrence inside the JSON label value)


# --- 4. generate.py: run_generators defined once, module-level helpers live ----------------------

def test_r7_run_generators_defined_once():
    src = (_REPO / "scripts" / "kg_engine" / "generate.py").read_text(encoding="utf-8")
    assert src.count("\ndef run_generators(") == 1


def test_r7_run_generators_uses_module_level_helpers(monkeypatch):
    import networkx as nx
    G = nx.MultiDiGraph()
    for i in range(6):
        G.add_node(f"n{i}", label=f"C{i}", kind="concept")
    for a, b in [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (2, 3), (0, 4)]:
        G.add_edge(f"n{a}", f"n{b}", relation="relates_to")
    calls = {"dedup": 0, "tally": 0}
    _dedup, _tally = generate._dedup_candidates, generate._convergence_tally
    monkeypatch.setattr(generate, "_dedup_candidates",
                        lambda *a, **k: (calls.__setitem__("dedup", calls["dedup"] + 1), _dedup(*a, **k))[1])
    monkeypatch.setattr(generate, "_convergence_tally",
                        lambda *a, **k: (calls.__setitem__("tally", calls["tally"] + 1), _tally(*a, **k))[1])
    generate.run_generators(G, mechanism="all", k=5)
    assert calls["dedup"] == 1 and calls["tally"] == 1  # the live path calls the module-level helpers


# --- 5. harness CLIs: clean exit-2 on malformed top-level JSON, no traceback ---------------------

@pytest.mark.parametrize("cmd,content", [
    ("ideation", "[1, 2, 3]"),      # top-level array
    ("convergence", "5"),            # top-level scalar
    ("specificity", "[1, 2, 3]"),   # top-level array
])
def test_r7_harness_cli_malformed_toplevel_exits_2(tmp_path, cmd, content):
    f = tmp_path / "in.json"
    f.write_text(content, encoding="utf-8")
    assert harness._main([cmd, str(f)]) == 2  # clean usage error, not a raw traceback + exit 1


def test_r7_harness_public_functions_reject_bad_shapes():
    with pytest.raises(ValueError):
        convergence(5)                       # non-list history -> clean ValueError, not TypeError
    with pytest.raises(ValueError):
        specificity([1, 2, 3], corpus=None)  # non-object graph -> clean ValueError, not AttributeError
    with pytest.raises(ValueError):
        ideation(["not", "a", "dict"], "src")  # existing guard, still holds


def test_r7_harness_demo_paths_still_ok():
    # the no-arg demo paths must remain exit 0 (guards only reject wrong SHAPES, not the demos)
    for cmd in ("ideation", "convergence", "specificity"):
        assert harness._main([cmd]) == 0


# --- 6. evaluator subagent must be granted kg_generate ------------------------------------------

def test_r7_evaluator_grants_kg_generate():
    tools_line = next(l for l in (_REPO / "agents" / "evaluator.md").read_text(encoding="utf-8").splitlines()
                      if l.startswith("tools:"))
    assert "mcp__plugin_burgess_burgess__kg_generate" in tools_line


# --- 7. kg-ground.md Stage 0b prescribes a remedy that actually clears the flag ------------------

def test_r7_kg_ground_stage0b_remedy_is_not_a_noop():
    text = (_REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
    stage = text.split("## Stage 0b", 1)[1].split("## Stage 0c", 1)[0]
    # The remedy r7 pinned, a kg_write re-emit with the new span, was a no-op too: the boundary quarantines a
    # re-emit of a judged claim (collapses-into-known-verdict). Since 0.27.0 the stage prescribes no remedy of its
    # own: the plan queues the claims (span_gone) and their grounders move the span through kg_ground.
    assert "kg_write({" not in stage
    assert '"span_gone": true' in stage and "`collapses-into-known-verdict`" in stage
    assert 'verdict="grounded",\n     support_span' not in stage
    assert 'support_span="<the new verbatim span>")` (re-earns' not in stage
