"""0.21.0: external sources with an epistemic level.

Through 0.20.2 every verdict was judged against the configured sources, the user's own notes, so `grounded`
meant "my notes say it", and the only outside support was `support_note`: a citation the engine could not
check, recorded as `inferred`. Now the user registers outside texts (`/burgess:kg-sources`): the engine copies
each one into `<project>/evidence/` with a level (1 reviewed … 5 unfiltered), a role and marks, and a grounder
cites verbatim spans from the copy. The level measures the filter a text passed, never the truth of a claim,
so it only decides what may be used: level 5, retracted and superseded sources support and refute nothing,
and as a veto on `failed` a lower level never fails a higher one (the clash stays a visible dispute). A
registered source is never extracted into the graph unless it is registered to be built. The engine fetches
pages itself, because WebFetch returns a model's paraphrase.

Through 0.21.0 the notes sat outside the scale and an external source never failed them; since 0.22.0 they
have a level too (4 by default) and the same rules hold for every source. The tests below that touch the notes
pin the 0.22.0 rule; `tests/test_fix_source_policy.py` pins the policy itself.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from email.message import Message
from pathlib import Path

import pytest

from kg_engine import evidence
from kg_engine.evidence import (EvidenceError, decode, failed_veto, html_text, load_registry, page_published,
                                parse_level, parse_marks, parse_published, parse_role)
from kg_engine.model import EpistemicState, Provenance, edge_id
from kg_engine.server import KGEngine, _register
from kg_engine.sources import SourceSet

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
COMMAND = (REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8")
GROUND_CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
ADVERSARY = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")

NOTES = """\
## Notes

Specificity-weighted betweenness reconciles with the bridge intuition. Degree approximates importance.

## Memory

