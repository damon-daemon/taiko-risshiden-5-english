"""UI strings of the ELF: the table of 1650 string pointers at 0x64C048.

The pointers are small-data globals (the code loads them gp-relative, gp = 0x653FF0),
so each string is translated by writing the English into the English data segment
and pointing its word there; the Japanese stays where it is.

tl/ui.txt: one line per string, "index<TAB>English" (\\n = newline). Indexes missing
from the file keep the Japanese. A line's printf conversions (%d, %5d, %s, %u, %y ...)
must match the Japanese ones in order.

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

def load_tl():
    out = {}
    if os.path.exists(TL):
        for line in open(TL, encoding='ascii').read().splitlines():
            if line.strip():
                k, _, v = line.partition('\t')
                out[int(k)] = v.replace('\\n', '\n')
    return out

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
    if errors:
        raise ValueError('\n'.join(errors))
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
