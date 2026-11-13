"""Core: the selection window, labels, refusals and the Print action.

Ported from smorin/smorin-bootstrap utils/bin/lost-sessions at 713e443. Core
never names an agent or a session manager: it reaches them through the
plugins (design 0006, Sections 2 and 6.3).
"""

from __future__ import annotations

import datetime as dt
import re
import shlex
import subprocess  # nosec B404 - fixed argv lists, never a shell
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from lost_sessions.agents import AgentTool
from lost_sessions.history import HistoryEntry, Listing
from lost_sessions.managers import SessionManager
from lost_sessions.models import Session
from lost_sessions.plugins import get_session_managers, pm

# Matched as text against spawn_dir, never opened or created.
HELPER_DIRS = ("/private/tmp/claude-", "/tmp/claude-")  # noqa: S108  # nosec B108
HELPER_PATH_PARTS = ("/lost-sessions-live-",)  # throwaway sessions from the live test
HELPER_TITLES = ("Codex Companion Task",)
ABOUT_MAX = 100  # Muse titles can be a whole prompt
LISTING_MAX_AGE = dt.timedelta(days=1)

RED = "\033[0;31m"
YELLOW = "\033[1;33m"
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
BOLD = "\033[1m"
RESET = "\033[0m"


def error(msg: str) -> None:
    print(f"{RED}{BOLD}✖  ERROR:{RESET}{RED} {msg}{RESET}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"{YELLOW}⚠  {msg}{RESET}", file=sys.stderr)


def success(msg: str) -> None:
    print(f"{GREEN}✔  {msg}{RESET}")


def info(msg: str) -> None:
    print(f"{BLUE}→{RESET}  {msg}")


# --- plugins ----------------------------------------------------------------------


def agent_tools() -> dict[str, AgentTool]:
    from lost_sessions.inventory import agent_tools as registered

    return registered(pm)


def session_managers() -> dict[str, SessionManager]:
    found = get_session_managers(pm)
    return {
        name: m for name, m in sorted(found.items()) if isinstance(m, SessionManager)
    }


# --- the window -----------------------------------------------------------------


def boot_time() -> dt.datetime:
    """The last boot, in local time: `sysctl kern.boottime` (macOS), else /proc/stat."""
    try:
        out = subprocess.run(  # nosec B603 - fixed argv, no shell
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        found = re.search(r"sec = (\d+)", out)
    except (OSError, subprocess.CalledProcessError):
        found = None
    if found is None:  # Linux
        found = re.search(r"^btime (\d+)$", Path("/proc/stat").read_text(), re.M)
    if found is None:
        raise OSError("cannot determine the boot time")
    return dt.datetime.fromtimestamp(int(found.group(1))).astimezone()


def default_start(boot: dt.datetime) -> dt.datetime:
    """00:00 local time on the day before the boot, whenever the command runs."""
    day = boot.astimezone().date() - dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(0)).astimezone()


def parse_since(
    value: str | None, boot: dt.datetime, now: dt.datetime | None = None
) -> dt.datetime:
    """`--since`: None (day before boot), <n>m|h|d|w, or an ISO date or date-time
    (local time). Raises ValueError for anything else."""
    if value is None:
        return default_start(boot)
    now = now or dt.datetime.now().astimezone()
    m = re.fullmatch(r"(\d+)([mhdw])", value)
    if m:
        unit = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[m.group(2)]
        return now - dt.timedelta(**{unit: int(m.group(1))})
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return dt.datetime.combine(
            dt.date.fromisoformat(value), dt.time(0)
        ).astimezone()
    parsed = dt.datetime.fromisoformat(value)  # ValueError on anything else
    return parsed if parsed.tzinfo else parsed.astimezone()


def _parse(ts: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(ts) if ts else None


class Row(BaseModel):
    """A session in the window, numbered by start time."""

    n: int
    session: Session


def select_rows(
    sessions: Sequence[Session], boot: dt.datetime, start: dt.datetime
) -> list[Row]:
    """Sessions started before boot and active since start, numbered by start time.

    Start time never changes, so resuming a session does not renumber the list.
    """
    picked = []
    for s in sessions:
        created, updated = _parse(s.created), _parse(s.updated)
        if created and updated and created < boot and updated >= start:
            picked.append(s)
    picked.sort(key=lambda s: (_parse(s.created), s.id))
    return [Row(n=n, session=s) for n, s in enumerate(picked, 1)]


def short_ids(rows: Sequence[Row], minimum: int = 8) -> dict[str, str]:
    """Shortest unique ID prefix per row, at least `minimum` characters (git-style)."""
    ids = [r.session.id for r in rows]
    out = {}
    for sid in ids:
        k = min(minimum, len(sid))
        while k < len(sid) and any(o != sid and o.startswith(sid[:k]) for o in ids):
            k += 1
        out[sid] = sid[:k]
    return out


def about(s: Session) -> str:
    text = " ".join((s.title or s.name or "(untitled)").split())
    return text if len(text) <= ABOUT_MAX else text[: ABOUT_MAX - 1] + "…"


def folder_missing(s: Session) -> bool:
    return bool(s.spawn_dir) and not Path(s.spawn_dir or "").is_dir()


def is_helper(s: Session) -> bool:
    """A run another session started in a throwaway folder; nothing to resume."""
    label = s.title or s.name or ""  # Codex keeps this text in `name`
    folder = s.spawn_dir or ""
    return (
        folder.startswith(HELPER_DIRS)
        or any(p in folder for p in HELPER_PATH_PARTS)
        or label.startswith(HELPER_TITLES)
    )


def hidden_by_default(s: Session) -> bool:
    """Running or restored by a manager: only Print applies, so `--all` reveals them."""
    return bool(s.restored_by) or s.live == "yes"


def refusal(s: Session, action: str) -> str | None:
    """Why a manager may not open this session; None when allowed. Print always is."""
    if action == "print":
        return None
    if s.live == "yes":
        return "already running"
    if s.restored_by:
        display, label = s.restored_by
        return f"already in {display} ({label})"
    if folder_missing(s):
        return f"its folder no longer exists: {s.spawn_dir}"
    return None


def state_label(s: Session) -> str:
    if s.live == "yes":
        return "RUNNING"
    if s.live == "unknown":
        return "maybe running"
    if s.restored_by:
        return f"in {s.restored_by[0]}"
    if folder_missing(s):
        return "folder missing"
    return ""


def resume_args(s: Session) -> list[str]:
    return agent_tools()[s.tool].resume_args(s)


def resume_command(s: Session) -> str:
    """The inventory's resume command, or one built from the ID when it withholds
    it (e.g. running)."""
    if s.resume:
        return s.resume
    argv = shlex.join(resume_args(s))
    d = s.spawn_dir
    in_dir = agent_tools()[s.tool].resume_in_dir
    return f"cd {shlex.quote(d)} && {argv}" if d and in_dir else argv


# --- loading the window ---------------------------------------------------------


class Window(BaseModel):
    boot: dt.datetime
    start: dt.datetime
    rows: list[Row]


def load_rows(since: str | None) -> Window:
    """Exits 2 on a bad --since."""
    from lost_sessions.inventory import collect, select

    boot = boot_time()
    try:
        start = parse_since(since, boot)
    except ValueError:
        error(
            f"--since {since!r}: use a date (2026-11-09), a date-time, "
            "or <n>m|h|d|w (e.g. 3d)"
        )
        sys.exit(2)
    inv = collect()
    if inv.failed:  # partial failure: one store unreadable, the others still listed
        for tool in inv.failed:
            warn(f"could not read {tool}: {inv.sources[tool].message}")
        warn("some sessions may be missing from this list")
    since_utc = start.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = select_rows(select(inv, since=since_utc), boot, start)
    restored: dict[str, tuple[str, str]] = {}
    for manager in session_managers().values():
        for sid, label in manager.restored_ids(boot).items():
            restored.setdefault(sid, (manager.display_name, label))
    for r in rows:
        r.session.restored_by = restored.get(r.session.id)
    return Window(boot=boot, start=start, rows=rows)


def restoring_managers() -> list[str]:
    """Display names of the managers that restore sessions by themselves."""
    return [m.display_name for m in session_managers().values() if m.restores]


def visible(rows: Sequence[Row], *, show_all: bool, include_helpers: bool) -> list[Row]:
    def keep(r: Row) -> bool:
        if not include_helpers and is_helper(r.session):
            return False
        return show_all or not hidden_by_default(r.session)

    return [r for r in rows if keep(r)]


def resolve_refs(
    refs: Sequence[str], rows: Sequence[Row], listing: Listing | None
) -> tuple[list[Row], list[str]]:
    """Map each REF (a number from the saved listing, or a full or unique-prefix
    session ID) to a row."""
    by_id = {r.session.id: r for r in rows}
    picked, problems = [], []
    for ref in refs:
        if re.fullmatch(r"\d{1,4}", ref):
            if not listing:
                problems.append(
                    f"#{ref}: no saved listing; run `lost-sessions list` first, "
                    "or use a session ID"
                )
                continue
            hit = next((r for r in listing.rows if r.n == int(ref)), None)
            if not hit:
                problems.append(f"#{ref} is not in the last listing")
            elif hit.id not in by_id:
                problems.append(f"#{ref} ({hit.id}) is no longer in the window")
            else:
                picked.append(by_id[hit.id])
            continue
        matches = [r for r in rows if r.session.id.startswith(ref)]
        if len(matches) == 1:
            picked.append(matches[0])
        elif not matches:
            problems.append(f"{ref}: no session ID starts with this")
        else:
            problems.append(
                f"{ref} matches {len(matches)} sessions: "
                + ", ".join(r.session.id for r in matches[:5])
            )
    return picked, problems


# --- the Print action -----------------------------------------------------------


def execute_print(r: Row) -> HistoryEntry:
    """The Print action: show the resume command; runs nothing."""
    s = r.session
    entry = HistoryEntry.new(
        action="print",
        tool=s.tool,
        id=s.id,
        about=about(s),
        dir=s.spawn_dir,
        commands=[resume_command(s)],
    )
    if folder_missing(s):
        entry.note = f"its folder no longer exists: {s.spawn_dir}"
    return entry


def exit_status(entries: Sequence[HistoryEntry]) -> int:
    """1 when any action failed or was skipped; blocked (opened, waiting at a
    prompt) counts as done."""
    return 1 if any(e.result in ("failed", "skipped") for e in entries) else 0
