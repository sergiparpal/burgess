"""Command-line entry point: ``python -m kg_engine.divergence <cmd> ...``.

Every command reads/writes JSON and takes ``--project`` plus, where relevant,
``--axes`` / ``--seed``. Output goes to stdout as JSON; errors print to stderr
and exit non-zero.

Structure (review-r5): the shared flags live on argparse PARENT parsers and each
subcommand registers its handler via ``set_defaults(handler=...)`` — previously
``--project`` was declared eight times and a parallel if/elif chain restated
every command name a second time, so adding a command meant two distant edits
that had to agree on the string.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config, pipeline, selftest


def _emit(obj: Any) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _read_json_file(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Identify which path failed — ingest reads both --candidates and --axes.
        raise config.ConfigError(f"could not read JSON from {path}: {exc}") from exc


# --------------------------------------------------------------------------- handlers
# One small function per subcommand; each returns the process exit code.


def _cmd_init_project(args) -> int:
    _emit(pipeline.init_project(args.project, args.axes, seed=args.seed, session=args.session))
    return 0


def _cmd_paths(args) -> int:
    _emit(pipeline.paths(args.project))
    return 0


def _cmd_recall(args) -> int:
    _emit(pipeline.recall(args.project, k=args.k))
    return 0


def _cmd_export(args) -> int:
    from . import export_ideas
    _emit(export_ideas.export_ideas(args.project, brief=args.brief))
    return 0


def _cmd_ingest(args) -> int:
    candidates = _read_json_file(args.candidates)
    _emit(pipeline.ingest(args.project, candidates, args.axes, seed=args.seed))
    return 0


def _cmd_remember(args) -> int:
    event = _read_json_file(args.event)
    _emit(pipeline.remember(args.project, event))
    return 0


def _cmd_parents(args) -> int:
    _emit(pipeline.parents(args.project, k=args.k, seed=args.seed))
    return 0


def _cmd_metrics(args) -> int:
    _emit(pipeline.metrics(args.project))
    return 0


def _cmd_selftest(args) -> int:
    report = selftest.run(project=args.project, live=args.live, seed=args.seed)
    _emit(report)
    return 0 if report.get("ok") else 1


def _cmd_import_cambrian(args) -> int:
    from . import importer

    report = importer.import_cambrian(args.project, source=Path(args.source) if args.source else None)
    _emit(report)
    return 0 if report.get("ok") else 1


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kg_engine.divergence",
        description="Deterministic diversity engine for the ideate skill.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # shared flags, declared once (selftest keeps its own --project: it DEFAULTS to "selftest"
    # instead of being required, so it can't ride the common parent).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True)
    seeded = argparse.ArgumentParser(add_help=False)
    seeded.add_argument("--seed", type=int, default=0)

    sp = sub.add_parser("init-project", parents=[common, seeded],
                        help="create state dirs, snapshot axes")
    sp.add_argument("--axes", required=True, help="path to axes .json/.yaml")
    sp.add_argument("--session", default=None,
                    help="session id to begin or resume (I10: a new/omitted id "
                         "wipes the ephemeral geometry archive; the persisted id "
                         "resumes the running session)")
    sp.set_defaults(handler=_cmd_init_project)

    sp = sub.add_parser("paths", parents=[common],
                        help="ensure the project state dir (+ tmp/) and print resolved paths")
    sp.set_defaults(handler=_cmd_paths)

    sp = sub.add_parser("recall", parents=[common], help="return preference memory for injection")
    sp.add_argument("--k", type=int, default=10)
    sp.set_defaults(handler=_cmd_recall)

    sp = sub.add_parser("ingest", parents=[common, seeded],
                        help="embed -> place -> novelty -> DPP -> monitor")
    sp.add_argument("--candidates", required=True, help="path to candidates .json")
    sp.add_argument("--axes", required=True, help="path to axes .json/.yaml")
    sp.set_defaults(handler=_cmd_ingest)

    sp = sub.add_parser("remember", parents=[common],
                        help="append a comparison/pin/discard to memory")
    sp.add_argument("--event", required=True, help="path to event .json")
    sp.set_defaults(handler=_cmd_remember)

    sp = sub.add_parser("parents", parents=[common, seeded],
                        help="diverse parents for next generation")
    sp.add_argument("--k", type=int, default=4)
    sp.set_defaults(handler=_cmd_parents)

    sp = sub.add_parser("metrics", parents=[common], help="current archive health")
    sp.set_defaults(handler=_cmd_metrics)

    sp = sub.add_parser("export", parents=[common],
                        help="write every idea of the current session to a Markdown file "
                             "under the brief's state dir and print where")
    sp.add_argument("--brief", default="", help="the brief, to head the file")
    sp.set_defaults(handler=_cmd_export)

    sp = sub.add_parser("selftest", parents=[seeded], help="full loop with stubbed LLM + human")
    sp.add_argument("--live", action="store_true", help="use the live embedder")
    sp.add_argument("--project", default="selftest")
    sp.set_defaults(handler=_cmd_selftest)

    sp = sub.add_parser(
        "import-cambrian", parents=[common],
        help="one-shot import of an old Cambrian project's preference memory "
             "(pins/discards/comparisons) into .kg/diverge; read-only on the source",
    )
    sp.add_argument("--from", dest="source", default=None,
                    help="old Cambrian project dir (default: ~/.cambrian/<project>)")
    sp.set_defaults(handler=_cmd_import_cambrian)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # surface a clean message, non-zero exit
        if config.debug_enabled():
            raise  # full traceback for diagnosis when debugging
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
