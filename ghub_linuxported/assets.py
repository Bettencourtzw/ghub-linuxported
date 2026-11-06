"""Checkout-local branding and product artwork; never fetched at runtime."""
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
APP_ICON = PACKAGING / "icons" / "io.github.ghub_linuxported.svg"
# A distinct lookup name avoids a stale installed icon in the About dialog.
APP_ICON_NAME = "io.github.ghub_linuxported.brand"

PRODUCT_IMAGES = {
    0x40BD: "pro-x2-superstrike.png",
    0xC0A8: "pro-x2-superstrike.png",
    0x40B4: "g515-lightspeed-tkl.png",
}
PRODUCT_NAMES = {
    "PRO X2 SUPERSTRIKE": "pro-x2-superstrike.png",
    "PRO X 2 SUPERSTRIKE": "pro-x2-superstrike.png",
    "G515 LS TKL": "g515-lightspeed-tkl.png",
    "G515 LIGHTSPEED TKL": "g515-lightspeed-tkl.png",
}


def device_image(device) -> Path | None:
    """Only show a product photograph for an identified model, never by category."""
    name = " ".join(device.title.upper().split()).removeprefix("LOGITECH ")
    filename = PRODUCT_IMAGES.get(device.pid) or PRODUCT_NAMES.get(name)
    if filename:
        path = PACKAGING / "devices" / filename
        if path.is_file():
            return path
    return None
