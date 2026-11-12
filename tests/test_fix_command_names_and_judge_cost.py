"""0.13.3 — a command is named the way Claude Code runs it, and --judge states what it costs in the field.

**Command names.** Claude Code runs a plugin's command under the plugin's name, `/burgess:kg-build`.
- On the field install (Claude Code 2.1.322, Windows, 2026-11-11), `/kg-experiment --judge` answered "Unknown
  command: /kg-experiment", and `/burgess:kg-experiment --judge` ran.
- Every command the field sessions ran was in that full form.
- The plugin's own texts used the short form, and the field session copied them. In its messages to the user it
  wrote the short form 105 times and the full form 4 times, so following its advice led to the same error.

Since 0.13.3 every text a user or the model reads names a command in full:
- the current docs (README, TUTORIAL, CLAUDE.md, docs/COMMANDS.md, MIGRATION.md, ARCHITECTURE.md);
- the command files, the operating-guide skill and its references, and plugin.json's option descriptions;
- the engine's MCP tool descriptions, and the strings it returns or prints.

The short form stays where nobody is told to type a command:
- code comments, and docstrings that are not MCP tool descriptions;
- the historical records (CHANGELOG entries before 0.13.3, docs/fusion/*);
- the subagents' prompts, so the measurement agents' text does not move;
- the header `## /kg-eval — <date>` that /kg-eval writes to its log, a format the earlier entries share.

**The judge's cost.** 0.13.0 stated about 1.5 million tokens for 12 prompts. That came from the third pilot's
judges, general-purpose agents started from the development session with its tools and instructions. The
field's kg-judges, measured on two runs, end with 60,000–80,000 tokens of context each. A run takes about
0.8 million new tokens, plus about 1.3 million read back from the prompt cache.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMANDS = sorted(p.stem for p in (REPO / "commands").glob("kg-*.md"))
NAMES = "|".join(c.removeprefix("kg-") for c in COMMANDS)
# a slash, then the command; not part of a path (commands/kg-build.md), a URL or an already full name
SHORT = re.compile(rf"(?<![\w:/.-])/kg-({NAMES})(?![\w-])")
FULL = re.compile(r"/burgess:kg-([a-z]+)")
LOG_HEADER = "## /kg-eval —"

TEXTS = ["README.md", "TUTORIAL.md", "CLAUDE.md", "docs/COMMANDS.md", "docs/MIGRATION.md", "docs/ARCHITECTURE.md",
         ".claude-plugin/plugin.json"]
TEXTS += [f"commands/{c}.md" for c in COMMANDS]
TEXTS += sorted(str(p.relative_to(REPO)) for p in (REPO / "skills").rglob("*.md"))
ENGINE = sorted(p for p in (REPO / "scripts").rglob("*.py") if "__pycache__" not in p.parts)


def _short_in_texts() -> list[str]:
    found = []
    for rel in TEXTS:
        for n, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
            if LOG_HEADER in line:
                continue
            found += [f"{rel}:{n}: {m.group(0)}" for m in SHORT.finditer(line)]
    return found


def _quiet_docstrings(tree: ast.AST) -> list[tuple[int, int]]:
    """Line ranges of the docstrings no model reads: every module, class and function docstring except an MCP
    tool's, which FastMCP sends as the tool's description."""
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(ast.unparse(d).startswith("mcp.tool") for d in getattr(node, "decorator_list", [])):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            spans.append((body[0].lineno, body[0].end_lineno))
    return spans


def _engine_strings(path: Path):
    """(line, text) of every string literal a model or a user can read: f-string pieces included, comments and
    quiet docstrings left out."""
    src = path.read_text(encoding="utf-8")
    quiet = _quiet_docstrings(ast.parse(src))
    kinds = {tokenize.STRING} | {getattr(tokenize, k) for k in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
                                  if hasattr(tokenize, k)}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in kinds and not any(a <= tok.start[0] <= b for a, b in quiet):
            yield tok.start[0], tok.string


def test_the_current_docs_and_the_plugin_texts_name_every_command_in_full():
    assert len(COMMANDS) == 9
    assert _short_in_texts() == []


def test_the_engine_names_commands_in_full_wherever_a_model_or_a_user_reads_them():
    short = [f"{p.relative_to(REPO)}:{line}: {m.group(0)}" for p in ENGINE for line, text in _engine_strings(p)
             for m in SHORT.finditer(text)]
    assert short == []


def test_the_engine_check_sees_tool_descriptions_and_returned_strings():
    # the check above must not pass by reading nothing: it reads kg_build_plan's description and kg_generate's
    # note, and it leaves the module docstring of server.py out
    strings = " ".join(text for _, text in _engine_strings(REPO / "scripts" / "kg_engine" / "server.py"))
    assert "Plan a /burgess:kg-build:" in strings
    assert "(run /burgess:kg-perturb to supply one)" in strings
    tree = ast.parse((REPO / "scripts" / "kg_engine" / "server.py").read_text(encoding="utf-8"))
    assert ast.get_docstring(tree) and ast.get_docstring(tree) not in strings


def test_every_full_name_is_a_command_and_none_is_doubled():
    texts = [(REPO / rel).read_text(encoding="utf-8") for rel in TEXTS]
    texts += [text for p in ENGINE for _, text in _engine_strings(p)]
    named = {m.group(1) for t in texts for m in FULL.finditer(t)}
    assert named and named <= {c.removeprefix("kg-") for c in COMMANDS}
    assert not any("/burgess:burgess:" in t for t in texts)


def test_only_the_kg_eval_log_header_keeps_the_short_form():
    # the exemption is one line, the header /kg-eval writes; earlier log entries share it, and
    # tests/test_fix_eval_log_and_annotator.py pins it
    held = [(rel, line) for rel in TEXTS for line in (REPO / rel).read_text(encoding="utf-8").splitlines()
            if LOG_HEADER in line]
    assert held == [("commands/kg-eval.md", "  printf '\\n## /kg-eval — %s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"")]


def _slug(heading: str) -> str:
    # GitHub's anchor for a heading: lower case, punctuation dropped (so `/burgess:kg-build` → burgesskg-build),
    # spaces to hyphens
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_the_commands_reference_contents_links_still_land():
    text = (REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    anchors = {_slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", text, re.M)}
    links = re.findall(r"\]\(#([^)]+)\)", text)
    assert {f"burgesskg-{c.removeprefix('kg-')}" for c in COMMANDS} <= set(links)
    assert [link for link in links if link not in anchors] == []


def test_the_judge_cost_is_the_fields_figure_everywhere_it_is_stated():
    readme = " ".join((REPO / "README.md").read_text(encoding="utf-8").split())
    reference = " ".join((REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8").split())
    command = " ".join((REPO / "commands" / "kg-experiment.md").read_text(encoding="utf-8").split())
    assert "`--judge` adds blind judges, about 0.8 million tokens for 12 prompts" in readme
    assert "with blind judges (about 0.8 million tokens more for 12 prompts)" in reference
    for text in (reference, command):
        assert "ends with 60,000–80,000 tokens of context" in text
        assert "about 0.8 million new tokens" in text and "about 1.3 million read back from the prompt cache" in text
    assert all("1.5 million" not in t for t in (readme, reference, command))
