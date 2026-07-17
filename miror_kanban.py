#!/usr/bin/env python3
"""Terminal Kanban board for Miror Kanban.

The default entrypoint launches the modern Textual app. The direct subcommands
remain dependency-free for quick automation and exports.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import json
import os
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


APP_NAME = "Miror Kanban"
DEFAULT_DATA_FILE = Path(__file__).resolve().parent / "miror_kanban.json"
VALID_TYPES = ("bug", "feature", "task", "idea")
VALID_PRIORITIES = ("p0", "p1", "p2", "p3")
VALID_STATUSES = ("backlog", "next", "doing", "testing", "done")


DEFAULT_BOARD: dict[str, Any] = {
    "version": 1,
    "next_id": 1,
    "columns": [
        {"id": "backlog", "name": "Backlog", "color": "blue"},
        {"id": "next", "name": "Next Up", "color": "cyan"},
        {"id": "doing", "name": "In Progress", "color": "yellow"},
        {"id": "testing", "name": "Testing", "color": "magenta"},
        {"id": "done", "name": "Done", "color": "green"},
    ],
    "items": [],
}


ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}

TYPE_COLORS = {
    "bug": "red",
    "feature": "green",
    "task": "cyan",
    "idea": "magenta",
}

PRIORITY_COLORS = {
    "p0": "red",
    "p1": "yellow",
    "p2": "cyan",
    "p3": "white",
}

PRIORITY_RANK = {priority: index for index, priority in enumerate(VALID_PRIORITIES)}


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def color(self, text: str, color: str | None = None, *, bold: bool = False, dim: bool = False) -> str:
        if not self.enabled:
            return text
        prefix = ""
        if bold:
            prefix += ANSI["bold"]
        if dim:
            prefix += ANSI["dim"]
        if color:
            prefix += ANSI.get(color, "")
        return f"{prefix}{text}{ANSI['reset']}" if prefix else text


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def wants_color(args: argparse.Namespace) -> bool:
    if getattr(args, "no_color", False) or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def load_board(path: Path) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(DEFAULT_BOARD)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not read {path}: invalid JSON at line {exc.lineno}.") from exc

    board = copy.deepcopy(DEFAULT_BOARD)
    board.update(data)
    board["columns"] = data.get("columns") or DEFAULT_BOARD["columns"]
    board["items"] = data.get("items") or []
    board["next_id"] = max(int(data.get("next_id", 1)), next_id_from_items(board["items"]))
    return board


def save_board(board: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def next_id_from_items(items: Iterable[dict[str, Any]]) -> int:
    largest = 0
    for item in items:
        raw_id = str(item.get("id", ""))
        if raw_id.startswith("MIR-"):
            try:
                largest = max(largest, int(raw_id.split("-", 1)[1]))
            except ValueError:
                pass
    return largest + 1


def next_item_id(board: dict[str, Any]) -> str:
    number = int(board.get("next_id", 1))
    board["next_id"] = number + 1
    return f"MIR-{number:03d}"


def normalize_choice(value: str | None, valid: tuple[str, ...], field_name: str) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if value not in valid:
        raise SystemExit(f"Invalid {field_name}: {value}. Expected one of: {', '.join(valid)}.")
    return value


def parse_tags(values: Iterable[str] | None) -> list[str]:
    tags: list[str] = []
    for value in values or []:
        for tag in value.split(","):
            clean = tag.strip().lower()
            if clean and clean not in tags:
                tags.append(clean)
    return tags


def split_title(words: list[str] | None) -> str:
    return " ".join(words or []).strip()


def get_item(board: dict[str, Any], item_id: str) -> dict[str, Any]:
    item_id = item_id.upper()
    for item in board["items"]:
        if str(item.get("id", "")).upper() == item_id:
            return item
    raise SystemExit(f"No item found for {item_id}.")


def make_item(
    board: dict[str, Any],
    title: str,
    item_type: str,
    status: str,
    priority: str,
    tags: list[str],
    owner: str,
    notes: str,
    due: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "id": next_item_id(board),
        "title": title,
        "type": item_type,
        "status": status,
        "priority": priority,
        "tags": tags,
        "owner": owner.strip(),
        "notes": notes.strip(),
        "due": due.strip(),
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": timestamp if status == "done" else "",
        "archived": False,
    }


def filtered_items(board: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    items = list(board["items"])

    if not getattr(args, "all", False):
        items = [item for item in items if not item.get("archived", False)]

    item_type = getattr(args, "type", None)
    priority = getattr(args, "priority", None)
    owner = getattr(args, "owner", None)
    tag = getattr(args, "tag", None)
    status = getattr(args, "status", None)

    if isinstance(tag, list):
        tag = None

    if item_type:
        items = [item for item in items if item.get("type") == item_type]
    if priority:
        items = [item for item in items if item.get("priority") == priority]
    if owner:
        owner_lower = owner.lower()
        items = [item for item in items if owner_lower in str(item.get("owner", "")).lower()]
    if tag:
        tag_lower = tag.lower()
        items = [item for item in items if tag_lower in item.get("tags", [])]
    if status:
        items = [item for item in items if item.get("status") == status]
    return sort_items(items)


def sort_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            PRIORITY_RANK.get(item.get("priority", "p3"), 99),
            item.get("due") or "9999-99-99",
            item.get("created_at", ""),
        ),
    )


def status_order(board: dict[str, Any]) -> list[str]:
    return [column["id"] for column in board.get("columns", [])]


def status_name(board: dict[str, Any], status: str) -> str:
    for column in board.get("columns", []):
        if column["id"] == status:
            return column["name"]
    return status.title()


def status_color(board: dict[str, Any], status: str) -> str | None:
    for column in board.get("columns", []):
        if column["id"] == status:
            return column.get("color")
    return None


def visible_len(text: str) -> int:
    length = 0
    in_escape = False
    for char in text:
        if char == "\033":
            in_escape = True
        elif in_escape and char == "m":
            in_escape = False
        elif not in_escape:
            length += 1
    return length


def pad_ansi(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_len(text))


def trim_plain(text: str, width: int) -> str:
    if width <= 0:
        return ""
    clean = " ".join(str(text).split())
    if len(clean) <= width:
        return clean
    if width <= 3:
        return clean[:width]
    return clean[: width - 3].rstrip() + "..."


def wrap_plain(text: str, width: int, max_lines: int | None = None) -> list[str]:
    if not text:
        return [""]
    wrapped = textwrap.wrap(
        " ".join(str(text).split()),
        width=max(1, width),
        break_long_words=True,
        replace_whitespace=True,
    )
    if not wrapped:
        wrapped = [""]
    if max_lines and len(wrapped) > max_lines:
        wrapped = wrapped[:max_lines]
        wrapped[-1] = trim_plain(wrapped[-1], width)
    return wrapped


def line_box(content: str, width: int, style: Style | None = None, color: str | None = None) -> str:
    inner_width = width - 4
    content = trim_plain(content, inner_width)
    if style and color:
        content = style.color(content, color)
    return f"| {pad_ansi(content, inner_width)} |"


def border(width: int) -> str:
    return "+" + "-" * max(0, width - 2) + "+"


def make_progress_bar(done: int, total: int, width: int = 24) -> str:
    if total == 0:
        filled = 0
    else:
        filled = round(width * done / total)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def summary_line(items: list[dict[str, Any]], style: Style) -> str:
    active = [item for item in items if not item.get("archived", False)]
    done = len([item for item in active if item.get("status") == "done"])
    total = len(active)
    bugs = len([item for item in active if item.get("type") == "bug" and item.get("status") != "done"])
    features = len([item for item in active if item.get("type") == "feature" and item.get("status") != "done"])
    p0 = len([item for item in active if item.get("priority") == "p0" and item.get("status") != "done"])
    percent = 0 if total == 0 else round(done * 100 / total)
    bar = make_progress_bar(done, total)
    pieces = [
        style.color(APP_NAME, "cyan", bold=True),
        f"{bar} {percent:>3}% done",
        style.color(f"{bugs} open bugs", "red" if bugs else "green"),
        style.color(f"{features} feature ideas", "green"),
        style.color(f"{p0} P0", "red" if p0 else "green"),
    ]
    return "  ".join(pieces)


def render_card(item: dict[str, Any], width: int, style: Style) -> list[str]:
    inner = width - 4
    item_type = str(item.get("type", "task"))
    priority = str(item.get("priority", "p3"))
    type_label = style.color(item_type.upper(), TYPE_COLORS.get(item_type), bold=True)
    priority_label = style.color(priority.upper(), PRIORITY_COLORS.get(priority), bold=True)
    header = f"{item.get('id')} [{priority_label} {type_label}]"
    lines = [line_box(header, width)]

    title_width = inner - 2
    title_lines = wrap_plain(item.get("title", ""), title_width, max_lines=3)
    for index, title_line in enumerate(title_lines):
        marker = ">" if index == 0 else " "
        lines.append(line_box(f"{marker} {title_line}", width))

    meta_bits = []
    if item.get("owner"):
        meta_bits.append(f"@{item['owner']}")
    if item.get("due"):
        meta_bits.append(f"due {item['due']}")
    if item.get("tags"):
        meta_bits.append("#" + " #".join(item["tags"][:3]))
    if meta_bits:
        lines.append(line_box(" ".join(meta_bits), width, style, "white"))

    if item.get("notes"):
        note = trim_plain(str(item["notes"]), inner - 8)
        if note:
            lines.append(line_box(f"note: {note}", width, style, "white"))
    lines.append(border(width))
    return lines


def render_column(board: dict[str, Any], column: dict[str, Any], items: list[dict[str, Any]], width: int, style: Style) -> list[str]:
    column_items = [item for item in items if item.get("status") == column["id"]]
    title = f" {column['name']} ({len(column_items)}) "
    color = column.get("color")
    lines = [border(width), line_box(title, width, style, color)]
    lines.append(border(width))
    if not column_items:
        lines.append(line_box("empty", width, style, "white"))
        lines.append(border(width))
        return lines

    for item in column_items:
        lines.extend(render_card(item, width, style))
    return lines


def render_board(board: dict[str, Any], items: list[dict[str, Any]], style: Style) -> str:
    terminal_width = shutil.get_terminal_size((120, 32)).columns
    usable_width = max(60, terminal_width)
    gap = 2
    min_column_width = 28
    max_columns = max(1, (usable_width + gap) // (min_column_width + gap))
    columns = board.get("columns", [])
    columns_per_row = min(len(columns), max_columns)
    column_width = max(min_column_width, (usable_width - gap * (columns_per_row - 1)) // columns_per_row)
    column_width = min(40, column_width)

    output = [summary_line(board["items"], style), ""]
    for start in range(0, len(columns), columns_per_row):
        group = columns[start : start + columns_per_row]
        rendered_columns = [render_column(board, column, items, column_width, style) for column in group]
        height = max(len(lines) for lines in rendered_columns)
        for lines in rendered_columns:
            lines.extend([" " * column_width] * (height - len(lines)))
        for row_index in range(height):
            output.append((" " * gap).join(lines[row_index] for lines in rendered_columns).rstrip())
        output.append("")
    return "\n".join(output).rstrip() + "\n"


def render_table(board: dict[str, Any], items: list[dict[str, Any]], style: Style) -> str:
    if not items:
        return "No items match.\n"
    terminal_width = shutil.get_terminal_size((120, 32)).columns
    title_width = max(24, min(64, terminal_width - 58))
    rows = [
        f"{'ID':<8} {'Type':<8} {'Pri':<4} {'Status':<12} {'Title':<{title_width}} Tags",
        "-" * min(terminal_width, 120),
    ]
    for item in items:
        item_type = style.color(str(item.get("type", "")), TYPE_COLORS.get(item.get("type", "")))
        priority = style.color(str(item.get("priority", "")).upper(), PRIORITY_COLORS.get(item.get("priority", "")))
        status = status_name(board, str(item.get("status", "")))
        tags = ", ".join(item.get("tags", []))
        rows.append(
            f"{item.get('id', ''):<8} "
            f"{pad_ansi(item_type, 8)} "
            f"{pad_ansi(priority, 4)} "
            f"{status:<12} "
            f"{trim_plain(item.get('title', ''), title_width):<{title_width}} "
            f"{tags}"
        )
    return "\n".join(rows) + "\n"


def render_details(board: dict[str, Any], item: dict[str, Any], style: Style) -> str:
    item_type = style.color(str(item.get("type", "")).upper(), TYPE_COLORS.get(item.get("type", "")), bold=True)
    priority = style.color(str(item.get("priority", "")).upper(), PRIORITY_COLORS.get(item.get("priority", "")), bold=True)
    lines = [
        f"{style.color(str(item.get('id')), 'cyan', bold=True)}  {priority} {item_type}",
        f"Title: {item.get('title', '')}",
        f"Status: {status_name(board, str(item.get('status', '')))}",
        f"Owner: {item.get('owner') or '-'}",
        f"Due: {item.get('due') or '-'}",
        f"Tags: {', '.join(item.get('tags', [])) or '-'}",
        f"Created: {item.get('created_at') or '-'}",
        f"Updated: {item.get('updated_at') or '-'}",
    ]
    if item.get("completed_at"):
        lines.append(f"Completed: {item.get('completed_at')}")
    lines.append("")
    lines.append("Notes:")
    lines.append(item.get("notes") or "-")
    return "\n".join(lines) + "\n"


def render_report(board: dict[str, Any], style: Style, source_items: list[dict[str, Any]] | None = None) -> str:
    source = board["items"] if source_items is None else source_items
    active = [item for item in source if not item.get("archived", False)]
    by_status = {column["id"]: 0 for column in board.get("columns", [])}
    by_type = {item_type: 0 for item_type in VALID_TYPES}
    by_priority = {priority: 0 for priority in VALID_PRIORITIES}
    for item in active:
        by_status[item.get("status", "")] = by_status.get(item.get("status", ""), 0) + 1
        by_type[item.get("type", "task")] = by_type.get(item.get("type", "task"), 0) + 1
        by_priority[item.get("priority", "p3")] = by_priority.get(item.get("priority", "p3"), 0) + 1

    done = by_status.get("done", 0)
    total = len(active)
    lines = [
        summary_line(source, style),
        "",
        "By status",
    ]
    for column in board.get("columns", []):
        lines.append(f"  {column['name']:<12} {by_status.get(column['id'], 0):>3}")

    lines.extend(["", "By type"])
    for item_type in VALID_TYPES:
        label = style.color(item_type, TYPE_COLORS.get(item_type))
        lines.append(f"  {pad_ansi(label, 12)} {by_type.get(item_type, 0):>3}")

    lines.extend(["", "By priority"])
    for priority in VALID_PRIORITIES:
        label = style.color(priority.upper(), PRIORITY_COLORS.get(priority))
        lines.append(f"  {pad_ansi(label, 12)} {by_priority.get(priority, 0):>3}")

    lines.extend(
        [
            "",
            f"Completion: {done}/{total} {make_progress_bar(done, total, 32)}",
            f"Archived: {len([item for item in source if item.get('archived', False)])}",
        ]
    )
    return "\n".join(lines) + "\n"


def export_markdown(board: dict[str, Any], items: list[dict[str, Any]]) -> str:
    lines = ["# Miror Kanban", ""]
    for column in board.get("columns", []):
        column_items = [item for item in items if item.get("status") == column["id"]]
        lines.append(f"## {column['name']} ({len(column_items)})")
        lines.append("")
        if not column_items:
            lines.append("_No items._")
            lines.append("")
            continue
        for item in column_items:
            tags = " ".join(f"#{tag}" for tag in item.get("tags", []))
            owner = f" @{item['owner']}" if item.get("owner") else ""
            due = f" due:{item['due']}" if item.get("due") else ""
            lines.append(
                f"- **{item['id']}** [{item.get('priority', '').upper()} {item.get('type', '').upper()}] "
                f"{item.get('title', '')}{owner}{due} {tags}".rstrip()
            )
            if item.get("notes"):
                lines.append(f"  - {item['notes']}")
        lines.append("")
    return "\n".join(lines)


def command_board(args: argparse.Namespace, board: dict[str, Any], style: Style) -> None:
    print(render_board(board, filtered_items(board, args), style), end="")


def command_list(args: argparse.Namespace, board: dict[str, Any], style: Style) -> None:
    print(render_table(board, filtered_items(board, args), style), end="")


def command_report(args: argparse.Namespace, board: dict[str, Any], style: Style) -> None:
    print(render_report(board, style, filtered_items(board, args)), end="")


def command_search(args: argparse.Namespace, board: dict[str, Any], style: Style) -> None:
    query = args.query.lower()
    args.all = getattr(args, "all", False)
    matches = []
    for item in filtered_items(board, args):
        haystack = " ".join(
            [
                item.get("id", ""),
                item.get("title", ""),
                item.get("notes", ""),
                item.get("owner", ""),
                " ".join(item.get("tags", [])),
            ]
        ).lower()
        if query in haystack:
            matches.append(item)
    print(render_table(board, matches, style), end="")


def command_show(args: argparse.Namespace, board: dict[str, Any], style: Style) -> None:
    print(render_details(board, get_item(board, args.id), style), end="")


def command_add(args: argparse.Namespace, board: dict[str, Any], data_path: Path, style: Style) -> None:
    title = args.title_text or split_title(args.title)
    if not title:
        raise SystemExit("Add needs a title. Example: python miror_kanban.py add bug Fix the login form")

    item = make_item(
        board,
        title=title,
        item_type=args.type,
        status=args.status,
        priority=args.priority,
        tags=parse_tags(args.tag),
        owner=args.owner or "",
        notes=args.notes or "",
        due=args.due or "",
    )
    board["items"].append(item)
    save_board(board, data_path)
    print(f"Added {item['id']}: {item['title']}")
    print(render_board(board, filtered_items(board, empty_filters()), style), end="")


def command_move(args: argparse.Namespace, board: dict[str, Any], data_path: Path) -> None:
    item = get_item(board, args.id)
    item["status"] = args.status
    item["updated_at"] = now_iso()
    item["completed_at"] = now_iso() if args.status == "done" else ""
    save_board(board, data_path)
    print(f"Moved {item['id']} to {args.status}.")


def command_done(args: argparse.Namespace, board: dict[str, Any], data_path: Path) -> None:
    item = get_item(board, args.id)
    timestamp = now_iso()
    item["status"] = "done"
    item["updated_at"] = timestamp
    item["completed_at"] = timestamp
    save_board(board, data_path)
    print(f"Completed {item['id']}.")


def command_archive(args: argparse.Namespace, board: dict[str, Any], data_path: Path) -> None:
    item = get_item(board, args.id)
    item["archived"] = True
    item["updated_at"] = now_iso()
    save_board(board, data_path)
    print(f"Archived {item['id']}.")


def command_delete(args: argparse.Namespace, board: dict[str, Any], data_path: Path) -> None:
    item = get_item(board, args.id)
    if not args.yes:
        raise SystemExit(f"Refusing to delete {item['id']} without --yes. Use archive for normal cleanup.")
    board["items"] = [candidate for candidate in board["items"] if candidate is not item]
    save_board(board, data_path)
    print(f"Deleted {item['id']}.")


def command_edit(args: argparse.Namespace, board: dict[str, Any], data_path: Path) -> None:
    item = get_item(board, args.id)
    changed = False
    updates = {
        "title": args.title_text,
        "type": args.type,
        "status": args.status,
        "priority": args.priority,
        "owner": args.owner,
        "notes": args.notes,
        "due": args.due,
    }
    for field, value in updates.items():
        if value is not None:
            item[field] = value.strip() if isinstance(value, str) else value
            changed = True

    if args.tag is not None:
        item["tags"] = parse_tags(args.tag)
        changed = True
    if args.add_tag:
        item["tags"] = sorted(set(item.get("tags", [])) | set(parse_tags(args.add_tag)))
        changed = True
    if args.remove_tag:
        remove = set(parse_tags(args.remove_tag))
        item["tags"] = [tag for tag in item.get("tags", []) if tag not in remove]
        changed = True

    if item.get("status") == "done" and not item.get("completed_at"):
        item["completed_at"] = now_iso()
    elif item.get("status") != "done":
        item["completed_at"] = ""

    if changed:
        item["updated_at"] = now_iso()
        save_board(board, data_path)
        print(f"Updated {item['id']}.")
    else:
        print("No changes supplied.")


def command_export(args: argparse.Namespace, board: dict[str, Any]) -> None:
    markdown = export_markdown(board, filtered_items(board, args))
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote {output_path}.")
    else:
        print(markdown)


def empty_filters() -> argparse.Namespace:
    return argparse.Namespace(all=False, type=None, priority=None, owner=None, tag=None, status=None)


def prompt_choice(prompt: str, valid: tuple[str, ...], default: str) -> str:
    suffix = "/".join(valid)
    while True:
        value = input(f"{prompt} ({suffix}) [{default}]: ").strip().lower()
        if not value:
            return default
        if value in valid:
            return value
        print(f"Choose one of: {', '.join(valid)}")


def prompt_free(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def pause() -> None:
    input("\nPress Enter to continue...")


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def interactive_add(board: dict[str, Any], data_path: Path) -> None:
    title = prompt_free("Title")
    if not title:
        print("Cancelled: title is required.")
        pause()
        return
    item_type = prompt_choice("Type", VALID_TYPES, "task")
    priority = prompt_choice("Priority", VALID_PRIORITIES, "p2")
    status = prompt_choice("Status", VALID_STATUSES, "backlog")
    owner = prompt_free("Owner")
    due = prompt_free("Due date")
    tags = parse_tags([prompt_free("Tags, comma separated")])
    notes = prompt_free("Notes")
    item = make_item(board, title, item_type, status, priority, tags, owner, notes, due)
    board["items"].append(item)
    save_board(board, data_path)
    print(f"Added {item['id']}.")
    pause()


def interactive_move(board: dict[str, Any], data_path: Path) -> None:
    item_id = prompt_free("Item ID").upper()
    if not item_id:
        return
    try:
        item = get_item(board, item_id)
    except SystemExit as exc:
        print(exc)
        pause()
        return
    status = prompt_choice("New status", VALID_STATUSES, item.get("status", "backlog"))
    item["status"] = status
    item["updated_at"] = now_iso()
    item["completed_at"] = now_iso() if status == "done" else ""
    save_board(board, data_path)
    print(f"Moved {item['id']} to {status}.")
    pause()


def interactive_edit(board: dict[str, Any], data_path: Path) -> None:
    item_id = prompt_free("Item ID").upper()
    if not item_id:
        return
    try:
        item = get_item(board, item_id)
    except SystemExit as exc:
        print(exc)
        pause()
        return

    print("Leave a field blank to keep the current value.")
    item["title"] = prompt_free("Title", item.get("title", ""))
    item["type"] = prompt_choice("Type", VALID_TYPES, item.get("type", "task"))
    item["priority"] = prompt_choice("Priority", VALID_PRIORITIES, item.get("priority", "p2"))
    item["status"] = prompt_choice("Status", VALID_STATUSES, item.get("status", "backlog"))
    item["owner"] = prompt_free("Owner", item.get("owner", ""))
    item["due"] = prompt_free("Due date", item.get("due", ""))
    tag_text = prompt_free("Tags, comma separated", ", ".join(item.get("tags", [])))
    item["tags"] = parse_tags([tag_text])
    item["notes"] = prompt_free("Notes", item.get("notes", ""))
    item["updated_at"] = now_iso()
    item["completed_at"] = now_iso() if item["status"] == "done" else ""
    save_board(board, data_path)
    print(f"Updated {item['id']}.")
    pause()


def interactive_show(board: dict[str, Any], style: Style) -> None:
    item_id = prompt_free("Item ID").upper()
    if not item_id:
        return
    try:
        print()
        print(render_details(board, get_item(board, item_id), style), end="")
    except SystemExit as exc:
        print(exc)
    pause()


def interactive_archive(board: dict[str, Any], data_path: Path) -> None:
    item_id = prompt_free("Item ID").upper()
    if not item_id:
        return
    try:
        item = get_item(board, item_id)
    except SystemExit as exc:
        print(exc)
        pause()
        return
    confirm = prompt_free(f"Archive {item['id']}? Type yes")
    if confirm.lower() != "yes":
        print("Cancelled.")
        pause()
        return
    item["archived"] = True
    item["updated_at"] = now_iso()
    save_board(board, data_path)
    print(f"Archived {item['id']}.")
    pause()


def interactive_filter(current: argparse.Namespace) -> argparse.Namespace:
    print("Blank values clear the matching filter.")
    current.type = prompt_free("Type filter", getattr(current, "type", "") or "") or None
    current.priority = prompt_free("Priority filter", getattr(current, "priority", "") or "") or None
    current.owner = prompt_free("Owner filter", getattr(current, "owner", "") or "") or None
    current.tag = prompt_free("Tag filter", getattr(current, "tag", "") or "") or None
    current.status = prompt_free("Status filter", getattr(current, "status", "") or "") or None

    for field, valid in (("type", VALID_TYPES), ("priority", VALID_PRIORITIES), ("status", VALID_STATUSES)):
        value = getattr(current, field, None)
        if value and value not in valid:
            print(f"Ignoring invalid {field}: {value}")
            setattr(current, field, None)
    return current


def interactive(args: argparse.Namespace, board: dict[str, Any], data_path: Path, style: Style) -> None:
    filters = argparse.Namespace(all=False, type=None, priority=None, owner=None, tag=None, status=None)
    while True:
        clear_screen()
        print(render_board(board, filtered_items(board, filters), style), end="")
        filter_bits = [
            f"{name}={getattr(filters, name)}"
            for name in ("type", "priority", "status", "owner", "tag")
            if getattr(filters, name, None)
        ]
        if filter_bits:
            print("Filters: " + ", ".join(filter_bits))
        print("Actions: [a]dd  [m]ove  [e]dit  [s]how  [f]ilter  [r]eport  [x]archive  [q]uit")
        choice = input("> ").strip().lower()
        if choice in ("q", "quit", "exit"):
            return
        if choice in ("a", "add"):
            interactive_add(board, data_path)
        elif choice in ("m", "move"):
            interactive_move(board, data_path)
        elif choice in ("e", "edit"):
            interactive_edit(board, data_path)
        elif choice in ("s", "show"):
            interactive_show(board, style)
        elif choice in ("f", "filter"):
            filters = interactive_filter(filters)
            pause()
        elif choice in ("r", "report"):
            print()
            print(render_report(board, style), end="")
            pause()
        elif choice in ("x", "archive"):
            interactive_archive(board, data_path)
        elif choice:
            print(f"Unknown action: {choice}")
            pause()


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="include archived items")
    parser.add_argument("--type", choices=VALID_TYPES, help="filter by item type")
    parser.add_argument("--priority", choices=VALID_PRIORITIES, help="filter by priority")
    parser.add_argument("--status", choices=VALID_STATUSES, help="filter by status")
    parser.add_argument("--owner", help="filter by owner text")
    parser.add_argument("--tag", help="filter by tag")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Miror Kanban terminal project board.")
    parser.add_argument("--data", default=str(DEFAULT_DATA_FILE), help=f"board data file (default: {DEFAULT_DATA_FILE})")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    subparsers = parser.add_subparsers(dest="command")

    board_parser = subparsers.add_parser("board", help="show the visual board")
    add_filter_args(board_parser)

    classic_parser = subparsers.add_parser("classic", help="run the old dependency-free menu")
    add_filter_args(classic_parser)

    list_parser = subparsers.add_parser("list", help="show matching items as a table")
    add_filter_args(list_parser)

    report_parser = subparsers.add_parser("report", help="show progress summary")
    add_filter_args(report_parser)

    search_parser = subparsers.add_parser("search", help="search title, notes, owner, tags, and ID")
    search_parser.add_argument("query")
    add_filter_args(search_parser)

    show_parser = subparsers.add_parser("show", help="show one item in detail")
    show_parser.add_argument("id")

    add_parser = subparsers.add_parser("add", help="add a new item")
    add_parser.add_argument("title", nargs="*", help="title words")
    add_parser.add_argument("--title", dest="title_text", help="title text")
    add_parser.add_argument("--type", choices=VALID_TYPES, default="task")
    add_parser.add_argument("--status", choices=VALID_STATUSES, default="backlog")
    add_parser.add_argument("--priority", choices=VALID_PRIORITIES, default="p2")
    add_parser.add_argument("--owner", default="")
    add_parser.add_argument("--tag", action="append", help="tag or comma-separated tags; repeatable")
    add_parser.add_argument("--notes", default="")
    add_parser.add_argument("--due", default="", help="free-form or YYYY-MM-DD due date")

    move_parser = subparsers.add_parser("move", help="move an item to another column")
    move_parser.add_argument("id")
    move_parser.add_argument("status", choices=VALID_STATUSES)

    done_parser = subparsers.add_parser("done", help="mark an item done")
    done_parser.add_argument("id")

    edit_parser = subparsers.add_parser("edit", help="edit item fields")
    edit_parser.add_argument("id")
    edit_parser.add_argument("--title", dest="title_text")
    edit_parser.add_argument("--type", choices=VALID_TYPES)
    edit_parser.add_argument("--status", choices=VALID_STATUSES)
    edit_parser.add_argument("--priority", choices=VALID_PRIORITIES)
    edit_parser.add_argument("--owner")
    edit_parser.add_argument("--tag", action="append", help="replace tags with this list")
    edit_parser.add_argument("--add-tag", action="append", help="add a tag or comma-separated tags")
    edit_parser.add_argument("--remove-tag", action="append", help="remove a tag or comma-separated tags")
    edit_parser.add_argument("--notes")
    edit_parser.add_argument("--due")

    archive_parser = subparsers.add_parser("archive", help="archive an item")
    archive_parser.add_argument("id")

    delete_parser = subparsers.add_parser("delete", help="permanently delete an item")
    delete_parser.add_argument("id")
    delete_parser.add_argument("--yes", action="store_true", help="confirm permanent deletion")

    export_parser = subparsers.add_parser("export", help="export the board as markdown")
    add_filter_args(export_parser)
    export_parser.add_argument("--output", help="write markdown to a file instead of stdout")

    return parser


def launch_tui(data_path: Path) -> int:
    try:
        from miror_kanban_tui import run_tui
    except ModuleNotFoundError as exc:
        if exc.name in {"textual", "rich"}:
            print("The modern board app needs Textual installed.")
            print()
            print("Install it with:")
            print("  python -m pip install -r requirements.txt")
            print()
            print("Then run:")
            print("  python miror_kanban.py")
            return 1
        raise

    run_tui(data_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    enable_windows_ansi()
    parser = build_parser()
    args = parser.parse_args(argv)
    data_path = Path(args.data)

    command = args.command
    if command is None:
        return launch_tui(data_path)

    board = load_board(data_path)
    style = Style(wants_color(args))

    if command == "classic":
        interactive(args, board, data_path, style)
    elif command == "board":
        command_board(args, board, style)
    elif command == "list":
        command_list(args, board, style)
    elif command == "report":
        command_report(args, board, style)
    elif command == "search":
        command_search(args, board, style)
    elif command == "show":
        command_show(args, board, style)
    elif command == "add":
        command_add(args, board, data_path, style)
    elif command == "move":
        command_move(args, board, data_path)
    elif command == "done":
        command_done(args, board, data_path)
    elif command == "edit":
        command_edit(args, board, data_path)
    elif command == "archive":
        command_archive(args, board, data_path)
    elif command == "delete":
        command_delete(args, board, data_path)
    elif command == "export":
        command_export(args, board)
    else:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
