"""Main-menu card labels (TAI5DATA entry 18): English redrawn into the textures.

Textures 1-9 of entry 18 are strips of 230-px cards (normal, highlighted, then the
locked '???' pair); each card has its label in a framed box at the bottom left
(x = 12, 2-px border, paper gradient inside, 26 rows of text). The box of the first
two cards is redrawn: border kept (widened to the English if needed), the inside
refilled with the row gradient of the original, and the English drawn with the
'label' size of latinfont in the original text colour. Colours are mapped to the
nearest opaque colour of the texture's palette.

tl/menu.txt: "texture<TAB>English" lines.
"""
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
import latinfont, tk5p

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'menu.txt')
ENTRY = 18
CARD, X0 = 230, 12
PAD = 8
GLOW = 3                      # highlighted cards: light glow around the box

def load_tl():
    out = {}
    if os.path.exists(TL):
        for line in open(TL, encoding='ascii').read().splitlines():
            if line.strip() and not line.startswith('#'):
                k, _, v = line.partition('\t')
                out[int(k)] = v
    return out

def luma(c):
    return (c[0] * 299 + c[1] * 587 + c[2] * 114) // 1000

class Canvas:
    def __init__(self, tex):
        self.typ, self.w, self.h, self.pix, self.pal = tk5p.indexed(tex)
        self.opaque = [i for i, c in enumerate(self.pal) if c[3] >= 0x80]
        self.cache = {}

    def get(self, x, y):
        return self.pal[self.pix[y * self.w + x]]

    def put(self, x, y, i):
        self.pix[y * self.w + x] = i

    def index(self, rgb):
        rgb = tuple(int(round(v)) for v in rgb[:3])
        if rgb not in self.cache:
            self.cache[rgb] = min(self.opaque, key=lambda i: sum((a - b) ** 2 for a, b in zip(self.pal[i], rgb)))
        return self.cache[rgb]

    def dark(self, x, y):
        return luma(self.get(x, y)) < 120

    def box(self, c):
        """(x0, y0, x1, y1, border) of the label frame of card c (inclusive)."""
        x0 = c * CARD + X0
        y1 = max(y for y in range(self.h) if self.dark(x0 + 3, y))
        b = 1
        while self.dark(x0 + 3, y1 - b):
            b += 1
        y0 = max(y for y in range(y1 - b) if self.dark(x0 + 3, y))
        y0 -= b - 1
        # right border: the first column after the text that is dark from top to bottom
        x1 = x0 + b + 10
        while not all(self.dark(x1, y) for y in range(y0, y1 + 1)):
            x1 += 1
        return x0, y0, x1 + b - 1, y1, b

def _median(cols):
    cols = sorted(cols, key=luma)
    return cols[len(cols) // 2]

def relabel(canvas, c, text, font):
    x0, y0, x1, y1, b = canvas.box(c)
    rows = range(y0 + b, y1 - b + 1)
    assert len(rows) >= 24, (c, x0, y0, x1, y1)
    left = {y: _median([canvas.get(x, y) for x in range(x0 + b, x0 + b + 5)]) for y in rows}
    right = {y: _median([canvas.get(x, y) for x in range(x1 - b - 4, x1 - b + 1)]) for y in rows}
    ink = min((canvas.get(x, y) for y in rows for x in range(x0 + b, x1 - b + 1)), key=luma)
    tw = sum(font[ch][1] for ch in text)
    width = max(x1 - x0 + 1, tw + 2 * PAD + 2 * b)
    nx1 = x0 + width - 1
    glow = GLOW if c == 1 else 0
    limit = (c + 1) * CARD - GLOW - 1
    if nx1 > limit:
        raise ValueError('menu label %r: %d px, room %d' % (text, width, limit - x0 + 1))
    # widen: move the right border (and glow) out, fill the new columns from a clean
    # column of the frame
    if nx1 > x1:
        span = range(y0 - glow, y1 + glow + 1)
        right_cols = [[canvas.pix[y * canvas.w + x] for y in span] for x in range(x1 - b + 1, x1 + glow + 1)]
        ref = [canvas.pix[y * canvas.w + x0 + b + 1] for y in span]
        for x in range(x1 - b + 1, nx1 - b + 1):
            for k, y in enumerate(span):
                canvas.put(x, y, ref[k])
        for j, col in enumerate(right_cols):
            for k, y in enumerate(span):
                canvas.put(nx1 - b + 1 + j, y, col[k])
    # inside: row gradient
    inner = range(x0 + b, nx1 - b + 1)
    n = len(inner) - 1
    bg = {}
    for y in rows:
        for k, x in enumerate(inner):
            t = k / n
            col = tuple(l + (r - l) * t for l, r in zip(left[y][:3], right[y][:3]))
            bg[x, y] = col
            canvas.put(x, y, canvas.index(col))
    # text, centred
    cw, ch, base, cap, stroke, top = latinfont.SIZES['label']
    x = x0 + b + (len(inner) - tw) // 2
    ty = y0 + b + (len(rows) - ch) // 2
    for chr_ in text:
        glyph, adv = font[chr_]
        for gy in range(ch):
            for gx in range(cw):
                v = glyph[gy][gx]
                px, py = x + gx, ty + gy
                if v and (px, py) in bg:
                    a = v / top
                    col = tuple(p + (q - p) * a for p, q in zip(bg[px, py], ink[:3]))
                    canvas.put(px, py, canvas.index(col))
        x += adv

def apply(data, elf, entry):
    """-> {ENTRY: new bytes}; entry(i) gives clean TAI5DATA entries. Rewrites the
    texture offset table in elf."""
    tl = load_tl()
    if not tl:
        return {}
    clean = entry(ENTRY)
    textures = tk5p.split(elf, clean)
    font = latinfont.render('label')
    for i, text in sorted(tl.items()):
        canvas = Canvas(textures[i])
        for c in (0, 1):
            relabel(canvas, c, text, font)
        textures[i] = tk5p.pack8(canvas.typ, canvas.w, canvas.h, canvas.pix, canvas.pal)
    return {ENTRY: tk5p.join(elf, clean, textures)}

if __name__ == '__main__':
    # menugfx.py preview out.png: the relabelled cards
    import datafile, mmap
    from PIL import Image
    elf = bytearray(open(os.path.join(ROOT, 'extract', 'SLPM_656.74'), 'rb').read())
    f = open(os.path.join(ROOT, 'extract', 'TAI5DATA.DAT'), 'rb')
    d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    clean_elf = bytes(elf)
    new = apply(d, elf, lambda i: datafile.entry(d, clean_elf, i))[ENTRY]
    texs = tk5p.split(elf, new)
    ims = []
    for i in sorted(load_tl()):
        typ, w, h, pix, pal = tk5p.indexed(texs[i])
        im = Image.frombytes('P', (w, h), bytes(pix))
        im.putpalette(b''.join(bytes(c[:3]) for c in pal))
        ims.append(im.convert('RGB').crop((0, 100, 2 * CARD, h)))
    sheet = Image.new('RGB', (2 * CARD * 2, 120 * ((len(ims) + 1) // 2)), (255, 0, 255))
    for k, im in enumerate(ims):
        sheet.paste(im, ((k % 2) * 2 * CARD, (k // 2) * 120))
    sheet.save(sys.argv[2])
