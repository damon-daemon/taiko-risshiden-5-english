"""Proportional Latin text: new half-width fonts and the ELF changes that use them.

The game draws text one character at a time; layout, wrapping and box sizing all ask
one function for a character's advance (0x470D30: half-width codes get the cell
advance 12/10/8 for the three font sizes, full-width ones 24/20/16). Half-width
glyphs are found by a linear search of a 140-entry code list (0x531E50).

Changes:
- fonts (TAI5DATA entries 5 and 7) are rebuilt in code order: glyph i = code 0x20+i
  for 0x20-0x7F (our own Latin font, tools/latinfont.py) and code 0x40+i for
  0xA0-0xDF (the disc's half-width kana glyphs, copied at build time);
- glyph lookup for half-width codes becomes direct arithmetic (code placed at
  0x470D38, inside the old width function), which frees the code list;
- the code list space holds two width tables (24px and 20px text, codes 0x20-0x7F)
  and the new width function; 0x470D30 jumps there;
- the string width function 0x470D70 (widest line of a string) returns an even
  width: labels sized to their text (Oicho-Kabu player names) were drawn sheared
  when the width was odd (texture row stride mismatch). Japanese widths are always
  even (12/24/10/20 px cells), so only odd English widths grow, by 1 px.

Addresses and registers are Koei the Best's (the lookup 0x4711F0 keeps the code in s2
and the glyph index in s3; the original edition used s0/s1).
"""
import struct

import latinfont
from asm import assemble, hi, lo

BASE, FOFF = 0x100000, 0x80
HALF_LIST = 0x531E50          # old half-width code list (140 x u16 + 0xFFFF), 288 bytes free
WIDTHS = HALF_LIST            # 96 bytes per size: large, then small
WIDTH_FN = HALF_LIST + 0xC0   # 24 instructions, up to 0x531F70
OLD_WIDTH_FN = 0x470D30       # 16 instruction slots (13 used by the game + padding)
LOOKUP_HALF = 0x4712A0        # glyph lookup: half-width list case (lui a2 / b / addiu a2)
LOOKUP_DONE = 0x471340        # continues with s3 = glyph index (or -1)
STR_WIDTH_END = 0x470E08      # string width fn: s0 = max(s0, s1); b epilogue; v0 = s0
STR_WIDTH_EPILOGUE = 0x470ECC
FONT_ENTRIES = {'large': (5, 24), 'small': (7, 20)}     # TAI5DATA entry, cell height
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
    """OLD_WIDTH_FN: jump to the new width function, then the direct half-width lookup
    (entered from LOOKUP_HALF with s2 = code; leaves s3 = glyph index or -1)."""
    return assemble(OLD_WIDTH_FN, [
        ('j', WIDTH_FN),
        ('nop',),
        'direct:',
        ('addiu', 'v1', 's2', -0x20),
        ('sltiu', 'at', 'v1', 0x60),
        ('bnez', 'at', 'done'),                 # 0x20-0x7F -> 0-95
        ('addu', 's3', 'v1', 'zero'),
        ('addiu', 'v1', 's2', -0xA0),
        ('sltiu', 'at', 'v1', 0x40),
        ('beqz', 'at', 'done'),                 # not a glyph -> -1
        ('addiu', 's3', 'zero', -1),
        ('addiu', 's3', 'v1', 0x60),            # 0xA0-0xDF -> 96-159
        'done:',
        ('j', LOOKUP_DONE),
        ('nop',),
    ])

DIRECT = OLD_WIDTH_FN + 8

def even_width():
    """End of the string width function: the same max in one instruction (pmaxw), then
    round up to even (widths are small and positive)."""
    return assemble(STR_WIDTH_END, [
        ('pmaxw', 's0', 's0', 's1'),
        ('andi', 'at', 's0', 1),
        ('b', STR_WIDTH_EPILOGUE),
        ('addu', 'v0', 's0', 'at'),
    ])

def even_width_original():
    return assemble(STR_WIDTH_END, [
        ('sltu', 'at', 's1', 's0'),
        ('movz', 's0', 's1', 'at'),
        ('b', STR_WIDTH_EPILOGUE),
        ('daddu', 'v0', 's0', 'zero'),
    ])

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
    assert struct.unpack_from('<I', elf, OLD_WIDTH_FN - BASE + FOFF)[0] == 0x3083FFFF, 'OLD_WIDTH_FN is not andi v1, a0, 0xffff'
    assert struct.unpack_from('<I', elf, LOOKUP_HALF - BASE + FOFF)[0] == 0x3C060053, 'LOOKUP_HALF is not lui a2, 0x53'
    assert struct.unpack_from('<I', elf, LOOKUP_DONE - BASE + FOFF)[0] == 0x2403FFFF, 'LOOKUP_DONE is not addiu v1, zero, -1'
    put(HALF_LIST, blob.ljust(288, b'\0'))
    code = old_width_fn()
    assert len(code) <= 64
    put(OLD_WIDTH_FN, code)
    put(LOOKUP_HALF, lookup_branch())
    o = STR_WIDTH_END - BASE + FOFF
    assert elf[o:o + 16] == even_width_original(), 'string width fn end not found'
    put(STR_WIDTH_END, even_width())
    return fonts
