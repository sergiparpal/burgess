"""0.22.4: a re-examination is answered by the item's next verdict, and the grounders do it with the text that
raised it.

The review of phase 2 of the field test of 2026-11-22 (Windows, prueba-burgess, on 0.22.3) came before its
`/burgess:kg-ground`. The project had moved to level 4, so the preprint counted, and 113 rejected items it had
flagged were listed for a second look. Three things stood in the way:
- a flag lasted until its item left the negative states, so a re-check that kept a rejection left it flagged on
  every pass, and with the list capped at 50 the same 50 would have come back each time;
- Stage 0c asked the orchestrator to re-verdict them, and the command never calls `kg_ground`;
- a span-less proposal's evidence was where its ends' spans lie, the notes it had been judged against, so a
  grounder would never have seen the preprint that flagged it.

Now a flag stores the audit log's size when it was raised, and a verdict recorded beyond it answers the flag;
the plan queues the open flags on rejected items for grounders; `kg_ground_item` gives each the sections of the
files that raised it; and a fresh flag adds its files to a carried one.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from kg_engine.canon import GROUND_AUDIT
from kg_engine.groundaudit import AuditIndex, audit_key, read_audit_index
from kg_engine.model import edge_id
from kg_engine.projector import REEX_MARK
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

NOTES = "## Notes\n\nDegree approximates importance in every sampled network.\n"
PREPRINT = "## Findings\n\nGamma bridges delta in the factories we watched for fifteen days.\n"
EID = edge_id("gamma", "bridges", "delta")


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
    return eng, tmp_path


def _add(eng, tmp_path, name, text, level=4, marks=""):
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    out = eng.kg_source_add(path=str(folder / name), level=level, role="primary", marks=marks)
    assert out["ok"], out
    return out["name"]


def _rejected(eng, source="gamma", target="delta"):
    eng.kg_propose({"edges": [{"source": source, "target": target, "relation": "bridges"}]})
    eid = edge_id(source, "bridges", target)
    assert eng.kg_ground(eid, "rejected", note="no-support: the notes never join them")["ok"]
    return eid


def _listed(eng) -> "list[str]":
    return [f["item_id"] for f in eng.kg_context()["advisory"]["reexaminable_verdicts"]]


def _stored(eng) -> "list[dict]":
    con = sqlite3.connect(eng.projector.db_path)
    try:
        return json.loads(con.execute("SELECT value FROM meta WHERE key='reexaminable_verdicts'").fetchone()[0])
    finally:
        con.close()


def _flagged(eng, tmp):
    eid = _rejected(eng)
    eng.kg_context()                                       # the projection that sees the sources once
    name = _add(eng, tmp, "preprint.md", PREPRINT)
    assert eid in _listed(eng)
    return eid, name


def _queued(plan) -> "list[dict]":
    return [i for b in plan["batches"] for i in b]


# --------------------------------------------------------------------------- the flag is answered

def test_a_second_look_that_keeps_the_rejection_answers_the_flag(rig):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    out = eng.kg_ground(eid, "rejected", note="no-support: re-read against the preprint, which asserts no bridge")
    assert out["ok"] and out["from"] == "rejected"
    assert eid not in _listed(eng)                         # 0.22.3 kept it here on every later pass
    assert eid not in _listed(eng)


def test_a_later_source_flags_the_answered_item_again(rig):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    eng.kg_ground(eid, "rejected", note="no-support: re-read against the preprint")
    assert eid not in _listed(eng)
    second = _add(eng, tmp, "study.md", "## Results\n\nGamma bridges delta again, a second study says.\n")
    flag = next(f for f in eng.kg_context()["advisory"]["reexaminable_verdicts"] if f["item_id"] == eid)
    assert flag["files"] == [second]                       # raised by the new text only


def test_a_verdict_on_another_item_does_not_answer_a_flag(rig):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    other = _rejected(eng, "omega", "sigma")
    assert eng.kg_ground(other, "rejected", note="no-support: still nothing")["ok"]
    assert eid in _listed(eng)


def test_the_mark_is_stored_and_never_shown(rig):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    stored = next(f for f in _stored(eng) if f["item_id"] == eid)
    assert isinstance(stored[REEX_MARK], int) and stored[REEX_MARK] > 0
    shown = next(f for f in eng.kg_context()["advisory"]["reexaminable_verdicts"] if f["item_id"] == eid)
    assert REEX_MARK not in shown


def test_the_audit_index_orders_records_by_their_place_in_the_log(tmp_path):
    log = tmp_path / GROUND_AUDIT
    records = [{"key": "e_a", "from": "unverified", "to": "rejected", "by": "agent", "at": "2026-11-21T10:00:00+00:00"},
               {"_ckpt": 1, "consumed": {}, "epistemic": {}, "at": "2026-11-21T10:00:01+00:00"},
               {"key": "node:n", "from": "unverified", "to": "rejected", "by": "agent", "at": "2026-11-22T09:00:00+00:00"}]
    log.write_text("".join(json.dumps(r) + "\n" for r in records) + "not json\n", encoding="utf-8")
    ix = read_audit_index(log)
    assert ix.size == log.stat().st_size and set(ix.last) == {"e_a", "node:n"}
    first, third = 0, len(json.dumps(records[0])) + 1 + len(json.dumps(records[1])) + 1
    assert ix.last["node:n"] == third and ix.mark_after("2026-11-21T12:00:00+00:00") == third
    assert ix.mark_after("2026-11-23T00:00:00+00:00") == ix.size
    assert ix.judged_since(audit_key("node", "n"), third) and not ix.judged_since("e_a", first + 1)
    assert read_audit_index(tmp_path / "missing.jsonl").size == 0 and AuditIndex().last == {}


# --------------------------------------------------------------------------- the plan queues them

def test_the_plan_queues_every_open_flag_after_the_new_work(rig):
    eng, tmp = rig
    ids = []
    eng.kg_propose({"edges": [{"source": "alpha", "target": f"beta-{i}", "relation": "bridges"} for i in range(52)]})
    for i in range(52):
        eid = edge_id("alpha", "bridges", f"beta-{i}")
        assert eng.kg_ground(eid, "rejected", note="no-support: nothing joins them")["ok"]
        ids.append(eid)
    eng.kg_propose({"edges": [{"source": "omega", "target": "sigma", "relation": "bridges"}]})   # new work
    eng.kg_context()
    _add(eng, tmp, "alpha.md", "## Alpha\n\nAlpha bridges every beta we could find.\n")
    advisory = eng.kg_context()["advisory"]
    assert len(advisory["reexaminable_verdicts"]) == 50 and advisory["reexaminable_verdicts_total"] == 52
    plan = eng.kg_ground_plan()
    items = _queued(plan)
    assert plan["queue"]["reexaminable"] == 52 and plan["queue"]["reexaminable_held"] == 0
    assert items[0] == {"id": edge_id("omega", "bridges", "sigma"), "kind": "edge"}        # new work first
    assert {i["id"] for i in items[1:]} == set(ids)
    assert all(i == {"id": i["id"], "kind": "edge", "reexamine": True} for i in items[1:])
    assert plan["queue"]["edges"] == 1                      # the flagged ones are counted apart


def test_the_progress_probe_drops_an_item_judged_again_without_projecting(rig, monkeypatch):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    assert [i["id"] for i in _queued(eng.kg_ground_plan())] == [eid]
    eng.kg_ground(eid, "rejected", note="no-support: re-read against the preprint")
    monkeypatch.setattr(eng.projector, "project", lambda *a, **k: pytest.fail("the plan projected"))
    plan = eng.kg_ground_plan()
    assert _queued(plan) == [] and plan["queue"]["reexaminable"] == 0


def test_a_flag_no_usable_source_raised_is_counted_not_queued(rig):
    eng, tmp = rig
    eid = _rejected(eng)
    eng.kg_context()
    _add(eng, tmp, "post.md", "Gamma bridges delta, trust me, a post says.\n", level=5)
    eng.kg_context()
    plan = eng.kg_ground_plan()
    assert _queued(plan) == [] and (plan["queue"]["reexaminable"], plan["queue"]["reexaminable_held"]) == (0, 1)


def test_a_focus_keeps_the_flags_it_names(rig):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    assert [i["id"] for i in _queued(eng.kg_ground_plan("gamma"))] == [eid]
    assert _queued(eng.kg_ground_plan("omega")) == []


def test_a_failed_item_is_listed_but_not_queued(rig):
    eng, tmp = rig
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    out = eng.kg_ground(EID, "failed", note="refuted: a counter-example the adversarial pass found")
    assert out["ok"], out
    eng.kg_context()
    _add(eng, tmp, "preprint.md", PREPRINT)
    assert EID in _listed(eng)
    plan = eng.kg_ground_plan()
    assert _queued(plan) == [] and plan["queue"]["reexaminable"] == 0


# --------------------------------------------------------------------------- the grounder's evidence

@pytest.fixture
def field(tmp_path):
    """Both ends of a proposal discussed in a usable note, as on the field graph: the proposal's shared context
    is that note, so only `reexamine` shows the preprint that flagged it."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "notes.md").write_text("## Mecanismos\n\nGamma lowers the cost of every review.\n\n"
                                    "Delta raises the cost of every review.\n", encoding="utf-8")
    eng = KGEngine(project, source_path=notes, pack_path=PACK)
    out = eng.kg_write({
        "nodes": [{"id": "gamma", "label": "gamma", "node_type": "operation"},
                  {"id": "delta", "label": "delta", "node_type": "operation"},
                  {"id": "cost", "label": "cost of every review", "node_type": "metric"}],
        "edges": [{"source": "gamma", "target": "cost", "relation": "approximates",
                   "span": "Gamma lowers the cost of every review", "source_file": "notes.md"},
                  {"source": "delta", "target": "cost", "relation": "approximates",
                   "span": "Delta raises the cost of every review", "source_file": "notes.md"}]})
    assert out["dispositions"]["ACCEPTED"] == 5, out
    return eng, tmp_path


