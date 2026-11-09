#!/usr/bin/env node
// MCP server launcher + SUPERVISOR (cross-platform; §2.1 bootstrap hardening + transport-resilience pass).
//
// `.mcp.json` runs `node launch_server.mjs`. Two jobs:
//
// 1. COLD-START SELF-HEAL (the original role). Launching the server directly as `<venv>/bin/python`
//    races the SessionStart venv build: on a cold first session that path may not exist yet, the spawn
//    fails, and Claude Code caches the server as "needs-auth" — dropping all kg_* tools for the whole
//    session. Going through Node (always present) means the MCP spawn ALWAYS succeeds; this launcher
//    then makes sure a venv build is under way and waits for it before launching the real server.
//    Warm sessions skip straight to launch.
//
//    The build never runs in THIS process (0.4.3). Claude Code gives a server MCP_TIMEOUT ms (30 000
//    by default) to answer `initialize`, then abandons it and kills it, and on Windows the processes it
//    started directly die with it (Node's and the `py` launcher's job objects). The launcher used to run
//    the build itself, in the foreground, and a cold Windows build takes minutes, so the kill landed
//    mid-install: a provision lock held by a dead pid, a half-built venv, and still no engine for the
//    session. Now the build goes to bootstrap's DETACHED worker (`--background`), which that kill does
//    not reach (checked with `taskkill /F /T` mid-wait), and the launcher only waits — while an engine
//    launched at the end of the wait could still answer in time (CONNECT). If the venv is not ready by
//    then, it says so and exits; the build carries on, and the user reconnects from /mcp once it is done
//    (Claude Code never retries a failed stdio server by itself).
//
// 2. SUPERVISION (the resilience pass). The Node process is a PERSISTENT PARENT that spawns the Python
//    engine as a child and supervises it, with capped exponential backoff, a crash-loop guard, and full
//    logging of every (re)launch / exit / backoff decision to `<KG_DATA>/server.log` (the SAME rotating
//    file the engine writes — see server.py:configure_logging). The restart POLICY is the pure, exported
//    `restartDecision` / `backoffFor`, unit-testable without spawning a real engine.
//
//    What it relaunches — and why NOT everything. The engine runs with `stdio: "inherit"`, so Node never
//    owns the JSON-RPC stream and CANNOT replay MCP's per-connection `initialize` handshake. That splits
//    a crash into two cases (see restartDecision for the full reasoning):
//      • STARTUP failure (crash before the engine served `initialize`, e.g. an import error against a
//        half-built venv): the client's `initialize` is still buffered, unread, on the inherited stdin, so
//        a heal + in-place relaunch genuinely self-heals the cold-start race — and the parent (hence the
//        client pipe) stays alive. This is the original §2.1 role, now with backoff + a crash-loop cap.
//      • POST-INIT crash (the engine had already answered `initialize`): a relaunched engine would start
//        UNINITIALIZED on a pipe the client already handshaked, and — because Node holds the pipe open —
//        the client neither re-handshakes nor sees an EOF, i.e. a connection that looks alive but is dead.
//        That is strictly WORSE than a clean disconnect, so we EXIT instead: the pipe closes, the client
//        detects the drop and reconnects with a fresh handshake. (Fully transparent post-init restart
//        would require Node to PROXY the stream and replay the handshake + synthesize responses for
//        in-flight request ids — a larger change, deliberately deferred.)
//    Either way the failure is now LOGGED with a full traceback (server.log) instead of vanishing.
//
// Venv/interpreter resolution lives in ./_engine_resolve.mjs (shared with the other launchers).
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readdirSync, realpathSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  venvDir, systemPython, enginePython, withPythonpath, clean, PROBE_TIMEOUT_MS, STAMP_NAME, PROVISION_LOG_NAME,
} from "./_engine_resolve.mjs";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url)); // <repo>/scripts
const ROOT = process.env.CLAUDE_PLUGIN_ROOT || dirname(SCRIPT_DIR);
const SCRIPTS = join(ROOT, "scripts");
const BOOTSTRAP = join(SCRIPTS, "bootstrap.py");
const VENV_DIR = venvDir(ROOT);  // the resolved engine venv (review-r5: was `dir`)

