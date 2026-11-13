"""Rex session-manager plugin. Rex restores nothing by itself; it opens sessions
in new windows on request."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, override

import click

from lost_sessions.hookspecs import hookimpl
from lost_sessions.managers import (
    Destination,
    Destinations,
    Plan,
    SessionManager,
    Step,
    run_json,
)

CURRENT = "current"  # --rex-session value: the Rex session lost-sessions runs in


class RexDestination(Destination):
    # The session lost-sessions runs in; with no id, Rex's active one.
    current: bool = False
    current_label: str | None = None

    def is_new(self) -> bool:
        return not (self.id or self.current)


class RexDestinations(Destinations):
    """Rex sessions. Existing ones are keyed by ID; `current` is this session."""

    def __init__(
        self,
        default_label: str,
        available: bool,
        sessions: list[dict[str, Any]],
        rex_current: str | None,
    ) -> None:
        super().__init__(default_label, available)
        self.sessions = sessions
        self.rex_current = rex_current

    def _for(self, entry: Mapping[str, Any]) -> Destination:
        key = ("id", str(entry.get("session_id")))
        if key not in self.pool:
            self.pool[key] = RexDestination(
                manager="rex", label=str(entry.get("label")), id=entry.get("session_id")
            )
        return self.pool[key]

    @override
    def get(self, label: str) -> Destination:
        if label == CURRENT:
            key = (CURRENT,)
            if key not in self.pool:
                mine = next(
                    (
                        x
                        for x in self.sessions
                        if x.get("session_id") == self.rex_current
                    ),
                    {},
                )
                self.pool[key] = RexDestination(
                    manager="rex",
                    label=CURRENT,
                    id=self.rex_current or None,
                    current=True,
                    current_label=mine.get("label"),
                )
            return self.pool[key]
        hit = next((e for e in self.sessions if e.get("session_id") == label), None)
        hit = hit or next((e for e in self.sessions if e.get("label") == label), None)
        if hit:
            return self._for(hit)
        key = ("new", label)
        if key not in self.pool:
            self.pool[key] = RexDestination(manager="rex", label=label)
        return self.pool[key]

    @override
    def choices(self) -> list[Destination]:
        """The default first, then the current session, then the other existing ones."""
        candidates = [self.default(), self.get(CURRENT)]
        candidates += [
            self._for(e)
            for e in self.sessions
            if e.get("session_id") != self.rex_current
        ]
        out: list[Destination] = []
        for d in candidates:
            if all(d is not o for o in out):
                out.append(d)
        return out

    @override
    def ambiguous(self, label: str) -> list[str]:
        ids = [
            str(e.get("session_id")) for e in self.sessions if e.get("label") == label
        ]
        return ids if len(ids) > 1 else []

    @override
    def where(self, d: Destination) -> str:
        if isinstance(d, RexDestination) and d.current:
            return f"current ({d.current_label or "Rex's active session"})"
        return super().where(d)

    @override
    def describe(self, d: Destination) -> str:
        if isinstance(d, RexDestination) and d.current:
            return self.where(d)
        return super().describe(d)


class Rex(SessionManager):
    name = "rex"
    display_name = "Rex"
    open_help = "open in a new window in a Rex session"
    destination_noun = ("session", "sessions")

    @override
    def click_options(self) -> list[click.Option]:
        return [
            click.Option(
                ["--rex-session"],
                default="recovered",
                metavar="LABEL",
                help=(
                    "default Rex session (default: recovered, created if missing; "
                    "`current` is the session you run this in)"
                ),
            )
        ]

    @override
    def destinations(self, options: Mapping[str, Any]) -> Destinations:
        response = run_json(["rex", "session", "list", "--json"])
        ss = response.data.get("sessions", [])
        sessions = (
            [x for x in ss if isinstance(x, dict)] if isinstance(ss, list) else []
        )
        return RexDestinations(
            options.get("rex_session") or "recovered",
            response.code == 0,
            sessions,
            os.environ.get("REX_SESSION") or None,
        )

    @override
    def plan(self, p: Plan, dest: Destination) -> list[Step]:
        cmd = ["--", "zsh", "-c", p.resume.command]
        if dest.is_new():
            return [
                Step(
                    argv=[
                        "rex",
                        "session",
                        "new",
                        dest.label,
                        "--json",
                        "--window",
                        p.label,
                        "-c",
                        p.cwd,
                        "--interactive",
                        *cmd,
                    ],
                    opens=True,
                )
            ]
        # An unscoped rename fails across sessions.
        scope = ["-s", dest.id] if dest.id else []
        return [
            Step(
                argv=[
                    "rex",
                    "run",
                    *scope,
                    "--json",
                    "--focus=false",
                    "--interactive",
                    "--label",
                    p.label,
                    "-c",
                    p.cwd,
                    *cmd,
                ]
            ),
            Step(
                argv=["rex", "window", "rename", *scope, "{window}", p.label],
                cosmetic=True,
            ),
        ]

    @override
    def on_response(
        self,
        step: Step,
        result: dict[str, Any],
        dest: Destination,
        fills: dict[str, str],
    ) -> dict[str, Any] | None:
        if result.get("session_id"):  # rex session new: the first window comes with it
            dest.id = result["session_id"]
            first = (result.get("initial_windows") or [{}])[0]
            return {"rex_session": dest.id, "rex_window": first.get("window_id")}
        if result.get("window_id"):
            fills["{window}"] = result["window_id"]
            return ({"rex_session": dest.id} if dest.id else {}) | {
                "rex_window": result["window_id"]
            }
        return None

    @override
    def focus_command(
        self, opened: Mapping[str, Any], options: Mapping[str, Any]
    ) -> list[str] | None:
        """Rex's app action `session.select` switches sessions, which `rex focus`
        alone does not."""
        if not opened.get("rex_window"):
            return None
        if opened.get("rex_session"):
            return [
                "rex",
                "do",
                "session.select",
                f"session_id={opened['rex_session']}",
                f"window_id={opened['rex_window']}",
            ]
        return ["rex", "focus", opened["rex_window"]]

    @override
    def warnings(self, labels: Sequence[str], options: Mapping[str, Any]) -> list[str]:
        if CURRENT in labels and not os.environ.get("REX_SESSION"):
            return [
                "not running inside Rex: `current` opens in the session the Rex app is showing"
            ]
        return []

    @override
    def workspaces_lines(self, dests: Destinations) -> list[str]:
        lines = [
            "Rex sessions (--rex-session, or REF@LABEL with --rex; `current` is this session):"
        ]
        for i, d in enumerate(dests.choices()):
            current = isinstance(d, RexDestination) and d.current
            extra = d.id or (
                "Rex's active session" if current else "created on first use"
            )
            lines.append(
                f"  {dests.describe(d):<40} {extra}"
                + ("   (default)" if i == 0 else "")
            )
        return lines

    @override
    def unreachable(self) -> str:
        return "could not reach Rex (`rex session list` failed)"


@hookimpl
def register_session_managers(register: Callable[[SessionManager], None]) -> None:
    register(Rex())
