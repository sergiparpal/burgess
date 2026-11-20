"""0.19.6: /burgess:kg-diverge saves every idea of a session through the engine, with the explanation each idea
was shown with.

Field sessions (Windows, 2026-11-16 to 11-19, and 2026-11-19): at the end of both, the user asked for every idea in
a Markdown file, each one explained. No tool returned the ideas, so the agent built the file itself. On 2026-11-19
it read the session store (`.kg/diverge/<brief>/session/candidates.json`) and its own transcript with Bash
scripts, dug the explanations of the rounds before two compactions out of that transcript, and generated the
Markdown with a 37 KB script run through Bash: ten permission prompts, about two hours of waiting. 0.19.5 then told
the command never to read `.kg/diverge/`, which left the export with no sanctioned path at all.

Now each candidate carries the `explanation` the agent shows the user, kept on its record and never embedded;
each record notes its batch and the slates that showed it; and kg_diverge_export writes the file under the
brief's own state folder. Never in the project root: in the field that folder is the source folder, and
/burgess:kg-build would read an export there as a source document.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg_engine.divergence import export_ideas, pipeline
from kg_engine.divergence.__main__ import main as cli_main
from kg_engine.divergence.config import Candidate, ConfigError
from kg_engine.divergence.state import State
from kg_engine.server import KGEngine, _register
from kg_engine.sources import SourceSet

REPO = Path(__file__).resolve().parents[1]
DIVERGE = (REPO / "commands" / "kg-diverge.md").read_text(encoding="utf-8")
SERVER = REPO / "scripts" / "kg_engine" / "server.py"
PACK = REPO / "pack" / "pack.yaml"

AXES = {"domain": "d", "unit_of_generation": "idea", "candidates_per_generation": 6, "slate_size": 4,
        "axes": [{"name": "form", "type": "categorical"},
                 {"name": "boldness", "type": "continuous", "range": [0.0, 1.0]},
                 {"name": "mechanism", "type": "open", "primary_novelty": True}]}
FIRST = ["tides", "orchards", "ledgers", "kites", "prisms", "anvils"]
SECOND = ["beacons", "mosaics", "embers", "compasses", "signals", "lanterns"]
NOW = datetime(2026, 11, 20, 9, 41, tzinfo=timezone(timedelta(hours=1)))


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_PROJECT_DIR", raising=False)
    monkeypatch.setenv("KG_DIVERGE_HOME", str(tmp_path / "diverge-home"))


def _batch(tag: str, words: list[str], explain: bool = True, parents: list[str] | None = None) -> list[dict]:
    out = []
    for i, w in enumerate(words):
        cand = {"id": f"{tag}{i}", "text": f"{tag} idea {i}: steer the work with {w}",
                "descriptor": {"form": f"f{i % 3}", "boldness": i / 5, "mechanism": f"{w} mechanism"},
                "genealogy": {"operator_id": "analogy", "parents": parents or []}}
        if explain:
            cand["explanation"] = f"  How {w} would work in practice.\nFor example, a team that tracks {w}.  "
        out.append(cand)
    return out


def _session(project: str = "brief", session: str = "sess-1") -> tuple[dict, dict]:
    pipeline.init_project(project, AXES, seed=1120, session=session)
    r1 = pipeline.ingest(project, _batch("a", FIRST), AXES, seed=1120)
    r2 = pipeline.ingest(project, _batch("b", SECOND, parents=["a0"]), AXES, seed=1120)
    return r1, r2


def _home() -> Path:
    return Path(os.environ["KG_DIVERGE_HOME"])


def _entry(text: str, cid: str) -> str:
    """One idea's block of an export: from its heading to the next heading."""
    m = re.search(rf"^### {re.escape(cid)}\b.*?(?=^##)", text + "\n##", flags=re.M | re.S)
    assert m, f"no entry for {cid}"
    return m.group(0)


class FakeMCP:
    """Captures registered wrapper callables (same idiom as tests/fusion/test_diverge_surface.py)."""

    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


# --------------------------------------------------------------------------- #
# 1. the explanation travels with the idea and never moves it
# --------------------------------------------------------------------------- #
def test_an_explanation_is_kept_on_the_record_and_on_later_slates():
    pipeline.init_project("brief", AXES, session="s1")
    cands = _batch("a", FIRST)
    del cands[0]["explanation"]
    out = pipeline.ingest("brief", cands, AXES)
    store = State("brief").read_candidates()
    assert set(store) == {f"a{i}" for i in range(6)}, "every idea survives dedup in this fixture"
    assert store["a1"]["explanation"] == "How orchards would work in practice.\nFor example, a team that tracks orchards."
    assert "explanation" not in store["a0"]  # none sent, none stored: the record keeps its old shape
    for item in out["slate"]:
        assert ("explanation" in item) == (item["id"] != "a0")
        if item["id"] != "a0":
            assert item["explanation"] == store[item["id"]]["explanation"]


