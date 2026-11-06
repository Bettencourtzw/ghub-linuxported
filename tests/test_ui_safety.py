"""Exercise real UI handler bodies without a GTK display; not a rendering test."""
import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / 'ghub_linuxported/ui'


def handler(file, cls, method, **globals):
    tree = ast.parse((ROOT / file).read_text())
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    fn = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == method)
    namespace = dict(globals)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT/file), 'exec'), namespace)
    return namespace[method]


class KeyboardHandlerTests(unittest.TestCase):
    def test_brightness_edit_updates_state_used_by_later_effect_changes(self):
        view = SimpleNamespace(_loading=False, bright=Mock(), state={'brightness': 100},
                               push_brightness=Mock())
        view.bright.get_value.return_value = 25
        handler('keyboard_view.py', 'KeyboardView', '_on_brightness')(view)
        self.assertEqual(view.state['brightness'], 25)

    def test_static_preview_draws_once_without_starting_timer(self):
        glib = Mock()
        view = SimpleNamespace(state={'mode': 'static'}, _anim=None, _animate=Mock())
        handler('keyboard_view.py', 'KeyboardView', '_update_preview', GLib=glib)(view)
        glib.timeout_add.assert_not_called()
        view._animate.assert_called_once_with(force=True)

    def test_switching_from_animation_to_static_cancels_timer(self):
        glib = Mock()
        view = SimpleNamespace(state={'mode': 'static'}, _anim=42, _animate=Mock())
        handler('keyboard_view.py', 'KeyboardView', '_update_preview', GLib=glib)(view)
        glib.source_remove.assert_called_once_with(42)
        self.assertIsNone(view._anim)

    def test_animated_preview_starts_only_one_timer(self):
        glib = Mock()
        glib.timeout_add.return_value = 42
        view = SimpleNamespace(state={'mode': 'wave'}, _anim=None, _animate=Mock())
        update = handler('keyboard_view.py', 'KeyboardView', '_update_preview', GLib=glib)
        update(view)
        update(view)
        glib.timeout_add.assert_called_once_with(33, view._animate)

    def test_close_flushes_pending_edits_before_stopping_service(self):
        events = []
        app = Mock()
        app.keyboard_view_closed.side_effect = lambda *args: events.append('close')
        view = SimpleNamespace(push_brightness=Mock(), push=Mock(), _subs=[], _anim=None,
                               shell=Mock(), found=object(), state={"mode": "static"})
        view.shell.get_application.return_value = app
        view.push_brightness.flush.side_effect = lambda: events.append('brightness')
        view.push.flush.side_effect = lambda: events.append('effect')
        handler('keyboard_view.py', 'KeyboardView', 'close')(view)
        self.assertEqual(events, ['brightness', 'effect', 'close'])
        app.keyboard_view_closed.assert_called_once_with(view.found, 'static')

    def test_debounced_edit_flush_runs_once_and_removes_timeout(self):
        glib, apply = Mock(), Mock()
        debounce = SimpleNamespace(_id=42, _pending=apply)
        flush = handler('widgets.py', 'Debouncer', 'flush', GLib=glib)
        flush(debounce)
        flush(debounce)
        apply.assert_called_once()
        glib.source_remove.assert_called_once_with(42)

    def test_close_restore_uses_new_profile_after_a_queued_save(self):
        from ghub_linuxported.model.profile import Profile
        raw = (ROOT.parents[1] / 'tests/fixtures/xatuke_profile1.bin').read_bytes()
        old = Profile.parse(1, raw)
        saved = copy.deepcopy(old)
        saved.hits[0].actuation = 5
        view = SimpleNamespace(run=Mock())
        restore = handler('mouse_view.py', 'MouseView', 'live_restore_from', Profile=Profile, copy=copy)
        restore(view, old, latest=True)
        service = Mock()
        service.snapshot.profiles = {1: saved}
        service.snapshot.bhop_ms = 0
        view.run.call_args.args[0](service)
        self.assertEqual(service.apply_hits.call_args_list[0].args[1].actuation, 5)


class ApplicationKeyboardTests(unittest.TestCase):
    def test_immediate_close_keeps_queued_custom_effect_alive(self):
        svc = Mock(state={'mode': 'onboard'})
        found = SimpleNamespace(key='keyboard')
        app = SimpleNamespace(keyboards={'keyboard': svc})
        handler('app.py', 'App', 'keyboard_view_closed')(app, found, 'static')
        svc.stop.assert_not_called()
        self.assertIs(app.keyboards['keyboard'], svc)

    def test_changed_path_reuses_worker_for_the_same_physical_keyboard(self):
        svc = Mock()
        svc.found = SimpleNamespace(pid=0x40b4)
        svc.identity = SimpleNamespace(unit_id='known')
        found = SimpleNamespace(key='new-path', pid=0x40b4, unit_id='known')
        app = SimpleNamespace(keyboards={'old-path': svc})
        result = handler('app.py', 'App', 'keyboard_service')(app, found)
        self.assertIs(result, svc)
        self.assertEqual(app.keyboards, {'new-path': svc})
        self.assertIs(svc.found, found)


class PreviewFixtureTests(unittest.TestCase):
    def test_preview_devices_retain_correct_routing_and_battery_fields(self):
        from ghub_linuxported.hidpp.mouse import Battery
        path = ROOT.parents[1] / 'tools/ui_preview.py'
        tree = ast.parse(path.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fake_devices')
        namespace = {'Battery': Battery}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
        mouse, keyboard = namespace['fake_devices']()
        self.assertEqual((mouse.kind, mouse.model, mouse.battery.percent), ('mouse', 'superstrike', 72))
        self.assertEqual((keyboard.kind, keyboard.model, keyboard.battery.percent), ('keyboard', 'keyboard', 64))
        self.assertTrue(mouse.awake)
        self.assertTrue(keyboard.awake)


class ReboundBatteryTests(unittest.TestCase):
    def test_battery_event_uses_current_device_after_path_change(self):
        from ghub_linuxported.devices import FoundDevice
        from ghub_linuxported.hidpp.mouse import Battery, Identity
        from ghub_linuxported.keyboard_service import DEFAULT_STATE
        found = FoundDevice('/dev/old', 0x40b4, 'G515', unit_id='known')
        app = SimpleNamespace(keyboards={}, _keyboard_battery=Mock())
        get_service = handler('app.py', 'App', 'keyboard_service',
                              GLib=SimpleNamespace(idle_add=lambda fn: fn()),
                              __name__='ghub_linuxported.ui.app', __package__='ghub_linuxported.ui')
        with patch('ghub_linuxported.keyboard_service.load_state', return_value=copy.deepcopy(DEFAULT_STATE)), \
             patch('ghub_linuxported.keyboard_service.KeyboardService.start'):
            svc = get_service(app, found)
        svc.identity = Identity(unit_id='known')
        replacement = FoundDevice('/dev/new', 0x40b4, 'G515', unit_id='known')
        self.assertIs(get_service(app, replacement), svc)
        battery = Battery(50, 0, False)
        svc._emit('battery', battery)
        app._keyboard_battery.assert_called_once_with(replacement, battery)
