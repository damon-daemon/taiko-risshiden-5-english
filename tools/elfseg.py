"""English data segment: code and data the patches need, loaded at the end of the BSS.

The ELF has two PT_LOAD program headers; the second (at _end = 0x8B3380) is empty.
Filling it makes the loader place our bytes right after the BSS. The heap starts at
_end, so crt0 is patched to start it after the segment instead:

  0x1001D0/0x1001D8  lui/addiu a0 = _end   SetupHeap syscall (0x3D): heap start
  0x1005A4/0x1005B0  lui/addiu a0 = _end   size of the one big malloc arena
  0x1005F4/0x100600  lui/addiu a1 = _end   (same, second copy)

  0x5142B4           word = _end           libkernel sbrk's heap pointer (sbrk 0x10F4C0)

0x100120/0x100128 (BSS clear end) stays: the BSS still ends at 0x8B3380.
"""
import struct, sys, os

sys.path.insert(0, os.path.dirname(__file__))
import asm

BASE = 0x8B3380
FOFF, VBASE = 0x80, 0x100000
HEAP_SITES = [(0x1001D0, 0x1001D8, 'a0'), (0x1005A4, 0x1005B0, 'a0'), (0x1005F4, 0x100600, 'a1')]
HEAP_WORDS = [0x5142B4]

class Segment:
    def __init__(self, base=BASE):
        self.base, self.data = base, bytearray()

    @property
    def end(self):
        return self.base + len(self.data)

    def add(self, b, align=4):
        self.data.extend(bytes(-len(self.data) % align))
        addr = self.end
        self.data.extend(b)
        return addr

    def reserve(self, n, align=4):
        """Address of n zero bytes (filled later with put)."""
        return self.add(bytes(n), align)

    def put(self, addr, b):
        o = addr - self.base
        assert 0 <= o and o + len(b) <= len(self.data)
        self.data[o:o + len(b)] = b

def patch(elf, vaddr, b):
    o = vaddr - VBASE + FOFF
    elf[o:o + len(b)] = b

def apply(elf, seg):
    """Append the segment to the ELF file, point PT_LOAD 2 at it, move the heap."""
    phoff = struct.unpack_from('<I', elf, 0x1C)[0]
    phnum = struct.unpack_from('<H', elf, 0x2C)[0]
    assert phnum == 2
    p = struct.unpack_from('<8I', elf, phoff + 32)
    assert p[0] == 1 and p[2] == BASE and p[4] == 0, 'PT_LOAD 2 is not the empty one at _end'
    elf.extend(bytes(-len(elf) % 0x80))
    off = len(elf)
    elf.extend(seg.data)
    size = len(seg.data)
    struct.pack_into('<8I', elf, phoff + 32, 1, off, BASE, BASE, size, size, 7, 0x10)
    end = (BASE + size + 0xFF) & ~0xFF
    for lui, addiu, reg in HEAP_SITES:
        patch(elf, lui, asm.assemble(lui, [('lui', reg, asm.hi(end))]))
        patch(elf, addiu, asm.assemble(addiu, [('addiu', reg, reg, asm.lo(end))]))
    for va in HEAP_WORDS:
        assert elf[va - VBASE + FOFF:va - VBASE + FOFF + 4] == struct.pack('<I', BASE)
        patch(elf, va, struct.pack('<I', end))
    return end
