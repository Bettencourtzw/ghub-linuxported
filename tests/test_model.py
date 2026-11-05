import base64
import unittest
from pathlib import Path

from ghub_linuxported.hidpp.mouse import HitsButton, decode_dpi_list, snap_dpi
from ghub_linuxported.hidpp.transport import build_request, match_reply, HidppError
from ghub_linuxported.model import hits_codes
from ghub_linuxported.model.buttons import (ButtonAction, KIND_KEY, KIND_MOUSE, KIND_FUNCTION,
                                            KIND_DEFAULT, KIND_DISABLED, KIND_CONSUMER)
from ghub_linuxported.model.profile import (Profile, crc16_ccitt, crc_ok, parse_directory,
                                            build_directory, DirectoryEntry)

FIXTURE = Path(__file__).parent / "fixtures" / "xatuke_profile1.bin"


class CrcTests(unittest.TestCase):
    def test_check_value(self):
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)  # CRC-16/CCITT-FALSE check

    def test_fixture_crc(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(len(raw), 255)
        self.assertTrue(crc_ok(raw))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.p = Profile.parse(1, self.raw)

    def test_fields(self):
        p = self.p
        self.assertEqual(p.rate_wireless_hz, 1000)
        self.assertEqual(p.default_stage, 2)
        self.assertEqual([(s.x, s.y, s.lod) for s in p.stages],
                         [(800, 800, 2), (1200, 1200, 2), (800, 800, 2), (2400, 2400, 2), (3200, 3200, 2)])
        self.assertEqual([(h.actuation, h.rt_level, h.rt_enabled, h.haptics) for h in p.hits],
                         [(2, 2, False, 3), (2, 2, False, 3)])
        self.assertEqual((p.power_save_s, p.power_off_s), (60, 300))
        self.assertEqual([a.code for a in p.buttons], [1, 2, 4, 8, 0x10])
        self.assertEqual(p.name, "PROFILE_NAME_DEFAULT")
        self.assertEqual(p.display_name, "Profile 1")
        self.assertEqual(p.bhop_ms, 0)

    def test_round_trip_is_byte_exact(self):
        self.assertEqual(self.p.serialize(), self.raw)

    def test_edit_only_touches_fields(self):
        p = self.p
        p.stages[0].x = 1600
        p.hits[0] = HitsButton(1, 3, True, 5)
        p.bhop_ms = 250
        p.rate_wireless_hz = 8000
        p.name = "CS2"
        out = p.serialize()
        self.assertTrue(crc_ok(out))
        q = Profile.parse(1, out)
        self.assertEqual(q.stages[0].x, 1600)
        self.assertEqual((q.hits[0].actuation, q.hits[0].rapid_trigger, q.hits[0].haptics), (1, 3, 5))
        self.assertEqual(q.bhop_ms, 250)
        self.assertEqual(q.rate_wireless_hz, 8000)
        self.assertEqual(q.name, "CS2")
        changed = [i for i in range(253) if out[i] != self.raw[i]]
        allowed = set(range(0x00, 0x01)) | set(range(0x04, 0x06)) | {0x25, 0x26, 0x27, 0x28} | set(range(0xA0, 0xD0))
        self.assertTrue(set(changed) <= allowed, [hex(i) for i in changed])

    def test_validation(self):
        for s in self.p.stages:
            s.lod = 0
        with self.assertRaises(ValueError):
            self.p.serialize()

    def test_json_round_trip(self):
        d = self.p.to_json()
        q = Profile.parse(1, self.raw)
        q.stages[1].x = 5000
        q.apply_json(d)
        self.assertEqual(q.serialize(), self.raw)


class DirectoryTests(unittest.TestCase):
    def test_parse_and_build(self):
        raw = bytearray(b"\xff" * 255)
        raw[0:22] = bytes.fromhex("000101ff000200ff000300ff000400ff000500ffffff")
        raw = bytes(raw[:-2]) + crc16_ccitt(bytes(raw[:-2])).to_bytes(2, "big")
        entries = parse_directory(raw)
        self.assertEqual([(e.sector, e.enabled) for e in entries],
                         [(1, True), (2, False), (3, False), (4, False), (5, False)])
        entries[2].enabled = True
        out = build_directory(entries, 255, raw)
        self.assertTrue(crc_ok(out))
        self.assertEqual(out[8:12], bytes.fromhex("000301ff"))
        self.assertEqual(out[22:253], raw[22:253])


class HitsCodeTests(unittest.TestCase):
    def test_all_pro_presets_decode_and_reencode(self):
        for player, _game, code in hits_codes.PRO_PRESETS:
            left, right = hits_codes.decode(code)
            self.assertEqual(hits_codes.encode(left, right), code, player)

    def test_ins(self):
        left, right = hits_codes.decode("MDAwNDA1MDMwNTEwMDQwMw==")
        self.assertEqual((left.actuation, left.rt_level, left.rt_enabled, left.haptics), (4, 3, True, 4))
        self.assertEqual((right.actuation, right.rt_level, right.rt_enabled, right.haptics), (5, 5, False, 3))

    def test_rejects_garbage(self):
        for bad in ["hello", base64.b64encode(b"0006060101110555").decode(), "", "MDAw"]:
            with self.assertRaises(hits_codes.InvalidHitsCode):
                hits_codes.decode(bad)

    def test_wire_encoding_matches_ghub_capture(self):
        # G HUB capture: 11 01 0c 1d 00 0c 09 14 -> left, actuation 3, rt 2 + enable, haptics 5
        h = HitsButton.from_wire(bytes.fromhex("0c0914"))
        self.assertEqual((h.actuation, h.rt_level, h.rt_enabled, h.haptics), (3, 2, True, 5))
        self.assertEqual(h.to_wire(), bytes.fromhex("0c0914"))


class ButtonTests(unittest.TestCase):
    def test_round_trips(self):
        for hexs, kind in [("80010001", KIND_MOUSE), ("80020206", KIND_KEY), ("800300cd", KIND_CONSUMER),
                           ("9005ff00", KIND_FUNCTION), ("ffffffff", KIND_DEFAULT), ("8000ffff", KIND_DISABLED)]:
            a = ButtonAction.decode(bytes.fromhex(hexs))
            self.assertEqual(a.kind, kind, hexs)
            self.assertEqual(a.encode().hex(), hexs)

    def test_describe(self):
        self.assertEqual(ButtonAction.decode(bytes.fromhex("80020206")).describe(), "Shift+C")
        self.assertEqual(ButtonAction.decode(bytes.fromhex("80010008")).describe(), "Back")
        self.assertEqual(ButtonAction.decode(bytes.fromhex("9005ff00")).describe(), "Cycle DPI stages")
        self.assertEqual(ButtonAction.decode(b"\x00\x12\x34\x56").encode(), b"\x00\x12\x34\x56")


class TransportTests(unittest.TestCase):
    def test_build_short_and_long(self):
        self.assertEqual(build_request(0xFF, 0, 1, 0xA, b"\x00\x00\x5a").hex(), "10ff001a00005a")
        long = build_request(1, 0x0C, 1, 0xA, bytes.fromhex("000c0914"))
        self.assertEqual(len(long), 20)
        self.assertEqual(long[:8].hex(), "11010c1a000c0914")

    def test_match(self):
        kind, params = match_reply(bytes.fromhex("11010c2a00080c0c") + bytes(12), 0x0C, 2, 0xA)
        self.assertEqual(kind, "ok")
        self.assertEqual(params[:4].hex(), "00080c0c")
        self.assertEqual(match_reply(bytes.fromhex("11010c2b00") + bytes(15), 0x0C, 2, 0xA), (None, None))
        kind, err = match_reply(bytes.fromhex("1101ff0c1a02") + bytes(14), 0x0C, 1, 0xA)
        self.assertEqual(kind, "error")
        self.assertIsInstance(err, HidppError)
        self.assertEqual(err.code, 2)
        self.assertEqual(match_reply(bytes.fromhex("0200010203"), 0x0C, 1, 0xA), (None, None))


class DpiListTests(unittest.TestCase):
    def test_decode(self):
        stream = [100, 0xE000 | 1, 200, 0xE000 | 2, 500, 0xE000 | 200, 44000, 0]
        ranges = decode_dpi_list(stream)
        self.assertEqual(ranges[0], (100, 100, 1))
        self.assertEqual(ranges[-1], (700, 44000, 200))
        self.assertEqual(snap_dpi(150, ranges), 150)
        self.assertEqual(snap_dpi(301, ranges), 302)
        self.assertEqual(snap_dpi(50000, ranges), 44000)
        self.assertEqual(snap_dpi(799, ranges), 700 + 200 * round(99 / 200))


if __name__ == "__main__":
    unittest.main()
