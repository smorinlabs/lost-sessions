# 0006. `lost-sessions` — plugin design

- **Status:** Accepted
- **Type:** Architecture and CLI contract
- **Created:** 2026-11-12
- **Applies to:** the whole `lost_sessions` package

**Purpose.** This is the agreed design for turning `lost-sessions` into a standalone, pluggable Python package (planning task T6). It folds every decision taken on 2026-11-12 into one design. The research it rests on is [research 0001](../research/0001-llm-plugin-pattern.md) (how `simonw/llm` does plugins, with sources).

**Implementation choices made in T6 (2026-11-12).**
- Section 7.3: the **CLI factory** (`build_cli()`) is used, not module reload. `main()` calls `load_plugins()` and then `build_cli()`; tests build a fresh CLI after registering fake plugins. Recorded as a deviation in Section 9.
- Section 11 checks resolved from source: `lineage` is `{kind: "subagent" | "fork", parent_id}`; `tmux` is passed through as any JSON value (no live registry entry carries one); the original script reads `id`, `tool`, `live`, `spawn_dir`, `created`, `updated`, `title`, `name` and `resume`.
- Section 7.2 omits three flags that the original script has and that the Section 8 contract keeps: `--all`, `--hide-running` and `--include-helpers` on `recover`, `list` and `open`.
- Port sources: `smorin/smorin-bootstrap` at `713e443` (`utils/bin/lost-sessions`, 118 passing tests) and `smorinlabs/smorinlabs-skills` at `cf83bf1` (`session-inventory`).

**Status labels.** **Decided** = answered by Steve on 2026-11-12. **Design** = my concrete shape inside a decided frame; T6 may refine it without asking. **Assumption** = not confirmed; T6 confirms before relying on it. **Fact** = read in source or observed.

---

## 1. Decision log

| ID | Question | Decision |
|---|---|---|
| Q-B | Are agent tools plugins too? | **Yes: two plugin kinds now.** Session managers (Herdr, Rex) and agent tools (Claude Code, Codex, Muse, OpenCode). `lost-sessions` is standalone: the scanning code in `session-inventory` moves into the package, and the `find_inventory()` dependency goes away. |
| Q-F | Entry-point group | **One group, `lost_sessions`**, like `llm`'s single `llm` group. A plugin implements whichever hooks it needs. External packages are named `lost-sessions-<name>`. |
| Q-E | How built-ins register | **A `DEFAULT_PLUGINS` list, exactly as `llm` does.** The six built-ins are imported by module path after third-party entry points, so they load even under `LOST_SESSIONS_LOAD_PLUGINS=''` and in tests. |
| Q-A | CLI framework | **`click`, with `register_commands(cli)` copied exactly.** Plugins can add subcommands. |
| Q-I | What "identical behavior" means | **The contract is what scripts and people depend on** (Section 8). Help layout and usage-error wording may change. |
| Q-G | Session record | **A Pydantic model, `Session(BaseModel)`, with `session-inventory`'s 22 field names**, plus `restored_by` in place of the ad-hoc `herdr` key. |
| Q-G2 | Pydantic scope | **Every data object is a Pydantic model; this is the project standard** (2026-11-12). That includes `Destination`, `Opened`, `HistoryEntry`, the inventory models, and the `last-list.json` listing. The plugin base classes with methods (`AgentTool`, `SessionManager`) stay plain abstract classes. |
| Q-D | Labels and refusals | **Core owns them; plugins supply facts.** Managers can add a manager-specific refusal. |
| Q-H | The skill's `session-inventory` | **`lost-sessions` is the single source.** It exposes a stable Python API `lost_sessions.inventory.collect()` (returns an `Inventory` model, Section 5.2) **and** a `lost-sessions inventory --json` command. The skill switches to the library in a follow-up project in `smorinlabs-skills`. |
| Q-C2 | Plugin install | **`install` / `uninstall` commands that drive `uv tool install`.** The plugin list comes from the environment. The commands can print the equivalent `uv` and `pip` lines. They never run `pip`. (Supersedes Q-C.) |
| Q-J | Compatibility of stored data | **Backward and forward compatible, with a version** (2026-11-12). Any missing field prints `?`. Unknown fields and newer versions are kept and shown, never rejected. Every line written gets a schema number, following how Claude Code and Codex evolve their stores (Section 8.1). |

