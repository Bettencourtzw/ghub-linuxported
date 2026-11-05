import unittest
from pathlib import Path

from ghub_linuxported.model.profile import Profile, crc_ok, parse_directory

FIX = Path(__file__).parent / "fixtures"


class RealUnitDumpTests(unittest.TestCase):
    def setUp(self):
        self.raw = (FIX / "unit_profile1.bin").read_bytes()

    def test_crc_and_round_trip(self):
        self.assertTrue(crc_ok(self.raw))
        self.assertEqual(Profile.parse(1, self.raw).serialize(), self.raw)

    def test_fields(self):
        p = Profile.parse(1, self.raw)
        self.assertEqual([s.x for s in p.stages], [800, 1200, 1600, 2400, 3200])
        self.assertEqual([(h.actuation, h.rt_level, h.rt_enabled, h.haptics) for h in p.hits], [(5, 2, False, 3)] * 2)
        self.assertEqual(p.bhop_ms, 0)

    def test_bhop_ff_preserved_and_settable(self):
        p = Profile.parse(1, self.raw)
        self.assertEqual(p.serialize()[0x25], 0xFF)
        p.bhop_ms = 150
        self.assertEqual(p.serialize()[0x25], 15)

    def test_directory(self):
        d = parse_directory((FIX / "unit_directory.bin").read_bytes())
        self.assertEqual([(e.sector, e.enabled) for e in d], [(1, True), (2, False), (3, False), (4, False), (5, False)])


if __name__ == "__main__":
    unittest.main()
