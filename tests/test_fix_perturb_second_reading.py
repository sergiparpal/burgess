"""0.19.0: a second reading keeps its relation and its passage, and reads with the graph's ids.

Field test (2026-11-16, 0.18.1). `/burgess:kg-perturb` re-read `fronteras-de-centralizacion.md`, one of the
sources the graph was built from. The second construction gave 13 of its 39 nodes an id the graph had, so the
ensemble step could compare 4 of its 22 edges; 3 the graph already held grounded. The fourth was new,
`tcp-ip-frente-a-osi grounds regla-de-centralizacion`, read off «TCP/IP frente a OSI es el caso canónico. …
Ganó el que acordó menos.». The ensemble step proposed it as `regla-de-centralizacion bridges
tcp-ip-frente-a-osi` with no text; its two ends were placed in different sections, so the grounder saw no
passage and rejected it `no-support`. A targeted extraction wrote the relation the same day.

So, in this release:
- an ensemble candidate is the edge the second construction wrote, with its relation and direction, and
  carries `passage`, the span it was written from; a pair whose second-graph edge records no relation is
  still a plain `bridges`;
- `kg_generate` says whether each passage verifies against the configured sources (`in_source`);
- `kg_propose` keeps a passage that holds there, opening the proposal's notes with it, and only the engine
  writes that segment;
- `kg_ground_item` shows the grounder a proposal's passage and the excerpt around it;
- `kg_section` serves a section of a second construction's source, with the graph's own known nodes, so the
  second reading can write a concept under the graph's id.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from kg_engine import generate as gen
from kg_engine.groundplan import PASSAGE_MARK, passage_of, with_passage, without_passage
from kg_engine.model import edge_id, normalize_text
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PERTURB = (REPO / "commands" / "kg-perturb.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GENERATOR = (REPO / "agents" / "generator.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one

CASE = ("TCP/IP frente a OSI es el caso canónico. OSI especificó el aparato entero. TCP/IP\n"
        "especificó direccionamiento y entrega, y soltó el resto. Ganó el que acordó menos.")
DOC = ("## La regla\n"
       "Centraliza el conjunto mínimo de acuerdos sin los cuales las partes no componen. Nada más.\n\n"
       "Es el argumento extremo a extremo aplicado fuera de las redes.\n\n"
       "## Interfaz o implementación\n"
       "Estandariza aquello en lo que todo debe coincidir para componer.\n\n"
       "Por tanto, conservador y lento con lo que estandarizas, permisivo con lo demás.\n\n"
       f"{CASE}\n\n"
       f"La clave {TOKEN} abre el registro del estándar.\n\n"
       "## Checklist\n- Revisa la frontera cada trimestre.\n")
OUTSIDE = "## Fuera\nTCP/IP frente a OSI muestra la regla de centralización mínima en acción.\n"
LOST = edge_id("tcpip", "grounds", "regla")


@pytest.fixture
def src(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    (d / "doc.md").write_text(DOC, encoding="utf-8")
    return d


@pytest.fixture
def eng(vault: Path, src: Path) -> KGEngine:
    e = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")
    out = e.kg_write({
        "nodes": [{"id": "regla", "label": "Regla de centralización mínima", "node_type": "claim"},
                  {"id": "extremo", "label": "Argumento extremo a extremo", "node_type": "claim"},
                  {"id": "conservador", "label": "Conservador con lo que estandarizas", "node_type": "claim"},
                  {"id": "tcpip", "label": "TCP/IP frente a OSI", "node_type": "claim"},
                  {"id": "registro", "label": "Registro del estándar", "node_type": "primitive"}],
        "edges": [{"source": "extremo", "target": "regla", "relation": "grounds", "source_file": "doc.md",
                   "span": "Es el argumento extremo a extremo aplicado fuera de las redes"},
                  {"source": "tcpip", "target": "conservador", "relation": "grounds", "source_file": "doc.md",
                   "span": "Ganó el que acordó menos"},
                  {"source": "registro", "target": "conservador", "relation": "projects", "source_file": "doc.md",
                   "span": f"La clave {TOKEN} abre el registro del estándar"}]})
    assert out["dispositions"]["ACCEPTED"] == 8, out
    return e


def _second_reading(eng: KGEngine, src: Path, *, name: str = "re", span: str = CASE,
                    source: "Path | None" = None) -> dict:
    """A second construction that writes `tcpip grounds regla` from ``span`` of ``source`` (doc.md, re-read)."""
    source = source or (src / "doc.md")
    return eng.kg_write({
        "nodes": [{"id": "tcpip", "label": "TCP/IP frente a OSI", "node_type": "claim"},
                  {"id": "regla", "label": "Centraliza el conjunto mínimo de acuerdos", "node_type": "claim"}],
        "edges": [{"source": "tcpip", "target": "regla", "relation": "grounds", "span": span,
                   "source_file": source.name}]},
        construction=name, source=str(source))


def _ensemble(eng: KGEngine, name: str = "re") -> dict:
    out = eng.kg_generate(mechanism="ensemble", second_construction=name, k=10)
    assert "degraded to regroup" not in (out.get("note") or ""), out
    return out


# --------------------------------------------------------------------------- the ensemble step


def _plain_graph(edges, **attrs) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for s, t in edges:
        for n in (s, t):
            G.add_node(n, label=n.upper(), specificity=1.0)
        G.add_edge(s, t, key=edge_id(s, "grounds", t), relation="grounds", epistemic_state="grounded", **attrs)
    return G


def test_ensemble_proposes_the_edge_the_second_construction_wrote():
    G = _plain_graph([("a", "b"), ("b", "c")])
    G2 = nx.MultiDiGraph()
    G2.add_edge("c", "a", key="e2", relation="enables", epistemic_state="unverified",
                span="C makes A possible", source_file="doc.md")
    cands = gen.ensemble(G, failures=set(), k=10, second_graph=G2)
    assert [(c.source, c.relation, c.target) for c in cands] == [("c", "enables", "a")]
    c = cands[0]
    assert c.passage == {"span": "C makes A possible", "source_file": "doc.md"}
    assert c.to_dict()["passage"] == c.passage and "span" not in c.to_dict()
    assert c.rationale.startswith("exo edge: the SECOND construction reads C enables A from a passage")
    assert "perturbation=external" in c.rationale and c.section == "§9"


def test_a_pair_whose_second_edge_records_no_relation_stays_a_plain_bridge():
    G = _plain_graph([("a", "b"), ("b", "c")])
    G2 = nx.MultiDiGraph()
    G2.add_edge("a", "c", key="e1")
    cands = gen.ensemble(G, failures=set(), k=10, second_graph=G2)
    assert [(c.relation, c.passage) for c in cands] == [("bridges", {})]
    assert "passage" not in cands[0].to_dict() and cands[0].rationale.startswith("exo bridge:")


def test_each_second_edge_is_checked_against_failure_memory_on_its_own_id():
    G = _plain_graph([("a", "b"), ("b", "c")])
    G2 = nx.MultiDiGraph()
    G2.add_edge("c", "a", key="e1", relation="enables", span="C makes A possible", source_file="doc.md")
    G2.add_edge("a", "c", key="e2", relation="grounds", span="A shows C", source_file="doc.md")
    got = gen.ensemble(G, failures={edge_id("c", "enables", "a")}, k=10, second_graph=G2)
    assert [(c.source, c.relation, c.target) for c in got] == [("a", "grounds", "c")]
    got = gen.ensemble(G, failures={edge_id("c", "grounds", "a")}, k=10, second_graph=G2)  # its reverse
    assert [(c.source, c.relation, c.target) for c in got] == [("c", "enables", "a")]
    got = gen.ensemble(G, failures={edge_id("a", "bridges", "c")}, k=10, second_graph=G2)  # another relation
    assert len(got) == 2


def test_a_rejected_second_edge_is_not_read():
    G = _plain_graph([("a", "b"), ("b", "c")])
    G2 = nx.MultiDiGraph()
    G2.add_edge("a", "c", key="e1", relation="grounds", epistemic_state="rejected", span="A shows C")
    assert gen.ensemble(G, failures=set(), k=10, second_graph=G2) == []


def test_other_mechanisms_carry_no_passage():
    G = _plain_graph([("a", "b"), ("b", "c"), ("c", "d")])
    for c in gen.run_generators(G, mechanism="all", failures=set(), k=10):
        assert "passage" not in c.to_dict()


# --------------------------------------------------------------------------- kg_generate


def test_kg_generate_says_the_passage_is_in_the_sources(eng, src):
    assert _second_reading(eng, src)["dispositions"]["ACCEPTED"] == 3
    out = _ensemble(eng)
    lost = [c for c in out["candidates"] if (c["source"], c["relation"], c["target"]) == ("tcpip", "grounds", "regla")]
    assert len(lost) == 1, out
    assert lost[0]["passage"]["in_source"] is True and lost[0]["passage"]["source_file"] == "doc.md"
    assert normalize_text(lost[0]["passage"]["span"]) == normalize_text(CASE)
    assert out["passages"] == {"in_source": 1, "outside_source": 0}
    assert "not in the configured sources" not in out["note"]


def test_kg_generate_says_when_a_passage_lies_outside_the_sources(eng, src, tmp_path):
    outside = tmp_path / "fuera.md"
    outside.write_text(OUTSIDE, encoding="utf-8")
    span = "TCP/IP frente a OSI muestra la regla de centralización mínima en acción"
    assert _second_reading(eng, src, name="out", span=span, source=outside)["dispositions"]["ACCEPTED"] == 3
    out = _ensemble(eng, "out")
    [c] = out["candidates"]
    assert c["passage"]["in_source"] is False
    assert out["passages"] == {"in_source": 0, "outside_source": 1}
    assert "1 ensemble candidate(s) carry a passage that is not in the configured sources" in out["note"]
    assert "/burgess:kg-build" in out["note"]


def test_a_passage_leaves_through_the_session_scrub_and_restores_on_propose(eng, src):
    span = f"La clave {TOKEN} abre el registro del estándar"
    _second_reading(eng, src, span=span)
    [c] = [c for c in _ensemble(eng)["candidates"] if c.get("passage")]
    assert TOKEN not in c["passage"]["span"] and "⟦" in c["passage"]["span"]
    got = eng.kg_propose({"edges": [{k: c[k] for k in ("source", "target", "relation", "passage")}]})
    assert got["passages"]["recorded"] == [LOST], got
    assert passage_of(_notes(eng))[0] == span                                    # the canon keeps the original


# --------------------------------------------------------------------------- kg_propose


def _propose(eng: KGEngine, passage=None, notes: str = "ensemble §9 [perturbation=external]") -> dict:
    edge = {"source": "tcpip", "target": "regla", "relation": "grounds", "notes": notes}
    if passage is not None:
        edge["passage"] = passage
    return eng.kg_propose({"edges": [edge]})


def _notes(eng: KGEngine) -> str:
    return next(e for e in eng.canon.read_node("tcpip").edges if e.id == LOST).notes


def test_a_passage_that_holds_in_the_sources_opens_the_proposals_notes(eng):
    got = _propose(eng, {"span": CASE, "source_file": "doc.md"})
    assert got["dispositions"]["ACCEPTED"] == 1 and got["passages"] == {"recorded": [LOST], "not_recorded": []}
    notes = _notes(eng)
    assert notes.startswith(PASSAGE_MARK) and notes.endswith(" | ensemble §9 [perturbation=external]")
    assert passage_of(notes) == (CASE, "doc.md")


def test_a_passage_the_sources_do_not_hold_is_not_kept(eng):
    got = _propose(eng, {"span": "TCP/IP frente a OSI muestra la regla en acción", "source_file": "fuera.md"})
    assert got["dispositions"]["ACCEPTED"] == 1                      # the proposal itself is written
    assert got["passages"] == {"recorded": [], "not_recorded": [{"id": LOST, "reason": "passage-not-in-source"}]}
    assert passage_of(_notes(eng)) is None


def test_a_passage_in_an_unnamed_file_records_the_file_that_holds_it(eng):
    _propose(eng, {"span": CASE, "source_file": ""})
    assert passage_of(_notes(eng)) == (CASE, "doc.md")


def test_a_malformed_or_short_passage_is_not_kept(eng):
    assert _propose(eng, {"span": ""})["passages"]["not_recorded"][0]["reason"] == "passage-malformed"
    assert _propose(eng, "a string")["passages"]["not_recorded"][0]["reason"] == "passage-malformed"
    assert _propose(eng, {"span": "Nad"})["passages"]["not_recorded"][0]["reason"] == "passage-too-short"


def test_only_the_engine_opens_notes_with_a_passage(eng):
    forged = with_passage("seed note", "Ganó el que acordó menos", "doc.md")
    got = _propose(eng, notes=forged)
    assert "passages" not in got                                      # no passage was handed in
    assert passage_of(_notes(eng)) is None and _notes(eng) == "seed note"


def test_a_proposal_without_a_passage_is_written_as_before(eng):
    got = _propose(eng)
    assert got["dispositions"]["ACCEPTED"] == 1 and "passages" not in got
    assert _notes(eng) == "ensemble §9 [perturbation=external]"


# --------------------------------------------------------------------------- kg_ground_item and kg_ground


def test_the_grounder_is_shown_the_passage_and_its_excerpt(eng):
    _propose(eng, {"span": CASE, "source_file": "doc.md"})
    got = eng.kg_ground_item(LOST)
    p = got["passage"]
    assert p["in_source"] is True and (p["source_file"], p["section"]) == ("doc.md", 2)
    assert p["title"] == "Interfaz o implementación" and p["span"] == CASE
    assert "Ganó el que acordó menos" in p["excerpt"]
    assert got["shared_context"]["sections"] == []      # the ends' own edges still lie in different sections
    assert got["context"] is None and got["span_in_source"] is None


def test_the_proposal_grounds_on_its_passage(eng):
    _propose(eng, {"span": CASE, "source_file": "doc.md"})
    out = eng.kg_ground(LOST, "grounded", note="the case is offered as evidence for the rule",
                        support_span=eng.kg_ground_item(LOST)["passage"]["span"])
    assert out["ok"], out
    e = next(e for e in eng.canon.read_node("tcpip").edges if e.id == LOST)
    assert (e.epistemic_state.value, e.provenance.value, e.source_file) == ("grounded", "span-present", "doc.md")


def test_a_passage_the_source_no_longer_holds_shows_as_not_in_source(eng, src, vault):
    _propose(eng, {"span": CASE, "source_file": "doc.md"})
    (src / "doc.md").write_text(DOC.replace("Ganó el que acordó menos.", "Ganó."), encoding="utf-8")
    later = KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")   # a later session
    p = later.kg_ground_item(LOST)["passage"]
    assert p["in_source"] is False and "excerpt" not in p


def test_any_other_edge_has_no_passage(eng):
    assert eng.kg_ground_item(edge_id("tcpip", "grounds", "conservador"))["passage"] is None
    _propose(eng)
    assert eng.kg_ground_item(LOST)["passage"] is None


# --------------------------------------------------------------------------- kg_section for a second construction


def test_a_second_constructions_section_comes_with_the_graphs_known_nodes(eng, tmp_path):
    second = tmp_path / "segunda.md"
    second.write_text("## Uno\nTCP/IP frente a OSI ganó al acordar menos.\n\n## Dos\nNada que ver.\n",
                      encoding="utf-8")
    before = set(eng._sections_read)
    got = eng.kg_section("segunda.md", 1, construction="re", source=str(second))
    assert got["ok"] and got["construction"] == "re" and got["of"] == 2
    assert got["text"].startswith("## Uno\nTCP/IP frente a OSI ganó")
    assert "tcpip" in {n["id"] for n in got["known_nodes"]}
    assert eng._sections_read == before                 # the graph's own build never saw this read
    w = eng.kg_write({"edges": [{"source": "tcpip", "target": "regla", "relation": "grounds",
                                 "span": "TCP/IP frente a OSI ganó al acordar menos",
                                 "source_file": "segunda.md"}]},
                     construction="re", source=str(second))
    assert w["dispositions"]["REJECTED"] == 0, w


def test_a_construction_read_never_stands_behind_an_edgeless_record_of_the_graph(eng, src):
    got = eng.kg_section("doc.md", 3, construction="re", source=str(src / "doc.md"))
    assert got["ok"] and got["title"] == "Checklist"
    out = eng.kg_record_edgeless_section("doc.md", 3, "A checklist with no relation between concepts.")
    assert out["ok"] is False, out


def test_construction_and_source_go_together_and_without_leads(eng, src):
    assert eng.kg_section("doc.md", 1, construction="re")["ok"] is False
    assert eng.kg_section("doc.md", 1, source=str(src / "doc.md"))["ok"] is False
    out = eng.kg_section("doc.md", 1, leads=True, construction="re", source=str(src / "doc.md"))
    assert out["ok"] is False and "leads" in out["error"]


# --------------------------------------------------------------------------- the field case, end to end


def test_a_relation_a_re_reading_finds_reaches_the_grounder_with_its_passage(eng, src):
    """The 2026-11-16 path on 0.19.0: the second reading builds from kg_section, the ensemble step keeps its
    relation and passage, kg_propose records it, and the grounder judges it on the text."""
    s = eng.kg_section("doc.md", 2, construction="re", source=str(src / "doc.md"))
    assert {"tcpip", "conservador"} <= {n["id"] for n in s["known_nodes"]}
    assert _second_reading(eng, src)["dispositions"]["REJECTED"] == 0
    [c] = [c for c in _ensemble(eng)["candidates"] if c["relation"] == "grounds"]
    edge = {k: c[k] for k in ("source", "target", "relation", "passage")}
    edge["notes"] = "ensemble §9 [perturbation=external]"
    assert eng.kg_propose({"edges": [edge]})["passages"]["recorded"] == [LOST]
    item = eng.kg_ground_item(LOST)
    assert item["passage"]["in_source"] and CASE.split("\n")[1] in item["passage"]["excerpt"]
    assert eng.kg_ground(LOST, "grounded", support_span=item["passage"]["span"])["ok"]


# --------------------------------------------------------------------------- the notes segment


def test_the_passage_segment_round_trips_a_span_with_separators_and_quotes():
    span = 'Una tabla | con «comillas» y "dobles"'
    notes = with_passage("idea | lead: none", span, "doc.md")
    assert notes.startswith(PASSAGE_MARK) and passage_of(notes) == (span, "doc.md")
    assert without_passage(notes) == "idea | lead: none"
    assert with_passage(notes, "otro", "b.md").count(PASSAGE_MARK) == 1
    assert passage_of("idea | passage: {\"span\": \"x\"}") is None          # only an opening segment counts
    assert passage_of("passage: not json") is None and without_passage("passage: not json") == "passage: not json"


# --------------------------------------------------------------------------- the texts that wire it


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_perturb_command_reads_sections_with_the_graphs_ids_and_carries_passages():
    flat = _flat(PERTURB)
    assert ('mcp__plugin_burgess_burgess__kg_section(source_file="<the basename of $SECOND_SOURCE>", '
            'section=<n>, construction="$CONSTRUCTION", source="$SECOND_SOURCE")') in flat
    assert "copy each candidate's `passage` onto its edge unchanged" in flat
    assert "`passages`" in flat and "outside your sources" in flat
    assert "Read the whole file" not in flat and "`Read` the whole file" not in flat


def test_the_generator_passes_a_passage_on_unchanged():
    flat = _flat(GENERATOR)
    assert "An `ensemble` edge candidate may carry `passage`" in flat
    assert "Copy it onto the edge unchanged, as `\"passage\"`" in flat


def test_the_grounder_judges_a_proposal_on_its_passage():
    flat = _flat(GROUNDER)
    assert "**A proposal with a `passage`** (0.19.0)." in flat
    assert "ground it with that span as `support_span`" in flat
    assert "`in_source` false" in flat


def test_the_batch_prompt_and_the_references_name_the_passage():
    flat = _flat(GROUND_CMD)
    assert "shared_context, the source sections where both its ends are discussed" in flat   # 0.18.0 stands
    assert "and, for a proposal from /burgess:kg-perturb, passage" in flat
    tools = _flat(TOOLS)
    assert "`passage` — for a proposal from" in tools
    assert "`construction` + `source`" in tools


def test_the_extractor_declares_a_known_id_in_a_second_construction():
    flat = _flat(EXTRACTOR)
    assert "**Building a second construction (`/kg-perturb`, 0.19.0).**" in flat
    assert "declare that node in `nodes[]`" in flat
