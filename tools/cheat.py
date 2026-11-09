"""Two PCSX2 cheats for the extras: all cards collected (Card List) and all events seen
(Event Gallery). The main-menu cards unlock from these counts.

usage: .venv/bin/python tools/cheat.py doc                    -> docs/cheats.md
       .venv/bin/python tools/cheat.py pnach [image.iso] [dir]  -> <dir>/SLPM-66267_<CRC>.pnach

How the game stores it (Koei the Best ELF; the system data at 0x6CC6B0 is BSS, so the
addresses are the same in the Japanese and the English build):
- officer cards 0-859: one byte each at 0x6CC6BC + i; the card is owned when the byte
  equals key(i) = rand(255) + 1 with the game's LCG seeded with i (check 0x2B8790,
  LCG 0x342F10: seed = seed * 0x6C078965 + 12345, value = (seed >> 16) & 0xFFFF).
- other cards 860-1237: bits at 0x6CCA18 (check 0x30DFA0); 1200 of them are real cards.
- events 0-73: bits at 0x6CCA48 (check 0x30E080, Event Gallery).
Main-menu cards unlock from these counts (0x2C85F0): some always, others with >= 1 card,
>= 1 event, >= 50 / 600 / 700 cards.
The values are written continuously (patch=1), so the system data saved to the memory
card keeps them: a player can save once and remove the cheat.

PCSX2 names a cheat file after the serial and the CRC of the main program, which changes
with every build; the codes themselves do not, so docs/cheats.md lists them once.
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import edition, iso

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIAL = 'SLPM-66267'
OFFICERS, OFFICER_BASE = 860, 0x6CC6BC
CARD_BITS, CARD_BASE = 1238 - 860, 0x6CCA18
EVENT_BITS, EVENT_BASE = 74, 0x6CCA48
CHEATS = [
    ('All cards', 'Collects every card in the Card List (1200) and unlocks the main-menu cards '
     'that need cards. Save once in the game and it stays on the memory card.'),
    ('All events seen', 'Marks every event as seen (Event Gallery). Save once in the game and '
     'it stays on the memory card.'),
]

def key(i):
    seed = (i * 0x6C078965 + 12345) & 0xFFFFFFFFFFFFFFFF
    return ((seed >> 16) & 0xFFFF) % 255 + 1

def bits(n):
    out = bytearray((n + 7) // 8)
    for i in range(n):
        out[i >> 3] |= 1 << (i & 7)
    return bytes(out)

def blocks():
    """(cheat index, base address, bytes)."""
    assert OFFICER_BASE + OFFICERS == CARD_BASE and CARD_BASE + len(bits(CARD_BITS)) == EVENT_BASE
    return [(0, OFFICER_BASE, bytes(key(i) for i in range(OFFICERS)) + bits(CARD_BITS)),
            (1, EVENT_BASE, bits(EVENT_BITS))]

def crc(elf):
    """PCSX2's game CRC: XOR of the ELF's 32-bit words."""
    c = 0
    for (w,) in struct.iter_unpack('<I', elf[:len(elf) // 4 * 4]):
        c ^= w
    return c

def writes(cheat):
    """(address, size, value) of one cheat: words, then the leftover bytes."""
    out = []
    for c, base, data in blocks():
        if c == cheat:
            words = len(data) // 4
            out += [(base + 4 * k, 4, struct.unpack_from('<I', data, 4 * k)[0]) for k in range(words)]
            out += [(base + k, 1, data[k]) for k in range(4 * words, len(data))]
    return out

def pnach_lines(cheat):
    name, desc = CHEATS[cheat]
    return ['[%s]' % name, 'author=damon-daemon', 'description=' + desc] + \
           ['patch=1,EE,%08X,%s,%0*X' % (a, 'word' if n == 4 else 'byte', 2 * n, v) for a, n, v in writes(cheat)]

def raw_lines(cheat):
    """Unencrypted raw codes (2aaaaaaa = 32-bit write, 0aaaaaaa = 8-bit write)."""
    return ['%d%07X %08X' % (2 if n == 4 else 0, a, v) for a, n, v in writes(cheat)]

def pnach(elf_crc):
    lines = ['gametitle=Taiko Risshiden V (Koei the Best) [%s] (%08X)' % (SERIAL, elf_crc)]
    for c in range(len(CHEATS)):
        lines += [''] + pnach_lines(c)
    return '\n'.join(lines) + '\n'

DOC = """# Cheats: all cards, all events

Two optional cheats for the Koei the Best edition ({serial}), English patch or Japanese disc:

- **All cards**: collects every card in the Card List (1200: officers, titles, sights,
  techniques, battles, other) and opens the main-menu cards that unlock by number of
  cards: Music Room, Mini-Games and New Officers.
- **All events seen**: marks every event as seen, so the Event Gallery shows all its
  artwork (its main-menu card appears).

You only need them once: with a cheat on, load any save and **save again in the game**.
The unlocks are then stored on the memory card and the cheat can be turned off.
They don't change anything inside a playthrough (money, stats, items, heroes).

## PCSX2

1. Find the game's CRC: in PCSX2 it is shown in the game's Properties (Summary) and in
   the log when the game starts. For the English patch v0.12.0 it is `14E09517`; every
   release of the patch has a different CRC, the Japanese disc is `06E0A070`.
2. In PCSX2's `cheats` folder (Settings > Folders) create `{serial}_<CRC>.pnach`
   (e.g. `{serial}_14E09517.pnach`) and paste one or both blocks below into it. Other
   emulators that read `.pnach` files (tested in PCSX2 2.4 only) may want the file named
   just `<CRC>.pnach`.
3. Enable cheats for the game (PCSX2 2.x: the game's Properties > Cheats, tick the ones
   you want) and start it.

{pnach}

## Raw codes

The same writes as unencrypted raw codes (`2aaaaaaa vvvvvvvv` = 32-bit write,
`0aaaaaaa 000000vv` = 8-bit write), for cheat tools that take raw codes. A cheat device
on a real PS2 may also need a master code for this game, which is not provided.

{raw}

Generated by `tools/cheat.py doc`.
"""

def details(title, lines):
    return '<details>\n<summary>%s (%d lines)</summary>\n\n```\n%s\n```\n</details>' % (title, len(lines), '\n'.join(lines))

def doc():
    pn = '\n\n'.join(details('.pnach: ' + CHEATS[c][0], pnach_lines(c)) for c in range(len(CHEATS)))
    raw = '\n\n'.join(details(CHEATS[c][0], raw_lines(c)) for c in range(len(CHEATS)))
    return DOC.format(serial=SERIAL, pnach=pn, raw=raw)

def make(image, out_dir):
    c = crc(iso.read_file(image, edition.ELF))
    path = os.path.join(out_dir, '%s_%08X.pnach' % (SERIAL, c))
    with open(path, 'w', newline='\r\n') as f:
        f.write(pnach(c))
    return path

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'doc'
    if cmd == 'doc':
        path = os.path.join(ROOT, 'docs', 'cheats.md')
        with open(path, 'w') as f:
            f.write(doc())
        print(path)
    elif cmd == 'pnach':
        image = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'build', 'taiko_risshiden_5_en.iso')
        print(make(image, sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, 'build')))
    else:
        sys.exit(__doc__)
