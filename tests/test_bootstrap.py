"""Hermetic tests for the self-provisioning bootstrap (scripts/bootstrap.py).

These exercise only the pure logic — path resolution, the idempotency stamp, the
readiness check, the concurrency lock, and the failure-cleanup contract. No venv is
created and nothing is installed, so the suite stays offline.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kg_engine import dirlock  # the lock's home since review-r5 (bootstrap wraps it)

_BOOT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py"


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("kg_bootstrap", _BOOT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bootstrap = _load_bootstrap()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Drop any inherited provisioning env so resolution is deterministic."""
    for var in ("KG_ENGINE_VENV", "CLAUDE_PLUGIN_DATA"):
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------- #
# _clean / resolve_venv_dir
# --------------------------------------------------------------------------- #
def test_clean_drops_empty_and_unsubstituted():
    assert bootstrap._clean("") == ""
    assert bootstrap._clean(None) == ""
    assert bootstrap._clean("   ") == ""
    # an unsubstituted ${VAR} (e.g. CLAUDE_PLUGIN_DATA unset in dev) must not be used
    assert bootstrap._clean("${CLAUDE_PLUGIN_DATA}/.venv".split("/")[0]) == ""
    # the bare-substitution sentinels (KG_ENGINE_VENV / DATA empty -> "/.venv" | "/venv")
    assert bootstrap._clean("/.venv") == ""
    assert bootstrap._clean("/venv") == ""
    assert bootstrap._clean("  /real/path ") == "/real/path"


def test_resolve_priority_explicit_arg_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_ENGINE_VENV", str(tmp_path / "env"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    got = bootstrap.resolve_venv_dir(str(tmp_path / "explicit"))
    assert got == (tmp_path / "explicit").resolve()


def test_resolve_priority_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_ENGINE_VENV", str(tmp_path / "env"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    assert bootstrap.resolve_venv_dir(None) == (tmp_path / "env").resolve()


def test_resolve_priority_plugin_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    assert bootstrap.resolve_venv_dir(None) == (tmp_path / "data" / ".venv").resolve()


def test_resolve_dev_fallback():
    # No env, no arg, and an empty/unsubstituted --venv all fall back to the dev tree
    # (the same <repo>/.venv that `uv sync` from the repo root builds).
    expected = (bootstrap.REPO_ROOT / ".venv").resolve()
    assert bootstrap.resolve_venv_dir(None) == expected
    assert bootstrap.resolve_venv_dir("") == expected
    assert bootstrap.resolve_venv_dir("/.venv") == expected


def test_venv_python_matches_os(tmp_path):
    py = bootstrap.venv_python(tmp_path)
    if os.name == "nt":
        assert py == tmp_path / "Scripts" / "python.exe"
    else:
        assert py == tmp_path / "bin" / "python"


# --------------------------------------------------------------------------- #
# compute_stamp
# --------------------------------------------------------------------------- #
def test_compute_stamp_is_deterministic():
    assert bootstrap.compute_stamp() == bootstrap.compute_stamp()


def test_compute_stamp_reacts_to_pyproject(tmp_path, monkeypatch):
    # A plugin update that changes pyproject.toml (the dependency source of truth) must
    # change the stamp and so force a rebuild.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\ndependencies = ['a']\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    s1 = bootstrap.compute_stamp()
    assert s1 == bootstrap.compute_stamp()
    pp.write_text("[project]\ndependencies = ['a', 'b']\n", encoding="utf-8")
    assert bootstrap.compute_stamp() != s1


def test_compute_stamp_reacts_to_interpreter_identity(tmp_path, monkeypatch):
    # F22: the venv's compiled wheels (pydantic-core, igraph, leidenalg) are ABI-bound to
    # the interpreter that built them. A same-path interpreter swap that leaves pyproject
    # UNTOUCHED (unversioned stdlib-venv symlink re-pointed, pyenv re-point, moved arch)
    # must still move the stamp so the venv rebuilds clean instead of importing an
    # ABI-mismatched wheel and crashing. So minor version, sys.platform and the machine
    # arch are all folded into the stamp.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\ndependencies = ['a']\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    base = bootstrap.compute_stamp()

    # A python minor bump (3.11 -> 3.12) with the same pyproject must change the stamp.
    class _VI(tuple):
        @property
        def major(self):  # not used by compute_stamp, kept for realism
            return self[0]

        @property
        def minor(self):
            return self[1]

    monkeypatch.setattr(bootstrap.sys, "version_info", _VI((3, 99, 0, "final", 0)))
    bumped_minor = bootstrap.compute_stamp()
    assert bumped_minor != base

    # An arch move (platform.machine) with the same pyproject + interpreter must too.
    monkeypatch.setattr(bootstrap.sys, "version_info", _VI((3, 99, 0, "final", 0)))
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "definitely-not-this-arch")
    bumped_arch = bootstrap.compute_stamp()
    assert bumped_arch != bumped_minor

    # A platform change (sys.platform: linux -> win32) must too.
    monkeypatch.setattr(bootstrap.sys, "version_info", _VI((3, 99, 0, "final", 0)))
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "definitely-not-this-arch")
    monkeypatch.setattr(bootstrap.sys, "platform", "some-other-os")
    bumped_platform = bootstrap.compute_stamp()
    assert bumped_platform != bumped_arch


def test_compute_stamp_keys_on_explicit_venv_interpreter_identity():
    """review-M7: the stamp keys on the VENV interpreter's identity passed in, not the running one — so a
    different bootstrapping/checking interpreter computes the SAME stamp the build wrote. Distinct
    identities give distinct stamps; the same identity is stable; no-arg falls back to the running one."""
    a = bootstrap.compute_stamp("3.12\0linux\0x86_64")
    b = bootstrap.compute_stamp("3.13\0linux\0x86_64")
    assert a != b
    assert a == bootstrap.compute_stamp("3.12\0linux\0x86_64")
    assert bootstrap.compute_stamp() == bootstrap.compute_stamp(bootstrap._running_identity())


# --------------------------------------------------------------------------- #
# is_ready
# --------------------------------------------------------------------------- #
def _fake_venv(venv_dir: Path, stamp: str) -> None:
    py = bootstrap.venv_python(venv_dir)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!stub\n", encoding="utf-8")
    (venv_dir / bootstrap.PTR_NAME).write_text(py.as_posix(), encoding="utf-8")
    (venv_dir / bootstrap.STAMP_NAME).write_text(stamp, encoding="utf-8")


def test_is_ready_false_when_missing(tmp_path):
    assert bootstrap.is_ready(tmp_path / "venv", "abc") is False


def test_is_ready_true_when_complete_and_matching(tmp_path):
    venv_dir = tmp_path / "venv"
    _fake_venv(venv_dir, "abc")
    assert bootstrap.is_ready(venv_dir, "abc") is True
    # A changed stamp (e.g. plugin update changed deps) invalidates readiness.
    assert bootstrap.is_ready(venv_dir, "different") is False


