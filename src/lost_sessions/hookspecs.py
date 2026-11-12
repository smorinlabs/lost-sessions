"""Hook specifications. Every hook is a `register_*` callback, as in simonw/llm."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click
from pluggy import HookimplMarker, HookspecMarker

hookspec = HookspecMarker("lost_sessions")
hookimpl = HookimplMarker("lost_sessions")


@hookspec
def register_agent_tools(register: Callable[[Any], None]) -> None:
    "Register AgentTool instances that find sessions of one agent (Claude Code, Codex, ...)"


@hookspec
def register_session_managers(register: Callable[[Any], None]) -> None:
    "Register SessionManager instances that can restore or open sessions (Herdr, Rex, ...)"


@hookspec
def register_commands(cli: click.Group) -> None:
    "Register additional click commands, e.g. 'lost-sessions mycommand ...'"
