"""The SessionManager plugin contract (design 0006, Section 6.2).

A session manager is a terminal app that restores sessions by itself (Herdr)
or opens them on request (Rex). Core runs a manager's plan step by step and
asks the manager to read each response; it never names a manager itself.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess  # nosec B404 - fixed argv lists, never a shell
from abc import ABC
from collections.abc import Mapping, Sequence
from typing import Any

import click
from pydantic import BaseModel, ConfigDict

from lost_sessions.models import Session

# Placeholders a step can carry until an earlier response fills them in, and how
# previews show them.
PLACEHOLDERS = {
    "{pane}": "<pane>",
    "{window}": "<window>",
    "{tab}": "<tab>",
    "{workspace}": "<new workspace>",
    "{session}": "<new session>",
}


class Destination(BaseModel):
    """Where a session opens. Shared by identity: rows sent to the same new
    destination share one object, so the first row creates it and the rest open
    inside it. `id` is None until the destination exists."""

    model_config = ConfigDict(validate_assignment=True)

    manager: str
    label: str
    id: str | None = None

    def is_new(self) -> bool:
        return self.id is None


class Step(BaseModel):
    """One command of a plan."""

    argv: list[str]
    cosmetic: bool = False  # names a tab or window; the session is already open
    opens: bool = False  # must open something according to its response


class Resume(BaseModel):
    """How to resume one session, supplied by its agent plugin through core."""

    command: str  # the shell command, e.g. "cd /w && claude --resume ID"
    argv: list[str]  # the bare argv, e.g. ["claude", "--resume", "ID"]


class Plan(BaseModel):
    """What core hands a manager about the row being opened."""

    session: Session
    n: int
    label: str  # window or tab label, e.g. "#3 title 3ac1dc"
    cwd: str
    resume: Resume


class Response(BaseModel):
    code: int
    data: dict[str, Any]
    error: dict[str, Any]


def run_json(argv: Sequence[str]) -> Response:
    """Run one command; never raises. Its stdout is parsed as a JSON object."""
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv, no shell
            list(argv), capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return Response(
            code=127, data={}, error={"code": "not_found", "message": str(exc)}
        )
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    err: dict[str, Any] = {}
    if proc.returncode:
        try:
            raw = json.loads(proc.stderr).get("error")
        except (ValueError, AttributeError):
            raw = None
        err = (
            raw
            if isinstance(raw, dict)
            else {
                "message": str(raw)
                if raw
                else (proc.stderr.strip() or f"exit {proc.returncode}")
            }
        )
    return Response(code=proc.returncode, data=data, error=err)


def result_of(data: Mapping[str, Any]) -> dict[str, Any]:
    r = data.get("result", data)
    return r if isinstance(r, dict) else {}


class Destinations(ABC):  # noqa: B024 - every member has a default
    """The destinations one manager offers, one shared object per destination."""

    def __init__(self, default_label: str, available: bool) -> None:
        self.default_label = default_label
        self.available = available
        self.pool: dict[tuple[str, ...], Destination] = {}

    def get(self, label: str) -> Destination:
        """A destination by ID or label; the first match for a shared label,
        else a new one."""
        raise NotImplementedError

    def default(self) -> Destination:
        return self.get(self.default_label)

    def choices(self) -> list[Destination]:
        """The default first, then the other existing ones, each once."""
        return [self.default()]

    def ambiguous(self, label: str) -> list[str]:
        """IDs of the existing destinations sharing `label`, when more than one does."""
        return []

    def where(self, d: Destination) -> str:
        """How a destination reads in the menu's Where column and the picker."""
        return d.label if not d.is_new() else f"{d.label} (new)"

    def describe(self, d: Destination) -> str:
        """where(d), plus the ID when another destination shares the label."""
        text = self.where(d)
        if not d.is_new() and self.ambiguous(d.label):
            text += f" ({d.id})"
        return text


class SessionManager(ABC):
    """Restores or opens agent sessions (Herdr, Rex, ...)."""

    name: str  # "herdr": the CLI flag (`open --herdr`) and the menu action
    display_name: str  # "Herdr": shown in labels and messages
    # Whether restored_ids() can be non-empty: the manager reopens sessions by
    # itself after a reboot, so `list` reports sessions "not in" it.
    restores: bool = False
    # Whether the manager opens sessions: implements destinations() and plan().
    # Only these get an `open --<name>` flag and a `workspaces` section.
    can_open: bool = False
    open_help: str = ""  # help for `open --<name>`
    # ("workspace", "workspaces"): what one destination is called in messages
    destination_noun: tuple[str, str] = ("destination", "destinations")

    def restored_ids(self, boot: dt.datetime) -> dict[str, str]:
        """Session IDs this manager will restore by itself, mapped to a label
        such as "work / tab". Managers that never restore return {}."""
        return {}

    def click_options(self) -> list[click.Option]:
        """Options core adds to `recover`, `open` and `workspaces`."""
        return []

    def destinations(self, options: Mapping[str, Any]) -> Destinations:
        """Where sessions can open, given this manager's option values."""
        raise NotImplementedError

    def plan(self, p: Plan, dest: Destination) -> list[Step]:
        """The commands that open p.session in dest."""
        return []

    def on_response(
        self,
        step: Step,
        result: dict[str, Any],
        dest: Destination,
        fills: dict[str, str],
    ) -> dict[str, Any] | None:
        """Read one successful response: fill placeholders, update dest, and
        return what is now open (the history `opened` keys), or None."""
        return None

    def blocked_note(
        self, error: Mapping[str, Any], fills: Mapping[str, str]
    ) -> str | None:
        """A note when a failed step means opened-but-waiting, else None."""
        return None

    def focus_command(
        self,
        opened: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> list[str] | None:
        """The command that brings an opened session to the front."""
        return None

    def warnings(
        self,
        labels: Sequence[str],
        options: Mapping[str, Any],
    ) -> list[str]:
        """Warnings about destinations named on the command line."""
        return []

    def workspaces_lines(self, dests: Destinations) -> list[str]:
        """The `workspaces` section for this manager, heading first."""
        noun = self.destination_noun[1]
        lines = [f"{self.display_name} {noun} (REF@LABEL with --{self.name}):"]
        for i, d in enumerate(dests.choices()):
            lines.append(f"  {dests.describe(d)}" + ("   (default)" if i == 0 else ""))
        return lines

    def unreachable(self) -> str:
        return f"could not reach {self.display_name}"