A failed claim is negative information and defends against re-proposal.
"""
PAPER = """<html><head><title>Study of degree</title>
<meta name="citation_journal_title" content="Journal of Graphs">
<meta name="citation_publication_date" content="2023/4/2"></head>
<body><nav><a href="/">Home</a></nav>
<h1>Results</h1>
<p>We found that betweenness bridges degree in every sampled graph we measured.</p>
<p>Specificity does not reconcile with the bridge intuition in sparse graphs at all.</p>
<footer>Copyright</footer></body></html>"""
CLAIM_SPAN = "Specificity-weighted betweenness reconciles with the bridge intuition"
PAPER_SPAN = "betweenness bridges degree in every sampled graph"
COUNTER_SPAN = "Specificity does not reconcile with the bridge intuition in sparse graphs"


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
def pages(monkeypatch):
    """A fake web: url -> (body, content type). The suite never touches the network."""
    web: dict = {}
    seen: list = []

    def fake_open(req, timeout):
        seen.append(req)
        url = req.full_url
        if url not in web:
            raise evidence.urllib.error.URLError("no route")
        body, ctype = web[url]
        return _Resp(body.encode("utf-8") if isinstance(body, str) else body, ctype, url)

    monkeypatch.setattr(evidence, "_urlopen", fake_open)
    web["seen"] = seen
    return web


@pytest.fixture
def rig(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "notes.md").write_text(NOTES, encoding="utf-8")
    eng = KGEngine(project, source_path=notes, pack_path=PACK)
    return eng, project, tmp_path


def _local(tmp_path: Path, name: str, text: str) -> Path:
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    p = folder / name
    p.write_text(text, encoding="utf-8")
    return p


def _add(eng, tmp_path, name, text, level, role="primary", marks=""):
    out = eng.kg_source_add(path=str(_local(tmp_path, name, text)), level=level, role=role, marks=marks)
    assert out["ok"], out
    return out["name"]


def _edge(eng, eid):
    return next(e for e in eng.canon.all_edges() if e.id == eid)


def _own_claim(eng):
    eng.kg_write({"edges": [{"source": "specificity-weighted betweenness", "target": "bridge intuition",
                             "relation": "reconciles_with", "span": CLAIM_SPAN, "source_file": "notes.md"}]})
    cid = edge_id("specificity-weighted betweenness", "reconciles_with", "bridge intuition")
    assert eng.kg_ground(cid, "grounded")["ok"]
    return cid


def _counter(eng, span, source_file, target="sparse graph counterexample"):
    out = eng.kg_write({"edges": [{"source": "specificity-weighted betweenness", "target": target,
                                   "relation": "attacked_by", "span": span, "source_file": source_file,
                                   "notes": "counter-edge (adversarial pass, hub specificity-weighted-betweenness)"}]})
    assert out.get("dispositions", {}).get("ACCEPTED"), out
    return edge_id("specificity-weighted betweenness", "attacked_by", target)


# --------------------------------------------------------------------------- the fixed extraction rule

def test_html_text_keeps_the_page_text_and_drops_its_furniture():
    title, text, meta = html_text(
        "<html><head><title>T &amp; U</title><script>var s = '<p>no</p>';</script><style>p{}</style></head>"
        "<body><nav>Menu</nav><h1>Results</h1><p>Models   with <b>attention</b>\n remember.</p>"
        "<ul><li>one</li><li>two <i>items</i></li></ul><table><tr><th>A</th><th>B</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table><pre>  keep   this\n spacing</pre><p>a<br>b</p>"
        "<h4>Sub</h4><footer>Copyright</footer></body></html>")
    assert title == "T & U"
    assert text == ("## Results\n\nModels with attention remember.\n\n- one\n- two items\n\nA | B\n1 | 2\n\n"
                    "  keep   this\n spacing\n\na\nb\n\n### Sub\n")
    assert "Menu" not in text and "Copyright" not in text and "no" not in text.split()


def test_an_unclosed_head_does_not_swallow_the_page():
    assert html_text("<html><head><title>T</title><body><p>Body text</p></body></html>")[1] == "Body text\n"


def test_the_page_metadata_gives_a_normalized_date():
    _t, _x, meta = html_text(PAPER)
    assert meta["citation_journal_title"] == "Journal of Graphs"
    assert page_published(meta) == "2023-04-02"
    assert page_published({"article:published_time": "2024-11-05T10:00:00Z"}) == "2024-11-05"
    assert page_published({}) == ""


def test_decoding_is_strict_and_never_replaces():
    assert decode("caf\xe9".encode("latin-1"), "iso-8859-1") == "caf\xe9"
    assert decode("﻿hola".encode("utf-8")) == "hola"
    with pytest.raises(EvidenceError) as e:
        decode(b"\xff\xfe\xfa broken")
    assert e.value.code == "undecodable"


def test_pdf_and_unknown_types_are_refused():
    for ctype, code in (("application/pdf", "pdf-not-supported"), ("image/png", "content-type-not-supported")):
        with pytest.raises(EvidenceError) as e:
            evidence.copy_from_bytes(b"%PDF-1.4", ctype)
        assert e.value.code == code
    with pytest.raises(EvidenceError) as e:
        evidence.copy_from_bytes(b"<html><body><script>app()</script></body></html>", "text/html")
    assert e.value.code == "no-text"


def test_argument_parsing():
    assert [parse_level(v) for v in (1, "2", "N3", "author-or-community", "unfiltered")] == [1, 2, 3, 4, 5]
    for bad in (0, 6, "", "high", True):
        with pytest.raises(EvidenceError):
            parse_level(bad)
    assert parse_role("Primary") == "primary"
    with pytest.raises(EvidenceError):
        parse_role("")
    assert parse_marks("retracted, interest") == ["interest", "retracted"]
    assert parse_marks("") == []
    with pytest.raises(EvidenceError):
        parse_marks("dubious")
    assert [parse_published(v) for v in ("", "2024", "2024-05", "2024-05-07")] == ["", "2024", "2024-05",
                                                                                  "2024-05-07"]
    for bad in ("2024-13", "May 2024", "24-05-07"):
        with pytest.raises(EvidenceError):
            parse_published(bad)


def test_the_level_vetoes_and_never_decides():
    none = {"class": "none"}
    own = lambda level, usable=True: {"class": "own", "level": level, "usable": usable}  # noqa: E731
    ext = lambda level, usable=True: {"class": "external", "level": level, "usable": usable}  # noqa: E731
    assert failed_veto(own(4), own(4)) == ""                             # the notes refute themselves
    assert failed_veto(own(4), ext(1)) == ""                             # 0.22.0: a reviewed paper fails a note
    assert failed_veto(ext(1), own(4)) == "failed-by-lower-level"        # and a note never fails it
    assert failed_veto(own(1), ext(3)) == "failed-by-lower-level"        # notes the user rated 1
    assert failed_veto(ext(1), ext(3)) == "failed-by-lower-level"
    assert failed_veto(ext(3), ext(1)) == ""
    assert failed_veto(ext(2), ext(2)) == ""                             # the same level: the text decides
    assert failed_veto(none, ext(4)) == ""                               # nothing to protect
    assert failed_veto(ext(1, usable=False), ext(4)) == ""               # its only support is unusable
    assert failed_veto(none, ext(5, usable=False)) == "failed-by-unusable-source"
    assert failed_veto(own(4), own(4, usable=False)) == "failed-by-unusable-source"
    assert failed_veto(own(4), none) == "refuted-by-has-no-span"


def test_the_fetch_says_nothing_about_the_user(pages):
    pages["https://example.org/p"] = ("<p>Some text here.</p>", "text/html; charset=utf-8")
    got = evidence.fetch("https://example.org/p")
    assert got.content_type == "text/html" and got.charset == "utf-8"
    agent = pages["seen"][-1].get_header("User-agent")
    assert agent == evidence.USER_AGENT
    assert not any(word in agent.lower() for word in ("burgess", "sergi", "github", "@"))
    with pytest.raises(EvidenceError) as e:
        evidence.fetch("ftp://example.org/p")
    assert e.value.code == "url-not-http"
    with pytest.raises(EvidenceError) as e:
        evidence.fetch("https://nowhere.example/")
    assert e.value.code == "fetch-failed"


def test_a_page_larger_than_the_cap_is_refused(pages):
    pages["https://example.org/big"] = ("x" * 50, "text/plain")
    with pytest.raises(EvidenceError) as e:
        evidence.fetch("https://example.org/big", max_bytes=10)
    assert e.value.code == "too-large"


# --------------------------------------------------------------------------- SourceSet with copies

def test_external_copies_verify_but_stay_out_of_the_corpus(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("Alpha grounds beta.\n", encoding="utf-8")
    copy = tmp_path / "ext-paper-1234abcd.md"
    copy.write_text("Alpha grounds beta, and gamma bridges delta.\n", encoding="utf-8")
    plain = SourceSet(notes)
    both = SourceSet(notes, extra=[copy])
    assert plain.concat == plain.full_concat == both.concat == "Alpha grounds beta.\n"
    assert both.full_concat == "Alpha grounds beta.\n\nAlpha grounds beta, and gamma bridges delta.\n"
    assert both.extra_names == ["ext-paper-1234abcd.md"] and both.is_extra("ext-paper-1234abcd.md")
    assert not both.is_extra("a.md") and not plain.is_extra("ext-paper-1234abcd.md")
    assert both.verifies("gamma bridges delta") and not plain.verifies("gamma bridges delta")
    assert both.files_containing("Alpha grounds beta") == ["a.md", "ext-paper-1234abcd.md"]
    assert both.stat_signature()[:1] == SourceSet.signature(notes) and len(both.stat_signature()) == 2


def test_a_glob_source_never_reaches_into_the_evidence_directory(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "ext-x-00000000.md").write_text("copy\n", encoding="utf-8")
    (tmp_path / "note.md").write_text("note\n", encoding="utf-8")
    pattern = str(tmp_path / "**" / "*.md")
    assert {p.name for p in SourceSet.resolve(pattern)} == {"note.md", "ext-x-00000000.md"}
    assert [p.name for p in SourceSet.resolve(pattern, exclude=tmp_path / "evidence")] == ["note.md"]


# --------------------------------------------------------------------------- registering

def test_a_preview_writes_nothing(rig, pages):
    eng, project, _ = rig
    pages["https://example.org/paper"] = (PAPER, "text/html; charset=utf-8")
    out = eng.kg_source_add(url="https://example.org/paper", preview=True)
    assert out["ok"] and out["preview"] and out["title"] == "Study of degree"
    assert out["published"] == "2023-04-02" and out["meta"]["citation_journal_title"] == "Journal of Graphs"
    assert PAPER_SPAN in _flat(out["excerpt"]) and "Copyright" not in out["excerpt"]
    assert not (project / "evidence").exists()


def test_registering_a_page_writes_the_copy_its_record_and_the_raw_bytes(rig, pages):
    eng, project, _ = rig
    pages["https://example.org/paper"] = (PAPER, "text/html; charset=utf-8")
    out = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary", note="a journal")
    assert out["ok"], out
    name = out["name"]
    assert name.startswith("ext-study-of-degree-") and name.endswith(".md")
    edir = project / "evidence"
    text = (edir / name).read_bytes()
    rec = json.loads((edir / (Path(name).stem + ".source.json")).read_text(encoding="utf-8"))
    assert rec["sha256_text"] == hashlib.sha256(text).hexdigest()
    assert rec["level"] == 1 and rec["level_by"] == "agent" and rec["role"] == "primary"
    assert rec["published"] == "2023-04-02" and rec["published_from"] == "page"
    assert rec["extractor"] == evidence.HTML_EXTRACTOR and rec["url"] == "https://example.org/paper"
    assert (edir / rec["raw"]).read_bytes() == PAPER.encode("utf-8")
    assert rec["sha256_raw"] == hashlib.sha256(PAPER.encode("utf-8")).hexdigest()
    assert out["source"]["level_name"] == "reviewed" and out["source"]["usable"] is True
    # the same text again is refused; the same URL with new text is accepted and named
    assert eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")["error"] == \
        "already-registered"
    pages["https://example.org/paper"] = (PAPER.replace("every sampled", "each sampled"), "text/html")
    again = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")
    assert again["ok"] and again["same_url_as"] == [name]


def test_registering_needs_a_level_and_a_role(rig, pages):
    eng, _, tmp = rig
    path = str(_local(tmp, "a.md", "Some outside text.\n"))
    assert eng.kg_source_add(path=path, role="primary")["error"] == "bad-level"
    assert eng.kg_source_add(path=path, level=2)["error"] == "bad-role"
    assert eng.kg_source_add(path=path, url="https://x.org", level=2, role="primary")["error"] == \
        "give-url-or-path"


def test_local_files(rig):
    eng, project, tmp = rig
    out = eng.kg_source_add(path=str(_local(tmp, "report.md", "An official figure.\n")), level=2,
                            role="primary")
    assert out["ok"] and (project / "evidence" / out["name"]).read_text(encoding="utf-8") == "An official figure.\n"
    rec = json.loads((project / "evidence" / (Path(out["name"]).stem + ".source.json")).read_text())
    assert rec["origin"] == "file" and rec["raw"] == "" and rec["extractor"] == "verbatim"
    pdf = tmp / "downloads" / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert eng.kg_source_add(path=str(pdf), level=1, role="primary")["error"] == "pdf-not-supported"
    notes = tmp / "notes" / "notes.md"
    assert eng.kg_source_add(path=str(notes), level=4, role="primary")["error"] == "already-a-configured-source"
    inside = project / "evidence" / out["name"]
    assert eng.kg_source_add(path=str(inside), level=4, role="primary")["error"] == "already-in-evidence"
    assert eng.kg_source_add(path="missing.md", level=4, role="primary")["error"] == "file-not-found"


def test_an_edited_copy_leaves_the_registry(rig):
    eng, project, tmp = rig
    name = _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    assert eng.verify_set().verifies("Gamma bridges delta")
    (project / "evidence" / name).write_text("Gamma bridges delta, and anything I like.\n", encoding="utf-8")
    (project / "evidence" / "stray.md").write_text("no record\n", encoding="utf-8")
    listing = eng.kg_source_list()
    assert listing["sources"] == []
    assert [p["problem"] for p in listing["problems"]] == ["text-edited"]
    assert listing["unregistered"] == ["stray.md"]
    assert not eng.verify_set().verifies("anything I like")


def test_a_malformed_record_is_reported_not_trusted(tmp_path):
    edir = tmp_path / "evidence"
    edir.mkdir()
    (edir / "ext-a-00000000.md").write_text("text\n", encoding="utf-8")
    (edir / "ext-a-00000000.source.json").write_text(json.dumps({"name": "ext-a-00000000.md", "level": 9,
                                                                 "role": "primary", "sha256_text": "x"}))
    reg = load_registry(edir)
    assert not reg and reg.problems[0]["problem"] == "bad-level"


def test_kg_source_set(rig):
    eng, project, tmp = rig
    name = _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    before = (project / "evidence" / name).read_bytes()
    out = eng.kg_source_set(name, level="3", marks="interest", published="2021-07", note="a vendor page")
    assert out["ok"] and out["changed"] == ["level", "marks", "published", "note"]
    assert out["source"]["level"] == 3 and out["source"]["marks"] == ["interest"]
    assert eng.kg_source_set(name, marks="")["changed"] == ["marks"]
    assert eng.kg_source_set(name)["changed"] == []
    assert eng.kg_source_set("ext-nope.md", level=1)["error"] == "source-not-found"
    assert eng.kg_source_set(name, marks="dubious")["error"] == "bad-marks"
    assert eng.kg_source_set(name, derives_from=name)["error"] == "derives-from-unknown"
    assert (project / "evidence" / name).read_bytes() == before


# --------------------------------------------------------------------------- never extracted

def test_a_registered_source_is_never_extracted(rig):
    eng, _, tmp = rig
    corpus = eng.source_text()
    _add(eng, tmp, "a.md", "## Outside\n\nGamma bridges delta across the outside text.\n", 2)
    plan = eng.kg_build_plan()
    assert [f["file"] for f in plan["files"]] == ["notes.md"]
    assert eng.source_text() == corpus
    assert eng.source_set().basenames == ["notes.md"]


def test_the_source_signature_is_unchanged_until_a_source_is_registered(rig):
    eng, _, tmp = rig
    assert eng._source_signature() == hashlib.sha256(eng.source_set().concat.encode()).hexdigest()
    _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    assert eng._source_signature() != hashlib.sha256(eng.source_set().concat.encode()).hexdigest()


# --------------------------------------------------------------------------- support

def test_a_hypothesis_is_promoted_on_a_span_from_a_usable_source(rig, pages):
    eng, _, _ = rig
    pages["https://example.org/paper"] = (PAPER, "text/html")
    name = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")["name"]
    eng.kg_propose({"edges": [{"source": "betweenness", "target": "degree", "relation": "bridges"}]})
    eid = edge_id("betweenness", "bridges", "degree")
    out = eng.kg_ground(eid, "grounded", support_span=PAPER_SPAN)
    assert out["ok"] and out["provenance_upgraded_to"] == "span-present"
    assert out["support_source"]["file"] == name and out["support_source"]["level"] == 1
    e = _edge(eng, eid)
    assert e.source_file == name and e.provenance == Provenance.SPAN_PRESENT


@pytest.mark.parametrize("level,marks,why", [(5, "", "unfiltered"), (2, "retracted", "retracted"),
                                              (2, "superseded", "superseded")])
def test_an_unusable_source_supports_nothing(rig, level, marks, why):
    eng, _, tmp = rig
    name = _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", level, marks=marks)
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    eid = edge_id("gamma", "bridges", "delta")
    out = eng.kg_ground(eid, "grounded", support_span="Gamma bridges delta across the outside text")
    assert (out["ok"], out["error"], out["source"], out["unusable"]) == (False, "support-not-usable", name, why)
    assert out["source_level"] == level and out["required_level"] == 4 and out["hint"]
    assert _edge(eng, eid).epistemic_state == EpistemicState.UNVERIFIED


def test_a_span_the_notes_also_hold_is_supported_by_the_notes(rig):
    eng, _, tmp = rig
    _add(eng, tmp, "a.md", "Degree approximates importance, as everyone says.\n", 5)
    eng.kg_propose({"edges": [{"source": "degree", "target": "importance", "relation": "approximates"}]})
    eid = edge_id("degree", "approximates", "importance")
    out = eng.kg_ground(eid, "grounded", support_span="Degree approximates importance")
    side = out["support_source"]
    assert out["ok"] and (side["class"], side["file"], side["level"], side["usable"]) == ("own", "notes.md", 4, True)


def test_an_edge_quoting_only_an_unfiltered_source_cannot_be_grounded(rig):
    eng, _, tmp = rig
    name = _add(eng, tmp, "post.md", "Gamma bridges delta, trust me.\n", 5)
    out = eng.kg_write({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges",
                                   "span": "Gamma bridges delta, trust me", "source_file": name}]})
    assert out["dispositions"].get("ACCEPTED") == 1       # the span is real: it verifies against the copy
    eid = edge_id("gamma", "bridges", "delta")
    assert eng.kg_ground(eid, "grounded")["error"] == "support-not-usable"
    assert eng.kg_ground(eid, "rejected", note="only an unfiltered post says so")["ok"]


def test_a_citation_is_recorded_as_unchecked(rig):
    eng, _, _ = rig
    eng.kg_propose({"edges": [{"source": "betweenness", "target": "degree", "relation": "bridges"}]})
    eid = edge_id("betweenness", "bridges", "degree")
    out = eng.kg_ground(eid, "grounded", support_note="Swanson 1986")
    assert out["ok"] and out["support"] == "unchecked-citation"
    assert "citation (unchecked): Swanson 1986" in _edge(eng, eid).notes


# --------------------------------------------------------------------------- the failed veto

def test_without_registered_sources_a_failed_needs_no_refutation_id(rig):
    eng, _, _ = rig
    cid = _own_claim(eng)
    assert eng.kg_ground(cid, "failed", note="refuted")["ok"]


def test_once_a_source_is_registered_a_failed_names_its_refutation(rig):
    eng, _, tmp = rig
    cid = _own_claim(eng)
    _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    assert eng.kg_ground(cid, "failed")["error"] == "failed-needs-refuted-by"
    assert eng.kg_ground(cid, "failed", refuted_by="e_missing__attacked-by__x")["error"] == \
        "refuted-by-not-found"
    eng.kg_write({"edges": [{"source": "degree", "target": "importance", "relation": "approximates",
                             "span": "Degree approximates importance", "source_file": "notes.md"}]})
    other = edge_id("degree", "approximates", "importance")
    assert eng.kg_ground(cid, "failed", refuted_by=other)["error"] == "refuted-by-not-a-counter-edge"
    eng.kg_write({"edges": [{"source": "failed claim", "target": "negative information", "relation": "attacked_by",
                             "span": "A failed claim is negative information", "source_file": "notes.md"}]})
    unrelated = edge_id("failed claim", "attacked_by", "negative information")
    assert eng.kg_ground(cid, "failed", refuted_by=unrelated)["error"] == "refuted-by-unrelated"
    assert _edge(eng, cid).epistemic_state == EpistemicState.GROUNDED


def test_a_reviewed_source_can_fail_a_claim_only_the_notes_support(rig, pages):
    """0.22.0: the notes stand at their level (4 by default), so a level-1 refutation may fail their claim.
    Through 0.21.0 the notes were out of reach of any external source, however reviewed."""
    eng, _, _ = rig
    cid = _own_claim(eng)
    pages["https://example.org/paper"] = (PAPER, "text/html")
    name = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")["name"]
    counter = _counter(eng, COUNTER_SPAN, name)
    out = eng.kg_ground(cid, "failed", refuted_by=counter, note="the study contradicts it")
    assert out["ok"] and out["refuted_by"] == counter
    assert _edge(eng, cid).epistemic_state == EpistemicState.FAILED


def test_notes_rated_higher_are_not_failed_by_a_lower_source(rig, pages):
    eng, _, tmp = rig
    cid = _own_claim(eng)
    assert eng.kg_source_set("notes.md", level=1)["changed"] == ["level"]
    blog = _add(eng, tmp, "blog.md", "Specificity does not reconcile with the bridge intuition in sparse graphs.\n", 3)
    counter = _counter(eng, COUNTER_SPAN, blog)
    out = eng.kg_ground(cid, "failed", refuted_by=counter)
    assert out["error"] == "failed-by-lower-level"
    assert out["claim_source"]["level"] == 1 and out["refuting_source"]["level"] == 3
    assert _edge(eng, cid).epistemic_state == EpistemicState.GROUNDED
    assert _edge(eng, counter).epistemic_state == EpistemicState.UNVERIFIED     # the dispute stays visible


def test_between_external_sources_a_lower_level_cannot_fail_a_higher_one(rig):
    eng, _, tmp = rig
    high = _add(eng, tmp, "review.md", "Theta bridges kappa in every cohort studied.\n", 1)
    low = _add(eng, tmp, "blog.md", "In my experience theta never bridges kappa at all.\n", 3)
    eng.kg_propose({"edges": [{"source": "theta", "target": "kappa", "relation": "bridges"}]})
    claim = edge_id("theta", "bridges", "kappa")
    assert eng.kg_ground(claim, "grounded", support_span="Theta bridges kappa in every cohort studied")["ok"]
    eng.kg_write({"edges": [{"source": "theta", "target": "blog counterexample", "relation": "attacked_by",
                             "span": "theta never bridges kappa at all", "source_file": low}]})
    counter = edge_id("theta", "attacked_by", "blog counterexample")
    assert eng.kg_ground(claim, "failed", refuted_by=counter)["error"] == "failed-by-lower-level"
    # the other way round, the text decides: a level-1 refutation may fail a level-3 claim
    eng.kg_propose({"edges": [{"source": "kappa", "target": "theta", "relation": "approximates"}]})
    weak = edge_id("kappa", "approximates", "theta")
    assert eng.kg_ground(weak, "grounded", support_span="theta never bridges kappa at all")["ok"]
    eng.kg_write({"edges": [{"source": "kappa", "target": "cohort result", "relation": "attacked_by",
                             "span": "Theta bridges kappa in every cohort studied", "source_file": high}]})
    strong = edge_id("kappa", "attacked_by", "cohort result")
    out = eng.kg_ground(weak, "failed", refuted_by=strong, note="the review contradicts the blog")
    assert out["ok"] and out["refuted_by"] == strong
    assert _edge(eng, weak).notes.endswith(f"refuted by: {strong}")


def test_an_unfiltered_source_refutes_nothing(rig):
    eng, _, tmp = rig
    post = _add(eng, tmp, "post.md", "Theta is a hoax, kappa is not real, wake up.\n", 5)
    eng.kg_propose({"edges": [{"source": "theta", "target": "kappa", "relation": "bridges"}]})
    claim = edge_id("theta", "bridges", "kappa")
    eng.kg_write({"edges": [{"source": "theta", "target": "hoax claim", "relation": "attacked_by",
                             "span": "Theta is a hoax, kappa is not real", "source_file": post}]})
    counter = edge_id("theta", "attacked_by", "hoax claim")
    assert eng.kg_ground(claim, "failed", refuted_by=counter)["error"] == "failed-by-unusable-source"


def test_the_notes_still_refute_themselves(rig):
    eng, _, tmp = rig
    cid = _own_claim(eng)
    _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    eng.kg_write({"edges": [{"source": "specificity-weighted betweenness", "target": "failed claim",
                             "relation": "collapses_into", "span": "A failed claim is negative information",
                             "source_file": "notes.md"}]})
    counter = edge_id("specificity-weighted betweenness", "collapses_into", "failed claim")
    assert eng.kg_ground(cid, "failed", refuted_by=counter)["ok"]


# --------------------------------------------------------------------------- what a grounder sees

def test_kg_ground_item_labels_external_passages(rig, pages):
    eng, _, tmp = rig
    pages["https://example.org/paper"] = (PAPER, "text/html")
    name = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")["name"]
    eng.kg_propose({"edges": [{"source": "betweenness", "target": "degree", "relation": "bridges"}]})
    eid = edge_id("betweenness", "bridges", "degree")
    eng.kg_ground(eid, "grounded", support_span=PAPER_SPAN)
    item = eng.kg_ground_item(eid)
    assert item["span_in_source"] is True
    assert item["span_source"]["class"] == "external" and item["span_source"]["file"] == name
    assert item["context"]["source_file"] == name and item["context"]["source"]["level"] == 1
    own = eng.kg_ground_item(_own_claim(eng))
    assert (own["span_source"]["class"], own["span_source"]["file"], own["span_source"]["level"]) == \
        ("own", "notes.md", 4)
    assert own["context"]["source"]["class"] == "own" and own["support_context"] is None


def test_a_node_sees_external_sections_beside_its_notes(rig):
    eng, _, tmp = rig
    from kg_engine.model import Node
    name = _add(eng, tmp, "a.md", "## Findings\n\nNegative information defends the graph against re-proposal "
                                  "of failed claims.\n", 2)
    junk = _add(eng, tmp, "b.md", "## Hype\n\nNegative information about failed claims is a scam.\n", 5)
    eng.canon.write_one(Node(id="memoria-negativa", label="Negative information defends against re-proposal",
                             node_type="claim", provenance=Provenance.HYPOTHESIZED,
                             body="A failed claim is negative information that defends against re-proposal."))
    sections = eng.kg_ground_item("memoria-negativa", kind="node")["source_context"]["sections"]
    files = [s["source_file"] for s in sections]
    assert "notes.md" in files and name in files and junk not in files
    ext = next(s for s in sections if s["source_file"] == name)
    assert ext["source"]["level"] == 2 and ext["source"]["usable"] is True
    assert all(s["source"]["class"] == "own" for s in sections if s["source_file"] == "notes.md")


def test_the_plan_lists_the_usable_sources_for_the_adversary(rig):
    eng, project, tmp = rig
    good = _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    _add(eng, tmp, "b.md", "Gamma is fake.\n", 5)
    ev = eng.kg_ground_plan()["evidence"]
    assert ev["path"] == str(project / "evidence")
    assert [f["name"] for f in ev["files"]] == [good] and ev["files"][0]["level"] == 2


def test_registering_a_source_wakes_the_pins_waiting_for_one(rig):
    eng, _, tmp = rig
    from kg_engine.model import Node
    eng.canon.write_one(Node(id="pin-a", label="Gamma bridges delta", node_type="claim",
                             provenance=Provenance.HYPOTHESIZED, body="[diverge] pinned idea: gamma bridges delta"))
    assert eng.kg_record_unsupported("pin-a", kind="node", note="nothing in the notes")["ok"]
    assert eng.kg_ground_plan()["queue"]["unsupported_waiting"] == 1
    _add(eng, tmp, "a.md", "Gamma bridges delta across the outside text.\n", 2)
    plan = eng.kg_ground_plan()
    assert plan["queue"]["unsupported_waiting"] == 0
    assert any(item["id"] == "pin-a" for batch in plan["batches"] for item in batch)


# --------------------------------------------------------------------------- the report and staleness

def test_kg_source_list_reports_what_grounded_claims_rest_on(rig, pages):
    eng, _, _ = rig
    _own_claim(eng)
    pages["https://example.org/paper"] = (PAPER, "text/html")
    name = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")["name"]
    eng.kg_propose({"edges": [{"source": "betweenness", "target": "degree", "relation": "bridges"},
                              {"source": "degree", "target": "betweenness", "relation": "approximates"}]})
    eng.kg_ground(edge_id("betweenness", "bridges", "degree"), "grounded", support_span=PAPER_SPAN)
    eng.kg_ground(edge_id("degree", "approximates", "betweenness"), "grounded", support_note="a book")
    listing = eng.kg_source_list()
    assert [s["name"] for s in listing["sources"]] == [name] and listing["by_level"] == {"1": 1}
    support = listing["support"]
    assert support["edges"] == {"own": {"4": 1}, "external": {"1": 1}, "unchecked_citation": 1, "unlocated": 0}
    assert support["external_items"][0]["source"] == name and support["on_unusable"] == []
    eng.kg_source_set(name, marks="retracted")
    assert eng.kg_source_list()["support"]["on_unusable"][0]["unusable"] == "retracted"


def test_a_verdict_on_an_external_span_is_not_stale_until_its_copy_goes(rig, pages):
    eng, project, _ = rig
    pages["https://example.org/paper"] = (PAPER, "text/html")
    name = eng.kg_source_add(url="https://example.org/paper", level=1, role="primary")["name"]
    eng.kg_propose({"edges": [{"source": "betweenness", "target": "degree", "relation": "bridges"}]})
    eid = edge_id("betweenness", "bridges", "degree")
    eng.kg_ground(eid, "grounded", support_span=PAPER_SPAN)
    eng.projector.project(incremental=False)
    assert eng.projector._read_meta().get("stale_verdicts", []) == []
    (project / "evidence" / name).unlink()
    eng.projector.project()
    assert [s["edge_id"] for s in eng.projector._read_meta()["stale_verdicts"]] == [eid]


# --------------------------------------------------------------------------- the surface and the texts

def test_the_tools_are_registered():
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
    assert {"kg_source_add", "kg_source_list", "kg_source_set"} <= set(mcp.tools)
    import inspect
    assert "refuted_by" in inspect.signature(mcp.tools["kg_ground"]).parameters


def test_the_command_copies_through_the_engine_only():
    head = COMMAND.split("---", 2)[1]
    allowed = next(line for line in head.splitlines() if line.startswith("allowed-tools:"))
    # 0.24.0: `find` launches kg-scout subagents (Task) and lists the waiting items (kg_source_find); the command
    # itself still reads no page and searches nothing: the scouts search, and the engine reads every page
    assert allowed.split(":", 1)[1].split(",") == [
        " Task", " mcp__plugin_burgess_burgess__kg_source_add", " mcp__plugin_burgess_burgess__kg_source_find",
        " mcp__plugin_burgess_burgess__kg_source_list", " mcp__plugin_burgess_burgess__kg_source_set",
        " mcp__plugin_burgess_burgess__kg_source_policy"]
    flat = _flat(COMMAND)
    assert "never use WebFetch or WebSearch yourself" in flat
    assert "The level measures the filter a text passed before it was published, never whether a claim is true" \
        in flat
    assert "stop: ask the user to confirm or correct it." in flat
    assert "$ARGUMENTS" in COMMAND


def test_the_grounders_know_the_levels_and_the_refutation_id():
    assert "**The level is not your verdict.**" in GROUNDER and "span_source" in GROUNDER
    flat = _flat(ADVERSARY)
    assert "refuted_by=<the counter-edge's id>" in flat
    assert "the level vetoes, never decides" in flat
    assert 'refuted_by="e_betweenness__confounded-by__generality-confound"' in ADVERSARY
    ground = _flat(GROUND_CMD)
    assert "refuted_by=<your counter-edge's id>" in ground and "<the plan's evidence.files" in ground