def test_the_grounder_gets_the_text_that_raised_the_flag(field):
    eng, tmp = field
    eid = _rejected(eng)
    eng.kg_context()
    name = _add(eng, tmp, "preprint.md", PREPRINT)
    eng.kg_context()
    item = eng.kg_ground_item(eid, "edge")
    shared = {s["source_file"] for s in item["shared_context"]["sections"]}
    assert shared == {"notes.md"} and item["support_context"] is None       # all a 0.22.3 grounder saw
    reex = item["reexamine"]
    assert reex["reason"] == "source-set-changed-since-judged"
    assert [f["file"] for f in reex["files"]] == [name] and reex["files"][0]["usable"] is True
    sections = reex["context"]["sections"]
    assert sections and {s["source_file"] for s in sections} == {name}
    assert "Gamma bridges delta" in sections[0]["excerpt"]
    eng.kg_ground(eid, "rejected", note="no-support: re-read against the preprint")
    assert eng.kg_ground_item(eid, "edge")["reexamine"] is None


def test_an_item_with_no_open_flag_has_no_reexamine(field):
    eng, _ = field
    eid = _rejected(eng)
    assert eng.kg_ground_item(eid, "edge")["reexamine"] is None
    assert eng.kg_ground_item("gamma", "node")["reexamine"] is None


