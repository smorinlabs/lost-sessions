"""Rex session-manager plugin. Rex restores nothing by itself; it opens sessions
in new windows on request."""

from __future__ import annotations

from collections.abc import Callable

from lost_sessions.hookspecs import hookimpl
from lost_sessions.managers import SessionManager


class Rex(SessionManager):
    name = "rex"
    display_name = "Rex"


@hookimpl
def register_session_managers(register: Callable[[SessionManager], None]) -> None:
    register(Rex())
