# Expanding device support

Research date: 2026-11-06. This is an implementation map, **not a claim that
these devices have been tested with GLP**. This change adds artwork only; it
does not enable new hardware writes.

## What the current app actually supports

`devices.py` discovers Logitech hidraw nodes, pings HID++ and reads identity,
kind and selected features. Other mice reach `GenericView` for device info.
All devices classified as keyboards currently reach `KeyboardView`, even
though that editor assumes a TKL layout and the G515 lighting path. That
classification is too broad to call general keyboard support.

`hidpp/mouse.py` resolves feature IDs to each device's runtime index correctly,
but its configurable mouse settings use extended DPI (`0x2202`), extended
report rate (`0x8061`) and SUPERSTRIKE HITS (`0x1B0C`). `model/profile.py` is
explicitly a SUPERSTRIKE format-8 parser. Do not send those profile bytes to
another model just because it exposes onboard memory (`0x8100`).

## Concrete next targets

Identifiers below are device IDs, not a guarantee that the receiver uses the
same USB PID. Firmware, wired/wireless mode and protocol version still matter.

| Family | Upstream evidence | Work needed in GLP |
|---|---|---|
| G305 (`4074`) | Solaar capture: DPI `2201`, rate `8060`, battery `1000`; libratbag has a G305 quirk | Standard DPI/rate adapters, legacy battery status, inspect the quirk before writes |
| G502 HERO (`c08b`), G502 X (`c099`) | libratbag HID++ 2 driver entries use `INDEX_OFFSET`; HERO capture has `2201`, `8060`, `8070`, `8100` | Standard controls and model-specific indexing; no automatic reuse of SUPERSTRIKE profiles |
| PRO X SUPERLIGHT (`4093` wireless, `c094` USB) | libratbag HID++ 2 device entry | Candidate for the same capability-based mouse controls; capture actual features first |
| G915 TKL (`408e` wireless; `c343` USB; `b35f` Bluetooth) | Solaar capture: RGB `8071`, per-key `8081`, brightness `8040`, battery voltage `1001` | Closest lighting candidate; validate layout, effects, host mode and battery conversion |
| G815 (`c33f`) | Solaar capture has `8071`, `8081`, `8040`; libratbag identifies a keyboard | Full-size layout and zone mapping, discovered effect slots; no battery expected from a wired-only device |
| G PRO keyboard (`c339`) | libratbag HID++ 2 entry | Read feature table and layout before selecting a lighting implementation |
| MX Keys / MX Master families | Solaar supports HID++ devices via appropriate receiver, USB or Bluetooth | Separate office-device controls: Fn/media, backlight, scroll and reprogrammable controls; not the G515 RGB screen |

## How to call more devices

Keep `Mouse.feature_index()` / `Mouse.call()` as the existing transport boundary.
HID++ feature IDs are stable; feature indexes are discovered per connection.
Solaar uses function bytes such as `0x20`; this app accepts the unshifted
function number (`2`) and shifts it in `build_request()`.

| Capability | Discovery/read/write route | Difference from current special-purpose path |
|---|---|---|
| Identity and features | ROOT `0000`, FEATURE_SET `0001`, name `0005`, firmware `0003` | Already present; save versions and flags as well as IDs |
| Standard DPI `2201` | Enumerate supported DPI via function 1; read 2; write 3 with sensor index and big-endian DPI | Extended `2202` uses different payloads and functions 5/6 for read/write |
| Standard report rate `8060` | Function 0 capability bitmask; read 1; write 2 | Value is a millisecond interval, not the `8061` high-rate enum |
| Battery | Separate adapters for status `1000`, voltage `1001`, unified `1004` | Only `1004` currently has a parser; voltage is not a percentage |
| Keyboard lighting | Probe `8070` vs `8071`, `8080` vs `8081`, and `8040` | Discover clusters, effect slots, zones and supported directions; do not assume the G515 map |
| Office keyboards | Fn inversion and backlight feature families | Versioned payloads; MX Keys backlighting is different from gaming RGB |

Use upstream code as protocol evidence, not copied implementation: Solaar and
libratbag have their own licenses. Feature presence alone does not establish
that a write is safe or that a layout matches.

## Recommended order

1. Make discovery reliable across buses/receivers. Preserve the Linux HID bus
   ID instead of labelling every non-SUPERSTRIKE-wired device LIGHTSPEED. Handle
   receiver pairing slots and unsupported HID++ 1.x devices explicitly.
2. Add a read-only capability snapshot and representative fixtures. Include
   model/transport IDs, protocol and firmware, feature versions, effect/zone
   descriptions, and permission/asleep states. Redact serials and unit IDs
   before sharing captures.
3. Build standard mouse DPI/rate and battery adapters with supported-range
   validation and read-back tests. Keep HITS hidden unless supported. Preserve
   each device's current host/onboard mode unless a user explicitly changes it.
4. Gate keyboard controls by discovered capabilities and verified layouts.
   Start with G915 TKL, then G815. Unsupported keyboards must retain an honest
   information-only screen rather than receiving G515 writes.
5. Add persistence only after verifying that model's profile format and backup,
   CRC and read-back behavior. Keep missing/unknown formats read-only.

Acceptance per new model: a real read-only capture, parser/transport fixtures,
correct UI capability gates, one reversible setting change plus read-back on
hardware, reconnect/sleep checks, and separate verification before flash writes.

## Pinned primary sources

- [Solaar feature catalogue](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/docs/features.md)
- [Solaar setting implementations](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/lib/logitech_receiver/settings_templates.py): `AdjustableDpi`, `ReportRate`, `Backlight2`, and lighting validators.
- [Solaar receiver/device scope](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/docs/devices.md)
- [G305 capture](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/docs/devices/G305%20Lightspeed%20Wireless%20Gaming%20Mouse%204074.text)
- [G502 HERO capture](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/docs/devices/G502%20SE%20Hero%20Gaming%20Mouse%20C08B.txt)
- [G915 TKL capture](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/docs/devices/G915%20TKL%20LIGHTSPEED%20Wireless%20RGB%20Mechanical%20Gaming%20Keyboard%20408E.txt)
- [G815 capture](https://github.com/pwr-Solaar/Solaar/blob/e7304c4c451cc9bb4f206a914844525e67856a28/docs/devices/G815%20Mechanical%20Keyboard%20C33F.txt)
- [libratbag device definitions](https://github.com/libratbag/libratbag/tree/8235b5bb6032dea15901ab58a8218956f4494d08/data/devices): `logitech-g305.device`, `logitech-g502-hero.device`, `logitech-g502-x.device`, `logitech-g-pro-x-wireless-superlight.device`, `logitech-g915-tkl.device`, `logitech-g815.device`, `logitech-g-pro-keyboard.device`.
