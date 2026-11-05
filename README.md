<div align="center">

<img src="packaging/icons/io.github.ghub_linuxported.svg" width="104" alt="">

# G HUB Linux Ported

**A G HUB-style control panel for Logitech G gear on Linux.**<br>
Mice, keyboards, lighting and more. Native, local and offline.

![Linux](https://img.shields.io/badge/Linux-GTK4%20%2B%20libadwaita-00a8e8?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square)

<img src="docs/screenshots/home.png" width="860" alt="Device overview">

</div>

## Devices

| Device | What you can customize |
|---|---|
| **PRO X2 SUPERSTRIKE** | HITS actuation, rapid trigger and haptics · DPI stages · polling up to 8 kHz · button remapping · bhop mode · onboard profiles |
| **G515 LS TKL** | LIGHTSYNC effects (static, breathing, color cycle, wave, ripple) · per-key painting · brightness |
| **Other Logitech HID++ devices** | Battery, firmware and feature info |

Every connected device shows up on the start screen. Click one to open its settings.

<p align="center">
  <img src="docs/screenshots/keyboard.png" width="49%" alt="Keyboard lighting">
  <img src="docs/screenshots/hits.png" width="49%" alt="HITS switches">
</p>

## Highlights

- **Instant feedback**: changes apply as you make them, with a live animated lighting preview
- **Lives in your tray**: closing the window keeps it running with battery, alerts and quick DPI. Right-click the icon and choose Quit to exit
- **Safe saving**: mouse settings are written to onboard memory with a backup, a CRC check and byte-for-byte verification
- **Keyboard lighting kept alive**: it is re-applied after sleep or reconnect, and handed back to the keyboard when you quit
- **G HUB look**: dark theme with Logitech G cyan, or follow your system theme

## Install

```sh
# Arch: sudo pacman -S python-gobject gtk4 libadwaita libdbusmenu-glib
git clone https://github.com/Bettencourtzw/ghub-linuxported.git
cd ghub-linuxported
./install.sh --udev
```

Open **G HUB Linux Ported** from your app menu. To start it hidden in the tray at login:

```sh
systemctl --user enable --now ghub-linuxported-tray.service
```

## CLI

```sh
ghub-linuxported-cli status                                # mouse battery, DPI, HITS, bhop
ghub-linuxported-cli hits --code MDAwNDA1MDMwNTEwMDQwMw==  # apply a HITS code
ghub-linuxported-cli rate                                  # measure real polling rate
```

## Credits

Built on the community's reverse-engineering work:
[xatuke](https://github.com/xatuke/logitech-superstrike-pro-x2-controller),
[kazehana99k](https://github.com/kazehana99k/Logitech-PRO-X2-SUPERSTRIKE-Linux-haptics-actuation-control-),
[linux-superstrike](https://github.com/mclol0/linux-superstrike),
[Solaar](https://github.com/pwr-Solaar/Solaar),
[OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) and
[libratbag](https://github.com/libratbag/libratbag).
Protocol notes: [docs/PROTOCOL.md](docs/PROTOCOL.md).

<sub>Not affiliated with Logitech. "Logitech", "G HUB", "LIGHTSYNC", "PRO X2 SUPERSTRIKE" and "G515" are trademarks of Logitech. MIT licensed.</sub>
