"""The `lost-sessions` command line."""

from __future__ import annotations

import json
import sys

import click

from lost_sessions import __version__
from lost_sessions.plugins import PluginManager, get_agent_tools, load_plugins, pm


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

    cli.add_command(_inventory_command(sorted(get_agent_tools(manager)), manager))
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


def main() -> None:
    load_plugins(pm)
    build_cli(pm)(prog_name="lost-sessions")
