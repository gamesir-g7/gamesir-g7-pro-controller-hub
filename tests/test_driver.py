import unittest
from unittest.mock import patch

from openpad.domain import ChargeState, ConnectionType
from openpad.drivers.cyclone2 import (
    BUTTON_CODES,
    Cyclone2Driver,
    extra_button_name,
    normalize_linux_axis,
    parse_capability_bits,
    parse_cyclone2_report,
    parse_input_report,
    parse_upower,
)


class Cyclone2ProtocolTests(unittest.TestCase):
    def test_parses_verified_charging_report(self):
        report = bytearray(64)
        report[0] = 0x12
        report[1:5] = bytes([255, 128, 1, 128])
        report[35] = 1
        report[36] = 45
        report[37] = 3
        report[38:53] = bytes([255, 206, 0, 79, 0, 177, 0, 97, 206, 0, 0, 0, 97, 255, 0])
        result = parse_cyclone2_report(bytes(report), "/dev/hidraw2")
        self.assertIsNotNone(result)
        self.assertEqual(result.snapshot.battery_percent, 45)
        self.assertEqual(result.snapshot.charge_state, ChargeState.CHARGING)
        self.assertEqual(result.snapshot.rgb_profile, 3)
        self.assertEqual(result.snapshot.rgb_zones, ["#FFCE00", "#4F00B1", "#0061CE", "#000000", "#61FF00"])
        self.assertTrue(result.snapshot.capabilities.rgb_read)
        self.assertTrue(result.snapshot.capabilities.rgb)
        self.assertTrue(result.snapshot.capabilities.profiles)
        self.assertFalse(result.inputs.available)
        self.assertEqual(result.inputs.left_x, 0.0)

    def test_rejects_corrupt_or_truncated_reports(self):
        self.assertIsNone(parse_cyclone2_report(bytes(64)))
        report = bytearray(37)
        report[0], report[35], report[36] = 0x12, 3, 101
        self.assertIsNone(parse_cyclone2_report(bytes(report)))

    def test_short_valid_report_keeps_battery_without_inventing_rgb(self):
        report = bytearray(37)
        report[0], report[35], report[36] = 0x12, 0, 58
        result = parse_cyclone2_report(bytes(report))
        self.assertEqual(result.snapshot.battery_percent, 58)
        self.assertIsNone(result.snapshot.rgb_profile)
        self.assertEqual(result.snapshot.rgb_zones, [])

    def test_input_report_defaults_safely(self):
        self.assertEqual(parse_input_report(b"\x12").to_dict()["pressed"], [])

    def test_standard_linux_axes_are_normalized(self):
        self.assertEqual(normalize_linux_axis(-32768, -32768, 32767), -1.0)
        self.assertAlmostEqual(normalize_linux_axis(255, 0, 255, trigger=True), 1.0)
        self.assertEqual(normalize_linux_axis(7, -32768, 32767, flat=128), 0.0)

    def test_linux_button_capabilities_and_extras_are_named(self):
        bits = parse_capability_bits("7cdb000000000000 0 0 0 0")
        self.assertTrue({0x130, 0x131, 0x13C, 0x13D, 0x13E}.issubset(bits))
        self.assertEqual(extra_button_name(0x2C0), "M1")
        self.assertEqual(extra_button_name(30, "Keyboard"), "Key A")

    def test_xbox_north_and_west_buttons_are_not_swapped(self):
        self.assertEqual(BUTTON_CODES[0x133], "X")
        self.assertEqual(BUTTON_CODES[0x134], "Y")

    def test_upower_charging_and_unrelated_devices(self):
        snapshot = parse_upower("""
          native-path: ps-controller-battery
          model: GameSir Cyclone 2
          type: gaming-input
          state: charging
          percentage: 42%
        """)
        self.assertEqual(snapshot.battery_percent, 42)
        self.assertEqual(snapshot.charge_state, ChargeState.CHARGING)
        self.assertEqual(snapshot.connection, ConnectionType.BLUETOOTH)
        self.assertIsNone(parse_upower("model: Laptop Battery\ntype: battery\npercentage: 80%"))

    def test_usb_mode_never_invents_battery(self):
        driver = Cyclone2Driver()
        with (
            patch.object(driver, "_read_hid", return_value=None),
            patch.object(driver, "_read_upower", return_value=None),
            patch.object(driver, "_usb_device", return_value=("0575", "GameSir Cyclone 2")),
            patch.object(driver, "_find_hidraw", return_value=None),
        ):
            snapshot = driver.read_snapshot()
        self.assertTrue(snapshot.connected)
        self.assertIsNone(snapshot.battery_percent)
        self.assertEqual(snapshot.status_key, "power_only")

    def test_settings_writes_require_explicit_reserved_configuration_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "four physical indicators"):
            Cyclone2Driver().write_settings({"rgb": "purple"})
        with self.assertRaisesRegex(RuntimeError, "four physical.*indicators"):
            Cyclone2Driver().commission_lighting(False)


if __name__ == "__main__":
    unittest.main()
