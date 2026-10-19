"""TK5P textures (TAI5DATA entries 15-102 and others).

Header (16 bytes): 'TK5P', u16 type, u16 palette count, u16 width, u16 height, u32 data
size. type & 0xF = pixel format (0 = 32bpp, 1 = 16bpp, 2 = 8bpp, 3 = 4bpp); 8/4bpp data is
the pixels followed by the palettes (256 / 16 x RGBA each, alpha 0-0x80). Some sheets have
2-18 palettes (entries 15, 85, 88, 93, 94, 96, 101), each used by different sprites: a
rebuilt texture must keep them all (with one, the game uploads the missing palette from
past the data: the duel HUD then sends garbage to VIF1 and every frame times out).
type & 0x10 = the data is compressed (decoder 0x477060): then u32 size, then a stream of 32-bit words
shared by three readers in order of need: 32 flags per word (MSB first: 1 = literal,
0 = match), literal bytes (4 per word, low byte first) and a 16-bit bit window for
matches (gamma-coded length 1-254, 255 = end; distance classes by a 5-bit prefix).
compress() writes that format (bit-cost optimal LZ parse).
"""
import struct

MAGIC = b'TK5P'
HEADER = 16
BPP = {0: 32, 1: 16, 2: 8, 3: 4}

def info(b):
    assert b[:4] == MAGIC
    typ, _, w, h, size = struct.unpack_from('<HHHHI', b, 4)
    return typ, w, h, size

# distance handlers by the 5-bit prefix (jump table 0x5A9270): (base, mask/xor, shift)
_DIST = [1, 1, 2, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 7, 7, 7, 7, 8, 8, 8, 8, 9, 9, 9, 9]

def decompress(b):
    """Data of a compressed TK5P (b = whole file) -> uncompressed data."""
    words = memoryview(b)[HEADER + 4:]
    nw = len(words) // 4
    words = struct.unpack_from('<%dI' % nw, words)
    pos = 0
    out = bytearray()
    M = 0xFFFFFFFF
    t5 = 0        # bits left in t6
    t6 = 0
    t7 = 0        # bit window (bit 15 = next bit)

    def refill(n):
        nonlocal t5, t6, t7, pos
        t7 = (t7 << n) & M
        if t5 < n:
            s = n - t5
            t7 |= ((t6 & ((1 << t5) - 1)) << s) & M
            t6 = words[pos]
            pos += 1
            t5 = 32 - s
            t7 |= t6 >> t5
        else:
            t5 -= n
            t7 |= (t6 >> t5) & ((1 << n) - 1)

    refill(16)
    lit, nlit = 0, 0
    while True:
        flags = words[pos]
        pos += 1
        for _ in range(32):
            if flags & 0x80000000:
                if nlit == 0:
                    lit = words[pos]
                    pos += 1
                out.append(lit & 0xFF)
                lit >>= 8
                nlit = (nlit + 1) & 3
            else:
                if t7 & 0x8000:
                    n = 1
                else:
                    for k in range(1, 7):
                        if t7 & (0x8000 >> k):
                            n = (t7 >> (15 - 2 * k)) & ((2 << k) - 1)
                            refill(2 * k)
                            break
                    else:
                        n = ((t7 & 0x1FC) >> 2) + 0x80
                        if n == 0xFF:
                            return bytes(out)
                        refill(13)
                t7 &= 0x7FFF
                h = _DIST[(t7 & 0x7C00) >> 10]
                if h == 1:
                    d = (t7 & 0x600) >> 9; refill(7)
                elif h == 2:
                    d = ((t7 & 0x300) >> 8) + 4; refill(8)
                elif h == 3:
                    d = (((t7 - 0xC00) & 0xF80) >> 7) + 8; refill(9)
                elif h == 4:
                    d = (((t7 - 0x1800) & 0x1FC0) >> 6) + 0x20; refill(10)
                elif h == 5:
                    d = (t7 & 0x1FFF) >> 5; refill(11)
                elif h == 6:
                    d = ((t7 & 0x1FFF) | 0x1000) >> 4; refill(12)
                elif h == 7:
                    d = (t7 & 0x1FFF) >> 3; refill(13)
                elif h == 8:
                    d = ((t7 & 0x1FFF) | 0x1000) >> 2; refill(14)
                else:
                    d = (t7 & 0x1FFF) >> 1; refill(15)
                src = len(out) - 1 - d
                for i in range(n + 1):
                    out.append(out[src + i])
            flags = (flags << 1) & M

def data(b):
    """Uncompressed pixel+palette data of a TK5P file."""
    typ = info(b)[0]
    return decompress(b) if typ & 0x10 else bytes(b[HEADER:HEADER + info(b)[3]])

def build(typ, w, h, d, npal=1):
    """Uncompressed TK5P file."""
    return MAGIC + struct.pack('<HHHHI', typ & 0xF, npal, w, h, len(d)) + d

