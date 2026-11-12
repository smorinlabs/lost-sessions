"""OpenCode agent plugin: the session tables in $XDG_DATA_HOME/opencode/opencode.db."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import override

from lost_sessions.agents import (
    AgentTool,
    ScanContext,
    SourceError,
    cd_prefix,
    data_home,
    iso_from_epoch,
    open_ro,
    process_cwd,
    runs_tool,
)
from lost_sessions.hookspecs import hookimpl
from lost_sessions.models import Lineage, Live, ScanResult, Session, SourceStatus

_COLS = (
    "id, parent_id, slug, directory, title, time_created, time_updated, time_archived"
)


def opencode_directory_liveness(
    sessions_in_dir: list[Session], pid: int
) -> dict[str, tuple[Live, str]]:
    """Decide liveness for sessions in a directory where an opencode process runs
    without naming its session (`opencode` started bare, or with --continue).

    sessions_in_dir: this directory's top-level sessions, newest `updated` first.
    Returns {session_id: (live, basis)} for any session whose verdict is set;
    sessions left out keep live="no".

    Policy (owner decision, smorinlabs-skills PR #86): only the newest session is
    `unknown`. The process proves some session here may be running, not which
    one, so nothing is claimed as running and older sessions keep their resume
    command.
    """
    if not sessions_in_dir:
        return {}
    newest = sessions_in_dir[0]
    return {
        newest.id: (
            "unknown",
            f"opencode pid {pid} running in this directory; newest session assumed",
        )
    }


class OpenCode(AgentTool):
    name = "opencode"
    needs_processes = True

    @override
    def scan(self, ctx: ScanContext) -> ScanResult:
        db_path = data_home() / "opencode" / "opencode.db"
        if not db_path.is_file():
            return ScanResult(
                sessions=[], source=SourceStatus(status="absent", path=str(db_path))
            )
        try:
            with open_ro(db_path) as db:
                # Newer OpenCode releases write `session_v2`, which imports the old
                # `session` rows. The import stops once OpenCode marks the migration
                # done, so a row written to `session` afterwards exists only there:
                # list it as `legacy_only`, with no v2 command for it.
                tables = {
                    r[0]
                    for r in db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                legacy = []
                if "session_v2" in tables:
                    v2_cols = {
                        r[1] for r in db.execute("PRAGMA table_info(session_v2)")
                    }
                    fork_col = (
                        "fork_session_id" if "fork_session_id" in v2_cols else "NULL"
                    )
                    rows = db.execute(
                        f"SELECT {_COLS}, {fork_col} FROM session_v2"  # noqa: S608  # nosec B608 - constant columns
                    ).fetchall()
                    if "session" in tables:
                        legacy = db.execute(
                            f"SELECT {_COLS}, NULL FROM session"  # noqa: S608  # nosec B608 - constant columns
                            " WHERE id NOT IN (SELECT id FROM session_v2)"
                        ).fetchall()
                else:
                    rows = db.execute(
                        f"SELECT {_COLS}, NULL FROM session"  # noqa: S608  # nosec B608 - constant columns
                    ).fetchall()
        except sqlite3.Error as exc:
            raise SourceError(f"opencode: {db_path}: {exc}") from exc
        records: list[Session] = []
        hidden = 0
        legacy_ids = {row[0] for row in legacy}
        for (
            sid,
            parent,
            slug,
            directory,
            title,
            created,
            updated,
            archived,
            fork,
        ) in rows + legacy:
            rec = Session(
                tool="opencode",
                id=sid,
                name=slug,
                title=title,
                spawn_dir=directory or None,
                archived=archived is not None,
                created=iso_from_epoch(created / 1e3),
                updated=iso_from_epoch(updated / 1e3),
                export_command=None if sid in legacy_ids else f"opencode export {sid}",
                live_basis="no opencode process",
            )
            if parent:
                rec.lineage = Lineage(kind="subagent", parent_id=parent)
                rec.hidden = True
                hidden += 1
            elif fork:  # a user fork: listed, like Codex and Muse forks
                rec.lineage = Lineage(kind="fork", parent_id=fork)
            records.append(rec)

        by_dir: dict[str, list[Session]] = {}
        for rec in records:
            if not rec.hidden and rec.spawn_dir:
                by_dir.setdefault(rec.spawn_dir, []).append(rec)
        known = {rec.id: rec for rec in records}
        for pid, argv in ctx.processes.items():
            if not runs_tool(argv, "opencode"):
                continue
            named = next(
                (
                    argv[i + 1]
                    for i, tok in enumerate(argv[:-1])
                    if tok in ("-s", "--session")
                ),
                None,
            )
            if named in known:
                session = known[named]
                session.live = "yes"
                session.live_host = "cli"
                session.pid = pid
                session.live_basis = f"opencode pid {pid} --session {named}"
                continue
            cwd = process_cwd(pid)
            group = sorted(
                by_dir.get(cwd or "", []), key=lambda r: r.updated or "", reverse=True
            )
            for sid, (live, basis) in opencode_directory_liveness(group, pid).items():
                if known[sid].live != "yes":
                    known[sid].live = live
                    known[sid].live_basis = basis
                    known[sid].pid = pid if live == "yes" else None

        for rec in records:
            if rec.live == "yes":
                rec.resume_blocked = "running"
            elif rec.id in legacy_ids:
                rec.resume_blocked = "legacy_only"
            elif not rec.spawn_dir:
                rec.resume_blocked = "no_workspace"
            else:
                rec.resume = f"{cd_prefix(rec.spawn_dir)}opencode --session {rec.id}"
        return ScanResult(
            sessions=records,
            source=SourceStatus(
                status="ok", path=str(db_path), legacy_only=len(legacy_ids)
            ),
            hidden_subagents=hidden,
        )


@hookimpl
def register_agent_tools(register: Callable[[AgentTool], None]) -> None:
    register(OpenCode())
