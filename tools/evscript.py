"""Event scripts (TAI5DATA entries 244, 246, ... 574): parse <-> rebuild.

Entry: u8 0, u8 id, u8 f0/f1/f2.., u8 group | u32 n | u32 off[n+1] (off[n] = size) | scripts.
The game reads the whole entry into the heap (0x4675A0) and copies script k into a
buffer of its own size (0x234B20), so scripts may grow.

Script bytecode (interpreter 0x23B780, handlers in the jump table 0x5487C0): a list of
instructions ended by a 00 word. The first byte is the opcode; most instructions are 4
bytes. Block instructions run a nested list (their body) and store their total length
(header + body + the body's 00 word) in the header, so rebuilding recomputes it:

  01 02 0E 0F   len = (w >> 8) * 4      body at +4
  04 05         len = (u16@2 >> 3) * 4  body at +4      (case / else-case; 13 bits)
  06            len = (w >> 9) * 4      body at +4 (+ an expression term if b1 & 1): switch
  08            len = u16@2 * 4         body at +4: switch
  inside a 06/08 body only 07 (len (w>>9)*4, body +4 [+ term if b1 & 1]) and 09
  (len (u16@2>>3)*4, body +4) are cases; other words there are skipped 4 at a time.
Fixed-size data with a length field: 0A 0B (u16@2>>3)*4, 0C 0D (u16@2 & 0x1FF)*4 (unused),
16-19 u16@4*4, 1C (w>>11)*4. Op 10 = assignment: header + 1 expression term (2 if
b1 & 3 == 3). Expression terms (0x2470A0) are 4 bytes, plus one nested term for the
(type, sub) pairs in NEST (sub = (u16 >> 7) & 0xFF).
Strings (NUL-terminated, padded with zeros to 4 bytes, each):
  11 12 13 1E 4A  one string after the 4-byte header (11/12/13 = dialogue/narration)
  15              b1 strings (choice menu)
  5A              family, given, text (dialogue with a temporary speaker name)
  3C              family, given, family reading, given reading (set a person's name)
  42              one string after a 12-byte header
Opcodes >= 0x5E (and 07/09/20 outside a switch) are 4-byte no-ops.

usage: evscript.py check            # parse + rebuild every entry (identity)
       evscript.py dump ENTRY [K]   # list the strings of an entry (script K)
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))

FIRST, LAST = 244, 574          # script entries: FIRST, FIRST + 2, ... LAST

NEST = {3: {0x92}, 5: {8, 9}, 6: {0xC, 0xD, 0xE, 0xF, 0x10, 0x12}, 0xC: {0xE, 0xF},
        0xD: {1, 2}, 0x11: {5, 6, 7, 8, 0x17}, 0x12: {5, 6, 7, 8, 0xC, 0xD, 0xE},
        0x13: {4, 5, 6, 7}, 0x14: {5, 6, 7, 8}, 0x15: {5, 6, 7, 8}, 0x17: {1, 2}}
CONST8 = {0x27, 0x36, 0x38, 0x40, 0x49, 0x4D, 0x5B}
CONST = {**{o: 8 for o in CONST8}, 0x41: 12, 0x45: 12, 0x33: 0x24, 0x32: 0x30, 0x34: 0x30}
TEXT_OPS = {0x11, 0x12, 0x13, 0x1E, 0x4A}
STR_OPS = {0x15: None, 0x5A: 3, 0x3C: 4, 0x42: 1}     # count (None = b1)
STR_HEAD = {0x42: 12}
BLOCK_OPS = {1, 2, 4, 5, 6, 8, 0xE, 0xF}

def u16(b, p): return struct.unpack_from('<H', b, p)[0]
def u32(b, p): return struct.unpack_from('<I', b, p)[0]

class ParseError(Exception):
    pass

def term_len(b, p):
    t, sub = b[p] & 0x7F, (u16(b, p) >> 7) & 0xFF
    return 4 + term_len(b, p + 4) if sub in NEST.get(t, ()) else 4

class Ins:
    """op; head = bytes before the body / strings; body = [Ins] or None (block);
    strs = [bytes] or None; switch = body is a switch body (cases only)."""
    __slots__ = ('op', 'head', 'body', 'strs', 'switch')
    def __init__(self, op, head, body=None, strs=None, switch=False):
        self.op, self.head, self.body, self.strs, self.switch = op, head, body, strs, switch

def _strings(b, p, count):
    out = []
    for _ in range(count):
        e = b.index(0, p)
        out.append(b[p:e])
        n = (e - p + 1 + 3) & ~3
        if any(b[e:p + n]):
            raise ParseError('non-zero string padding at %x' % e)
        p += n
    return out, p

def _ins_len(b, p, in_switch):
    """-> (length, body offset or None)"""
    op, w, h = b[p], u32(b, p), u16(b, p + 2)
    if in_switch:
        if op == 7:
            return (w >> 9) << 2, p + 4 + (term_len(b, p + 4) if b[p + 1] & 1 else 0)
        if op == 9:
            return (h >> 3) << 2, p + 4
        return 4, None
    if op in (1, 2, 0xE, 0xF):
        return (w >> 8) << 2, p + 4
    if op in (4, 5):
        return (h >> 3) << 2, p + 4
    if op == 6:
        return (w >> 9) << 2, p + 4 + (term_len(b, p + 4) if b[p + 1] & 1 else 0)
    if op == 8:
        return h << 2, p + 4
    if op in (0xA, 0xB):
        return (h >> 3) << 2, None
    if op in (0xC, 0xD):
        raise ParseError('if/while op %02x (unused in the game data) at %x' % (op, p))
    if 0x16 <= op <= 0x19:
        return u16(b, p + 4) << 2, None
    if op == 0x1C:
        return (w >> 11) << 2, None
    if op == 0x10:
        q = p + 4 + term_len(b, p + 4)
        if b[p + 1] & 3 == 3:
            q += term_len(b, q)
        return q - p, None
    return CONST.get(op, 4), None

class Block(list):
    """[Ins] + end = the closing word (opcode byte 00; the other 3 bytes are ignored by
    the game but kept)."""
    end = bytes(4)

def parse_list(b, p, end, in_switch=False):
    """-> (Block, offset after the closing 00 word)"""
    out = Block()
    while True:
        if p + 4 > end:
            raise ParseError('block overruns its end %x' % end)
        op = b[p]
        if op == 0:
            out.end = b[p:p + 4]
            return out, p + 4
        if not in_switch and (op in TEXT_OPS or op in STR_OPS):
            head = b[p:p + STR_HEAD.get(op, 4)]
            count = 1 if op in TEXT_OPS else (STR_OPS[op] or b[p + 1])
            strs, q = _strings(b, p + len(head), count)
            out.append(Ins(op, head, strs=strs))
            p = q
            continue
        n, body = _ins_len(b, p, in_switch)
        if n < 4 or p + n > end:
            raise ParseError('bad length %d of op %02x at %x' % (n, op, p))
        if body is None:
            out.append(Ins(op, b[p:p + n]))
        else:
            sw = op in (6, 8) and not in_switch
            kids, q = parse_list(b, body, p + n, sw)
            if q != p + n:
                raise ParseError('block %02x at %x ends at %x, not %x' % (op, p, q, p + n))
            out.append(Ins(op, b[p:body], body=kids, switch=sw))
        p += n

def build_list(items, in_switch=False):
    out = bytearray()
    for it in items:
        if it.strs is not None:
            out += it.head
            for s in it.strs:
                out += s + bytes(((len(s) + 1 + 3) & ~3) - len(s))
        elif it.body is None:
            out += it.head
        else:
            body = build_list(it.body, it.switch)
            n = len(it.head) + len(body)
            head = bytearray(it.head)
            w = u32(head, 0)
            if in_switch and it.op == 7 or not in_switch and it.op == 6:
                if n >> 2 >= 1 << 23: raise ParseError('block too long')
                w = (w & 0x1FF) | (n >> 2) << 9
            elif in_switch and it.op == 9 or not in_switch and it.op in (4, 5):
                if n >> 2 >= 1 << 13:
                    raise ParseError('case block of %d bytes > 32 KB' % n)
                w = (w & 0x7FFFF) | (n >> 2) << 19
            elif it.op == 8:
                if n >> 2 >= 1 << 16: raise ParseError('block too long')
                w = (w & 0xFFFF) | (n >> 2) << 16
            else:
                if n >> 2 >= 1 << 24: raise ParseError('block too long')
                w = (w & 0xFF) | (n >> 2) << 8
            struct.pack_into('<I', head, 0, w)
            out += head + body
    return bytes(out + getattr(items, 'end', bytes(4)))

class Entry:
    """head = bytes before off[0] other than n/offsets (8-byte header + padding);
    scripts = [(items, tail)] with tail = zero bytes after the script's 00 word."""
    def __init__(self, data):
        n = u32(data, 4)
        off = struct.unpack_from('<%dI' % (n + 1), data, 8)
        if off[n] != len(data):
            raise ParseError('offset table does not end at the entry size')
        self.head = data[:8]
        self.pad = data[8 + 4 * (n + 1):off[0]]
        self.scripts = []
        for k in range(n):
            items, q = parse_list(data, off[k], off[k + 1])
            tail = data[q:off[k + 1]]
            if any(tail):
                raise ParseError('script %d: data after the end word' % k)
            self.scripts.append((items, len(tail)))

    def build(self):
        n = len(self.scripts)
        bodies = [build_list(items) + bytes(tail) for items, tail in self.scripts]
        off = [8 + 4 * (n + 1) + len(self.pad)]
        for s in bodies:
            off.append(off[-1] + len(s))
        return (self.head + struct.pack('<%dI' % (n + 1), *off) + self.pad + b''.join(bodies))

