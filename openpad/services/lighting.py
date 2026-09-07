from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from openpad.domain import ControllerSnapshot


REPORT_LENGTH = 64
ZONE_REGISTERS = (0x05, 0x08, 0x0E, 0x11)
ZONE_NAMES = ("Left", "Right", "Logo", "Center")
# Report 0x12 exposes rendered static colors in this physical order. Slot 4
# (offset 47) stays black and is not a configurable zone.
STATIC_ZONE_OFFSETS = (41, 44, 38, 50)
COLOR_PATTERN = re.compile(r"^#[0-9A-F]{6}$")


@dataclass(frozen=True)
class LightingProfile:
    profile_id: str
    name: str
    description: str
    zones: tuple[str, str, str, str]
    brightness: int
    tag: str = "SIGNATURE"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


LIGHTING_PROFILES = (
    LightingProfile(
        "aurora-drift",
        "Aurora Drift",
        "Violet, cyan and mint with a soft luminous center.",
        ("#7C5CFF", "#00CFFF", "#36D399", "#B9A7FF"),
        58,
        "SIGNATURE",
    ),
    LightingProfile(
        "ember-core",
        "Ember Core",
        "Hot crimson and amber inspired by a compact reactor.",
        ("#FF365F", "#FF7A00", "#FFD166", "#FF2D95"),
        62,
        "ENERGY",
    ),
    LightingProfile(
        "deep-ocean",
        "Deep Ocean",
        "Electric blue gradients with a turquoise center.",
        ("#0057FF", "#00BFFF", "#0047AB", "#00FFD1"),
        52,
        "FOCUS",
    ),
    LightingProfile(
        "neon-sakura",
        "Neon Sakura",
        "Pink and ultraviolet balanced for a dark desktop.",
        ("#FF4FB3", "#9B5CFF", "#FF86D7", "#6D5BFF"),
        55,
        "VAPOR",
    ),
    LightingProfile(
        "stealth-mint",
        "Stealth Mint",
        "Low brightness graphite with sharp mint highlights.",
        ("#07110F", "#36D399", "#101824", "#7CFFCB"),
        38,
        "STEALTH",
    ),
    LightingProfile(
        "cyber-ice",
        "Cyber Ice",
        "Crisp cyan, electric blue and ultraviolet highlights.",
        ("#00E5FF", "#4F7CFF", "#B6F3FF", "#8B5CFF"),
        54,
        "CLEAN",
    ),
    LightingProfile(
        "solar-circuit",
        "Solar Circuit",
        "A high-energy sunset flowing from amber into violet.",
        ("#FF6B35", "#FFB000", "#FF2D55", "#7C3AED"),
        60,
        "SUNSET",
    ),
    LightingProfile(
        "ghost-mono",
        "Ghost Mono",
        "Cold white and gunmetal for a restrained minimal setup.",
        ("#E8EDF7", "#8792A8", "#FFFFFF", "#3E4C66"),
        46,
        "MINIMAL",
    ),
)


class LightingApplyError(RuntimeError):
    def __init__(self, message: str, recovered: bool = False) -> None:
        super().__init__(message)
        self.recovered = recovered


@dataclass(frozen=True)
class LightingSafetyState:
    checkpoint: bool = False
    readback: bool = False
    recovery: bool = False
    active_profile_id: str = ""
    checkpoint_path: str = ""
    reserved_configuration: str = ""

    @property
    def unlocked(self) -> bool:
        return self.checkpoint and self.readback and self.recovery


def get_profile(profile_id: str) -> LightingProfile:
    for profile in LIGHTING_PROFILES:
        if profile.profile_id == profile_id:
            return profile
    raise ValueError(f"Unknown lighting profile: {profile_id}")


def _rgb_bytes(color: str) -> bytes:
    normalized = color.strip().upper()
    if not COLOR_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid RGB color: {color}")
    return bytes.fromhex(normalized[1:])


