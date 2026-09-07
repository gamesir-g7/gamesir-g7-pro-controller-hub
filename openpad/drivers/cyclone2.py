from __future__ import annotations

import os
import re
import select
import struct
import subprocess
import time
import fcntl
import threading
from datetime import datetime, timezone
from pathlib import Path

from openpad.domain import (
    ChargeState,
    ConnectionType,
    ControllerSnapshot,
    DriverCapabilities,
    DriverResult,
    InputSnapshot,
)
from openpad.drivers.base import ControllerDriver
from openpad.services.lighting import (
    LightingApplyError,
    LightingSafetyState,
    apply_profile_transaction,
    create_checkpoint,
    get_profile,
    load_safety_state,
    save_safety_state,
)

MATCH_WORDS = ("gamesir", "cyclone", "wireless controller")
USB_PRODUCTS = {"0575", "100b"}
HEARTBEAT = bytes((0x0F, 0xF2, 0x00))
ABS_FIELDS = {0: "left_x", 1: "left_y", 3: "right_x", 4: "right_y", 2: "left_trigger", 5: "right_trigger"}
BUTTON_CODES = {
    0x130: "A", 0x131: "B", 0x132: "C", 0x133: "X", 0x134: "Y", 0x135: "Z",
    0x136: "LB", 0x137: "RB", 0x138: "LT", 0x139: "RT", 0x13A: "View",
    0x13B: "Menu", 0x13C: "Home", 0x13D: "L3", 0x13E: "R3",
    0x220: "D-Up", 0x221: "D-Down", 0x222: "D-Left", 0x223: "D-Right",
}
KEY_NAMES = {
    1: "Esc", 14: "Backspace", 15: "Tab", 28: "Enter", 29: "Left Ctrl", 42: "Left Shift",
    54: "Right Shift", 56: "Left Alt", 57: "Space", 97: "Right Ctrl", 100: "Right Alt",
    103: "Key Up", 105: "Key Left", 106: "Key Right", 108: "Key Down",
}
KEY_LETTERS = {code: letter for code, letter in zip(
    (16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30, 31, 32, 33, 34, 35, 36, 37, 38, 44, 45, 46, 47, 48, 49, 50),
    "QWERTYUIOPASDFGHJKLZXCVBNM",
)}
INPUT_ABSINFO = struct.Struct("iiiiii")


def parse_capability_bits(text: str) -> set[int]:
    words = text.split()
    if not words:
        return set()
    value = int("".join(word.zfill(16) for word in words), 16)
    return {bit for bit in range(value.bit_length()) if value & (1 << bit)}


def extra_button_name(code: int, source_name: str = "") -> str:
    if code in BUTTON_CODES:
        return BUTTON_CODES[code]
    if 0x2C0 <= code <= 0x2E7:
        return f"M{code - 0x2C0 + 1}"
    if 0x110 <= code <= 0x117:
        return f"Mouse {code - 0x110 + 1}"
    if code in KEY_LETTERS:
        return f"Key {KEY_LETTERS[code]}"
    if 59 <= code <= 68:
        return f"F{code - 58}"
    if code == 87:
        return "F11"
    if code == 88:
        return "F12"
    return KEY_NAMES.get(code, f"Extra {code}")


def run_command(*args: str) -> str:
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=3, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def normalize_axis(value: int) -> float:
    return max(-1.0, min(1.0, (value - 128) / 127.0))


def normalize_linux_axis(value: int, minimum: int, maximum: int, trigger: bool = False, flat: int = 0) -> float:
    if maximum <= minimum:
        return 0.0
    if trigger:
        return max(0.0, min(1.0, (value - minimum) / (maximum - minimum)))
    midpoint = (minimum + maximum) / 2
    half_range = (maximum - minimum) / 2
    normalized = max(-1.0, min(1.0, (value - midpoint) / half_range))
    deadzone = max(0.025, min(0.25, flat / half_range))
    if abs(normalized) <= deadzone:
        return 0.0
    magnitude = (abs(normalized) - deadzone) / (1 - deadzone)
    return max(-1.0, min(1.0, magnitude if normalized > 0 else -magnitude))


def parse_input_report(data: bytes) -> InputSnapshot:
    # Report 0x12 is verified for battery/charge only. Inputs come from evdev.
    return InputSnapshot()


