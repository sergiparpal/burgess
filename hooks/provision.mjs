#!/usr/bin/env node
// SessionStart provisioning hook — the SINGLE cross-platform implementation (review-r5).
//
// This file used to be a dispatcher that picked provision.sh (POSIX) or provision.ps1 (Windows),
// which encoded the same launcher twice in two shell dialects — root fallback, uv PATH prepend,
// Python>=3.10 probe, bootstrap hand-off — with interpreter-candidate lists that had already
// drifted apart. Node is present wherever Claude Code runs, so the whole job now lives here on the
// shared resolver (_engine_resolve.mjs systemPython, which absorbed the versioned python3.x probe
// tail). provision.sh / provision.ps1 remain as one-line dev shims that exec this script.
//
// The launcher finds a Python >= 3.10 and hands off to scripts/bootstrap.py, which does the real,
// idempotent provisioning in a DETACHED background process and returns in milliseconds — so the
// bounded synchronous spawn below is cheap and the detached worker outlives this script.
//
// NB: no pointer-only fast path here. The interpreter pointer (engine-python.txt) survives a
// plugin update that changes dependencies, so short-circuiting on its existence would skip the
// background rebuild on exactly the update case it's meant to handle. Always hand off to
// `bootstrap.py --background`, which checks the content STAMP (the real freshness gate) and
// returns in milliseconds when current.
//
// Failure is silent by design (this is a background hook): if anything goes wrong — no suitable
// Python, no bootstrap script — the MCP launcher starts a background build of its own when the
// server is spawned, and reports clearly if that build cannot finish inside Claude Code's MCP
// connect window.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PROBE_TIMEOUT_MS, clean, systemPython, venvDir } from "../scripts/_engine_resolve.mjs";

try {
  const hooksDir = dirname(fileURLToPath(import.meta.url));
  // Dev fallback (`--plugin-dir .` without the var, or run by hand): hooks/ -> repo root.
  const root = clean(process.env.CLAUDE_PLUGIN_ROOT) || dirname(hooksDir);
  const boot = join(root, "scripts", "bootstrap.py");
  if (existsSync(boot)) {
    // Prepend uv's usual install dir (~/.local/bin on POSIX, %USERPROFILE%\.local\bin on Windows)
    // BEFORE the probe, so both a standalone-installed uv (bootstrap's shutil.which('uv') fast
    // path) and a user-local Python not yet on the inherited PATH are found. Harmless if absent.
    // Filter out an empty inherited PATH before joining: an unset/empty PATH would otherwise leave a
    // trailing `<...>/.local/bin:` whose empty element POSIX resolves as the CWD, putting a possibly
    // attacker-controlled `python3` in the session's working directory on the probe's search path
    // (review-r8-21).
    const localBin = join(homedir(), ".local", "bin");
    process.env.PATH = [localBin, process.env.PATH].filter(Boolean).join(delimiter);
    const py = systemPython(); // >= 3.10, each candidate probe bounded by PROBE_TIMEOUT_MS
    if (py) {
      // Pass the SAME resolved venv dir the launcher uses (`venvDir(root)`) as `--venv`, instead of
      // letting bootstrap self-resolve. Without this the background worker resolves a RELATIVE
      // KG_ENGINE_VENV against its process CWD while the launcher/precontext resolve it against `root`
      // (expandResolve), so the two build/look at different dirs — a double build or a never-found venv
      // (review-low: relative KG_ENGINE_VENV base mismatch). Absolute/default paths are unaffected.
      const venv = venvDir(root);
      // stdio ignored so bootstrap never writes to the hook log (it logs to provision.log).
      // Defensive timeout: `--background` returns in ms after spawning the detached worker, but a
      // wedged interpreter must not block this synchronous spawn forever. `--reconcile` asks the
      // worker for the once-per-session canon sweep (§1.8); this hook is the only caller that does —
      // the MCP launcher also starts background builds, and must not double the sweep.
      spawnSync(py, [boot, "--background", "--reconcile", "--venv", venv], {
        stdio: "ignore",
        timeout: PROBE_TIMEOUT_MS,
        killSignal: "SIGKILL",
      });
    }
  }
} catch {
  // never surface an error from a background hook
}
process.exit(0);
