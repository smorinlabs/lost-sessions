"""Contract suite: every registered agent and manager plugin (design 0006, TS-3).

Runs against whatever the plugin manager reports, built-ins and test fakes alike,
so a third-party plugin installed in the test environment is checked the same way.
"""

from __future__ import annotations

import sys

import pytest

from lost_sessions import core
from lost_sessions.agents import AgentTool, ScanContext
from lost_sessions.managers import Destinations, SessionManager, Step
from lost_sessions.models import ScanResult, Session
from lost_sessions.plugins import load_plugins, pm

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="lost-sessions targets macOS and Linux"
)

load_plugins(pm)
AGENTS = sorted(core.agent_tools())
MANAGERS = sorted(core.session_managers())


def test_the_built_ins_are_registered():
    assert {"claude", "codex", "muse", "opencode"} <= set(AGENTS)
    assert {"herdr", "rex"} <= set(MANAGERS)


@pytest.mark.parametrize("name", AGENTS)
def test_agent_contract(name, tmp_path, monkeypatch):
    agent = core.agent_tools()[name]
    assert isinstance(agent, AgentTool)
    assert agent.name == name and name.isidentifier()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    result = agent.scan(ScanContext(home=tmp_path))  # an empty home: nothing to find
    assert isinstance(result, ScanResult)
    assert result.sessions == []
    assert result.source.status in ("ok", "absent")
    argv = agent.resume_args(Session(tool=name, id="contract-id"))
    assert isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)
    assert "contract-id" in argv


@pytest.mark.parametrize("name", MANAGERS)
def test_manager_contract(name):
    m = core.session_managers()[name]
    assert isinstance(m, SessionManager)
    assert m.name == name and name.isidentifier()
    assert m.display_name
    singular, plural = m.destination_noun
    assert singular and plural
    for option in m.click_options():
        assert option.name, "every manager option has a parameter name"
    if m.can_open:
        assert len(m.menu_key) == 1 and m.menu_key not in "pxwWafq "  # core's own keys
        assert m.new_placeholder.startswith("{") and m.new_placeholder.endswith("}")
        assert m.open_help


@pytest.mark.parametrize(
    "name", [n for n in MANAGERS if core.session_managers()[n].can_open]
)
def test_opening_manager_plans_steps(name, monkeypatch, tmp_path):
    m = core.session_managers()[name]
    monkeypatch.setenv("PATH", str(tmp_path))  # no real tools: discovery must not crash
    # click 8.3+ marks a missing default with a sentinel; the CLI passes None
    defaults = {
        o.name: o.default if isinstance(o.default, str) else None
        for o in m.click_options()
    }
    dests = m.destinations(defaults)
    assert isinstance(dests, Destinations)
    assert dests.available is False
    target = dests.default()
    assert target.is_new()
    row = core.Row(
        n=1, session=Session(tool="claude", id="contract-id", spawn_dir=str(tmp_path))
    )
    steps = m.plan(core.make_plan(row), target)
    assert steps and all(isinstance(s, Step) and s.argv for s in steps)
    assert any(s.opens for s in steps), (
        "a plan must contain a step that opens something"
    )
    assert dests.describe(target)


def test_menu_keys_do_not_clash():
    keys = [m.menu_key for m in core.menu_managers()]
    assert len(keys) == len(set(keys))
