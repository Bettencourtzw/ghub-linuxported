"""Regression checks for audited write, import, reconnect and settings failures."""
import copy
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ghub_linuxported import devices, storage
from ghub_linuxported.hidpp.mouse import Mouse, FeatureMissing, Identity
from ghub_linuxported.hidpp.transport import HidppTimeout, HidppError
from ghub_linuxported.keyboard_service import KeyboardService, DEFAULT_STATE, save_state
from ghub_linuxported.model.profile import Profile
from ghub_linuxported.worker import DeviceWorker

FIXTURE = (Path(__file__).parent / 'fixtures/xatuke_profile1.bin').read_bytes()


class WorkerSafetyTests(unittest.TestCase):
    def test_close_finishes_write_then_restore_then_releases_device(self):
        worker = DeviceWorker()
        worker.dev = Mock()
        entered, release = threading.Event(), threading.Event()
        order = []
        def write(_):
            entered.set()
            self.assertTrue(release.wait(2))
            order.append('write')
        worker.submit(write)
        worker.submit(lambda _: order.append('restore'))
        worker.on_stop = lambda: order.append('release')
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            worker.stop(wait=0)
            self.assertTrue(worker._thread.is_alive())
            release.set()
            worker.stop(wait=2)
            self.assertFalse(worker._thread.is_alive())
            self.assertEqual(order, ['write', 'restore', 'release'])
            worker.dev.close.assert_called_once()
        finally:
            release.set()
            worker.stop(wait=2)

    def test_disconnected_close_reports_queued_work_and_exits(self):
        worker = DeviceWorker()
        error = Mock()
        worker.submit(Mock(), on_error=error)
        worker.stop(wait=0)
        worker.start()
        worker.stop(wait=2)
        self.assertFalse(worker._thread.is_alive())
        self.assertIsInstance(error.call_args.args[0], ConnectionError)

    def test_failed_initialization_closes_handle_and_can_retry(self):
        worker = DeviceWorker()
        bad, good = Mock(), Mock()
        worker.open_device = Mock(side_effect=[bad, good])
        worker.refresh = Mock(side_effect=[FeatureMissing('RGB'), None])
        with patch('ghub_linuxported.worker.traceback.print_exc'):
            worker._try_connect()
        bad.close.assert_called_once()
        self.assertIsNone(worker.dev)
        worker._try_connect()
        self.assertIs(worker.dev, good)
        self.assertEqual(worker.status, 'connected')

    def test_shutdown_rejects_new_commands(self):
        worker = DeviceWorker()
        worker.stop()
        error = Mock()
        worker.submit(Mock(), on_error=error)
        self.assertIsInstance(error.call_args.args[0], ConnectionError)


class ImportSafetyTests(unittest.TestCase):
    def test_invalid_imports_preserve_entire_edit(self):
        invalid = [[], {'default_stage': 99}, {'default_stage': -1}, {'stages': []},
                   {'hits': []}, {'buttons': ['ff'] * 5}, {'buttons': ['ffffffff'] * 6},
                   {'shift_buttons': None}, {'name': None}, {'name': 'a\x00b'},
                   {'power_save_s': -1}, {'power_off_s': 65536}, {'bhop_ms': 105},
                   {'rate_wired_hz': 123}, {'angle_snapping': 'false'},
                   {'hits': [{'actuation': 60}] * 2}, {'hits': [{'rt_enabled': 1}] * 2}]
        for data in invalid:
            with self.subTest(data=data):
                profile = Profile.parse(1, FIXTURE)
                before = copy.deepcopy(profile)
                if isinstance(data, dict):
                    data = {'name': 'must not stick', **data}
                with self.assertRaises(ValueError):
                    profile.apply_json(data)
                self.assertEqual(profile, before)

    def test_valid_import_retains_destination_raw_bytes(self):
        profile = Profile.parse(1, FIXTURE)
        profile.apply_json({'name': 'Gaming', 'raw': 'untrusted raw ignored'})
        self.assertEqual(profile.name, 'Gaming')
        self.assertEqual(profile.raw, FIXTURE)
        self.assertEqual(len(profile.serialize()), len(FIXTURE))


class ConfigSafetyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in [('CONFIG_DIR', Path(tmp.name)), ('CONFIG_FILE', Path(tmp.name)/'config.json')]:
            patcher = patch.object(storage, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_mouse_update_preserves_keyboard_and_theme(self):
        save_state('40b4', {'mode': 'static'})
        storage.update_config({'theme': 'system'})
        storage.update_config({'live': {'surface': 1}})
        result = storage.load_config()
        self.assertEqual(result['keyboards']['40b4']['mode'], 'static')
        self.assertEqual(result['theme'], 'system')
        self.assertEqual(result['live']['surface'], 1)

    def test_concurrent_updates_keep_each_device(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: save_state(str(n), {'mode': 'static'}), range(20)))
        self.assertEqual(len(storage.load_config()['keyboards']), 20)

    def test_cleared_key_colors_are_not_merged_back_in(self):
        save_state('40b4', {'keys': {'4': [1, 2, 3]}})
        save_state('40b4', {'keys': {}})
        self.assertEqual(storage.load_config()['keyboards']['40b4']['keys'], {})


