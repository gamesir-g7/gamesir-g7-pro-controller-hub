from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_VENDOR = "3537"
SUPPORTED_PRODUCT = "100b"
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
USBMON_MMAP_LINKTYPE = 220
KNOWN_HEARTBEAT = bytes((0x0F, 0xF2, 0x00))


class RgbLabError(RuntimeError):
    """Raised before capture when the passive workflow cannot run safely."""


@dataclass(frozen=True)
class UsbDevice:
    vendor_id: str
    product_id: str
    bus: int
    address: int
    sysfs_name: str


@dataclass(frozen=True)
class CaptureRecord:
    label: str
    captured_at: str
    seconds: int
    vendor_id: str
    product_id: str
    bus: int
    address: int
    capture_file: str
    sha256: str


@dataclass(frozen=True)
class UsbTransfer:
    bus: int
    address: int
    endpoint: int
    payload: bytes


def find_supported_device(sysfs_root: Path = Path("/sys/bus/usb/devices")) -> UsbDevice | None:
    for candidate in sorted(sysfs_root.glob("*")):
        try:
            vendor = (candidate / "idVendor").read_text().strip().lower()
            product = (candidate / "idProduct").read_text().strip().lower()
            bus = int((candidate / "busnum").read_text().strip())
            address = int((candidate / "devnum").read_text().strip())
        except (OSError, ValueError):
            continue
        if vendor == SUPPORTED_VENDOR and product == SUPPORTED_PRODUCT:
            return UsbDevice(vendor, product, bus, address, candidate.name)
    return None


def validate_label(label: str) -> str:
    normalized = label.strip().lower()
    if not LABEL_PATTERN.fullmatch(normalized):
        raise RgbLabError("Use a short label containing only letters, numbers, '-' or '_'.")
    return normalized


def capture_directory(data_home: Path | None = None) -> Path:
    root = data_home or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    directory = root / "openpad-hub" / "rgb-lab"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory


def build_capture_command(device: UsbDevice, seconds: int) -> list[str]:
    tcpdump = shutil.which("tcpdump")
    pkexec = shutil.which("pkexec")
    timeout = shutil.which("timeout")
    if not tcpdump or not pkexec or not timeout:
        raise RgbLabError("Passive capture requires tcpdump, timeout and pkexec.")
    if not 3 <= seconds <= 60:
        raise RgbLabError("Capture duration must be between 3 and 60 seconds.")
    # usbmon's stable binary ABI stores devnum at byte 11 and the little-endian
    # busnum at bytes 12-13. Raw link offsets keep the capture restricted even
    # on libpcap versions without symbolic USB filter fields.
    packet_filter = (
        f"link[11] = {device.address} and "
        f"link[12] = {device.bus & 0xff} and link[13] = {(device.bus >> 8) & 0xff}"
    )
    return [
        pkexec,
        timeout,
        "--signal=INT",
        "--kill-after=2",
        str(seconds),
        tcpdump,
        "-i",
        f"usbmon{device.bus}",
        "-nn",
        "-s",
        "0",
        "-U",
        "-w",
        "-",
        packet_filter,
    ]


def capture_usb_traffic(label: str, seconds: int = 12, data_home: Path | None = None) -> CaptureRecord:
    """Capture only the verified device through usbmon; never write to HID."""
    safe_label = validate_label(label)
    device = find_supported_device()
    if device is None:
        raise RgbLabError("Connect the Cyclone 2 receiver (3537:100b) before capturing.")
    command = build_capture_command(device, seconds)
    directory = capture_directory(data_home)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    capture_path = directory / f"{timestamp}-{safe_label}.pcap"

    with capture_path.open("xb") as output:
        capture_path.chmod(0o600)
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=False)
    # GNU timeout returns 124 after the requested duration. tcpdump can also
    # exit cleanly when it receives SIGINT.
    if result.returncode not in (0, 124):
        capture_path.unlink(missing_ok=True)
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RgbLabError(detail or "Passive USB capture failed.")
    if capture_path.stat().st_size < 24:
        capture_path.unlink(missing_ok=True)
        raise RgbLabError("The capture was empty; no controller traffic was observed.")

    digest = hashlib.sha256(capture_path.read_bytes()).hexdigest()
    record = CaptureRecord(
        label=safe_label,
        captured_at=datetime.now(timezone.utc).isoformat(),
        seconds=seconds,
        vendor_id=device.vendor_id,
        product_id=device.product_id,
        bus=device.bus,
        address=device.address,
        capture_file=capture_path.name,
        sha256=digest,
    )
    manifest_path = capture_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(asdict(record), indent=2) + "\n")
    manifest_path.chmod(0o600)
    return record


def read_outgoing_transfers(capture_path: Path) -> list[UsbTransfer]:
    """Read outgoing usbmon submissions from a private tcpdump capture."""
    raw = capture_path.read_bytes()
    if len(raw) < 24:
        raise RgbLabError("The capture is truncated.")
    magic = raw[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise RgbLabError("Unsupported capture format; use the OpenPad RGB lab capture command.")
    linktype = struct.unpack_from(f"{endian}I", raw, 20)[0]
    if linktype != USBMON_MMAP_LINKTYPE:
        raise RgbLabError("The capture does not use the expected usbmon mmap format.")

    transfers: list[UsbTransfer] = []
    offset = 24
    while offset + 16 <= len(raw):
        _, _, included, _ = struct.unpack_from(f"{endian}IIII", raw, offset)
        offset += 16
        if included > len(raw) - offset:
            raise RgbLabError("The capture contains a truncated packet.")
        packet = raw[offset:offset + included]
        offset += included
        if len(packet) < 64 or packet[8] != ord("S") or packet[10] & 0x80:
            continue
        captured_length = struct.unpack_from(f"{endian}I", packet, 36)[0]
        if captured_length == 0 or len(packet) < 64 + captured_length:
            continue
        bus = struct.unpack_from(f"{endian}H", packet, 12)[0]
        transfers.append(UsbTransfer(
            bus=bus,
            address=packet[11],
            endpoint=packet[10] & 0x0F,
            payload=packet[64:64 + captured_length],
        ))
    return transfers


def report_counts(capture_path: Path, include_heartbeat: bool = False) -> Counter[str]:
    reports: Counter[str] = Counter()
    for transfer in read_outgoing_transfers(capture_path):
        payload = transfer.payload
        padded_heartbeat = payload[:3] == KNOWN_HEARTBEAT and not any(payload[3:])
        if padded_heartbeat and not include_heartbeat:
            continue
        reports[payload.hex(" ")] += 1
    return reports


def compare_captures(baseline: Path, changed: Path) -> Counter[str]:
    """Return output reports that occur more often after one controlled change."""
    difference = report_counts(changed)
    difference.subtract(report_counts(baseline))
    return Counter({payload: count for payload, count in difference.items() if count > 0})
