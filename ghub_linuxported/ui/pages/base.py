from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


class Page:
    key = ""
    title = ""
    icon = ""
    subtitle = ""

    def __init__(self, win):
        self.win = win
        self.loading = False
        self.widget = self.build()

    def build(self) -> Gtk.Widget:
        raise NotImplementedError

    def load(self, snap, edit):
        self.loading = True
        try:
            self.fill(snap, edit)
        finally:
            self.loading = False

    def fill(self, snap, edit):
        pass

    # helpers
    @staticmethod
    def prefs_page(*groups, description=None) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        if description:
            page.set_description(description)
        for g in groups:
            page.add(g)
        return page

    @staticmethod
    def group(title, description=None, suffix=None) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title=title)
        if description:
            g.set_description(description)
        if suffix:
            g.set_header_suffix(suffix)
        return g
