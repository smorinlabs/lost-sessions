"""`list`, `open --print` and `history` match the original script (design 0006, Section 8).

The oracle is the pinned `lost-sessions` script from smorin/smorin-bootstrap at
713e443, vendored in tests/oracle/. It reads sessions from a fake
`session-inventory` on PATH; the new CLI reads the same sessions from a fake
agent plugin. Stdout, exit codes and history lines must match, except for the
decided additions: `schema` and `written_by` on new lines (Section 8.1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.test_core import (  # noqa: F401 - fixture
    CLAUDE_ID,
    CODEX_ID,
    MUSE_ID,
    cli_env,
    run,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="the pinned script reads the boot time with sysctl"
)

ORACLE = Path(__file__).resolve().parent / "oracle" / "lost-sessions"
FAKE_INVENTORY = textwrap.dedent(
    f"""\
    #!{sys.executable}
    import os, sys
    print(open(os.environ["FAKE_INVENTORY_JSON"]).read())
    """
)


@pytest.fixture
def both(cli_env, tmp_path):
    """The oracle's PATH, HOME and state are separate from the new CLI's."""
    tmp = cli_env["tmp"]
    bindir = tmp_path / "oracle-bin"
    bindir.mkdir()
    (bindir / "session-inventory").write_text(FAKE_INVENTORY)
    (bindir / "session-inventory").chmod(0o755)
    inv = tmp_path / "inventory.json"
    sessions = [s.model_dump(mode="json") for s in cli_env["agent"].sessions]
    inv.write_text(json.dumps({"sessions": sessions}))
    home = tmp_path / "oracle-home"
    home.mkdir()
    env = {
        "PATH": f"{bindir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "XDG_STATE_HOME": str(tmp_path / "oracle-state"),
        "FAKE_INVENTORY_JSON": str(inv),
    }

    def oracle(*argv, extra_env=None):
        run_env = env | (extra_env or {})
        if extra_env:  # managers: put the fakes' directory before the oracle's bin
            run_env["PATH"] = os.environ["PATH"].replace(
                "/usr/bin:/bin", f"{bindir}:/usr/bin:/bin", 1
            )
        r = subprocess.run(
            [sys.executable, str(ORACLE), *argv],
            capture_output=True,
            text=True,
            env=run_env,
            timeout=60,
        )
        return r.returncode, r.stdout, r.stderr

    def oracle_log():
        p = tmp_path / "oracle-state" / "lost-sessions" / "history.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()]

    def new_log():
        p = tmp / "state" / "lost-sessions" / "history.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()]

    return oracle, oracle_log, new_log, tmp_path


SINCE = ("--since", "2000-01-01")


@pytest.mark.parametrize(
    "argv",
    [
        ["list", *SINCE],
        ["list", *SINCE, "--all"],
        ["list", *SINCE, "--include-helpers", "--hide-running"],
    ],
    ids=["list", "all", "helpers"],
)
def test_list_matches(both, argv):
    oracle, *_ = both
    old = oracle(*argv)
    new = run(*argv)
    assert new[0] == old[0]
    assert new[1] == old[1]


def _without_stamps(entries):
    return [
        {k: v for k, v in e.items() if k not in ("schema", "written_by", "time")}
        for e in entries
    ]


def test_open_print_and_history_match(both):
    oracle, oracle_log, new_log, tmp = both
    argv = ["open", CLAUDE_ID[:8], CODEX_ID, MUSE_ID, "gone-1", "--print", *SINCE]
    old = oracle(*argv)
    new = run(*argv)
    assert new[0] == old[0]

    def comparable(out, state):
        # Drop the timestamped header line of each entry; name the state dir once.
        out = out.replace(str(state), "<STATE>")
        return [line for line in out.splitlines() if not line.startswith("20")]

    assert comparable(new[1], tmp / "state") == comparable(old[1], tmp / "oracle-state")
    assert _without_stamps(new_log()) == _without_stamps(oracle_log())
    assert all(e["schema"] == 1 for e in new_log())
    assert list(new_log()[0])[:10] == list(oracle_log()[0])


def test_numbered_open_uses_the_listing_like_the_oracle(both):
    oracle, oracle_log, new_log, _ = both
    oracle("list", *SINCE)
    run("list", *SINCE)
    old = oracle("open", "2", "--print")
    new = run("open", "2", "--print")
    assert new[0] == old[0] == 0
    assert _without_stamps(new_log()) == _without_stamps(oracle_log())


def test_usage_errors_match(both):
    oracle, *_ = both
    for argv in (["list", "--since", "soon"], ["open", "99", "--print", *SINCE]):
        assert run(*argv)[0] == oracle(*argv)[0] == 2


# --- session managers: open --herdr/--rex, workspaces, --focus (PR 3b) ------------------


@pytest.fixture
def both_with_managers(both, monkeypatch, tmp_path):
    """Fake herdr and rex for both: each logs the commands it receives."""
    from tests.test_managers import FAKE_HERDR, FAKE_REX, SYSTEM_PATH, write_exe

    oracle, oracle_log, new_log, tmp = both
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    write_exe(bindir / "herdr", FAKE_HERDR)
    write_exe(bindir / "rex", FAKE_REX)
    oracle_calls = tmp_path / "oracle-calls.jsonl"
    new_calls = tmp_path / "new-calls.jsonl"
    oracle_calls.touch()
    new_calls.touch()
    monkeypatch.setenv("PATH", f"{bindir}:{SYSTEM_PATH}")
    monkeypatch.setenv("FAKE_LOG", str(new_calls))
    monkeypatch.setenv("REX_SESSION", "session:cur")
    oracle_bin = tmp_path / "oracle-bin"
    for name in ("herdr", "rex"):
        (oracle_bin / name).symlink_to(bindir / name)

    def run_oracle(*argv, extra=None):
        env = {
            "FAKE_LOG": str(oracle_calls),
            "REX_SESSION": "session:cur",
            **(extra or {}),
        }
        return oracle(*argv, extra_env=env)

    def calls(path):
        got = [json.loads(line) for line in path.read_text().splitlines()]
        return [c for c in got if "list" not in c[1:3]]

    return {
        "oracle": run_oracle,
        "oracle_log": oracle_log,
        "new_log": new_log,
        "tmp": tmp,
        "oracle_calls": lambda: calls(oracle_calls),
        "new_calls": lambda: calls(new_calls),
    }


def _same_stdout(new, old, tmp):
    def norm(out, state):
        out = out.replace(str(state), "<STATE>")
        return [line for line in out.splitlines() if not line.startswith("20")]

    assert norm(new, tmp / "state") == norm(old, tmp / "oracle-state")


@pytest.mark.parametrize(
    "argv",
    [
        ["open", CLAUDE_ID, CODEX_ID, MUSE_ID, "--herdr"],
        [
            "open",
            f"{CLAUDE_ID}@existing",
            f"{CODEX_ID}@brand-new",
            "--herdr",
            "--focus",
        ],
        ["open", CLAUDE_ID, "--rex"],
        [
            "open",
            CLAUDE_ID,
            f"{CODEX_ID}@current",
            "--rex",
            "--rex-session",
            "other",
            "--focus",
        ],
        ["open", "running-1", "maybe-1", "gone-1", "--rex", "--all"],
        ["open", f"{CLAUDE_ID}@dup", "--herdr"],
        [
            "open",
            CLAUDE_ID,
            "--herdr",
            "--herdr-session",
            "t",
            "--workspace",
            "existing",
        ],
    ],
    ids=[
        "herdr",
        "herdr-dests-focus",
        "rex",
        "rex-current-focus",
        "refusals",
        "ambiguous",
        "herdr-named-session",
    ],
)
def test_open_in_a_manager_matches(both_with_managers, argv):
    b = both_with_managers
    old = b["oracle"](*argv, *SINCE)
    new = run(*argv, *SINCE)
    assert new[0] == old[0]
    _same_stdout(new[1], old[1], b["tmp"])
    assert b["new_calls"]() == b["oracle_calls"]()
    if (b["tmp"] / "oracle-state" / "lost-sessions" / "history.jsonl").exists():
        assert _without_stamps(b["new_log"]()) == _without_stamps(b["oracle_log"]())


def test_workspaces_matches(both_with_managers):
    b = both_with_managers
    old = b["oracle"]("workspaces")
    new = run("workspaces")
    assert new[0] == old[0] == 0
    assert new[1] == old[1]


def test_blocked_and_failed_match(both_with_managers, monkeypatch):
    b = both_with_managers
    monkeypatch.setenv("FAKE_BLOCK", "muse")
    old = b["oracle"]("open", MUSE_ID, "--herdr", *SINCE, extra={"FAKE_BLOCK": "muse"})
    new = run("open", MUSE_ID, "--herdr", *SINCE)
    assert new[0] == old[0]
    assert _without_stamps(b["new_log"]()) == _without_stamps(b["oracle_log"]())


def test_the_manager_comparisons_are_not_vacuous(both_with_managers):
    b = both_with_managers
    b["oracle"]("open", CLAUDE_ID, "--herdr", *SINCE)
    run("open", CLAUDE_ID, "--herdr", *SINCE)
    verbs = [c[1:3] for c in b["oracle_calls"]()]
    assert ["workspace", "create"] in verbs and ["agent", "start"] in verbs
    assert b["new_calls"]() == b["oracle_calls"]()
