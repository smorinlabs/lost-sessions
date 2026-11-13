"""`plugins`, `install` and `uninstall` (design 0006, Sections 7.2 and 7.4)."""

from __future__ import annotations

import json
import shlex
import sys
import types
from unittest import mock

import pytest

from lost_sessions import installer
from tests.test_core import cli_env, run  # noqa: F401 - cli_env is a fixture


def dist(name, version="1.0", direct_url=None, plugin=True):
    eps = (
        [types.SimpleNamespace(group="lost_sessions", name=name.split("-")[-1])]
        if plugin
        else []
    )

    def read_text(filename):
        if filename == "direct_url.json" and direct_url is not None:
            return json.dumps(direct_url)
        return None

    return types.SimpleNamespace(
        metadata={"Name": name}, version=version, entry_points=eps, read_text=read_text
    )


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A fake environment: lost-sessions plus two installed plugins."""
    dists = [
        dist("lost-sessions", "0.1.0", plugin=False),
        dist("lost-sessions-alpha"),
        dist(
            "lost-sessions-beta",
            direct_url={
                "url": "file:///w/beta-1.0-py3-none-any.whl",
                "archive_info": {},
            },
        ),
        dist("click", "8.5.0", plugin=False),
    ]
    monkeypatch.setattr(installer.metadata, "distributions", lambda: dists)
    monkeypatch.setattr(
        installer.metadata,
        "distribution",
        lambda name: next(d for d in dists if d.metadata["Name"] == name),
    )
    monkeypatch.setattr(installer.sys, "prefix", str(tmp_path))
    return {"prefix": tmp_path, "dists": dists}


def uv_tool(env):
    (env["prefix"] / "uv-receipt.toml").write_text("[tool]\n")


# --- discovery and requirement specs ----------------------------------------------


def test_installed_plugins_are_the_distributions_with_our_entry_point(env):
    assert [installer.name_of(d) for d in installer.installed_plugins()] == [
        "lost-sessions-alpha",
        "lost-sessions-beta",
    ]


@pytest.mark.parametrize(
    ("direct_url", "version", "expected"),
    [
        (None, "1.0", ["--with", "lost-sessions-x"]),
        (None, "2.0rc1", ["--with", "lost-sessions-x==2.0rc1"]),  # keep a pre-release
        (
            {"url": "file:///w/x.whl", "archive_info": {}},
            "1.0",
            ["--with", "lost-sessions-x @ file:///w/x.whl"],
        ),
        (
            {
                "url": "https://github.com/o/x",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
            },
            "1.0",
            ["--with", "lost-sessions-x @ git+https://github.com/o/x@abc123"],
        ),
        (
            {"url": "file:///w/x", "dir_info": {"editable": True}},
            "1.0",
            ["--with-editable", "/w/x"],
        ),
    ],
    ids=["pypi", "pre-release", "local-wheel", "git", "editable"],
)
def test_requirements_keep_where_a_plugin_came_from(direct_url, version, expected):
    assert installer.with_args(dist("lost-sessions-x", version, direct_url)) == expected


def test_the_tool_itself_keeps_its_source_too():
    editable = dist(
        "lost-sessions",
        "0.1.0",
        {"url": "file:///src/ls", "dir_info": {"editable": True}},
        plugin=False,
    )
    assert installer.tool_args(editable) == ["--editable", "/src/ls"]
    assert installer.tool_args(dist("lost-sessions", "0.1.0", plugin=False)) == [
        "lost-sessions"
    ]


# --- install / uninstall -------------------------------------------------------------


def test_install_print_shows_both_lines_and_which_applies(env, cli_env):
    code, out, _ = run("install", "lost-sessions-gamma", "--print")
    assert code == 0
    assert (
        "uv tool install lost-sessions --with lost-sessions-alpha --with "
        "'lost-sessions-beta @ file:///w/beta-1.0-py3-none-any.whl' "
        "--with lost-sessions-gamma"
    ) in out
    assert (
        shlex.join([sys.executable, "-m", "pip", "install", "lost-sessions-gamma"])
        in out
    )
    assert "applies here: pip" in out


def test_install_outside_a_uv_tool_runs_nothing_and_exits_one(env, cli_env):
    with mock.patch.object(installer.subprocess, "run") as ran:
        code, _, err = run("install", "lost-sessions-gamma")
    assert code == 1
    ran.assert_not_called()
    assert "nothing was run" in err


def test_install_in_a_uv_tool_runs_the_uv_line(env, cli_env):
    uv_tool(env)
    with (
        mock.patch.object(
            installer.subprocess,
            "run",
            return_value=types.SimpleNamespace(returncode=0),
        ) as ran,
        mock.patch.object(installer.shutil, "which", return_value="/bin/uv"),
    ):
        code, out, err = run("install", "lost-sessions-gamma")
    assert code == 0
    argv = ran.call_args.args[0]
    assert argv[:4] == ["/bin/uv", "tool", "install", "lost-sessions"]
    assert argv[4:] == [
        "--with",
        "lost-sessions-alpha",
        "--with",
        "lost-sessions-beta @ file:///w/beta-1.0-py3-none-any.whl",
        "--with",
        "lost-sessions-gamma",
    ]
    assert "applies here: uv" in out
    assert "--with" in err  # the warning about non-plugin add-ons and pins


def test_uninstall_drops_the_plugin_from_the_uv_line(env, cli_env):
    uv_tool(env)
    with (
        mock.patch.object(
            installer.subprocess,
            "run",
            return_value=types.SimpleNamespace(returncode=0),
        ) as ran,
        mock.patch.object(installer.shutil, "which", return_value="/bin/uv"),
    ):
        code, _, _ = run("uninstall", "lost_sessions_alpha")  # names compare normalized
    assert code == 0
    argv = ran.call_args.args[0]
    assert "lost-sessions-alpha" not in argv
    assert argv[-1] == "lost-sessions-beta @ file:///w/beta-1.0-py3-none-any.whl"


def test_uninstall_print_shows_the_pip_uninstall_line(env, cli_env):
    code, out, _ = run("uninstall", "lost-sessions-alpha", "--print")
    assert code == 0
    assert (
        shlex.join([sys.executable, "-m", "pip", "uninstall", "lost-sessions-alpha"])
        in out
    )


def test_uninstall_of_a_plugin_that_is_not_installed_is_an_error(env, cli_env):
    code, _, err = run("uninstall", "lost-sessions-nope", "--print")
    assert code == 1
    assert "not installed" in err


def test_uv_missing_in_a_uv_tool_is_an_error_not_a_crash(env, cli_env):
    uv_tool(env)
    with mock.patch.object(installer.shutil, "which", return_value=None):
        code, _, err = run("install", "lost-sessions-gamma")
    assert code == 1
    assert "uv" in err


def test_a_failed_uv_run_exits_one(env, cli_env):
    uv_tool(env)
    with (
        mock.patch.object(
            installer.subprocess,
            "run",
            return_value=types.SimpleNamespace(returncode=2),
        ),
        mock.patch.object(installer.shutil, "which", return_value="/bin/uv"),
    ):
        code, _, _ = run("install", "lost-sessions-gamma")
    assert code == 1


# --- plugins ---------------------------------------------------------------------------


def test_plugins_hides_built_ins_unless_all(cli_env):
    code, out, _ = run("plugins")
    assert code == 0
    listed = json.loads(out)
    assert all(
        not p["name"].startswith("lost_sessions.default_plugins.") for p in listed
    )
    code, out, _ = run("plugins", "--all")
    names = [p["name"] for p in json.loads(out)]
    for m in ("claude", "codex", "muse", "opencode", "herdr", "rex"):
        assert f"lost_sessions.default_plugins.{m}" in names
    assert names == sorted(names)


def test_plugins_hook_filter(cli_env):
    _, out, _ = run("plugins", "--all", "--hook", "register_session_managers")
    names = {p["name"] for p in json.loads(out)}
    assert names >= {
        "lost_sessions.default_plugins.herdr",
        "lost_sessions.default_plugins.rex",
    }
    assert "lost_sessions.default_plugins.claude" not in names
    entry = next(p for p in json.loads(out) if p["name"].endswith(".herdr"))
    assert entry["hooks"] == ["register_session_managers"]


def test_a_requested_package_replaces_the_installed_one_with_the_same_name(
    env, cli_env
):
    code, out, _ = run("install", "lost-sessions-beta==2.0", "--print")
    assert code == 0
    line = next(x for x in out.splitlines() if x.startswith("uv:"))
    assert "beta-1.0-py3-none-any.whl" not in line  # the old source is replaced
    assert line.endswith("--with lost-sessions-alpha --with lost-sessions-beta==2.0")


@pytest.mark.parametrize(
    ("spec", "name"),
    [
        ("lost-sessions-x", "lost-sessions-x"),
        ("lost_sessions.X==2.0rc1", "lost-sessions-x"),
        ("lost-sessions-x[extra]>=1", "lost-sessions-x"),
        ("lost-sessions-x @ file:///w/x.whl", "lost-sessions-x"),
        ("lost-sessions-x@file:///w/x.whl", "lost-sessions-x"),
        ("./plugins/x", None),
        ("/abs/x-1.0-py3-none-any.whl", None),
        ("git+https://github.com/o/x", None),
    ],
)
def test_requested_names(spec, name):
    assert installer.requested_name(spec) == name
