"""Packaging end to end (design 0006, TS-7, TS-8, TS-9). Marked slow: it builds
wheels and installs them with uv into temporary tool directories, never the
user's own `uv tool` installs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.platform == "win32", reason="lost-sessions targets macOS and Linux"
    ),
    pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv"),
]

FAKE_PLUGIN = textwrap.dedent("""\
    from lost_sessions import hookimpl


    @hookimpl
    def register_commands(cli):
        @cli.command(name="fake-hello")
        def hello():
            "Say hello from a third-party plugin"
            print("hello from lost-sessions-fake")
""")

FAKE_PYPROJECT = textwrap.dedent("""\
    [project]
    name = "lost-sessions-fake"
    version = "0.0.1"
    requires-python = ">=3.13"

    [project.entry-points.lost_sessions]
    fake = "lost_sessions_fake"

    [build-system]
    requires = ["uv_build>=0.5,<1.0"]
    build-backend = "uv_build"
""")


def sh(argv, env, cwd=None, check=True):
    r = subprocess.run(
        argv, capture_output=True, text=True, env=env, cwd=cwd, timeout=600
    )
    if check and r.returncode:
        raise AssertionError(f"{argv} exited {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


@pytest.fixture(scope="module")
def wheels(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_TOOL")}
    sh(["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)], env)
    fake = tmp_path_factory.mktemp("fake")
    (fake / "src" / "lost_sessions_fake").mkdir(parents=True)
    (fake / "src" / "lost_sessions_fake" / "__init__.py").write_text(FAKE_PLUGIN)
    (fake / "pyproject.toml").write_text(FAKE_PYPROJECT)
    (fake / "README.md").write_text("fake plugin\n")
    sh(["uv", "build", "--wheel", "--out-dir", str(out), str(fake)], env)
    tool = next(out.glob("lost_sessions-*.whl"))
    plugin = next(out.glob("lost_sessions_fake-*.whl"))
    return tool, plugin


@pytest.fixture
def tool_env(tmp_path, monkeypatch):
    env = {k: v for k, v in os.environ.items() if k != "LOST_SESSIONS_LOAD_PLUGINS"}
    env |= {
        "UV_TOOL_DIR": str(tmp_path / "tools"),
        "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
        "HOME": str(tmp_path / "home"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    (tmp_path / "home").mkdir()
    return env, tmp_path


def plugins(binary, env, *args):
    return json.loads(sh([str(binary), "plugins", *args], env).stdout)


def test_uv_tool_install_lists_built_ins_and_manages_a_plugin(wheels, tool_env):
    tool_wheel, plugin_wheel = wheels
    env, tmp = tool_env
    sh(["uv", "tool", "install", str(tool_wheel)], env)
    binary = tmp / "bin" / "lost-sessions"

    # TS-9: the uv-tool detection signal still exists where install looks for it.
    assert (tmp / "tools" / "lost-sessions" / "uv-receipt.toml").is_file()

    # TS-7: the six built-ins are present; no third-party plugin yet.
    names = [p["name"] for p in plugins(binary, env, "--all")]
    for m in ("claude", "codex", "muse", "opencode", "herdr", "rex"):
        assert f"lost_sessions.default_plugins.{m}" in names
    assert plugins(binary, env) == []

    # install runs `uv tool install ... --with <plugin>` and keeps the local wheel source.
    spec = f"lost-sessions-fake @ {plugin_wheel.as_uri()}"
    out = sh([str(binary), "install", spec], env).stdout
    assert "applies here: uv" in out
    assert f"@ {tool_wheel.as_uri()}" in out  # the tool keeps its local-wheel source
    listed = plugins(binary, env)
    assert listed == [
        {
            "name": "lost-sessions-fake",
            "hooks": ["register_commands"],
            "version": "0.0.1",
        }
    ]
    assert (
        sh([str(binary), "fake-hello"], env).stdout.strip()
        == "hello from lost-sessions-fake"
    )

    # TS-8: the plugin survives `uv tool upgrade --reinstall`.
    sh(["uv", "tool", "upgrade", "--reinstall", "lost-sessions"], env)
    assert [p["name"] for p in plugins(binary, env)] == ["lost-sessions-fake"]

    # a second install keeps the first plugin; --print shows it in the uv line
    printed = sh([str(binary), "install", "lost-sessions-other", "--print"], env).stdout
    assert f"lost-sessions-fake @ {plugin_wheel.as_uri()}" in printed

    # uninstall rebuilds the tool without it
    sh([str(binary), "uninstall", "lost-sessions-fake"], env)
    assert plugins(binary, env) == []


def test_install_in_a_plain_virtualenv_prints_and_runs_nothing(wheels, tool_env):
    tool_wheel, _ = wheels
    env, tmp = tool_env
    venv = tmp / "venv"
    sh(["uv", "venv", "--python", sys.executable, str(venv)], env)
    sh(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin" / "python"),
            str(tool_wheel),
        ],
        env,
    )
    binary = venv / "bin" / "lost-sessions"
    printed = sh([str(binary), "install", "lost-sessions-x", "--print"], env)
    assert "applies here: pip" in printed.stdout
    assert f"{venv / 'bin' / 'python'} -m pip install lost-sessions-x" in printed.stdout
    refused = sh([str(binary), "install", "lost-sessions-x"], env, check=False)
    assert refused.returncode == 1
    assert "nothing was run" in refused.stderr
