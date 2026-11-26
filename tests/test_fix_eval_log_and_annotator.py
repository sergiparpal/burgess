"""0.11.7 — /kg-eval keeps its log out of the source, its annotators need no shell, and its advice is checked
against the current plugin.

Field run on 0.11.6 (Windows, 2026-11-10). The numbers were right: precision 0.84 and α 0.901 both check
out against the CSVs. Three things were wrong:

- **The log was in the source.** The log went to `<project>/PROGRESS.md`, where 0.11.4 had put it. The
  user's source is the project folder itself, and `SourceSet` reads every `.md` at the top of a source
  folder. So the log became a ninth document: 85 sections, up from 84. The next /kg-build would have
  extracted it, and /kg-experiment's rag arm and its scoring would have read it as source.
- **The annotators used a shell.** They had Read, Grep and Bash, and were told to write the CSV with Bash.
  They searched the documents with shell grep and sed as well. In a setup that asks before every shell
  command, they cost the user 74 approvals (34, 28 and 12), plus 7 from the command itself. About 51 of
  the run's 56 minutes went to waiting.
- **The advice was stale.** The run recommended four extractor rules that the extractor has carried since
  0.8.0–0.11.0. Of the 13 edges labeled other than `correct`:
  - 9 were first-build extractions from 2026-11-07, before 0.8.0;
  - 3 were counter-edges from adversarial passes;
  - 1 was a lead written before 0.11.0.

  Grounding had already rejected 11 of the 13.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import re
import stat
from pathlib import Path

import pytest

from kg_engine import harness
from kg_engine.canon import Canon
from kg_engine.groundplan import ATTACK_MARK, LEAD_FROM_MARK
from kg_engine.model import AuthoredBy, Edge, EpistemicState, Node, Provenance
from kg_engine.sources import SourceSet

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "commands" / "kg-eval.md"
EXPERIMENT = REPO / "commands" / "kg-experiment.md"
ANNOTATOR = REPO / "agents" / "annotator.md"
EXTRACTOR = REPO / "agents" / "extractor.md"
USER_TEXTS = (sorted((REPO / "commands").glob("*.md")) + sorted((REPO / "agents").glob("*.md"))
              + sorted((REPO / "skills").rglob("*.md")) + [REPO / "TUTORIAL.md", REPO / "docs" / "COMMANDS.md"])

_spec = importlib.util.spec_from_file_location("f4_probe_0117", REPO / "scripts" / "f4_probe.py")
f4_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f4_probe)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


# --------------------------------------------------------------------------- the log stays out of the source

@pytest.mark.parametrize("path", USER_TEXTS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_nothing_points_the_log_at_the_top_of_the_project(path):
    assert "${CLAUDE_PROJECT_DIR}/PROGRESS.md" not in _read(path)


@pytest.mark.parametrize("path", [EVAL, EXPERIMENT], ids=lambda p: p.name)
def test_both_commands_append_their_log_under_dot_kg(path):
    # 0.28.0: the engine writes the entry (step `log`); no shell block of either command appends anything
    text = _read(path)
    assert ".kg/PROGRESS.md" in text and 'step="log"' in text
    assert not [b for b in _bash_blocks(text) if ">>" in b]


def test_the_engine_appends_the_log_under_dot_kg_and_never_overwrites(tmp_path):
    from kg_engine import measure

    log = measure._append_log(tmp_path, "\n## first entry\n")
    assert log == tmp_path / ".kg" / "PROGRESS.md"
    # /kg-experiment's header opens a NEW file only; an entry is never written over another
    measure._append_log(tmp_path, "\n## second entry\n", header="# Experiment log\n\n")
    assert log.read_bytes() == b"\n## first entry\n\n## second entry\n"
    assert measure._append_log(tmp_path / "other", "\n## x\n", header="# Experiment log\n\n").read_text(
        encoding="utf-8") == "# Experiment log\n\n\n## x\n"
    assert not (tmp_path / "PROGRESS.md").exists()


def test_a_log_at_the_top_of_a_source_folder_is_a_document_and_one_under_dot_kg_is_not(tmp_path):
    (tmp_path / "doc.md").write_text("# A\nbody\n", encoding="utf-8")
    (tmp_path / "PROGRESS.md").write_text("\n## /kg-eval — 2026-11-10T16:02:05Z\n", encoding="utf-8")
    (tmp_path / ".kg" / "eval").mkdir(parents=True)
    (tmp_path / ".kg" / "PROGRESS.md").write_text("# log\n", encoding="utf-8")
    assert {p.name for p in SourceSet.resolve(str(tmp_path))} == {"doc.md", "PROGRESS.md"}  # the field case
    (tmp_path / "PROGRESS.md").unlink()
    assert [p.name for p in SourceSet.resolve(str(tmp_path))] == ["doc.md"]
    # a recursive glob does not descend into the dot folder either
    assert [p.name for p in SourceSet.resolve(str(tmp_path / "**" / "*.md"))] == ["doc.md"]


def _legacy(argv, capsys):
    rc = harness._main(["legacy-log", *map(str, argv)])
    return rc, capsys.readouterr().out


def test_legacy_log_names_an_old_log_the_source_reads_and_leaves_it_alone(tmp_path, capsys):
    (tmp_path / "doc.md").write_text("# A\nbody\n", encoding="utf-8")
    old = tmp_path / "PROGRESS.md"
    old.write_bytes(b"\n## /kg-eval \xe2\x80\x94 2026-11-10T16:02:05Z\n")
    before = old.read_bytes()
    assert harness.legacy_log(tmp_path, str(tmp_path)) == old
    rc, out = _legacy([tmp_path, tmp_path], capsys)
    assert rc == 0 and out.startswith("NOTE: ") and str(old) in out
    assert str(tmp_path / ".kg" / "PROGRESS.md") in out and "never moves or deletes" in out
    assert old.read_bytes() == before and not (tmp_path / ".kg").exists()


def test_legacy_log_is_silent_when_no_old_log_is_a_source_document(tmp_path, capsys):
    project, other = tmp_path / "project", tmp_path / "docs"
    project.mkdir(), other.mkdir()
    (project / "doc.md").write_text("# A\n", encoding="utf-8")
    (other / "doc.md").write_text("# B\n", encoding="utf-8")
    assert _legacy([project, project], capsys) == (0, "")          # no old log
    (project / ".kg").mkdir()
    (project / ".kg" / "PROGRESS.md").write_text("# log\n", encoding="utf-8")
    assert _legacy([project, project], capsys) == (0, "")          # the new place is no document
    (project / "PROGRESS.md").write_text("# old log\n", encoding="utf-8")
    assert _legacy([project, project / "doc.md"], capsys) == (0, "")  # a one-file source
    assert _legacy([project, other], capsys) == (0, "")            # the source is another folder
    assert _legacy([project, tmp_path / "missing"], capsys) == (0, "")


def test_both_commands_check_for_an_old_log_in_their_first_step():
    # 0.28.0: the first engine step of each command answers `legacy_log` (kg_engine.measure.legacy_note)
    eval_step0 = _flat(_read(EVAL)[_read(EVAL).index("## Step 0"):_read(EVAL).index("## Stage 4")])
    exp_text = _read(EXPERIMENT)
    exp_step0 = _flat(exp_text[exp_text.index("## Step 0"):exp_text.index("### The optional `lightrag` arm")])
    assert 'kg_eval(step="sample")' in eval_step0 and "`legacy_log`" in eval_step0
    assert 'kg_experiment(step="start")' in exp_step0 and "`legacy_log`" in exp_step0
    assert "pass it on to the user now and again at the end, and go on" in eval_step0
    assert "If it holds a note, pass it on to the user and stop" in exp_step0
    for path in (EVAL, EXPERIMENT):
        assert "Don't move or delete the file" in _flat(_read(path)), path.name


def test_the_first_step_names_an_old_log_the_source_reads(tmp_path):
    from kg_engine import measure

    (tmp_path / "doc.md").write_text("# A\nbody\n", encoding="utf-8")
    (tmp_path / "PROGRESS.md").write_text("\n## /kg-eval — 2026-11-10T16:02:05Z\n", encoding="utf-8")
    note = measure.legacy_note(tmp_path, tmp_path)
    assert note and str(tmp_path / "PROGRESS.md") in note and "never moves or deletes" in note
    assert str(tmp_path / ".kg" / "PROGRESS.md") in note
    assert measure.legacy_note(tmp_path, None) is None              # the notes are not built: no old log is read


# --------------------------------------------------------------------------- the annotator has no shell

def _front(text: str) -> str:
    return re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)


def test_the_annotator_reads_with_read_and_grep_and_writes_with_write():
    text = _read(ANNOTATOR)
    tools = re.search(r"^tools:\s*(.+)$", _front(text), re.M).group(1)
    assert [t.strip() for t in tools.split(",")] == ["Read", "Grep", "Write"]
    assert not _bash_blocks(text), "the annotator has no shell to run a bash block in"
    assert "grep -" not in text and "python" not in text.lower().replace("f4_probe.py", "")


def test_the_annotator_writes_one_labels_file_that_fill_reads():
    text = _flat(_read(ANNOTATOR))
    sample = json.loads(re.search(r"```json\n(.*?)```", _read(ANNOTATOR), re.S).group(1))
    assert all(set(v) == {"verdict", "span_found", "notes"} for v in sample.values())
    assert all(v["verdict"] in f4_probe.VALID_VERDICTS for v in sample.values())
    assert "The engine fills the sheet from this file" in text and "never edit the file" in text
    assert "do not open any other `labels*.csv` or `labels*.json`" in text  # Stage 7 stays blind


def test_kg_eval_has_every_pass_write_its_own_labels_file_and_fills_before_reading():
    # 0.28.0: the run's folder holds one labels file per pass, and the engine fills each sheet before it reads
    # one (test_fix_commands_without_shell runs both steps)
    text = _read(EVAL)
    flat = _flat(text)
    assert "write your labels to <labels.labels>" in flat
    assert "labels = labels.labels_a" in text and "labels = labels.labels_b" in text
    assert 'kg_eval(step="score", run="<run>")' in flat
    assert "It fills the sheet from the annotator's labels and scores it" in flat
    assert 'kg_eval(step="agreement", run="<run>")' in flat and "It fills each sheet from its pass's labels" in flat
    assert "Never write or change a label yourself" in flat
    assert "Annotators get `Read`, `Grep` and `Write`, and no shell" in flat


# --------------------------------------------------------------------------- f4_probe fill

_GRAPH = {
    "nodes": [{"id": "a", "label": "Recuperación (híbrida, con «reranking»)"}, {"id": "b", "label": "Context rot"},
              {"id": "c", "label": "Oráculo \"fuerte\""}],
    "links": [
        {"id": "e_a__defends-against__b", "source": "a", "target": "b", "relation": "defends_against",
         "confidence": "INFERRED", "confidence_score": 0.5, "source_file": "Mejorar, sin perder.md"},
        {"id": "e_c__grounds__a", "source": "c", "target": "a", "relation": "grounds",
         "confidence": "INFERRED", "confidence_score": 0.7, "source_file": "Fábricas.md"},
        {"id": "e_b__attacked-by__c", "source": "b", "target": "c", "relation": "attacked_by",
         "confidence": "AMBIGUOUS", "confidence_score": "", "source_file": "Fábricas.md"},
    ],
}
_LABELS = {
    "e_a__defends-against__b": {"verdict": "correct", "span_found": "y",
                                "notes": "\"Puedes mitigarlo con recuperación precisa, compactación y subagentes\""},
    "e_c__grounds__a": {"verdict": "wrong_type", "span_found": "yes",
                        "notes": "the case grounds the rule, not the reverse; «oráculo», $HOME, `x`\nsecond line"},
    "e_b__attacked-by__c": {"verdict": "Fabricated", "span_found": "N", "notes": ""},
}


def _sheet(tmp_path: Path) -> Path:
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(_GRAPH, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "labels.csv"
    f4_probe.sheet(str(graph), 80, str(out), include_extracted=False)
    return out


def _rows(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_fill_writes_the_labels_and_keeps_every_other_column(tmp_path, capsys):
    sheet = _sheet(tmp_path)
    sheet.chmod(0o640)
    before = _rows(sheet)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(_LABELS, ensure_ascii=False), encoding="utf-8")
    f4_probe.main(["fill", str(sheet), str(labels)])
    assert "filled 3 rows" in capsys.readouterr().out
    if os.name == "posix":  # the swapped-in file keeps the sheet's mode, not mkstemp's 0600
        assert stat.S_IMODE(sheet.stat().st_mode) == 0o640
    after = _rows(sheet)
    assert [r["edge_id"] for r in after] == [r["edge_id"] for r in before]  # row order kept
    for b, a in zip(before, after):
        assert {k: v for k, v in a.items() if k not in ("verdict", "span_found", "notes")} == \
               {k: v for k, v in b.items() if k not in ("verdict", "span_found", "notes")}
        want = _LABELS[a["edge_id"]]
        assert a["verdict"] == want["verdict"].lower() and a["notes"] == want["notes"]
        assert a["span_found"] == ("y" if want["span_found"].lower() in ("y", "yes") else "n")
    f4_probe.main(["score", str(sheet)])
    out = capsys.readouterr().out
    assert "labeled edges: 3" in out and "PRECISION (correct / labeled):        0.33" in out
    assert not list(tmp_path.glob(".fill-*"))  # no temporary left behind


@pytest.mark.parametrize("change, problem", [
    (lambda d: d.pop("e_c__grounds__a"), "e_c__grounds__a: no entry in the labels file"),
    (lambda d: d.update({"e_x__grounds__y": {"verdict": "correct", "span_found": "y"}}),
     "e_x__grounds__y: not a row of the sheet"),
    (lambda d: d["e_c__grounds__a"].update(verdict="wrong_node"), "verdict 'wrong_node' is not one of"),
    (lambda d: d["e_c__grounds__a"].update(span_found="maybe"), "span_found 'maybe' is not y or n"),
    (lambda d: d.update({"e_c__grounds__a": "correct"}), "expected an object with verdict/span_found/notes"),
])
def test_fill_takes_the_labels_whole_or_not_at_all(tmp_path, change, problem):
    sheet = _sheet(tmp_path)
    before = sheet.read_bytes()
    labels = json.loads(json.dumps(_LABELS))
    change(labels)
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        f4_probe.main(["fill", str(sheet), str(path)])
    assert problem in str(e.value) and "the sheet is unchanged" in str(e.value)
    assert sheet.read_bytes() == before


@pytest.mark.parametrize("content, problem", [
    ('{"e_a__defends-against__b": {"verdict": "correct", "notes": "a "quoted" span"}}', "as JSON"),
    ('[{"edge_id": "e_a__defends-against__b"}]', "must hold one JSON object keyed by edge_id"),
])
def test_fill_refuses_a_file_that_is_not_one_json_object(tmp_path, content, problem):
    sheet = _sheet(tmp_path)
    before = sheet.read_bytes()
    path = tmp_path / "labels.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        f4_probe.main(["fill", str(sheet), str(path)])
    assert problem in str(e.value) and sheet.read_bytes() == before


# --------------------------------------------------------------------------- who wrote each labeled edge

def _edge(src, rel, tgt, **kw) -> Edge:
    return Edge(source=src, target=tgt, relation=rel, span=f"{src} {rel} {tgt}", **kw)


@pytest.fixture
def written(vault):
    """A canon with one edge from each writer the canon can tell apart."""
    g, r = EpistemicState.GROUNDED, EpistemicState.REJECTED
    nodes = [
        Node(id="extracted", label="Extracted", edges=[_edge("extracted", "grounds", "claim", epistemic_state=r)]),
        Node(id="lead-head", label="Lead head", edges=[_edge(
            "lead-head", "enables", "claim", epistemic_state=g,
            notes=f"{LEAD_FROM_MARK}e_extracted__grounds__claim) | grounded on the span")]),
        Node(id="hub", label="Hub", edges=[_edge(
            "hub", "attacked_by", "objection", epistemic_state=g,
            notes=f"{ATTACK_MARK}hub), standing challenge | grounded")]),
        Node(id="person", label="Person", edges=[_edge(
            "person", "grounds", "claim", epistemic_state=g, authored_by=AuthoredBy.HUMAN)]),
        Node(id="idea", label="Idea", edges=[_edge(
            "idea", "bridges", "claim", provenance=Provenance.HYPOTHESIZED)]),
        Node(id="claim", label="Claim"), Node(id="objection", label="Objection"),
    ]
    Canon(vault).write_nodes(nodes, message="seed")
    return vault


def _labels_csv(path: Path, verdicts: dict) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=f4_probe.SHEET_COLS)
        w.writeheader()
        for eid, verdict in verdicts.items():
            w.writerow({**{c: "" for c in f4_probe.SHEET_COLS}, "edge_id": eid, "verdict": verdict})
    return path


def test_writers_splits_the_sample_by_writer_and_by_verdict(written, tmp_path, capsys):
    sheet = _labels_csv(tmp_path / "labels.csv", {
        "e_extracted__grounds__claim": "wrong_type",
        "e_lead-head__enables__claim": "correct",
        "e_hub__attacked-by__objection": "wrong_type",
        "e_person__grounds__claim": "correct",
        "e_idea__bridges__claim": "fabricated",
        "e_gone__grounds__claim": "correct",       # merged away since the sheet was drawn
        "e_hub__grounds__claim": "",               # not labeled: skipped, as f4_probe score skips it
    })
    edges = {e.id: e for e in Canon(written, ensure_layout=False).all_edges()}
    res = harness.sample_writers(_rows(sheet), edges)
    assert res["by_writer"] == {"counter-edge": {"labeled": 1, "correct": 0},
                                "extractor": {"labeled": 1, "correct": 0},
                                "human": {"labeled": 1, "correct": 1},
                                "lead": {"labeled": 1, "correct": 1},
                                "proposal": {"labeled": 1, "correct": 0}}
    assert res["by_state"] == {"grounded": {"labeled": 3, "correct": 2},
                               "rejected": {"labeled": 1, "correct": 0},
                               "unverified": {"labeled": 1, "correct": 0}}
    assert [(o["writer"], o["state"], o["verdict"]) for o in res["not_correct"]] == [
        ("counter-edge", "grounded", "wrong_type"), ("extractor", "rejected", "wrong_type"),
        ("proposal", "unverified", "fabricated")]
    assert res["absent"] == ["e_gone__grounds__claim"]

    assert harness._main(["writers", str(sheet), str(written)]) == 0
    out = capsys.readouterr().out
    assert "  counter-edge         1        0       0.00" in out
    assert "wrong_type   grounded    counter-edge  e_hub__attacked-by__objection" in out
    assert "not in the canon now (1): e_gone__grounds__claim" in out
    assert out.rstrip().endswith(harness._WRITER_LEGEND)


def test_writers_refuses_a_project_with_no_canon_and_lays_none_out(tmp_path, capsys):
    sheet = _labels_csv(tmp_path / "labels.csv", {"e_a__grounds__b": "correct"})
    project = tmp_path / "project"
    project.mkdir()
    assert harness._main(["writers", str(sheet), str(project)]) == 2
    assert "no canon/ folder" in capsys.readouterr().err
    assert list(project.iterdir()) == []
    assert harness._main(["writers", str(tmp_path / "missing.csv"), str(project)]) == 2
    assert harness._main(["writers"]) == 2


def test_kg_eval_runs_writers_and_checks_a_refinement_against_the_current_contract():
    from kg_engine import measure

    text = _read(EVAL)
    flat = _flat(text)
    assert "- **writers** — each labeled edge read in the canon" in text
    assert "Before you recommend a refinement, here or in 4.5, check it against the current plugin." in flat
    # 0.28.0: the run copies the contract into its folder, inside the project, and the orchestrator reads the copy
    assert "Read the current contract, copied into Step 0's `contract.folder`" in flat
    assert measure.CONTRACT_FILES == ("agents/extractor.md", "agents/adversarial-grounder.md", "pack/pack.yaml")
    for contract in measure.CONTRACT_FILES:
        assert f"`{Path(contract).name}`" in text, contract
    assert "the edge was written before the rule" in flat
    assert "Name the errors whose rule the current contract already states" in flat


def test_the_rules_the_field_run_recommended_are_in_the_extractor():
    # The run's four recommendations, against the contract the installed 0.11.6 extractor reads.
    text = _flat(_read(EXTRACTOR))
    assert "a precondition or means that makes something possible, or makes it work → `enables`" in text
    assert "`wrong-node`" in text
    assert "a factor that biases the HEAD's figure, whether it inflates it, lowers it" in text
    assert "an instance/example offered as **evidence** for a claim → `grounds` (the example is the HEAD)" in text


# --------------------------------------------------------------------------- the log block keeps the text as written

def test_the_log_keeps_the_models_text_as_written(tmp_path):
    # 0.28.0: the engine writes the entry, so nothing the model supplies goes through a shell
    from kg_engine import measure

    best = {"pass": 1, "labeled": 80, "precision": 0.9, "astrology_rate": 0.05, "span_support_rate": 0.95,
            "per_relation": [], "calibration": None, "writers": None}
    record = {"graph": "/data/derived/graph.json", "source": "/src/docs", "passes": [best]}
    text = measure.render_eval_log(record, None, None,
                                   "a precondition is `enables`, not `grounds`; $HOME stays as written",
                                   folder="/project/.kg/eval/20261126T101500Z")
    log = measure._append_log(tmp_path, text).read_text(encoding="utf-8")
    assert "a precondition is `enables`, not `grounds`; $HOME stays as written" in log
    assert re.search(r"\n## /kg-eval — \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n", log)
    assert "graph: /data/derived/graph.json   (labeled n=80)\nsource: /src/docs\n" in log
    assert not (tmp_path / "PROGRESS.md").exists()
