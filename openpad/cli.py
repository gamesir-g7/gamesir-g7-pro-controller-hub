from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpad.demo import DemoDriver
from openpad.drivers.cyclone2 import Cyclone2Driver
from openpad.services.rgb_lab import (
    RgbLabError,
    capture_directory,
    capture_usb_traffic,
    compare_captures,
    report_counts,
)
from openpad.services.lighting import LIGHTING_PROFILES, create_checkpoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openpad-hub", description="Open controller hub for Linux")
    parser.add_argument("--once", action="store_true", help="print one reading and exit")
    parser.add_argument("--json", action="store_true", help="use JSON with --once")
    parser.add_argument("--background", action="store_true", help="start in the system tray")
    parser.add_argument("--demo", action="store_true", help="use the safe simulated controller")
    parser.add_argument("--lighting-profiles", action="store_true", help="list the built-in read-only lighting previews")
    parser.add_argument("--lighting-checkpoint", action="store_true", help="save a private, non-restorable lighting checkpoint")
    rgb_lab = parser.add_mutually_exclusive_group()
    rgb_lab.add_argument("--rgb-capture", metavar="LABEL", help="passively capture USB traffic for RGB research")
    rgb_lab.add_argument("--rgb-inspect", type=Path, metavar="CAPTURE", help="list output reports without writing to the controller")
    rgb_lab.add_argument("--rgb-compare", type=Path, nargs=2, metavar=("BASE", "CHANGED"), help="compare two RGB captures")
    parser.add_argument("--capture-seconds", type=int, default=12, help="RGB capture duration (3-60 seconds)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.lighting_profiles:
        print(json.dumps([profile.to_dict() for profile in LIGHTING_PROFILES], ensure_ascii=False, indent=2))
        return 0
    if args.rgb_inspect or args.rgb_compare:
        try:
            reports = report_counts(args.rgb_inspect) if args.rgb_inspect else compare_captures(*args.rgb_compare)
        except (OSError, RgbLabError) as exc:
            print(f"Inspection failed: {exc}")
            return 2
        if not reports:
            print("No unknown outgoing reports were found.")
            return 0
        for payload, count in reports.most_common():
            print(f"{count:4}  {payload}")
        return 0
    if args.rgb_capture:
        print("Passive RGB lab: OpenPad Hub will not send commands to the controller.")
        print("Change exactly one RGB setting in the official software during this capture.")
        try:
            record = capture_usb_traffic(args.rgb_capture, args.capture_seconds)
        except RgbLabError as exc:
            print(f"Capture failed: {exc}")
            return 2
        print(f"Capture saved privately in {capture_directory() / record.capture_file}")
        return 0
    driver = DemoDriver() if args.demo else Cyclone2Driver()
    if args.lighting_checkpoint:
        snapshot = driver.read().snapshot
        try:
            path = create_checkpoint(snapshot)
        except (OSError, ValueError) as exc:
            print(f"Checkpoint failed: {exc}")
            return 2
        print(f"Private lighting checkpoint saved: {path}")
        print("This checkpoint is diagnostic only and cannot restore the original effect yet.")
        return 0
    if args.once:
        result = driver.read()
        inputs = driver.read_inputs()
        if args.json:
            snapshot = result.snapshot
            print(json.dumps({
                "connected": snapshot.connected,
                "model": snapshot.model,
                "productId": snapshot.product_id,
                "connection": snapshot.connection.value,
                "batteryPercent": snapshot.battery_percent,
                "chargeState": snapshot.charge_state.value,
                "rgbProfile": snapshot.rgb_profile,
                "rgbZones": snapshot.rgb_zones,
                "permissionRequired": snapshot.permission_required,
                "inputAvailable": inputs.available,
                "inputs": inputs.to_dict(),
            }, ensure_ascii=False))
        else:
            print(result.snapshot.label)
        return 0
    try:
        from openpad.qt_app import run_gui
    except ImportError as exc:
        print(f"Falta PySide6 para abrir la interfaz: {exc}")
        print("En Fedora: sudo dnf install python3-pyside6")
        return 1
    return run_gui(driver, background=args.background, demo=args.demo)
