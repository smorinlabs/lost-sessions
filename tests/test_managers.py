"""The Herdr and Rex managers: plans, execution, destinations, focus, and the
`open --herdr/--rex` and `workspaces` commands (design 0006, TS-5).

Ported from smorin/smorin-bootstrap tests/test_lost_sessions.py at 713e443. Fake
`herdr` and `rex` programs replay the JSON the real tools returned in the
2026-11-11 live run (Herdr 0.9.5, rex 0.1.0-preview.14).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import textwrap

import pytest

from lost_sessions import core, history
from lost_sessions.default_plugins.herdr import HerdrDestination, agent_name
from lost_sessions.default_plugins.rex import RexDestination
from lost_sessions.history import HistoryEntry
from lost_sessions.managers import run_json
from tests.test_core import (  # noqa: F401 - cli_env is a fixture
    CLAUDE_ID,
    CODEX_ID,
    MUSE_ID,
    OC_ID,
    SINCE,
    cli_env,
    run,
    session,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="lost-sessions targets macOS and Linux"
)

NAME_RE = r"^[a-z][a-z0-9_-]{0,31}$"
SYSTEM_PATH = (
    "/usr/bin:/bin:/usr/sbin:/sbin"  # never the user's PATH: real rex/herdr unreachable
)

FAKE_HERDR = textwrap.dedent(f"""\
    #!{sys.executable}
    import json, os, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(["herdr"] + a) + "\\n")
    if a[:2] == ["--session", "t"]:
        a = a[2:]
    def out(o):
        print(json.dumps(o)); sys.exit(0)
    def fail(code, msg):
        sys.stderr.write(json.dumps({{"error": {{"code": code, "message": msg}}}}) + "\\n"); sys.exit(1)
    nopane = os.environ.get("FAKE_NOPANE") == "1"
    if a[:2] == ["workspace", "list"]:
        out({{"id": "cli:workspace:list", "result": {{"type": "workspace_list", "workspaces": [
            {{"workspace_id": "wA", "label": "existing", "tab_count": 2, "number": 1}},
            {{"workspace_id": "wD1", "label": "dup", "tab_count": 1, "number": 2}},
            {{"workspace_id": "wD2", "label": "dup", "tab_count": 1, "number": 3}}]}}}})
    if a[:2] == ["workspace", "create"]:
        out({{"id": "cli:workspace:create", "result": {{}} if nopane else {{"root_pane": {{
            "pane_id": "wN:p1", "tab_id": "wN:t1", "workspace_id": "wN"}},
            "workspace": {{"workspace_id": "wN", "label": a[a.index("--label") + 1]}}}}}})
    if a[:2] == ["tab", "create"]:
        ws = a[a.index("--workspace") + 1]
        out({{"id": "cli:tab:create", "result": {{"root_pane": {{"pane_id": ws + ":p9", "tab_id": ws + ":t9",
            "workspace_id": ws}}}}}})
    if a[:2] == ["tab", "rename"]:
        out({{"id": "cli:tab:rename", "result": {{}}}})
    if a[:2] == ["tab", "focus"]:
        out({{"id": "cli:tab:focus", "result": {{"type": "tab_info", "tab": {{"tab_id": a[2], "focused": True}}}}}})
    if a[:2] == ["agent", "start"]:
        name, kind = a[2], a[a.index("--kind") + 1]
        names = os.environ["FAKE_LOG"] + ".names"
        taken = open(names).read().split() if os.path.exists(names) else []
        if name in taken:
            fail("agent_name_taken", "agent name already in use")
        open(names, "a").write(name + "\\n")
        if kind in os.environ.get("FAKE_BLOCK", "").split(","):
            fail("agent_not_ready", "blocked during startup")
        out({{"id": "cli:agent:start", "result": {{"agent": {{"agent": kind, "agent_status": "idle"}}}}}})
    if a[:2] == ["pane", "report-agent"]:
        out({{"id": "cli:pane:report_agent", "result": {{}}}})
    fail("unknown", "unexpected")
