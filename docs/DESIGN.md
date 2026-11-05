# Design: G HUB Linux Ported (PRO X2 SUPERSTRIKE control app)

Date: 2026-11-05. Status: approved by the user in chat ("get the app ready").

## Goal

A local-only Linux replacement for G HUB covering everything the PRO X2
SUPERSTRIKE offers: HITS (actuation, rapid trigger, haptics), DPI stages/LOD,
report rate, buttons, bhop scroll filter, surface mode, power timers, onboard
profiles, plus a tray helper (battery, alerts) and diagnostics.

## Decisions

- **Stack:** Python + GTK4/libadwaita (already installed; native on Hyprland). Custom
  drawing uses GTK4's Gsk path API (no pycairo dependency).
- **Protocol:** pure-Python HID++ 2.0 over hidraw, feature indexes resolved at runtime.
- **Persistence:** onboard memory by default. Live setters give instant feedback; a single
  "Save to mouse" writes the profile. Host mode is optional; the tray re-applies live-only
  settings (surface mode, and everything in host mode) on reconnect.
- **Flash safety:** fresh read → backup to disk → CRC → write once → byte-exact read-back →
  reload. No write loops. ROM factory profile is cloned, never written.
- **Out of scope:** per-app automatic profile switching (not selected), macros editing
  (existing macros are preserved verbatim), pairing.

## Architecture

```
hidpp/transport.py   frames, swid matching, retries, hidraw discovery
hidpp/mouse.py       one method per device feature
model/profile.py     sector parse/serialize (patches known fields only), directory, CRC
model/buttons.py     button actions + key-capture tables
model/hits_codes.py  G HUB HITS code codec + published pro presets
service.py           worker thread, snapshot, live apply, verified save path
ui/                  window, pages (overview, hits, sensor, buttons, bhop, power, profiles, diagnostics)
tray/                StatusNotifierItem + dbusmenu over Gio, notifications
cli.py               status / dump / hits / rate
```

## Error handling

Permission denied → status page with one-click pkexec install of the udev rule. No reply →
banner "move the mouse to wake it", auto-reconnect every 2 s. Verification failure → error
toast naming the backup file; restore from the Profiles page.

## Testing

Unit tests (stdlib unittest): CRC, profile round-trip byte-exactness, field-only edits,
directory, HITS codes (all published pro codes), button codec, framing, DPI list, and the
save path against a simulated flash mouse (backup, verify failure, pristine clone).
`tools/ui_preview.py` renders every page with a simulated device. Hardware check: read-only
`cli dump` first, then one live HITS round-trip, then one verified save.
