"""The history log and the saved listing (design 0006, Sections 5.2 and 8.1).

Both live in ${XDG_STATE_HOME:-~/.local/state}/lost-sessions/. Writing is
strict and stamps every line with `schema` and `written_by`. Reading never
fails on content: unknown keys are kept, newer schemas are shown with a note,
and a line that is not JSON is reported and skipped.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError

from lost_sessions import __version__

if TYPE_CHECKING:
    from lost_sessions.core import Row

SCHEMA = 1  # bump only for a breaking change (Section 8.1 rule 3)
WRITTEN_BY = f"lost-sessions {__version__}"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "lost-sessions"


def log_path() -> Path:
    return state_dir() / "history.jsonl"


def listing_path() -> Path:
    return state_dir() / "last-list.json"


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class HistoryEntry(BaseModel):
    """One logged action. Read leniently: every field defaults, extras are kept."""

    model_config = ConfigDict(extra="allow")

    time: str | None = None
    action: str | None = None
    tool: str | None = None
    id: str | None = None
    about: str | None = None
    dir: str | None = None
    commands: list[str] | None = None
    opened: dict[str, Any] | None = None
    result: str | None = None
    note: str | None = None
    schema_: int | None = None  # the line's "schema" key (0 when absent)
    written_by: str | None = None

    @classmethod
    def new(cls, **fields: object) -> HistoryEntry:
        """A fresh entry with today's ten keys filled in, as the script wrote them."""
        base: dict[str, object] = {
            "time": now_iso(),
            "commands": [],
            "opened": {},
            "result": "ok",
            "note": "",
        }
        return cls.model_validate(base | fields)

    def to_line(self) -> str:
        """The JSONL line: the ten original keys in order, then the stamps."""
        data = {
            "time": self.time,
            "action": self.action,
            "tool": self.tool,
            "id": self.id,
            "about": self.about,
            "dir": self.dir,
            "commands": self.commands if self.commands is not None else [],
            "opened": self.opened if self.opened is not None else {},
            "result": self.result,
            "note": self.note if self.note is not None else "",
            "schema": SCHEMA,
            "written_by": WRITTEN_BY,
        }
        return json.dumps(data)


class HistoryLine(BaseModel):
    """One line of history.jsonl as read: its parsed entry, or why it is unusable."""

    number: int
    raw: dict[str, Any] | None = None
    entry: HistoryEntry | None = None


def append_log(entry: HistoryEntry) -> None:
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(entry.to_line() + "\n")


_TEXT_FIELDS = (
    "time",
    "action",
    "tool",
    "id",
    "about",
    "dir",
    "result",
    "note",
    "written_by",
)


def _coerced(fields: dict[str, Any]) -> dict[str, Any]:
    """Known keys holding unexpected types, turned into text so the line still shows."""
    out = dict(fields)
    for key in _TEXT_FIELDS:
        if out.get(key) is not None and not isinstance(out[key], str):
            out[key] = str(out[key])
    commands = out.get("commands")
    if commands is not None:
        items = commands if isinstance(commands, list) else [commands]
        out["commands"] = [str(c) for c in items]
    opened = out.get("opened")
    if opened is not None and not isinstance(opened, dict):
        out["opened"] = {"value": opened}
    return out


def _entry(raw: dict[str, Any]) -> HistoryEntry:
    fields = {k: v for k, v in raw.items() if k != "schema"}
    schema = raw.get("schema", 0)
    fields["schema_"] = schema if isinstance(schema, int) else None
    try:
        return HistoryEntry.model_validate(fields)
    except ValidationError:
        return HistoryEntry.model_validate(_coerced(fields))


def read_log() -> list[HistoryLine]:
    try:
        # Bytes: json.loads decodes each line, so one bad UTF-8 byte stays one
        # unreadable line (UnicodeDecodeError is a ValueError).
        lines = log_path().read_bytes().splitlines()
    except OSError:
        return []
    out = []
    for number, line in enumerate(lines, 1):
        try:
            raw = json.loads(line)
        except ValueError:
            raw = None
        if isinstance(raw, dict):
            out.append(HistoryLine(number=number, raw=raw, entry=_entry(raw)))
        else:
            out.append(HistoryLine(number=number))
    return out


def _shown(entry: HistoryEntry, name: str) -> str:
    """A missing field prints `?`; a present but empty one prints empty (rule 6)."""
    if name not in entry.model_fields_set:
        return "?"
    value = getattr(entry, name)
    return "" if value is None else str(value)


def format_entry(entry: HistoryEntry) -> str:
    opened = entry.opened or {}
    where = ", ".join(f"{k}={v}" for k, v in opened.items())
    lines = [
        (
            f"{_shown(entry, 'time')}  {_shown(entry, 'action'):<5}  "
            f"{_shown(entry, 'result'):<7}  {_shown(entry, 'tool')}  {_shown(entry, 'id')}"
        ),
        f"    about: {_shown(entry, 'about')}",
        f"    dir:   {_shown(entry, 'dir')}",
    ]
    lines += [f"    cmd:   {c}" for c in entry.commands or []]
    if where:
        lines.append(f"    open:  {where}")
    if "note" not in entry.model_fields_set:
        lines.append("    note:  ?")
    elif entry.note:
        lines.append(f"    note:  {entry.note}")
    if entry.schema_ is not None and entry.schema_ > SCHEMA:
        lines.append(
            f"    (written as schema {entry.schema_}; upgrade lost-sessions to see all of it)"
        )
    return "\n".join(lines)


def format_line(line: HistoryLine) -> str:
    if line.entry is None:
        return f"? (unreadable line {line.number})"
    return format_entry(line.entry)


# --- the saved listing (`open 3` refers to it) -----------------------------------


class ListingRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    n: int
    id: str
    about: str | None = None


class Listing(BaseModel):
    model_config = ConfigDict(extra="allow")

    saved: str | None = None
    since: str | None = None
    rows: list[ListingRow]
    schema_: int = 0
    written_by: str | None = None


def save_listing(rows: Sequence[Row], start: dt.datetime) -> None:
    from lost_sessions.core import about

    p = listing_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "saved": now_iso(),
        "since": start.isoformat(timespec="seconds"),
        "rows": [
            {"n": r.n, "id": r.session.id, "about": about(r.session)} for r in rows
        ],
        "schema": SCHEMA,
        "written_by": WRITTEN_BY,
    }
    p.write_text(json.dumps(data))


def load_listing() -> Listing | None:
    """The saved listing, or None when it is missing, unreadable or newer than us."""
    try:
        raw = json.loads(listing_path().read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    schema = raw.pop("schema", 0)
    if not isinstance(schema, int) or schema > SCHEMA:
        return None
    try:
        listing = Listing.model_validate(raw | {"schema_": schema})
    except ValidationError:
        return None
    if listing.saved is not None:
        try:
            saved = dt.datetime.fromisoformat(listing.saved)
        except ValueError:
            return None
        if saved.tzinfo is None:  # cannot be compared with now: treat as unreadable
            return None
    return listing
