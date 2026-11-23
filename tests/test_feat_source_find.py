"""0.24.0: `/burgess:kg-sources find` suggests outside sources for the items waiting for one.

The user asked on 2026-11-21 for a command where Burgess *suggests* sources that could verify or refute what the
graph cannot settle; 0.21.0-0.23.1 built the registry, the levels and the policy, and the suggestions were still
missing. The flow: `kg_source_find` lists the items a grounder recorded as unsupported that still wait, a `kg-scout`
subagent searches OpenAlex through the engine (`kg_source_search`) and the web, the engine reads each candidate
itself (`kg_source_probe`, verbatim passages, never WebFetch), every search is logged
(`kg_source_record_search` for the web ones), and the user registers what they pick with the usual `add`, which
records the items the page was found for (`found_for`).

Through 0.23.1 any new usable source woke every waiting item: in the field one source would have sent all 119
waiting pins of `prueba-burgess` back to a grounder. Since 0.24.0 a new usable source wakes only the items it was
found for and those whose words it contains.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from kg_engine import evidence as ev
from kg_engine.canon import SOURCE_SEARCHES
from kg_engine.model import EpistemicState, Node, Provenance
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
SCOUT = (REPO / "agents" / "scout.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")

NOTES = "## Notes\n\nEntropy grounds the arrow of time. Heat flows from hot to cold.\n"
PIN = "pin-stigmergy"
PIN_BODY = ("Builder agents coordinate through stigmergy: each leaves a trace in the shared repository that steers "
            "the next agent.\n\n[diverge] pinned candidate=c0 brief=factory")
OTHER = "pin-tides"
OTHER_BODY = "Tidal forces slow the rotation of the moon.\n\n[diverge] pinned candidate=c1 brief=factory"
PAGE = ("<html><head><title>Stigmergy in software teams</title>"
        "<meta name=\"citation_journal_title\" content=\"Journal of Coordination\">"
        "<meta name=\"citation_doi\" content=\"10.1234/stig.2025.7\">"
        "<meta name=\"citation_online_date\" content=\"2025/03/04\"></head><body><main>"
        "<h2>Results</h2><p>Agents coordinate through stigmergy when each trace in a shared repository steers the "
        "next agent's work.</p><p>Unrelated paragraph about funding and ethics.</p>"
        "<p>A second look: traces left by builders in the repository steer later builders.</p></main></body></html>")
WORK = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/STIG.2025.7",
        "display_name": "Stigmergy in software teams", "publication_date": "2025-03-04", "type": "article",
        "primary_location": {"landing_page_url": "https://example.org/stig",
                             "source": {"display_name": "Journal of Coordination", "type": "journal"}},
        "best_oa_location": {"landing_page_url": "https://example.org/stig/oa"}, "is_retracted": False,
        "abstract_inverted_index": {"Agents": [0], "coordinate": [1], "through": [2], "stigmergy.": [3]},
        "cited_by_count": 12}


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
def web(monkeypatch):
    """The network, faked: `pages` maps a URL prefix to (body, content type); every request is kept in `seen`."""
    pages: "dict[str, tuple[bytes, str]]" = {}
    seen: "list[str]" = []

    def urlopen(req, timeout):
        url = req.full_url
        seen.append(url)
        for prefix, (body, ctype) in pages.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return _Resp(body, ctype, url)
        raise urllib.error.URLError("no route in the test")

    monkeypatch.setattr(ev, "_urlopen", urlopen)
    monkeypatch.setattr(ev, "_sleep", lambda s: None)          # 0.24.3 paces catalogue calls: no real waiting
    return pages, seen


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text(NOTES, encoding="utf-8")
    e = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    e.canon.write_nodes([Node(id=PIN, label="Builder agents coordinate through stigmergy", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body=PIN_BODY),
                         Node(id=OTHER, label="Tidal forces slow the rotation of the moon", node_type="claim",
                              provenance=Provenance.HYPOTHESIZED, body=OTHER_BODY)], message="pins")
    for iid in (PIN, OTHER):
        assert e.kg_record_unsupported(iid, "node", "no passage states it")["ok"]
    return e


def _queued(engine) -> "list[str]":
    return [i["id"] for b in engine.kg_ground_plan()["batches"] for i in b]


def _ledger(engine) -> "list[dict]":
    path = engine.canon.root / SOURCE_SEARCHES
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _add_file(engine, tmp_path, name, html, **kw):
    f = tmp_path / name
    f.write_bytes(html.encode("utf-8"))
    return engine.kg_source_add(path=str(f), level=kw.pop("level", 1), role="primary", **kw)


# --------------------------------------------------------------------------- the catalogue

def test_the_catalogue_fields():
    assert ev.bare_doi("https://doi.org/10.1007/S10664-026-10965-6.") == "10.1007/s10664-026-10965-6"
    assert ev.bare_doi("doi:10.1234/abc") == "10.1234/abc" and ev.bare_doi("no doi here") == ""
    assert ev.rebuild_abstract({"b": [1], "a": [0], "c": [2, 4], "d": [3]}) == "a b c d c"
    assert ev.level_hint("article", "journal", False)[0] == 1
    assert ev.level_hint("conference-paper", "conference", False)[0] == 1     # how OpenAlex types an ICLR paper
    assert ev.level_hint("standard", "", False)[0] == 2 and ev.level_hint("dissertation", "repository", False)[0] == 4
    assert ev.level_hint("report", "", False)[0] is None
    assert ev.level_hint("preprint", "repository", False)[0] == 4
    assert ev.level_hint("book-chapter", "", False)[0] == 3
    assert ev.level_hint("article", "journal", True)[0] is None
    work = ev.openalex_work(WORK)
    assert (work["doi"], work["url"], work["oa_url"], work["venue_type"], work["level_hint"]) == \
        ("10.1234/stig.2025.7", "https://example.org/stig", "https://example.org/stig/oa", "journal", 1)
    assert work["abstract"] == "Agents coordinate through stigmergy." and work["cited_by"] == 12


def test_the_search_sends_the_query_and_nothing_else(web):
    pages, seen = web
    pages["https://api.openalex.org/works"] = (json.dumps({"results": [WORK]}).encode(), "application/json")
    found, _budget = ev.openalex_search("stigmergy software agents", 5)
    assert [w["title"] for w in found] == ["Stigmergy in software teams"]
    url = seen[-1]
    assert "search=stigmergy+software+agents" in url and "per_page=5" in url and "select=" in url
    assert "mailto" not in url and "api_key" not in url and "@" not in url


def test_a_spent_budget_and_a_bad_answer_are_named(web):
    pages, _ = web
    # 0.24.3: a spent budget is what OpenAlex says it is (a 429 with no budget left); a bare 429 is a rate limit
    pages["https://api.openalex.org/works"] = (urllib.error.HTTPError("u", 429, "Too Many",
                                                                      {"X-RateLimit-Remaining-USD": "0"}, None), "")
    with pytest.raises(ev.EvidenceError) as e:
        ev.openalex_search("stigmergy")
    assert e.value.code == "search-budget"
    pages["https://api.openalex.org/works"] = (b"<html>maintenance</html>", "text/html")
    with pytest.raises(ev.EvidenceError) as e:
        ev.openalex_search("stigmergy")
    assert e.value.code == "search-failed"


def test_the_best_passages_are_the_page_s_own_words():
    text = ("## A\n\nAgents coordinate through stigmergy in a shared repository.\n\nFunding and ethics.\n\n"
            "Traces in the repository steer builders.\n")
    got = ev.best_passages(text, ["stigmergy", "repository", "agents", "traces"])
    assert got[0]["text"].startswith("## A") or "stigmergy" in got[0]["text"]
    assert all(p["text"] in text for p in got) and len(got) <= ev.PASSAGES
    assert ev.best_passages(text, []) == [] and ev.best_passages("", ["x", "y"]) == []


# --------------------------------------------------------------------------- the items waiting for a source

def test_find_lists_the_waiting_items(eng):
    out = eng.kg_source_find()
    assert out["ok"] and out["waiting_total"] == 2 and out["never_searched"] == 2
    item = next(i for i in out["items"] if i["id"] == PIN)
    assert item["kind"] == "node" and item["text"].startswith("Builder agents coordinate through stigmergy")
    assert "[diverge]" not in item["text"] and "stigmergy" in item["terms"]
    assert item["looked_for"] == "no passage states it" and item["searched"] == []
    assert [i["id"] for i in eng.kg_source_find(focus="stigmergy")["items"]] == [PIN]
    assert len(eng.kg_source_find(limit=1)["items"]) == 1


def test_find_says_when_nothing_waits(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    out = KGEngine(project, tmp_path / "d", pack_path=PACK).kg_source_find()
    assert out["ok"] and out["items"] == [] and "nothing waits for a source" in out["note"]


def test_a_searched_item_comes_after_the_never_searched(eng, web):
    pages, _ = web
    pages["https://api.openalex.org/works"] = (json.dumps({"results": []}).encode(), "application/json")
    assert eng.kg_source_search("stigmergy agents", item_id=PIN)["count"] == 0
    out = eng.kg_source_find()
    assert [i["id"] for i in out["items"]] == [OTHER, PIN] and out["never_searched"] == 1
    assert out["items"][1]["searched"][0]["query"] == "stigmergy agents" and out["openalex_searches_today"] == 1


# --------------------------------------------------------------------------- searching and reading

def test_a_search_is_logged_for_its_item(eng, web):
    pages, _ = web
    pages["https://api.openalex.org/works"] = (json.dumps({"results": [WORK]}).encode(), "application/json")
    out = eng.kg_source_search("stigmergy agents", item_id=PIN, stance="against")
    assert out["ok"] and out["results"][0]["level_hint"] == 1
    rec = _ledger(eng)[-1]
    assert (rec["type"], rec["backend"], rec["item"], rec["stance"], rec["results"]) == \
        ("search", "openalex", PIN, "against", 1)
    assert rec["found"][0]["doi"] == "10.1234/stig.2025.7"


def test_a_query_never_carries_a_secret(eng, web):
    _pages, seen = web
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one
    for query in (f"stigmergy {token}", "stigmergy ⟦SECRET:1⟧", "x", "w " * 150):
        out = eng.kg_source_search(query, item_id=PIN)
        assert not out["ok"] and out["error"] == "query-refused", query
    assert seen == [] and _ledger(eng) == []


def test_a_probe_reads_the_page_itself(eng, web):
    pages, _ = web
    pages["https://example.org/stig"] = (PAGE.encode(), "text/html; charset=utf-8")
    out = eng.kg_source_probe("https://example.org/stig", item_id=PIN, terms="stigmergy repository traces")
    assert out["ok"] and out["doi"] == "10.1234/stig.2025.7" and out["published"] == "2025-03-04"
    assert out["venue"] == "Journal of Coordination" and out["level_hint"] == 1
    assert "stigmergy" in out["passages"][0]["text"] and "funding" not in out["passages"][0]["text"].lower()
    assert "registered_as" not in out
    rec = _ledger(eng)[-1]
    assert (rec["type"], rec["item"], rec["ok"], rec["doi"]) == ("probe", PIN, True, "10.1234/stig.2025.7")


def test_a_probe_refuses_a_bot_check(eng, web):
    pages, _ = web
    pages["https://example.org/blocked"] = (b"<html><head><title>Client Challenge</title></head><body>"
                                            b"<p>A required part of this site couldn't load.</p></body></html>",
                                            "text/html")
    out = eng.kg_source_probe("https://example.org/blocked", item_id=PIN)
    assert not out["ok"] and out["error"] == "fetch-blocked" and "save" in out["hint"]
    assert _ledger(eng)[-1]["error"] == "fetch-blocked"


def test_the_scout_logs_its_web_searches(eng):
    out = eng.kg_source_record_search(PIN, searches=[{"query": "stigmergy agents", "stance": "for", "results": 0}],
                                      proposed=[{"url": "https://example.org/stig", "title": "Stigmergy",
                                                 "level": 1, "stance": "supports"}], note="one candidate")
    assert {k: out[k] for k in ("ok", "item", "searches", "proposed")} == \
        {"ok": True, "item": PIN, "searches": 1, "proposed": 1}
    assert out["missing"] == ["openalex for", "openalex against"]          # 0.24.2: the catalogue was not searched
    kinds = [(r["type"], r.get("backend")) for r in _ledger(eng)]
    assert kinds == [("search", "web"), ("proposed", None)]
    assert not eng.kg_source_record_search("no-such-item")["ok"]
    assert not eng.kg_source_record_search(PIN, searches=[{"query": "", "stance": "for"}])["ok"]


# --------------------------------------------------------------------------- registering what was found

def test_a_page_read_for_an_item_is_registered_for_it(eng, web, tmp_path):
    pages, _ = web
    pages["https://example.org/stig"] = (PAGE.encode(), "text/html; charset=utf-8")
    eng.kg_source_probe("https://example.org/stig", item_id=PIN, terms="stigmergy")
    out = eng.kg_source_add(url="https://example.org/stig", level=1, role="primary")
    assert out["ok"] and out["found_for"] == [PIN]
    rec = json.loads((eng.project_dir / "evidence" / (Path(out["name"]).stem + ".source.json")).read_text())
    assert rec["found_for"] == [PIN] and rec["doi"] == "10.1234/stig.2025.7"
    again = eng.kg_source_probe("https://example.org/stig", item_id=OTHER)
    assert again["registered_as"] == [out["name"]]


def test_a_saved_page_is_matched_by_its_doi(eng, web, tmp_path):
    pages, _ = web
    pages["https://api.openalex.org/works"] = (json.dumps({"results": [WORK]}).encode(), "application/json")
    eng.kg_source_search("stigmergy", item_id=PIN)                 # the catalogue gave its DOI
    out = _add_file(eng, tmp_path, "saved.html", PAGE)             # the user saved the page from a browser
    assert out["found_for"] == [PIN]


def test_for_items_names_the_items_by_hand(eng, tmp_path):
    out = _add_file(eng, tmp_path, "saved.html", PAGE.replace("10.1234/stig.2025.7", "10.9/x"), for_items=OTHER)
    assert out["found_for"] == [OTHER]
    bad = _add_file(eng, tmp_path, "other.html", PAGE.replace("Results", "Other"), for_items="nope")
    assert not bad["ok"] and bad["error"] == "item-not-found"


# --------------------------------------------------------------------------- what a new source wakes

def test_a_source_wakes_only_what_it_was_found_for_or_bears_on(eng, tmp_path):
    assert _queued(eng) == []                                       # both pins wait
    unrelated = ("<html><head><title>Ocean salinity</title></head><body><main><p>Salinity varies with depth "
                 "and season in every basin.</p></main></body></html>")
    assert _add_file(eng, tmp_path, "salt.html", unrelated)["ok"]
    assert _queued(eng) == [] and eng.kg_ground_plan()["queue"]["unsupported_waiting"] == 2   # 0.23.1: both woke
    assert _add_file(eng, tmp_path, "stig.html", PAGE)["ok"]        # shares the stigmergy pin's words
    assert _queued(eng) == [PIN]
    assert [i["id"] for i in eng.kg_source_find()["items"]] == [OTHER]


def test_a_source_found_for_an_item_wakes_it_whatever_its_words(eng, tmp_path):
    spanish = ("<html><head><title>Mareas</title></head><body><main><p>Las fuerzas de marea frenan la rotación "
               "de la luna.</p></main></body></html>")
    assert _add_file(eng, tmp_path, "mareas.html", spanish, for_items=OTHER)["ok"]
    assert _queued(eng) == [OTHER]


def test_a_focus_still_offers_every_waiting_item(eng):
    assert _queued(eng) == []
    assert [i["id"] for b in eng.kg_ground_plan(focus="tidal")["batches"] for i in b] == [OTHER]


# --------------------------------------------------------------------------- the texts

def test_the_scout_reads_pages_through_the_engine_only():
    head = SCOUT.split("---", 2)[1]
    tools = [t.strip() for t in head.split("tools:", 1)[1].splitlines()[0].split(",")]
    assert "WebSearch" in tools and "WebFetch" not in tools and "Bash" not in tools
    assert {"mcp__plugin_burgess_burgess__kg_source_search", "mcp__plugin_burgess_burgess__kg_source_probe",
            "mcp__plugin_burgess_burgess__kg_source_record_search"} <= set(tools)
    assert "omitClaudeMd: true" in head
    body = " ".join(SCOUT.split())
    assert "Never use WebFetch" in body and "never register" in body.lower()


def test_the_command_runs_find():
    head = COMMAND.split("---", 2)[1]
    assert "find [focus] [n]" in head and "mcp__plugin_burgess_burgess__kg_source_find" in head and "Task" in head
    body = " ".join(COMMAND.split())
    assert "## find" in COMMAND and "burgess:kg-scout" in body
    for tool in ("kg_source_find", "kg_source_search", "kg_source_probe", "kg_source_record_search"):
        assert f"`{tool}" in TOOLS, tool
