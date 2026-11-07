"""Regression: Burgess commands read their arguments from `$ARGUMENTS`, never from numbered placeholders,
and /kg-build takes the `extract_wave_size` option from its own text, not from the shell.

Found after 0.4.4, while checking how a file name with spaces would reach /kg-build. The behavior below
was read from the Claude Code binary and run for real on 2026-11-07 (2.1.316 under WSL; the reporting
Windows install's 2.1.319 carries the same code). The older 2.1.202 on that machine also counts from 0,
but empties a `$N` with no argument behind it and counts that as a substitution, so it never appends the
ARGUMENTS line either:

- `$N` means `$ARGUMENTS[N]`, counted from **0**, so `$1` is the SECOND argument. A `$N` with no
  argument behind it is left as it is. Quoted text is one argument, without its quotes.
- `$ARGUMENTS` is the raw text typed after the command, quotes included.
- When nothing was substituted, Claude Code appends `ARGUMENTS: <raw text>` to the command.
- `${user_config.KEY}` in command text becomes the option's value when the option is set. An unset option
  leaves the placeholder (the schema's `default` is NOT applied); a sensitive one becomes a notice.
- `CLAUDE_PLUGIN_OPTION_<KEY>` variables go to hooks and MCP servers only, never to the Bash tool.

The commands were written for `$1` as the first argument. On 2.1.316, one argument worked by luck: `$1` was
left as it was and the appended ARGUMENTS line carried the value. With two (`/kg-build notes.md 4`) every
`$1` became `4` and the path vanished from the prompt. /kg-build's wave size never reached its script:
`${2:-…}` is not a placeholder Claude Code fills, bash's own `$2` is empty in the Bash tool, and so is
`CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE`, so every build ran in waves of 6 whatever the option said.
/kg-perturb's `SECOND="$1"` ran with an empty `$1` unless the orchestrator rewrote it, which silently
degraded a perturbation to `regroup`.

`_expand` models that substitution. It is pinned to the five expansions recorded that day (see
`OBSERVED`) and is used to show what the orchestrator receives. The static pins do not depend on it.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMMANDS = sorted((REPO / "commands").glob("*.md"))
SKILL_TEXTS = sorted((REPO / "skills").rglob("*.md"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---- a model of Claude Code's substitution, as observed ----------------------------------------------

# One pass, in the order Claude Code applies them, so a filled-in value is never re-read as a placeholder:
# an escaped `\$` before a digit or ARGUMENTS stays a literal `$`; `$ARGUMENTS[N]`; `$N`; `$ARGUMENTS`.
_PLACEHOLDER = re.compile(r"(?<!\\)\\\$(?=\d|ARGUMENTS)|\$ARGUMENTS\[(\d+)\]|\$(\d+)(?!\w)|\$ARGUMENTS")


def _tokens(raw: str) -> list[str]:
    """Shell-style split; whitespace split when the quoting does not parse (Claude Code's fallback)."""
    if not raw.strip():
        return []
    try:
        toks = shlex.split(raw)
    except ValueError:
        toks = []
    return toks or raw.split()


def _expand(text: str, raw: str, options: "dict[str, str] | None" = None) -> str:
    """What the orchestrator receives for a command `text` invoked with the typed arguments `raw`."""
    options = options or {}
    text = re.sub(r"\$\{user_config\.([^}]+)\}", lambda m: options.get(m.group(1), m.group(0)), text)
    toks = _tokens(raw)
    hit = False

    def fill(m: "re.Match[str]") -> str:
        nonlocal hit
        if m.group(0).startswith("\\"):
            return "$"
        index = m.group(1) or m.group(2)
        if index is not None:
            i = int(index)
            if i >= len(toks):
                return m.group(0)                # no such argument: left as it is
            hit = True
            return toks[i]
        hit = True
        return raw                               # $ARGUMENTS: the raw text, quotes and all

    out = _PLACEHOLDER.sub(fill, text)
    if not hit and raw:
        out += f"\n\nARGUMENTS: {raw}"
    return out


# (command text, typed arguments, options) -> what the transcript recorded, verbatim.
OBSERVED = [
    ("ONE=[$1] TWO=[$2]\nReply with the single word OK.\n", "fronteras.md", None,
     "ONE=[$1] TWO=[$2]\nReply with the single word OK.\n\n\nARGUMENTS: fronteras.md"),
    ("ZERO=[$0] ONE=[$1] TWO=[$2]\nReply with the single word OK.\n", '"Fábricas de software.md" 3', None,
     "ZERO=[Fábricas de software.md] ONE=[3] TWO=[$2]\nReply with the single word OK.\n"),
    ("WAVE=[${user_config.wave}] ZERO=[$0] ONE=[$1] ALL=[$ARGUMENTS]\n", "a b", None,
     "WAVE=[${user_config.wave}] ZERO=[a] ONE=[b] ALL=[a b]\n"),
    ("WAVE=[${user_config.wave}] ZERO=[$0] ONE=[$1] ALL=[$ARGUMENTS]\n", "", None,
     "WAVE=[${user_config.wave}] ZERO=[$0] ONE=[$1] ALL=[]\n"),
    ("WAVE=[${user_config.wave}] ZERO=[$0] ONE=[$1] ALL=[$ARGUMENTS]\n", '"x y" 3', {"wave": "8"},
     'WAVE=[8] ZERO=[x y] ONE=[3] ALL=["x y" 3]\n'),
]


@pytest.mark.parametrize("text,raw,options,recorded", OBSERVED)
def test_the_model_reproduces_what_claude_code_did(text, raw, options, recorded):
    assert _expand(text, raw, options) == recorded


# ---- static pins: they hold whatever the substitution does ------------------------------------------

@pytest.mark.parametrize("path", COMMANDS + SKILL_TEXTS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_command_or_skill_text_holds_a_numbered_placeholder(path):
    text = _read(path)
    found = sorted(set(re.findall(r"\$\d+", text)))
    assert not found, f"{path.name} uses {found}: Claude Code counts these from 0; read $ARGUMENTS"
    assert "$ARGUMENTS[" not in text


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.name)
def test_every_command_that_takes_arguments_reads_ARGUMENTS(path):
    text = _read(path)
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if front and "argument-hint:" in front.group(1):
        assert "$ARGUMENTS" in text, f"{path.name} declares arguments but never reads $ARGUMENTS"


@pytest.mark.parametrize("raw", ["", "notes.md", '"Fábricas de software.md" 4', "a b c"])
@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.name)
def test_the_typed_text_is_the_only_argument_claude_code_fills_in(path, raw):
    # Nothing but $ARGUMENTS changes, whatever is typed: no numbered placeholder takes a word, and no
    # ARGUMENTS line is appended because nothing was filled in.
    text = _read(path)
    assert _expand(text, raw) == text.replace("$ARGUMENTS", raw)