""")

# Like real Rex, renaming a window that lives in another session fails unless the
# command is scoped to that session with -s.
FAKE_REX = textwrap.dedent(f"""\
    #!{sys.executable}
    import json, os, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(["rex"] + a) + "\\n")
    def scope():
        return a[a.index("-s") + 1] if "-s" in a else None
    if a[:2] == ["session", "list"]:
        print(json.dumps({{"sessions": [{{"session_id": "session:cur", "label": "mine"}},
                                       {{"session_id": "session:other", "label": "other"}}]}}))
    elif a[:2] == ["session", "new"]:
        if os.environ.get("FAKE_REX_FAIL") == "1":
            sys.stderr.write("Error: server unavailable\\n"); sys.exit(1)
        sid = "session:new-" + a[2]
        print(json.dumps({{"session_id": sid, "initial_windows": [
            {{"window_id": "window:in-" + sid, "block_ids": ["block:1"], "revision": 1}}]}}))
    elif a[:1] == ["run"]:
        print(json.dumps({{"window_id": "window:in-" + (scope() or "active"), "block_ids": ["block:2"],
                          "revision": 2}}))
    elif a[:2] == ["do", "session.select"] or a[:1] == ["focus"]:
        print("null")
    elif a[:2] == ["window", "rename"]:
        win = [t for t in a[2:] if t.startswith("window:")][0]
        home = win[len("window:in-"):]
        if home != "active" and scope() != home:
            sys.stderr.write(f'Error: window target "{{win}}" not found\\n'); sys.exit(3)
    sys.exit(0)
