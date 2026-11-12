"""The `lost-sessions` command line."""

from __future__ import annotations

import click

from lost_sessions import __version__
from lost_sessions.plugins import PluginManager, load_plugins, pm


def build_cli(manager: PluginManager = pm) -> click.Group:
    """Create the click group and let plugins add commands.

    A factory instead of an import-time group (design 0006, Section 7.3), so
    flags generated from registered managers and plugins registered after
    import both reach a freshly built CLI.
    """

    @click.group(
        help=(
            "Recover Claude Code, Codex, Muse and OpenCode sessions that started "
            "before the last boot but that no session manager will restore."
        )
    )
    @click.version_option(__version__, prog_name="lost-sessions")
    def cli() -> None:
        pass

    manager.hook.register_commands(cli=cli)
    return cli


def main() -> None:
    load_plugins(pm)
    build_cli(pm)(prog_name="lost-sessions")
