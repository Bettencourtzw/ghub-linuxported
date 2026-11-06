import unittest
from pathlib import Path
from unittest.mock import patch

from ghub_linuxported.devices import FoundDevice
from ghub_linuxported import assets


class DeviceArtworkTests(unittest.TestCase):
    def test_known_products_resolve_offline(self):
        for pid, name in ((0x40BD, 'pro-x2-superstrike.png'), (0xC0A8, 'pro-x2-superstrike.png'),
                          (0x40B4, 'g515-lightspeed-tkl.png')):
            with self.subTest(pid=pid):
                path = assets.device_image(FoundDevice('/dev/test', pid, ''))
                self.assertEqual(path.name, name)
                self.assertTrue(path.is_file())

    def test_exact_reported_name_can_resolve_without_known_pid(self):
        dev = FoundDevice('/dev/test', 0, '', name='Logitech G515 LIGHTSPEED TKL')
        self.assertEqual(assets.device_image(dev).name, 'g515-lightspeed-tkl.png')

    def test_unknown_and_similarly_named_products_have_no_photo(self):
        for name in ('G515 RAPID TKL', 'G515 TKL', 'PRO X SUPERLIGHT 2', '../../etc/passwd', ''):
            with self.subTest(name=name):
                dev = FoundDevice('/dev/test', 0, name, kind='keyboard', model='keyboard')
                self.assertIsNone(assets.device_image(dev))

    def test_missing_asset_falls_back(self):
        with patch.object(Path, 'is_file', return_value=False):
            self.assertIsNone(assets.device_image(FoundDevice('/dev/test', 0x40BD, '')))

    def test_brand_alias_uses_the_current_artwork(self):
        self.assertTrue(assets.APP_ICON.is_file())
        alias = assets.APP_ICON.with_name(assets.APP_ICON_NAME + '.svg')
        self.assertEqual(alias.resolve(), assets.APP_ICON.resolve())


if __name__ == '__main__':
    unittest.main()