def is_script(data):
    if len(data) < 12 or data[0] != 0:
        return False
    n = u32(data, 4)
    return 0 < n < 5000 and 8 + 4 * (n + 1) <= len(data) and u32(data, 8 + 4 * n) == len(data)

def entries():
    return range(FIRST, LAST + 1, 2)

def strings(items, path=()):
    """Yield (path, ins, index) for every string, in order (path = indices into the tree)."""
    for i, it in enumerate(items):
        if it.strs is not None:
            for j in range(len(it.strs)):
                yield path + (i,), it, j
        elif it.body is not None:
            yield from strings(it.body, path + (i,))

def _open():
    import datafile
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    elf = open(os.path.join(root, 'extract', 'SLPM_656.74'), 'rb').read()
    f = open(os.path.join(root, 'extract', 'TAI5DATA.DAT'), 'rb')
    rows = datafile.toc(elf)
    def get(i):
        s, z = rows[i]
        f.seek(s * 2048)
        return f.read(z)
    return get

def main():
    import text
    get = _open()
    if sys.argv[1] == 'check':
        total = scripts = nstr = 0
        for i in entries():
            data = get(i)
            if not is_script(data):
                print('entry %d: not a script entry' % i)
                continue
            e = Entry(data)
            if e.build() != data:
                raise SystemExit('entry %d: rebuild differs' % i)
            total += 1
            scripts += len(e.scripts)
            nstr += sum(1 for items, _ in e.scripts for _ in strings(items))
        print('%d entries, %d scripts, %d strings: identical' % (total, scripts, nstr))
    elif sys.argv[1] == 'dump':
        e = Entry(get(int(sys.argv[2])))
        ks = [int(sys.argv[3])] if len(sys.argv) > 3 else range(len(e.scripts))
        for k in ks:
            for path, it, j in strings(e.scripts[k][0]):
                print('%d %s %02X.%d %s' % (k, '.'.join(map(str, path)), it.op, j,
                                           text.decode(it.strs[j]).replace('\n', '\\n')))

if __name__ == '__main__':
    main()