**Already decided before T7** (from the T6 brief): repo `smorinlabs/lost-sessions`, PyPI name `lost-sessions`, built from `smorinlabs/py-launch-blueprint`. Herdr and Rex ship built in, using the same interface as third-party plugins. `smorin-bootstrap` later installs the package instead of carrying the script.

---

## 2. Architecture

The runtime has three layers. The CLI calls core. Core calls plugins only through the pluggy plugin manager.

```
 lost-sessions (click group)  <-- register_commands(cli): plugins may add subcommands
        |
        v
 core: select lost sessions, label, refuse, open, log history
        |                                   |
        | register_agent_tools              | register_session_managers
        v                                   v
 AgentTool plugins                    SessionManager plugins
 claude codex muse opencode           herdr rex            (built-in, DEFAULT_PLUGINS)
 lost-sessions-<agent> ...            lost-sessions-<mgr>  (third-party, entry points)
        |                                   |
        +-- scan() -> list[Session]         +-- restored_ids(), destinations(), plan(), open(), focus_command()
```

How to read it: data flows down and back up. One `lost-sessions recover` run goes like this:
1. Core asks every agent plugin to `scan()`.
2. Core removes the sessions that any manager will restore itself (`restored_ids()`).
3. Core labels the rest and shows the menu.
4. Core hands the chosen session to the chosen manager's `open()`.

`--print` stays in core; it needs no manager.

---

## 3. Package layout (Design)

```
lost_sessions/
  __init__.py          # public API: hookimpl, Session, AgentTool, SessionManager, get_plugins
  hookspecs.py         # HookspecMarker("lost_sessions"), HookimplMarker("lost_sessions"), three hookspecs
  plugins.py           # pm = PluginManager("lost_sessions"); DEFAULT_PLUGINS; load_plugins()
  models.py            # Pydantic: Session, ScanResult, SourceStatus, Destination, Opened, HistoryEntry
  agents.py            # AgentTool base class + ScanContext (shared process table, home, since)
  managers.py          # SessionManager base class
  inventory.py         # collect(tools) -> Inventory; filter(...) for --live/--since/--include-subagents (stable public API, Q-H)
  core.py              # boot time, window, lost-session selection, labels, refusals (Q-D)
  history.py           # ${XDG_STATE_HOME:-~/.local/state}/lost-sessions/history.jsonl
  installer.py         # install / uninstall (Q-C2)
  menu.py              # Textual menu; Textual imported lazily inside functions (keeps --help fast)
  cli.py               # click group; load_plugins(); pm.hook.register_commands(cli=cli)
  default_plugins/
    __init__.py
    claude.py codex.py muse.py opencode.py    # AgentTool built-ins (ported scan_<tool>())
    herdr.py rex.py                           # SessionManager built-ins
```

`DEFAULT_PLUGINS` lists the six `lost_sessions.default_plugins.*` modules (Q-E).

---

## 4. Hookspecs (Decided shape; names Design)

```python
# lost_sessions/hookspecs.py
from pluggy import HookimplMarker, HookspecMarker

hookspec = HookspecMarker("lost_sessions")
hookimpl = HookimplMarker("lost_sessions")


@hookspec
def register_agent_tools(register):
    "Register AgentTool instances that find sessions of one agent (Claude Code, Codex, ...)"


@hookspec
def register_session_managers(register):
    "Register SessionManager instances that can restore or open sessions (Herdr, Rex, ...)"


@hookspec
def register_commands(cli):
    "Register additional click commands, e.g. 'lost-sessions mycommand ...'"
```

