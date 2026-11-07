"""Tests for the /kg-build extraction wave-size resolver (kg_engine.waves).

Covers the deterministic resolver (resolve_wave_size / explain_wave_size + the `python -m kg_engine.waves`
CLI) and the runtime path that feeds it: since 0.5.0 `kg_build_plan` resolves the wave size from the typed
arguments and the option text the command hands it. Through 0.4.6 a drift guard here ran the command's
pure-Bash mirror instead; the command has no Bash left, so the resolver is the only implementation.

Contract: precedence inline-arg > user_config (the extract_wave_size option) > default(6); parse to int;
unset/non-numeric/<1 -> default; >10 -> clamp to 10; always in [1, 10].
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kg_engine.waves import (
    DEFAULT_WAVE_SIZE,
    MAX_WAVE_SIZE,
    MIN_WAVE_SIZE,
    WAVE_ENV,
    explain_wave_size,
    main,
    resolve_wave_size,
)

ROOT = Path(__file__).resolve().parents[1]


def test_constants_are_the_documented_bounds():
    assert (DEFAULT_WAVE_SIZE, MIN_WAVE_SIZE, MAX_WAVE_SIZE) == (6, 1, 10)
    assert WAVE_ENV == "CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE"


def test_default_when_unset():
    assert resolve_wave_size() == 6
    assert resolve_wave_size(None, None) == 6
    assert resolve_wave_size("", "") == 6
    assert resolve_wave_size("   ", "   ") == 6  # whitespace-only is treated as unset


@pytest.mark.parametrize("raw", ["abc", "3x", "6.5", "0x4", "", "   ", "+", "-"])
def test_non_numeric_falls_back_to_default(raw):
    assert resolve_wave_size(raw) == 6
    assert resolve_wave_size(None, raw) == 6


@pytest.mark.parametrize("raw", ["0", "-1", "-10"])
def test_below_minimum_falls_back_to_default(raw):
    # < 1 resolves to the DEFAULT (6), not clamped up to the minimum (1)
    assert resolve_wave_size(raw) == 6


@pytest.mark.parametrize("raw,expected", [("11", 10), ("100", 10), ("99999", 10)])
def test_above_maximum_clamps_to_ten(raw, expected):
    assert resolve_wave_size(raw) == expected
    assert resolve_wave_size(None, raw) == expected


@pytest.mark.parametrize("raw,expected", [("1", 1), ("5", 5), ("6", 6), ("9", 9), ("10", 10)])
def test_in_range_passes_through(raw, expected):
    assert resolve_wave_size(raw) == expected


def test_whitespace_padded_is_invalid_like_the_bash_runtime():
    # the runtime is the command's pure-Bash, which rejects any non-ASCII-digit char (incl. surrounding
    # whitespace and a leading sign) -> default. The reference mirrors it EXACTLY, so a padded/signed
    # value resolves to the default 6, not its inner number (this is what actually happens at runtime).
    assert resolve_wave_size("  4  ") == 6
    assert resolve_wave_size(" 4") == 6
    assert resolve_wave_size("4 ") == 6
    assert resolve_wave_size("+5") == 6


def test_int_and_leading_zero_inputs_resolve_to_their_value():
    assert resolve_wave_size(7) == 7        # an int arg (not a str) is accepted
    assert resolve_wave_size(99) == 10
    assert resolve_wave_size(0) == 6
    assert resolve_wave_size("07") == 7     # leading zeros are read base-10 (matches Bash's [ ] compare)
    assert resolve_wave_size("007") == 7


def test_precedence_inline_arg_beats_env_beats_default():
    assert resolve_wave_size("3", "8") == 3      # explicit arg wins
    assert resolve_wave_size(None, "8") == 8     # no arg -> env
    assert resolve_wave_size("", "8") == 8       # empty arg -> env
    assert resolve_wave_size(None, None) == 6    # neither -> default


def test_invalid_explicit_arg_falls_to_default_not_env():
    # a present-but-invalid arg resolves to the default; it does NOT cascade down to the env value
    assert resolve_wave_size("abc", "8") == 6
    assert resolve_wave_size("0", "8") == 6


# ---- the CLI shim ----------------------------------------------------------
def test_cli_prints_resolved_value(capsys, monkeypatch):
    monkeypatch.delenv(WAVE_ENV, raising=False)
    assert main(["waves", "3"]) == 0
    assert capsys.readouterr().out.strip() == "3"


def test_cli_clamps_and_reads_env(capsys, monkeypatch):
    monkeypatch.setenv(WAVE_ENV, "9")
    assert main(["waves"]) == 0                      # no arg -> env
    assert capsys.readouterr().out.strip() == "9"
    assert main(["waves", "11"]) == 0                # arg beats env, clamped
    assert capsys.readouterr().out.strip() == "10"


# ---- explain_wave_size: the value and the level it came from ---------------------------------------
@pytest.mark.parametrize("arg,cfg,expected", [
    ("3", "8", (3, "argument")),
    ("11", None, (10, "argument")),     # clamped, keeps its origin
    ("", "8", (8, "option")),
    (None, "11", (10, "option")),
    ("0", "8", (6, "default")),         # present-but-invalid: the default, never the option
    ("abc", None, (6, "default")),
    (None, "${user_config.extract_wave_size}", (6, "default")),   # an unfilled placeholder
    (None, None, (6, "default")),
])
def test_explain_wave_size_reports_the_level_used(arg, cfg, expected):
    assert explain_wave_size(arg, cfg) == expected
    assert resolve_wave_size(arg, cfg) == expected[0]


# ---- the runtime path: kg_build_plan resolves the wave size (0.5.0) ---------------------------------
# The two ways a value reaches the plan, reproduced as they happen: the typed wave size is the trailing
# whole number of `$ARGUMENTS`, which kg_build_plan splits off itself, and the option is the text Claude Code
# filled into `${user_config.extract_wave_size}` (left as written when the option is unset), which the command
# passes as `configured_wave_size`. The engine reads no env var for it (tests/test_manifests.py), so neither
# does this test's engine.
_CFG_PLACEHOLDER = "${user_config.extract_wave_size}"


@pytest.fixture
def plan_engine(tmp_path, vault, monkeypatch):
    from kg_engine.server import KGEngine

    monkeypatch.setenv(WAVE_ENV, "9")   # must change nothing: the engine never reads it
    src = tmp_path / "doc.md"
    src.write_text("## A\na\n\n## B\nb\n", encoding="utf-8")
    return KGEngine(vault, source_path=src)


@pytest.mark.parametrize("typed,cfg,expected,origin", [
    ("", _CFG_PLACEHOLDER, 6, "default"),     # nothing typed, option unset: the placeholder stays
    ("", "8", 8, "option"),
    ("", "11", 10, "option"),
    ("", "0", 6, "default"),
    ("", "abc", 6, "default"),
    ("doc.md 3", "8", 3, "argument"),         # typed beats the option
    ("4", _CFG_PLACEHOLDER, 4, "argument"),   # a lone whole number is the wave size
    ("doc.md 0", "8", 6, "default"),          # present-but-invalid does not cascade to the option
    ("doc.md 100", "", 10, "argument"),
    ("doc.md", "7", 7, "option"),
])
def test_the_plan_resolves_the_wave_size_like_the_resolver(plan_engine, typed, cfg, expected, origin):
    plan = plan_engine.kg_build_plan(typed, cfg)
    assert plan["ok"], plan
    assert (plan["wave_size"], plan["wave_size_from"]) == (expected, origin)
    assert plan["waves"] == -(-plan["sections_uncovered"] // expected)


def test_the_command_hands_the_option_to_the_plan():
    text = (ROOT / "commands" / "kg-build.md").read_text(encoding="utf-8")
    assert f'configured_wave_size: "{_CFG_PLACEHOLDER}"' in text
    assert "WAVE_CFG" not in text and "WAVE_ARG" not in text   # the 0.4.x Bash channels are gone
