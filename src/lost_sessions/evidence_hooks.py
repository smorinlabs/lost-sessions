"""Normalize supported runtime notifications without guessing their meaning."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lost_sessions.evidence import Event

HookTool = Literal["agy", "claude", "codex"]

# Antigravity emits camelCase payloads for non-SessionStart hooks (`Stop`,
# `PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`). `Stop` fires
# after every turn rather than at session close, so it must NEVER map to `ended`.
_AGY_IGNORED_SIGNAL_KEYS = frozenset(
    {
        "terminationReason",
        "executionNum",
        "fullyIdle",
        "toolCall",
        "invocationNum",
    }
)


class HookInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    session_id: str = Field(min_length=1)
    hook_event_name: str
    source: str | None = None
    reason: str | None = None


class AgyHookInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    conversation_id: str = Field(alias="conversationId", min_length=1)
    hook_event_name: str = Field(alias="hookEventName")
    cwd: str | None = None
    workspace_paths: list[str] | None = Field(default=None, alias="workspacePaths")
    transcript_path: str | None = Field(default=None, alias="transcriptPath")
    source: str | None = None
    reason: str | None = None


def _normalize_agy_hook(payload: object) -> Event | None:
    if isinstance(payload, dict):
        event_name = payload.get("hookEventName")
        if isinstance(event_name, str) and event_name.strip() != "SessionStart":
            # Explicitly ignore `Stop` (fires after every turn, not session close)
            # and all other non-SessionStart Antigravity hook events.
            return None
        if event_name is None and _AGY_IGNORED_SIGNAL_KEYS.intersection(payload):
            return None
    value = AgyHookInput.model_validate(payload)
    if value.hook_event_name == "SessionStart":
        source = value.source or None
        reason = source or value.reason or None
        return Event(
            tool="agy",
            session_id=value.conversation_id,
            source="hook",
            kind="context-refreshed" if source == "compact" else "opened",
            native_event="SessionStart",
            reason=reason,
        )
    return None


def normalize_hook(tool: HookTool, payload: object) -> Event | None:
    if tool == "agy":
        return _normalize_agy_hook(payload)
    if (
        isinstance(payload, dict)
        and isinstance(name := payload.get("hook_event_name"), str)
        and name.strip() not in {"SessionStart", "SessionEnd"}
    ):
        return None
    value = HookInput.model_validate(payload)
    if value.hook_event_name == "SessionStart":
        source = value.source or None
        return Event(
            tool=tool,
            session_id=value.session_id,
            source="hook",
            kind="context-refreshed" if source == "compact" else "opened",
            native_event=value.hook_event_name,
            reason=source,
        )
    if value.hook_event_name == "SessionEnd":
        reason = value.reason or None
        return Event(
            tool=tool,
            session_id=value.session_id,
            source="hook",
            kind="ended",
            native_event=value.hook_event_name,
            reason=reason,
        )
    return None
