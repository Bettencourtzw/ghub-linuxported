"""Save-path tests against a simulated mouse with flash memory."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ghub_linuxported import service as service_mod, storage
from ghub_linuxported.hidpp.mouse import OnboardInfo, Identity, HitsButton, ONBOARD_MODE
from ghub_linuxported.model.profile import Profile, crc_ok, parse_directory

FIXTURE = (Path(__file__).parent / "fixtures" / "xatuke_profile1.bin").read_bytes()


class FakeMouse:
    def __init__(self, ram_profiles=True, corrupt_writes=False):
        self.onboard = OnboardInfo(1, 8, 1, 5, 1, 5, 16, 255)
        self.flash = {0x0101: FIXTURE[:-2] + b"\xff\xff", 0x0100: b"\xff" * 255}
        if ram_profiles:
            d = bytearray(b"\xff" * 255)
            d[0:22] = bytes.fromhex("000101ff000200ff000300ff000400ff000500ffffff")
            from ghub_linuxported.model.profile import with_crc
            self.flash[0] = with_crc(bytes(d))
            for s in range(1, 6):
                self.flash[s] = FIXTURE
            self.active = 1
        else:
            self.flash[0] = b"\xff" * 255
            self.active = 0x0101
        self.corrupt_writes = corrupt_writes
        self.writes = []
        self.mode = ONBOARD_MODE
        self.activations = []

    def read_sector(self, sector, size=None):
        return self.flash.get(sector, b"\xff" * 255)

    def write_sector(self, sector, data):
        self.writes.append(sector)
        self.flash[sector] = data if not self.corrupt_writes else b"\x00" + data[1:]

    def set_current_profile(self, sector):
        self.activations.append(sector)
        self.active = sector

    def current_profile(self):
        return self.active

    def mode_set(self, mode):
        self.mode = mode


class ServiceSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(storage, "BACKUP_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def make(self, **kw):
        svc = service_mod.DeviceService()
        svc.mouse = FakeMouse(**kw)
        svc.snapshot.identity = Identity(unit_id="test")
        svc.snapshot.active_sector = svc.mouse.active
        svc.snapshot.directory = parse_directory(svc.mouse.flash[0]) if crc_ok(svc.mouse.flash[0]) else []
        svc.refresh = lambda: None  # refresh needs the full HID++ API; not under test here
        return svc

    def test_save_writes_backup_and_verifies(self):
        svc = self.make()
        p = Profile.parse(1, FIXTURE)
        p.stages[0].x = 1600
        p.hits[1] = HitsButton(5, 1, True, 0)
        svc.save_profile(p)
        self.assertEqual(svc.mouse.writes, [1])
        q = Profile.parse(1, svc.mouse.flash[1])
        self.assertEqual(q.stages[0].x, 1600)
        self.assertEqual(q.hits[1].haptics, 0)
        backups = list(Path(self.tmp.name).glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(svc.mouse.activations[-1], 1)  # reloaded

    def test_unchanged_save_writes_nothing(self):
        svc = self.make()
        svc.save_profile(Profile.parse(1, FIXTURE))
        self.assertEqual(svc.mouse.writes, [])

    def test_verification_failure_raises(self):
        svc = self.make(corrupt_writes=True)
        p = Profile.parse(1, FIXTURE)
        p.stages[0].x = 1600
        with self.assertRaises(service_mod.SaveError):
            svc.save_profile(p)
        self.assertEqual(svc.mouse.writes, [1])  # exactly one write, no retry loop

    def test_pristine_mouse_clones_factory_profile(self):
        svc = self.make(ram_profiles=False)
        p = Profile.parse(0x0101, svc.mouse.flash[0x0101])
        p.stages[0].x = 400
        svc.save_profile(p)
        self.assertTrue(crc_ok(svc.mouse.flash[1]))
        self.assertEqual(Profile.parse(1, svc.mouse.flash[1]).stages[0].x, 400)
        d = parse_directory(svc.mouse.flash[0])
        self.assertEqual((d[0].sector, d[0].enabled), (1, True))
        self.assertEqual(svc.mouse.active, 1)

    def test_bad_crc_never_written(self):
        svc = self.make()
        with self.assertRaises(service_mod.SaveError):
            svc._write_verified(1, FIXTURE[:-1] + b"\x00", "test")
        self.assertEqual(svc.mouse.writes, [])

    def test_failed_backup_read_never_writes(self):
        from ghub_linuxported.hidpp.transport import HidppError
        svc = self.make()
        with mock.patch.object(svc.mouse, "read_sector", side_effect=HidppError(1, 0, 1, b"error")):
            with self.assertRaises(service_mod.SaveError):
                svc._write_verified(1, FIXTURE, "test")
        self.assertEqual(svc.mouse.writes, [])

    def test_incomplete_backup_read_never_writes(self):
        svc = self.make()
        with mock.patch.object(svc.mouse, "read_sector", return_value=b"short"):
            with self.assertRaises(service_mod.SaveError):
                svc._write_verified(1, FIXTURE, "test")
        self.assertEqual(svc.mouse.writes, [])

    def test_cannot_disable_last_profile(self):
        svc = self.make()
        for e in svc.snapshot.directory[1:]:
            e.enabled = False
        with self.assertRaises(service_mod.SaveError):
            svc.set_profile_enabled(1, False)


if __name__ == "__main__":
    unittest.main()
