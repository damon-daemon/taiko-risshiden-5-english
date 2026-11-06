"""UI strings of the ELF: the table of 1650 string pointers at 0x6503C8.

The pointers are small-data globals (the code loads them gp-relative, gp = 0x658370),
so each string is translated by writing the English into the English data segment
and pointing its word there; the Japanese stays where it is.

tl/ui.txt: one line per string, "index<TAB>English" (\\n = newline). Indexes missing
from the file keep the Japanese. A line's printf conversions (%d, %5d, %s, %u, %y ...)
must match the Japanese ones in order.

"index@site<TAB>English" gives one code site its own string (the other users of the
index keep the shared one): for a label too wide for one screen only. The site's
"lw rt, slot(gp); move a0, sN" becomes "lui rt; addiu rt", which needs a0 = sN
already: only after a call to the setter 0x3462D0 (it leaves a0 alone) made with
a0 = sN.

  ui.py export   -> script/ui.json (index, Japanese, English) for review
"""
import json, os, re, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import edition
import elfseg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'ui.txt')
SCRIPT = os.path.join(ROOT, 'script', 'ui.json')
TABLE, COUNT = 0x6503C8, 1650
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

GP, SETTER = 0x658370, 0x3462D0

def _writes_a0(w):
    """Whether an instruction writes a0 (R-type rd, or rt of an immediate op / load)."""
    op = w >> 26
    if op == 0:
        return w >> 11 & 0x1F == 4
    return (op in range(0x08, 0x10) or op in range(0x18, 0x1A) or op in range(0x20, 0x28)
            or op in (0x1E, 0x37)) and w >> 16 & 0x1F == 4

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
        k = next((k for k in range(1, 5) if w(site - 8 - 4 * k) == 0x0000202D | src << 21), None)
        assert k, 'ui %d@%x: a0 not set before the setter call' % (i, site)
        # nothing between that move and the load (the call's delay slot included) changes a0
        assert not any(_writes_a0(w(a)) for a in range(site - 8 - 4 * k + 4, site, 4)
                       if a != site - 8), 'ui %d@%x: a0 changed after the move' % (i, site)
        addr = seg.add(text.encode('ascii') + b'\0', 1)
        hi, lo = (addr + 0x8000) >> 16, addr & 0xFFFF
        elf[_f(site):_f(site) + 8] = struct.pack('<2I', 0x3C000000 | rt << 16 | hi,
                                                 0x24000000 | rt << 21 | rt << 16 | lo)

def fmts(b):
    return [m.group() for m in FMT.finditer(b)]

def _conv_error(i, jp, en):
    jf = [f.replace(b'%y', b'%d') for f in fmts(jp)]
    if [f.replace(b'%y', b'%d') for f in fmts(en)] != jf:
        return 'ui %d: conversions %s, Japanese has %s' % (i, fmts(en), fmts(jp))

def apply(elf, seg):
    tl = load_tl()
    errors, n = [], 0
    jps = {i: jp for i, p, jp in strings(elf) if p}
    for i, jp in jps.items():
        if i not in tl:
            continue
        en = tl[i].encode('ascii')
        e = _conv_error(i, jp, en)
        if e:
            errors.append(e)
            continue
        addr = seg.add(en + b'\0', 1)
        elf[_f(TABLE + 4 * i):_f(TABLE + 4 * i) + 4] = struct.pack('<I', addr)
        n += 1
    import overflow                 # buffer limits of the copies that receive these strings
    errors += overflow.check_ui(tl)
    for (i, site), text in sorted(load_tl(sites=True).items()):   # site strings: same checks
        e = _conv_error(i, jps.get(i, b''), text.encode('ascii'))
        errors += ['%s (site %x)' % (e, site)] if e else []
        errors += ['%s (site %x)' % (x, site) for x in overflow.check_ui({i: text})]
    if errors:
        raise ValueError('\n'.join(errors))
    apply_sites(elf, seg)
    apply_widths(elf)
    return n

# Label boxes sized for the Japanese that wrap the English ("Missi|on"): the width
# immediate of the rect call (0x343950: x, y, w, h) that sizes the header text object.
# (vaddr of the addiu, Japanese width, English width)
WIDTHS = [(0x407FE0, 0x28, 0x48),    # Missions chooser header (ui 580, column ~125 px)
          (0x4A0DC4, 0x28, 0x48)]    # the other Missions list header (same layout)

# Other layout immediates (vaddr, Japanese word, English word): Person Info panel, the
# Infamy gauge starts 52 px into its row (0x4E7050 draws the cells at rect.x + delta):
# "Infamy" (ui 864) is wider than the Japanese 悪名, so the gauge moves 8 px right
# (the 10 cells of 10 px still end inside the 160-px row; the Fame gauge is untouched).
OFFSETS = [(0x4E939C, 0x24020034, 0x2402003C),   # addiu v0, zero, 0x34 -> 0x3C
           # list cells with a leading icon (Bases list castles, 0x48EC80): the icon is drawn
           # at cell.x + 8 and the text at cell.x + 28, where a Latin first letter (no left
           # bearing, unlike kanji) touches the icon -> text at cell.x + 32
           (0x48ED90, 0x2445001C, 0x24450020)]   # addiu a1, v0, 0x1c -> 0x20

def apply_widths(elf):
    for va, jp, en in WIDTHS:
        w = struct.unpack_from('<I', elf, _f(va))[0]
        assert w == 0x24070000 | jp, 'ui width %x: not addiu a3,zero,%x' % (va, jp)
        struct.pack_into('<I', elf, _f(va), 0x24070000 | en)
    for va, jp, en in OFFSETS:
        assert struct.unpack_from('<I', elf, _f(va))[0] == jp, 'ui offset %x' % va
        struct.pack_into('<I', elf, _f(va), en)

def export(elf):
    tl = load_tl()
    rows = [{'id': i, 'jp': jp.decode('cp932', 'replace'), 'en': tl.get(i, '')} for i, p, jp in strings(elf)]
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    json.dump(rows, open(SCRIPT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return rows

if __name__ == '__main__':
    elf = open(os.path.join(ROOT, 'extract', edition.ELF), 'rb').read()
    if sys.argv[1:] == ['export']:
        print(len(export(elf)), 'strings ->', SCRIPT)
