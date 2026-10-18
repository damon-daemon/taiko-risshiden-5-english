"""Name entry: an English letter grid.

The name-entry grid (object fields +0x21C mode, +0x228 table size in bytes) has six
modes; the character of a cell is fetched by 0x4F53B0, which copies 2 bytes of the
mode's table into a small string buffer. Mode 1 (英数) used the full-width table at
0x5B2920 (０-９ Ａ-Ｚ ａ-ｚ, a NUL-terminated string whose strlen gives the size).

Changes:
- the mode-1 table becomes ASCII "X\\0" pairs (A-Z, a-z, 0-9: same 124 bytes), so a
  cell gives a 1-byte character drawn with the proportional Latin font and a 9-byte
  name field holds 8 letters instead of 4 full-width ones;
- its size comes from a constant instead of strlen (0x4F5348);
- the grid opens in mode 1 instead of 0 (kanji by reading) for names; reading fields
  still force hiragana (mode 3).
Mode names and buttons are in tl/elfstr.txt (5b2bf0-5b2d30).

The new-officer card joins family and given with the format at 0x582270 (made
"%s %s" in tl/elfstr.txt) for the name and for the reading line; the reading call
(0x2C9334/0x2C933C) is pointed at an unreferenced "%s%s" (0x545C98) instead, since
the reading converter turns an ASCII space into a kana glyph.
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

TABLE = 0x5B2920
CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
SIZE_CALL = 0x4F5348            # jal strlen(table) for mode 1
OPEN_MODE = [0x2CC0EC, 0x4F7B28]  # delay slots: move a1, zero (mode 0)
READING_FMT = (0x2C9334, 0x2C933C, 0x545C98)   # lui a1 / addiu a1 -> "%s%s"

def apply(elf):
    f = TABLE - elfseg.VBASE + elfseg.FOFF
    old = bytes(elf[f:f + 2 * len(CHARS)])
    assert old[:2] == '０'.encode('cp932') and len(old) == 124
    elf[f:f + 124] = b''.join(c.encode('ascii') + b'\0' for c in CHARS)
    assert elf[f + 124:f + 128] == bytes(4)
    o = SIZE_CALL - elfseg.VBASE + elfseg.FOFF
    assert elf[o:o + 4] == struct.pack('<I', 0x0C0CF7C8)       # jal 0x33DF20 (strlen)
    elfseg.patch(elf, SIZE_CALL, asm.assemble(SIZE_CALL, [('addiu', 'v0', 'zero', 2 * len(CHARS))]))
    for at in OPEN_MODE:
        o = at - elfseg.VBASE + elfseg.FOFF
        assert elf[o:o + 4] == struct.pack('<I', 0x282D)        # daddu a1, zero, zero
        elfseg.patch(elf, at, asm.assemble(at, [('addiu', 'a1', 'zero', 1)]))
    hi_at, lo_at, fmt = READING_FMT
    o = fmt - elfseg.VBASE + elfseg.FOFF
    assert elf[o - 1:o + 5] == b'\0%s%s\0'
    for at, w in ((hi_at, 0x3C050058), (lo_at, 0x24A52270)):
        o = at - elfseg.VBASE + elfseg.FOFF
        assert elf[o:o + 4] == struct.pack('<I', w)
    elfseg.patch(elf, hi_at, asm.assemble(hi_at, [('lui', 'a1', asm.hi(fmt))]))
    elfseg.patch(elf, lo_at, asm.assemble(lo_at, [('addiu', 'a1', 'a1', asm.lo(fmt))]))
