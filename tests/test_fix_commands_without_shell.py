"""0.28.0: /kg-eval, /kg-experiment and /kg-perturb run their steps in the engine, and what a measurement agent
reads lies inside the project.

Found in the end-to-end run of 2026-11-25 (Windows, Claude Code 2.1.331, Burgess 0.25.1). The user's settings set
`permissions.blockReadsOutsideWorkingDirectories`. Under it, Claude Code asks the person before any Bash command
that names a path outside the working directories, or that its parser cannot analyse (`$(…)`, `${…}`, `case`,
quotes), and marks that question as one the auto mode's classifier may not answer. Every Bash block of the three
commands started the plugin's Python from the plugin's folder:
- /kg-eval was refused four times and measured nothing;
- /kg-perturb's classification of its argument was refused twice, and the session did it by hand;
- /kg-experiment's first block is the same, so it would have stopped at once.

The same setting blocks the file tools outside the project too. So an annotator could not read a source the build
keeps in the plugin's data folder (a project built from registered sources), nor the orchestrator the plugin's
contract before recommending a refinement.

Now three tools run the steps: `kg_eval` and `kg_experiment` (one step per call) and `kg_perturb_plan`. They use
the command lines' functions, with the same seeds, so their numbers are the command lines' numbers on the same
files. A /kg-eval run copies into its folder under `.kg/eval/` the documents its edges cite and the contract. The
log entries are written by the engine from the saved results. Only the optional LightRAG arm keeps a Bash step:
it is opt-in, sends the whole source to OpenAI with the user's key and costs money, so that approval is kept.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
import subprocess
from contextlib import redirect_stdout
from pathlib import Path, PureWindowsPath

import pytest

from kg_engine import harness, judge, measure
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
EVAL = (REPO / "commands" / "kg-eval.md").read_text(encoding="utf-8")
EXPERIMENT = (REPO / "commands" / "kg-experiment.md").read_text(encoding="utf-8")
PERTURB = (REPO / "commands" / "kg-perturb.md").read_text(encoding="utf-8")
PREFIX = "mcp__plugin_burgess_burgess__"

_spec = importlib.util.spec_from_file_location("f4_probe_0280", REPO / "scripts" / "f4_probe.py")
f4_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f4_probe)

FILE = "Fábricas de software.md"
DOC = ("# Fábricas\n\n## Argumento\nLa fábrica funciona cuando verifica cada cambio.\n\n"
       "El oráculo decide si una salida es correcta.\n\n"
       "## Medidas\nUna métrica de reversiones aproxima la calidad de los cambios.\n")
NODES = [{"id": "fabrica", "label": "fábrica", "node_type": "claim", "body": "La fábrica de software."},
         {"id": "verificacion", "label": "verificación", "node_type": "operation", "body": "Verificar cada cambio."},
         {"id": "oraculo", "label": "oráculo", "node_type": "primitive", "body": "Lo que decide."},
         {"id": "salida-correcta", "label": "salida correcta", "node_type": "claim", "body": "Una salida válida."},
         {"id": "reversiones", "label": "métrica de reversiones", "node_type": "metric", "body": "Cuántos cambios se revierten."},
         {"id": "calidad", "label": "calidad de los cambios", "node_type": "claim", "body": "Lo bien que salen."}]
EDGES = [{"source": "fabrica", "target": "verificacion", "relation": "grounds",
          "span": "La fábrica funciona cuando verifica cada cambio", "source_file": FILE},
         {"source": "oraculo", "target": "salida-correcta", "relation": "grounds",
          "span": "El oráculo decide si una salida es correcta", "source_file": FILE},
         {"source": "reversiones", "target": "calidad", "relation": "approximates",
          "span": "Una métrica de reversiones aproxima la calidad de los cambios", "source_file": FILE}]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _front(text: str) -> str:
    return re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)


def _bash_blocks(text: str) -> list:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


def _files(root: Path) -> dict:
    # POSIX keys on every platform: on Windows `relative_to` gives backslashes, which a `.kg/` prefix misses
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def rig(tmp_path):
    """A project whose notes lie OUTSIDE it, as the plugin's `source_path` can put them, with three claims."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notas"
    notes.mkdir()
    # CRLF on every platform, as a Windows editor saves notes: the Windows CI leg caught a comparison that
    # assumed the engine keeps a file's line endings (it reads text with universal newlines)
    (notes / FILE).write_text(DOC, encoding="utf-8", newline="\r\n")
    eng = KGEngine(project, source_path=notes, pack_path=PACK)
    for section in (1, 2):
        eng.kg_section(FILE, section)
    out = eng.kg_write({"nodes": NODES, "edges": EDGES})
    assert out["dispositions"]["ACCEPTED"] == len(NODES) + len(EDGES), out
    return eng, project, notes


