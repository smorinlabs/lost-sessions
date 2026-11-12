# `lost_sessions` — noun-verb CLI

`lost_sessions` is the gh-style entry point for this project. Commands follow a
`lost_sessions <noun> <verb>` shape and share one set of global flags, one output
contract, and structured logging out of the box.

## Architecture

The package is split into three layers under `src/lost_sessions/`:

| Layer | Path | Role |
|-------|------|------|
| Library (`core`) | `core/` | Pure logic + Pydantic models. No printing. Reused by every front-end. |
| CLI (`cli`) | `cli/` | Thin presentation: formats `core` results. One module per noun in `cli/commands/`. |
| Web (`web`) | `web/` | FastAPI service behind the `web` extra — same models, second front-end (`just serve`, `just test-web`). See [EXAMPLEWEB.md](EXAMPLEWEB.md). |

The result of every command is a Pydantic model in `core/models.py` — that
model *is* the JSON representation, and the renderer turns the same object into
human text, JSON, or Markdown.

## Global flags (on every command)

| Flag | Purpose |
|------|---------|
| `-o, --output [text\|json\|markdown]` | output format (default `text`; env `LOST_SESSIONS_OUTPUT`; config `output.format`) |
| `--json` | shorthand for `--output json` |
| `--output-file PATH` | write results to a file instead of stdout (format still set by `--output`) |
| `-v, --verbose` | raise console log level (`-v` info, `-vv` debug) |
| `-q, --quiet` | lower console log level to error |
| `--log-level LEVEL` | explicit console level, overrides `-v`/`-q` (env `LOST_SESSIONS_LOG_LEVEL`) |
| `--log-file [PATH]` | enable rotating file logging; bare flag uses the XDG state path (env `LOST_SESSIONS_LOG_FILE`) |
| `--no-color` | force color off (`NO_COLOR` env and config `output.color` also honored) |
| `--config PATH` | path to a TOML config file (overrides discovery; env `LOST_SESSIONS_CONFIG`) |
| `--token TEXT` | Py token (overrides `$LOST_SESSIONS_TOKEN`; never stored on disk) |
| `--no-input` | never prompt; fail instead (scripts/CI) |
| `-V, --version` | version + Python + platform (root) |
| `-h, --help` | help at every level |

## Output contract

- **Results** → stdout (pipe-safe), or the `--output-file` path when given.
  **Logs, messages, errors** → stderr, always.
- In `--json` mode, stdout is clean parseable JSON; errors become a structured
  `{"error": {"code", "name", "message", "error_code", …}}` object on stderr
  (`hint` and `traceback_path` appear when available; keys are append-only).
- Format never auto-switches on TTY: piped output formats the same as
  interactive output unless `-o`/`LOST_SESSIONS_OUTPUT`/config says otherwise.
- Color: auto-detected from the TTY; `--no-color` > `NO_COLOR` env >
  `output.color` config (`auto`/`always`/`never`) > auto-detect.
- **Pager**: interactive `text` output taller than the terminal pipes through
  `LOST_SESSIONS_PAGER` > `PAGER` > `less -FRX` (set-but-empty disables, git-style).
  Never when piped, with `--output-file`, in JSON/Markdown mode, or under
  `--no-input`; a missing pager binary falls back to plain output.
- **Terminal niceties** (text mode on a terminal only): cells may carry OSC-8
  hyperlinks and relative times via each model's `table_rows_rich()`
  (helpers in `core/format.py`). JSON stays raw fields + ISO-8601 UTC;
  Markdown uses the plain rows.

## Exit codes & error codes

Both tables are **stable and append-only** — scripts depend on them.
Exit codes are coarse (what should the shell do); error codes (`LOST_SESSIONS###`)
are fine-grained (what exactly happened) and may share an exit code. Human
output prints the error code after the message plus an actionable `hint:`
line when one exists; JSON carries them as `error_code` / `hint`.

| Exit | Meaning      | Error code | Meaning                                |
|------|--------------|------------|----------------------------------------|
| 0    | success      | —          |                                        |
| 1    | config error | `LOST_SESSIONS001`  | configuration missing/invalid          |
| 2    | auth error   | `LOST_SESSIONS002`  | token missing/rejected                 |
| 3    | API error    | `LOST_SESSIONS003`  | remote call failed                     |
| 3    | API error    | `LOST_SESSIONS005`  | project not found (`projects get`)     |
| 3    | API error    | `LOST_SESSIONS006`  | workspace not found (`--workspace`)    |
| 4    | I/O or bug   | `LOST_SESSIONS000`  | unexpected error (see crash log)       |
| 5    | interrupted  | `LOST_SESSIONS004`  | Ctrl-C / aborted prompt                |

Unexpected errors (`LOST_SESSIONS000`) always append the full traceback to
`<state>/lost_sessions/lost_sessions_crash.log` and print `full traceback: <path>` — nothing is
lost even without `--verbose`. Mistyped commands get git-style
"Did you mean …?" suggestions at every level.

