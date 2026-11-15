"""Optional local evidence: append records, derive summaries, never infer liveness."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from lost_sessions.history import state_dir

Text = Annotated[str, Field(min_length=1, max_length=8192)]
Kind = Literal[
    "opened", "ended", "close-intent", "assessment", "turn", "context-refreshed"
]
Source = Literal["user", "agent", "hook", "import"]
WorkState = Literal[
    "incomplete", "probably-complete", "complete", "paused", "blocked", "handed-off"
]
Activity = Literal["work", "orientation", "administrative", "unknown"]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Event(BaseModel):
    """One occurrence or judgment. Input is validated before it reaches storage."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    schema_version: Literal[1] = 1
    record_id: UUID = Field(default_factory=uuid4)
    tool: Text
    session_id: Text
    kind: Kind
    source: Source
    occurred_at: AwareDatetime = Field(default_factory=utc_now)
    run_id: Text | None = None
    native_event: Text | None = None
    reason: Text | None = None
    note: Text | None = None
    scope: Text | None = None
    work_state: WorkState | None = None
    remaining: list[Text] = Field(default_factory=list, max_length=100)
    references: list[Text] = Field(default_factory=list, max_length=100)
    through_turn: Text | None = None
    turn_id: Text | None = None
    activity: Activity | None = None
    supersedes: UUID | None = None

    @model_validator(mode="after")
    def check_meanings(self) -> Self:
        if self.kind == "assessment":
            if not all((self.note, self.scope, self.work_state, self.through_turn)):
                raise ValueError(
                    "assessments require note, scope, work_state and through_turn"
                )
        elif (
            self.work_state is not None
            or self.scope
            or self.through_turn
            or self.remaining
        ):
            raise ValueError("work assessment fields belong only on assessment records")
        if self.kind == "turn":
            if not all((self.note, self.turn_id, self.activity)):
                raise ValueError("turn records require note, turn_id and activity")
        elif self.turn_id or self.activity:
            raise ValueError("turn_id and activity belong only on turn records")
        if self.kind == "close-intent" and not self.note:
            raise ValueError("close-intent requires a note")
        if self.source == "hook" and self.kind in (
            "assessment",
            "close-intent",
            "turn",
        ):
            raise ValueError("a runtime hook cannot make a semantic assessment")
        if self.supersedes == self.record_id:
            raise ValueError("a record cannot supersede itself")
        return self


class Record(Event):
    """The event plus locally assigned receipt time and machine identity."""

    recorded_at: AwareDatetime
    machine_id: str


class EvidenceRead(BaseModel):
    records: list[Record] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_event(payload: object) -> Event:
    """Apply the same shape and size checks to previews and stored writes."""
    event = Event.model_validate(payload)
    if len(event.model_dump_json().encode()) > 65536:
        raise ValueError("evidence record exceeds 64 KiB")
    return event


class Store:
    """SQLite serializes concurrent appenders; reads never initialize a store."""

    def __init__(self, path: Path | None = None, *, timeout: float = 5.0) -> None:
        self.path = path if path is not None else state_dir() / "evidence.sqlite3"
        self.timeout = timeout

    @staticmethod
    def _version(conn: sqlite3.Connection) -> int:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _machine_id(conn: sqlite3.Connection) -> str:
        identity = conn.execute("SELECT machine_id FROM meta").fetchall()
        if len(identity) != 1 or not isinstance(identity[0][0], str):
            raise ValueError("invalid evidence store identity")
        machine_id = identity[0][0]
        try:
            UUID(machine_id)
        except ValueError as exc:
            raise ValueError("invalid evidence store identity") from exc
        return machine_id

    def append(self, event: Event) -> Record:
        # Revalidate library callers too, including model_copy/model_construct.
        event = validate_event(event.model_dump())
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.path, timeout=self.timeout)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            version = self._version(conn)
            if version == 0:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if tables:
                    raise ValueError("unrecognized evidence database")
                conn.execute("CREATE TABLE meta (machine_id TEXT NOT NULL)")
                conn.execute("INSERT INTO meta VALUES (?)", (str(uuid4()),))
                conn.execute(
                    "CREATE TABLE records (sequence INTEGER PRIMARY KEY, "
                    "record_id TEXT UNIQUE NOT NULL, tool TEXT NOT NULL, "
                    "session_id TEXT NOT NULL, payload TEXT NOT NULL)"
                )
                conn.execute(
                    "CREATE INDEX session_records ON records(tool, session_id)"
                )
                conn.execute("PRAGMA user_version=1")
            elif version != 1:
                raise ValueError(f"unsupported evidence database version {version}")
            machine_id = self._machine_id(conn)
            prior = conn.execute(
                "SELECT payload FROM records WHERE record_id=?", (str(event.record_id),)
            ).fetchone()
            if prior:
                record = Record.model_validate_json(prior[0])
                if (
                    Event.model_validate(
                        record.model_dump(exclude={"recorded_at", "machine_id"})
                    )
                    != event
                ):
                    raise ValueError("record_id already exists with different content")
                return record
            if event.supersedes:
                old = conn.execute(
                    "SELECT payload FROM records WHERE record_id=?",
                    (str(event.supersedes),),
                ).fetchone()
                if old is None:
                    raise ValueError("superseded record does not exist")
                target = Record.model_validate_json(old[0])
                if (target.tool, target.session_id, target.kind) != (
                    event.tool,
                    event.session_id,
                    event.kind,
                ):
                    raise ValueError(
                        "corrections must refer to the same session and kind"
                    )
                if event.kind == "turn" and event.turn_id != target.turn_id:
                    raise ValueError("turn corrections must refer to the same turn_id")
            record = Record(
                **event.model_dump(), recorded_at=utc_now(), machine_id=machine_id
            )
            conn.execute(
                "INSERT INTO records(record_id,tool,session_id,payload) VALUES (?,?,?,?)",
                (
                    str(record.record_id),
                    record.tool,
                    record.session_id,
                    record.model_dump_json(),
                ),
            )
            return record

    def read(
        self, tool: str | None = None, session_id: str | None = None
    ) -> EvidenceRead:
        result = EvidenceRead()
        try:
            # stat distinguishes an absent store from permission errors.
            self.path.stat()
        except FileNotFoundError:
            return result
        except OSError as exc:
            result.warnings.append(f"cannot read evidence: {exc}")
            return result
        try:
            with closing(
                sqlite3.connect(
                    self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25
                )
            ) as conn:
                if self._version(conn) != 1:
                    result.warnings.append(
                        "unsupported evidence database version; upgrade lost-sessions"
                    )
                    return result
                machine_id = self._machine_id(conn)
                rows = conn.execute(
                    "SELECT sequence, record_id, tool, session_id, payload FROM records WHERE (? IS NULL OR tool=?) "
                    "AND (? IS NULL OR session_id=?) ORDER BY sequence",
                    (tool, tool, session_id, session_id),
                )
                for sequence, record_id, runtime, sid, payload in rows:
                    try:
                        record = Record.model_validate_json(payload)
                        if (
                            str(record.record_id),
                            record.tool,
                            record.session_id,
                            record.machine_id,
                        ) != (record_id, runtime, sid, machine_id):
                            raise ValueError("stored record identity mismatch")
                        result.records.append(record)
                    except (ValidationError, ValueError):
                        result.warnings.append(
                            f"unreadable or unsupported evidence record {sequence}"
                        )
        except (OSError, sqlite3.Error, ValueError) as exc:
            result.warnings.append(f"cannot read evidence: {exc}")
        return result