def _label(sheet: Path, path: Path, verdicts: dict) -> dict:
    rows = list(csv.DictReader(open(sheet, encoding="utf-8")))
    labels = {r["edge_id"]: {"verdict": verdicts.get(r["relation"], "correct"), "span_found": "y",
                             "notes": "«" + r["source_label"] + "»"} for r in rows}
    path.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return labels


# --------------------------------------------------------------------------- the command texts

def test_kg_eval_and_kg_perturb_run_no_shell_and_declare_their_engine_tool():
    for text, tool in ((EVAL, "kg_eval"), (PERTURB, "kg_perturb_plan")):
        tools = [t.strip() for t in re.search(r"^allowed-tools:\s*(.+)$", _front(text), re.M).group(1).split(",")]
        assert "Bash" not in tools and PREFIX + tool in tools, tools
        assert not _bash_blocks(text)


def test_kg_experiment_keeps_one_shell_block_the_opt_in_lightrag_arm():
    tools = re.search(r"^allowed-tools:\s*(.+)$", _front(EXPERIMENT), re.M).group(1)
    assert PREFIX + "kg_experiment" in tools
    [block] = _bash_blocks(EXPERIMENT)
    assert "lightrag_arm answer" in block
    step1b = EXPERIMENT[EXPERIMENT.index("## Step 1b"):EXPERIMENT.index("## Step 2")]
    assert block in step1b and "Only when Step 0's `lightrag` said `\"available\": true`" in step1b
    assert "it asks the person first" in _flat(step1b)


@pytest.mark.parametrize("text", [EVAL, EXPERIMENT, PERTURB], ids=["kg-eval", "kg-experiment", "kg-perturb"])
def test_no_step_outside_the_lightrag_block_starts_the_plugins_python(text):
    rest = text
    for block in _bash_blocks(text):
        rest = rest.replace(block, "")
    for marker in ("engine_python.mjs", "kg_engine.paths", '"$PY"', "python -m", "f4_probe.py"):
        assert marker not in rest, marker


def test_every_engine_tool_the_three_commands_name_exists(engine):
    class FakeMCP:
        def __init__(self):
            self.tools = set()

        def tool(self):
            def deco(fn):
                self.tools.add(fn.__name__)
                return fn
            return deco

    mcp = FakeMCP()
    _register(mcp, engine)
    named = set(re.findall(PREFIX + r"(\w+)", EVAL + EXPERIMENT + PERTURB))
    assert {"kg_eval", "kg_experiment", "kg_perturb_plan"} <= named
    assert named <= mcp.tools, named - mcp.tools


# --------------------------------------------------------------------------- kg_eval

def test_sample_copies_what_the_agents_read_into_the_project(rig):
    eng, project, notes = rig
    out = eng.kg_eval("sample")
    assert out["ok"], out
    folder = Path(out["folder"])
    assert folder.parent == project / ".kg" / "eval" and folder.name == out["run"]
    # the documents exactly as the engine reads them, the text a span is checked against, inside the project
    src = Path(out["source"]["folder"])
    assert src.is_relative_to(project) and out["source"]["documents"] == [FILE]
    assert (src / FILE).read_bytes() == eng.verify_set().texts[FILE].encode("utf-8")
    assert eng.verify_set().texts[FILE] == DOC          # the notes' CRLF read as LF (universal newlines)
    assert (notes / FILE).read_bytes() == DOC.replace("\n", "\r\n").encode("utf-8")
    # the contract the orchestrator checks advice against, as the running plugin has it
    contract = Path(out["contract"]["folder"])
    assert out["contract"]["files"] == ["extractor.md", "adversarial-grounder.md", "pack.yaml"]
    for rel in measure.CONTRACT_FILES:
        assert (contract / Path(rel).name).read_bytes() == (REPO / rel).read_bytes()
    assert out["copy"] == "development" and out["legacy_log"] is None
    assert out["summary"]["edges"] == len(EDGES) and out["sample"]["rows"] == len(EDGES)


