"""Scenario titles and intro texts (new game, scenario choice).

Each scenario file (TAI5DATA 5-12 = scenarios 1-8, ILNK) starts with subfile 0:
  +0x00 5 bytes (start date: +4 = day), +0x05 title[17], +0x16 intro text[400], then data.
Scenarios 5 and 7 have an empty title field: left empty (their titles may come from
elsewhere; check in the emulator). The intro scrolls in a narrow column that wraps
mid-word, so the English is wrapped here at WIDTH px (24px font widths).

tl/scenarios.txt: "N.title<TAB>text" and "N.intro<TAB>text" (N = 1-8).
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import datafile, latinfont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'scenarios.txt')
FIRST = 5                       # TAI5DATA entry of scenario 1
TITLE, TITLE_LEN = 0x05, 17
INTRO, INTRO_LEN = 0x16, 400
WIDTH = 236

def load_tl():
    out = {}
    if os.path.exists(TL):
        for line in open(TL, encoding='ascii').read().splitlines():
            if line.strip() and not line.startswith('#'):
                k, _, v = line.partition('\t')
                n, _, field = k.partition('.')
                out.setdefault(int(n), {})[field] = v
    return out

def wrap(text, width=WIDTH):
    w = {c: g[1] for c, g in latinfont.render('large').items()}
    lines, cur = [], ''
    for word in text.split(' '):
        cand = (cur + ' ' + word) if cur else word
        if sum(w[c] for c in cand) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return '\n'.join(lines)

def apply(data, elf):
    """-> {entry: new bytes} for datafile.apply."""
    changes, errors = {}, []
    for n, fields in sorted(load_tl().items()):
        i = FIRST + n - 1
        e = bytearray(datafile.entry(data, elf, i))
        a = struct.unpack_from('<I', e, 8)[0]
        for field, (off, size) in (('title', (TITLE, TITLE_LEN)), ('intro', (INTRO, INTRO_LEN))):
            if field in fields and (field == 'intro' or e[a + off]):
                t = fields[field] if field == 'title' else wrap(fields[field])
                b = t.encode('ascii')
                if len(b) >= size:
                    errors.append('scenario %d %s: %d bytes, room %d' % (n, field, len(b), size - 1))
                    continue
                e[a + off:a + off + size] = b.ljust(size, b'\0')
        changes[i] = bytes(e)
    if errors:
        raise ValueError('\n'.join(errors))
    return changes
