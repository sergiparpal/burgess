"""The paths a command's Bash block needs for THIS project (0.23.0): ``python -m kg_engine.paths <what> ...``.

Since 0.23.0 each project keeps its own derived layer under the plugin's data dir
(``envconfig.resolve_project_data_dir``) and may name its own notes in its policy
(``evidence.Policy.notes_path``). A command's text can no longer spell the graph's path as
``${CLAUDE_PLUGIN_DATA}/derived/graph.json`` or the source as ``${user_config.source_path}``: the first is the
shared folder 0.22 and earlier wrote, and the second is the plugin's one value for every project, which is not
what a project with its own notes, or one that builds from registered sources, was built from. These subcommands
print the project's own, one line each:

- ``graph <project> <plugin_data>``: the project's ``derived/graph.json``.
- ``data-dir <project> <plugin_data>``: the project's data dir.
- ``source <project> <plugin_data> [source_path]``: a path ``SourceSet`` reads as exactly the files the graph is
  built from. That is the notes path itself when the build reads the notes alone, else a folder under the
  project's data dir holding a copy of each file the build reads (the registered copies marked ``build``, and
  the notes when they are built too), refreshed on each call. Prints nothing when there is no source at all.

``plugin_data`` is the command text's ``${CLAUDE_PLUGIN_DATA}``, given explicitly because the Bash tool's
environment does not carry the plugin's variables.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import envconfig

CONTENT_DIRNAME = "content"


def project_data_dir(project: "str | Path", plugin_data: str = "") -> Path:
    """The project's data dir, as the server resolves it, for a plugin data dir given explicitly."""
    root = envconfig.clean(plugin_data) or envconfig.clean_env("KG_DATA") or envconfig.clean_env("CLAUDE_PLUGIN_DATA")
    if not root:
        return Path(project) / envconfig.DATA_DIRNAME
    return Path(root) / envconfig.PROJECTS_DIRNAME / envconfig.project_key(project)


def graph_path(project: "str | Path", plugin_data: str = "") -> Path:
    return project_data_dir(project, plugin_data) / envconfig.DERIVED_DIRNAME / "graph.json"


def content_source(project: "str | Path", plugin_data: str = "", source_path: str = "") -> str:
    """A path whose files are exactly what the project's graph is built from (see the module docstring)."""
    from .evidence import evidence_dir
    from .server import _SourceResolver   # deferred: the server module is heavy, and only this needs it

    project = Path(project)
    resolver = _SourceResolver(envconfig.clean(source_path) or None, evidence_dir(project), project)
    return write_content(resolver, project_data_dir(project, plugin_data))


def write_content(resolver, data_dir: "str | Path") -> str:
    """`content_source` for a resolver already built: the notes path when the build reads the notes alone, else
    `<data_dir>/content/` holding a copy of each file the build reads, refreshed now. The engine calls this with
    its own resolver (0.28.0: `kg_eval`, `kg_experiment`), so a measurement reads the path the command lines
    read."""
    pol = resolver.policy()
    built, _other = resolver._split()
    notes = resolver.notes_path() if pol.build_from_notes else None
    if not built:
        return str(notes) if notes else ""
    content = resolver.resolve()
    folder = Path(data_dir) / CONTENT_DIRNAME
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in content.texts.items():
        with open(folder / name, "w", encoding="utf-8", newline="") as f:   # the text as read, no newline translation
            f.write(text)
    return str(folder)


def main(argv: "list[str] | None" = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in ("graph", "data-dir", "source"):
        sys.stderr.write("usage: python -m kg_engine.paths graph|data-dir|source <project> [plugin_data] "
                         "[source_path]\n")
        return 2
    what, project = args[0], args[1]
    plugin_data = args[2] if len(args) > 2 else ""
    if what == "graph":
        out = str(graph_path(project, plugin_data))
    elif what == "data-dir":
        out = str(project_data_dir(project, plugin_data))
    else:
        out = content_source(project, plugin_data, args[3] if len(args) > 3 else os.environ.get("KG_SOURCE_PATH", ""))
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