def test_two_arguments_both_reach_kg_build():
    text = _read(REPO / "commands" / "kg-build.md")
    got = _expand(text, '"Fábricas de software.md" 4')
    assert '**Arguments, as typed:** `"Fábricas de software.md" 4`' in got


def test_kg_build_reads_the_option_from_its_text_not_the_shell():
    text = _read(REPO / "commands" / "kg-build.md")
    assert "CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE" not in text   # hooks and the MCP server only
    # Since 0.5.0 the filled-in option goes to kg_build_plan, not to a WAVE_CFG line of a Bash block.
    assert 'configured_wave_size: "${user_config.extract_wave_size}"' in text


# ---- running the commands' Bash as the orchestrator would -------------------------------------------

def _working_bash() -> "str | None":
    """A bash that actually runs, or None: Git Bash first on Windows, the shell Claude Code's Bash tool
    uses there (the PATH `bash` may be the WSL stub). Same probe as test_fix_kg_build_paths."""
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files"):
            if base:
                candidates.append(str(Path(base) / "Git" / "bin" / "bash.exe"))
    candidates.append(shutil.which("bash"))
    for c in candidates:
        if not c or not Path(c).exists():
            continue
        try:
            r = subprocess.run([c, "-c", "echo ok"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip() == "ok":
            return c
    return None


BASH = _working_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no working bash (Windows without Git Bash)")


def _first_bash_block(text: str, after: str = "") -> str:
    section = text[text.index(after):] if after else text
    m = re.search(r"```bash\n(.*?)```", section, re.S)
    assert m, f"no ```bash block after {after!r}"
    return m.group(1)


def _run(script: str, tmp_path: Path, **env_extra: str) -> "tuple[int, str]":
    path = tmp_path / "block.sh"
    path.write_text(script, encoding="utf-8", newline="\n")      # CRLF would break bash
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")}
    env.update(env_extra)                                         # the Bash tool has no plugin options
    r = subprocess.run([BASH, str(path)], capture_output=True, env=env, timeout=60)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="replace").replace("\r", "")


def _plan_call(expanded: str) -> "tuple[str, str]":
    """The two values the orchestrator copies into kg_build_plan, read off the FILLED-IN command text: the
    arguments line, and the configured_wave_size text."""
    args = re.search(r"\*\*Arguments, as typed:\*\* `(.*)`", expanded)
    cfg = re.search(r'configured_wave_size: "([^"]*)"', expanded)
    assert args and cfg, "kg-build.md lost its arguments line or its kg_build_plan call"
    return args.group(1), cfg.group(1)


@pytest.fixture
def one_document(tmp_path: Path) -> Path:
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n\n## One\nx\n\n## Two\ny\n", encoding="utf-8")
    return doc


@pytest.mark.parametrize("raw,options,expected", [
    ("", {"extract_wave_size": "8"}, 8),            # the option, set: it reaches the build
    ("", None, 6),                                   # unset: the placeholder stays, and is not a number
    ("3", {"extract_wave_size": "8"}, 3),            # the arguments' wave size beats the option
    ("", {"extract_wave_size": "25"}, 10),           # clamped like any other value
    ('"doc.md" 4', None, 4),                         # a quoted subset, then the wave size
    ("doc.md 5", {"extract_wave_size": "8"}, 5),
])
def test_the_wave_size_reaches_the_plan(one_document, vault, raw, options, expected):
    # End to end without a shell: the command text as Claude Code fills it in (the model above), the two
    # values the orchestrator copies from it, and the plan the engine makes of them. Through 0.4.6 this
    # ran Step 0b's Bash block instead; 0.5.0 has none.
    from kg_engine.server import KGEngine

    args, cfg = _plan_call(_expand(_read(REPO / "commands" / "kg-build.md"), raw, options))
    plan = KGEngine(vault, source_path=one_document).kg_build_plan(args, cfg)
    assert plan["ok"], plan
    assert plan["wave_size"] == expected


def _kg_perturb_block(second: "str | None") -> str:
    script = _first_bash_block(_read(REPO / "commands" / "kg-perturb.md"))
    if second is not None:                                         # the orchestrator's own substitution
        assert 'SECOND="__SECOND__"' in script
        script = script.replace('SECOND="__SECOND__"', f'SECOND="{second}"', 1)
    return script


@needs_bash
def test_kg_perturb_stops_when_its_argument_was_not_filled_in(tmp_path):
    code, out = _run(_kg_perturb_block(None), tmp_path)
    assert code == 1, out
    assert "MODE=" not in out, out              # a forgotten substitution never passes for "no second source"


@needs_bash
@pytest.mark.parametrize("second,expected", [
    ("", ["MODE=degrade"]),
    ("otra carpeta/graph.json", ["MODE=graph", "SECOND_GRAPH=otra carpeta/graph.json"]),
    ("Mi segundo documento.md", ["MODE=source", "CONSTRUCTION=mi-segundo-documento",
                                 "SECOND_SOURCE=Mi segundo documento.md"]),
])
def test_kg_perturb_classifies_the_path_it_was_given(tmp_path, second, expected):
    code, out = _run(_kg_perturb_block(second), tmp_path)
    assert code == 0, out
    assert out.strip().splitlines() == expected, out
