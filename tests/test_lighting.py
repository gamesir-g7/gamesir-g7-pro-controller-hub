import json
import stat
import tempfile
import unittest
from pathlib import Path

from openpad.domain import ConnectionType, ControllerSnapshot
from openpad.services.lighting import (
    LIGHTING_PROFILES,
    ZONE_REGISTERS,
    STATIC_ZONE_OFFSETS,
    build_led_register_write,
    build_profile_reports,
    build_static_zone_reports,
    build_static_mode,
    create_checkpoint,
    get_profile,
    latest_private_checkpoint,
    apply_profile_transaction,
    LightingApplyError,
    LightingSafetyState,
    load_safety_state,
    expected_static_zones,
    report_matches_static_profile,
    save_safety_state,
)


class LightingSafetyTests(unittest.TestCase):
    def test_original_profiles_are_complete_and_bounded(self):
        self.assertEqual(len(LIGHTING_PROFILES), 8)
        self.assertEqual(len({profile.profile_id for profile in LIGHTING_PROFILES}), 8)
        for profile in LIGHTING_PROFILES:
            self.assertEqual(len(profile.zones), 4)
            self.assertTrue(0 <= profile.brightness <= 100)
            for color in profile.zones:
                self.assertRegex(color, r"^#[0-9A-F]{6}$")

    def test_protocol_frames_match_the_public_capture_specification(self):
        brightness = build_led_register_write(0x04, bytes((100,)))
        self.assertEqual(brightness[:7], bytes((0x0F, 0x03, 0x20, 0x00, 0x04, 0x01, 0x64)))
        self.assertEqual(len(brightness), 64)

        static = build_static_mode("#FF0000")
        self.assertEqual(static[:10], bytes((0x0F, 0x03, 0x20, 0x00, 0x01, 0x3A, 0x01, 0x05, 0x0A, 0x32)))
        self.assertEqual(static[10:19], bytes.fromhex("ff0000ff0000ff0000"))

    def test_profile_sequence_is_static_four_zones_then_brightness(self):
        profile = get_profile("aurora-drift")
        reports = build_profile_reports(profile)
        self.assertEqual(len(reports), 6)
        self.assertEqual(reports[0][4], 0x01)
        self.assertEqual(tuple(report[4] for report in reports[1:5]), ZONE_REGISTERS)
        self.assertEqual(reports[-1][4:7], bytes((0x04, 0x01, profile.brightness)))

        zone_reports = build_static_zone_reports(profile)
        self.assertEqual(tuple(report[4] for report in zone_reports), ZONE_REGISTERS)

    @staticmethod
    def _static_report(profile_id: str) -> bytes:
        profile = get_profile(profile_id)
        report = bytearray(64)
        report[0] = 0x12
        report[37] = 0
        for offset, color in zip(STATIC_ZONE_OFFSETS, expected_static_zones(profile), strict=True):
            report[offset:offset + 3] = bytes.fromhex(color[1:])
        return bytes(report)

    def test_static_readback_maps_and_scales_the_four_real_zones(self):
        profile = get_profile("aurora-drift")
        report = self._static_report(profile.profile_id)
        self.assertTrue(report_matches_static_profile(report, profile))
        animated = bytearray(report)
        animated[37] = 1
        self.assertFalse(report_matches_static_profile(bytes(animated), profile))

    def test_every_built_in_profile_has_unambiguous_static_readback(self):
        rendered = {}
        for profile in LIGHTING_PROFILES:
            report = self._static_report(profile.profile_id)
            self.assertTrue(report_matches_static_profile(report, profile))
            zones = tuple(expected_static_zones(profile))
            self.assertNotIn(zones, rendered)
            rendered[zones] = profile.profile_id

    def test_checkpoint_is_private_atomic_and_explicitly_not_restorable(self):
        snapshot = ControllerSnapshot(
            connected=True,
            product_id="100b",
            connection=ConnectionType.WIRELESS,
            rgb_profile=3,
            rgb_zones=["#112233", "#445566", "#778899", "#000000", "#AABBCC"],
            raw_report_hex=bytes(range(64)).hex(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = create_checkpoint(snapshot, b"descriptor", Path(directory))
            record = json.loads(path.read_text())
            self.assertFalse(record["restorable"])
            self.assertEqual(record["hardwareProfile"], 3)
            self.assertEqual(record["device"], "3537:100b")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(latest_private_checkpoint(Path(directory)), path)

    def test_checkpoint_rejects_unverified_mode_or_incomplete_report(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                create_checkpoint(ControllerSnapshot(connected=True, product_id="0575"), data_home=Path(directory))
            with self.assertRaises(ValueError):
                create_checkpoint(ControllerSnapshot(connected=True, product_id="100b"), data_home=Path(directory))

    def test_transaction_requires_independent_verification_and_private_checkpoint(self):
        profile = get_profile("neon-sakura")
        written = []
        reads = iter([self._static_report("aurora-drift")] + [self._static_report(profile.profile_id)] * 3)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text("{}")
            checkpoint.chmod(0o600)
            apply_profile_transaction(profile, written.append, lambda: next(reads, None), checkpoint, pause=lambda _: None)
        self.assertEqual(len(written), 4)

    def test_failed_change_restores_previous_verified_profile(self):
        requested = get_profile("ember-core")
        previous = get_profile("aurora-drift")
        written = []
        invalid = bytearray(self._static_report(requested.profile_id))
        invalid[38] ^= 0x01
        reads = iter(
            [self._static_report(previous.profile_id)]
            + [bytes(invalid)] * 40
            + [self._static_report(previous.profile_id)] * 3
        )
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text("{}")
            checkpoint.chmod(0o600)
            with self.assertRaises(LightingApplyError) as raised:
                apply_profile_transaction(
                    requested,
                    written.append,
                    lambda: next(reads, None),
                    checkpoint,
                    previous_profile=previous,
                    pause=lambda _: None,
                )
        self.assertTrue(raised.exception.recovered)
        self.assertEqual(len(written), 8)

    def test_safety_state_is_private_and_requires_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            data_home = Path(directory)
            checkpoint = data_home / "checkpoint.json"
            checkpoint.write_text("{}")
            checkpoint.chmod(0o600)
            state = LightingSafetyState(True, True, True, "aurora-drift", str(checkpoint), "configuration-3")
            path = save_safety_state(state, data_home)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertTrue(load_safety_state(data_home).unlocked)
            checkpoint.unlink()
            self.assertFalse(load_safety_state(data_home).unlocked)


if __name__ == "__main__":
    unittest.main()