def test_the_sheets_are_the_command_lines_sheet(rig, tmp_path):
    eng, _project, _notes = rig
    out = eng.kg_eval("sample")
    cli = tmp_path / "cli.csv"
    with redirect_stdout(io.StringIO()):
        f4_probe.sheet(out["graph"], 80, str(cli), include_extracted=False)
    for name in measure.SHEETS:
        assert Path(out["sheets"][name]).read_bytes() == cli.read_bytes(), name


def test_score_fills_then_scores_as_the_command_line_does(rig, tmp_path):
    eng, _project, _notes = rig
    out = eng.kg_eval("sample")
    sheet, labels = Path(out["sheets"]["labels"]), Path(out["labels"]["labels"])
    _label(sheet, labels, {"approximates": "vague"})
    cli = tmp_path / "cli.csv"
    cli.write_bytes(sheet.read_bytes())
    buf = io.StringIO()
    with redirect_stdout(buf):
        f4_probe.main(["fill", str(cli), str(labels)])
        f4_probe.main(["score", str(cli)])
    res = eng.kg_eval("score", run=out["run"])
    assert res["ok"], res
    assert sheet.read_bytes() == cli.read_bytes()          # the engine filled the sheet the command line fills
    score = res["score"]
    assert (score["labeled"], score["correct"]) == (3, 2)
    assert f"PRECISION (correct / labeled):        {score['precision']:.2f}" in buf.getvalue()
    assert f"astrology rate (fabricated+vague):    {score['astrology_rate']:.2f}" in buf.getvalue()
    edges = {e.id: e for e in eng.canon.all_edges()}
    assert res["writers"] == harness.sample_writers(list(csv.DictReader(open(cli, encoding="utf-8"))), edges)
    assert [o["verdict"] for o in res["writers"]["not_correct"]] == ["vague"]
    assert res["below_target"] is True


def test_a_labels_file_that_does_not_fit_changes_nothing(rig):
    eng, _project, _notes = rig
    out = eng.kg_eval("sample")
    sheet = Path(out["sheets"]["labels"])
    before = sheet.read_bytes()
    no_file = eng.kg_eval("score", run=out["run"])
    assert no_file["ok"] is False and "no labels file yet" in no_file["problems"]
    labels = _label(sheet, Path(out["labels"]["labels"]), {})
    labels.pop(next(iter(labels)))
    Path(out["labels"]["labels"]).write_text(json.dumps(labels), encoding="utf-8")
    res = eng.kg_eval("score", run=out["run"])
    assert res["ok"] is False and "no entry in the labels file" in res["problems"]
    assert sheet.read_bytes() == before


def test_agreement_is_the_command_lines_alpha(rig):
    eng, _project, _notes = rig
    out = eng.kg_eval("sample")
    a = _label(Path(out["sheets"]["labels_a"]), Path(out["labels"]["labels_a"]), {})
    b = _label(Path(out["sheets"]["labels_b"]), Path(out["labels"]["labels_b"]), {"approximates": "wrong_type"})
    res = eng.kg_eval("agreement", run=out["run"])
    assert res["ok"], res
    sets = [{k: v["verdict"] for k, v in a.items()}, {k: v["verdict"] for k, v in b.items()}]
    assert res["krippendorff_alpha"] == round(harness.agreement(sets), 3) and res["units"] == 3
    assert json.loads((Path(out["folder"]) / "label_sets.json").read_text(encoding="utf-8")) == sets


