"""0.28.1: a /kg-eval log entry's `iterations` line holds just `none` when the session wrote its reasons after the
word, and every stated count of the MCP tools is the number the server registers.

Found in the field runs of 0.28.0 (2026-11-26):
- `iterations`. Both runs, in WSL and on Windows (Claude Code 2.1.332, the installed plugin), passed a sentence
  that began "none (precision …". The Windows one came after the command had been changed to ask for "just
  `none`", and its entry's line read "1 (none (precision 0.94 >= 0.70, one pass). The only error, …)": 496
  characters of reasons the entry states already or the session's summary gives. The engine now records a text
  that begins with the word "none" as that word alone, and keeps any text on one line.
- The counts. The Windows session that read the skill's `references/tools.md` noticed that its opening said "the
  thirty-six graph tools" while its §1 said thirty-nine: the line came in 0.24.0 and 0.28.0 missed it.
  `docs/COMMANDS.md` still said "40 MCP tools", written in 0.22.0. No test pinned these counts, so each new tool
  could leave one stale; these tests read every one against `_register`.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

import pytest

from kg_engine import measure
from kg_engine.server import KGEngine, _register

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
LINE = "- iterations:                        "

# What the Windows run passed (session 07cdc32a, 2026-11-26), verbatim
FIELD = ("none (precision 0.94 >= 0.70, one pass). The only error, e_span-present-provenance__enables__authority-of-"
         "span-check (writer: lead, wrong_type: source says \"grounds\"), breaks a rule the current extractor.md "
         "Leads mode already states (check the span states head relation tail as the relation table defines it); "
         "the edge predates or ignored that rule, so no refinement is recommended. It is still grounded in the "
         "canon; /burgess:kg-ground could re-judge it.")
# ... and what the WSL run passed, before the command asked for "just `none`"
FIELD_WSL = "none (precision 1.0 met the 0.70 target on pass 1; no pack or extractor changes)"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _iterations_line(iterations: str) -> str:
    entry = measure.render_eval_log({}, None, None, iterations, folder="run")
    return next(line for line in entry.split("\n") if line.startswith("- iterations:"))


# --------------------------------------------------------------------------- iterations

@pytest.mark.parametrize("text", [FIELD, FIELD_WSL, "none", "None.", "NONE — nothing to refine", "", "  \n "],
                         ids=["field-windows", "field-wsl", "none", "None.", "NONE-and-a-reason", "empty", "blank"])
def test_a_text_that_begins_with_none_is_recorded_as_none(text):
    assert _iterations_line(text) == LINE + "0 (none)"


def test_a_word_that_only_begins_with_the_letters_is_kept():
    assert _iterations_line("nonetheless tightened `grounds`") == LINE + "0 (nonetheless tightened `grounds`)"


def test_a_refinement_written_on_several_lines_stays_on_one():
    entry = measure.render_eval_log({}, None, None, "tightened `grounds` in the pack\n  and the Leads rule\n",
                                    folder="run")
    lines = entry.split("\n")
    i = lines.index(LINE + "0 (tightened `grounds` in the pack and the Leads rule)")
    assert lines[i + 1:i + 3] == ["", "Stage 7 — agreement + specificity"]     # the entry keeps its shape


def test_the_field_text_reaches_the_log_as_none(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    notes = tmp_path / "notas"
    notes.mkdir()
    (notes / "notas.md").write_text("# Notas\n\n## Uno\nLa fábrica funciona cuando verifica cada cambio.\n",
                                    encoding="utf-8")
    eng = KGEngine(project, source_path=notes, pack_path=PACK)
    eng.kg_section("notas.md", 1)
    out = eng.kg_write({"nodes": [{"id": "fabrica", "label": "fábrica", "node_type": "claim",
                                   "body": "La fábrica de software."},
                                  {"id": "verificacion", "label": "verificación", "node_type": "operation",
                                   "body": "Verificar cada cambio."}],
                        "edges": [{"source": "fabrica", "target": "verificacion", "relation": "grounds",
                                   "span": "La fábrica funciona cuando verifica cada cambio",
                                   "source_file": "notas.md"}]})
    assert out["dispositions"]["ACCEPTED"] == 3, out
    sample = eng.kg_eval("sample")
    rows = list(csv.DictReader(open(sample["sheets"]["labels"], encoding="utf-8")))
    Path(sample["labels"]["labels"]).write_text(json.dumps(
        {r["edge_id"]: {"verdict": "correct", "span_found": "y", "notes": ""} for r in rows}), encoding="utf-8")
    assert eng.kg_eval("score", run=sample["run"])["score"]["precision"] == 1.0
    entry = eng.kg_eval("log", run=sample["run"], iterations=FIELD)["entry"]
    assert LINE + "1 (none)\n" in entry
    log = (project / ".kg" / "PROGRESS.md").read_text(encoding="utf-8")
    assert log == entry and "The only error" not in log


def test_the_command_and_the_tool_say_what_the_engine_records():
    command = _flat((REPO / "commands" / "kg-eval.md").read_text(encoding="utf-8"))
    assert "or just `none` when there were none" in command
    assert ("The engine records a text that begins with `none` as that word alone: your reasons go to the user, "
            "as the next paragraph says.") in command
    tools = _flat((REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8"))
    assert 'a text that begins with "none" is recorded as that word alone (0.28.1)' in tools
    server = _flat((REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8"))
    assert 'a text that begins with "none" is recorded as that word alone, so give your reasons to the user' in server


# --------------------------------------------------------------------------- the counts of the tools

_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80}


def _number(word: str) -> int:
    if word.isdigit():
        return int(word)
    word = word.lower()
    if word in _UNITS:
        return _UNITS[word]
    tens, _, unit = word.partition("-")
    return _TENS[tens] + (_UNITS[unit] if unit else 0)


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def surface(engine):
    mcp = _FakeMCP()
    _register(mcp, engine)
    names = set(mcp.tools)
    diverge = {n for n in names if n.startswith("kg_diverge_")}
    return {"names": names, "total": len(names), "divergence": len(diverge), "graph": len(names - diverge)}


def _read(rel: str) -> str:
    return _flat((REPO / rel).read_text(encoding="utf-8"))      # flattened: a count may wrap across lines


# Each sentence that states a count, and which count it states. A pin whose sentence is rewritten fails until it
# is updated here with the new wording: a count the docs state is a count these tests check.
PINS = [
    ("skills/burgess/references/tools.md", r"the ([a-z-]+) graph tools \(§1\)", "graph"),
    ("skills/burgess/references/tools.md", r"then the ([a-z-]+) divergence-surface tools \(§1B\)", "divergence"),
    ("skills/burgess/references/tools.md", r"These \*\*([a-z-]+)\*\* are the \*\*only\*\* graph tools", "graph"),
    ("skills/burgess/references/tools.md", r"The ([a-z-]+) \*\*divergence-surface\*\* tools \(§1B\) complete",
     "divergence"),
    ("skills/burgess/references/tools.md", r"complete the server's \*\*([a-z-]+)\*\*", "total"),
    ("skills/burgess/SKILL.md", r"make \*\*([a-z-]+)\*\* graph tools", "graph"),
    ("skills/burgess/SKILL.md", r"graph tools, and the ([a-z-]+) \*\*divergence-surface\*\* tools", "divergence"),
    ("skills/burgess/SKILL.md", r"make \*\*([a-z-]+)\*\* tools in total", "total"),
    ("CLAUDE.md", r"MCP server \((\d+) tools, namespaced", "total"),
    ("README.md", r"MCP server \(`burgess`, (\d+) tools\)", "total"),
    ("docs/ARCHITECTURE.md", r"\((\d+) tools, namespaced", "total"),
    ("docs/ARCHITECTURE.md", r"## 5\. The MCP tool surface \((\d+) tools\)", "total"),
    ("docs/COMMANDS.md", r"over \*\*(\d+) MCP tools\*\*", "total"),
]


@pytest.mark.parametrize("rel, pattern, count", PINS, ids=[f"{p[0]}:{p[2]}:{i}" for i, p in enumerate(PINS)])
def test_every_stated_count_of_the_tools_is_the_servers(surface, rel, pattern, count):
    found = re.findall(pattern, _read(rel))
    assert found, f"{rel}: the sentence that states the {count} count is gone; update its pin here"
    assert [_number(n) for n in found] == [surface[count]] * len(found), (rel, found, surface[count])


def test_the_skill_names_every_tool_and_its_counts_add_up(surface):
    passage = re.search(r"The [a-z-]+ read/write/ground tools .*? make \*\*[a-z-]+\*\* tools in total",
                        _read("skills/burgess/SKILL.md")).group(0)
    parts = [_number(re.search(pattern, passage).group(1)) for pattern in (
        r"The ([a-z-]+) read/write/ground tools",
        r"plus the ([a-z-]+) \*\*generative-layer\*\* tools",
        r"and the ([a-z-]+) that run /burgess:kg-eval's")]
    assert sum(parts) == surface["graph"], parts
    named = set(re.findall(r"`((?:kg|get|query|shortest)_[a-z_]+)`", passage))
    assert named == surface["names"], (sorted(surface["names"] - named), sorted(named - surface["names"]))
