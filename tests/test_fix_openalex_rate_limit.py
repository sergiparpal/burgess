"""0.24.3: a rate limit from OpenAlex is not a spent budget.

On the field run of 2026-11-23 (`/burgess:kg-sources find 3`, `prueba-burgess`, on 0.24.2) a scout ran six catalogue
searches a second apart or in parallel; three drew HTTP 429. A diagnostic request a few minutes later showed
`X-RateLimit-Remaining-USD: 0.084` of `0.1`: the budget was far from spent. 0.24.2 read every 429 as a spent budget,
so the scout dropped the catalogue for the run, `missing` moved the searches to the web, and the report told the
user the daily limit had run out. Now the engine paces its catalogue requests, waits and retries once on a 429,
says the budget is spent only when OpenAlex says so (HTTP 402, or a 429 with no budget left), and reports what is
left. A catalogue search that failed is owed to the web with the same stance.
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
OK = json.dumps({"results": [{"display_name": "Stigmergy in teams", "type": "article",
                              "primary_location": {"source": {"type": "journal"}}}]}).encode()
BUDGET = {"X-RateLimit-Remaining-USD": "0.084", "X-RateLimit-Limit-USD": "0.1", "X-RateLimit-Reset": "35161"}


def _flat(text: str) -> str:
    return " ".join(text.split())


class _Resp:
    def __init__(self, body: bytes, headers: dict, url: str):
        self._body, self._url = body, url
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        for k, v in headers.items():
            self.headers[k] = v

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def net(monkeypatch):
    """OpenAlex, faked: `answers` is the queue of answers (an exception, or `(body, headers)`), the last one repeated;
    `slept` keeps every wait the engine asked for, and nothing really waits."""
    answers: list = []
    seen: "list[str]" = []
    slept: "list[float]" = []

    def urlopen(req, timeout):
        seen.append(req.full_url)
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        body, headers = answer
        return _Resp(body, headers, req.full_url)

    monkeypatch.setattr(ev, "_urlopen", urlopen)
    monkeypatch.setattr(ev, "_sleep", slept.append)
    return answers, seen, slept


def _too_many(headers: "dict | None" = None):
    return urllib.error.HTTPError("u", 429, "Too Many Requests", headers or {}, None)


def test_the_budget_is_read_from_the_headers(net):
    answers, _, _ = net
    answers.append((OK, BUDGET))
    works, budget = ev.openalex_search("stigmergy")
    assert [w["title"] for w in works] == ["Stigmergy in teams"]
    assert budget == {"remaining_usd": 0.084, "limit_usd": 0.1, "reset_s": 35161.0}


def test_a_rate_limit_is_waited_out_once(net):
    answers, seen, slept = net
    answers.extend([_too_many({"Retry-After": "3", **BUDGET}), (OK, BUDGET)])
    works, _ = ev.openalex_search("stigmergy")
    assert len(works) == 1 and len(seen) == 2 and 3.0 in slept


def test_a_rate_limit_that_lasts_is_named_as_such(net):
    answers, seen, _ = net
    answers.append(_too_many(BUDGET))
    with pytest.raises(ev.EvidenceError) as e:
        ev.openalex_search("stigmergy")
    assert e.value.code == "search-rate-limited" and "0.084" in e.value.detail and len(seen) == 2


def test_a_spent_budget_is_what_openalex_says(net):
    answers, seen, _ = net
    answers.append(_too_many({"X-RateLimit-Remaining-USD": "0", "X-RateLimit-Reset": "7200"}))
    with pytest.raises(ev.EvidenceError) as e:
        ev.openalex_search("stigmergy")
    assert e.value.code == "search-budget" and "2.0 h" in e.value.detail and len(seen) == 1   # no retry
    answers[:] = [urllib.error.HTTPError("u", 402, "Payment Required", {}, None)]
    with pytest.raises(ev.EvidenceError) as e:
        ev.openalex_search("stigmergy")
    assert e.value.code == "search-budget"


def test_the_engine_paces_its_requests(net, monkeypatch):
    answers, _, slept = net
    answers.append((OK, BUDGET))
    monkeypatch.setattr(ev, "_openalex_last", [ev.time.monotonic()])    # a request has just gone out
    ev.openalex_search("stigmergy")
    # a hair of float slack: on Windows `time.monotonic()` ticks coarsely, the two readings can be equal, and
    # `last + 1.1 - now` then comes out as 1.1000000000000227 (the Windows CI leg of PR #148)
    assert slept and 0 < slept[0] <= ev.OPENALEX_SPACING_S + 1e-6


@pytest.fixture
def eng(tmp_path, net):
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
    assert e.kg_record_unsupported(PIN, "node", "no passage states it")["ok"]
    return e, net[0]


def test_the_tools_report_what_is_left(eng):
    e, answers = eng
    answers.append((OK, BUDGET))
    out = e.kg_source_search("stigmergy agents", item_id=PIN, stance="for")
    assert out["budget"]["remaining_usd"] == 0.084
    assert e.kg_source_find()["openalex_budget_left_usd"] == 0.084


def test_a_rate_limited_stance_is_owed_to_the_web(eng):
    e, answers = eng
    answers.append((OK, BUDGET))
    assert e.kg_source_search("stigmergy agents", item_id=PIN, stance="for")["ok"]
    answers[:] = [_too_many(BUDGET)]
    out = e.kg_source_search("stigmergy fails", item_id=PIN, stance="against")
    assert out["error"] == "search-rate-limited" and "budget is not spent" in out["hint"]
    rec = e.kg_source_record_search(PIN, searches=[{"query": "stigmergy agents", "stance": "for", "results": 4}])
    assert rec["missing"] == ["web against"]                            # the catalogue's for still counts


def test_the_texts_tell_a_rate_limit_from_a_spent_budget():
    scout = _flat(SCOUT)
    assert "`search-rate-limited` is not that" in scout
    assert "Never write that the daily budget ran out unless the answer said `search-budget`." in scout
    assert "Say the daily budget ran out only when a scout met `search-budget`" in _flat(COMMAND)
    assert "`search-rate-limited`: a 429 again after the pause, with budget left." in _flat(TOOLS)
