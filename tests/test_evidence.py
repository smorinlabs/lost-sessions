"""Optional evidence must never become an invented session state."""

import concurrent.futures
import datetime as dt
import sqlite3
import threading
import time

import pytest
from pydantic import ValidationError

from lost_sessions.evidence import Event, Store, summarize
from lost_sessions.evidence_hooks import normalize_hook


def event(kind="opened", hour=9, **fields):
    return Event(
        tool="codex",
        session_id="full-session-id",
        kind=kind,
        source="agent",
        occurred_at=f"2026-11-14T{hour:02}:00:00Z",
        **fields,
    )


def test_reading_absent_store_creates_nothing(tmp_path):
    path = tmp_path / "absent" / "evidence.sqlite3"
    assert Store(path).read().records == []
    assert not path.parent.exists()


def test_reading_uninitialized_store_preserves_empty_file(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    path.touch()
    result = Store(path).read()
    assert result.records == []
    assert result.warnings == []
    assert path.read_bytes() == b""


def test_version_zero_with_tables_is_not_an_empty_store(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")
    result = Store(path).read()
    assert result.records == []
    assert result.warnings


def test_ignored_hook_does_not_require_session_identity():
    assert normalize_hook("codex", {"hook_event_name": "Stop"}) is None


def test_reopen_and_recap_preserve_completion_and_original_history(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(event(run_id="run-1"))
    store.append(
        event("turn", 10, turn_id="work", activity="work", note="Verified fix")
    )
    store.append(
        event(
            "assessment",
            11,
            work_state="probably-complete",
            scope="Fix login",
            through_turn="work",
            note="Main work verified",
            remaining=["Release"],
        )
    )
    store.append(event("ended", 12, run_id="run-1", reason="other"))
    store.append(event("opened", 13, run_id="run-2", reason="resume"))
    store.append(
        event("turn", 14, turn_id="recap", activity="orientation", note="Recap only")
    )
    records = store.read().records
    summary = summarize(records)
    assert len(records) == 6
    assert summary.closure == "reopened-after-end"
    assert summary.last_work_at.hour == 10
    assert summary.last_interaction_at.hour == 14
    assert summary.assessment.work_state == "probably-complete"
    assert summary.assessment_currency == "as-recorded"
    store.append(
        event("turn", 15, turn_id="fix2", activity="work", note="New requirement")
    )
    assert (
        summarize(store.read().records).assessment_currency == "work-since-assessment"
    )


def test_record_retry_is_idempotent_but_changed_content_is_rejected(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    original = event()
    assert store.append(original) == store.append(original)
    with pytest.raises(ValueError, match="different content"):
        store.append(original.model_copy(update={"reason": "changed"}))
    assert len(store.read().records) == 1


def test_delayed_old_end_does_not_close_new_opening(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(event(run_id="old"))
    store.append(event("opened", 10, run_id="new"))
    store.append(event("ended", 11, run_id="old"))
    assert summarize(store.read().records).closure == "ambiguous"
    store.append(event("ended", 12, run_id="new"))
    assert summarize(store.read().records).closure == "end-observed"


def test_missing_run_identity_does_not_claim_correlated_close(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(event())
    store.append(event("ended", 10))
    assert summarize(store.read().records).closure == "end-observed-unmatched"


def test_latest_end_without_its_own_opening_is_unmatched(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(event(run_id="a"))
    store.append(event("ended", 10, run_id="a"))
    store.append(event("ended", 11, run_id="b"))
    assert summarize(store.read().records).closure == "end-observed-unmatched"


def test_assessment_currency_uses_covered_turn_when_available(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(
        event("turn", 9, turn_id="covered", activity="work", note="Initial task")
    )
    store.append(
        event("turn", 10, turn_id="later", activity="unknown", note="Not classified")
    )
    store.append(
        event(
            "assessment",
            11,
            scope="Initial task",
            through_turn="covered",
            work_state="complete",
            note="Retrospective assessment",
        )
    )
    assert (
        summarize(store.read().records).assessment_currency
        == "unclassified-activity-since-assessment"
    )


def test_correction_can_fix_an_incorrectly_late_event_time(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    prior = store.append(
        event("turn", 12, turn_id="work", activity="work", note="Wrong time")
    )
    store.append(
        event(
            "turn",
            9,
            turn_id="work",
            activity="work",
            note="Corrected time",
            supersedes=prior.record_id,
        )
    )
    assert summarize(store.read().records).last_work_at.hour == 9


def test_persisted_identity_mismatch_is_a_partial_read(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    store = Store(path)
    store.append(event())
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE records SET session_id='different'")
    result = store.read()
    assert result.records == []
    assert len(result.warnings) == 1


def test_explicit_close_intent_is_not_a_runtime_end(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(event("close-intent", 10, note="Done for today"))
    summary = summarize(store.read().records)
    assert summary.close_intent.note == "Done for today"
    assert summary.closure == "no-end-recorded"
    assert summary.assessment is None


def test_clock_offsets_and_receipt_order_do_not_change_event_order(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    store.append(event("ended", 11, run_id="a"))
    opened = event(run_id="a").model_copy(
        update={"occurred_at": dt.datetime.fromisoformat("2026-11-14T01:00:00-08:00")}
    )
    store.append(opened)
    assert summarize(store.read().records).closure == "end-observed"


def test_correction_preserves_history_and_checks_session_identity(tmp_path):
    store = Store(tmp_path / "evidence.sqlite3")
    prior = store.append(
        event("turn", 10, turn_id="t1", activity="work", note="Initial")
    )
    store.append(
        event(
            "turn",
            11,
            turn_id="t1",
            activity="orientation",
            note="Actually recap",
            supersedes=prior.record_id,
        )
    )
    summary = summarize(store.read().records)
    assert summary.record_count == 2
    assert summary.last_work_at is None
    with pytest.raises(ValueError, match="same session and kind"):
        store.append(event("opened", 12, supersedes=prior.record_id))


def test_concurrent_writes_survive_and_share_machine_identity(tmp_path):
    path = tmp_path / "evidence.sqlite3"

    def write(index):
        return Store(path).append(event(note=f"writer {index}"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(write, range(24)))
    assert len(Store(path).read().records) == 24
    assert len({r.machine_id for r in records}) == 1


def test_append_waits_for_brief_writer_contention(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    store = Store(path)
    store.append(event())
    started = threading.Event()

    def write():
        started.set()
        return store.append(event(note="after competing writer"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with sqlite3.connect(path) as competing:
            competing.execute("BEGIN IMMEDIATE")
            pending = pool.submit(write)
            assert started.wait(timeout=2)
            time.sleep(0.4)
            competing.rollback()
        pending.result(timeout=6)
    assert len(store.read().records) == 2


def test_short_write_budget_reports_a_busy_database(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    Store(path).append(event())
    with sqlite3.connect(path) as competing:
        competing.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            Store(path, timeout=0.01).append(event())
    assert len(Store(path).read().records) == 1


def test_unreadable_record_is_reported_without_discarding_good_evidence(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    store = Store(path)
    store.append(event())
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO records (record_id, tool, session_id, payload) VALUES (?, ?, ?, ?)",
            ("broken", "codex", "full-session-id", "not json"),
        )
    read = store.read()
    assert len(read.records) == 1
    assert read.warnings


@pytest.mark.parametrize(
    "fields",
    [
        {"occurred_at": "2026-11-14T09:00:00"},
        {"kind": "assessment", "work_state": "complete"},
        {"kind": "turn", "turn_id": "t", "activity": "work"},
        {"kind": "ended", "work_state": "complete"},
        {"session_id": " "},
    ],
)
def test_invalid_or_misleading_fields_are_rejected(fields):
    with pytest.raises(ValidationError):
        Event.model_validate(
            {
                "tool": "codex",
                "session_id": "full-session-id",
                "kind": "opened",
                "source": "agent",
                **fields,
            }
        )


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_hooks_preserve_raw_meaning(tool):
    payload = {
        "session_id": "full-id",
        "hook_event_name": "SessionStart",
        "source": "compact",
    }
    assert normalize_hook(tool, payload).kind == "context-refreshed"
    payload.update(hook_event_name="SessionEnd", reason="other")
    record = normalize_hook(tool, payload)
    assert record.kind == "ended"
    assert record.reason == "other"
    assert record.work_state is None
    payload["hook_event_name"] = "Stop"
    assert normalize_hook(tool, payload) is None
