from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_settings_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "openpad-hub/settings.json"


@dataclass
class AppSettings:
    language: str = "en"
    reduced_motion: bool = False
    history_enabled: bool = True
    notifications_enabled: bool = True
    low_battery_thresholds: list[int] = field(default_factory=lambda: [15, 10, 5])
    start_in_background: bool = False


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return AppSettings()
        defaults = asdict(AppSettings())
        return AppSettings(**{key: data.get(key, value) for key, value in defaults.items()})

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)