class Summary(BaseModel):
    """Advisory evidence only. Native creation time and liveness stay separate."""

    record_count: int = 0
    first_observed_at: dt.datetime | None = None
    last_opened_at: dt.datetime | None = None
    last_ended_at: dt.datetime | None = None
    last_interaction_at: dt.datetime | None = None
    last_work_at: dt.datetime | None = None
    closure: Literal[
        "no-end-recorded",
        "reopened-after-end",
        "end-observed",
        "end-observed-unmatched",
        "ambiguous",
    ] = "no-end-recorded"
    assessment: Record | None = None
    close_intent: Record | None = None
    assessment_currency: Literal[
        "not-assessed",
        "as-recorded",
        "work-since-assessment",
        "unclassified-activity-since-assessment",
    ] = "not-assessed"
    coverage: Literal["not-recorded", "partial"] = "not-recorded"


def summarize(records: list[Record]) -> Summary:
    """Reduce one session's history without discarding superseded evidence."""
    if not records:
        return Summary()
    if len({(r.machine_id, r.tool, r.session_id) for r in records}) != 1:
        raise ValueError("summarize requires records for one machine and session")
    superseded = {r.supersedes for r in records if r.supersedes}
    active = sorted(
        (r for r in records if r.record_id not in superseded),
        key=lambda r: (r.occurred_at, r.recorded_at, str(r.record_id)),
    )
    opened = [r for r in active if r.kind == "opened"]
    ended = [r for r in active if r.kind == "ended"]
    turns = [r for r in active if r.kind == "turn"]
    work = [r for r in turns if r.activity == "work"]
    assessments = [r for r in active if r.kind == "assessment"]
    intents = [r for r in active if r.kind == "close-intent"]
    summary = Summary(
        record_count=len(records),
        first_observed_at=min(r.recorded_at for r in records),
        last_opened_at=opened[-1].occurred_at if opened else None,
        last_ended_at=ended[-1].occurred_at if ended else None,
        last_interaction_at=turns[-1].occurred_at if turns else None,
        last_work_at=work[-1].occurred_at if work else None,
        assessment=assessments[-1] if assessments else None,
        close_intent=intents[-1] if intents else None,
        coverage="partial",
    )
    if ended:
        last_end = ended[-1]
        if opened and opened[-1].occurred_at > last_end.occurred_at:
            summary.closure = "reopened-after-end"
        elif opened and any(
            r.occurred_at == last_end.occurred_at
            or (
                r.run_id
                and not any(
                    e.run_id == r.run_id and e.occurred_at > r.occurred_at
                    for e in ended
                )
            )
            for r in opened
        ):
            summary.closure = "ambiguous"
        elif opened and all(r.run_id for r in opened) and last_end.run_id:
            summary.closure = "end-observed"
        else:
            summary.closure = "end-observed-unmatched"
    if summary.assessment:
        assessment = summary.assessment
        summary.assessment_currency = "as-recorded"
        covered = next(
            (r for r in reversed(turns) if r.turn_id == assessment.through_turn), None
        )
        boundary = covered.occurred_at if covered else assessment.occurred_at
        later = [r for r in turns if r.occurred_at > boundary]
        if any(r.activity == "work" for r in later):
            summary.assessment_currency = "work-since-assessment"
        elif any(r.activity == "unknown" for r in later):
            summary.assessment_currency = "unclassified-activity-since-assessment"
    return summary
