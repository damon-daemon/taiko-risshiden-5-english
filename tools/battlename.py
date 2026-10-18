"""Battle titles: "Battle of <place>" instead of "<place>の戦い".

0x253460 builds the battle title in a 28-byte stack buffer (sp+0x60) with
strcpy(buf, place) and strcat(buf, "の戦い") (four sites: named battles, castles,
provinces, towns). The strcat calls are replaced by prefix(buf, s), which puts s
(tl/elfstr.txt 54a3c8 = "Battle of ") in front of the place name and cuts the result
to 27 characters. The suffix string stays the argument, so its English is the prefix.
"""
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

STRCAT_CALLS = [0x253570, 0x2535B0, 0x25365C, 0x2536B4]
MAX = 27

def code(tmp):
    return [
        # copy the place name to tmp
        ('addu', 't0', 'a0', 'zero'), ('lui', 't1', asm.hi(tmp)), ('addiu', 't1', 't1', asm.lo(tmp)),
        'c1:', ('lbu', 't3', 0, 't0'), ('sb', 't3', 0, 't1'), ('addiu', 't0', 't0', 1),
        ('bnez', 't3', 'c1'), ('addiu', 't1', 't1', 1),
        # buf = prefix
        ('addu', 't0', 'a0', 'zero'), ('addu', 't1', 'a1', 'zero'),
        'c2:', ('lbu', 't3', 0, 't1'), ('beqz', 't3', 'c2d'), ('nop',),
        ('sb', 't3', 0, 't0'), ('addiu', 't0', 't0', 1), ('b', 'c2'), ('addiu', 't1', 't1', 1),
        # + place name, at most MAX characters in all
        'c2d:', ('lui', 't1', asm.hi(tmp)), ('addiu', 't1', 't1', asm.lo(tmp)), ('addiu', 't2', 'a0', MAX),
        'c3:', ('beq', 't0', 't2', 'cut'), ('lbu', 't3', 0, 't1'),
        ('sb', 't3', 0, 't0'), ('addiu', 't0', 't0', 1), ('bnez', 't3', 'c3'), ('addiu', 't1', 't1', 1),
        ('jr', 'ra'), ('nop',),
        'cut:', ('sb', 'zero', 0, 't0'), ('jr', 'ra'), ('nop',)]

def apply(elf, seg):
    tmp = seg.reserve(64, 4)
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, code(tmp)), 4)
    for call in STRCAT_CALLS:
        assert elf[call - elfseg.VBASE + elfseg.FOFF:][:4] == asm.assemble(call, [('jal', 0x12BE10)])
        elfseg.patch(elf, call, asm.assemble(call, [('jal', at)]))
