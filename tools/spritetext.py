"""Sprite text (one sprite per character, e.g. the big battle-intro title): proportional Latin.

The sprite-text layouts 0x473350 and 0x473C50 (with escape codes; Koei the Best) ask the width function for each character's
advance with the object's own cell sizes (obj+0x24 full-width, +0x25 half-width) and uses the
result twice: as the sprite's width (0x4765B0: the whole glyph cell is drawn into it) and to move
the pen. The battle title uses cells of 48/24 px (2x the 24px font), which the proportional width
function does not know, so Latin came out monospaced ("Fi el d Tutori al"). Now:
  - the sprite keeps the cell width (glyph ink starts at column 0; the rest is transparent),
  - the pen moves by the proportional width, scaled 2x, when the half-width cell is 24 or 20 px
    (stored in the layout's free stack slot 0x58; ra in 0x5C);
  - the battle title (0x252310) is centred by its pixel width instead of 24 px per byte.
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg, vwf

WIDTH_CALL = 0x473398        # jal 0x470D30 (char advance) in the sprite-text layout
PEN_STEP = 0x4734AC          # dsll32 a0, s0, 16 / dsra32 a0, a0, 16 (pen += advance)
WIDTH_CALL2 = 0x473D64       # the same in the layout with escape codes (0x473C50)
PEN_STEP2 = 0x473E0C         # andi a0, s0, 0xffff (pen += advance + spacing)
STR_WIDTH = 0x470D70         # widest line of a string (a0 str, a1 full, a2 half, a3 &lines)
TITLE_LEN = 0x252604         # battle title: jal strlen(sp+0x60); x = (0x1C0 - 48 * (len / 2)) / 2
ORIG_WIDTH_CALL = 0x0C000000 | vwf.OLD_WIDTH_FN >> 2
ORIG_PEN = (0x0010243C, 0x0004243F)
ORIG_TITLE = (0x0C04B088, 0x27A40060, 0x00022842, 0x0240202D, 0x00051840, 0x240201C0,
              0x00651821, 0x24060058, 0x00031900)

def advance(width_fn):
    """v0 = cell advance (sprite width); 0x58(sp) = pen advance."""
    return [
        ('sw', 'ra', 0x5C, 'sp'),
        ('addu', 't1', 'a1', 'zero'),
        ('jal', width_fn),
        ('addu', 't2', 'a2', 'zero'),
        ('addu', 't3', 'v0', 'zero'),          # cell (or proportional for 12/10 px cells)
        ('addiu', 'at', 'zero', 24),
        ('beq', 't2', 'at', 'double'),
        ('addiu', 'at', 'zero', 20),
        ('bne', 't2', 'at', 'done'),
        ('addu', 't4', 't3', 'zero'),
        'double:',
        ('srl', 'a1', 't1', 1),
        ('jal', width_fn),
        ('srl', 'a2', 't2', 1),
        ('sll', 't4', 'v0', 1),
        'done:',
        ('sw', 't4', 0x58, 'sp'),
        ('addu', 'v0', 't3', 'zero'),
        ('lw', 'ra', 0x5C, 'sp'),
        ('jr', 'ra'),
        ('nop',),
    ]

def title_width():
    """v0 = pixel width of the title string at a0 in the 2x sprite font."""
    return [
        ('addiu', 'sp', 'sp', -16), ('sd', 'ra', 0, 'sp'),
        ('addiu', 'a1', 'zero', 24), ('addiu', 'a2', 'zero', 12),
        ('jal', STR_WIDTH), ('addu', 'a3', 'zero', 'zero'),
        ('sll', 'v0', 'v0', 1),
        ('ld', 'ra', 0, 'sp'), ('jr', 'ra'), ('addiu', 'sp', 'sp', 16),
    ]

def _words(elf, va, n):
    return struct.unpack_from('<%dI' % n, elf, va - elfseg.VBASE + elfseg.FOFF)

def apply(elf, seg):
    assert _words(elf, WIDTH_CALL, 1) == (ORIG_WIDTH_CALL,), 'sprite-text width call'
    assert _words(elf, PEN_STEP, 2) == ORIG_PEN, 'sprite-text pen step'
    assert _words(elf, TITLE_LEN, 9) == ORIG_TITLE, 'battle title centring'
    assert _words(elf, WIDTH_CALL2, 1) == (ORIG_WIDTH_CALL,), 'sprite-text width call 2'
    assert _words(elf, PEN_STEP2, 1) == (0x3204FFFF,), 'sprite-text pen step 2'
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, advance(vwf.WIDTH_FN)), 4)
    elfseg.patch(elf, WIDTH_CALL, asm.assemble(WIDTH_CALL, [('jal', at)]))
    elfseg.patch(elf, PEN_STEP, asm.assemble(PEN_STEP, [('lw', 'a0', 0x58, 'sp'), ('nop',)]))
    elfseg.patch(elf, WIDTH_CALL2, asm.assemble(WIDTH_CALL2, [('jal', at)]))
    elfseg.patch(elf, PEN_STEP2, asm.assemble(PEN_STEP2, [('lw', 'a0', 0x58, 'sp')]))
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, title_width()), 4)
    # jal title_width; (delay a0 = sp+0x60 kept); v1 = width; the 48-px-per-2-bytes maths goes
    elfseg.patch(elf, TITLE_LEN, asm.assemble(TITLE_LEN, [('jal', at)]))
    elfseg.patch(elf, TITLE_LEN + 8, asm.assemble(TITLE_LEN + 8, [('addu', 'v1', 'v0', 'zero')]))
    for va in (TITLE_LEN + 16, TITLE_LEN + 24, TITLE_LEN + 32):
        elfseg.patch(elf, va, asm.assemble(va, [('nop',)]))
