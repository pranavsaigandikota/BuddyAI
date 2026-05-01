"""
buddy_planner.py — Local task and calendar manager for Buddy AI.
Uses SQLite so data persists across sessions with no external dependencies.
Run standalone to test: python buddy_planner.py
"""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path(__file__).parent / "memory" / "buddy_planner.db"
DB_PATH.parent.mkdir(exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT NOT NULL,
            done      INTEGER NOT NULL DEFAULT 0,
            priority  TEXT NOT NULL DEFAULT 'normal',
            created   TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            event_date  TEXT NOT NULL,
            event_time  TEXT,
            notes       TEXT,
            created     TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


# ── Tasks ──────────────────────────────────────────────────────────────────────

def add_task(title: str, priority: str = "normal") -> str:
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (title, priority, created) VALUES (?, ?, ?)",
            (title.strip(), priority, datetime.now().isoformat())
        )
    return f"Task added: '{title}'"


def list_tasks(include_done: bool = False) -> str:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, done, priority FROM tasks WHERE done <= ? ORDER BY id DESC",
            (1 if include_done else 0,)
        ).fetchall()
    if not rows:
        return "No tasks." if include_done else "No pending tasks."
    parts = []
    for r in rows:
        status = "✓" if r["done"] else "○"
        parts.append(f"[{status}] #{r['id']} {r['title']} ({r['priority']})")
    return "\n".join(parts)


def complete_task(task_id: int) -> str:
    with _get_conn() as conn:
        conn.execute("UPDATE tasks SET done=1 WHERE id=?", (task_id,))
        row = conn.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone()
    return f"Task #{task_id} '{row['title'] if row else '?'}' marked done."


def delete_task(task_id: int) -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone()
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    return f"Task #{task_id} '{row['title'] if row else '?'}' deleted."


# ── Events ─────────────────────────────────────────────────────────────────────

def add_event(title: str, event_date: str, event_time: str = "", notes: str = "") -> str:
    """
    event_date: any string like 'tomorrow', '2025-06-01', 'Monday', etc.
    We store it as-is since we don't need strict parsing.
    """
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO events (title, event_date, event_time, notes, created) VALUES (?, ?, ?, ?, ?)",
            (title.strip(), event_date.strip(), event_time.strip(), notes.strip(), datetime.now().isoformat())
        )
    time_str = f" at {event_time}" if event_time else ""
    return f"Event added: '{title}' on {event_date}{time_str}"


def list_events(when: str = "upcoming") -> str:
    """
    when: 'today', 'upcoming', or 'all'
    """
    today = date.today().isoformat()
    with _get_conn() as conn:
        if when == "today":
            rows = conn.execute(
                "SELECT * FROM events WHERE event_date = ? ORDER BY event_time",
                (today,)
            ).fetchall()
        elif when == "all":
            rows = conn.execute("SELECT * FROM events ORDER BY event_date, event_time").fetchall()
        else:  # upcoming
            rows = conn.execute(
                "SELECT * FROM events WHERE event_date >= ? ORDER BY event_date, event_time LIMIT 10",
                (today,)
            ).fetchall()
    if not rows:
        return f"No {when} events."
    parts = []
    for r in rows:
        time_str = f" at {r['event_time']}" if r["event_time"] else ""
        note_str = f" — {r['notes']}" if r["notes"] else ""
        parts.append(f"#{r['id']} {r['title']} on {r['event_date']}{time_str}{note_str}")
    return "\n".join(parts)


def delete_event(event_id: int) -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT title FROM events WHERE id=?", (event_id,)).fetchone()
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    return f"Event #{event_id} '{row['title'] if row else '?'}' deleted."


# ── Unified interface for tool executor ────────────────────────────────────────

def handle_planner_tool(action: str, arg: str) -> str:
    """
    Route planner tool calls from the main server.
    action: add_task | list_tasks | complete_task | delete_task |
            add_event | list_events | delete_event
    arg: JSON string or plain text depending on action
    """
    try:
        if action == "add_task":
            # arg can be plain text or JSON {"title":..., "priority":...}
            try:
                obj = json.loads(arg)
                return add_task(obj.get("title", arg), obj.get("priority", "normal"))
            except Exception:
                return add_task(arg)

        elif action == "list_tasks":
            return list_tasks()

        elif action == "complete_task":
            return complete_task(int(arg))

        elif action == "delete_task":
            return delete_task(int(arg))

        elif action == "add_event":
            try:
                obj = json.loads(arg)
                return add_event(
                    obj.get("title", ""),
                    obj.get("date", "TBD"),
                    obj.get("time", ""),
                    obj.get("notes", "")
                )
            except Exception:
                return add_event(arg, "TBD")

        elif action == "list_events":
            when = arg.strip().lower() if arg.strip() else "upcoming"
            return list_events(when)

        elif action == "delete_event":
            return delete_event(int(arg))

    except Exception as e:
        return f"Planner error: {e}"

    return f"Unknown planner action: {action}"


if __name__ == "__main__":
    print("=== Planner Test ===")
    print(add_task("Fix the leaked dimension portal", "high"))
    print(add_task("Buy Szechuan sauce"))
    print(add_event("Council of Ricks meeting", "tomorrow", "3:00 PM", "Bring portal gun"))
    print()
    print("Tasks:")
    print(list_tasks())
    print()
    print("Events:")
    print(list_events())
