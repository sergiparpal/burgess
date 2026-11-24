"""The CI gate fails unless every test leg ran and succeeded (2026-11-24).

`ci-complete` is the one check the branch ruleset requires. It read only the matrix's summary result
(`needs.*.result`). On PR #153 that summary said success while the macOS leg had never run: GitHub found no runner
for it and cancelled it after 15 minutes. The gate passed, and auto-merge merged the PR. A second step now asks the
API for every leg of the run and fails unless each one concluded success, or when it finds none.
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


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="needs a POSIX bash")
@pytest.mark.parametrize("legs, passes", [
    ("engine tests + smoke (ubuntu-latest, 3.12)\tsuccess\nengine tests + smoke (macos-latest, 3.12)\tsuccess", True),
    ("engine tests + smoke (ubuntu-latest, 3.12)\tsuccess\nengine tests + smoke (macos-latest, 3.12)\tcancelled", False),
    ("engine tests + smoke (ubuntu-latest, 3.12)\tfailure", False),
    ("engine tests + smoke (windows-latest, 3.12)\tnone", False),
    ("", False),                                                          # no leg found: the gate stays shut
])
def test_the_step_fails_unless_each_leg_succeeded(tmp_path, legs, passes):
    stub = tmp_path / "gh"
    stub.write_text("#!/usr/bin/env bash\nprintf '%s' \"$LEGS\"\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "LEGS": legs}
    # GitHub replaces its `${{ … }}` expressions before bash sees the script, so do the same here
    script = re.sub(r"\$\{\{\s*github\.(\w+)\s*\}\}",
                    lambda m: {"repository": "owner/repo", "run_id": "1"}[m.group(1)], STEP["run"])
    done = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert (done.returncode == 0) is passes, done.stdout + done.stderr
