"""0.19.5: /burgess:kg-diverge reads plugin files by path, resumes from recall, and stops a false cold-start
collapse under the static embedder; comparisons and repeats are described as they work.

Field session (Windows, 2026-11-19, session 6cedf547, 48 ideas over 3 rounds):

- The command named its references as `references/operators.md` and its templates as `pack/domains/...`,
  paths that lead nowhere from the project. The agent looked for them with find, cat and sed, and every
  Bash read outside the project waited for the user's approval: seven reads, 96 minutes, most of it before
  the first round. (The first field session found the same files with Glob and Read, which ask nothing.)
  After a compaction it read `axes.json` and `pins.json` with Bash too.
- The first batch scored a mean cosine of 0.5807 against the cold-start threshold of 0.55, which was tuned
  on the hash fixture. The session regenerated and told the user the twelve ideas "spoke of mutation with
  the same words". They were twelve distinct mechanisms. The fourth batch scored 0.581 and passed, because
  by then the calibrated limit was 0.69.
- The session said a lost comparison came back because "comparisons weigh little in the selection". The
  slate and the parents do not read comparisons at all. It also suggested discarding ideas because they
  kept returning to the slate; a discard is negative memory, and one of them was a parent of two later ideas.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pytest

from kg_engine.divergence import config, monitor, pipeline, session as session_mod
from kg_engine.divergence.config import ConfigError, EngineConfig
from kg_engine.divergence.embed import Embedder

REPO = Path(__file__).resolve().parents[1]
DIVERGE = (REPO / "commands" / "kg-diverge.md").read_text(encoding="utf-8")
SERVER = REPO / "scripts" / "kg_engine" / "server.py"
ROOT = "${CLAUDE_PLUGIN_ROOT}"


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("KG_DIVERGE_EMBEDDER", "hash")
    monkeypatch.delenv("KG_PROJECT_DIR", raising=False)
    monkeypatch.setenv("KG_DIVERGE_HOME", str(tmp_path / "diverge-home"))


# --------------------------------------------------------------------------- #
# 1. plugin files by path, state from the engine
# --------------------------------------------------------------------------- #
def test_every_reference_and_template_the_command_names_is_a_plugin_path_that_exists():
    flat = _flat(DIVERGE)
    # no bare relative path is left for the agent to search for
    assert re.findall(r"(?<![/\w])references/\w+\.md", DIVERGE) == []
    assert re.findall(r"(?<![/\w}])pack/domains", DIVERGE) == []
    for name in ("operators.md", "axis_inference.md", "judge_rubric.md"):
        assert (REPO / "skills" / "burgess" / "references" / name).is_file()
        assert f"{ROOT}/skills/burgess/references/{name}" in flat
    assert f"{ROOT}/pack/domains/" in flat and (REPO / "pack" / "domains" / "generic.yaml").is_file()
    assert f"{ROOT}/pack/domains/examples/" in flat
    assert (REPO / "pack" / "domains" / "examples" / "research_hypotheses.yaml").is_file()


def test_the_command_says_read_tool_only_and_no_state_files():
    flat = _flat(DIVERGE)
    assert "**Files: Read tool only, never Bash.**" in flat
    assert "Open them with the Read tool at those paths; there is nothing to search for." in flat
    assert "Never read `.kg/diverge/` files." in flat
    # the Read grant is already the command's; nothing here needs Bash
    front = DIVERGE.split("---", 2)[1]
    assert "allowed-tools: Read," in front and "Bash" not in front


def test_the_command_tells_how_to_resume_after_a_compaction():
    flat = _flat(DIVERGE)
    start = flat.index("**After a compaction.**")
    para = flat[start:start + 700]
    assert "call `kg_diverge_recall(project)` before anything else" in para
    assert "Do not call `kg_diverge_init` with another session id, which would wipe the archive" in para
    assert flat.index("8. **Record & continue.**") < start < flat.index("9. **React to the monitor**")


def _template(name: str):
    return config.resolve_axes_source(name)


def test_init_returns_the_resolved_axes_so_no_template_is_opened():
    out = pipeline.init_project("brief", _template("research_hypotheses"), seed=1119, session="sess-a")
    assert out["axes"] == config.load_all(_template("research_hypotheses"))[0].to_dict()["axes"]
    names = [a["name"] for a in out["axes"]]
    assert names == ["locus", "population", "time_horizon", "testability", "causal_mechanism"]
    assert [a for a in out["axes"] if a.get("primary_novelty")] == [
        {"name": "causal_mechanism", "type": "open", "primary_novelty": True}]
    assert out["unit_of_generation"] == "hypothesis"
    assert out["candidates_per_generation"] == 12
    # and an inline dict resolves the same way
    inline = {"domain": "d", "unit_of_generation": "idea", "candidates_per_generation": 5,
              "axes": [{"name": "form", "type": "categorical"},
                       {"name": "mechanism", "type": "open", "primary_novelty": True}]}
    out2 = pipeline.init_project("brief2", inline, session="sess-b")
    assert [a["name"] for a in out2["axes"]] == ["form", "mechanism"]
    assert out2["candidates_per_generation"] == 5


def test_recall_returns_the_session_context_a_compacted_chat_needs():
    init = pipeline.init_project("brief", _template("research_hypotheses"), seed=1119, session="sess-q7mz")
    rec = pipeline.recall("brief")
    assert rec["session_id"] == "sess-q7mz"
    assert rec["seed"] == 1119
    assert rec["axes"] == init["axes"]
    assert rec["unit_of_generation"] == "hypothesis"
    assert rec["candidates_per_generation"] == 12
    # the preference memory is still there
    assert {"domain", "preferences", "pins", "discards", "summary"} <= set(rec)
    # resuming with the recalled id wipes nothing
    again = pipeline.init_project("brief", _template("research_hypotheses"), seed=1119,
                                  session=rec["session_id"])
    assert again["new_session"] is False


def test_recall_on_a_project_never_inited_leaves_the_context_out():
    rec = pipeline.recall("never-inited")
    assert not {"session_id", "seed", "axes", "unit_of_generation", "candidates_per_generation"} & set(rec)
    assert rec["pins"] == [] and rec["discards"] == []


def _tool_doc(name: str) -> str:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name and any(
                ast.unparse(d).startswith("mcp.tool") for d in node.decorator_list):
            return _flat(ast.get_docstring(node) or "")
    raise AssertionError(f"no MCP tool {name}")


def test_the_tool_descriptions_say_where_the_axes_and_the_session_context_come_from():
    assert "the resolved `axes`" in _tool_doc("kg_diverge_init")
    assert "there is no template file to open for them" in _tool_doc("kg_diverge_init")
    recall = _tool_doc("kg_diverge_recall")
    assert "`session_id`" in recall and "`seed`" in recall and "`axes`" in recall
    assert "never read `.kg/diverge/` files for it" in recall


# --------------------------------------------------------------------------- #
# 2. the cold-start similarity threshold is the embedder's own
# --------------------------------------------------------------------------- #
def test_each_embedder_family_has_its_cold_start_threshold():
    assert monitor.default_cos_threshold("hash") == 0.55 == monitor.DEFAULT_COS_THRESHOLD
    assert monitor.default_cos_threshold("static") == 0.67
    # an unmeasured family keeps the old default
    assert monitor.default_cos_threshold("local") == monitor.DEFAULT_COS_THRESHOLD
    assert monitor.default_cos_threshold("anything-else") == monitor.DEFAULT_COS_THRESHOLD


def test_the_engine_config_leaves_the_threshold_to_the_embedder_unless_pinned():
    assert EngineConfig().monitor_cos_threshold is None
    assert config.load_engine_config({}).monitor_cos_threshold is None
    assert config.load_engine_config({"engine": {"monitor_cos_threshold": None}}).monitor_cos_threshold is None
    assert config.load_engine_config({"engine": {"monitor_cos_threshold": 0.6}}).monitor_cos_threshold == 0.6
    with pytest.raises(ConfigError):
        config.load_engine_config({"engine": {"monitor_cos_threshold": 1.5}})
    with pytest.raises(ConfigError):
        config.load_engine_config({"engine": {"monitor_cos_threshold": "high"}})


def _vecs_with_mean_cosine(c: float, n: int = 12, d: int = 64) -> np.ndarray:
    """n unit vectors whose every pairwise cosine is exactly c: sqrt(c)*e0 + sqrt(1-c)*e_i."""
    v = np.zeros((n, d))
    v[:, 0] = np.sqrt(c)
    for i in range(n):
        v[i, i + 1] = np.sqrt(1 - c)
    return v


def test_the_field_first_batch_no_longer_flags_under_static_and_still_does_under_hash():
    vecs = _vecs_with_mean_cosine(0.5807)
    counts = [1] * 12
    static = pipeline._evaluate_monitor(vecs, counts, [], EngineConfig(), "static")
    assert static["mean_cosine"] == pytest.approx(0.5807, abs=1e-4)
    assert static["calibrated"] is False and static["cos_limit"] == 0.67
    assert static["collapsing"] is False and static["too_similar"] is False
    hashed = pipeline._evaluate_monitor(vecs, counts, [], EngineConfig(), "hash")
    assert hashed["cos_limit"] == 0.55 and hashed["collapsing"] is True
    # a pinned threshold wins over the family default
    pinned = pipeline._evaluate_monitor(vecs, counts, [], EngineConfig(monitor_cos_threshold=0.55), "static")
    assert pinned["cos_limit"] == 0.55 and pinned["collapsing"] is True


def test_a_template_like_collapse_still_flags_at_cold_start_under_static():
    # the selftest's samey fixtures score 0.89 under potion (measured 2026-11-20)
    mon = pipeline._evaluate_monitor(_vecs_with_mean_cosine(0.89), [1] * 12, [], EngineConfig(), "static")
    assert mon["collapsing"] is True and mon["too_similar"] is True


def test_the_calibrated_rule_does_not_depend_on_the_embedder():
    vecs = _vecs_with_mean_cosine(0.60)
    for name in ("static", "hash"):
        mon = pipeline._evaluate_monitor(vecs, [1] * 12, [0.50, 0.52], EngineConfig(), name)
        assert mon["calibrated"] is True and mon["cos_limit"] == pytest.approx(0.66)
        assert mon["collapsing"] is False


class _FixedCosine(Embedder):
    """Every distinct text gets its own basis vector over a shared component: pairwise cosine is exactly c."""
    dim = 128

    def __init__(self, name: str, c: float):
        self.name = name
        self.c = c
        self.index: dict[str, int] = {}

    def _embed_raw(self, texts):
        out = np.zeros((len(texts), self.dim))
        for row, t in enumerate(texts):
            i = self.index.setdefault(t, len(self.index) + 1)
            out[row, 0] = np.sqrt(self.c)
            out[row, i] = np.sqrt(1 - self.c)
        return out


AXES = {"domain": "d", "unit_of_generation": "idea", "candidates_per_generation": 12,
        "axes": [{"name": "form", "type": "categorical"},
                 {"name": "mechanism", "type": "open", "primary_novelty": True}]}


def _ingest_first_batch(monkeypatch, project: str, embedder_name: str, axes) -> dict:
    """A first generation of 12 distinct ideas at the field's mean cosine, under a named embedder family."""
    fake = _FixedCosine(embedder_name, 0.5807)
    monkeypatch.setattr(session_mod, "get_embedder", lambda *a, **k: fake)
    pipeline.init_project(project, axes, session="s1")
    cands = [{"id": f"c1{chr(97 + i)}", "text": f"idea {i}",
              "descriptor": {"form": f"f{i}", "mechanism": f"mechanism {i}"}} for i in range(12)]
    return pipeline.ingest(project, cands, axes)["monitor"]