def test_an_explanation_must_be_text():
    base = {"id": "x", "text": "an idea", "descriptor": {}}
    assert Candidate.from_dict(dict(base, explanation=None)).explanation == ""
    assert "explanation" not in Candidate.from_dict(base).to_dict()
    with pytest.raises(ConfigError, match="'explanation' must be a string"):
        Candidate.from_dict(dict(base, explanation=["two", "lines"]))


def _geometry(project: str, explain: bool) -> dict:
    pipeline.init_project(project, AXES, seed=3, session="s1")
    r1 = pipeline.ingest(project, _batch("a", FIRST, explain=explain), AXES, seed=3)
    r2 = pipeline.ingest(project, _batch("b", SECOND, explain=explain), AXES, seed=3)
    st = State(project)
    return {"slates": [r1["slate_ids"], r2["slate_ids"]],
            "novelty": [[s["novelty"] for s in r["slate"]] for r in (r1, r2)],
            "cosine": [r1["monitor"]["mean_cosine"], r2["monitor"]["mean_cosine"]],
            "archive": st.read_archive(), "embeddings": st.read_embeddings()}


def test_the_explanation_never_moves_an_idea():
    # geometry reads `text` alone (I5): the same ideas with and without explanations land, score and slate
    # identically
    assert _geometry("with", True) == _geometry("without", False)


def test_records_note_their_batch_and_the_slates_that_showed_them():
    r1, r2 = _session()
    store = State("brief").read_candidates()
    assert {store[f"a{i}"]["batch"] for i in range(6)} == {1}
    assert {store[f"b{i}"]["batch"] for i in range(6)} == {2}
    for cid, rec in store.items():
        expected = [b for b, r in ((1, r1), (2, r2)) if cid in r["slate_ids"]]
        assert rec.get("slated_in", []) == expected, cid
    assert any(not rec.get("slated_in") for rec in store.values()), "slate_size 4 leaves ideas unshown"


# --------------------------------------------------------------------------- #
# 2. the export: every idea, what was done with it, and nothing else touched
# --------------------------------------------------------------------------- #
def test_export_writes_every_idea_with_what_was_done_with_it():
    r1, r2 = _session()
    pin, loser = r1["slate_ids"][0], r1["slate_ids"][1]
    pipeline.remember("brief", {"type": "pin", "id": pin})
    pipeline.remember("brief", {"type": "discard", "id": "b5"})
    pipeline.remember("brief", {"type": "comparison", "winner": pin, "loser": loser})
    st = State("brief")
    st.write_materialized({pin: {"nodes": ["steer-the-work"], "edges": [], "session": "sess-1"}})
    st.write_candidates({**st.read_candidates(),
                         "b3": {k: v for k, v in st.read_candidates()["b3"].items() if k != "explanation"}})

    out = export_ideas.export_ideas("brief", brief="How should a team steer agent work?\nGive mechanisms.",
                                    now=NOW)
    path = Path(out["path"])
    assert path == (_home() / "brief" / "ideas-brief-sess-1.md").resolve() and path.is_file()
    assert out["ideas"] == 12 and out["batches"] == 2 and out["session_id"] == "sess-1"
    assert out["pinned"] == [pin] and out["discarded"] == ["b5"] and out["comparisons"] == 1
    assert out["unexplained"] == ["b3"]
    text = path.read_text(encoding="utf-8")
    assert out["bytes"] == len(text.encode("utf-8"))

    assert text.startswith("# Ideas: brief\n\n> How should a team steer agent work?\n> Give mechanisms.\n")
    assert "12 ideas in 2 batches · session `sess-1` · seed 1120 · exported 2026-11-20T09:41+01:00" in text
    assert "Axes: form, boldness (0–1), mechanism (open)" in text
    assert f"Pinned: {pin} · Discarded: b5 · Comparisons: 1" in text
    assert text.index("## Batch 1") < text.index("## Batch 2")
    for w in FIRST + SECOND:
        assert f"steer the work with {w}" in text
        assert f"mechanism: {w} mechanism" in text
    assert "How orchards would work in practice.\nFor example, a team that tracks orchards." in text
    assert "How compasses would work in practice." not in text  # b3's explanation was taken away above
    assert f"### {pin} (pinned)" in text and "### b5 (discarded)" in text
    entry = _entry(text, pin)
    assert f"- mechanism: {FIRST[int(pin[1:])]} mechanism\n- form: f" in entry and "· boldness: " in entry
    assert "- operator: analogy\n" in entry
    assert re.search(r"on the slate in batch(es)? 1\b", entry) and "· pinned" in entry
    assert f"beat {loser}" in entry and "in the graph as `steer-the-work`" in entry
    assert f"lost to {pin}" in _entry(text, loser)
    assert "- operator: analogy · parents: a0" in _entry(text, "b0")
    store = State("brief").read_candidates()
    never = [cid for cid, rec in store.items() if not rec.get("slated_in")]
    assert never and all("never on the slate" in _entry(text, cid) for cid in never)


def test_export_changes_no_state():
    _session()
    pipeline.remember("brief", {"type": "pin", "id": "a0"})
    root = _home() / "brief"
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = export_ideas.export_ideas("brief", now=NOW)
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert set(after) - set(before) == {Path(out["path"])}
    assert all(after[p] == data for p, data in before.items())