def test_a_flagged_node_gets_the_sections_of_its_sources(rig):
    eng, tmp = rig
    eng.kg_propose({"nodes": [{"id": "gamma-claim", "label": "Gamma bridges delta", "node_type": "claim",
                               "body": "Gamma bridges delta in real factories."}]})
    assert eng.kg_ground("gamma-claim", "rejected", kind="node", note="no-support: the notes never say it")["ok"]
    eng.kg_context()
    name = _add(eng, tmp, "preprint.md", PREPRINT)
    eng.kg_context()
    item = eng.kg_ground_item("gamma-claim", "node")
    assert {s["source_file"] for s in item["reexamine"]["context"]["sections"]} == {name}
    assert [i for i in _queued(eng.kg_ground_plan())] == [{"id": "gamma-claim", "kind": "node", "reexamine": True}]


# --------------------------------------------------------------------------- flags across copies and versions

def test_a_new_copy_of_the_source_adds_its_name_to_the_flag(rig):
    eng, tmp = rig
    eid, old = _flagged(eng, tmp)
    new = _add(eng, tmp, "preprint-v2.md", PREPRINT.replace("fifteen", "fifteen full"))
    flag = next(f for f in eng.kg_context()["advisory"]["reexaminable_verdicts"] if f["item_id"] == eid)
    assert flag["files"] == sorted([old, new])
    assert eng.kg_source_set(old, marks="superseded")["ok"]
    assert eid in _listed(eng)                              # 0.22.3 held it: its only file was superseded
    assert [i["id"] for i in _queued(eng.kg_ground_plan())] == [eid]


