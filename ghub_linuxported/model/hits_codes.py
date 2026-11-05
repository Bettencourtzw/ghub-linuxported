"""G HUB "HITS codes": Base64 of 16 ASCII digits = 8 two-digit decimal fields.

  00  APL APR  RTL RTR  [L-enabled R-enabled]  HL HR
  e.g. INS (CS2): MDAwNDA1MDMwNTEwMDQwMw== -> 00 04 05 03 05 10 04 03
       actuation L4/R5, rapid trigger L3 on / R(5) off, haptics L4/R3

Derived from the pro codes Logitech publishes at
logitechg.com/discover/learn/superstrike-hits-codes; every code there decodes
with this layout (one, Doki's, has a typo on the page — see PRO_PRESETS).
"""
from __future__ import annotations

import base64
import binascii

from ..hidpp.mouse import HitsButton


class InvalidHitsCode(ValueError):
    pass


def decode(code: str) -> tuple[HitsButton, HitsButton]:
    code = code.strip()
    try:
        digits = base64.b64decode(code, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidHitsCode("not a HITS code (invalid Base64)") from exc
    if len(digits) != 16 or not digits.isdigit():
        raise InvalidHitsCode("not a HITS code (expected 16 digits)")
    f = [digits[i:i + 2] for i in range(0, 16, 2)]
    if f[0] != "00":
        raise InvalidHitsCode(f"unsupported HITS code version {f[0]}")
    apl, apr, rtl, rtr, hl, hr = (int(x) for x in (f[1], f[2], f[3], f[4], f[6], f[7]))
    en_l, en_r = f[5][0], f[5][1]
    if en_l not in "01" or en_r not in "01":
        raise InvalidHitsCode("invalid rapid-trigger flags")
    for v, lo, hi, what in ((apl, 1, 10, "actuation"), (apr, 1, 10, "actuation"),
                            (rtl, 1, 5, "rapid trigger"), (rtr, 1, 5, "rapid trigger"),
                            (hl, 0, 5, "haptics"), (hr, 0, 5, "haptics")):
        if not lo <= v <= hi:
            raise InvalidHitsCode(f"{what} value {v} out of range {lo}..{hi}")
    return (HitsButton(apl, rtl, en_l == "1", hl), HitsButton(apr, rtr, en_r == "1", hr))


def encode(left: HitsButton, right: HitsButton) -> str:
    digits = (f"00{left.actuation:02d}{right.actuation:02d}{left.rt_level:02d}{right.rt_level:02d}"
              f"{int(left.rt_enabled)}{int(right.rt_enabled)}{left.haptics:02d}{right.haptics:02d}")
    return base64.b64encode(digits.encode()).decode()


# (player, game, code) — verbatim from Logitech's page, except Doki, whose
# published code ends in "0555" (invalid); the page's table says haptics 5/5.
PRO_PRESETS = [
    ("INS", "CS2", "MDAwNDA1MDMwNTEwMDQwMw=="),
    ("Coach Joe", "Valorant", "MDAwMjAyMDIwMjExMDQwMw=="),
    ("KSCERATO", "CS2", "MDAwMjAyMDMwMjExMDMwMw=="),
    ("Siwoo", "League of Legends", "MDAwMjAyMDEwMTExMDMwMw=="),
    ("Lucid", "League of Legends", "MDAwNTAxMDEwMTExMDMwMw=="),
    ("ShowMaker", "League of Legends", "MDAwMjAyMDEwMTExMDIwMg=="),
    ("Smash", "League of Legends", "MDAwMjAyMDIwMjExMDEwMQ=="),
    ("Career", "League of Legends", "MDAwMjAyMDIwMjExMDQwNA=="),
    ("MrFaLin", "Valorant", "MDAwNDA1MDIwMjExMDMwNQ=="),
    ("Yetujey", "Valorant", "MDAwNDA0MDMwMzExMDIwMg=="),
    ("Blaz", "Rainbow Six Siege", "MDAwNjA2MDMwMzExMDAwMA=="),
    ("Doki", "Rainbow Six Siege", base64.b64encode(b"0006060101110505").decode()),
]
