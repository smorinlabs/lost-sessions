"""The `recover` menu and command (design 0006, TS-5).

Ported from smorin/smorin-bootstrap tests/test_lost_sessions.py (TestMenu and the
recover CLI tests) at 713e443. Each test drives the Textual app with its pilot.
"""

from __future__ import annotations

import asyncio
import sys
from unittest import mock

import pytest

from lost_sessions import cli, core, menu
from lost_sessions.default_plugins.herdr import HerdrDestinations
from tests.test_core import (  # noqa: F401
    CLAUDE_ID,
    CODEX_ID,
    MUSE_ID,
    SINCE,
    cli_env,
    run,
)
from tests.test_managers import fakes, rows  # noqa: F401 - fakes is a fixture

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="lost-sessions targets macOS and Linux"
)

SIZE = (120, 40)  # a real terminal, not Textual's 80x24 default
OPTS = {"workspace": "recovered", "rex_session": "recovered", "herdr_session": None}


def dests(**options):
    managers = {m.name: m for m in core.menu_managers()}
    return {name: m.destinations(OPTS | options) for name, m in managers.items()}


def make_app(env, picked=None, label="recovered", herdr_ok=True, show_all=False):
    picked = picked if picked is not None else list(rows(env).values())
    return menu.make_menu(picked, dests(workspace=label), {"herdr": herdr_ok}, show_all)


def ids(app):
    return [r.session.id for r in app.shown()]


def drive(app, body, size=SIZE):
    async def go():
        async with app.run_test(size=size) as pilot:
            await body(pilot)

    asyncio.run(go())


def assert_fits(app, column, text):
    """The column is wide enough to show the whole cell, not just its data."""
    table = app.query_one("#table")
    assert table.columns[column].get_render_width(table) >= len(text)


def test_preview_follows_the_chosen_action(fakes):
    app = make_app(fakes)

    async def body(pilot):
        assert "no action" in app.preview_text()
        assert "r for Rex, h for Herdr" in app.preview_text()
        await pilot.press("r")
        assert "rex session new recovered" in app.preview_text()
        await pilot.press("h")
        assert "herdr workspace create --label recovered" in app.preview_text()
        await pilot.press("p")
        assert f"claude --resume {CLAUDE_ID}" in app.preview_text()

    drive(app, body)


def test_where_column_shows_each_rows_destination(fakes):
    app = make_app(fakes)

    async def body(pilot):
        assert app.where_text(CLAUDE_ID) == "—"
        await pilot.press("h")
        assert app.where_text(CLAUDE_ID) == "recovered (new)"
        assert (
            str(app.query_one("#table").get_cell(CLAUDE_ID, "where"))
            == "recovered (new)"
        )
        await pilot.press("p")
        assert app.where_text(CLAUDE_ID) == "—"

    drive(app, body)


