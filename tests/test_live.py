"""Live test for the Herdr path (design 0006, TS-10). Not part of the default run.

Runs only with LOST_SESSIONS_LIVE=1 and `pytest -m live tests/test_live.py`. It
starts a throwaway named Herdr server, creates throwaway Codex and Muse sessions
(two tiny model calls), opens both through the Herdr plugin, checks that Herdr
saved them, restarts the server, and checks that Muse is resumed. The server is
stopped and deleted afterwards; the user's default Herdr session and Rex are
never touched.

Ported from smorin/smorin-bootstrap tests/test_lost_sessions_live.py at 713e443.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from lost_sessions import core
from lost_sessions.default_plugins.herdr import HerdrDestination
from lost_sessions.inventory import collect, parse_since, select
from lost_sessions.models import Session
from lost_sessions.plugins import load_plugins, pm

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("LOST_SESSIONS_LIVE") != "1",
        reason="set LOST_SESSIONS_LIVE=1 to run",
    ),
]

# Unique per run, so the test never stops or deletes a Herdr session it did not create.
NAME = f"lost-sessions-live-{os.getpid()}-{int(time.time())}"
LAYOUT = Path.home() / ".config/herdr/sessions" / NAME / "session.json"


def herdr(*args, check=True):
    return subprocess.run(
        ["herdr", "--session", NAME, *args], capture_output=True, text=True, check=check
    )


def session_exists():
    out = herdr("session", "list", check=False).stdout
    return any(line.split()[:1] == [NAME] for line in out.splitlines())


def wait_for(predicate, timeout=60, step=1.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return False


def start_server():
    proc = subprocess.Popen(
        ["herdr", "--session", NAME, "server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_for(
        lambda: herdr("workspace", "list", check=False).returncode == 0, timeout=20
    ):
        proc.kill()
        proc.wait(timeout=10)
        raise AssertionError("server did not start")
    return proc


def stop_server(proc):
    herdr("server", "stop", check=False)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_codex_and_muse_are_saved_and_muse_resumes_after_restart():
    assert not session_exists(), (
        f"Herdr session {NAME} already exists; refusing to touch it"
    )
    load_plugins(pm)
    # The folder prefix makes lost-sessions treat these throwaway sessions as helper runs.
    work = Path(tempfile.mkdtemp(prefix="lost-sessions-live-"))
    codex_out = subprocess.run(
        [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-c",
            'model_reasoning_effort="low"',
            "--json",
            "Reply with exactly: OK",
        ],
        cwd=work,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    codex_id = next(
        json.loads(line)["thread_id"]
        for line in codex_out.splitlines()
        if line.startswith("{") and json.loads(line).get("type") == "thread.started"
    )
    subprocess.run(
        ["muse", "exec", "--reasoning-effort", "low", "Reply with exactly: OK"],
        cwd=work,
        capture_output=True,
        text=True,
        check=True,
    )
    inv = collect(["muse"])
    muse_id = next(
        s.id
        for s in select(inv, since=parse_since("30m"))
        if s.spawn_dir in (str(work.resolve()), str(work))
    )
    rows = [
        core.Row(
            n=1,
            session=Session(
                tool="codex",
                id=codex_id,
                title="live codex",
                spawn_dir=str(work),
                resume=f"codex resume {codex_id}",
            ),
        ),
        core.Row(
            n=2,
            session=Session(
                tool="muse",
                id=muse_id,
                title="live muse",
                spawn_dir=str(work),
                resume=f"cd {work} && muse resume {muse_id}",
            ),
        ),
    ]
    herdr_manager = core.session_managers()["herdr"]
    proc = start_server()
    try:
        target = HerdrDestination(manager="herdr", label="recovered", session=NAME)
        codex_entry = core.execute(rows[0], herdr_manager, target)
        muse_entry = core.execute(rows[1], herdr_manager, target)
        assert codex_entry.result == "ok", codex_entry
        assert muse_entry.result in ("ok", "blocked"), (
            muse_entry
        )  # a fresh folder asks for trust

        def saved():
            try:
                text = LAYOUT.read_text()
            except OSError:
                return False
            return codex_id in text and muse_id in text

        assert wait_for(saved), "Herdr did not save both sessions"
        layout = json.loads(LAYOUT.read_text())
        panes = [
            p
            for ws in layout["workspaces"]
            for t in ws["tabs"]
            for p in t["panes"].values()
        ]
        assert ["muse", "resume", muse_id] in [
            (p.get("agent_resume") or {}).get("argv") for p in panes
        ]

        stop_server(proc)
        proc = start_server()
        pane = (muse_entry.opened or {})["herdr_pane"]
        assert wait_for(
            lambda: (
                f"muse resume {muse_id}"
                in herdr("pane", "read", pane, "--source", "recent", check=False).stdout
            ),
            timeout=30,
        ), "Muse was not resumed after the restart"
    finally:
        stop_server(proc)
        subprocess.run(
            ["herdr", "session", "delete", NAME], capture_output=True, check=False
        )
