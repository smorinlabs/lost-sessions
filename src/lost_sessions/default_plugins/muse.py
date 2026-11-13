"""Muse agent plugin: the session index under $XDG_DATA_HOME/muse."""

from __future__ import annotations

import shlex
import socket
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import override

from lost_sessions.agents import (
    RECORD_ERRORS,
    AgentTool,
    ScanContext,
    SourceError,
    cd_prefix,
    data_home,
    iso_from_epoch,
    open_ro,
    runs_tool,
    unreadable_session,
)
from lost_sessions.hookspecs import hookimpl
from lost_sessions.models import Lineage, Live, ScanResult, Session, SourceStatus


def muse_liveness(
    session_dir: str, procs: dict[int, list[str]]
) -> tuple[Live, str, int | None]:
    lock = Path(session_dir) / ".session.lock"
    try:
        fields = dict(
            line.split("=", 1) for line in lock.read_text().splitlines() if "=" in line
        )
    except OSError:
        return "no", "no session lock", None
    host, pid = fields.get("host"), fields.get("pid", "")
    if host and host != socket.gethostname():
        return "unknown", f"lock held on another host ({host})", None
    if not pid.isdigit():
        return "unknown", "lock has no pid", None
    argv = procs.get(int(pid))
    if argv is None:
        return "no", f"stale lock, pid {pid} not running", None
    if not runs_tool(argv, "muse"):
        return "no", f"stale lock, pid {pid} is another program", None
    return "yes", f"lock pid {pid} alive (muse)", int(pid)


def muse_names(home: Path) -> dict[str, str]:
    """session id -> canonical name from Muse's name authority. The index's
    session_name column is only a projection and can be empty."""
    db_path = (
        home
        / "Library"
        / "Application Support"
        / "Muse"
        / "session-name-authority"
        / "session-names.db"
    )
    if not db_path.is_file():
        return {}
    try:
        with open_ro(db_path) as db:
            return dict(
                db.execute(
                    "SELECT session_id, normalized_name FROM session_name_claims"
                    " WHERE kind = 'canonical'"
                )
            )
    except sqlite3.Error:
        return {}


class Muse(AgentTool):
    name = "muse"
    needs_processes = True

    @override
    def resume_args(self, session: Session) -> list[str]:
        return ["muse", "resume", session.id]

    @override
    def scan(self, ctx: ScanContext) -> ScanResult:
        db_path = data_home(ctx.home) / "muse" / "session-index.db"
        if not db_path.is_file():
            return ScanResult(
                sessions=[], source=SourceStatus(status="absent", path=str(db_path))
            )
        try:
            with open_ro(db_path) as db:
                rows = db.execute(
                    "SELECT session_id, session_dir, session_log_path, workspace_root,"
                    " git_branch, title, session_name, created_at_us, updated_at_us,"
                    " msp_fork_source_session_id FROM sessions"
                ).fetchall()
        except sqlite3.Error as exc:
            raise SourceError(f"muse: {db_path}: {exc}") from exc
        names = muse_names(ctx.home)
        records = []
        for row in rows:
            try:
                records.append(self._record(row, names, ctx.processes))
            except RECORD_ERRORS:
                records.append(unreadable_session("muse", row[0], row[2]))
        return ScanResult(
            sessions=records, source=SourceStatus(status="ok", path=str(db_path))
        )

    def _record(
        self, row: tuple, names: dict[str, str], procs: dict[int, list[str]]
    ) -> Session:
        sid, sdir, log, ws, branch, title, name, created, updated, fork = row
        name = names.get(sid) or name
        rec = Session(
            tool="muse",
            id=sid,
            spawn_dir=ws or None,
            branch=branch,
            title=title,
            name=name,
            name_resumable=name is not None,
            transcript=log,
            export_command=f"muse export --session {sid}",
            created=iso_from_epoch(created / 1e6) if created else None,
            updated=iso_from_epoch(updated / 1e6) if updated else None,
        )
        if fork:
            rec.lineage = Lineage(kind="fork", parent_id=fork)
        rec.live, rec.live_basis, rec.pid = muse_liveness(sdir, procs)
        rec.live_host = "cli" if rec.live == "yes" else None
        if rec.live == "yes":
            rec.resume_blocked = "running"
        elif not rec.spawn_dir:
            rec.resume_blocked = "no_workspace"
        else:
            rec.resume = f"{cd_prefix(ws)}muse resume {sid}"
            if name:
                rec.resume_by_name = f"{cd_prefix(ws)}muse resume {shlex.quote(name)}"
        return rec


@hookimpl
def register_agent_tools(register: Callable[[AgentTool], None]) -> None:
    register(Muse())
