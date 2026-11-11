"""0.13.0 — /kg-experiment --judge: the blind judge, shipped without novelty.

Three pilots (docs/fusion/EXPERIMENT.md, option D) fixed the instrument:
- a packet per prompt, holding every arm's idea plus a decoy and a positive control;
- each idea with its own evidence from the source, under the third pilot's rule;
- fresh judges scoring and ranking the items;
- validity checks on the controls in every run.

A calibration without judges then showed that evidence retrieved for an idea's own words cannot reveal a
paraphrase of the source. So the shipped judge scores grounded and useful, never novelty.

These tests pin the deterministic half (scripts/kg_engine/judge.py and its two harness subcommands), the
judge agent, the command's opt-in step and the hook's silence for the judge. On the field data, the module
reproduced the third pilot's packets byte for byte (1,632,453 bytes) and its aggregate.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from kg_engine import harness, judge

REPO = Path(__file__).resolve().parents[1]

DOCS = {
    "revision.md": (
        "El sistema RADAR de Meta aprueba solo cambios de bajo riesgo y los integra sin revisión humana.\n\n"
        "Con RADAR, las reversiones bajaron a 1/3 y los incidentes a 1/50 de los cambios revisados.\n\n"
        "La revisión humana sigue siendo necesaria para los cambios complejos que tocan varios equipos.\n\n"
        "Los autores parten sus cambios para quedar en bajo riesgo, lo que puede ser buena práctica o evasión."
    ),
    "agentes.md": (
        "Uber atribuye a agentes más del 70 % de sus cambios, incluido el uso interactivo.\n\n"
        "La diferencia con otras cifras se explicaría en parte por el cambio de definición.\n\n"
        "Faros mide un aumento del 154 % en el tamaño de los cambios y del 91 % en el tiempo de revisión.\n\n"
        "Los equipos pequeños revisan más rápido cuando los cambios son pequeños y frecuentes."
    ),
    "medidas.md": (
        "Para medir la seguridad hace falta comparar cambios del mismo riesgo con y sin revisión.\n\n"
        "Nadie publica una tasa de escapes comparable entre la vía revisada y la no revisada.\n\n"
        "Una métrica que se convierte en objetivo deja de medir bien lo que medía."
    ),
}
PROMPTS = [f"Pregunta {k} sobre revisión de cambios y seguridad" for k in range(1, 13)]
IDEAS = {
    "control": ["Un equipo podría revisar solo los cambios que tocan varias áreas del producto."] * 12,
    "graph": ["RADAR integra cambios de bajo riesgo, y sus reversiones bajaron a 1/3 de las revisadas."] * 12,
    "rag": ["Uber atribuye a agentes más del 70 % de sus cambios, incluido el uso interactivo."] * 12,
}
DECOY = "Un informe Valdrecht de 2025 halló que el 41 % de los cambios aprobados sin revisión se revertía."
POSITIVE = ("RADAR integra cambios de bajo riesgo con reversiones a 1/3, y Uber atribuye a agentes más del "
            "70 % de sus cambios; quizá ambas cifras dependan de qué cambios se cuentan.")


@pytest.fixture()
def evidence():
    return judge.Evidence(DOCS)


# --------------------------------------------------------------------------- evidence and order


def test_clauses_split_at_punctuation_and_coordinators():
    clauses = judge.Evidence.clauses("RADAR aprueba los cambios de bajo riesgo, y Uber atribuye a agentes "
                                     "más del 70 % de sus cambios porque cuenta el uso interactivo también.")
    assert "RADAR aprueba los cambios de bajo riesgo" in clauses
    # a coordinator right after a comma stays at the clause's head, as in the pilots' calibrated rule
    assert "y Uber atribuye a agentes más del 70 % de sus cambios" in clauses
    assert "cuenta el uso interactivo también." in clauses
    assert all(len(c.split()) >= judge.MIN_CLAUSE_WORDS for c in clauses)


def test_evidence_fills_the_ideas_figures_and_names(evidence):
    passages = evidence.build(POSITIVE)
    text = " ".join(p["text"] for p in passages)
    for term in ("RADAR", "1/3", "Uber", "70 %"):
        assert term in text
    assert sum(len(p["text"]) for p in passages) <= judge.EVIDENCE_CHARS


def test_evidence_stops_at_its_cap(evidence, monkeypatch):
    monkeypatch.setattr(judge, "EVIDENCE_CHARS", 120)
    passages = evidence.build(POSITIVE)
    assert sum(len(p["text"]) for p in passages) <= 120


def test_terms_split_held_from_invented(evidence):
    held, invented = evidence.terms(DECOY, skip_initial=True)
    assert "Valdrecht" in invented and "41 %" in invented
    held, invented = evidence.terms(POSITIVE, skip_initial=True)
    assert {"RADAR", "Uber", "70 %"} <= held and not invented


def test_item_order_is_the_pilots_rotation():
    items = ["control", "graph", "graph+generate", "graph+generate+dpp", "rag", "decoy", "positive"]
    # the third pilot's base order, which its packets and aggregate were built and checked with
    assert judge.item_order(items, 0) == ["decoy", "positive", "rag", "control", "graph+generate+dpp",
                                          "graph", "graph+generate"]
    for position in range(len(items)):
        assert sorted(judge.item_order(items, k)[position] for k in range(len(items))) == sorted(items)


# --------------------------------------------------------------------------- the controls' checks


def test_a_decoy_must_invent_its_support(evidence):
    ok = judge.check_controls(evidence, [DECOY], [POSITIVE])[0]
    assert ok["ok"], ok["problems"]
    bad = judge.check_controls(evidence, ["RADAR integra cambios de bajo riesgo con reversiones a 1/3."],
                               [POSITIVE])[0]
    assert not bad["ok"] and "decoy" in bad["problems"][0]


@pytest.mark.parametrize("positive, reason", [
    ("RADAR integra cambios de bajo riesgo según el estudio Halvorsen de 2024.", "does not hold"),
    ("Las reversiones de RADAR bajaron a 1/3 y sus incidentes a 1/50.", "fewer than two documents"),
    ("Quizá el sistema RADAR deba revisarse más a menudo.", "fewer than two"),
])
def test_a_positive_control_must_hold_real_spread_facts(evidence, positive, reason):
    result = judge.check_controls(evidence, [DECOY], [positive])[0]
    assert not result["ok"]
    assert any(reason in p for p in result["problems"]), result["problems"]


# --------------------------------------------------------------------------- packets


def test_packets_are_written_only_when_the_controls_pass(tmp_path):
    out = judge.build_packets(IDEAS, PROMPTS, DOCS, ["RADAR aprueba cambios."] * 12, [POSITIVE] * 12, tmp_path)
    assert out["written"] is False and len(out["checks"]) == 12
    assert (tmp_path / "private" / "checks.json").is_file()
    assert not (tmp_path / "packets").exists()


def test_packets_hide_the_arms_and_keep_the_mapping_private(tmp_path):
    out = judge.build_packets(IDEAS, PROMPTS, DOCS, [DECOY] * 12, [POSITIVE] * 12, tmp_path)
    assert out["written"] and out["packets"] == 12
    assert out["items"] == ["control", "graph", "rag", "decoy", "positive"]
    packets = sorted((tmp_path / "packets").glob("*.md"))
    assert [p.name for p in packets] == [f"{k:02d}.md" for k in range(1, 13)]
    first = packets[0].read_text(encoding="utf-8")
    assert re.findall(r"^## Idea ([A-Z])$", first, re.M) == list("ABCDE")
    for name in ("graph", "rag", "control", "decoy", "positive", "mapping"):
        assert name not in first.lower()
    mapping = json.loads((tmp_path / "private" / "mapping.json").read_text(encoding="utf-8"))
    assert mapping["packets"]["01"] == dict(zip("ABCDE", judge.item_order(out["items"], 0)))


def test_packets_are_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    judge.build_packets(IDEAS, PROMPTS, DOCS, [DECOY] * 12, [POSITIVE] * 12, a)
    judge.build_packets(IDEAS, PROMPTS, DOCS, [DECOY] * 12, [POSITIVE] * 12, b)
    for name in ("01.md", "07.md", "12.md"):
        assert (a / "packets" / name).read_bytes() == (b / "packets" / name).read_bytes()


def test_a_folder_with_verdicts_is_refused(tmp_path):
    (tmp_path / "verdicts").mkdir()
    (tmp_path / "verdicts" / "01.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already holds verdicts"):
        judge.build_packets(IDEAS, PROMPTS, DOCS, [DECOY] * 12, [POSITIVE] * 12, tmp_path)


def test_inputs_must_line_up(tmp_path):
    with pytest.raises(ValueError, match="one idea per prompt"):
        judge.build_packets({"graph": ["solo una idea"]}, PROMPTS, DOCS, [DECOY] * 12, [POSITIVE] * 12, tmp_path)
    with pytest.raises(ValueError, match="decoys"):
        judge.build_packets(IDEAS, PROMPTS, DOCS, [DECOY] * 11, [POSITIVE] * 12, tmp_path)


# --------------------------------------------------------------------------- aggregation


def _judged(tmp_path, n=12, graph_first=10, decoy_low=None, positive_high=None, drop=()):
    """A judge folder with synthetic verdicts over control, graph, rag and the two controls. Graph ranks above
    rag in the first `graph_first` prompts; the decoy is least grounded in `decoy_low` prompts and the
    positive control scores 5 in `positive_high` (all by default)."""
    items = ["control", "graph", "rag", "decoy", "positive"]
    decoy_low = n if decoy_low is None else decoy_low
    positive_high = n if positive_high is None else positive_high
    mapping = {"items": items, "seed": judge.SEED, "packets": {}}
    (tmp_path / "private").mkdir()
    (tmp_path / "verdicts").mkdir()
    for k in range(n):
        key = f"{k + 1:02d}"
        order = judge.item_order(items, k)
        labels = dict(zip("ABCDE", order))
        mapping["packets"][key] = labels
        lab = {item: label for label, item in labels.items()}
        grounded = {"control": 4, "graph": 4, "rag": 5, "decoy": 1 if k < decoy_low else 5,
                    "positive": 5 if k < positive_high else 2}
        best = ["graph", "rag"] if k < graph_first else ["rag", "graph"]
        ranking = best + ["positive", "control", "decoy"]
        verdict = {"scores": {lab[i]: {"grounded": grounded[i], "useful": 3} for i in items},
                   "ranking": [lab[i] for i in ranking], "notes": "synthetic"}
        if key not in drop:
            (tmp_path / "verdicts" / f"{key}.json").write_text(json.dumps(verdict), encoding="utf-8")
    (tmp_path / "private" / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    return tmp_path


def test_a_valid_judge_decides_on_its_rankings(tmp_path):
    result = judge.aggregate(_judged(tmp_path, graph_first=10))
    assert result["valid"] and result["n"] == 12 and not result["problems"]
    assert result["verdict"] == "graph beat rag in the judges' ranking in 10 of 12 prompts"
    assert result["control_verdict"] == "graph beat control in the judges' ranking in 12 of 12 prompts"
    assert "dpp_verdict" not in result and "generate_verdict" not in result
    assert result["means"]["decoy"]["grounded"] == 1 and result["means"]["rag"] == {"grounded": 5, "useful": 3}
    assert result["checks"]["v2_grounded_gap"]["gap"] == pytest.approx(3.333, abs=1e-3)


def test_too_few_wins_is_not_a_win(tmp_path):
    result = judge.aggregate(_judged(tmp_path, graph_first=9))
    assert result["verdict"] == "graph did NOT clearly beat rag in the judges' ranking (9 of 12 prompts; 10 needed)"


@pytest.mark.parametrize("kwargs, failed", [({"decoy_low": 9}, "v1_decoy_least_grounded"),
                                            ({"positive_high": 9}, "v3_positive_grounded")])
def test_a_failed_check_leaves_every_verdict_unmeasured(tmp_path, kwargs, failed):
    result = judge.aggregate(_judged(tmp_path, **kwargs))
    assert not result["valid"] and not result["checks"][failed]["passed"]
    assert result["verdict"].startswith("not measured: the judge failed its validity checks")
    assert failed in result["verdict"] and result["control_verdict"].startswith("not measured")


def test_fewer_than_five_prompts_decide_nothing(tmp_path):
    result = judge.aggregate(_judged(tmp_path, n=4, graph_first=4))
    assert not result["valid"]
    assert result["verdict"] == "not measured: too few prompts judged (4; the sign test needs at least 5)"


def test_a_missing_or_malformed_verdict_drops_its_prompt(tmp_path):
    folder = _judged(tmp_path, drop=("03",))
    bad = json.loads((folder / "verdicts" / "05.json").read_text(encoding="utf-8"))
    bad["scores"][bad["ranking"][0]]["useful"] = 6
    (folder / "verdicts" / "05.json").write_text(json.dumps(bad), encoding="utf-8")
    result = judge.aggregate(folder)
    assert result["n"] == 10
    assert any(p.startswith("03: no readable verdict") for p in result["problems"])
    assert any(p.startswith("05:") and "1 to 5" in p for p in result["problems"])


# --------------------------------------------------------------------------- the harness subcommands


def test_judge_subcommands_are_wired(tmp_path, capsys):
    assert harness._main(["judge-packets"]) == 2
    assert "usage: judge-packets" in capsys.readouterr().err
    assert harness._main(["judge-aggregate", str(tmp_path)]) == 2
    assert "private/mapping.json" in capsys.readouterr().err


def test_judge_packets_exits_3_when_a_control_fails(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    for name, text in DOCS.items():
        (src / name).write_text(text, encoding="utf-8")
    (tmp_path / "outputs.json").write_text(json.dumps({"outputs": IDEAS}), encoding="utf-8")
    (tmp_path / "prompts.json").write_text(json.dumps(PROMPTS), encoding="utf-8")
    (tmp_path / "controls.json").write_text(json.dumps({"decoys": ["RADAR aprueba cambios."] * 12,
                                                        "positives": [POSITIVE] * 12}), encoding="utf-8")
    argv = ["judge-packets", str(tmp_path / "outputs.json"), str(tmp_path / "prompts.json"), str(src),
            str(tmp_path / "controls.json"), str(tmp_path / "judge")]
    assert harness._main(argv) == 3
    assert json.loads(capsys.readouterr().out)["written"] is False
    (tmp_path / "controls.json").write_text(json.dumps({"decoys": [DECOY] * 12, "positives": [POSITIVE] * 12}),
                                            encoding="utf-8")
    assert harness._main(argv) == 0
    assert len(list((tmp_path / "judge" / "packets").glob("*.md"))) == 12


# --------------------------------------------------------------------------- the agent, the command, the hook


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_judge_agent_reads_one_packet_and_never_scores_novelty():
    text = (REPO / "agents" / "judge.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert re.search(r"^name: kg-judge$", head, re.M)
    assert re.search(r"^tools: Read, Write$", head, re.M)
    body = _flat(text)
    assert "**grounded**" in body and "**useful**" in body
    assert "Do **not** score novelty" in body
    example = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
    assert all(set(s) == {"grounded", "useful"} for s in example["scores"].values())


def test_the_command_runs_the_judge_only_when_asked():
    text = (REPO / "commands" / "kg-experiment.md").read_text(encoding="utf-8")
    assert 'argument-hint: "[--judge] [prompts_path]"' in text
    body = _flat(text)
    assert "If the line holds the word `--judge` standing alone, take it out" in body
    step = _flat(text[text.index("## Step 3b"):text.index("## Step 4")])
    assert "Skip this step unless the arguments held `--judge`" in step
    assert 'Task(subagent_type: "kg-judge"' in step
    assert "judge-packets" in step and "judge-aggregate" in step
    assert "about 1.5 million tokens" in step
    assert "Never put anything from `$J/private/` into a judge's prompt" in step
    assert "the judge's `verdict` is the headline" in body


def test_the_hook_stays_silent_for_the_judge():
    spec = importlib.util.spec_from_file_location("kg_precontext_judge", REPO / "hooks" / "precontext.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert hook._blind_caller({"agent_type": "burgess:kg-judge"})
    assert hook._blind_caller({"agent_type": "kg-judge"})