def test_a_flag_from_before_0_22_4_counts_only_later_verdicts(rig):
    eng, tmp = rig
    eid, _ = _flagged(eng, tmp)
    # As 0.22.3 left it: no mark in the flag, no projection time in the index, and the rejection long before.
    log = eng.canon.root / GROUND_AUDIT
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    for rec in lines:
        rec["at"] = "2000-01-01T00:00:00+00:00"
    log.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    con = sqlite3.connect(eng.projector.db_path)
    flags = json.loads(con.execute("SELECT value FROM meta WHERE key='reexaminable_verdicts'").fetchone()[0])
    con.execute("UPDATE meta SET value=? WHERE key='reexaminable_verdicts'",
                (json.dumps([{k: v for k, v in f.items() if k != REEX_MARK} for f in flags]),))
    con.execute("UPDATE meta SET value=? WHERE key='projected_at'", ("2000-01-02T00:00:00+00:00",))
    con.commit()
    con.close()
    assert [i["id"] for i in _queued(eng.kg_ground_plan())] == [eid]   # the old rejection does not answer it
    eng.kg_ground(eid, "rejected", note="no-support: re-read against the preprint")
    assert _queued(eng.kg_ground_plan()) == []
    assert eid not in _listed(eng)                          # the projection adopts the same mark


# --------------------------------------------------------------------------- a source flags what it has a passage about

def test_a_word_of_the_verdict_notes_flags_nothing(rig):
    eng, tmp = rig
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    assert eng.kg_ground(EID, "rejected", note="no-support: neither source states it; untested")["ok"]
    eng.kg_context()
    _add(eng, tmp, "essay.md", "## Essay\n\nNeither source agrees, and the claim stays untested.\n")
    assert EID not in _listed(eng)                          # 0.22.3 flagged it on its own note's words


def test_one_shared_word_or_two_in_different_paragraphs_flag_nothing(rig):
    eng, tmp = rig
    _rejected(eng)
    eng.kg_context()
    _add(eng, tmp, "one.md", "## One\n\nGamma is all this text is about.\n")
    _add(eng, tmp, "two.md", "## Two\n\nGamma is one thing.\n\nDelta is quite another.\n")
    assert EID not in _listed(eng)
    _add(eng, tmp, "both.md", "## Both\n\nGamma and delta meet here.\n")
    assert EID in _listed(eng)


def test_numbers_are_not_words_of_a_claim(rig):
    eng, tmp = rig
    eng.kg_propose({"nodes": [{"id": "merge-claim", "label": "Factories merged 11 of 14 pull requests",
                               "node_type": "claim"}]})
    assert eng.kg_ground("merge-claim", "rejected", kind="node", note="no-support")["ok"]
    eng.kg_context()
    _add(eng, tmp, "days.md", "## Days\n\nOver 11 days, 14 agents ran.\n")
    assert "merge-claim" not in _listed(eng)


def _as_before_0_22_4(eng, files_of=None, rules="4"):
    """Rewrite the stored flags as an older engine left them: no mark, the files given per item (none for a
    flag from before 0.22.3), the projection rules of 0.22.3; and every verdict long before any file changed."""
    log = eng.canon.root / GROUND_AUDIT
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    for rec in lines:
        rec["at"] = "2000-01-01T00:00:00+00:00"
    log.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    con = sqlite3.connect(eng.projector.db_path)
    flags = []
    for f in json.loads(con.execute("SELECT value FROM meta WHERE key='reexaminable_verdicts'").fetchone()[0]):
        f = {k: v for k, v in f.items() if k not in (REEX_MARK, "files")}
        if files_of and files_of.get(f["item_id"]):
            f["files"] = files_of[f["item_id"]]
        flags.append(f)
    con.execute("UPDATE meta SET value=? WHERE key='reexaminable_verdicts'", (json.dumps(flags),))
    con.execute("UPDATE meta SET value=? WHERE key='projection_rules'", (rules,))
    con.commit()
    con.close()


def _old_rule_flags(eng, tmp):
    """Two rejected items the old one-word rule flagged when a preprint came: one it has a passage about, one it
    shares a single word with."""
    eid = _rejected(eng)
    other = _rejected(eng, "omega", "sigma")
    eng.kg_context()
    name = _add(eng, tmp, "preprint.md", PREPRINT + "\nOmega was never measured.\n")
    eng.kg_context()
    con = sqlite3.connect(eng.projector.db_path)       # what the one-word rule had stored: both items
    con.execute("UPDATE meta SET value=? WHERE key='reexaminable_verdicts'", (json.dumps(
        [{"item_id": i, "kind": "edge", "state": "rejected", "reason": "source-set-changed-since-judged"}
         for i in (eid, other)]),))
    con.commit()
    con.close()
    return eid, other, name