def test_reported_sequence_changes_the_row_at_real_size(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("h")
        assert_fits(app, "where", "recovered (new)")
        await pilot.press("w", "down", "enter")
        assert app.where_text(CLAUDE_ID) == "existing"
        assert str(app.query_one("#table").get_cell(CLAUDE_ID, "where")) == "existing"
        assert "herdr tab create --workspace wA" in app.preview_text()

    drive(app, body)


def test_w_changes_only_the_highlighted_row(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("h", "down", "h", "up", "w", "down", "enter")
        assert app.where_text(CLAUDE_ID) == "existing"
        assert app.where_text(CODEX_ID) == "recovered (new)"
        await pilot.press("down")  # row 2 is now the first into the new workspace
        assert "herdr workspace create --label recovered" in app.preview_text()

    drive(app, body)


def test_shift_w_copies_the_destination_to_rows_with_the_same_action(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press(
            "h", "down", "h", "down", "r", "up", "up", "w", "down", "enter", "W"
        )
        assert app.where_text(CODEX_ID) == "existing"
        assert app.where_text(MUSE_ID) == "recovered (new)"  # the Rex row keeps its own
        assert (MUSE_ID, "herdr") not in app.targets

    drive(app, body)


def test_rows_sharing_a_new_destination_create_it_once(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("h", "down", "h")
        assert "herdr tab create --workspace <new workspace>" in app.preview_text()
        await pilot.press("down", "r", "down", "r")
        assert "rex run -s <new session>" in app.preview_text()
        assert "rex window rename -s <new session>" in app.preview_text()

    drive(app, body)


def test_picker_title_sits_above_the_list_and_starts_on_the_current_choice(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("h", "w")
        options = app.screen.query_one("OptionList")
        title = app.screen.query_one("#title")
        assert title.region.y + title.region.height < options.region.y + 1
        assert options.highlighted == 0
        await pilot.press("down", "enter", "w")
        assert app.screen.query_one("OptionList").highlighted == 1

    drive(app, body)


def test_rex_picker_offers_current_and_existing_sessions(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("r", "w", "down", "enter")
        assert app.where_text(CLAUDE_ID) == "current (mine)"
        assert "rex run -s session:cur" in app.preview_text()

    drive(app, body)


def test_w_without_an_open_action_does_not_open_the_picker(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("w")
        assert "Picker" not in type(app.screen).__name__
        await pilot.press("p", "w")
        assert "Picker" not in type(app.screen).__name__

    drive(app, body)


def test_a_shows_and_hides_running_rows_and_keeps_choices(fakes):
    app = make_app(fakes)

    async def body(pilot):
        assert "running-1" not in ids(app)
        assert "running: hidden" in str(app.query_one("#top").render())
        await pilot.press("p", "a")
        assert "running-1" in ids(app)
        assert app.query_one("#table").row_count == len(ids(app))
        assert "running: shown" in str(app.query_one("#top").render())
        await pilot.press("a")
        assert "running-1" not in ids(app)
        assert app.actions.get(CLAUDE_ID) == "print"
        assert app.current_id() == CLAUDE_ID

    drive(app, body)


def test_toggle_keeps_the_cursor_on_a_later_row(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press(
            "down", "down", "down", "a"
        )  # maybe-1, below the hidden running-1
        assert app.current_id() == "maybe-1"
        await pilot.press("a")
        assert app.current_id() == "maybe-1"

    drive(app, body)


def test_picker_keeps_the_highlight_visible_on_a_short_terminal(fakes):
    workspaces = [
        {"workspace_id": f"w{i}", "label": f"ws{i}", "tab_count": 1} for i in range(25)
    ]
    d = dests()
    d["herdr"] = HerdrDestinations("recovered", True, workspaces, None)
    one = [r for r in rows(fakes).values() if r.session.id == CLAUDE_ID]
    app = menu.make_menu(one, d)

    async def body(pilot):
        await pilot.press("h", "w", *["down"] * 20)
        options = app.screen.query_one("OptionList")
        box = app.screen.query_one("#box")
        assert options.region.bottom <= box.region.bottom
        assert options.region.bottom <= 24

    drive(app, body, size=(80, 24))


def test_show_all_starts_with_running_rows(fakes):
    app = make_app(fakes, show_all=True)

    async def body(pilot):
        assert "running-1" in ids(app)

    drive(app, body)


def test_hidden_print_choice_still_runs_and_is_counted(fakes):
    app = make_app(fakes, show_all=True)

    async def body(pilot):
        await pilot.press("down", "down", "down", "p", "a")
        assert "1 chosen (1 hidden)" in str(app.query_one("#top").render())
        await pilot.press("enter")

    drive(app, body)
    assert [(r.session.id, a) for r, a, _ in app.return_value] == [
        ("running-1", "print")
    ]


def test_f_marks_one_row_for_focus(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("f")
        assert app.focus_id is None  # no action yet
        await pilot.press("h", "f")
        assert app.focus_id == CLAUDE_ID
        assert (
            str(app.query_one("#table").get_cell(CLAUDE_ID, "action"))
            == "Herdr ▸ focus"
        )
        assert_fits(app, "action", "Herdr ▸ focus")
        assert "focus: #1" in str(app.query_one("#top").render())
        await pilot.press("down", "r", "f")
        assert app.focus_id == CODEX_ID  # moving the mark clears the first
        assert str(app.query_one("#table").get_cell(CLAUDE_ID, "action")) == "Herdr"
        await pilot.press("f")
        assert app.focus_id is None  # f again unmarks

    drive(app, body)


def test_print_clears_the_focus_mark(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("r", "f", "p")
        assert app.focus_id is None

    drive(app, body)


def test_nothing_chosen_returns_nothing(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("enter")

    drive(app, body)
    assert app.return_value == []


def test_quit_returns_nothing(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("r", "q")

    drive(app, body)
    assert app.return_value == []


def test_mixed_actions_are_returned_in_row_order_with_their_destinations(fakes):
    app = make_app(fakes)

    async def body(pilot):
        await pilot.press("h", "down", "r", "down", "p", "enter")

    drive(app, body)
    got = [
        (r.session.id, a, t and app.dests[a].where(t)) for r, a, t in app.return_value
    ]
    assert got == [
        (CLAUDE_ID, "herdr", "recovered (new)"),
        (CODEX_ID, "rex", "recovered (new)"),
        (MUSE_ID, "print", None),
    ]


def test_picker_uses_the_chosen_default_label(fakes):
    app = make_app(fakes, label="foo")

    async def body(pilot):
        await pilot.press("h", "w", "enter")
        assert app.where_text(CLAUDE_ID) == "foo (new)"
        assert "workspace create --label foo" in app.preview_text()

    drive(app, body)


def test_brackets_render_literally_and_preview_is_exact(fakes):
    one = [r for r in rows(fakes).values() if r.session.id == "bracket-1"]
    one[0].session.spawn_dir = "/Users/x/c/app/[slug]/page"
    one[
        0
    ].session.resume = "cd '/Users/x/c/app/[slug]/page' && claude --resume bracket-1"
    app = make_app(fakes, picked=one)

    async def body(pilot):
        await pilot.press("p")
        assert "[slug]" in app.preview_text()
        assert "[slug]" in str(app.query_one("#preview").render())

    drive(app, body)


def test_running_rows_with_all_are_print_only(fakes):
    one = [r for r in rows(fakes).values() if r.session.id == "running-1"]
    app = make_app(fakes, picked=one, show_all=True)

    async def body(pilot):
        await pilot.press("r", "h", "space")
        assert app.actions.get("running-1") == "print"
        await pilot.press("enter")

    drive(app, body)
    assert [a for _, a, _ in app.return_value] == ["print"]


def test_herdr_unavailable_disables_only_herdr(fakes):
    app = make_app(fakes, herdr_ok=False)

    async def body(pilot):
        await pilot.press("h")
        assert app.actions.get(CLAUDE_ID) is None
        assert "Herdr not available" in str(app.query_one("#top").render())
        await pilot.press("r", "enter")

    drive(app, body)
    assert [a for _, a, _ in app.return_value] == ["rex"]


# --- the recover command ---------------------------------------------------------------


def test_recover_without_terminal_is_usage_error(fakes):
    with mock.patch.object(cli, "interactive", return_value=False):
        code, _, err = run("recover", *SINCE)
    assert code == 2
    assert "lost-sessions open" in err


def test_recover_runs_each_row_into_its_destination_then_focuses_the_mark(fakes):
    rs = rows(fakes)
    d = dests()
    stub = mock.Mock(focus_id=CODEX_ID)
    stub.run.return_value = [
        (rs[CLAUDE_ID], "herdr", d["herdr"].default()),
        (rs[CODEX_ID], "herdr", d["herdr"].default()),
        (rs[MUSE_ID], "rex", d["rex"].get("other")),
    ]
    with (
        mock.patch.object(menu, "make_menu", return_value=stub),
        mock.patch.object(cli, "interactive", return_value=True),
    ):
        code, _, _ = run("recover", *SINCE)
    assert code == 0
    verbs = [c[1:3] for c in fakes["calls"]()]
    assert verbs.count(["workspace", "create"]) == 1
    assert ["run", "-s"] in verbs
    assert fakes["calls"]()[-1] == ["herdr", "tab", "focus", "wN:t9"]


def test_recover_with_nothing_lost_says_so(fakes):
    fakes["agent"].sessions = [s for s in fakes["agent"].sessions if s.live == "yes"]
    with mock.patch.object(cli, "interactive", return_value=True):
        code, out, _ = run("recover", *SINCE)
    assert code == 0
    assert (
        "No lost sessions in this window (1 running or in Herdr; --all shows them)."
        in out
    )


def test_recover_when_nothing_is_chosen(fakes):
    stub = mock.Mock(focus_id=None)
    stub.run.return_value = []
    with (
        mock.patch.object(menu, "make_menu", return_value=stub),
        mock.patch.object(cli, "interactive", return_value=True),
    ):
        code, out, _ = run("recover", *SINCE)
    assert code == 0
    assert "Nothing chosen" in out
