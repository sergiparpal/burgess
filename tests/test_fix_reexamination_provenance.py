"""0.22.3: a re-examination flag remembers which sources raised it, and the policy texts say what wakes a waiting
item.

Phase 1 of the field test of 2026-11-22 (Windows, prueba-burgess, on 0.22.2) left the project at level 2 with one
note rated 2. The 113 rejected items flagged when a level-4 preprint was registered showed again, because one
source now counted, so a `/burgess:kg-ground` would have re-checked them against that note, which they had
already been judged against. 0.22.2 held flags only while no source at all was usable. And the session told the
user the policy change would bring back the 119 waiting pins: the `kg_source_policy` description and
`/burgess:kg-sources` still said any change does, the 0.22.0 rule that 0.22.1 had replaced.

Now a new flag records the changed files whose words it shares, and the reader holds it back while every one of
them is unusable; a flag from before keeps the 0.22.2 rule. The texts say that only a usable source the item was
not judged against wakes it.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from kg_engine.model import edge_id
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
SOURCES_CMD = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

NOTES = "## Notes\n\nDegree approximates importance in every sampled network.\n"
PREPRINT = "## Findings\n\nGamma bridges delta in the factories we watched for fifteen days.\n"


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


def _add(eng, tmp_path, name, text, level, marks=""):
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    out = eng.kg_source_add(path=str(folder / name), level=level, role="primary", marks=marks)
    assert out["ok"], out
    return out["name"]


def _rejected_proposal(eng):
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    eid = edge_id("gamma", "bridges", "delta")
    assert eng.kg_ground(eid, "rejected", note="no-support: the notes never join gamma and delta")["ok"]
    return eid


def _listed(eng) -> "list[dict]":
    return eng.kg_context()["advisory"]["reexaminable_verdicts"]


def test_a_new_flag_names_the_files_that_raised_it(rig):
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()
    name = _add(eng, tmp, "preprint.md", PREPRINT, 4)
    flag = next(f for f in _listed(eng) if f["item_id"] == eid)
    assert flag["files"] == [name]


def test_an_unfiltered_source_raises_no_re_check_while_the_notes_count(rig):
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()
    _add(eng, tmp, "post.md", "Gamma bridges delta, trust me, a post says.\n", 5)
    advisory = eng.kg_context()["advisory"]
    assert eid not in [f["item_id"] for f in advisory["reexaminable_verdicts"]]   # the notes are usable
    held = advisory["reexaminable_held"]
    assert held["total"] == 1 and held["reason"] == "raised-by-unusable-source"
    assert held["required_level"] == 4 and "flagged only by sources the policy does not accept" in held["hint"]


def test_a_flag_follows_its_source_s_marks(rig):
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()
    name = _add(eng, tmp, "preprint.md", PREPRINT, 4)
    assert eid in [f["item_id"] for f in _listed(eng)]
    eng.kg_source_set(name, marks="retracted")
    assert eid not in [f["item_id"] for f in _listed(eng)]
    eng.kg_source_set(name, marks="")
    assert eid in [f["item_id"] for f in _listed(eng)]


def test_a_flag_from_before_keeps_the_0_22_2_rule(rig):
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()
    _add(eng, tmp, "preprint.md", PREPRINT, 4)
    eng.kg_context()
    con = sqlite3.connect(eng.projector.db_path)                       # strip `files`, as 0.22.2 stored flags
    flags = json.loads(con.execute("SELECT value FROM meta WHERE key='reexaminable_verdicts'").fetchone()[0])
    con.execute("UPDATE meta SET value=? WHERE key='reexaminable_verdicts'",
                (json.dumps([{k: v for k, v in f.items() if k != "files"} for f in flags]),))
    con.commit()
    con.close()
    eng.kg_source_policy(required_level=2)
    eng.kg_source_set("notes.md", level=2)                             # one source counts: shown, as in 0.22.2
    assert eid in [f["item_id"] for f in eng.projector.kg_context(usable={"notes.md"})["advisory"]
                   ["reexaminable_verdicts"]]
    held = eng.projector.kg_context(usable=set())["advisory"]["reexaminable_held"]
    assert held["reason"] == "no-usable-source"                        # nothing counts: held


def test_the_read_only_hook_path_filters_nothing(rig):
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()
    _add(eng, tmp, "post.md", "Gamma bridges delta, trust me, a post says.\n", 5)
    eng.kg_context()
    advisory = eng.projector.kg_context()["advisory"]                  # no `usable`: as through 0.22.2
    assert eid in [f["item_id"] for f in advisory["reexaminable_verdicts"]] and "reexaminable_held" not in advisory


# --------------------------------------------------------------------------- the texts

def test_the_policy_texts_say_what_wakes_a_waiting_item():
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
    policy = _flat(mcp.tools["kg_source_policy"].__doc__)
    assert "offers again the items waiting for sources;" not in policy
    assert "a stricter one never does" in policy
    assert "Registering a source the policy accepts wakes the items waiting" in _flat(mcp.tools["kg_source_add"].__doc__)
    sources = _flat(SOURCES_CMD)
    assert "A change of policy brings back the items that were waiting for new sources." not in sources
    assert "Never tell the user that a policy change brings them back otherwise." in sources
    assert "When the result's `source.usable` is true, the pins waiting for new sources come back" in sources
    assert "It offers again every item waiting for sources." not in _flat(TOOLS)
    assert "every source that flagged an item is one the policy does not accept now" in _flat(GROUND_CMD)
