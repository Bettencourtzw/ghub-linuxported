# UI screenshots

These are native GTK4/libadwaita captures from the app on macOS, using the
simulated devices in `tools/ui_preview.py`. Battery levels and device status
are examples. They do not demonstrate Linux hardware support or hardware tests.

The preview uses temporary settings, disables real discovery and tray services,
and never submits commands to hardware. Interactive mode opens the device
picker and lets you navigate the same interface without connecting devices.

Regenerate from the repository root:

```sh
python3 tools/ui_preview.py docs/screenshots --width 1240 --height 1000
python3 tools/ui_preview.py docs/screenshots --page home --width 1100 --height 700
```

On macOS, install `gtk4`, `libadwaita`, `pygobject3` and `adwaita-icon-theme`
with Homebrew first. To keep the picker open, run:

```sh
python3 tools/ui_preview.py --interactive --width 1100 --height 700
```
