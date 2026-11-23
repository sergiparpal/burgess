"""0.24.2: a scout runs the three searches it owes every item, and reads a work's own page.

On the field run of 2026-11-23 (`/burgess:kg-sources find`, six waiting ideas of `prueba-burgess`), two scouts with
three items each ran no `against` search for any of the six and the web search for two; the scout given one item
an hour earlier had run all three. The user was shown candidates nobody had tried to refute. The scout also left
unread a promising work it had seen only through a summary (DeLoop, on agents stuck in loops).

Now `kg_source_record_search` answers which required searches the log does not hold for the item yet
(`missing`: the catalogue for and against, and the web for), and the scout must run them before it reports.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from kg_engine import evidence as ev
from kg_engine.model import Node, Provenance
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
SCOUT = (REPO / "agents" / "scout.md").read_text(encoding="utf-8")
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
PIN = "pin-stigmergy"


def _flat(text: str) -> str:
    return " ".join(text.split())


class _Resp:
    def __init__(self, body: bytes, ctype: str, url: str):
        self._body, self._url = body, url
        self.headers = Message()
        self.headers["Content-Type"] = ctype

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def eng(tmp_path, monkeypatch):
    state = {"answer": (json.dumps({"results": []}).encode(), "application/json")}

    def urlopen(req, timeout):
        body = state["answer"]
        if isinstance(body, Exception):
            raise body
        return _Resp(body[0], body[1], req.full_url)

    monkeypatch.setattr(ev, "_urlopen", urlopen)
    monkeypatch.setattr(ev, "_sleep", lambda s: None)          # 0.24.3 paces catalogue calls: no real waiting
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text("## Notes\n\nEntropy grounds the arrow of time.\n", encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label="Builder agents coordinate through stigmergy", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED,
                              body="Builder agents coordinate through stigmergy.\n\n[diverge] pinned candidate=c0")],
                        message="pin")
    return e, state


def _record(e, **kw):
    return e.kg_source_record_search(PIN, searches=kw.pop("searches", []), proposed=kw.pop("proposed", []),
                                     note=kw.pop("note", ""))


def test_a_record_names_the_searches_still_owed(eng):
    e, _ = eng
    out = _record(e, note="nothing searched yet")
    assert out["missing"] == ["openalex for", "openalex against", "web for"] and "run the missing" in out["hint"]
    e.kg_source_search("stigmergy software agents", item_id=PIN, stance="for")
    out = _record(e, searches=[{"query": "stigmergy agents coordination", "stance": "for", "results": 3}])
    assert out["missing"] == ["openalex against"]
    e.kg_source_search("stigmergy fails to coordinate agents", item_id=PIN, stance="against")
    out = _record(e)
    assert out["missing"] == [] and "hint" not in out


def test_a_failed_catalogue_search_is_owed_to_the_web(eng):
    # 0.24.3: through 0.24.2 a failed catalogue search counted as tried, so an item whose search against was
    # refused got no search against at all; now the web owes that stance
    e, state = eng
    state["answer"] = urllib.error.URLError("offline")
    for stance in ("for", "against"):
        assert e.kg_source_search("stigmergy agents", item_id=PIN, stance=stance)["error"] == "search-failed"
    assert _record(e, searches=[{"query": "stigmergy", "stance": "for", "results": 0}])["missing"] == ["web against"]


def test_a_spent_budget_moves_the_catalogue_searches_to_the_web(eng):
    e, state = eng
    state["answer"] = urllib.error.HTTPError("u", 429, "Too Many", {"X-RateLimit-Remaining-USD": "0"}, None)
    assert e.kg_source_search("stigmergy agents", item_id=PIN)["error"] == "search-budget"
    out = _record(e, searches=[{"query": "stigmergy agents", "stance": "for", "results": 4}])
    assert out["missing"] == ["web against"]


def test_only_the_recent_searches_count(eng, monkeypatch):
    e, _ = eng
    e.kg_source_search("stigmergy agents", item_id=PIN, stance="for")
    monkeypatch.setattr(KGEngine, "FIND_RUN_WINDOW_S", -60)          # every logged search is now too old
    assert _record(e)["missing"] == ["openalex for", "openalex against", "web for"]


def test_the_scout_owes_every_item_three_searches():
    body = _flat(SCOUT)
    assert "three searches for every item, whatever the other items found" in body
    assert "Never skip the **against** search" in body
    assert "The answer's `missing` lists the required searches the log does not hold for this item yet." in body
    assert "find its own page (its arXiv or DOI page" in body
    assert "Each item is owed three searches" in _flat(COMMAND)
    assert "`missing` (0.24.2)" in _flat(TOOLS)
