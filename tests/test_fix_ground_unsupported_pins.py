"""0.20.1: a [diverge] pin a grounder left unverified for want of support waits for the sources to change.

On 2026-11-21 the user carried 120 pinned ideas of four test sessions into the field graph. The contract
leaves an unsupported pin `unverified` instead of rejecting it, and nothing recorded that judgment, so the
plan queued every pin on every pass. The pass over the 120 ran ten grounders, about $2.50, and left all
120 unverified; the next pass would have done the same, and the one after, with nothing changed. A pin
offered again only when the sources or the pin change is judged once per change instead.

`kg_record_unsupported` is the record, mirroring `kg_record_attack` (0.10.0): a ledger beside the canon, no
state change, refused for anything but an unverified [diverge]-pinned hypothesis.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_engine.groundplan import item_signature, unsupported_records, waits_for_sources
from kg_engine.model import EpistemicState
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
LEDGER = ".kg-unsupported-pins.jsonl"


def _flat(text: str) -> str:
    return " ".join(text.split())


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A project with a source and two materialized pins, idea-brief-c0 and idea-brief-c1."""
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    monkeypatch.delenv("KG_PACK_PATH", raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    src = tmp_path / "source.md"
    src.write_text("Entropy grounds the arrow of time. Heat flows from hot to cold.\n", encoding="utf-8")
    engine = KGEngine(proj, source_path=src, pack_path=PACK)
    mcp = _FakeMCP()
    _register(mcp, engine)
    t = mcp.tools
    t["kg_diverge_init"](project="brief", axes="generic", session="s1", seed=5)
    cands = [{"id": f"c{i}", "text": f"idea {i}: concept about topic {i} via approach {i}",
              "descriptor": {"angle": f"a{i}", "scope": "broad", "form": f"f{i % 2}",
                             "boldness": (i % 5) / 4.0, "mechanism": f"mechanism {i}"},
              "genealogy": {"operator_id": "analogy", "parents": []}} for i in range(6)]
    assert t["kg_diverge_ingest"](project="brief", candidates=cands, axes="generic", seed=5)["slate"]
    for cid in ("c0", "c1"):
        t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": cid})
    assert t["kg_diverge_materialize"](project="brief")["materialized"] == 2
    return engine, t, src


def _queued(plan: dict) -> list[str]:
    return [item["id"] for batch in plan["batches"] for item in batch]


def _record(t, node_id: str = "idea-brief-c0", **kw):
    return t["kg_record_unsupported"](target_id=node_id, kind=kw.pop("kind", "node"),
                                      note=kw.pop("note", "no passage states this mechanism"))


# ------------------------------------------------------------------------------------------- the plan


def test_a_recorded_pin_waits_and_the_others_stay_queued(rig):
    engine, t, _ = rig
    assert sorted(_queued(engine.kg_ground_plan())) == ["idea-brief-c0", "idea-brief-c1"]
    out = _record(t)
    assert out["ok"] and out["item"] == "idea-brief-c0" and out["kind"] == "node"
    plan = engine.kg_ground_plan()
    assert _queued(plan) == ["idea-brief-c1"]
    assert plan["queue"]["unsupported_waiting"] == 1 and plan["queue"]["nodes"] == 1


def test_a_source_change_offers_the_pin_again(rig):
    engine, t, src = rig
    _record(t)
    # 0.24.4: a new paragraph wakes the pin when it shares three of its words (about, concept, topic)
    src.write_text(src.read_text(encoding="utf-8") + "A new paragraph about the concept of topic 0.\n",
                   encoding="utf-8")
    plan = engine.kg_ground_plan()
    assert "idea-brief-c0" in _queued(plan) and plan["queue"]["unsupported_waiting"] == 0


def test_a_focus_offers_the_recorded_pins_again(rig):
    engine, t, _ = rig
    _record(t)
    plan = engine.kg_ground_plan(focus="topic")
    assert "idea-brief-c0" in _queued(plan) and plan["queue"]["unsupported_waiting"] == 0


def test_an_unreadable_ledger_offers_every_pin(rig):
    engine, t, _ = rig
    _record(t)
    (engine.canon.root / LEDGER).write_text("not json\n{\"kind\": 3}\n", encoding="utf-8")
    plan = engine.kg_ground_plan()
    assert sorted(_queued(plan)) == ["idea-brief-c0", "idea-brief-c1"]


def test_without_a_ledger_the_plan_reports_zero_waiting(rig):
    engine, _, _ = rig
    assert engine.kg_ground_plan()["queue"]["unsupported_waiting"] == 0
    assert not (engine.canon.root / LEDGER).exists()   # the read-only plan never creates it


# -------------------------------------------------------------------------------------------- the record


def test_the_record_sets_no_state_and_signs_the_sources(rig):
    engine, t, _ = rig
    before = (engine.canon.notes_dir / "idea-brief-c0.md").read_text(encoding="utf-8")
    _record(t)
    assert (engine.canon.notes_dir / "idea-brief-c0.md").read_text(encoding="utf-8") == before
    lines = (engine.canon.root / LEDGER).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["item"] == "idea-brief-c0" and rec["kind"] == "node"
    assert rec["source_sig"] == engine._source_signature() and rec["note"]
    assert engine.canon.read_node("idea-brief-c0").epistemic_state is EpistemicState.UNVERIFIED


@pytest.mark.parametrize("target,kind,note,needle", [
    ("idea-brief-c9", "node", "x", "node not found"),
    ("idea-brief-c0", "vertex", "x", "invalid kind"),
    ("idea-brief-c0", "node", "   ", "note"),
    ("", "node", "x", "name the pin"),
])
def test_bad_requests_are_refused(rig, target, kind, note, needle):
    _, t, _ = rig
    out = t["kg_record_unsupported"](target_id=target, kind=kind, note=note)
    assert out["ok"] is False and needle in out["error"]


def test_an_ordinary_proposal_cannot_be_hidden_from_the_queue(rig):
    engine, t, _ = rig
    engine.kg_propose({"nodes": [{"id": "plain-hypothesis", "label": "A plain generated proposal",
                                  "node_type": "claim", "body": "No pin marker here."}]})
    out = _record(t, "plain-hypothesis")
    assert out["ok"] is False and "kg_ground" in out["error"]
    assert "plain-hypothesis" in _queued(engine.kg_ground_plan())


def test_a_verdicted_pin_cannot_be_recorded(rig):
    engine, t, _ = rig
    assert engine.kg_ground("idea-brief-c1", "failed", kind="node", note="refuted for the test").get("ok", True)
    out = _record(t, "idea-brief-c1")
    assert out["ok"] is False and "unverified" in out["error"]


# ----------------------------------------------------------------------------------------- the helpers


def test_a_change_to_the_pin_changes_its_signature():
    node = SimpleNamespace(label="Idea", body="text\n\n[diverge] pinned candidate=c0")
    sig = item_signature("node", node)
    record = {"at": "t", "source_sig": "s", "item_sig": sig, "evidence": 2}
    assert waits_for_sources(record, "s", sig)
    # a 0.20.1 record carries no evidence version: its grounder saw no source text (0.20.2), so it is stale
    assert not waits_for_sources({"at": "t", "source_sig": "s", "item_sig": sig}, "s", sig)
    assert not waits_for_sources(record, "s2", sig)                      # the sources changed
    edited = SimpleNamespace(label="Idea", body="text, edited\n\n[diverge] pinned candidate=c0")
    assert not waits_for_sources(record, "s", item_signature("node", edited))   # the pin changed
    assert not waits_for_sources(None, "s", sig)


def test_the_latest_record_wins_and_junk_lines_are_skipped():
    lines = [json.dumps({"kind": "node", "item": "p", "at": "2026-01-01T00:00:00", "source_sig": "a",
                         "item_sig": "x"}),
             "garbage",
             json.dumps({"kind": "node", "item": "p", "at": "2026-02-01T00:00:00", "source_sig": "b",
                         "item_sig": "x"}),
             json.dumps({"kind": "thing", "item": "q", "at": "2026-01-01T00:00:00"})]
    recs = unsupported_records(lines)
    assert set(recs) == {("node", "p")} and recs[("node", "p")]["source_sig"] == "b"


# -------------------------------------------------------------------------------------------- the text


def test_the_grounder_records_an_unsupported_pin():
    assert "mcp__plugin_burgess_burgess__kg_record_unsupported" in GROUNDER.splitlines()[3]   # tools line
    text = _flat(GROUNDER)
    assert "**Then record it** with `kg_record_unsupported(target_id=<id>, kind=<node|edge>, note=" in text
    assert "record that with `kg_record_unsupported`" in text


def test_the_command_tells_the_grounder_and_reports_what_waits():
    text = _flat(GROUND_CMD)
    assert ("[diverge]-pinned item without support stays unverified, and you record it with "
            "mcp__plugin_burgess_burgess__kg_record_unsupported(target_id, kind, note)") in text
    assert "drops out of the plan once the grounder records it with `kg_record_unsupported`" in text
    assert "When `queue.unsupported_waiting` is not 0, say in either case that that many pinned ideas wait" in text


def test_the_tool_reference_documents_it():
    assert "`kg_record_unsupported(target_id, kind=\"node\", note)`" in TOOLS
