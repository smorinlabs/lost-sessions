"""Plugin loading and registration (design 0006, TS-1 and TS-2)."""

from __future__ import annotations

import types
from importlib import metadata

import click
import pytest
from click.testing import CliRunner

from lost_sessions import hookimpl
from lost_sessions.cli import build_cli
from lost_sessions.plugins import (
    DEFAULT_PLUGINS,
    ENTRY_POINT_GROUP,
    get_agent_tools,
    get_session_managers,
    load_plugins,
    make_plugin_manager,
)


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeManager:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def pm():
    return make_plugin_manager()


@pytest.fixture
def registered(pm):
    """Register a throwaway plugin and always unregister it (TS-2)."""

    def _register(plugin, name):
        pm.register(plugin, name=name)
        return plugin

    names = []

    def register(plugin, name):
        names.append(name)
        return _register(plugin, name)

    try:
        yield register
    finally:
        for name in names:
            pm.unregister(name=name)


# --- TS-1: loading -------------------------------------------------------------


def test_built_ins_load_when_third_party_plugins_are_disabled(pm, monkeypatch):
    monkeypatch.setenv("LOST_SESSIONS_LOAD_PLUGINS", "")
    calls = []
    monkeypatch.setattr(pm, "load_setuptools_entrypoints", calls.append)
    load_plugins(pm)
    assert calls == []
    for path in DEFAULT_PLUGINS:
        assert pm.has_plugin(path)


def test_entry_points_load_when_the_variable_is_unset(pm, monkeypatch):
    monkeypatch.delenv("LOST_SESSIONS_LOAD_PLUGINS", raising=False)
    calls = []
    monkeypatch.setattr(pm, "load_setuptools_entrypoints", calls.append)
    load_plugins(pm)
    assert calls == [ENTRY_POINT_GROUP]
    assert all(pm.has_plugin(path) for path in DEFAULT_PLUGINS)


def test_the_six_built_ins_are_the_designed_modules():
    assert DEFAULT_PLUGINS == tuple(
        f"lost_sessions.default_plugins.{m}"
        for m in ("claude", "codex", "muse", "opencode", "herdr", "rex")
    )


def test_loading_twice_is_harmless(pm, monkeypatch):
    monkeypatch.setenv("LOST_SESSIONS_LOAD_PLUGINS", "")
    load_plugins(pm)
    load_plugins(pm)
    assert len(pm.get_plugins()) == len(DEFAULT_PLUGINS)


def _fake_distribution(name, module):
    entry_point = types.SimpleNamespace(
        group=ENTRY_POINT_GROUP,
        name=name.removeprefix("lost-sessions-"),
        load=lambda: module,
    )
    return types.SimpleNamespace(
        entry_points=[entry_point], metadata={"Name": name}, version="1.2.3"
    )


def test_allow_list_loads_only_the_named_distributions(pm, monkeypatch, capsys):
    wanted = types.ModuleType("lost_sessions_wanted")
    distributions = {
        "lost-sessions-wanted": _fake_distribution("lost-sessions-wanted", wanted)
    }

    def distribution(name):
        if name not in distributions:
            raise metadata.PackageNotFoundError(name)
        return distributions[name]

    monkeypatch.setattr(metadata, "distribution", distribution)
    monkeypatch.setenv(
        "LOST_SESSIONS_LOAD_PLUGINS", "lost-sessions-wanted, lost-sessions-missing"
    )
    monkeypatch.setattr(pm, "load_setuptools_entrypoints", pytest.fail)
    load_plugins(pm)
    assert pm.is_registered(wanted)
    assert pm.distributions[wanted].version == "1.2.3"
    assert "Plugin lost-sessions-missing could not be found" in capsys.readouterr().err