def test_the_first_read_after_the_upgrade_retests_the_older_flags(rig):
    eng, tmp = rig
    eid, other, name = _old_rule_flags(eng, tmp)
    _as_before_0_22_4(eng)
    assert eng.projector.is_stale()                         # PROJECTION_RULES "5": the first read rebuilds
    flags = {f["item_id"]: f for f in eng.kg_context()["advisory"]["reexaminable_verdicts"]}
    assert flags[eid]["files"] == [name]                    # the preprint has a passage about it
    assert other not in flags                               # one shared word: dropped
    stored = {f["item_id"]: f for f in _stored(eng)}
    assert isinstance(stored[eid][REEX_MARK], int)


def test_a_0_22_3_flag_is_retested_against_the_files_it_names(rig):
    eng, tmp = rig
    eid, other, name = _old_rule_flags(eng, tmp)
    post = _add(eng, tmp, "post.md", "Omega, sigma and the rest.\n", level=5)
    eng.kg_context()
    _as_before_0_22_4(eng, files_of={eid: [name], other: [name]})
    assert set(_listed(eng)) == {eid}                       # the other one's file has no passage about it


def test_an_older_flag_no_file_changed_after_is_kept_as_it_was(rig):
    eng, tmp = rig
    eid, _, _ = _old_rule_flags(eng, tmp)
    _as_before_0_22_4(eng)
    log = eng.canon.root / GROUND_AUDIT                     # every verdict after every file's last change
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    for rec in lines:
        rec["at"] = "2999-01-01T00:00:00+00:00"
    log.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    con = sqlite3.connect(eng.projector.db_path)
    con.execute("UPDATE meta SET value=? WHERE key='projected_at'", ("2999-01-02T00:00:00+00:00",))
    con.commit()
    con.close()
    flags = {f["item_id"]: f for f in eng.kg_context()["advisory"]["reexaminable_verdicts"]}
    assert eid in flags and "files" not in flags[eid]       # nothing says what raised it: kept as it was


def test_the_plan_retests_the_older_flags_before_the_rebuild(rig):
    eng, tmp = rig
    eid, other, _ = _old_rule_flags(eng, tmp)
    _as_before_0_22_4(eng)
    plan = eng.kg_ground_plan()                             # no projection yet: the plan applies the same test
    assert [i["id"] for i in _queued(plan) if i.get("reexamine")] == [eid]


# --------------------------------------------------------------------------- the texts

def test_the_command_leaves_the_second_look_to_the_grounders():
    flat = _flat(GROUND_CMD)
    assert ("`mcp__plugin_burgess_burgess__kg_context(query=\"$ARGUMENTS\")` first, and keep its `advisory` block"
            in flat)
    assert "In Stage 0's `kg_context` advisory, read `advisory.reexaminable_verdicts[]`" in flat
    assert "**Do not re-check them yourself.**" in flat
    assert "For each `item_id`, decide whether the source now supports it" not in flat
    assert "`<id> (node, re-examine)` or `<id> (edge, re-examine)`" in flat
    assert "- e_cold-brew-launch__bridges__summer-menu (edge, re-examine)" in GROUND_CMD
    assert "a rejection again is a verdict too, and it answers the re-examination" in flat
    assert "A re-examined item drops out once a grounder has given it a new verdict" in flat


def test_the_grounder_always_stamps_a_re_examined_item():
    flat = _flat(GROUNDER)
    assert "**Always stamp one**, rejected again included" in flat
    assert "Never record a re-examined item with `kg_record_unsupported`" in flat
    assert "`reexamine.context` is what is new" in flat


def test_the_tool_texts_describe_the_answer_and_the_queue():
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
    assert "`queue.reexaminable`" in _flat(mcp.tools["kg_ground_plan"].__doc__)
    assert "gets `reexamine`" in _flat(mcp.tools["kg_ground_item"].__doc__)
    assert "lasts until its item's next verdict, whatever it is" in _flat(mcp.tools["kg_context"].__doc__)
    flat = _flat(TOOLS)
    assert "**`queue.reexaminable` (0.22.4):**" in flat and "`reexamine` (0.22.4)" in flat
    assert "Since 0.22.4 a flag lasts until its item is judged again, whatever the verdict" in flat