class DiscoverySafetyTests(unittest.TestCase):
    def test_one_timeout_does_not_hide_the_next_device(self):
        nodes = [SimpleNamespace(path='/dev/hidraw1', product=0x40b4, name='Keyboard'),
                 SimpleNamespace(path='/dev/hidraw2', product=0x40b4, name='Keyboard')]
        good = devices.FoundDevice(nodes[1].path, 0x40b4, 'Keyboard', awake=True)
        previous = devices.FoundDevice(nodes[0].path, 0x40b4, 'Keyboard', awake=True)
        with patch.object(devices, 'list_logitech_nodes', return_value=nodes), \
             patch.object(devices, 'probe', side_effect=[HidppTimeout('timeout'), good]):
            found, denied = devices.scan({previous.key: previous})
        self.assertIn(good, found)
        self.assertFalse(next(d for d in found if d.key == previous.key).awake)
        self.assertTrue(previous.awake)
        self.assertFalse(denied)

    def test_only_verified_rgb_keyboard_gets_lighting_controls(self):
        for pid, features, expected in [(0x1234, {0x8071, 0x8081, 0x8040}, 'generic'),
                                        (0x40b4, set(), 'generic'),
                                        (0x40b4, {0x8071, 0x8081, 0x8040}, 'keyboard')]:
            d = devices.FoundDevice('/dev/hidraw1', pid, 'Keyboard', kind='keyboard', features=features)
            devices._classify(d)
            self.assertEqual(d.model, expected)

    def test_reused_path_with_different_product_is_never_opened(self):
        node = SimpleNamespace(path='/dev/hidraw1', product=0xc33f, name='Keyboard')
        with patch('ghub_linuxported.hidpp.mouse.list_logitech_nodes', return_value=[node]), \
             patch('ghub_linuxported.hidpp.mouse.HidrawTransport') as transport:
            with self.assertRaises(FileNotFoundError):
                Mouse.open(node=node.path, expected_pid=0x40b4)
            transport.assert_not_called()

    def test_reused_path_same_product_different_unit_is_closed(self):
        node = SimpleNamespace(path='/dev/hidraw1', product=0x40b4, name='Keyboard')
        with patch('ghub_linuxported.hidpp.mouse.list_logitech_nodes', return_value=[node]), \
             patch('ghub_linuxported.hidpp.mouse.HidrawTransport') as transport, \
             patch.object(Mouse, '_ping', return_value='2.0'), \
             patch.object(Mouse, 'feature_index', return_value=None), \
             patch.object(Mouse, 'identity', return_value=Identity(unit_id='new')):
            with self.assertRaises(FileNotFoundError):
                Mouse.open(node=node.path, dev_index=1, expected_pid=0x40b4, expected_unit='old')
            transport.return_value.close.assert_called_once()


class KeyboardSafetyTests(unittest.TestCase):
    def make_service(self):
        with patch('ghub_linuxported.keyboard_service.load_state', return_value=copy.deepcopy(DEFAULT_STATE)):
            return KeyboardService(None, devices.FoundDevice('/dev/hidraw1', 0x40b4, 'G515'))

    def test_reconnect_restores_saved_brightness(self):
        svc = self.make_service()
        svc.state.update(mode='static', brightness=25)
        svc.dev = Mock()
        svc.dev.identity.return_value = Identity(unit_id='known')
        light = Mock(claimed=False)
        light.info.brightness = 100
        with patch('ghub_linuxported.keyboard_service.Lighting', return_value=light):
            svc.refresh()
        light.set_brightness.assert_called_once_with(25)
        light.static.assert_called_once()

    def test_failed_effect_is_not_persisted(self):
        svc = self.make_service()
        svc.lighting = Mock(claimed=False)
        svc.lighting.claim.side_effect = FeatureMissing('RGB')
        before = copy.deepcopy(svc.state)
        with patch('ghub_linuxported.keyboard_service.save_state') as save:
            with self.assertRaises(FeatureMissing):
                svc.apply({**svc.state, 'mode': 'static'})
            save.assert_not_called()
        self.assertEqual(svc.state, before)

    def test_reconnect_requires_previous_unit_identity(self):
        svc = self.make_service()
        svc.identity = Identity(unit_id='known')
        with patch.object(Mouse, 'open') as opened:
            svc.open_device()
        self.assertEqual(opened.call_args.kwargs['expected_pid'], 0x40b4)
        self.assertEqual(opened.call_args.kwargs['expected_unit'], 'known')
