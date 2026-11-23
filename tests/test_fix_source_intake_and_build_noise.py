"""0.23.1: a bot check is refused, the online date is taken, a repeated edge keeps its first passage, and page
furniture is no longer extracted.

Phase 3 of the field test of 2026-11-22 built a graph in `prueba-burgess-n1` from two peer-reviewed articles:
- Springer sent the engine on Windows a 210-character "Client Challenge" for three articles, which the preview
  reported as `ok: true`;
- the proposed date was the issue's (2027-04) rather than the online one (2026-11-03);
- Copilot §35 lost its coverage when §53 wrote the same edge, because the later passage replaced the span;
- of 137 sections, 95 were read and recorded as holding no edge, most of them page furniture, reference lists
  and publisher back matter.
And 0.23.0's migration left `-shm`/`-wal` files beside the old shared index.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from kg_engine import envconfig
from kg_engine import evidence as ev
from kg_engine.buildplan import parse_arguments, skip_reason
from kg_engine.canon import GROUND_AUDIT
from kg_engine.groundaudit import audit_key, read_audit_index
from kg_engine.model import edge_id
from kg_engine.server import KGEngine, adopt_shared_derived

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _html(body: str, title: str = "A study") -> bytes:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>".encode("utf-8")


# --------------------------------------------------------------------------- a bot check is refused

def test_a_bot_check_is_known_by_its_title_or_its_words():
    challenge = ev.copy_from_bytes(_html("<p>A required part of this site couldn’t load. This may be due to a "
                                         "browser extension.</p>", "Client Challenge"), "text/html")
    assert "Client Challenge" in ev.blocked_page(challenge)
    short = ev.copy_from_bytes(_html("<p>Please verify you are human to continue.</p>", "Example"), "text/html")
    assert "verify you are human" in ev.blocked_page(short)
    long_page = ev.copy_from_bytes(_html("<main><p>" + "How captcha systems fail real users. " * 80 + "</p></main>"),
                                   "text/html")
    assert ev.blocked_page(long_page) == ""
    note = ev.Copy(text="Client Challenge", title="Client Challenge", meta={}, content_type="text/markdown",
                   extractor=ev.VERBATIM, raw=b"", raw_ext=".md")
    assert ev.blocked_page(note) == ""                                    # the user's own text is never checked


def test_kg_source_add_refuses_a_bot_check_at_the_preview(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    eng = KGEngine(project, tmp_path / "data", source_path=None, pack_path=PACK)
    page = tmp_path / "saved.html"
    page.write_bytes(_html("<p>Checking your browser before accessing the site.</p>", "Just a moment..."))
    out = eng.kg_source_add(path=str(page), preview=True)
    assert not out["ok"] and out["error"] == "fetch-blocked" and "save it again" in out["hint"]
    assert not (project / "evidence").exists()


def test_the_online_date_comes_first_and_never_a_future_one():
    assert ev.page_published({"citation_publication_date": "2027/04", "citation_online_date": "2026/11/03"}) == "2026-11-03"
    assert ev.page_published({"citation_publication_date": "2099/01", "dc.date": "2026-04-13"}) == "2026-04-13"
    assert ev.page_published({"citation_publication_date": "2099/01"}) == "2099-01"   # nothing earlier declared
    assert ev.page_published({}) == ""


# --------------------------------------------------------------------------- a repeated edge keeps its passage

ONE = "RMSSD approximates frustration in every session we measured"
TWO = "RMSSD approximates frustration across all twelve participants"
DOC = f"## One\n\n{ONE}.\n\n## Two\n\nAgain, {TWO}.\n"
NODES = [{"id": "rmssd", "label": "RMSSD", "node_type": "metric"},
         {"id": "frustration", "label": "frustration", "node_type": "primitive"}]
EID = edge_id("rmssd", "approximates", "frustration")


@pytest.fixture
def doc(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    src = tmp_path / "doc.md"
    src.write_text(DOC, encoding="utf-8")
    return KGEngine(project, tmp_path / "data", source_path=src, pack_path=PACK), src


def _edge(span):
    return {"source": "rmssd", "target": "frustration", "relation": "approximates", "span": span,
            "source_file": "doc.md"}


def _stored(eng):
    return next(e for n in eng.canon.all_nodes() for e in n.edges if e.id == EID)


def test_a_later_passage_is_kept_beside_the_first(doc):
    eng, _ = doc
    assert eng.kg_write({"nodes": NODES, "edges": [_edge(ONE)]})["dispositions"]["ACCEPTED"] == 3
    out = eng.kg_write({"edges": [_edge(TWO)]})
    assert out["also_stated"] == [EID]
    edge = _stored(eng)
    assert edge.span == ONE and ev.also_passages(edge.notes) == [(TWO, "doc.md")]
    assert [s["covered"] for s in eng._coverage([edge])["sections"]] == [True, True]
    assert "also_stated" not in eng.kg_write({"edges": [_edge(TWO)]})           # the same passage again: nothing
    assert "also_stated" not in eng.kg_write({"edges": [_edge(ONE)]})


def test_a_stale_first_passage_is_replaced(doc):
    eng, src = doc
    eng.kg_write({"nodes": NODES, "edges": [_edge(ONE)]})
    src.write_text(f"## Two\n\nAgain, {TWO}.\n", encoding="utf-8")            # the first passage is gone
    out = eng.kg_write({"edges": [_edge(TWO)]})
    assert "also_stated" not in out and _stored(eng).span == TWO


THREE = "RMSSD approximates frustration once the task gets harder"


def test_a_re_anchored_edge_keeps_the_passages_that_still_verify(doc):
    eng, src = doc
    src.write_text(DOC + f"\n## Three\n\n{THREE}.\n", encoding="utf-8")
    eng.kg_write({"nodes": NODES, "edges": [_edge(ONE)]})
    eng.kg_write({"edges": [_edge(TWO)]})
    src.write_text(f"## Two\n\nAgain, {TWO}.\n\n## Three\n\n{THREE}.\n", encoding="utf-8")   # §One is gone
    eng.kg_write({"edges": [_edge(THREE)]})
    edge = _stored(eng)
    assert edge.span == THREE and ev.also_passages(edge.notes) == [(TWO, "doc.md")]


def test_the_same_passage_written_again_updates_the_edge(doc):
    # an extractor restating its own edge with another confidence: the write applies, as through 0.23.0, and the
    # passage kept beside it stays (tests/test_kg_ground_plan.py marks an edge weak this way)
    eng, _ = doc
    eng.kg_write({"nodes": NODES, "edges": [_edge(ONE)]})
    eng.kg_write({"edges": [_edge(TWO)]})
    out = eng.kg_write({"edges": [{**_edge(ONE), "confidence": "AMBIGUOUS", "notes": "restated"}]})
    edge = _stored(eng)
    assert "also_stated" not in out and edge.confidence.value == "AMBIGUOUS"
    assert edge.notes.startswith("restated | ") and ev.also_passages(edge.notes) == [(TWO, "doc.md")]


def test_the_same_words_in_another_file_are_another_passage(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    for name in ("a.md", "b.md"):
        (notes / name).write_text(f"## {name}\n\n{ONE}.\n", encoding="utf-8")
    eng = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    eng.kg_write({"nodes": NODES, "edges": [{**_edge(ONE), "source_file": "a.md"}]})
    out = eng.kg_write({"edges": [{**_edge(ONE), "source_file": "b.md"}]})
    assert out["also_stated"] == [EID] and ev.also_passages(_stored(eng).notes) == [(ONE, "b.md")]
    plan = eng.kg_build_plan("", "")
    assert [s["covered"] for f in plan["files"] for s in f["sections"]] == [True, True]


def test_at_most_eight_passages_are_kept_beside_the_first(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    lines = [f"RMSSD approximates frustration in session {i}" for i in range(12)]
    src = tmp_path / "doc.md"
    src.write_text("\n\n".join(f"## S{i}\n\n{line}." for i, line in enumerate(lines)) + "\n", encoding="utf-8")
    eng = KGEngine(project, tmp_path / "data", source_path=src, pack_path=PACK)
    eng.kg_write({"nodes": NODES, "edges": [_edge(lines[0])]})
    for line in lines[1:]:
        eng.kg_write({"edges": [_edge(line)]})
    edge = _stored(eng)
    assert edge.span == lines[0] and [sp for sp, _f in ev.also_passages(edge.notes)] == lines[1:1 + ev.ALSO_MAX]


def test_the_build_plan_counts_the_kept_passages(doc):
    eng, _ = doc
    eng.kg_write({"nodes": NODES, "edges": [_edge(ONE)]})
    eng.kg_write({"edges": [_edge(TWO)]})
    plan = eng.kg_build_plan("", "")
    assert [s["covered"] for s in plan["files"][0]["sections"]] == [True, True] and plan["sections_uncovered"] == 0


# --------------------------------------------------------------------------- page furniture

def test_html_text_3_keeps_the_main_part_and_drops_the_furniture():
    page = ("<header><nav>Search | Log in</nav><h1>The masthead title</h1></header>"
            "<div class='c-article-main eds-l-with-sidebar'><main>"
            "<h2>Results</h2><p>Experts were slower with suggestions on.</p>"
            "<section class='c-article-recommendations'><h2>Similar content being viewed by others</h2><p>x</p></section>"
            "<section class='app-explore-related-subjects'><h2>Explore related subjects</h2></section>"
            "<div class='related-work'><h2>Related work</h2><p>Earlier studies found the same.</p></div>"
            "<aside><h2>Sidebar</h2></aside><div role='complementary'>More</div>"
            "</main></div><footer>Contact</footer>")
    title, text, meta = ev.html_text(page)
    assert "Experts were slower" in text and "Related work" in text and "Earlier studies" in text
    for gone in ("masthead", "Search", "Similar content", "Explore related", "Sidebar", "More", "Contact"):
        assert gone not in text, gone
    assert ev.HTML_EXTRACTOR == "html-text/3"


def test_a_main_part_of_divs_ends_at_its_own_closing_tag():
    # the furniture <div>s inside a <div role="main"> are counted as they close, so the page after it stays out
    page = ("<div role='main'><h2>A</h2><p>Inside the article.</p>"
            "<div class='share-box'><div>Share</div><div>Tweet</div></div>"
            "<p>Still inside.</p></div><div><p>After the main part.</p></div>")
    _title, text, _meta = ev.html_text(page)
    assert "Inside the article." in text and "Still inside." in text
    assert "Share" not in text and "Tweet" not in text and "After the main part." not in text


def test_a_page_without_main_keeps_its_whole_body():
    title, text, meta = ev.html_text("<h2>Intro</h2><p>Plain page text.</p><div class='share-buttons'>Share</div>")
    assert "Plain page text." in text and "Share" not in text


def test_the_skip_rule():
    assert skip_reason("References", "## References\n- a") == "reference-list"
    assert skip_reason("9 References", "x" * 500) == "reference-list"
    assert skip_reason("Referencias", "x" * 500) == "reference-list"
    assert skip_reason("Publisher’s Note", "## P\n" + "y" * 300) == "back-matter"
    assert skip_reason("Funding", "## Funding\n" + "y" * 300) == "back-matter"
    assert skip_reason("Data Availibility Statement", "x" * 500) == "back-matter"   # the Copilot article's typo
    assert skip_reason("Abstract", "## Abstract\n") == "empty"
    assert skip_reason("8 Results", "## 8 Results\n\n---\n") == "empty"
    # a one-line note can state an edge: a short section is planned
    assert skip_reason("Argumento", "## Argumento\nLa fábrica funciona cuando verifica cada cambio.\n") == ""
    assert skip_reason("Related Work", "## Related Work\n" + "z" * 300) == ""
    assert skip_reason("Notes", "## Notes\n" + "z" * 300) == ""
    assert parse_arguments("--all").every and parse_arguments("--all paper.md 3").subset == "paper.md"
    assert not parse_arguments("paper.md").every


def test_the_build_plan_leaves_them_out_unless_asked(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    src = tmp_path / "paper.md"
    src.write_text("## Abstract\n\n## Results\n\nExperts were slower with suggestions on.\n\n## References\n\n"
                   "- Smith 2020.\n- Jones 2021.\n\n## Funding\n\n" + "Public grant. " * 10 + "\n", encoding="utf-8")
    eng = KGEngine(project, tmp_path / "data", source_path=src, pack_path=PACK)
    plan = eng.kg_build_plan("", "")
    rows = {r["title"]: r for r in plan["files"][0]["sections"]}
    assert rows["Abstract"]["skipped"] == "empty" and rows["References"]["skipped"] == "reference-list"
    assert rows["Funding"]["skipped"] == "back-matter" and "skipped" not in rows["Results"]
    assert (plan["sections_uncovered"], plan["sections_skipped"], plan["waves"]) == (1, 3, 1)
    every = eng.kg_build_plan("--all", "")
    assert (every["sections_uncovered"], every["sections_skipped"]) == (4, 0)


# --------------------------------------------------------------------------- the legacy read leaves nothing behind

def test_reading_the_shared_index_creates_no_side_files(tmp_path):
    project = tmp_path / "mine"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    eng = KGEngine(project, tmp_path / "root", pack_path=PACK)
    eng.kg_write({"nodes": [{"id": n, "label": n, "node_type": "claim"} for n in ("alpha-node", "beta-node")]})
    eng.kg_context()
    legacy = tmp_path / "root" / "derived"
    for side in ("index.sqlite-shm", "index.sqlite-wal"):
        (legacy / side).unlink(missing_ok=True)
    before = sorted(q.name for q in legacy.iterdir())
    target = tmp_path / "root" / "projects" / envconfig.project_key(project)
    assert adopt_shared_derived(tmp_path / "root", target, project) == ["index.sqlite", "graph.json"]
    assert sorted(q.name for q in legacy.iterdir()) == before


# --------------------------------------------------------------------------- a legacy flag and the verdict's second

def test_a_file_written_in_the_verdicts_second_counts_as_changed_after_it(tmp_path):
    # A flag stored before 0.22.3 names no file and is re-tested against the files changed after its item's
    # verdict, both clocks to the second. Through 0.23.0 a file written in the verdict's own second was left out,
    # so with another file changed later the flag was tested against that one alone and dropped (1 run in 20 of
    # test_fix_reexamination_answered.py::test_a_0_22_3_flag_is_retested_against_the_files_it_names; once on
    # macOS CI after the 0.23.0 merge). The clocks are pinned here, so it fails every time, not 1 in 20.
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "notes.md").write_text("## Notes\n\nDegree approximates importance in every sampled network.\n",
                                    encoding="utf-8")
    eng = KGEngine(project, tmp_path / "data", source_path=notes, pack_path=PACK)
    eng.kg_propose({"edges": [{"source": "gamma", "target": "delta", "relation": "bridges"}]})
    eid = edge_id("gamma", "bridges", "delta")
    assert eng.kg_ground(eid, "rejected", note="no-support: the notes never join them")["ok"]
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    names = {}
    for fname, text in (("preprint.md", "## Findings\n\nGamma bridges delta in the factories we watched.\n"),
                        ("post.md", "## Post\n\nOmega, sigma and the rest.\n")):
        (downloads / fname).write_text(text, encoding="utf-8")
        out = eng.kg_source_add(path=str(downloads / fname), level=4, role="primary")
        assert out["ok"], out
        names[fname] = out["name"]
    audit = read_audit_index(eng.canon.root / GROUND_AUDIT)
    second = datetime.fromisoformat(audit.last_at[audit_key("edge", eid)]).timestamp()
    os.utime(project / "evidence" / names["preprint.md"], (second + 0.4, second + 0.4))   # the verdict's second
    os.utime(project / "evidence" / names["post.md"], (second + 5, second + 5))           # a later change
    nodes = {n.id: n for n in eng.canon.all_nodes()}
    edge = next(e for n in nodes.values() for e in n.edges if e.id == eid)
    entry = {"item_id": eid, "kind": "edge", "state": "rejected", "reason": "source-set-changed-since-judged"}

    def retest():
        return eng.projector._retest_before_0_22_4(entry, edge, "edge", nodes, eng.verify_set(), audit, {})

    assert retest() == (True, [names["preprint.md"]])
    # a tie never drops a flag: with only files from the verdict's second, none bearing on the item, the flag
    # stays as it was (test_fix_reexaminable_own_file.py's upgrade test, whose files share that second)
    for fname, at in (("preprint.md", second - 30), ("post.md", second + 0.4)):
        os.utime(project / "evidence" / names[fname], (at, at))
    assert retest() == (True, None)
    # a later change none of the files bears on drops it, as 0.22.4 does
    os.utime(project / "evidence" / names["post.md"], (second + 5, second + 5))
    assert retest() == (False, None)


# --------------------------------------------------------------------------- the texts

def test_the_commands_say_what_to_do():
    build = _flat((REPO / "commands" / "kg-build.md").read_text(encoding="utf-8"))
    assert "**`--all` as the first word** (0.23.1) plans every section" in build
    assert "A section is to extract when it is neither covered, edgeless nor skipped." in build
    sources = _flat((REPO / "commands" / "kg-sources.md").read_text(encoding="utf-8"))
    assert "`fetch-blocked` (0.23.1): the site sent the engine a bot check" in sources
