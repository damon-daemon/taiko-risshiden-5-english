"""Proportional Latin text: new half-width fonts and the ELF changes that use them.

The game draws text one character at a time; layout, wrapping and box sizing all ask
one function for a character's advance (0x467A80: half-width codes get the cell
advance 12/10/8 for the three font sizes, full-width ones 24/20/16). Half-width
glyphs are found by a linear search of a 140-entry code list (0x5290D0).

Changes:
- fonts (TAI5DATA entries 0 and 2) are rebuilt in code order: glyph i = code 0x20+i
  for 0x20-0x7F (our own Latin font, tools/latinfont.py) and code 0x40+i for
  0xA0-0xDF (the disc's half-width kana glyphs, copied at build time);
- glyph lookup for half-width codes becomes direct arithmetic (code placed at
  0x467A88, inside the old width function), which frees the code list;
- the code list space holds two width tables (24px and 20px text, codes 0x20-0x7F)
  and the new width function; 0x467A80 jumps there.
"""
import struct

import latinfont
from asm import assemble, hi, lo

BASE, FOFF = 0x100000, 0x80
HALF_LIST = 0x5290D0          # old half-width code list (140 x u16 + 0xFFFF), 288 bytes free
WIDTHS = HALF_LIST            # 96 bytes per size: large, then small
WIDTH_FN = HALF_LIST + 0xC0   # 24 instructions, up to 0x5291F0
OLD_WIDTH_FN = 0x467A80       # 16 instruction slots
LOOKUP_HALF = 0x468060        # glyph lookup: 'code < 0x100' branch target
LOOKUP_DONE = 0x4681B8        # continues with s1 = glyph index (or -1)
FONT_ENTRIES = {'large': (0, 24), 'small': (2, 20)}     # TAI5DATA entry, cell height
OLD_CODES = 140

# --- code -----------------------------------------------------------------------
def width_fn():
    """v0 = advance(a0 = code, a1 = full-width advance, a2 = half-width advance)."""
    return assemble(WIDTH_FN, [
        ('andi', 'v1', 'a0', 0xFFFF),
        ('ori', 'v0', 'zero', 0x874B),          # two double-width symbols (as before)
        ('beq', 'v1', 'v0', 'double'),
        ('ori', 'v0', 'zero', 0x874C),
        ('beq', 'v1', 'v0', 'double'),
        ('addiu', 't0', 'v1', -0x20),
        ('sltiu', 'at', 't0', 0x60),
        ('beqz', 'at', 'cell'),                 # not 0x20-0x7F
        ('addiu', 'at', 'zero', 12),
        ('beq', 'a2', 'at', 'table'),           # 24px text: first table
        ('lui', 'v0', hi(WIDTHS)),
        ('addiu', 'at', 'zero', 10),
        ('bne', 'a2', 'at', 'cell'),            # 16px text has no Latin glyphs
        ('nop',),
        ('addiu', 't0', 't0', 0x60),            # 20px text: second table
        'table:',
        ('addu', 'v0', 'v0', 't0'),
        ('jr', 'ra'),
        ('lbu', 'v0', lo(WIDTHS), 'v0'),
        'cell:',
        ('sltiu', 'at', 'v1', 0x100),
        ('movz', 'a2', 'a1', 'at'),
        ('jr', 'ra'),
        ('addu', 'v0', 'a2', 'zero'),
        'double:',
        ('jr', 'ra'),
        ('sll', 'v0', 'a1', 1),
    ])

def old_width_fn():
    """0x467A80: jump to the new width function, then the direct half-width lookup
    (entered from LOOKUP_HALF with s0 = code; leaves s1 = glyph index or -1)."""
    return assemble(OLD_WIDTH_FN, [
        ('j', WIDTH_FN),
        ('nop',),
        'direct:',
        ('addiu', 'v1', 's0', -0x20),
        ('sltiu', 'at', 'v1', 0x60),
        ('bnez', 'at', 'done'),                 # 0x20-0x7F -> 0-95
        ('addu', 's1', 'v1', 'zero'),
        ('addiu', 'v1', 's0', -0xA0),
        ('sltiu', 'at', 'v1', 0x40),
        ('beqz', 'at', 'done'),                 # not a glyph -> -1
        ('addiu', 's1', 'zero', -1),
        ('addiu', 's1', 'v1', 0x60),            # 0xA0-0xDF -> 96-159
        'done:',
        ('j', LOOKUP_DONE),
        ('nop',),
    ])

DIRECT = OLD_WIDTH_FN + 8

def lookup_branch():
    return assemble(LOOKUP_HALF, [('b', DIRECT), ('nop',)])

# --- data -------------------------------------------------------------------------
def old_codes(elf):
    off = HALF_LIST - BASE + FOFF
    codes = list(struct.unpack_from('<%dH' % OLD_CODES, elf, off))
    assert struct.unpack_from('<H', elf, off + 2 * OLD_CODES)[0] == 0xFFFF
    return [c & 0xFF for c in codes]

def build_font(old, codes, size):
    """old font entry bytes -> new font entry (160 glyphs in code order)."""
    h = FONT_ENTRIES[size][1]
    gs = 12 * h // 2
    assert len(old) == OLD_CODES * gs
    glyphs = latinfont.render(size)
    out = bytearray(160 * gs)
    for i in range(96):
        c = chr(0x20 + i)
        if c in glyphs:
            rows = glyphs[c][0]
            for y in range(h):
                for x in range(0, 12, 2):
                    out[i * gs + (y * 12 + x) // 2] = rows[y][x] | rows[y][x + 1] << 4
    for k, code in enumerate(codes):
        if code >= 0xA0:
            i = code - 0x40
            out[i * gs:(i + 1) * gs] = old[k * gs:(k + 1) * gs]
    return bytes(out)

def width_tables():
    t = bytearray()
    for size in ('large', 'small'):
        g = latinfont.render(size)
        t += bytes(g[chr(c)][1] if chr(c) in g else 0 for c in range(0x20, 0x80))
    return bytes(t)

def apply(elf, entry):
    """elf: bytearray (patched in place); entry(i) -> clean TAI5DATA entry bytes.
    Returns {entry index: new bytes} for the fonts."""
    codes = old_codes(elf)
    fonts = {i: build_font(entry(i), codes, size) for size, (i, _) in FONT_ENTRIES.items()}
    def put(va, data):
        elf[va - BASE + FOFF:va - BASE + FOFF + len(data)] = data
    blob = width_tables() + width_fn()
    assert len(blob) <= 288, len(blob)
    put(HALF_LIST, blob.ljust(288, b'\0'))
    code = old_width_fn()
    assert len(code) <= 64
    put(OLD_WIDTH_FN, code)
    put(LOOKUP_HALF, lookup_branch())
    return fonts
