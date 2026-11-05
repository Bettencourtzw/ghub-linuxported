"""Render every page with a simulated mouse (no hardware) and save PNG screenshots.

    python3 tools/ui_preview.py OUTDIR [--dark]
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

SIZE = (1400, 900)
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
    tex = win.get_renderer().render_texture(node, None)
    tex.save_to_png(str(path))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    dark = "--dark" in sys.argv
    app = App()
    import ghub_linuxported.ui.app as appmod
    appmod.DeviceService = FakeService
    keys = []

    def shoot(i=0):
        win = app.win
        if i == 0:
            keys.extend(p.key for p in win.pages)
        if i >= len(keys):
            app.quit()
            return False
        win.goto(keys[i])
        GLib.timeout_add(700, lambda: (render(win, out / f"{i:02d}_{keys[i]}.png"), shoot(i + 1)) and False)
        return False

    def setup():
        if dark:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        app.win.set_default_size(*SIZE)
        # Under Hyprland the window is tiled; float + size just this window for screenshots.
        import os, shutil, subprocess
        if shutil.which("hyprctl") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            def hypr():
                pid = os.getpid()
                subprocess.run(["hyprctl", "dispatch", "setfloating", f"pid:{pid}"], capture_output=True)
                subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact {SIZE[0]} {SIZE[1]},pid:{pid}"],
                               capture_output=True)
                return False
            GLib.timeout_add(600, hypr)
        GLib.timeout_add(2000, shoot)
        return False
    app.connect("activate", lambda *_: GLib.idle_add(setup))
    app.run([])


if __name__ == "__main__":
    main()
