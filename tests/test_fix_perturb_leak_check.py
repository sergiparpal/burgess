"""0.19.1: /burgess:kg-perturb checks the canon with a digest, and the ensemble step says how each edge fared.

Field run (2026-11-16, 0.19.0). `/burgess:kg-perturb` re-read «Síntesis - Fábricas de software.md» with the graph's
known nodes. The extractor wrote 20 nodes, every one an id the graph had, and 10 edges. All 10 repeated edges
of the graph: 9 grounded, and one the graph had rejected (`base-de-conocimientos enables fabrica-industrial`).
`kg_generate(ensemble)` returned 0 candidates with an empty note, so the session ran scripts over the canon to
learn why. Its leak check hashed the canon with Bash, because its notes said counts could miss a leak. The
review showed that this is now exactly so: the second reading declares the graph's own nodes with a label and
body, so a write that lost its `construction=` routing would rewrite existing nodes, and every count would
stay the same. The field project has no git, so such a rewrite could not be undone.

So, in this release:
- `kg_metrics(digest=True)` adds `canon_digest`, a sha256 of the canon's note files, and the command compares
  it, with the counts, before and after the build;
- with a second construction, `kg_generate` carries `ensemble`: how each of its live edges fared, summing to
  `edges`; `note` says why when none of them is new, and when the top-k cut leaves new edges out.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import networkx as nx
import pytest

from kg_engine import generate as gen
from kg_engine.generate import BRIDGES_RELATION, ensemble_tally
from kg_engine.model import edge_id
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PERTURB = (REPO / "commands" / "kg-perturb.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
COMMANDS = (REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8")

DOC = ("## Arquitectura\n"
       "El Brain guarda la memoria del proyecto para evitar amnesia y alucinaciones.\n\n"
       "Una cola de prefusión garantiza la serializabilidad de los cambios paralelos.\n\n"
       "## Qué es una fábrica\n"
       "La fábrica requiere tener una base de conocimientos con la que mejorar en cada iteración.\n")
SECOND = ("## Otra lectura\n"
          "El Brain guarda la memoria del proyecto para evitar amnesia y alucinaciones.\n\n"
          "La fábrica requiere tener una base de conocimientos con la que mejorar en cada iteración.\n\n"
          "Sin memoria persistente no hay cola de prefusión que valga.\n\n"
          "La serializabilidad exige que el Brain conserve el orden de los cambios.\n\n"
          "La base de conocimientos alimenta la cola de prefusión.\n")
REJECTED = edge_id("base", "enables", "fabrica")


@pytest.fixture
def src(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    (d / "doc.md").write_text(DOC, encoding="utf-8")
    return d


@pytest.fixture
def second(tmp_path: Path) -> Path:
    p = tmp_path / "second" / "otra.md"
    p.parent.mkdir()
    p.write_text(SECOND, encoding="utf-8")
    return p


NODES = [{"id": "brain", "label": "Brain", "node_type": "primitive", "body": "Memoria persistente del proyecto."},
         {"id": "amnesia", "label": "Amnesia y alucinaciones", "node_type": "failure"},
         {"id": "cola", "label": "Cola de prefusión", "node_type": "operation"},
         {"id": "serial", "label": "Serializabilidad de los cambios paralelos", "node_type": "primitive"},
         {"id": "base", "label": "Base de conocimientos", "node_type": "primitive"},
         {"id": "fabrica", "label": "Fábrica industrial de software", "node_type": "primitive",
          "body": "Sentido 1: historia (Hitachi, SDC, Toshiba)."}]


@pytest.fixture
def eng(vault: Path, src: Path) -> KGEngine:
    """The field's shape: two live edges, and `base enables fabrica`, which the graph rejected."""
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    out = e.kg_write({
        "nodes": NODES,
        "edges": [{"source": "brain", "target": "amnesia", "relation": "defends_against", "source_file": "doc.md",
                   "span": "El Brain guarda la memoria del proyecto para evitar amnesia y alucinaciones"},
                  {"source": "cola", "target": "serial", "relation": "enables", "source_file": "doc.md",
                   "span": "Una cola de prefusión garantiza la serializabilidad de los cambios paralelos"},
                  {"source": "base", "target": "fabrica", "relation": "enables", "source_file": "doc.md",
                   "span": "La fábrica requiere tener una base de conocimientos"}]})
    assert out["dispositions"]["ACCEPTED"] == 9, out
    assert e.kg_ground(REJECTED, "rejected", note="wrong-node: the passage is about the AI factory")["ok"]
    return e


