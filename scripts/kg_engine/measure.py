"""The measurement steps of /burgess:kg-eval and /burgess:kg-experiment, run in the engine (0.28.0).

Through 0.27.0 both commands ran these steps as Bash blocks that started the plugin's Python from the plugin's
folder. Under `permissions.blockReadsOutsideWorkingDirectories` (the user's Windows settings since 2026-11-12),
Claude Code asks the person before any Bash command that names a path outside the project, or that its parser
cannot analyse (`$(…)`, `${…}`, `case`, quotes), and the auto mode's classifier cannot answer that question for
them. In the end-to-end run of 2026-11-25, /kg-eval was refused four times and measured nothing. The same
setting blocks the file tools outside the project too, so an annotator could not read a source kept in the
plugin's data folder (a project built from registered sources), nor the orchestrator the plugin's contract.

So the engine runs the steps (`kg_eval`, `kg_experiment`), and every file a measurement agent reads lies under
the project's `.kg/`: a run of /kg-eval copies the documents its edges cite and the contract it checks advice
against into its own folder. The log entries are written here, from the saved results, in the format the
commands' shell blocks wrote; the model supplies only what it alone knows.

What these functions write stays under `<project>/.kg/`, which Burgess never reads as a source document: the
canon, the verdicts and the derived layer are never touched. A run id is checked against `RUN_RE` before it
names a folder, so no argument can lead a write out of `.kg/`. Nothing here prints: an MCP stdio server speaks
its protocol on stdout. They use the same functions, with the same seeds, as the command lines
(`f4_probe.py`, `python -m kg_engine.harness`), so a number is the number the command line gives on the same
files.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePath

from . import evalsheet, harness, judge
from .atomicio import atomic_write_text
from .sources import SourceSet, section_corpus

KG_DIRNAME = ".kg"
EVAL_DIRNAME = "eval"
EXPERIMENT_DIRNAME = "experiment"
LOG_NAME = harness.LOG_NAME

# The plugin this engine belongs to: scripts/kg_engine/measure.py -> the plugin's root.
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
# The contract a /kg-eval refinement is checked against before it is recommended (4.4 of the command).
CONTRACT_FILES = ("agents/extractor.md", "agents/adversarial-grounder.md", "pack/pack.yaml")
DEMO_SOURCE = PLUGIN_ROOT / "examples" / "source.md"

RUN_RE = re.compile(r"\d{8}T\d{6}Z(?:-\d{1,3})?")
RUN_ATTEMPTS = 100

# The three sheets of a /kg-eval run: Stage 4's, and Stage 7's two independent passes. One seeded sample.
SHEETS = ("labels", "labels_a", "labels_b")
AGREEMENT_SHEETS = ("labels_a", "labels_b")

# The order a /kg-experiment log lists its arms in; an arm the run did not have is left out.
ARM_ORDER = ("control", "graph", "graph+generate", "graph+generate+dpp", "rag", "lightrag")
TABLE_COLUMNS = ("n", "novelty", "support", "grounded_novelty", "diversity", "utility", "unsupported_rate")
VERDICT_LINES = (("verdict", "Verdict (graph vs rag)"),
                 ("control_verdict", "Control verdict"),
                 ("generate_verdict", "Generate verdict (graph+generate vs graph)"),
                 ("dpp_verdict", "DPP verdict"),
                 ("lightrag_verdict", "LightRAG verdict"))
JUDGE_VERDICT_LINES = (("verdict", "Judge verdict (graph vs rag)"),
                       ("control_verdict", "Judge control verdict"),
                       ("generate_verdict", "Judge generate verdict"),
                       ("dpp_verdict", "Judge DPP verdict"),
                       ("lightrag_verdict", "Judge LightRAG verdict"))


class MeasureError(ValueError):
    """A step that cannot run as asked, with the message to show."""


# --------------------------------------------------------------------------- shared

def utc_stamp(now: "datetime | None" = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def utc_iso(now: "datetime | None" = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_run(run) -> str:
    run = str(run or "").strip()
    if not RUN_RE.fullmatch(run):
        raise MeasureError(f"run {run!r} is not a run id: pass the `run` the first step returned "
                           "(like 20261126T101500Z)")
    return run


def plugin_copy(root: "PurePath | str" = PLUGIN_ROOT) -> str:
    """`installed` when the plugin runs from Claude Code's plugin cache (a `plugins/cache` folder), else
    `development` (a checkout run with --plugin-dir). /kg-eval edits the pack only in a development checkout."""
    parts = [p.lower() for p in (root if isinstance(root, PurePath) else Path(root)).parts]
    installed = any(a == "plugins" and b == "cache" for a, b in zip(parts, parts[1:]))
    return "installed" if installed else "development"


def _kg(project) -> Path:
    return Path(project) / KG_DIRNAME


def _write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise MeasureError(f"could not read {path}: {e}") from None


def _append_log(project, text: str, *, header: str = "") -> Path:
    """Append `text` to `<project>/.kg/PROGRESS.md` (LF, never overwriting); `header` opens a new file."""
    log = _kg(project) / LOG_NAME
    log.parent.mkdir(parents=True, exist_ok=True)
    new = not log.exists()
    with open(log, "a", encoding="utf-8", newline="\n") as f:
        if new and header:
            f.write(header)
        f.write(text)
    return log


def _plain_name(name: str) -> str:
    """A document's name as a file name inside a run's folder: one plain path component."""
    if not name or name in (".", "..") or Path(name).name != name or "/" in name or "\\" in name:
        raise MeasureError(f"a source document has a name that is not a plain file name: {name!r}")
    return name


def copy_documents(documents: "dict[str, str]", folder: Path) -> list:
    """Write each document's text, exactly as the engine read it (no newline translation), into `folder`,
    replacing what an earlier pass of the run left there."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for name, text in documents.items():
        with open(folder / _plain_name(name), "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return sorted(documents)


def legacy_note(project, notes_path) -> "str | None":
    """The `harness legacy-log` note: a log an earlier version left at the top of the project, read as a
    source document (0.11.7). Burgess never moves or deletes it."""
    old = harness.legacy_log(project, str(notes_path) if notes_path else None)
    if old is None:
        return None
    new = _kg(project) / LOG_NAME
    return (f"{old} is one of the source documents. Through Burgess 0.11.6, /burgess:kg-eval and "
            f"/burgess:kg-experiment kept their log there; they now write {new}. While it stays in the "
            f"source folder, /burgess:kg-build extracts it like any other document and /burgess:kg-experiment "
            f"reads it as source. Ask the user to move it out of that folder, for instance into {new.parent}. "
            f"Burgess never moves or deletes it.")


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    return json.dumps(value)


# --------------------------------------------------------------------------- /kg-eval

def _eval_base(project) -> Path:
    return _kg(project) / EVAL_DIRNAME


def _eval_run_dir(project, run) -> Path:
    folder = _eval_base(project) / check_run(run)
    if not (folder / "run.json").is_file():
        raise MeasureError(f"no /burgess:kg-eval run {run} in {_eval_base(project)}: start with step `sample`")
    return folder


def _new_eval_run(project, now=None) -> "tuple[str, Path]":
    base = _eval_base(project)
    base.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp(now)
    for k in range(1, RUN_ATTEMPTS + 1):
        run = stamp if k == 1 else f"{stamp}-{k}"
        try:
            (base / run).mkdir()
        except FileExistsError:
            continue
        return run, base / run
    raise MeasureError(f"could not open a new run folder in {base}")


def eval_sample(project, *, graph_path, graph_given: bool, documents: "dict[str, str]", source_path: str,
                notes_path=None, run: str = "", now=None) -> dict:
    """Step `sample`: open a run (or, with `run`, sample it again after a rebuild in a development checkout),
    copy into its folder the documents its edges can cite and the contract, and write its three sheets from
    one seeded sample. Stale labels of the run are removed, so a pass can never score an earlier pass's file."""
    graph_path = Path(graph_path)
    if not graph_path.is_file():
        raise MeasureError(f"no graph at {graph_path}: run /burgess:kg-build first")
    folder = _eval_run_dir(project, run) if run else None   # a resample names a run that exists
    # The sample is drawn before a new run's folder is made, so a graph with nothing to label leaves none.
    try:
        summary = evalsheet.summarize(graph_path)
        rows, left_out = evalsheet.draw(graph_path, evalsheet.SAMPLE_SIZE)
    except (evalsheet.SheetError, ValueError) as e:
        raise MeasureError(f"could not sample {graph_path}: {e}") from None
    if folder is not None:
        record = _read_json(folder / "run.json") or {}
        run = folder.name
    else:
        run, folder = _new_eval_run(project, now)
        record = {"run": run, "created_at": utc_iso(now), "passes": [], "pass": 0}
    names = copy_documents(documents, folder / "source")
    contract = folder / "contract"
    contract.mkdir(exist_ok=True)
    copied = []
    for rel in CONTRACT_FILES:
        src = PLUGIN_ROOT / rel
        if src.is_file():
            shutil.copyfile(src, contract / src.name)
            copied.append(src.name)
    for name in SHEETS:
        for stale in (folder / f"{name}.json", folder / f"{name}.score.json"):
            stale.unlink(missing_ok=True)
        evalsheet.write_sheet(rows, folder / f"{name}.csv")
    (folder / "label_sets.json").unlink(missing_ok=True)
    (folder / "agreement.json").unlink(missing_ok=True)
    record.update({"pass": int(record.get("pass", 0)) + 1, "graph": str(graph_path), "graph_given": graph_given,
                   "source": source_path, "documents": names, "sampled": len(rows),
                   "left_out_proposals": left_out, "sampled_at": utc_iso(now)})
    _write_json(folder / "run.json", record)
    return {
        "ok": True, "step": "sample", "run": run, "pass": record["pass"], "folder": str(folder),
        "graph": str(graph_path), "summary": summary,
        "sample": {"rows": len(rows), "left_out_proposals": left_out, "seed": evalsheet.SAMPLE_SEED},
        "sheets": {name: str(folder / f"{name}.csv") for name in SHEETS},
        "labels": {name: str(folder / f"{name}.json") for name in SHEETS},
        "source": {"folder": str(folder / "source"), "documents": names},
        "contract": {"folder": str(contract), "files": copied},
        "copy": plugin_copy(),
        "legacy_log": legacy_note(project, notes_path),
    }


def _fill(folder: Path, name: str) -> "str | None":
    """Fill one sheet of the run from its labels file; the problem as text, or None when it filled."""
    labels = folder / f"{name}.json"
    if not labels.is_file():
        return f"no labels file yet: {labels} (the annotator writes it)"
    try:
        evalsheet.fill(folder / f"{name}.csv", labels)
    except evalsheet.SheetError as e:
        return str(e)
    return None


def _sheet_rows(path: Path) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def eval_score(project, *, run: str, edges: dict) -> dict:
    """Step `score` (Stage 4): fill `labels.csv` from the annotator's `labels.json`, score it, and split the
    labeled edges by writer and by the verdict each holds now. A labels file that does not label the sheet
    row for row changes nothing, and `problems` says why, for the same annotator to write it again."""
    folder = _eval_run_dir(project, run)
    problem = _fill(folder, "labels")
    if problem:
        return {"ok": False, "step": "score", "run": folder.name, "problems": problem,
                "labels": str(folder / "labels.json")}
    rows = _sheet_rows(folder / "labels.csv")
    try:
        score = evalsheet.score_rows([r for r in rows if evalsheet.verdict_of(r)])
    except evalsheet.SheetError as e:
        return {"ok": False, "step": "score", "run": folder.name, "problems": str(e)}
    writers = harness.sample_writers(rows, edges)
    record = _read_json(folder / "run.json") or {}
    k = int(record.get("pass", 1))
    entry = {"pass": k, "scored_at": utc_iso(), **score, "writers": writers}
    record["passes"] = [p for p in record.get("passes", []) if p.get("pass") != k] + [entry]
    _write_json(folder / "run.json", record)
    _write_json(folder / "labels.score.json", entry)
    return {"ok": True, "step": "score", "run": folder.name, "pass": k, "score": score, "writers": writers,
            "target": evalsheet.PRECISION_GATE, "below_target": score["precision"] < evalsheet.PRECISION_GATE}


def eval_agreement(project, *, run: str) -> dict:
    """Step `agreement` (Stage 7): fill the two independent passes' sheets, then Krippendorff's α over them."""
    folder = _eval_run_dir(project, run)
    problems = {name: p for name in AGREEMENT_SHEETS if (p := _fill(folder, name))}
    if problems:
        return {"ok": False, "step": "agreement", "run": folder.name, "problems": problems}
    label_sets = [{r["edge_id"]: evalsheet.verdict_of(r) for r in _sheet_rows(folder / f"{name}.csv")
                   if evalsheet.verdict_of(r)} for name in AGREEMENT_SHEETS]
    _write_json(folder / "label_sets.json", label_sets)
    alpha = harness.agreement(label_sets)
    reliable = alpha >= harness._ALPHA_RELIABLE
    units = len(set(label_sets[0]) & set(label_sets[1]))
    result = {"krippendorff_alpha": round(alpha, 3), "reliable": reliable, "threshold": harness._ALPHA_RELIABLE,
              "units": units,
              "verdict": (f"RELIABLE (>={harness._ALPHA_RELIABLE})" if reliable
                          else "BELOW THRESHOLD — grounding signal stays advisory")}
    _write_json(folder / "agreement.json", result)
    return {"ok": True, "step": "agreement", "run": folder.name, **result}


def eval_specificity(project, *, run: str) -> dict:
    """Step `specificity` (Stage 7): the specificity bridge-metric gate over the run's graph and its source,
    whose IDF corpus is the projector's own (the source split into sections)."""
    folder = _eval_run_dir(project, run)
    record = _read_json(folder / "run.json") or {}
    source = record.get("source") or ""
    if not source or not SourceSet.resolve(source):
        raise MeasureError("the graph has no source to measure specificity against")
    gdata = _read_json(Path(record.get("graph") or ""))
    if not isinstance(gdata, dict):
        raise MeasureError(f"the run's graph {record.get('graph')} is gone or not a node-link graph")
    text = harness._source_text(source)
    result = harness.specificity(gdata, section_corpus(text) or [text])
    _write_json(folder / "specificity.json", result)
    return {"ok": True, "step": "specificity", "run": folder.name, "specificity": result}


def eval_validate_pack(project, *, run: str, pack_path) -> dict:
    """Step `validate_pack` (a development checkout, 4.5): the pack loads, and how much of the source its
    vocabulary covers. It reads the pack the plugin runs with; it changes nothing."""
    from .pack import coverage, load_pack   # lazy: only this step needs pydantic's pack model
    folder = _eval_run_dir(project, run)
    record = _read_json(folder / "run.json") or {}
    path = Path(pack_path) if pack_path else PLUGIN_ROOT / "pack" / "pack.yaml"
    try:
        pack = load_pack(path)
    except Exception as e:  # noqa: BLE001 — any load failure is the answer: the pack is invalid
        return {"ok": False, "step": "validate_pack", "run": folder.name, "pack": str(path),
                "error": f"PACK INVALID: {e}"}
    source = record.get("source") or ""
    cov = coverage(pack, SourceSet(source).concat) if source and SourceSet.resolve(source) else None
    return {"ok": True, "step": "validate_pack", "run": folder.name, "pack": str(path), "domain": pack.domain,
            "node_types": len(pack.node_types), "edge_types": len(pack.edge_types),
            "glossary": len(pack.glossary), "coverage": cov}


def _best_pass(passes: list) -> "dict | None":
    """The pass with the best precision, the earliest of a tie (§4: record the best, not the last)."""
    best = None
    for p in passes:
        if best is None or p.get("precision", -1) > best.get("precision", -1):
            best = p
    return best


def _relation_line(per_relation) -> str:
    if per_relation is None:
        return "n/a (the sheet has no relation column)"
    if not per_relation:
        return f"n/a (no relation with {evalsheet.MIN_RELATION_N} or more labeled edges)"
    return ", ".join(f"{r['relation']}={r['precision']:.2f} ({r['correct']}/{r['labeled']})" for r in per_relation)


def _writer_lines(writers) -> "tuple[str, str]":
    if not writers:
        return "n/a", "n/a"
    by_writer = ", ".join(f"{k}={v['correct'] / v['labeled']:.2f} ({v['correct']}/{v['labeled']})"
                          for k, v in writers.get("by_writer", {}).items()) or "n/a"
    by_state = ", ".join(f"{k} {v['correct']}/{v['labeled']} correct"
                         for k, v in writers.get("by_state", {}).items()) or "n/a"
    return by_writer, by_state


def _calibration_line(cal) -> str:
    if not cal:
        return "n/a"
    meaning = ("scores track correctness" if cal["tracks"]
               else "scores don't separate correct from wrong: confidence is vocabulary, not grounding")
    return f"gap {cal['gap']:+.2f} ({meaning})"


def _iterations_text(iterations: str) -> str:
    """The orchestrator's `iterations` text as the entry's one line holds it (0.28.1). Whitespace collapses to
    single spaces, so a text of several lines cannot break the entry's shape, and a text that begins with the
    word "none" is recorded as just `none`. Both field runs of 0.28.0 (2026-11-26) passed a sentence that began
    "none (precision …". The Windows one came after the command had been changed to ask for "just `none`", and
    made a 496-character line of reasons that the entry states already or the session's own summary gives."""
    text = " ".join((iterations or "").split())
    if not text or re.match(r"none\b", text, re.IGNORECASE):
        return "none"
    return text


def render_eval_log(record: dict, agreement, specificity, iterations: str, *, folder: str, now=None) -> str:
    """The `/kg-eval` log entry, in the format the command's shell block wrote through 0.27.0, plus the run's
    folder."""
    passes = record.get("passes", [])
    best = _best_pass(passes)
    k = len(passes)
    lines = [f"\n## /kg-eval — {utc_iso(now)}",
             f"graph: {record.get('graph', 'n/a')}   (labeled n={best['labeled'] if best else 0})",
             f"source: {record.get('source') or 'n/a'}",
             f"run: {folder}",
             "",
             "Stage 4 — extraction precision"]
    if best:
        by_writer, by_state = _writer_lines(best.get("writers"))
        lines += [
            f"- PRECISION (best of {k} pass(es)):  {best['precision']:.2f}   "
            f"(target >= {evalsheet.PRECISION_GATE:.2f} — recorded, non-gating)",
            f"- astrology rate (fabricated+vague): {best['astrology_rate']:.2f}",
            f"- span-support rate (span_found=y):  {best['span_support_rate']:.2f}",
            f"- per-relation precision:            {_relation_line(best.get('per_relation'))}",
            f"- by writer:                         {by_writer}",
            f"- by grounding verdict:              {by_state}",
            f"- confidence calibration:            {_calibration_line(best.get('calibration'))}",
        ]
    else:
        lines.append("- PRECISION:                         not measured (no labels were scored)")
    lines += [f"- iterations:                        {k} ({_iterations_text(iterations)})",
              "",
              "Stage 7 — agreement + specificity"]
    if agreement:
        lines.append(f"- krippendorff_alpha:                {agreement['krippendorff_alpha']:.3f}   "
                     f"(reliable >= {agreement['threshold']} — {'RELIABLE' if agreement['reliable'] else 'advisory'})")
    else:
        lines.append("- krippendorff_alpha:                not measured")
    if specificity:
        verdict = specificity.get("verdict") or specificity.get("reason") or "n/a"
        lines.append(f"- specificity gate:                  gate_on={_fmt(specificity.get('gate_on'))} — {verdict}")
        lines.append(f"- generality confound detected:      {_fmt(specificity.get('generality_confound_detected'))}; "
                     f"rank_churn={_fmt(specificity.get('rank_churn'))}")
    else:
        lines.append("- specificity gate:                  not measured")
    return "\n".join(lines) + "\n"


def eval_log(project, *, run: str, iterations: str = "", now=None) -> dict:
    """Step `log`: append the run's entry to `.kg/PROGRESS.md`, written from the saved results. `iterations`
    is what only the orchestrator knows: the refinements made (a development checkout) or recommended (an
    installed copy), or "none"; `_iterations_text` keeps it on one line, and a text that begins with "none"
    as just that."""
    folder = _eval_run_dir(project, run)
    record = _read_json(folder / "run.json") or {}
    text = render_eval_log(record, _read_json(folder / "agreement.json"), _read_json(folder / "specificity.json"),
                           iterations or "", folder=str(folder), now=now)
    log = _append_log(project, text)
    return {"ok": True, "step": "log", "run": folder.name, "log": str(log), "entry": text}


# --------------------------------------------------------------------------- /kg-experiment

def _exp_dir(project) -> Path:
    return _kg(project) / EXPERIMENT_DIRNAME


def _exp_record_path(project, run) -> Path:
    return _exp_dir(project) / f"run-{check_run(run)}.json"


def _exp_record(project, run) -> dict:
    record = _read_json(_exp_record_path(project, run))
    if record is None:
        raise MeasureError(f"no /burgess:kg-experiment run {run} in {_exp_dir(project)}: start with step `start`")
    return record


def prompts_path(project, run) -> Path:
    return _exp_dir(project) / f"prompts-{check_run(run)}.json"


def outputs_path(project) -> Path:
    return _exp_dir(project) / "ideation_outputs.json"


def _is_demo(documents: "dict[str, str]") -> bool:
    """Whether the source is the demo that ships with the plugin, whose default prompts the command holds."""
    if len(documents) != 1 or not DEMO_SOURCE.is_file():
        return False

    def norm(t: str) -> str:
        return t.replace("\r\n", "\n").strip()
    return norm(next(iter(documents.values()))) == norm(DEMO_SOURCE.read_text(encoding="utf-8"))


def _load_prompts(path: Path) -> list:
    from .lightrag_arm import _load_prompts as load   # the one reading rule both arms share; imports no lightrag
    try:
        prompts = load(path)
    except (OSError, ValueError) as e:
        raise MeasureError(f"could not read the prompts file {path}: {e}") from None
    if not prompts:
        raise MeasureError(f"the prompts file {path} holds no prompt")
    return prompts


def experiment_start(project, *, source_path: str, notes_path=None, prompts: str = "",
                     lightrag=None, now=None) -> dict:
    """Step `start`: open a run, and say what it can do: the legacy-log note (the command stops on it),
    whether the optional LightRAG arm can run and the blind judge's controls fit the source, and whether the
    source is the demo. A prompt file given as `prompts` is read here and saved as the run's prompt set, so
    no agent reads a file outside the project."""
    if not source_path or not SourceSet.resolve(source_path):
        raise MeasureError("the graph has no source: run /burgess:kg-build first")
    base = _exp_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp(now)
    for k in range(1, RUN_ATTEMPTS + 1):
        run = stamp if k == 1 else f"{stamp}-{k}"
        path = _exp_record_path(project, run)
        if not path.exists() and not prompts_path(project, run).exists():
            break
    else:
        raise MeasureError(f"could not open a new run in {base}")
    documents = SourceSet(source_path).texts
    given = None
    if prompts:
        p = Path(prompts).expanduser()
        p = p if p.is_absolute() else Path(project) / p
        if not p.is_file():
            raise MeasureError(f"no prompts file at {p}")
        given = _load_prompts(p)
        _write_json(prompts_path(project, run), given)
    if lightrag is None:
        from .lightrag_arm import availability as lightrag
    available, reason = lightrag()
    capacity = judge.control_capacity(judge.Evidence(documents))
    record = {"run": run, "created_at": utc_iso(now), "source": source_path, "documents": sorted(documents),
              "prompts_given": str(prompts) if prompts else None, "lightrag": {"available": available,
                                                                               "reason": reason},
              "judge_possible": capacity["judge_possible"]}
    _write_json(_exp_record_path(project, run), record)
    return {
        "ok": True, "step": "start", "run": run, "folder": str(base),
        "prompts_path": str(prompts_path(project, run)), "prompts": given,
        "demo_source": _is_demo(documents), "documents": sorted(documents),
        "legacy_log": legacy_note(project, notes_path),
        "lightrag": {"available": available, "reason": reason},
        "judge": capacity,
        "outputs_path": str(outputs_path(project)),
        "rag_dir": str(base / f"rag-{run}"),
        "judge_dir": str(base / f"judge-{run}"),
    }


def experiment_rag(project, *, run: str, source_path: str, budget_tokens: int = harness._RAG_BUDGET_TOKENS) -> dict:
    """Step `rag`: the rag arm's passages, BM25 over the source's paragraphs (`harness rag-slices`)."""
    _exp_record(project, run)
    path = prompts_path(project, run)
    if not path.is_file():
        raise MeasureError(f"no prompt set at {path}: save the prompts there first (Step 1)")
    prompts = _load_prompts(path)
    out = _exp_dir(project) / f"rag-{run}"
    try:
        index = harness.write_rag_contexts(prompts, source_path, str(out), budget_tokens)
    except (harness._LoadError, ValueError) as e:
        raise MeasureError(str(e)) from None
    counts = [len(p["passages"]) for p in index["prompts"]]
    docs = {q["document"] for p in index["prompts"] for q in p["passages"]}
    return {"ok": True, "step": "rag", "run": run, "rag_dir": str(out), "prompts": len(counts),
            "passages": {"min": min(counts), "max": max(counts)}, "documents_used": len(docs),
            "documents": len(SourceSet.resolve(source_path)), "budget_tokens": int(budget_tokens),
            "files": [p["file"] for p in index["prompts"]]}


def experiment_score(project, *, run: str, source_path: str) -> dict:
    """Step `score`: `harness ideation` over the evaluator's outputs and the source, and the check of the
    evaluator's order (`harness evaluator-order`). Both are saved as `score-<run>.json`, and the outputs and
    their drafts are kept beside them under the run's name."""
    _exp_record(project, run)
    out = outputs_path(project)
    blob = _read_json(out)
    if blob is None:
        raise MeasureError(f"no outputs at {out}: the evaluator writes them (Step 2)")
    if not isinstance(blob, dict):
        raise MeasureError('the outputs file must be a JSON object like {"outputs": {...}}')
    if not source_path or not SourceSet.resolve(source_path):
        raise MeasureError("the graph has no source to score against")
    src_text = harness._source_text(source_path)
    documents = SourceSet(source_path).texts
    conditions = blob.get("outputs", {k: v for k, v in blob.items() if k != "source"})
    try:
        result = harness.ideation(conditions, src_text, documents=documents)
    except ValueError as e:
        raise MeasureError(f"the outputs in {out} cannot be scored: {e}") from None
    order = harness.evaluator_order(str(out))
    kept = []
    for suffix in ("", ".control", ".graph"):
        src = out.with_name(f"ideation_outputs{suffix}.json")
        if src.is_file():
            dst = out.with_name(f"ideation_outputs{suffix}-{run}.json")
            shutil.copy2(src, dst)   # copy2 keeps the times the order check reads
            kept.append(str(dst))
    score_path = _exp_dir(project) / f"score-{run}.json"
    _write_json(score_path, {"ideation": result, "evaluator_order": order})
    return {"ok": True, "step": "score", "run": run, "ideation": result, "evaluator_order": order,
            "score_path": str(score_path), "kept": kept}


def experiment_judge_packets(project, *, run: str, source_path: str) -> dict:
    """Step `judge_packets` (`--judge`): check the controls, then write one blind packet per prompt
    (`harness judge-packets`). `ok: false` with `failures` when a control failed its check: no packet is
    written, and the controls are rewritten once."""
    _exp_record(project, run)
    jdir = _exp_dir(project) / f"judge-{run}"
    controls_path = jdir / "private" / "controls.json"
    controls = _read_json(controls_path)
    if controls is None:
        raise MeasureError(f"no controls at {controls_path}: write them first (Step 3b, 1)")
    if not isinstance(controls, dict):
        raise MeasureError('the controls file must be a JSON object like {"decoys": [...], "positives": [...]}')
    blob = _read_json(outputs_path(project))
    if not isinstance(blob, dict) or not isinstance(blob.get("outputs"), dict):
        raise MeasureError(f"no outputs at {outputs_path(project)}")
    prompts = _load_prompts(prompts_path(project, run))
    try:
        result = judge.build_packets(blob["outputs"], prompts, SourceSet(source_path).texts,
                                     list(controls.get("decoys") or []), list(controls.get("positives") or []),
                                     str(jdir))
    except ValueError as e:
        raise MeasureError(str(e)) from None
    if result.get("written"):
        # one judge per packet: its packet and the verdict file it writes, never which arm is which
        result["judges"] = [{"packet": str(p), "verdict": str(jdir / "verdicts" / f"{p.stem}.json")}
                            for p in sorted((jdir / "packets").glob("*.md"))]
    else:
        result["failures"] = result.pop("checks", [])
    return {"ok": bool(result.get("written")), "step": "judge_packets", "run": run, "judge_dir": str(jdir),
            **result}


def experiment_judge_score(project, *, run: str) -> dict:
    """Step `judge_score` (`--judge`): the judges' verdicts under the pre-declared checks and sign tests
    (`harness judge-aggregate`), saved as `judge_score-<run>.json`."""
    _exp_record(project, run)
    jdir = _exp_dir(project) / f"judge-{run}"
    if not (jdir / "private" / "mapping.json").is_file():
        raise MeasureError(f"no packets were built in {jdir} (private/mapping.json is missing)")
    blob = _read_json(outputs_path(project))
    outputs = blob.get("outputs") if isinstance(blob, dict) else None
    result = judge.aggregate(str(jdir), outputs)
    path = _exp_dir(project) / f"judge_score-{run}.json"
    _write_json(path, result)
    return {"ok": True, "step": "judge_score", "run": run, "judge_score_path": str(path), **result}


def _support_line(check) -> str:
    if not isinstance(check, dict) or "rag" not in check or "control" not in check:
        return "not checked (the run needs both a rag and a control arm)"
    return (f"rag {_fmt(check.get('rag'))}, control {_fmt(check.get('control'))}, gap {_fmt(check.get('gap'))} "
            f"(needs {_fmt(check.get('min_gap'))}); probe drop {_fmt(check.get('probe_drop'))}")


def render_experiment_log(*, prompts_count: int, prompt_source: str, prompt_file: str, score: dict,
                          judge_score, judge_note: str = "", now=None) -> str:
    """The `/kg-experiment` log entry, in the format the command's shell block wrote through 0.27.0."""
    ideation, order = score.get("ideation") or {}, score.get("evaluator_order") or {}
    table = ideation.get("table") or {}
    arms = [a for a in ARM_ORDER if a in table] + sorted(a for a in table if a not in ARM_ORDER)
    lines = [f"\n## kg-experiment (Stage 8, method 0.12.0) — {utc_iso(now)}", "",
             f"Prompts: {prompts_count} ({prompt_source.strip() or 'n/a'}): {prompt_file}", "",
             "| condition | " + " | ".join(TABLE_COLUMNS) + " |",
             "|-----------|---|---------|---------|------------------|-----------|---------|------------------|"]
    for arm in arms:
        row = table[arm]
        lines.append(f"| {arm} | " + " | ".join(_fmt(row.get(c)) for c in TABLE_COLUMNS) + " |")
    for key, title in VERDICT_LINES:
        if key in ideation:
            lines += ["", f"**{title}:** {ideation[key]}"]
    lines += ["", f"**Support check:** {_support_line(ideation.get('support_check'))}"]
    for caveat in ideation.get("caveats") or []:
        lines += ["", f"**Caveat:** {caveat}"]
    problems = order.get("problems") or []
    lines += ["", "**Evaluator order:** " + ("verified" if order.get("verified")
                                              else "not verified: " + "; ".join(problems or ["no check ran"]))]
    if judge_score:
        checks = judge_score.get("checks") or {}
        v1, v2, v3 = (checks.get("v1_decoy_least_grounded") or {}, checks.get("v2_grounded_gap") or {},
                      checks.get("v3_positive_grounded") or {})
        n = judge_score.get("n", 0)
        lines += ["", f"**Judge (blind; grounded and useful, not novelty):** {n} prompts judged; "
                      f"V1 {_fmt(v1.get('prompts'))} of {n}, V2 gap {_fmt(v2.get('gap'))}, "
                      f"V3 {_fmt(v3.get('prompts'))} of {n}; valid: {_fmt(judge_score.get('valid'))}",
                  "", "| item | grounded | useful | mean rank |", "|---|---|---|---|"]
        ranks = judge_score.get("mean_rank") or {}
        for item, means in (judge_score.get("means") or {}).items():
            lines.append(f"| {item} | {_fmt(means.get('grounded'))} | {_fmt(means.get('useful'))} | "
                         f"{_fmt(ranks.get(item))} |")
        for key, title in JUDGE_VERDICT_LINES:
            if key in judge_score:
                lines += ["", f"**{title}:** {judge_score[key]}"]
        if judge_score.get("problems"):
            lines += ["", "**Judge problems:** " + "; ".join(judge_score["problems"])]
    elif judge_note.strip():
        lines += ["", f"**Judge:** {judge_note.strip()}"]
    return "\n".join(lines) + "\n"


def experiment_log(project, *, run: str, prompt_source: str = "", judge_note: str = "", now=None) -> dict:
    """Step `log`: append the run's entry to `.kg/PROGRESS.md` (an `# Experiment log` header opens a new
    file), written from `score-<run>.json` and, when the judge ran, `judge_score-<run>.json`.
    `prompt_source` says where the prompts came from; `judge_note` why the judge did not run, when asked for."""
    _exp_record(project, run)
    score = _read_json(_exp_dir(project) / f"score-{run}.json")
    if score is None:
        raise MeasureError("score the run first (step `score`)")
    path = prompts_path(project, run)
    count = len(_load_prompts(path)) if path.is_file() else 0
    text = render_experiment_log(prompts_count=count, prompt_source=prompt_source, prompt_file=str(path),
                                 score=score, judge_score=_read_json(_exp_dir(project) / f"judge_score-{run}.json"),
                                 judge_note=judge_note, now=now)
    log = _append_log(project, text, header="# Experiment log\n\n")
    return {"ok": True, "step": "log", "run": run, "log": str(log), "entry": text}
