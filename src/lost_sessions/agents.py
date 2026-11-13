"""The AgentTool plugin contract and helpers for reading agent stores.

Agent plugins read their store read-only and never write to it. The helpers
are ported unchanged from `session-inventory` (smorinlabs-skills cf83bf1).
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shlex
import sqlite3
import subprocess  # nosec B404 - fixed argv lists, never a shell
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ValidationError

from lost_sessions.models import ScanResult, Session

TAIL_BYTES = 256 * 1024
# What a single stored record can raise when its shape changed. Scanners catch
# these per record and mark it unreadable; OSError still fails the whole store.
RECORD_ERRORS = (ValidationError, TypeError, ValueError, AttributeError, KeyError)
HEAD_LINES = 60


class SourceError(Exception):
    """A whole store exists but could not be read."""


class ScanContext(BaseModel):
    """What core gives every agent plugin for one scan."""

    home: Path
    # pid -> argv tokens; empty unless some selected tool needs processes
    processes: dict[int, list[str]] = {}


class AgentTool(ABC):
    """Finds the sessions of one agent (Claude Code, Codex, ...)."""

    name: str
    # Whether scan() reads ScanContext.processes; core runs `ps` only if needed.
    needs_processes: bool = False

    @abstractmethod
    def scan(self, ctx: ScanContext) -> ScanResult:
        """Read this agent's store, read-only, and report its sessions."""

    # Whether the resume command runs in the session's folder (`cd DIR && ...`).
    resume_in_dir: bool = True

    @abstractmethod
    def resume_args(self, session: Session) -> list[str]:
        """The command that resumes `session`, e.g. ["codex", "resume", id]."""


# --- helpers --------------------------------------------------------------


def iso_from_epoch(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    return dt.datetime.fromtimestamp(seconds, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_normalize(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_home(home: Path) -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else home / ".local" / "share"


def unreadable_session(tool: str, sid: object, transcript: object = None) -> Session:
    """The record for a session whose stored data does not fit the model.

    A store that changed shape marks that session unreadable; it never stops
    the scan (design 0006, Section 8.1 rule 8).
    """
    path = None if transcript is None else str(transcript)
    return Session(tool=tool, id=str(sid), transcript=path, unreadable=True)


def open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def cd_prefix(directory: str | None) -> str:
    return f"cd {shlex.quote(directory)} && " if directory else ""


def processes() -> dict[int, list[str]]:
    """pid -> argv tokens for every process (one ps call).

    `-ww`: unlimited width. Without it procps `ps` (Linux) cuts each line at 80
    columns when stdout is not a terminal, losing trailing arguments.
    """
    out = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["ps", "-axww", "-o", "pid=,command="],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    table = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            table[int(parts[0])] = parts[1].split()
    return table


def runs_tool(argv: list[str], tool: str) -> bool:
    """The process is `tool` itself (or its versioned binary, e.g.
    muse-bin-1.3.0-R3401.1), or an interpreter running a script with that name."""
    pattern = re.compile(rf"{re.escape(tool)}(-bin[-.\w]*)?")
    return any(pattern.fullmatch(Path(tok).name) for tok in argv[:2])


def utc_lstart(pid: int) -> str | None:
    out = subprocess.run(  # noqa: S603  # nosec B603 B607 - fixed argv, no shell
        ["ps", "-o", "lstart=", "-p", str(pid)],  # noqa: S607
        capture_output=True,
        text=True,
        env={**os.environ, "TZ": "UTC"},
        check=False,
    ).stdout
    return " ".join(out.split()) or None


def process_cwd(pid: int) -> str | None:
    out = subprocess.run(  # noqa: S603  # nosec B603 B607 - fixed argv, no shell
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return next((line[1:] for line in out.splitlines() if line.startswith("n")), None)