def _reread(eng: KGEngine, second: Path, edges: list, *, name: str = "otra") -> dict:
    """A second construction with the graph's own ids, the nodes declared with a label and body of its own, as
    the 0.19.0 brief asks; `edges` are (source, relation, target, span) read off `second`."""
    out = eng.kg_write({
        "nodes": [{**n, "label": n["label"] + " (segunda lectura)", "body": "Cuerpo de la segunda lectura."}
                  for n in NODES],
        "edges": [{"source": s, "target": t, "relation": r, "span": span, "source_file": second.name}
                  for s, r, t, span in edges]},
        construction=name, source=str(second))
    assert out["dispositions"]["REJECTED"] == 0 and out["dispositions"]["QUARANTINED"] == 0, out
    return out


FIELD_EDGES = [("brain", "defends_against", "amnesia",
                "El Brain guarda la memoria del proyecto para evitar amnesia y alucinaciones"),
               ("base", "enables", "fabrica", "La fábrica requiere tener una base de conocimientos")]


# --------------------------------------------------------------------------- the canon digest


def test_kg_metrics_without_digest_is_unchanged(eng):
    assert set(eng.kg_metrics()) == {"nodes", "edges", "edges_by_epistemic_state"}


def test_the_digest_holds_while_the_canon_does_not_change(eng):
    first = eng.kg_metrics(digest=True)["canon_digest"]
    assert len(first) == 64
    eng.kg_context(budget=2000)
    eng.kg_generate(mechanism="bridge", k=5)
    assert eng.kg_metrics(digest=True)["canon_digest"] == first


def test_a_routed_second_construction_leaves_the_digest_alone(eng, second):
    before = eng.kg_metrics(digest=True)
    _reread(eng, second, FIELD_EDGES)
    assert eng.kg_metrics(digest=True) == before


def test_an_unrouted_rewrite_of_known_nodes_moves_the_digest_and_not_the_counts(eng):
    """The hazard the digest exists for: the same write without `construction=` lands on the graph's own
    nodes. Every count stays the same; labels and an unverified body are rewritten."""
    before = eng.kg_metrics(digest=True)
    out = eng.kg_write({
        "nodes": [{**n, "label": n["label"] + " (segunda lectura)", "body": "Cuerpo de la segunda lectura."}
                  for n in NODES],
        "edges": [{"source": "brain", "target": "amnesia", "relation": "defends_against", "source_file": "doc.md",
                   "span": "El Brain guarda la memoria del proyecto para evitar amnesia y alucinaciones"}]})
    assert out["dispositions"]["ACCEPTED"] >= len(NODES), out
    after = eng.kg_metrics(digest=True)
    assert {k: v for k, v in after.items() if k != "canon_digest"} == \
        {k: v for k, v in before.items() if k != "canon_digest"}
    assert after["canon_digest"] != before["canon_digest"]
    fabrica = eng.get_node("fabrica")
    assert fabrica["label"] == "Fábrica industrial de software (segunda lectura)"
    assert "Hitachi" not in (eng.canon.read_node("fabrica").body or "")


def test_an_idempotent_rewrite_leaves_the_digest_alone(eng):
    before = eng.kg_metrics(digest=True)["canon_digest"]
    eng.kg_write({"nodes": [n for n in NODES if n["id"] in ("cola", "serial")],
                  "edges": [{"source": "cola", "target": "serial", "relation": "enables", "source_file": "doc.md",
                             "span": "Una cola de prefusión garantiza la serializabilidad de los cambios "
                                     "paralelos"}]})
    assert eng.kg_metrics(digest=True)["canon_digest"] == before


def test_the_digest_sees_a_hand_edit(eng):
    before = eng.kg_metrics(digest=True)["canon_digest"]
    p = eng.canon.node_path("cola")
    p.write_text(p.read_text(encoding="utf-8") + "\nUna nota a mano.\n", encoding="utf-8")
    assert eng.kg_metrics(digest=True)["canon_digest"] != before


def test_the_kg_metrics_tool_takes_digest(engine):
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("burgess-test")
    _register(mcp, engine)
    tool = {t.name: t for t in asyncio.run(mcp.list_tools())}["kg_metrics"]
    assert "digest" in (tool.inputSchema.get("properties") or {})
    assert "canon_digest" in tool.description and "/burgess:kg-perturb" in tool.description


# --------------------------------------------------------------------------- the ensemble tally


def _graph(edges) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for s, rel, t, state in edges:
        for n in (s, t):
            G.add_node(n, label=n.upper(), specificity=1.0)
        G.add_edge(s, t, key=edge_id(s, rel or "x", t), relation=rel, epistemic_state=state,
                   span=f"{s} {rel} {t}", source_file="doc.md")
    return G