def test_agreement_names_the_sheet_whose_labels_are_missing(rig):
    eng, _project, _notes = rig
    out = eng.kg_eval("sample")
    _label(Path(out["sheets"]["labels_a"]), Path(out["labels"]["labels_a"]), {})
    res = eng.kg_eval("agreement", run=out["run"])
    assert res["ok"] is False and list(res["problems"]) == ["labels_b"]


def test_specificity_is_the_command_lines_gate(rig):
    eng, _project, _notes = rig
    out = eng.kg_eval("sample")
    res = eng.kg_eval("specificity", run=out["run"])
    assert res["ok"], res
    buf = io.StringIO()
    with redirect_stdout(buf):
        harness._cmd_specificity(["specificity", out["graph"], eng._measure_source()])
    assert res["specificity"] == json.loads(buf.getvalue())


def test_a_second_pass_drops_the_stale_labels_and_the_log_keeps_the_best(rig):
    eng, project, _notes = rig
    out = eng.kg_eval("sample")
    run, folder = out["run"], Path(out["folder"])
    _label(Path(out["sheets"]["labels"]), Path(out["labels"]["labels"]), {})
    assert eng.kg_eval("score", run=run)["score"]["precision"] == 1.0
    again = eng.kg_eval("sample", run=run)                       # a development checkout's next pass
    assert again["ok"] and again["run"] == run and again["pass"] == 2
    assert not (folder / "labels.json").exists()                  # a pass never scores an earlier pass's file
    _label(Path(again["sheets"]["labels"]), Path(again["labels"]["labels"]), {"grounds": "fabricated"})
    assert eng.kg_eval("score", run=run)["score"]["precision"] == pytest.approx(1 / 3)
    entry = eng.kg_eval("log", run=run, iterations="tightened `grounds` in the pack")["entry"]
    assert "- PRECISION (best of 2 pass(es)):  1.00" in entry
    assert "(labeled n=3)" in entry and "- iterations:                        2 (tightened `grounds` in the pack)" in entry
    assert (project / ".kg" / "PROGRESS.md").read_text(encoding="utf-8") == entry


def test_the_log_is_written_from_the_saved_results_and_appended(rig):
    eng, project, notes = rig
    out = eng.kg_eval("sample")
    run = out["run"]
    for name in measure.SHEETS:
        _label(Path(out["sheets"][name]), Path(out["labels"][name]), {})
    eng.kg_eval("score", run=run)
    eng.kg_eval("agreement", run=run)
    eng.kg_eval("specificity", run=run)
    first = eng.kg_eval("log", run=run, iterations="none")
    entry = first["entry"]
    assert re.match(r"\n## /kg-eval — \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n", entry)
    assert f"\nsource: {notes}\nrun: {out['folder']}\n" in entry
    assert "- by writer:                         extractor=1.00 (3/3)" in entry
    assert "- krippendorff_alpha:                1.000   (reliable >= 0.67 — RELIABLE)" in entry
    assert "- specificity gate:                  gate_on=false" in entry
    eng.kg_eval("log", run=run, iterations="none")
    log = (project / ".kg" / "PROGRESS.md").read_text(encoding="utf-8")
    assert log.count("\n## /kg-eval — ") == 2 and log.startswith(entry)


def test_a_step_refuses_what_it_cannot_run(rig):
    eng, project, _notes = rig
    assert eng.kg_eval("nope")["ok"] is False
    for run in ("../../etc", "20261126T101500Z/../x", ""):
        res = eng.kg_eval("score", run=run)
        assert res["ok"] is False and "is not a run id" in res["error"], res
    res = eng.kg_eval("log", run="20261126T101500Z")
    assert res["ok"] is False and "start with step `sample`" in res["error"]
    assert not (project / ".kg").exists()


def test_a_measurement_writes_only_under_dot_kg_and_never_the_canon(rig):
    eng, project, _notes = rig
    eng._ensure_projected(views=False)
    canon_before = _files(project / "canon")
    outside_before = {k: v for k, v in _files(project).items() if not k.startswith(".kg/")}
    out = eng.kg_eval("sample")
    for name in measure.SHEETS:
        _label(Path(out["sheets"][name]), Path(out["labels"][name]), {})
    for step in ("score", "agreement", "specificity", "validate_pack", "log"):
        assert eng.kg_eval(step, run=out["run"])["ok"], step
    assert _files(project / "canon") == canon_before
    assert {k: v for k, v in _files(project).items() if not k.startswith(".kg/")} == outside_before