These follow `llm`'s style: every hook is a `register_*` callback. Behavior lives on the registered object, not in more hooks. A built-in plugin looks like this:

```python
# lost_sessions/default_plugins/herdr.py
from lost_sessions import hookimpl, SessionManager


class HerdrManager(SessionManager):
    name = "herdr"
    display_name = "Herdr"
    ...


@hookimpl
def register_session_managers(register):
    register(HerdrManager())
```

**Design: name clashes.** Core's `register` closure rejects a second plugin with the same `name`. It warns on stderr and keeps the first one, so built-ins win because pluggy calls them first. **Do not** iterate `pm.get_plugins()` to get an order: it returns a `set` (Fact, from the research).

---

## 5. Data models (Decided: Pydantic)

### 5.1 `Session` (Q-G)

Field names are exactly those of `new_record()` in `session-inventory`. This keeps `inventory --json` identical to `session-inventory list --json`.

```python
class Session(BaseModel):
    tool: str
    id: str
    name: str | None = None
    name_resumable: bool = False
    title: str | None = None
    spawn_dir: str | None = None
    branch: str | None = None
    created: str | None = None
    updated: str | None = None  # ISO 8601 strings, as today
    transcript: str | None = None
    lineage: ... = None
    archived: bool = False
    unreadable: bool = False
    live: Literal["yes", "no", "unknown"] = "no"
    live_basis: str | None = None
    live_host: str | None = None
    pid: int | None = None
    tmux: ... = None
    resume: str | None = None
    resume_by_name: str | None = None
    resume_blocked: str | None = None
    export_command: str | None = None
    restored_by: tuple[str, str] | None = Field(
        default=None, exclude=True
    )  # (manager display_name, label) set by core; not in inventory JSON
    hidden: bool = Field(
        default=False, exclude=True
    )  # replaces the "_hidden" key (subagents)
```

**Design notes.** `...` marks a type T6 reads from the scanner code; I did not trace `lineage` and `tmux`. `restored_by` and `hidden` are excluded from JSON, so the output of `inventory --json` matches the old field set.

### 5.2 Other models

| Model | Replaces | Fields (Design) |
|---|---|---|
| `Inventory` | the `(sessions, census, sources, failed)` tuple from today's `collect()` | `sessions: list[Session]`, `census: dict[str, Census]`, `sources: dict[str, SourceStatus]`, `failed: list[str]`. This is the stable API return value. It carries everything `inventory --json` and the skill need for the `{"sessions", "census", "sources"}` envelope and the exit-1 error. Today's `collect()` takes no `since`; `cmd_list` filters afterwards, and `inventory.filter()` keeps that split. |
| `ScanResult` | the `(recs, src, hidden)` tuple from `scan_<tool>()` | `sessions: list[Session]`, `source: SourceStatus`, `hidden_subagents: int` |
| `SourceStatus` | the `src` dict | `status` (`ok` or `error`), `message`, plus the existing keys |
| `Destination` | the `HerdrTarget` and `RexTarget` dataclasses (lines 235–247) | A base model `manager: str`, `label: str`, `id: str | None` (None = created on first use). Each manager subclasses it for its own fields, for example `HerdrDestination.session` and `RexDestination.current`, so core never names Herdr or Rex fields. Mutable (not frozen), because `id` is filled in after first use. |
| `Opened` | the `entry["opened"]` dict | `manager: str` plus `ids: dict[str, str]`. The keys are defined by each manager and are printed generically as `key=value`, as `format_entry()` does today. It serializes back to the same flat JSONL keys (`rex_session`, `rex_window`, …). Fixed per-manager fields would put Herdr and Rex knowledge into core and block third-party managers. |
| `HistoryEntry` | the dict built in `execute()` | `time`, `action`, `tool`, `id`, `about`, `dir`, `commands`, `opened`, `result`, `note`; serialized to the **same JSONL keys and order** (Section 8). Writing is strict. **Reading is lenient** (`extra="allow"`, every field defaulted), because `history` must keep showing old or hand-edited lines, as the tolerant `format_entry()` (`e.get(..., '?')`) does today. |
| `Listing` | `last-list.json` (the numbered list that `open 3` refers to) | the numbered rows and when they were written; read leniently, like history |

