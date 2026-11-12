"""The `lost-sessions` command line."""

from __future__ import annotations

import click

from lost_sessions import __version__


def build_cli() -> click.Group:
    """Create the click group. A factory, so tests can build a fresh CLI."""

    @click.group(
        help=(
            "Recover Claude Code, Codex, Muse and OpenCode sessions that started "
            "before the last boot but that no session manager will restore."
        )
    )
    @click.version_option(__version__, prog_name="lost-sessions")
    def cli() -> None:
        pass

    return cli


def main() -> None:
    build_cli()(prog_name="lost-sessions")
