"""0.12.0 — /kg-experiment scores grounded novelty and compares arms prompt by prompt.

Three field runs on the Windows corpus (eight Spanish documents, 445,018 characters; 2026-11-10 and 11)
returned the same negative headline, and the 0.11.x rule could not have returned another:
- novelty is distance from the source, and the control arm never sees the source (0.91 against the graph arm's
  0.71-0.76), while the rule required graph >= control on novelty;
- the unsupported-claim guard passed a sentence when any of its first three long words occurred anywhere in the
  source, and its own probe passed 140 of 143, 171 of 173 and 181 of 181 sentences with an invented word;
- one pooled number per arm with a no-regression rule let differences of 0.003 decide.

The method is pre-declared in docs/fusion/EXPERIMENT.md ("Stage 8 method, 0.12.0"):
- **support** of a sentence is the share of its key terms' IDF weight that the source holds. Terms are compared
  by stem, so an inflection is not an invention; an invented term weighs the most.
- **grounded novelty** of an idea is novelty × support.
- **pairs** are compared prompt by prompt with a one-sided sign test (10 of 12, as in D1): graph vs rag is the
  headline, then graph vs control, graph+generate vs graph, graph+generate+dpp vs graph+generate and graph vs
  lightrag.
- **an instrument check**, rag's support exceeding control's by 0.10, gates every verdict that uses support.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kg_engine import harness
from kg_engine.harness import _SupportIndex, ideation, sign_test_needed

REPO = Path(__file__).resolve().parents[1]
DEMO = (REPO / "examples" / "source.md").read_text(encoding="utf-8")

RAG = ["A compression is a single idea that stands in for many observations, and it earns its keep only when it "
       "predicts.",
       "Span-present provenance grounds a claim more strongly than inference, because the verifiable span is the "
       "check.",
       "Raw betweenness is the natural bridge metric but it is confounded by the generality confound.",
       "A failed claim is negative information that must be recorded and never pruned.",
       "The derived projection is regenerable and disposable, and it must contain nothing the canon does not."]
GRAPH = ["Specificity weighting would expose a vague node, because its terms are not rare enough to earn betweenness.",
         "Negative compression could bridge compression and failures: a failed claim compresses many refuted "
         "observations.",
         "A defending claim would record the refuted span and reject any re-proposal that collapses into it.",
         "The derived projection should never contain anything the canon lacks; the reconciler re-attaches verdicts.",
         "Genuine bridges join separate communities, while a vague hub merely overlaps everything loosely."]
CONTROL = ["Popularity bias lets heavily mentioned topics accumulate influence regardless of their substance.",
           "Participation coefficients measure how evenly connections spread across separate modules.",
           "Keeping a blocklist of rejected statements prevents teams from repeating earlier mistakes.",
           "Caching layers sometimes store computed fields that are missing from the upstream database.",
           "Recency bias makes newer ideas look novel simply because reviewers saw them last."]


# --------------------------------------------------------------------------- the measures

def test_terms_are_compared_by_stem():
    assert harness._stem("Compararía") == "compar" == harness._stem("compara")
    assert harness._sentence_stems("La revisión humana compararía revisiones") == ["revisi", "humana", "compar"]


def test_an_inflection_is_not_an_invention():
    index = _SupportIndex(source_text="El equipo compara los incidentes de cada despliegue.\n")
    assert index.coverage(harness._sentence_stems("compararía incidentes despliegues")) == 1.0


def test_an_invented_term_costs_more_than_a_common_one():
    paragraphs = "\n\n".join([f"Los cambios del sistema número {k} pasan la revisión." for k in range(20)]
                             + ["Solo aquí aparece el clasificador Zalando."])
    index = _SupportIndex(source_text=paragraphs)
    with_rare = index.coverage(["cambio", "sistem", "clasif"])        # all present; "clasif" in one paragraph
    with_invented = index.coverage(["cambio", "sistem", "zqxjvb"])    # an invented term in its place
    assert with_rare == 1.0 and with_invented < 0.5
    # the invented term weighs more than any present one
    assert index.idf("zqxjvb") > index.idf("clasif") > index.idf("cambio")


def test_terms_from_two_paragraphs_are_supported_together():
    # the first draft required one paragraph, which penalized an idea linking two parts of the source
    index = _SupportIndex(source_text="Zalando enruta por reglas.\n\nMeta filtra los cambios por riesgo.\n")
    assert index.coverage(harness._sentence_stems("Zalando filtraría cambios por riesgo")) == 1.0


def test_an_idea_with_nothing_to_judge_has_no_support():
    row = harness._score_condition(["Muy corto.", "Tiny one here."], DEMO)
    assert row["support"] == 0.0 and row["grounded_novelty"] == 0.0


def test_grounded_novelty_is_novelty_times_support():
    index = _SupportIndex(source_text=DEMO)
    s = harness._idea_scores(GRAPH[0], harness._ngrams(DEMO), index)
    assert s["grounded"] == pytest.approx(s["novelty"] * s["support"])


def test_the_table_reports_every_column():
    res = ideation({"control": CONTROL, "graph": GRAPH, "rag": RAG}, DEMO)
    for row in res["table"].values():
        assert set(row) == {"n", "diversity", "novelty", "support", "grounded_novelty", "utility",
                            "unsupported_rate"}


# --------------------------------------------------------------------------- the decision rule

@pytest.mark.parametrize("n", [5, 8, 12, 20])
def test_the_wins_needed_are_the_sign_tests(n):
    k = sign_test_needed(n)
    tail = lambda k: sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n  # noqa: E731
    assert tail(k) <= 0.05 < tail(k - 1)


def test_twelve_prompts_need_ten_wins_as_in_d1():
    assert sign_test_needed(12) == 10
    assert sign_test_needed(4) is None


def _grounded_lists(xs, ys):
    return {"graph": xs, "rag": ys}


def test_ten_of_twelve_beats_and_nine_does_not():
    ten = harness._paired([0.5] * 10 + [0.1] * 2, [0.2] * 12)
    nine = harness._paired([0.5] * 9 + [0.1] * 3, [0.2] * 12)
    assert harness._pair_verdict("graph", "rag", ten, None) == "graph beat rag on grounded novelty in 10 of 12 prompts"
    assert harness._pair_verdict("graph", "rag", nine, None) == \
        "graph did NOT clearly beat rag on grounded novelty (9 of 12 prompts; 10 needed)"


def test_a_tie_counts_against_the_challenger():
    cmp = harness._paired([0.204] * 12, [0.2] * 12)        # within the 0.005 tie band every time
    assert (cmp["wins"], cmp["ties"]) == (0, 12)


def test_too_few_prompts_to_decide():
    cmp = harness._paired([0.9] * 3, [0.1] * 3)
    assert harness._pair_verdict("graph", "rag", cmp, None).startswith("graph vs rag: too few prompts to decide (3;")


def test_the_field_shape_can_now_be_won():
    # control is the most novel but unanchored, as on the field corpus; 0.11.x could never let graph win here
    res = ideation({"control": CONTROL, "graph": GRAPH, "rag": RAG}, DEMO)
    t = res["table"]
    assert t["control"]["novelty"] > t["graph"]["novelty"]
    assert res["support_check"]["valid"] is True
    assert res["verdict"] == "graph beat rag on grounded novelty in 5 of 5 prompts"
    assert res["control_verdict"] == "graph beat control on grounded novelty in 5 of 5 prompts"


def test_the_pairs_are_the_declared_ones():
    res = ideation({"control": CONTROL, "graph": GRAPH, "graph+generate": RAG, "graph+generate+dpp": GRAPH,
                    "rag": RAG, "lightrag": CONTROL}, DEMO)
    assert set(res["comparisons"]) == {"graph vs rag", "graph vs control", "graph+generate vs graph",
                                       "graph+generate+dpp vs graph+generate", "graph vs lightrag"}
    assert "beat graph on grounded novelty" in res["generate_verdict"] or "clearly beat graph" in \
        res["generate_verdict"]                                    # generation is measured against graph now
    assert "the LightRAG baseline" in res["lightrag_verdict"]


def test_the_headline_is_always_present():
    assert ideation({"control": CONTROL}, DEMO)["verdict"] == "insufficient data"
    assert "verdict" not in ideation({"control": CONTROL}, DEMO)["comparisons"]


def test_a_failed_check_marks_every_support_verdict_not_measured():
    res = ideation({"control": RAG, "graph": GRAPH, "rag": RAG}, DEMO)   # control written like rag
    assert res["support_check"]["valid"] is False
    assert res["verdict"].startswith("not measured: ") and res["control_verdict"].startswith("not measured: ")
    assert any(c.startswith("support does not separate") for c in res["caveats"])


def test_an_unchecked_run_says_so():
    res = ideation({"graph": GRAPH, "rag": RAG}, DEMO)                  # no control arm
    assert res["support_check"]["valid"] is None
    assert any(c.startswith("support was not checked") for c in res["caveats"])
    assert not res["verdict"].startswith("not measured")


def test_prompts_stay_aligned_when_an_idea_is_not_a_string():
    graph = [None, *GRAPH[1:]]                                          # malformed JSON at prompt 1
    res = ideation({"graph": graph, "rag": RAG, "control": CONTROL}, DEMO)
    cmp = res["comparisons"]["graph vs rag"]
    assert cmp["n"] == 5 and cmp["losses"] >= 1                         # prompt 1 lost, prompts 2-5 still paired


# --------------------------------------------------------------------------- the command line

def test_a_folder_source_is_indexed_one_document_at_a_time(tmp_path):
    (tmp_path / "a.md").write_text("Primer documento sin salto final", encoding="utf-8")
    (tmp_path / "b.md").write_text("Segundo documento\n", encoding="utf-8")
    documents = harness.SourceSet(str(tmp_path)).texts
    assert _SupportIndex(documents=documents).n == 2
    assert _SupportIndex(source_text=harness.SourceSet(str(tmp_path)).concat).n == 1   # what concat would merge


def test_the_scores_do_not_depend_on_the_hash_seed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "source.md").write_text(DEMO, encoding="utf-8")
    outputs = tmp_path / "outputs.json"
    outputs.write_text(json.dumps({"outputs": {"control": CONTROL, "graph": GRAPH, "rag": RAG}}), encoding="utf-8")
    runs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONPATH": str(REPO / "scripts"), "PYTHONHASHSEED": seed}
        r = subprocess.run([sys.executable, "-m", "kg_engine.harness", "ideation", str(outputs), str(src)],
                           capture_output=True, env=env, timeout=120)
        assert r.returncode == 0, r.stderr.decode()
        runs.append(r.stdout)
    assert runs[0] == runs[1]
