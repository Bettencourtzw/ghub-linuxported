"""ghub-linuxported-cli: diagnostics and quick live settings from a terminal."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .hidpp.mouse import Mouse, FEATURE_NAMES, SURFACE_MODES, HitsButton
from .hidpp.transport import SWID_CLI, list_logitech_nodes
from .model.profile import Profile, crc_ok, parse_directory, LOD_NAMES
from .model import hits_codes
from .diagnostics import measure_report_rate


def _open() -> Mouse:
    try:
        return Mouse.open(SWID_CLI)
    except PermissionError as exc:
        sys.exit(f"error: {exc}\nInstall the udev rule: sudo ./install.sh --udev")
    except FileNotFoundError as exc:
        sys.exit(f"error: {exc}")


def cmd_scan(_):
    for n in list_logitech_nodes():
        print(f"{n.path:14} {n.vendor:04x}:{n.product:04x} {n.kind:9} {n.name}")


def cmd_status(_):
    m = _open()
    ident = m.identity()
    b = m.battery()
    print(f"{ident.name}  [{ident.connection}, HID++ {ident.protocol}, {m.node.path}]")
    print(f"unit {ident.unit_id}  model {ident.model_id} {ident.model_string}")
    for fw in ident.firmware:
        print("  " + fw)
    print(f"battery {b.percent}% ({b.label})")
    info = m.onboard_info()
    print(f"mode {'onboard' if m.mode_get() == 1 else 'host'}, active profile sector 0x{m.current_profile():04x}, "
          f"{info.profile_count} profiles, sector size {info.sector_size}, format {info.profile_format}")
    x, y, lod = m.dpi_get()
    print(f"DPI (getter, may be stale) {x}x{y}, stage {m.dpi_stage_get()}")
    print(f"report rate (getter, may be stale) {m.rate_get()} Hz, supported {m.rate_supported()}")
    for i, side in enumerate(("left", "right")):
        h = m.hits_get(i)
        print(f"HITS {side}: actuation {h.actuation}, rapid trigger "
              f"{'L' + str(h.rt_level) if h.rt_enabled else 'off (level ' + str(h.rt_level) + ')'}, haptics {h.haptics}")
    print(f"surface mode {SURFACE_MODES[m.surface_get()]}, bhop window {m.bhop_get() or 'off'} ms")
    print("HITS code:", hits_codes.encode(m.hits_get(0), m.hits_get(1)))


def cmd_features(_):
    m = _open()
    for idx, fid, flags, ver in m.list_features():
        print(f"0x{idx:02x}  0x{fid:04x}  v{ver}  flags 0x{flags:02x}  {FEATURE_NAMES.get(fid, '')}")


def cmd_dump(args):
    """Read-only: dump directory + every profile sector (and the ROM factory profile)."""
    m = _open()
    info = m.onboard_info()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for sec in [0x0000] + list(range(1, info.profile_count + 1)) + [0x0100, 0x0101]:
        try:
            raw = m.read_sector(sec)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"sector 0x{sec:04x}: unreadable ({exc})")
            continue
        (out / f"sector_{sec:04x}.bin").write_bytes(raw)
        print(f"sector 0x{sec:04x}: crc {'ok' if crc_ok(raw) else 'BAD/none'}  -> {out}/sector_{sec:04x}.bin")
        if sec == 0:
            print("   directory:", [(hex(e.sector), e.enabled) for e in parse_directory(raw)])
        elif sec != 0x0100:
            try:
                p = Profile.parse(sec, raw)
                print(f"   name={p.display_name!r} rate={p.rate_wireless_hz}/{p.rate_wired_hz}Hz "
                      f"default stage={p.default_stage} bhop={p.bhop_ms}ms")
                print("   stages:", ", ".join(f"{s.x}x{s.y}/{LOD_NAMES.get(s.lod, 'off')}" for s in p.stages))
                print("   hits:", [(h.actuation, h.rapid_trigger, h.haptics) for h in p.hits],
                      " buttons:", [a.describe(i) for i, a in enumerate(p.buttons)])
            except ValueError as exc:
                print("   (not a profile)", exc)


def cmd_hits(args):
    m = _open()
    if args.code:
        left, right = hits_codes.decode(args.code)
        m.hits_set(0, left)
        m.hits_set(1, right)
        print("applied (live). Use the app's 'Save to mouse' to make it persistent.")
        return
    for i in ([0] if args.left else [1] if args.right else [0, 1]):
        h = m.hits_get(i)
        if args.actuation:
            h.actuation = args.actuation
        if args.haptics is not None:
            h.haptics = args.haptics
        if args.rapid_trigger is not None:
            h.rt_enabled = args.rapid_trigger > 0
            if args.rapid_trigger:
                h.rt_level = args.rapid_trigger
        m.hits_set(i, h)
        print(("left", "right")[i], m.hits_get(i))


def cmd_rate(args):
    m = _open()
    print(f"Move the mouse continuously for {args.seconds} s ...")
    r = measure_report_rate(m.node.path, args.seconds)
    if not r.hz:
        print("not enough motion reports — keep the mouse moving")
    else:
        print(f"measured {r.hz:.0f} Hz (~{r.nominal} Hz) from {r.reports} reports, jitter {r.jitter_us:.0f} µs")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ghub-linuxported-cli", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="list Logitech hidraw nodes").set_defaults(fn=cmd_scan)
    sub.add_parser("status", help="show device state").set_defaults(fn=cmd_status)
    sub.add_parser("features", help="list HID++ features").set_defaults(fn=cmd_features)
    d = sub.add_parser("dump", help="read-only dump of all profile sectors")
    d.add_argument("out", nargs="?", default="superstrike-dump")
    d.set_defaults(fn=cmd_dump)
    h = sub.add_parser("hits", help="set HITS live (volatile)")
    h.add_argument("--code", help="apply a G HUB HITS code")
    h.add_argument("--actuation", type=int, choices=range(1, 11))
    h.add_argument("--rapid-trigger", type=int, choices=range(0, 6), help="0 = off")
    h.add_argument("--haptics", type=int, choices=range(0, 6))
    g = h.add_mutually_exclusive_group()
    g.add_argument("--left", action="store_true")
    g.add_argument("--right", action="store_true")
    h.set_defaults(fn=cmd_hits)
    r = sub.add_parser("rate", help="measure the real polling rate")
    r.add_argument("--seconds", type=float, default=2.0)
    r.set_defaults(fn=cmd_rate)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
