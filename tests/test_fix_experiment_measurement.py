"""0.11.8 — /kg-experiment says when a column measured nothing, retrieves its rag passages deterministically,
reads every letter, and its evaluator needs no shell.

Field run on 0.11.7 (Windows, 2026-11-10; eight Spanish documents, 445,018 characters). The numbers were
right: `harness ideation` on a copy reproduced the score file exactly. All three verdicts were negative. But
the table said less than it seemed to:

- **The hallucination guard was blind.** unsupported_rate was 0.0 in every arm. A sentence counts as supported
  when any of its first three long words occurs anywhere in the source, and a corpus that size holds nearly
  every ordinary word: "El sistema Zorblax de Quantifex redujo las reversiones un 93 % en 2019" passed, and so
  did an English version. On the 2,741-character demo corpus the same sentences are caught.
- **utility was 0.0 everywhere.** Its markers are English words. Since 0.11.4 the prompts are drafted in the
  corpus's language, and no Spanish idea contains one.
- **The tokenizer knew only ASCII letters.** "revisión" counted as "revisi", "Ámbito" as "mbito", "más" not at
  all, in every idea and in 214 of the graph's 425 node labels (whose IDF specificity the projector computes
  with the same tokenizer). Re-scored with Unicode letters, no number moved more than 0.007 and the verdicts
  held; re-projected, 158 node specificities changed and the specificity gate, the top-10 weighted bridges
  and kg_generate's slate did not.
- **The evaluator used a shell.** It had Read, Grep and Bash but no Write, so it wrote its files through
  heredocs (two of 25 KB failed to parse) and built the rag arm with its own retrieval script, which crashed
  twice on the console's cp1252 encoding. 14 shell calls, 9 approvals; one waited 26 minutes. Its procedure
  also told it to read the source before writing the control answers, which it did not do.
- **"k=12 ignored".** The run read kg_generate's 51 candidates as `k` ignored. `k` is per mechanism (12 bridge,
  12 periphery, 11 regroup, 10 transplant, 4 compression, 2 seed); the tool description did not say so.

What the headline verdict should compare (novelty is measured against a source the control arm never sees)
is a separate decision; nothing here changes a verdict rule.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from kg_engine import harness
from kg_engine.projector import PROJECTION_RULES

REPO = Path(__file__).resolve().parents[1]
EXPERIMENT = REPO / "commands" / "kg-experiment.md"
EVALUATOR = REPO / "agents" / "evaluator.md"
SERVER = REPO / "scripts" / "kg_engine" / "server.py"
TOOLS_MD = REPO / "skills" / "burgess" / "references" / "tools.md"
DEMO = REPO / "examples" / "source.md"
OLD_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")  # the tokenizer through 0.11.7


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


def _front(text: str) -> str:
    return re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


# --------------------------------------------------------------------------- the evaluator has no shell

def test_the_evaluator_reads_with_read_and_writes_with_write():
    text = _read(EVALUATOR)
    tools = [t.strip() for t in re.search(r"^tools:(.*)$", _front(text), re.M).group(1).split(",")]
    assert tools == ["Read", "Write", "mcp__plugin_burgess_burgess__kg_context",
                     "mcp__plugin_burgess_burgess__query_graph", "mcp__plugin_burgess_burgess__kg_generate"]
    assert not _bash_blocks(text) and "```bash" not in text
    # no Grep either: the rag arm's passages come from the command, and reading the source for any other
    # arm would give that arm context the comparison does not account for
    assert "Grep" not in text


def test_the_evaluator_writes_control_before_any_tool_call():
    text = _read(EVALUATOR)
    procedure = _section(text, "## Procedure", "## Worked example")
    steps = [m.group(1) for m in re.finditer(r"^\d+\. \*\*([A-Z+ ]+?)(?: pass)?\.?\*\*", procedure, re.M)]
    assert steps.index("CONTROL") < steps.index("GRAPH") < steps.index("RAG"), steps
    assert "Make NO tool call" in procedure
    assert "Write every CONTROL answer before your first tool call" in _flat(text)
    # the 0.11.7 procedure opened with "Get to know the source" (Grep and Read it) before the control pass
    assert "Get to know the source" not in text


def test_the_evaluator_answers_rag_from_the_commands_passages_only():
    flat = _flat(_read(EVALUATOR))
    assert "**Read** file *k* of the rag folder and answer from its passages only" in flat
    assert "If the prompt file or the rag folder is missing, say which one and stop" in flat


def test_both_generate_arms_take_one_kg_generate_slate():
    for path in (EVALUATOR, EXPERIMENT):
        flat = _flat(_read(path))
        assert 'kg_generate(mechanism="all", k=12, dpp=false)' in flat, path.name
        assert 'kg_generate(mechanism="all", k=12, dpp=true)' in flat, path.name
        assert "k` is per mechanism" in flat, path.name
    # through 0.11.7 graph+generate took kg_context's stored hypotheses[] when there were any, a set the dpp
    # arm's kg_generate call could not reorder
    assert "the same call's `hypotheses[]` (or a `/kg-generate` slate)" not in _read(EXPERIMENT)


def test_the_evaluator_checks_the_file_it_wrote():
    flat = _flat(_read(EVALUATOR))
    assert "read it back with **Read** and check that it parses as JSON" in flat
    assert "A JSON string cannot hold a raw line break or an unescaped `\"`" in flat


# --------------------------------------------------------------------------- the command prepares the arms

def test_step_0_notes_the_run_and_whether_lightrag_can_run():
    first = next(b for b in _bash_blocks(_read(EXPERIMENT)) if '"$PY"' in b)
    assert '"$PY" -m kg_engine.lightrag_arm check' in first
    assert 'echo "RUN=$(date -u +%Y%m%dT%H%M%SZ)"' in first


def test_the_prompt_file_is_written_with_write_under_the_run_name():
    text = _read(EXPERIMENT)
    assert "Write" in _front(text).split("allowed-tools:", 1)[1]
    assert "save it with the **Write** tool as a JSON array of strings to" in _flat(text)
    assert "${CLAUDE_PROJECT_DIR}/.kg/experiment/prompts-<RUN>.json" in text


def test_step_1b_builds_the_rag_passages_before_the_evaluator_starts():
    text = _read(EXPERIMENT)
    call = '"$PY" -m kg_engine.harness rag-slices "$EXP/prompts-$RUN.json" "${user_config.source_path}" "$EXP/rag-$RUN"'
    blocks = [b for b in _bash_blocks(text) if call in b]
    assert len(blocks) == 2  # the default block, and the one that adds the LightRAG answers
    assert "lightrag_arm answer" not in blocks[0] and "lightrag_arm answer" in blocks[1]
    assert text.index("## Step 1b") < text.index("## Step 2")
    brief = _flat(_section(text, "## Step 2", "## Step 3"))
    assert "the rag folder `${CLAUDE_PROJECT_DIR}/.kg/experiment/rag-<RUN>`" in brief
    assert "The evaluator has no shell" in brief
    assert "Write all **control** answers first, from the prompts alone, before any tool call." in brief


def test_the_log_and_the_summary_carry_the_caveats_and_the_dpp_verdict():
    text = _read(EXPERIMENT)
    log = next(b for b in _bash_blocks(text) if ">> \"$PROGRESS\"" in b)
    assert "printf '\\n**Caveat:** %s\\n'" in log
    assert "printf '\\n**DPP verdict:** %s\\n'" in log
    assert "| graph+generate+dpp |" in log
    assert "Every entry of `caveats`, verbatim, right after the verdict" in _flat(text)


def test_kg_generate_says_k_is_per_mechanism():
    server = _flat(_read(SERVER))
    assert "`k` is per mechanism: each one surfaces its own top k" in server
    assert "max candidates **per mechanism** (ranked)" in _flat(_read(TOOLS_MD))


# --------------------------------------------------------------------------- every letter is a letter

def test_words_keep_their_letters_outside_ascii():
    assert harness._WORD.findall("más revisión rápido Ámbito ¿Qué?") == ["más", "revisión", "rápido", "Ámbito", "Qué"]
    assert harness._key_terms("La revisión automática detecta") == ["revisión", "automática", "detecta"]


@pytest.mark.parametrize("text", [
    DEMO.read_text(encoding="utf-8"),
    "AI-based e2e x_y 3D a1 B -- i.e. naïve? well-known_term 2026 C3PO",
])
def test_ascii_words_are_found_exactly_as_before(text):
    ascii_only = "".join(ch for ch in text if ord(ch) < 128)
    assert harness._WORD.findall(ascii_only) == OLD_WORD.findall(ascii_only)


def test_node_specificity_reads_an_accented_label_whole():
    seeds = harness.idf_seeds(["la revisión humana", "la revisión", "otra cosa", "algo más"])
    assert "revisión" in seeds and "revisi" not in seeds
    whole = harness.node_specificity("Revisión humana", seeds, default=9.0)
    assert whole == pytest.approx((seeds["revisión"] + seeds["humana"]) / 2)


def test_an_index_built_under_the_ascii_tokenizer_is_rebuilt():
    # "3" (0.11.8): an index written by an older plugin holds specificities of truncated words
    assert PROJECTION_RULES == "3"


# --------------------------------------------------------------------------- columns that cannot tell

INVENTED_ES = "El sistema Zorblax de Quantifex redujo las reversiones un 93 % en 2019."

# a large source in the field's register: every ordinary long word occurs somewhere
_LARGE = " ".join([
    "El sistema de revisión automática redujo las reversiones de los cambios en producción.",
    "Cada agente propone cambios pequeños y la integración continua comprueba las pruebas.",
    "La medida compara incidentes por cambio antes y después de retirar la revisión humana.",
    "Un clasificador por reglas enruta los cambios de bajo riesgo hacia la fusión automática.",
] * 40)

_SPANISH_IDEAS = [
    "Una medida nueva compararía los incidentes por cambio en producción. Cada agente propondría cambios "
    "pequeños y la integración continua comprobaría las pruebas.",
    "El clasificador enrutaría los cambios de bajo riesgo. La revisión humana se retiraría solo después "
    "de comparar las reversiones.",
]


def _scored(outputs: dict, source: str) -> dict:
    return harness.ideation(outputs, source)


def test_the_guard_is_reported_blind_when_invented_sentences_pass():
    outs = {"control": _SPANISH_IDEAS, "graph": _SPANISH_IDEAS[::-1], "rag": [INVENTED_ES + " " + _SPANISH_IDEAS[0]]}
    res = _scored(outs, _LARGE)
    # the field case: the guard passes an invented claim, so every arm scores a clean 0.0
    assert harness._score_condition([INVENTED_ES], _LARGE)["unsupported_rate"] == 0.0
    assert all(row["unsupported_rate"] == 0.0 for row in res["table"].values())
    probe = res["guard_probe"]
    assert probe["probes"] > 0 and probe["pass_rate"] >= harness._GUARD_BLIND_AT
    assert probe["source_chars"] == len(_LARGE)
    blind = [c for c in res["caveats"] if c.startswith("unsupported_rate cannot tell the arms apart")]
    assert len(blind) == 1
    assert f"{probe['passed']} of {probe['probes']}" in blind[0] and f"{len(_LARGE):,} characters" in blind[0]
    assert "could not have caught an arm that invents things" in blind[0]


def test_the_guard_is_not_reported_blind_where_it_can_tell():
    demo = DEMO.read_text(encoding="utf-8")
    # the invented sentence is caught on the small demo corpus
    assert harness._score_condition([INVENTED_ES], demo)["unsupported_rate"] == 1.0
    outs = {
        "control": ["Popularity bias lets heavily mentioned nodes accumulate centrality regardless of content.",
                    "Participation coefficients measure how evenly links spread across separate modules."],
        "graph": ["Specificity weighting exposes a vague node because its terms are not rare in the corpus.",
                  "A failed claim is negative information that defends against re-proposing a refuted edge."],
    }
    res = _scored(outs, demo)
    assert res["guard_probe"]["pass_rate"] < harness._GUARD_BLIND_AT
    assert not any(c.startswith("unsupported_rate") for c in res["caveats"])


def test_the_probe_judges_the_same_sentences_as_the_guard():
    ideas = ["Short one. " + _SPANISH_IDEAS[0], "Tiny. Too short.", _SPANISH_IDEAS[1]]
    judged = sum(len(harness._judged_terms(o)) for o in ideas)
    assert harness.guard_probe({"graph": ideas}, _LARGE)["probes"] == judged
    assert harness.guard_probe({"graph": ideas}, "")["pass_rate"] == 0.0
    assert harness.guard_probe({"graph": ["Too short."]}, _LARGE)["pass_rate"] is None


def test_utility_is_reported_when_no_arm_uses_a_marker():
    res = _scored({"control": _SPANISH_IDEAS, "graph": _SPANISH_IDEAS}, _LARGE)
    assert any(c.startswith("utility counts only the English markers") for c in res["caveats"])
    res = _scored({"control": _SPANISH_IDEAS, "graph": ["A bridges B because C holds."]}, _LARGE)
    assert not any(c.startswith("utility") for c in res["caveats"])


def test_caveats_never_change_a_verdict():
    outs = {"control": _SPANISH_IDEAS, "graph": _SPANISH_IDEAS[::-1]}
    res = _scored(outs, _LARGE)
    assert res["caveats"]  # blind guard and no utility marker
    assert res["verdict"] in ("graph condition produced more diverse/novel ideas without more unsupported claims",
                              "graph condition did NOT clearly beat control")
    plain = harness._arm_beats(res["table"]["graph"], res["table"]["control"])
    assert res["verdict"].startswith("graph condition produced") == plain


def test_every_ideation_result_carries_a_caveat_list(capsys):
    assert harness._main(["ideation"]) == 0  # the demo outputs
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out["caveats"], list) and set(out["guard_probe"]) == {"probes", "passed", "pass_rate",
                                                                          "source_chars"}


# --------------------------------------------------------------------------- the rag arm's passages

_DOC_A = """# Revisión de código

