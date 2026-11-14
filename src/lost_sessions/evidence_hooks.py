"""Normalize supported runtime notifications without guessing their meaning."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lost_sessions.evidence import Event


class HookInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    session_id: str = Field(min_length=1)
    hook_event_name: str
    source: str | None = None
    reason: str | None = None


def normalize_hook(tool: Literal["claude", "codex"], payload: object) -> Event | None:
    value = HookInput.model_validate(payload)
    if value.hook_event_name == "SessionStart":
        return Event(
            tool=tool,
            session_id=value.session_id,
            source="hook",
            kind="context-refreshed" if value.source == "compact" else "opened",
            native_event=value.hook_event_name,
            reason=value.source,
        )
    if value.hook_event_name == "SessionEnd":
        return Event(
            tool=tool,
            session_id=value.session_id,
            source="hook",
            kind="ended",
            native_event=value.hook_event_name,
            reason=value.reason,
        )
    return None
