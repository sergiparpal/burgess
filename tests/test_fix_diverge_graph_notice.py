"""0.19.8: every /burgess:kg-diverge round ends by saying what reaches the graph.

Two test sessions on 2026-11-21 (Windows, 0.19.7, 60 ideas each) ended with five pins each. Afterwards
the user asked whether the ideas had gone into the graph as candidates, and then why only 10 of 120
could. Nothing in a round said that nothing enters the graph unless the user asks, or that only pinned
ideas can be carried. The pin bullet of step 7 even sent the reader to /burgess:kg-generate's propose
lane, when kg_diverge_materialize is the door. To carry the other 110 ideas they had to be pinned
first, which also made them parents and lifted six discards: the command never said how, or at what
cost.

The engine is unchanged. These tests pin the text, and the pin-first path the text now promises.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_engine.model import EpistemicState, Provenance
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
DIVERGE = (REPO / "commands" / "kg-diverge.md").read_text(encoding="utf-8")
COMMANDS = (REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
TUTORIAL = (REPO / "TUTORIAL.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

NOTICE = ("Nothing goes into the graph unless you ask. If you do, the pinned ideas go in; "
          "name any others and I'll pin them first.")


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
    """A project with a source, the registered tools, one ingested round, c0 pinned and c3 discarded."""
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
    cands = [
        {"id": f"c{i}", "text": f"idea {i}: concept about topic {i} via approach {i}",
         "descriptor": {"angle": f"a{i}", "scope": "broad", "form": f"f{i % 2}",
                        "boldness": (i % 5) / 4.0, "mechanism": f"mechanism {i}"},
         "genealogy": {"operator_id": "analogy", "parents": []}}
        for i in range(6)
    ]
    assert t["kg_diverge_ingest"](project="brief", candidates=cands, axes="generic", seed=5)["slate"]
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "c0"})
    t["kg_diverge_remember"](project="brief", event={"type": "discard", "id": "c3"})
    return engine, t


# ---------------------------------------------------------------------------------------------- the path


def test_an_idea_the_user_names_goes_in_once_it_is_pinned(rig):
    engine, t = rig
    refused = t["kg_diverge_materialize"](project="brief", candidate_ids=["c2"])["results"]
    assert refused[0]["status"] == "refused" and "not-pinned" in refused[0]["reason"]

    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "c2"})
    (res,) = t["kg_diverge_materialize"](project="brief", candidate_ids=["c2"])["results"]
    assert res["status"] == "ACCEPTED", res
    node = engine.canon.read_node("idea-brief-c2")
    assert node.provenance is Provenance.HYPOTHESIZED
    assert node.epistemic_state is EpistemicState.UNVERIFIED


def test_pinning_a_discarded_idea_lifts_its_discard_and_makes_it_a_parent(rig):
    _, t = rig
    assert "c3" in t["kg_diverge_recall"](project="brief")["discards"]
    t["kg_diverge_remember"](project="brief", event={"type": "pin", "id": "c3"})
    recall = t["kg_diverge_recall"](project="brief")
    assert "c3" not in recall["discards"] and "c3" in recall["pins"]
    parents = [p["id"] if isinstance(p, dict) else p
               for p in t["kg_diverge_parents"](project="brief", seed=5)["parents"]]
    assert "c3" in parents
    (res,) = t["kg_diverge_materialize"](project="brief", candidate_ids=["c3"])["results"]
    assert res["status"] == "ACCEPTED", res


# ---------------------------------------------------------------------------------------------- the text


def test_every_round_ends_by_saying_what_reaches_the_graph():
    text = _flat(DIVERGE)
    step7 = text[text.index("7. **Present the returned `slate`**"):text.index("8. **Record & continue.**")]
    assert "end the round by saying what reaches the graph" in step7
    assert "in one line, every round" in step7
    assert NOTICE in step7


def test_the_pin_bullet_names_the_right_door():
    text = _flat(DIVERGE)
    assert "via /burgess:kg-generate's propose lane" not in text
    assert "the only ideas that can go into the graph, when the user asks" in text


def test_the_command_says_how_to_carry_an_idea_that_is_not_pinned():
    text = _flat(DIVERGE)
    assert "When the user names an idea that is not pinned, pin it first with `kg_diverge_remember`" in text
    assert "it is a parent of every later round of this brief" in text
    assert "it lifts the idea's discard if it had one" in text
    assert "comes back in every `/burgess:kg-ground` pass while it stays `unverified`" in text


def test_the_user_docs_say_it_too():
    commands = _flat(COMMANDS)
    assert "Each round ends with a one-line reminder: nothing goes into the graph unless you ask" in commands
    assert "To carry an idea you have not pinned, name it: Claude pins it first" in commands
    assert "every `/burgess:kg-ground` pass judges it again" in commands
    assert "Every round ends with a one-line reminder of this" in _flat(TUTORIAL)
    assert "To carry an idea the user names that is not pinned, pin it first with `kg_diverge_remember`" in _flat(TOOLS)
