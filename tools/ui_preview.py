"""Render every page with a simulated mouse (no hardware) and save PNG screenshots.

    python3 tools/ui_preview.py OUTDIR
    python3 tools/ui_preview.py --interactive  # leave the device picker open
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ghub_linuxported.service import DeviceService, Snapshot  # noqa: E402
from ghub_linuxported.hidpp.mouse import Identity, Battery, OnboardInfo, HitsButton  # noqa: E402
from ghub_linuxported.model.profile import Profile, parse_directory, DirectoryEntry  # noqa: E402
from ghub_linuxported.ui.app import App  # noqa: E402

SIZE = (1440, 920)
FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "xatuke_profile1.bin"


def fake_snapshot():
    raw = FIX.read_bytes()
    s = Snapshot()
    s.identity = Identity(name="PRO X2 SUPERSTRIKE", unit_id="00-00-00-00", model_id="40BDC0A80000",
                          model_string="0000XXXXXXXX", firmware=["Bootloader: BL2 73.00.B0011", "Main: MPM 42.00.B0011"],
                          protocol="4.2", connection="LIGHTSPEED wireless", node="/dev/hidraw8")
    s.battery = Battery(72, 0, False)
    s.onboard = OnboardInfo(1, 8, 1, 5, 1, 5, 16, 255)
    s.active_sector = 1
    s.directory = [DirectoryEntry(1, True), DirectoryEntry(2, True)] + [DirectoryEntry(n, False) for n in (3, 4, 5)]
    for n in range(1, 6):
        s.profiles[n] = Profile.parse(n, raw)
    s.live_hits = [HitsButton(2, 2, False, 3), HitsButton(2, 2, False, 3)]
    s.hits_caps = {"buttons": 3, "actuation_max": 10, "rt_max": 5, "haptics_max": 5}
    s.bhop_ms = 0
    s.surface = 0
    s.rate_supported = [125, 250, 500, 1000, 2000, 4000, 8000]
    s.dpi_ranges = [(100, 100, 1), (101, 200, 1), (202, 500, 2), (505, 1000, 5), (1010, 2000, 10),
                    (2020, 5000, 20), (5050, 10000, 50), (10100, 20000, 100), (20125, 32000, 125), (32200, 44000, 200)]
    s.dpi_stage = 2
    s.features = [(0, 0x0000, 0, 0), (1, 0x0001, 0, 2), (2, 0x0003, 0, 7), (0x0c, 0x1B0C, 0, 0), (0x0e, 0x8100, 0, 0)]
    return s


class FakeService(DeviceService):
    def start(self):
        self.status = "connected"
        self.snapshot = fake_snapshot()
        GLib.idle_add(lambda: (self._emit("status", "connected", ""), self._emit("snapshot", self.snapshot)) and False)

    def submit(self, fn, on_done=None, on_error=None):
        if on_error:
            GLib.idle_add(lambda: on_error(ConnectionError("preview mode")) and False)


def render(win, path):
    paintable = Gtk.WidgetPaintable.new(win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        win.queue_draw()
        return False
    tex = win.get_renderer().render_texture(node, None)
    if not tex.save_to_png(str(path)):
        raise OSError(f"Could not save {path}")
    return True


def fake_devices():
    from ghub_linuxported.devices import FoundDevice
    m = FoundDevice("/dev/hidraw-fake-m", 0x40BD, "Logitech X2 SUPERSTRIKE", 1, "PRO X2 SUPERSTRIKE", "mouse",
                    "superstrike", True, Battery(72, 0, False), "LIGHTSPEED wireless")
    k = FoundDevice("/dev/hidraw-fake-k", 0x40B4, "Logitech G515 LS TKL", 1, "G515 LS TKL", "keyboard",
                    "keyboard", True, Battery(64, 1, True), "LIGHTSPEED wireless")
    return [m, k]


def fake_keyboard_service(found, state):
    from ghub_linuxported.keyboard_service import KeyboardService
    from ghub_linuxported.hidpp.lighting import Lighting, LightingInfo, EffectSlot

    class FakeKb(KeyboardService):
        def start(self):
            self.status = "connected"
            self.identity = Identity(name="G515 LS TKL", unit_id="00-00-00-00", model_id="B38940B4C355",
                                     firmware=["Main: MPK 25.01.B0011"], protocol="4.2",
                                     connection="LIGHTSPEED wireless")
            self.battery = Battery(64, 1, True)
            self.lighting = Lighting(None)
            self.lighting.info = LightingInfo(1, [EffectSlot(0, i, e, 0, 0) for i, e in
                                                  enumerate((0, 1, 0x0A, 0x15, 0x16, 0x17))],
                                              list(range(1, 96)), 100, 5, 60)

        def submit(self, fn, on_done=None, on_error=None):
            if on_done:
                GLib.idle_add(lambda: on_done(None) and False)

        def stop(self, wait=0.0):
            pass
    svc = FakeKb(lambda fn, *a: GLib.idle_add(lambda: fn(*a) and False), found)
    svc.state.update(state)
    svc.start()
    return svc


def hypr_float(pid, w, h):
    """Float + size the preview window (Hyprland >= 0.55 Lua dispatchers, then legacy syntax)."""
    import os, shutil, subprocess
    if not (shutil.which("hyprctl") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")):
        return
    for expr in (f"hl.dsp.window.float({{ action = 'enable', window = 'pid:{pid}' }})",
                 f"hl.dsp.window.resize({{ x = {w}, y = {h}, window = 'pid:{pid}' }})"):
        subprocess.run(["hyprctl", "dispatch", expr], capture_output=True)
    subprocess.run(["hyprctl", "dispatch", "setfloating", f"pid:{pid}"], capture_output=True)
    subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact {w} {h},pid:{pid}"], capture_output=True)


class PreviewApp(App):
    """The hardware-free preview has no tray to keep alive after closing."""

    def do_startup(self):
        super().do_startup()
        self.set_accels_for_action("app.quit", ["<Primary>q", "<Control>q"])

    def _on_close(self, _win):
        self.really_quit()
        return True


def main():
    import argparse
    import tempfile
    import types
    from ghub_linuxported import storage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", nargs="?", default="docs/screenshots")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--page", choices=("all", "home", "keyboard"), default="all")
    parser.add_argument("--width", type=int, default=SIZE[0])
    parser.add_argument("--height", type=int, default=SIZE[1])
    args = parser.parse_args()
    out = Path(args.out)
    if not args.interactive:
        out.mkdir(parents=True, exist_ok=True)
    preview_data = tempfile.TemporaryDirectory(prefix="glp-preview-")
    storage.CONFIG_DIR = Path(preview_data.name) / "config"
    storage.CONFIG_FILE = storage.CONFIG_DIR / "config.json"
    storage.DATA_DIR = Path(preview_data.name) / "data"
    storage.BACKUP_DIR = storage.DATA_DIR / "backups"
    import ghub_linuxported.ui.home as home
    import ghub_linuxported.ui.mouse_view as mv
    from ghub_linuxported.model.keyboard_layout import TKL_ANSI, WASD, ARROWS
    devs = fake_devices()
    home.scan = lambda previous=None: (devs, False)
    mv.DeviceService = FakeService

    class NoTray:
        def __init__(self, *a, **k): pass
        def start(self): pass
        def stop(self): pass
        def set_devices(self, d): pass
        def keyboard_battery(self, d): pass
    traymod = types.ModuleType("ghub_linuxported.tray.main")
    traymod.Tray = NoTray
    traymod.tray_host_available = lambda: False
    sys.modules[traymod.__name__] = traymod
    App._restore_keyboards = lambda self: None
    gamer = {str(k.usage): [0, 168, 232] for k in TKL_ANSI}
    gamer.update({str(u): [255, 0, 129] for u in WASD | ARROWS})
    kb_state = {"mode": "static", "keys": gamer}
    App.keyboard_service = lambda self, found: fake_keyboard_service(found, kb_state)
    App.keyboard_view_closed = lambda self, found, mode: None
    app = PreviewApp()
    app.set_application_id("io.github.ghub_linuxported.Preview")
    app.connect("startup", lambda _: Gtk.Settings.get_default().set_property("gtk-icon-theme-name", "Adwaita"))
    W, H = args.width, args.height

    capture_errors = []

    def steps():
        win = app.win
        home_dev = {d.kind: d for d in devs}
        seq = [("home", None), ("keyboard", lambda: (win.open_device(home_dev["keyboard"]),
                                      win.nav.get_visible_page().view.goto("lighting"))),
               ("keyboard-keys", lambda: win.nav.get_visible_page().view.mode_buttons["perkey"].set_active(True)),
               ("mouse", lambda: (win.nav.pop(), win.open_device(home_dev["mouse"]))),
               ("hits", lambda: win.nav.get_visible_page().view.goto("hits")),
               ("buttons", lambda: win.nav.get_visible_page().view.goto("buttons"))]

        if args.page == "home":
            seq = seq[:1]
        elif args.page == "keyboard":
            seq = seq[1:3]

        def run(i=0):
            if i >= len(seq):
                app.really_quit()
                return False
            name, action = seq[i]
            if action:
                action()
            attempts = 0

            def capture():
                nonlocal attempts
                attempts += 1
                try:
                    if render(win, out / f"{name}.png"):
                        run(i + 1)
                        return False
                    if attempts < 5:
                        return True
                    raise RuntimeError(f"No rendered frame for {name}")
                except Exception as exc:
                    capture_errors.append(exc)
                    app.really_quit()
                    return False
            GLib.timeout_add(1600, capture)
            return False
        run()
        return False

    def setup():
        win = app.win
        win.set_default_size(W, H)
        hypr_float(__import__("os").getpid(), W, H)
        if not args.interactive:
            GLib.timeout_add(2200, steps)
        return False
    GLib.timeout_add(1200, setup)
    try:
        app.run([sys.argv[0]])
    finally:
        preview_data.cleanup()
    if capture_errors:
        raise RuntimeError("Screenshot capture failed") from capture_errors[0]


if __name__ == "__main__":
    main()