**Decided (Q-G2):** all of these are Pydantic models. The plugin base classes `AgentTool` and `SessionManager` stay plain abstract classes with methods.

**Measured cost (2026-11-12, Pydantic 2.14.3, this Mac, warm runs):**
- importing Pydantic: about 50 ms;
- defining 8 model classes: about 10 ms;
- validating 500 sessions of 23 fields each: about 1 ms.

That is paid on every command, including `--help`. It is acceptable, but core must keep Textual imported lazily, as the script does today (L662), so the two costs do not stack.

---

## 6. Plugin contracts (Design)

### 6.1 `AgentTool` — finds and resumes one agent's sessions

| Member | Purpose | Ported from |
|---|---|---|
| `name` | `"claude"`, `"codex"`, … The value of `Session.tool` and of `inventory --tool`. | `TOOLS` |
| `scan(ctx: ScanContext) -> ScanResult` | Read this agent's store, read-only, and set `live` from `ctx.processes`. | `scan_claude/codex/muse/opencode()` |
| `resume_args(session) -> list[str]` | The command that resumes a session, e.g. `["codex", "resume", id]`. | `resume_args()` (L258) |
| `is_helper(session) -> bool` | Throwaway helper runs that are hidden by default (Codex Companion tasks). | part of `is_helper()` (L157) |

`ScanContext` carries `home`, `since` and one shared process table. Core runs the `processes()` scan once and passes it to every agent, as `collect()` does today.

### 6.2 `SessionManager` — restores or opens sessions

| Member | Purpose | Ported from |
|---|---|---|
| `name`, `display_name` | `"herdr"` / `"Herdr"`. `name` becomes `open --herdr` and the menu action. | `ACTIONS` (L36) |
| `click_options() -> list[click.Option]` | Manager options that core attaches to `recover`, `open` and `workspaces`, e.g. `--workspace`, `--herdr-session`, `--rex-session`. | `build_parser()` (L1137–1143) |
| `available() -> bool` | Is the binary on `PATH` and reachable? | `herdr_workspaces()`, `rex_sessions()` |
| `restored_ids(boot) -> dict[str, str]` | IDs this manager restores by itself, mapped to a label such as `"main"`. Rex returns `{}`. | `herdr_index()` (L146) |
| `destinations(opts) -> list[Destination]`, `default_destination(opts)` | Where sessions can be opened. | `Destinations` class (L568) |
| `plan(session, dest) -> list[list[str]]` | Commands shown in previews. | `plan()` (L282) |
| `open(session, dest) -> Opened` | Run the plan. | `execute()` (L363) |
| `focus_command(opened) -> list[str] \| None` | Bring an opened session to the front. | `focus_command()` (L423) |
| `refusal(session) -> str \| None` (optional) | A manager-specific block, e.g. "Herdr not reachable". | new (Q-D) |

**Herdr-only knowledge stays in the Herdr plugin.** Herdr tracks Claude and Codex through its own integrations, but not Muse or OpenCode. For those two it runs `herdr pane report-agent`. This is `REPORT_TOOLS` (L40) and `plan()` (L304–307).

### 6.3 Labels and refusals (Q-D: core owns them)

Core computes, in this order. It is the same order as `refusal()` / `state_label()` at L207–232 today:

