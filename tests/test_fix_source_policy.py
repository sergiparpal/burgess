"""0.22.0: every source has a level, the notes included, and the project decides the level it requires.

Through 0.21.0 the configured sources, the user's notes, sat outside the scale: notes of unknown level verified
an idea exactly as a peer-reviewed paper did, and a reviewed paper could not fail what they said. And a
registered source was never extracted, so a graph could not be built from level-1 sources: putting the papers in
the notes folder would have stripped them of their level. The user asked both questions on 2026-11-21.

Now `policy.json` in the evidence directory holds `required_level` (the worst level that may still support or
refute: 4 by default, 1 for only peer-reviewed sources), `notes_level` (the level of a note with no record of
its own, 4 by default), per-note records, and `build_from_notes`. A registered source with `build` is extracted
like a note. Under a strict policy a claim the notes state is verified on another source's passage
(`support_span`, recorded as a `support:` segment), or left unverified and recorded, never rejected for its
level.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kg_engine import evidence
from kg_engine.evidence import Policy, load_policy
from kg_engine.model import EpistemicState, Node, Provenance, edge_id
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")

NOTES = """\
## Notes

Specificity-weighted betweenness reconciles with the bridge intuition. Degree approximates importance.
"""
CLAIM_SPAN = "Specificity-weighted betweenness reconciles with the bridge intuition"
REVIEW = """\
## Findings