# --------------------------------------------------------------------------- #
# do_install failure cleanup
# --------------------------------------------------------------------------- #
def _fake_install_real_venv(vd, *a, **k):
    # A real install creates a venv (pyvenv.cfg) plus an interpreter; mirror that so the
    # failure-cleanup path sees a dir that "looks like ours".
    py = bootstrap.venv_python(vd)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!stub\n", encoding="utf-8")
    (vd / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")


def test_do_install_removes_venv_on_failure(tmp_path, monkeypatch):
    # A failed dep install must not leave a partial venv that the next run would later
    # "reuse"; do_install removes it so the next provision rebuilds clean.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)

    venv_dir = tmp_path / "venv"

    def fail_verify(py):
        raise subprocess.CalledProcessError(1, ["uv", "sync"])

    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "verify_imports", fail_verify)
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.do_install(venv_dir)
    assert not venv_dir.exists()


def test_do_install_keeps_preexisting_foreign_dir_on_failure(tmp_path, monkeypatch):
    # bootstrap-4: --venv / KG_ENGINE_VENV may point at a pre-existing populated USER dir.
    # A failed install must NOT blindly rmtree it (that would delete user data); only a
    # dir we own (pyvenv.cfg / engine-python.txt / install.stamp) may be removed.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)

    venv_dir = tmp_path / "user-data"
    venv_dir.mkdir()
    sentinel = venv_dir / "important.txt"
    sentinel.write_text("do not delete me\n", encoding="utf-8")

    # do_install refuses upfront (SystemExit) rather than scaffolding a venv into the populated
    # foreign dir — so the user's data is neither deleted NOR polluted with venv files.
    with pytest.raises(SystemExit):
        bootstrap.do_install(venv_dir)
    assert venv_dir.exists()
    assert sentinel.read_text(encoding="utf-8") == "do not delete me\n"
    assert not bootstrap.venv_python(venv_dir).exists()  # nothing scaffolded into the user dir
    assert not (venv_dir / "pyvenv.cfg").exists()


def test_do_install_refuses_preexisting_foreign_venv_with_pyvenv_cfg(tmp_path, monkeypatch):
    # bootstrap-1: a USER's own real venv (it HAS a pyvenv.cfg, like every venv) pointed at by
    # --venv / KG_ENGINE_VENV must NOT be treated as ours. A bare pyvenv.cfg no longer qualifies as
    # an engine marker, so do_install refuses to scaffold into it and NEVER rmtrees it on failure —
    # the regression that previously let install_with_uv run against (and rmtree) a user's venv.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)

    venv_dir = tmp_path / "user-venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    site = venv_dir / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "userpkg.py").write_text("# the user's installed package\n", encoding="utf-8")

    # install_with_* must never even be reached — the refusal fires before any scaffolding.
    def _boom(*a, **k):  # pragma: no cover - asserts it is never invoked
        raise AssertionError("must not scaffold into a foreign venv")

    monkeypatch.setattr(bootstrap, "install_with_uv", _boom)
    monkeypatch.setattr(bootstrap, "install_with_pip", _boom)

    with pytest.raises(SystemExit):
        bootstrap.do_install(venv_dir)
    # The user's venv survives intact — neither deleted nor polluted with our markers.
    assert (venv_dir / "pyvenv.cfg").exists()
    assert (site / "userpkg.py").read_text(encoding="utf-8") == "# the user's installed package\n"
    assert not (venv_dir / bootstrap.PTR_NAME).exists()
    assert not (venv_dir / bootstrap.STAMP_NAME).exists()


def test_has_engine_marker_ignores_bare_pyvenv_cfg(tmp_path):
    # The ownership predicate keys on engine markers ONLY (bootstrap-1): a bare pyvenv.cfg is not enough.
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    assert bootstrap._has_engine_marker(venv_dir) is False
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    assert bootstrap._has_engine_marker(venv_dir) is False     # pyvenv.cfg alone -> NOT ours
    (venv_dir / bootstrap.PTR_NAME).write_text("x\n", encoding="utf-8")
    assert bootstrap._has_engine_marker(venv_dir) is True      # engine pointer -> ours
    (venv_dir / bootstrap.PTR_NAME).unlink()
    (venv_dir / bootstrap.STAMP_NAME).write_text("x\n", encoding="utf-8")
    assert bootstrap._has_engine_marker(venv_dir) is True      # install.stamp -> ours


# --------------------------------------------------------------------------- #
# FALLO 1 — ownership sentinel: a hard-killed build is reclaimed, never wedged
# --------------------------------------------------------------------------- #
def _install_ok(monkeypatch):
    """Stub the install so do_install runs its guard/marker logic without a real venv build."""
    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "verify_imports", lambda py: None)
    monkeypatch.setattr(bootstrap, "probe_leidenalg", lambda py: None)
    monkeypatch.setattr(bootstrap, "probe_divergence", lambda py: None)


def test_do_install_claims_owner_sentinel_before_populating(tmp_path, monkeypatch):
    # FALLO 1: bootstrap stamps the ownership sentinel BEFORE any bin/lib lands, so a kill mid-build
    # leaves a dir the next run recognises as its own. Assert the sentinel is already present when
    # install_with_* first runs, and is CLEARED once the venv is sealed (crash-report v0.2.4, hole B:
    # a healthy venv must carry NO live reclaim token, else a user venv later placed here could be
    # reclaimed — the sentinel is now a sibling that outlives the venv dir, so it must not linger).
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "data" / ".venv"

    seen = {}

    def install(vd, *a, **k):
        seen["sentinel_present_during_install"] = bootstrap._has_owner_sentinel(vd)
        _fake_install_real_venv(vd, *a, **k)

    monkeypatch.setattr(bootstrap, "install_with_uv", install)
    monkeypatch.setattr(bootstrap, "install_with_pip", install)
    monkeypatch.setattr(bootstrap, "verify_imports", lambda py: None)
    monkeypatch.setattr(bootstrap, "probe_leidenalg", lambda py: None)
    monkeypatch.setattr(bootstrap, "probe_divergence", lambda py: None)

    bootstrap.do_install(venv_dir)
    assert seen["sentinel_present_during_install"] is True     # claimed BEFORE populating
    assert bootstrap._has_owner_sentinel(venv_dir) is False    # CLEARED once sealed (no live token)
    assert (venv_dir / bootstrap.PTR_NAME).exists()            # and it built + sealed


