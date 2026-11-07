"""0.6.0: kg_section shows each extractor the canon nodes its section names, so ids get reused across sections.

Field report on 0.5.2, a full /kg-build of an 8-file Spanish corpus (84 sections, 486 nodes): each extractor
named its nodes without seeing the canon, so one concept written by two sections landed under two ids about
19 times (`radar` / `meta-radar`, `pass-at-k` / `pass-k`, `experimento-con-oraculo` /
`experimentos-con-oraculo`...), and 102 nodes ended with no edge at all.

kg_section now returns `known_nodes`: up to 60 canon nodes whose NAME the section mentions (at least half the
content words of the id or the label, singular or plural, accents and function words ignored), ranked by
how specifically they are named (a rarity weight over the canon's names), then degree, then id. The match
only decides what the extractor is shown; reusing an id stays the extractor's judgment, and nothing is merged.
Measured offline on that build's own canon and sections, two members of 16 of its 18 duplicate groups appear
together in some section's list. The two misses are a translation and a pair of synonyms with no word in
common.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.buildplan import KNOWN_NODES_LIMIT, related_nodes
from kg_engine.model import Node
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # GitHub-token SHAPED, not a real one


def _ids(text: str, nodes, **kw) -> "list[str]":
    return [n.id for n in related_nodes(text, nodes, **kw)[0]]


# ---- what counts as named ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,node", [
    ("El RADAR de Meta mide el riesgo.", Node(id="meta-radar", label="Meta RADAR")),       # half its words
    ("un experimento con oráculo", Node(id="experimentos-con-oraculo", label="Experimentos con oráculo")),
    ("las señales externas", Node(id="senal-externa", label="Señal externa")),             # plural → singular
    ("Vercel redujo un 58 % sus PR", Node(id="vercel-58-monorepo", label="Vercel 58")),     # a number counts
    ("pass@k sube con k", Node(id="pass-at-k", label="pass@k")),
    ("la revisión humana del código", Node(id="revision-humana", label="Revisión humana")),
])
def test_a_section_names_a_node_by_its_words_accents_and_plurals_aside(text, node):
    assert _ids(text, [node]) == [node.id]


@pytest.mark.parametrize("text,node", [
    ("la revisión del código", Node(id="revision-humana-con-agentes", label="Revisión humana con agentes")),
    ("de la y en el", Node(id="de-la", label="de la")),                                    # function words only
    ("RADAR", Node(id="a", label="b")),                                                    # one-letter words
])
def test_a_passing_word_or_function_words_do_not_name_a_node(text, node):
    assert _ids(text, [node]) == []


def test_a_rarely_named_word_outranks_a_common_one():
    # `codigo` is in many names and `radar` in one, so of two names found whole, the one found through the
    # rare word is the more specific match and leads.
    common = [Node(id=f"codigo-{w}", label=f"código {w}") for w in ("limpio", "abierto", "legado", "fuente")]
    plain = Node(id="revision-codigo", label="Revisión del código")
    rare = Node(id="revision-radar", label="Revisión RADAR")
    ids = _ids("La revisión del código usa RADAR.", common + [plain, rare])
    assert ids[:2] == ["revision-radar", "revision-codigo"]


def test_ties_break_by_degree_then_id_so_every_run_agrees():
    nodes = [Node(id="b-radar", label="b radar"), Node(id="a-radar", label="a radar"),
             Node(id="c-radar", label="c radar")]
    text = "radar a b c"
    assert _ids(text, nodes) == ["a-radar", "b-radar", "c-radar"]
    assert _ids(text, nodes, degree={"c-radar": 5}) == ["c-radar", "a-radar", "b-radar"]


def test_the_list_is_capped_and_counts_what_it_cut():
    nodes = [Node(id=f"radar-{i:03d}", label=f"radar {i:03d}") for i in range(KNOWN_NODES_LIMIT + 15)]
    shown, total = related_nodes("radar " + " ".join(f"{i:03d}" for i in range(200)), nodes)
    assert (len(shown), total) == (KNOWN_NODES_LIMIT, KNOWN_NODES_LIMIT + 15)
    assert KNOWN_NODES_LIMIT == 60


# ---- through kg_section -----------------------------------------------------------------------------

@pytest.fixture
def eng(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "doc.md"
    src.write_text("## Uno\nEl RADAR de Meta mide el riesgo de cada cambio.\n\n"
                   "## Dos\nMeta RADAR vuelve a medir el riesgo, ahora con experimentos con oráculo.\n",
                   encoding="utf-8")
    return KGEngine(vault, source_path=src, pack_path=REPO / "pack" / "pack.yaml")


def _write_section_one(eng: KGEngine) -> None:
    out = eng.kg_write({"nodes": [{"id": "meta-radar", "label": "Meta RADAR", "node_type": "metric"}],
                        "edges": [{"source": "meta-radar", "target": "riesgo-de-cambio", "relation": "approximates",
                                   "span": "El RADAR de Meta mide el riesgo de cada cambio",
                                   "source_file": "doc.md"}], "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 2, out              # the node and the edge


def test_an_empty_canon_shows_nothing(eng):
    got = eng.kg_section("doc.md", 2)
    assert (got["ok"], got["known_nodes"], got["known_nodes_more"]) == (True, [], 0)


def test_a_later_section_sees_the_node_an_earlier_one_wrote(eng):
    _write_section_one(eng)
    got = eng.kg_section("doc.md", 2)
    assert {"id": "meta-radar", "label": "Meta RADAR", "node_type": "metric"} in got["known_nodes"]
    assert got["text"].startswith("## Dos\n")                       # the section itself is unchanged


def test_labels_leave_through_the_egress_scrub(eng):
    _write_section_one(eng)
    eng.canon.write_nodes([Node(id="meta-radar-clave", label=f"Meta RADAR {TOKEN}")], message="seed")
    got = eng.kg_section("doc.md", 2)
    assert TOKEN not in str(got["known_nodes"])


def test_an_unreadable_canon_still_serves_the_section(eng, monkeypatch):
    def boom():
        raise OSError("disk gone")

    monkeypatch.setattr(eng, "_canon_baseline", boom)
    got = eng.kg_section("doc.md", 1)
    assert got["ok"] and got["known_nodes"] == [] and got["text"].startswith("## Uno")


def test_a_wave_of_sections_parses_the_canon_once(eng, monkeypatch):
    _write_section_one(eng)
    eng.kg_section("doc.md", 1)                                      # warm the baseline cache
    calls = []
    real = eng.canon.all_nodes
    monkeypatch.setattr(eng.canon, "all_nodes", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(5):
        eng.kg_section("doc.md", 2)
    assert calls == []


# ---- the texts that wire it together ----------------------------------------------------------------

def test_the_extractor_reuses_an_id_only_for_the_same_concept():
    flat = " ".join(EXTRACTOR.split())
    assert "**`kg_section` also returns `known_nodes`**" in flat
    assert "**The same concept → its id.**" in flat
    assert "**Never for a broader, narrower or merely related concept.**" in flat
    assert "**When in doubt, create a new node.**" in flat
    assert "**Do not redeclare a known node in `nodes[]`.**" in flat


def test_the_launch_template_mentions_the_known_nodes():
    flat = " ".join(CMD.split())
    assert ("reuse a known node's id only for the same concept, and never redeclare it in nodes[]" in flat)
