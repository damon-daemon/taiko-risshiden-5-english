"""Bigger buffers for TAI5MSG blocks.

The message system keeps msg00 and a working copy of the current block in an arena
(descriptor 0x65B030: msg00 at +0, current block at +0xE700, size 0x1E700, inside a
fixed memory pool) and caches up to 10 blocks in 64 KB heap buffers (0x3486B0). Most
English blocks are larger than 64 KB (up to ~88 KB) and msg00 is larger than 0xE700:
loading one overflowed the buffers and corrupted the heap (the game hung in the heap
walker 0x15C540 at the first council).

Changes: the arena moves to the English data segment (MSG0 = 0xF000 bytes for msg00,
then BLOCK = 0x20000 for the working copy), every 0xE700 offset becomes 0xF000 (two
ori, and two 0x7FFF + 0x6701 split adds), the cache buffers and the slot -> working
copy memcpy become 0x20000. build checks the block sizes against these limits.
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg

MSG0 = 0xF000             # max msg00 size (also the working-copy offset; <= 0xFFFE)
BLOCK = 0x20000           # max size of any other block
ARENA_INIT = 0x313D54     # lw v1,-0x60AC(gp) ... jal 0x33EAE0 (arena_init(0x65B030, base, size))
OFFSETS_ORI = [0x346DE4, 0x3475B8]          # ori a1, zero, 0xE700
OFFSETS_SPLIT = [0x347604, 0x34762C]        # (d)addiu v0, v0, 0x6701 after +0x7FFF
SLOT_MALLOC = 0x3486B0    # lui a0, 1
SLOT_COPY = 0x346DFC      # lui a2, 1

def _word(elf, va):
    return struct.unpack_from('<I', elf, va - elfseg.VBASE + elfseg.FOFF)[0]

def check(blocks):
    """blocks = encoded TAI5MSG block sizes; raise if a buffer would overflow."""
    errors = []
    if blocks[0] > MSG0:
        errors.append('msg00 is %d bytes, buffer %d' % (blocks[0], MSG0))
    errors += ['msg%02d is %d bytes, buffer %d' % (i, n, BLOCK) for i, n in enumerate(blocks) if n > BLOCK]
    if errors:
        raise ValueError('\n'.join(errors))

def apply(elf, seg):
    arena = seg.reserve(MSG0 + BLOCK, 64)
    assert _word(elf, ARENA_INIT + 0x1C) == 0x0C0CFAB8, 'arena init call moved'   # jal 0x33EAE0
    elfseg.patch(elf, ARENA_INIT, asm.assemble(ARENA_INIT, [
        ('lui', 'a1', asm.hi(arena)), ('addiu', 'a1', 'a1', asm.lo(arena)),
        ('lui', 'a0', 0x66), ('lui', 'a2', (MSG0 + BLOCK) >> 16), ('ori', 'a2', 'a2', (MSG0 + BLOCK) & 0xFFFF),
        ('addiu', 'a0', 'a0', -0x4FD0), ('nop',), ('jal', 0x33EAE0), ('nop',)]))
    for at in OFFSETS_ORI:
        w = _word(elf, at)
        assert w & 0xFFFF == 0xE700 and w >> 26 == 0x0D, hex(at)
        elfseg.patch(elf, at, struct.pack('<I', (w & 0xFFFF0000) | MSG0))
    for at in OFFSETS_SPLIT:
        w = _word(elf, at)
        assert w & 0xFFFF == 0x6701 and _word(elf, at - 4) & 0xFFFF == 0x7FFF, hex(at)
        elfseg.patch(elf, at, struct.pack('<I', (w & 0xFFFF0000) | (MSG0 - 0x7FFF)))
    for at, reg in ((SLOT_MALLOC, 'a0'), (SLOT_COPY, 'a2')):
        w = _word(elf, at)
        assert w >> 26 == 0x0F and w & 0xFFFF == 1, hex(at)
        elfseg.patch(elf, at, asm.assemble(at, [('lui', reg, BLOCK >> 16)]))
    return arena
