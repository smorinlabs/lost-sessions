"""Explicit recording and read-only views of optional session evidence."""

from __future__ import annotations

import json
import sqlite3
from typing import override

import click
from pydantic import ValidationError

from lost_sessions.evidence import Store, Summary, summarize, validate_event
from lost_sessions.evidence_hooks import HookTool, normalize_hook
from lost_sessions.plugins import PluginManager


class SessionNotFound(click.ClickException):
    exit_code = 3


class EvidenceGroup(click.Group):
    """Keep evidence errors machine-readable when JSON output was requested."""

    @override
    def invoke(self, ctx: click.Context) -> object:
        args = ctx.args
        machine = (
            "--json" in args
            or "--output=json" in args
            or "-ojson" in args
            or any(
                arg in ("-o", "--output") and args[i + 1 : i + 2] == ["json"]
                for i, arg in enumerate(args)
            )
        )
        try:
            return super().invoke(ctx)
        except (click.ClickException, OSError, sqlite3.Error, ValueError) as exc:
            code = exc.exit_code if isinstance(exc, click.ClickException) else 1
            message = (
                exc.format_message()
                if isinstance(exc, click.ClickException)
                else str(exc)
            )
            if machine:
                click.echo(
                    json.dumps(
                        {
                            "error": {
                                "code": "invalid_input"
                                if code == 2
                                else "evidence_error",
                                "message": message,
                            }
                        }
                    ),
                    err=True,
                )
            else:
                click.echo(f"lost-sessions: {message}", err=True)
            ctx.exit(code)


def _read_document(path: str) -> object:
    with click.open_file(path, "r", encoding="utf-8") as stream:
        text = stream.read(1048577)
    if len(text.encode()) > 1048576:
        raise ValueError("input exceeds 1 MiB")
    return json.loads(text)


def summary_text(summary: Summary) -> str:
    fields = [
        f"coverage: {summary.coverage} ({summary.record_count} records)",
        f"first observed: {summary.first_observed_at or 'unknown'}",
        f"last opened: {summary.last_opened_at or 'unknown'}",
        f"last end observed: {summary.last_ended_at or 'unknown'}",
        f"closure evidence: {summary.closure}",
        f"last interaction: {summary.last_interaction_at or 'unknown'}",
        f"last task-directed turn: {summary.last_work_at or 'unknown'}",
    ]
    if summary.assessment:
        r = summary.assessment
        fields.extend(
            (
                f"work: {r.work_state} ({r.source}; {summary.assessment_currency})",
                f"scope: {r.scope}; assessed through: {r.through_turn}",
                f"note: {r.note}",
            )
        )
        fields.extend(f"remaining: {item}" for item in r.remaining)
        fields.extend(f"reference: {item}" for item in r.references)
    if summary.close_intent:
        r = summary.close_intent
        fields.append(f"closure declared: {r.occurred_at} ({r.source}): {r.note}")
    return "\n".join(fields)