def test_the_tally_accounts_for_every_live_second_edge():
    G = _graph([("a", "grounds", "b", "grounded"), ("c", "enables", "d", "unverified"),
                ("e", "grounds", "f", "rejected")])
    G.add_node("g", label="G", specificity=1.0)
    failures = {edge_id("e", "grounds", "f")}
    G2 = _graph([("a", "grounds", "b", "unverified"),     # repeated: this very edge is live here
                 ("b", "enables", "a", "unverified"),     # joined_otherwise: the pair is joined here
                 ("f", "grounds", "e", "unverified"),     # known failure, by its reverse
                 ("x", "grounds", "a", "unverified"),     # ends_missing: x is not a node here
                 ("a", "", "c", "unverified"),            # untyped
                 ("a", "enables", "g", "unverified"),     # new
                 ("c", "grounds", "g", "rejected")])      # not live in the second construction: not counted
    tally = ensemble_tally(G, G2, failures=failures)
    assert tally == {"edges": 6, "ends_missing": 1, "repeated": 1, "joined_otherwise": 1, "untyped": 1,
                     "known_failures": 1, "new": 1, "known_failure_ids": [edge_id("e", "grounds", "f")]}
    parts = sum(v for k, v in tally.items() if k not in ("edges", "known_failure_ids"))
    assert parts == tally["edges"]
    cands = gen.ensemble(G, failures=failures, k=10, second_graph=G2)
    assert sum(1 for c in cands if c.relation != BRIDGES_RELATION) == tally["new"]


def test_kg_generate_says_why_nothing_is_new(eng, second):
    """The field run: the second reading repeats a live edge and the edge the graph rejected."""
    _reread(eng, second, FIELD_EDGES)
    out = eng.kg_generate(mechanism="ensemble", second_construction="otra", k=10)
    assert out["count"] == 0
    assert out["ensemble"] == {"edges": 2, "ends_missing": 0, "repeated": 1, "joined_otherwise": 0, "untyped": 0,
                               "known_failures": 1, "new": 0, "known_failure_ids": [REJECTED]}
    assert "none of the second construction's 2 edge(s) is new here" in out["note"]
    assert "already edges of this graph: 1" in out["note"]
    assert f"known failures: 1 ({REJECTED})" in out["note"]


def test_kg_generate_says_when_k_leaves_new_edges_out(eng, second):
    _reread(eng, second, FIELD_EDGES + [
        ("brain", "enables", "cola", "Sin memoria persistente no hay cola de prefusión que valga"),
        ("serial", "grounds", "brain", "La serializabilidad exige que el Brain conserve el orden de los cambios"),
        ("base", "enables", "cola", "La base de conocimientos alimenta la cola de prefusión")])
    out = eng.kg_generate(mechanism="ensemble", second_construction="otra", k=2)
    assert out["ensemble"]["new"] == 3 and out["count"] == 2
    assert "wrote 3 edge(s) between nodes this graph does not join; ensemble returns its top 2" in out["note"]
    assert "is new here" not in out["note"]


def test_new_edges_within_k_need_no_tally_note(eng, second):
    _reread(eng, second, [("brain", "enables", "cola", "Sin memoria persistente no hay cola de prefusión que valga")])
    out = eng.kg_generate(mechanism="ensemble", second_construction="otra", k=10)
    assert out["ensemble"]["new"] == 1 and out["count"] == 1
    assert "is new here" not in out["note"] and "raise k" not in out["note"]


def test_only_an_ensemble_over_a_second_construction_carries_a_tally(eng, second):
    _reread(eng, second, FIELD_EDGES)
    assert "ensemble" not in eng.kg_generate(mechanism="bridge", second_construction="otra", k=5)
    degraded = eng.kg_generate(mechanism="ensemble", k=5)
    assert "ensemble" not in degraded and "degraded to regroup" in degraded["note"]


# --------------------------------------------------------------------------- the texts


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_perturb_command_checks_the_digest_and_reports_the_tally():
    flat = _flat(PERTURB)
    assert "mcp__plugin_burgess_burgess__kg_metrics(digest=true)" in flat
    assert "`canon_digest`" in flat and "without changing any count" in flat
    assert "needs no Bash" in flat
    assert "If `count` is 0, skip this step" in flat
    for key in ("`repeated`", "`joined_otherwise`", "`known_failure_ids`", "`ends_missing`"):
        assert key in flat, key
    assert "never re-derive it from the canon" in flat


def test_the_references_describe_the_digest_and_the_tally():
    flat = _flat(TOOLS)
    assert "mcp__plugin_burgess_burgess__kg_metrics(digest=False)" in flat and "`canon_digest`" in flat
    assert "`known_failure_ids`" in flat and "`joined_otherwise`" in flat
    assert "`canon_digest`" in _flat(COMMANDS)
