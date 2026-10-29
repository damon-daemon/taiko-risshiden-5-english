"""Loose strings of the ELF data (menu labels, battle names, memory card messages ...)
that are neither in the UI pointer table (ui.py) nor in a record table (elftables.py).

tl/elfstr.txt: "vaddr<TAB>English" lines (vaddr in hex, \\n = newline; UTF-8, ASCII text
plus the controller button marks ①②④⑤⑥ of the font). English that fits
the string's slot (its bytes plus the zero padding up to the next non-zero byte) is
written in place. Longer English goes into the English data segment and every
reference is repointed:
  - 32-bit data words equal to the address inside a reviewed pointer table
    (POINTER_TABLES). Any other word with that value is an error until it has been
    checked: numbers can look like addresses (0x5258C4, an edge of the road graph
    u16 0 | u16 0x58, equals the address of 兵法書; repointing it broke long-distance
    travel, issue #7),
  - lui/addiu (or load/store) pairs in the code that build the address, when that lui
    has no other user (else the pair cannot be changed alone: shorten the English).
A string with no reference found must fit its slot. printf conversions must match.

  elfstr.py export   -> script/elfstr.json (vaddr, room, references, Japanese, English)
"""
import collections, json, os, re, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, elfseg, elftables, names, ui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'elfstr.txt')
SCRIPT = os.path.join(ROOT, 'script', 'elfstr.json')
CODE_END = 0x51CF80                 # vaddr where the data starts (file 0x41D000)
DATA_LO, DATA_HI = 0x51CF80, 0x5B1F80
# [lo, hi) vaddr ranges of data checked to be pointer tables (string pointers bounded by
# zeros or other fields); 0x64DBA0 is a single pointer (save data title 太閤立志伝Ｖ)
POINTER_TABLES = [(0x51D1A0, 0x51D1C8), (0x51EE40, 0x51EF84), (0x5213D8, 0x521418),
                  (0x521C00, 0x521D58), (0x521FAC, 0x522034), (0x5223A0, 0x5223B0),
                  (0x5224B0, 0x5224C4), (0x5260C4, 0x5260D4), (0x527FF8, 0x528034),
                  (0x528DB0, 0x528DB8), (0x52C848, 0x52C858), (0x52D3E0, 0x52D3F0),
                  (0x54A360, 0x54A3B4), (0x54A4F0, 0x54A510), (0x64DAE0, 0x64DAE8),
                  (0x64DBA0, 0x64DBA4), (0x64DCE4, 0x64DD98)]
# words that equal a string address but are numbers: road graph edges 0x525840
# (6-byte records), a field of the records at 0x57A1F4
NOT_POINTERS = {0x5258C4, 0x57A224}
FMT = ui.FMT

def _f(va):
    return va - elfseg.VBASE + elfseg.FOFF

def _w(elf, va):
    return struct.unpack_from('<I', elf, _f(va))[0]

def _s16(x):
    return x - 0x10000 if x & 0x8000 else x

def _writes(w):
    """Register written by instruction w (None if none / unknown)."""
    op = w >> 26
    if op in (0, 0x1C):
        return (w >> 11) & 31
    if op in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x1A, 0x1B, 0x1E, 0x37) or 0x20 <= op <= 0x27:
        return (w >> 16) & 31
    if op == 0x03:
        return 31
    return None

def _is_jump(w):
    op = w >> 26
    return op in (2, 3) or (op == 0 and (w & 0x3F) in (8, 9))