def test_allow_list_tolerates_repeated_and_clashing_entry_points(pm, monkeypatch):
    first = types.ModuleType("lost_sessions_first")
    clash = types.ModuleType("lost_sessions_clash")
    distributions = {
        "lost-sessions-first": _fake_distribution("lost-sessions-first", first),
        # a second distribution exposing the same entry-point name, "first"
        "other-first": types.SimpleNamespace(
            entry_points=[
                types.SimpleNamespace(
                    group=ENTRY_POINT_GROUP, name="first", load=lambda: clash
                )
            ],
            metadata={"Name": "other-first"},
            version="9",
        ),
    }
    monkeypatch.setattr(metadata, "distribution", distributions.__getitem__)
    monkeypatch.setenv(
        "LOST_SESSIONS_LOAD_PLUGINS",
        "lost-sessions-first,lost-sessions-first,other-first",
    )
    load_plugins(pm)
    assert pm.is_registered(first)
    assert not pm.is_registered(clash)


def test_discovered_entry_point_plugins_get_distribution_metadata(pm, monkeypatch):
    plugin = types.ModuleType("lost_sessions_discovered")
    dist = types.SimpleNamespace(version="4.5.6")
    monkeypatch.delenv("LOST_SESSIONS_LOAD_PLUGINS", raising=False)

    def fake_discovery(group):
        pm.register(plugin, name="discovered")

    monkeypatch.setattr(pm, "load_setuptools_entrypoints", fake_discovery)
    monkeypatch.setattr(pm, "list_plugin_distinfo", lambda: [(plugin, dist)])
    load_plugins(pm)
    assert pm.distributions[plugin] is dist


# --- TS-2: registration through the hooks ----------------------------------------


def test_fake_agent_tool_and_manager_register_through_the_hooks(pm, registered):
    class FakePlugin:
        __name__ = "FakePlugin"

        @hookimpl
        def register_agent_tools(self, register):
            register(FakeTool("fake-agent"))

        @hookimpl
        def register_session_managers(self, register):
            register(FakeManager("fake-manager"))

    registered(FakePlugin(), "undo-FakePlugin")
    assert list(get_agent_tools(pm)) == ["fake-agent"]
    assert list(get_session_managers(pm)) == ["fake-manager"]


def test_unregistering_removes_the_plugin(pm):
    class Gone:
        __name__ = "Gone"

        @hookimpl
        def register_agent_tools(self, register):
            register(FakeTool("gone"))

    pm.register(Gone(), name="undo-Gone")
    pm.unregister(name="undo-Gone")
    assert get_agent_tools(pm) == {}


def test_duplicate_name_keeps_the_first_registration_and_warns(pm, registered, capsys):
    first, second = FakeTool("dup"), FakeTool("dup")

    class Early:
        __name__ = "Early"

        @hookimpl
        def register_agent_tools(self, register):
            register(first)

    class Late:
        __name__ = "Late"

        @hookimpl
        def register_agent_tools(self, register):
            register(second)

    # pluggy calls the most recently registered plugin first, so Late runs first.
    registered(Early(), "undo-Early")
    registered(Late(), "undo-Late")
    assert get_agent_tools(pm)["dup"] is second
    err = capsys.readouterr().err
    assert "dup" in err and "already registered" in err


def test_register_commands_adds_a_subcommand_to_a_fresh_cli(pm, registered):
    class HelloPlugin:
        __name__ = "HelloPlugin"

        @hookimpl
        def register_commands(self, cli):
            @cli.command(name="hello-world")
            def hello_world():
                "Print hello world"
                click.echo("Hello world!")

    assert "hello-world" not in build_cli(pm).commands
    registered(HelloPlugin(), "undo-HelloPlugin")
    result = CliRunner().invoke(build_cli(pm), ["hello-world"])
    assert result.exit_code == 0
    assert result.output == "Hello world!\n"


def test_version_option(pm):
    result = CliRunner().invoke(build_cli(pm), ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("lost-sessions, version ")


def test_inventory_tool_choices_come_from_loaded_agent_plugins(pm):
    class NameOnly:
        __name__ = "NameOnly"

        @hookimpl
        def register_agent_tools(self, register):
            register(FakeTool("not-an-agent-tool"))

    pm.register(NameOnly(), name="undo-NameOnly")
    try:
        choices = next(
            p for p in build_cli(pm).commands["inventory"].params if p.name == "tool"
        ).type.choices
    finally:
        pm.unregister(name="undo-NameOnly")
    assert list(choices) == ["claude", "codex", "muse", "opencode"]
