"""Exercise real UI handler bodies without a GTK display; not a rendering test."""
import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
        app.keyboard_view_closed.side_effect = lambda _: events.append('close')
        view = SimpleNamespace(push_brightness=Mock(), push=Mock(), _subs=[], _anim=None,
                               shell=Mock(), found=object())
        view.shell.get_application.return_value = app
        view.push_brightness.flush.side_effect = lambda: events.append('brightness')
        view.push.flush.side_effect = lambda: events.append('effect')
        handler('keyboard_view.py', 'KeyboardView', 'close')(view)
        self.assertEqual(events, ['brightness', 'effect', 'close'])

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
