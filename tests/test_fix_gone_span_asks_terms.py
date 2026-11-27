"""0.28.3: a claim whose sentence was rewritten in other words is looked for before it is marked obsolete.

The limit the 0.27.0 live test named and the 0.27.0 PR left out ("Not in this PR"). A claim whose span left its file
comes to its grounder with `span_gone.sections`: the sections of its file that share the most of the claim's own
words (its two ends and its old span). A sentence the user rewrote in other words can share none of them, so the
passage that states the claim now sits in a section the view leaves out, and the grounder, seeing nothing, marks the
claim obsolete. The grounder could have asked for passages with words of its own (`kg_ground_item` with `terms`,
0.24.6), but its contract allowed that only across languages, and when the request was left to its choice it was
never made (0.28.2, twice in a forced run).

Now:
- its view also shows `new_text`: the paragraphs of its file written or rewritten since the claim was last judged,
  whatever their words, from the ledger of sections read (0.26.0). In the live test of 2026-11-27 the grounder asked
  as the rule below makes it, with words that shared one with the rewrite, and marked the claim obsolete while the
  notes still stated it: a request by words alone does not close the case;
- such a claim's request ranks the sections of its own file, whatever the file's level, as its view does
  (`requested_context` with `files`): that file is where the claim can move to, and the usable sections of every
  source are not (an external copy is evidence, not text the graph is built from);
- `kg_ground` refuses `obsolete` with `terms-not-asked` until one request is on record against the item and the
  sources as they are, except for a claim whose move is held for a second grounder, who declines it with
  `obsolete` and may not search;
- a move found after the request is held for a second grounder, as any support found after one is (0.24.6), and
  the confirm view tells that grounder to decline it with `obsolete`, not to record it unsupported;
- a held move of an obsolete claim that came back is queued for that second grounder: through 0.28.2 the plan
  queued holds only on unverified and grounded items, and left an obsolete claim's out of every plan.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.model import EpistemicState, edge_id
from kg_engine.server import KGEngine
from kg_engine.sources import plan_sections

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"

FILE = "Fábricas de software.md"
OLD = "La fábrica funciona cuando verifica cada cambio"
# the same claim in other words: no word in common with the claim's ends or its old span
REWRITE = "Una línea de producción de código solo marcha si comprueba toda modificación que entra"
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
WORDS = "línea producción código comprueba modificación"     # what a grounder asks with: the claim said another way


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


def _section(eng: KGEngine, title: str) -> int:
    """Read a section as a /kg-build extractor does (kg_section), and return its number."""
    text = (Path(eng.source_path) / FILE).read_text(encoding="utf-8")
    index = next(s.index for s in plan_sections(text)[1] if s.title == title)
    assert eng.kg_section(FILE, index)["ok"]
    return index


def _edit(notes: Path, old: str, new: str) -> None:
    path = notes / FILE
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _edge(eng: KGEngine, eid: str):
    return next(e for e in eng.canon.all_edges() if e.id == eid)


def _rows(plan: dict) -> "list[dict]":
    return [item for batch in plan["batches"] for item in batch]


# ---- the request finds what the view leaves out ----------------------------------------------------------------

def test_a_rewrite_in_other_words_is_found_by_the_request_and_not_by_the_ranked_sections(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    gone = eng.kg_ground_item(CLAIM)["span_gone"]
    assert not any(REWRITE in s["excerpt"] for s in gone["sections"]), gone   # the claim's words reach nothing
    assert "ask once with terms" in gone["rule"] and "obsolete" in gone["rule"]
    asked = eng.kg_ground_item(CLAIM, terms=WORDS)
    ctx = asked["requested_context"]
    assert ctx["files"] == [FILE] and ctx["repeated"] is False, ctx
    assert REWRITE in ctx["sections"][0]["excerpt"] and ctx["sections"][0]["title"] == "Argumento"
    assert ctx["terms"] == ["linea", "produccion", "codigo", "comprueba", "modificacion"]   # folded, as any terms
    assert set(ctx["terms"]) <= set(ctx["sections"][0]["matched"])
    # an item whose span holds asks the usable sections of every source, as before
    other = eng.kg_ground_item(ORACLE, terms="oráculo salida correcta")["requested_context"]
    assert "files" not in other and other["sections"]


def test_the_request_reads_the_claims_file_whatever_its_level(rig):
    """Under a policy the notes do not meet, the usable sections are none: the claim's own file is still where it
    is stated now, and its support is checked when it is grounded (`_reanchor`)."""
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    assert eng.kg_source_policy(required_level=1)["ok"]
    ctx = eng.kg_ground_item(CLAIM, terms=WORDS)["requested_context"]
    assert ctx["files"] == [FILE] and REWRITE in ctx["sections"][0]["excerpt"], ctx
    assert ctx["sections"][0]["source"]["usable"] is False
    assert eng.kg_ground_item(ORACLE, terms="oráculo salida correcta")["requested_context"]["sections"] == []


# ---- obsolete waits for the request ----------------------------------------------------------------------------

def test_obsolete_is_refused_until_the_grounder_has_asked(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    out = eng.kg_ground(CLAIM, "obsolete", note="nothing states it")
    assert out["ok"] is False and out["error"] == "terms-not-asked", out
    assert out["source_file"] == FILE and out["max_terms"] == KGEngine.GROUND_TERMS_MAX
    assert 'kg_ground_item(target_id, "edge", terms="…")' in out["hint"]
    edge = _edge(eng, CLAIM)
    assert edge.epistemic_state == EpistemicState.GROUNDED and edge.span == OLD        # nothing changed
    assert eng.kg_ground_item(CLAIM, terms="tortuga marina migración")["requested_context"]["sections"] == []
    out = eng.kg_ground(CLAIM, "obsolete", note="asked with my own words too: nothing states it")
    assert out["ok"] and out["to"] == "obsolete", out


def test_a_request_made_before_the_file_changed_again_does_not_count(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    assert eng.kg_ground_item(CLAIM, terms=WORDS)["requested_context"]["sections"]
    _edit(notes, f"{SECOND}.", "El oráculo cambió de sitio.")                         # another edit: a new look
    assert eng.kg_ground(CLAIM, "obsolete")["error"] == "terms-not-asked"
    again = eng.kg_ground_item(CLAIM, terms=WORDS)["requested_context"]
    assert again["repeated"] is False
    assert eng.kg_ground(CLAIM, "obsolete", note="t")["ok"]


def test_the_other_verdicts_need_no_request(rig):
    """Only `obsolete` waits: a move on a passage the view shows, a rejection of a rejected claim judged again, and a
    refutation are what they were."""
    eng, notes = rig
    assert eng.kg_ground(ORACLE, "rejected", note="vague: t")["ok"]
    _edit(notes, f"{SECOND}.", "Un oráculo decide si cada salida es correcta o no.")
    assert eng.kg_ground(ORACLE, "rejected", note="re-read: still vague")["ok"]
    _edit(notes, f"{OLD}.", "La fábrica funciona si verifica cada cambio.")
    out = eng.kg_ground(CLAIM, "grounded", support_span="La fábrica funciona si verifica cada cambio")
    assert out["ok"] and out["reanchored"]["source_file"] == FILE and "held" not in out, out


# ---- a move found after the request is held ----------------------------------------------------------------------

def test_a_held_move_is_confirmed_by_a_second_grounder(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    eng.kg_ground_item(CLAIM, terms=WORDS)
    held = eng.kg_ground(CLAIM, "grounded", support_span=REWRITE, note="found with my own words")
    assert held["held"] and held["needs_confirmation"] and held["terms"], held
    assert _edge(eng, CLAIM).span == OLD                                                # nothing moved yet
    plan = eng.kg_ground_plan("", "")
    assert {"id": CLAIM, "kind": "edge", "confirm": True} in _rows(plan)
    assert plan["queue"]["confirm"] == 1 and plan["queue"]["spans_gone"] == 0
    item = eng.kg_ground_item(CLAIM)
    assert item["span_gone"] and item["confirm"]["span"] == REWRITE
    assert "mark it obsolete" in item["confirm"]["rule"] and "record it" not in item["confirm"]["rule"]
    assert eng.kg_ground_item(CLAIM, terms=WORDS)["error"] == "terms-not-allowed"
    out = eng.kg_ground(CLAIM, "grounded", support_span=REWRITE, note="the rewrite states it")
    assert out["ok"] and out["confirmed"] and out["reanchored"] == {"source_file": FILE, "from_file": FILE}, out
    edge = _edge(eng, CLAIM)
    assert edge.span == REWRITE and edge.epistemic_state == EpistemicState.GROUNDED
    assert "confirmed by a second grounder" in edge.notes


def test_a_second_grounder_declines_a_held_move_with_obsolete_without_asking(rig):
    """It may not search, so the request it would owe is not asked of it, even once the sources have changed."""
    eng, notes = rig
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    eng.kg_ground_item(CLAIM, terms=WORDS)
    assert eng.kg_ground(CLAIM, "grounded", support_span=REWRITE, note="found with my own words")["held"]
    _edit(notes, f"{SECOND}.", "El oráculo cambió de sitio.")                         # the first request is stale
    out = eng.kg_ground(CLAIM, "obsolete", note="decline: the passage says how code is made, not that it verifies")
    assert out["ok"] and out["to"] == "obsolete", out
    plan = eng.kg_ground_plan("", "")
    assert plan["queue"]["confirm"] == 0 and CLAIM not in {r["id"] for r in _rows(plan)}   # the hold is answered


def test_a_held_move_of_an_obsolete_claim_comes_to_a_second_grounder(rig):
    eng, notes = rig
    _edit(notes, f"{OLD}.\n\n", "")
    eng.kg_ground_item(CLAIM, terms=WORDS)
    assert eng.kg_ground(CLAIM, "obsolete", note="the sentence was removed")["ok"]
    back = "La fábrica verifica cada cambio antes de integrarlo"
    _edit(notes, f"{SECOND}.", f"{SECOND}.\n\n{back}.")
    index = _section(eng, "Argumento")
    assert eng.kg_record_edgeless_section(FILE, index, "the claim it states is already judged")["ok"]
    assert eng.kg_ground_plan("", "")["queue"]["obsolete_returned"] == 1             # it comes back
    eng.kg_ground_item(CLAIM, terms="fábrica verifica integrarlo")
    assert eng.kg_ground(CLAIM, "grounded", support_span=back, note="found with my own words")["held"]
    plan = eng.kg_ground_plan("", "")
    assert {"id": CLAIM, "kind": "edge", "confirm": True} in _rows(plan), plan["batches"]
    assert plan["queue"]["confirm"] == 1 and plan["queue"]["obsolete_returned"] == 0
    out = eng.kg_ground(CLAIM, "grounded", support_span=back, note="it is stated again")
    assert out["ok"] and out["confirmed"] and out["from"] == "obsolete" and out["reanchored"], out
    assert _edge(eng, CLAIM).epistemic_state == EpistemicState.GROUNDED


# ---- the view shows the file's new text ------------------------------------------------------------------------

def _new(item: dict) -> "list[str]":
    return [x["excerpt"] for x in item["span_gone"]["new_text"]]


def test_the_view_shows_a_rewrite_that_shares_no_word_with_the_claim(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    gone = eng.kg_ground_item(CLAIM)["span_gone"]
    assert not any(REWRITE in s["excerpt"] for s in gone["sections"])                 # the claim's words reach nothing
    assert [x["excerpt"] for x in gone["new_text"]] == [f"{REWRITE}."] and gone["new_text_total"] == 1
    entry = gone["new_text"][0]
    assert entry["title"] == "Argumento" and entry["matched"] == [] and entry["source"]["class"] == "own"
    assert "new_text holds the paragraphs of the file written or rewritten" in gone["rule"]
    # grounded on it straight from the view: no request, so nothing is held
    out = eng.kg_ground(CLAIM, "grounded", support_span=REWRITE, note="new_text: §Argumento says it in other words")
    assert out["ok"] and out["reanchored"] and "held" not in out, out
    assert _edge(eng, CLAIM).span == REWRITE


def test_text_a_build_read_after_the_verdict_is_still_new_to_the_claim(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    index = _section(eng, "Argumento")                                               # /kg-build reads it again
    assert eng.kg_record_edgeless_section(FILE, index, "the claim it states is already judged")["recorded"] == "read"
    assert _new(eng.kg_ground_item(CLAIM)) == [f"{REWRITE}."]


def test_text_read_before_the_claims_last_verdict_is_not_new(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    index = _section(eng, "Argumento")
    assert eng.kg_record_edgeless_section(FILE, index, "the claim it states is already judged")["ok"]
    eng.kg_ground_item(CLAIM, terms="tortuga marina migración")
    assert eng.kg_ground(CLAIM, "obsolete", note="judged against the rewrite: it does not state it")["ok"]
    assert _new(eng.kg_ground_item(CLAIM)) == []                                    # judged against that text already
    later = "La fábrica comprueba de nuevo lo que cambia"
    _edit(notes, f"{SECOND}.", f"{SECOND}.\n\n{later}.")
    assert _new(eng.kg_ground_item(CLAIM)) == [f"{later}."]


def test_a_claim_never_judged_counts_only_text_no_build_has_read(rig):
    """With no verdict on record there is nothing to measure "since" from: text a build has read is not new to it."""
    eng, notes = rig
    rewritten = "Un juez automático declara buena o mala cada respuesta"
    _edit(notes, f"{SECOND}.", f"{rewritten}.")
    assert _new(eng.kg_ground_item(ORACLE)) == [f"{rewritten}."]                   # unread: new
    index = _section(eng, "Argumento")
    assert eng.kg_record_edgeless_section(FILE, index, "the claim it states is already written")["ok"]
    assert _new(eng.kg_ground_item(ORACLE)) == []                                   # read, and no verdict to compare


def test_a_section_no_build_has_read_is_left_out(rig):
    """A section only the edgeless ledger records, and one a build skips for good, hold no read record: their text is
    not new to a claim, or it would come back with every claim of the file."""
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    index = _section(eng, "Vocabulario")
    assert eng.kg_record_edgeless_section(FILE, index, "a glossary entry, no relation")["ok"]
    _edit(notes, "- **Arnés:**", "- **Oráculo:** lo que juzga cada salida.\n- **Arnés:**")
    path = notes / FILE
    path.write_text(path.read_text(encoding="utf-8") + "\n## Referencias\n- Pérez, 2024. Fábricas.\n",
                    encoding="utf-8")
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    assert _new(eng.kg_ground_item(CLAIM)) == [f"{REWRITE}."]


def test_no_record_of_the_file_shows_no_new_text(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    _edit(notes, f"{OLD}.", f"{REWRITE}.")
    (eng.canon.root / ".kg-read-sections.jsonl").unlink()
    gone = eng.kg_ground_item(CLAIM)["span_gone"]
    assert gone["new_text"] is None and gone["new_text_total"] == 0


def test_new_text_is_capped_and_ranked_by_the_claims_words(rig):
    eng, notes = rig
    assert eng.kg_ground(CLAIM, "grounded", note="§1")["ok"]
    filler = [f"El párrafo {n} habla de otra cosa distinta" for n in range(1, 8)]
    _edit(notes, f"{OLD}.", "\n\n".join(f"{x}." for x in filler + [REWRITE, "Cada cambio de la fábrica se verifica"]))
    gone = eng.kg_ground_item(CLAIM)["span_gone"]
    assert gone["new_text_total"] == 9 and len(gone["new_text"]) == KGEngine.NEW_TEXT_MAX == 6
    assert gone["new_text"][0]["excerpt"] == "Cada cambio de la fábrica se verifica."     # shares the claim's words
    assert [x["excerpt"] for x in gone["new_text"][1:]] == [f"{x}." for x in filler[:5]]   # then in source order


# ---- the texts --------------------------------------------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def _read(*parts: str) -> str:
    return _flat((REPO.joinpath(*parts)).read_text(encoding="utf-8"))


def test_the_contract_the_command_and_the_references_say_so():
    grounder = _read("agents", "grounder.md")
    rule = grounder.split("## A claim whose passage left its file (0.27.0)", 1)[1].split(" ## ", 1)[0]
    assert "**Nothing in `span_gone` states it: ask once before you call it gone (0.28.3).**" in rule
    assert 'Call `kg_ground_item(target_id, "edge", terms="…")` once' in rule
    assert "The engine refuses `obsolete` with `terms-not-asked` until you have asked" in rule
    assert "- `new_text` (0.28.3): the paragraphs of that file written or rewritten since the claim was last judged" in rule
    assert "decline it with `obsolete`" in grounder
    # the cross-language rule keeps its 0.28.2 wording
    assert ("call `kg_ground_item(target_id, kind, terms=\"…\")` once, before you record the item unsupported: at "
            "most 8 words") in grounder
    command = _read("commands", "kg-ground.md")
    assert "If none does, ask kg_ground_item once more with terms" in command
    assert "the engine refuses obsolete before you have asked" in command
    tools = _read("skills", "burgess", "references", "tools.md")
    assert "Since 0.28.3 it waits for one request of the grounder's" in tools
    assert "For such a claim (0.28.3) a `terms` request ranks the sections of that file" in tools
    assert "`new_text` (0.28.3, `KGEngine._new_text_view`)" in tools
    assert "new_text, the paragraphs of its file written or rewritten since it was last judged" in command
    architecture = _read("docs", "ARCHITECTURE.md")
    assert "`kg_ground` refuses `obsolete` with `terms-not-asked` until it has (0.28.3, " in architecture
    assert "the paragraphs of the claim's file written or rewritten since it was last judged (`new_text`" in architecture
    server = _read("scripts", "kg_engine", "server.py")
    assert "Before `obsolete`, ask kg_ground_item once with your own `terms` (0.28.3)" in server
    assert "When none of these states it, ask once with `terms` before you mark it obsolete" in server
    assert "so `span_gone` also holds `new_text` (0.28.3)" in server
