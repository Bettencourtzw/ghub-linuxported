# Fixtures

- `xatuke_profile1.bin` — factory profile sector (255 bytes) dumped by the
  xatuke/logitech-superstrike-pro-x2-controller project. Its original dump had a
  zeroed tail (an old read bug at offsets >= 239), so the last two bytes were
  replaced with a freshly computed CRC-16/CCITT-FALSE to make it self-consistent.
  Field offsets 0x00..0xDF are untouched.
- `unit_profile1.bin`, `unit_directory.bin` — read-only dump of a second unit
  (fw MPM 42.01.B0014) taken with `ghub-linuxported-cli dump`. Valid CRCs; note
  the bhop byte 0x25 is 0xFF ("never configured") on this unit.
