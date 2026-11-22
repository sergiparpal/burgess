"""0.22.2: while no source is usable, the plan says so and the re-examination list is held back.

Field pass of 2026-11-22 on 0.22.1 (Windows, prueba-burgess): the project required level 1 and every source was
level 4. `/burgess:kg-ground` queued nothing and launched no grounder, as intended. But its plan read
`blocked: null`, because the block was reported only when it left something out and every pin was already
waiting, although the command says it is set whenever no source is usable. And `kg_context` listed 113 rejected
items as re-examinable: they had been flagged when a preprint was registered under level 4, flags last until
an item is judged again, and the projector that raises them knows nothing of the policy, so they would have
shown on every pass. The agent rightly re-checked none of them.

Now `blocked` is set whenever nothing is usable, and `kg_context` holds the list back
(`advisory.reexaminable_held`) while nothing is usable, keeping the stored flags so they return when a source
counts again.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.model import Node, Provenance, edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")

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


def _add(eng, tmp_path, name, text, level):
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    out = eng.kg_source_add(path=str(folder / name), level=level, role="primary")
    assert out["ok"], out
    return out["name"]


def _rejected_proposal(eng):
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    eid = edge_id("gamma", "bridges", "delta")
    assert eng.kg_ground(eid, "rejected", note="no-support: the notes never join gamma and delta")["ok"]
    return eid


def test_the_block_is_reported_even_when_everything_already_waits(rig):
    eng, _ = rig
    eng.canon.write_one(Node(id="pin-a", label="Gamma bridges delta", node_type="claim",
                             provenance=Provenance.HYPOTHESIZED, body="[diverge] pinned idea: gamma bridges delta"))
    assert eng.kg_record_unsupported("pin-a", kind="node", note="nothing in the notes")["ok"]
    eng.kg_source_policy(required_level=1)
    plan = eng.kg_ground_plan()
    assert plan["batches"] == [] and plan["queue"]["unsupported_waiting"] == 1
    assert plan["blocked"]["reason"] == "no-usable-source"
    assert (plan["blocked"]["items"], plan["blocked"]["hubs"]) == (0, 0)


def test_the_re_examination_list_is_held_while_nothing_is_usable(rig):
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()                                          # the projection that sees the sources once
    _add(eng, tmp, "preprint.md", PREPRINT, 4)                # mentions gamma and delta: a re-look candidate
    advisory = eng.kg_context()["advisory"]
    assert eid in [r["item_id"] for r in advisory["reexaminable_verdicts"]]
    assert "reexaminable_held" not in advisory
    eng.kg_source_policy(required_level=1)                    # the notes and the preprint are level 4
    advisory = eng.kg_context()["advisory"]
    assert advisory["reexaminable_verdicts"] == [] and advisory["reexaminable_verdicts_total"] == 0
    held = advisory["reexaminable_held"]
    assert held["total"] == 1 and held["reason"] == "no-usable-source" and held["required_level"] == 1
    eng.kg_source_policy(required_level=4)                    # the flags were kept: they come back
    advisory = eng.kg_context()["advisory"]
    assert eid in [r["item_id"] for r in advisory["reexaminable_verdicts"]]
    assert "reexaminable_held" not in advisory


def test_a_usable_source_unrelated_to_the_flag_does_not_release_it(rig):
    """0.22.2 held flags only while no source at all was usable, so this flag came back as soon as an unrelated
    level-1 review was registered. Since 0.22.3 it remembers that only the preprint raised it, and stays held
    until the preprint counts (tests/test_fix_reexamination_provenance.py)."""
    eng, tmp = rig
    eid = _rejected_proposal(eng)
    eng.kg_context()
    _add(eng, tmp, "preprint.md", PREPRINT, 4)
    eng.kg_source_policy(required_level=1)
    assert eng.kg_context()["advisory"]["reexaminable_held"]["total"] == 1
    _add(eng, tmp, "review.md", "## Results\n\nA reviewed study of networks.\n", 1)
    advisory = eng.kg_context()["advisory"]
    assert advisory["reexaminable_held"]["reason"] == "raised-by-unusable-source"
    assert eid not in [r["item_id"] for r in advisory["reexaminable_verdicts"]]
    eng.kg_source_policy(required_level=4)
    assert eid in [r["item_id"] for r in eng.kg_context()["advisory"]["reexaminable_verdicts"]]


def test_the_command_reads_the_held_list():
    flat = _flat(GROUND_CMD)
    assert "When `advisory.reexaminable_held` is present (0.22.2), the list is held back" in flat
    assert "even when nothing was left out (0.22.2)" in flat
