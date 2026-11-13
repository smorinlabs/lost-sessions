# Writing plugins

lost-sessions finds agent sessions and reopens them only through plugins, the
way [`simonw/llm`](https://llm.datasette.io/en/stable/plugins/) does. The six
built-in plugins, Claude Code, Codex, Muse and OpenCode (agents) and Herdr and
Rex (session managers), use exactly the interface described here. A
third-party plugin is an ordinary Python package that registers more of them.

There are two kinds of plugin object:

| Kind | Base class | What it does | Built-in examples |
|---|---|---|---|
| Agent tool | `AgentTool` | Reads one agent's session store and reports its sessions | `claude`, `codex`, `muse`, `opencode` |
| Session manager | `SessionManager` | Restores sessions by itself after a reboot, opens sessions on request, or both | `herdr`, `rex` |

A plugin can also add subcommands to `lost-sessions`.

## Package layout

Name the distribution `lost-sessions-<name>` and the module
`lost_sessions_<name>`. Declare one entry point in the group `lost_sessions`:

```toml
[project]
name = "lost-sessions-acme"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["lost-sessions"]

[project.entry-points.lost_sessions]
acme = "lost_sessions_acme"
```

The entry-point name (`acme`) is the plugin's registration name. One module
can implement any of the hooks below.

## Hooks

Every hook is a `register_*` callback, as in `llm`: lost-sessions passes a
`register` function, and the plugin calls it with objects. Behavior lives on
those objects, not in more hooks.

```python
from lost_sessions import hookimpl


@hookimpl
def register_agent_tools(register):
    register(AcmeAgent())


@hookimpl
def register_session_managers(register):
    register(AcmeManager())


@hookimpl
def register_commands(cli):
    @cli.command(name="acme-status")
    def acme_status():
        "Show Acme's own status"
        print("ok")
```

| Hook | Called with | Register |
|---|---|---|
| `register_agent_tools(register)` | a callback | `AgentTool` instances |
| `register_session_managers(register)` | a callback | `SessionManager` instances |
| `register_commands(cli)` | the root `click` group | new commands, by decorating `cli` |

Names must be unique. When two plugins register the same `name`, the first one
wins and lost-sessions prints a warning; built-ins register first.

## Agent tools

An agent tool reads one agent's store **read-only** and returns its sessions.

```python
from lost_sessions import AgentTool, ScanContext, ScanResult, Session, SourceStatus
from lost_sessions.agents import RECORD_ERRORS, cd_prefix, unreadable_session


class AcmeAgent(AgentTool):
    name = "acme"  # the value of Session.tool and of `inventory --tool acme`
    needs_processes = False  # True if scan() reads ctx.processes

    def scan(self, ctx: ScanContext) -> ScanResult:
        store = ctx.home / ".acme" / "sessions"
        if not store.is_dir():
            return ScanResult(sessions=[], source=SourceStatus(status="absent", path=str(store)))
        sessions = []
        for path in sorted(store.glob("*.json")):
            try:
                sessions.append(self._record(path))
            except RECORD_ERRORS:  # a record of another shape: unreadable, not fatal
                sessions.append(unreadable_session("acme", path.stem, path))
        return ScanResult(sessions=sessions, source=SourceStatus(status="ok", path=str(store)))

    def _record(self, path) -> Session:
        ...  # parse one stored session into a Session

    def resume_args(self, session: Session) -> list[str]:
        return ["acme", "resume", session.id]
```

The contract:

- **`name`** is a short identifier, unique among agent tools.
- **`scan(ctx)`** returns a `ScanResult`: the sessions, the store's
  `SourceStatus` (`ok`, `absent` or `error`), and how many subagent sessions it
  hid (`hidden_subagents`). Raise `lost_sessions.agents.SourceError` when the
  whole store exists but cannot be read; lost-sessions reports that agent as a
  failed source and still lists the others.
- **Never write to the store**, and treat every stored field as optional. A
  record whose shape changed becomes `unreadable_session(...)`, never an
  exception. `RECORD_ERRORS` lists what a changed record can raise.
- **`ctx.home`** is the home directory to read; use it instead of
  `Path.home()`. `lost_sessions.agents.data_home(ctx.home)` honors
  `XDG_DATA_HOME`.
- **`ctx.processes`** maps PIDs to argv lists. It is filled only when some
  selected agent sets `needs_processes = True`; core runs `ps` once for all of
  them.
- **`resume_args(session)`** is the bare command that resumes a session.
  Set `resume_in_dir = False` if the agent resumes without changing into the
  session's folder, as Codex does.

Fill `Session.resume` with the full shell command when the session can be
resumed, or `resume_blocked` with the reason (`running`, `no_workspace`, ...).
Set `live` to `yes`, `no` or `unknown`, with `live_basis` saying why.

## Session managers

A session manager can do two separate things. **Restoring**: after a reboot it
reopens some sessions by itself, so lost-sessions must not offer them again.
**Opening**: it can open a chosen session on request.

### Restoring only

```python
import datetime as dt

from lost_sessions import SessionManager


class Keeper(SessionManager):
    name = "keeper"
    display_name = "Keeper"
    restores = True

    def restored_ids(self, boot: dt.datetime) -> dict[str, str]:
        """Session IDs Keeper will reopen, mapped to where (e.g. "work / tab")."""
        return {}
```

A session in `restored_ids()` is labeled `in Keeper` and refused for every
manager, as the built-in Herdr plugin does.

### Opening

Set `can_open = True` and implement the opening members. Only opening
managers get an `open --<name>` flag, a `workspaces` section and a key in the
`recover` menu.

| Member | Purpose |
|---|---|
| `open_help` | Help text for `open --<name>` |
| `menu_key`, `menu_order` | The one-letter `recover` key and its place in the action cycle (Rex is 1, Herdr 2) |
| `destination_noun` | What one destination is called, e.g. `("workspace", "workspaces")` |
| `new_placeholder` | How a later row previews a destination an earlier row creates, e.g. `"{workspace}"` |
| `click_options()` | Options added to `recover`, `open` and `workspaces`, e.g. `--workspace` |
| `destinations(options)` | A `Destinations` subclass: where sessions can open, and whether the manager is reachable |
| `plan(plan, dest)` | The commands that open `plan.session` in `dest`, as `Step` objects |
| `on_response(step, result, dest, fills)` | Read one successful response: fill placeholders such as `{pane}`, set `dest.id`, return the history `opened` keys or None |
| `blocked_note(error, fills)` | Text when a failed step means "opened, waiting at a prompt" |
| `focus_command(opened, options)` | The command that brings an opened session to the front |
| `warnings(labels, options)` | Warnings about destinations named on the command line |
| `workspaces_lines(dests)`, `unreachable()` | The `workspaces` section, and the error when the manager cannot be reached |

lost-sessions runs a plan step by step. A `Step` has `argv`, `cosmetic`
(a rename: a failure is only a note) and `opens` (the step must open
something according to its response, or the action fails). Placeholders in
`argv` are filled from earlier responses. Destinations are shared by
identity: rows sent to the same new destination share one object, so the
first row creates it and the rest open inside it.

## Rules for every plugin

- **Import cheaply.** Every plugin module is imported on every command,
  including `--help`. Import heavy libraries inside methods, not at module
  level (the lesson from `llm` issues #732 and #949).
- **Never run `pip` or write to user stores.** Read stores read-only; open
  sessions only through `plan()`.
- **Keep names stable.** `AgentTool.name` appears in the inventory JSON and in
  history; `SessionManager.name` is a CLI flag.

## Testing a plugin

Build a registry of your own, so the test does not depend on what else is
installed:

```python
from lost_sessions import core
from lost_sessions.plugins import load_plugins, make_plugin_manager

import lost_sessions_acme


def test_acme_is_registered(monkeypatch):
    monkeypatch.setenv("LOST_SESSIONS_LOAD_PLUGINS", "")  # built-ins only
    manager = make_plugin_manager()
    load_plugins(manager)
    manager.register(lost_sessions_acme, name="acme")
    assert "acme" in core.agent_tools(manager)
```

`LOST_SESSIONS_LOAD_PLUGINS` controls third-party loading: unset loads every
installed plugin, an empty value loads none, and `a,b` loads only those
distributions. Built-ins always load.

## Installing a plugin

```bash
lost-sessions install lost-sessions-acme          # in a `uv tool` install
uv tool install lost-sessions --with lost-sessions-acme   # the same, by hand
uv tool install lost-sessions --with-editable ./lost-sessions-acme   # while developing
lost-sessions plugins                              # lists it, with its hooks and version
```

`lost-sessions install` reinstalls the tool with all its plugins, keeping
where each came from (an index, a local wheel, git or an editable checkout).
It never runs `pip`, so plugins survive `uv tool upgrade`. Outside a
`uv tool` environment it prints the equivalent commands and runs nothing.
