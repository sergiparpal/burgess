"""The CI gate fails unless every test leg ran and succeeded (2026-11-24).

`ci-complete` is the one check the branch ruleset requires. It read only the matrix's summary result
(`needs.*.result`). On PR #153 that summary said success while the macOS leg had never run: GitHub found no runner
for it and cancelled it after 15 minutes. The gate passed, and auto-merge merged the PR. A second step now asks the
API for every leg of the run and fails unless each one concluded success, or when it finds none. On this fix's
own PR a re-run of that step met a passing 502 from the API, so it asks up to five times before failing closed.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CI = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
GATE = CI["jobs"]["ci-complete"]
STEP = next(s for s in GATE["steps"] if s.get("name") == "Fail unless every test leg ran and succeeded")


def test_the_gate_reads_every_leg_of_the_run():
    assert CI["jobs"]["test"]["name"] == "engine tests + smoke"          # the prefix the step selects legs by
    assert GATE["needs"] == ["test"] and GATE["if"] == "always()"
    assert GATE["permissions"] == {"actions": "read"}                    # read-only, this job only
    assert GATE["steps"][0]["name"] == "Fail unless every required job succeeded"   # the summary check stays
    run = STEP["run"]
    assert "actions/runs/${{ github.run_id }}/jobs?filter=latest" in run
    assert 'startswith("engine tests")' in run
    assert STEP["env"] == {"GH_TOKEN": "${{ github.token }}"}


GREEN = "engine tests + smoke (ubuntu-latest, 3.12)\tsuccess\nengine tests + smoke (macos-latest, 3.12)\tsuccess"


def _run_step(tmp_path, legs: str, fails: int = 0):
    """Run the step's script as GitHub would (`bash -eo pipefail`, its `${{ … }}` expressions replaced first),
    with a stub `gh` that answers a server error for its first `fails` calls and then `legs`, and a stub `sleep`."""
    gh = tmp_path / "gh"
    gh.write_text("#!/usr/bin/env bash\n"
                  "n=$(cat \"$COUNT\" 2>/dev/null || echo 0); n=$((n+1)); echo \"$n\" > \"$COUNT\"\n"
                  "if [ \"$n\" -le \"$FAILS\" ]; then echo 'gh: Server Error (HTTP 502)' >&2; exit 1; fi\n"
                  "printf '%s' \"$LEGS\"\n", encoding="utf-8")
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for stub in (gh, sleep):
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "LEGS": legs,
           "FAILS": str(fails), "COUNT": str(tmp_path / "count")}
    script = re.sub(r"\$\{\{\s*github\.(\w+)\s*\}\}",
                    lambda m: {"repository": "owner/repo", "run_id": "1"}[m.group(1)], STEP["run"])
    done = subprocess.run(["bash", "-eo", "pipefail", "-c", script], env=env, capture_output=True, text=True)
    calls = int((tmp_path / "count").read_text()) if (tmp_path / "count").exists() else 0
    return done, calls


POSIX = pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="needs a POSIX bash")


@POSIX
@pytest.mark.parametrize("legs, passes", [
    (GREEN, True),
    ("engine tests + smoke (ubuntu-latest, 3.12)\tsuccess\nengine tests + smoke (macos-latest, 3.12)\tcancelled", False),
    ("engine tests + smoke (ubuntu-latest, 3.12)\tfailure", False),
    ("engine tests + smoke (windows-latest, 3.12)\tnone", False),
    ("", False),                                                          # no leg found: the gate stays shut
])
def test_the_step_fails_unless_each_leg_succeeded(tmp_path, legs, passes):
    done, _ = _run_step(tmp_path, legs)
    assert (done.returncode == 0) is passes, done.stdout + done.stderr


@POSIX
def test_a_passing_server_error_is_asked_again(tmp_path):
    done, calls = _run_step(tmp_path, GREEN, fails=2)
    assert done.returncode == 0 and calls == 3, done.stdout + done.stderr


@POSIX
def test_an_api_that_never_answers_keeps_the_gate_shut(tmp_path):
    done, calls = _run_step(tmp_path, GREEN, fails=99)
    assert done.returncode != 0 and calls == 5
    assert "did not list this run's jobs after 5 attempts" in done.stdout