Across the cohort, specificity-weighted betweenness reconciles with the bridge intuition in every network.
"""
REVIEW_SPAN = "specificity-weighted betweenness reconciles with the bridge intuition in every network"


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def rig(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "notes.md").write_text(NOTES, encoding="utf-8")
    eng = KGEngine(project, source_path=notes, pack_path=PACK)
    return eng, project, tmp_path


def _local(tmp_path: Path, name: str, text: str) -> Path:
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    p = folder / name
    p.write_text(text, encoding="utf-8")
    return p


def _add(eng, tmp_path, name, text, level, role="primary", build=False):
    out = eng.kg_source_add(path=str(_local(tmp_path, name, text)), level=level, role=role, build=build)
    assert out["ok"], out
    return out["name"]


def _edge(eng, eid):
    return next(e for e in eng.canon.all_edges() if e.id == eid)


def _claim(eng):
    eng.kg_write({"edges": [{"source": "specificity-weighted betweenness", "target": "bridge intuition",
                             "relation": "reconciles_with", "span": CLAIM_SPAN, "source_file": "notes.md"}]})
    return edge_id("specificity-weighted betweenness", "reconciles_with", "bridge intuition")


# --------------------------------------------------------------------------- the policy

def test_the_defaults_are_the_0_21_0_acceptance(rig):
    eng, project, _ = rig
    out = eng.kg_source_policy()
    assert out["ok"] and out["changed"] == []
    # 0.23.0 adds where the notes come from (tests/test_fix_per_project_sources.py)
    assert {k: out["policy"][k] for k in ("required_level", "notes_level", "build_from_notes", "notes_path",
                                          "notes_from")} == {"required_level": 4, "notes_level": 4,
                                                             "build_from_notes": True, "notes_path": "",
                                                             "notes_from": "global"}
    assert [n["name"] for n in out["notes"]] == ["notes.md"] and out["notes"][0]["level"] == 4
    assert out["notes"][0]["usable"] and out["notes"][0]["built"] and not out["notes"][0]["recorded"]
    assert not (project / "evidence" / "policy.json").exists()       # reading writes nothing
    assert eng._source_signature() == hashlib.sha256(eng.source_set().concat.encode()).hexdigest()


def test_the_policy_is_kept_and_validated(rig):
    eng, project, _ = rig
    out = eng.kg_source_policy(required_level=1, notes_level=3, build_from_notes=False)
    assert out["changed"] == ["required_level", "notes_level", "build_from_notes"]
    data = json.loads((project / "evidence" / "policy.json").read_text(encoding="utf-8"))
    assert (data["required_level"], data["notes_level"], data["build_from_notes"]) == (1, 3, False)
    again = KGEngine(project, source_path=eng.source_path, pack_path=PACK)
    got = again.kg_source_policy()["policy"]
    assert (got["required_level"], got["notes_level"], got["build_from_notes"]) == (1, 3, False)
    assert eng.kg_source_policy(required_level=5)["error"] == "bad-required-level"
    assert eng.kg_source_policy(notes_level=7)["error"] == "bad-level"
    assert eng.kg_source_policy(build_from_notes="maybe")["error"] == "bad-build-from-notes"


def test_a_malformed_policy_falls_back_to_the_defaults_and_says_so(rig):
    eng, project, _ = rig
    (project / "evidence").mkdir()
    (project / "evidence" / "policy.json").write_text('{"required_level": "high"}', encoding="utf-8")
    listing = eng.kg_source_list()
    assert listing["policy"]["required_level"] == 4
    assert [p["problem"] for p in listing["problems"]] == ["bad-level"]
    pol, problems = load_policy(project / "evidence")
    assert isinstance(pol, Policy) and pol.is_default() and problems


def test_a_note_gets_its_own_level(rig):
    eng, project, _ = rig
    out = eng.kg_source_set("notes.md", level=2, role="secondary", note="a synthesis of reviewed work")
    assert out["ok"] and out["changed"] == ["level", "role", "note"]
    assert (out["source"]["class"], out["source"]["level"], out["source"]["usable"]) == ("own", 2, True)
    note = next(n for n in eng.kg_source_list()["notes"] if n["name"] == "notes.md")
    assert note["level"] == 2 and note["recorded"]
    assert eng.kg_source_set("notes.md", title="x")["error"] == "not-for-notes"
    assert eng.kg_source_set("nope.md", level=1)["error"] == "source-not-found"


def test_a_policy_change_moves_the_source_signature(rig):
    eng, _, _ = rig
    before = eng._source_signature()
    eng.kg_source_policy(required_level=1)
    assert eng._source_signature() != before
    eng.kg_source_policy(required_level=4)
    assert eng._source_signature() == before


# --------------------------------------------------------------------------- a strict policy

def test_under_a_strict_policy_the_notes_only_propose(rig):
    eng, _, _ = rig
    cid = _claim(eng)
    eng.kg_source_policy(required_level=1)
    out = eng.kg_ground(cid, "grounded")
    assert out["error"] == "support-not-usable" and out["unusable"] == "below-required-level"
    assert (out["source"], out["source_level"], out["required_level"]) == ("notes.md", 4, 1)
    assert _edge(eng, cid).epistemic_state == EpistemicState.UNVERIFIED


def test_a_claim_of_the_notes_is_verified_on_a_reviewed_passage(rig):
    eng, _, tmp = rig
    cid = _claim(eng)
    review = _add(eng, tmp, "review.md", REVIEW, 1)
    eng.kg_source_policy(required_level=1)
    item = eng.kg_ground_item(cid)
    assert item["span_source"]["usable"] is False and item["support_source"]["file"] == "notes.md"
    sections = item["support_context"]["sections"]
    assert sections and sections[0]["source_file"] == review and sections[0]["source"]["usable"] is True
    assert all(s["source"]["usable"] for s in sections)
    out = eng.kg_ground(cid, "grounded", support_span=REVIEW_SPAN, note="the review states it")
    assert out["ok"] and out["support_source"]["file"] == review and out["support_source"]["level"] == 1
    e = _edge(eng, cid)
    assert e.span == CLAIM_SPAN and e.source_file == "notes.md"            # the extraction is kept
    assert evidence.supports_of(e.notes) == [(REVIEW_SPAN, review)]
    assert eng.kg_ground_item(cid)["support_source"]["level"] == 1
    support = eng.kg_source_list()["support"]
    assert support["edges"]["external"] == {"1": 1} and support["on_unusable"] == []


def test_a_support_span_from_a_source_below_the_level_is_refused(rig):
    eng, _, tmp = rig
    cid = _claim(eng)
    blog = _add(eng, tmp, "blog.md", REVIEW, 3)
    eng.kg_source_policy(required_level=2)
    out = eng.kg_ground(cid, "grounded", support_span=REVIEW_SPAN)
    assert out["error"] == "support-not-usable" and out["source"] == blog and out["source_level"] == 3


def test_raising_the_level_puts_earlier_verdicts_on_the_report(rig):
    eng, _, _ = rig
    cid = _claim(eng)
    assert eng.kg_ground(cid, "grounded")["ok"]
    out = eng.kg_source_policy(required_level=1)
    assert out["on_unusable_total"] == 1
    flagged = eng.kg_source_list()["support"]["on_unusable"]
    assert flagged == [{"id": cid, "kind": "edge", "source": "notes.md", "unusable": "below-required-level"}]
    assert _edge(eng, cid).epistemic_state == EpistemicState.GROUNDED      # a verdict never changes by itself


def test_a_claim_without_usable_support_waits_instead_of_being_rejected(rig):
    eng, _, tmp = rig
    cid = _claim(eng)
    assert eng.kg_record_unsupported(cid, kind="edge", note="nothing yet")["ok"] is False   # usable span: a verdict
    eng.kg_source_policy(required_level=1)
    assert eng.kg_record_unsupported(cid, kind="edge", note="no level-1 source states it")["ok"]
    plan = eng.kg_ground_plan()
    assert plan["queue"]["unsupported_waiting"] == 1
    assert not any(item["id"] == cid for batch in plan["batches"] for item in batch)
    _add(eng, tmp, "review.md", REVIEW, 1)                                   # a new source wakes it
    plan = eng.kg_ground_plan()
    assert plan["queue"]["unsupported_waiting"] == 0
    assert any(item["id"] == cid for batch in plan["batches"] for item in batch)


def test_a_proposal_may_wait_while_the_notes_are_below_the_level(rig):
    eng, _, _ = rig
    eng.kg_propose({"edges": [{"source": "degree", "target": "importance", "relation": "approximates"}]})
    pid = edge_id("degree", "approximates", "importance")
    assert eng.kg_record_unsupported(pid, kind="edge", note="only the notes say it")["ok"] is False
    eng.kg_source_policy(required_level=2)
    assert eng.kg_record_unsupported(pid, kind="edge", note="only the notes say it")["ok"]


def test_a_proposal_without_a_usable_shared_section_gets_support_context(rig):
    eng, _, tmp = rig
    _claim(eng)
    _add(eng, tmp, "review.md", REVIEW, 1)
    eng.kg_propose({"edges": [{"source": "specificity-weighted betweenness", "target": "bridge intuition",
                               "relation": "grounds"}]})
    pid = edge_id("specificity-weighted betweenness", "grounds", "bridge intuition")
    assert eng.kg_ground_item(pid)["support_context"] is None              # the notes' section is usable
    eng.kg_source_policy(required_level=1)
    item = eng.kg_ground_item(pid)
    assert item["shared_context"]["sections"][0]["source"]["usable"] is False
    assert item["support_context"]["sections"][0]["source"]["level"] == 1


def test_the_veto_reads_the_notes_level(rig):
    eng, _, tmp = rig
    cid = _claim(eng)
    assert eng.kg_ground(cid, "grounded")["ok"]
    blog = _add(eng, tmp, "blog.md", "Specificity never reconciles with the bridge intuition at all.\n", 3)
    eng.kg_write({"edges": [{"source": "specificity-weighted betweenness", "target": "blog objection",
                             "relation": "attacked_by", "span": "Specificity never reconciles with the bridge "
                             "intuition", "source_file": blog}]})
    counter = edge_id("specificity-weighted betweenness", "attacked_by", "blog objection")
    eng.kg_source_set("notes.md", level=2)
    assert eng.kg_ground(cid, "failed", refuted_by=counter)["error"] == "failed-by-lower-level"
    eng.kg_source_set("notes.md", level=4)
    assert eng.kg_ground(cid, "failed", refuted_by=counter)["ok"]


# --------------------------------------------------------------------------- building from sources

def test_a_source_registered_to_be_built_is_extracted(rig):
    eng, _, tmp = rig
    name = _add(eng, tmp, "review.md", REVIEW, 1, build=True)
    plan = eng.kg_build_plan()
    assert [f["file"] for f in plan["files"]] == ["notes.md", name]
    assert "in every network" in eng.source_text()
    section = eng.kg_section(name, 1)
    assert section["ok"] and REVIEW_SPAN in _flat(section["text"]).lower()
    listing = eng.kg_source_list()
    assert listing["sources"][0]["build"] is True and listing["sources"][0]["level"] == 1


def test_building_can_be_turned_off_again(rig):
    eng, _, tmp = rig
    name = _add(eng, tmp, "review.md", REVIEW, 1, build=True)
    out = eng.kg_source_set(name, build=False)
    assert out["changed"] == ["build"] and "hint" in out
    assert [f["file"] for f in eng.kg_build_plan()["files"]] == ["notes.md"]


def test_a_graph_can_be_built_from_level_1_sources_alone(rig):
    eng, _, tmp = rig
    old = _claim(eng)                                   # a claim extracted before the switch
    name = _add(eng, tmp, "review.md", REVIEW, 1, build=True)
    eng.kg_source_policy(required_level=1, build_from_notes=False)
    assert [f["file"] for f in eng.kg_build_plan()["files"]] == [name]
    assert "Degree approximates importance" not in eng.source_text()       # the notes leave the corpus
    assert eng.verify_set().verifies(CLAIM_SPAN, "notes.md")                # but their spans still verify
    note = next(n for n in eng.kg_source_list()["notes"] if n["name"] == "notes.md")
    assert note["built"] is False and note["usable"] is False
    eng.kg_write({"edges": [{"source": "specificity-weighted betweenness", "target": "every network",
                             "relation": "grounds", "span": REVIEW_SPAN, "source_file": name}]})
    built = edge_id("specificity-weighted betweenness", "grounds", "every network")
    out = eng.kg_ground(built, "grounded")
    assert out["ok"]
    assert eng.kg_ground_item(built)["span_source"]["level"] == 1
    eng.projector.project(incremental=False)
    assert old not in [s["edge_id"] for s in eng.projector._read_meta().get("stale_verdicts", [])]


# --------------------------------------------------------------------------- the surface and the texts

def test_the_policy_tool_is_registered():
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn
            return deco

    mcp = FakeMCP()
    _register(mcp, object())
    import inspect
    assert "kg_source_policy" in mcp.tools
    assert "build" in inspect.signature(mcp.tools["kg_source_add"]).parameters
    assert "build" in inspect.signature(mcp.tools["kg_source_set"]).parameters


def test_the_texts_carry_the_model():
    flat = _flat(COMMAND)
    assert "## policy" in COMMAND and "mcp__plugin_burgess_burgess__kg_source_policy" in COMMAND
    assert "Build a graph from level-1 sources alone:" in flat
    assert "Never change the policy or a note's level on your own initiative" in flat
    grounder = _flat(GROUNDER)
    assert "e. **Support elsewhere.**" in GROUNDER
    assert "Never reject a claim because its only support is below the required level." in grounder
    assert "never rejected for its level" in _flat(GROUND_CMD)
