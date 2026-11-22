"""Single home for the engine's environment/config resolution rules — a stdlib-only LEAF module.

Imported by the engine (``server.py``), the installer (``bootstrap.py``), the PreToolUse hook
(``hooks/precontext.py``), and the optional lightrag arm — several of which run OUTSIDE the engine
venv, before any third-party dep exists, so this module must depend on NOTHING beyond the standard
library (the same constraint as ``atomicio``; ``kg_engine.__init__`` is import-light, so importing
this never pulls in the heavy engine). The JS twin of ``clean`` lives in
``scripts/_engine_resolve.mjs`` — the one declared cross-language mirror.

Until review-r5 these rules lived in five hand-synced copies with two different sentinel sets, and
the ``${...}`` placeholder filter (review-r4: opt-skips-placeholder-filter) had landed in only one
of them: the hook's ``metrics_mode`` read an unsubstituted ``${user_config.metrics_mode}`` as a real
value. Every consumer now resolves through here; the hook's two documented adaptations
(``plugin_data_fallback``, ``plugin_root``) are explicit keyword knobs at its call sites instead of
a forked copy of the rule.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

# The default engine data dirname under the project root — also encoded (as a documented mirror of
# this rule) in launch_server.mjs serverLogDir, which cannot import Python.
DATA_DIRNAME = ".kg-data"
# The derived layer's names under the data dir — hosted in this stdlib leaf so the PreToolUse hook's
# cheap index-exists pre-check (which runs on every Grep/Glob/Read and must NOT import the heavy
# projector) shares them with the projector/server/lightrag consumers (review-r5).
DERIVED_DIRNAME = "derived"
INDEX_DB_NAME = "index.sqlite"
# Where each project's own data lives inside the plugin's shared data dir (0.23.0): `<root>/projects/<key>/`.
PROJECTS_DIRNAME = "projects"


def clean(value: "str | None") -> str:
    """Canonical env-value cleaner: drop empty / whitespace-only values, strip a matched pair of
    surrounding quotes (below), drop unsubstituted ``${...}`` placeholders (Claude Code passes
    ``${user_config.*}`` through literally when the user never set the option), and the bare
    sentinels left by substituting an empty var into a ``${VAR}/.venv`` template. Mirrored by
    ``clean()`` in scripts/_engine_resolve.mjs; keep the two in lockstep."""
    if not value:
        return ""
    v = _dequote(value.strip())
    if not v or v.startswith("${") or v in ("/.venv", "/venv"):
        return ""
    return v


def _dequote(v: str) -> str:
    """Strip surrounding matched quote pairs (``"..."`` or ``'...'``), the way a shell would. A user
    who wraps ``source_path`` (or any path option) in quotes — or a host that hands us a JSON-quoted
    userConfig value — would otherwise leave literal quote characters *inside* the path, so
    ``Path('"C:\\\\x"')`` points nowhere and the engine silently degrades to an empty source. The
    settings UI's doubled backslashes are only a JSON-display artifact (the substituted env value
    carries single backslashes) — the quotes are the real breakage. We peel **repeatedly** so a
    double-wrapped value (``""C:\\\\x""``) collapses to the bare path, not a still-quoted ``"C:\\\\x"``;
    each pass drops ≥2 chars so it always terminates. Only symmetric pairs peel (a lone/interior/
    mismatched quote is left as part of the path). Mirrored by ``dequote()`` in
    scripts/_engine_resolve.mjs; keep the two in lockstep."""
    while len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v


def clean_env(key: str) -> "str | None":
    """Read one env var through ``clean``; None when unset/placeholder/sentinel."""
    return clean(os.environ.get(key)) or None


def plugin_option(name: str, default: "str | None" = None) -> "str | None":
    """A ``CLAUDE_PLUGIN_OPTION_<NAME>`` user-config read, through the SAME placeholder filter as
    every other env read (review-r4: opt-skips-placeholder-filter) — an unsubstituted
    ``${user_config.*}`` literal reads as unset, never as a real value."""
    return clean_env(f"CLAUDE_PLUGIN_OPTION_{name}") or default


def resolve_project(default: "str | None" = None) -> "str | None":
    """The project dir: ``KG_PROJECT_DIR`` (the .mcp.json override) wins over ``CLAUDE_PROJECT_DIR``,
    else ``default`` (the server passes ``os.getcwd()``; the hook passes its payload's ``cwd``,
    which may be absent — the hook then bails silently)."""
    return clean_env("KG_PROJECT_DIR") or clean_env("CLAUDE_PROJECT_DIR") or default


def resolve_data_dir(project: "str | Path", *, plugin_data_fallback: bool = False) -> Path:
    """The engine data dir (derived layer + server.log): ``KG_DATA`` if set, else
    ``<project>/.kg-data``. ``plugin_data_fallback`` inserts a ``CLAUDE_PLUGIN_DATA`` step between
    the two — the PreToolUse hook's documented adaptation: its env lacks the .mcp.json wiring that
    sets ``KG_DATA=${CLAUDE_PLUGIN_DATA}`` for the server, so it reads the source var directly.
    Both entry points land on the same dir whenever .mcp.json is intact."""
    data = clean_env("KG_DATA")
    if not data and plugin_data_fallback:
        data = clean_env("CLAUDE_PLUGIN_DATA")
    return Path(data) if data else Path(project) / DATA_DIRNAME


def project_key(project: "str | Path") -> str:
    """A stable folder name for one project inside the plugin's shared data dir (0.23.0): its folder's name,
    folded to lower-case ``[a-z0-9-]`` and cut to 40 characters, then 12 hex digits of the sha256 of its
    absolute, case-normalized path. The server and the PreToolUse hook get the same project dir from Claude
    Code (``CLAUDE_PROJECT_DIR``) and fold it the same way, so they meet on one folder."""
    norm = os.path.normcase(os.path.abspath(str(project)))
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
    name = re.sub(r"[^a-z0-9]+", "-", Path(norm).name.lower()).strip("-")[:40] or "project"
    return f"{name}-{digest}"


def resolve_project_data_dir(project: "str | Path", *, plugin_data_fallback: bool = False) -> Path:
    """The data dir of ONE project's derived layer (0.23.0): ``<root>/projects/<project_key>`` when the root is
    the plugin's shared data dir (``KG_DATA``, or ``CLAUDE_PLUGIN_DATA`` for the hook, as in
    ``resolve_data_dir``), else ``<project>/.kg-data``, which is the project's own already. Claude Code keys
    ``CLAUDE_PLUGIN_DATA`` by plugin, not by project: through 0.22.4 every project shared one derived layer, so
    opening another project rebuilt the index, one project's graph view replaced the other's, and the
    /burgess:kg-generate ledger kept one project's generations whichever project ran next. The server log
    stays at the root (``resolve_data_dir``), where the launcher writes it too."""
    data = clean_env("KG_DATA")
    if not data and plugin_data_fallback:
        data = clean_env("CLAUDE_PLUGIN_DATA")
    if not data:
        return Path(project) / DATA_DIRNAME
    return Path(data) / PROJECTS_DIRNAME / project_key(project)


def resolve_source(project: "str | Path", *, explicit: "str | None" = None) -> "str | None":
    """The configured source: an explicit override (CLI flag) wins, then the ``source_path`` user
    config, then ``KG_SOURCE_PATH``, then the documented default — the bundled
    ``examples/source.md`` when it exists under the project — else None (engine degrades to an
    empty source)."""
    src = explicit or plugin_option("SOURCE_PATH") or clean_env("KG_SOURCE_PATH")
    if src:
        return src
    guess = Path(project) / "examples" / "source.md"
    return str(guess) if guess.exists() else None


def resolve_pack_path(project: "str | Path", *, explicit: "str | None" = None,
                      plugin_root: "str | None" = None) -> "str | None":
    """The domain pack: an explicit override wins, then ``KG_PACK_PATH`` (.mcp.json points it at the
    plugin-root pack), then — only when ``plugin_root`` is supplied — ``<plugin_root>/pack/pack.yaml``,
    then ``<project>/pack/pack.yaml``, else None. ``plugin_root`` is the hook's documented
    adaptation: on an installed plugin the project dir has no pack and the hook's env lacks the
    .mcp.json ``KG_PACK_PATH`` wiring, so a project-only lookup would wire EMPTY specificity seeds
    into a projection the server then serves as fresh (finding: precontext-bypasses-facade)."""
    pack = explicit or clean_env("KG_PACK_PATH")
    if pack:
        return pack
    for base in (plugin_root, str(project)):
        if base:
            guess = Path(base) / "pack" / "pack.yaml"
            if guess.exists():
                return str(guess)
    return None