## Usage

```bash
# Projects (noun) → list / get (verbs)
lost_sessions projects list
lost_sessions projects list --workspace "My Workspace" --json
lost_sessions projects list -o markdown
lost_sessions projects get 12345

# Config — set/get non-secret keys by dotted path (no network required)
lost_sessions config init                                 # guided setup (prompts on stderr)
lost_sessions config init --yes                           # accept current values, no prompts
lost_sessions config path
lost_sessions config get output.color
lost_sessions config set logging.level info               # writes [logging] level
lost_sessions config set output.color always --dry-run    # preview, write nothing
lost_sessions config set logging.file_level debug --yes   # skip the overwrite prompt
# the token is NEVER stored in config — pass --token or set $LOST_SESSIONS_TOKEN
lost_sessions config get token --json                     # masked; resolves from flag/env

# Diagnose setup (Python/platform, config file, token). Exits non-zero on errors.
lost_sessions doctor
lost_sessions doctor --json
lost_sessions doctor --bundle --json   # redacted snapshot to paste into a bug report

# Shell completion (bash, zsh, fish)
lost_sessions completion bash >> ~/.bashrc
eval "$(lost_sessions completion zsh)"
lost_sessions completion fish > ~/.config/fish/completions/lost_sessions.fish
```

Mutating commands (e.g. `config set`, `config init`) share a safety pattern:
`--dry-run` previews the change, an overwrite prompts for confirmation on
stderr, and `--yes` / `--no-input` make it non-interactive (the latter refuses
rather than prompting).

## Configuration file (TOML, XDG)

`lost_sessions` reads a TOML config file from an XDG-compliant location, namespaced
under the app and named so its purpose is obvious:

```
~/.config/lost_sessions/lost_sessions_config.toml          # $XDG_CONFIG_HOME/lost_sessions/lost_sessions_config.toml
```

```toml
# lost_sessions_config.toml — non-secret settings only, organized into tables
[output]
format = "text"   # text | json | markdown
color  = "auto"   # auto | always | never

[logging]
level = "warning" # console level
```

Config is discovered in layers, each overriding the previous: system
(`$XDG_CONFIG_DIRS`) → user (`$XDG_CONFIG_HOME`) → project
(`./lost_sessions_config.toml`); `--config` overrides discovery entirely. Per-setting
precedence: flag → env (`LOST_SESSIONS_*`) → project → user → system → default.

Secrets are **never** stored here — the token resolves from `--token` or
`$LOST_SESSIONS_TOKEN` only. The same XDG convention applies to other file kinds
(resolved in `core/paths.py`): data → `$XDG_DATA_HOME/lost_sessions/lost_sessions_db.db`,
state/logs → `$XDG_STATE_HOME/lost_sessions/lost_sessions.log`, cache → `$XDG_CACHE_HOME/lost_sessions/`.

On **Windows** the XDG variables still win when set, but the defaults are
platform-native: config → `%APPDATA%\lost_sessions`, data/state → `%LOCALAPPDATA%\lost_sessions`,
cache → `%LOCALAPPDATA%\lost_sessions\Cache` (matching `platformdirs` conventions).

First run: when no config file exists anywhere and stderr is an interactive
terminal, a one-time hint (recorded by a state marker) points at
`lost_sessions config init`. It never appears for scripts (`--no-input`, `-q`,
piped stderr, JSON mode).

## Structured logging (dual sink)

Logging uses [`structlog`](https://www.structlog.org/) rendered through stdlib
handlers, giving two independent sinks:

- **Console (stderr, always on)** — human-friendly colored output on a TTY,
  one-JSON-object-per-line when piped or in CI. Level: `WARNING` by default;
  `-v` info, `-vv` debug, `-q` error, `--log-level` explicit override
  (also `LOST_SESSIONS_LOG_LEVEL` / config `logging.level`).
- **Rotating file (off by default)** — enabled by `--log-file [PATH]`,
  `$LOST_SESSIONS_LOG_FILE`, or config `logging.file`. Bare `--log-file` writes to
  `$XDG_STATE_HOME/lost_sessions/lost_sessions.log` (logs are *state*, not config). Rotates at
  10 MB x 5 backups. Its level (`logging.file_level`, default `debug`) and
  format (`logging.format`: `text` or `json` JSONL; env `LOST_SESSIONS_LOG_FORMAT`)
  are independent of the console.

When both sinks are active they attach to the same logger: the logger floor is
the most verbose sink and each handler filters independently — e.g. a quiet
console at `warning` while the file captures full `debug` detail.

```bash
lost_sessions doctor -vv                          # debug detail on stderr
lost_sessions doctor --log-file                   # + JSONL/text file under XDG state
lost_sessions doctor --log-file /tmp/run.log --log-level error   # quiet console, full file
lost_sessions config set logging.file_level info --yes           # tune the file sink
```

Results on stdout are never mixed with logs — `lost_sessions ... --json | jq` stays
safe at any verbosity.