// The connect window. Claude Code abandons a stdio MCP server that has not answered `initialize` within
// MCP_TIMEOUT ms (30 000 when unset; .mcp.json has no per-server startup timeout), marks it failed for the
// session and never retries it by itself. So a venv that is not ready yet is waited for only while an
// engine launched at the end of the wait could still answer in time. ENGINE_START_RESERVE_MS is what the
// engine gets to import and serve `initialize`: measured on Windows at 2.7 s right after a build and
// ~1.6 s warm, with room left for a cold disk or an antivirus scan. Waiting past that cannot produce a
// connection; it only turns this launcher's explicit message into the client's bare timeout.
// (Replaces the 40-minute foreground catch-up ceiling, which assumed a client that waits for the build.)
export const CONNECT = {
  DEFAULT_TIMEOUT_MS: 30_000,
  ENGINE_START_RESERVE_MS: 10_000,
  POLL_MS: 1_000,
};

// The client's connect timeout, read the way Claude Code reads MCP_TIMEOUT: an integer of milliseconds,
// anything else (or a non-positive value) meaning the default. Claude Code passes its whole environment to
// the servers it spawns, so a user who raised MCP_TIMEOUT to let a first session wait out its build is
// seen here, and the launcher waits that much longer.
export function connectTimeoutMs(env = process.env, C = CONNECT) {
  const n = Number.parseInt(clean(env.MCP_TIMEOUT), 10);
  return Number.isFinite(n) && n > 0 ? n : C.DEFAULT_TIMEOUT_MS;
}

// The wall-clock time by which the venv must be ready for this launch to still connect. Counted from the
// launcher's own start, the closest observable point to when the client started its timer.
export function provisionDeadline(startedAtMs, env = process.env, C = CONNECT) {
  return startedAtMs + Math.max(0, connectTimeoutMs(env, C) - C.ENGINE_START_RESERVE_MS);
}