def parse_cyclone2_report(data: bytes, path: str = "", product_id: str = "100b") -> DriverResult | None:
    if len(data) < 37 or data[0] != 0x12:
        return None
    battery, charge = data[36], data[35]
    if battery > 100 or charge not in (0, 1):
        return None
    rgb_profile = data[37] if len(data) >= 53 else None
    rgb_zones = [
        f"#{data[offset]:02X}{data[offset + 1]:02X}{data[offset + 2]:02X}"
        for offset in range(38, 53, 3)
    ] if len(data) >= 53 else []
    snapshot = ControllerSnapshot(
        connected=True,
        product_id=product_id,
        connection=ConnectionType.WIRELESS,
        battery_percent=battery,
        charge_state=ChargeState.CHARGING if charge == 1 else ChargeState.NOT_CHARGING,
        rgb_profile=rgb_profile,
        rgb_zones=rgb_zones,
        raw_report_hex=data.hex(),
        source=path,
        capabilities=Cyclone2Driver.capabilities,
    )
    return DriverResult(snapshot=snapshot, inputs=parse_input_report(data))


def parse_upower(text: str, path: str = "") -> ControllerSnapshot | None:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.strip().split(":", 1)
            fields[key.lower()] = value.strip()
    identity = " ".join((fields.get("model", ""), fields.get("native-path", ""), path)).lower()
    if not any(word in identity for word in MATCH_WORDS) and fields.get("type", "").lower() != "gaming-input":
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", fields.get("percentage", ""))
    percentage = round(float(match.group(1))) if match else None
    state = fields.get("state", "").lower()
    charge_state = {
        "charging": ChargeState.CHARGING,
        "pending-charge": ChargeState.CHARGING,
        "fully-charged": ChargeState.FULL,
        "discharging": ChargeState.NOT_CHARGING,
        "empty": ChargeState.NOT_CHARGING,
    }.get(state, ChargeState.UNKNOWN)
    return ControllerSnapshot(
        connected=True,
        model=fields.get("model") or "GameSir Cyclone 2",
        connection=ConnectionType.BLUETOOTH,
        battery_percent=percentage,
        charge_state=charge_state,
        source=path,
        capabilities=Cyclone2Driver.capabilities,
    )


