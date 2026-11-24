"""0.25.1: who wrote a work comes from the page or the catalogue, never from a model's memory.

On the field run of 2026-11-23 a `kg-scout` proposed a level-1 paper against an idea and named its authors in its
report. Nothing the engine had returned named any author: the probe gave the title, DOI, venue and passages, and the
page parser kept only the first `citation_author` tag in `meta`, which no tool returned. The names came from the
scout's memory and belonged to nobody who wrote the paper. The session's notes kept them, and on 2026-11-24 they
reached the user. The engine's own records held only the title and DOI, which were right, so the
registration still matched the paper to its idea.

Now the page parser reads every author the page declares, the preview, the probe and the record carry them, a
catalogue result carries its first three, and the scout and the command name authors from those only.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from kg_engine import evidence as ev
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
SCOUT = (REPO / "agents" / "scout.md").read_text(encoding="utf-8")
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
TOOLS = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
SERVER = " ".join((REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8").split())

BODY = "<body><main><h2>Results</h2><p>Early warnings fail on short series.</p></main></body></html>"


def _page(*metas: "tuple[str, str]", title: str = "Limits to early warning") -> str:
    tags = "".join(f'<meta name="{k}" content="{v}">' for k, v in metas)
    return f"<html><head><title>{title}</title>{tags}</head>{BODY}"


PAPER = _page(("citation_title", "Limits to early warning"), ("citation_author", "Ana  Ruiz"),
              ("citation_author", "Ben Ode"), ("citation_author", "Ana Ruiz"),
              ("citation_journal_title", "Journal of Signals"), ("DC.creator", "Someone Else"),
              ("author", "Site Editor"))


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
        seen.append(req.full_url)
        for prefix, (body, ctype) in pages.items():
            if req.full_url.startswith(prefix):
                return _Resp(body, ctype, req.full_url)
        raise urllib.error.URLError("no route in the test")

    monkeypatch.setattr(ev, "_urlopen", urlopen)
    monkeypatch.setattr(ev, "_sleep", lambda s: None)
    return pages, seen


@pytest.fixture
def eng(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes.md"
    notes.write_text("## Notes\n\nEarly warnings precede a regime shift.\n", encoding="utf-8")
    return KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)


def _register(engine, tmp_path, name: str, html: str) -> dict:
    f = tmp_path / name
    f.write_text(html, encoding="utf-8")
    return engine.kg_source_add(path=str(f), level=1, role="primary")


# --------------------------------------------------------------------------- the page

def test_the_page_names_every_author_in_its_order():
    title, text, meta, authors = ev.html_page(PAPER)
    assert authors == ["Ana Ruiz", "Ben Ode"]                 # whitespace collapsed, a repeated tag kept once
    assert meta["citation_author"] == "Ana Ruiz"               # `meta` still keeps the first value of each tag
    assert (title, text, meta) == ev.html_text(PAPER)          # the copy itself is unchanged by the authors


def test_the_first_family_the_page_uses_is_its_list():
    assert ev.html_page(_page(("dc.creator", "Dee One"), ("DC.Creator", "Dee Two"), ("author", "Site")))[3] == \
        ["Dee One", "Dee Two"]                                 # Dublin Core before the generic tag, any case
    assert ev.html_page(_page(("dcterms.creator", "Tee One")))[3] == ["Tee One"]
    assert ev.html_page(_page(("author", "Blog Writer")))[3] == ["Blog Writer"]
    assert ev.html_page(_page(("citation_journal_title", "J"), ("citation_author", "  ")))[3] == []


def test_a_file_of_text_names_no_author(tmp_path):
    note = tmp_path / "copy.md"
    note.write_text("Author: Somebody\n\nEarly warnings fail on short series.\n", encoding="utf-8")
    assert ev.copy_from_file(note).authors == []               # never read out of a text: only a page's tags count
    assert ev.copy_from_bytes(b"plain words", "text/plain").authors == []
    assert ev.page_authors(ev.copy_from_bytes(PAPER.encode(), "text/html")) == \
        {"authors": ["Ana Ruiz", "Ben Ode"], "authors_total": 2}


def test_a_long_list_is_capped_and_counted():
    many = _page(*(("citation_author", f"Author {i}") for i in range(ev.AUTHORS_MAX + 5)))
    got = ev.page_authors(ev.copy_from_bytes(many.encode(), "text/html"))
    assert len(got["authors"]) == ev.AUTHORS_MAX and got["authors_total"] == ev.AUTHORS_MAX + 5
    assert got["authors"][0] == "Author 0"


# --------------------------------------------------------------------------- what the tools return

def test_the_preview_and_the_probe_give_the_page_s_authors(eng, web):
    pages, _ = web
    pages["https://example.org/limits"] = (PAPER.encode(), "text/html")
    preview = eng.kg_source_add(url="https://example.org/limits", preview=True)
    assert preview["ok"] and preview["authors"] == ["Ana Ruiz", "Ben Ode"] and preview["authors_total"] == 2
    probe = eng.kg_source_probe("https://example.org/limits", terms="early warning")
    assert probe["ok"] and probe["authors"] == ["Ana Ruiz", "Ben Ode"] and probe["authors_total"] == 2
    pages["https://example.org/blog"] = (_page(title="A post").encode(), "text/html")
    assert eng.kg_source_probe("https://example.org/blog")["authors"] == []     # a page that names none: none


def test_the_record_keeps_the_authors_and_the_list_shows_them(eng, tmp_path):
    out = _register(eng, tmp_path, "limits.html", PAPER)
    assert out["ok"] and out["authors"] == ["Ana Ruiz", "Ben Ode"] and out["authors_total"] == 2
    sidecar = eng.project_dir / "evidence" / (Path(out["name"]).stem + ".source.json")
    rec = json.loads(sidecar.read_text(encoding="utf-8"))
    assert rec["authors"] == ["Ana Ruiz", "Ben Ode"] and rec["authors_total"] == 2
    md = tmp_path / "notes-copy.md"
    md.write_text("A copy someone typed: early warnings need long series.\n", encoding="utf-8")
    plain = eng.kg_source_add(path=str(md), level=4, role="secondary")
    assert plain["ok"] and "authors" not in plain
    listed = {s["name"]: s for s in eng.kg_source_list()["sources"]}
    assert listed[out["name"]]["authors"] == ["Ana Ruiz", "Ben Ode"]
    assert "authors" not in listed[plain["name"]]


def test_a_record_from_before_0_25_1_loads_without_authors(eng, tmp_path):
    out = _register(eng, tmp_path, "limits.html", PAPER)
    sidecar = eng.project_dir / "evidence" / (Path(out["name"]).stem + ".source.json")
    rec = json.loads(sidecar.read_text(encoding="utf-8"))
    for key in ("authors", "authors_total"):
        rec.pop(key)
    sidecar.write_text(json.dumps(rec), encoding="utf-8")
    reg = ev.load_registry(eng.project_dir / "evidence")
    assert not reg.problems and reg.get(out["name"]).authors == [] and reg.get(out["name"]).authors_total == 0


@pytest.mark.parametrize("field, value", [("authors", "Ana Ruiz"), ("authors", ["Ana Ruiz", ""]),
                                          ("authors_total", True), ("authors_total", -1), ("authors_total", "2")])
def test_a_malformed_author_field_is_reported(eng, tmp_path, field, value):
    out = _register(eng, tmp_path, "limits.html", PAPER)
    sidecar = eng.project_dir / "evidence" / (Path(out["name"]).stem + ".source.json")
    rec = json.loads(sidecar.read_text(encoding="utf-8"))
    rec[field] = value
    sidecar.write_text(json.dumps(rec), encoding="utf-8")
    reg = ev.load_registry(eng.project_dir / "evidence")
    assert reg.get(out["name"]) is None
    assert [p["problem"] for p in reg.problems] == ["sidecar-malformed"]


# --------------------------------------------------------------------------- the catalogue

WORK = {"display_name": "Limits to early warning", "doi": "https://doi.org/10.1234/ew.2012.1", "type": "article",
        "primary_location": {"source": {"display_name": "Journal of Signals", "type": "journal"}},
        "authorships": [{"author": {"display_name": "Ana Ruiz"}}, {"author": {}, "raw_author_name": "Ben Ode"},
                        "not an authorship", {"author": {"display_name": "Ana Ruiz"}},
                        {"author": {"display_name": "Cy Dee"}}, {"author": {"display_name": "Di Eff"}}]}


def test_a_catalogue_result_names_its_first_authors():
    work = ev.openalex_work(WORK)
    assert work["authors"] == ["Ana Ruiz", "Ben Ode", "Cy Dee"] and work["authors_total"] == 4
    bare = ev.openalex_work({"display_name": "No authorships"})
    assert bare["authors"] == [] and bare["authors_total"] == 0
    assert "authorships" in ev.OPENALEX_SELECT.split(",")


def test_the_search_asks_for_the_authors_and_returns_them(eng, web):
    pages, seen = web
    pages["https://api.openalex.org/works"] = (json.dumps({"results": [WORK]}).encode(), "application/json")
    out = eng.kg_source_search("early warning limits")
    assert out["ok"] and out["results"][0]["authors"] == ["Ana Ruiz", "Ben Ode", "Cy Dee"]
    assert "authorships" in seen[-1] and "mailto" not in seen[-1]   # a field asked for, nothing about the user sent


# --------------------------------------------------------------------------- the language layer

def test_the_scout_names_authors_only_from_the_engine():
    assert "## Who wrote it" in SCOUT and "**Never name an author from memory**" in SCOUT
    assert "a probe's `authors` (the names the page itself declares)" in SCOUT
    assert "catalogue result's `authors`" in SCOUT
    assert '"authors": ["<each name as the engine gave it; [] for none>"]' in SCOUT
    # the rule stands without the field case's names: an example in a subagent's prompt primes it (0.18.1)
    assert "Brett" not in SCOUT and "Boettiger" not in SCOUT


def test_the_command_and_the_reference_name_authors_from_the_engine():
    assert "Never invent a source, a title, an author, a date or a level" in COMMAND
    assert "Name the authors as the preview's `authors` gives them (0.25.1)" in COMMAND
    assert "its authors when the scout's candidate carries them (`authors`" in COMMAND
    assert "never from memory" in TOOLS and "`authors` (0.25.1)" in TOOLS
    assert "name a work's authors from these, never from memory" in SERVER     # kg_source_add's description
