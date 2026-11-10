"""0.11.4 — /kg-eval and /kg-experiment run on an installed plugin, Windows included.

Found on 2026-11-10, when the user asked what else to try on the Windows corpus. Both commands, and the
two subagents they drive, were written for a development checkout:

- Every Python step named `/home/sergi/Burgess/.venv/bin/python`, a checkout on no user's machine, or
  `${CLAUDE_PLUGIN_DATA}/.venv/bin/python`, which does not exist on Windows (`.venv\\Scripts\\python.exe`).
  They now resolve the interpreter with `scripts/engine_python.mjs`, the launcher's own rule.
- Paths used `${VAR:-default}` forms. Claude Code fills in only the exact `${CLAUDE_PLUGIN_ROOT}`,
  `${CLAUDE_PLUGIN_DATA}` and `${CLAUDE_PROJECT_DIR}` tokens (read from the 2.1.316 binary), so /kg-eval
  looked for its graph under `<project>/.kg-data` and told the user to run /kg-build, /kg-experiment wrote
  under `/tmp`, and /kg-generate's absorption ledger landed in `<project>/.kg-data/derived`.
- The source was the repo's `examples/source.md`. The configured source can be a folder (the Windows corpus
  is eight documents in one), and the harness CLI and the LightRAG arm read it with `read_text`.
- /kg-experiment's 12 default prompts are about the demo corpus, so on any other corpus the experiment
  measured nothing. They are now used only for the demo; otherwise the prompts are drafted from the graph.
- /kg-eval's below-target loop edited `pack.yaml`/`agents/extractor.md` and re-ran /kg-build. In an
  installed copy that edits the version cache and rewrites the user's canon; it now only recommends.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_engine import harness, lightrag_arm
from kg_engine.sources import SourceSet, section_corpus

REPO = Path(__file__).resolve().parents[1]
TEXTS = (sorted((REPO / "commands").glob("*.md")) + sorted((REPO / "agents").glob("*.md"))
         + sorted((REPO / "skills").rglob("*.md")))
EVAL = REPO / "commands" / "kg-eval.md"
EXPERIMENT = REPO / "commands" / "kg-experiment.md"
GENERATE = REPO / "commands" / "kg-generate.md"
EVALUATOR = REPO / "agents" / "evaluator.md"
ANNOTATOR = REPO / "agents" / "annotator.md"
RESOLVER = REPO / "scripts" / "engine_python.mjs"
NODE = shutil.which("node")
# The exact tokens Claude Code fills into a plugin's command and agent text (2.1.316, the loader's spe());
# skills also get ${CLAUDE_SKILL_DIR}.
FILLED = {"CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR", "CLAUDE_SKILL_DIR"}
RESOLVE_LINE = 'PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")" || exit 1'


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


# --------------------------------------------------------------------------- what the text asks for

@pytest.mark.parametrize("path", TEXTS, ids=_rel)
def test_every_claude_variable_is_a_token_claude_code_fills_in(path):
    text = _read(path)
    for name, rest in re.findall(r"\$\{(CLAUDE_[A-Z_]+)([^}]*)\}", text):
        assert name in FILLED, f"{_rel(path)}: ${{{name}}} is never filled in"
        assert rest == "", f"{_rel(path)}: ${{{name}{rest}}} is a default form, which is never filled in"
    bare = sorted(set(re.findall(r"\$CLAUDE_[A-Z_]+", text)))
    assert not bare, f"{_rel(path)}: {bare} are never filled in; only the braced token is"


@pytest.mark.parametrize("path", TEXTS, ids=_rel)
def test_no_development_paths(path):
    text = _read(path)
    assert "/home/" not in text, f"{_rel(path)} names a development checkout"
    assert "/.venv/bin/python" not in text, f"{_rel(path)} spells a venv interpreter path, absent on Windows"


@pytest.mark.parametrize("path", [EVAL, EXPERIMENT, EVALUATOR, ANNOTATOR], ids=_rel)
def test_every_bash_block_that_runs_python_resolves_it_first(path):
    # Each Bash call is a fresh shell: a block that uses "$PY" resolves it itself, by the launcher's rule.
    blocks = [b for b in _bash_blocks(_read(path)) if '"$PY"' in b]
    assert blocks, f"{_rel(path)} runs no engine Python"
    for b in blocks:
        assert RESOLVE_LINE in b, f"{_rel(path)}: a block uses $PY without resolving it:\n{b}"
        assert b.index(RESOLVE_LINE) < b.index('"$PY"')


def test_kg_eval_reads_the_engine_graph_and_the_configured_source():
    text = _read(EVAL)
    assert 'GRAPH="${CLAUDE_PLUGIN_DATA}/derived/graph.json"' in text
    assert "query_graph(limit=1)" in text  # re-projects the shared derived dir for this project first
    assert '"$PY" -m kg_engine.harness specificity "$GRAPH" "${user_config.source_path}"' in text
    assert "${CLAUDE_PROJECT_DIR}/PROGRESS.md" in text and "${CLAUDE_PROJECT_DIR}/.kg/eval" in text
    assert "examples/source.md" not in text and ".kg-data" not in text


def test_kg_eval_never_edits_an_installed_copy_or_rebuilds_the_canon():
    section = _read(EVAL).split("### 4.5", 1)[1].split("\n---\n", 1)[0]
    assert "plugins/cache" in section
    assert "Do **not** edit `pack.yaml` or `agents/*.md` there" in section
    assert "Do **not** re-run `/kg-build` either" in section


def test_kg_experiment_drafts_its_prompts_for_any_corpus_but_the_demo():
    text = _read(EXPERIMENT)
    front = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
    assert "mcp__plugin_burgess_burgess__kg_agenda" in front  # drafting reads the graph's agenda
    assert "Use them only when the configured source is that file" in text
    assert "draft 12 prompts from the user's own graph" in text
    assert "${CLAUDE_PROJECT_DIR}/.kg/experiment/prompts-" in text
    # the demo corpus is only ever named as the plugin's own file, never as what the run reads
    starts = [m.start() for m in re.finditer(r"examples/source\.md", text)]
    prefix = "${CLAUDE_PLUGIN_ROOT}/"
    assert starts and all(text[i - len(prefix):i] == prefix for i in starts)


def test_kg_experiment_scores_and_retrieves_from_the_configured_source():
    text = _read(EXPERIMENT)
    assert '"$PY" -m kg_engine.harness ideation "$EXP/ideation_outputs.json" "${user_config.source_path}"' in text
    assert '--source "${user_config.source_path}"' in text
    assert "/tmp" not in text


def test_the_evaluator_reads_the_source_it_is_given_and_pastes_none():
    text = _read(EVALUATOR)
    assert not re.findall(r"\$\d", text)  # it is told its inputs, not handed numbered placeholders
    template = re.search(r"## Output.*?```json\n(.*?)```", text, re.S).group(1)
    assert '"source"' not in template  # the harness reads the source by path
    assert '--source "<the source path you were given>"' in text


def test_the_annotator_finds_each_rows_document_in_a_folder_source():
    text = _read(ANNOTATOR)
    assert "each row's document" in text and "`source_file`" in text


def test_kg_generate_keeps_its_ledger_where_the_engine_reads_it():
    assert 'DERIVED="${CLAUDE_PLUGIN_DATA}/derived"' in _read(GENERATE)


# --------------------------------------------------------------------------- engine_python.mjs

def _resolve(arg=None, **env_over):
    env = {k: v for k, v in os.environ.items() if k not in ("KG_ENGINE_VENV", "CLAUDE_PLUGIN_DATA")}
    env.update(env_over)
    cmd = [NODE, str(RESOLVER)] + ([arg] if arg is not None else [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)


def _fake_python(venv: Path) -> Path:
    exe = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    return exe


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_resolver_prints_the_pointer_bootstrap_wrote(tmp_path):
    data = tmp_path / "data"
    target = _fake_python(tmp_path / "elsewhere")  # the pointer may name any existing interpreter
    (data / ".venv").mkdir(parents=True)
    (data / ".venv" / "engine-python.txt").write_text(f"{target}\n", encoding="utf-8")
    r = _resolve(str(data))
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == target


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_resolver_falls_back_to_the_platforms_conventional_path(tmp_path):
    data = tmp_path / "data"
    exe = _fake_python(data / ".venv")
    r = _resolve(str(data))
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == exe


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_resolver_honours_KG_ENGINE_VENV_like_the_launcher(tmp_path):
    exe = _fake_python(tmp_path / "custom-venv")
    r = _resolve(str(tmp_path / "empty-data"), KG_ENGINE_VENV=str(tmp_path / "custom-venv"))
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == exe


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_resolver_exits_1_when_nothing_is_provisioned(tmp_path):
    r = _resolve(str(tmp_path / "empty-data"))
    assert r.returncode == 1 and r.stdout == ""
    assert "SessionStart" in r.stderr


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_an_unfilled_token_falls_back_to_the_environment(tmp_path):
    # Where Claude Code leaves ${CLAUDE_PLUGIN_DATA} unfilled (tools on another machine), the literal is
    # dropped like any unsubstituted value and the environment decides, as it does for the launcher.
    data = tmp_path / "data"
    exe = _fake_python(data / ".venv")
    r = _resolve("${CLAUDE_PLUGIN_DATA}", CLAUDE_PLUGIN_DATA=str(data))
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == exe


# --------------------------------------------------------------------------- a folder source, read once

DOC_A = "# Alpha\n\n## One\n\nEntropy grounds the arrow of time.\n\n## Two\n\nHeat flows from hot to cold.\n"
DOC_B = ("# Beta\n\n## Three\n\nA compression stands in for many observations.\n\n"
         "## Four\n\nBetweenness is confounded by the generality confound.\n")


def _folder(tmp_path: Path) -> Path:
    src = tmp_path / "corpus"
    src.mkdir()
    (src / "b.md").write_text(DOC_B, encoding="utf-8")
    (src / "a.md").write_text(DOC_A, encoding="utf-8")
    (src / ".hidden.md").write_text("# Hidden\n\nnever read\n", encoding="utf-8")
    (src / "notes.json").write_text("{}", encoding="utf-8")
    return src


def _graph(tmp_path: Path) -> Path:
    g = {"directed": True, "multigraph": False, "graph": {},
         "nodes": [{"id": n, "label": n} for n in ("entropy", "time", "compression", "betweenness")],
         "links": [{"source": "entropy", "target": "time"},
                   {"source": "compression", "target": "betweenness"},
                   {"source": "entropy", "target": "compression"}]}
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(g), encoding="utf-8")
    return p


def _specificity_of(gpath: Path, text: str) -> dict:
    gdata = json.loads(gpath.read_text(encoding="utf-8"))
    return json.loads(json.dumps(harness.specificity(gdata, section_corpus(text) or [text])))


def test_specificity_reads_a_folder_source_exactly_as_the_projector(tmp_path, capsys):
    src, gpath = _folder(tmp_path), _graph(tmp_path)
    text = SourceSet(src).concat  # the projector's corpus input (projector._src_text)
    assert "never read" not in text and DOC_A in text and DOC_B in text
    assert harness._main(["specificity", str(gpath), str(src)]) == 0
    assert json.loads(capsys.readouterr().out) == _specificity_of(gpath, text)


def test_a_single_file_source_reads_byte_for_byte_as_before(tmp_path, capsys):
    src, gpath = _folder(tmp_path) / "a.md", _graph(tmp_path)
    assert SourceSet(src).concat == src.read_text(encoding="utf-8")
    assert harness._main(["specificity", str(gpath), str(src)]) == 0
    assert json.loads(capsys.readouterr().out) == _specificity_of(gpath, src.read_text(encoding="utf-8"))


def test_a_source_with_no_document_is_a_clean_error_not_the_demo(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert harness._main(["specificity", str(_graph(tmp_path)), str(empty)]) == 2
    assert "source path not found" in capsys.readouterr().err


def test_ideation_scores_against_a_source_given_by_path(tmp_path, capsys):
    src = _folder(tmp_path)
    outputs = {"control": ["Heat flows from hot to cold because entropy grounds the arrow of time."],
               "graph": ["A compression bridges betweenness and entropy because it stands in for observations."],
               "rag": ["Betweenness is confounded by the generality confound, the text says."]}
    blob = tmp_path / "outputs.json"
    blob.write_text(json.dumps({"outputs": outputs, "source": "unrelated words only"}), encoding="utf-8")
    assert harness._main(["ideation", str(blob), str(src)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got == json.loads(json.dumps(harness.ideation(outputs, SourceSet(src).concat)))
    # the path wins over an embedded "source": scoring against those words would come out different
    assert got != json.loads(json.dumps(harness.ideation(outputs, "unrelated words only")))


def test_ideation_without_a_path_still_reads_the_embedded_source(tmp_path, capsys):
    outputs = {"control": ["entropy grounds time here"], "graph": ["entropy grounds time there"]}
    blob = tmp_path / "outputs.json"
    blob.write_text(json.dumps({"outputs": outputs, "source": "entropy grounds time"}), encoding="utf-8")
    assert harness._main(["ideation", str(blob)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got == json.loads(json.dumps(harness.ideation(outputs, "entropy grounds time")))


def test_lightrag_rebuilds_when_a_document_in_a_folder_source_changes(tmp_path):
    src = _folder(tmp_path)
    before = lightrag_arm._source_signature(src)
    # an in-place edit leaves the folder's own entry alone; the document's size and mtime move
    (src / "a.md").write_text(DOC_A + "\nA longer line, edited in place.\n", encoding="utf-8")
    assert lightrag_arm._source_signature(src) != before
