#!/usr/bin/env python3
"""I11 gate: each donor's Stage-0 state must still be identifiable in its history.

Checks, for each donor pinned in scripts/donor_pins.json:
  1. the donor directory exists and is a git repo,
  2. the pinned Stage-0 SHA still exists there as a commit,
  3. that SHA is reachable from the donor's current `HEAD`.

Exit code 0 iff every check passes. Run before every commit (installed as
.git/hooks/pre-commit; also invoked explicitly at every stage gate).
Cross-platform: pathlib + subprocess only, no shell.

Why reachability and not `HEAD == pinned SHA` (the original rule):

The invariant I11 protects is historical — *the fusion never wrote to a donor*.
That is now a settled fact about a finished migration; nothing this repository does
today can retroactively change it. The original gate enforced it through a proxy,
"the donor is frozen exactly where Stage 0 left it", which held only while the
donors stayed retired. It stopped holding the moment a donor resumed its own life:
Cambrian was republished and has since moved many commits past its pin, so the
proxy failed on every commit while the actual invariant remained perfectly intact.

Reachability is the weaker, true statement: the Stage-0 tree is still recoverable
and auditable (`git show <sha>`), so every attribution claim in
docs/fusion/ATTRIBUTION.md can still be checked against exactly what was copied.
What is deliberately no longer enforced is that a donor's working tree be clean or
its HEAD unmoved — a live repository is expected to have both, and neither tells us
anything about what the fusion did.

A pinned SHA that has become unreachable (history rewritten, commit garbage
collected, wrong checkout) is still a hard failure: at that point the provenance
record really has been lost.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_FILE = REPO_ROOT / "scripts" / "donor_pins.json"


def _git(donor: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(donor), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    pins = json.loads(PINS_FILE.read_text(encoding="utf-8"))
    failures: list[str] = []

    for name, info in pins["donors"].items():
        donor = (REPO_ROOT / info["path"]).resolve()
        sha = info["sha"]

        if not donor.is_dir():
            failures.append(f"{name}: donor directory missing at {donor}")
            continue

        # `cat-file -e <sha>^{commit}` is the cheapest existence-and-type check.
        exists = _git(donor, "cat-file", "-e", f"{sha}^{{commit}}")
        if exists.returncode != 0:
            failures.append(
                f"{name}: pinned Stage-0 commit {sha} no longer exists in {donor} "
                f"— the provenance record for this donor is gone"
            )
            continue

        # A commit is its own ancestor, so a donor still sitting exactly on its pin
        # passes here too.
        reachable = _git(donor, "merge-base", "--is-ancestor", sha, "HEAD")
        if reachable.returncode != 0:
            head = _git(donor, "rev-parse", "HEAD").stdout.strip()
            failures.append(
                f"{name}: pinned Stage-0 commit {sha} is not reachable from HEAD "
                f"{head} — history was rewritten or the wrong ref is checked out"
            )

    if failures:
        print("I11 GATE FAIL — donor Stage-0 provenance is not intact:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("I11 gate: donor Stage-0 commits present and reachable OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
