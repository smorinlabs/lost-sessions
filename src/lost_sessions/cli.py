"""The `lost-sessions` command line."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections.abc import Callable

import click

from lost_sessions import __version__
from lost_sessions.plugins import PluginManager, load_plugins, pm


def build_cli(manager: PluginManager = pm) -> click.Group:
    """Create the click group and let plugins add commands.

    A factory instead of an import-time group (design 0006, Section 7.3), so
    flags generated from registered plugins and plugins registered after
    import both reach a freshly built CLI.
    """

    @click.group(
        invoke_without_command=True,
        help=(
            "Recover Claude Code, Codex, Muse and OpenCode sessions that started "
            "before the last boot but that no session manager will restore."
        ),
    )
    @click.version_option(__version__, prog_name="lost-sessions")
    @click.pass_context
    def cli(ctx: click.Context) -> None:
        # The original script printed help and exited 0 when run bare; click
        # 8.2+ would exit 2, which the CLI contract (Section 8) forbids.
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())

    from lost_sessions.inventory import agent_tools

    cli.add_command(_inventory_command(list(agent_tools(manager)), manager))
    for command in (_list_command(manager), _open_command(manager), _history_command()):
        cli.add_command(command)
    manager.hook.register_commands(cli=cli)
    return cli


def _since(
    _ctx: click.Context, _param: click.Parameter, value: str | None
) -> str | None:
    from lost_sessions.inventory import parse_since

    if value is None:
        return None
    try:
        return parse_since(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


def _inventory_command(tools: list[str], manager: PluginManager) -> click.Command:
    @click.command(name="inventory")
    @click.option(
        "--tool",
        "tool",
        multiple=True,
        type=click.Choice(tools),
        help="restrict to a tool (repeatable)",
    )
    @click.option(
        "--live",
        is_flag=True,
        help="only sessions running right now (live yes, plus unknown = possibly running)",
    )
    @click.option(
        "--since",
        callback=_since,
        help="only sessions active since <n>m|h|d|w or an ISO date",
    )
    @click.option(
        "--include-subagents",
        is_flag=True,
        help="also list subagent and guardian threads (always counted)",
    )
    @click.option("-o", "--output", type=click.Choice(["text", "json"]), default=None)
    @click.option("--json", "as_json", is_flag=True, help="same as --output json")
    def inventory(
        tool: tuple[str, ...],
        live: bool,
        since: str | None,
        include_subagents: bool,
        output: str | None,
        as_json: bool,
    ) -> None:
        """Read-only inventory of agent sessions, newest activity first."""
        from lost_sessions.inventory import collect, select

        mode = "json" if as_json else (output or "text")
        inv = collect(tool or None, manager=manager)
        keep = select(inv, live=live, since=since, include_subagents=include_subagents)
        sources = {
            name: src.model_dump(exclude_none=True) for name, src in inv.sources.items()
        }
        if mode == "json":
            doc = {
                "sessions": [rec.model_dump(mode="json") for rec in keep],
                "census": {n: c.model_dump() for n, c in inv.census.items()},
                "sources": sources,
            }
            click.echo(json.dumps(doc, indent=2))
        else:
            for r in keep:
                fields = (r.tool, r.id, r.name, r.live, r.updated, r.spawn_dir, r.title)
                click.echo("\t".join(str(v) if v else "-" for v in fields))
            for name, c in inv.census.items():
                click.echo(
                    f"# census {name}: listed={c.listed}"
                    f" hidden_subagents={c.hidden_subagents}"
                    f" unreadable={c.unreadable} live={c.live}"
                    f" source={sources[name]['status']}"
                )
        if inv.failed:
            message = "; ".join(sources[t]["message"] for t in inv.failed)
            if mode == "json":
                error = {
                    "code": "source_unreadable",
                    "message": message,
                    "sources": inv.failed,
                }
                click.echo(json.dumps({"error": error}), err=True)
            else:
                click.echo(
                    f"lost-sessions: could not read {', '.join(inv.failed)}: {message}",
                    err=True,
                )
            sys.exit(1)

    return inventory


# --- recovery commands ----------------------------------------------------------


def _window_options(f: Callable[..., None]) -> Callable[..., None]:
    """--since, --all/--hide-running and --include-helpers, as the script had them."""
    f = click.option(
        "--include-helpers",
        is_flag=True,
        help="also show helper runs (scratchpad folders, Codex Companion tasks)",
    )(f)
    f = click.option(
        "--hide-running",
        is_flag=True,
        help="hide running and restored sessions (the default)",
    )(f)
    f = click.option(
        "--all",
        "show_all",
        is_flag=True,
        help="also show running and restored sessions (Print only)",
    )(f)
    return click.option(
        "--since",
        metavar="WHEN",
        help=(
            "start of the window: a date, a date-time, or <n>m|h|d|w (default: "
            "00:00 on the day before the last boot). Sessions must have started "
            "before the boot"
        ),
    )(f)


def _check_exclusive(show_all: bool, hide_running: bool) -> None:
    if show_all and hide_running:
        from lost_sessions.core import error

        error("argument --hide-running: not allowed with argument --all")
        sys.exit(2)


def _list_command(manager: PluginManager) -> click.Command:
    @click.command(name="list", help="numbered list of dropped sessions")
    @_window_options
    def list_(
        since: str | None, show_all: bool, hide_running: bool, include_helpers: bool
    ) -> None:
        from lost_sessions import core, history

        _check_exclusive(show_all, hide_running)
        window = core.load_rows(since, manager)
        rows = window.rows
        shown = core.visible(rows, show_all=show_all, include_helpers=include_helpers)
        shorts = core.short_ids(rows)
        lost = [
            r
            for r in rows
            if not r.session.restored_by
            and not core.is_helper(r.session)
            and r.session.live != "yes"
        ]
        not_in = " or ".join(core.restoring_managers(manager)) or "a session manager"
        boot, start = window.boot, window.start
        print(
            f"Boot: {boot:%a %b %d %H:%M}   sessions started before it and active "
            f"since {start:%a %b %d %H:%M}"
        )
        print(
            f"{len(rows)} sessions; {len(lost)} lost "
            f"(not in {not_in}, not running, not helper runs)\n"
        )
        for r in shown:
            s = r.session
            state = core.state_label(s) or "closed"
            if s.restored_by:
                where = f"IN {s.restored_by[0].upper()}: {s.restored_by[1]}"
            else:
                where = f"not in {not_in}"
            created = core._parse(s.created)
            updated = core._parse(s.updated)
            if created is None or updated is None:  # select_rows keeps dated ones
                continue
            print(
                f"[{r.n:>2}] {shorts[s.id]}  {s.tool:<8} {where}  |  {state}  |  "
                f"started {created.astimezone():%b %d}  "
                f"last active {updated.astimezone():%b %d %H:%M}"
            )
            print(f"     about: {core.about(s)}")
            print(f"     id:    {s.id}")
            print(f"     dir:   {s.spawn_dir}")
            print(f"     open:  {core.resume_command(s, manager)}\n")
        history.save_listing(shown, start)

    return list_


def _open_command(manager: PluginManager) -> click.Command:
    @click.command(
        name="open",
        help=(
            "print or open sessions without the menu. REF is a number from the "
            "last `list` or `recover`, or a full or unique-prefix session ID."
        ),
    )
    @click.argument("refs", nargs=-1, required=True, metavar="REF...")
    @click.option("--print", "print_", is_flag=True, help="print the resume command")
    @_window_options
    def open_(
        refs: tuple[str, ...],
        print_: bool,
        since: str | None,
        show_all: bool,
        hide_running: bool,
        include_helpers: bool,
    ) -> None:
        from lost_sessions import core, history

        _check_exclusive(show_all, hide_running)
        if not print_:
            core.error("choose how to open the sessions: --print")
            sys.exit(2)
        split = [r.partition("@") for r in refs]
        names = [ref for ref, _, _ in split]
        if any(at for _, at, _ in split):
            core.error(
                "REF@DEST names a session-manager destination; "
                "it does not apply to --print"
            )
            sys.exit(2)
        listing = history.load_listing()
        numeric = any(re.fullmatch(r"\d{1,4}", r) for r in names)
        if not since and numeric and listing:
            since = listing.since
        window = core.load_rows(since, manager)
        picked, problems = core.resolve_refs(names, window.rows, listing)
        for p in problems:
            core.error(p)
        if problems:
            sys.exit(2)
        if numeric and listing:
            saved = core._parse(listing.saved)
            age = dt.datetime.now().astimezone() - saved if saved else None
            if saved and age and age > core.LISTING_MAX_AGE:
                core.warn(
                    f"numbers come from a listing saved {saved:%b %d %H:%M}; "
                    "run `lost-sessions list` to refresh"
                )
        entries = []
        for r in picked:
            core.info(f"#{r.n} → {r.session.id}  {core.about(r.session)}")
            entry = core.execute_print(r, manager)
            history.append_log(entry)
            core.success(f"print #{r.n} {entry.result}; logged to {history.log_path()}")
            print(history.format_entry(entry))
            entries.append(entry)
        sys.exit(core.exit_status(entries))

    return open_


def _history_command() -> click.Command:
    @click.command(
        name="history", help="show where the log is, then every logged action"
    )
    @click.option(
        "--json",
        "as_json",
        is_flag=True,
        help="print the raw JSON lines (the log location goes to stderr)",
    )
    def history_(as_json: bool) -> None:
        from lost_sessions import history

        print(f"Log: {history.log_path()}", file=sys.stderr if as_json else sys.stdout)
        lines = history.read_log()
        if as_json:
            for line in lines:
                if line.raw is None:
                    print(history.format_line(line), file=sys.stderr)
                else:
                    print(json.dumps(line.raw))
        elif not lines:
            print("No recoveries logged yet.")
        else:
            print()
            print("\n\n".join(history.format_line(line) for line in lines))

    return history_


def main() -> None:
    load_plugins(pm)
    build_cli(pm)(prog_name="lost-sessions")
