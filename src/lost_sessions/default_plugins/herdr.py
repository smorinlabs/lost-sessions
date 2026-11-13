"""Herdr session-manager plugin.

A session counts as "in Herdr" when its ID is in the last Herdr snapshot saved
before the boot, or in the current layout, of any Herdr session.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import override

from lost_sessions.hookspecs import hookimpl
from lost_sessions.managers import SessionManager


def _layout_ids(path: Path, prefix: str = "") -> dict[str, str]:
    """Map session id -> 'workspace / tab' for one Herdr layout file."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    idx = {}
    for ws in data.get("workspaces", []):
        for tab in ws.get("tabs", []):
            name = ws.get("custom_name") or ws.get("id")
            where = f"{prefix}{name} / {tab.get('custom_name') or '-'}"
            for pane in tab.get("panes", {}).values():
                sid = (pane.get("agent_session") or {}).get("value")
                if sid:
                    idx[sid] = where
                for token in (pane.get("agent_resume") or {}).get("argv", []):
                    idx[token] = where
    return idx


def _session_dir_ids(
    session_dir: Path, boot: dt.datetime, prefix: str = ""
) -> dict[str, str]:
    snap_dir = session_dir / "session-snapshots"
    snaps = (
        [p for p in snap_dir.glob("*.json") if p.stat().st_mtime < boot.timestamp()]
        if snap_dir.is_dir()
        else []
    )
    idx = {}
    if snaps:
        idx.update(_layout_ids(max(snaps, key=lambda p: p.stat().st_mtime), prefix))
    idx.update(_layout_ids(session_dir / "session.json", prefix))
    return idx


def herdr_index(herdr_dir: Path, boot: dt.datetime) -> dict[str, str]:
    """IDs Herdr will restore, across the default and every named Herdr session."""
    herdr_dir = Path(herdr_dir)
    idx = _session_dir_ids(herdr_dir, boot)
    if (herdr_dir / "sessions").is_dir():
        for d in sorted((herdr_dir / "sessions").iterdir()):
            if d.is_dir():
                idx.update(_session_dir_ids(d, boot, prefix=f"{d.name}: "))
    return idx


class Herdr(SessionManager):
    name = "herdr"
    display_name = "Herdr"
    restores = True

    @override
    def restored_ids(self, boot: dt.datetime) -> dict[str, str]:
        return herdr_index(Path.home() / ".config" / "herdr", boot)


@hookimpl
def register_session_managers(register: Callable[[SessionManager], None]) -> None:
    register(Herdr())
