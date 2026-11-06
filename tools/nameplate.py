"""Event speaker nameplate: draw an English name as one text object.

0x2FCDE0(window, name) splits the name into strlen/2 two-byte characters (at most 8)
and gives each its own text object (window+0x208+i*4, 24 px apart, 20/18 px for 7/8
characters). English cut into byte pairs comes out garbled ("N ni j" for Ninja).

The patch replaces its strlen call (0x2FCE14): a name that starts with an ASCII byte
is set as the text of slot 0 (position and colour as the original, no extra
character spacing, no maximum width) and strlen returns 0, so the per-character loop is skipped. Japanese names
(first byte >= 0x80) take the original path. The slots were cleared by 0x2FC5A0. (Koei the Best: window in s6, name in s5;
the original edition had them the other way round.)
"""
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

STRLEN_CALL, STRLEN = 0x2FCE14, 0x3432F0
SET_POS, SET_SPACING, SET_COLOUR, SET_TEXT = 0x4735E0, 0x473B80, 0x473770, 0x472E60
WINDOW, NAME = 's6', 's5'                    # the caller's registers
POS_X, POS_Y = 0x5918D0, 0x5918D4            # nameplate text origin (words)
SPACING = 0                                  # obj+0x28 = extra pixels per character (+0x2A: per line)

def code(at):
    return [
        ('lbu', 't1', 0, 'a0'), ('beqz', 't1', 'jp'), ('sltiu', 't2', 't1', 0x80),
        ('bnez', 't2', 'en'), ('nop',),
        'jp:', ('j', STRLEN), ('nop',),
        # WINDOW / NAME: the caller's registers
        'en:', ('addiu', 'sp', 'sp', -0x20), ('sd', 'ra', 0x10, 'sp'), ('sd', 's0', 0, 'sp'),
        ('lw', 's0', 0x208, WINDOW),
        ('lui', 'at', asm.hi(POS_X)), ('lw', 'a1', asm.lo(POS_X), 'at'),
        ('lui', 'at', asm.hi(POS_Y)), ('lw', 'a2', asm.lo(POS_Y), 'at'),
        ('jal', SET_POS), ('addu', 'a0', 's0', 'zero'),
        ('addu', 'a0', 's0', 'zero'), ('addiu', 'a1', 'zero', SPACING),
        ('jal', SET_SPACING), ('addu', 'a2', 'zero', 'zero'),
        ('lhu', 'a1', 0x232, WINDOW), ('jal', SET_COLOUR), ('addu', 'a0', 's0', 'zero'),
        ('sh', 'zero', 0x1C, 's0'),
        ('addu', 'a0', 's0', 'zero'), ('addu', 'a1', 'zero', 'zero'),
        ('jal', SET_TEXT), ('addu', 'a2', NAME, 'zero'),
        ('ld', 'ra', 0x10, 'sp'), ('ld', 's0', 0, 'sp'), ('addiu', 'sp', 'sp', 0x20),
        ('jr', 'ra'), ('addu', 'v0', 'zero', 'zero')]

def apply(elf, seg):
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, code(at)), 4)
    o = STRLEN_CALL - elfseg.VBASE + elfseg.FOFF
    assert int.from_bytes(elf[o:o + 4], 'little') == 0x0C000000 | STRLEN >> 2, 'strlen call'
    assert int.from_bytes(elf[o + 4:o + 8], 'little') == 0x0000202D | asm.R[NAME] << 21, 'move a0, NAME'
    elfseg.patch(elf, STRLEN_CALL, asm.assemble(STRLEN_CALL, [('jal', at)]))
