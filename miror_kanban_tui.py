#!/usr/bin/env python3
"""Modern Textual UI for Miror Kanban."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Static

from miror_kanban import (
    DEFAULT_DATA_FILE,
    VALID_PRIORITIES,
    VALID_STATUSES,
    VALID_TYPES,
    load_board,
    make_item,
    now_iso,
    parse_tags,
    save_board,
    sort_items,
)


TYPE_STYLES = {
    "bug": "bold #ff6b6b",
    "feature": "bold #8bd5ca",
    "task": "bold #7aa2f7",
    "idea": "bold #c792ea",
}

PRIORITY_STYLES = {
    "p0": "bold #ff5370",
    "p1": "bold #ffc777",
    "p2": "bold #82aaff",
    "p3": "bold #a6accd",
}


class IssueCard(Static):
    """A selectable issue card."""

    class Selected(Message):
        def __init__(self, item_id: str) -> None:
            self.item_id = item_id
            super().__init__()

    can_focus = True

    def __init__(self, item: dict[str, Any], selected: bool = False) -> None:
        self.item = item
        super().__init__(self.render_item(), classes="issue-card selected" if selected else "issue-card")

    def render_item(self) -> Text:
        item_type = str(self.item.get("type", "task"))
        priority = str(self.item.get("priority", "p3"))
        text = Text()
        text.append(str(self.item.get("id", "")), style="bold #89ddff")
        text.append("  ")
        text.append(priority.upper(), style=PRIORITY_STYLES.get(priority, "bold"))
        text.append("  ")
        text.append(item_type.upper(), style=TYPE_STYLES.get(item_type, "bold"))
        text.append("\n")
        text.append(str(self.item.get("title", "")), style="bold #eef2ff")

        meta: list[str] = []
        if self.item.get("owner"):
            meta.append(f"@{self.item['owner']}")
        if self.item.get("due"):
            meta.append(f"due {self.item['due']}")
        if self.item.get("tags"):
            meta.extend(f"#{tag}" for tag in self.item.get("tags", [])[:3])
        if meta:
            text.append("\n")
            text.append(" ".join(meta), style="#a6accd")
        return text

    def on_click(self) -> None:
        self.post_message(self.Selected(str(self.item["id"])))


class ClickOnlyButton(Button):
    """A button that mouse users can click without entering keyboard focus order."""

    can_focus = False


class ItemEditor(ModalScreen[dict[str, Any] | None]):
    """New/edit item modal."""

    CSS = """
    ItemEditor {
        align: center middle;
        background: #0b0b0c;
    }

    #editor-dialog {
        width: 68;
        max-width: 92%;
        height: auto;
        max-height: 90%;
        background: #0b0b0c;
        border-top: solid #2c2c31;
        border-bottom: solid #2c2c31;
        padding: 1 1;
    }

    #editor-title {
        height: 1;
        margin-bottom: 1;
        color: #eef2ff;
        text-style: bold;
    }

    .editor-row {
        height: 1;
        margin-bottom: 1;
    }

    .field-label {
        width: 10;
        height: 1;
        content-align: left middle;
        color: #6f737f;
    }

    .field-input {
        width: 1fr;
    }

    #editor-dialog Input {
        height: 1;
        min-height: 1;
        background: #0b0b0c;
        border: none;
        padding: 0;
    }

    #editor-error {
        height: 1;
        color: #ff6b6b;
    }

    #editor-buttons {
        width: 100%;
        height: 1;
        margin-top: 1;
        padding: 0;
    }

    #editor-button-spacer {
        width: 1fr;
    }

    #editor-buttons Button {
        height: 1;
        min-height: 1;
        width: 8;
        min-width: 8;
        margin-right: 1;
        margin-left: 0;
        padding: 0;
        background: #0b0b0c;
        border: none;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self, item: dict[str, Any] | None = None, default_status: str = "backlog") -> None:
        super().__init__()
        self.item = item
        self.default_status = default_status

    def compose(self) -> ComposeResult:
        item = self.item or {}
        title = "Edit Item" if self.item else "New Item"
        buttons: list[Any] = []
        if self.item:
            buttons.append(ClickOnlyButton("Delete", id="delete", variant="error"))
        buttons.extend(
            [
                Static("", id="editor-button-spacer"),
                Button("Cancel", id="cancel"),
                Button("Save", id="save", variant="primary"),
            ]
        )
        yield Vertical(
            Static(title, id="editor-title"),
            Horizontal(
                Static("title", classes="field-label"),
                Input(value=str(item.get("title", "")), placeholder="required", id="field-title", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("type", classes="field-label"),
                Input(value=str(item.get("type", "task")), placeholder="bug feature task idea", id="field-type", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("priority", classes="field-label"),
                Input(value=str(item.get("priority", "p2")), placeholder="p0 p1 p2 p3", id="field-priority", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("status", classes="field-label"),
                Input(value=str(item.get("status", self.default_status)), placeholder="backlog next doing testing done", id="field-status", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("owner", classes="field-label"),
                Input(value=str(item.get("owner", "")), placeholder="optional", id="field-owner", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("due", classes="field-label"),
                Input(value=str(item.get("due", "")), placeholder="optional", id="field-due", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("tags", classes="field-label"),
                Input(value=", ".join(item.get("tags", [])), placeholder="comma separated", id="field-tags", classes="field-input"),
                classes="editor-row",
            ),
            Horizontal(
                Static("notes", classes="field-label"),
                Input(value=str(item.get("notes", "")), placeholder="optional", id="field-notes", classes="field-input"),
                classes="editor-row",
            ),
            Static("", id="editor-error"),
            Horizontal(
                *buttons,
                id="editor-buttons",
            ),
            id="editor-dialog",
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.save()

    @on(Button.Pressed, "#cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def save_pressed(self) -> None:
        self.save()

    @on(Button.Pressed, "#delete")
    def delete_pressed(self) -> None:
        if not self.item:
            return
        self.dismiss({"id": self.item.get("id"), "_delete": True})

    def save(self) -> None:
        title = self.query_one("#field-title", Input).value.strip()
        if not title:
            self.query_one("#editor-error", Static).update("Title is required.")
            return

        item_type = self.query_one("#field-type", Input).value.strip().lower()
        priority = self.query_one("#field-priority", Input).value.strip().lower()
        status = self.query_one("#field-status", Input).value.strip().lower()

        if item_type not in VALID_TYPES:
            self.query_one("#editor-error", Static).update(f"type must be one of: {', '.join(VALID_TYPES)}")
            return
        if priority not in VALID_PRIORITIES:
            self.query_one("#editor-error", Static).update(f"priority must be one of: {', '.join(VALID_PRIORITIES)}")
            return
        if status not in VALID_STATUSES:
            self.query_one("#editor-error", Static).update(f"status must be one of: {', '.join(VALID_STATUSES)}")
            return

        result = {
            "id": self.item.get("id") if self.item else None,
            "title": title,
            "type": item_type,
            "priority": priority,
            "status": status,
            "owner": self.query_one("#field-owner", Input).value.strip(),
            "due": self.query_one("#field-due", Input).value.strip(),
            "tags": parse_tags([self.query_one("#field-tags", Input).value]),
            "notes": self.query_one("#field-notes", Input).value.strip(),
        }
        self.dismiss(result)


class ConfirmArchive(ModalScreen[bool]):
    """Confirmation modal for archiving."""

    CSS = """
    ConfirmArchive {
        align: center middle;
    }

    #confirm-dialog {
        width: 56;
        max-width: 92%;
        height: auto;
        background: #202126;
        border: round #ff6b6b;
        padding: 1 2;
    }

    #confirm-title {
        color: #eef2ff;
        text-style: bold;
        margin-bottom: 1;
    }

    #confirm-copy {
        color: #a6accd;
        margin-bottom: 1;
    }

    #confirm-buttons {
        height: 3;
        align-horizontal: right;
        padding-top: 1;
    }

    #confirm-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, item: dict[str, Any]) -> None:
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Archive {self.item['id']}?", id="confirm-title"),
            Static(str(self.item.get("title", "")), id="confirm-copy"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Archive", id="archive", variant="error"),
                id="confirm-buttons",
            ),
            id="confirm-dialog",
        )

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#archive")
    def archive_pressed(self) -> None:
        self.dismiss(True)


class MirorKanbanApp(App[None]):
    """A modern terminal kanban app."""

    CSS = """
    Screen {
        background: #0b0b0c;
        color: #d7deea;
    }

    #topbar {
        dock: top;
        height: 1;
        background: #0b0b0c;
        padding: 0 1;
    }

    #brand {
        width: 16;
        height: 1;
        content-align: left middle;
        color: #eef2ff;
        text-style: bold;
    }

    #search {
        width: 24;
        height: 1;
        margin: 0 2 0 0;
        padding: 0;
        border: none;
        background: #0b0b0c;
        color: #a6accd;
    }

    #summary {
        width: 1fr;
        height: 1;
        content-align: right middle;
        color: #a6accd;
    }

    #main {
        height: 1fr;
        background: #0b0b0c;
    }

    #columns {
        width: 1fr;
        height: 1fr;
        padding: 0 1 1 1;
    }

    #details {
        width: 34;
        min-width: 28;
        height: 1fr;
        background: #0b0b0c;
        border-left: solid #2c2c31;
        padding: 1 2;
        color: #d7deea;
    }

    .column {
        width: 1fr;
        min-width: 12;
        height: 100%;
        margin-right: 1;
        padding: 0 1;
        background: #0b0b0c;
        border-left: solid #25262b;
    }

    .column-header {
        height: 2;
        content-align: center middle;
        text-style: bold;
        color: #eef2ff;
        border-bottom: solid #25262b;
    }

    .issue-card {
        width: 100%;
        height: auto;
        min-height: 4;
        margin-bottom: 1;
        padding: 0 1;
        background: #0b0b0c;
        border: round #33343a;
        color: #d7deea;
    }

    .issue-card:hover {
        border: round #7aa2f7;
        background: #101114;
    }

    .issue-card:focus {
        border: heavy #8bd5ca;
    }

    .issue-card.selected {
        border: heavy #8bd5ca;
        background: #111317;
    }

    .empty-column {
        height: 4;
        content-align: center middle;
        color: #6b7280;
    }

    Footer {
        background: #0b0b0c;
        color: #a6accd;
    }
    """

    BINDINGS = [
        Binding("n", "new_item", "New"),
        Binding("enter", "edit_item", "Open"),
        Binding("e", "edit_item", "Edit", show=False),
        Binding("m", "move_item", "Move"),
        Binding("d", "done_item", "Done"),
        Binding("a", "archive_item", "Archive", show=False),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear", show=False),
        Binding("down", "next_card", "Next", priority=True),
        Binding("up", "previous_card", "Prev", priority=True),
        Binding("right", "next_column", "Column", priority=True),
        Binding("left", "previous_column", "Column", priority=True),
        Binding("tab", "next_card", "Next", show=False, priority=True),
        Binding("shift+tab", "previous_card", "Prev", show=False, priority=True),
        Binding("j", "next_card", "Next", show=False),
        Binding("k", "previous_card", "Prev", show=False),
        Binding("l", "next_column", "Column", show=False),
        Binding("h", "previous_column", "Column", show=False),
        Binding("r", "reload_board", "Reload", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, data_path: Path = DEFAULT_DATA_FILE) -> None:
        super().__init__()
        self.data_path = data_path
        self.board = load_board(data_path)
        self.search_text = ""
        self.selected_id: str | None = None

    def board_screen_active(self) -> bool:
        return not isinstance(self.screen, (ItemEditor, ConfirmArchive))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        board_only = {
            "next_card",
            "previous_card",
            "next_column",
            "previous_column",
            "focus_search",
            "clear_search",
            "new_item",
            "edit_item",
            "move_item",
            "done_item",
            "archive_item",
            "reload_board",
        }
        if action in board_only and not self.board_screen_active():
            return False
        return True

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("Miror Kanban", id="brand"),
            Input(placeholder="/ filter", id="search"),
            Static("", id="summary"),
            id="topbar",
        )
        yield Horizontal(
            Horizontal(id="columns"),
            Static("", id="details"),
            id="main",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self.rebuild_board(focus_selected=True)

    def all_active_items(self) -> list[dict[str, Any]]:
        return [item for item in self.board["items"] if not item.get("archived", False)]

    def visible_items(self) -> list[dict[str, Any]]:
        items = self.all_active_items()
        query = self.search_text.strip().lower()
        if query:
            items = [
                item
                for item in items
                if query
                in " ".join(
                    [
                        str(item.get("id", "")),
                        str(item.get("title", "")),
                        str(item.get("notes", "")),
                        str(item.get("owner", "")),
                        " ".join(item.get("tags", [])),
                    ]
                ).lower()
            ]
        return sort_items(items)

    def selected_item(self) -> dict[str, Any] | None:
        if not self.selected_id:
            return None
        for item in self.board["items"]:
            if item.get("id") == self.selected_id and not item.get("archived", False):
                return item
        return None

    async def rebuild_board(self, focus_selected: bool = False) -> None:
        items = self.visible_items()
        visible_ids = [item["id"] for item in items]
        if self.selected_id not in visible_ids:
            self.selected_id = visible_ids[0] if visible_ids else None

        columns = self.query_one("#columns", Horizontal)
        await columns.remove_children()
        by_status = {status: [] for status in VALID_STATUSES}
        for item in items:
            by_status.setdefault(item.get("status", "backlog"), []).append(item)

        for column in self.board.get("columns", []):
            status = column["id"]
            column_items = by_status.get(status, [])
            title = f"{column['name']}  {len(column_items)}"
            widgets: list[Any] = [Static(title, classes="column-header")]
            if column_items:
                widgets.extend(IssueCard(item, selected=item["id"] == self.selected_id) for item in column_items)
            else:
                widgets.append(Static("No items", classes="empty-column"))
            await columns.mount(VerticalScroll(*widgets, classes="column"))

        self.update_summary()
        self.update_detail()
        if focus_selected:
            self.focus_selected_card()

    def focus_selected_card(self) -> None:
        if not self.selected_id:
            return
        for card in self.query(IssueCard):
            if card.item["id"] == self.selected_id:
                card.focus()
                card.scroll_visible()
                return

    def set_selected(self, item_id: str | None, *, focus: bool = True) -> None:
        self.selected_id = item_id
        focused_card: IssueCard | None = None
        for card in self.query(IssueCard):
            is_selected = card.item["id"] == item_id
            card.set_class(is_selected, "selected")
            if is_selected:
                focused_card = card
        if focused_card and focus:
            focused_card.focus()
            focused_card.scroll_visible()
        self.update_summary()
        self.update_detail()

    def update_summary(self) -> None:
        active = self.all_active_items()
        visible = self.visible_items()
        total = len(active)
        done = len([item for item in active if item.get("status") == "done"])
        open_bugs = len([item for item in active if item.get("type") == "bug" and item.get("status") != "done"])
        p0 = len([item for item in active if item.get("priority") == "p0" and item.get("status") != "done"])
        percent = 0 if total == 0 else round(done * 100 / total)
        text = Text()
        text.append(f"{percent}% done", style="bold #8bd5ca")
        text.append(f"  {open_bugs} bugs", style="#ff6b6b" if open_bugs else "#8bd5ca")
        text.append(f"  {p0} P0", style="#ff5370" if p0 else "#8bd5ca")
        if self.selected_id:
            text.append(f"  {self.selected_id}", style="#89ddff")
        if self.search_text:
            text.append(f"  showing {len(visible)}/{total}", style="#a6accd")
        self.query_one("#summary", Static).update(text)

    def update_detail(self) -> None:
        item = self.selected_item()
        text = Text()
        if not item:
            text.append("No item selected", style="bold #a6accd")
            text.append("\n\nPress n to add a bug, feature, task, or idea.", style="#6b7280")
            self.query_one("#details", Static).update(text)
            return

        item_type = str(item.get("type", "task"))
        priority = str(item.get("priority", "p3"))
        text.append(str(item.get("id", "")), style="bold #89ddff")
        text.append("  ")
        text.append(priority.upper(), style=PRIORITY_STYLES.get(priority, "bold"))
        text.append("  ")
        text.append(item_type.upper(), style=TYPE_STYLES.get(item_type, "bold"))
        text.append("\n\n")
        text.append(str(item.get("title", "")), style="bold #eef2ff")
        text.append("\n\n")
        text.append("Status\n", style="bold #a6accd")
        text.append(label_for_status(str(item.get("status", ""))) + "\n\n", style="#d7deea")
        text.append("Owner\n", style="bold #a6accd")
        text.append((str(item.get("owner")) if item.get("owner") else "-") + "\n\n", style="#d7deea")
        text.append("Due\n", style="bold #a6accd")
        text.append((str(item.get("due")) if item.get("due") else "-") + "\n\n", style="#d7deea")
        text.append("Tags\n", style="bold #a6accd")
        tags = " ".join(f"#{tag}" for tag in item.get("tags", [])) or "-"
        text.append(tags + "\n\n", style="#c792ea")
        text.append("Notes\n", style="bold #a6accd")
        text.append((str(item.get("notes")) if item.get("notes") else "-") + "\n\n", style="#d7deea")
        text.append("Shortcuts\n", style="bold #a6accd")
        text.append("arrows/tab select   / filter   enter edit   m move   d done", style="#6b7280")
        self.query_one("#details", Static).update(text)

    def save(self) -> None:
        save_board(self.board, self.data_path)

    def notify_user(self, message: str, severity: str = "information") -> None:
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify(message, severity=severity)

    @on(IssueCard.Selected)
    def card_selected(self, event: IssueCard.Selected) -> None:
        self.set_selected(event.item_id)

    @on(Input.Changed, "#search")
    async def search_changed(self, event: Input.Changed) -> None:
        self.search_text = event.value
        await self.rebuild_board()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    async def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        if search.value:
            search.value = ""
        self.search_text = ""
        await self.rebuild_board(focus_selected=True)

    def action_new_item(self) -> None:
        default_status = "backlog"
        item = self.selected_item()
        if item:
            default_status = str(item.get("status", "backlog"))
        self.push_screen(ItemEditor(default_status=default_status), self.editor_saved)

    def action_edit_item(self) -> None:
        item = self.selected_item()
        if not item:
            self.notify_user("Select an item first.", "warning")
            return
        self.push_screen(ItemEditor(item=dict(item)), self.editor_saved)

    async def editor_saved(self, result: dict[str, Any] | None) -> None:
        if not result:
            return
        timestamp = now_iso()
        if result.get("_delete") and result.get("id"):
            item = self.find_item(str(result["id"]))
            if not item:
                return
            item["archived"] = True
            item["updated_at"] = timestamp
            self.save()
            self.selected_id = None
            await self.rebuild_board(focus_selected=True)
            return

        if result.get("id"):
            item = self.find_item(str(result["id"]))
            if not item:
                return
            item.update(
                {
                    "title": result["title"],
                    "type": result["type"],
                    "status": result["status"],
                    "priority": result["priority"],
                    "tags": result["tags"],
                    "owner": result["owner"],
                    "notes": result["notes"],
                    "due": result["due"],
                    "updated_at": timestamp,
                    "completed_at": timestamp if result["status"] == "done" else "",
                }
            )
            self.selected_id = str(item["id"])
        else:
            item = make_item(
                self.board,
                title=str(result["title"]),
                item_type=str(result["type"]),
                status=str(result["status"]),
                priority=str(result["priority"]),
                tags=list(result["tags"]),
                owner=str(result["owner"]),
                notes=str(result["notes"]),
                due=str(result["due"]),
            )
            self.board["items"].append(item)
            self.selected_id = str(item["id"])
        self.save()
        await self.rebuild_board(focus_selected=True)

    def find_item(self, item_id: str) -> dict[str, Any] | None:
        for item in self.board["items"]:
            if str(item.get("id")) == item_id:
                return item
        return None

    async def action_next_card(self) -> None:
        await self.select_by_offset(1)

    async def action_previous_card(self) -> None:
        await self.select_by_offset(-1)

    async def action_next_column(self) -> None:
        await self.select_column_by_offset(1)

    async def action_previous_column(self) -> None:
        await self.select_column_by_offset(-1)

    async def select_by_offset(self, offset: int) -> None:
        items = self.visible_items()
        if not items:
            return
        ids = [item["id"] for item in items]
        current = ids.index(self.selected_id) if self.selected_id in ids else 0
        self.set_selected(ids[(current + offset) % len(ids)])

    async def select_column_by_offset(self, offset: int) -> None:
        items = self.visible_items()
        if not items:
            return

        by_status = {status: [] for status in VALID_STATUSES}
        for item in items:
            by_status.setdefault(str(item.get("status", "backlog")), []).append(item)

        selected = self.selected_item()
        if selected:
            current_status = str(selected.get("status", "backlog"))
            current_items = by_status.get(current_status, [])
            current_row = next(
                (index for index, item in enumerate(current_items) if item["id"] == selected["id"]),
                0,
            )
            start_index = VALID_STATUSES.index(current_status) if current_status in VALID_STATUSES else 0
        else:
            current_row = 0
            start_index = 0

        for step in range(1, len(VALID_STATUSES) + 1):
            target_status = VALID_STATUSES[(start_index + offset * step) % len(VALID_STATUSES)]
            target_items = by_status.get(target_status, [])
            if target_items:
                self.set_selected(target_items[min(current_row, len(target_items) - 1)]["id"])
                break

    async def action_move_item(self) -> None:
        item = self.selected_item()
        if not item:
            self.notify_user("Select an item first.", "warning")
            return
        current = str(item.get("status", "backlog"))
        index = VALID_STATUSES.index(current) if current in VALID_STATUSES else 0
        next_status = VALID_STATUSES[min(index + 1, len(VALID_STATUSES) - 1)]
        item["status"] = next_status
        item["updated_at"] = now_iso()
        item["completed_at"] = now_iso() if next_status == "done" else ""
        self.save()
        await self.rebuild_board(focus_selected=True)

    async def action_done_item(self) -> None:
        item = self.selected_item()
        if not item:
            self.notify_user("Select an item first.", "warning")
            return
        timestamp = now_iso()
        item["status"] = "done"
        item["updated_at"] = timestamp
        item["completed_at"] = timestamp
        self.save()
        await self.rebuild_board(focus_selected=True)

    def action_archive_item(self) -> None:
        item = self.selected_item()
        if not item:
            self.notify_user("Select an item first.", "warning")
            return
        self.push_screen(ConfirmArchive(item), self.archive_confirmed)

    async def archive_confirmed(self, confirmed: bool) -> None:
        if not confirmed or not self.selected_id:
            return
        item = self.find_item(self.selected_id)
        if not item:
            return
        item["archived"] = True
        item["updated_at"] = now_iso()
        self.save()
        self.selected_id = None
        await self.rebuild_board(focus_selected=True)

    async def action_reload_board(self) -> None:
        self.board = load_board(self.data_path)
        await self.rebuild_board(focus_selected=True)
        self.notify_user("Board reloaded.")


def label_for_status(status: str) -> str:
    labels = {
        "backlog": "Backlog",
        "next": "Next Up",
        "doing": "In Progress",
        "testing": "Testing",
        "done": "Done",
    }
    return labels.get(status, status.title())


def run_tui(data_path: Path = DEFAULT_DATA_FILE) -> None:
    MirorKanbanApp(data_path=data_path).run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Modern terminal UI for Miror Kanban.")
    parser.add_argument("--data", default=str(DEFAULT_DATA_FILE))
    args = parser.parse_args()
    run_tui(Path(args.data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