def test_ingest_judges_a_first_batch_by_its_embedders_threshold(monkeypatch):
    mon = _ingest_first_batch(monkeypatch, "p-static", "static", AXES)
    assert mon["mean_cosine"] == pytest.approx(0.5807, abs=1e-4)
    assert mon["calibrated"] is False
    assert mon["cos_limit"] == 0.67 and mon["collapsing"] is False
    mon = _ingest_first_batch(monkeypatch, "p-hash", "hash", AXES)
    assert mon["cos_limit"] == 0.55 and mon["collapsing"] is True
    # a domain that pins the threshold keeps it
    pinned = dict(AXES, engine={"monitor_cos_threshold": 0.55})
    mon = _ingest_first_batch(monkeypatch, "p-pinned", "static", pinned)
    assert mon["cos_limit"] == 0.55 and mon["collapsing"] is True


# --------------------------------------------------------------------------- #
# 3. comparisons and repeats, as they work
# --------------------------------------------------------------------------- #
def test_the_remember_description_says_comparisons_do_not_move_the_slate():
    doc = _tool_doc("kg_diverge_remember")
    assert "low-weight" not in doc
    assert "The engine does NOT use comparisons to pick the slate or the parents" in doc
    assert "Never tell the user a comparison moved the slate." in doc


def test_the_command_explains_comparisons_and_earlier_ideas_on_the_slate():
    flat = _flat(DIVERGE)
    assert "The answers do not move the slate or the parents" in flat
    assert "never explain it as comparisons weighing little, because the slate does not read them at all" in flat
    assert "**Earlier ideas on the slate.** The engine picks the slate from every idea in the archive" in flat
    assert "A repeat is no reason to discard" in flat
    assert "never as a way to stop one from coming back" in flat
    assert flat.index("**Earlier ideas on the slate.**") < flat.index("**Then the rest of this round.**")


def _slate_after_two_batches(project: str, compare: bool) -> list[str]:
    pipeline.init_project(project, AXES, session="s1")
    first = [{"id": f"a{i}", "text": f"first batch idea {i} about {w}",
              "descriptor": {"form": f"f{i % 4}", "mechanism": f"{w} mechanism"}}
             for i, w in enumerate(["tides", "orchards", "ledgers", "kites", "prisms", "anvils"])]
    out = pipeline.ingest(project, first, AXES)
    if compare:
        loser, winner = out["slate_ids"][0], out["slate_ids"][1]
        pipeline.remember(project, {"type": "comparison", "winner": winner, "loser": loser})
    second = [{"id": f"b{i}", "text": f"second batch idea {i} on {w}",
               "descriptor": {"form": f"f{(i + 1) % 4}", "mechanism": f"{w} route"}}
              for i, w in enumerate(["beacons", "mosaics", "embers", "compasses", "signals", "lanterns"])]
    return pipeline.ingest(project, second, AXES)["slate_ids"]


def test_a_comparison_does_not_change_the_next_slate():
    # pins the claim the command and the tool description now make
    assert _slate_after_two_batches("no-compare", False) == _slate_after_two_batches("with-compare", True)
