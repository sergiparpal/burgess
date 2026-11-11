"""Stage 6 — the graph+generate+dpp experiment arm (FUSION_PLAN §13).

The vendored harness is arm-tolerant; these tests pin the new arm's canonical
position and the dedicated dpp_verdict (the D1 comparison surface).
"""
from __future__ import annotations

from kg_engine.harness import _CANONICAL_ARMS, ideation

SOURCE = ("entropy grounds the arrow of time. betweenness measures bridges. "
          "compression predicts observations. falsification defends against failures. "
          "provenance carries spans. communities connect through genuine bridges.")


def _ideas(diverse: bool, prompts: int = 10) -> list[str]:
    # 0.12.0 compares arms prompt by prompt with a one-sided sign test, which needs at least five prompts to
    # decide (10 of 12, as in D1); three ideas are cycled over `prompts` prompts.
    if diverse:
        # the source's own terms in new orders: novel word sequences whose key terms still meet in the source
        # (0.12.0 scores grounded novelty, and a word the source lacks counts against support)
        base = [
            "Genuine bridges connect communities, and provenance carries spans.",
            "Falsification defends betweenness against failures through genuine provenance.",
            "Compression predicts bridges; communities carries entropy through observations.",
        ]
    else:
        base = [
            "entropy grounds the arrow of time in the graph.",
            "entropy grounds the arrow of time for bridges.",
            "entropy grounds the arrow of time again.",
        ]
    return [base[k % len(base)] for k in range(prompts)]


def test_arm_is_canonical_and_ordered_after_graph_generate():
    assert "graph+generate+dpp" in _CANONICAL_ARMS
    assert _CANONICAL_ARMS.index("graph+generate+dpp") == _CANONICAL_ARMS.index("graph+generate") + 1


def test_dpp_verdict_present_and_directional():
    out = ideation({"control": _ideas(False), "graph": _ideas(True),
                    "graph+generate": _ideas(False), "graph+generate+dpp": _ideas(True)},
                   source_text=SOURCE)
    assert list(out["table"])[:4] == ["control", "graph", "graph+generate", "graph+generate+dpp"]
    assert out["dpp_verdict"].startswith("graph+generate+dpp beat graph+generate on grounded novelty")

    flipped = ideation({"graph+generate": _ideas(True), "graph+generate+dpp": _ideas(False)},
                       source_text=SOURCE)
    assert "did NOT clearly beat" in flipped["dpp_verdict"]


def test_dpp_verdict_absent_when_arm_missing():
    out = ideation({"control": _ideas(False), "graph": _ideas(True)}, source_text=SOURCE)
    assert "dpp_verdict" not in out
