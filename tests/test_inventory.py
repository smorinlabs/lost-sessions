"""`lost-sessions inventory` and the four built-in agent plugins (TS-4).

Ported from smorinlabs/smorinlabs-skills tests/test_session_inventory.py at
cf83bf1, where they drove the `session-inventory list` script. They now drive
`python -m lost_sessions inventory` the same way: fixture stores for Claude
Code, Codex, Muse and OpenCode under a fake HOME, stand-in processes for
liveness, and subprocess runs that check exit codes, the stdout/stderr split
and the JSON contract.
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

# The scanners read the process table with `ps` and `lsof`, and the stand-ins are
# executable shebang scripts: POSIX only, like the original tool (macOS).
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="agent scanners and stand-ins need POSIX tools"
)

COMMAND = [sys.executable, "-m", "lost_sessions"]

NOW = time.time()
HOUR = 3600


def iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def write_jsonl(path: Path, records, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def utc_lstart(pid: int) -> str:
    out = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        env={**os.environ, "TZ": "UTC"},
    ).stdout
    return " ".join(out.split())


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


@pytest.fixture()
def procs():
    """Start stand-in processes; kill them all at teardown."""
    started = []

    def start(argv, cwd=None):
        """Start a process; stand-ins built by fake_tool signal readiness through
        READY_FILE once they run under their own name with locks held."""
        ready = Path(argv[0] + f".ready-{len(started)}")
        p = subprocess.Popen(
            argv, cwd=cwd, env={**os.environ, "READY_FILE": str(ready)}
        )
        started.append(p)
        if argv[0].endswith(("/sleep", "sleep")):
            return p
        deadline = time.time() + 15
        while not ready.exists():
            assert time.time() < deadline, f"stand-in {argv[0]} never became ready"
            time.sleep(0.05)
        return p

    yield start
    for p in started:
        p.kill()
        p.wait()


def fake_tool(bindir: Path, name: str) -> Path:
    """An executable named after a tool that sleeps, optionally holding a file open."""
    bindir.mkdir(parents=True, exist_ok=True)
    exe = bindir / name
    exe.write_text(
        f"#!{sys.executable}\n"  # absolute: a PATH shim would change the pid
        "import os, sys, time\n"
        "held = [open(a) for a in sys.argv[1:] if a.endswith('.lock')]\n"
        "open(os.environ['READY_FILE'], 'w').close()\n"
        "time.sleep(60)\n"
    )
    exe.chmod(0o755)
    return exe


# --- fixture stores -----------------------------------------------------------


def build_claude(home: Path):
    proj = home / ".claude" / "projects" / "-work-alpha"
    ids = {
        "renamed": "11111111-1111-4111-8111-111111111111",
        "plain": "22222222-2222-4222-8222-222222222222",
        "broken": "33333333-3333-4333-8333-333333333333",
    }
    write_jsonl(
        proj / f"{ids['renamed']}.jsonl",
        [
            {"type": "mode", "sessionId": ids["renamed"]},
            {
                "type": "user",
                "timestamp": iso(NOW - 3 * HOUR),
                "cwd": "/work/alpha",
                "gitBranch": "main",
                "sessionId": ids["renamed"],
            },
            {"type": "ai-title", "aiTitle": "old title", "sessionId": ids["renamed"]},
            {
                "type": "ai-title",
                "aiTitle": "Fix skill symlinks",
                "sessionId": ids["renamed"],
            },
            {
                "type": "custom-title",
                "customTitle": "symlink-fix",
                "sessionId": ids["renamed"],
            },
        ],
        mtime=NOW - 1 * HOUR,
    )
    write_jsonl(
        proj / f"{ids['plain']}.jsonl",
        [
            {
                "type": "user",
                "timestamp": iso(NOW - 50 * HOUR),
                "cwd": "/work/my repo",
                "sessionId": ids["plain"],
            },
        ],
        mtime=NOW - 48 * HOUR,
    )
    (proj / f"{ids['broken']}.jsonl").write_text("{not json\n\x00\x01garbage")
    # sidecar dir: must be ignored
    write_jsonl(
        proj / ids["renamed"] / "subagents" / "agent-x.jsonl",
        [{"type": "user", "timestamp": iso(NOW), "cwd": "/work/alpha"}],
    )
    return ids


def build_codex(home: Path):
    root = home / ".codex"
    day = root / "sessions" / "2026" / "09" / "20"
    ids = {
        "user": "0a000000-0000-7000-8000-00000000000a",
        "fork": "0b000000-0000-7000-8000-00000000000b",
        "sub": "0c000000-0000-7000-8000-00000000000c",
        "guard": "0d000000-0000-7000-8000-00000000000d",
    }

    def meta(i, **extra):
        return [
            {
                "type": "session_meta",
                "payload": {
                    "id": i,
                    "timestamp": iso(NOW - 5 * HOUR),
                    "cwd": "/work/beta",
                    "thread_source": "user",
                    "source": "cli",
                    **extra,
                },
            }
        ]

    write_jsonl(
        day / f"rollout-2026-09-20T10-00-00-{ids['user']}.jsonl",
        meta(ids["user"]),
        NOW - 2 * HOUR,
    )
    write_jsonl(
        day / f"rollout-2026-09-20T11-00-00-{ids['fork']}.jsonl",
        meta(ids["fork"], forked_from_id=ids["user"]),
        NOW - 2 * HOUR,
    )
    write_jsonl(
        day / f"rollout-2026-09-20T12-00-00-{ids['sub']}.jsonl",
        meta(
            ids["sub"],
            thread_source="subagent",
            source={"subagent": {"thread_spawn": {"parent_thread_id": ids["user"]}}},
        ),
        NOW - 2 * HOUR,
    )
    write_jsonl(
        day / f"rollout-2026-09-20T13-00-00-{ids['guard']}.jsonl",
        meta(
            ids["guard"],
            thread_source="guardian_review",
            source={"subagent": {"other": "guardian"}},
        ),
        NOW - 2 * HOUR,
    )
    write_jsonl(
        root / "session_index.jsonl",
        [
            {"id": ids["user"], "thread_name": "Review README", "updated_at": iso(NOW)},
        ],
    )
    locks = root / "thread-writer-locks"
    locks.mkdir(parents=True)
    for i in ids.values():
        (locks / f"{i}.lock").touch()
    return ids


MUSE_SCHEMA = """CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY, session_dir TEXT NOT NULL, session_log_path TEXT NOT NULL,
  workspace_root TEXT, git_branch TEXT, title TEXT NOT NULL, session_name TEXT,
  created_at_us INTEGER, updated_at_us INTEGER, status TEXT NOT NULL,
  msp_fork_source_session_id TEXT)"""


def build_muse(home: Path, host: str | None = None):
    data = home / ".local" / "share" / "muse"
    ids = {
        "named": "01a0ca24-4bbc-7ec1-bd58-21281a1af2bf",
        "stale": "01a0ca25-4bbc-7ec1-bd58-21281a1af2bf",
        "noworkspace": "01a0ca26-4bbc-7ec1-bd58-21281a1af2bf",
        "fork": "01a0ca27-4bbc-7ec1-bd58-21281a1af2bf",
    }
    data.mkdir(parents=True)
    db = sqlite3.connect(data / "session-index.db")
    db.execute(MUSE_SCHEMA)
    rows = [
        (
            ids["named"],
            "/work/gamma",
            "main",
            "Look at CI bottleneck",
            None,
            None,
            NOW - 1 * HOUR,
        ),
        (
            ids["stale"],
            "/work/gamma",
            None,
            "Old stale one",
            None,
            None,
            NOW - 30 * HOUR,
        ),
        (ids["noworkspace"], None, None, "New session", None, None, NOW - 4 * HOUR),
        (
            ids["fork"],
            "/work/gamma",
            None,
            "Forked",
            None,
            ids["named"],
            NOW - 2 * HOUR,
        ),
    ]
    for sid, ws, branch, title, name, fork, updated in rows:
        sdir = data / "sessions" / "2026" / "09" / "22" / sid
        sdir.mkdir(parents=True)
        (sdir / "session.jsonl").write_text("{}\n")
        (sdir / ".session.lock").write_text(
            f"pid={dead_pid()}\nhost={host or socket.gethostname()}\n"
        )
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                str(sdir),
                str(sdir / "session.jsonl"),
                ws,
                branch,
                title,
                name,
                int((updated - HOUR) * 1e6),
                int(updated * 1e6),
                "valid",
                fork,
            ),
        )
    db.commit()
    db.close()
    authority = (
        home / "Library" / "Application Support" / "Muse" / "session-name-authority"
    )
    authority.mkdir(parents=True)
    names = sqlite3.connect(authority / "session-names.db")
    names.execute(
        "CREATE TABLE session_name_claims (normalized_name TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
        " kind TEXT NOT NULL, claim_revision INTEGER NOT NULL, created_sequence INTEGER NOT NULL)"
    )
    names.execute(
        "INSERT INTO session_name_claims VALUES ('old-name', ?, 'tombstone', 0, 1)",
        (ids["named"],),
    )
    names.execute(
        "INSERT INTO session_name_claims VALUES ('copper-umbra', ?, 'canonical', 1, 2)",
        (ids["named"],),
    )
    names.commit()
    names.close()
    return ids, data


OPENCODE_SCHEMA = """CREATE TABLE session (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT, slug TEXT NOT NULL,
  directory TEXT NOT NULL, title TEXT NOT NULL, version TEXT NOT NULL,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, time_archived INTEGER)"""


def build_opencode(home: Path):
    data = home / ".local" / "share" / "opencode"
    data.mkdir(parents=True)
    # Unique per call: OpenCode liveness reads the machine-wide process table, so
    # a stand-in `opencode --session <id>` from a parallel test must not match.
    token = os.urandom(4).hex()
    ids = {
        "top": f"ses_top{token}",
        "child": f"ses_child{token}",
        "archived": f"ses_arch{token}",
    }
    db = sqlite3.connect(data / "opencode.db")
    db.execute(OPENCODE_SCHEMA)
    ms = lambda t: int(t * 1000)  # noqa: E731
    db.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ids["top"],
            "p1",
            None,
            "brave-otter",
            "/work/delta",
            "Find justfile recipes",
            "1",
            ms(NOW - 7 * HOUR),
            ms(NOW - 6 * HOUR),
            None,
        ),
    )
    db.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ids["child"],
            "p1",
            ids["top"],
            "calm-fox",
            "/work/delta",
            "Explore (@explore subagent)",
            "1",
            ms(NOW - 7 * HOUR),
            ms(NOW - 6 * HOUR),
            None,
        ),
    )
    db.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ids["archived"],
            "p1",
            None,
            "quiet-owl",
            "/work/delta",
            "Archived one",
            "1",
            ms(NOW - 90 * HOUR),
            ms(NOW - 80 * HOUR),
            ms(NOW - 70 * HOUR),
        ),
    )
    db.commit()
    db.close()
    return ids, data


@pytest.fixture()
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture()
def world(home):
    return {
        "claude": build_claude(home),
        "codex": build_codex(home),
        "muse": build_muse(home)[0],
        "opencode": build_opencode(home)[0],
    }


def run(home: Path, *args, env_extra=None):
    env = {
        k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "XDG_DATA_HOME")
    }
    env.update({"HOME": str(home), **(env_extra or {})})
    env["LOST_SESSIONS_LOAD_PLUGINS"] = ""  # built-in plugins only
    return subprocess.run(
        [*COMMAND, *args], capture_output=True, text=True, env=env, timeout=60
    )


def inventory(home: Path, *args, **kw):
    r = run(home, "inventory", "--json", *args, **kw)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def by_id(doc):
    return {s["id"]: s for s in doc["sessions"]}


# --- CLI basics (R4.1, R6.1, R7.9) ----------------------------------------------


def test_bare_invocation_prints_help_and_exits_zero(home):
    r = run(home)
    assert r.returncode == 0
    assert "usage" in r.stdout.lower()


def test_version_goes_to_stdout(home):
    r = run(home, "--version")
    assert r.returncode == 0 and r.stdout.strip()


def test_output_flags_select_json(home):
    # session-inventory also accepted these before its verb; lost-sessions takes
    # them on `inventory` only, since its other commands have their own output.
    for argv in (
        ["inventory", "--json"],
        ["inventory", "-o", "json"],
        ["inventory", "--output", "json"],
    ):
        r = run(home, *argv)
        assert r.returncode == 0, (argv, r.stderr)
        assert json.loads(r.stdout)["sessions"] == []
    assert not run(home, "inventory").stdout.lstrip().startswith("{")


def test_unknown_tool_is_usage_error(home):
    r = run(home, "inventory", "--tool", "grok")
    assert r.returncode == 2


def test_bad_since_is_usage_error(home):
    r = run(home, "inventory", "--since", "yesterday-ish")
    assert r.returncode == 2


def test_empty_home_is_success_with_absent_sources(home):
    doc = inventory(home)
    assert doc["sessions"] == []
    assert {v["status"] for v in doc["sources"].values()} == {"absent"}


# --- per-tool extraction ------------------------------------------------------


def test_claude_name_title_dir_and_resume(home, world):
    s = by_id(inventory(home, "--tool", "claude"))[world["claude"]["renamed"]]
    assert s["tool"] == "claude"
    assert s["name"] == "symlink-fix"
    assert s["title"] == "Fix skill symlinks"
    assert s["spawn_dir"] == "/work/alpha"
    assert s["branch"] == "main"
    assert s["created"].startswith(iso(NOW - 3 * HOUR)[:16])
    assert (
        s["resume"] == f"cd /work/alpha && claude --resume {world['claude']['renamed']}"
    )
    assert s["name_resumable"] is False and s["resume_by_name"] is None


def test_claude_resume_quotes_paths_with_spaces(home, world):
    s = by_id(inventory(home, "--tool", "claude"))[world["claude"]["plain"]]
    assert (
        s["resume"]
        == f"cd '/work/my repo' && claude --resume {world['claude']['plain']}"
    )


def test_claude_unreadable_is_listed_and_counted(home, world):
    doc = inventory(home, "--tool", "claude")
    s = by_id(doc)[world["claude"]["broken"]]
    assert s["unreadable"] is True
    assert doc["census"]["claude"]["unreadable"] == 1


def test_claude_sidecar_dirs_are_ignored(home, world):
    doc = inventory(home, "--tool", "claude")
    assert len(doc["sessions"]) == 3


def test_codex_names_forks_and_hidden_subagents(home, world):
    doc = inventory(home, "--tool", "codex")
    ids = world["codex"]
    got = by_id(doc)
    assert set(got) == {ids["user"], ids["fork"]}
    assert got[ids["user"]]["name"] == "Review README"
    assert got[ids["user"]]["name_resumable"] is True
    assert got[ids["user"]]["resume"] == f"codex resume {ids['user']}"
    assert got[ids["user"]]["resume_by_name"] == "codex resume 'Review README'"
    assert got[ids["fork"]]["lineage"] == {"kind": "fork", "parent_id": ids["user"]}
    assert doc["census"]["codex"]["hidden_subagents"] == 2


def test_codex_include_subagents_shows_them_with_lineage(home, world):
    ids = world["codex"]
    got = by_id(inventory(home, "--tool", "codex", "--include-subagents"))
    assert got[ids["sub"]]["lineage"] == {"kind": "subagent", "parent_id": ids["user"]}
    assert ids["guard"] in got


def test_codex_string_subagent_source_is_hidden(home, world):
    # real shape seen on 2026-09-22: {"subagent": "review"} (string, not object)
    rid = "0e000000-0000-7000-8000-00000000000e"
    write_jsonl(
        home
        / ".codex/sessions/2026/09/20"
        / f"rollout-2026-09-20T14-00-00-{rid}.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": rid,
                    "timestamp": iso(NOW),
                    "cwd": "/w",
                    "thread_source": "subagent",
                    "source": {"subagent": "review"},
                },
            }
        ],
    )
    doc = inventory(home, "--tool", "codex", "--include-subagents")
    assert by_id(doc)[rid]["lineage"] == {"kind": "subagent", "parent_id": None}
    assert doc["census"]["codex"]["hidden_subagents"] == 3


def test_codex_home_env_is_honored(home, world, tmp_path):
    moved = tmp_path / "elsewhere"
    (home / ".codex").rename(moved)
    got = by_id(
        inventory(home, "--tool", "codex", env_extra={"CODEX_HOME": str(moved)})
    )
    assert world["codex"]["user"] in got


def test_muse_name_resume_and_fork(home, world):
    ids = world["muse"]
    got = by_id(inventory(home, "--tool", "muse"))
    s = got[ids["named"]]
    assert s["name"] == "copper-umbra" and s["name_resumable"] is True
    assert s["title"] == "Look at CI bottleneck"
    assert s["resume"] == f"cd /work/gamma && muse resume {ids['named']}"
    assert s["resume_by_name"] == "cd /work/gamma && muse resume copper-umbra"
    assert got[ids["fork"]]["lineage"] == {"kind": "fork", "parent_id": ids["named"]}
    assert s["export_command"] == f"muse export --session {ids['named']}"


def test_muse_name_falls_back_to_index_column(home, world):
    ids = world["muse"]
    (
        home
        / "Library"
        / "Application Support"
        / "Muse"
        / "session-name-authority"
        / "session-names.db"
    ).unlink()
    db = sqlite3.connect(home / ".local/share/muse/session-index.db")
    db.execute(
        "UPDATE sessions SET session_name = 'from-index' WHERE session_id = ?",
        (ids["fork"],),
    )
    db.commit()
    db.close()
    got = by_id(inventory(home, "--tool", "muse"))
    assert got[ids["fork"]]["name"] == "from-index"
    assert got[ids["named"]]["name"] is None


def test_muse_missing_workspace_blocks_resume(home, world):
    s = by_id(inventory(home, "--tool", "muse"))[world["muse"]["noworkspace"]]
    assert s["resume"] is None and s["resume_blocked"] == "no_workspace"


def test_muse_schema_change_is_partial_failure(home, world):
    db = sqlite3.connect(home / ".local/share/muse/session-index.db")
    db.execute("ALTER TABLE sessions RENAME COLUMN workspace_root TO ws")
    db.commit()
    db.close()
    r = run(home, "inventory", "--json")
    assert r.returncode == 1
    doc = json.loads(r.stdout)
    assert doc["sources"]["muse"]["status"] == "error"
    assert world["codex"]["user"] in by_id(doc)  # other tools still listed
    err = json.loads(r.stderr.strip().splitlines()[-1])
    assert err["error"]["code"] == "source_unreadable" and err["error"]["sources"] == [
        "muse"
    ]


def test_muse_store_is_not_modified(home, world):
    db_path = home / ".local/share/muse/session-index.db"
    before = db_path.read_bytes()
    inventory(home, "--tool", "muse")
    assert db_path.read_bytes() == before


def test_xdg_data_home_is_honored(home, world, tmp_path):
    moved = tmp_path / "xdg"
    (home / ".local" / "share").rename(moved)
    doc = inventory(
        home,
        "--tool",
        "muse",
        "--tool",
        "opencode",
        env_extra={"XDG_DATA_HOME": str(moved)},
    )
    assert world["muse"]["named"] in by_id(doc)
    assert world["opencode"]["top"] in by_id(doc)


def test_opencode_slug_children_archive_and_export(home, world):
    ids = world["opencode"]
    doc = inventory(home, "--tool", "opencode")
    got = by_id(doc)
    assert set(got) == {ids["top"], ids["archived"]}
    s = got[ids["top"]]
    assert s["name"] == "brave-otter" and s["name_resumable"] is False
    assert s["resume"] == f"cd /work/delta && opencode --session {ids['top']}"
    assert s["transcript"] is None
    assert s["export_command"] == f"opencode export {ids['top']}"
    assert got[ids["archived"]]["archived"] is True
    assert doc["census"]["opencode"]["hidden_subagents"] == 1


# Newer OpenCode releases write to `session_v2`, which keeps every `session` row;
# the old table stops receiving new ones.
OPENCODE_V2_SCHEMA = """CREATE TABLE session_v2 (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT, parent_id TEXT, slug TEXT NOT NULL,
  directory TEXT NOT NULL, title TEXT, version TEXT NOT NULL,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, time_archived INTEGER, time_idle INTEGER)"""


def test_opencode_session_v2_rows_are_listed(home):
    ids, data = build_opencode(home)
    ms = lambda t: int(t * 1000)  # noqa: E731
    new, new_child = "ses_new0000000000000000000", "ses_newkid000000000000000"
    untitled = "ses_untitled00000000000000"
    db = sqlite3.connect(data / "opencode.db")
    db.execute(OPENCODE_V2_SCHEMA)
    db.execute(
        "INSERT INTO session_v2 (id, project_id, parent_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived)"
        " SELECT id, project_id, parent_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived FROM session"
    )
    for sid, parent, slug in ((new, None, "swift-hawk"), (new_child, new, "tiny-wren")):
        db.execute(
            "INSERT INTO session_v2 (id, project_id, parent_id, slug, directory, title, version,"
            " time_created, time_updated) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                sid,
                "p1",
                parent,
                slug,
                "/work/echo",
                f"title {slug}",
                "2",
                ms(NOW - 2 * HOUR),
                ms(NOW - HOUR),
            ),
        )
    # session_v2.title is nullable; 6 of 17 rows on the reporting machine had none.
    db.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            untitled,
            "p1",
            "bare-moth",
            "/work/echo",
            None,
            "2",
            ms(NOW - 2 * HOUR),
            ms(NOW - HOUR),
        ),
    )
    db.commit()
    db.close()

    doc = inventory(home, "--tool", "opencode")
    got = by_id(doc)
    assert set(got) == {ids["top"], ids["archived"], new, untitled}
    assert got[untitled]["title"] is None and got[untitled]["name"] == "bare-moth"
    s = got[new]
    assert s["name"] == "swift-hawk" and s["title"] == "title swift-hawk"
    assert s["spawn_dir"] == "/work/echo"
    assert s["resume"] == f"cd /work/echo && opencode --session {new}"
    assert got[ids["archived"]]["archived"] is True
    assert doc["census"]["opencode"]["hidden_subagents"] == 2


def test_opencode_legacy_only_rows_are_listed_without_commands(home):
    # OpenCode stops importing `session` into `session_v2` once its migration is marked done, so a row
    # written to the old table afterwards exists only there. List it, but offer no v2 command for it.
    ids, data = build_opencode(home)
    ms = lambda t: int(t * 1000)  # noqa: E731
    new = "ses_new0000000000000000000"
    db = sqlite3.connect(data / "opencode.db")
    db.execute(OPENCODE_V2_SCHEMA)
    db.execute(
        "INSERT INTO session_v2 (id, project_id, parent_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived)"
        " SELECT id, project_id, parent_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived FROM session WHERE id = ?",
        (ids["top"],),
    )
    db.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            new,
            "p1",
            "swift-hawk",
            "/work/echo",
            "t",
            "2",
            ms(NOW - 2 * HOUR),
            ms(NOW - HOUR),
        ),
    )
    db.commit()
    db.close()

    doc = inventory(home, "--tool", "opencode")
    got = by_id(doc)
    assert set(got) == {
        ids["top"],
        ids["archived"],
        new,
    }  # the legacy-only child stays hidden
    legacy = got[ids["archived"]]
    assert legacy["resume"] is None and legacy["resume_blocked"] == "legacy_only"
    assert legacy["export_command"] is None
    assert got[new]["resume"] == f"cd /work/echo && opencode --session {new}"
    assert got[ids["top"]]["resume_blocked"] is None
    assert doc["sources"]["opencode"]["legacy_only"] == 2  # archived + the hidden child
    assert doc["census"]["opencode"]["hidden_subagents"] == 1


def test_opencode_v2_fork_keeps_its_lineage_and_stays_listed(home):
    ids, data = build_opencode(home)
    ms = lambda t: int(t * 1000)  # noqa: E731
    fork = "ses_fork000000000000000000"
    db = sqlite3.connect(data / "opencode.db")
    db.execute(
        OPENCODE_V2_SCHEMA.replace(
            "parent_id TEXT,", "parent_id TEXT, fork_session_id TEXT,"
        )
    )
    db.execute(
        "INSERT INTO session_v2 (id, project_id, parent_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived)"
        " SELECT id, project_id, parent_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived FROM session"
    )
    db.execute(
        "INSERT INTO session_v2 (id, project_id, fork_session_id, slug, directory, title, version,"
        " time_created, time_updated) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            fork,
            "p1",
            ids["top"],
            "keen-lark",
            "/work/delta",
            "forked",
            "2",
            ms(NOW - 2 * HOUR),
            ms(NOW - HOUR),
        ),
    )
    db.commit()
    db.close()

    doc = inventory(home, "--tool", "opencode")
    got = by_id(doc)
    assert got[fork]["lineage"] == {"kind": "fork", "parent_id": ids["top"]}
    assert got[fork]["resume"] == f"cd /work/delta && opencode --session {fork}"
    assert got[ids["top"]]["lineage"] is None
    assert doc["census"]["opencode"]["hidden_subagents"] == 1
    assert doc["sources"]["opencode"]["legacy_only"] == 0


# --- filters --------------------------------------------------------------------


def test_tool_filter_is_repeatable(home, world):
    doc = inventory(home, "--tool", "muse", "--tool", "opencode")
    assert {s["tool"] for s in doc["sessions"]} == {"muse", "opencode"}
    assert set(doc["census"]) == {"muse", "opencode"}


def test_since_filters_on_last_activity(home, world):
    doc = inventory(home, "--since", "3h")
    got = by_id(doc)
    assert world["claude"]["renamed"] in got  # 1h ago
    assert world["claude"]["plain"] not in got  # 48h ago
    assert world["muse"]["stale"] not in got  # 30h ago


def test_sort_is_newest_first_and_deterministic(home, world):
    doc = inventory(home)
    keys = [(s["updated"], s["tool"], s["id"]) for s in doc["sessions"]]
    # ISO-8601 Z strings sort lexically; stable sort gives updated desc, then tool, then id
    expected = sorted(
        sorted(keys, key=lambda k: (k[1], k[2])), key=lambda k: k[0], reverse=True
    )
    assert keys == expected


# --- liveness -------------------------------------------------------------------


def test_nothing_running_means_live_no(home, world):
    doc = inventory(home)
    assert {s["live"] for s in doc["sessions"]} <= {"no", "unknown"}
    assert inventory(home, "--live")["sessions"] == []


def test_claude_registry_live_and_blocks_resume(home, world, procs):
    p = procs(["sleep", "60"])
    sid = world["claude"]["renamed"]
    reg = home / ".claude" / "sessions"
    reg.mkdir(parents=True)
    (reg / f"{p.pid}.json").write_text(
        json.dumps(
            {
                "pid": p.pid,
                "procStart": utc_lstart(p.pid),
                "sessionId": sid,
                "cwd": "/work/alpha",
                "status": "busy",
                "name": "alpha-7e",
                "tmux": "main:@1.%1",
            }
        )
    )
    s = by_id(inventory(home, "--live"))[sid]
    assert s["live"] == "yes" and s["pid"] == p.pid and s["tmux"] == "main:@1.%1"
    assert s["resume"] is None and s["resume_blocked"] == "running"


def test_claude_reused_pid_is_not_live(home, world, procs):
    p = procs(["sleep", "60"])
    sid = world["claude"]["renamed"]
    reg = home / ".claude" / "sessions"
    reg.mkdir(parents=True)
    (reg / f"{p.pid}.json").write_text(
        json.dumps(
            {"pid": p.pid, "procStart": "Mon Jan  1 00:00:00 2024", "sessionId": sid}
        )
    )
    s = by_id(inventory(home))[sid]
    assert s["live"] == "no" and s["resume"] is not None


def test_codex_held_lock_is_live(home, world, procs):
    ids = world["codex"]
    lock = home / ".codex" / "thread-writer-locks" / f"{ids['user']}.lock"
    procs([str(fake_tool(home / "bin", "codex")), str(lock)])
    got = by_id(inventory(home, "--tool", "codex"))
    assert got[ids["user"]]["live"] == "yes"
    assert got[ids["user"]]["live_host"] == "cli"
    assert got[ids["fork"]]["live"] == "no"  # lock file exists but nobody holds it


def test_codex_lock_held_by_app_server_is_labeled(home, world, procs):
    ids = world["codex"]
    lock = home / ".codex" / "thread-writer-locks" / f"{ids['user']}.lock"
    procs([str(fake_tool(home / "bin", "codex")), "app-server", str(lock)])
    s = by_id(inventory(home, "--tool", "codex"))[ids["user"]]
    assert s["live"] == "yes" and s["live_host"] == "app-server"
    assert s["resume"] is None and s["resume_blocked"] == "running"


def test_muse_lock_with_live_muse_process_is_live(home, world, procs):
    ids = world["muse"]
    p = procs([str(fake_tool(home / "bin", "muse"))])
    lock = next(
        (home / ".local/share/muse/sessions").rglob(f"{ids['named']}/.session.lock")
    )
    lock.write_text(f"pid={p.pid}\nhost={socket.gethostname()}\n")
    got = by_id(inventory(home, "--tool", "muse"))
    assert got[ids["named"]]["live"] == "yes"
    assert got[ids["stale"]]["live"] == "no"  # stale lock, dead pid


def test_muse_versioned_binary_counts_as_muse(home, world, procs):
    # the `muse` launcher runs a versioned binary, e.g. muse-bin-1.3.0-R3401.1
    ids = world["muse"]
    p = procs(
        [
            str(fake_tool(home / "bin", "muse-bin-1.3.0-R3401.1")),
            "resume",
            "copper-umbra",
        ]
    )
    lock = next(
        (home / ".local/share/muse/sessions").rglob(f"{ids['named']}/.session.lock")
    )
    lock.write_text(f"pid={p.pid}\nhost={socket.gethostname()}\n")
    assert by_id(inventory(home, "--tool", "muse"))[ids["named"]]["live"] == "yes"


def test_muse_lock_pid_owned_by_other_program_is_not_live(home, world, procs):
    ids = world["muse"]
    p = procs(["sleep", "60"])  # alive, but not muse
    lock = next(
        (home / ".local/share/muse/sessions").rglob(f"{ids['named']}/.session.lock")
    )
    lock.write_text(f"pid={p.pid}\nhost={socket.gethostname()}\n")
    assert by_id(inventory(home, "--tool", "muse"))[ids["named"]]["live"] == "no"


def test_muse_lock_from_other_host_is_unknown(home, world):
    ids = world["muse"]
    lock = next(
        (home / ".local/share/muse/sessions").rglob(f"{ids['named']}/.session.lock")
    )
    lock.write_text("pid=1\nhost=some-other-machine\n")
    assert by_id(inventory(home, "--tool", "muse"))[ids["named"]]["live"] == "unknown"


def test_opencode_process_with_session_arg_is_live(home, world, procs):
    ids = world["opencode"]
    procs([str(fake_tool(home / "bin", "opencode")), "--session", ids["top"]])
    assert by_id(inventory(home, "--tool", "opencode"))[ids["top"]]["live"] == "yes"


def test_opencode_process_in_directory_surfaces_a_signal(home, world, procs, tmp_path):
    # policy-agnostic: whatever opencode_directory_liveness decides, a bare
    # `opencode` running in the directory must not leave the newest session "no"
    ids = world["opencode"]
    workdir = tmp_path / "delta"
    workdir.mkdir()
    db = sqlite3.connect(home / ".local/share/opencode/opencode.db")
    db.execute("UPDATE session SET directory = ?", (str(workdir.resolve()),))
    db.commit()
    db.close()
    procs([str(fake_tool(home / "bin", "opencode"))], cwd=workdir)
    got = by_id(inventory(home, "--tool", "opencode"))
    s = got[ids["top"]]
    assert s["live"] != "no" and "opencode pid" in s["live_basis"]


def test_opencode_directory_fallback_marks_only_newest_unknown(
    home, world, procs, tmp_path
):
    # owner decision (PR #86): without --session, only the newest top-level
    # session in the process's directory is `unknown`; older ones stay `no`
    ids = world["opencode"]
    workdir = tmp_path / "delta"
    workdir.mkdir()
    db = sqlite3.connect(home / ".local/share/opencode/opencode.db")
    db.execute("UPDATE session SET directory = ?", (str(workdir.resolve()),))
    db.commit()
    db.close()
    procs([str(fake_tool(home / "bin", "opencode"))], cwd=workdir)
    got = by_id(inventory(home, "--tool", "opencode"))
    assert got[ids["top"]]["live"] == "unknown"
    assert got[ids["top"]]["resume"] is not None  # unknown never blocks resume
    assert got[ids["archived"]]["live"] == "no"
    # --live keeps possibly-running sessions (PR #86 review, thread 4114456485)
    live_ids = set(by_id(inventory(home, "--tool", "opencode", "--live")))
    assert live_ids == {ids["top"]}


# --- text output ----------------------------------------------------------------


def test_text_output_lines_and_census(home, world):
    r = run(home, "inventory", "--tool", "muse")
    assert r.returncode == 0
    lines = r.stdout.strip().splitlines()
    assert any(
        line.startswith("muse\t" + world["muse"]["named"]) and "copper-umbra" in line
        for line in lines
    )
    assert any(line.startswith("# census muse") for line in lines)


# --- library API (design 0006, Q-H) ------------------------------------------------


def test_collect_is_the_stable_library_api(home, world, monkeypatch):
    from lost_sessions.inventory import collect, select
    from lost_sessions.models import Inventory

    monkeypatch.setenv("HOME", str(home))
    for var in ("CODEX_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    inv = collect(["muse", "claude"], home=home)
    assert isinstance(inv, Inventory)
    assert list(inv.census) == ["muse", "claude"]
    assert inv.failed == []
    ids = {s.id for s in select(inv)}
    assert world["muse"]["named"] in ids and world["claude"]["renamed"] in ids


# --- malformed stores never crash (design 0006, Section 8.1 rule 8) ---------------


def test_wrong_typed_fields_mark_the_session_unreadable(home, world):
    # A numeric cwd (Claude), a null id (Codex), and text in integer timestamp
    # columns (Muse, OpenCode; SQLite keeps non-numeric text as text): stores
    # that changed shape must not crash the scan.
    bad_claude = "44444444-4444-4444-8444-444444444444"
    write_jsonl(
        home / ".claude" / "projects" / "-work-alpha" / f"{bad_claude}.jsonl",
        [
            {
                "type": "user",
                "timestamp": iso(NOW - HOUR),
                "cwd": 123,
                "sessionId": bad_claude,
            },
        ],
    )
    bad_codex = "0f000000-0000-7000-8000-00000000000f"
    write_jsonl(
        home
        / ".codex/sessions/2026/09/20"
        / f"rollout-2026-09-20T15-00-00-{bad_codex}.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {"id": None, "timestamp": iso(NOW), "cwd": "/w"},
            }
        ],
    )
    db = sqlite3.connect(home / ".local/share/muse/session-index.db")
    db.execute(
        "UPDATE sessions SET created_at_us = 'soon' WHERE session_id = ?",
        (world["muse"]["stale"],),
    )
    db.commit()
    db.close()
    db = sqlite3.connect(home / ".local/share/opencode/opencode.db")
    db.execute(
        "UPDATE session SET time_updated = 'later' WHERE id = ?",
        (world["opencode"]["archived"],),
    )
    db.commit()
    db.close()
    doc = inventory(home)
    got = by_id(doc)
    assert got[bad_claude]["unreadable"] is True
    assert got[bad_codex]["unreadable"] is True
    assert got[world["muse"]["stale"]]["unreadable"] is True
    assert got[world["opencode"]["archived"]]["unreadable"] is True
    assert got[world["muse"]["named"]]["unreadable"] is False  # neighbours unaffected
    assert {v["status"] for v in doc["sources"].values()} == {"ok"}


def test_collect_reads_every_store_under_the_given_home(
    home, world, monkeypatch, tmp_path
):
    from lost_sessions.inventory import collect

    elsewhere = tmp_path / "not-home"
    elsewhere.mkdir()
    monkeypatch.setenv("HOME", str(elsewhere))
    for var in ("CODEX_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    inv = collect(home=home)
    assert {v.status for v in inv.sources.values()} == {"ok"}
    assert {s.tool for s in inv.sessions} == {"claude", "codex", "muse", "opencode"}


def test_claude_lines_that_are_not_objects_are_skipped(home, world):
    sid = "55555555-5555-4555-8555-555555555555"
    path = home / ".claude" / "projects" / "-work-alpha" / f"{sid}.jsonl"
    path.write_text(
        "[]\nnull\n"
        + json.dumps(
            {
                "type": "user",
                "timestamp": iso(NOW - HOUR),
                "cwd": "/work/alpha",
                "sessionId": sid,
            }
        )
        + "\n"
    )
    s = by_id(inventory(home, "--tool", "claude"))[sid]
    assert s["unreadable"] is False and s["spawn_dir"] == "/work/alpha"


def test_missing_process_table_fails_only_the_agents_that_need_it(
    home, world, monkeypatch
):
    import lost_sessions.inventory as inventory_module
    from lost_sessions.inventory import collect

    def no_ps():
        raise FileNotFoundError("ps")

    monkeypatch.setattr(inventory_module, "processes", no_ps)
    monkeypatch.setenv("HOME", str(home))
    for var in ("CODEX_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    inv = collect(home=home)
    assert inv.failed == ["codex", "muse", "opencode"]
    assert inv.sources["claude"].status == "ok"
    assert {s.tool for s in inv.sessions} == {"claude"}
    assert "process table" in inv.sources["muse"].message
