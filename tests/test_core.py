"""Core selection, history, `list`, `open --print` and `history` (design 0006, TS-5).

Ported from smorin/smorin-bootstrap tests/test_lost_sessions.py at 713e443. The
fake `session-inventory` program there is replaced by a fake agent plugin that
returns the same fixture sessions (design 0006, TS-5).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from lost_sessions import core, history
from lost_sessions.agents import AgentTool, ScanContext
from lost_sessions.cli import build_cli
from lost_sessions.default_plugins.herdr import herdr_index
from lost_sessions.hookspecs import hookimpl
from lost_sessions.models import ScanResult, Session, SourceStatus
from lost_sessions.plugins import load_plugins, pm

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="lost-sessions targets macOS and Linux"
)

UTC = dt.UTC
BOOT = dt.datetime(2026, 11, 11, 9, 51, tzinfo=UTC)
START = dt.datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
# Made-up IDs in each tool's format, never real sessions.
CLAUDE_ID = "3ac1dc6f-0000-4000-8000-00000000fa4e"
CODEX_ID = "01a1c914-0000-7000-8000-00000000fa4e"
MUSE_ID = "01a1cc59-0000-7000-8000-00000000fa4e"
OC_ID = "ses_e33a6af1fakefakefakefake00"


def session(id, created="2026-11-10T01:00:00Z", updated="2026-11-10T22:00:00Z", **kw):
    tool = kw.pop("tool", "claude")
    d = kw.pop("spawn_dir", "/Users/x/c/repo")
    resume = {
        "claude": f"cd {d} && claude --resume {id}",
        "codex": f"codex resume {id}",
        "muse": f"cd {d} && muse resume {id}",
        "opencode": f"cd {d} && opencode --session {id}",
    }[tool]
    s = {
        "tool": tool,
        "id": id,
        "name": None,
        "title": f"title {id[:6]}",
        "spawn_dir": d,
        "created": created,
        "updated": updated,
        "live": "no",
        "resume": resume,
        "resume_blocked": None,
    }
    s.update(kw)
    return Session(**s)


def row(s, n=3):
    return core.Row(n=n, session=s)


def herdr_layout(*ids, ws="work", tab="tab", resume_argv=None):
    panes = {
        str(n): {"cwd": "/", "agent_session": {"value": i}}
        for n, i in enumerate(ids, 1)
    }
    if resume_argv:
        panes["99"] = {
            "cwd": "/",
            "agent_resume": {
                "source": "lost-sessions",
                "agent": "muse",
                "argv": resume_argv,
            },
        }
    return {
        "workspaces": [
            {
                "id": "w1",
                "custom_name": ws,
                "tabs": [{"custom_name": tab, "panes": panes}],
            }
        ]
    }


# --- selection ------------------------------------------------------------------


def test_window_keeps_sessions_started_before_boot_and_active_since_start():
    sessions = [
        session("before-window", "2026-11-01T00:00:00Z", "2026-11-09T00:00:00Z"),
        session("in-window", "2026-11-09T00:00:00Z", "2026-11-10T20:00:00Z"),
        session("resumed-after-boot", "2026-11-10T01:00:00Z", "2026-11-11T12:00:00Z"),
        session("started-after-boot", "2026-11-11T10:00:00Z", "2026-11-11T11:00:00Z"),
    ]
    ids = [r.session.id for r in core.select_rows(sessions, BOOT, START)]
    assert ids == ["in-window", "resumed-after-boot"]


def test_numbers_follow_start_time_and_survive_a_resume():
    sessions = [
        session("b", "2026-11-10T02:00:00Z", "2026-11-10T21:00:00Z"),
        session("a", "2026-11-10T01:00:00Z", "2026-11-10T22:00:00Z"),
    ]
    rows = core.select_rows(sessions, BOOT, START)
    assert [(r.n, r.session.id) for r in rows] == [(1, "a"), (2, "b")]
    sessions[1].updated = "2026-11-11T12:00:00Z"
    rows = core.select_rows(sessions, BOOT, START)
    assert [(r.n, r.session.id) for r in rows] == [(1, "a"), (2, "b")]


def test_missing_timestamps_are_skipped():
    assert (
        core.select_rows([session("x", None, "2026-11-10T22:00:00Z")], BOOT, START)
        == []
    )


def test_short_ids_grow_until_unique():
    rows = [
        row(session("01a1cc76-aaaa")),
        row(session("01a1cc76-bbbb")),
        row(session(CLAUDE_ID)),
    ]
    assert core.short_ids(rows) == {
        "01a1cc76-aaaa": "01a1cc76-a",
        "01a1cc76-bbbb": "01a1cc76-b",
        CLAUDE_ID: "3ac1dc6f",
    }


def test_about_collapses_and_truncates_long_titles():
    s = session("x", title="line one\n\n" + "word " * 200)
    assert len(core.about(s)) <= core.ABOUT_MAX
    assert core.about(s).startswith("line one word")
    assert core.about(s).endswith("…")


def test_default_window_is_midnight_on_the_day_before_boot():
    boot = dt.datetime(2026, 11, 13, 18, 0).astimezone()  # a Friday evening
    start = core.parse_since(None, boot)
    assert (start.date(), start.hour, start.minute) == (dt.date(2026, 11, 12), 0, 0)
    assert start.tzinfo is not None


def test_date_is_local_midnight_with_offset():
    start = core.parse_since("2026-11-09", BOOT)
    assert start.isoformat()[:19] == "2026-11-09T00:00:00"
    assert start.utcoffset() is not None


def test_relative_window_values():
    now = dt.datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert core.parse_since("3d", BOOT, now) == now - dt.timedelta(days=3)
    assert core.parse_since("90m", BOOT, now) == now - dt.timedelta(minutes=90)


def test_bad_window_value_raises():
    with pytest.raises(ValueError):
        core.parse_since("yesterday-ish", BOOT)


def test_boot_time_is_known_on_this_platform():
    boot = core.boot_time()
    assert boot.tzinfo is not None
    assert boot < dt.datetime.now().astimezone()


# --- Herdr's restore index (the Herdr manager's restored_ids) ------------------


@pytest.fixture
def herdr_dir(tmp_path):
    (tmp_path / "session-snapshots").mkdir()
    return tmp_path


def _write(base, rel, data, when):
    import os

    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    os.utime(p, (when.timestamp(), when.timestamp()))


def test_uses_last_snapshot_before_boot_plus_current_layout(herdr_dir):
    _write(
        herdr_dir,
        "session-snapshots/old.json",
        herdr_layout("closed-long-ago"),
        BOOT - dt.timedelta(days=30),
    )
    _write(
        herdr_dir,
        "session-snapshots/last.json",
        herdr_layout("pre-boot", ws="ws", tab="t"),
        BOOT - dt.timedelta(minutes=8),
    )
    _write(
        herdr_dir,
        "session-snapshots/after.json",
        herdr_layout("post-boot-snap"),
        BOOT + dt.timedelta(hours=1),
    )
    _write(
        herdr_dir,
        "session.json",
        herdr_layout("current"),
        BOOT + dt.timedelta(hours=10),
    )
    idx = herdr_index(herdr_dir, BOOT)
    assert set(idx) == {"pre-boot", "current"}
    assert idx["pre-boot"] == "ws / t"


def test_agent_resume_argv_counts_as_in_herdr(herdr_dir):
    _write(
        herdr_dir,
        "session.json",
        herdr_layout(resume_argv=["muse", "resume", MUSE_ID]),
        BOOT,
    )
    assert MUSE_ID in herdr_index(herdr_dir, BOOT)


def test_named_herdr_sessions_are_included(herdr_dir):
    _write(herdr_dir, "session.json", herdr_layout("default-one"), BOOT)
    _write(
        herdr_dir,
        "sessions/side/session.json",
        herdr_layout("named-one", ws="side-ws"),
        BOOT,
    )
    idx = herdr_index(herdr_dir, BOOT)
    assert set(idx) == {"default-one", "named-one"}
    assert idx["named-one"] == "side: side-ws / tab"


def test_missing_or_corrupt_files_yield_empty_index(herdr_dir):
    (herdr_dir / "session.json").write_text("{not json")
    assert herdr_index(herdr_dir, BOOT) == {}
    assert herdr_index(herdr_dir / "nope", BOOT) == {}


# --- helpers and resume commands --------------------------------------------------


def test_scratchpad_and_live_test_folders_are_helpers():
    assert core.is_helper(
        session("x", spawn_dir="/private/tmp/claude-501/-Users-x-c-repo/abc/sp/t")
    )
    assert core.is_helper(
        session("x", spawn_dir="/var/folders/ab/T/lost-sessions-live-tt4nkeqo")
    )


def test_codex_companion_title_or_name_is_helper():
    assert core.is_helper(session("x", title="Codex Companion Task: Pilot check"))
    assert core.is_helper(
        session("x", tool="codex", title=None, name="Codex Companion Task: Pilot")
    )


def test_normal_session_is_not_helper():
    assert not core.is_helper(session("x"))
    assert not core.is_helper(session("x", title=None, spawn_dir=None))


@pytest.fixture
def agents():
    load_plugins(pm)
    return core.agent_tools()


def test_resume_args_per_tool(agents):
    d = "/Users/x/c/my repo"
    assert core.resume_args(session(CLAUDE_ID, spawn_dir=d)) == [
        "claude",
        "--resume",
        CLAUDE_ID,
    ]
    assert core.resume_args(session(CODEX_ID, tool="codex")) == [
        "codex",
        "resume",
        CODEX_ID,
    ]
    assert core.resume_args(session(MUSE_ID, tool="muse")) == [
        "muse",
        "resume",
        MUSE_ID,
    ]
    assert core.resume_args(session(OC_ID, tool="opencode")) == [
        "opencode",
        "--session",
        OC_ID,
    ]


def test_resume_command_is_built_when_the_inventory_withholds_it(agents):
    d = "/Users/x/c/my repo"
    s = session(CLAUDE_ID, spawn_dir=d, resume=None, resume_blocked="running")
    assert (
        core.resume_command(s)
        == f"cd '/Users/x/c/my repo' && claude --resume {CLAUDE_ID}"
    )
    assert core.resume_command(
        session(CODEX_ID, tool="codex", spawn_dir=d, resume=None)
    ) == (f"codex resume {CODEX_ID}")


# --- the CLI harness ----------------------------------------------------------------


class FakeAgent(AgentTool):
    """Stands in for every agent: returns the fixture sessions it was given."""

    name = "fake"

    def resume_args(self, session):
        return ["fake", session.id]

    def __init__(self):
        self.sessions: list[Session] = []
        self.fail: str | None = None

    def scan(self, ctx: ScanContext) -> ScanResult:
        from lost_sessions.agents import SourceError

        if self.fail:
            raise SourceError(self.fail)
        return ScanResult(
            sessions=[s.model_copy() for s in self.sessions],
            source=SourceStatus(status="ok", path="fake"),
        )


class FakeAgentPlugin:
    __name__ = "FakeAgentPlugin"

    def __init__(self, agent):
        self.agent = agent

    @hookimpl
    def register_agent_tools(self, register):
        register(self.agent)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """HOME and XDG_STATE_HOME are temporary; one fake agent supplies the sessions."""
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for var in ("CODEX_HOME", "XDG_DATA_HOME", "REX_SESSION"):
        monkeypatch.delenv(var, raising=False)
    w = str(work)
    agent = FakeAgent()
    agent.sessions = [
        session(
            CLAUDE_ID,
            created="2000-01-02T00:00:00Z",
            updated="2000-01-03T00:00:00Z",
            spawn_dir=w,
        ),
        session(
            CODEX_ID,
            tool="codex",
            created="2000-01-02T01:00:00Z",
            updated="2000-01-03T00:00:00Z",
            spawn_dir=w,
        ),
        session(
            MUSE_ID,
            tool="muse",
            created="2000-01-02T02:00:00Z",
            updated="2000-01-03T00:00:00Z",
            spawn_dir=w,
        ),
        session(
            "running-1",
            created="2000-01-02T03:00:00Z",
            updated="2000-01-03T00:00:00Z",
            live="yes",
            resume=None,
            resume_blocked="running",
            spawn_dir=w,
        ),
        session(
            "maybe-1",
            created="2000-01-02T04:00:00Z",
            updated="2000-01-03T00:00:00Z",
            live="unknown",
            live_basis="opencode pid 7 in this folder",
            spawn_dir=w,
        ),
        session(
            "gone-1",
            tool="muse",
            created="2000-01-02T05:00:00Z",
            updated="2000-01-03T00:00:00Z",
            spawn_dir=str(tmp_path / "deleted"),
            resume=None,
            resume_blocked="no_workspace",
        ),
        session(
            "bracket-1",
            created="2000-01-02T06:00:00Z",
            updated="2000-01-03T00:00:00Z",
            title="fix [/api] route [docs](http://x)",
            spawn_dir=w,
        ),
    ]
    plugin = FakeAgentPlugin(agent)
    load_plugins(pm)
    pm.register(plugin, name="undo-FakeAgentPlugin")
    try:
        yield {"tmp": tmp_path, "work": work, "agent": agent}
    finally:
        pm.unregister(name="undo-FakeAgentPlugin")


SINCE = ("--since", "2000-01-01")


def run(*argv):
    result = CliRunner().invoke(build_cli(pm), list(argv), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


# --- state: history log and saved listing -----------------------------------------


def test_log_location_honors_xdg_state_home(cli_env, monkeypatch):
    tmp = cli_env["tmp"]
    assert history.log_path() == tmp / "state" / "lost-sessions" / "history.jsonl"
    monkeypatch.setenv("XDG_STATE_HOME", "")
    assert (
        history.log_path() == tmp / "home" / ".local/state/lost-sessions/history.jsonl"
    )


def test_append_then_read_back(cli_env):
    history.append_log(history.HistoryEntry(action="print", id="a"))
    history.append_log(history.HistoryEntry(action="rex", id="b"))
    assert [e.entry.id for e in history.read_log()] == ["a", "b"]


def test_read_log_keeps_going_past_corrupt_lines(cli_env):
    history.log_path().parent.mkdir(parents=True)
    history.log_path().write_text('{"id": "a"}\nnot json\n')
    lines = history.read_log()
    assert lines[0].entry.id == "a"
    assert lines[1].entry is None and lines[1].number == 2


def _rows(agent):
    return core.select_rows(
        [s.model_copy() for s in agent.sessions],
        BOOT,
        dt.datetime(2000, 1, 1, tzinfo=UTC),
    )


def test_listing_round_trip_and_ref_resolution(cli_env):
    rows = _rows(cli_env["agent"])
    history.save_listing(rows, START)
    picked, problems = core.resolve_refs(
        ["2", "3ac1dc", MUSE_ID], rows, history.load_listing()
    )
    assert [r.session.id for r in picked] == [CODEX_ID, CLAUDE_ID, MUSE_ID]
    assert problems == []


def test_ref_problems(cli_env):
    rows = _rows(cli_env["agent"])
    history.save_listing(rows, START)
    _, problems = core.resolve_refs(
        ["99", "zzzz", "01a1c"], rows, history.load_listing()
    )
    assert len(problems) == 3
    assert "matches 2 sessions" in problems[2]
    _, problems = core.resolve_refs(["1"], rows, None)
    assert "no saved listing" in problems[0]


def test_number_whose_session_left_the_window(cli_env):
    rows = _rows(cli_env["agent"])
    history.save_listing(rows, START)
    _, problems = core.resolve_refs(["1"], rows[1:], history.load_listing())
    assert "no longer in the window" in problems[0]


# --- CLI ------------------------------------------------------------------------------


def test_bare_invocation_prints_help_and_exits_zero(cli_env):
    code, out, _ = run()
    assert code == 0
    for sub in ("list", "open", "history", "inventory"):
        assert sub in out


def test_list_hides_running_unless_all_and_marks_maybe_running(cli_env):
    _, out, _ = run("list", *SINCE)
    assert CLAUDE_ID in out
    assert "running-1" not in out
    assert "maybe running" in out
    _, out, _ = run("list", *SINCE, "--all")
    assert "running-1" in out
    assert "RUNNING" in out
    assert "None" not in out


def test_bad_since_is_usage_error(cli_env):
    code, _, err = run("list", "--since", "soon")
    assert code == 2
    assert "--since" in err


def test_partial_inventory_failure_still_lists_and_warns(cli_env):
    class Broken(AgentTool):
        name = "broken"

        def resume_args(self, session):
            return []

        def scan(self, ctx):
            from lost_sessions.agents import SourceError

            raise SourceError("opencode: opencode.db: database is locked")

    plugin = FakeAgentPlugin(Broken())
    plugin.__name__ = "Broken"
    pm.register(plugin, name="undo-Broken")
    try:
        code, out, err = run("list", *SINCE)
    finally:
        pm.unregister(name="undo-Broken")
    assert code == 0
    assert CLAUDE_ID in out
    assert "database is locked" in err


def test_all_and_hide_running_cannot_be_combined(cli_env):
    code, _, err = run("list", *SINCE, "--all", "--hide-running")
    assert code == 2
    assert "not allowed with" in err
    _, out, _ = run("list", *SINCE, "--hide-running")
    assert "running-1" not in out


def test_open_by_number_uses_the_saved_listing(cli_env):
    run("list", *SINCE)
    code, out, _ = run(
        "open", "1", "--print"
    )  # no --since: reuses the listing's window
    assert code == 0
    assert f"claude --resume {CLAUDE_ID}" in out
    last = history.read_log()[-1].entry
    assert (last.action, last.id) == ("print", CLAUDE_ID)


def test_open_by_id_prefix_needs_no_listing(cli_env):
    code, out, _ = run("open", "3ac1dc6f", "--print", *SINCE)
    assert code == 0
    assert CLAUDE_ID in out


def test_print_of_running_session_shows_a_real_command(cli_env):
    code, out, _ = run("open", "running-1", "--print", *SINCE, "--all")
    assert code == 0
    assert f"cd {cli_env['work']} && claude --resume running-1" in out


def test_print_notes_a_missing_folder(cli_env):
    run("open", "gone-1", "--print", *SINCE)
    assert "no longer exists" in history.read_log()[-1].entry.note


def test_open_unknown_refs_are_usage_errors(cli_env):
    code, _, err = run("open", "99", "--print", *SINCE)
    assert code == 2
    assert "99" in err


def test_destination_with_print_is_a_usage_error(cli_env):
    code, _, err = run("open", f"{CLAUDE_ID}@existing", "--print", *SINCE)
    assert code == 2
    assert "@" in err


def test_open_needs_a_way_to_open(cli_env):
    code, _, err = run("open", CLAUDE_ID, *SINCE)
    assert code == 2
    assert "--print" in err


def test_history_shows_location_first(cli_env):
    run("open", "3ac1dc6f", "--print", *SINCE)
    _, out, _ = run("history")
    assert str(history.log_path()) in out.splitlines()[0]
    assert CLAUDE_ID in out


def test_history_json_is_pure_json_lines(cli_env):
    run("open", "3ac1dc6f", "--print", *SINCE)
    _, out, err = run("history", "--json")
    assert [json.loads(line)["id"] for line in out.splitlines()] == [CLAUDE_ID]
    assert str(history.log_path()) in err


def test_history_when_empty(cli_env):
    _, out, _ = run("history")
    assert str(history.log_path()) in out.splitlines()[0]
    assert "No recoveries" in out


# --- stored-data compatibility (design 0006, Section 8.1, TS-11) ---------------------


SCHEMA_0 = {  # today's real format: ten keys, no schema
    "time": "2026-11-11T10:00:00-08:00",
    "action": "print",
    "tool": "claude",
    "id": "old-0",
    "about": "an old one",
    "dir": "/w",
    "commands": ["claude --resume old-0"],
    "opened": {},
    "result": "ok",
    "note": "",
}


def _write_log(lines):
    history.log_path().parent.mkdir(parents=True, exist_ok=True)
    history.log_path().write_text("".join(line + "\n" for line in lines))


def test_new_lines_are_stamped_with_schema_and_writer(cli_env):
    run("open", "3ac1dc6f", "--print", *SINCE)
    raw = json.loads(history.log_path().read_text().splitlines()[-1])
    assert list(raw)[:10] == list(SCHEMA_0)
    assert raw["schema"] == 1
    assert raw["written_by"].startswith("lost-sessions ")


def test_history_shows_every_kind_of_line_and_exits_zero(cli_env):
    newer = {
        "schema": 99,
        "time": "t",
        "action": "teleport",
        "id": "future",
        "brand_new": [1],
    }
    missing = {"time": "t2", "id": "sparse"}
    _write_log(
        [
            json.dumps(SCHEMA_0),
            json.dumps(newer),
            json.dumps(missing),
            "not json at all",
        ]
    )
    code, out, err = run("history")
    assert code == 0
    assert "old-0" in out and "future" in out and "sparse" in out
    assert "schema 99" in out  # newer lines carry an upgrade note
    assert "? (unreadable line 4)" in out
    sparse = out[out.index("sparse") :]
    assert "about: ?" in sparse and "dir:   ?" in sparse
    code, out, err = run("history", "--json")
    assert code == 0
    assert [json.loads(line) for line in out.splitlines()] == [SCHEMA_0, newer, missing]
    assert "? (unreadable line 4)" in err


def test_present_but_empty_fields_print_empty(cli_env):
    _write_log([json.dumps(SCHEMA_0 | {"note": "", "about": ""})])
    _, out, _ = run("history")
    assert "about: \n" in out


def test_unreadable_listing_asks_for_a_fresh_list(cli_env):
    history.listing_path().parent.mkdir(parents=True, exist_ok=True)
    history.listing_path().write_text("{broken")
    code, _, err = run("open", "1", "--print", *SINCE)
    assert code == 2
    assert "lost-sessions list" in err


def test_listing_with_a_newer_schema_asks_for_a_fresh_list(cli_env):
    history.listing_path().parent.mkdir(parents=True, exist_ok=True)
    history.listing_path().write_text(
        json.dumps({"schema": 99, "rows": [{"n": 1, "id": CLAUDE_ID}]})
    )
    code, _, err = run("open", "1", "--print", *SINCE)
    assert code == 2
    assert "lost-sessions list" in err


def test_listing_is_stamped(cli_env):
    run("list", *SINCE)
    data = json.loads(history.listing_path().read_text())
    assert data["schema"] == 1 and data["written_by"].startswith("lost-sessions ")
    assert {"saved", "since", "rows"} <= set(data)


def test_state_dir_name(cli_env):
    assert history.state_dir().name == Path("lost-sessions").name


def test_wrong_typed_known_fields_still_show(cli_env):
    _write_log(
        [
            json.dumps(
                {"time": 5, "id": ["x"], "commands": "one", "opened": 3, "note": None}
            )
        ]
    )
    code, out, _ = run("history")
    assert code == 0
    assert "cmd:   one" in out and "value=3" in out


# --- review fixes (PR #12) ------------------------------------------------------------


def test_commands_use_the_manager_given_to_build_cli(cli_env, monkeypatch):
    from lost_sessions.plugins import make_plugin_manager

    isolated = make_plugin_manager()
    load_plugins(isolated)
    isolated.register(FakeAgentPlugin(cli_env["agent"]), name="isolated-fake")
    pm.unregister(name="undo-FakeAgentPlugin")  # the global registry no longer has it
    try:
        result = CliRunner().invoke(build_cli(isolated), ["list", *SINCE])
    finally:
        pm.register(FakeAgentPlugin(cli_env["agent"]), name="undo-FakeAgentPlugin")
    assert result.exit_code == 0
    assert CLAUDE_ID in result.stdout


@pytest.mark.parametrize("saved", ["not-a-date", "2026-11-11T10:00:00"])
def test_listing_with_a_bad_saved_time_asks_for_a_fresh_list(cli_env, saved):
    run("list", *SINCE)
    data = json.loads(history.listing_path().read_text())
    data["saved"] = saved
    history.listing_path().write_text(json.dumps(data))
    code, _, err = run("open", "1", "--print")
    assert code == 2
    assert "lost-sessions list" in err


def test_listing_with_a_stray_schema_key_still_loads(cli_env):
    run("list", *SINCE)
    data = json.loads(history.listing_path().read_text())
    data["schema_"] = "x"
    history.listing_path().write_text(json.dumps(data))
    assert history.load_listing() is not None
    assert run("open", CLAUDE_ID, "--print", *SINCE)[0] == 0


@pytest.mark.parametrize(
    "layout",
    [
        {"workspaces": None},
        {"workspaces": [None]},
        {"workspaces": [{"tabs": [{"panes": []}]}]},
    ],
)
def test_misshapen_herdr_layouts_are_unreadable_not_fatal(herdr_dir, layout):
    (herdr_dir / "session.json").write_text(json.dumps(layout))
    assert herdr_index(herdr_dir, BOOT) == {}


def test_invalid_utf8_in_history_is_one_unreadable_line(cli_env):
    history.log_path().parent.mkdir(parents=True, exist_ok=True)
    history.log_path().write_bytes(
        json.dumps(SCHEMA_0).encode()
        + b"\n\xff\xfe broken\n"
        + json.dumps(SCHEMA_0).encode()
        + b"\n"
    )
    code, out, _ = run("history")
    assert code == 0
    assert "? (unreadable line 2)" in out
    assert out.count("about: an old one") == 2