class Cyclone2Driver(ControllerDriver):
    driver_id = "gamesir-cyclone2"
    capabilities = DriverCapabilities(
        battery=True,
        charging=True,
        inputs=True,
        rgb_read=True,
        rgb=True,
        profiles=True,
    )

    def __init__(self, timeout: float = 0.4) -> None:
        self.timeout = timeout
        self._last_inputs = InputSnapshot()
        self._last_report_at = 0.0
        self._last_error = ""
        self._pressed: set[str] = set()
        self._input_fd: int | None = None
        self._input_path: Path | None = None
        self._input_lock = threading.Lock()
        self._button_fds: dict[Path, int] = {}
        self._button_sources: dict[Path, str] = {}
        self._available_buttons: list[str] = []
        self._extra_buttons: set[str] = set()
        self._diagnostics_cache: list[dict[str, str]] = []
        self._diagnostics_at = 0.0

    @staticmethod
    def _usb_device() -> tuple[str, str] | None:
        for device in Path("/sys/bus/usb/devices").glob("*"):
            try:
                vendor = (device / "idVendor").read_text().strip().lower()
                product = (device / "idProduct").read_text().strip().lower()
                name = (device / "product").read_text().strip() if (device / "product").exists() else ""
            except OSError:
                continue
            if vendor == "3537" and product in USB_PRODUCTS:
                return product, name
        return None

    @staticmethod
    def _find_hidraw(product_id: str | None = None) -> Path | None:
        for device in Path("/sys/class/hidraw").glob("hidraw*"):
            try:
                uevent = (device / "device/uevent").read_text().upper()
            except OSError:
                continue
            match = re.search(r"HID_ID=0003:00003537:0000([0-9A-F]{4})", uevent)
            if match and match.group(1).lower() in USB_PRODUCTS and (product_id is None or match.group(1).lower() == product_id):
                return Path("/dev") / device.name
        return None

    @staticmethod
    def _find_event() -> Path | None:
        for device in Path("/sys/class/input").glob("event*"):
            try:
                vendor = (device / "device/id/vendor").read_text().strip().lower()
                product = (device / "device/id/product").read_text().strip().lower()
            except OSError:
                continue
            if vendor == "3537" and product in USB_PRODUCTS:
                candidate = Path("/dev/input") / device.name
                try:
                    mask = int((device / "device/capabilities/abs").read_text().strip() or "0", 16)
                    if all(mask & (1 << code) for code in (0, 1, 3, 4)):
                        return candidate
                except (OSError, ValueError):
                    pass
        return None

    def _close_input(self) -> None:
        if self._input_fd is not None:
            try:
                os.close(self._input_fd)
            except OSError:
                pass
        self._input_fd = None
        self._input_path = None
        for fd in self._button_fds.values():
            try:
                os.close(fd)
            except OSError:
                pass
        self._button_fds.clear()
        self._button_sources.clear()
        self._available_buttons = []
        self._extra_buttons.clear()

    @staticmethod
    def _event_sysfs(path: Path) -> Path:
        return Path("/sys/class/input") / path.name / "device"

    def _configure_input_devices(self, main_path: Path) -> None:
        sysfs = self._event_sysfs(main_path)
        try:
            key_bits = parse_capability_bits((sysfs / "capabilities/key").read_text())
            abs_bits = parse_capability_bits((sysfs / "capabilities/abs").read_text())
        except OSError:
            key_bits, abs_bits = set(), set()
        self._available_buttons = [name for code, name in BUTTON_CODES.items() if code in key_bits]
        if 16 in abs_bits and 17 in abs_bits:
            self._available_buttons.extend(["D-Up", "D-Down", "D-Left", "D-Right"])

        for device in Path("/sys/class/input").glob("event*"):
            candidate = Path("/dev/input") / device.name
            if candidate == main_path:
                continue
            try:
                vendor = (device / "device/id/vendor").read_text().strip().lower()
                product = (device / "device/id/product").read_text().strip().lower()
                name = (device / "device/name").read_text().strip()
                keys = parse_capability_bits((device / "device/capabilities/key").read_text())
            except OSError:
                continue
            if vendor != "3537" or product not in USB_PRODUCTS or not keys:
                continue
            try:
                self._button_fds[candidate] = os.open(candidate, os.O_RDONLY | os.O_NONBLOCK)
                self._button_sources[candidate] = name
            except OSError:
                continue

    def _set_hat(self, code: int, value: int) -> None:
        pairs = {16: ("D-Left", "D-Right"), 17: ("D-Up", "D-Down")}
        negative, positive = pairs[code]
        self._pressed.discard(negative)
        self._pressed.discard(positive)
        if value < 0:
            self._pressed.add(negative)
        elif value > 0:
            self._pressed.add(positive)

    def _drain_events(self, fd: int, source_name: str, main: bool = False) -> None:
        event_size = struct.calcsize("llHHi")
        while True:
            try:
                payload = os.read(fd, event_size * 64)
            except BlockingIOError:
                break
            except OSError:
                break
            if not payload:
                break
            for offset in range(0, len(payload) - event_size + 1, event_size):
                _, _, event_type, code, value = struct.unpack_from("llHHi", payload, offset)
                if event_type == 1:
                    name = BUTTON_CODES.get(code) if main else extra_button_name(code, source_name)
                    if not name:
                        continue
                    if not main:
                        self._extra_buttons.add(name)
                    if value:
                        self._pressed.add(name)
                    else:
                        self._pressed.discard(name)
                elif main and event_type == 3 and code in (16, 17):
                    self._set_hat(code, value)

    def _read_linux_inputs(self) -> InputSnapshot | None:
        """Read the standard Linux input API; this never writes to the controller."""
        path = self._input_path if self._input_fd is not None and self._input_path and self._input_path.exists() else self._find_event()
        if not path:
            self._close_input()
            self._last_inputs = InputSnapshot()
            return self._last_inputs
        with self._input_lock:
            if self._input_fd is None or self._input_path != path:
                self._close_input()
                try:
                    self._input_fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    self._input_path = path
                    self._configure_input_devices(path)
                except OSError:
                    self._last_inputs = InputSnapshot()
                    return self._last_inputs
            fd = self._input_fd
            values = dict(self._last_inputs.to_dict())
            values["available"] = True
            for code, field in ABS_FIELDS.items():
                buffer = bytearray(INPUT_ABSINFO.size)
                request = 0x80184540 + code  # EVIOCGABS(code), struct input_absinfo
                try:
                    fcntl.ioctl(fd, request, buffer, True)
                except OSError:
                    continue
                current, minimum, maximum, _, flat, _ = INPUT_ABSINFO.unpack(buffer)
                values[field] = normalize_linux_axis(current, minimum, maximum, code in (2, 5), flat)
            for code in (16, 17):
                buffer = bytearray(INPUT_ABSINFO.size)
                try:
                    fcntl.ioctl(fd, 0x80184540 + code, buffer, True)
                    self._set_hat(code, INPUT_ABSINFO.unpack(buffer)[0])
                except OSError:
                    pass
            self._drain_events(fd, "Gamepad", main=True)
            for candidate, button_fd in tuple(self._button_fds.items()):
                self._drain_events(button_fd, self._button_sources.get(candidate, "Extra input"))
            values["available_buttons"] = self._available_buttons + sorted(self._extra_buttons - set(self._available_buttons))
            values["pressed"] = sorted(self._pressed)
            self._last_inputs = InputSnapshot(**values)
            return self._last_inputs

    @staticmethod
    def _bluetooth_connected() -> bool:
        for line in run_command("bluetoothctl", "devices").splitlines():
            match = re.match(r"Device ([0-9A-F:]{17}) (.+)", line, re.I)
            if match and any(word in match.group(2).lower() for word in MATCH_WORDS):
                info = run_command("bluetoothctl", "info", match.group(1)).lower()
                if re.search(r"connected:\s*yes", info):
                    return True
        return False

    def probe(self) -> bool:
        return bool(self._usb_device() or self._bluetooth_connected())

    def _read_hid(self) -> DriverResult | None:
        # The heartbeat and battery offsets are verified only for product 100b.
        path = self._find_hidraw("100b")
        if not path:
            return None
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            self._last_error = f"Sin permiso para leer {path}"
            return None
        except OSError as exc:
            self._last_error = str(exc)
            return None
        try:
            os.write(fd, HEARTBEAT)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
                if not ready:
                    break
                result = parse_cyclone2_report(os.read(fd, 64), str(path))
                if result:
                    self._last_report_at = time.time()
                    self._last_error = ""
                    return result
        except OSError as exc:
            self._last_error = str(exc)
        finally:
            os.close(fd)
        return None

    def _read_upower(self) -> ControllerSnapshot | None:
        for path in run_command("upower", "-e").splitlines():
            candidate = parse_upower(run_command("upower", "-i", path.strip()), path.strip())
            if candidate:
                return candidate
        return None

    def _fallback_snapshot(self) -> ControllerSnapshot:
        usb = self._usb_device()
        hidraw = self._find_hidraw()
        if usb:
            product_id, _ = usb
            return ControllerSnapshot(
                connected=True,
                product_id=product_id,
                connection=ConnectionType.USB if product_id == "0575" else ConnectionType.WIRELESS,
                source=str(hidraw or "sysfs"),
                permission_required=bool(hidraw and not os.access(hidraw, os.R_OK | os.W_OK)),
                capabilities=self.capabilities,
            )
        upower = self._read_upower()
        if upower:
            return upower
        if self._bluetooth_connected():
            return ControllerSnapshot(connected=True, connection=ConnectionType.BLUETOOTH, capabilities=self.capabilities)
        return ControllerSnapshot(capabilities=self.capabilities)

    def read_snapshot(self) -> ControllerSnapshot:
        result = self._read_hid()
        return result.snapshot if result else self._fallback_snapshot()

    def read_inputs(self) -> InputSnapshot:
        return self._read_linux_inputs()

    @staticmethod
    def _lighting_descriptor(path: Path) -> bytes:
        try:
            return (Path("/sys/class/hidraw") / path.name / "device/report_descriptor").read_bytes()
        except OSError:
            return b""

    @staticmethod
    def _write_lighting_report(fd: int, report: bytes) -> None:
        allowed_registers = {0x01, 0x04, 0x05, 0x08, 0x0E, 0x11}
        if len(report) != 64 or report[:3] != bytes((0x0F, 0x03, 0x20)) or report[4] not in allowed_registers:
            raise LightingApplyError("Blocked an undocumented lighting report")
        if os.write(fd, report) != len(report):
            raise OSError("Incomplete HID lighting write")

    @staticmethod
    def _read_lighting_report(fd: int) -> bytes | None:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            return None
        latest: bytes | None = None
        try:
            while True:
                latest = os.read(fd, 64)
        except BlockingIOError:
            return latest

    def _open_lighting_session(self) -> tuple[Path, int, ControllerSnapshot]:
        result = self._read_hid()
        if result is None or result.snapshot.product_id.lower() != "100b":
            raise LightingApplyError("Cyclone 2 must be connected in XInput mode (3537:100b)")
        path = Path(result.snapshot.source)
        verified_path = self._find_hidraw("100b")
        if verified_path != path:
            raise LightingApplyError("The verified HID device changed before the lighting transaction")
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise LightingApplyError(f"Cannot open the verified lighting channel: {exc}") from exc
        try:
            for _ in range(32):
                os.read(fd, 64)
        except BlockingIOError:
            pass
        except OSError:
            os.close(fd)
            raise
        return path, fd, result.snapshot

    def commission_lighting(self, reserved_configuration_confirmed: bool = False) -> LightingSafetyState:
        """Verify static read-back, a controlled change, and recovery."""
        if reserved_configuration_confirmed is not True:
            raise LightingApplyError("Confirm the four physical channel indicators before commissioning")
        path, fd, snapshot = self._open_lighting_session()
        checkpoint = create_checkpoint(snapshot, self._lighting_descriptor(path))
        aurora = get_profile("aurora-drift")
        ocean = get_profile("deep-ocean")
        base_state = LightingSafetyState(
            checkpoint=True,
            checkpoint_path=str(checkpoint),
            reserved_configuration="configuration-3-four-indicators",
        )
        save_safety_state(base_state)
        try:
            write = lambda report: self._write_lighting_report(fd, report)
            read = lambda: self._read_lighting_report(fd)
            apply_profile_transaction(aurora, write, read, checkpoint)
            save_safety_state(LightingSafetyState(
                checkpoint=True,
                readback=True,
                active_profile_id=aurora.profile_id,
                checkpoint_path=str(checkpoint),
                reserved_configuration=base_state.reserved_configuration,
            ))
            apply_profile_transaction(ocean, write, read, checkpoint, previous_profile=aurora)
            apply_profile_transaction(aurora, write, read, checkpoint, previous_profile=ocean)
        finally:
            os.close(fd)
        state = LightingSafetyState(
            checkpoint=True,
            readback=True,
            recovery=True,
            active_profile_id=aurora.profile_id,
            checkpoint_path=str(checkpoint),
            reserved_configuration=base_state.reserved_configuration,
        )
        save_safety_state(state)
        return state

    def write_settings(self, settings: dict[str, object]) -> None:
        allowed_keys = {"lighting_profile_id", "reserved_configuration_confirmed"}
        if set(settings) != allowed_keys or settings.get("reserved_configuration_confirmed") is not True:
            raise LightingApplyError("Every lighting change requires confirmation of four physical indicators")
        state = load_safety_state()
        if not state.unlocked or not state.active_profile_id:
            raise LightingApplyError("Lighting writes remain locked until all three hardware checks pass")
        requested = get_profile(str(settings["lighting_profile_id"]))
        previous = get_profile(state.active_profile_id)
        path, fd, snapshot = self._open_lighting_session()
        checkpoint = create_checkpoint(snapshot, self._lighting_descriptor(path))
        try:
            apply_profile_transaction(
                requested,
                lambda report: self._write_lighting_report(fd, report),
                lambda: self._read_lighting_report(fd),
                checkpoint,
                previous_profile=previous,
            )
        finally:
            os.close(fd)
        save_safety_state(LightingSafetyState(
            checkpoint=True,
            readback=True,
            recovery=True,
            active_profile_id=requested.profile_id,
            checkpoint_path=str(checkpoint),
            reserved_configuration=state.reserved_configuration,
        ))

    def diagnostics(self) -> list[dict[str, str]]:
        if self._diagnostics_cache and time.monotonic() - self._diagnostics_at < 5:
            return self._diagnostics_cache
        usb = self._usb_device()
        hidraw = self._find_hidraw()
        permission = bool(hidraw and os.access(hidraw, os.R_OK | os.W_OK))
        permission_status = "ok" if permission else "warn" if hidraw else "off"
        permission_detail = "Access granted" if permission else "Run the permission repair" if hidraw else "Channel unavailable"
        self._diagnostics_cache = [
            {"name": "USB device", "status": "ok" if usb else "off", "detail": f"3537:{usb[0]}" if usb else "Not detected"},
            {"name": "HID channel", "status": "ok" if hidraw else "off", "detail": str(hidraw or "Unavailable")},
            {"name": "Permissions", "status": permission_status, "detail": permission_detail},
            {"name": "Input events", "status": "ok" if self._find_event() else "warn", "detail": str(self._find_event() or "No compatible evdev axes")},
            {"name": "Last report", "status": "ok" if self._last_report_at else "warn", "detail": datetime.fromtimestamp(self._last_report_at).strftime("%H:%M:%S") if self._last_report_at else "No HID reading"},
            {"name": "Recent error", "status": "warn" if self._last_error else "ok", "detail": self._last_error or "None"},
        ]
        self._diagnostics_at = time.monotonic()
        return self._diagnostics_cache

    def read(self) -> DriverResult:
        result = self._read_hid()
        if result:
            result.inputs = self._last_inputs
            result.diagnostics = self.diagnostics()
            return result
        return DriverResult(self._fallback_snapshot(), self._last_inputs, self.diagnostics())
