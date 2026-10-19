"""SQLite 持久层。单文件，无外部服务。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    emotion TEXT,
    importance REAL DEFAULT 0.5,
    flagged INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    vec TEXT NOT NULL,
    emotion TEXT,
    weight REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS transcript (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_memories_ts ON memories(ts DESC);
CREATE INDEX IF NOT EXISTS idx_transcript_ts ON transcript(ts DESC);
"""


class Store:
    def __init__(self, path: str | Path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(p), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    # ---------- kv ----------
    def kv_get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def kv_set(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )

    # ---------- counters ----------
    def counter_get(self, key: str, default: float = 0.0) -> float:
        with self._lock:
            row = self.conn.execute("SELECT value FROM counters WHERE key=?", (key,)).fetchone()
        return float(row["value"]) if row else default

    def counter_set(self, key: str, value: float) -> None:
        self._exec(
            "INSERT INTO counters(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), time.time()),
        )

    # ---------- profile ----------
    def profile_set(self, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO profile(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, time.time()),
        )

    def profile_all(self) -> Dict[str, str]:
        with self._lock:
            rows = self.conn.execute("SELECT key, value FROM profile ORDER BY updated_at DESC").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ---------- events ----------
    def add_event(
        self,
        text: str,
        kind: str,
        emotion: Optional[Dict[str, Any]] = None,
        importance: float = 0.5,
        flagged: bool = False,
        ts: Optional[float] = None,
    ) -> int:
        cur = self._exec(
            "INSERT INTO events(ts,kind,text,emotion,importance,flagged) VALUES(?,?,?,?,?,?)",
            (
                ts or time.time(),
                kind,
                text,
                json.dumps(emotion, ensure_ascii=False) if emotion else None,
                importance,
                1 if flagged else 0,
            ),
        )
        return int(cur.lastrowid or 0)

    def recent_events(self, limit: int = 20, include_flagged: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM events"
        if not include_flagged:
            sql += " WHERE flagged=0"
        sql += " ORDER BY ts DESC LIMIT ?"
        with self._lock:
            rows = self.conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- memories ----------
    def add_memory(
        self,
        text: str,
        vec: List[float],
        kind: str = "episodic",
        emotion: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
    ) -> int:
        cur = self._exec(
            "INSERT INTO memories(ts,kind,text,vec,emotion,weight) VALUES(?,?,?,?,?,?)",
            (
                time.time(),
                kind,
                text,
                json.dumps(vec),
                json.dumps(emotion, ensure_ascii=False) if emotion else None,
                weight,
            ),
        )
        return int(cur.lastrowid or 0)

    def all_memories(self, limit: int = 3000) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM memories ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["vec"] = json.loads(d["vec"])
            d["emotion"] = json.loads(d["emotion"]) if d["emotion"] else None
            out.append(d)
        return out

    # ---------- transcript ----------
    def add_turn(self, role: str, text: str, ts: Optional[float] = None) -> int:
        cur = self._exec(
            "INSERT INTO transcript(ts,role,text) VALUES(?,?,?)",
            (float(ts) if ts else time.time(), role, text),
        )
        return int(cur.lastrowid or 0)

    def get_turn(self, turn_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM transcript WHERE id=?", (int(turn_id),)
            ).fetchone()
        return dict(row) if row else None

    def update_turn_text(self, turn_id: int, text: str) -> None:
        self._exec(
            "UPDATE transcript SET text=? WHERE id=?", (text, int(turn_id))
        )

    def delete_turn(self, turn_id: int) -> None:
        self._exec("DELETE FROM transcript WHERE id=?", (int(turn_id),))

    def find_turn(self, role: str, text: str, ts: Optional[float] = None,
                  limit: int = 40, window: float = 1800.0) -> Optional[Dict[str, Any]]:
        """按角色 + 文本片段找最近的一条 turn（撤回实时消息用）。"""
        needle = (text or "").strip()
        if not needle:
            return None
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM transcript WHERE role=? ORDER BY id DESC LIMIT ?",
                (role, int(limit)),
            ).fetchall()
        for r in rows:
            body = str(r["text"] or "")
            if needle not in body:
                continue
            if ts and abs(float(r["ts"] or 0) - float(ts)) > window:
                continue
            return dict(r)
        return None

    def recent_turns(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM transcript ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
