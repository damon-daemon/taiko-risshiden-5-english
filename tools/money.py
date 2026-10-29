"""Money in messages: "500 mon", "3 kan 500 mon" instead of "500文", "3貫500文".

The game's printf (0x340xxx) prints %m / %M (money, half- / full-width digits) with
0x33FC10(emit, value, width, fullwidth): for each unit (index 0 = 貫, 1 = 文) it
prints the number, then the unit as one SJIS character from the word table at
gp-0x6438 (two emit calls), and stops when the rest is 0. The two emit calls are
replaced by unit(index, emit, value, divisor), which emits " kan" or " mon" and,
after " kan", a space when a mon part follows (rest = value % divisor, as the
caller computes next with 0x1201C8). It returns the bytes emitted; the caller
counts 2 per unit, so the patch adds the difference.
"""
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

SITE = 0x33FD38          # unit index -> word table -> two jalr emit calls (10 words)
MOD = 0x1201C8           # 64-bit remainder (a0 % a1)
UNITS = (b' kan', b' mon')
ORIGINAL = (0x0011103C, 0x0002103F, 0x00021880, 0x2782 << 16 | 0x9BC8, 0x0043A821,
            0x8EA20000, 0x0280F809, 0x00022203, 0x0280F809, 0x92A40000)

def code(words):
    return [
        ('addiu', 'sp', 'sp', -48), ('sd', 'ra', 0, 'sp'), ('sd', 's0', 8, 'sp'), ('sd', 's1', 16, 'sp'),
        ('sd', 's2', 24, 'sp'), ('sd', 's3', 32, 'sp'),
        ('addu', 's0', 'a1', 'zero'), ('addu', 's3', 'zero', 'zero'), ('addu', 's2', 'zero', 'zero'),
        ('sll', 't0', 'a0', 2), ('lui', 't1', asm.hi(words)), ('addiu', 't1', 't1', asm.lo(words)),
        ('addu', 't0', 't0', 't1'), ('bnez', 'a0', 'emit'), ('lw', 's1', 0, 't0'),
        # kan: a space follows if a mon part is left
        ('or', 'a0', 'a2', 'zero'), ('jal', MOD), ('or', 'a1', 'a3', 'zero'),
        ('sltu', 's2', 'zero', 'v0'),
        'emit:', ('lbu', 'a0', 0, 's1'), ('beqz', 'a0', 'tail'), ('nop',),
        ('jalr', 's0'), ('addiu', 's1', 's1', 1), ('b', 'emit'), ('addiu', 's3', 's3', 1),
        'tail:', ('beqz', 's2', 'done'), ('nop',),
        ('jalr', 's0'), ('addiu', 'a0', 'zero', 0x20), ('addiu', 's3', 's3', 1),
        'done:', ('addu', 'v0', 's3', 'zero'),
        ('ld', 'ra', 0, 'sp'), ('ld', 's0', 8, 'sp'), ('ld', 's1', 16, 'sp'), ('ld', 's2', 24, 'sp'),
        ('ld', 's3', 32, 'sp'), ('jr', 'ra'), ('addiu', 'sp', 'sp', 48)]

def apply(elf, seg):
    o = SITE - elfseg.VBASE + elfseg.FOFF
    import struct
    assert struct.unpack_from('<10I', elf, o) == ORIGINAL, 'money unit site'
    strs = [seg.add(u + b'\0', 1) for u in UNITS]
    words = seg.add(struct.pack('<2I', *strs), 4)
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, code(words)), 4)
    elfseg.patch(elf, SITE, asm.assemble(SITE, [
        ('addu', 'a0', 's1', 'zero'), ('addu', 'a1', 's4', 'zero'), ('or', 'a2', 's3', 'zero'),
        ('or', 'a3', 's0', 'zero'), ('jal', at), ('nop',),
        ('addu', 's2', 's2', 'v0'), ('addiu', 's2', 's2', -2), ('nop',), ('nop',)]))
