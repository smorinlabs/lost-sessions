"""Herdr session-manager plugin.

A session counts as "in Herdr" when its ID is in the last Herdr snapshot saved
before the boot, or in the current layout, of any Herdr session.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, override

import click

from lost_sessions.hookspecs import hookimpl
from lost_sessions.managers import (
    Destination,
    Destinations,
    Plan,
    SessionManager,
    Step,
    result_of,
    run_json,
)

# Herdr records Claude and Codex sessions through its own integrations. Muse has
# none and OpenCode's is optional, so for them the resume command is reported.
REPORT_TOOLS = ("muse", "opencode")
LOG_SOURCE = "lost-sessions"


def _layout_ids(path: Path, prefix: str = "") -> dict[str, str]:
    """Map session id -> 'workspace / tab' for one Herdr layout file."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    idx: dict[str, str] = {}
    try:
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
    except (TypeError, AttributeError):  # a layout of another shape: unreadable
        return {}
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


def agent_name(tool: str, sid: str) -> str:
    """Unique per session: Codex and Muse IDs are time-ordered, so their prefixes
    collide."""
    digest = hashlib.sha1(sid.encode(), usedforsecurity=False).hexdigest()[:10]
    return f"lost-{tool}-{digest}"


class HerdrDestination(Destination):
    session: str | None = None  # a named Herdr session; None is the default one


class HerdrDestinations(Destinations):
    """Herdr workspaces. Existing ones are keyed by ID: two workspaces can share
    a label."""

    def __init__(
        self,
        default_label: str,
        available: bool,
        workspaces: list[dict[str, Any]],
        session: str | None,
    ) -> None:
        super().__init__(default_label, available)
        self.workspaces = workspaces
        self.session = session

    def _for(self, entry: Mapping[str, Any]) -> Destination:
        key = ("id", str(entry.get("workspace_id")))
        if key not in self.pool:
            self.pool[key] = HerdrDestination(
                manager="herdr",
                label=str(entry.get("label")),
                id=entry.get("workspace_id"),
                session=self.session,
            )
        return self.pool[key]

    @override
    def get(self, label: str) -> Destination:
        hit = next((e for e in self.workspaces if e.get("workspace_id") == label), None)
        hit = hit or next((e for e in self.workspaces if e.get("label") == label), None)
        if hit:
            return self._for(hit)
        key = ("new", label)
        if key not in self.pool:
            self.pool[key] = HerdrDestination(
                manager="herdr", label=label, session=self.session
            )
        return self.pool[key]

    @override
    def choices(self) -> list[Destination]:
        out: list[Destination] = []
        for d in [self.default()] + [self._for(e) for e in self.workspaces]:
            if all(d is not o for o in out):
                out.append(d)
        return out

    @override
    def ambiguous(self, label: str) -> list[str]:
        ids = [
            str(e.get("workspace_id"))
            for e in self.workspaces
            if e.get("label") == label
        ]
        return ids if len(ids) > 1 else []


def _herdr(session: str | None) -> list[str]:
    return ["herdr"] + (["--session", session] if session else [])


