"""Address map: original edition (SLPM-65674) -> Koei the Best (SLPM-66267).

Best's ELF is a full relink (code and data moved, some functions recompiled), so the
map is built from evidence, not a fixed delta:
  code  functions (split after `jr ra` + delay slot) are hashed with address fields
        masked (j/jal targets, lui and non-sp immediates) and aligned in order; a matched
        function maps word for word ('exact'); paired but changed functions are aligned
        instruction by instruction ('fuzzy': registers may differ, check by hand).
  data  unique 32-byte windows (words that look like pointers masked) are anchors; an
        address between two anchors with the same delta maps with that delta.
  bss   lui/lo address pairs and data pointer words of matched code/data vote for a
        delta per target address; an address takes the delta of the nearest voted
        address at or below it (same symbol region).

usage: edmap.py VADDR...        print the mapping of each address
"""
import bisect, collections, difflib, hashlib, os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE, FOFF = 0x100000, 0x80
A_ELF = os.path.join(ROOT, 'extract', 'regular', 'SLPM_656.74')
B_ELF = os.path.join(ROOT, 'extract', 'SLPM_662.67')
A_TEXT_END = 0x41D000 - FOFF + BASE
B_TEXT_END = 0x425D80 - FOFF + BASE
BRANCH = {1, 4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17}