def test_do_install_reclaims_own_hard_killed_build(tmp_path, monkeypatch):
    # FALLO 1 + crash-report v0.2.4 hole B (the wedge): an interrupted provision left a populated venv
    # (pyvenv.cfg + interpreter) with NO completion marker AND — because a venv-dir wipe/recreate or an
    # interrupted rmtree stripped everything inside it — NO in-venv token either. The reclaim token that
    # survives is the SIBLING sentinel beside the venv. The next do_install must recognise this husk as
    # ITS OWN interrupted build and rebuild clean, instead of raising SystemExit "refusing to provision"
    # (which wedged the venv path until a human deleted it).
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "data" / ".venv"

    # Simulate the leftover: populated, sibling OWNER sentinel present, NO completion marker, and NOTHING
    # inside the venv dir marks it as ours (the crash-report husk — its in-venv contents are a partial graph).
    venv_dir.mkdir(parents=True)
    bootstrap._claim_owner_sentinel(venv_dir)                  # stamps the SIBLING token beside the venv
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    py = bootstrap.venv_python(venv_dir)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!stub\n", encoding="utf-8")
    assert not bootstrap._has_engine_marker(venv_dir)          # the wedge precondition
    assert bootstrap._has_owner_sentinel(venv_dir)             # ...but our token survived, beside the venv
    assert not (venv_dir / bootstrap.OWNER_NAME).exists()      # and it is NOT inside the venv (hole B)

    _install_ok(monkeypatch)
    bootstrap.do_install(venv_dir)                             # must NOT raise "refusing to provision"
    assert (venv_dir / bootstrap.PTR_NAME).exists()            # rebuilt + sealed
    assert (venv_dir / bootstrap.STAMP_NAME).exists()
    assert bootstrap._has_owner_sentinel(venv_dir) is False    # token cleared once resealed


def test_do_install_claims_owner_sentinel_on_in_place_upgrade(tmp_path, monkeypatch):
    # Crash-report 2026-07-07 (the wedge's in-place-upgrade twin): a plugin update that changes dependencies
    # moves the install stamp, so do_install UPGRADES the existing, completion-marker-bearing venv IN PLACE —
    # install_with_uv must UNINSTALL the old wheels before reinstalling the new ones. Before the fix the OWNER
    # sentinel was claimed ONLY on the fresh-build path (ours_to_clean), so a hard kill mid-swap left a
    # populated, markerless, OWNERLESS dir that every later run REFUSED forever (the wedge) — meanwhile the
    # half-swapped venv was missing a transitive dep (e.g. `anyio`) and the MCP server crash-looped on
    # ImportError. The fix claims the sentinel before ANY mutation, so an interrupted in-place upgrade is
    # reclaimable next run (via test_do_install_reclaims_own_hard_killed_build) instead of wedging.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "data" / ".venv"

    # A legit PRIOR build: populated (pyvenv.cfg + interpreter) AND carrying a completion marker, but with a
    # now-stale stamp (a deps change moved it) — the in-place-upgrade case, NOT a fresh build and NOT the
    # hard-killed-fresh-build reclaim case. Crucially it has NO owner sentinel yet: it was sealed by a build
    # that predates this fix (a completed build never needed one), which is exactly the pre-fix gap.
    venv_dir.mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (venv_dir / bootstrap.PTR_NAME).write_text("old-python\n", encoding="utf-8")
    (venv_dir / bootstrap.STAMP_NAME).write_text("STALE-STAMP\n", encoding="utf-8")
    py = bootstrap.venv_python(venv_dir)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!stub\n", encoding="utf-8")
    assert bootstrap._has_engine_marker(venv_dir)          # a prior build -> in-place upgrade, not fresh
    assert not bootstrap._has_owner_sentinel(venv_dir)     # and NOT yet owned (the pre-fix gap)

    seen = {}

    def install(vd, *a, **k):
        # The regression pin: the sentinel must ALREADY be claimed when the in-place upgrade — which
        # uninstalls the old wheels first — begins, so a kill here leaves a RECLAIMABLE dir, not a wedged one.
        seen["sentinel_present_during_install"] = bootstrap._has_owner_sentinel(vd)
        _fake_install_real_venv(vd, *a, **k)

    monkeypatch.setattr(bootstrap, "install_with_uv", install)
    monkeypatch.setattr(bootstrap, "install_with_pip", install)
    monkeypatch.setattr(bootstrap, "verify_imports", lambda py: None)
    monkeypatch.setattr(bootstrap, "probe_leidenalg", lambda py: None)
    monkeypatch.setattr(bootstrap, "probe_divergence", lambda py: None)

    bootstrap.do_install(venv_dir)
    assert seen["sentinel_present_during_install"] is True   # claimed BEFORE the in-place upgrade ran
    assert bootstrap._has_owner_sentinel(venv_dir) is False  # CLEARED once the upgrade re-sealed the venv
    assert (venv_dir / bootstrap.PTR_NAME).exists()          # upgraded + re-sealed


def test_do_install_still_refuses_foreign_dir_without_sentinel(tmp_path, monkeypatch):
    # The FALLO 1 fix must NOT widen the reclaim to a user's foreign venv: a populated dir with a bare
    # pyvenv.cfg (every venv has one) but NEITHER a completion marker NOR our OWNER sentinel is still
    # refused — never scaffolded into, never rmtree'd. This is the guard the sentinel narrows, not removes.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "user-venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    keep = venv_dir / "keep.txt"
    keep.write_text("user data\n", encoding="utf-8")

    def _boom(*a, **k):  # pragma: no cover - asserts it is never invoked
        raise AssertionError("must not scaffold into a foreign venv")

    monkeypatch.setattr(bootstrap, "install_with_uv", _boom)
    monkeypatch.setattr(bootstrap, "install_with_pip", _boom)
    with pytest.raises(SystemExit):
        bootstrap.do_install(venv_dir)
    assert keep.read_text(encoding="utf-8") == "user data\n"   # survives intact
    assert not bootstrap._has_owner_sentinel(venv_dir)          # never claimed (no token beside it)
    assert not (venv_dir / bootstrap.OWNER_NAME).exists()       # nor inside it
    assert not (venv_dir / bootstrap.PTR_NAME).exists()


# --------------------------------------------------------------------------- #
# crash-report v0.2.4 "anyio wedge", hole B — the reclaim token must live OUTSIDE
# the venv dir so a wipe/recreate of the venv can't destroy it
# --------------------------------------------------------------------------- #
def test_owner_sentinel_lives_outside_the_venv_dir(tmp_path):
    # Structural pin: the sentinel is a SIBLING of the venv dir, never inside it. If it lived inside,
    # the failure/interrupt cleanup's rmtree(venv_dir) — or an in-place dependency-manager recreate —
    # would take the very token the next run needs to reclaim the husk down with the venv (hole B).
    venv_dir = tmp_path / "data" / ".venv"
    sentinel = bootstrap._owner_sentinel(venv_dir)
    assert sentinel.parent == venv_dir.parent          # beside the venv, like the lock dir
    assert venv_dir not in sentinel.parents            # and NOT under it
    assert sentinel != venv_dir / bootstrap.OWNER_NAME  # specifically not the old in-venv location


