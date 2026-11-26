"""0.27.0: a claim whose passage left its file is judged again, moved to the passage that states it, or obsolete.

The case the 0.26.0 entry of DECISIONS left for a separate change. A claim's span is the sentence of the notes it
was extracted from; when the user rewrote or deleted that sentence:
- a grounded claim kept its verdict, resting on text that was gone. The R3 advisory listed it, and the command's
  Stage 0b had a grounder write it again with `kg_write` and the new sentence, which the boundary quarantines as a
  claim already judged (`collapses-into-known-verdict`), so its span never moved;
- an unverified one was rejected by its grounder as not in the source, permanent negative memory: had the
  sentence come back, the claim could never have;
- `obsolete` was accepted on any edge, and no agent gave it.

Now `kg_ground_plan` queues every live claim whose file no longer holds its span (`span_gone`), `kg_ground_item`
gives that file's sections as they read now, and `kg_ground` takes one of two answers: grounded on the passage
that states the claim now, which moves its span there (the old one kept as a `span was:` segment), or obsolete.
Such a claim is never rejected, `obsolete` is refused anywhere else, an obsolete claim comes back when its
sentence does or a build reads new text of its file that bears on it, and a claim whose file is not among the
sources is not judged at all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.buildplan import read_record, section_digest, section_units
from kg_engine.evidence import spans_was
from kg_engine.model import EpistemicState, edge_id
from kg_engine.server import KGEngine
from kg_engine.sources import plan_sections

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
BUILD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

FILE = "Fábricas de software.md"
OTHER = "Otras notas.md"
OLD = "La fábrica funciona cuando verifica cada cambio"
NEW = "Una fábrica de software solo funciona si verifica cada cambio que entra"
SECOND = "El oráculo decide si una salida es correcta"
DOC = (f"# Fábricas\n\n## Argumento\n{OLD}.\n\n{SECOND}.\n\n"
       "## Vocabulario\n- **Arnés:** el entorno que ejecuta al agente.\n")
NODES = [{"id": "fabrica", "label": "fábrica", "node_type": "claim", "body": "La fábrica de software."},
         {"id": "verificacion", "label": "verificación", "node_type": "operation", "body": "Verificar cada cambio."},
         {"id": "oraculo", "label": "oráculo", "node_type": "primitive", "body": "Lo que decide."},
         {"id": "salida-correcta", "label": "salida correcta", "node_type": "claim", "body": "Una salida válida."}]
CLAIM = edge_id("fabrica", "grounds", "verificacion")
ORACLE = edge_id("oraculo", "grounds", "salida-correcta")
EDGES = [{"source": "fabrica", "target": "verificacion", "relation": "grounds", "span": OLD, "source_file": FILE},
         {"source": "oraculo", "target": "salida-correcta", "relation": "grounds", "span": SECOND,
          "source_file": FILE}]


@pytest.fixture
def rig(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notas"
    notes.mkdir()
    (notes / FILE).write_text(DOC, encoding="utf-8")
    eng = KGEngine(project, source_path=notes, pack_path=PACK)
    _section(eng, "Argumento")
    out = eng.kg_write({"nodes": NODES, "edges": EDGES})
    assert out["dispositions"]["ACCEPTED"] == 6, out
    return eng, notes


def _section(eng: KGEngine, title: str, name: str = FILE) -> int:
    """Read a section as a /kg-build extractor does (kg_section), and return its number."""
    text = (Path(eng.source_path) / name).read_text(encoding="utf-8")
    index = next(s.index for s in plan_sections(text)[1] if s.title == title)
    assert eng.kg_section(name, index)["ok"]
    return index


def _edit(notes: Path, old: str, new: str, name: str = FILE) -> None:
    path = notes / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _edge(eng: KGEngine, eid: str):
    return next(e for e in eng.canon.all_edges() if e.id == eid)


def _rows(plan: dict) -> "list[dict]":
    return [item for batch in plan["batches"] for item in batch]


def _row(plan: dict, eid: str) -> "dict | None":
    return next((item for item in _rows(plan) if item["id"] == eid), None)


# ---- which claims are judged again ------------------------------------------------------------------------------

def test_a_gone_span_is_told_from_one_that_holds_and_from_a_missing_file(rig):
    eng, notes = rig
    vs = eng.verify_set()
    assert eng._span_gone(_edge(eng, CLAIM), vs) is None
    _edit(notes, f"{OLD}.", f"{NEW}.")
    vs = eng.verify_set()
    assert eng._span_gone(_edge(eng, CLAIM), vs) == "gone"
    assert eng._span_gone(_edge(eng, ORACLE), vs) is None
    moved = _edge(eng, CLAIM)
    moved.source_file = "Borrado.md"
    assert eng._span_gone(moved, vs) == "unplaced" and eng._own_file(moved, vs) == ""
    unnamed = _edge(eng, CLAIM)
    unnamed.source_file = ""
    assert eng._own_file(unnamed, vs) == FILE and eng._span_gone(unnamed, vs) == "gone"   # one file: its own
    (notes / OTHER).write_text("Otra cosa.\n", encoding="utf-8")
    vs = eng.verify_set()
    assert eng._own_file(unnamed, vs) == "" and eng._span_gone(unnamed, vs) == "unplaced"   # several: none


def test_the_plan_queues_a_grounded_claim_whose_sentence_is_gone_after_the_new_items(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{NEW}.")
    plan = eng.kg_ground_plan("", "")
    assert _rows(plan) == [{"id": ORACLE, "kind": "edge"}, {"id": CLAIM, "kind": "edge", "span_gone": True}]
    assert plan["queue"]["spans_gone"] == 1 and plan["queue"]["edges"] == 1
    assert plan["files_missing"] is None
    assert eng.kg_ground_plan("verificacion", "")["queue"]["spans_gone"] == 1   # in the focus like any item
    assert eng.kg_ground_plan("oraculo", "")["queue"]["spans_gone"] == 0


def test_an_unverified_claim_whose_sentence_is_gone_is_marked_where_it_was(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{NEW}.")
    plan = eng.kg_ground_plan("", "")
    assert _row(plan, CLAIM) == {"id": CLAIM, "kind": "edge", "span_gone": True}
    assert plan["queue"]["edges"] == 2 and plan["queue"]["spans_gone"] == 1


def test_the_item_gives_the_file_as_it_reads_now(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{NEW}.")
    item = eng.kg_ground_item(CLAIM)
    assert item["span_in_source"] is False and item["context"] is None
    gone = item["span_gone"]
    assert gone["span"] == OLD and gone["source_file"] == FILE
    assert NEW in gone["sections"][0]["excerpt"] and gone["sections"][0]["title"] == "Argumento"
    assert {"fabrica", "funciona", "verifica", "cambio"} <= set(gone["sections"][0]["matched"])
    assert gone["elsewhere"] == [] and gone["also_present"] == []
    assert "obsolete" in gone["rule"] and "Never reject it" in gone["rule"]
    assert eng.kg_ground_item(ORACLE)["span_gone"] is None


def test_the_item_names_a_file_that_holds_the_old_span_word_for_word(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.\n\n", "")
    (notes / OTHER).write_text(f"## Movido\n{OLD}, como decía.\n", encoding="utf-8")
    gone = eng.kg_ground_item(CLAIM)["span_gone"]
    assert gone["elsewhere"] == [OTHER]
    out = eng.kg_ground(CLAIM, "grounded", support_span=OLD, note="moved to the other notes")
    assert out["ok"] and out["reanchored"] == {"source_file": OTHER, "from_file": FILE}, out
    assert _edge(eng, CLAIM).source_file == OTHER


def test_the_item_shows_the_passages_it_was_also_written_with(rig):
    eng, notes = rig
    also = "Verificar cada cambio es lo que hace funcionar la fábrica"
    _edit(notes, "- **Arnés:**", f"- {also}.\n- **Arnés:**")
    _section(eng, "Vocabulario")
    eng.kg_write({"edges": [dict(EDGES[0], span=also)]})                   # the same claim, from §2
    _edit(notes, f"{OLD}.\n\n", "")
    gone = eng.kg_ground_item(CLAIM)["span_gone"]
    assert [p["span"] for p in gone["also_present"]] == [also]
    assert gone["also_present"][0]["context"]["title"] == "Vocabulario"


# ---- the two answers --------------------------------------------------------------------------------------------

def test_grounded_on_the_new_passage_moves_the_span_and_keeps_the_old_one(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    first = _edge(eng, CLAIM).verdict_at
    _edit(notes, f"{OLD}.", f"{NEW}.")
    out = eng.kg_ground(CLAIM, "grounded", support_span=NEW, note="§1 now says it in other words")
    assert out["ok"] and out["from"] == "grounded" and out["reanchored"] == {"source_file": FILE, "from_file": FILE}
    assert out["support_source"]["usable"] is True
    edge = _edge(eng, CLAIM)
    assert edge.span == NEW and edge.source_file == FILE and edge.epistemic_state == EpistemicState.GROUNDED
    assert edge.verdict_at == first                                         # a re-confirmation keeps the time
    assert spans_was(edge.notes) == [(OLD, FILE)]
    assert "§1 now says it in other words" in edge.notes
    assert _row(eng.kg_ground_plan("", ""), CLAIM) is None                  # it holds again
    report = eng.reconciler.scan(full_sweep=True)
    assert report.requarantined == [] and _edge(eng, CLAIM).epistemic_state == EpistemicState.GROUNDED


def test_an_unverified_claim_grounded_on_the_new_passage_is_stamped(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{NEW}.")
    out = eng.kg_ground(CLAIM, "grounded", support_span=NEW, note="§1")
    assert out["ok"] and out["from"] == "unverified" and out["reanchored"]["source_file"] == FILE
    edge = _edge(eng, CLAIM)
    assert edge.verdict_at and edge.span == NEW


def test_a_gone_claim_is_never_rejected_and_needs_a_passage(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{NEW}.")
    for state in ("grounded", "unverified"):
        if state == "unverified":
            eng.kg_write({"edges": [dict(EDGES[1])]})          # ORACLE stays unverified; use it below
        target = CLAIM if state == "grounded" else ORACLE
        if state == "unverified":
            _edit(notes, f"{SECOND}.", "El oráculo cambió de opinión.")
        out = eng.kg_ground(target, "rejected", note="no-support: span not in source")
        assert out["error"] == "span-gone-not-rejected", out
    assert eng.kg_ground(CLAIM, "grounded", note="again")["error"] == "span-gone-needs-passage"
    assert eng.kg_ground(CLAIM, "grounded", support_span="una frase que no existe en ninguna parte")["error"] == \
        "support-span-not-in-source"
    assert eng.kg_ground(CLAIM, "grounded", support_span="Una")["error"] == "support-span-too-short"
    edge = _edge(eng, CLAIM)
    assert edge.span == OLD and edge.epistemic_state == EpistemicState.GROUNDED   # nothing changed


def test_the_passage_must_lie_in_a_file_the_graph_is_built_from(rig, tmp_path):
    eng, notes = rig
    _edit(notes, f"{OLD}.\n\n", "")
    paper = tmp_path / "paper.md"
    paper.write_text(f"## Results\n{NEW}.\n", encoding="utf-8")
    assert eng.kg_source_add(path=str(paper), level=1, role="primary")["ok"]   # evidence only, not built
    out = eng.kg_ground(CLAIM, "grounded", support_span=NEW)
    assert out["error"] == "passage-not-in-built-sources", out


def test_the_moved_claim_must_rest_on_usable_support(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{NEW}.")
    assert eng.kg_source_policy(required_level=1)["ok"]                    # the notes (level 4) support nothing
    out = eng.kg_ground(CLAIM, "grounded", support_span=NEW)
    assert out["error"] == "support-not-usable", out
    plan = eng.kg_ground_plan("", "")
    assert _row(plan, CLAIM) is None and plan["blocked"]["items"] >= 1    # nothing usable: left out, counted


def test_obsolete_says_the_passage_left_its_file_and_nothing_else(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "obsolete")["error"] == "obsolete-span-still-present"
    assert eng.kg_ground(ORACLE, "rejected", note="vague: t")["ok"]
    _edit(notes, f"{SECOND}.", "Nada.")
    assert eng.kg_ground(ORACLE, "obsolete")["error"] == "obsolete-not-for-negative-memory"
    eng.kg_propose({"edges": [{"source": "fabrica", "target": "oraculo", "relation": "bridges"}]})
    assert eng.kg_ground(edge_id("fabrica", "bridges", "oraculo"), "obsolete")["error"] == "obsolete-needs-a-span"
    before = eng.kg_context()["falsification_counters"]["failed_or_rejected_edges"]
    _edit(notes, f"{OLD}.", f"{NEW}.")
    out = eng.kg_ground(CLAIM, "obsolete", note="§1 now speaks of what enters, not of each change")
    assert out["ok"] and out["to"] == "obsolete", out
    assert eng.kg_context()["falsification_counters"]["failed_or_rejected_edges"] == before   # not a refutation
    assert eng.kg_metrics()["edges_by_epistemic_state"]["obsolete"] == 1
    assert _row(eng.kg_ground_plan("", ""), CLAIM) is None                # nothing new: it waits


def test_a_rejected_claim_judged_again_may_stay_rejected_or_move(rig):
    """A rejected claim a source changed under (0.22.4) may have lost its passage: it stays negative memory unless
    a passage states it, and then it moves like any other."""
    eng, notes = rig
    assert eng.kg_ground(ORACLE, "rejected", note="vague: t")["ok"]
    _edit(notes, f"{SECOND}.", "Un oráculo decide si cada salida es correcta o no.")
    item = eng.kg_ground_item(ORACLE)
    assert item["span_gone"] and item["span_gone"]["sections"], item["span_gone"]
    assert eng.kg_ground(ORACLE, "rejected", note="re-read: still vague")["ok"]          # stays negative memory
    assert eng.kg_ground(ORACLE, "obsolete")["error"] == "obsolete-not-for-negative-memory"
    out = eng.kg_ground(ORACLE, "grounded", support_span="Un oráculo decide si cada salida es correcta o no")
    assert out["ok"] and out["from"] == "rejected" and out["reanchored"]["source_file"] == FILE, out
    assert eng.kg_ground(ORACLE, "failed", note="refuted for the test")["ok"]
    _edit(notes, "Un oráculo decide si cada salida es correcta o no.", "Nada.")
    assert eng.kg_ground_item(ORACLE)["span_gone"] is None                               # a refutation stands


# ---- an obsolete claim comes back ------------------------------------------------------------------------------

def test_an_obsolete_claim_comes_back_when_its_sentence_does(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{NEW}.")
    assert eng.kg_ground(CLAIM, "obsolete", note="rewritten")["ok"]
    _edit(notes, f"{NEW}.", f"{OLD}.")                                    # the edit undone
    plan = eng.kg_ground_plan("", "")
    assert _row(plan, CLAIM) == {"id": CLAIM, "kind": "edge", "reexamine": True}
    assert plan["queue"]["obsolete_returned"] == 1
    item = eng.kg_ground_item(CLAIM)
    assert item["span_in_source"] is True and item["span_gone"] is None and item["context"]
    assert eng.kg_ground(CLAIM, "obsolete")["error"] == "obsolete-span-still-present"
    out = eng.kg_ground(CLAIM, "grounded", note="the sentence is back")
    assert out["ok"] and out["from"] == "obsolete" and "reanchored" not in out
    assert _row(eng.kg_ground_plan("", ""), CLAIM) is None


def test_an_obsolete_claim_comes_back_when_a_build_reads_new_text_about_it(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.\n\n", "")
    assert eng.kg_ground(CLAIM, "obsolete", note="the sentence was removed")["ok"]
    # new text in its file that shares none of its words: a build reads it, and nothing comes back
    _edit(notes, f"{SECOND}.", f"{SECOND}.\n\nEl arnés corre en un contenedor aislado.")
    index = _section(eng, "Argumento")
    assert eng.kg_record_edgeless_section(FILE, index, "nothing new to write")["ok"]
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 0
    # new text that bears on it, not yet read by a build: nothing yet
    _edit(notes, "El arnés corre", "La fábrica verifica cada cambio antes de integrarlo. El arnés corre")
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 0
    index = _section(eng, "Argumento")
    assert eng.kg_record_edgeless_section(FILE, index, "the claim it states is already judged")["ok"]
    plan = eng.kg_ground_plan("", "")
    assert _row(plan, CLAIM) == {"id": CLAIM, "kind": "edge", "reexamine": True}
    assert "verifica cada cambio antes de integrarlo" in eng.kg_ground_item(CLAIM)["span_gone"]["sections"][0]["excerpt"]
    # any verdict answers it, obsolete again included
    assert eng.kg_ground(CLAIM, "obsolete", note="read again: it says when, not that it works")["ok"]
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 0


def test_a_read_recorded_by_0_26_0_is_ordered_by_its_time(rig):
    """A read record from 0.26.0 carries no audit mark: it counts when stamped after the verdict's second."""
    eng, notes = rig
    _edit(notes, f"{OLD}.", "La fábrica verifica cada cambio antes de integrarlo.")
    assert eng.kg_ground(CLAIM, "obsolete", note="rewritten")["ok"]
    text = (notes / FILE).read_text(encoding="utf-8")
    sec = next(s for s in plan_sections(text)[1] if s.title == "Argumento")
    at = _edge(eng, CLAIM).verdict_at
    ledger = eng.canon.root / ".kg-read-sections.jsonl"
    with open(ledger, "a", encoding="utf-8") as f:                         # the same second: not after it
        f.write(read_record(FILE, sec.index, sec.title, section_digest(sec.text), section_units(sec.text), at,
                            "write") + "\n")
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 0
    ledger.write_text("".join(line + "\n" for line in ledger.read_text(encoding="utf-8").splitlines()
                              if f'"at": "{at}"' not in line), encoding="utf-8")
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(read_record(FILE, sec.index, sec.title, section_digest(sec.text), section_units(sec.text),
                            "2099-01-01T00:00:00+00:00", "write") + "\n")
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 1


