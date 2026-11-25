"""Antigravity (`agy`) agent plugin: `~/.gemini/antigravity-cli/conversation_summaries.db`."""

from __future__ import annotations

import datetime as dt
import json
import re
import shlex
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import override
from urllib.parse import unquote, urlparse

from lost_sessions.agents import (
    RECORD_ERRORS,
    AgentTool,
    ScanContext,
    SourceError,
    cd_prefix,
    iso_from_epoch,
    iso_normalize,
    open_ro,
    process_cwd,
    runs_tool,
    unreadable_session,
)
from lost_sessions.hookspecs import hookimpl
from lost_sessions.models import Lineage, Live, ScanResult, Session, SourceStatus

_CREATED_HEAD_BYTES = 64 * 1024
_AGY_BIN = re.compile(r"agy(-bin[-.\w]*)?")
_TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
    r"(?:\s*([Zz]|[+-]\d{2}:?\d{2})(?:\s+[A-Za-z0-9_/+:-]+)?)?$"
)
_MONOTONIC_RE = re.compile(r"\s+m=[+-]?\d.*$")

_NON_TUI_SUBCOMMANDS = frozenset(
    {
        "acp",
        "agent",
        "agents",
        "changelog",
        "help",
        "install",
        "mcp",
        "mic-serve",
        "models",
        "plugin",
        "plugins",
        "remote-control",
        "update",
    }
)
_CONVERSATION_FLAGS = frozenset({"--conversation", "--resume", "-r"})
_CONVERSATION_PREFIXES = ("--conversation=", "--resume=", "-r=")
_VALUE_FLAGS = frozenset(
    {
        "--add-dir",
        "--agent",
        "--conversation",
        "--effort",
        "--input-format",
        "--json-schema",
        "--log-file",
        "--mode",
        "--model",
        "--output-format",
        "--print",
        "--print-timeout",
        "--project",
        "--prompt",
        "--prompt-interactive",
        "--resume",
        "--settings",
        "-i",
        "-p",
        "-r",
    }
)
_HELP_FLAGS = frozenset({"-h", "--help", "--version"})
_OPTIONAL_COLUMNS = (
    ("title", "NULL"),
    ("preview", "NULL"),
    ("last_modified_time", "NULL"),
    ("workspace_uris", "NULL"),
    ("parent_conversation_id", "NULL"),
    ("nesting_depth", "0"),
)


def _normalize_timestamp(value: object) -> str | None:
    """Normalize ISO-8601, Go `time.Time`, or numeric epoch values to UTC `Z`."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("invalid timestamp type: bool")
    if isinstance(value, (int, float)):
        seconds = float(value)
        abs_val = abs(seconds)
        if abs_val >= 1e17:
            seconds /= 1e9
        elif abs_val >= 1e14:
            seconds /= 1e6
        elif abs_val >= 1e11:
            seconds /= 1e3
        try:
            return iso_from_epoch(seconds)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        raise TypeError(f"invalid timestamp type: {type(value).__name__}")
    text = _MONOTONIC_RE.sub("", value.strip()).strip()
    if not text:
        return None
    match = _TIMESTAMP_RE.match(text)
    if match:
        date_part, time_part, frac_part, offset_part = match.groups()
        frac = f".{frac_part[:6]}" if frac_part else ""
        if not offset_part or offset_part in ("Z", "z"):
            offset = "+00:00"
        elif ":" in offset_part:
            offset = offset_part
        else:
            offset = f"{offset_part[:3]}:{offset_part[3:]}"
        try:
            parsed = dt.datetime.fromisoformat(f"{date_part}T{time_part}{frac}{offset}")
        except ValueError:
            return None
        return parsed.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_normalize(text)


def _uri_to_local_path(candidate: str) -> str | None:
    """Convert one `file://` URI or bare absolute path into a normalized local path."""
    text = candidate.strip()
    if not text:
        return None
    if text.startswith("file://"):
        parsed = urlparse(text)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            return None
        path = unquote(parsed.path)
    elif "://" in text:
        return None
    else:
        path = text
    if not path.startswith("/"):
        return None
    return "/" if path == "/" else path.rstrip("/")


def _extract_spawn_dir(raw: object) -> str | None:
    """Extract the first valid local workspace path from `workspace_uris`."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(f"workspace_uris must be str, got {type(raw).__name__}")
    text = raw.strip()
    if not text:
        return None

    candidates: list[str] | None = None
    if text.startswith(("[", '"')):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            candidates = [item for item in parsed if isinstance(item, str)]
        elif isinstance(parsed, str):
            candidates = [parsed]

    if candidates is None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) == 1 and "," in lines[0]:
            parts = [part.strip() for part in lines[0].split(",") if part.strip()]
            if len(parts) > 1 and all(p.startswith(("file://", "/")) for p in parts):
                candidates = parts
            else:
                candidates = lines
        else:
            candidates = lines

    for candidate in candidates:
        local = _uri_to_local_path(candidate)
        if local is not None:
            return local
    return None