La revisión de código con agentes detecta defectos antes de la fusión.

## Riesgo

Un cambio de bajo riesgo se fusiona sin segunda aprobación cuando pasa el clasificador.
"""

_DOC_B = """# Otra cosa

Las ontologías describen conceptos y relaciones de un dominio.

Un párrafo muy largo """ + " ".join(f"palabra{i}" for i in range(400)) + """
"""


def _corpus(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text(_DOC_A, encoding="utf-8")
    (src / "b.md").write_text(_DOC_B, encoding="utf-8")
    return src


def _prompts(tmp_path: Path, prompts) -> Path:
    p = tmp_path / "prompts.json"
    p.write_text(json.dumps(prompts, ensure_ascii=False), encoding="utf-8")
    return p


def test_retrieval_folds_accents_and_ranks_the_matching_passage_first(tmp_path):
    src = _corpus(tmp_path)
    slices = harness.rag_slices(["revision de codigo", "ontologias y conceptos"],
                                harness.SourceSet(str(src)).texts)
    first = slices[0][0]
    assert first["document"] == "a.md" and "La revisión de código con agentes" in first["text"]
    assert first["text"].startswith("# Revisión de código")  # the heading travels with its paragraph
    assert slices[1][0]["document"] == "b.md" and "ontologías" in slices[1][0]["text"]


def test_passages_stay_short_and_the_budget_holds(tmp_path):
    texts = harness.SourceSet(str(_corpus(tmp_path))).texts
    passages = [p for t in texts.values() for p in harness._passages(t)]
    assert max(len(p) for p in passages) <= harness._RAG_PASSAGE_CHARS
    assert any(p.startswith("Un párrafo muy largo") for p in passages)  # cut, not dropped
    words = " ".join(f"palabra{i}" for i in range(400))
    assert " ".join(p for p in passages if "palabra" in p).replace("Un párrafo muy largo ", "") == words
    tight = harness.rag_slices(["palabra1 palabra2 palabra3 revisión"], texts, budget_tokens=10)[0]
    assert len(tight) == 1  # the best passage always, then nothing past the budget
    roomy = harness.rag_slices(["palabra1 palabra2 palabra3 revisión"], texts)[0]
    assert sum(len(p["text"]) for p in roomy) <= harness._RAG_BUDGET_TOKENS * harness._RAG_CHARS_PER_TOKEN


def test_a_prompt_that_shares_no_word_gets_no_passage(tmp_path):
    out = tmp_path / ".kg" / "experiment" / "rag-x"
    harness.write_rag_contexts(["zzz qqq"], str(_corpus(tmp_path)), str(out))
    assert "No passage of the source shares a word with this prompt." in (out / "01.md").read_text(encoding="utf-8")


def test_the_cli_writes_one_file_per_prompt_and_an_index(tmp_path, capsys):
    src = _corpus(tmp_path)
    prompts = ["revisión de código", "ontologías", "bajo riesgo"]
    out = tmp_path / ".kg" / "experiment" / "rag-run"
    assert harness._main(["rag-slices", str(_prompts(tmp_path, prompts)), str(src), str(out)]) == 0
    said = capsys.readouterr().out
    assert said.startswith(f"wrote 3 rag contexts to {out}:") and "of 2 documents" in said
    assert sorted(p.name for p in out.iterdir()) == ["01.md", "02.md", "03.md", "index.json"]
    first = (out / "01.md").read_text(encoding="utf-8")
    assert first.startswith("# Prompt 1 of 3\n\nrevisión de código\n") and "## Passage 1 — a.md" in first
    assert "score" not in first  # numbers in a generator's context leak into its ideas (D1)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert [p["prompt"] for p in index["prompts"]] == prompts and index["budget_tokens"] == 2000
    assert all(set(q) == {"document", "score", "chars"} for p in index["prompts"] for q in p["passages"])


@pytest.mark.parametrize("form", ["array", "object", "lines"])
def test_the_prompts_are_read_like_the_lightrag_arm_reads_them(tmp_path, form):
    prompts = ["revisión de código", "ontologías"]
    p = tmp_path / "prompts.txt"
    p.write_text({"array": json.dumps(prompts), "object": json.dumps({"prompts": prompts}),
                  "lines": "\n".join(prompts) + "\n"}[form], encoding="utf-8")
    out = tmp_path / ".kg" / "rag"
    assert harness._main(["rag-slices", str(p), str(_corpus(tmp_path)), str(out)]) == 0
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert [q["prompt"] for q in index["prompts"]] == prompts


def test_the_contexts_never_land_where_the_source_reads_documents(tmp_path, capsys):
    src = _corpus(tmp_path)
    before = sorted(p.name for p in src.iterdir())
    assert harness._main(["rag-slices", str(_prompts(tmp_path, ["revisión"])), str(src), str(src)]) == 2
    assert "is a folder the source reads its documents from" in capsys.readouterr().err
    assert sorted(p.name for p in src.iterdir()) == before
    # a one-file source reads that file only, so the folder around it is no source
    assert harness._main(["rag-slices", str(_prompts(tmp_path, ["revisión"])), str(src / "a.md"), str(src)]) == 0
    assert harness.SourceSet.resolve(str(src / "a.md")) == [src / "a.md"]


@pytest.mark.parametrize("argv, message", [
    (["rag-slices"], "usage: rag-slices PROMPTS SOURCE OUT_DIR"),
    (["rag-slices", "{missing}", "{src}", "{out}"], "prompts file not found"),
    (["rag-slices", "{prompts}", "{nowhere}", "{out}"], "source path not found"),
    (["rag-slices", "{empty}", "{src}", "{out}"], "the prompts file holds no prompt"),
    (["rag-slices", "{prompts}", "{src}", "{out}", "lots"], "BUDGET_TOKENS must be a whole number"),
])
def test_bad_input_is_a_clean_error(tmp_path, capsys, argv, message):
    paths = {"missing": tmp_path / "missing.json", "src": _corpus(tmp_path), "out": tmp_path / ".kg" / "rag",
             "prompts": _prompts(tmp_path, ["revisión"]), "nowhere": tmp_path / "nowhere",
             "empty": tmp_path / "empty.json"}
    paths["empty"].write_text("[]", encoding="utf-8")
    assert harness._main([a.format(**{k: str(v) for k, v in paths.items()}) for a in argv]) == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / ".kg").exists()


def _run_cli(args, env_extra):
    env = {**os.environ, "PYTHONPATH": str(REPO / "scripts"), **env_extra}
    return subprocess.run([sys.executable, "-m", "kg_engine.harness", *map(str, args)],
                          capture_output=True, env=env, timeout=120)


def test_the_passages_do_not_depend_on_the_hash_seed(tmp_path):
    src = _corpus(tmp_path)
    prompts = _prompts(tmp_path, ["revisión de código con agentes", "riesgo y aprobación", "ontologías palabra7"])
    outs = []
    for seed in ("1", "2"):
        out = tmp_path / f".kg-{seed}"
        r = _run_cli(["rag-slices", prompts, src, out], {"PYTHONHASHSEED": seed})
        assert r.returncode == 0, r.stderr.decode()
        outs.append({p.name: p.read_bytes() for p in sorted(out.iterdir())})
    assert outs[0] == outs[1]


def test_the_summary_survives_a_console_that_cannot_spell_the_path(tmp_path):
    out = tmp_path / ".kg" / "rag-ő"  # U+0151 is not in cp1252
    r = _run_cli(["rag-slices", _prompts(tmp_path, ["revisión"]), _corpus(tmp_path), out],
                 {"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"})
    assert r.returncode == 0, r.stderr.decode("cp1252", "replace")
    assert b"\\u0151" in r.stdout and (out / "01.md").exists()
