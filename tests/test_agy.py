"""Antigravity (`agy`) agent plugin, evidence hook adapter, and plugin manifest tests."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from lost_sessions import core
from lost_sessions.agents import ScanContext, SourceError
from lost_sessions.cli import build_cli
from lost_sessions.default_plugins import agy as agy_module
from lost_sessions.default_plugins.agy import Antigravity
from lost_sessions.evidence import Store
from lost_sessions.evidence_hooks import normalize_hook
from lost_sessions.models import Lineage, Session

ROOT = Path(__file__).resolve().parents[1]

AGY_SCHEMA = """CREATE TABLE conversation_summaries (
  conversation_id text PRIMARY KEY,
  title text NOT NULL DEFAULT "",
  preview text NOT NULL DEFAULT "",
  step_count integer NOT NULL DEFAULT 0,
  last_modified_time datetime NOT NULL,
  workspace_uris text NOT NULL,
  status text NOT NULL DEFAULT "",
  source text NOT NULL DEFAULT "",
  project_id text NOT NULL DEFAULT "",
  agent_name text NOT NULL DEFAULT "",
  parent_conversation_id text NOT NULL DEFAULT "",
  nesting_depth integer NOT NULL DEFAULT 0,
  battle_id text NOT NULL DEFAULT "",
  winning_conversation_id text NOT NULL DEFAULT "",
  not_fully_idle numeric NOT NULL DEFAULT false,
  killed numeric NOT NULL DEFAULT false,
  last_user_input_time datetime NOT NULL DEFAULT "",
  last_user_input_step_index integer NOT NULL DEFAULT -1,
  app_data_dir text NOT NULL DEFAULT "",
  raw_summary blob,
  group_id text NOT NULL DEFAULT ""
)"""


def _app_data(home: Path) -> Path:
    return home / ".gemini" / "antigravity-cli"


def _create_db(home: Path, rows: list[tuple], schema: str = AGY_SCHEMA) -> Path:
    app_data = _app_data(home)
    app_data.mkdir(parents=True, exist_ok=True)
    db_path = app_data / "conversation_summaries.db"
    db = sqlite3.connect(db_path)
    db.execute(schema)
    if rows:
        placeholders = ",".join("?" for _ in rows[0])
        db.executemany(
            f"INSERT INTO conversation_summaries VALUES ({placeholders})",  # noqa: S608
            rows,
        )
    db.commit()
    db.close()
    return db_path


def _full_row(
    sid: str,
    *,
    title: object = "Fix parser",
    preview: object = "preview text",
    last_modified_time: object = "2026-11-25T03:15:00Z",
    workspace_uris: object = '["file:///work/alpha"]',
    parent_conversation_id: object = "",
    nesting_depth: object = 0,
) -> tuple[object, ...]:
    return (
        sid,
        title,
        preview,
        3,
        last_modified_time,
        workspace_uris,
        "",
        "",
        "default-cli-project",
        "",
        parent_conversation_id,
        nesting_depth,
        "",
        "",
        0,
        0,
        "",
        -1,
        "",
        None,
        "",
    )


def _write_transcript(
    home: Path,
    sid: str,
    lines: list[str] | list[dict],
    *,
    mtime: float | None = None,
) -> Path:
    path = (
        _app_data(home)
        / "brain"
        / sid
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = [line if isinstance(line, str) else json.dumps(line) for line in lines]
    path.write_text("".join(f"{line}\n" for line in rendered), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _by_id(result) -> dict[str, Session]:
    return {s.id: s for s in result.sessions}


# --- store handling & schema defense ------------------------------------------


def test_absent_db_returns_absent_without_creating_anything(tmp_path):
    result = Antigravity().scan(ScanContext(home=tmp_path))
    assert result.sessions == []
    assert result.source.status == "absent"
    assert result.source.path == str(_app_data(tmp_path) / "conversation_summaries.db")
    assert not (tmp_path / ".gemini").exists()


def test_corrupt_db_raises_source_error(tmp_path):
    db_path = _app_data(tmp_path) / "conversation_summaries.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("not a sqlite database")
    with pytest.raises(SourceError, match="agy:"):
        Antigravity().scan(ScanContext(home=tmp_path))


def test_missing_table_or_conversation_id_raises_source_error(tmp_path):
    db_path = _app_data(tmp_path) / "conversation_summaries.db"
    db_path.parent.mkdir(parents=True)
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE other (id TEXT)")
    db.commit()
    db.close()
    with pytest.raises(SourceError, match="missing conversation_summaries"):
        Antigravity().scan(ScanContext(home=tmp_path))

    db_path.unlink()
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE conversation_summaries (title TEXT)")
    db.commit()
    db.close()
    with pytest.raises(SourceError, match="missing conversation_id"):
        Antigravity().scan(ScanContext(home=tmp_path))


def test_optional_columns_missing_still_scans_defensively(tmp_path):
    sid = "11111111-1111-4111-8111-111111111111"
    _create_db(
        tmp_path,
        [(sid,)],
        schema="CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY)",
    )
    tpath = _write_transcript(
        tmp_path,
        sid,
        [{"step_index": 0, "created_at": "2026-11-24T10:00:00Z"}],
        mtime=1764000000.0,
    )
    res = Antigravity().scan(ScanContext(home=tmp_path))
    assert res.source.status == "ok"
    s = _by_id(res)[sid]
    assert s.title is None
    assert s.name is None
    assert s.spawn_dir is None
    assert s.resume is None
    assert s.resume_blocked == "no_workspace"
    assert s.created == "2026-11-24T10:00:00Z"
    assert s.updated == "2025-11-24T16:00:00Z"
    assert s.transcript == str(tpath)
    assert s.hidden is False


def test_scan_never_modifies_db_bytes(tmp_path):
    sid = "11111111-1111-4111-8111-111111111111"
    db_path = _create_db(tmp_path, [_full_row(sid)])
    before = db_path.read_bytes()
    Antigravity().scan(ScanContext(home=tmp_path))
    assert db_path.read_bytes() == before


# --- workspace_uris extraction ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('["file:///work/my%20repo", "file:///work/second"]', "/work/my repo"),
        (
            '["ssh://remote/repo", "file://otherhost/share", "file:///work/local"]',
            "/work/local",
        ),
        ('"file:///work/json-str/"', "/work/json-str"),
        ("file:///work/line1\nfile:///work/line2", "/work/line1"),
        ("file:///work/c1, file:///work/c2", "/work/c1"),
        ("file://localhost/work/local/", "/work/local"),
        ("/work/bare/path/", "/work/bare/path"),
        ("/work/dir,with,commas", "/work/dir,with,commas"),
        ("/", "/"),
        ("", None),
        ("   ", None),
        ("[]", None),
        ("relative/path", None),
        ("ssh://remote/only", None),
    ],
)
def test_workspace_uris_variants(tmp_path, raw, expected):
    sid = "22222222-2222-4222-8222-222222222222"
    _create_db(tmp_path, [_full_row(sid, workspace_uris=raw)])
    s = _by_id(Antigravity().scan(ScanContext(home=tmp_path)))[sid]
    assert s.spawn_dir == expected
    if expected is None:
        assert s.resume is None and s.resume_blocked == "no_workspace"
    else:
        assert s.resume_blocked is None
        assert s.resume is not None and f"agy --conversation {sid}" in s.resume


def test_resume_command_quotes_spaces_and_matches_contract(tmp_path):
    sid = "22222222-2222-4222-8222-222222222222"
    _create_db(tmp_path, [_full_row(sid, workspace_uris='["file:///work/my%20repo"]')])
    plugin = Antigravity()
    s = _by_id(plugin.scan(ScanContext(home=tmp_path)))[sid]
    assert plugin.resume_in_dir is True
    assert plugin.resume_args(s) == ["agy", "--conversation", sid]
    assert s.resume == f"cd '/work/my repo' && agy --conversation {sid}"


def test_resume_command_quotes_shell_metacharacters_in_conversation_id(tmp_path):
    crafted = "target; touch /tmp/x"
    _create_db(tmp_path, [_full_row(crafted, workspace_uris='["file:///work/alpha"]')])
    s = _by_id(Antigravity().scan(ScanContext(home=tmp_path)))[crafted]
    assert s.resume == "cd /work/alpha && agy --conversation 'target; touch /tmp/x'"


# --- timestamps, transcript created_at, titles, lineage -----------------------


def test_created_from_transcript_line1_and_never_falls_back_to_updated(tmp_path):
    with_t = "aaaaaaaa-0000-4000-8000-000000000001"
    no_t = "aaaaaaaa-0000-4000-8000-000000000002"
    corrupt_t = "aaaaaaaa-0000-4000-8000-000000000003"
    huge_t = "aaaaaaaa-0000-4000-8000-000000000004"

    _create_db(
        tmp_path,
        [
            _full_row(
                with_t,
                title="With transcript",
                last_modified_time="2026-11-25T05:00:00Z",
            ),
            _full_row(
                no_t,
                title="",
                preview="Fallback preview",
                last_modified_time="2026-11-25T05:00:00Z",
            ),
            _full_row(
                corrupt_t,
                title="",
                preview="",
                last_modified_time="2026-11-25T05:00:00Z",
            ),
            _full_row(
                huge_t, title="Huge line 1", last_modified_time="2026-11-25T05:00:00Z"
            ),
        ],
    )
    _write_transcript(
        tmp_path,
        with_t,
        [{"step_index": 0, "created_at": "2026-11-24T19:02:49-08:00", "content": "hi"}],
    )
    corrupt_path = _write_transcript(tmp_path, corrupt_t, ["{not valid json"])
    # Line 1 exceeds 64 KiB cap; created_at near start is still recovered safely.
    _write_transcript(
        tmp_path,
        huge_t,
        [
            '{"step_index":0,"created_at":"2026-11-24T01:02:03Z","content":"'
            + ("x" * 70000)
            + '"}'
        ],
    )

    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path)))
    assert got[with_t].created == "2026-11-25T03:02:49Z"
    assert got[with_t].title == "With transcript"
    assert got[with_t].name is None
    assert got[with_t].name_resumable is False

    # Missing transcript MUST leave created=None (never copy last_modified_time).
    assert got[no_t].created is None
    assert got[no_t].transcript is None
    assert got[no_t].title == "Fallback preview"
    assert got[no_t].updated == "2026-11-25T05:00:00Z"

    # Corrupt transcript leaves row readable, transcript path populated, created=None.
    assert got[corrupt_t].unreadable is False
    assert got[corrupt_t].created is None
    assert got[corrupt_t].transcript == str(corrupt_path)
    assert got[corrupt_t].title is None

    # Huge line 1 still extracts created_at within the bounded 64 KiB read.
    assert got[huge_t].created == "2026-11-24T01:02:03Z"


def test_truncated_line1_reads_only_top_level_created_at(tmp_path):
    nested_before = "aaaaaaaa-0000-4000-8000-000000000011"
    nested_only = "aaaaaaaa-0000-4000-8000-000000000012"
    in_string = "aaaaaaaa-0000-4000-8000-000000000013"
    epoch_after_str = "aaaaaaaa-0000-4000-8000-000000000014"

    _create_db(
        tmp_path,
        [
            _full_row(nested_before),
            _full_row(nested_only),
            _full_row(in_string),
            _full_row(epoch_after_str),
        ],
    )
    _write_transcript(
        tmp_path,
        nested_before,
        [
            '{"metadata":{"created_at":"2020-01-01T00:00:00Z"},'
            '"created_at":"2026-11-24T01:02:03Z","content":"' + ("x" * 70000) + '"}'
        ],
    )
    _write_transcript(
        tmp_path,
        nested_only,
        [
            '{"metadata":{"created_at":"2020-01-01T00:00:00Z"},"content":"'
            + ("x" * 70000)
            + '","created_at":"2026-11-24T01:02:03Z"}'
        ],
    )
    _write_transcript(
        tmp_path,
        in_string,
        [
            '{"content":"\\"created_at\\":\\"2020-01-01T00:00:00Z\\"'
            + ("x" * 70000)
            + '"}'
        ],
    )
    _write_transcript(
        tmp_path,
        epoch_after_str,
        [
            '{"note":"{\\"created_at\\":\\"2020-01-01T00:00:00Z\\"}",'
            '"created_at":1764000000,"content":"' + ("x" * 70000) + '"}'
        ],
    )

    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path)))
    assert got[nested_before].created == "2026-11-24T01:02:03Z"
    assert got[nested_only].created is None
    assert got[in_string].created is None
    assert got[epoch_after_str].created == "2025-11-24T16:00:00Z"


@pytest.mark.parametrize(
    ("raw_ts", "expected"),
    [
        ("2026-11-25T03:02:49Z", "2026-11-25T03:02:49Z"),
        ("2026-11-24T19:02:49-08:00", "2026-11-25T03:02:49Z"),
        ("2026-11-25 03:02:49.123456+00:00", "2026-11-25T03:02:49Z"),
        ("2026-11-24 19:02:49.123456789 -0800 PST m=+0.123456", "2026-11-25T03:02:49Z"),
        ("2026-11-25 03:02:49", "2026-11-25T03:02:49Z"),
        (1764000000, "2025-11-24T16:00:00Z"),
        (1764000000 * 1000, "2025-11-24T16:00:00Z"),
        (1764000000 * 1_000_000, "2025-11-24T16:00:00Z"),
        (1764000000 * 1_000_000_000, "2025-11-24T16:00:00Z"),
    ],
)
def test_updated_timestamp_normalization(tmp_path, raw_ts, expected):
    sid = "33333333-3333-4333-8333-333333333333"
    _create_db(tmp_path, [_full_row(sid, last_modified_time=raw_ts)])
    assert (
        _by_id(Antigravity().scan(ScanContext(home=tmp_path)))[sid].updated == expected
    )


def test_updated_falls_back_to_transcript_mtime_when_db_timestamp_unparseable(tmp_path):
    sid = "33333333-3333-4333-8333-333333333334"
    _create_db(tmp_path, [_full_row(sid, last_modified_time="not-a-timestamp")])
    _write_transcript(
        tmp_path,
        sid,
        [{"step_index": 0, "created_at": "2025-11-24T10:00:00Z"}],
        mtime=1764000000.0,
    )
    s = _by_id(Antigravity().scan(ScanContext(home=tmp_path)))[sid]
    assert s.updated == "2025-11-24T16:00:00Z"


def test_subagent_hidden_and_fork_listed_with_lineage(tmp_path):
    root_id = "44444444-0000-4000-8000-000000000001"
    sub_id = "44444444-0000-4000-8000-000000000002"
    fork_id = "44444444-0000-4000-8000-000000000003"
    _create_db(
        tmp_path,
        [
            _full_row(root_id),
            _full_row(sub_id, parent_conversation_id=root_id, nesting_depth=1),
            _full_row(fork_id, parent_conversation_id=root_id, nesting_depth=0),
        ],
    )
    res = Antigravity().scan(ScanContext(home=tmp_path))
    got = _by_id(res)
    assert res.hidden_subagents == 1
    assert got[root_id].hidden is False and got[root_id].lineage is None
    assert got[sub_id].hidden is True
    assert got[sub_id].lineage == Lineage(kind="subagent", parent_id=root_id)
    assert got[fork_id].hidden is False
    assert got[fork_id].lineage == Lineage(kind="fork", parent_id=root_id)


def test_malformed_row_becomes_unreadable_without_aborting_scan(tmp_path):
    good = "55555555-0000-4000-8000-000000000001"
    bad_ws = "55555555-0000-4000-8000-000000000002"
    bad_depth = "55555555-0000-4000-8000-000000000003"
    _create_db(
        tmp_path,
        [
            _full_row(good),
            # SQLite TEXT affinity preserves BLOB values as bytes, not str.
            _full_row(bad_ws, workspace_uris=b"\xff\xfe"),
            _full_row(bad_depth, nesting_depth="not-a-number"),
        ],
    )
    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path)))
    assert got[good].unreadable is False
    assert got[bad_ws].unreadable is True
    assert got[bad_depth].unreadable is True


# --- 3-tier liveness ----------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [
            "/usr/local/bin/agy",
            "--conversation",
            "66666666-0000-4000-8000-000000000001",
        ],
        ["agy", "--resume", "66666666-0000-4000-8000-000000000001"],
        ["agy", "-r", "66666666-0000-4000-8000-000000000001"],
        ["agy", "--conversation=66666666-0000-4000-8000-000000000001"],
        ["agy", "--resume=66666666-0000-4000-8000-000000000001"],
        ["agy", "-r=66666666-0000-4000-8000-000000000001"],
        [
            "python3",
            "/work/bin/agy",
            "--model",
            "pro",
            "--conversation",
            "66666666-0000-4000-8000-000000000001",
        ],
    ],
)
def test_tier1_explicit_conversation_id_marks_live_yes(tmp_path, argv):
    sid = "66666666-0000-4000-8000-000000000001"
    other = "66666666-0000-4000-8000-000000000002"
    _create_db(tmp_path, [_full_row(sid), _full_row(other)])
    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path, processes={4242: argv})))
    assert got[sid].live == "yes"
    assert got[sid].live_host == "cli"
    assert got[sid].pid == 4242
    assert got[sid].resume is None
    assert got[sid].resume_blocked == "running"
    assert got[other].live == "no"
    assert got[other].resume is not None


@pytest.mark.parametrize(
    "subcmd",
    [
        "acp",
        "agent",
        "agents",
        "changelog",
        "help",
        "install",
        "mcp",
        "mic-serve",
        "models",
        "plugin",
        "plugins",
        "remote-control",
        "update",
    ],
)
def test_non_tui_subcommands_are_excluded_from_liveness(tmp_path, monkeypatch, subcmd):
    sid = "77777777-0000-4000-8000-000000000001"
    _create_db(tmp_path, [_full_row(sid, workspace_uris='["file:///work/alpha"]')])
    monkeypatch.setattr(agy_module, "process_cwd", lambda pid: "/work/alpha")
    got = _by_id(
        Antigravity().scan(
            ScanContext(home=tmp_path, processes={9001: ["agy", subcmd, "--stdio"]})
        )
    )
    assert got[sid].live == "no"
    assert got[sid].live_basis == "no agy process"


def test_tier2_directory_fallback_marks_only_newest_non_hidden_unknown(
    tmp_path, monkeypatch
):
    older = "88888888-0000-4000-8000-000000000001"
    newest = "88888888-0000-4000-8000-000000000002"
    newest_sub = "88888888-0000-4000-8000-000000000003"
    explicit_live = "88888888-0000-4000-8000-000000000004"

    _create_db(
        tmp_path,
        [
            _full_row(older, last_modified_time="2026-11-25T01:00:00Z"),
            _full_row(newest, last_modified_time="2026-11-25T02:00:00Z"),
            _full_row(
                newest_sub,
                last_modified_time="2026-11-25T04:00:00Z",
                parent_conversation_id=newest,
                nesting_depth=1,
            ),
            _full_row(
                explicit_live,
                last_modified_time="2026-11-25T03:00:00Z",
                workspace_uris='["file:///work/beta"]',
            ),
        ],
    )
    cwds = {100: "/work/alpha", 200: "/work/beta", 300: "/work/alpha"}
    monkeypatch.setattr(agy_module, "process_cwd", cwds.get)
    procs = {
        100: ["agy"],
        200: ["agy", "--conversation", explicit_live],
        201: ["agy", "-c"],  # same dir as 200 (would not downgrade Tier 1 yes)
        300: ["agy", "--conversation", "unknown-id-not-in-db"],
    }
    cwds[201] = "/work/beta"

    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path, processes=procs)))
    # Tier 2 marks only newest non-hidden session in /work/alpha as unknown
    assert got[newest].live == "unknown"
    assert got[newest].pid is None
    assert got[newest].resume == f"cd /work/alpha && agy --conversation {newest}"
    assert got[newest].resume_blocked is None
    assert "agy pid 100" in (got[newest].live_basis or "")
    # Older session stays no; subagent stays no
    assert got[older].live == "no"
    assert got[newest_sub].live == "no"
    # Tier 1 live="yes" is never downgraded by Tier 2 in the same directory
    assert got[explicit_live].live == "yes"
    assert got[explicit_live].pid == 200
    assert got[explicit_live].resume_blocked == "running"


def test_explicit_unknown_id_does_not_trigger_tier2_fallback(tmp_path, monkeypatch):
    sid = "88888888-0000-4000-8000-000000000010"
    _create_db(tmp_path, [_full_row(sid)])
    monkeypatch.setattr(agy_module, "process_cwd", lambda pid: "/work/alpha")
    got = _by_id(
        Antigravity().scan(
            ScanContext(
                home=tmp_path,
                processes={500: ["agy", "--conversation", "other-session-id"]},
            )
        )
    )
    assert got[sid].live == "no"


@pytest.mark.parametrize(
    "argv",
    [
        ["agy", "--prompt-interactive", "--conversation=target"],
        ["agy", "-i", "--resume", "target"],
        ["agy", "--model", "--conversation=target"],
        ["agy", "--", "--conversation", "target"],
    ],
)
def test_value_flag_arguments_are_not_mistaken_for_conversation_id(
    tmp_path, monkeypatch, argv
):
    _create_db(tmp_path, [_full_row("target")])
    monkeypatch.setattr(agy_module, "process_cwd", lambda pid: "/work/other")
    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path, processes={600: argv})))
    assert got["target"].live == "no"


def test_real_conversation_id_after_value_flag_is_still_extracted(tmp_path):
    fake = "88888888-0000-4000-8000-000000000021"
    real = "88888888-0000-4000-8000-000000000022"
    _create_db(tmp_path, [_full_row(fake), _full_row(real)])
    argv = [
        "agy",
        "--prompt-interactive",
        f"--conversation={fake}",
        "--conversation",
        real,
    ]
    got = _by_id(Antigravity().scan(ScanContext(home=tmp_path, processes={601: argv})))
    assert got[fake].live == "no"
    assert got[real].live == "yes"
    assert got[real].pid == 601


def test_recovery_window_requires_transcript_created_timestamp(tmp_path):
    dated = "99999999-0000-4000-8000-000000000001"
    undated = "99999999-0000-4000-8000-000000000002"
    _create_db(
        tmp_path,
        [
            _full_row(dated, last_modified_time="2026-11-10T22:00:00Z"),
            _full_row(undated, last_modified_time="2026-11-10T22:00:00Z"),
        ],
    )
    _write_transcript(
        tmp_path,
        dated,
        [{"step_index": 0, "created_at": "2026-11-10T01:00:00Z"}],
    )
    res = Antigravity().scan(ScanContext(home=tmp_path))
    rows = core.select_rows(
        res.sessions,
        dt.datetime(2026, 11, 11, 9, 51, tzinfo=dt.UTC),
        dt.datetime(2026, 11, 10, 8, 0, tzinfo=dt.UTC),
    )
    assert [r.session.id for r in rows] == [dated]


# --- evidence hooks for agy ---------------------------------------------------


def test_normalize_agy_session_start_camel_case_payload():
    payload = {
        "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",
        "hookEventName": "SessionStart",
        "cwd": "/workspace/project",
        "workspacePaths": ["/workspace/project"],
        "transcriptPath": "/home/u/.gemini/antigravity-cli/brain/ec33ebf9/.system_generated/logs/transcript.jsonl",
        "artifactDirectoryPath": "/home/u/.gemini/antigravity-cli/brain/ec33ebf9",
        "modelName": "gemini-3.6-flash-medium",
    }
    event = normalize_hook("agy", payload)
    assert event is not None
    assert event.tool == "agy"
    assert event.session_id == "ec33ebf9-0cba-4100-8142-c61503f6c587"
    assert event.source == "hook"
    assert event.kind == "opened"
    assert event.native_event == "SessionStart"
    assert event.reason is None


def test_normalize_agy_session_start_preserves_reason_or_source():
    with_reason = normalize_hook(
        "agy",
        {
            "conversationId": "conv-1",
            "hookEventName": "SessionStart",
            "reason": "resume",
        },
    )
    assert with_reason is not None
    assert with_reason.kind == "opened"
    assert with_reason.reason == "resume"

    with_source = normalize_hook(
        "agy",
        {
            "conversationId": "conv-1",
            "hookEventName": "SessionStart",
            "source": "startup",
        },
    )
    assert with_source is not None
    assert with_source.kind == "opened"
    assert with_source.reason == "startup"

    compact = normalize_hook(
        "agy",
        {
            "conversationId": "conv-1",
            "hookEventName": "SessionStart",
            "source": "compact",
        },
    )
    assert compact is not None
    assert compact.kind == "context-refreshed"
    assert compact.reason == "compact"

    blank_reason = normalize_hook(
        "agy",
        {
            "conversationId": "conv-1",
            "hookEventName": "SessionStart",
            "source": "   ",
            "reason": "",
        },
    )
    assert blank_reason is not None
    assert blank_reason.reason is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",
            "hookEventName": "Stop",
            "executionNum": 1,
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
            "continuationActive": False,
        },
        {"hookEventName": "Stop"},
        {
            "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",
            "executionNum": 1,
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
        },
        {"conversationId": "conv-1", "hookEventName": "PreToolUse"},
        {"conversationId": "conv-1", "hookEventName": "PostToolUse"},
        {"conversationId": "conv-1", "hookEventName": "PreInvocation"},
        {"conversationId": "conv-1", "hookEventName": "PostInvocation"},
    ],
)
def test_normalize_agy_explicitly_ignores_stop_and_other_events(payload):
    assert normalize_hook("agy", payload) is None


def test_cli_evidence_hook_agy_records_session_start_ignores_stop_and_emits_json(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    store_path = tmp_path / "state" / "lost-sessions" / "evidence.sqlite3"
    runner = CliRunner()
    cli = build_cli()
    args = ["evidence", "hook", "--tool", "agy"]

    # Stop MUST be ignored (no DB created) and still emit `{}` on stdout.
    stop_res = runner.invoke(
        cli,
        args,
        input=json.dumps(
            {
                "conversationId": "conv-stop",
                "hookEventName": "Stop",
                "terminationReason": "NO_TOOL_CALL",
                "fullyIdle": True,
            }
        ),
    )
    assert stop_res.exit_code == 0
    assert json.loads(stop_res.stdout) == {}
    assert not store_path.exists()

    # Invalid input fails open: exit 0, stderr warning, valid `{}` stdout.
    bad_res = runner.invoke(cli, args, input="not json")
    assert bad_res.exit_code == 0
    assert json.loads(bad_res.stdout) == {}
    assert "not recorded" in bad_res.stderr

    # SessionStart records opened and emits `{}` stdout.
    start_res = runner.invoke(
        cli,
        args,
        input=json.dumps(
            {
                "conversationId": "conv-open",
                "hookEventName": "SessionStart",
                "cwd": "/work/proj",
                "workspacePaths": ["/work/proj"],
                "transcriptPath": "/work/proj/transcript.jsonl",
            }
        ),
    )
    assert start_res.exit_code == 0
    assert json.loads(start_res.stdout) == {}
    assert start_res.stderr == ""
    records = Store(store_path).read("agy", "conv-open").records
    assert len(records) == 1
    assert records[0].kind == "opened"
    assert records[0].native_event == "SessionStart"

    # Subsequent Stop does not add an ended record.
    stop_after = runner.invoke(
        cli,
        args,
        input=json.dumps(
            {
                "conversationId": "conv-open",
                "hookEventName": "Stop",
                "terminationReason": "NO_TOOL_CALL",
                "fullyIdle": True,
            }
        ),
    )
    assert stop_after.exit_code == 0
    assert json.loads(stop_after.stdout) == {}
    assert len(Store(store_path).read("agy", "conv-open").records) == 1


# --- native Antigravity plugin manifest validation ----------------------------


def test_antigravity_plugin_manifest_and_hook_template():
    plugin = ROOT / "plugins" / "lost-sessions"
    manifest_path = plugin / ".antigravity-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["$schema"] == "https://antigravity.google/schemas/v1/plugin.json"
    assert manifest["name"] == "lost-sessions"
    assert "_generated" not in manifest
    assert "hooks" not in manifest
    assert not (plugin / "hooks.json").exists()

    template_path = (
        plugin / "skills" / "lost-sessions" / "references" / "antigravity-hooks.json"
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert "lost-sessions-evidence" in template
    hook_group = template["lost-sessions-evidence"]
    assert set(hook_group) == {"SessionStart"}
    assert "Stop" not in hook_group
    handlers = hook_group["SessionStart"]
    assert isinstance(handlers, list) and len(handlers) == 1
    assert handlers[0]["type"] == "command"
    assert "--tool agy" in handlers[0]["command"]


def test_agy_plugin_validate_strict_passes_when_agy_is_installed():
    agy_bin = shutil.which("agy")
    if not agy_bin:
        pytest.skip("agy CLI not installed")
    plugin = ROOT / "plugins" / "lost-sessions"
    proc = subprocess.run(
        [agy_bin, "plugin", "validate", "--strict", "--json", str(plugin)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["manifest"] == ".antigravity-plugin/plugin.json"
    assert report["components"]["skills"] == 1
    assert report["components"]["hooks"] == 0
    bad = [f for f in report["findings"] if f["severity"] in ("error", "warning")]
    assert bad == []
