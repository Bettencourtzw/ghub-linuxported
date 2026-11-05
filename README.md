# G HUB Linux Ported

A local, offline control panel for the **Logitech G PRO X2 SUPERSTRIKE** on Linux.
Native GTK4 / libadwaita app, a tray helper for your bar, and a CLI. No account,
no cloud, no Wine, no background daemon required. Not affiliated with Logitech.

## Features

| Area | What you can do |
|---|---|
| **HITS switches** | Per-button actuation point (1–10), rapid trigger (off / 1–5), click haptics (off / 1–5); link both buttons; changes apply live so you feel them instantly |
| **HITS codes** | Import/export G HUB HITS codes; one-click presets of the pro codes Logitech publishes |
| **Sensor** | 5 DPI stages (100–44 000, independent X/Y), enable/disable stages, default + DPI-shift stage, lift-off distance per stage, report rate up to 8 kHz wireless / 1 kHz wired, gaming surface mode, angle snapping |
| **Buttons** | Clickable mouse diagram; remap any button to a mouse button, key/shortcut (press to record), media key, DPI/profile function, or disable; separate G-Shift layer |
| **Bhop mode** | Bunny-hop scroll filter: 100–1000 ms window, live + stored |
| **Power** | Low-power and deep-sleep timers; battery level and charge state |
| **Profiles** | 5 onboard profiles: activate, enable/disable in the on-mouse cycle, rename, copy between slots, factory reset; onboard vs host control mode; JSON import/export |
| **Safety** | Every flash write: automatic backup → CRC → byte-exact read-back verification → profile reload. One-click restore of any backup. Factory profile is never modified (it's cloned first) |
| **Tray** | Battery icon in Waybar/KDE tray, low-battery and fully-charged notifications, quick DPI stage + profile switching (scroll on the icon cycles DPI), re-applies live-only settings when the mouse reconnects |
| **Diagnostics** | Real measured polling rate, click tester (hold time, fastest re-click, CPS, scroll), HID++ feature table, raw HID++ console |

Everything you save goes into the mouse's **onboard memory**, so it works on any
computer — even without this app running.

## Install

Requirements: Python 3.11+, `python-gobject`, `gtk4`, `libadwaita` ≥ 1.7 (Arch: `sudo pacman -S python-gobject gtk4 libadwaita`).

```sh
git clone <this repo> ~/ghub-linuxported
cd ~/ghub-linuxported
./install.sh --udev          # launchers + menu entry + icon, and the udev access rule (sudo)
systemctl --user enable --now ghub-linuxported-tray.service   # optional tray helper
```

On Hyprland without a systemd graphical session, use `exec-once = ghub-linuxported-tray` instead.

The udev rule (`packaging/70-ghub-linuxported.rules`) grants the logged-in user
access to Logitech hidraw nodes. It must be numbered below 73 so systemd turns
the `uaccess` tag into an ACL. The app also offers a one-click install (via
`pkexec`) when it detects missing permissions.

Run without installing: `./bin/ghub-linuxported`.

## CLI

```sh
ghub-linuxported-cli scan                 # list Logitech hidraw nodes
ghub-linuxported-cli status               # battery, mode, DPI, rate, HITS, bhop, surface
ghub-linuxported-cli features             # HID++ feature table
ghub-linuxported-cli dump [DIR]           # read-only dump of every profile sector
ghub-linuxported-cli hits --code MDAwNDA1MDMwNTEwMDQwMw==   # apply a HITS code (live)
ghub-linuxported-cli hits --actuation 3 --rapid-trigger 2 --haptics 4 [--left|--right]
ghub-linuxported-cli rate                 # measure the real polling rate
```

## How settings are stored

| Setting | Applied live via | Stored in profile at |
|---|---|---|
| HITS (actuation / RT / haptics) | `0x1B0C` fn1 | `0x26–0x2B` |
| Bhop window | `0x80E0` fn2 | `0x25` |
| Report rate | `0x8061` fn3 | `0x00` wireless, `0x01` wired |
| DPI stage select | `0x8100` fn12 | default stage `0x02` |
| DPI stages / LOD | (profile reload) | `0x04` + 5×5 bytes |
| Buttons / G-Shift | (profile reload) | `0x30` / `0x70` |
| Surface mode | `0x8090` fn1 | live only — re-applied by the tray |

Full protocol notes: [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Files

- Config: `~/.config/ghub-linuxported/config.json`
- Backups: `~/.local/share/ghub-linuxported/backups/` (never auto-deleted)

## Development

```sh
python3 -m unittest discover -s tests -t .      # unit tests (no hardware)
python3 tools/ui_preview.py /tmp/shots --dark   # render every page with a simulated mouse
```

## Credits

Protocol knowledge comes from the community's reverse-engineering work:
[xatuke/logitech-superstrike-pro-x2-controller](https://github.com/xatuke/logitech-superstrike-pro-x2-controller),
[kazehana99k (HITS 0x1B0C)](https://github.com/kazehana99k/Logitech-PRO-X2-SUPERSTRIKE-Linux-haptics-actuation-control-),
[oddvalue](https://github.com/oddvalue/linux-superstrike) / [mclol0](https://github.com/mclol0/linux-superstrike) linux-superstrike,
[Solaar](https://github.com/pwr-Solaar/Solaar) and [libratbag](https://github.com/libratbag/libratbag).
This code is an independent implementation. "Logitech", "G HUB" and "PRO X2 SUPERSTRIKE"
are trademarks of Logitech, used only to describe compatibility.

License: MIT.
