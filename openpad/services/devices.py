from __future__ import annotations

from openpad.drivers.base import ControllerDriver


class DeviceManager:
    """Selects the first verified driver that recognizes attached hardware."""

    def __init__(self, drivers: list[ControllerDriver]) -> None:
        self.drivers = drivers

    def select_driver(self) -> ControllerDriver | None:
        for driver in self.drivers:
            if driver.probe():
                return driver
        return None
