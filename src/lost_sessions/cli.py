"""The `lost-sessions` command line."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys

import click

from lost_sessions import __version__
from lost_sessions.managers import SessionManager
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
    for command in (
        _recover_command(manager),
        _list_command(manager),
        _open_command(manager),
        _workspaces_command(manager),
        _history_command(),
    ):
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


def _window_params() -> list[click.Parameter]:
    """--since, --all/--hide-running and --include-helpers, as the script had them."""
    return [
        click.Option(
            ["--since"],
            metavar="WHEN",
            help=(
                "start of the window: a date, a date-time, or <n>m|h|d|w (default: "
                "00:00 on the day before the last boot). Sessions must have started "
                "before the boot"
            ),
        ),
        click.Option(
            ["--all", "show_all"],
            is_flag=True,
            help="also show running and restored sessions (Print only)",
        ),
        click.Option(
            ["--hide-running"],
            is_flag=True,
            help="hide running and restored sessions (the default)",
        ),
        click.Option(
            ["--include-helpers"],
            is_flag=True,
            help="also show helper runs (scratchpad folders, Codex Companion tasks)",
        ),
    ]


def _check_exclusive(show_all: bool, hide_running: bool) -> None:
    if show_all and hide_running:
        from lost_sessions.core import error

        error("argument --hide-running: not allowed with argument --all")
        sys.exit(2)


def _list_command(manager: PluginManager) -> click.Command:
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

    return click.Command(
        name="list",
        callback=list_,
        params=_window_params(),
        help="numbered list of dropped sessions",
    )


LAST = "\0last"  # `--focus` with no REF: the last session opened


def _managers(manager: PluginManager) -> dict[str, SessionManager]:
    from lost_sessions.core import session_managers

    load_plugins(manager)
    return {name: m for name, m in session_managers(manager).items() if m.can_open}


def _open_command(manager: PluginManager) -> click.Command:
    managers = _managers(manager)

    def command(
        refs: tuple[str, ...],
        print_: bool,
        focus: str | None,
        since: str | None,
        show_all: bool,
        hide_running: bool,
        include_helpers: bool,
        **options: object,
    ) -> None:
        from lost_sessions import core, history

        _check_exclusive(show_all, hide_running)
        chosen = [name for name in managers if options.pop(f"via_{name}", False)]
        ways = ["print"] * print_ + chosen
        if len(ways) != 1:
            flags = " ".join(["--print", *(f"--{n}" for n in managers)])
            if len(ways) > 1:
                core.error(f"choose one of {flags}")
            else:
                core.error(f"one of the arguments {flags} is required")
            sys.exit(2)
        action = ways[0]
        mgr = managers.get(action)
        split = [
            r.partition("@") for r in refs
        ]  # 29@codex: into the `codex` destination
        names = [ref for ref, _, _ in split]
        wanted = [dest if at else None for _, at, dest in split]
        if action == "print" and any(w is not None for w in wanted):
            core.error(
                "REF@DEST names a session-manager destination; "
                "it does not apply to --print"
            )
            sys.exit(2)
        if any(w == "" for w in wanted):
            core.error("REF@ needs a destination after the @, e.g. 29@recovered")
            sys.exit(2)
        if focus is not None and action == "print":
            core.error(
                "--focus brings an opened session to the front; "
                "it does not apply to --print"
            )
            sys.exit(2)
        if focus not in (None, LAST) and focus not in names:
            core.error(
                f"--focus {focus}: name one of the REFs being opened ({', '.join(names)})"
            )
            sys.exit(2)
        listing = history.load_listing()
        numeric = any(re.fullmatch(r"\d{1,4}", r) for r in names)
        if not since and numeric and listing:
            since = listing.since
        window = core.load_rows(since, manager)
        picked, problems = core.resolve_refs(names, window.rows, listing)
        if mgr is not None:
            defaults = [str(options.get(o.name or "")) for o in mgr.click_options()]
            for note in mgr.warnings([*defaults, *(w for w in wanted if w)], options):
                core.warn(note)
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
        dests = None
        if mgr is not None:
            dests = mgr.destinations(options)
            _, plural = mgr.destination_noun
            for label in dict.fromkeys(w or dests.default_label for w in wanted):
                ids = dests.ambiguous(label)
                if ids:
                    core.error(
                        f"{label!r} names {len(ids)} {plural} ({', '.join(ids)}); "
                        f"use the ID instead, e.g. REF@{ids[0]}"
                    )
                    sys.exit(2)
        entries = []
        for r, dest_label in zip(picked, wanted, strict=True):
            target = None
            if dests is not None:
                target = dests.get(dest_label) if dest_label else dests.default()
            where = f"  → {dests.describe(target)}" if dests and target else ""
            core.info(f"#{r.n} → {r.session.id}  {core.about(r.session)}{where}")
            entries.append(core.run_action(r, action, mgr, target, manager))
        if focus is not None and entries:
            opened = [e for e in entries if core.focus_command(e, options, manager)]
            if focus == LAST:
                pick = opened[-1] if opened else entries[-1]
            else:
                pick = entries[names.index(focus)]
            core.run_focus(pick, options, manager)
        sys.exit(core.exit_status(entries))

    params: list[click.Parameter] = [
        click.Argument(["refs"], nargs=-1, required=True, metavar="REF..."),
        click.Option(
            ["--print", "print_"], is_flag=True, help="print the resume command"
        ),
    ]
    params += [
        click.Option([f"--{name}", f"via_{name}"], is_flag=True, help=m.open_help)
        for name, m in managers.items()
    ]
    params.append(
        click.Option(
            ["--focus"],
            is_flag=False,
            flag_value=LAST,
            default=None,
            metavar="REF",
            help=(
                "afterwards, bring REF (default: the last one opened) to the front "
                "in its session manager"
            ),
        )
    )
    for m in managers.values():
        params += m.click_options()
    return click.Command(
        name="open",
        callback=command,
        params=params + _window_params(),
        help=(
            "print or open sessions without the menu. REF is a number from the "
            "last `list` or `recover`, or a full or unique-prefix session ID. "
            "REF@DEST opens that session in the destination named DEST instead "
            "of the default, e.g. 29@codex 31@'tax prep'."
        ),
    )


def _workspaces_command(manager: PluginManager) -> click.Command:
    managers = _managers(manager)

    def command(**options: object) -> None:
        from lost_sessions import core

        ok = True
        for i, m in enumerate(managers.values()):
            dests = m.destinations(options)
            lines = m.workspaces_lines(dests)
            if i:
                print()
            print(lines[0])
            if dests.available:
                for line in lines[1:]:
                    print(line)
            else:
                core.error(m.unreachable())
                ok = False
        sys.exit(0 if ok else 1)

    params: list[click.Parameter] = []
    for m in managers.values():
        params += m.click_options()
    return click.Command(
        name="workspaces",
        callback=command,
        params=params,
        help="list the destinations each session manager can open sessions in",
    )


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _recover_command(manager: PluginManager) -> click.Command:
    managers = _managers(manager)

    def command(
        since: str | None,
        show_all: bool,
        hide_running: bool,
        include_helpers: bool,
        **options: object,
    ) -> None:
        from lost_sessions import core, history
        from lost_sessions import menu as menu_module

        _check_exclusive(show_all, hide_running)
        if not interactive():
            flags = "|".join(["--print", *(f"--{n}" for n in managers)])
            core.error(
                f"lost-sessions recover needs a terminal; without one use "
                f"`lost-sessions open REF {flags}`"
            )
            sys.exit(2)
        window = core.load_rows(since, manager)
        rows = window.rows
        # `a` in the menu shows or hides the running ones
        candidates = core.visible(rows, show_all=True, include_helpers=include_helpers)
        if not core.visible(rows, show_all=show_all, include_helpers=include_helpers):
            hidden = len(candidates)
            not_in = (
                " or ".join(core.restoring_managers(manager)) or "a session manager"
            )
            core.info(
                "No lost sessions in this window"
                + (
                    f" ({hidden} running or in {not_in}; --all shows them)."
                    if hidden
                    else " (try --since)."
                )
            )
            sys.exit(0)
        history.save_listing(candidates, window.start)
        dests = {name: m.destinations(options) for name, m in managers.items()}
        available = {name: d.available for name, d in dests.items()}
        menu = menu_module.make_menu(candidates, dests, available, show_all, manager)
        chosen = menu.run() or []
        if not chosen:
            core.info("Nothing chosen; nothing done.")
            sys.exit(0)
        # Re-check liveness: a session may have been resumed elsewhere meanwhile.
        fresh = core.load_rows(window.start.isoformat(timespec="seconds"), manager)
        live_now = {r.session.id: r.session.live for r in fresh.rows}
        entries = []
        for r, action, target in chosen:
            if action != "print" and live_now.get(r.session.id) == "yes":
                r.session.live = "yes"
            entries.append(
                core.run_action(r, action, managers.get(action), target, manager)
            )
        marked = [
            e for e in entries if e.id == menu.focus_id
        ]  # focus last: it ends in front
        if marked:
            core.run_focus(marked[0], options, manager)
        sys.exit(core.exit_status(entries))

    params = _window_params()
    for m in managers.values():
        params += m.click_options()
    return click.Command(
        name="recover",
        callback=command,
        params=params,
        help="interactive menu: choose Print or a session manager for each dropped session",
    )


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
