from __future__ import annotations

from abc import ABC, abstractmethod

from openpad.domain import ControllerSnapshot, DriverCapabilities, DriverResult, InputSnapshot


class UnsupportedOperation(RuntimeError):
    pass


class ControllerDriver(ABC):
    driver_id = "unknown"
    capabilities = DriverCapabilities()

    @abstractmethod
    def probe(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read_snapshot(self) -> ControllerSnapshot:
        raise NotImplementedError

    def read_inputs(self) -> InputSnapshot:
        return InputSnapshot()

    def read_settings(self) -> dict[str, object]:
        return {}

    def write_settings(self, settings: dict[str, object]) -> None:
        raise UnsupportedOperation("This driver does not support writable settings")

    def diagnostics(self) -> list[dict[str, str]]:
        return []

    def read(self) -> DriverResult:
        return DriverResult(self.read_snapshot(), self.read_inputs(), self.diagnostics())
