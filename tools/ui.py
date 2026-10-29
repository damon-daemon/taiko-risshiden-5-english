"""UI strings of the ELF: the table of 1650 string pointers at 0x64C048.

The pointers are small-data globals (the code loads them gp-relative, gp = 0x653FF0),
so each string is translated by writing the English into the English data segment
and pointing its word there; the Japanese stays where it is.

tl/ui.txt: one line per string, "index<TAB>English" (\\n = newline). Indexes missing
from the file keep the Japanese. A line's printf conversions (%d, %5d, %s, %u, %y ...)
must match the Japanese ones in order.

"index@site<TAB>English" gives one code site its own string (the other users of the
index keep the shared one): for a label too wide for one screen only. The site's
"lw rt, slot(gp); move a0, sN" becomes "lui rt; addiu rt", which needs a0 = sN
already: only after a call to the setter 0x340E80 (it leaves a0 alone) made with
a0 = sN.

  ui.py export   -> script/ui.json (index, Japanese, English) for review
"""
import json, os, re, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import elfseg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'ui.txt')
SCRIPT = os.path.join(ROOT, 'script', 'ui.json')
TABLE, COUNT = 0x64C048, 1650
FMT = re.compile(rb'%[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]')

def _f(va):
    return va - elfseg.VBASE + elfseg.FOFF

def strings(elf):
    """[(index, pointer, bytes)] of the table (pointer 0 = no string)."""
    out = []
    for i in range(COUNT):
        p = struct.unpack_from('<I', elf, _f(TABLE + 4 * i))[0]
        b = b''
        if p:
            o = _f(p)
            b = bytes(elf[o:elf.index(b'\0', o)])
        out.append((i, p, b))
    return out

def load_tl(sites=False):
    """{index: English}, or with sites=True {(index, site vaddr): English}."""
    out = {}
    if os.path.exists(TL):
        for line in open(TL, encoding='ascii').read().splitlines():
            if line.strip():
                k, _, v = line.partition('\t')
                i, at, site = k.partition('@')
                if bool(at) == sites:
                    out[(int(i), int(site, 16)) if sites else int(i)] = v.replace('\\n', '\n')
    return out

GP, SETTER = 0x653FF0, 0x340E80

def apply_sites(elf, seg):
    """index@site lines: point one gp load of a UI string at a site-specific string."""
    w = lambda va: struct.unpack_from('<I', elf, _f(va))[0]
    for (i, site), text in sorted(load_tl(sites=True).items()):
        lw, mv = w(site), w(site + 4)
        assert lw >> 16 == 0x8F80 | (lw >> 16 & 0x1F) and lw & 0xFFFF == (TABLE + 4 * i - GP) & 0xFFFF, \
            'ui %d@%x: not a load of the slot' % (i, site)
        rt, src = lw >> 16 & 0x1F, mv >> 21 & 0x1F
        assert mv & 0xFC1FFFFF == 0x0000202D, 'ui %d@%x: no move a0 after the load' % (i, site)
        assert w(site - 8) == 0x0C000000 | SETTER >> 2, 'ui %d@%x: no setter call before' % (i, site)
        assert any(w(site - 8 - 4 * k) == 0x0000202D | src << 21 for k in range(1, 5)), \
            'ui %d@%x: a0 not set before the setter call' % (i, site)
        addr = seg.add(text.encode('ascii') + b'\0', 1)
        hi, lo = (addr + 0x8000) >> 16, addr & 0xFFFF
        elf[_f(site):_f(site) + 8] = struct.pack('<2I', 0x3C000000 | rt << 16 | hi,
                                                 0x24000000 | rt << 21 | rt << 16 | lo)

def fmts(b):
    return [m.group() for m in FMT.finditer(b)]

def apply(elf, seg):
    tl = load_tl()
    errors, n = [], 0
    for i, p, jp in strings(elf):
        if i not in tl or not p:
            continue
        en = tl[i].encode('ascii')
        jf = [f.replace(b'%y', b'%d') for f in fmts(jp)]
        if [f.replace(b'%y', b'%d') for f in fmts(en)] != jf:
            errors.append('ui %d: conversions %s, Japanese has %s' % (i, fmts(en), fmts(jp)))
            continue
        addr = seg.add(en + b'\0', 1)
        elf[_f(TABLE + 4 * i):_f(TABLE + 4 * i) + 4] = struct.pack('<I', addr)
        n += 1
    import overflow                 # buffer limits of the copies that receive these strings
    errors += overflow.check_ui(tl)
    if errors:
        raise ValueError('\n'.join(errors))
    apply_sites(elf, seg)
    return n

def export(elf):
    tl = load_tl()
    rows = [{'id': i, 'jp': jp.decode('cp932', 'replace'), 'en': tl.get(i, '')} for i, p, jp in strings(elf)]
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    json.dump(rows, open(SCRIPT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return rows

if __name__ == '__main__':
    elf = open(os.path.join(ROOT, 'extract', 'SLPM_656.74'), 'rb').read()
    if sys.argv[1:] == ['export']:
        print(len(export(elf)), 'strings ->', SCRIPT)