def test_owner_sentinel_survives_rmtree_of_venv_dir(tmp_path):
    # The durability guarantee that closes hole B: once claimed, the token outlives a full wipe of the
    # venv dir. This is exactly what the failure-cleanup rmtree (or a uv/pip recreate) does to the venv,
    # and the sentinel MUST still be there afterwards for the next run's reclaim branch to fire.
    venv_dir = tmp_path / "data" / ".venv"
    venv_dir.mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    bootstrap._claim_owner_sentinel(venv_dir)
    assert bootstrap._has_owner_sentinel(venv_dir)

    bootstrap.shutil.rmtree(venv_dir)                  # the crash-cleanup / recreate wipes the whole venv
    assert not venv_dir.exists()
    assert bootstrap._has_owner_sentinel(venv_dir)     # ...but the reclaim token survives beside it


def test_do_install_clears_sentinel_after_clean_failure_so_user_venv_stays_refused(tmp_path, monkeypatch):
    # After a build that FAILS but whose except-cleanup fully removed our venv, the sibling ownership
    # token must be dropped too. Otherwise — now that the token outlives the venv dir — a user later
    # pointing --venv at this same path with their OWN (markerless) venv would have it RECLAIMED and
    # rmtree'd, since a lingering token would falsely read as "our interrupted build". The clean-failure
    # clear keeps that path refused, preserving the never-delete-a-user-venv invariant.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "data" / ".venv"

    def fail_verify(py):
        raise subprocess.CalledProcessError(1, ["uv", "sync"])

    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "verify_imports", fail_verify)
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.do_install(venv_dir)
    assert not venv_dir.exists()                        # venv cleaned up on the clean failure...
    assert not bootstrap._has_owner_sentinel(venv_dir)  # ...and the reclaim token dropped with it

    # A user now puts their OWN venv at that exact path: no engine marker, no live token -> do_install
    # must REFUSE (never reclaim/rmtree it). If the token had lingered this would silently delete it.
    venv_dir.mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    keep = venv_dir / "keep.txt"
    keep.write_text("user data\n", encoding="utf-8")

    def _boom(*a, **k):  # pragma: no cover - asserts it is never invoked
        raise AssertionError("must not scaffold into / reclaim a foreign venv")

    monkeypatch.setattr(bootstrap, "install_with_uv", _boom)
    monkeypatch.setattr(bootstrap, "install_with_pip", _boom)
    with pytest.raises(SystemExit):
        bootstrap.do_install(venv_dir)
    assert keep.read_text(encoding="utf-8") == "user data\n"  # the user's venv survives intact


def test_do_install_keeps_sentinel_when_cleanup_leaves_a_husk(tmp_path, monkeypatch):
    # The asymmetry that makes reclaim work: if the failure-cleanup rmtree can NOT fully remove the venv
    # (a Windows sharing violation, a HARD kill mid-walk), the populated husk remains — so the token must
    # be KEPT, not cleared, so the next run reclaims it (hole B). Simulate by stubbing rmtree to a no-op.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)
    venv_dir = tmp_path / "data" / ".venv"

    def fail_verify(py):
        raise subprocess.CalledProcessError(1, ["uv", "sync"])

    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "verify_imports", fail_verify)
    # rmtree fails to remove the venv (leaves the husk) — the token must NOT be cleared.
    monkeypatch.setattr(bootstrap.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.do_install(venv_dir)
    assert venv_dir.exists()                            # husk remains (rmtree couldn't clear it)
    assert bootstrap._has_owner_sentinel(venv_dir)      # ...so the reclaim token is KEPT for next run


# --------------------------------------------------------------------------- #
# leidenalg soft probe (SAC-blocked native DLL → graceful degradation)
# --------------------------------------------------------------------------- #
def test_verify_imports_excludes_leidenalg_but_keeps_core():
    # Windows Smart App Control can block leidenalg's unsigned native _c_leiden DLL from
    # LOADING even though it installs fine. At runtime projector._leiden already degrades to
    # label propagation, so a blocked leidenalg must NOT be a mandatory import that aborts
    # provisioning. It moved to a separate soft probe; the hard set keeps only what the server
    # genuinely needs to come up.
    assert "leidenalg" not in bootstrap._VERIFY_IMPORTS
    for mod in ("mcp", "pydantic", "networkx", "igraph", "yaml", "kg_engine"):
        assert mod in bootstrap._VERIFY_IMPORTS


def test_leidenalg_probe_swallows_launch_failure(tmp_path, capsys):
    # The probe must NEVER raise or exit non-zero — even if the interpreter can't be launched
    # at all. A missing interpreter path makes subprocess.run raise FileNotFoundError (an
    # OSError); the probe swallows it and still prints the fallback line.
    bootstrap.probe_leidenalg(tmp_path / "no-such-python")  # must not raise
    assert "label-propagation fallback" in capsys.readouterr().out


def test_leidenalg_probe_reports_status_with_real_interpreter(capfd):
    # Against a REAL interpreter the probe prints exactly one status line and returns None
    # (never raises). The line is emitted by the in-venv child subprocess, so capture at the
    # fd level (capfd, not capsys). Which line appears depends on whether leidenalg loads in
    # THIS environment, so accept either — the contract is "always reports, never fails".
    bootstrap.probe_leidenalg(Path(bootstrap.sys.executable))
    out = capfd.readouterr().out
    assert ("Leiden community detection enabled" in out) or ("label-propagation fallback" in out)


def test_do_install_completes_when_leidenalg_unavailable(tmp_path, monkeypatch):
    # The end-to-end guarantee for the SAC case: even when leidenalg is unimportable, do_install
    # still finishes — writing engine-python.txt + install.stamp and returning the interpreter.
    # The probe is advisory only and can never abort the provision (which would rmtree the venv).
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)

    venv_dir = tmp_path / "venv"
    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "verify_imports", lambda py: None)  # core imports "succeed"

    called = {"probe": False}

    def fake_probe(py):  # leidenalg blocked: reports unavailable, returns cleanly
        called["probe"] = True
        print("[bootstrap] leidenalg unavailable (ImportError: DLL load failed while importing "
              "_c_leiden); using label-propagation fallback (projector._leiden)")

    monkeypatch.setattr(bootstrap, "probe_leidenalg", fake_probe)

    py = bootstrap.do_install(venv_dir)
    assert called["probe"]                                   # the probe ran (after verify)
    assert py.exists()
    assert (venv_dir / bootstrap.PTR_NAME).exists()
    assert (venv_dir / bootstrap.STAMP_NAME).exists()        # stamp written last => provision OK