def build_led_register_write(register: int, payload: bytes) -> bytes:
    if not 0 <= register <= 0xFF or len(payload) > 58:
        raise ValueError("Invalid Cyclone 2 lighting register write")
    report = bytearray(REPORT_LENGTH)
    report[0:3] = bytes((0x0F, 0x03, 0x20))
    report[4] = register
    report[5] = len(payload)
    report[6:6 + len(payload)] = payload
    return bytes(report)


def build_static_mode(seed_color: str) -> bytes:
    color = _rgb_bytes(seed_color)
    payload = bytearray((0x01, 0x05, 0x0A, 0x32))
    payload.extend(color * 7)
    payload.extend(bytes(58 - len(payload)))
    return build_led_register_write(0x01, bytes(payload))


def build_profile_reports(profile: LightingProfile) -> list[bytes]:
    if not 0 <= profile.brightness <= 100:
        raise ValueError("Brightness must be between 0 and 100")
    reports = [build_static_mode(profile.zones[0])]
    reports.extend(
        build_led_register_write(register, _rgb_bytes(color))
        for register, color in zip(ZONE_REGISTERS, profile.zones, strict=True)
    )
    reports.append(build_led_register_write(0x04, bytes((profile.brightness,))))
    return reports


def build_static_zone_reports(profile: LightingProfile) -> list[bytes]:
    """Build only the four zone writes; never attempt to change effect mode."""
    return [
        build_led_register_write(register, _rgb_bytes(color))
        for register, color in zip(ZONE_REGISTERS, profile.zones, strict=True)
    ]


def live_colors_from_report(report: bytes) -> tuple[str, ...]:
    if len(report) < 53 or report[0] != 0x12:
        return ()
    return tuple(
        f"#{report[offset]:02X}{report[offset + 1]:02X}{report[offset + 2]:02X}"
        for offset in range(38, 53, 3)
    )


def static_zones_from_report(report: bytes) -> tuple[str, ...]:
    """Decode the four rendered zone samples when telemetry confirms mode 0."""
    if len(report) < 53 or report[0] != 0x12 or report[37] != 0:
        return ()
    return tuple(
        f"#{report[offset]:02X}{report[offset + 1]:02X}{report[offset + 2]:02X}"
        for offset in STATIC_ZONE_OFFSETS
    )


