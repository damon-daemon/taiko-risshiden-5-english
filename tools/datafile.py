"""TAI5DATA.DAT: 584 entries addressed by a table of contents inside the ELF.

TOC at ELF file offset 0x41F1F0 (vaddr 0x51F170): 584 x (u32 sector, u32 size, u32 0),
sectors relative to the start of TAI5DATA.DAT. Known entries:
  0 half-width font 12x24, 4bpp (low nibble first), 140 glyphs
  1 full-width font 24x24, 4bpp, 3809 glyphs in JIS order
  3 full-width font 20x20, 4bpp, 3809 glyphs
  244-577 event scripts (every other entry) and their companion data
"""
import struct

SECTOR = 2048
TOC = 0x41F1F0
COUNT = 584
SHIFT_FROM = 243            # entries from here on make room by shifting the ones after them

def toc(elf):
    return [struct.unpack_from('<II', elf, TOC + 12 * i) for i in range(COUNT)]

def entry(data, elf, i):
    sector, size = toc(elf)[i]
    return bytes(data[sector * SECTOR:sector * SECTOR + size])

def apply(data, elf, changes):
    """Write changed entries ({index: bytes}) into data (bytearray) and their TOC rows
    into elf (bytearray). An entry that outgrows the sectors up to the next entry is
    appended at the end of the file (entries >= SHIFT_FROM shift the following ones
    instead). Returns the indices that were appended."""
    moved = []
    for i, new in sorted(changes.items(), key=lambda kv: toc(elf)[kv[0]][0]):
        rows = toc(elf)
        starts = sorted(s for s, _ in rows)
        sector, size = rows[i]
        nxt = next((s for s in starts if s > sector), len(data) // SECTOR)
        need = (len(new) + SECTOR - 1) // SECTOR
        if sector + need > nxt and i >= SHIFT_FROM:
            # event scripts: open a gap instead of appending (an appended copy wastes the
            # old slot and TAI5DATA must stay small enough to grow in place on the disc)
            delta = sector + need - nxt
            data[nxt * SECTOR:nxt * SECTOR] = bytes(delta * SECTOR)
            for j, (s, n) in enumerate(rows):
                if s >= nxt:
                    struct.pack_into('<I', elf, TOC + 12 * j, s + delta)
            nxt += delta
        if sector + need > nxt:
            sector = (len(data) + SECTOR - 1) // SECTOR
            data.extend(bytes(sector * SECTOR - len(data)))
            data.extend(bytes((len(new) + SECTOR - 1) // SECTOR * SECTOR))
            moved.append(i)
        else:
            end = nxt * SECTOR
            data[sector * SECTOR:end] = bytes(end - sector * SECTOR)
        data[sector * SECTOR:sector * SECTOR + len(new)] = new
        struct.pack_into('<II', elf, TOC + 12 * i, sector, len(new))
    return moved