def code_pairs(elf):
    """({target: [(lui va, user va)]}, {lui va: number of users}) for the code.
    A lui register is followed until it is overwritten or a jump's delay slot ends;
    any other read of it counts as a user too (so such a lui is never changed)."""
    pairs, users = collections.defaultdict(list), collections.Counter()
    lui, end_after = {}, None
    for va in range(elfseg.VBASE, CODE_END, 4):
        w = _w(elf, va)
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:
            lui[rt] = (imm << 16, va)
        else:
            if rs in lui and (op in (0x09, 0x0D) or 0x20 <= op <= 0x3F):
                t = (lui[rs][0] + (imm if op == 0x0D else _s16(imm))) & 0xFFFFFFFF
                pairs[t].append((lui[rs][1], va))
                users[lui[rs][1]] += 1
                if 0x28 <= op <= 0x3F and rt in lui and rt != rs:     # stores the lui value
                    users[lui[rt][1]] += 2
            else:
                for r in {rs, rt}:
                    if r in lui:
                        users[lui[r][1]] += 2
            wr = _writes(w)
            if wr in lui:
                del lui[wr]
        if end_after is not None and va >= end_after:
            lui.clear()
            end_after = None
        if _is_jump(w):
            end_after = va + 4
    return pairs, users

def data_words(elf):
    """{value: [vaddr]} of the aligned words of the data (pointer candidates)."""
    out = collections.defaultdict(list)
    end = elfseg.VBASE + struct.unpack_from('<I', elf, struct.unpack_from('<I', elf, 0x1C)[0] + 16)[0]
    for va in range(CODE_END, end - 3, 4):
        v = _w(elf, va)
        if DATA_LO <= v < DATA_HI:
            out[v].append(va)
    return out

def in_pointer_table(va):
    return any(lo <= va < hi for lo, hi in POINTER_TABLES)

