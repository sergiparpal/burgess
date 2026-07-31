"""One-shot importer: old Cambrian state -> Burgess .kg/diverge layout (Stage 3).

Maps a Cambrian project's DURABLE preference memory (pins, discards, A-vs-B
comparisons, per domain) into a Burgess divergence project. Best-effort and
read-only on the source: files it cannot parse are reported, never modified.

Deliberately NOT imported, by design rather than omission:
* geometry state (archive.json, candidates.json, embeddings.json,
  mech_embeddings.json, open_nicher.json) — session-ephemeral in Burgess (I10);
  the durable archive is the knowledge graph, and a fresh session re-seeds from
  pins;
* meta.json / axes.json — the project is re-initialized under Burgess's pack/
  template resolution (`kg_diverge_init`), which re-snapshots axes and settings.
Both are listed in the report's ``skipped`` section so nothing disappears
silently.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import ConfigError
from .state import State, read_jsonl

_GEOMETRY_FILES = ("archive.json", "candidates.json", "embeddings.json",
                   "mech_embeddings.json", "open_nicher.json")
_META_FILES = ("meta.json", "axes.json")


def _default_source(project: str) -> Path:
    base = Path(os.environ.get("CAMBRIAN_HOME") or "~/.cambrian").expanduser()
    return base / project


def _read_json_list(path: Path, report: dict[str, Any]) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["errors"].append(f"{path}: {exc}")
        return []
    if not isinstance(data, list):
        report["errors"].append(f"{path}: expected a JSON list, got {type(data).__name__}")
        return []
    return [str(x) for x in data]


def import_cambrian(
    project: str,
    source: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Import old Cambrian preference memory into ``.kg/diverge/<project>``."""
    src = Path(source).expanduser() if source else _default_source(project)
    if not src.is_dir():
        raise ConfigError(
            f"no Cambrian project state at {src} — pass --from <old project dir> "
            f"(e.g. ~/.cambrian/<project>)"
        )

    report: dict[str, Any] = {"ok": True, "source": str(src), "imported": {},
                              "skipped": [], "errors": []}
    state = State(project, home=home).ensure()
    report["target"] = str(state.root)

    memory_root = src / "memory"
    domains = sorted(p.name for p in memory_root.iterdir() if p.is_dir()) if memory_root.is_dir() else []
    if not domains:
        report["errors"].append(f"{memory_root}: no per-domain memory found")

    for domain in domains:
        ddir = memory_root / domain
        counts = {"pins": 0, "discards": 0, "comparisons": 0}

        pins_path = ddir / "pins.json"
        if pins_path.exists():
            for cid in _read_json_list(pins_path, report):
                state.add_pin(domain, cid)
                counts["pins"] += 1

        discards_path = ddir / "discards.json"
        if discards_path.exists():
            for cid in _read_json_list(discards_path, report):
                # add_discard after add_pin would un-pin (mutual exclusion); the old
                # layout already kept the two disjoint, so order does not matter —
                # but guard anyway: never let an import discard something it pinned.
                if cid not in state.read_pins(domain):
                    state.add_discard(domain, cid)
                    counts["discards"] += 1
                else:
                    report["errors"].append(
                        f"{discards_path}: {cid} present in both pins and discards "
                        f"upstream; kept as PIN (latest-wins is unknowable offline)"
                    )

        comp_path = ddir / "comparisons.jsonl"
        if comp_path.exists():
            # the SAME tolerant-JSONL recovery policy State.read_comparisons uses (review-r5),
            # with the corrupt-line count surfaced into this import's error report.
            try:
                events, corrupt = read_jsonl(comp_path)
            except OSError as exc:
                report["errors"].append(f"{comp_path}: {exc}")
                events, corrupt = [], 0
            if corrupt:
                report["errors"].append(f"{comp_path}: skipped {corrupt} corrupt line(s)")
            for event in events:
                state.append_comparison(domain, event)
                counts["comparisons"] += 1

        report["imported"][domain] = counts

    for name in _GEOMETRY_FILES:
        if (src / name).exists():
            report["skipped"].append(
                f"{name}: geometry is session-ephemeral in Burgess (I10) — a new "
                f"session re-seeds from pins"
            )
    for name in _META_FILES:
        if (src / name).exists():
            report["skipped"].append(
                f"{name}: re-created by kg_diverge_init under the Burgess pack/"
                f"template resolution"
            )

    report["ok"] = not report["errors"] or bool(report["imported"])
    return report
