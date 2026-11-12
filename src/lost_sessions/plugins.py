"""The plugin manager and plugin loading (design 0006, Section 7.1)."""

from __future__ import annotations

import importlib
import os
import sys
from importlib import metadata
from typing import Protocol

import pluggy

from lost_sessions import hookspecs

ENTRY_POINT_GROUP = "lost_sessions"
LOAD_PLUGINS_ENV = "LOST_SESSIONS_LOAD_PLUGINS"
DEFAULT_PLUGINS = tuple(
    f"lost_sessions.default_plugins.{m}"
    for m in ("claude", "codex", "muse", "opencode", "herdr", "rex")
)


class PluginManager(pluggy.PluginManager):
    """pluggy's manager plus our own plugin -> distribution map.

    The map replaces llm's write to pluggy's private `_plugin_distinfo`.
    """

    def __init__(self) -> None:
        super().__init__(ENTRY_POINT_GROUP)
        self.distributions: dict[object, metadata.Distribution] = {}


def make_plugin_manager() -> PluginManager:
    manager = PluginManager()
    manager.add_hookspecs(hookspecs)
    return manager


pm = make_plugin_manager()


def load_plugins(manager: PluginManager = pm) -> None:
    """Load third-party plugins, then the built-ins. Safe to call repeatedly.

    LOST_SESSIONS_LOAD_PLUGINS is read here, not at import: unset loads every
    installed plugin, "" loads none, "a,b" loads only those distributions.
    Built-ins always load, and they load last so pluggy calls them first.
    """
    if all(manager.has_plugin(path) for path in DEFAULT_PLUGINS):
        return
    allow = os.environ.get(LOAD_PLUGINS_ENV)
    if allow is None:
        manager.load_setuptools_entrypoints(ENTRY_POINT_GROUP)
    else:
        for name in (n.strip() for n in allow.split(",")):
            if name:
                _load_distribution(manager, name)
    for path in DEFAULT_PLUGINS:
        if not manager.has_plugin(path):
            manager.register(importlib.import_module(path), path)


def _load_distribution(manager: PluginManager, name: str) -> None:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        sys.stderr.write(f"Plugin {name} could not be found\n")
        return
    for entry_point in distribution.entry_points:
        if entry_point.group == ENTRY_POINT_GROUP:
            plugin = entry_point.load()
            manager.register(plugin, name=entry_point.name)
            manager.distributions[plugin] = distribution


class Named(Protocol):
    """What core needs from any registered object: its unique name."""

    name: str


def _collect(hook: pluggy.HookCaller, kind: str) -> dict[str, Named]:
    """Call one register_* hook; the first object registered under a name wins."""
    found: dict[str, Named] = {}

    def register(obj: Named) -> None:
        if obj.name in found:
            sys.stderr.write(
                f"Warning: {kind} {obj.name!r} is already registered; "
                "keeping the first one\n"
            )
            return
        found[obj.name] = obj

    hook(register=register)
    return found


def get_agent_tools(manager: PluginManager = pm) -> dict[str, Named]:
    return _collect(manager.hook.register_agent_tools, "agent tool")


def get_session_managers(manager: PluginManager = pm) -> dict[str, Named]:
    return _collect(manager.hook.register_session_managers, "session manager")
