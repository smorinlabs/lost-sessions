"""`inventory --json` matches `session-inventory list --json` (design 0006, TS-6).

The oracle is the pinned `session-inventory` script from
smorinlabs/smorinlabs-skills at cf83bf1, vendored in tests/oracle/. Both run
against the same fixture stores under a fake HOME; their JSON must be equal,
field for field and in the same order.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_inventory import build_claude, build_codex, build_muse, build_opencode

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the oracle and the scanners need POSIX tools"
)


ORACLE = Path(__file__).resolve().parent / "oracle" / "session-inventory"


def _env(home):
    env = {
        k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "XDG_DATA_HOME")
    }
    env.update({"HOME": str(home), "LOST_SESSIONS_LOAD_PLUGINS": ""})
    return env


def _run(argv, home):
    r = subprocess.run(argv, capture_output=True, text=True, env=_env(home), timeout=60)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture()
def world(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    build_claude(home)
    build_codex(home)
    build_muse(home)
    build_opencode(home)
    return home


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--include-subagents"],
        ["--tool", "codex", "--tool", "claude"],
        ["--since", "3h"],
        ["--live"],
    ],
    ids=["all", "subagents", "tool-order", "since", "live"],
)
def test_json_matches_the_oracle(world, args):
    old = _run([sys.executable, str(ORACLE), "list", "--json", *args], world)
    new = _run(
        [sys.executable, "-m", "lost_sessions", "inventory", "--json", *args], world
    )
    assert new[0] == old[0]
    assert json.loads(new[1]) == json.loads(old[1])
    assert list(json.loads(new[1])) == list(json.loads(old[1]))
    assert new[1] == old[1]


def test_text_output_matches_the_oracle(world):
    old = _run([sys.executable, str(ORACLE), "list"], world)
    new = _run([sys.executable, "-m", "lost_sessions", "inventory"], world)
    assert new == old


def test_partial_failure_matches_the_oracle(world):
    import sqlite3

    db = sqlite3.connect(world / ".local/share/muse/session-index.db")
    db.execute("ALTER TABLE sessions RENAME COLUMN workspace_root TO ws")
    db.commit()
    db.close()
    old = _run([sys.executable, str(ORACLE), "list", "--json"], world)
    new = _run([sys.executable, "-m", "lost_sessions", "inventory", "--json"], world)
    assert new == old
