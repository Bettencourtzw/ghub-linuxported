"""App styling: base CSS for custom widgets + the "G HUB" look (deep black, G cyan).

Themes: "ghub" (default) and "system" (follow the desktop's libadwaita style).
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from . import draw

GHUB_ACCENT = (0.0, 0.70, 0.95)  # Logitech G-like cyan

BASE_CSS = """
.hero {
  padding: 8px;
  background-image: linear-gradient(135deg, alpha(@accent_bg_color, 0.18), alpha(@accent_bg_color, 0.02) 60%);
}
.chip {
  padding: 4px 12px;
  border-radius: 999px;
  background: alpha(currentColor, 0.08);
  font-weight: 600;
  font-size: 0.9em;
}
.chip.accent { background: alpha(@accent_bg_color, 0.18); color: @accent_color; }
.tile { padding: 16px 18px; min-height: 84px; }
.hits-card { padding: 20px 22px; }
.click-pad { min-height: 260px; }
.console { font-size: 0.9em; }
.display { font-size: 42px; font-weight: 800; }
label.accent { color: @accent_color; }
.eyebrow { font-size: 0.78em; font-weight: 800; letter-spacing: 0.18em; opacity: 0.6; }
.home-title { font-size: 30px; font-weight: 800; letter-spacing: 0.02em; }
.brand { font-weight: 900; letter-spacing: 0.22em; font-size: 0.95em; }
.device-tile {
  padding: 18px 18px 18px 18px;
  border-radius: 22px;
  background-color: alpha(currentColor, 0.035);
  background-image: radial-gradient(circle at 50% 34%, alpha(@accent_bg_color, 0.13), transparent 62%);
  border: 1px solid alpha(currentColor, 0.07);
  transition: all 180ms ease;
}
.device-tile:hover {
  background-color: alpha(@accent_bg_color, 0.07);
  border-color: alpha(@accent_bg_color, 0.55);
  box-shadow: 0 0 0 1px alpha(@accent_bg_color, 0.25), 0 10px 36px alpha(@accent_bg_color, 0.18);
}
.device-tile .tile-name { font-weight: 800; letter-spacing: 0.06em; font-size: 1.05em; }
.device-tile.asleep { opacity: 0.55; }
.battery-pill { padding: 2px 10px; border-radius: 999px; background: alpha(currentColor, 0.07);
                font-size: 0.85em; font-weight: 700; }
.swatch { min-width: 30px; min-height: 30px; border-radius: 999px; padding: 0; border: 2px solid alpha(currentColor, 0.15); }
.swatch.selected { border-color: @accent_color; box-shadow: 0 0 0 2px alpha(@accent_bg_color, 0.35); }
.effect-card { padding: 14px; border-radius: 16px; min-width: 104px; background-color: alpha(currentColor, 0.04); }
.effect-card:hover { background-color: alpha(@accent_bg_color, 0.08); }
.effect-card:checked { background-color: alpha(@accent_bg_color, 0.16); box-shadow: inset 0 0 0 2px @accent_bg_color; }
"""

GHUB_CSS = """
:root {
  --accent-bg-color: rgb(0 168 232);
  --accent-color: rgb(80 210 255);
  --accent-fg-color: rgb(0 16 24);
  --window-bg-color: rgb(13 14 18);
  --window-fg-color: rgb(233 237 242);
  --view-bg-color: rgb(16 18 23);
  --view-fg-color: rgb(233 237 242);
  --headerbar-bg-color: rgb(13 14 18);
  --headerbar-backdrop-color: rgb(13 14 18);
  --headerbar-shade-color: rgb(0 0 0 / 0%);
  --sidebar-bg-color: rgb(9 10 13);
  --sidebar-backdrop-color: rgb(9 10 13);
  --sidebar-border-color: rgb(255 255 255 / 5%);
  --card-bg-color: rgb(255 255 255 / 4%);
  --card-shade-color: rgb(0 0 0 / 50%);
  --popover-bg-color: rgb(24 26 32);
  --dialog-bg-color: rgb(20 22 27);
  --thumbnail-bg-color: rgb(24 26 32);
}
.navigation-sidebar > row:selected {
  background-color: alpha(@accent_bg_color, 0.16);
  box-shadow: inset 3px 0 0 @accent_bg_color;
}
.navigation-sidebar > row:selected image { color: @accent_color; }
toggle-group toggle:checked, .toggle-group button:checked { color: @accent_color; }
scale highlight { background-color: @accent_bg_color; }
"""

_providers: dict[str, Gtk.CssProvider] = {}


def _provider(name, css):
    p = _providers.get(name)
    if p is None:
        p = Gtk.CssProvider()
        p.load_from_string(css)
        _providers[name] = p
    return p


def apply(theme: str):
    display = Gdk.Display.get_default()
    Gtk.StyleContext.add_provider_for_display(display, _provider("base", BASE_CSS),
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    sm = Adw.StyleManager.get_default()
    ghub = _provider("ghub", GHUB_CSS)
    if theme == "ghub":
        sm.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        Gtk.StyleContext.add_provider_for_display(display, ghub, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        draw.ACCENT_OVERRIDE = draw.rgba(*GHUB_ACCENT)
    else:
        Gtk.StyleContext.remove_provider_for_display(display, ghub)
        sm.set_color_scheme({"light": Adw.ColorScheme.FORCE_LIGHT,
                             "dark": Adw.ColorScheme.FORCE_DARK}.get(theme, Adw.ColorScheme.DEFAULT))
        draw.ACCENT_OVERRIDE = None