def _transcript_path(app_data: Path, sid: str) -> Path:
    return app_data / "brain" / sid / ".system_generated" / "logs" / "transcript.jsonl"


def _extract_top_level_created_at(text: str) -> object:
    """Scan a truncated JSON object prefix for a top-level `created_at` value."""
    decoder = json.JSONDecoder()
    n = len(text)
    i = 0
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n or text[i] != "{":
        return None
    i += 1
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n or text[i] != '"':
            return None
        try:
            key, i = decoder.raw_decode(text, i)
        except ValueError:
            return None
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n or text[i] != ":":
            return None
        i += 1
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            return None
        try:
            val, i = decoder.raw_decode(text, i)
        except ValueError:
            # Truncated mid-value (e.g., an oversized content string): no later
            # top-level key can exist within this bounded prefix.
            return None
        if key == "created_at":
            return val
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i < n and text[i] == ",":
            i += 1
        else:
            return None
    return None


def _read_created_at(transcript_path: Path) -> str | None:
    """Read `created_at` from line 1 of `transcript.jsonl` with a bounded read."""
    try:
        with transcript_path.open("rb") as fh:
            raw = fh.readline(_CREATED_HEAD_BYTES)
    except OSError:
        return None
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    try:
        obj = json.loads(text)
    except ValueError:
        if len(raw) == _CREATED_HEAD_BYTES and not raw.endswith(b"\n"):
            val = _extract_top_level_created_at(text)
            try:
                return _normalize_timestamp(val)
            except TypeError:
                return None
        return None
    if not isinstance(obj, dict):
        return None
    try:
        return _normalize_timestamp(obj.get("created_at"))
    except TypeError:
        return None


def _agy_process_args(argv: list[str]) -> list[str] | None:
    """Return CLI arguments for an interactive `agy` process, else None."""
    if not runs_tool(argv, "agy"):
        return None
    bin_idx = next(
        (i for i, tok in enumerate(argv[:2]) if _AGY_BIN.fullmatch(Path(tok).name)),
        None,
    )
    if bin_idx is None:
        return None
    args = argv[bin_idx + 1 :]
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in _HELP_FLAGS:
            return None
        if tok == "--":
            break
        if tok in _VALUE_FLAGS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if tok in _NON_TUI_SUBCOMMANDS:
            return None
        break
    return args


def _extract_conversation_id(args: list[str]) -> str | None:
    """Return the explicit `--conversation`/`--resume`/`-r` ID if passed."""
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            break
        if tok in _CONVERSATION_FLAGS:
            return args[i + 1] if i + 1 < len(args) else None
        for prefix in _CONVERSATION_PREFIXES:
            if tok.startswith(prefix):
                return tok.removeprefix(prefix) or None
        if tok in _VALUE_FLAGS:
            i += 2
            continue
        i += 1
    return None


def agy_directory_liveness(
    sessions_in_dir: list[Session], pid: int
) -> dict[str, tuple[Live, str]]:
    """Decide liveness for sessions in a directory where an interactive `agy`
    process runs without naming its conversation ID.

    sessions_in_dir: this directory's top-level sessions, newest `updated` first.
    Returns {session_id: (live, basis)} for any session whose verdict is set;
    sessions left out keep live="no".
    """
    if not sessions_in_dir:
        return {}
    newest = sessions_in_dir[0]
    return {
        newest.id: (
            "unknown",
            f"agy pid {pid} running in this directory; newest session assumed",
        )
    }


