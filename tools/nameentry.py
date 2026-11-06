"""Name entry: an English letter grid.

The name-entry grid (object fields +0x21C mode, +0x228 table size in bytes) has six
modes; the character of a cell is fetched by a helper that copies 2 bytes of the
mode's table into a small string buffer (Koei the Best addresses). Mode 1 (英数) used the full-width table at
0x5BB720 (０-９ Ａ-Ｚ ａ-ｚ, a NUL-terminated string whose strlen gives the size).

Changes:
- the mode-1 table becomes ASCII "X\\0" pairs (A-Z, a-z, 0-9: same 124 bytes), so a
  cell gives a 1-byte character drawn with the proportional Latin font and a 9-byte
  name field holds 8 letters instead of 4 full-width ones;
- its size comes from a constant instead of strlen (0x4FE2C0);
- the grid opens in mode 1 instead of 0 (kanji by reading) for names; reading fields
  still force hiragana (mode 3).
Mode names and buttons are in tl/elfstr.txt.

The new-officer card joins family and given with the format at 0x58AFE0 (made
"%s %s" in tl/elfstr.txt) for the name and for the reading line; the reading call
(0x2CAF04/0x2CAF0C) is pointed at an unreferenced "%s%s" (0x54EA18) instead, since
the reading converter turns an ASCII space into a kana glyph.
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

TABLE = 0x5BB720
CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
SIZE_CALL = 0x4FE2C0            # jal strlen(table) for mode 1
STRLEN = 0x3432F0
OPEN_MODE = [0x2CDC88, 0x500B90]  # delay slots of jal 0x4FF640: move a1, zero (mode 0)
READING_FMT = (0x2CAF04, 0x2CAF0C, 0x54EA18)   # lui a1 / addiu a1 -> "%s%s"

def apply(elf):
    f = TABLE - elfseg.VBASE + elfseg.FOFF
    old = bytes(elf[f:f + 2 * len(CHARS)])
    assert old[:2] == '０'.encode('cp932') and len(old) == 124
    elf[f:f + 124] = b''.join(c.encode('ascii') + b'\0' for c in CHARS)
    assert elf[f + 124:f + 128] == bytes(4)
    o = SIZE_CALL - elfseg.VBASE + elfseg.FOFF
    assert elf[o:o + 4] == struct.pack('<I', 0x0C000000 | STRLEN >> 2)
    elfseg.patch(elf, SIZE_CALL, asm.assemble(SIZE_CALL, [('addiu', 'v0', 'zero', 2 * len(CHARS))]))
    for at in OPEN_MODE:
        o = at - elfseg.VBASE + elfseg.FOFF
        assert elf[o:o + 4] == struct.pack('<I', 0x282D)        # daddu a1, zero, zero
        elfseg.patch(elf, at, asm.assemble(at, [('addiu', 'a1', 'zero', 1)]))
    hi_at, lo_at, fmt = READING_FMT
    o = fmt - elfseg.VBASE + elfseg.FOFF
    assert elf[o - 1:o + 5] == b'\0%s%s\0'
    for at, w in ((hi_at, 0x3C050059), (lo_at, 0x24A5AFE0)):
        o = at - elfseg.VBASE + elfseg.FOFF
        assert elf[o:o + 4] == struct.pack('<I', w)
    elfseg.patch(elf, hi_at, asm.assemble(hi_at, [('lui', 'a1', asm.hi(fmt))]))
    elfseg.patch(elf, lo_at, asm.assemble(lo_at, [('addiu', 'a1', 'a1', asm.lo(fmt))]))
