from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                identity TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                url TEXT NOT NULL,
                caption TEXT NOT NULL,
                posted_at REAL NOT NULL,
                topic TEXT NOT NULL DEFAULT 'cat'
            )
            """
        )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(posts)")}
        if "topic" not in columns:
            self.conn.execute("ALTER TABLE posts ADD COLUMN topic TEXT NOT NULL DEFAULT 'cat'")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def was_posted(self, identity: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM posts WHERE identity = ?", (identity,)).fetchone()
        return row is not None

    def mark_posted(self, item: Any, caption: str) -> None:
        topic = getattr(item, "topic", "cat")
        self.conn.execute(
            (
                "INSERT OR REPLACE INTO posts(identity, source, kind, url, caption, posted_at, topic) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            ),
            (item.identity, item.source, item.kind, item.url, caption, time.time(), topic),
        )
        self.conn.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO state(key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    def stats(self) -> dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        today = self.conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE posted_at >= ?",
            (time.time() - 24 * 3600,),
        ).fetchone()["n"]
        by_kind = {
            row["kind"]: row["n"]
            for row in self.conn.execute("SELECT kind, COUNT(*) AS n FROM posts GROUP BY kind")
        }
        by_topic = {
            row["topic"]: row["n"]
            for row in self.conn.execute("SELECT topic, COUNT(*) AS n FROM posts GROUP BY topic")
        }
        last = self.conn.execute(
            "SELECT posted_at, source, kind FROM posts ORDER BY posted_at DESC LIMIT 1"
        ).fetchone()
        return {
            "total": int(total),
            "last24h": int(today),
            "by_kind": by_kind,
            "by_topic": by_topic,
            "last_post": dict(last) if last else None,
        }

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT source, kind, topic, url, posted_at FROM posts ORDER BY posted_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.conn.close()
