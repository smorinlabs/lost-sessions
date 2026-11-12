# 0020. lost-sessions replaces the template's example CLI, web service and container

- **Status:** Accepted
- **Date:** 2026-11-12
- **Deciders:** Steve Morin
- **Related:** [design 0006](../design/0006-lost-sessions-plugin-design.md);
  supersedes ADRs 0002–0004, 0006–0013, 0015–0017; amends ADR 0018

## Context

This repository was created from `smorinlabs/py-launch-blueprint` with
Template Press. The template ships a demonstration product: a noun-verb
example CLI (`projects`, `config`, `doctor`), a hexagonal `core/` library, a
FastAPI web service behind the `web` extra, OpenTelemetry tracing behind the
`otel` extra, and a container image published to GHCR.

`lost-sessions` is a command-line tool that recovers agent sessions after a
reboot. Its behavior is fixed by the original `lost-sessions` script, and its
architecture is the plugin design in design 0006.

## Decision

Remove the template's demonstration product and keep its repository
infrastructure:

- **Removed:** the example CLI and `core/` library, the web service and its
  OpenAPI snapshot and contract workflow, the `web` and `otel` extras, the
  Dockerfile and container publishing, `tach` and the hexagonal import
  contracts, and the CLI-convention documents (`EXAMPLECLI.md`,
  `EXAMPLEWEB.md`, design 0001 and 0002).
- **Kept:** release tooling, lint, type checking, commitlint, security
  scanning, the Sphinx docs site, `press verify`, and the meta tests.
- **Replaced:** the console command is `lost-sessions` (from
  `lost_sessions.cli:main`). The package layout and CLI contract follow
  design 0006.

## Consequences

- The ADRs listed above describe code that no longer exists; they stay as
  history with status *Superseded by 0020*.
- ADR 0018's hook/CI parity still holds, minus `tach` and the OpenAPI
  snapshot check.
- CLI help snapshots are gone with the example CLI; the press rules no longer
  regenerate them.
