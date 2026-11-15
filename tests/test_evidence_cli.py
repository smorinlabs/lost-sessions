"""Commands are opt-in, bounded, and safe to call from optional runtime hooks."""

import json
import os
import sqlite3

import pytest
from click.testing import CliRunner

from lost_sessions.cli import build_cli
from lost_sessions.evidence import Store
from lost_sessions.models import Census, Inventory, Session, SourceStatus


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return (
        CliRunner(),
        build_cli(),
        tmp_path / "state" / "lost-sessions" / "evidence.sqlite3",
    )


def document(**fields):
    return json.dumps(
        {
            "tool": "other",
            "session_id": "full-id",
            "kind": "opened",
            "source": "user",
            **fields,
        }
    )


def test_validate_write_read_and_summary(isolated):
    runner, cli, path = isolated
    checked = runner.invoke(
        cli, ["evidence", "record", "--dry-run", "--json"], input=document()
    )
    assert checked.exit_code == 0, checked.output
    assert not path.exists()
    # Reuse the validated UUID and event time to make retries idempotent.
    stored = runner.invoke(
        cli, ["evidence", "record", "--file", "-", "--json"], input=checked.stdout
    )
    assert stored.exit_code == 0, stored.output
    retry = runner.invoke(cli, ["evidence", "record", "--json"], input=checked.stdout)
    assert retry.stdout == stored.stdout
    listed = runner.invoke(
        cli, ["evidence", "list", "--tool", "other", "--session", "full-id", "--json"]
    )
    assert len(json.loads(listed.stdout)["records"]) == 1
    viewed = runner.invoke(
        cli, ["evidence", "view", "--tool", "other", "--session", "full-id", "--json"]
    )
    assert json.loads(viewed.stdout)["evidence"]["coverage"] == "partial"
    assert json.loads(viewed.stdout)["session"] is None
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "args, payload",
    [
        (["record", "--json"], ""),
        (["record", "--json"], "{"),
        (["record", "--json"], document(kind="assessment", work_state="complete")),
        (["record", "--json"], document() + " " * 1048576),
        (["list", "--json"], ""),
    ],
)
def test_bad_input_is_a_structured_error_without_writes(isolated, args, payload):
    runner, cli, path = isolated
    result = runner.invoke(cli, ["evidence", *args], input=payload)
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "invalid_input"
    assert not path.exists()


def test_empty_history_and_missing_session_have_distinct_exit_codes(isolated):
    runner, cli, path = isolated
    for command, code in (("list", 0), ("view", 3)):
        result = runner.invoke(
            cli,
            ["evidence", command, "--tool", "other", "--session", "missing", "--json"],
        )
        assert result.exit_code == code, result.output
    assert not path.exists()


def test_hook_ignores_turn_end_and_handles_invalid_input(isolated):
    runner, cli, path = isolated
    args = ["evidence", "hook", "--tool", "codex"]
    result = runner.invoke(
        cli, args, input=json.dumps({"session_id": "id", "hook_event_name": "Stop"})
    )
    assert result.exit_code == 0
    assert not path.exists()
    result = runner.invoke(cli, args, input="bad json")
    assert result.exit_code == 0
    assert result.stdout == ""
    assert "not recorded" in result.stderr
    result = runner.invoke(
        cli,
        args,
        input=json.dumps(
            {"session_id": "id", "hook_event_name": "SessionEnd", "reason": "other"}
        ),
    )
    assert result.exit_code == 0
    assert Store(path).read().records[0].kind == "ended"


def test_hook_database_failure_does_not_interrupt_runtime(isolated):
    runner, cli, path = isolated
    path.parent.mkdir(parents=True)
    path.write_text("broken database")
    result = runner.invoke(
        cli,
        ["evidence", "hook", "--tool", "claude"],
        input=json.dumps(
            {"session_id": "id", "hook_event_name": "SessionStart", "source": "resume"}
        ),
    )
    assert result.exit_code == 0
    assert "not recorded" in result.stderr
    assert path.read_text() == "broken database"


@pytest.mark.parametrize("broken_identity", [None, "not-a-uuid", "duplicate"])
def test_invalid_store_identity_refuses_writes_and_hooks_fail_open(
    isolated, broken_identity
):
    runner, cli, path = isolated
    assert (
        runner.invoke(cli, ["evidence", "record", "--json"], input=document()).exit_code
        == 0
    )
    with sqlite3.connect(path) as conn:
        if broken_identity is None:
            conn.execute("DELETE FROM meta")
        elif broken_identity == "duplicate":
            conn.execute("INSERT INTO meta SELECT machine_id FROM meta")
        else:
            conn.execute("UPDATE meta SET machine_id=?", (broken_identity,))
    result = runner.invoke(cli, ["evidence", "record", "--json"], input=document())
    assert result.exit_code == 1
    assert "invalid evidence store identity" in result.stderr
    hook = runner.invoke(
        cli,
        ["evidence", "hook", "--tool", "claude"],
        input=json.dumps({"session_id": "id", "hook_event_name": "SessionEnd"}),
    )
    assert hook.exit_code == 0
    assert "not recorded" in hook.stderr
    assert Store(path).read().warnings
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_inventory_enrichment_preserves_selection_and_native_fields(
    isolated, monkeypatch
):
    runner, cli, path = isolated
    from lost_sessions import inventory

    session = Session(
        tool="codex",
        id="id",
        created="2026-11-10T09:00:00Z",
        updated="2026-11-14T09:00:00Z",
        live="yes",
    )
    inv = Inventory(
        sessions=[session],
        census={"codex": Census(listed=1, hidden_subagents=0, unreadable=0, live=1)},
        sources={"codex": SourceStatus(status="ok")},
        failed=[],
    )
    monkeypatch.setattr(inventory, "collect", lambda *a, **kw: inv)
    base = runner.invoke(cli, ["inventory", "--json"])
    enriched = runner.invoke(cli, ["inventory", "--evidence", "--json"])
    assert enriched.exit_code == 0, enriched.output
    doc = json.loads(enriched.stdout)
    assert doc["sessions"][0].pop("evidence")["coverage"] == "not-recorded"
    assert doc.pop("evidence_warnings") == []
    assert doc == json.loads(base.stdout)
    assert not path.exists()
    # An unreadable optional store cannot erase native discovery or its liveness.
    path.parent.mkdir(parents=True)
    path.write_text("broken")
    enriched = runner.invoke(cli, ["inventory", "--evidence", "--json"])
    assert enriched.exit_code == 0
    doc = json.loads(enriched.stdout)
    assert doc["evidence_warnings"]
    assert doc["sessions"][0]["live"] == "yes"
    assert runner.invoke(cli, ["inventory", "--json"]).stdout == base.stdout


def test_future_database_remains_untouched(isolated):
    runner, cli, path = isolated
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    result = runner.invoke(cli, ["evidence", "record", "--json"], input=document())
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"]["code"] == "evidence_error"
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 99


def test_dry_run_enforces_stored_record_size_limit(isolated):
    runner, cli, path = isolated
    payload = document(references=["a" * 8192] * 9)
    result = runner.invoke(
        cli, ["evidence", "record", "--dry-run", "--json"], input=payload
    )
    assert result.exit_code == 2
    assert "64 KiB" in result.stderr
    assert not path.exists()