""")


def write_exe(path, body):
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def fakes(cli_env, monkeypatch):
    """PATH holds only fake herdr/rex and the system tools."""
    tmp = cli_env["tmp"]
    bindir = tmp / "bin"
    bindir.mkdir()
    write_exe(bindir / "herdr", FAKE_HERDR)
    write_exe(bindir / "rex", FAKE_REX)
    log = tmp / "calls.jsonl"
    log.touch()
    monkeypatch.setenv("PATH", f"{bindir}:{SYSTEM_PATH}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("REX_SESSION", "session:cur")

    def calls(lists=False):
        """Commands the fakes received; `list` lookups only when asked."""
        got = [json.loads(line) for line in log.read_text().splitlines()]
        return got if lists else [c for c in got if "list" not in c[1:3]]

    return {**cli_env, "bin": bindir, "calls": calls, "log": log}


def rows(env):
    picked = core.select_rows(
        [s.model_copy() for s in env["agent"].sessions],
        dt.datetime(2026, 11, 11, tzinfo=dt.UTC),
        dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
    )
    return {r.session.id: r for r in picked}


def managers():
    return core.session_managers()


def herdr_dest(label="recovered", id=None, session=None):
    return HerdrDestination(manager="herdr", label=label, id=id, session=session)


def rex_dest(label="recovered", id=None, current=False):
    return RexDestination(manager="rex", label=label, id=id, current=current)


def plan_row(id=CLAUDE_ID, tool="claude", n=3, **kw):
    s = session(
        id, tool=tool, spawn_dir=kw.pop("spawn_dir", "/Users/x/c/my repo"), **kw
    )
    return core.Row(n=n, session=s)


def steps(row, name, dest):
    return [s.argv for s in managers()[name].plan(core.make_plan(row), dest)]


# --- isolation ---------------------------------------------------------------------


def test_only_the_fakes_are_on_path(fakes):
    for tool in ("rex", "herdr"):
        assert shutil.which(tool) == str(fakes["bin"] / tool)


def test_a_broken_fake_fails_instead_of_reaching_the_real_tool(fakes):
    write_exe(fakes["bin"] / "rex", "    not a script\n")  # no #! line: exec fails
    response = run_json(["rex", "session", "list", "--json"])
    assert response.code != 0
    assert response.data == {}


# --- plans --------------------------------------------------------------------------


def test_rex_plan_into_the_active_session_runs_then_names_the_window(cli_env):
    r = plan_row()
    got = steps(r, "rex", rex_dest("current", current=True))
    assert got[0] == [
        "rex",
        "run",
        "--json",
        "--focus=false",
        "--interactive",
        "--label",
        "#3 title 3ac1dc",
        "-c",
        "/Users/x/c/my repo",
        "--",
        "zsh",
        "-c",
        r.session.resume,
    ]
    assert got[1] == ["rex", "window", "rename", "{window}", "#3 title 3ac1dc"]


def test_rex_plan_into_a_new_session_names_its_first_window(cli_env):
    r = plan_row()
    assert steps(r, "rex", rex_dest()) == [
        [
            "rex",
            "session",
            "new",
            "recovered",
            "--json",
            "--window",
            "#3 title 3ac1dc",
            "-c",
            "/Users/x/c/my repo",
            "--interactive",
            "--",
            "zsh",
            "-c",
            r.session.resume,
        ]
    ]


def test_rex_plan_into_another_session_scopes_run_and_rename(cli_env):
    got = steps(plan_row(), "rex", rex_dest("other", "session:other"))
    assert got[0][:4] == ["rex", "run", "-s", "session:other"]
    assert got[1] == [
        "rex",
        "window",
        "rename",
        "-s",
        "session:other",
        "{window}",
        "#3 title 3ac1dc",
    ]


def test_preview_of_a_second_row_into_a_new_rex_session(cli_env):
    text = core.preview(
        plan_row(), "rex", managers()["rex"], rex_dest("recovered", "{session}")
    )
    assert "rex run -s <new session>" in text


def test_herdr_plan_creates_workspace_names_its_first_tab_and_starts_agent(cli_env):
    r = plan_row()
    got = steps(r, "herdr", herdr_dest())
    assert got[0] == [
        "herdr",
        "workspace",
        "create",
        "--label",
        "recovered",
        "--cwd",
        "/Users/x/c/my repo",
        "--no-focus",
    ]
    assert got[1] == ["herdr", "tab", "rename", "{tab}", "#3 title 3ac1dc"]
    assert got[2][:4] == ["herdr", "agent", "start", agent_name("claude", CLAUDE_ID)]
    assert got[2][4:] == [
        "--kind",
        "claude",
        "--pane",
        "{pane}",
        "--",
        "--resume",
        CLAUDE_ID,
    ]
    assert len(got) == 3  # Claude has a Herdr integration: no report-agent


def test_herdr_plan_uses_tab_in_existing_workspace(cli_env):
    got = steps(plan_row(), "herdr", herdr_dest("existing", "wA"))
    assert got[0] == [
        "herdr",
        "tab",
        "create",
        "--workspace",
        "wA",
        "--cwd",
        "/Users/x/c/my repo",
        "--label",
        "#3 title 3ac1dc",
        "--no-focus",
    ]


def test_muse_and_opencode_report_their_resume_command(cli_env):
    for id, tool, argv in (
        (MUSE_ID, "muse", ["muse", "resume", MUSE_ID]),
        (OC_ID, "opencode", ["opencode", "--session", OC_ID]),
    ):
        got = steps(plan_row(id, tool), "herdr", herdr_dest())
        assert got[-1] == [
            "herdr",
            "pane",
            "report-agent",
            "{pane}",
            "--source",
            "lost-sessions",
            "--agent",
            tool,
            "--state",
            "idle",
            "--agent-session-id",
            id,
            "--",
            *argv,
        ]


def test_named_herdr_session_prefix(cli_env):
    got = steps(plan_row(), "herdr", herdr_dest(session="t"))
    assert all(s[:3] == ["herdr", "--session", "t"] for s in got)


def test_preview_shows_every_step_shell_quoted(cli_env):
    text = core.preview(plan_row(), "herdr", managers()["herdr"], herdr_dest())
    assert (
        "herdr workspace create --label recovered --cwd '/Users/x/c/my repo' --no-focus"
        in text
    )
    assert "--pane <pane>" in text


def test_print_plan_is_the_resume_command_only(cli_env):
    r = plan_row()
    assert core.preview(r, "print", None, None) == r.session.resume


def test_agent_names_are_valid_and_unique_for_time_ordered_ids():
    ids = [
        "01a1cc76-0001-7aaa-8000-000000000001",
        "01a1cc76-0001-7aaa-8000-000000000002",
        "ses_e9f206e96ffenoxNbQAwSPtNDN",
        "ses_e9f211b1affeyRdvQTSZigGu0e",
    ]
    names = [agent_name("opencode" if i.startswith("ses_") else "muse", i) for i in ids]
    assert len(set(names)) == len(names)
    for n in names:
        assert __import__("re").match(NAME_RE, n)


# --- execution ------------------------------------------------------------------------


def execute(r, name, dest):
    return core.execute(r, managers()[name], dest)


def test_rex_opens_window_in_active_session_and_renames_it(fakes):
    entry = execute(rows(fakes)[CLAUDE_ID], "rex", rex_dest("current", current=True))
    assert (entry.result, entry.note) == ("ok", "")
    assert entry.opened == {"rex_window": "window:in-active"}
    assert fakes["calls"]()[1] == [
        "rex",
        "window",
        "rename",
        "window:in-active",
        "#1 title 3ac1dc",
    ]


def test_rex_new_session_is_created_once_then_reused_with_scoped_renames(fakes):
    target = rex_dest()
    rs = rows(fakes)
    first = execute(rs[CLAUDE_ID], "rex", target)
    second = execute(rs[CODEX_ID], "rex", target)
    assert first.opened == {
        "rex_session": "session:new-recovered",
        "rex_window": "window:in-session:new-recovered",
    }
    assert (second.result, second.note) == ("ok", "")
    assert [c[1:3] for c in fakes["calls"]()] == [
        ["session", "new"],
        ["run", "-s"],
        ["window", "rename"],
    ]
    assert fakes["calls"]()[2][3:5] == ["-s", "session:new-recovered"]


def test_rex_current_session_inside_rex_is_scoped(fakes):
    entry = execute(
        rows(fakes)[CLAUDE_ID], "rex", rex_dest("current", "session:cur", current=True)
    )
    assert (entry.result, entry.note) == ("ok", "")
    assert fakes["calls"]()[0][:3] == ["rex", "run", "-s"]


def test_herdr_new_workspace_then_reuses_it(fakes):
    target = herdr_dest()
    rs = rows(fakes)
    first = execute(rs[CLAUDE_ID], "herdr", target)
    second = execute(rs[CODEX_ID], "herdr", target)
    assert first.opened == {
        "herdr_workspace": "wN",
        "herdr_tab": "wN:t1",
        "herdr_pane": "wN:p1",
    }
    assert second.opened == {
        "herdr_workspace": "wN",
        "herdr_tab": "wN:t9",
        "herdr_pane": "wN:p9",
    }
    assert [c[1:3] for c in fakes["calls"]()] == [
        ["workspace", "create"],
        ["tab", "rename"],
        ["agent", "start"],
        ["tab", "create"],
        ["agent", "start"],
    ]
    assert fakes["calls"]()[1][3] == "wN:t1"


def test_muse_reports_resume_command_to_herdr(fakes):
    entry = execute(rows(fakes)[MUSE_ID], "herdr", herdr_dest("existing", "wA"))
    assert entry.result == "ok"
    assert fakes["calls"]()[-1][:4] == ["herdr", "pane", "report-agent", "wA:p9"]


def test_trust_prompt_is_logged_blocked_and_still_reported(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_BLOCK", "muse")
    entry = execute(rows(fakes)[MUSE_ID], "herdr", herdr_dest("existing", "wA"))
    assert entry.result == "blocked"
    assert "trust" in entry.note
    assert fakes["calls"]()[-1][1:3] == ["pane", "report-agent"]


def test_failure_is_logged_failed(fakes):
    write_exe(
        fakes["bin"] / "herdr",
        '#!/bin/sh\necho \'{"error":{"code":"boom"}}\' >&2\nexit 1\n',
    )
    entry = execute(rows(fakes)[CLAUDE_ID], "herdr", herdr_dest())
    assert entry.result == "failed"
    assert "boom" in entry.note


def test_missing_program_is_failed_not_a_crash(fakes, monkeypatch):
    (fakes["bin"] / "rex").unlink()
    monkeypatch.setenv("PATH", str(fakes["bin"]))
    entry = execute(rows(fakes)[CLAUDE_ID], "rex", rex_dest())
    assert entry.result == "failed"
    assert "not_found" in entry.note


def test_create_without_pane_is_failed_and_agent_not_started(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_NOPANE", "1")
    entry = execute(rows(fakes)[CLAUDE_ID], "herdr", herdr_dest())
    assert entry.result == "failed"
    assert ["agent", "start"] not in [c[1:3] for c in fakes["calls"]()]


def test_non_object_json_is_tolerated(fakes):
    write_exe(
        fakes["bin"] / "herdr",
        "#!/bin/sh\necho '[1,2]'\necho '{\"error\":\"text\"}' >&2\nexit 1\n",
    )
    assert execute(rows(fakes)[CLAUDE_ID], "herdr", herdr_dest()).result == "failed"


def test_two_time_ordered_sessions_get_distinct_agent_names(fakes):
    w = str(fakes["work"])
    a = core.Row(
        n=1,
        session=session(
            "01a1cc76-0001-7aaa-8000-000000000001", tool="muse", spawn_dir=w
        ),
    )
    b = core.Row(
        n=2,
        session=session(
            "01a1cc76-0001-7aaa-8000-000000000002", tool="muse", spawn_dir=w
        ),
    )
    target = herdr_dest("existing", "wA")
    assert [execute(r, "herdr", target).result for r in (a, b)] == ["ok", "ok"]


def test_missing_folder_is_skipped_for_rex(fakes):
    assert execute(rows(fakes)["gone-1"], "rex", rex_dest()).result == "skipped"
    assert fakes["calls"]() == []


# --- focus ---------------------------------------------------------------------------


def entry(action, opened, result="ok"):
    return HistoryEntry.new(
        action=action,
        result=result,
        opened=opened,
        tool="claude",
        id=CLAUDE_ID,
        about="a",
        dir="/",
    )


def test_focus_commands_per_manager(cli_env):
    assert core.focus_command(entry("herdr", {"herdr_tab": "wN:t1"}), {}) == [
        "herdr",
        "tab",
        "focus",
        "wN:t1",
    ]
    assert core.focus_command(
        entry("herdr", {"herdr_tab": "wN:t1"}), {"herdr_session": "t"}
    ) == ["herdr", "--session", "t", "tab", "focus", "wN:t1"]
    assert core.focus_command(
        entry("rex", {"rex_session": "session:s", "rex_window": "window:w"}), {}
    ) == ["rex", "do", "session.select", "session_id=session:s", "window_id=window:w"]
    assert core.focus_command(entry("rex", {"rex_window": "window:w"}), {}) == [
        "rex",
        "focus",
        "window:w",
    ]


def test_nothing_to_focus_when_nothing_opened(cli_env):
    assert core.focus_command(entry("herdr", {}), {}) is None
    assert core.focus_command(entry("print", {}), {}) is None
    assert (
        core.focus_command(
            entry("rex", {"rex_window": "window:w"}, result="failed"), {}
        )
        is None
    )


def test_focus_runs_and_returns_a_log_entry(fakes):
    opened = execute(rows(fakes)[CLAUDE_ID], "herdr", herdr_dest())
    f = core.focus(opened, {})
    assert (f.action, f.result, f.id) == ("focus", "ok", CLAUDE_ID)
    assert fakes["calls"]()[-1] == ["herdr", "tab", "focus", "wN:t1"]


def test_focus_without_ids_is_skipped_with_a_note(fakes):
    f = core.focus(entry("herdr", {}), {})
    assert f.result == "skipped"
    assert "nothing" in f.note


# --- destinations -----------------------------------------------------------------------


def dests(name, **options):
    opts = {
        "workspace": "recovered",
        "rex_session": "recovered",
        "herdr_session": None,
    } | options
    return managers()[name].destinations(opts)


def test_same_label_is_one_shared_target(fakes):
    h, r = dests("herdr"), dests("rex")
    assert h.get("recovered") is h.get("recovered")
    assert r.get("recovered") is r.default()


def test_existing_labels_resolve_to_ids(fakes):
    assert dests("herdr").get("existing").id == "wA"
    assert dests("rex").get("other").id == "session:other"
    assert dests("herdr").get("recovered").id is None
    assert dests("rex").get("recovered").id is None


def test_current_rex_session_inside_and_outside_rex(fakes, monkeypatch):
    r = dests("rex")
    cur = r.get("current")
    assert (cur.id, cur.current) == ("session:cur", True)
    assert r.where(cur) == "current (mine)"
    monkeypatch.setenv("REX_SESSION", "")
    r = dests("rex")
    cur = r.get("current")
    assert (cur.id, cur.current) == (None, True)
    assert r.where(cur) == "current (Rex's active session)"


def test_choices_put_the_default_first_and_the_current_session_once(fakes):
    r, h = dests("rex"), dests("herdr")
    assert [r.where(t) for t in r.choices()] == [
        "recovered (new)",
        "current (mine)",
        "other",
    ]
    assert [h.describe(t) for t in h.choices()] == [
        "recovered (new)",
        "existing",
        "dup (wD1)",
        "dup (wD2)",
    ]


def test_workspaces_sharing_a_label_stay_distinct(fakes):
    h = dests("herdr")
    assert [t.id for t in h.choices()[2:]] == ["wD1", "wD2"]
    assert h.get("wD2").id == "wD2"  # a DEST can be an ID
    assert h.ambiguous("dup") == ["wD1", "wD2"]
    assert h.ambiguous("existing") == []


def test_existing_default_is_not_listed_twice(fakes):
    h = dests("herdr", workspace="existing")
    assert [h.describe(t) for t in h.choices()] == [
        "existing",
        "dup (wD1)",
        "dup (wD2)",
    ]


# --- CLI ------------------------------------------------------------------------------------


def test_open_refuses_running_session_logs_skip_and_exits_one(fakes):
    code, _, err = run("open", "running-1", "--rex", *SINCE, "--all")
    assert code == 1
    assert "skipped" in err
    assert fakes["calls"]() == []
    assert history.read_log()[-1].entry.result == "skipped"


def test_open_maybe_running_warns_and_opens(fakes):
    code, _, err = run("open", "maybe-1", "--rex", *SINCE)
    assert code == 0
    assert "may already be running" in err
    assert fakes["calls"]()[0][:3] == ["rex", "session", "new"]


def test_open_exit_status_failed_is_one_blocked_is_zero(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_BLOCK", "muse")
    assert run("open", MUSE_ID, "--herdr", *SINCE)[0] == 0
    (fakes["bin"] / "rex").unlink()
    assert run("open", CLAUDE_ID, "--rex", *SINCE)[0] == 1


def test_workspaces_lists_existing_herdr_workspaces(fakes):
    code, out, _ = run("workspaces")
    assert code == 0
    assert "existing" in out
    assert "recovered" in out


def test_workspaces_also_lists_rex_sessions(fakes):
    _, out, _ = run("workspaces")
    assert "Rex sessions" in out
    assert "current (mine)" in out
    assert "session:other" in out


def test_workspaces_without_herdr_is_an_error(fakes, monkeypatch):
    (fakes["bin"] / "herdr").unlink()
    monkeypatch.setenv("PATH", str(fakes["bin"]))
    code, _, err = run("workspaces")
    assert code == 1
    assert "could not reach Herdr" in err


def test_open_sends_each_ref_to_its_own_destination(fakes):
    run("list", *SINCE)
    code, _, _ = run(
        "open", "1@existing", "2@brand-new", "3", "--herdr"
    )  # no --since: listing's
    assert code == 0
    creates = [c[1:] for c in fakes["calls"]() if c[2:3] == ["create"]]
    assert creates[0][:4] == ["tab", "create", "--workspace", "wA"]
    assert creates[1][:4] == ["workspace", "create", "--label", "brand-new"]
    assert creates[2][:4] == ["workspace", "create", "--label", "recovered"]


def test_open_rex_session_option_and_current(fakes):
    run("open", CLAUDE_ID, "--rex", "--rex-session", "other", *SINCE)
    assert fakes["calls"]()[0][:4] == ["rex", "run", "-s", "session:other"]
    run("open", f"{CODEX_ID}@current", "--rex", *SINCE)
    assert fakes["calls"]()[-2][:4] == ["rex", "run", "-s", "session:cur"]


def test_open_default_rex_destination_is_a_new_recovered_session(fakes):
    run("open", CLAUDE_ID, "--rex", *SINCE)
    assert fakes["calls"]()[0][:4] == ["rex", "session", "new", "recovered"]


def test_current_outside_rex_warns(fakes, monkeypatch):
    monkeypatch.delenv("REX_SESSION")
    _, _, err = run("open", f"{CLAUDE_ID}@current", "--rex", *SINCE)
    assert "not running inside Rex" in err


def test_ambiguous_destination_is_a_usage_error_naming_the_ids(fakes):
    code, _, err = run("open", f"{CLAUDE_ID}@dup", "--herdr", *SINCE)
    assert code == 2
    assert "wD1" in err
    assert fakes["calls"]() == []
    code, _, _ = run("open", f"{CLAUDE_ID}@wD2", "--herdr", *SINCE)
    assert (code, fakes["calls"]()[0][:4]) == (
        0,
        ["herdr", "tab", "create", "--workspace"],
    )
    assert fakes["calls"]()[0][4] == "wD2"


def test_open_focus_defaults_to_the_last_session_opened(fakes):
    code, _, _ = run("open", CLAUDE_ID, CODEX_ID, "--herdr", "--focus", *SINCE)
    assert code == 0
    assert fakes["calls"]()[-1] == ["herdr", "tab", "focus", "wN:t9"]
    assert history.read_log()[-1].entry.action == "focus"


def test_open_focus_names_one_ref(fakes):
    run(
        "open",
        f"{CLAUDE_ID}@existing",
        CODEX_ID,
        "--herdr",
        "--focus",
        CLAUDE_ID,
        *SINCE,
    )
    assert fakes["calls"]()[-1] == ["herdr", "tab", "focus", "wA:t9"]


def test_open_focus_on_a_rex_session(fakes):
    run("open", CLAUDE_ID, "--rex", "--rex-session", "other", "--focus", *SINCE)
    assert fakes["calls"]()[-1] == [
        "rex",
        "do",
        "session.select",
        "session_id=session:other",
        "window_id=window:in-session:other",
    ]


def test_focus_without_ref_skips_sessions_that_were_not_opened(fakes):
    run("open", CLAUDE_ID, "running-1", "--herdr", "--focus", *SINCE)
    assert fakes["calls"]()[-1] == ["herdr", "tab", "focus", "wN:t1"]


def test_a_destination_named_rename_still_reports_a_failure(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_REX_FAIL", "1")
    code, _, _ = run("open", f"{CLAUDE_ID}@rename", "--rex", *SINCE)
    assert (code, history.read_log()[-1].entry.result) == (1, "failed")


def test_focus_usage_errors(fakes):
    code, _, err = run("open", CLAUDE_ID, "--herdr", "--focus", "nope", *SINCE)
    assert code == 2
    assert "--focus" in err
    code, _, _ = run("open", CLAUDE_ID, "--print", "--focus", *SINCE)
    assert code == 2
    assert fakes["calls"]() == []


def test_exactly_one_way_to_open(fakes):
    code, _, err = run("open", CLAUDE_ID, *SINCE)
    assert code == 2 and "--print" in err and "--herdr" in err and "--rex" in err
    code, _, _ = run("open", CLAUDE_ID, "--print", "--rex", *SINCE)
    assert code == 2


# --- review fixes (PR #13) --------------------------------------------------------------


class RestoreOnly:
    __name__ = "RestoreOnly"

    @staticmethod
    def manager():
        from lost_sessions.managers import SessionManager

        class Keeper(SessionManager):
            name = "keeper"
            display_name = "Keeper"
            restores = True

        return Keeper()


@pytest.fixture
def restore_only_plugin(fakes):
    from lost_sessions.hookspecs import hookimpl
    from lost_sessions.plugins import pm

    class Plugin:
        __name__ = "KeeperPlugin"

        @hookimpl
        def register_session_managers(self, register):
            register(RestoreOnly.manager())

    pm.register(Plugin(), name="undo-KeeperPlugin")
    try:
        yield
    finally:
        pm.unregister(name="undo-KeeperPlugin")


def test_a_restore_only_manager_does_not_break_open_or_workspaces(
    restore_only_plugin, fakes
):
    code, _, _ = run("open", CLAUDE_ID, "--herdr", *SINCE)
    assert code == 0
    code, out, _ = run("workspaces")
    assert code == 0 and "Herdr workspaces" in out and "Rex sessions" in out
    code, _, _ = run("open", CLAUDE_ID, "--keeper", *SINCE)
    assert code == 2  # a manager that cannot open gets no --keeper flag


def test_rex_run_without_a_window_id_is_failed(fakes):
    write_exe(fakes["bin"] / "rex", "#!/bin/sh\necho '{}'\n")
    entry = execute(rows(fakes)[CLAUDE_ID], "rex", rex_dest("other", "session:other"))
    assert entry.result == "failed"
    assert "nothing opened" in entry.note


def test_rex_session_without_a_first_window_is_failed(fakes):
    write_exe(
        fakes["bin"] / "rex",
        '#!/bin/sh\necho \'{"session_id": "session:s", "initial_windows": []}\'\n',
    )
    target = rex_dest()
    entry = execute(rows(fakes)[CLAUDE_ID], "rex", target)
    assert entry.result == "failed"
    assert target.id == "session:s"  # the session exists; later rows reuse it


def test_non_string_herdr_ids_are_failed_not_a_crash(fakes):
    write_exe(
        fakes["bin"] / "herdr",
        '#!/bin/sh\necho \'{"result": {"root_pane": {"pane_id": 7, "tab_id": 8, "workspace_id": "wN"}}}\'\n',
    )
    entry = execute(rows(fakes)[CLAUDE_ID], "herdr", herdr_dest())
    assert entry.result == "failed"


def test_an_opening_manager_without_its_own_section_gets_a_generic_one():
    from lost_sessions.managers import Destination, Destinations, SessionManager

    class Plain(SessionManager):
        name, display_name, can_open = "plain", "Plain", True

    class PlainDests(Destinations):
        def get(self, label):
            return Destination(manager="plain", label=label)

    lines = Plain().workspaces_lines(PlainDests("recovered", True))
    assert lines == [
        "Plain destinations (REF@LABEL with --plain):",
        "  recovered (new)   (default)",
    ]