class Herdr(SessionManager):
    name = "herdr"
    display_name = "Herdr"
    restores = True
    can_open = True
    open_help = "open in a Herdr workspace"
    destination_noun = ("workspace", "workspaces")

    @override
    def restored_ids(self, boot: dt.datetime) -> dict[str, str]:
        return herdr_index(Path.home() / ".config" / "herdr", boot)

    @override
    def click_options(self) -> list[click.Option]:
        return [
            click.Option(
                ["--workspace"],
                default="recovered",
                metavar="LABEL",
                help="default Herdr workspace (default: recovered, created if missing)",
            ),
            click.Option(
                ["--herdr-session"],
                metavar="NAME",
                help="a named Herdr session instead of the default one",
            ),
        ]

    @override
    def destinations(self, options: Mapping[str, Any]) -> Destinations:
        session = options.get("herdr_session")
        response = run_json([*_herdr(session), "workspace", "list"])
        ws = result_of(response.data).get("workspaces", [])
        workspaces = (
            [w for w in ws if isinstance(w, dict)] if isinstance(ws, list) else []
        )
        return HerdrDestinations(
            options.get("workspace") or "recovered",
            response.code == 0,
            workspaces,
            session,
        )

    @override
    def plan(self, p: Plan, dest: Destination) -> list[Step]:
        session = dest.session if isinstance(dest, HerdrDestination) else None
        herdr = _herdr(session)
        if dest.id:
            steps = [
                Step(
                    argv=[
                        *herdr,
                        "tab",
                        "create",
                        "--workspace",
                        dest.id,
                        "--cwd",
                        p.cwd,
                        "--label",
                        p.label,
                        "--no-focus",
                    ],
                    opens=True,
                )
            ]
        else:
            steps = [
                Step(
                    argv=[
                        *herdr,
                        "workspace",
                        "create",
                        "--label",
                        dest.label,
                        "--cwd",
                        p.cwd,
                        "--no-focus",
                    ],
                    opens=True,
                ),
                Step(argv=[*herdr, "tab", "rename", "{tab}", p.label], cosmetic=True),
            ]
        s = p.session
        name = agent_name(s.tool, s.id)
        steps.append(
            Step(
                argv=[
                    *herdr,
                    "agent",
                    "start",
                    name,
                    "--kind",
                    s.tool,
                    "--pane",
                    "{pane}",
                    "--",
                    *p.resume.argv[1:],
                ]
            )
        )
        if s.tool in REPORT_TOOLS:
            steps.append(
                Step(
                    argv=[
                        *herdr,
                        "pane",
                        "report-agent",
                        "{pane}",
                        "--source",
                        LOG_SOURCE,
                        "--agent",
                        s.tool,
                        "--state",
                        "idle",
                        "--agent-session-id",
                        s.id,
                        "--",
                        *p.resume.argv,
                    ]
                )
            )
        return steps

    @override
    def on_response(
        self,
        step: Step,
        result: dict[str, Any],
        dest: Destination,
        fills: dict[str, str],
    ) -> dict[str, Any] | None:
        pane = result.get("root_pane")
        if not isinstance(pane, dict):
            return None
        pane_id, tab_id = pane.get("pane_id"), pane.get("tab_id")
        if not (
            isinstance(pane_id, str) and pane_id and isinstance(tab_id, str) and tab_id
        ):
            return None  # an opening step then fails: nothing opened we can address
        fills["{pane}"], fills["{tab}"] = pane_id, tab_id
        dest.id = dest.id or pane.get("workspace_id")
        return {
            "herdr_workspace": dest.id,
            "herdr_tab": pane.get("tab_id"),
            "herdr_pane": pane.get("pane_id"),
        }

    @override
    def blocked_note(
        self, error: Mapping[str, Any], fills: Mapping[str, str]
    ) -> str | None:
        if error.get("code") != "agent_not_ready":
            return None
        return (
            f"opened in Herdr pane {fills.get('{pane}')}, waiting at a startup prompt "
            "(usually folder trust); answer it in Herdr"
        )

    @override
    def focus_command(
        self, opened: Mapping[str, Any], options: Mapping[str, Any]
    ) -> list[str] | None:
        """`herdr tab focus` also switches to the tab's workspace."""
        if not opened.get("herdr_tab"):
            return None
        return [
            *_herdr(options.get("herdr_session")),
            "tab",
            "focus",
            opened["herdr_tab"],
        ]

    @override
    def workspaces_lines(self, dests: Destinations) -> list[str]:
        lines = ["Herdr workspaces (--workspace, or REF@LABEL with --herdr):"]
        workspaces = dests.workspaces if isinstance(dests, HerdrDestinations) else []
        tabs = {w.get("workspace_id"): w.get("tab_count", 0) for w in workspaces}
        for i, d in enumerate(dests.choices()):
            extra = (
                f"{d.id:<6} {tabs.get(d.id, 0)} tabs"
                if d.id
                else "created on first use"
            )
            lines.append(
                f"  {dests.describe(d):<40} {extra}"
                + ("   (default)" if i == 0 else "")
            )
        return lines

    @override
    def unreachable(self) -> str:
        return "could not reach Herdr (`herdr workspace list` failed)"

    @override
    def warnings(self, labels: Sequence[str], options: Mapping[str, Any]) -> list[str]:
        return []


@hookimpl
def register_session_managers(register: Callable[[SessionManager], None]) -> None:
    register(Herdr())