def to_rgba(b):
    """(w, h, RGBA bytes) of an 8/4bpp TK5P (alpha scaled to 0-255)."""
    typ, w, h, size = info(b)
    d = data(b)
    bpp = BPP[typ & 0xF]
    if bpp == 8:
        pix, pal = d[:w * h], d[w * h:w * h + 1024]
    elif bpp == 4:
        n = w * h // 2
        pix = bytes(v for x in d[:n] for v in (x & 15, x >> 4))
        pal = d[n:n + 64]
    else:
        raise ValueError('bpp %d' % bpp)
    out = bytearray()
    for p in pix:
        r, g, bl, a = pal[4 * p:4 * p + 4]
        out += bytes((r, g, bl, min(255, a * 2)))
    return w, h, bytes(out)

# ---------------------------------------------------------------- 8bpp editing

def swizzle(i):
    """PS2 CLUT order: palette slot of colour i (bits 3 and 4 swapped; self-inverse)."""
    return (i & 0xE7) | ((i & 8) << 1) | ((i & 16) >> 1)

def indexed(b):
    """(type, w, h, pixels bytearray, palette [(r, g, b, a)] in index order) of an 8bpp TK5P."""
    typ, w, h, size = info(b)
    assert BPP[typ & 0xF] == 8
    d = data(b)
    pal = [tuple(d[w * h + 4 * swizzle(i):w * h + 4 * swizzle(i) + 4]) for i in range(256)]
    return typ, w, h, bytearray(d[:w * h]), pal

def extra_palettes(b):
    """The palettes after the first of an 8bpp TK5P (b'' for most textures)."""
    typ, w, h, size = info(b)
    return bytes(data(b)[w * h + 1024:])

def pack8(typ, w, h, pix, pal, extra=b''):
    """8bpp TK5P from indexed() data (+ extra_palettes() of the original), compressed if
    type says so (as the original)."""
    p = bytearray(1024)
    for i, c in enumerate(pal):
        p[4 * swizzle(i):4 * swizzle(i) + 4] = bytes(c)
    d = bytes(pix) + bytes(p) + extra
    npal = 1 + len(extra) // 1024
    return build_compressed(typ, w, h, d, npal) if typ & 0x10 else build(typ, w, h, d, npal)

# ---------------------------------------------------------------- texture packs

def offsets(entry):
    """Offsets of the TK5P files of a TAI5DATA entry made of concatenated textures."""
    offs, o = [], 0
    while True:
        o = entry.find(MAGIC, o)
        if o < 0:
            return offs
        offs.append(o)
        o += 4

def pack_table(elf, entry):
    """(ELF file offset, stride) of the table that locates the textures of a pack:
    u32 offsets (stride 4, followed by the entry size; e.g. entry 18 -> 0x422630) or
    (u32 offset, u32 0) pairs (stride 8, mini-game packs). (None, None) if there is
    none (e.g. entry 67, sector-aligned uncompressed textures)."""
    offs = offsets(entry)
    for stride in (4, 8):
        seq = b''.join(struct.pack('<I', o) + bytes(stride - 4) for o in offs)
        at = elf.find(seq)
        if at >= 0:
            assert elf.find(seq, at + 1) < 0, 'texture table found twice'
            return at, stride
    return None, None

def split(elf, entry):
    offs = offsets(entry)
    return [entry[a:b] for a, b in zip(offs, offs[1:] + [len(entry)])]

def join(elf, entry, textures):
    """New entry bytes from its (changed) textures. Textures that still fit their
    original slots keep the layout; otherwise they are packed again and the offset
    table in elf is rewritten."""
    offs = offsets(entry)
    slots = [b - a for a, b in zip(offs, offs[1:] + [len(entry)])]
    for k, (t, o) in enumerate(zip(textures, offs)):
        old = entry[o:o + HEADER]
        assert t[6:8] == old[6:8] and info(t)[1:] == info(old)[1:], \
            'texture %d: palette count/size/data size changed' % k
    if all(len(t) <= n for t, n in zip(textures, slots)):
        return b''.join(t + bytes(n - len(t)) for t, n in zip(textures, slots))
    at, stride = pack_table(elf, entry)
    assert at is not None, 'texture grew and the pack has no offset table'
    align = 2048 if all(o % 2048 == 0 for o in offs) else 4
    out, new = bytearray(), []
    for t in textures:
        new.append(len(out))
        out += t + bytes(-len(t) % align)
    for k, o in enumerate(new):
        struct.pack_into('<I', elf, at + stride * k, o)
    if stride == 4 and struct.unpack_from('<I', elf, at + 4 * len(new))[0] == len(entry):
        struct.pack_into('<I', elf, at + 4 * len(new), len(out))
    return bytes(out)

# ---------------------------------------------------------------- compression

