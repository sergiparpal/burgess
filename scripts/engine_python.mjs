#!/usr/bin/env node
// Print the engine's Python interpreter, resolved exactly as the launcher resolves it (0.11.4).
//
// Commands whose Bash steps run engine scripts (/kg-eval, /kg-experiment and their subagents) call this
// instead of spelling a venv path. Through 0.11.3 they named `${CLAUDE_PLUGIN_DATA}/.venv/bin/python`,
// which does not exist on Windows (the venv's interpreter is `.venv\Scripts\python.exe` there), next to a
// development path that existed on no user's machine.
//
// venvDir() and enginePython() are the launcher's own rules, so the two can never disagree: the venv is
// KG_ENGINE_VENV, else <plugin data>/.venv, else <plugin root>/.venv; inside it, the interpreter is the
// pointer bootstrap writes (engine-python.txt), else the conventional path for the platform.
//
// Usage, from a command's text (Claude Code fills in both ${…} when the command loads):
//   PY="$(node "${CLAUDE_PLUGIN_ROOT}/scripts/engine_python.mjs" "${CLAUDE_PLUGIN_DATA}")"
// The plugin data dir comes as an argument because a command's Bash steps cannot count on finding
// CLAUDE_PLUGIN_DATA in their environment. Exit 1, with the reason on stderr, when no interpreter is
// provisioned yet.
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { clean, enginePython, venvDir } from "./_engine_resolve.mjs";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const dataArg = clean(process.argv[2]);
const env = dataArg ? { ...process.env, CLAUDE_PLUGIN_DATA: dataArg } : process.env;
const dir = venvDir(root, env);
const py = enginePython(dir);
if (!py) {
  process.stderr.write(
    `no engine interpreter under ${dir} yet: start a new Claude Code session so the plugin's ` +
      "SessionStart hook provisions it, then run the command again\n",
  );
  process.exit(1);
}
process.stdout.write(`${py}\n`);
