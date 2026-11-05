# PRO X2 SUPERSTRIKE protocol notes (as implemented)

Device: wireless PID `0x40BD` via LIGHTSPEED receiver `046d:c54d`, wired PID `0xC0A8`.
HID++ 4.2 over hidraw. Feature indexes are resolved at runtime (Root `0x0000` fn0).

## Framing

- Short `0x10` (3 params) / long `0x11` (16 params). Requests with more than 3 params must be long.
- `[rid][dev][feat_idx][fn<<4 | swid][params]`. Errors: byte 2 = `0xFF` (HID++ 2.0) or `0x8F` (1.0), then `[feat_idx][fn|swid][code]`.
- Software ids: GUI `0xA`, tray `0xB`, CLI `0xC` (swid 0 = notifications, 1 = kernel).
- The child node (`hid-logitech-dj`) answers on device index `0xFF`/`0x01`; we ping to pick.

## Features used

| Feature | Use |
|---|---|
| `0x0003` Device info | fn0 entities / unit id / model id; fn1 firmware per entity; fn2 model string |
| `0x0005` Device name | fn0 length, fn1 chunks |
| `0x1004` Unified battery | fn1 → `[soc%][level][charging 0..4][ext power]` |
| `0x1B0C` Analog buttons (HITS) | fn0 caps; fn2 `[btn]` get → `[btn][act<<2][rt<<2 \| enable][hap<<2]`; fn1 set (same bytes, long report). Buttons 0 = left, 1 = right |
| `0x2202` Extended DPI | fn2 paged DPI list (range markers `0b111` top bits); fn5 get; fn6 set (host mode) |
| `0x8061` Extended report rate | fn1 supported mask (bit i = 125<<i Hz); fn2 get (stale); fn3 set (live) |
| `0x8090` Mode status | fn0 get, `status1` bits 1..2 = surface (auto/on/off); fn1 set `00 mode<<1 00 06` |
| `0x80E0` Bunny hop | fn1 = **get** window (10 ms units); fn2 = **set**. Never call fn2 to read |
| `0x8100` Onboard profiles | fn0 info; fn1/2 mode (1 onboard, 2 host); fn3/4 current profile; fn5 read 16 B; fn6/7/8 write begin/data/commit; fn11/12 DPI stage |

## Onboard profile sector (format 8, 255 bytes)

CRC-16/CCITT-FALSE over bytes 0..252, big-endian at 253..254. Reads may not cross
the sector end (read the last chunk at offset 239). Directory = sector `0x0000`,
4-byte entries `[secHi][secLo][enabled][pad]`, terminated `ff ff`. ROM factory
profile = `0x0101` (its CRC field is `ffff`).

| Offset | Field |
|---|---|
| `0x00` / `0x01` | report rate index wireless / wired (Hz = 125 << n) |
| `0x02` / `0x03` | default DPI stage / DPI-shift stage |
| `0x04 + 5n` | stage n: `Xlo Xhi Ylo Yhi LOD` (LOD 0 = disabled, 1 low, 2 med, 3 high) |
| `0x21` | power mode |
| `0x22` | angle snapping (0/1) |
| `0x25` | bhop window, 10 ms units |
| `0x26–0x2B` | HITS left, right: `[act<<2][rt<<2 \| en][hap<<2]` |
| `0x2C` / `0x2E` | low-power / deep-sleep timeout, u16 LE seconds |
| `0x30–0x6F` | buttons, 4 bytes each (slot 0..4 = L, R, M, Back, Forward) |
| `0x70–0x9F` | G-Shift button layer |
| `0xA0–0xCF` | name, UTF-16LE |

Button entry: `80 01 <mask BE16>` mouse, `80 02 <mods> <usage>` key, `80 03 <usage BE16>`
consumer, `80 00 ff ff` disabled, `90 <fn> ff 00` function, `ff ff ff ff` default, `0x0X…` macro (kept verbatim).

## HITS codes (G HUB)

Base64 of 16 ASCII digits: `00 APL APR RTL RTR [L-en R-en] HL HR`.
Example INS (CS2) `MDAwNDA1MDMwNTEwMDQwMw==` → `00 04 05 03 05 10 04 03`.

## Verification status

Field map verified against a factory dump (tests/fixtures) and cross-checked with
the sources in the README. Run `ghub-linuxported-cli dump` on your unit to compare.
