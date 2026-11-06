"""App config (~/.config/ghub-linuxported) and sector backups (~/.local/share/...)."""
from __future__ import annotations

import fcntl
import tempfile
import threading
import json
import os
import time
from pathlib import Path

APP_ID = "io.github.ghub_linuxported"
APP_NAME = "G HUB Linux Ported"


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "ghub-linuxported"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "ghub-linuxported"
BACKUP_DIR = DATA_DIR / "backups"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "low_battery_percent": 15,
    "notify_low_battery": True,
    "notify_charged": True,
    "link_hits_buttons": True,
    # Live-only settings the tray helper re-applies when the mouse reconnects.
    "reapply_on_connect": True,
    "live": {},          # e.g. {"surface": 0, "hits": [...], "bhop_ms": 0, "rate_hz": 1000, "dpi": [x, y, lod]}
    "theme": "ghub",  # ghub | system
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text()))
    except (OSError, ValueError):
        pass
    return cfg


_config_lock = threading.Lock()


def update_config(changes: dict):
    """Merge only owned fields under a process and thread lock."""
    def merge(target, patch):
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                target[key].update(value)
            else:
                target[key] = value

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with _config_lock, CONFIG_FILE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cfg = load_config()
        merge(cfg, changes)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=CONFIG_DIR, delete=False) as f:
                tmp = Path(f.name)
                json.dump(cfg, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(CONFIG_FILE)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        return cfg


def backup_sector(unit_id: str, sector: int, raw: bytes, reason: str) -> Path:
    """Store a sector image before it is overwritten. Never pruned automatically."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"{stamp}_{unit_id or 'mouse'}_sector{sector:04x}.json"
    n = 1
    while path.exists():
        path = BACKUP_DIR / f"{stamp}-{n}_{unit_id or 'mouse'}_sector{sector:04x}.json"
        n += 1
    path.write_text(json.dumps({"unit_id": unit_id, "sector": sector, "reason": reason,
                                "time": time.time(), "raw": raw.hex()}, indent=1))
    return path


def list_backups() -> list[dict]:
    out = []
    if not BACKUP_DIR.exists():
        return out
    for p in sorted(BACKUP_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text())
            d["path"] = str(p)
            out.append(d)
        except (OSError, ValueError):
            continue
    return out
