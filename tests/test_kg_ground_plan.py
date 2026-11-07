"""0.7.0: /kg-ground plans its queue and hands each grounder its evidence in the engine, so it needs no shell.

Field report on 0.6.1, a /kg-ground on Windows in auto mode: the orchestrator listed the queue with
`query_graph(epistemic_state="unverified", limit=1000)`. On a canon of 168 unverified edges and 399 nodes that
came back as 300 000 characters, which Claude Code saved to a file. The orchestrator then wrote Python scripts to
parse it and read the plugin's own engine source, all through Bash, which auto mode stops on permission prompts:
the failure /kg-build had before 0.5.0. Two more flaws in the old flow: one grounder was asked to drain the whole
queue, and its prompt said to check spans against `examples/source.md`, the demo.

0.7.0 moves the work into two MCP tools the command and the grounders declare:

- `kg_ground_plan(focus, configured_wave_size, batch_size)`: the queue (every unverified edge, every unverified
  HYPOTHESIZED node) as `{id, kind}` items in batches, pins first, then other hypotheses, then the text edges
  their extractor marked weak, then the other text edges, each group in source order; the wave size; the hubs;
  and the source files.
- `kg_ground_item(target_id, kind)`: one item's evidence, which is the edge, `span_in_source` (the engine's own
  check now), its two nodes, and the excerpt of the section that holds the span, with the session scrub.

The extractor's own nodes are no longer queued: each names a concept the text uses, and the claims about it are
its edges.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_engine.groundplan import (DEFAULT_BATCH_SIZE, EXCERPT_CHARS, MAX_BATCH_SIZE, clamp_batch_size,
                                  focus_matches, span_excerpt)
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
ADVERSARIAL = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one

DOC = ("## Riesgo\nIntro del riesgo.\n\nEl RADAR de Meta mide el riesgo de cada cambio.\n\nCierre.\n\n"
       "## Calidad\nLas pruebas de mutación miden la calidad de los tests.\n\n"
       f"## Clave\nLa clave {TOKEN} abre el panel de control.\n")


# ---- the excerpt -------------------------------------------------------------------------------------

def test_the_excerpt_is_the_paragraph_and_its_neighbours():
    text = "## T\nUno.\n\nDos dice X causa Y.\n\nTres.\n\nCuatro."
    assert span_excerpt(text, "X causa Y") == text   # small enough to take every neighbour


def test_neighbours_stop_at_the_cap():
    far = "palabra " * 200
    text = f"{far}\n\nDos dice X causa Y.\n\n{far}"
    got = span_excerpt(text, "X causa Y", max_chars=600)
    assert got == "Dos dice X causa Y."


def test_a_span_across_two_paragraphs_is_found():
    text = "Uno.\n\nla primera mitad\n\nla segunda mitad\n\nCuatro."
    assert "la primera mitad" in span_excerpt(text, "la primera mitad la segunda mitad")


def test_a_long_table_is_cut_to_the_lines_around_the_span():
    rows = [f"| fila {i} | valor {i} |" for i in range(400)]
    rows[200] = "| control estadístico | no sirve aquí |"
    text = "\n".join(rows)
    got = span_excerpt(text, "control estadístico | no sirve aquí", max_chars=300)
    assert "control estadístico" in got and len(got) <= 300


def test_a_span_the_section_does_not_hold_has_no_excerpt():
    assert span_excerpt("Nada que ver.", "otra cosa") is None
    assert span_excerpt("Algo.", "") is None


def test_batch_size_and_focus_rules():
    assert (clamp_batch_size(None), clamp_batch_size("x"), clamp_batch_size(0)) == (DEFAULT_BATCH_SIZE,) * 3
    assert (clamp_batch_size(5), clamp_batch_size(99)) == (5, MAX_BATCH_SIZE)
    assert focus_matches("", "x", "y")
    assert focus_matches("radar", "meta-radar", "RADAR de Meta")
    assert focus_matches("pruebas mutación", "pruebas-de-mutacion", "")
    assert not focus_matches("radar", "calidad", "Calidad")


# ---- the plan ----------------------------------------------------------------------------------------

@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text(DOC, encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    out = e.kg_write({"nodes": [{"id": "meta-radar", "label": "Meta RADAR", "node_type": "metric"},
                                {"id": "riesgo", "label": "riesgo", "node_type": "failure"},
                                {"id": "pruebas-de-mutacion", "label": "pruebas de mutación", "node_type": "operation"},
                                {"id": "calidad", "label": "calidad", "node_type": "metric"},
                                {"id": "clave", "label": "clave", "node_type": "primitive"},
                                {"id": "panel", "label": "panel de control", "node_type": "primitive"}],
                      "edges": [{"source": "pruebas-de-mutacion", "target": "calidad", "relation": "approximates",
                                 "span": "Las pruebas de mutación miden la calidad de los tests",
                                 "source_file": "doc.md"},
                                {"source": "meta-radar", "target": "riesgo", "relation": "approximates",
                                 "span": "El RADAR de Meta mide el riesgo de cada cambio", "source_file": "doc.md"},
                                {"source": "clave", "target": "panel", "relation": "grounds",
                                 "span": f"La clave {TOKEN} abre el panel de control", "source_file": "doc.md"}],
                      "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 9, out
    return e


RADAR = "e_meta-radar__approximates__riesgo"
MUTACION = "e_pruebas-de-mutacion__approximates__calidad"
CLAVE = "e_clave__grounds__panel"


def _ids(plan: dict) -> "list[tuple[str, str]]":
    return [(i["id"], i["kind"]) for b in plan["batches"] for i in b]


def test_the_queue_is_the_unverified_edges_in_source_order(eng):
    plan = eng.kg_ground_plan("", "")
    assert plan["ok"]
    assert _ids(plan) == [(RADAR, "edge"), (MUTACION, "edge"), (CLAVE, "edge")]   # §Riesgo, §Calidad, §Clave
    assert plan["queue"] == {"edges": 3, "weak_edges": 0, "nodes": 0, "extractor_nodes_not_queued": 6}
    assert plan["source"]["files"] == ["doc.md"]


def test_edges_marked_weak_go_before_the_other_text_edges(eng):
    # CLAVE is last in source order; marked AMBIGUOUS it leads, and MUTACION, scored under one half, follows it
    eng.kg_write({"edges": [{"source": "clave", "target": "panel", "relation": "grounds",
                             "span": f"La clave {TOKEN} abre el panel de control", "source_file": "doc.md",
                             "confidence": "AMBIGUOUS"},
                            {"source": "pruebas-de-mutacion", "target": "calidad", "relation": "approximates",
                             "span": "Las pruebas de mutación miden la calidad de los tests",
                             "source_file": "doc.md", "confidence_score": 0.4}]})
    plan = eng.kg_ground_plan("", "")
    assert _ids(plan) == [(MUTACION, "edge"), (CLAVE, "edge"), (RADAR, "edge")]   # weak ones in source order
    assert plan["queue"]["weak_edges"] == 2
    eng.kg_write({"edges": [{"source": "pruebas-de-mutacion", "target": "calidad", "relation": "approximates",
                             "span": "Las pruebas de mutación miden la calidad de los tests",
                             "source_file": "doc.md", "confidence_score": 0.5}]})   # one half is not weak
    assert [i for i, _ in _ids(eng.kg_ground_plan("", ""))] == [CLAVE, RADAR, MUTACION]


def test_pins_and_hypotheses_go_first(eng):
    eng.kg_propose({"nodes": [{"id": "idea-pinned", "label": "Idea", "node_type": "claim",
                               "body": "[diverge] pinned from a brief"},
                              {"id": "idea-generada", "label": "Otra", "node_type": "claim"}]})
    ids = [i for i, _ in _ids(eng.kg_ground_plan("", ""))]
    assert ids[:2] == ["idea-pinned", "idea-generada"]
    assert eng.kg_ground_plan("", "")["queue"]["nodes"] == 2


def test_a_verdicted_item_leaves_the_queue(eng):
    assert eng.kg_ground(RADAR, "rejected", note="test")["ok"]
    assert RADAR not in [i for i, _ in _ids(eng.kg_ground_plan("", ""))]


def test_batches_waves_and_the_option(eng):
    plan = eng.kg_ground_plan("", "2", batch_size=2)
    assert [len(b) for b in plan["batches"]] == [2, 1]
    assert (plan["batch_size"], plan["wave_size"], plan["wave_size_from"], plan["waves"]) == (2, 2, "option", 1)
    unset = eng.kg_ground_plan("", "${user_config.extract_wave_size}")
    assert (unset["wave_size"], unset["wave_size_from"]) == (6, "default")


def test_the_focus_keeps_what_touches_a_named_node(eng):
    assert _ids(eng.kg_ground_plan("radar", "")) == [(RADAR, "edge")]
    assert eng.kg_ground_plan("nada-parecido", "")["batches"] == []


def test_hubs_are_the_most_connected_nodes(vault, tmp_path):
    src = tmp_path / "hub.md"
    src.write_text("## H\nEl centro une a, b y c.\n", encoding="utf-8")
    e = KGEngine(vault, source_path=src)
    e.kg_write({"edges": [{"source": "centro", "target": t, "relation": "grounds",
                           "span": "El centro une a, b y c", "source_file": "hub.md"} for t in ("a", "b", "c")]})
    assert e.kg_ground_plan("", "")["hubs"] == [{"id": "centro", "label": "centro", "degree": 3}]


# ---- the evidence ------------------------------------------------------------------------------------

def test_an_edges_evidence_is_its_span_its_nodes_and_its_excerpt(eng):
    got = eng.kg_ground_item(RADAR)
    assert got["ok"] and got["kind"] == "edge"
    assert got["edge"]["span"] == "El RADAR de Meta mide el riesgo de cada cambio"
    assert got["span_in_source"] is True
    assert (got["source_node"]["id"], got["target_node"]["id"]) == ("meta-radar", "riesgo")
    assert got["context"]["title"] == "Riesgo"
    assert "Intro del riesgo." in got["context"]["excerpt"]                # the neighbouring paragraphs
    assert len(got["context"]["excerpt"]) <= EXCERPT_CHARS


def test_a_stale_span_shows_as_not_in_source(eng, tmp_path):
    (tmp_path / "doc.md").write_text(DOC.replace("mide el riesgo", "estima el riesgo"), encoding="utf-8")
    got = eng.kg_ground_item(RADAR)
    assert got["span_in_source"] is False and got["context"] is None


def test_evidence_leaves_through_the_session_scrub(eng):
    got = eng.kg_ground_item(CLAVE)
    blob = json.dumps(got)
    assert TOKEN not in blob
    assert "⟦SECRET:" in got["edge"]["span"] and "⟦SECRET:" in got["context"]["excerpt"]
    # the session placeholders restore, so a support span copied back from the evidence verifies
    restore = eng._restore_fn()
    assert TOKEN in restore(got["edge"]["span"])


def test_a_nodes_evidence_is_the_node_and_its_edges(eng):
    got = eng.kg_ground_item("meta-radar", "node")
    assert got["ok"] and got["node"]["label"] == "Meta RADAR"
    assert [e["id"] for e in got["edges"]] == [RADAR]


def test_unknown_items_are_refused(eng):
    assert eng.kg_ground_item("e_nada__grounds__nada")["ok"] is False
    assert eng.kg_ground_item("nada", "node")["ok"] is False
    assert eng.kg_ground_item(RADAR, "otra")["ok"] is False


def test_both_tools_through_the_real_mcp_layer(eng):
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from kg_engine.server import _register

    mcp = FastMCP("burgess-test")
    _register(mcp, eng)

    def call(name, args):
        out = asyncio.run(mcp.call_tool(name, args))
        out = out[0] if isinstance(out, tuple) else out
        return json.loads(out[0].text)

    plan = call("kg_ground_plan", {"focus": "", "configured_wave_size": 3, "batch_size": "2"})
    assert (plan["wave_size"], plan["batch_size"]) == (3, 2)
    assert call("kg_ground_item", {"target_id": RADAR})["span_in_source"] is True


# ---- the texts that wire it together -----------------------------------------------------------------

def _frontmatter_line(text: str, key: str) -> str:
    for line in text.split("---", 2)[1].splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1]
    raise AssertionError(key)


def test_kg_ground_declares_no_shell_and_plans_through_the_engine():
    allowed = {t.strip() for t in _frontmatter_line(CMD, "allowed-tools").split(",")}
    assert "Bash" not in allowed
    assert "mcp__plugin_burgess_burgess__kg_ground_plan" in allowed
    assert "```bash" not in CMD
    flat = " ".join(CMD.split())
    assert "This command needs no shell and no file access." in flat
    assert 'focus: "<the arguments line above, verbatim; empty if nothing was typed>"' in CMD
    assert 'configured_wave_size: "${user_config.extract_wave_size}"' in CMD
    assert "mcp__plugin_burgess_burgess__kg_ground_item(target_id:" in CMD
    assert "examples/source.md" not in CMD


def test_the_grounders_fetch_their_evidence_instead_of_reading_files():
    tools = {t.strip() for t in _frontmatter_line(GROUNDER, "tools").split(",")}
    assert {"mcp__plugin_burgess_burgess__kg_ground_item", "mcp__plugin_burgess_burgess__kg_ground_plan"} <= tools
    flat = " ".join(GROUNDER.split())
    assert "**The check is the excerpt, not a file.**" in flat
    assert "Read the source once" not in flat
    adversarial = " ".join(ADVERSARIAL.split())
    assert "mcp__plugin_burgess_burgess__kg_ground_item" in _frontmatter_line(ADVERSARIAL, "tools")
    assert "`kg_ground_plan`'s `source.files`" in adversarial
