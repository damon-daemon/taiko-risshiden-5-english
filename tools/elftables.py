"""Name tables in the ELF: fixed records with a name and its half-width kana reading.

English needs no reading, so a name may run on into the reading field: it may use
the bytes from the name up to the first data byte (measured from the clean ELF over
all records: any non-zero byte that is not name or reading text), minus one for the NUL.

tl/tables/<table>.txt: "index<TAB>English" lines; missing indexes keep the Japanese.

  elftables.py export   -> script/tables/<table>.json (index, Japanese, reading, English)
"""
import json, os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import elfseg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'tables')
SCRIPT = os.path.join(ROOT, 'script', 'tables')

# name: (file offset of record 0, stride, count, name offset, reading offset)
TABLES = {
    'towns':      (0x44D870, 24, 310, 1, 12),
    'sights':     (0x478F20, 40, 58, 4, 19),
    'techniques': (0x479A10, 40, 84, 0, 15),
    'battleskills': (0x47B44C, 34, 64, 4, 20),
    'cards':      (0x47BCD0, 31, 55, 0, 15),
    'provinces':  (0x47CB60, 24, 66, 0, 11),
    'items':      (0x482C60, 40, 350, 0, 15),
    'ninja':      (0x489160, 22, 30, 0, 9),
    'seas':       (0x489660, 28, 20, 0, 11),
    'offices':    (0x48A6B0, 26, 150, 0, 11),
    'schools':    (0x493010, 22, 24, 0, 9),
    'shops':      (0x493510, 18, 41, 0, 7),    # shop-name stems (UI #25 '%sya')
    'pirates':    (0x493F20, 18, 30, 0, 7),    # pirate band names (UI #24 '%s navy')
    'courtranks': (0x422930, 20, 15, 0, 9),
    'goods':      (0x423BF0, 26, 100, 0, 9),
    'titles':     (0x47A730, 32, 105, 0, 16),  # honorary titles (剣豪, 茶聖 ...) and schools
    'missions':   (0x4865F0, 28, 150, 0, 0),   # mission (主命) names per role
    'tasks':      (0x487680, 12, 18, 0, 0),    # trade/production commands
    'regions':    (0x494610, 11, 19, 0, 0),
}

def _cstr(elf, o):
    return bytes(elf[o:elf.index(b'\0', o)])

def text_end(elf, name):
    """Offset (in the record) of the first data byte after the name that is not part
    of the name or reading text (over all records): the name may run on up to there."""
    base, stride, count, no, ro = TABLES[name]
    end = stride
    for i in range(count):
        o = base + i * stride
        text = set(range(no, no + len(_cstr(elf, o + no)) + 1)) | set(range(ro, ro + len(_cstr(elf, o + ro)) + 1))
        nz = next((k for k in range(no, stride) if elf[o + k] and k not in text), stride)
        end = min(end, nz)
    return end

def records(elf, name):
    base, stride, count, no, ro = TABLES[name]
    return [(i, _cstr(elf, base + i * stride + no), _cstr(elf, base + i * stride + ro)) for i in range(count)]

def load_tl(name):
    path = os.path.join(TL, name + '.txt')
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding='ascii').read().splitlines():
            if line.strip():
                k, _, v = line.partition('\t')
                out[int(k)] = v
    return out

def apply(elf, clean_elf):
    """Write the English of every table into elf; returns {table: count}."""
    done, errors = {}, []
    for name, (base, stride, count, no, ro) in TABLES.items():
        tl = load_tl(name)
        end = text_end(clean_elf, name)
        room = end - no - 1
        for i, en in tl.items():
            b = en.encode('ascii')
            if len(b) > room:
                errors.append('%s %d: %r is %d bytes, room %d' % (name, i, en, len(b), room))
                continue
            o = base + i * stride + no
            elf[o:o + room + 1] = b + bytes(room + 1 - len(b))
        done[name] = len(tl)
        import overflow             # buffer limits of the copies that receive these names
        errors += overflow.check_table(name, tl)
    if errors:
        raise ValueError('\n'.join(errors))
    return done

# Town reading (0x27FAA0: kana reading of town a1 + "じょう"/"のまち"... suffix, shown under
# castle names and used by 8 callers). The English name runs on into the reading field,
# so the reading is garbage: the function returns an empty string instead.
TOWN_READING = 0x27FAA0

def apply_code(elf, seg):
    import asm
    empty = seg.add(b'\0', 1)
    o = TOWN_READING - elfseg.VBASE + elfseg.FOFF
    assert elf[o:o + 4] == bytes.fromhex('e0ffbd27'), 'town reading function moved'   # addiu sp, sp, -0x20
    elfseg.patch(elf, TOWN_READING, asm.assemble(TOWN_READING, [
        ('lui', 'v0', asm.hi(empty)), ('jr', 'ra'), ('addiu', 'v0', 'v0', asm.lo(empty))]))

def export(elf):
    os.makedirs(SCRIPT, exist_ok=True)
    for name in TABLES:
        tl = load_tl(name)
        rows = [{'id': i, 'jp': jp.decode('cp932', 'replace'), 'reading': rd.decode('cp932', 'replace'),
                 'en': tl.get(i, '')} for i, jp, rd in records(elf, name)]
        json.dump({'room': text_end(elf, name) - TABLES[name][3] - 1, 'rows': rows},
                  open(os.path.join(SCRIPT, name + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)

if __name__ == '__main__':
    elf = open(os.path.join(ROOT, 'extract', 'SLPM_656.74'), 'rb').read()
    if sys.argv[1:] == ['export']:
        export(elf)
        for name in TABLES:
            print(name, 'room', text_end(elf, name) - TABLES[name][3] - 1)