def test_a_graph_given_by_path_is_measured_instead(rig, tmp_path):
    eng, _project, _notes = rig
    eng._ensure_projected(views=False)
    given = tmp_path / "snapshot.json"
    given.write_bytes(eng.projector.graph_path.read_bytes())
    out = eng.kg_eval("sample", graph=f'"{given}"')
    assert out["ok"] and out["graph"] == str(given)
    missing = eng.kg_eval("sample", graph=str(tmp_path / "none.json"))
    assert missing["ok"] is False and "no graph at" in missing["error"]


def test_the_copy_is_installed_only_inside_claude_codes_plugin_cache():
    assert measure.plugin_copy(Path("/home/u/.claude/plugins/cache/sergiparpal/burgess/0.28.0")) == "installed"
    assert measure.plugin_copy(PureWindowsPath(r"C:\Users\u\.claude\plugins\cache\x\burgess\0.28.0")) == "installed"
    assert measure.plugin_copy(Path("/home/u/code/burgess")) == "development"


# --------------------------------------------------------------------------- kg_experiment

JDOCS = {
    "revision.md": (
        "El sistema RADAR de Meta aprueba solo cambios de bajo riesgo y los integra sin revisión humana.\n\n"
        "Con RADAR, las reversiones bajaron a 1/3 y los incidentes a 1/50 de los cambios revisados.\n\n"
        "La revisión humana sigue siendo necesaria para los cambios complejos que tocan varios equipos.\n\n"
        "Los autores parten sus cambios para quedar en bajo riesgo, lo que puede ser buena práctica o evasión."),
    "agentes.md": (
        "Uber atribuye a agentes más del 70 % de sus cambios, incluido el uso interactivo.\n\n"
        "La diferencia con otras cifras se explicaría en parte por el cambio de definición.\n\n"
        "Faros mide un aumento del 154 % en el tamaño de los cambios y del 91 % en el tiempo de revisión.\n\n"
        "Los equipos pequeños revisan más rápido cuando los cambios son pequeños y frecuentes."),
    "medidas.md": (
        "Para medir la seguridad hace falta comparar cambios del mismo riesgo con y sin revisión.\n\n"
        "Nadie publica una tasa de escapes comparable entre la vía revisada y la no revisada.\n\n"
        "Una métrica que se convierte en objetivo deja de medir bien lo que medía."),
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


@pytest.fixture
def lab(tmp_path):
    """A project whose source is a folder of three documents outside it."""
    project = tmp_path / "project"
    project.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, text in JDOCS.items():
        (docs / name).write_text(text, encoding="utf-8")
    return KGEngine(project, source_path=docs, pack_path=PACK), project, docs


def _write_outputs(start: dict) -> Path:
    out = Path(start["outputs_path"])
    out.with_name("ideation_outputs.control.json").write_text(
        json.dumps({"outputs": {"control": IDEAS["control"]}}), encoding="utf-8")
    out.with_name("ideation_outputs.graph.json").write_text(
        json.dumps({"outputs": {"control": IDEAS["control"], "graph": IDEAS["graph"]}}), encoding="utf-8")
    out.write_text(json.dumps({"outputs": IDEAS}, ensure_ascii=False), encoding="utf-8")
    return out


def test_start_saves_the_users_prompt_file_inside_the_project(lab, tmp_path):
    eng, project, _docs = lab
    given = tmp_path / "mis prompts.txt"                       # outside the project, one prompt per line
    given.write_text("¿Qué decide RADAR?\n¿Qué mide Faros?\n", encoding="utf-8")
    out = eng.kg_experiment("start", prompts=f'"{given}"')
    assert out["ok"], out
    assert out["prompts"] == ["¿Qué decide RADAR?", "¿Qué mide Faros?"]
    saved = Path(out["prompts_path"])
    assert saved.parent == project / ".kg" / "experiment" and saved.name == f"prompts-{out['run']}.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == out["prompts"]
    assert out["demo_source"] is False and out["judge"]["judge_possible"] is True
    assert eng.kg_experiment("start", prompts=str(tmp_path / "none.txt"))["ok"] is False


def test_start_spots_the_demo_and_says_why_the_judge_cannot_run_on_it(tmp_path):
    demo = tmp_path / "copia del demo.md"
    demo.write_bytes((REPO / "examples" / "source.md").read_bytes())
    out = KGEngine(tmp_path / "p", source_path=demo, pack_path=PACK).kg_experiment("start")
    assert out["ok"] and out["demo_source"] is True and out["prompts"] is None
    assert out["judge"]["judge_possible"] is False and out["judge"]["problems"]


def test_rag_is_the_command_lines_rag(lab, tmp_path):
    eng, _project, docs = lab
    start = eng.kg_experiment("start")
    Path(start["prompts_path"]).write_text(json.dumps(PROMPTS[:3], ensure_ascii=False), encoding="utf-8")
    res = eng.kg_experiment("rag", run=start["run"])
    assert res["ok"] and res["rag_dir"] == start["rag_dir"] and res["files"] == ["01.md", "02.md", "03.md"]
    cli = tmp_path / "cli-rag"
    harness.write_rag_contexts(PROMPTS[:3], str(docs), str(cli))
    assert _files(Path(res["rag_dir"])) == _files(cli)


def test_score_is_the_command_lines_score_and_keeps_the_runs_outputs(lab):
    eng, project, docs = lab
    start = eng.kg_experiment("start")
    Path(start["prompts_path"]).write_text(json.dumps(PROMPTS, ensure_ascii=False), encoding="utf-8")
    out = _write_outputs(start)
    res = eng.kg_experiment("score", run=start["run"])
    assert res["ok"], res
    buf = io.StringIO()
    with redirect_stdout(buf):
        harness._cmd_ideation(["ideation", str(out), str(docs)])
    assert res["ideation"] == json.loads(buf.getvalue())
    assert res["evaluator_order"] == harness.evaluator_order(str(out)) and res["evaluator_order"]["verified"]
    run = start["run"]
    for suffix in ("", ".control", ".graph"):
        kept = out.with_name(f"ideation_outputs{suffix}-{run}.json")
        assert kept.read_bytes() == out.with_name(f"ideation_outputs{suffix}.json").read_bytes()
    saved = json.loads((project / ".kg" / "experiment" / f"score-{run}.json").read_text(encoding="utf-8"))
    assert saved == {"ideation": res["ideation"], "evaluator_order": res["evaluator_order"]}


def test_the_judge_steps_build_the_packets_and_score_the_verdicts(lab):
    eng, project, _docs = lab
    start = eng.kg_experiment("start")
    run, jdir = start["run"], Path(start["judge_dir"])
    Path(start["prompts_path"]).write_text(json.dumps(PROMPTS, ensure_ascii=False), encoding="utf-8")
    _write_outputs(start)
    assert eng.kg_experiment("judge_packets", run=run)["ok"] is False          # no controls yet
    (jdir / "private").mkdir(parents=True)
    controls = jdir / "private" / "controls.json"
    controls.write_text(json.dumps({"decoys": ["RADAR aprueba cambios."] * 12, "positives": [POSITIVE] * 12}),
                        encoding="utf-8")
    failed = eng.kg_experiment("judge_packets", run=run)
    assert failed["ok"] is False and len(failed["failures"]) == 12 and not (jdir / "packets").exists()
    controls.write_text(json.dumps({"decoys": [DECOY] * 12, "positives": [POSITIVE] * 12}), encoding="utf-8")
    built = eng.kg_experiment("judge_packets", run=run)
    assert built["ok"], built
    assert [Path(j["packet"]).name for j in built["judges"]] == [f"{k:02d}.md" for k in range(1, 13)]
    assert all(Path(j["verdict"]).parent == jdir / "verdicts" for j in built["judges"])
    # every judge ranks graph first and scores the decoy lowest
    mapping = json.loads((jdir / "private" / "mapping.json").read_text(encoding="utf-8"))
    (jdir / "verdicts").mkdir()
    for key, labels in mapping["packets"].items():
        by_item = {item: label for label, item in labels.items()}
        grounded = {"control": 4, "graph": 4, "rag": 5, "decoy": 1, "positive": 5}
        verdict = {"scores": {by_item[i]: {"grounded": g, "useful": 3} for i, g in grounded.items()},
                   "ranking": [by_item[i] for i in ("graph", "rag", "positive", "control", "decoy")]}
        (jdir / "verdicts" / f"{key}.json").write_text(json.dumps(verdict), encoding="utf-8")
    scored = eng.kg_experiment("judge_score", run=run)
    assert scored["ok"] and scored["valid"] and scored["verdict"].startswith("graph beat rag")
    blob = json.loads(Path(start["outputs_path"]).read_text(encoding="utf-8"))
    expected = judge.aggregate(str(jdir), blob["outputs"])
    assert {k: v for k, v in scored.items() if k in expected} == expected
    eng.kg_experiment("score", run=run)
    entry = eng.kg_experiment("log", run=run, prompt_source="drafted from the graph")["entry"]
    assert "**Judge (blind; grounded and useful, not novelty):** 12 prompts judged; V1 12 of 12" in entry
    assert "\n**Judge verdict (graph vs rag):** graph beat rag" in entry and "| decoy | 1 | 3 |" in entry


def test_the_experiment_log_is_written_from_the_saved_scores(lab):
    eng, project, _docs = lab
    start = eng.kg_experiment("start")
    run = start["run"]
    Path(start["prompts_path"]).write_text(json.dumps(PROMPTS, ensure_ascii=False), encoding="utf-8")
    _write_outputs(start)
    assert eng.kg_experiment("log", run=run)["ok"] is False                  # score first
    eng.kg_experiment("score", run=run)
    entry = eng.kg_experiment("log", run=run, prompt_source="the user's file",
                              judge_note="not measured: the controls failed their checks")["entry"]
    log = (project / ".kg" / "PROGRESS.md").read_text(encoding="utf-8")
    assert log == "# Experiment log\n\n" + entry
    assert re.match(r"\n## kg-experiment \(Stage 8, method 0\.12\.0\) — \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n", entry)
    assert f"Prompts: 12 (the user's file): {start['prompts_path']}" in entry
    assert entry.index("| control |") < entry.index("| graph |") < entry.index("| rag |")
    assert "\n**Verdict (graph vs rag):** " in entry and "\n**Evaluator order:** verified\n" in entry
    assert "\n**Judge:** not measured: the controls failed their checks\n" in entry


# --------------------------------------------------------------------------- kg_perturb_plan

@pytest.mark.parametrize("name,construction", [
    ("Mi segundo documento.md", "mi-segundo-documento"),
    ("ÉTICA (v2).md", "tica-v2"),          # the old block lowercased ASCII only and hyphenated every other run
    ("---.md", "second"),
])
def test_the_construction_is_named_as_the_shell_block_named_it(vault, name, construction):
    (vault / name).write_text("# T\n\n## Uno\nTexto.\n\n## Dos\nMás texto.\n", encoding="utf-8")
    plan = KGEngine(vault).kg_perturb_plan(name)
    assert plan["ok"] and plan["mode"] == "source" and plan["construction"] == construction, plan
    assert plan["sections"] == 2 and plan["source_file"] == name


def test_the_plan_says_whether_the_second_source_is_one_of_the_graphs_own(engine, source_path, tmp_path):
    assert engine.kg_perturb_plan(str(source_path))["own_source"] is True
    other = tmp_path / "otro.md"
    other.write_text("# Otro\n\nTexto.\n", encoding="utf-8")
    assert engine.kg_perturb_plan(str(other))["own_source"] is False
    graph = tmp_path / "SEGUNDO.JSON"
    graph.write_text('{"nodes": [], "links": []}', encoding="utf-8")
    assert engine.kg_perturb_plan(str(graph)) == {"ok": True, "mode": "graph", "second_graph": str(graph)}