// Block until isReady() holds or the deadline passes; true means ready. Synchronous on purpose, like the
// rest of the cold path: nothing needs the event loop before the engine is spawned (the client's
// `initialize` waits in the pipe for the engine to read it), and the heal path it replaces blocked the same
// way for up to five minutes, not for a share of the connect window. isReady() runs once more after the
// last sleep, so a build that lands right at the deadline still counts. Injectable for a fake-clock test.
export function waitUntilReady({ isReady, deadline, now = Date.now, sleep = sleepSync, pollMs = CONNECT.POLL_MS }) {
  for (;;) {
    if (isReady()) return true;
    const left = deadline - now();
    if (left <= 0) return false;
    sleep(Math.min(pollMs, left));
  }
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

// A server that exits within this window of starting WITHOUT having written its readiness marker is
// treated as a startup failure (an import error against a half-built / just-updated venv) and triggers
// the one self-heal retry. The AUTHORITATIVE signal is the engine's readiness marker (servedInit,
// below), consulted FIRST — a crash with the marker present is post-init regardless of how long it ran.
// This window is only the SECONDARY tie-breaker used when the marker is ABSENT: it is deliberately wide
// so a slow-surfacing startup import failure (a cold machine / slow disk taking well over a second to
// fault) still gets the heal instead of being misread as post-init. A marker-less post-init crash inside
// the window is bounded by the MAX_RESTARTS crash-loop cap.
const EARLY_FAILURE_MS = 20000;

// Signals that mean the engine CRASHED (a hard fault), as opposed to a graceful terminate we or the OS
// requested (SIGTERM/SIGINT). A crash signal during STARTUP (e.g. SIGSEGV/SIGABRT while importing against
// a broken venv, before `initialize` is served) must NOT be mislabeled a clean exit — it has to fall
// through to the startup self-heal path, exactly like a non-zero startup exit code.
const CRASH_SIGNALS = new Set(["SIGSEGV", "SIGABRT", "SIGBUS", "SIGILL", "SIGFPE", "SIGKILL"]);

// PROBE_TIMEOUT_MS (the interpreter-probe / bootstrap-check spawnSync bound) is imported from
// _engine_resolve.mjs — its single home since review-r5.

// The readiness marker: one file PER SPAWN (0.11.2). Before each spawn the supervisor names a fresh file in
// KG_DATA (see serverLogDir / server.py resolve_data_dir) and hands its path to the child in
// KG_READY_MARKER. The engine writes it as its stdio serve loop comes up (server.readiness_lifespan) and
// removes it when it shuts down cleanly. A marker still there when the child has exited is the
// authoritative "this engine served `initialize`" signal the supervisor uses to classify a crash as
// post-init (exit clean) vs startup (relaunch in place). The supervisor reads it once and removes it.
//
// Through 0.11.1 every engine used ONE `.engine-ready`, and in an installed plugin KG_DATA is
// CLAUDE_PLUGIN_DATA: a single dir for every session on the machine, whatever its folder. So a session
// spawning its engine deleted the marker of another session's live engine, an engine shutting down
// cleanly deleted whichever marker was there, and a marker another session's engine had just written
// passed for this child's. A crash in an engine's first EARLY_FAILURE_MS could then be read either way
// wrong: a post-init crash as a startup failure (a venv rebuild nobody needed, then a relaunch onto a pipe
// the client had already handshaked) or a startup failure as post-init (no self-heal). A file whose name
// only this supervisor and its child know cannot be touched by another session, and it needs no mtime
// check against the spawn time either.
const READY_MARKER_ENV = "KG_READY_MARKER"; // kept in sync with server.READY_MARKER_ENV
const READY_MARKER_PREFIX = ".engine-ready-";
// What a sweep may remove: a per-spawn marker (prefix, supervisor pid, 12 hex digits) or the single
// marker of 0.11.1 and earlier. Nothing else in KG_DATA matches.
const READY_MARKER_FILE = /^\.engine-ready(?:-\d+-[0-9a-f]{12})?$/;
// A marker only decides how an exit inside EARLY_FAILURE_MS is read. One older than this belongs to an
// engine long past that window, or to one killed too hard to remove it while its supervisor died with it
// (both processes gone, nobody left to read it). Each supervisor sweeps those as it starts, so sessions
// that end that way cannot pile them up. An old session still running 0.11.1 or earlier clears its
// single marker before each spawn, so removing a stale one takes nothing from it either.
const READY_MARKER_STALE_MS = 60 * 60 * 1000;

// A fresh marker path for the next spawn: no other process, this supervisor's earlier children
// included, has been given it.
export function newReadyMarker(env = process.env) {
  return join(serverLogDir(env), `${READY_MARKER_PREFIX}${process.pid}-${randomBytes(6).toString("hex")}`);
}

// Did the child that was handed `marker` write it, i.e. begin serving? Absent means "not served", and
// the caller falls back to the wall-clock window.
export function markerServedInit(marker) {
  return Boolean(marker) && existsSync(marker);
}

// Remove a child's marker once its exit has been read: a crash leaves it behind, and the next spawn gets
// a new one.
export function clearReadyMarker(marker) {
  if (!marker) return;
  try {
    rmSync(marker, { force: true });
  } catch {
    /* best-effort */
  }
}

// Remove the readiness markers in `dir` older than `staleMs`; returns how many went. Best-effort: a dir
// that cannot be listed, or a file that vanishes or resists, is skipped.
export function sweepStaleReadyMarkers(dir = serverLogDir(), now = Date.now(), staleMs = READY_MARKER_STALE_MS) {
  let names;
  try {
    names = readdirSync(dir);
  } catch {
    return 0;
  }
  let swept = 0;
  for (const name of names) {
    if (!READY_MARKER_FILE.test(name)) continue;
    const p = join(dir, name);
    try {
      if (now - statSync(p).mtimeMs > staleMs) {
        rmSync(p, { force: true });
        swept += 1;
      }
    } catch {
      /* gone already, or not ours to remove */
    }
  }
  return swept;
}

// ----------------------------------------------------------------------------------------------------
// Supervision policy (pure + exported so tests exercise the decision table without spawning an engine).
// ----------------------------------------------------------------------------------------------------
export const SUPERVISOR = {
  EARLY_FAILURE_MS, // crash within this window = died during STARTUP, before serving `initialize` -> relaunch
  MAX_RESTARTS: 5, // startup retries within RESTART_WINDOW_MS before we declare a crash-loop and give up
  RESTART_WINDOW_MS: 60_000,
  BACKOFF_INITIAL_MS: 200,
  BACKOFF_MAX_MS: 5_000,
};

// Capped exponential backoff: 200, 400, 800, 1600, 3200, 5000(cap), 5000, …
export function backoffFor(consecutiveFailures, S = SUPERVISOR) {
  const n = Math.max(0, consecutiveFailures);
  return Math.min(S.BACKOFF_INITIAL_MS * 2 ** n, S.BACKOFF_MAX_MS);
}

// Pure restart policy. Given how/why the child exited and the recent restart history, return the action:
//   { action: "exit",      code, reason }   — stop the supervisor (clean shutdown / post-init / crash-loop)
//   { action: "heal",      reason }         — force a venv rebuild, then relaunch (early import failure)
//   { action: "relaunch",  reason }         — relaunch after backoff (a STARTUP retry only)
// `recentRestartCount` = startup-window unexpected exits within RESTART_WINDOW_MS (the caller prunes it).
//
// CRITICAL design point (why post-init crashes EXIT rather than relaunch). The engine runs with
// stdio:"inherit": Node never owns the JSON-RPC stream, so it cannot replay the per-connection MCP
// `initialize` handshake on a relaunch. That makes the two cases fundamentally different:
//   • A crash DURING STARTUP (before the engine served `initialize`) leaves the client's `initialize`
//     request still BUFFERED, unread, on the inherited stdin — a relaunched engine reads and answers it,
//     so an in-place heal/relaunch genuinely self-heals the cold-start race (§2.1, the original role).
//   • A crash AFTER the engine already answered `initialize` cannot be papered over: a relaunched engine
//     starts uninitialized, the client (seeing Node still alive) never re-handshakes AND gets no EOF, so
//     the connection looks alive but is dead — strictly WORSE than a clean disconnect. So we EXIT: Node
//     goes away, the pipe closes, the client detects the drop and reconnects with a fresh handshake.
// `servedInit` is the AUTHORITATIVE signal: the engine writes a readiness marker as its serve loop comes
// up (server.readiness_lifespan), so a crash with the marker present is post-init regardless of how long
// it ran — this is what fixes a fast post-init crash (a tool call that kills the engine in <5s) being
// mis-relaunched in place and stranding the client. `EARLY_FAILURE_MS` remains the FALLBACK proxy used
// only when the marker is absent (an older engine, or the marker write failed): the engine's
// import+startup is sub-second, so a crash within the window is overwhelmingly a startup failure. (Fully
// transparent post-init restart would require Node to PROXY the stream and replay the handshake — a
// larger change, deliberately deferred; see the header.)
export function restartDecision(
  { code, signal, ranForMs, shuttingDown, triedHeal, recentRestartCount, servedInit = false },
  S = SUPERVISOR
) {
  // A deliberate shutdown (we forwarded a term signal, the session is ending): ALWAYS a code-0 clean exit.
  // On Windows libuv maps kill(SIGTERM) to a numeric exit code (signum) with signal=null, so an ordinary
  // shutdown would otherwise surface that non-zero code (review-low) — force 0 when shuttingDown.
  if (shuttingDown) {
    return { action: "exit", code: 0, reason: "clean-exit" };
  }
  // A clean exit otherwise: a GRACEFUL terminate signal (SIGTERM/SIGINT that we did not flag as a
  // shutdown, or the OS asked for), or a zero/empty exit code. Honor it — do NOT relaunch. A CRASH signal
  // (SIGSEGV/SIGABRT/… — see CRASH_SIGNALS) is deliberately NOT short-circuited here: a hard fault during
  // startup, before `initialize` is served, must fall through to the startup self-heal logic below, so it
  // is handled just like a non-zero startup exit code instead of being mislabeled a clean exit.
  if ((signal && !CRASH_SIGNALS.has(signal)) || (!signal && !code)) {
    return { action: "exit", code: signal ? 0 : code ?? 0, reason: "clean-exit" };
  }
  // Died during STARTUP — i.e. WITHOUT having written its readiness marker (servedInit is the AUTHORITATIVE
  // gate: absent ⇒ startup) AND within the wide EARLY_FAILURE_MS window (the marker-absent secondary
  // tie-breaker, before serving the buffered `initialize`): self-heal in place.
  if (!servedInit && ranForMs < S.EARLY_FAILURE_MS) {
    // A near-instant non-zero exit looks like an import error against a half-built / just-updated venv
    // (the --check fast-path can pass on a stamp-fresh-but-broken venv): force ONE rebuild before retrying.
    if (!triedHeal) return { action: "heal", reason: "early-failure-heal" };
    // Repeated startup failures: stop thrashing — exit cleanly with a logged reason.
    if (recentRestartCount >= S.MAX_RESTARTS) return { action: "exit", code: 1, reason: "crash-loop-cap" };
    return { action: "relaunch", reason: "startup-retry" };
  }
  // Crashed AFTER serving `initialize` (marker present, or ran past the startup window) — relaunching onto
  // the held-open pipe would strand an uninitialized engine, so exit cleanly and let the client reconnect
  // with a fresh handshake (see the note above).
  return { action: "exit", code, reason: "post-init-exit" };
}

// Where the supervisor appends its events — resolved EXACTLY as the engine's data dir (server.py
// resolve_data_dir): KG_DATA if set, else <project>/.kg-data. In an installed plugin KG_DATA is set
// (== CLAUDE_PLUGIN_DATA), so Node and Python agree on the file; in a bare dev launch they may differ.
export function serverLogDir(env = process.env) {
  const data = clean(env.KG_DATA);
  if (data) return data;
  const proj = clean(env.KG_PROJECT_DIR) || clean(env.CLAUDE_PROJECT_DIR) || process.cwd();
  return join(proj, ".kg-data");
}

function serverLog(msg) {
  // Best-effort: a logging failure must NEVER break the supervisor. Python owns rotation of server.log;
  // the supervisor's few lines per restart ride along.
  try {
    const p = join(serverLogDir(), "server.log");
    mkdirSync(dirname(p), { recursive: true });
    appendFileSync(p, `${new Date().toISOString()} INFO supervisor [node ${process.pid}]: ${msg}\n`);
  } catch {
    /* swallow */
  }
}

// Get a build going without running it here: `bootstrap.py --background` spawns the detached worker and
// returns in milliseconds. The worker serializes on the provision lock, so when the SessionStart hook's
// worker is already building, this one waits for it and leaves as soon as the venv is current — and if
// that build failed, this one takes the lock and builds. No `--reconcile`: the per-session sweep (§1.8) is
// the hook's, and the old foreground catch-up never ran it either. stdio is ignored because bootstrap
// prints [bootstrap]… lines to stdout, which this process is about to hand to JSON-RPC.
// `force` drops install.stamp first so the worker cannot take bootstrap's ready fast path: the heal case,
// where the stamp MATCHES but the engine still fails to import — without it the worker would do nothing
// and the retry would relaunch the identical broken server.
function startBackgroundBuild(sysPy, force = false) {
  if (force) {
    try {
      rmSync(join(VENV_DIR, STAMP_NAME), { force: true });
    } catch {
      /* best-effort */
    }
  }
  const r = spawnSync(sysPy, [BOOTSTRAP, "--background", "--venv", VENV_DIR],
    { stdio: "ignore", timeout: PROBE_TIMEOUT_MS });
  if (r.error || r.status !== 0) {
    const why = r.error ? r.error.code || r.error.message : `exit ${r.status}`;
    process.stderr.write(`[burgess] could not start the background engine build (${why}).\n`);
    serverLog(`background build did not start (${why})`);
  }
}

// Ready means `bootstrap.py --check` passes. The stamp is the last thing a build writes, so while it is
// absent most polls cost one stat instead of two interpreter spawns (--check also asks the venv's own
// python for its ABI identity).
function venvReady(sysPy) {
  return existsSync(join(VENV_DIR, STAMP_NAME)) && stampFresh(sysPy);
}

// Start or join a background build and wait for it inside the connect window. True = ready to launch.
function catchUp(sysPy, deadline, force = false) {
  startBackgroundBuild(sysPy, force);
  return waitUntilReady({ isReady: () => venvReady(sysPy), deadline });
}

// The launcher is giving up on this connection, not on the build: say so where the user will look.
// Claude Code shows a failed server's stderr under /mcp, and server.log keeps a line for later.
function reportStillProvisioning() {
  const timeout = connectTimeoutMs();
  const log = join(dirname(VENV_DIR), PROVISION_LOG_NAME);
  process.stderr.write(
    "[burgess] The engine's Python environment is still being set up in the background. That is " +
      "normal on the first session after an install or an update, and can take a few minutes. Claude " +
      `Code gives an MCP server ${Math.round(timeout / 1000)}s to start (MCP_TIMEOUT), so this launch stops ` +
      "here; the setup keeps going. Once it has finished, reconnect the burgess server from /mcp, or start " +
      `a new session. Progress: ${log}. To make a first session wait for the setup instead, start Claude ` +
      "Code with MCP_TIMEOUT=600000.\n"
  );
  serverLog(`venv not ready inside the connect window (MCP_TIMEOUT=${timeout}ms); exiting, the background build continues`);
}

// The venv is fresh only when bootstrap.py --check exits 0 (interpreter present AND install.stamp
// matches the current pyproject). Checking interpreter existence alone would launch a STALE venv after
// a deps-changing update left the old interpreter in place. --check prints nothing, so it is JSON-RPC-safe.
function stampFresh(sysPy) {
  if (!sysPy) return false;
  const r = spawnSync(sysPy, [BOOTSTRAP, "--check", "--venv", VENV_DIR], {
    stdio: ["ignore", "ignore", "ignore"],
    timeout: PROBE_TIMEOUT_MS,
  });
  // A timed-out (r.error) or non-zero --check is "not fresh" -> start or join a build and wait (catchUp)
  // (review-low).
  return !r.error && r.status === 0;
}

// The supervision loop, with every side-effecting dependency injectable so a test can drive the REAL
// loop (simulate an engine-child crash, assert relaunch-within-backoff, assert the crash-loop cap exits
// cleanly) without spawning a real engine or killing the test process. main() binds the production deps.
//   spawnEngine(marker) -> a child-process-like EventEmitter emitting "error"(err) and "exit"(code, signal);
//                    `marker` is the readiness-marker path this child is handed (KG_READY_MARKER)
//   exit(code)    -> terminate the supervisor (default process.exit)
//   heal()        -> force a venv rebuild + re-resolve the interpreter (early-import-failure recovery);
//                    returning `false` means the rebuild cannot finish while this connection can still be
//                    served, and the supervisor exits instead of relaunching (any other value: relaunch)
//   now()         -> monotonic-ish ms clock; schedule(fn, ms) -> deferred relaunch (default setTimeout)
export function createSupervisor({
  spawnEngine,
  exit = (code) => process.exit(code),
  heal = () => {},
  now = () => Date.now(),
  schedule = (fn, ms) => setTimeout(fn, ms),
  cancel = (handle) => clearTimeout(handle),
  log = serverLog,
  onChildSpawned = () => {},
  // The readiness-marker path for the next child: a new one per spawn, never shared (0.11.2).
  newMarker = () => newReadyMarker(),
  // Did the child that just exited write the marker it was handed (i.e. begin serving)? Injectable so
  // tests drive the post-init vs startup classification without a real engine; production reads the file.
  servedInit = (marker) => markerServedInit(marker),
  // Remove a child's marker once its exit has been read. Injectable so the loop tests stay hermetic (no
  // real filesystem marker).
  clearMarker = (marker) => clearReadyMarker(marker),
  policy = SUPERVISOR,
} = {}) {
  let child = null;
  let startedAt = 0;
  let shuttingDown = false; // set when WE forward a term signal -> a subsequent child death is "clean"
  let consecutiveFailures = 0; // escalates the startup-retry backoff
  let restartTimes = []; // timestamps of startup-window retries, pruned to RESTART_WINDOW_MS (crash-loop guard)
  let triedHeal = false; // whether we already spent the one early-failure venv rebuild
  let pendingRelaunch = null; // a scheduled backoff relaunch, so shutdown can cancel it and exit promptly

  function markShutdown(sig) {
    shuttingDown = true;
    try {
      child?.kill?.(sig);
    } catch {
      /* child already gone */
    }
    // A SIGINT/SIGTERM arriving mid-backoff (no live child to kill) must not leave Node idling until the
    // pending relaunch timer fires — cancel it and exit promptly so the session tears down cleanly.
    if (pendingRelaunch !== null) {
      cancel(pendingRelaunch);
      pendingRelaunch = null;
      exit(0);
    }
  }

  function spawnOnce() {
    const marker = newMarker(); // this child's own readiness marker: no other process writes or removes it
    startedAt = now();
    child = spawnEngine(marker);
    child.on("error", (e) => {
      // A spawn-level error (ENOENT, EACCES) is not a server crash-loop — the binary can't run at all,
      // so relaunching would just thrash. Log it and give up cleanly.
      log(`spawn error: ${e.message}`);
      process.stderr.write(`[burgess] failed to start engine server: ${e.message}\n`);
      exit(1);
    });
    child.on("exit", (code, signal) => onChildExit(code, signal, marker));
    onChildSpawned(child);
    return child;
  }

  function onChildExit(code, signal, marker) {
    child = null;
    const t = now();
    const ranForMs = t - startedAt;
    const served = servedInit(marker); // did this child write its readiness marker (begin serving)?
    clearMarker(marker); // read once; a crash leaves it behind, and a relaunch is handed a new one
    restartTimes = restartTimes.filter((ts) => t - ts < policy.RESTART_WINDOW_MS);
    const decision = restartDecision(
      { code, signal, ranForMs, shuttingDown, triedHeal, recentRestartCount: restartTimes.length, servedInit: served },
      policy
    );
    log(
      `engine exited code=${code} signal=${signal} ranForMs=${ranForMs} servedInit=${served} -> ${decision.reason}`
    );

    if (decision.action === "exit") {
      if (decision.reason === "crash-loop-cap") {
        process.stderr.write(
          `[burgess] engine crash-looped during startup (${restartTimes.length} retries in ` +
            `${policy.RESTART_WINDOW_MS / 1000}s); giving up. See ${join(serverLogDir(), "server.log")}.\n`
        );
      }
      exit(decision.code);
      return;
    }

    if (decision.action === "heal") {
      triedHeal = true;
      // FORCE a rebuild so a stamp-fresh-but-broken venv is reinstalled, then re-resolve python. When the
      // rebuild is still running at the connect deadline, exit rather than relaunch: the worker may be
      // rewriting the venv in place, and the client is about to give up on this connection anyway.
      if (heal() === false) {
        log("early-failure heal did not finish inside the connect window -> exit");
        exit(1);
        return;
      }
      log("relaunching after early-failure heal");
      spawnOnce();
      return;
    }

    // startup retry with capped exponential backoff (only reached for sub-EARLY_FAILURE_MS exits)
    restartTimes.push(t);
    const backoff = backoffFor(consecutiveFailures, policy);
    consecutiveFailures += 1;
    log(`relaunching in ${backoff}ms (consecutiveFailures=${consecutiveFailures}, recent=${restartTimes.length})`);
    pendingRelaunch = schedule(() => {
      pendingRelaunch = null;
      if (!shuttingDown) spawnOnce();
    }, backoff);
  }

  function installSignalHandlers() {
    // A forwarded SIGINT/SIGTERM means the SESSION is ending, so mark shuttingDown so the child's
    // resulting death is treated as clean (no relaunch). Registered ONCE against the mutable `child`.
    process.on("SIGINT", () => markShutdown("SIGINT"));
    process.on("SIGTERM", () => markShutdown("SIGTERM"));
    process.on("exit", () => markShutdown("SIGTERM"));
  }

  function start() {
    spawnOnce();
  }

  return { start, installSignalHandlers, markShutdown };
}

function main() {
  const deadline = provisionDeadline(Date.now());
  const sysPy = systemPython();
  let py = enginePython(VENV_DIR);

  // Cold (no interpreter) OR stale (interpreter present but stamp out of date): get a background build
  // going and wait for it inside the connect window. A stale venv is NOT launched in the meantime: the build
  // upgrades it in place, so its packages can be half-swapped at any moment.
  if (!py || !stampFresh(sysPy)) {
    if (sysPy) {
      if (!catchUp(sysPy, deadline)) {
        reportStillProvisioning();
        process.exit(1);
      }
      py = enginePython(VENV_DIR);
    }
  }

  if (!py) {
    process.stderr.write(
      "[burgess] engine venv is not provisioned and no Python >= 3.10 was found " +
        "on PATH. Install Python 3.10+ and start a new session.\n"
    );
    process.exit(1);
  }

  // kg_engine resolves off PYTHONPATH=scripts (.mcp.json already sets this; belt-and-braces for a
  // direct/dev launch). The KG_* env vars come through from .mcp.json untouched.
  const env = withPythonpath(process.env, SCRIPTS);

  const sup = createSupervisor({
    // stdio: "inherit" — the engine owns the real JSON-RPC stdio; Node's fds ARE the client pipe, kept
    // open across restarts, so the OS-level connection is never torn down when the engine relaunches.
    spawnEngine: (marker) =>
      spawn(py, ["-m", "kg_engine.server"], { stdio: "inherit", env: { ...env, [READY_MARKER_ENV]: marker } }),
    heal: () => {
      if (!sysPy) return true; // nothing to rebuild with: relaunch as is, as before
      // Same connect window as the initial wait, so the heal can only use what the startup left of it.
      // The wait blocks the loop (and so markShutdown) for at most that remainder, where the foreground
      // heal it replaces could block teardown for five minutes (review-low).
      if (!catchUp(sysPy, deadline, true)) {
        reportStillProvisioning();
        return false;
      }
      const fixed = enginePython(VENV_DIR);
      if (fixed) py = fixed;
      return true;
    },
  });
  sup.installSignalHandlers();
  installProcessGuards();
  const swept = sweepStaleReadyMarkers();
  serverLog(`supervisor up (py=${py})${swept ? ` (removed ${swept} stale readiness marker${swept === 1 ? "" : "s"})` : ""}`);
  sup.start();
}

// Last-resort process guards, installed only on the real supervisor path (never on import, so the
// launcher tests are unaffected). Node >= 15 terminates the process on an unhandled promise rejection:
// for a long-running supervisor whose whole job is to keep the engine alive, a stray rejection in a
// logging or heal path would silently take the MCP server down with no trace in server.log. Log it and
// KEEP SUPERVISING — the child engine is the thing that matters, and nothing here awaits a promise whose
// failure invalidates supervisor state. An uncaughtException is different: state may be inconsistent, so
// record it and exit non-zero, which is what would have happened anyway — except now it is written down
// (review-r11).
function installProcessGuards() {
  process.on("unhandledRejection", (reason) => {
    serverLog(`unhandled rejection (supervisor continues): ${reason?.stack || reason}`);
  });
  process.on("uncaughtException", (err) => {
    serverLog(`uncaught exception: ${err?.stack || err}`);
    process.exit(1);
  });
}

// Only supervise when invoked as the entry script — importing this module (the launcher tests import the
// pure helpers) must NOT spawn an engine or probe the venv. Compare REALPATHS rather than file URLs: the
// plugin runs `node <abs>/launch_server.mjs` where <abs> may traverse a symlinked cache dir (e.g.
// ~/.claude/plugins/cache/...), so a raw URL string compare could be FALSE and the server would silently
// never start. realpathSync resolves both sides to the same inode; a `node -e` import has no script argv[1]
// (so it short-circuits false) — exactly the no-spawn behavior the tests rely on.
function _invokedAsMain() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return realpathSync(entry) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}
if (_invokedAsMain()) {
  main();
}