def test_a_baseline_brings_no_obsolete_claim_back(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", "La fábrica verifica cada cambio antes de integrarlo.")
    assert eng.kg_ground(CLAIM, "obsolete", note="rewritten")["ok"]
    (eng.canon.root / ".kg-read-sections.jsonl").unlink()                 # the ledger lost: the plan lays a baseline
    assert eng.kg_build_plan("", "").get("baseline")
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 0


# ---- what is not judged -----------------------------------------------------------------------------------------

def test_a_claim_whose_file_is_missing_is_named_not_judged(rig):
    eng, notes = rig
    (notes / OTHER).write_text(f"## Otra\n{NEW}.\n\nEl arnés corre aislado.\n", encoding="utf-8")
    _section(eng, "Otra", OTHER)
    eng.kg_write({"edges": [{"source": "fabrica", "target": "oraculo", "relation": "enables", "span": NEW,
                             "source_file": OTHER},
                            {"source": "oraculo", "target": "verificacion", "relation": "grounds",
                             "span": "El arnés corre aislado", "source_file": OTHER}]})
    moved = edge_id("fabrica", "enables", "oraculo")
    assert eng.kg_ground(moved, "grounded", note="§Otra")["ok"]
    (notes / OTHER).unlink()                                               # moved away, renamed, another folder
    plan = eng.kg_ground_plan("", "")
    assert plan["files_missing"]["files"] == [{"file": OTHER, "claims": 2}]
    assert (plan["files_missing"]["grounded"], plan["files_missing"]["unverified"]) == (1, 1)
    assert _row(plan, moved) is None and _row(plan, edge_id("oraculo", "grounds", "verificacion")) is None
    assert eng.kg_ground_plan("fabrica", "")["files_missing"]["files"] == [{"file": OTHER, "claims": 2}]
    for verdict in ("grounded", "rejected", "obsolete"):
        out = eng.kg_ground(moved, verdict, support_span=OLD if verdict == "grounded" else "")
        assert out["error"] == "span-file-not-among-sources" and out["source_file"] == OTHER, out
    assert eng.kg_ground(moved, "failed", note="refuted for the test")["ok"]   # a refutation stays open


def test_the_build_plan_counts_only_the_claims_whose_file_it_plans(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{NEW}.")
    assert eng.kg_build_plan("", "")["spans_gone"] == {"grounded": 1, "unverified": 0, "grounded_ids": [CLAIM]}
    edge = _edge(eng, CLAIM)
    owner = eng.canon.read_node("fabrica")
    for e in owner.edges:
        if e.id == CLAIM:
            e.source_file = "source.md"                                    # a legacy name no source has
    eng.canon.write_one(owner)
    assert "spans_gone" not in eng.kg_build_plan("", "")
    assert edge.span == OLD


# ---- the rest of the verdict path ------------------------------------------------------------------------------

def test_kg_write_still_cannot_move_a_judged_claims_span(rig):
    """Why the move is kg_ground's: a re-emit of a judged claim is quarantined, as it always was (review-C1)."""
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{NEW}.")
    _section(eng, "Argumento")
    out = eng.kg_write({"edges": [dict(EDGES[0], span=NEW)]})
    assert [d["reason"] for d in out["details"] if d["kind"] == "edge"] == ["collapses-into-known-verdict"]
    assert _edge(eng, CLAIM).span == OLD


def test_a_move_found_after_the_grounders_own_search_is_held_and_confirmed(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{NEW}.")
    assert eng.kg_ground_item(CLAIM, terms="fábrica verifica cambio")["ok"]
    held = eng.kg_ground(CLAIM, "grounded", support_span=NEW, note="found with my own words")
    assert held["held"] and held["needs_confirmation"], held
    assert _edge(eng, CLAIM).span == OLD                                   # nothing moved yet
    plan = eng.kg_ground_plan("", "")
    assert plan["queue"]["confirm"] == 1 and plan["queue"]["spans_gone"] == 0
    assert {"id": CLAIM, "kind": "edge", "confirm": True} in _rows(plan)
    out = eng.kg_ground(CLAIM, "grounded", support_span=NEW, note="a second grounder confirms the passage")
    assert out["ok"] and out["confirmed"] and out["reanchored"]["source_file"] == FILE, out
    assert _edge(eng, CLAIM).span == NEW


# ---- the texts --------------------------------------------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_grounder_contract_has_the_two_answers_and_no_rejection():
    rule = _flat(GROUNDER.split("## A claim whose passage left its file (0.27.0)", 1)[1].split("\n## ", 1)[0])
    assert "Ask one question: **does the text now state this claim?**" in rule
    assert 'verdict="grounded", support_span="<the passage, verbatim from an excerpt>"' in rule
    assert 'verdict="obsolete", note=' in rule
    assert "**Never reject it for this**, and never record it unsupported." in rule
    step = _flat(GROUNDER.split("a. **Span is real.**", 1)[1].split("b. **Span actually asserts", 1)[0])
    assert "judge it by **A claim whose passage left its file**" in step
    assert '→ `rejected`, note `"no-support: span not in source"`' not in step
    tools = next(line for line in GROUNDER.splitlines() if line.startswith("tools:"))
    for gone in ("Read", "Grep", "kg_write"):
        assert gone not in tools.replace("kg_ground_plan", "").replace("kg_ground_item", ""), gone
    assert "mcp__plugin_burgess_burgess__kg_ground," in tools


def test_the_command_routes_nothing_and_tells_the_user():
    stage = _flat(CMD.split("## Stage 0b", 1)[1].split("## Stage 0c", 1)[0])
    assert '**Do not route them yourself.** The plan already holds every grounded or unverified claim' in stage
    assert "`files_missing`" in stage and "`queue.obsolete_returned`" in stage
    assert "kg_write({" not in stage and "`collapses-into-known-verdict`" in stage
    brief = _flat(CMD.split('subagent_type: "kg-grounder"', 1)[1].split('"""\n)', 1)[0])
    assert "- e_summer-menu__grounds__cold-brew-launch (edge, span gone)" in brief
    assert "An item marked span gone has lost its passage" in brief
    assert "- rejected: the span does not state the relation" in brief
    assert "- obsolete: only for an item whose passage is gone" in brief
    assert "`<id> (edge, span gone)`" in _flat(CMD)
    report = _flat(CMD.split("## Stage 3", 1)[1].split("\n## ", 1)[0])
    assert "`failed` and `obsolete`" in report and "obsolete +o" in report


def test_the_build_command_and_the_reference_say_kg_ground_judges_them():
    assert "The next `/burgess:kg-ground` judges each one again (0.27.0)" in _flat(BUILD)
    flat = _flat(TOOLS)
    for field in ("`span-gone-not-rejected`", "`span-gone-needs-passage`", "`obsolete-span-still-present`",
                  "`passage-not-in-built-sources`", "`span-file-not-among-sources`", "**`queue.spans_gone` (0.27.0):**",
                  "**`queue.obsolete_returned` (0.27.0", "**`files_missing` (0.27.0):**", "- `span_gone` (0.27.0"):
        assert field in flat, field