class Antigravity(AgentTool):
    name = "agy"
    needs_processes = True
    resume_in_dir = True

    @override
    def resume_args(self, session: Session) -> list[str]:
        return ["agy", "--conversation", session.id]

    @override
    def scan(self, ctx: ScanContext) -> ScanResult:
        app_data = ctx.home / ".gemini" / "antigravity-cli"
        db_path = app_data / "conversation_summaries.db"
        if not db_path.is_file():
            return ScanResult(
                sessions=[], source=SourceStatus(status="absent", path=str(db_path))
            )
        try:
            with closing(open_ro(db_path)) as db:
                cols = {
                    r[1]
                    for r in db.execute("PRAGMA table_info(conversation_summaries)")
                }
                if not cols:
                    raise SourceError(
                        f"agy: {db_path}: missing conversation_summaries table"
                    )
                if "conversation_id" not in cols:
                    raise SourceError(f"agy: {db_path}: missing conversation_id column")
                select_exprs = [
                    "conversation_id",
                    *(
                        col if col in cols else fallback
                        for col, fallback in _OPTIONAL_COLUMNS
                    ),
                ]
                rows = db.execute(
                    f"SELECT {', '.join(select_exprs)} FROM conversation_summaries"  # noqa: S608  # nosec B608 - constant column allowlist
                ).fetchall()
        except sqlite3.Error as exc:
            raise SourceError(f"agy: {db_path}: {exc}") from exc

        records: list[Session] = []
        for row in rows:
            try:
                records.append(self._record(row, app_data))
            except RECORD_ERRORS:
                sid = row[0]
                tpath = (
                    _transcript_path(app_data, sid)
                    if isinstance(sid, str) and sid
                    else None
                )
                transcript = (
                    str(tpath) if tpath is not None and tpath.is_file() else None
                )
                records.append(unreadable_session("agy", sid, transcript))
        hidden = sum(r.hidden for r in records)

        by_dir: dict[str, list[Session]] = {}
        for rec in records:
            if not rec.hidden and rec.spawn_dir:
                by_dir.setdefault(rec.spawn_dir, []).append(rec)
        known = {rec.id: rec for rec in records if not rec.unreadable}
        for pid, argv in ctx.processes.items():
            args = _agy_process_args(argv)
            if args is None:
                continue
            named = _extract_conversation_id(args)
            if named is not None:
                if named in known:
                    session = known[named]
                    session.live = "yes"
                    session.live_host = "cli"
                    session.pid = pid
                    session.live_basis = f"agy pid {pid} --conversation {named}"
                continue
            cwd = process_cwd(pid)
            group = sorted(
                by_dir.get(cwd or "", []), key=lambda r: r.updated or "", reverse=True
            )
            for sid, (live, basis) in agy_directory_liveness(group, pid).items():
                if known[sid].live != "yes":
                    known[sid].live = live
                    known[sid].live_basis = basis
                    known[sid].pid = pid if live == "yes" else None

        for rec in records:
            if rec.unreadable:
                continue
            if rec.live == "yes":
                rec.resume_blocked = "running"
            elif not rec.spawn_dir:
                rec.resume_blocked = "no_workspace"
            else:
                prefix = cd_prefix(rec.spawn_dir)
                rec.resume = f"{prefix}agy --conversation {shlex.quote(rec.id)}"

        return ScanResult(
            sessions=records,
            source=SourceStatus(status="ok", path=str(db_path)),
            hidden_subagents=hidden,
        )

    def _record(self, row: tuple[object, ...], app_data: Path) -> Session:
        (
            sid,
            title,
            preview,
            last_modified_time,
            workspace_uris,
            parent_conversation_id,
            nesting_depth,
        ) = row
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("conversation_id must be a non-empty string")
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string")
        if preview is not None and not isinstance(preview, str):
            raise TypeError("preview must be a string")
        if parent_conversation_id is not None and not isinstance(
            parent_conversation_id, str
        ):
            raise TypeError("parent_conversation_id must be a string")
        if nesting_depth is None:
            depth = 0
        elif isinstance(nesting_depth, int) and not isinstance(nesting_depth, bool):
            depth = nesting_depth
        elif isinstance(nesting_depth, str):
            depth = int(nesting_depth)
        else:
            raise TypeError("nesting_depth must be an integer")

        spawn_dir = _extract_spawn_dir(workspace_uris)
        tpath = _transcript_path(app_data, sid)
        has_transcript = tpath.is_file()
        # `created` comes strictly from line 1 of transcript.jsonl; never
        # substitute last_modified_time, which changes on post-boot touches.
        created = _read_created_at(tpath) if has_transcript else None
        updated = _normalize_timestamp(last_modified_time)
        if updated is None and has_transcript:
            try:
                updated = iso_from_epoch(tpath.stat().st_mtime)
            except OSError:
                updated = None

        rec_title = (title.strip() if title and title.strip() else None) or (
            preview.strip() if preview and preview.strip() else None
        )
        parent_id = (
            parent_conversation_id.strip()
            if parent_conversation_id and parent_conversation_id.strip()
            else None
        )

        rec = Session(
            tool="agy",
            id=sid,
            name=None,
            title=rec_title,
            spawn_dir=spawn_dir,
            created=created,
            updated=updated,
            transcript=str(tpath) if has_transcript else None,
            live_basis="no agy process",
        )
        if depth > 0:
            rec.lineage = Lineage(kind="subagent", parent_id=parent_id)
            rec.hidden = True
        elif parent_id:
            rec.lineage = Lineage(kind="fork", parent_id=parent_id)
        return rec


@hookimpl
def register_agent_tools(register: Callable[[AgentTool], None]) -> None:
    register(Antigravity())
