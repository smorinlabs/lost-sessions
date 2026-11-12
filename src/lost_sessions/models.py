"""Pydantic data models (design 0006, Section 5).

`Session` keeps `session-inventory`'s field names and order, so
`inventory --json` matches `session-inventory list --json` byte for byte.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Live = Literal["yes", "no", "unknown"]


class Lineage(BaseModel):
    kind: Literal["subagent", "fork"]
    parent_id: str | None = None


class Session(BaseModel):
    """One agent session, as found by an agent plugin."""

    model_config = ConfigDict(validate_assignment=True)

    tool: str
    id: str
    name: str | None = None
    name_resumable: bool = False
    title: str | None = None
    spawn_dir: str | None = None
    branch: str | None = None
    created: str | None = None
    updated: str | None = None
    transcript: str | None = None
    lineage: Lineage | None = None
    archived: bool = False
    unreadable: bool = False
    live: Live = "no"
    live_basis: str | None = None
    live_host: str | None = None
    pid: int | None = None
    tmux: JsonValue = None
    resume: str | None = None
    resume_by_name: str | None = None
    resume_blocked: str | None = None
    export_command: str | None = None
    # Set by core, never part of the inventory JSON.
    restored_by: tuple[str, str] | None = Field(default=None, exclude=True)
    hidden: bool = Field(default=False, exclude=True)


class SourceStatus(BaseModel):
    """Whether one agent's store could be read. Dumped with exclude_none."""

    status: Literal["ok", "absent", "error"]
    path: str | None = None
    message: str | None = None
    legacy_only: int | None = None


class Census(BaseModel):
    listed: int
    hidden_subagents: int
    unreadable: int
    live: int


class ScanResult(BaseModel):
    sessions: list[Session]
    source: SourceStatus
    hidden_subagents: int = 0


class Inventory(BaseModel):
    """Everything one scan of the selected agents found (the stable API value)."""

    sessions: list[Session]
    census: dict[str, Census]
    sources: dict[str, SourceStatus]
    failed: list[str]
