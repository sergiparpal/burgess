"""Deterministic resolver for the `/kg-build` extraction wave size (orchestration knob, not engine config).

`/kg-build` launches one `kg-extractor` subagent per section, in BOUNDED PARALLEL WAVES whose size this
resolves. It is an ORCHESTRATION parameter: the engine holds no setting for it and reads no env var for it
(cf. `tests/test_manifests.py`). Both values arrive as ARGUMENTS of `kg_build_plan`, which calls this
module, so since 0.5.0 this is the runtime resolution itself rather than a reference a Bash script
mirrored. It stays runnable as `python -m kg_engine.waves [arg]` for CI / any python-having caller.

Precedence: explicit inline arg > user_config (the `extract_wave_size` option) > default. A value that
is present but invalid at a given level falls straight to the default (it does NOT cascade to the next
level), as the Bash `${WAVE_ARG:-$WAVE_CFG}` of 0.4.5–0.4.6 did. Validation: parse to an integer;
unset / non-numeric / below the minimum → the default; above the maximum → clamp to the maximum.

Where each level comes from at runtime (0.5.0): the inline arg is the trailing whole number of the typed
`$ARGUMENTS`, which `kg_build_plan` splits off itself (`buildplan.parse_arguments`). The option reaches the
command through its own text: Claude Code fills `${user_config.extract_wave_size}` when the command loads
if the option is set and leaves the placeholder (non-numeric, so the default) when it is not, and the
command hands that text to `kg_build_plan` as `configured_wave_size`.
`CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE` (`WAVE_ENV`) is what hooks and MCP servers receive; the engine
deliberately does not read it, and only this module's CLI does.
"""
from __future__ import annotations

import os

DEFAULT_WAVE_SIZE = 6
MIN_WAVE_SIZE = 1
MAX_WAVE_SIZE = 10
WAVE_ENV = "CLAUDE_PLUGIN_OPTION_EXTRACT_WAVE_SIZE"


def resolve_wave_size(arg=None, env=None, *, default: int = DEFAULT_WAVE_SIZE,
                      lo: int = MIN_WAVE_SIZE, hi: int = MAX_WAVE_SIZE) -> int:
    """Resolve the bounded wave size from an inline override and the user_config value.

    The rules are the ones the 0.4.x Bash Step 0b applied, kept exactly when `kg_build_plan` took the
    resolution over in 0.5.0, so a configured or typed wave size means what it meant before:

    - **Precedence (Bash `${WAVE_ARG:-$WAVE_CFG}`):** the inline `arg` wins when it is a non-empty
      string — even whitespace-only, which is a *present* value and does NOT cascade to `env` (only a
      truly empty/unset `arg` falls through to `env`, then to `default`).
    - **Validation (Bash `case … in ''|*[!0-9]*`):** the chosen value must be a non-empty run of **ASCII
      digits** — anything with a sign, decimal point, or surrounding/embedded whitespace (`'+5'`, `' 4 '`,
      `'6.5'`) is invalid and resolves to `default` (it does not cascade to the next level).
    - **Clamp:** an all-digit value `< lo` → `default`; `> hi` → `hi`. Always returns an int in `[lo, hi]`.
    """
    return explain_wave_size(arg, env, default=default, lo=lo, hi=hi)[0]


def explain_wave_size(arg=None, env=None, *, default: int = DEFAULT_WAVE_SIZE,
                      lo: int = MIN_WAVE_SIZE, hi: int = MAX_WAVE_SIZE) -> "tuple[int, str]":
    """``(wave_size, origin)``: ``resolve_wave_size`` plus the level the value came from —
    ``"argument"``, ``"option"``, or ``"default"`` when the chosen level held nothing usable (unset, an
    unfilled placeholder, not a whole number, below the minimum). A value clamped to the maximum keeps
    its origin. ``kg_build_plan`` reports both, so the orchestrator can tell the user which wave size
    it used and why. The one implementation of the rule; ``resolve_wave_size`` is its first half."""
    from_arg = arg is not None and str(arg) != ""
    raw = arg if from_arg else env
    if raw is None or str(raw) == "":
        return default, "default"
    s = str(raw)
    if not (s.isascii() and s.isdigit()):  # ASCII digits only — what the 0.4.x Bash `*[!0-9]*` rejected
        return default, "default"
    n = int(s)
    if n < lo:
        return default, "default"
    return min(n, hi), ("argument" if from_arg else "option")


def main(argv=None) -> int:
    """`python -m kg_engine.waves [wave_size]` → print the resolved wave size. Reads the inline override
    from argv[1] (if given) and the user_config value from the environment (`WAVE_ENV`), as a hook or CI
    has it. `/kg-build` does not come through here: `kg_build_plan` receives both values as arguments."""
    import sys
    argv = sys.argv if argv is None else argv
    arg = argv[1] if len(argv) > 1 else None
    print(resolve_wave_size(arg, os.environ.get(WAVE_ENV)))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shim over resolve_wave_size
    raise SystemExit(main())