def expected_static_zones(profile: LightingProfile) -> tuple[str, ...]:
    """The controller reports static rendered channels at floor(RGB / 2)."""
    return tuple(
        "#" + bytes(channel // 2 for channel in _rgb_bytes(color)).hex().upper()
        for color in profile.zones
    )


def report_matches_static_profile(report: bytes, profile: LightingProfile) -> bool:
    return static_zones_from_report(report) == expected_static_zones(profile)


def _send_profile(
    profile: LightingProfile,
    write_report: Callable[[bytes], None],
    pause: Callable[[float], None],
) -> None:
    for index, report in enumerate(build_static_zone_reports(profile)):
        if index:
            pause(0.08)
        write_report(report)


def apply_profile_transaction(
    profile: LightingProfile,
    write_report: Callable[[bytes], None],
    read_report: Callable[[], bytes | None],
    checkpoint_path: Path,
    previous_profile: LightingProfile | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> None:
    """Apply four static zones and verify mapped mode-0 telemetry.

    A private checkpoint is mandatory. If verification fails and a previously
    verified OpenPad profile exists, that profile is restored and independently
    verified before the error is returned. The verifier must check configured
    state in confirmed static mode 0. Animated reports are never accepted.
    """
    if not checkpoint_path.is_file() or checkpoint_path.stat().st_mode & 0o077:
        raise LightingApplyError("A private 0600 checkpoint is required before writing")

    initial = read_report()
    if initial is None or len(initial) < 38 or initial[0] != 0x12 or initial[37] != 0:
        raise LightingApplyError("Static mode 0 must be selected physically before writing")

    _send_profile(profile, write_report, pause)
    if _verify_static_profile(profile, read_report):
        return

    recovered = False
    if previous_profile is not None:
        try:
            _send_profile(previous_profile, write_report, pause)
            recovered = _verify_static_profile(previous_profile, read_report)
        except OSError:
            recovered = False
    detail = "read-back failed; previous profile restored" if recovered else "read-back failed; recovery is not verified"
    raise LightingApplyError(detail, recovered=recovered)


def _verify_static_profile(
    profile: LightingProfile,
    read_report: Callable[[], bytes | None],
    required_matches: int = 3,
    max_reports: int = 40,
) -> bool:
    matches = 0
    for _ in range(max_reports):
        report = read_report()
        if report is not None and report_matches_static_profile(report, profile):
            matches += 1
            if matches >= required_matches:
                return True
        else:
            matches = 0
    return False


def lighting_data_directory(data_home: Path | None = None) -> Path:
    root = data_home or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    directory = root / "openpad-hub" / "lighting" / "checkpoints"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory


def lighting_root_directory(data_home: Path | None = None) -> Path:
    return lighting_data_directory(data_home).parent


def safety_state_path(data_home: Path | None = None) -> Path:
    return lighting_root_directory(data_home) / "safety-state.json"


def load_safety_state(data_home: Path | None = None) -> LightingSafetyState:
    path = safety_state_path(data_home)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        state = LightingSafetyState(
            checkpoint=record.get("checks", {}).get("checkpoint") is True,
            readback=record.get("checks", {}).get("readback") is True,
            recovery=record.get("checks", {}).get("recovery") is True,
            active_profile_id=str(record.get("activeProfile", "")),
            checkpoint_path=str(record.get("checkpointPath", "")),
            reserved_configuration=str(record.get("reservedConfiguration", "")),
        )
        if state.active_profile_id:
            get_profile(state.active_profile_id)
        if state.checkpoint and not Path(state.checkpoint_path).is_file():
            return LightingSafetyState()
        return state
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return LightingSafetyState()


def save_safety_state(state: LightingSafetyState, data_home: Path | None = None) -> Path:
    root = lighting_root_directory(data_home)
    destination = safety_state_path(data_home)
    record = {
        "format": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "reservedConfiguration": state.reserved_configuration,
        "activeProfile": state.active_profile_id,
        "checkpointPath": state.checkpoint_path,
        "checks": {
            "checkpoint": state.checkpoint,
            "readback": state.readback,
            "recovery": state.recovery,
        },
    }
    fd, temporary_name = tempfile.mkstemp(prefix=".safety-", dir=root)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(record, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def latest_private_checkpoint(data_home: Path | None = None) -> Path | None:
    directory = lighting_data_directory(data_home)
    for candidate in sorted(directory.glob("*-lighting-checkpoint.json"), reverse=True):
        try:
            if candidate.is_file() and not candidate.stat().st_mode & 0o077:
                return candidate
        except OSError:
            continue
    return None


def create_checkpoint(
    snapshot: ControllerSnapshot,
    descriptor: bytes = b"",
    data_home: Path | None = None,
) -> Path:
    if not snapshot.connected or snapshot.product_id.lower() != "100b":
        raise ValueError("A Cyclone 2 in XInput mode (3537:100b) is required")
    if not snapshot.raw_report_hex or snapshot.rgb_profile is None:
        raise ValueError("A complete live lighting report is required")

    raw_report = bytes.fromhex(snapshot.raw_report_hex)
    timestamp = datetime.now(timezone.utc)
    record = {
        "format": 1,
        "createdAt": timestamp.isoformat(),
        "driver": "gamesir-cyclone2",
        "device": f"{snapshot.vendor_id.lower()}:{snapshot.product_id.lower()}",
        "connection": snapshot.connection.value,
        "hardwareProfile": snapshot.rgb_profile,
        "liveColors": snapshot.rgb_zones,
        "rawReport": snapshot.raw_report_hex,
        "rawReportSha256": hashlib.sha256(raw_report).hexdigest(),
        "descriptorSha256": hashlib.sha256(descriptor).hexdigest() if descriptor else None,
        "restorable": False,
        "reason": "Live telemetry is captured, but the original persistent effect is not fully readable yet.",
    }

    directory = lighting_data_directory(data_home)
    filename = timestamp.strftime("%Y%m%dT%H%M%SZ") + "-lighting-checkpoint.json"
    destination = directory / filename
    payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=".checkpoint-", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
