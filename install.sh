#!/bin/sh
# ghub-linuxported installer (per-user, no pip).
#   ./install.sh            install launchers, desktop entry, icon, tray service (user)
#   ./install.sh --udev     also install the udev access rule (asks for sudo)
#   ./install.sh --uninstall
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
RULE=/etc/udev/rules.d/70-ghub-linuxported.rules

if [ "${1:-}" = "--uninstall" ]; then
  systemctl --user disable --now ghub-linuxported-tray.service 2>/dev/null || true
  rm -f "$BIN/ghub-linuxported" "$BIN/ghub-linuxported-tray" "$BIN/ghub-linuxported-cli" \
        "$APPS/io.github.ghub_linuxported.desktop" "$ICONS/io.github.ghub_linuxported.svg" \
        "$UNITS/ghub-linuxported-tray.service"
  echo "Removed user files. Config/backups kept in ~/.config/ghub-linuxported and ~/.local/share/ghub-linuxported."
  [ -f "$RULE" ] && echo "To remove the udev rule: sudo rm $RULE && sudo udevadm control --reload"
  exit 0
fi

python3 - <<'EOF'
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 7), "libadwaita >= 1.7 required"
EOF

mkdir -p "$BIN" "$APPS" "$ICONS" "$UNITS"
for b in ghub-linuxported ghub-linuxported-tray ghub-linuxported-cli; do
  ln -sf "$REPO/bin/$b" "$BIN/$b"
done
install -m644 "$REPO/packaging/io.github.ghub_linuxported.desktop" "$APPS/"
install -m644 "$REPO/packaging/icons/io.github.ghub_linuxported.svg" "$ICONS/"
install -m644 "$REPO/packaging/ghub-linuxported-tray.service" "$UNITS/"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
systemctl --user daemon-reload 2>/dev/null || true
echo "Installed: ghub-linuxported (app), ghub-linuxported-tray, ghub-linuxported-cli -> $BIN"

if [ "${1:-}" = "--udev" ]; then
  sudo install -m644 "$REPO/packaging/70-ghub-linuxported.rules" "$RULE"
  sudo udevadm control --reload
  sudo udevadm trigger --subsystem-match=hidraw
  echo "udev rule installed: $RULE"
elif [ ! -f "$RULE" ]; then
  echo "NOTE: run './install.sh --udev' once so your user can access the mouse."
fi

cat <<EOF

Tray helper (battery in Waybar, alerts, quick DPI):
  systemctl --user enable --now ghub-linuxported-tray.service
  (or in hyprland.conf:  exec-once = ghub-linuxported-tray)
EOF
