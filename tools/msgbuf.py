"""Bigger buffers for TAI5MSG blocks.

The message system keeps msg00 and a working copy of the current block in an arena
(descriptor 0x65F3B0: msg00 at +0, current block at +0xE700, size 0x1E700, inside a
fixed memory pool) and caches up to 10 blocks in 64 KB heap buffers (0x34D978). Most
English blocks are larger than 64 KB (up to ~88 KB) and msg00 is larger than 0xE700:
loading one overflowed the buffers and corrupted the heap (the game hung in the heap
walker at the first council). Addresses: Koei the Best.

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
ARENA_INIT = 0x318574     # lw v1,-0x60AC(gp) ... jal 0x343E40 (arena_init(0x65F3B0, base, size))
ARENA_FN = 0x343E40
DESCRIPTOR = 0x65F3B0
OFFSETS_ORI = [0x34C08C, 0x34C86C]          # ori a1, zero, 0xE700 (0x34C760 compares a size: kept)
OFFSETS_SPLIT = [0x34C928, 0x34C950]        # (d)addiu v0, v0, 0x6701 after +0x7FFF
SLOT_MALLOC = 0x34D978    # lui a0, 1
SLOT_COPY = 0x34C0AC      # lui a2, 1

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
    assert _word(elf, ARENA_INIT + 0x1C) == 0x0C000000 | ARENA_FN >> 2, 'arena init call moved'
    elfseg.patch(elf, ARENA_INIT, asm.assemble(ARENA_INIT, [
        ('lui', 'a1', asm.hi(arena)), ('addiu', 'a1', 'a1', asm.lo(arena)),
        ('lui', 'a0', asm.hi(DESCRIPTOR)), ('lui', 'a2', (MSG0 + BLOCK) >> 16), ('ori', 'a2', 'a2', (MSG0 + BLOCK) & 0xFFFF),
        ('addiu', 'a0', 'a0', asm.lo(DESCRIPTOR)), ('nop',), ('jal', ARENA_FN), ('nop',)]))
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
