"""End-of-session export: every idea of a brief's current session in one Markdown file (0.19.6).

The user keeps the ideas of a /burgess:kg-diverge session as a file. Until 0.19.6 no tool returned
them, so the agent built the file itself. In the 2026-11-19 field run it read the session store and
its own transcript with Bash scripts, recovered the explanations of rounds lost to compaction from
that transcript, and generated the Markdown with a 37 KB script: ten permission prompts, about two
hours of waiting. Here the engine writes the file from its own state:

* each idea's text as the engine kept it, and the ``explanation`` the agent ingested it with;
* its descriptor, its operator and parents;
* the batch it arrived in and the batches whose slate showed it (``pipeline._mark_batch``);
* what the user did with it: pinned, discarded, compared, materialized into the graph.

Where the file goes is the safety property. It is written under the brief's own state directory,
``<project>/.kg/diverge/<brief>/``, never in the project root. In the field the project folder IS
the source folder (``source_path``), and a directory source is every ``.md`` at its top level
(``sources.SourceSet.resolve``): an export written there would be read by the next
/burgess:kg-build as a source document, and the session's ideas would come back as spans to ground
claims on — hypotheses laundered into evidence. The dot-directory is skipped by both the
directory and the glob resolution. The engine also never writes where the agent asks: a tool that
wrote any path would bypass the permission check every other file write passes through. Copying
the file elsewhere is the user's call, through a tool that asks.

Nothing reads the file back, so it cannot carry geometry across sessions (I10), and the module
imports only its siblings and ``atomicio`` (I3).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..atomicio import atomic_write_text
from . import originality
from .config import ConfigError
from .session import Session
from .state import State, _path_slug

# How many ideas the export names as closest to each held-out cliché (0.20.0).
CLOSEST_PER_CLICHE = 3


def export_path(state: State, session_id: str) -> Path:
    """``<brief state dir>/ideas-<brief>[-<session>].md``: one file per session, so exporting again
    in the same session replaces it and a later session never overwrites an earlier one."""
    name = f"ideas-{state.root.name}"
    if session_id:
        name += f"-{_path_slug(session_id)}"
    return state.root / f"{name}.md"


def _fmt_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{round(float(value), 2):g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt_value(v) for v in value)
    return str(value)


def _axis_label(axis: dict[str, Any]) -> str:
    name = str(axis.get("name", "?"))
    if axis.get("type") == "open":
        return f"{name} (open)"
    rng = axis.get("range")
    if axis.get("type") == "continuous" and isinstance(rng, (list, tuple)) and len(rng) == 2:
        return f"{name} ({_fmt_value(rng[0])}–{_fmt_value(rng[1])})"
    return name


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _descriptor_lines(descriptor: dict[str, Any], axes: list[dict[str, Any]]) -> list[str]:
    """The open axis (the mechanism carrier) on its own line, then the other axes in their declared
    order, then any descriptor key the axes do not name."""
    names = [str(a.get("name")) for a in axes]
    open_names = [str(a.get("name")) for a in axes
                  if a.get("type") == "open" or a.get("primary_novelty")]
    lines = []
    for name in open_names:
        if descriptor.get(name) not in (None, ""):
            lines.append(f"- {name}: {_fmt_value(descriptor[name])}")
    rest = [n for n in names if n not in open_names] + [k for k in descriptor if k not in names]
    parts = [f"{n}: {_fmt_value(descriptor[n])}" for n in rest
             if n in descriptor and descriptor[n] not in (None, "")]
    if parts:
        lines.append("- " + " · ".join(parts))
    return lines


def _genealogy_line(genealogy: dict[str, Any]) -> str | None:
    op = genealogy.get("operator_id") or genealogy.get("operator")
    parents = [str(p) for p in (genealogy.get("parents") or []) if p]
    parts = []
    if op:
        parts.append(f"operator: {op}")
    if parents:
        parts.append(f"parents: {', '.join(parents)}")
    return ("- " + " · ".join(parts)) if parts else None


def _status_line(rec: dict[str, Any], pinned: bool, discarded: bool, beat: list[str],
                 lost_to: list[str], nodes: list[str]) -> str | None:
    parts = []
    shown = [int(b) for b in rec.get("slated_in") or []]
    if shown:
        parts.append(f"on the slate in batch{'es' if len(shown) > 1 else ''} "
                     f"{', '.join(str(b) for b in shown)}")
    elif "batch" in rec:
        # Only a record that carries batch numbers can say it was never slated; one ingested
        # before 0.19.6 does not know.
        parts.append("never on the slate")
    if pinned:
        parts.append("pinned")
    if discarded:
        parts.append("discarded")
    if beat:
        parts.append(f"beat {', '.join(beat)}")
    if lost_to:
        parts.append(f"lost to {', '.join(lost_to)}")
    if nodes:
        parts.append(f"in the graph as {', '.join(f'`{n}`' for n in nodes)}")
    return ("- " + " · ".join(parts)) if parts else None


def _cliche_lines(cliches: list[dict[str, Any]]) -> list[str]:
    """The ``## Clichés`` section (0.20.0): every mapped cliché with its role, the ideas closest to
    each held-out one, and the graph node a materialized one became. Empty when none was mapped."""
    if not cliches:
        return []
    out = ["## Clichés", "",
           "The obvious answers mapped before generating. The ideas were generated away from the "
           "avoided ones. The set-aside ones were kept out of view, to check the ideas against at the "
           "end: for each, the closest ideas and their cosine similarity in this session's embedding "
           "space, an advisory reading that ranks nothing.", ""]
    for c in cliches:
        role = "avoided" if c.get("role") == "avoided" else "set aside"
        line = f"- **{c.get('id', '?')}** ({role}): {str(c.get('text', '')).strip()}"
        closest = c.get("closest")
        if c.get("role") == "held_out" and closest:
            line += " · closest ideas: " + ", ".join(
                f"{x['id']} ({_fmt_value(x['similarity'])})" for x in closest)
        elif c.get("role") == "held_out" and closest is not None:
            line += " · closest ideas: not measured (no comparable embeddings)"
        if c.get("node"):
            line += f" · in the graph as `{c['node']}`"
        out.append(line)
    out.append("")
    return out


def _held_out_closest(sess: Session, meta: dict[str, Any], cliches: list[dict[str, Any]],
                      embeddings: dict[str, list[float]], ids: list[str]) -> dict[str, list]:
    """The ideas closest to each held-out cliché, ``{cliché id: [{"id", "similarity"}, ...]}``.

    Only the held-out clichés are measured: the avoided ones steered the generation, so a distance
    to them would only grade the steering (never validate against O_train). The ideas are this
    session's stored embeddings; the clichés are embedded with the same embedder. An embedder the
    session did not use, or one that fails to load, gives ``[]``: the reading is advisory, and the
    export never fails for it."""
    held = [c for c in cliches if c.get("role") == "held_out"]
    if not held:
        return {}
    empty = {c["id"]: [] for c in held}
    try:
        if meta.get("embedder") and meta["embedder"] != sess.embedder.name:
            return empty
        have = [i for i in ids if i in embeddings]
        if not have:
            return empty
        vecs = sess.embedder.embed([c["text"] for c in held])
        near = originality.nearest_ideas(vecs, [embeddings[i] for i in have], have,
                                         k=CLOSEST_PER_CLICHE)
    except Exception:  # noqa: BLE001 — advisory reading; a missing model never fails the export
        return empty
    return {c["id"]: n for c, n in zip(held, near)}


def render(*, project: str, brief: str, records: list[dict[str, Any]],
           axes: list[dict[str, Any]], session_id: str, seed: Any, pins: list[str],
           discards: list[str], comparisons: list[dict[str, Any]],
           materialized: dict[str, Any], exported_at: str,
           cliches: list[dict[str, Any]] | None = None) -> str:
    """The Markdown text of an export. Pure: the caller reads the state and writes the file."""
    ids = [r["id"] for r in records]
    here = set(ids)
    pinned_here = [p for p in pins if p in here]
    pinned_elsewhere = [p for p in pins if p not in here]
    discarded_here = [d for d in discards if d in here]
    comps = [c for c in comparisons
             if c.get("winner") in here or c.get("loser") in here]
    beat: dict[str, list[str]] = {}
    lost_to: dict[str, list[str]] = {}
    for c in comps:
        w, lo = str(c.get("winner", "")), str(c.get("loser", ""))
        if lo not in beat.setdefault(w, []):  # a pair answered twice is named once
            beat[w].append(lo)
        if w not in lost_to.setdefault(lo, []):
            lost_to[lo].append(w)
    batches = sorted({int(r["batch"]) for r in records if "batch" in r})

    out: list[str] = [f"# Ideas: {project}", ""]
    if brief.strip():
        out += [f"> {line}" if line.strip() else ">" for line in brief.strip().splitlines()]
        out.append("")
    summary = _plural(len(records), "idea", "ideas")
    if batches:
        summary += f" in {_plural(len(batches), 'batch', 'batches')}"
    meta_bits = [summary]
    if session_id:
        meta_bits.append(f"session `{session_id}`")
    if seed is not None:
        meta_bits.append(f"seed {seed}")
    meta_bits.append(f"exported {exported_at}")
    out += [" · ".join(meta_bits), ""]
    if axes:
        out += ["Axes: " + ", ".join(_axis_label(a) for a in axes), ""]
    choice = [f"Pinned: {', '.join(pinned_here) or 'none'}",
              f"Discarded: {', '.join(discarded_here) or 'none'}",
              f"Comparisons: {len(comps)}"]
    out.append(" · ".join(choice))
    if pinned_elsewhere:
        one = len(pinned_elsewhere) == 1
        out.append(f"(Pinned in an earlier session and not in this file, because "
                   f"{'its record' if one else 'their records'} ended with that session: "
                   f"{', '.join(pinned_elsewhere)}.)")
    out += ["", "Each idea: its text as the engine kept it, the explanation it was presented with, "
                "its descriptor, how it was made, and what was done with it. A batch is one ingest; "
                "a round that was regenerated is two batches.", ""]
    out += _cliche_lines(cliches or [])

    groups: list[tuple[str, list[dict[str, Any]]]] = []
    undated = [r for r in records if "batch" not in r]
    if undated:
        groups.append(("Earlier ideas (ingested before batches were numbered)", undated))
    for b in batches:
        groups.append((f"Batch {b}", [r for r in records if r.get("batch") == b]))

    for title, recs in groups:
        out += [f"## {title}", ""]
        for r in recs:
            cid = r["id"]
            marks = [m for m, on in (("pinned", cid in pinned_here),
                                     ("discarded", cid in discarded_here)) if on]
            out.append(f"### {cid}" + (f" ({', '.join(marks)})" if marks else ""))
            out.append("")
            out.append(str(r.get("text", "")).strip())
            out.append("")
            explanation = str(r.get("explanation", "") or "").strip()
            if explanation:
                out.append(explanation)
                out.append("")
            lines = _descriptor_lines(r.get("descriptor") or {}, axes)
            gl = _genealogy_line(r.get("genealogy") or {})
            if gl:
                lines.append(gl)
            entry = materialized.get(cid) if isinstance(materialized, dict) else None
            nodes = list(entry.get("nodes") or []) if isinstance(entry, dict) else []
            sl = _status_line(r, cid in pinned_here, cid in discarded_here,
                              beat.get(cid, []), lost_to.get(cid, []), nodes)
            if sl:
                lines.append(sl)
            if lines:
                out += lines
                out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def export_ideas(project: str, brief: str = "", home: Path | None = None,
                 now: datetime | None = None) -> dict[str, Any]:
    """Write every idea of ``project``'s current session to its export file; return where and what.

    Raises :class:`ConfigError` when the brief has no ideas in its current session: never inited,
    or a new session id wiped the previous one's records (I10). Pins of an earlier session keep
    only their ids, so the file names them without text."""
    if brief is not None and not isinstance(brief, str):
        raise ConfigError("brief must be a string")
    sess = Session(project, home=home)
    state = sess.state
    if not state.exists():
        raise ConfigError(f"project {project!r} has no divergence state: call kg_diverge_init and "
                          f"ingest ideas first")
    with state.project_read_lock():
        store = state.read_candidates() or {}
        domain = sess.domain
        pins = list(state.read_pins(domain))
        discards = list(state.read_discards(domain))
        comparisons = list(state.read_comparisons(domain))
        materialized = state.read_materialized()
        meta = state.read_meta()
        session_id = str(state.read_session().get("session_id") or "")
        axes_doc = state.read_axes() or {}
        cliches = state.read_cliches()
        embeddings = state.read_embeddings() if cliches else {}
    records = [dict(rec, id=str(rec.get("id") or cid)) for cid, rec in store.items()
               if isinstance(rec, dict)]
    if not records:
        raise ConfigError(f"project {project!r} has no ideas in its current session to export"
                          + (f" (session {session_id!r})" if session_id else ""))
    axes = [a for a in (axes_doc.get("axes") or []) if isinstance(a, dict)]
    closest = _held_out_closest(sess, meta, cliches, embeddings, [r["id"] for r in records])
    in_graph = materialized.get("_cliches") if isinstance(materialized, dict) else None
    in_graph = in_graph if isinstance(in_graph, dict) else {}
    cliche_view: list[dict[str, Any]] = []
    for c in cliches:
        item = {"id": c.get("id"), "text": c.get("text"), "role": c.get("role")}
        if c.get("role") == "held_out":
            item["closest"] = closest.get(c.get("id"), [])
        entry = in_graph.get(c.get("id"))
        nodes = list(entry.get("nodes") or []) if isinstance(entry, dict) else []
        if nodes:
            item["node"] = nodes[0]
        cliche_view.append(item)
    stamp = (now or datetime.now().astimezone()).isoformat(timespec="minutes")
    text = render(project=project, brief=brief or "", records=records, axes=axes,
                  session_id=session_id, seed=meta.get("seed"), pins=pins, discards=discards,
                  comparisons=comparisons, materialized=materialized, exported_at=stamp,
                  cliches=cliche_view)
    path = export_path(state, session_id)
    atomic_write_text(path, text)
    here = {r["id"] for r in records}
    return {
        "ok": True,
        "path": str(path.resolve()),
        "ideas": len(records),
        "batches": len({r["batch"] for r in records if "batch" in r}),
        "pinned": [p for p in pins if p in here],
        "discarded": [d for d in discards if d in here],
        "comparisons": sum(1 for c in comparisons
                           if c.get("winner") in here or c.get("loser") in here),
        "unexplained": [r["id"] for r in records if not str(r.get("explanation") or "").strip()],
        "cliches": cliche_view,
        "session_id": session_id,
        "bytes": len(text.encode("utf-8")),
    }