def evidence_command(manager: PluginManager) -> click.Group:
    @click.group(name="evidence", cls=EvidenceGroup)
    def group() -> None:
        """Record optional evidence, or inspect its history and advisory summary."""

    @group.command(name="record")
    @click.option(
        "--file", "path", default="-", help="JSON input file; - reads stdin (default)"
    )
    @click.option("--dry-run", is_flag=True, help="validate and print without writing")
    @click.option("-o", "--output", type=click.Choice(["text", "json"]), default="text")
    @click.option("--json", "as_json", is_flag=True, help="same as --output json")
    def record(path: str, dry_run: bool, output: str, as_json: bool) -> None:
        """Append one event or assessment. Reuse record_id and event time on retry."""
        try:
            event = validate_event(_read_document(path))
        except ValidationError as exc:
            message = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'record'}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)
            )
            raise click.UsageError(message) from exc
        except (ValueError, UnicodeError) as exc:
            raise click.UsageError(str(exc)) from exc
        result = event if dry_run else Store().append(event)
        if as_json or output == "json":
            click.echo(result.model_dump_json())
        else:
            click.echo(
                f"{'Validated' if dry_run else 'Recorded'} {result.record_id}: "
                f"{result.kind} for {result.tool}:{result.session_id}"
            )

    def read(
        tool: str, session_id: str, output: str, as_json: bool, view: bool
    ) -> None:
        from lost_sessions.inventory import agent_tools, collect

        result = Store().read(tool, session_id)
        summary = summarize(result.records)
        native = None
        if view and tool in agent_tools(manager):
            inv = collect([tool], manager=manager)
            native = next((s for s in inv.sessions if s.id == session_id), None)
            result.warnings.extend(
                f"{name}: {inv.sources[name].message}" for name in inv.failed
            )
        if view and native is None and not result.records and not result.warnings:
            raise SessionNotFound(f"session not found: {tool}:{session_id}")
        if as_json or output == "json":
            doc = {"tool": tool, "session_id": session_id, "warnings": result.warnings}
            if view:
                doc.update(
                    session=native.model_dump(mode="json") if native else None,
                    evidence=summary.model_dump(mode="json"),
                )
            else:
                doc["records"] = [r.model_dump(mode="json") for r in result.records]
            click.echo(json.dumps(doc, indent=2))
        elif view:
            click.echo(f"{tool}:{session_id}")
            if native:
                click.echo(
                    f"created: {native.created or 'unknown'}\n"
                    f"live: {native.live} ({native.live_basis or 'no basis'})"
                )
            click.echo(summary_text(summary))
        else:
            for r in result.records:
                click.echo(
                    f"{r.occurred_at.isoformat()} {r.kind} ({r.source}) {r.record_id}\n"
                    f"  {r.note or r.reason or ''}"
                )
        if result.warnings:
            click.echo(
                json.dumps(
                    {
                        "error": {
                            "code": "evidence_partial",
                            "message": "; ".join(result.warnings),
                        }
                    }
                )
                if as_json or output == "json"
                else "\n".join(result.warnings),
                err=True,
            )
            raise click.exceptions.Exit(1)

    for name in ("list", "view"):

        def callback(tool: str, session_id: str, output: str, as_json: bool) -> None:
            ctx = click.get_current_context()
            read(tool, session_id, output, as_json, view=ctx.command.name == "view")

        group.add_command(
            click.Command(
                name,
                callback=callback,
                params=[
                    click.Option(["--tool"], required=True, help="exact runtime name"),
                    click.Option(
                        ["--session", "session_id"],
                        required=True,
                        help="full session ID",
                    ),
                    click.Option(
                        ["-o", "--output"],
                        type=click.Choice(["text", "json"]),
                        default="text",
                    ),
                    click.Option(
                        ["--json", "as_json"],
                        is_flag=True,
                        help="same as --output json",
                    ),
                ],
                help="Show recorded history."
                if name == "list"
                else "Join native session facts with optional evidence.",
            )
        )

    @group.command(name="hook")
    @click.option(
        "--tool", required=True, type=click.Choice(["agy", "claude", "codex"])
    )
    def hook(tool: HookTool) -> None:
        """Consume an opt-in SessionStart/SessionEnd notification on stdin.

        Unknown events are ignored. Recording failures warn on stderr and exit 0.
        Antigravity hooks expect JSON on stdout, so `--tool agy` writes `{}` on
        stdout even when ignoring events or failing open.
        This command never installs hooks or changes runtime configuration.
        """
        try:
            event = normalize_hook(tool, _read_document("-"))
            if event:
                Store(timeout=0.25).append(event)
        except (OSError, sqlite3.Error, ValueError) as exc:
            # Do not dump the runtime payload or Pydantic input in a hook warning.
            message = (
                "invalid hook payload" if isinstance(exc, ValidationError) else str(exc)
            )
            click.echo(f"lost-sessions: evidence not recorded: {message}", err=True)
        if tool == "agy":
            click.echo("{}")

    return group
