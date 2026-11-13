# lost-sessions

Recover the agent sessions a reboot dropped. `lost-sessions` finds Claude Code,
Codex, Muse and OpenCode sessions that started before the last boot and that no
session manager will restore, then prints their resume commands or reopens
them in Herdr or Rex.

Agents and session managers are plugins, the way
[`simonw/llm`](https://llm.datasette.io/en/stable/plugins/) does plugins. The
six built-ins use the same interface a third-party `lost-sessions-<name>`
package uses.

## Install

```bash
uv tool install "lost-sessions @ git+https://github.com/smorinlabs/lost-sessions@v0.1.0"
```

Python 3.13 or later. macOS and Linux.

## Use

| Command | What it does |
|---|---|
| `lost-sessions recover` | Interactive menu: choose Print, Rex or Herdr for each dropped session, then run them all |
| `lost-sessions list` | Numbered list of the dropped sessions in the window |
| `lost-sessions open REF… --print\|--rex\|--herdr [--focus [REF]]` | Print or open sessions without the menu; `REF@DEST` picks a destination |
| `lost-sessions workspaces` | The Herdr workspaces and Rex sessions you can open sessions in |
| `lost-sessions history [--json]` | Every action taken, from `${XDG_STATE_HOME:-~/.local/state}/lost-sessions/history.jsonl` |
| `lost-sessions inventory [--json]` | Read-only inventory of every agent session on this machine |
| `lost-sessions plugins [--all]` | Installed plugins, as JSON |
| `lost-sessions install PKG…` / `uninstall PKG…` | Add or remove plugins in the `uv tool` install |

The window is every session that started before the last boot and was active
since its start: by default 00:00 on the day before the boot. `--since` sets
that start, as a date (`--since 2026-11-09`) or a duration back from now
(`--since 3d`); pick an earlier start to widen the window. Running sessions
and sessions a manager restores are hidden unless `--all`.

## Library

```python
from lost_sessions.inventory import collect, select

inventory = collect()  # an Inventory: sessions, census, sources, failed
for session in select(inventory, live=True):
    print(session.tool, session.id, session.resume)
```

## Plugins

See [Writing plugins](docs/source/reference/plugins.md) for the hooks, the
`AgentTool` and `SessionManager` contracts, and how to test and install a
plugin. The design is in
[design 0006](docs/design/0006-lost-sessions-plugin-design.md).

## Develop

```bash
make bootstrap   # bare machines only: just + uv
just setup       # dev environment and git hooks
just check       # tests, lint, types, import contracts
```

See [AGENTS.md](AGENTS.md) for the full workflow.
