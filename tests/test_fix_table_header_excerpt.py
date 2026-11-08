"""0.8.0: a span in a body row of a long table reaches the grounder under the table's header.

Field report on 0.7.0: `kg_ground_item` cut the 60-line mechanism matrix of «Retirar revisión humana» (8 346
characters, over the 3 000-character excerpt cap) down to the rows around each span, and dropped the row that
names the columns (`| Mecanismo | Cubre | I/D/R | … |`). Four edges came from that matrix: one grounder guessed
what the columns meant and grounded three, another judged the fourth row "two bare cells" and rejected it.
`span_excerpt` now keeps the header and rule rows on top, with a `…` line where it skipped rows.
"""
from __future__ import annotations

from pathlib import Path

from kg_engine.groundplan import EXCERPT_CHARS, TABLE_GAP, span_excerpt
from kg_engine.server import KGEngine

PACK = Path(__file__).resolve().parents[1] / "pack" / "pack.yaml"
HEADER = "| Mecanismo | Cubre | I/D/R | Madurez |"
RULE = "| --- | --- | --- | --- |"
ROW = "| Escenarios reservados | Sobreajuste a tests visibles | D | Toda en StrongDM |"
SPAN = "Escenarios reservados | Sobreajuste a tests visibles"


def _matrix(at: int = 40, n: int = 60) -> str:
    rows = [f"| Mecanismo {i} con un nombre largo de relleno | Fallo {i} que cubre | I | Madura {i} y probada |"
            for i in range(n)]
    rows[at] = ROW
    return "\n".join([HEADER, RULE] + rows)


def test_a_row_far_down_a_long_table_keeps_the_header():
    table = _matrix()
    assert len(table) > EXCERPT_CHARS                      # the table alone is over the cap, as in the field
    got = span_excerpt("## Matriz\n\nLeyenda de las columnas.\n\n" + table, SPAN)
    assert got.split("\n")[:3] == [HEADER, RULE, TABLE_GAP]
    assert ROW in got and len(got) <= EXCERPT_CHARS


def test_a_row_right_under_the_header_needs_no_gap_line():
    got = span_excerpt(_matrix(at=0), SPAN)
    assert got.split("\n")[:3] == [HEADER, RULE, ROW]
    assert TABLE_GAP not in got.split("\n")


def test_the_cap_still_holds():
    got = span_excerpt(_matrix(), SPAN, max_chars=400)
    assert got.startswith(HEADER) and ROW in got and len(got) <= 400


def test_a_header_too_wide_for_the_cap_is_left_out():
    wide = "| " + " | ".join(f"Columna {i}" for i in range(80)) + " |"
    rows = ["| a | b |"] * 100 + [ROW] + ["| c | d |"] * 100
    got = span_excerpt("\n".join([wide, "|" + "---|" * 80] + rows), SPAN, max_chars=400)
    assert ROW in got and not got.startswith("| Columna") and len(got) <= 400


def test_lines_without_a_rule_row_are_cut_as_before():
    rows = [f"| fila {i} | valor {i} |" for i in range(400)]
    rows[200] = "| control estadístico | no sirve aquí |"
    got = span_excerpt("\n".join(rows), "control estadístico | no sirve aquí", max_chars=300)
    assert "control estadístico" in got and not got.startswith("| fila 0 |") and len(got) <= 300


def test_kg_ground_item_hands_the_grounder_the_header(vault: Path, tmp_path: Path):
    src = tmp_path / "matriz.md"
    src.write_text("## Matriz de mecanismos\n\nLeyenda.\n\n" + _matrix() + "\n", encoding="utf-8")
    e = KGEngine(vault, source_path=src, pack_path=PACK)
    out = e.kg_write({"nodes": [{"id": "escenarios-reservados", "label": "Escenarios reservados",
                                 "node_type": "operation"},
                                {"id": "sobreajuste", "label": "Sobreajuste a tests visibles", "node_type": "failure"}],
                      "edges": [{"source": "escenarios-reservados", "target": "sobreajuste",
                                 "relation": "defends_against", "span": SPAN, "source_file": "matriz.md"}],
                      "complete": True})
    assert out["dispositions"]["ACCEPTED"] == 3, out
    excerpt = e.kg_ground_item("e_escenarios-reservados__defends-against__sobreajuste")["context"]["excerpt"]
    assert excerpt.split("\n")[:3] == [HEADER, RULE, TABLE_GAP] and ROW in excerpt
