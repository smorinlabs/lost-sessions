"""Codex agent plugin: rollouts under $CODEX_HOME (default ~/.codex)."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess  # nosec B404 - fixed argv lists, never a shell
from collections.abc import Callable
from pathlib import Path
from typing import override

from lost_sessions.agents import AgentTool, ScanContext, iso_from_epoch, iso_normalize
from lost_sessions.hookspecs import hookimpl
from lost_sessions.models import Lineage, ScanResult, Session, SourceStatus

CODEX_HIDDEN_SOURCES = {"subagent", "guardian_review"}
_ID = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)


def codex_held_locks(lock_dir: Path) -> dict[str, int]:
    """thread id -> pid holding its writer lock open (one lsof call)."""
    if not lock_dir.is_dir():
        return {}
    out = subprocess.run(  # noqa: S603  # nosec B603 B607 - fixed argv, no shell
        ["lsof", "-Fpn", "+D", str(lock_dir)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    held: dict[str, int] = {}
    pid = None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and line.endswith(".lock") and pid is not None:
            held[Path(line[1:]).stem] = pid
    return held


def codex_names(root: Path) -> dict[str, str]:
    names = {}
    index = root / "session_index.jsonl"
    if index.is_file():
        for line in index.read_text(errors="replace").splitlines():
            try:
                obj = json.loads(line)
                if obj.get("thread_name"):
                    names[obj["id"]] = obj["thread_name"]  # later lines win
            except (ValueError, KeyError, AttributeError):
                continue
    return names


class Codex(AgentTool):
    name = "codex"
    needs_processes = True

    @override
    def scan(self, ctx: ScanContext) -> ScanResult:
        root = (
            Path(os.environ["CODEX_HOME"])
            if os.environ.get("CODEX_HOME")
            else ctx.home / ".codex"
        )
        sessions = root / "sessions"
        if not sessions.is_dir():
            return ScanResult(
                sessions=[], source=SourceStatus(status="absent", path=str(sessions))
            )
        held = codex_held_locks(root / "thread-writer-locks")
        names = codex_names(root)
        records, hidden = [], 0
        for path in sorted(sessions.glob("*/*/*/rollout-*.jsonl")):
            match = _ID.search(path.name)
            rec = Session(tool="codex", id=match.group(1) if match else path.stem)
            rec.transcript = str(path)
            rec.updated = iso_from_epoch(path.stat().st_mtime)
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    meta = json.loads(fh.readline())["payload"]
                rec.id = meta.get("id", rec.id)
            except (ValueError, KeyError, TypeError, AttributeError):
                rec.unreadable = True
                records.append(rec)
                continue
            rec.spawn_dir = meta.get("cwd")
            rec.created = iso_normalize(meta.get("timestamp"))
            # source is "cli"/"exec", {"subagent": "review"}, or
            # {"subagent": {"thread_spawn": {...}}}
            source = meta.get("source")
            subagent = source.get("subagent") if isinstance(source, dict) else None
            spawn = (
                (subagent.get("thread_spawn") or {})
                if isinstance(subagent, dict)
                else {}
            )
            if meta.get("thread_source") in CODEX_HIDDEN_SOURCES:
                rec.lineage = Lineage(
                    kind="subagent", parent_id=spawn.get("parent_thread_id")
                )
                rec.hidden = True
                hidden += 1
            elif meta.get("forked_from_id"):
                rec.lineage = Lineage(kind="fork", parent_id=meta["forked_from_id"])
            rec.name = names.get(rec.id)
            rec.name_resumable = rec.name is not None
            if rec.id in held:
                pid = held[rec.id]
                # app-server hosts (IDE, desktop app, companion plugins) keep
                # many threads loaded
                host = (
                    "app-server"
                    if "app-server" in ctx.processes.get(pid, [])
                    else "cli"
                )
                rec.live = "yes"
                rec.live_host = host
                rec.pid = pid
                rec.resume_blocked = "running"
                rec.live_basis = f"writer lock held by pid {pid} ({host})"
            else:
                rec.live_basis = "writer lock not held"
                rec.resume = f"codex resume {rec.id}"
                if rec.name:
                    rec.resume_by_name = f"codex resume {shlex.quote(rec.name)}"
            records.append(rec)
        return ScanResult(
            sessions=records,
            source=SourceStatus(status="ok", path=str(sessions)),
            hidden_subagents=hidden,
        )


@hookimpl
def register_agent_tools(register: Callable[[AgentTool], None]) -> None:
    register(Codex())