def words(elf, lo, hi):
    return list(struct.unpack_from('<%dI' % ((hi - lo) // 4), elf, lo - BASE + FOFF))

def norm(w):
    op, rs = w >> 26, (w >> 21) & 31
    if op in (2, 3):
        return op << 26
    if op in (0, 0x10, 0x11, 0x12, 0x1C) or op in BRANCH or rs == 29:
        return w
    return w & 0xFFFF0000

def functions(ws):
    out, start = [], 0
    for i, w in enumerate(ws):
        if w == 0x03E00008 and i + 1 < len(ws):
            out.append((start, i + 2))
            start = i + 2
    out.append((start, len(ws)))
    return out

def units(ws):
    """Code units: split after `jr ra` + delay slot and at every j/jal target."""
    cuts = {0, len(ws)}
    for i, w in enumerate(ws):
        if w == 0x03E00008 and i + 2 <= len(ws):
            cuts.add(i + 2)
        if w >> 26 in (2, 3):
            t = (((w & 0x3FFFFFF) << 2) - BASE) // 4
            if 0 <= t < len(ws):
                cuts.add(t)
    c = sorted(cuts)
    return list(zip(c, c[1:]))

def is_ptr(w):
    return 0x100000 <= w < 0x2000000

class Map:
    def __init__(self):
        self.A = open(A_ELF, 'rb').read()
        self.B = open(B_ELF, 'rb').read()
        self.a_file_end = BASE + len(self.A) - FOFF
        self.b_file_end = BASE + len(self.B) - FOFF
        self.code = {}          # A word va -> (B va, 'exact'|'fuzzy')
        self._code()
        self._data()
        self._bss()

    # ---- code
    def _code(self):
        wa = words(self.A, BASE, A_TEXT_END)
        wb = words(self.B, BASE, B_TEXT_END)
        self.wa, self.wb = wa, wb
        fa, fb = units(wa), units(wb)
        na_, nb_ = [norm(w) for w in wa], [norm(w) for w in wb]
        key = lambda ns, f: hashlib.md5(struct.pack('<%dI' % (f[1] - f[0]), *ns[f[0]:f[1]])).digest()
        ha = [key(na_, f) for f in fa]
        hb = [key(nb_, f) for f in fb]
        done_a, done_b = set(), set()
        def exact(i, j):
            fi, fj = fa[i], fb[j]
            for k in range(fi[1] - fi[0]):
                self.code[BASE + 4 * (fi[0] + k)] = (BASE + 4 * (fj[0] + k), 'exact')
            done_a.add(i); done_b.add(j)
        # 1. in-order alignment of identical units, then unique identical units anywhere
        sm = difflib.SequenceMatcher(None, ha, hb, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    exact(i, j)
        ca = collections.Counter(ha[i] for i in range(len(fa)) if i not in done_a)
        cb = collections.Counter(hb[j] for j in range(len(fb)) if j not in done_b)
        posb = {hb[j]: j for j in range(len(fb)) if j not in done_b}
        for i in range(len(fa)):
            if i not in done_a and ca[ha[i]] == 1 and cb[ha[i]] == 1:
                exact(i, posb[ha[i]])
        # 2. call graph: a mapped `jal T` pairs the units starting at T in A and in B;
        #    paired units that differ are aligned instruction by instruction
        start_a = {BASE + 4 * f[0]: i for i, f in enumerate(fa)}
        start_b = {BASE + 4 * f[0]: j for j, f in enumerate(fb)}
        self.unit_ratio = {}
        while True:
            pairs = set()
            for va, (vb, _) in list(self.code.items()):
                w = wa[(va - BASE) // 4]
                if w >> 26 not in (2, 3):
                    continue
                v = wb[(vb - BASE) // 4]
                if v >> 26 != w >> 26:
                    continue
                ta, tb = (w & 0x3FFFFFF) << 2, (v & 0x3FFFFFF) << 2
                if ta in start_a and tb in start_b and start_a[ta] not in done_a and start_b[tb] not in done_b:
                    pairs.add((start_a[ta], start_b[tb]))
            if not pairs:
                break
            for i, j in sorted(pairs):
                if i in done_a or j in done_b:
                    continue
                done_a.add(i); done_b.add(j)
                (a0, a1), (b0, b1) = fa[i], fb[j]
                s2 = difflib.SequenceMatcher(None, na_[a0:a1], nb_[b0:b1], autojunk=False)
                self.unit_ratio[BASE + 4 * a0] = s2.ratio()
                for t, x1, x2, y1, y2 in s2.get_opcodes():
                    if t == 'equal':
                        for k in range(x2 - x1):
                            self.code[BASE + 4 * (a0 + x1 + k)] = (BASE + 4 * (b0 + y1 + k), 'fuzzy')
        self.unmatched_units = [BASE + 4 * fa[i][0] for i in range(len(fa)) if i not in done_a]

    # ---- initialised data
    def _data(self):
        lo_a, lo_b = A_TEXT_END, B_TEXT_END
        wa = words(self.A, lo_a, self.a_file_end & ~3)
        wb = words(self.B, lo_b, self.b_file_end & ~3)
        N = 8
        def keys(ws):
            nw = [0xFFFFFFFF if is_ptr(w) else w for w in ws]
            d = collections.defaultdict(list)
            for i in range(len(nw) - N):
                if any(nw[i:i + N]):
                    d[tuple(nw[i:i + N])].append(i)
            return d
        ka, kb = keys(wa), keys(wb)
        anchors = []
        for k, ia in ka.items():
            ib = kb.get(k)
            if len(ia) == 1 and ib and len(ib) == 1:
                anchors.append((lo_a + 4 * ia[0], lo_b + 4 * ib[0] - (lo_a + 4 * ia[0])))
        anchors.sort()
        self.data_anchor_va = [a for a, _ in anchors]
        self.data_anchor_d = [d for _, d in anchors]

    def _data_map(self, va):
        i = bisect.bisect_right(self.data_anchor_va, va) - 1
        if i < 0:
            return None
        d = self.data_anchor_d[i]
        nxt = self.data_anchor_d[i + 1] if i + 1 < len(self.data_anchor_d) else d
        # anchors cover va..va+31: inside one, or between two agreeing ones
        if va < self.data_anchor_va[i] + 32 or nxt == d:
            return va + d, 'data'
        return va + d, 'data?'

    # ---- bss (and a cross-check for data): votes from matched references
    def _bss(self):
        votes = collections.defaultdict(collections.Counter)
        def lui_pairs(ws, base):
            out, lui = {}, {}
            for i, w in enumerate(ws):
                op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
                va = base + 4 * i
                if op == 0x0F:
                    lui[rt] = (imm << 16, va)
                elif op in (0x09, 0x0D, 0x23, 0x2B, 0x21, 0x25, 0x24, 0x20, 0x29, 0x28,
                            0x37, 0x3F, 0x31, 0x39, 0x1E, 0x1F) and rs in lui:
                    hi = lui[rs][0]
                    t = hi | imm if op == 0x0D else (hi + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                    out[va] = t
            return out
        ra = lui_pairs(self.wa, BASE)
        rb = lui_pairs(self.wb, BASE)
        for va, t in ra.items():
            m = self.code.get(va)
            if m and m[0] in rb:
                votes[t][rb[m[0]] - t] += 1
        # pointer words inside anchored data
        for i, a in enumerate(self.data_anchor_va):
            d = self.data_anchor_d[i]
            for o in range(0, 32, 4):
                wa = struct.unpack_from('<I', self.A, a + o - BASE + FOFF)[0]
                if is_ptr(wa):
                    wb = struct.unpack_from('<I', self.B, a + d + o - BASE + FOFF)[0]
                    if is_ptr(wb):
                        votes[wa][wb - wa] += 1
        self.votes = votes
        self.vote_va = sorted(votes)
        self.vote_d = [votes[t].most_common(1)[0][0] for t in self.vote_va]
        tgt = sorted(t for t in votes if t >= self.a_file_end)
        self.bss_va = tgt
        self.bss_d = [votes[t].most_common(1)[0][0] for t in tgt]

    def _bss_map(self, va):
        if va in self.votes:
            d, n = self.votes[va].most_common(1)[0]
            return va + d, 'bss=%d' % n
        i = bisect.bisect_right(self.bss_va, va) - 1
        if i < 0:
            return None
        return va + self.bss_d[i], 'bss~0x%X' % self.bss_va[i]

    def map(self, va):
        if va < A_TEXT_END:
            return self.code.get(va & ~3, (None, 'code-unmapped'))
        if va < self.a_file_end:
            if va in self.votes:            # referenced exactly by matched code/data
                d, n = self.votes[va].most_common(1)[0]
                return va + d, 'data-ref=%d' % n
            i = bisect.bisect_right(self.data_anchor_va, va) - 1
            if i >= 0 and va < self.data_anchor_va[i] + 32:
                return va + self.data_anchor_d[i], 'data'
            # nearest evidence below: an anchor or a referenced address
            j = bisect.bisect_right(self.vote_va, va) - 1
            ea = self.data_anchor_va[i] if i >= 0 else -1
            ev = self.vote_va[j] if j >= 0 else -1
            if ev > ea:
                return va + self.vote_d[j], 'data~ref 0x%X' % ev
            if i >= 0:
                return va + self.data_anchor_d[i], 'data~anchor 0x%X' % ea
            return None, 'data-unmapped'
        return self._bss_map(va) or (None, 'bss-unmapped')

def load():
    """Map, cached in build/edmap.pkl (keyed by both ELFs)."""
    import pickle
    h = hashlib.sha1(open(A_ELF, 'rb').read() + open(B_ELF, 'rb').read()).hexdigest()
    path = os.path.join(ROOT, 'build', 'edmap.pkl')
    try:
        with open(path, 'rb') as f:
            key, state = pickle.load(f)
        if key == h:
            m = Map.__new__(Map)
            m.__dict__.update(state)
            return m
    except (OSError, EOFError, pickle.UnpicklingError):
        pass
    m = Map()
    m.A = m.B = m.wa = m.wb = None          # don't pickle the ELFs
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        pickle.dump((h, m.__dict__), f)
    return m

if __name__ == '__main__':
    m = load()
    for a in sys.argv[1:]:
        va = int(a, 16)
        b, how = m.map(va)
        print('0x%06X -> %s %s' % (va, '0x%06X' % b if b is not None else '-', how))