def test_export_never_lands_in_the_source_folder(tmp_path, monkeypatch):
    # The field layout: the project folder is the source folder (source_path = the folder of .md documents).
    monkeypatch.delenv("KG_DIVERGE_HOME", raising=False)
    proj = tmp_path / "prueba"
    proj.mkdir()
    (proj / "notes.md").write_text("# A source document\n\nSome text.\n", encoding="utf-8")
    engine = KGEngine(proj, pack_path=PACK, source_path=proj)
    mcp = FakeMCP()
    _register(mcp, engine)
    t = mcp.tools
    assert t["kg_diverge_init"](project="brief", axes=AXES, session="sess-1")["ok"]
    t["kg_diverge_ingest"](project="brief", candidates=_batch("a", FIRST), axes=AXES)
    out = t["kg_diverge_export"](project="brief", brief="the brief")
    path = Path(out["path"])
    assert path.is_file() and (proj / ".kg" / "diverge").resolve() in path.parents
    # neither a directory source nor a recursive glob reads it ...
    assert SourceSet.resolve(proj) == [proj / "notes.md"]
    assert [p.name for p in SourceSet.resolve(str(proj / "**" / "*.md"))] == ["notes.md"]
    # ... which is the point: the same file in the project root would be a source document
    shutil.copy(path, proj / path.name)
    assert path.name in [p.name for p in SourceSet.resolve(proj)]


def test_one_file_per_session():
    _session(session="sess-1")
    first = export_ideas.export_ideas("brief", now=NOW)
    pipeline.remember("brief", {"type": "pin", "id": "a2"})
    again = export_ideas.export_ideas("brief", now=NOW)
    assert again["path"] == first["path"] and "a2" in again["pinned"]
    kept = Path(first["path"]).read_text(encoding="utf-8")
    # a new session wipes the archive (I10) and exports to its own file; the earlier one is left alone
    pipeline.init_project("brief", AXES, seed=1120, session="sess-2")
    pipeline.ingest("brief", _batch("c", ["harbors", "quilts", "meters"]), AXES, seed=1120)
    later = export_ideas.export_ideas("brief", now=NOW)
    assert later["path"] != first["path"] and later["path"].endswith("ideas-brief-sess-2.md")
    assert later["ideas"] == 3
    assert Path(first["path"]).read_text(encoding="utf-8") == kept
    # the pin of sess-1 is named, though its record ended with that session
    text = Path(later["path"]).read_text(encoding="utf-8")
    assert "Pinned in an earlier session and not in this file" in text and "a2." in text


def test_export_without_ideas_says_why():
    with pytest.raises(ConfigError, match="call kg_diverge_init"):
        export_ideas.export_ideas("never-inited")
    _session(session="sess-1")
    pipeline.init_project("brief", AXES, seed=1120, session="sess-2")  # a new session wipes the records
    with pytest.raises(ConfigError, match="no ideas in its current session.*sess-2"):
        export_ideas.export_ideas("brief")


def test_the_cli_exports_too(capsys):
    _session()
    assert cli_main(["export", "--project", "brief", "--brief", "the brief"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ideas"] == 12 and Path(out["path"]).is_file()


# --------------------------------------------------------------------------- #
# 3. the tool and the command say how to use it
# --------------------------------------------------------------------------- #
def _tool_doc(name: str) -> str:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name and any(
                ast.unparse(d).startswith("mcp.tool") for d in node.decorator_list):
            return _flat(ast.get_docstring(node) or "")
    raise AssertionError(f"no MCP tool {name}")


def test_the_tool_descriptions_say_what_is_kept_and_where_the_file_goes():
    doc = _tool_doc("kg_diverge_export")
    assert "Call it when the user ends the session or asks to save the ideas" in doc
    assert "under .kg/diverge/<project>/" in doc and "never in the project root" in doc
    assert "Never assemble the file yourself" in doc
    ingest = _tool_doc("kg_diverge_ingest")
    assert '"explanation"' in ingest and "never embeds it" in ingest


def test_the_command_writes_explanations_and_saves_through_the_engine():
    flat = _flat(DIVERGE)
    front = DIVERGE.split("---", 2)[1]
    assert "mcp__plugin_burgess_burgess__kg_diverge_export" in front and "Bash" not in front
    assert "*Layer 3 — the explanation.* Write the `explanation` you will show the user in step 7" in flat
    assert '"explanation": "two or three plain lines: how it works in practice, and one concrete example"' in flat
    assert "Present the explanation you ingested, so what the user reads is what the export keeps." in flat
    assert "Those lines are the explanation you ingested it with." in flat
    step = flat[flat.index("11. **Save the ideas**"):]
    assert "Call `kg_diverge_export(project, brief)` once" in step
    assert "Never build the file yourself: no Bash, no script, no writing it out with Write" in step
    assert "never in the project folder, because the project folder can be the source folder" in step
    assert "a single copy command, which asks for permission once" in step
    assert "`kg_diverge_export` writes every idea of the session to a file for the user (step 11)" in flat
