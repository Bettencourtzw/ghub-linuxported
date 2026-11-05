"""All sidebar pages. Each page exposes key/title/icon/subtitle, .widget and .load(snapshot, edit)."""


def build_pages(win):
    from .overview import OverviewPage
    from .hits import HitsPage
    from .sensor import SensorPage
    from .buttons import ButtonsPage
    from .bhop import BhopPage
    from .power import PowerPage
    from .profiles import ProfilesPage
    from .diagnostics import DiagnosticsPage
    return [cls(win) for cls in (OverviewPage, HitsPage, SensorPage, ButtonsPage, BhopPage,
                                 PowerPage, ProfilesPage, DiagnosticsPage)]
