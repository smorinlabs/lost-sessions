"""Session inventory: the stable public API (design 0006, Q-H).

`collect()` scans the selected agents and returns an `Inventory`; `select()`
applies the `--live`, `--since` and `--include-subagents` filters, as
`session-inventory list` does after its own `collect()`.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from pathlib import Path

from lost_sessions.agents import (
    AgentTool,
    ScanContext,
    SourceError,
    iso_normalize,
    processes,
)
from lost_sessions.models import Census, Inventory, ScanResult, Session, SourceStatus
from lost_sessions.plugins import PluginManager, get_agent_tools, load_plugins, pm


def agent_tools(manager: PluginManager = pm) -> dict[str, AgentTool]:
    """Registered agent plugins by name, in name order."""
    load_plugins(manager)
    tools = get_agent_tools(manager)
    return {
        name: tool
        for name, tool in sorted(tools.items())
        if isinstance(tool, AgentTool)
    }


def collect(
    tools: Sequence[str] | None = None,
    *,
    home: Path | None = None,
    manager: PluginManager = pm,
) -> Inventory:
    """Scan `tools` (default: every registered agent) and report what was found."""
    registered = agent_tools(manager)
    names = list(dict.fromkeys(tools)) if tools else list(registered)
    selected = [registered[name] for name in names]
    procs = processes() if any(t.needs_processes for t in selected) else {}
    ctx = ScanContext(home=home or Path.home(), processes=procs)
    sessions: list[Session] = []
    census: dict[str, Census] = {}
    sources: dict[str, SourceStatus] = {}
    failed: list[str] = []
    for tool in selected:
        try:
            result = tool.scan(ctx)
        except (SourceError, OSError) as exc:
            result = ScanResult(
                sessions=[], source=SourceStatus(status="error", message=str(exc))
            )
            failed.append(tool.name)
        recs = result.sessions
        sources[tool.name] = result.source
        census[tool.name] = Census(
            listed=sum(not r.hidden for r in recs),
            hidden_subagents=result.hidden_subagents,
            unreadable=sum(r.unreadable for r in recs),
            live=sum(r.live == "yes" and not r.hidden for r in recs),
        )
        sessions.extend(recs)
    return Inventory(sessions=sessions, census=census, sources=sources, failed=failed)


def parse_since(value: str) -> str:
    """`<n>m|h|d|w` or an ISO date/date-time -> an ISO 8601 UTC string.

    Raises ValueError for anything else.
    """
    match = re.fullmatch(r"(\d+)([mhdw])", value)
    if match:
        unit = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[match.group(2)]
        point = dt.datetime.now(dt.UTC) - dt.timedelta(**{unit: int(match.group(1))})
        return point.strftime("%Y-%m-%dT%H:%M:%SZ")
    normalized = iso_normalize(value if "T" in value else f"{value}T00:00:00+00:00")
    if normalized is None:
        raise ValueError(f"invalid --since {value!r}: use <n>m|h|d|w or an ISO date")
    return normalized


def select(
    inventory: Inventory,
    *,
    live: bool = False,
    since: str | None = None,
    include_subagents: bool = False,
) -> list[Session]:
    """Filter and sort: newest activity first, then tool, then id."""
    keep = []
    for rec in inventory.sessions:
        if rec.hidden and not include_subagents:
            continue
        if live and rec.live == "no":  # keep `unknown`: possibly running
            continue
        if since and (rec.updated or "") < since:
            continue
        keep.append(rec)
    keep.sort(key=lambda r: (r.tool, r.id))
    keep.sort(key=lambda r: r.updated or "", reverse=True)
    return keep
