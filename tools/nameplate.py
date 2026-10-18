"""Event speaker nameplate: draw an English name as one text object.

0x2F8FB0(window, name) splits the name into strlen/2 two-byte characters (at most 8)
and gives each its own text object (window+0x208+i*4, 24 px apart, 20/18 px for 7/8
characters). English cut into byte pairs comes out garbled ("N ni j" for Ninja).

The patch replaces its strlen call (0x2F8FE4): a name that starts with an ASCII byte
is set as the text of slot 0 (position and colour as the original, no extra
character spacing, no maximum width) and strlen returns 0, so the per-character loop is skipped. Japanese names
(first byte >= 0x80) take the original path. The slots were cleared by 0x2F8760.
"""
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

STRLEN_CALL, STRLEN = 0x2F8FE4, 0x33DF20
SET_POS, SET_SPACING, SET_COLOUR, SET_TEXT = 0x46A3D0, 0x46A9F0, 0x46A580, 0x469C60
POS_X, POS_Y = 0x588B60, 0x588B64            # nameplate text origin (words)
SPACING = 0                                  # obj+0x28 = extra pixels per character (+0x2A: per line)

def code(at):
    return [
        ('lbu', 't1', 0, 'a0'), ('beqz', 't1', 'jp'), ('sltiu', 't2', 't1', 0x80),
        ('bnez', 't2', 'en'), ('nop',),
        'jp:', ('j', STRLEN), ('nop',),
        # s5 = window, s6 = name (the caller's registers)
        'en:', ('addiu', 'sp', 'sp', -0x20), ('sd', 'ra', 0x10, 'sp'), ('sd', 's0', 0, 'sp'),
        ('lw', 's0', 0x208, 's5'),
        ('lui', 'at', asm.hi(POS_X)), ('lw', 'a1', asm.lo(POS_X), 'at'),
        ('lui', 'at', asm.hi(POS_Y)), ('lw', 'a2', asm.lo(POS_Y), 'at'),
        ('jal', SET_POS), ('addu', 'a0', 's0', 'zero'),
        ('addu', 'a0', 's0', 'zero'), ('addiu', 'a1', 'zero', SPACING),
        ('jal', SET_SPACING), ('addu', 'a2', 'zero', 'zero'),
        ('lhu', 'a1', 0x232, 's5'), ('jal', SET_COLOUR), ('addu', 'a0', 's0', 'zero'),
        ('sh', 'zero', 0x1C, 's0'),
        ('addu', 'a0', 's0', 'zero'), ('addu', 'a1', 'zero', 'zero'),
        ('jal', SET_TEXT), ('addu', 'a2', 's6', 'zero'),
        ('ld', 'ra', 0x10, 'sp'), ('ld', 's0', 0, 'sp'), ('addiu', 'sp', 'sp', 0x20),
        ('jr', 'ra'), ('addu', 'v0', 'zero', 'zero')]

def apply(elf, seg):
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, code(at)), 4)
    elfseg.patch(elf, STRLEN_CALL, asm.assemble(STRLEN_CALL, [('jal', at)]))
