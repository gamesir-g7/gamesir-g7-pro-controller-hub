from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from openpad.domain import ControllerSnapshot


def default_database_path() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "openpad-hub"
    return root / "history.sqlite3"


class BatteryHistory:
    def __init__(self, path: Path | None = None, retention_days: int = 30) -> None:
        self.path = path or default_database_path()
        self.retention_days = retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=2)

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS battery_samples (
                    timestamp INTEGER NOT NULL,
                    device_id TEXT NOT NULL,
                    percent INTEGER NOT NULL,
                    charge_state TEXT NOT NULL,
                    connection TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_samples_device_time ON battery_samples(device_id, timestamp)")

    def record(self, snapshot: ControllerSnapshot, now: int | None = None) -> bool:
        if not snapshot.connected or snapshot.battery_percent is None:
            return False
        now = now or int(time.time())
        with self._connect() as db:
            previous = db.execute(
                "SELECT timestamp, percent, charge_state FROM battery_samples WHERE device_id=? ORDER BY timestamp DESC LIMIT 1",
                (snapshot.device_id,),
            ).fetchone()
            if previous and previous[1] == snapshot.battery_percent and previous[2] == snapshot.charge_state.value and now - previous[0] < 300:
                return False
            db.execute(
                "INSERT INTO battery_samples VALUES (?, ?, ?, ?, ?)",
                (now, snapshot.device_id, snapshot.battery_percent, snapshot.charge_state.value, snapshot.connection.value),
            )
            db.execute("DELETE FROM battery_samples WHERE timestamp < ?", (now - self.retention_days * 86400,))
        return True

    def query(self, device_id: str, hours: int = 24, now: int | None = None) -> list[dict[str, int | str]]:
        now = now or int(time.time())
        with self._connect() as db:
            rows = db.execute(
                "SELECT timestamp, percent, charge_state FROM battery_samples WHERE device_id=? AND timestamp>=? ORDER BY timestamp",
                (device_id, now - hours * 3600),
            ).fetchall()
        return [{"timestamp": row[0], "percent": row[1], "chargeState": row[2]} for row in rows]