def _len_code(n):
    """Bits of the match length code (copy n + 1 bytes; n = 1..254, 255 = end)."""
    if n >= 128:
        return '0' * 7 + format(n - 128, '07b')
    k = n.bit_length() - 1
    return '0' * k + format(n, '0%db' % (k + 1))

def _dist_code(d):
    """Bits of the match distance code (source = output position - 1 - d)."""
    if d < 4:
        return '0000' + format(d, '02b')
    if d < 8:
        return '00010' + format(d - 4, '02b')
    if d < 32:
        return format(d + 0x10, '08b')
    if d < 128:
        return format(d + 0x40, '09b')
    if d < 256:
        return format(d + 0x100, '010b')
    if d < 512:
        return format(d + 0x300, '011b')
    if d < 1024:
        return format(d + 0x800, '012b')
    if d < 2048:
        return format(d + 0x1400, '013b')
    return format(d + 0x3000, '014b')

MAX_DIST, MAX_LEN = 4096, 255

def _match_len(d, i, j, n):
    k = 0
    lim = min(MAX_LEN, n - i)
    while k + 16 <= lim and d[i + k:i + k + 16] == d[j + k:j + k + 16]:
        k += 16
    while k < lim and d[i + k] == d[j + k]:
        k += 1
    return k

def _tokens(d, chain=48):
    """Bit-cost optimal parse (dynamic programming): [byte] literals and
    (length, distance) matches. A literal costs 9 bits (flag + byte), a match
    1 + length code + distance code bits."""
    n = len(d)
    cands = [None] * n
    heads = {}
    for i in range(n):
        found = []
        if i + 2 < n:
            key = d[i:i + 3]
            seen = 0
            best = 2
            for j in reversed(heads.get(key, ())):
                if i - j > MAX_DIST:
                    break
                k = _match_len(d, i, j, n)
                if k > best:
                    best = k
                    found.append((k, i - j - 1))
                    if k == MAX_LEN:
                        break
                seen += 1
                if seen >= chain:
                    break
            heads.setdefault(key, []).append(i)
        if i > 0 and i + 1 < n and d[i - 1] == d[i] == d[i + 1] and not found:
            found.append((2, 0))
        cands[i] = found
    INF = float('inf')
    cost = [INF] * (n + 1)
    pick = [None] * n
    cost[n] = 0
    lc = [len(_len_code(m)) for m in range(256)]
    for i in range(n - 1, -1, -1):
        best, choice = 9 + cost[i + 1], None
        for k, dist in cands[i]:
            db = len(_dist_code(dist))
            # the full length, and shorter ones where the length code gets cheaper
            for L in {k, min(k, 128), min(k, 64), min(k, 32), min(k, 16), min(k, 8), min(k, 4), min(k, 2)}:
                if L >= 2:
                    c = 1 + lc[L - 1] + db + cost[i + L]
                    if c < best:
                        best, choice = c, (L, dist)
        cost[i], pick[i] = best, choice
    out, i = [], 0
    while i < n:
        if pick[i]:
            out.append(pick[i])
            i += pick[i][0]
        else:
            out.append(d[i])
            i += 1
    return out

def compress(d):
    """Data -> compressed stream (the u32 size word and the word stream) that
    decompress() and the game's decoder read back as d."""
    toks = _tokens(bytes(d)) + [None]                    # None = end code
    bits = ''.join((_len_code(t[0] - 1) + _dist_code(t[1])) if isinstance(t, tuple)
                   else '0' * 7 + '1' * 7 if t is None else '' for t in toks)
    bits += '0' * (-len(bits) % 32 + 64)
    lits = bytes(t for t in toks if isinstance(t, int))
    lits += bytes(-len(lits) % 4)
    words, bw, lw = [], 0, 0
    fetched = 0

    def need(nbits):
        # the decoder's 16-bit window: loads a word when it runs out
        nonlocal fetched, bw
        fetched += nbits
        while bw * 32 < fetched:
            words.append(int(bits[bw * 32:bw * 32 + 32], 2))
            bw += 1

    need(16)
    nlit = 0
    for g in range(0, len(toks), 32):
        group = toks[g:g + 32]
        flags = 0
        for k, t in enumerate(group):
            if isinstance(t, int):
                flags |= 0x80000000 >> k
        words.append(flags)
        for t in group:
            if isinstance(t, int):
                if nlit == 0:
                    words.append(struct.unpack_from('<I', lits, lw * 4)[0])
                    lw += 1
                nlit = (nlit + 1) & 3
            elif t is None:
                break
            else:
                need(len(_len_code(t[0] - 1)) + len(_dist_code(t[1])))
    return struct.pack('<I', len(d)) + struct.pack('<%dI' % len(words), *words)

def build_compressed(typ, w, h, d, npal=1):
    """Compressed TK5P file."""
    return MAGIC + struct.pack('<HHHHI', (typ & 0xF) | 0x10, npal, w, h, len(d)) + compress(d)
