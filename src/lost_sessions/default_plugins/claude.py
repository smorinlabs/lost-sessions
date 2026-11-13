"""Claude Code agent plugin: transcripts under ~/.claude/projects."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import override

from lost_sessions.agents import (
    HEAD_LINES,
    RECORD_ERRORS,
    TAIL_BYTES,
    AgentTool,
    ScanContext,
    cd_prefix,
    iso_from_epoch,
    iso_normalize,
    unreadable_session,
    utc_lstart,
)
from lost_sessions.hookspecs import hookimpl
from lost_sessions.models import ScanResult, Session, SourceStatus


def claude_registry(home: Path) -> dict[str, dict]:
    """sessionId -> live-registry entry, for entries whose process is really alive."""
    live = {}
    reg = home / ".claude" / "sessions"
    for entry_path in sorted(reg.glob("*.json")) if reg.is_dir() else []:
        try:
            entry = json.loads(entry_path.read_text())
            pid, sid = int(entry["pid"]), entry["sessionId"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        started = utc_lstart(pid)
        recorded = " ".join(str(entry.get("procStart", "")).split())
        if started and started == recorded:
            live[sid] = entry
    return live


def _field(line: str, key: str) -> str | None:
    try:
        return json.loads(line).get(key)
    except (ValueError, AttributeError):
        return None


def claude_title_and_name(path: Path) -> tuple[str | None, str | None]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - TAIL_BYTES))
        tail = fh.read().decode("utf-8", "replace").splitlines()
    title = name = None
    for line in reversed(tail):
        if title is None and '"ai-title"' in line:
            title = _field(line, "aiTitle")
        if name is None and '"custom-title"' in line:
            name = _field(line, "customTitle")
        if title and name:
            break
    return title, name


class ClaudeCode(AgentTool):
    name = "claude"

    @override
    def resume_args(self, session: Session) -> list[str]:
        return ["claude", "--resume", session.id]

    @override
    def scan(self, ctx: ScanContext) -> ScanResult:
        root = ctx.home / ".claude" / "projects"
        if not root.is_dir():
            return ScanResult(
                sessions=[], source=SourceStatus(status="absent", path=str(root))
            )
        live = claude_registry(ctx.home)
        records = []
        for path in sorted(root.glob("*/*.jsonl")):
            try:
                records.append(self._record(path, live))
            except RECORD_ERRORS:
                records.append(unreadable_session("claude", path.stem, str(path)))
        return ScanResult(
            sessions=records, source=SourceStatus(status="ok", path=str(root))
        )

    def _record(self, path: Path, live: dict[str, dict]) -> Session:
        rec = Session(tool="claude", id=path.stem)
        rec.transcript = str(path)
        rec.updated = iso_from_epoch(path.stat().st_mtime)
        parsed_any = False
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _, line in zip(range(HEAD_LINES), fh, strict=False):
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):  # valid JSON that is not a record
                    continue
                parsed_any = True
                if obj.get("cwd") and not rec.spawn_dir:
                    rec.spawn_dir = obj["cwd"]
                    rec.branch = obj.get("gitBranch")
                if obj.get("timestamp") and not rec.created:
                    rec.created = iso_normalize(obj["timestamp"])
                if rec.spawn_dir and rec.created:
                    break
        if not parsed_any:
            rec.unreadable = True
            return rec
        rec.title, rec.name = claude_title_and_name(path)
        entry = live.get(rec.id)
        if entry:
            rec.live = "yes"
            rec.live_host = "cli"
            rec.pid = entry["pid"]
            rec.tmux = entry.get("tmux")
            rec.live_basis = f"registry pid {entry['pid']} alive, start time matches"
            rec.name = rec.name or entry.get("name")
        else:
            rec.live_basis = "no live registry entry"
        if rec.live == "yes":
            rec.resume_blocked = "running"
        elif rec.spawn_dir:
            rec.resume = f"{cd_prefix(rec.spawn_dir)}claude --resume {rec.id}"
        else:
            rec.resume_blocked = "no_workspace"
        return rec


@hookimpl
def register_agent_tools(register: Callable[[AgentTool], None]) -> None:
    register(ClaudeCode())
