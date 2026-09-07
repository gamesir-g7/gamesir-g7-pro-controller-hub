from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ChargeState(str, Enum):
    UNKNOWN = "unknown"
    NOT_CHARGING = "not_charging"
    CHARGING = "charging"
    FULL = "full"


class ConnectionType(str, Enum):
    DISCONNECTED = "disconnected"
    USB = "usb"
    WIRELESS = "wireless"
    BLUETOOTH = "bluetooth"


@dataclass(frozen=True)
class DriverCapabilities:
    battery: bool = False
    charging: bool = False
    inputs: bool = False
    gyroscope: bool = False
    rgb_read: bool = False
    rgb: bool = False
    profiles: bool = False
    calibration: bool = False
    firmware_read: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass
class InputSnapshot:
    available: bool = False
    available_buttons: list[str] = field(default_factory=list)
    left_x: float = 0.0
    left_y: float = 0.0
    right_x: float = 0.0
    right_y: float = 0.0
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    pressed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ControllerSnapshot:
    device_id: str = "gamesir-cyclone2"
    connected: bool = False
    model: str = "GameSir Cyclone 2"
    vendor_id: str = "3537"
    product_id: str = ""
    connection: ConnectionType = ConnectionType.DISCONNECTED
    battery_percent: int | None = None
    charge_state: ChargeState = ChargeState.UNKNOWN
    firmware: str = ""
    signal_percent: int | None = None
    rgb_profile: int | None = None
    rgb_zones: list[str] = field(default_factory=list)
    raw_report_hex: str = ""
    source: str = ""
    permission_required: bool = False
    capabilities: DriverCapabilities = field(default_factory=DriverCapabilities)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def charging(self) -> bool:
        return self.charge_state == ChargeState.CHARGING

    @property
    def status_key(self) -> str:
        if not self.connected:
            return "disconnected"
        if self.battery_percent is None:
            return "power_only" if self.connection == ConnectionType.USB else "battery_unavailable"
        return self.charge_state.value

    @property
    def label(self) -> str:
        if not self.connected:
            return "GameSir disconnected"
        if self.battery_percent is None:
            return "GameSir on USB — receiving power" if self.connection == ConnectionType.USB else "Battery unavailable"
        suffix = {
            ChargeState.CHARGING: " — charging",
            ChargeState.NOT_CHARGING: " — not charging",
            ChargeState.FULL: " — fully charged",
            ChargeState.UNKNOWN: "",
        }[self.charge_state]
        return f"GameSir: {self.battery_percent}%{suffix}"


@dataclass
class DriverResult:
    snapshot: ControllerSnapshot
    inputs: InputSnapshot = field(default_factory=InputSnapshot)
    diagnostics: list[dict[str, str]] = field(default_factory=list)
