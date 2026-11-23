"""0.22.1: a policy that leaves no usable source no longer wastes a grounding pass, waiting items wake only for
new usable evidence, and a formula is copied once.

Field run of 2026-11-22 (Windows, prueba-burgess): the user registered a level-4 arXiv preprint, then set the
project to require level 1. No file was usable any more (the 9 notes and the preprint are level 4), yet the next
`/burgess:kg-ground` would have sent 119 pins to 10 grounders: registering the preprint had woken them, rightly at
the time, and a stricter policy could not put them back to sleep. And the copy of the preprint read
`daily merges rose 15×\\times`: the HTML rule copied each formula's LaTeX annotation beside its rendering.

Now `kg_ground_plan` leaves out, as `blocked`, what no usable source could settle (hypotheses, hub attacks) and
keeps the extracted claims; a record keeps the hashes of the files usable when it was made, and an item wakes only
when a usable file it has not seen appears; the HTML rule (`html-text/2`) drops MathML annotations and invisible
math operators; the policy says when nothing is usable.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kg_engine import evidence
from kg_engine.groundplan import item_signature
from kg_engine.model import Node, Provenance, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
SOURCES_CMD = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
LEDGER = ".kg-unsupported-pins.jsonl"

NOTES = """\
## Notes

Betweenness grounds the bridge metric. Betweenness approximates importance in sparse graphs.
Betweenness is confounded by the generality confound. Degree approximates importance.
"""
OUTSIDE = "## Findings\n\nGamma bridges delta across the outside text.\n"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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


def _add(eng, tmp_path, name, text, level):
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    out = eng.kg_source_add(path=str(folder / name), level=level, role="primary")
    assert out["ok"], out
    return out["name"]


def _pin(eng, nid="pin-a"):
    eng.canon.write_one(Node(id=nid, label="Gamma bridges delta", node_type="claim",
                             provenance=Provenance.HYPOTHESIZED, body="[diverge] pinned idea: gamma bridges delta"))
    return nid


def _waiting(eng) -> int:
    return eng.kg_ground_plan()["queue"]["unsupported_waiting"]


def _queued(plan) -> "set[str]":
    return {item["id"] for batch in plan["batches"] for item in batch}


# --------------------------------------------------------------------------- nothing usable

def test_with_no_usable_source_the_plan_keeps_only_extracted_claims(rig):
    eng, _, _ = rig
    pin = _pin(eng)
    eng.kg_propose({"edges": [{"source": "degree", "target": "betweenness", "relation": "approximates"}]})
    proposal = edge_id("degree", "approximates", "betweenness")
    eng.kg_write({"edges": [{"source": "degree", "target": "importance", "relation": "approximates",
                             "span": "Degree approximates importance", "source_file": "notes.md"}]})
    extracted = edge_id("degree", "approximates", "importance")
    assert _queued(eng.kg_ground_plan()) == {pin, proposal, extracted}
    assert eng.kg_ground_plan()["blocked"] is None
    eng.kg_source_policy(required_level=1)
    plan = eng.kg_ground_plan()
    assert _queued(plan) == {extracted}                       # its span can still be rejected for what it says
    assert plan["blocked"]["reason"] == "no-usable-source" and plan["blocked"]["items"] == 2
    assert plan["blocked"]["required_level"] == 1 and "/burgess:kg-sources" in plan["blocked"]["hint"]
    assert plan["queue"]["nodes"] == 0 and plan["queue"]["edges"] == 1


def test_a_usable_source_lifts_the_block(rig):
    eng, _, tmp = rig
    pin = _pin(eng)
    eng.kg_source_policy(required_level=1)
    assert pin not in _queued(eng.kg_ground_plan())
    _add(eng, tmp, "review.md", OUTSIDE, 1)
    plan = eng.kg_ground_plan()
    assert plan["blocked"] is None and pin in _queued(plan)


def test_no_hub_is_attacked_when_nothing_could_be_failed(rig):
    eng, _, _ = rig
    for target, relation, span in (("bridge metric", "grounds", "Betweenness grounds the bridge metric"),
                                   ("importance", "approximates", "Betweenness approximates importance"),
                                   ("generality confound", "confounded_by",
                                    "Betweenness is confounded by the generality confound")):
        eng.kg_write({"edges": [{"source": "betweenness", "target": target, "relation": relation, "span": span,
                                 "source_file": "notes.md"}]})
        assert eng.kg_ground(edge_id("betweenness", relation, target), "grounded")["ok"]
    assert [h["id"] for h in eng.kg_ground_plan()["hubs"]] == ["betweenness"]
    eng.kg_source_policy(required_level=1)
    plan = eng.kg_ground_plan()
    assert plan["hubs"] == [] and plan["blocked"]["hubs"] == 1


# --------------------------------------------------------------------------- waking

def test_only_new_usable_evidence_wakes_a_waiting_item(rig):
    eng, _, tmp = rig
    pin = _pin(eng)
    assert eng.kg_record_unsupported(pin, kind="node", note="nothing in the notes")["ok"]
    assert _waiting(eng) == 1
    _add(eng, tmp, "post.md", "Gamma bridges delta, trust me.\n", 5)       # unfiltered: supports nothing
    assert _waiting(eng) == 1
    eng.kg_source_policy(required_level=1)                                  # stricter: nothing new is usable
    assert _waiting(eng) == 1
    _add(eng, tmp, "blog.md", "Gamma bridges delta, says a blog.\n", 4)    # below the required level
    assert _waiting(eng) == 1
    _add(eng, tmp, "review.md", OUTSIDE, 1)                                 # usable and new
    assert _waiting(eng) == 0


def test_a_looser_policy_wakes_a_waiting_item(rig):
    eng, _, _ = rig
    pin = _pin(eng)
    eng.kg_source_policy(required_level=2)
    assert eng.kg_record_unsupported(pin, kind="node", note="nothing usable")["ok"]
    assert _waiting(eng) == 1
    eng.kg_source_policy(required_level=4)                                  # the notes become usable
    assert _waiting(eng) == 0


def test_an_edited_note_still_wakes_a_waiting_item(rig):
    eng, _, tmp = rig
    pin = _pin(eng)
    assert eng.kg_record_unsupported(pin, kind="node", note="nothing in the notes")["ok"]
    (tmp / "notes" / "notes.md").write_text(NOTES + "\nGamma bridges delta in the new paragraph.\n", encoding="utf-8")
    assert _waiting(eng) == 0


def test_the_recorder_keeps_the_usable_files(rig):
    eng, project, _ = rig
    pin = _pin(eng)
    assert eng.kg_record_unsupported(pin, kind="node", note="nothing in the notes")["ok"]
    line = json.loads((project / LEDGER).read_text(encoding="utf-8").splitlines()[-1])
    assert line["usable"] == [_sha(NOTES)]


def _legacy(project, eng, nid, source_sig):
    """A ledger line as 0.20.2 to 0.22.0 wrote it: no `usable` list."""
    node = eng.canon.read_node(nid)
    line = {"kind": "node", "item": nid, "at": "2026-11-21T17:00:00+00:00", "source_sig": source_sig,
            "item_sig": item_signature("node", node), "evidence": 2, "note": "nothing in the notes"}
    with open(project / LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def test_a_record_from_before_0_22_1_is_read_against_the_notes_it_was_made_on(rig):
    """The field case: 120 records made on 0.20.x against the notes alone, then a preprint registered and a
    stricter policy. The record stands for the notes it was judged on, so only new usable evidence wakes it."""
    eng, project, tmp = rig
    pin = _pin(eng)
    _legacy(project, eng, pin, _sha(NOTES))                                 # the 0.20.x signature of these notes
    assert _waiting(eng) == 1
    _add(eng, tmp, "preprint.md", "Gamma bridges delta, a preprint says.\n", 4)
    assert _waiting(eng) == 0                                               # a usable source appeared: woken
    eng.kg_source_policy(required_level=1)
    assert _waiting(eng) == 1                                               # nothing usable is new any more
    _add(eng, tmp, "review.md", OUTSIDE, 1)
    assert _waiting(eng) == 0


def test_a_record_of_other_notes_keeps_the_old_rule(rig):
    eng, project, _ = rig
    pin = _pin(eng)
    _legacy(project, eng, pin, _sha("notes the project no longer has"))
    assert _waiting(eng) == 0                                               # its signature no longer matches


# --------------------------------------------------------------------------- the warning

def test_the_policy_says_when_nothing_is_usable(rig):
    eng, _, tmp = rig
    out = eng.kg_source_policy()
    assert out["usable_sources"] == 1 and "warning" not in out
    out = eng.kg_source_policy(required_level=1)
    assert out["usable_sources"] == 0 and "nothing can be grounded or refuted" in out["warning"]
    listing = eng.kg_source_list()
    assert listing["usable_sources"] == 0 and listing["warning"]
    _add(eng, tmp, "review.md", OUTSIDE, 1)
    assert eng.kg_source_list()["usable_sources"] == 1 and "warning" not in eng.kg_source_list()


# --------------------------------------------------------------------------- the HTML rule

def test_a_formula_is_copied_once():
    markup = ('<p>Daily merges rose 15<math alttext="\\times"><semantics><mo>×</mo>'
              '<annotation encoding="application/x-tex">\\times</annotation></semantics></math> during rollout '
              '(<math alttext="\\kappa=0.91"><semantics><mrow><mi>κ</mi><mo>=</mo><mn>0.91</mn></mrow>'
              '<annotation-xml encoding="MathML-Content"><ci>κ</ci></annotation-xml></semantics></math>), with '
              '<math><mi>f</mi><mo>\u2061</mo><mo>\u200b</mo><mi>x</mi></math> and a\u200bspace.</p>')
    _title, text, _meta = evidence.html_text(markup)
    assert text == "Daily merges rose 15× during rollout (κ=0.91), with fx and a\u200bspace.\n"
    # the rule came in with html-text/2; 0.23.1 (html-text/3, page furniture left out) keeps it
    assert evidence.HTML_EXTRACTOR.startswith("html-text/") and int(evidence.HTML_EXTRACTOR.rsplit("/", 1)[1]) >= 2


def test_a_registered_page_records_the_new_rule(rig, monkeypatch):
    eng, _, _ = rig
    from email.message import Message

    class Resp:
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"

        def read(self, n=-1):
            return "<p>Merges rose 15<math><mo>×</mo><annotation>\\times</annotation></math> here.</p>".encode()

        def geturl(self):
            return "https://example.org/p"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(evidence, "_urlopen", lambda req, timeout: Resp())
    out = eng.kg_source_add(url="https://example.org/p", level=4, role="primary")
    assert out["ok"]
    rec = json.loads((eng.project_dir / "evidence" / (Path(out["name"]).stem + ".source.json")).read_text())
    assert rec["extractor"] == evidence.HTML_EXTRACTOR
    assert (eng.project_dir / "evidence" / out["name"]).read_text(encoding="utf-8") == "Merges rose 15× here.\n"


# --------------------------------------------------------------------------- the texts

def test_the_commands_explain_a_blocked_queue_and_the_warning():
    ground = _flat(GROUND_CMD)
    assert "`blocked` (0.22.1): set when no source is usable under the project's policy" in ground
    assert "launch no grounder for what it left out" in ground
    sources = _flat(SOURCES_CMD)
    assert "**When the result carries `warning`**" in sources
