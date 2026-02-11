"""SQLite-backed storage for web UI runs and logs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TERMINAL_STATUSES = {"success", "failed", "cancelled"}


def utc_now_iso() -> str:
    """Return UTC ISO timestamp with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStorage:
    """Persist runs and logs to a local SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    config_path TEXT,
                    weekly_config_path TEXT,
                    extra_args TEXT NOT NULL DEFAULT '[]',
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step TEXT NOT NULL DEFAULT '排队中',
                    progress INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL,
                    output_path TEXT,
                    error_message TEXT,
                    exit_code INTEGER,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    module TEXT NOT NULL,
                    message TEXT NOT NULL,
                    raw_line TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_run_id_id ON logs(run_id, id);
                """
            )

    def _row_to_run(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["extra_args"] = json.loads(data.get("extra_args") or "[]")
        except json.JSONDecodeError:
            data["extra_args"] = []
        try:
            data["stats"] = json.loads(data.get("stats_json") or "{}")
        except json.JSONDecodeError:
            data["stats"] = {}
        data.pop("stats_json", None)
        return data

    def _row_to_log(self, row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    def has_active_run(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM runs WHERE status IN ('queued', 'running') LIMIT 1"
            ).fetchone()
            return bool(row)

    def create_run(
        self,
        *,
        mode: str,
        dry_run: bool,
        config_path: str,
        weekly_config_path: str,
        extra_args: List[str],
        command: str,
    ) -> int:
        now = utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO runs (
                        mode, dry_run, config_path, weekly_config_path, extra_args,
                        command, status, current_step, progress,
                        started_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', '排队中', 0, ?, ?, ?)
                    """,
                    (
                        mode,
                        1 if dry_run else 0,
                        config_path,
                        weekly_config_path,
                        json.dumps(extra_args, ensure_ascii=False),
                        command,
                        now,
                        now,
                        now,
                    ),
                )
                return int(cur.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return

        allowed = {
            "status",
            "current_step",
            "progress",
            "ended_at",
            "duration_seconds",
            "output_path",
            "error_message",
            "exit_code",
        }
        update_fields = {k: v for k, v in fields.items() if k in allowed}
        if not update_fields:
            return

        update_fields["updated_at"] = utc_now_iso()

        keys = list(update_fields.keys())
        placeholders = ", ".join(f"{k} = ?" for k in keys)
        values = [update_fields[k] for k in keys]
        values.append(run_id)

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE runs SET {placeholders} WHERE id = ?",
                    values,
                )

    def merge_stats(self, run_id: int, stats_patch: Dict[str, Any]) -> None:
        if not stats_patch:
            return

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT stats_json FROM runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if not row:
                    return

                try:
                    current = json.loads(row["stats_json"] or "{}")
                except json.JSONDecodeError:
                    current = {}

                for key, value in stats_patch.items():
                    if (
                        isinstance(current.get(key), dict)
                        and isinstance(value, dict)
                    ):
                        current[key].update(value)
                    else:
                        current[key] = value

                conn.execute(
                    "UPDATE runs SET stats_json = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps(current, ensure_ascii=False),
                        utc_now_iso(),
                        run_id,
                    ),
                )

    def append_log(
        self,
        run_id: int,
        *,
        level: str,
        module: str,
        message: str,
        raw_line: str,
        timestamp: Optional[str] = None,
    ) -> int:
        ts = timestamp or utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO logs (run_id, timestamp, level, module, message, raw_line)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, ts, level, module, message, raw_line),
                )
                return int(cur.lastrowid)

    def list_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
            return [self._row_to_run(row) for row in rows]

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            return self._row_to_run(row) if row else None

    def get_logs(self, run_id: int, after_id: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM logs
                WHERE run_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (run_id, max(0, after_id), max(1, min(limit, 2000))),
            ).fetchall()
            return [self._row_to_log(row) for row in rows]

    def latest_log(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM logs WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return self._row_to_log(row) if row else None

    def delete_run(self, run_id: int, delete_artifact: bool = False) -> Tuple[bool, bool]:
        run = self.get_run(run_id)
        if not run:
            return False, False

        artifact_removed = False
        if delete_artifact and run.get("output_path"):
            try:
                artifact_path = Path(run["output_path"])
                if artifact_path.exists() and artifact_path.is_file():
                    artifact_path.unlink()
                    artifact_removed = True
            except OSError:
                artifact_removed = False

        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

        return True, artifact_removed