def slot(elf, va):
    """(Japanese bytes, room) of the string at va: room = bytes up to the next 8-byte
    boundary after its NUL (the compiler's padding; zeros beyond it may be constants),
    and never past the next non-zero byte, minus one for the NUL."""
    o = _f(va)
    assert elf[o - 1] == 0, '%x is not the start of a string' % va
    e = elf.index(b'\0', o)
    k = e
    while k < len(elf) and elf[k] == 0:
        k += 1
    end = min(k, (va + (e - o) + 1 + 7) // 8 * 8 - va + o)
    return bytes(elf[o:e]), end - o - 1

def load_tl():
    out = {}
    if os.path.exists(TL):
        for line in open(TL, encoding='utf-8').read().splitlines():
            if line.strip() and not line.startswith('#'):
                k, _, v = line.partition('\t')
                out[int(k, 16)] = v.replace('\\n', '\n')
    return out

def apply(elf, clean_elf, seg):
    tl = load_tl()
    if not tl:
        return 0, 0
    pairs, users = code_pairs(clean_elf)
    words = data_words(clean_elf)
    errors, moved = [], 0
    for va, en in sorted(tl.items()):
        jp, room = slot(clean_elf, va)
        b = en.encode('cp932')         # ASCII, plus the button marks ①②④⑤⑥
        if [f.replace(b'%y', b'%d') for f in FMT.findall(b)] != [f.replace(b'%y', b'%d') for f in FMT.findall(jp)]:
            errors.append('elfstr %x: conversions %s, Japanese has %s' % (va, FMT.findall(b), FMT.findall(jp)))
            continue
        if len(b) <= room:
            o = _f(va)
            elf[o:o + room + 1] = b + bytes(room + 1 - len(b))
            continue
        code, data = pairs.get(va, []), [a for a in words.get(va, []) if a not in NOT_POINTERS]
        unknown = [a for a in data if not in_pointer_table(a)]
        if unknown:
            errors.append('elfstr %x: %d bytes, room %d; data words %s equal its address outside '
                          'POINTER_TABLES: check whether they are pointers (add the table) or '
                          'numbers (NOT_POINTERS)' % (va, len(b), room, ' '.join('%x' % a for a in unknown)))
            continue
        if not code and not data:
            errors.append('elfstr %x: %d bytes, room %d and no reference to repoint' % (va, len(b), room))
            continue
        shared = [l for l, u in code if users[l] != 1]
        if shared:
            errors.append('elfstr %x: %d bytes, room %d; lui at %s has other users'
                          % (va, len(b), room, ' '.join('%x' % l for l in shared)))
            continue
        new = seg.add(b + b'\0', 1)
        for at in data:
            elfseg.patch(elf, at, struct.pack('<I', new))
        for l, u in code:
            lw, uw = _w(clean_elf, l), _w(clean_elf, u)
            assert (_w(elf, l), _w(elf, u)) == (lw, uw), 'elfstr %x: code at %x/%x already patched' % (va, l, u)
            hi = (new + 0x8000) >> 16
            lo = (new - (hi << 16)) & 0xFFFF
            if uw >> 26 == 0x0D:                                  # ori: unsigned low half
                hi, lo = new >> 16, new & 0xFFFF
            elfseg.patch(elf, l, struct.pack('<I', (lw & 0xFFFF0000) | hi))
            elfseg.patch(elf, u, struct.pack('<I', (uw & 0xFFFF0000) | lo))
        moved += 1
    import overflow                 # buffer limits of the copies that receive these strings
    errors += overflow.check_elfstr(tl, lambda va: slot(clean_elf, va)[0])
    if errors:
        raise ValueError('\n'.join(errors))
    return len(tl), moved

# ---------------------------------------------------------------- survey

def _is_text(b):
    i, jp = 0, 0
    while i < len(b):
        c = b[i]
        if 0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC:
            if i + 1 >= len(b) or not (0x40 <= b[i + 1] <= 0xFC and b[i + 1] != 0x7F):
                return False
            jp += 1
            i += 2
            continue
        if 0xA1 <= c <= 0xDF:
            jp += 1
        elif not (0x20 <= c < 0x7F or c in (0x0A, 0x1B)):
            return False
        i += 1
    return jp > 0

def candidates(elf):
    """[(vaddr, Japanese)] of the Shift-JIS strings in the data that the other tools
    do not cover (at least two full-width characters, mostly Japanese)."""
    covered = []
    for i, p, b in ui.strings(elf):
        if p:
            covered.append((_f(p), _f(p) + len(b) + 1))
    for base, st, cnt, no, ro in elftables.TABLES.values():
        covered.append((base, base + st * cnt))
    covered.append((names.OFFICERS, names.OFFICERS + names.OFF_REC * names.OFF_COUNT))
    covered.append((names.POOL, names.POOL + names.POOL_REC * names.POOL_COUNT))
    out, o, hi = [], _f(DATA_LO), _f(DATA_HI)
    while o < hi:
        if elf[o] == 0:
            o += 1
            continue
        e = elf.index(b'\0', o)
        b = bytes(elf[o:e])
        if _is_text(b) and not any(a <= o < z for a, z in covered):
            t = b.decode('cp932', 'replace')
            fw = len(re.findall('[぀-ヿ一-鿿！-～　-〿]', t))
            if '\ufffd' not in t and (fw >= 2 and fw * 2 >= len(t) * 0.6 or fw >= 1 and FMT.search(b) and len(b) <= 16):
                out.append((o - elfseg.FOFF + elfseg.VBASE, b))
        o = e + 1
    return out

def export(elf):
    tl = load_tl()
    pairs, users = code_pairs(elf)
    words = data_words(elf)
    rows = []
    for va, b in candidates(elf):
        jp, room = slot(elf, va)
        code = pairs.get(va, [])
        rows.append({'va': '%x' % va, 'room': room, 'code': len(code),
                     'shared': sum(users[l] != 1 for l, u in code), 'data': len(words.get(va, [])),
                     'jp': jp.decode('cp932', 'replace'), 'en': tl.get(va, '')})
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    json.dump(rows, open(SCRIPT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return rows

if __name__ == '__main__':
    elf = open(os.path.join(ROOT, 'extract', 'SLPM_656.74'), 'rb').read()
    if sys.argv[1:] == ['export']:
        print(len(export(elf)), 'strings ->', SCRIPT)
