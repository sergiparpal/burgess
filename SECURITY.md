# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/sergiparpal/burgess/security/advisories/new)
rather than opening a public issue.

Expect an initial response within 7 days. If a report is confirmed, the fix and the advisory
are published together.

## Supported versions

Only the latest release on `main` receives security fixes.

## Scope

This repository is a Claude Code plugin: a set of skills and agents plus a local MCP server and
Python engine. It runs on the user's own machine and holds no credentials.

The parts most worth scrutiny are therefore:

- **The MCP server** — it is the plugin's tool surface, and it processes content that
  originates from user-supplied source documents.
- **Source-document ingestion** — extraction reads arbitrary Markdown or plain text the user
  points it at, including the scrubbing path.
- **The provisioner** (`scripts/bootstrap.py` and the `hooks/` launchers) — it creates a
  virtualenv and installs dependencies.
- **Dependency supply chain** — the runtime and `backend` extras.
- **Local state handling** — the graph canon, derived projections, and exported artifacts.

Out of scope: the accuracy, completeness, or usefulness of any extracted graph or generated
hypothesis, and any behaviour of the Claude model itself. A graph claim marked `hypothesized`
is by design unverified — that is a documented state, not a vulnerability.