def test_stamp_written_strictly_last(tmp_path, monkeypatch):
    # bootstrap-2: a matching stamp must imply a VERIFIED venv. If verify_imports fails the
    # stamp is never written, so is_ready() can never report a half-built venv as ready.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)

    venv_dir = tmp_path / "venv"
    monkeypatch.setattr(bootstrap, "install_with_uv", _fake_install_real_venv)
    monkeypatch.setattr(bootstrap, "install_with_pip", _fake_install_real_venv)

    def fail_verify(py):
        raise subprocess.CalledProcessError(1, ["uv", "sync"])

    monkeypatch.setattr(bootstrap, "verify_imports", fail_verify)
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.do_install(venv_dir)
    assert not (venv_dir / bootstrap.STAMP_NAME).exists()


# --------------------------------------------------------------------------- #
# lock
# --------------------------------------------------------------------------- #
def test_lock_is_mutually_exclusive(tmp_path):
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True
    assert bootstrap.try_acquire(venv_dir) is False  # second caller is locked out
    bootstrap.release(venv_dir)
    assert bootstrap.try_acquire(venv_dir) is True    # released -> acquirable again
    bootstrap.release(venv_dir)


def test_stale_lock_is_stolen(tmp_path):
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True
    lock = bootstrap._lock_dir(venv_dir)
    hb = bootstrap._heartbeat_file(venv_dir)
    # Age BOTH the lock dir and the heartbeat: liveness is judged by the heartbeat, so an
    # abandoned holder (no recent heartbeat) is what makes a lock genuinely stealable.
    old = time.time() - bootstrap.STALE_LOCK_SECS - 60
    os.utime(lock, (old, old))
    if hb.exists():
        os.utime(hb, (old, old))
    # A fresh provisioner reclaims an abandoned lock instead of waiting forever.
    assert bootstrap.try_acquire(venv_dir) is True
    bootstrap.release(venv_dir)


def test_fresh_but_long_lock_is_not_stolen(tmp_path):
    # bootstrap-1: a slow cold source-build (igraph/leidenalg from sdist) can outlive
    # STALE_LOCK_SECS while still healthy. The holder refreshes a heartbeat during install,
    # so even when the lock DIR mtime is ancient a recent heartbeat keeps the lock live and
    # a concurrent provisioner must NOT steal it (stealing -> two installs clobber one venv).
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True
    lock = bootstrap._lock_dir(venv_dir)
    # The dir itself looks ancient...
    old = time.time() - bootstrap.STALE_LOCK_SECS - 60
    os.utime(lock, (old, old))
    # ...but the holder just sent a heartbeat (the install loop is alive).
    bootstrap.heartbeat(venv_dir)
    assert bootstrap._heartbeat_file(venv_dir).exists()
    assert bootstrap.try_acquire(venv_dir) is False  # live holder is not stolen
    bootstrap.release(venv_dir)


def test_orphan_sideline_does_not_block_steal(tmp_path):
    # F24: a crash between os.replace() and rmtree() in the steal path orphans a non-empty
    # ``.kg-provision.lock.stale-<...>`` dir. A later stealer must not be wedged by it: the steal target
    # is collision-proof (PID + time_ns), and a GENUINELY STALE orphan (mtime older than STALE_LOCK_SECS)
    # is reaped first, so the steal succeeds AND the leftover is cleaned. (A FRESH orphan — possibly a
    # concurrent racer's in-flight sideline — is intentionally spared; see test_fresh_orphan_is_spared.)
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True
    lock = bootstrap._lock_dir(venv_dir)
    hb = bootstrap._heartbeat_file(venv_dir)

    # Plant a NON-EMPTY orphan sideline that an earlier crashed stealer left behind, named
    # exactly as the old (PID-only) scheme would have — the case that used to ENOTEMPTY.
    orphan = lock.parent / f"{bootstrap.LOCK_NAME}.stale-{os.getpid()}"
    orphan.mkdir()
    (orphan / "leftover").write_text("crashed mid-steal\n", encoding="utf-8")

    # Age the live lock + heartbeat past the stale threshold so it is genuinely stealable, and age the
    # orphan too so the mtime-gated sweep treats it as a real crash leftover (not a live racer's sideline).
    old = time.time() - bootstrap.STALE_LOCK_SECS - 60
    os.utime(lock, (old, old))
    if hb.exists():
        os.utime(hb, (old, old))
    os.utime(orphan, (old, old))

    # The steal must succeed despite the orphan, and the stale orphan must be swept away.
    assert bootstrap.try_acquire(venv_dir) is True
    assert not orphan.exists()
    bootstrap.release(venv_dir)
    # No stale sidelines leaked after a clean steal.
    assert not list(lock.parent.glob(f"{bootstrap.LOCK_NAME}.stale-*"))


def test_fresh_orphan_is_spared(tmp_path):
    # The orphan-sweep must NOT reap a FRESH ``*.stale-*`` dir: it may be the in-flight sideline of a
    # CONCURRENT stealer/releaser (unique pid+time_ns name). rmtree-ing it out from under that racer
    # would make its own re-validation see the dir "vanished" and STEAL a lock it meant to RESTORE,
    # destroying a live holder. The steal still succeeds despite the fresh orphan (collision-proof
    # naming); the orphan is simply left to age out, not clobbered mid-flight.
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True
    lock = bootstrap._lock_dir(venv_dir)
    hb = bootstrap._heartbeat_file(venv_dir)

    # A fresh (just-created) orphan stands in for a concurrent racer's in-flight sideline.
    fresh = lock.parent / f"{bootstrap.LOCK_NAME}.stale-999999-{time.time_ns()}"
    fresh.mkdir()
    (fresh / "info").write_text("a live racer's sideline\n", encoding="utf-8")

    # Age the live lock + heartbeat so it is genuinely stealable, but leave the orphan FRESH.
    old = time.time() - bootstrap.STALE_LOCK_SECS - 60
    os.utime(lock, (old, old))
    if hb.exists():
        os.utime(hb, (old, old))

    # The steal succeeds despite the fresh orphan, and the fresh orphan is left untouched (not clobbered).
    assert bootstrap.try_acquire(venv_dir) is True
    assert fresh.exists()
    bootstrap.release(venv_dir)


# --------------------------------------------------------------------------- contended provisioning
# Why this is NOT the canon lease's problem (2026-07-30, DECISIONS.md "The provision lock stays
# unordered"): canon.LeaseLock had to be made FIFO-fair because each of its waiters needs a TURN — a
# writer that keeps losing races eventually exhausts its budget and fails its write. A provisioning
# waiter needs an OUTCOME (the venv being ready), not a turn: when the builder finishes, every waiter
# leaves on the readiness check without ever taking the lock. That is what makes the unordered 2s poll
# correct here, so it is worth pinning rather than leaving as an implicit property.
#
# Real SUBPROCESSES, not threads: dirlock._OWNED_TOKENS is module state, so threads sharing one process
# would share the token map and could pop each other's ownership between release()'s os.replace and its
# pop — a hazard that cannot exist across the separate processes this lock actually serializes.