| Condition | Label | Refusal for any manager (Print always allowed) |
|---|---|---|
| `live == "yes"` | `RUNNING` | `already running` |
| `live == "unknown"` | `maybe running` | — |
| `restored_by = (display_name, label)` set (some manager's `restored_ids()` has the ID) | `in <display_name>` | `already in <display_name> (<label>)` |
| `spawn_dir` missing | `folder missing` | `its folder no longer exists: <dir>` |
| `manager.refusal(session)` returns text | — | that text |

The cross-manager rule (a session Herdr restores is refused for Rex too) is enforced in core. That keeps today's behavior.

---

## 7. Loading and the CLI (Decided frame; code Design)

### 7.1 Loading

```python
DEFAULT_PLUGINS = tuple(
    f"lost_sessions.default_plugins.{m}"
    for m in ("claude", "codex", "muse", "opencode", "herdr", "rex")
)


def load_plugins():
    ...  # idempotent, like llm
    allow = os.environ.get(
        "LOST_SESSIONS_LOAD_PLUGINS"
    )  # read here, not at import (deviation)
    if allow is None and not _test_mode():
        pm.load_setuptools_entrypoints("lost_sessions")
    elif allow:
        ...  # per-distribution, as llm; keep our own plugin->distribution map
    for path in DEFAULT_PLUGINS:
        pm.register(importlib.import_module(path), path)
```

- `LOST_SESSIONS_LOAD_PLUGINS`: unset loads every plugin. `''` loads no third-party plugins (the built-ins still load). `a,b` loads only those distributions.
- Do not write to pluggy's private `pm._plugin_distinfo`, as `llm` does. Keep our own mapping instead.
- Plugins must import cheaply: the `--help` latency lesson from `llm` #732 and #949. Import heavy modules inside methods.

### 7.2 CLI surface

| Command | Status | Notes |
|---|---|---|
| `recover` | kept | Interactive menu; actions are Print plus one per registered manager. |
| `list` | kept | Numbered list of lost sessions. |
| `open REF… (--print \| --<manager>) [--focus [REF]]` | kept | `--herdr` and `--rex` are generated from manager names, so the spelling is unchanged. `REF@DEST` is unchanged. **T6 check:** `--focus` takes an optional value; in click use `is_flag=False, flag_value=…`. |
| `workspaces` | kept | Lists destinations from every manager. |
| `history [--json]` | kept | |
| `inventory [--tool T]… [--live] [--since W] [--include-subagents] [--json]` | **new (Q-H)** | Same flags and output as `session-inventory list`. JSON envelope: `{"sessions": [...], "census": {...}, "sources": {...}}`. Exit `1` with `{"error": {"code": "source_unreadable", ...}}` on stderr when a source fails. |
| `plugins [--all] [--hook H]…` | **new** | Copied from `llm plugins`. JSON list of `{name, hooks, version}`. Built-ins are hidden unless `--all`. |
| `install PKG…`, `uninstall PKG…`, both with `--print` | **new (Q-C2)** | Section 7.4. |

### 7.3 Design note: click binds commands at import

Click builds its command tree when `cli.py` is imported. Today `llm` calls `load_plugins()` and `register_commands` at import time. That conflicts with three parts of this design:
- generating `--<manager>` flags and `click_options()` from the registered managers;
- test fixtures that register fake managers after import (TS-2, TS-3, TS-5);
- reading `LOST_SESSIONS_LOAD_PLUGINS` per test, because the `_loaded` guard makes loading once per process.

There are two ways out. T6 picks one:

| Way | How | Effect |
|---|---|---|
| Reload, as `llm` does | Tests call `importlib.reload(cli)` after registering fakes, as in `llm`'s `test_register_commands`, and reset `_loaded`. | An exact copy. The tests are more fragile. |
| CLI factory (deviation) | `build_cli(pm)` creates the click group and calls `register_commands`. `main()` calls `load_plugins()` and then `build_cli()`. Tests build a fresh CLI after registering fakes. | Clean tests, and the env var is honored per build. Recorded in Section 9. |

### 7.4 `install` / `uninstall` (Q-C2, confirmed reading)

1. **Find the installed plugins in the environment.** Use `importlib.metadata.distributions()` and keep the ones that declare a `lost_sessions` entry point. The `lost-sessions` package itself is excluded.
2. **Detect how it was installed.** If `Path(sys.prefix, "uv-receipt.toml")` exists, this is a `uv tool` install. Only the file's existence is checked; it is never parsed.
3. **Build both commands.** The new list is the installed plugins plus (or minus) `PKG`.
   ```
   uv:   uv tool install lost-sessions --with <p1> --with <p2> ...
   pip:  <sys.executable> -m pip install PKG          (uninstall: -m pip uninstall PKG)
   ```
   Only one line applies to a given environment. In a `uv tool` environment the `uv` line applies; the `pip` line cannot run there, because those environments have no `pip`. In a plain virtualenv the `pip` line applies. The output labels which line applies.
4. **Act:**
   - With `--print`: print both lines and exit `0`.
   - In a `uv tool` install: run the `uv` line.
   - Anywhere else: print both lines, explain that nothing was run, and exit `1`.
   - **Never run `pip`.** Running it is what loses plugins on `uv tool upgrade` (`llm` #575, reproduced in T7).

**Accepted consequences.** Two things are lost at the next `install`: packages added by hand with `--with` that are not plugins, and a version pin on `lost-sessions` itself (pins live only in the receipt). `install` warns when that would happen.

**Facts behind this (observed with `uv` 0.11.29 on 2026-11-12):**
- Re-running `uv tool install X --with …` replaces the add-on list, so additions and removals both work.
- `uv tool upgrade --reinstall` keeps the listed add-ons.
- Packages installed behind `uv`'s back are dropped.
- `uv` tool environments have no `pip`.

---

## 8. "Identical behavior" contract for the port (Q-I)

| Must match the current script | May change |
|---|---|
| Subcommands, flag names, defaults, `REF@DEST` syntax | `--help` layout |
| Exit codes `0` / `1` / `2` (usage errors stay `2`) | Usage-error wording, provided it still names the bad flag or `@` |
| Stdout data of `list`, `open --print`, `workspaces`, `history` | |
| `history --json` output and the existing `history.jsonl` keys | New lines gain two keys, `schema` and `written_by` (Q-J). This addition is the one deliberate exception. |
| The selection window (`--since`, the default of 00:00 on the day before boot), helper hiding, the Herdr-restored rule | |

The current tests already assert exit codes and substrings, for example `test_bad_since_is_usage_error` checks `code == 2` and `"--since" in err`. So most assertions port unchanged.

---

### 8.1 Compatibility and versioning of stored data (Q-J)

**What Claude Code and Codex do today.** I observed this on this Mac on 2026-11-12, reading only key names and never content.

| Store | Version marker | How it evolves |
|---|---|---|
| Claude Code transcripts `~/.claude/projects/*/*.jsonl` (76 files) | Every line carries `version`, the app version that wrote it (`2.1.280`, `2.1.296`, `2.1.322` seen), plus a `type` field naming the kind of line. There is no schema number. | Additive. Newer files have new keys (`attributionSkill`, …) and new line types (`api-request`). Readers must ignore what they don't know. |
| Codex rollouts `~/.codex/sessions/**/rollout-*.jsonl` (62 files) | Lines are wrapped as `{timestamp, type, payload, ordinal}`. The first line, `session_meta`, carries `cli_version` (`0.167.0`, `0.167.1`). | Mostly additive, but not only. A newer file adds a wrapper key `metadata`, and the older file's `multi_agent_version` field is gone in the newer one. **Fields can disappear.** |
| Codex SQLite stores `~/.codex/state_5.sqlite`, `logs_2.sqlite`, … | Two layers. A generation number in the file name (`_5`) marks a breaking change: a new file, with the old one left behind. Inside, 62 numbered `sqlx` migrations upgrade the schema step by step. | Breaking changes get a new file; others are migrations. |
| Codex and Claude prompt history `~/.codex/history.jsonl`, `~/.claude/history.jsonl` | None. | Small, fixed key sets: `session_id, text, ts` on 2,563 lines, and `display, pastedContents, project, sessionId, timestamp` on 9,303 lines. They have not changed. |
| OpenCode database | A new table name, `session_v2`, alongside the old `session` table. | `session-inventory` already reads both and checks columns with `PRAGMA table_info` (lines 379–390). P64 added that after the old table stopped receiving rows. |

**Lesson (Inference).** None of them rejects old data. They stamp *who wrote it*, add fields freely, and mark only breaking changes. Fields can still vanish (the Codex case), so a reader must treat every field as optional.

**Rules for `lost-sessions` (Decided frame, Design detail).** These apply to `history.jsonl` and `last-list.json`:
1. **Stamp every new line** with `"schema": 1` (the format number) and `"written_by": "lost-sessions <version>"` (diagnostic, like Claude's `version` and Codex's `cli_version`).
2. **A line without `schema` is schema 0,** today's format. It reads with no conversion; its 10 keys are unchanged.
3. **Bump `schema` only for a breaking change:** a field renamed or removed, or a meaning changed. Adding a field never bumps it.
4. **Never rewrite old lines.** The log stays append-only, and no migration touches it.
5. **Reading never fails on content.** Unknown keys are kept (`extra="allow"`). A line with a newer `schema` is shown with the fields `lost-sessions` knows, plus a one-line note to upgrade. A line that is not valid JSON is shown as `? (unreadable line N)`, and the rest of the file still prints.
6. **A missing field prints `?`.** A field that is present but empty prints as empty. *Deliberate change:* today a missing `about`, `dir` or `note` prints empty; it will print `?`. A missing `time`, `action`, `result`, `tool` or `id` already prints `?`.
7. **`last-list.json` follows the same rules.** If it is unreadable or has an unknown schema, `open 3` says "run `lost-sessions list` first" rather than crashing.
8. **Agent plugins read the agents' stores just as defensively.** Every field is optional, unknown line types and keys are skipped, and versioned names are handled the way `scan_opencode` handles `session_v2` (check what exists, then read old and new). A store that changed shape yields `unreadable: true` for that session and a `sources` error, never a crash. This is the existing `session-inventory` behavior, kept.

Tests to add: TS-11 (below).

## 9. `llm` copied exactly versus deliberate deviations

| Element | Copied from `llm` | Deviation and reason |
|---|---|---|
| `pluggy`, marker pair, one module-level `PluginManager` | yes | |
| `register_*(register)` hooks, behavior on registered objects | yes | |
| `register_commands(cli)` with click | yes (Q-A) | |
| Built-ins via `DEFAULT_PLUGINS`, registered last | yes (Q-E) | |
| One entry-point group, plugins named `<tool>-<name>` | yes (Q-F) | |
| `plugins [--all] [--hook]` | yes | |
| Pydantic for structured data | yes (`llm.Options`) | extended to `Session` and the other records |
| Allow-list environment variable | semantics yes | Read in `load_plugins()`, not at import, so tests can set it. |
| Distribution metadata for listings | | Our own map instead of the private `pm._plugin_distinfo`. |
| `install` / `uninstall` | the commands yes | They drive `uv`, never `pip` (avoids `llm` #575). |
| Test isolation | the idea yes | An explicit test-mode switch instead of `sys._called_from_test`, if T6 prefers. |
| CLI construction | | A `build_cli()` factory (chosen in T6; Section 7.3): plugin-generated flags, fresh CLIs in tests, and the env var honored per build. |

---

## 10. Test plan (Design)

| ID | Test |
|---|---|
| TS-1 | Test mode blocks third-party entry points; built-ins still load (Q-E). |
| TS-2 | Fixtures register fake `AgentTool` and `SessionManager` classes with `pm.register` and always `pm.unregister` in `finally`, as in `llm`'s `conftest.py`. |
| TS-3 | A contract suite runs against every registered agent and manager (the built-ins plus the fakes). |
| TS-4 | Scanner tests port from `smorinlabs-skills` `tests/test_session_inventory.py`, so each built-in agent plugin keeps its coverage. |
| TS-5 | The 118 tests in `tests/test_lost_sessions.py` port with the Section 8 contract. The fake `session-inventory` script (`FAKE_INV_EXIT`) is replaced by fake agent plugins. |
| TS-6 | `inventory --json` matches `session-inventory list --json` on the same fixture stores (a golden-file test). |
| TS-7 | Packaging: build the wheel, install it into a clean `uv tool` directory, and assert `lost-sessions plugins --all` lists all six built-ins. Install a fake external plugin and assert it is discovered. This is the counterpart of `llm`'s `test-llm-load-plugins.sh`. |
| TS-8 | Using a local index or `--find-links`: `install --print` output for both a `uv tool` environment and a plain virtualenv. In the `uv tool` case, `uv` runs, and the plugin survives `uv tool upgrade --reinstall`. |
| TS-9 | A test that fails if `uv`'s tool environment stops containing `uv-receipt.toml` (the detection signal). |
| TS-11 | Compatibility fixtures: a schema-0 history file (today's real format), a schema-1 file, a file with a fake `schema: 99` line containing unknown keys, a line missing fields (prints `?`), and a non-JSON line. `history` and `history --json` print all of them and exit `0`. The same cases cover `last-list.json`. |
| TS-10 | The live test `tests/test_lost_sessions_live.py` still passes against real Herdr and Rex. |

---

## 11. T6 work items

1. Create the repo from `py-launch-blueprint` (ask first, per T6).
2. Port the scanners from `session-inventory` into the four agent plugins, test-first (TS-4, TS-6). **This is the port queued from Q-B.**
3. Port `lost-sessions` into core, the two manager plugins and the click CLI, test-first (TS-1 to TS-5, TS-10).
4. Add the `inventory`, `plugins`, `install` and `uninstall` commands (TS-6 to TS-9).
5. Write the plugin-author docs: the hookspecs, the two base classes, the lazy-import rule, `lost-sessions-<name>` naming, and the `uv tool install --with` line.
6. The `smorin-bootstrap` PR that installs the package (T6 task 3, unchanged).
7. The Muse review install (T8, unchanged).

### Checks still open for T6 (not decisions; verify while building)

- Types of `lineage` and `tmux`, and which of the 22 fields the current `lost-sessions` actually reads.
- `install` when `lost-sessions` or a plugin comes from anywhere other than PyPI: an editable `-e .`, a local wheel, a git URL, or a pre-release. The `uv` line resolves names from PyPI, so the line must carry the original source. TS-7 and TS-8 need a local index or `--find-links` for the built wheel and the fake plugin.
- `install` rebuilding the `uv` environment that the running process lives in.
- click's optional-value `--focus`.
- The Textual menu code (L668 onward) was not read during design. Check how it consumes labels.

## 12. Follow-up outside T6 (Q-H)

A new project in `smorinlabs-skills`: switch `plugins/session/skills/session-agent-list/scripts/session-inventory` to import `lost_sessions.inventory.collect()` (which returns an `Inventory`) through a `uv` inline dependency (`# dependencies = ["lost-sessions>=X"]`). It keeps its CLI, `docs/session-inventory-cli.md`, `CONFORMANCE.md` and its tests. It is blocked until `lost-sessions` is on PyPI. Open check: does the Codex harness run `uv` inline dependencies the same way Claude Code does?

## 13. Rust (`brot`, T3)

This design does not decide anything for T3. See Section 10 of [research 0001](../research/0001-llm-plugin-pattern.md) for the three options: external binaries on `PATH`, compiled-in features, and WASM components.
