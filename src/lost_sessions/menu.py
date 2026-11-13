"""The `recover` menu (Textual). Ported from the original script at 713e443.

Textual is imported inside make_menu() so other commands start fast. State is
keyed by session ID, so showing or hiding rows never moves a choice to another
session. Keys, labels and the action cycle come from the session managers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from lost_sessions import core
from lost_sessions.managers import Destination, Destinations, SessionManager
from lost_sessions.plugins import PluginManager, pm

Choice = tuple[core.Row, str, Destination | None]


def make_menu(
    rows: Sequence[core.Row],
    dests: Mapping[str, Destinations],
    available: Mapping[str, bool] | None = None,
    show_all: bool = False,
    manager: PluginManager = pm,
) -> Any:  # noqa: ANN401 - a textual App subclass defined below
    """Build the Textual app; `available` marks managers that could not be reached."""
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.screen import ModalScreen
    from textual.widgets import DataTable, Footer, OptionList, Static

    managers: dict[str, SessionManager] = {
        # A manager with no menu key cannot be chosen; leave it out, keep the menu
        m.name: m
        for m in core.menu_managers(manager)
        if m.name in dests and m.menu_key
    }
    available = dict(available or {})
    ok = {name: available.get(name, True) for name in managers}

    class Table(DataTable, inherit_bindings=False):  # drop Enter: it is the Run key
        BINDINGS: ClassVar[list] = [
            b for b in DataTable.BINDINGS if getattr(b, "key", None) != "enter"
        ]

    class Picker(ModalScreen):
        CSS = """
        Picker { align: center middle; }
        #box { width: 70%; height: auto; max-height: 80%; border: round $accent; padding: 0 1; }
        #title { height: auto; margin-bottom: 1; }
        #box OptionList { height: auto; max-height: 60vh; }
        """
        BINDINGS: ClassVar[list] = [Binding("escape", "dismiss_none", "Cancel")]

        def __init__(self, title: str, choices: list[str], start: int) -> None:
            super().__init__()
            self.title_text, self.choices, self.start = title, choices, start

        def compose(self) -> ComposeResult:
            with Vertical(id="box"):
                yield Static(self.title_text, id="title", markup=False)
                yield OptionList(*[Text(c) for c in self.choices])

        def on_mount(self) -> None:
            self.query_one(OptionList).highlighted = self.start

        def on_option_list_option_selected(
            self, event: OptionList.OptionSelected
        ) -> None:
            self.dismiss(event.option_index)

        def action_dismiss_none(self) -> None:
            self.dismiss(None)

    labels: dict[str | None, str] = {None: "—", "print": "Print"}
    labels |= {name: m.display_name for name, m in managers.items()}
    kinds = {
        name: f"{m.display_name} {m.destination_noun[0]}"
        for name, m in managers.items()
    }
    order: list[str | None] = [None, "print", *managers]
    shorts = core.short_ids(rows)
    names_or = " or ".join(m.display_name for m in managers.values())
    keys_or = " or ".join(f"{m.menu_key} ({m.display_name})" for m in managers.values())

    bindings = [Binding("p", "set('print')", "Print")]
    bindings += [
        Binding(m.menu_key, f"set('{name}')", m.display_name)
        for name, m in managers.items()
    ]
    bindings += [
        Binding("x", "set('')", "Clear"),
        Binding("space", "cycle", "Cycle"),
        Binding("w", "where", "Where"),
        Binding("W", "where_all", "Where: all like this"),
        Binding("a", "toggle_all", "Running"),
        Binding("f", "focus_mark", "Focus"),
        Binding("enter", "confirm", "Run"),
        Binding("q", "quit_none", "Quit"),
        Binding("escape", "quit_none", "Quit", show=False),
    ]

    class Menu(App):
        CSS = (
            "#preview { border: round $accent; padding: 0 1; height: auto; max-height: 12; }"
            " #top { padding: 0 1; }"
        )
        BINDINGS: ClassVar[list] = bindings

        def __init__(self) -> None:
            super().__init__()
            self.rows, self.dests, self.show_all = list(rows), dests, show_all
            self.by_id = {r.session.id: r for r in rows}
            self.actions: dict[str, str | None] = {}  # session id -> action
            # (session id, kind) -> destination; unset means the kind's default
            self.targets: dict[tuple[str, str], Destination] = {}
            self.focus_id: str | None = (
                None  # brought to the front after everything runs
            )

        def compose(self) -> ComposeResult:
            yield Static(id="top", markup=False)
            yield Table(cursor_type="row", id="table")
            yield Static(id="preview", markup=False)
            yield Footer()

        def on_mount(self) -> None:
            t = self.query_one(Table)
            for key, label in (
                ("n", "#"),
                ("id", "ID"),
                ("tool", "Tool"),
                ("action", "Action"),
                ("where", "Where"),
                ("when", "Last active"),
                ("state", "State"),
                ("about", "About"),
            ):
                t.add_column(label, key=key)
            self.fill_table()
            t.focus()

        def shown(self) -> list[core.Row]:
            return [
                r
                for r in self.rows
                if self.show_all or not core.hidden_by_default(r.session)
            ]

        def fill_table(self, keep: str | None = None) -> None:
            t = self.query_one(Table)
            t.clear()
            for r in self.shown():
                s, sid = r.session, r.session.id
                updated = core._parse(s.updated)
                when = updated.astimezone().strftime("%b %d %H:%M") if updated else "?"
                t.add_row(
                    Text(str(r.n)),
                    Text(shorts[sid]),
                    Text(s.tool),
                    Text(self.action_text(sid)),
                    Text(self.where_text(sid)),
                    Text(when),
                    Text(core.state_label(s)),
                    Text(core.about(s)[:70]),
                    key=sid,
                )
            ids = [r.session.id for r in self.shown()]
            if keep in ids:
                t.move_cursor(row=ids.index(keep))
            self.refresh_view()

        def current_id(self) -> str | None:
            shown = self.shown()
            if not shown:
                return None
            return shown[
                min(self.query_one(Table).cursor_row, len(shown) - 1)
            ].session.id

        def target_for(self, sid: str, kind: str | None = None) -> Destination | None:
            kind = kind or self.actions.get(sid)
            if kind not in kinds:
                return None
            return self.targets.get((sid, kind)) or self.dests[kind].default()

        def action_text(self, sid: str) -> str:
            text = labels[self.actions.get(sid)]
            return f"{text} ▸ focus" if sid == self.focus_id else text

        def where_text(self, sid: str) -> str:
            t = self.target_for(sid)
            kind = self.actions.get(sid)
            return self.dests[kind].describe(t) if t and kind else "—"

        def planned_target(self, sid: str) -> Destination | None:
            """The target row `sid` will see when actions run in row order: a new
            destination an earlier row creates shows as a placeholder."""
            kind = self.actions.get(sid)
            t = self.target_for(sid)
            if t is None or kind is None:
                return None
            if t.is_new():
                for r in self.rows:
                    if r.session.id == sid:
                        break
                    if (
                        self.actions.get(r.session.id) == kind
                        and self.target_for(r.session.id) is t
                    ):
                        return t.model_copy(
                            update={"id": managers[kind].new_placeholder}
                        )
            return t

        def preview_text(self) -> str:
            sid = self.current_id()
            if sid is None:
                return ""
            action = self.actions.get(sid)
            mgr = managers.get(action or "")
            return core.preview(
                self.by_id[sid], action, mgr, self.planned_target(sid), manager
            )

        def refresh_view(self) -> None:
            chosen = [sid for sid, a in self.actions.items() if a]
            visible = {r.session.id for r in self.shown()}
            off = sum(1 for sid in chosen if sid not in visible)
            parts = [
                f"{len(self.shown())} sessions",
                f"{len(chosen)} chosen" + (f" ({off} hidden)" if off else ""),
                "running: shown" if self.show_all else "running: hidden",
            ]
            if self.focus_id:
                parts.append(f"focus: #{self.by_id[self.focus_id].n}")
            parts += [
                f"{managers[n].display_name} not available"
                for n, up in ok.items()
                if not up
            ]
            self.query_one("#top", Static).update(Text(" · ".join(parts)))
            self.query_one("#preview", Static).update(Text(self.preview_text()))

        def update_row(self, sid: str) -> None:
            t = self.query_one(Table)
            if sid in {r.session.id for r in self.shown()}:
                t.update_cell(
                    sid, "action", Text(self.action_text(sid)), update_width=True
                )
                t.update_cell(
                    sid, "where", Text(self.where_text(sid)), update_width=True
                )

        def on_data_table_row_highlighted(
            self, _event: DataTable.RowHighlighted
        ) -> None:
            self.refresh_view()

        def action_set(self, action: str) -> None:
            sid = self.current_id()
            if sid is None:
                return
            if action in ok and not ok[action]:
                self.bell()
                self.notify(
                    f"{managers[action].display_name} is not available", markup=False
                )
                return
            why = core.refusal(self.by_id[sid].session, action) if action else None
            if why:
                self.bell()
                self.notify(f"Print only: {why}", markup=False)
                return
            self.actions[sid] = action or None
            if sid == self.focus_id and self.actions[sid] not in kinds:
                self.focus_id = None  # only an opened session can be focused
            self.update_row(sid)
            self.refresh_view()

        def action_cycle(self) -> None:
            sid = self.current_id()
            if sid is None:
                return
            nxt = order[(order.index(self.actions.get(sid)) + 1) % len(order)]
            while nxt and (
                core.refusal(self.by_id[sid].session, nxt)
                or (nxt in ok and not ok[nxt])
            ):
                nxt = order[(order.index(nxt) + 1) % len(order)]
            self.action_set(nxt or "")

        def action_where(self) -> None:
            sid = self.current_id()
            kind = self.actions.get(sid) if sid else None
            if sid is None or kind not in kinds:
                self.bell()
                self.notify(f"Choose {keys_or} for this row first", markup=False)
                return
            options = self.dests[kind].choices()
            current = self.target_for(sid)
            start = next((i for i, t in enumerate(options) if t is current), 0)

            def chosen(index: int | None) -> None:
                if index is None:
                    return
                self.targets[(sid, kind)] = options[index]
                self.update_row(sid)
                self.refresh_view()

            self.push_screen(
                Picker(
                    f"Open #{self.by_id[sid].n} in which {kinds[kind]}?",
                    [self.dests[kind].describe(t) for t in options],
                    start,
                ),
                chosen,
            )

        def action_where_all(self) -> None:
            sid = self.current_id()
            kind = self.actions.get(sid) if sid else None
            if sid is None or kind not in kinds:
                self.bell()
                return
            t = self.target_for(sid)
            if t is None:
                return
            for other, a in self.actions.items():
                if a == kind:
                    self.targets[(other, kind)] = t
                    self.update_row(other)
            self.notify(
                f"Every {labels[kind]} row now opens in {self.dests[kind].describe(t)}",
                markup=False,
            )
            self.refresh_view()

        def action_focus_mark(self) -> None:
            sid = self.current_id()
            if sid is None or self.actions.get(sid) not in kinds:
                self.bell()
                self.notify(
                    f"Only a session opened in {names_or} can be focused", markup=False
                )
                return
            previous, self.focus_id = (
                self.focus_id,
                (None if self.focus_id == sid else sid),
            )
            for other in {previous, sid} - {None}:
                if other:
                    self.update_row(other)
            self.refresh_view()

        def action_toggle_all(self) -> None:
            keep = self.current_id()
            self.show_all = not self.show_all
            self.fill_table(keep)

        def action_confirm(self) -> None:
            chosen: list[Choice] = []
            for r in self.rows:
                action = self.actions.get(r.session.id)
                if action:
                    chosen.append((r, action, self.target_for(r.session.id)))
            self.exit(chosen)

        def action_quit_none(self) -> None:
            self.exit([])

    return Menu()