_CONTENDED_CHILD = '''
import importlib.util, os, sys, time
from pathlib import Path

boot_path, venv_dir, ready, markers = sys.argv[1:5]
venv_dir, ready, markers = Path(venv_dir), Path(ready), Path(markers)

spec = importlib.util.spec_from_file_location("kg_bootstrap", boot_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.POLL_SECS = 0.05                       # keep the test quick; the loop shape is unchanged
mod.venv_current = lambda vd: ready.exists()   # "the venv is provisioned" signal, shared by all children

out = mod._wait_for_lock(venv_dir, time.time() + 60)
if out is None:                            # we hold the lock -> we are a candidate builder
    try:
        if ready.exists():
            # bootstrap's post-acquire re-check (provision(): "re-check now that we hold the lock")
            print("RESULT acquired-after-ready")
        else:
            (markers / ("build-%d" % os.getpid())).write_text("built", encoding="utf-8")
            time.sleep(0.3)                # the venv build
            ready.write_text("ready", encoding="utf-8")
            print("RESULT built")
    finally:
        mod.release(venv_dir)
elif out == mod.EXIT_OK:
    print("RESULT another-finished")
else:
    print("RESULT exit-%s" % out)
'''


def test_concurrent_provisioners_run_one_build_and_none_starve(tmp_path):
    """N sessions racing to provision must produce exactly ONE build, and every waiter must reach a
    terminal answer — none may sit out its whole deadline. The lock is deliberately unordered, so this
    is the property that makes ordering unnecessary: a loser of the mkdir race does not queue for a
    turn, it observes the finished venv and leaves."""
    child = tmp_path / "child.py"
    child.write_text(_CONTENDED_CHILD, encoding="utf-8")
    venv_dir = tmp_path / "venv"
    ready = tmp_path / "ready"
    markers = tmp_path / "markers"
    markers.mkdir()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_BOOT_PATH.parent)  # kg_engine (dirlock) lives beside bootstrap.py
    for var in ("KG_ENGINE_VENV", "CLAUDE_PLUGIN_DATA"):
        env.pop(var, None)

    procs = [
        subprocess.Popen(
            [sys.executable, str(child), str(_BOOT_PATH), str(venv_dir), str(ready), str(markers)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        for _ in range(4)
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        assert p.returncode == 0, f"provisioner crashed: {err}"
        line = [ln for ln in out.splitlines() if ln.startswith("RESULT ")]
        assert line, f"no result from provisioner: {out!r} {err!r}"
        results.append(line[0].removeprefix("RESULT "))

    # Exactly one real build: the lock did its job (two would mean two jobs clobbering one venv).
    assert len(list(markers.iterdir())) == 1, f"expected one build, got {sorted(markers.iterdir())}"
    assert results.count("built") == 1, results
    # Nobody starved: every other session reached a terminal answer instead of waiting out its deadline.
    assert not [r for r in results if r.startswith("exit-")], f"a provisioner starved: {results}"
    # The lock is released and nothing leaked behind it.
    lock = bootstrap._lock_dir(venv_dir)
    assert not lock.exists(), "the provision lock outlived the wave"
    assert not list(lock.parent.glob(f"{bootstrap.LOCK_NAME}.stale-*"))
    assert not list(lock.parent.glob(f"{bootstrap.LOCK_NAME}.release-*"))


def _write_info(venv_dir, *, pid, host, token="tok", t=None):
    """Plant a lock-dir ``info`` record (the steal/release ownership + liveness signal)."""
    lock = bootstrap._lock_dir(venv_dir)
    lock.mkdir(parents=True, exist_ok=True)
    when = bootstrap.time.time() if t is None else t
    (lock / "info").write_text(
        f"pid={pid} host={host} token={token} t={when:.0f}\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# M7 / FALLO 2 — PID-liveness probe: a crashed holder is reclaimable in ms, not 30 min
# --------------------------------------------------------------------------- #
def test_dead_pid_lock_is_stolen_before_stale_window(tmp_path):
    # M7 / FALLO 2: a hard-killed background worker freezes its heartbeat, so the age signal stays
    # FRESH for the full 30-min STALE_LOCK_SECS. A cheap pid-liveness probe must reclaim it in
    # milliseconds instead — os.kill(pid, 0) on POSIX, OpenProcess (_win_pid_alive) on Windows. Now
    # cross-platform (FALLO 2 removed the Windows skip: the probe there is no longer a no-op).
    venv_dir = tmp_path / "venv"
    # A held, FRESH lock (heartbeat just now) whose recorded holder is a dead pid on THIS host.
    bootstrap._lock_dir(venv_dir).mkdir(parents=True)
    bootstrap.heartbeat(venv_dir)
    _write_info(venv_dir, pid=_dead_pid(), host=dirlock._HOST)
    assert dirlock.lock_age(bootstrap._lock_dir(venv_dir)) < bootstrap.STALE_LOCK_SECS  # NOT stale by age
    assert bootstrap.try_acquire(venv_dir) is True  # ...but the dead-pid probe reclaims it
    bootstrap.release(venv_dir)


def test_pid_probe_dispatches_to_windows_liveness_probe(monkeypatch):
    # FALLO 2 dispatch (runs on any OS): under os.name == "nt", pid_probe must consult _win_pid_alive
    # instead of returning a blanket assume-alive — that is what makes a dead holder reclaimable in ms
    # on Windows. Stub the probe so this is exercised on the Linux CI too (the real OpenProcess call is
    # covered by the reclaim test above when it runs on Windows).
    monkeypatch.setattr(dirlock.os, "name", "nt")
    seen = {}

    def fake_alive(pid):
        seen["pid"] = pid
        return False  # report the recorded holder dead

    monkeypatch.setattr(dirlock, "_win_pid_alive", fake_alive)
    rec = {"pid": "4321", "host": dirlock._HOST}
    assert dirlock.pid_probe(rec) is False   # dead per the Windows probe
    assert seen["pid"] == 4321               # ...which pid_probe actually consulted
    monkeypatch.setattr(dirlock, "_win_pid_alive", lambda pid: True)
    assert dirlock.pid_probe(rec) is True     # alive per the Windows probe
    # A cross-host record is still assumed alive WITHOUT probing, even on nt.
    assert dirlock.pid_probe({"pid": "4321", "host": "other-host"}) is True


def test_live_pid_fresh_lock_is_not_stolen(tmp_path):
    # The probe must not over-reclaim: a FRESH lock held by a LIVE pid (our own) stays held.
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True  # records our live pid in info
    age = dirlock.lock_age(bootstrap._lock_dir(venv_dir))
    assert age < bootstrap.STALE_LOCK_SECS
    assert bootstrap.try_acquire(venv_dir) is False  # live holder is not stolen
    bootstrap.release(venv_dir)


def test_foreign_host_pid_is_treated_as_alive(tmp_path):
    # A pid recorded on ANOTHER host can't be probed locally; treat it as alive (so a fresh
    # lock from a different machine on a shared FS is not stolen by the probe). Only age can
    # reclaim it — exactly canon._pid_probe's cross-host rule.
    venv_dir = tmp_path / "venv"
    bootstrap._lock_dir(venv_dir).mkdir(parents=True)
    bootstrap.heartbeat(venv_dir)
    _write_info(venv_dir, pid=_dead_pid(), host="some-other-host")
    assert bootstrap.try_acquire(venv_dir) is False  # foreign-host pid -> assumed alive
    bootstrap.release(venv_dir)  # we don't own it -> no-op
    assert bootstrap._lock_dir(venv_dir).exists()


# --------------------------------------------------------------------------- #
# M8 — reclaim TOCTOU: a holder that refreshes in the steal window keeps its lock
# --------------------------------------------------------------------------- #
def test_steal_restores_lock_that_became_fresh_in_the_window(tmp_path, monkeypatch):
    # M8: the steal decision reads age, then os.replace()s the lock aside. If the holder's
    # heartbeat fires in that window the MOVED dir is now LIVE; the stealer must re-validate
    # the sidelined dir and put it back (lose the race) instead of destroying a live build's
    # heartbeat. Simulate the window by re-validating against a LIVE pid + fresh heartbeat.
    venv_dir = tmp_path / "venv"
    bootstrap._lock_dir(venv_dir).mkdir(parents=True)
    # Make the lock look stealable to the FIRST check (aged heartbeat + a dead pid)...
    lock = bootstrap._lock_dir(venv_dir)
    hb = bootstrap._heartbeat_file(venv_dir)
    hb.write_text("x\n", encoding="utf-8")
    old = bootstrap.time.time() - bootstrap.STALE_LOCK_SECS - 60
    os.utime(lock, (old, old))
    os.utime(hb, (old, old))
    _write_info(venv_dir, pid=_dead_pid(), host=dirlock._HOST)

    # ...but the holder "refreshes" in the steal window: re-validation of the SIDELINED dir
    # sees a fresh heartbeat + live pid, so the steal must back off and restore the lock.
    real_replace = bootstrap.os.replace
    state = {"moved": False}

    def replace_then_refresh(src, dst, *a, **k):
        real_replace(src, dst, *a, **k)
        if not state["moved"] and bootstrap.LOCK_NAME + ".stale-" in str(dst):
            state["moved"] = True
            now = bootstrap.time.time()
            os.utime(Path(dst), (now, now))
            os.utime(Path(dst) / "heartbeat", (now, now))
            (Path(dst) / "info").write_text(
                f"pid={os.getpid()} host={dirlock._HOST} token=live t={now:.0f}\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(bootstrap.os, "replace", replace_then_refresh)
    assert bootstrap.try_acquire(venv_dir) is False  # lost the race -> live holder preserved
    # The lock is back at the live path and still carries the holder's live record.
    assert lock.exists()
    assert dirlock.parse_info(lock).get("token") == "live"


# --------------------------------------------------------------------------- #
# M9 — release() verifies ownership before rmtree (false-steal-then-revive)
# --------------------------------------------------------------------------- #
def test_release_does_not_destroy_a_foreign_lock(tmp_path):
    # M9: a holder falsely judged stale (suspend/resume past STALE_LOCK_SECS) is stolen by a
    # successor that now holds a BRAND-NEW lock at the same path. When the original holder
    # finally resumes and calls release(), it must NOT rmtree the successor's lock — release
    # only removes a lock whose info still carries OUR token (mirrors LeaseLock.release F15).
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True            # original holder (token A)
    our_token = dirlock._OWNED_TOKENS[str(bootstrap._lock_dir(venv_dir))]

    # A successor steals the path and writes its OWN token, as a real steal+reacquire would.
    lock = bootstrap._lock_dir(venv_dir)
    (lock / "info").write_text(
        f"pid={os.getpid()} host={dirlock._HOST} token=successor t={bootstrap.time.time():.0f}\n",
        encoding="utf-8",
    )
    assert our_token != "successor"

    bootstrap.release(venv_dir)  # the original holder releases on its way out
    # The successor's lock survives, with its token intact.
    assert lock.exists()
    assert dirlock.parse_info(lock).get("token") == "successor"
    # Clean up the successor lock (no recorded ownership -> manual rmtree).
    bootstrap.shutil.rmtree(lock, ignore_errors=True)


def test_release_removes_our_own_lock(tmp_path):
    # The happy path still works: a lock we own (our token in info) is removed by release().
    venv_dir = tmp_path / "venv"
    assert bootstrap.try_acquire(venv_dir) is True
    lock = bootstrap._lock_dir(venv_dir)
    assert lock.exists()
    bootstrap.release(venv_dir)
    assert not lock.exists()
    assert str(lock) not in dirlock._OWNED_TOKENS  # ownership forgotten on release
    assert not list(lock.parent.glob(f"{bootstrap.LOCK_NAME}.release-*"))  # no sideline leaked


# --------------------------------------------------------------------------- #
# low — heartbeat write failure backstops onto the lock-dir mtime
# --------------------------------------------------------------------------- #
def test_heartbeat_failure_touches_lock_dir_as_backstop(tmp_path, monkeypatch):
    # low/edge-case: if the heartbeat file write keeps failing (read-only fs / ENOSPC / AV),
    # the live holder must still advance _lock_age's FALLBACK signal (the lock-dir mtime) so a
    # genuine >30-min build is not judged stale and stolen. The except branch touches the dir.
    venv_dir = tmp_path / "venv"
    lock = bootstrap._lock_dir(venv_dir)
    lock.mkdir(parents=True)
    # No heartbeat file exists yet and every write_text raises -> the else branch is taken and
    # fails, so the backstop os.utime(lock) must run instead.
    monkeypatch.setattr(bootstrap.Path, "write_text", _raise_oserror)
    old = bootstrap.time.time() - 100
    os.utime(lock, (old, old))
    before = lock.stat().st_mtime
    bootstrap.heartbeat(venv_dir)
    assert not bootstrap._heartbeat_file(venv_dir).exists()  # the hb file never landed
    assert lock.stat().st_mtime > before                     # ...but the dir mtime advanced


def _raise_oserror(*a, **k):
    raise OSError("simulated read-only fs")


def _dead_pid() -> int:
    """A pid that is (almost certainly) not running: spawn a trivial child and reap it."""
    p = subprocess.Popen(
        [bootstrap.sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    p.wait()
    return p.pid


# --------------------------------------------------------------------------- #
# --check (launcher freshness probe; node-launchers-2)
# --------------------------------------------------------------------------- #
def test_check_exit_code_tracks_readiness(tmp_path, monkeypatch, capsys):
    # The MCP launcher runs `bootstrap.py --check --venv DIR` to detect a STALE venv (old
    # interpreter present but deps changed). It must exit 0 iff is_ready and print nothing
    # to stdout (it shares stdout with the JSON-RPC channel).
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\ndependencies = ['a']\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "PYPROJECT", pp)

    venv_dir = tmp_path / "venv"
    argv = ["--check", "--venv", str(venv_dir)]

    # Not provisioned yet -> non-zero, silent.
    assert bootstrap.main(argv) != 0
    assert capsys.readouterr().out == ""

    # Provision with the CURRENT stamp -> exit 0.
    _fake_venv(venv_dir, bootstrap.compute_stamp())
    assert bootstrap.main(argv) == 0
    assert capsys.readouterr().out == ""

    # A deps change moves the stamp; the old (now-stale) venv -> non-zero.
    pp.write_text("[project]\ndependencies = ['a', 'b']\n", encoding="utf-8")
    assert bootstrap.main(argv) != 0
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# foreground --wait default (F23)
# --------------------------------------------------------------------------- #
def test_default_wait_outlasts_stale_lock(tmp_path, monkeypatch):
    # F23: try_acquire() can only STEAL a lock once its heartbeat age passes
    # STALE_LOCK_SECS. A hard-killed holder freezes its heartbeat, so the lock is not
    # stealable until STALE_LOCK_SECS elapses. If the foreground --wait deadline fired
    # FIRST (the old 1200s vs the 1800s stale window), provision() would return 0 without
    # building — silently dropping every kg_* tool for that session. So the default --wait
    # must be >= STALE_LOCK_SECS: one run can both wait out a live build and reclaim a dead
    # one. Capture the wait_secs main() forwards to provision() when no --wait is given.
    seen = {}

    def fake_provision(venv_dir, *, wait_secs, reconcile=False):
        seen["wait_secs"] = wait_secs
        return 0

    monkeypatch.setattr(bootstrap, "provision", fake_provision)
    rc = bootstrap.main(["--venv", str(tmp_path / "venv")])
    assert rc == 0
    assert seen["wait_secs"] >= bootstrap.STALE_LOCK_SECS

    # An explicit --wait override still wins (operator can shorten/lengthen at will).
    bootstrap.main(["--venv", str(tmp_path / "venv"), "--wait", "5"])
    assert seen["wait_secs"] == 5.0


# --------------------------------------------------------------------------- #
# review-r13 — the Windows sharing violation on the lock DIRECTORY renames
#
# Every rename in dirlock moves the live lock dir while waiting provisioners poll it:
# try_acquire -> is_stealable -> parse_info OPENS `lock/info` on each poll, and Python's
# open() does not grant FILE_SHARE_DELETE, so on Windows renaming that directory raises
# PermissionError (ERROR_SHARING_VIOLATION). These pins inject exactly that error, so the
# regression fails on EVERY platform rather than occasionally on the Windows CI leg — the
# flake that found it passed on a rerun of the identical commit.
# --------------------------------------------------------------------------- #
class _FlakyReplace:
    """os.replace that raises the Windows sharing violation for its first ``n`` calls."""

    def __init__(self, n, real):
        self.left, self.real, self.calls = n, real, 0

    def __call__(self, src, dst):
        self.calls += 1
        if self.left > 0:
            self.left -= 1
            raise PermissionError(
                32, "The process cannot access the file because it is being used by another process"
            )
        return self.real(src, dst)


@pytest.fixture
def flaky_replace(monkeypatch):
    def install(n):
        flaky = _FlakyReplace(n, os.replace)
        monkeypatch.setattr(dirlock.os, "replace", flaky)
        return flaky

    return install


def test_release_survives_a_transient_sharing_violation(tmp_path, flaky_replace):
    """THE flake. A peer holding `lock/info` open made release()'s rename fail; the OSError was
    read as "already reclaimed", the token dropped, and the lock dir outlived its owner."""
    lock = tmp_path / "provision.lock"
    assert dirlock.try_acquire(lock, stale_secs=1800)
    flaky = flaky_replace(3)  # three violations, then the reader closes its handle

    dirlock.release(lock)

    assert not lock.exists(), "the lock outlived release() — the leak this retry exists to close"
    assert flaky.calls == 4, f"expected 3 retries then success, got {flaky.calls} attempts"
    assert not list(tmp_path.glob("*.release-*")), "no sideline may survive a successful release"
    assert str(lock) not in dirlock._OWNED_TOKENS


def test_release_still_degrades_when_the_violation_never_clears(tmp_path, flaky_replace):
    """The budget is bounded, so a PERSISTENT violation must still return quietly rather than
    raise out of a release running in bootstrap's `finally`. The lock leaks, exactly as before —
    reclaimable by the next acquirer's pid probe. The retry narrows the window, it does not
    promise the rename."""
    lock = tmp_path / "provision.lock"
    assert dirlock.try_acquire(lock, stale_secs=1800)
    flaky = flaky_replace(10**6)

    start = time.monotonic()
    dirlock.release(lock)  # must not raise
    elapsed = time.monotonic() - start

    assert lock.exists(), "a permanent violation cannot be renamed away — the leak is the fallback"
    assert elapsed < dirlock._REPLACE_TIMEOUT * 3, f"release stalled {elapsed:.1f}s at exit"
    assert flaky.calls > 1, "the deadline must buy more than one attempt"


def test_a_lost_race_is_not_slowed_by_the_retry_budget(tmp_path, monkeypatch):
    """Only PermissionError is retried. A genuinely lost race surfaces as FileNotFoundError —
    another racer already moved the dir — and must back off NOW rather than sleep out a budget
    waiting for a directory that is gone."""
    lock = tmp_path / "provision.lock"
    lock.mkdir()
    calls = {"n": 0}

    def vanished(src, dst):
        calls["n"] += 1
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(dirlock.os, "replace", vanished)
    start = time.monotonic()
    assert dirlock._steal(lock, stale_secs=0.0) is False
    elapsed = time.monotonic() - start

    assert calls["n"] == 1, "FileNotFoundError must not be retried"
    assert elapsed < dirlock._REPLACE_TIMEOUT / 2, f"a lost race waited {elapsed:.2f}s"


def test_steal_survives_a_transient_sharing_violation(tmp_path, flaky_replace):
    """The reclaim path has the same exposure: without the retry a stealable lock is abandoned for
    the round and the waiter re-loops a whole POLL_SECS later."""
    lock = tmp_path / "provision.lock"
    lock.mkdir()
    (lock / "info").write_text("pid=0 host=nowhere token=dead t=0\n", encoding="utf-8")
    os.utime(lock, (0, 0))  # ancient -> genuinely stealable
    flaky = flaky_replace(2)

    assert dirlock._steal(lock, stale_secs=1.0) is True
    assert not lock.exists(), "a successful steal moves the stale dir aside"
    assert flaky.calls == 3
