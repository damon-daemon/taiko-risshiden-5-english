"""Redraw Japanese text baked into 8bpp TK5P textures (banners, labels, buttons).

Lettering comes from the stroke glyphs of latinfont (original drawings), rendered at
any size; colours are taken from the original texture so the English keeps its look:

  banner(): big outlined lettering on a transparent texture (勝利, 軍議 ...): the
    original's layers are measured (fill with its grain, a dark outline, a soft light
    outer outline) and rebuilt around the English.
  plate(): text on a background (読み込み中 strip, small buttons): the text area is
    refilled row by row from a clean sample area beside it, then the English is drawn
    with the original's ink and outline colours.

Items (texture, kind, area) are listed in ITEMS; their English is in tl/gfx.txt
("entry.texture<TAB>English").
"""
import collections, os, sys
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
import latinfont, tk5p

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'gfx.txt')
SS = 4

def luma(c):
    return (c[0] * 299 + c[1] * 587 + c[2] * 114) // 1000

class Canvas:
    """An 8bpp texture being edited: pixels are palette indexes (palette in index order)."""
    def __init__(self, tex):
        self.typ, self.w, self.h, self.pix, self.pal = tk5p.indexed(tex)
        self.extra = tk5p.extra_palettes(tex)
        top = min(0x80, max(c[3] for c in self.pal))
        self.opaque = [i for i, c in enumerate(self.pal) if c[3] >= top - 4]
        self.cache = {}

    def get(self, x, y):
        return self.pal[self.pix[y * self.w + x]]

    def idx(self, x, y):
        return self.pix[y * self.w + x]

    def put(self, x, y, i):
        self.pix[y * self.w + x] = i

    def index(self, rgb, alpha=0x80):
        """Nearest palette entry to an RGB colour (and alpha, 0-0x80)."""
        key = tuple(int(round(v)) for v in rgb[:3]) + (int(round(alpha)),)
        if key not in self.cache:
            if alpha >= 0x80:
                cands = self.opaque
            else:
                cands = range(256)
            self.cache[key] = min(cands, key=lambda i: sum((a - b) ** 2 for a, b in zip(self.pal[i][:3], key[:3]))
                                  + 4 * (self.pal[i][3] - key[3]) ** 2)
        return self.cache[key]

    def light(self, rgb, alpha):
        """Palette entry for a soft edge of a light outline: same colour, lower alpha."""
        key = ('light',) + tuple(rgb) + (int(alpha),)
        if key not in self.cache:
            cands = [i for i, c in enumerate(self.pal) if luma(c) >= luma(rgb) - 24] or range(256)
            self.cache[key] = min(cands, key=lambda i: abs(self.pal[i][3] - alpha) * 8
                                  + sum((a - b) ** 2 for a, b in zip(self.pal[i][:3], rgb)) ** 0.5)
        return self.cache[key]

    def tex(self):
        return tk5p.pack8(self.typ, self.w, self.h, self.pix, self.pal, self.extra)

# ---------------------------------------------------------------- lettering

def text_masks(text, cap, widths, condense=1.0, spacing=None, descender=None):
    """Coverage images (PIL 'L', SS times the final size) of text drawn with each
    stroke width in widths (px, final scale): wider strokes give the outline layers.
    Returns (images, (w, h), (left, top) of the cap box) at final scale."""
    stroke = widths[0]
    s = (cap - stroke) / latinfont.C
    spacing = stroke * 0.45 if spacing is None else spacing
    pad = max(widths) / 2 + 2
    xs, x = [], pad
    for c in text:
        w, _ = latinfont.GLYPHS[c]
        xs.append(x)
        x += (w * s * condense + stroke + spacing) if c != ' ' else cap * 0.32
    width = x - spacing + pad
    if descender is None:
        descender = any(c in 'gjpqy,;' for c in text)
    height = cap + stroke + 2 * pad + (3 * s if descender else 0)
    base = pad + cap - stroke / 2
    out = []
    for sw in widths:
        im = Image.new('L', (int(width * SS) + 1, int(height * SS) + 1), 0)
        dr = ImageDraw.Draw(im)
        r = sw * SS / 2
        for c, x0 in zip(text, xs):
            for st in latinfont.GLYPHS[c][1]:
                pts = [((x0 + stroke / 2 + px * s * condense) * SS, (base - py * s) * SS) for px, py in st]
                # segment by segment with round joints (thick joined polylines spike)
                for a, b in zip(pts, pts[1:]):
                    dr.line([a, b], fill=255, width=max(1, round(sw * SS)))
                for px, py in pts:
                    dr.ellipse((px - r, py - r, px + r, py + r), fill=255)
        out.append(im)
    return out, (width, height), (pad, pad)

def downsample(im, size):
    return im.resize(size, Image.BOX)

# ---------------------------------------------------------------- banners

def _runs(row):
    out, x = [], 0
    while x < len(row):
        if row[x]:
            x0 = x
            while x < len(row) and row[x]:
                x += 1
            out.append((x0, x))
        x += 1
    return out

def banner_style(cv):
    """Layers of an outlined banner: (fill rows {y: [index...]}, outline index,
    outer rgb, outer width, outline width, text rows (y0, y1))."""
    w, h = cv.w, cv.h
    A = [[cv.get(x, y)[3] for x in range(w)] for y in range(h)]
    L = [[luma(cv.get(x, y)) for x in range(w)] for y in range(h)]
    light = [[A[y][x] > 0 and L[y][x] >= 235 for x in range(w)] for y in range(h)]
    inner = [[A[y][x] >= 0x78 and L[y][x] < 235 for x in range(w)] for y in range(h)]
    ys = [y for y in range(h) if any(inner[y])]
    # outer width: runs of light pixels between transparency and the inner text
    widths, dark = [], collections.Counter()
    for y in ys:
        for x0, x1 in _runs(light[y]):
            if x1 < w and inner[y][x1] and (x0 == 0 or A[y][x0 - 1] == 0 or not inner[y][x0 - 1]):
                widths.append(x1 - x0)
                for k in range(3):
                    if x1 + k < w and inner[y][x1 + k]:
                        dark[cv.idx(x1 + k, y)] += 1
    if widths:
        outer_w = sorted(widths)[len(widths) // 2]
        outline = dark.most_common(1)[0][0]
        outline_w = 2 if outer_w >= 5 else 1
        outer = collections.Counter(cv.get(x, y)[:3] for y in range(h) for x in range(w) if light[y][x])
        outer_rgb = outer.most_common(1)[0][0]
    else:
        # no light outer outline: the dark outline is the text's edge against transparency
        edge = collections.Counter(cv.idx(x, y) for y in ys for x in range(w) if inner[y][x] and any(
            A[y + dy][x + dx] < 0x78 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if 0 <= y + dy < h and 0 <= x + dx < w))
        outer_w, outline, outline_w, outer_rgb = 0, edge.most_common(1)[0][0], 1, None
        light = [[A[y][x] < 0x78 for x in range(w)] for y in range(h)]
    # fill: inner pixels away from the light outline
    near = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if light[y][x] or A[y][x] < 0x78:
                for dy in range(-outline_w - 1, outline_w + 2):
                    for dx in range(-outline_w - 1, outline_w + 2):
                        if 0 <= y + dy < h and 0 <= x + dx < w:
                            near[y + dy][x + dx] = True
    fill = {y: [cv.idx(x, y) for x in range(w) if inner[y][x] and not near[y][x]] for y in range(h)}
    # one colour per row (the median by brightness): the originals are striped
    fill = {y: sorted(v, key=lambda i: luma(cv.pal[i]))[len(v) // 2] for y, v in fill.items() if v}
    return fill, outline, outer_rgb, outer_w, outline_w, (ys[0], ys[-1])

def banner(cv, text, cap=None):
    """Replace the lettering of an outlined banner texture with text (centred)."""
    fill, outline, outer_rgb, ow, lw, (y0, y1) = banner_style(cv)
    transparent = min(range(256), key=lambda i: cv.pal[i][3])
    cap = cap or (y1 - y0 + 1) * 0.72
    condense = 1.0
    while True:
        stroke = max(2.0, cap * (0.17 if cap >= 30 else 0.12))
        o_w = min(ow, max(2.0, cap * 0.12))           # a thick glow merges small letters
        l_w = lw if cap >= 24 else 1
        widths = [stroke, stroke + 2 * l_w, stroke + 2 * (l_w + o_w)]
        masks, (tw, th), _ = text_masks(text, cap, widths, condense)
        if tw <= cv.w - 4 or cap < 12:
            break
        if condense > 0.8:
            condense *= 0.96
        else:
            cap *= 0.95
    if tw > cv.w - 4:
        raise ValueError('banner %r: %d px wide, texture %d' % (text, tw, cv.w))
    size = (int(tw) + 1, int(th) + 1)
    core, mid, out = (downsample(m, (size[0], size[1])) for m in masks)
    ox = (cv.w - size[0]) // 2
    oy = (y0 + y1) // 2 - size[1] // 2
    fy = sorted(fill)
    for y in range(cv.h):
        for x in range(cv.w):
            cv.put(x, y, transparent)
    for y in range(size[1]):
        ty = oy + y
        if not 0 <= ty < cv.h:
            continue
        row = fill[min(fy, key=lambda r: abs(r - (y0 + (y1 - y0) * y / size[1])))]
        for x in range(size[0]):
            tx = ox + x
            c, m, o = core.getpixel((x, y)) / 255, mid.getpixel((x, y)) / 255, out.getpixel((x, y)) / 255
            if c > 0.5:
                i = row
            elif m > 0.5:
                i = outline
            elif o > 0.1 and outer_rgb:
                i = cv.light(outer_rgb, o * 0x80)
            else:
                continue
            cv.put(tx, ty, i)

# ---------------------------------------------------------------- plates

def plate(cv, area, sample, text, ink, edge, cap, stroke, edge_w=1.5, align='center', text_area=None):
    """Erase area (x0, y0, x1, y1) by refilling each row with the colours of the same
    row in the sample columns (sx0, sx1), then draw text with ink inside an edge outline
    (rgb colours or None), centred in text_area (default: area) over what is there."""
    x0, y0, x1, y1 = area
    orig = sorted((cv.get(x, y) for y in range(y0, y1) for x in range(x0, x1)), key=luma)
    ink_a = orig[len(orig) // 16][3]                     # alpha of the original text
    if sample == 'inpaint':
        # replace only the text's pixels by the nearest other pixel of the row (keeps
        # brush swashes and gradients under the text)
        th = (luma(orig[len(orig) // 16]) + luma(orig[len(orig) * 3 // 4])) / 2
        for y in range(y0, y1):
            row = [cv.idx(x, y) for x in range(x0 - 1, x1 + 1)]
            keep = [luma(cv.pal[i]) > th for i in row]
            for k in range(1, len(row) - 1):
                if not keep[k]:
                    near = min((j for j in range(len(row)) if keep[j]), key=lambda j: abs(j - k), default=None)
                    if near is not None:
                        cv.put(x0 - 1 + k, y, row[near])
    else:
        for y in range(y0, y1):
            row = [cv.idx(x, y) for x in range(*sample)]
            for x in range(x0, x1):
                cv.put(x, y, row[(x - x0) % len(row)])
    if ink is None:
        ink = orig[len(orig) // 16][:3]                   # the original text colour
    if not text:
        return
    x0, y0, x1, y1 = text_area or area
    widths = [stroke] + ([stroke + 2 * edge_w] if edge else [])
    condense = 1.0
    while True:
        masks, (tw, th), (px, py) = text_masks(text, cap, widths, condense, descender=True)
        if tw <= x1 - x0 or condense < 0.6:
            break
        condense *= 0.95
    size = (int(tw) + 1, int(th) + 1)
    layers = [downsample(m, size) for m in masks]
    ox = {'center': x0 + ((x1 - x0) - size[0]) // 2, 'left': x0, 'right': x1 - size[0]}[align]
    oy = y0 + ((y1 - y0) - round(cap + widths[0])) // 2 - round(py)     # capitals centred
    for y in range(size[1]):
        for x in range(size[0]):
            tx, ty = ox + x, oy + y
            if not (0 <= tx < cv.w and 0 <= ty < cv.h):
                continue
            base = cv.get(tx, ty)
            c = layers[0].getpixel((x, y)) / 255
            e = layers[1].getpixel((x, y)) / 255 if edge else 0
            if c <= 0 and e <= 0:
                continue
            col = base[:3]
            if e > 0:
                col = tuple(p + (q - p) * e for p, q in zip(col, edge))
            if c > 0:
                col = tuple(p + (q - p) * c for p, q in zip(col, ink))
            cv.put(tx, ty, cv.index(col, base[3] + (max(ink_a, base[3]) - base[3]) * max(c, e)))

# ---------------------------------------------------------------- labels

def label(cv, box, text, cap=None, bold=0.15):
    """Outlined text on a flat background inside box (x0, y0, x1, y1 inclusive):
    background = most common colour on the box edge, outline = text pixels touching
    the background, fill = the other text pixels; then the English, centred."""
    x0, y0, x1, y1 = box
    edge = [cv.idx(x, y) for x in range(x0, x1 + 1) for y in (y0, y1)] + \
           [cv.idx(x, y) for y in range(y0, y1 + 1) for x in (x0, x1)]
    bgi = collections.Counter(edge).most_common(1)[0][0]
    bg = cv.pal[bgi]
    isfg = lambda x, y: sum(abs(a - b) for a, b in zip(cv.get(x, y)[:3], bg[:3])) > 12
    ring, core = collections.Counter(), collections.Counter()
    for y in range(y0 + 1, y1):
        for x in range(x0 + 1, x1):
            if isfg(x, y):
                if any(not isfg(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                    ring[cv.idx(x, y)] += 1
                else:
                    core[cv.idx(x, y)] += 1
    ys = [y for y in range(y0, y1 + 1) if any(isfg(x, y) for x in range(x0, x1 + 1))]
    outline_i = ring.most_common(1)[0][0]
    outline = cv.pal[outline_i][:3]
    inner = [i for i, n in core.most_common() if abs(luma(cv.pal[i]) - luma(outline)) > 20]
    fill = cv.pal[inner[0]][:3] if inner else bg[:3]       # none: hollow lettering
    text_a = cv.pal[inner[0] if inner else outline_i][3]
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            cv.put(x, y, bgi)
    cap = cap or (ys[-1] - ys[0] + 1) * 0.68
    lw = 1.0 if cap < 14 else 1.6
    condense = 1.0
    while True:
        stroke = max(1.6, cap * bold)
        masks, (tw, th), _ = text_masks(text, cap, [stroke, stroke + 2 * lw], condense)
        if tw <= x1 - x0 + 1 or cap < 6:
            break
        if condense > 0.8:
            condense *= 0.96
        else:
            cap *= 0.95
    size = (int(tw) + 1, int(th) + 1)
    c_im, o_im = (downsample(m, size) for m in masks)
    ox = x0 + (x1 - x0 + 1 - size[0]) // 2
    oy = (ys[0] + ys[-1] + 1) // 2 - size[1] // 2
    for y in range(size[1]):
        for x in range(size[0]):
            tx, ty = ox + x, oy + y
            if not (x0 <= tx <= x1 and y0 <= ty <= y1):
                continue
            c, o = c_im.getpixel((x, y)) / 255, o_im.getpixel((x, y)) / 255
            if o <= 0.05:
                continue
            col = tuple(p + (q - p) * o for p, q in zip(bg[:3], outline))
            col = tuple(p + (q - p) * c for p, q in zip(col, fill))
            a = bg[3] + (text_a - bg[3]) * o              # keeps semi-transparent plates
            cv.put(tx, ty, cv.index(col, a))

# ---------------------------------------------------------------- haloed glyphs

def glyph(cv, box, text, bold=0.2, halo_w=2.0):
    """Light lettering with a soft dark halo on a transparent background (体力 icons):
    colours measured in box, which is cleared and redrawn with text, centred."""
    x0, y0, x1, y1 = box
    px = [(cv.get(x, y), cv.idx(x, y)) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    solid = sorted(luma(c) for c, i in px if c[3] >= 0x50)
    hi = min(128, solid[len(solid) * 3 // 4]) if solid else 128       # brightest quarter
    light = collections.Counter(i for c, i in px if c[3] >= 0x50 and luma(c) >= hi)
    fill_a = sorted(cv.pal[i][3] for i in light.elements())[sum(light.values()) // 2]
    dark = [c for c, i in px if 0 < c[3] and luma(c) < min(80, hi // 2)]
    fill = cv.pal[light.most_common(1)[0][0]][:3]
    halo = collections.Counter(c[:3] for c in dark).most_common(1)[0][0] if dark else (0, 0, 0)
    halo_a = max(c[3] for c in dark) if dark else 0x40
    ys = [y for y in range(y0, y1 + 1) if any(cv.get(x, y)[3] >= 0x50 and luma(cv.get(x, y)) >= hi
                                               for x in range(x0, x1 + 1))]
    clear = min(range(256), key=lambda i: cv.pal[i][3])
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            cv.put(x, y, clear)
    cap = (ys[-1] - ys[0] + 1) * 0.62
    condense = 1.0
    while True:
        stroke = max(1.6, cap * bold)
        masks, (tw, th), _ = text_masks(text, cap, [stroke, stroke + 2 * halo_w], condense)
        if tw <= x1 - x0 + 1 or cap < 6:
            break
        if condense > 0.75:
            condense *= 0.96
        else:
            cap *= 0.95
    size = (int(tw) + 1, int(th) + 1)
    c_im, h_im = (downsample(m, size) for m in masks)
    ox = x0 + (x1 - x0 + 1 - size[0]) // 2
    oy = (ys[0] + ys[-1] + 1) // 2 - size[1] // 2
    for y in range(size[1]):
        for x in range(size[0]):
            tx, ty = ox + x, oy + y
            if not (x0 <= tx <= x1 and y0 <= ty <= y1):
                continue
            c, h = c_im.getpixel((x, y)) / 255, h_im.getpixel((x, y)) / 255
            if c > 0.1:
                col = tuple(p + (q - p) * c for p, q in zip(halo, fill))
                cv.put(tx, ty, cv.index(col, fill_a if c > 0.5 else max(halo_a, fill_a * c)))
            elif h > 0.05:
                cv.put(tx, ty, cv.index(halo, halo_a * h))

# ---------------------------------------------------------------- buttons

def button(cv, cell, text, inset=5, bold=0.16):
    # inset: px or (left, top, right, bottom)
    """Dark text on a framed button: cell (x0, y0, x1, y1) is the whole button; the
    inside (inset px in) is refilled row by row with the row's median paper colour, then
    the English is drawn in the darkest original text colour, centred."""
    x0, y0, x1, y1 = cell
    l, t, r, b = inset if isinstance(inset, tuple) else (inset,) * 4
    ix0, iy0, ix1, iy1 = x0 + l, y0 + t, x1 - r, y1 - b
    inner = [cv.get(x, y) for y in range(iy0, iy1 + 1) for x in range(ix0, ix1 + 1)]
    lum = sorted(luma(c) for c in inner)
    dark = collections.Counter(c[:3] for c in inner if luma(c) <= lum[len(lum) // 12])
    ink = dark.most_common(1)[0][0]
    bg = {}
    for y in range(iy0, iy1 + 1):
        # the row's median colour, ignoring the text
        row = [cv.get(x, y) for x in range(ix0, ix1 + 1)]
        paper = [c for c in row if luma(c) > lum[len(lum) // 3]] or row
        col = _median(paper)[:3]
        i = cv.index(col)
        for x in range(ix0, ix1 + 1):
            bg[x, y] = col
            cv.put(x, y, i)
    h = iy1 - iy0 + 1
    cap = h * 0.62
    condense = 1.0
    while True:
        stroke = max(1.4, cap * bold)
        masks, (tw, th), _ = text_masks(text, cap, [stroke], condense)
        if tw <= ix1 - ix0 + 1 or cap < 6:
            break
        if condense > 0.78:
            condense *= 0.96
        else:
            cap *= 0.95
    size = (int(tw) + 1, int(th) + 1)
    m = downsample(masks[0], size)
    ox = ix0 + (ix1 - ix0 + 1 - size[0]) // 2
    oy = iy0 + (h - size[1]) // 2
    for y in range(size[1]):
        for x in range(size[0]):
            tx, ty = ox + x, oy + y
            c = m.getpixel((x, y)) / 255
            if c > 0.05 and (tx, ty) in bg:
                col = tuple(p + (q - p) * c for p, q in zip(bg[tx, ty], ink))
                cv.put(tx, ty, cv.index(col))

def _median(cols):
    cols = sorted(cols, key=luma)
    return cols[len(cols) // 2]

def _grid(x0, y0, w, h, cols, rows, n=None):
    cells = [(x0 + c * w, y0 + r * h, x0 + c * w + w - 1, y0 + r * h + h - 1)
             for r in range(rows) for c in range(cols)]
    return cells[:n]

# ---------------------------------------------------------------- items

# (entry, texture): ('banner',) or ('plate', area, sample columns, ink, edge, cap, stroke)
ITEMS = {
    (16, 1): ('plate', (30, 2, 200, 40), (205, 235), (40, 34, 30), (230, 222, 205), 22, 3.6),
    (15, 0): ('labels', [(312, 145, 366, 171), (368, 145, 500, 171), (312, 173, 366, 199), (368, 173, 500, 199)]),
    (15, 5): ('glyphs', [(230, 180 + 28 * k, 255, 207 + 28 * k) for k in range(5)]),
    (96, 0): ('mixed', [('glyphs', (160 + 26 * k, 24, 185 + 26 * k, 51)) for k in range(3)]
              + [('labels', (3, 80, 124, 107))]),
    (93, 1): ('mixed', [('glyphs', (160 + 26 * k, 24, 185 + 26 * k, 51)) for k in range(3)]
              + [('labels', (3, 80, 124, 107))]),             # battle atlas variant of 96.0
    # Oicho-Kabu (card dice): buttons, player/dealer tags, hand names
    (65, 0): ('buttons', [(4, 4, 91, 39)], 'list', 6),
    (65, 1): ('buttons', [(10, 4, 85, 39)], 'list', 6),
    (65, 12): ('buttons', _grid(0, 0, 88, 32, 4, 3), 'rows', (4, 4, 10, 8)),
    (65, 13): ('buttons', _grid(0, 0, 48, 32, 3, 2), 'cycle', 4),
    (65, 56): ('buttons', _grid(0, 0, 88, 32, 3, 1), 'cycle', (4, 4, 10, 8)),
    (65, 58): ('buttons', _grid(0, 0, 72, 22, 3, 5, 13), 'list', 4),
    # slot machine (49), dice (68), medicine (58), military-science quiz (61)
    (49, 0): ('buttons', _grid(0, 0, 48, 28, 4, 1), 'cycle', (4, 4, 6, 6)),
    (49, 12): ('buttons', [(0, 0, 87, 23)], 'list', (5, 3, 6, 3)),
    (68, 0): ('buttons', [(0, 0, 63, 31)], 'list', (4, 4, 7, 7)),
    (68, 1): ('buttons', _grid(0, 0, 88, 32, 2, 1), 'cycle', (4, 4, 10, 8)),
    (58, 3): ('banner',),
    (58, 13): ('plate', (76, 3, 101, 29), (102, 110), (64, 56, 48), None, 13, 2.2, (76, 3, 160, 29)),
    (58, 14): ('plate', (76, 3, 101, 29), (102, 110), (64, 56, 48), None, 13, 2.2, (76, 3, 160, 29)),
    (58, 15): ('plate', (76, 3, 101, 29), (102, 110), (64, 56, 48), None, 13, 2.2, (76, 3, 160, 29)),
    (61, 2): ('buttons', _grid(0, 0, 24, 16, 4, 8), 'cycle', 2),
    **{(61, k): ('buttons', [(0, 0, 55, 39)], 'list', (5, 5, 8, 8)) for k in range(5, 21)},
    # mini-game screens: counters (52 mining, 59/60 archery), headers (51 waterway, 53 building)
    (51, 1): ('plates', [((146, 96, 167, 115), (128, 140), (110, 96, 167, 115), 'right', 12, 2.0),
                         ((199, 88, 243, 109), (244, 248), (194, 88, 250, 109), 'center', 12, 2.2)]),
    (52, 1): ('plates', [((36, 365, 174, 384), (176, 186), (36, 364, 186, 385), 'left', 12, 2.2),
                         ((158, 396, 182, 415), (120, 140), None, 'left', 12, 2.2)]),
    (53, 1): ('plates', [((144, 87, 196, 109), (200, 215), (110, 87, 229, 109), 'center', 13, 2.4)]),
    (59, 4): ('plates', [((36, 365, 150, 384), (152, 172), (36, 364, 186, 385), 'left', 12, 2.2),
                         ((158, 396, 182, 415), (120, 140), None, 'left', 12, 2.2)]),
    (60, 9): ('plates', [((36, 365, 150, 384), (152, 172), (36, 364, 186, 385), 'left', 12, 2.2),
                         ((158, 396, 182, 415), (120, 140), None, 'left', 12, 2.2),
                         ((57, 321, 78, 342), (49, 53), (52, 321, 84, 342), 'center', 11, 2.0),
                         ((254, 322, 274, 342), (276, 280), (244, 321, 278, 342), 'center', 11, 2.0)]),
    # horse race records: column headers (No. is already English)
    **{(77, k): ('plates', [((44, 10, 92, 34), (150, 190), (45, 10, 200, 34), 'left', 16, 2.8),
                            ((200, 10, 341, 34), (150, 190), (202, 10, 355, 34), 'left', 16, 2.8),
                            ((355, 10, 425, 34), (150, 190), (357, 10, 470, 34), 'left', 16, 2.8)])
       for k in (0, 2)},
    # clan strategy panel (78.14) and mission report header (78.15)
    (78, 14): ('plates', [((15, 10, 72, 30), 'inpaint', (17, 10, 150, 30), 'left', 12, 2.4),
                          ((15, 37, 68, 56), 'inpaint', (17, 37, 150, 56), 'left', 12, 2.4),
                          ((15, 76, 67, 96), 'inpaint', (17, 76, 150, 96), 'left', 12, 2.4)]),
    (78, 15): ('plates', [((33, 10, 70, 27), (100, 120), (35, 10, 150, 27), 'left', 12, 2.4),
                          ((156, 10, 190, 27), (100, 120), (158, 10, 280, 27), 'left', 12, 2.4),
                          ((282, 10, 316, 27), (330, 350), (284, 10, 390, 27), 'left', 12, 2.4)]),
    (95, 0): ('banner',), (95, 1): ('banner',),
    (101, 0): ('mixed', [('glyphs', (26 * k, 180, 26 * k + 25, 206)) for k in range(7)]
               + [('glyphs', (x0, y0, x1, y0 + 29)) for y0 in (208, 239)
                  for x0, x1 in ((0, 45), (47, 94), (95, 139), (140, 186))]),
    (101, 1): ('banner',), (101, 2): ('banner',), (101, 3): ('banner',),
    (101, 5): ('banner',), (101, 6): ('banner',), (101, 7): ('banner',),
    **{(67, k): ('banner',) for k in range(13)},
}

def load_tl():
    out = {}
    if os.path.exists(TL):
        for line in open(TL, encoding='ascii').read().splitlines():
            if line.strip() and not line.startswith('#'):
                k, _, v = line.partition('\t')
                e, _, t = k.partition('.')
                out[int(e), int(t)] = v
    return out

def redraw(tex, item, text):
    cv = Canvas(tex)
    if item[0] == 'banner':
        banner(cv, text)
    elif item[0] == 'mixed':
        for (kind, box), t in zip(item[1], text.split('|')):
            (glyph if kind == 'glyphs' else label)(cv, box, t)
    elif item[0] == 'plates':
        # several spots on one panel: (erase area, sample columns, text area, align, cap, stroke)
        for (area, sample, tarea, align, cap, stroke), t in zip(item[1], text.split('|')):
            plate(cv, area, sample, t, None, None, cap, stroke, align=align, text_area=tarea)
    elif item[0] == 'buttons':
        texts = text.split('|')
        for k, cell in enumerate(item[1]):
            t = {'cycle': lambda: texts[k % len(texts)], 'rows': lambda: texts[k // 4],
                 'list': lambda: texts[k]}[item[2]]()
            button(cv, cell, t, item[3])
    elif item[0] == 'glyphs':
        for box in item[1]:
            glyph(cv, box, text)
    elif item[0] == 'labels':
        for box, t in zip(item[1], text.split('|')):
            label(cv, box, t)
    else:
        _, area, sample, ink, edge, cap, stroke, *more = item
        plate(cv, area, sample, text, ink, edge, cap, stroke, text_area=more[0] if more else None)
    return cv.tex()

def apply(elf, entry):
    """-> {entry: new bytes}; entry(i) = clean TAI5DATA entry. Rewrites offset tables in elf."""
    tl = load_tl()
    by_entry = collections.defaultdict(dict)
    for (e, t), text in tl.items():
        by_entry[e][t] = text
    out = {}
    for e, items in sorted(by_entry.items()):
        clean = entry(e)
        texs = tk5p.split(elf, clean)
        for t, text in items.items():
            texs[t] = redraw(texs[t], ITEMS[e, t], text)
        out[e] = tk5p.join(elf, clean, texs)
    return out

def to_image(tex):
    cv = Canvas(tex)
    im = Image.new('RGBA', (cv.w, cv.h))
    im.putdata([tuple(cv.pal[i][:3]) + (min(255, cv.pal[i][3] * 2),) for i in cv.pix])
    return im

if __name__ == '__main__':
    # gfx.py preview out.png: every item of tl/gfx.txt on a checker background
    import datafile, mmap
    elf = bytearray(open(os.path.join(ROOT, 'extract', 'SLPM_656.74'), 'rb').read())
    f = open(os.path.join(ROOT, 'extract', 'TAI5DATA.DAT'), 'rb')
    d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    clean = bytes(elf)
    ims = []
    for (e, t), text in sorted(load_tl().items()):
        texs = tk5p.split(clean, datafile.entry(d, clean, e))
        ims.append(to_image(redraw(texs[t], ITEMS[e, t], text)))
    W = 1100
    x = y = rowh = 0
    pos = []
    for im in ims:
        if x + im.width > W:
            x, y, rowh = 0, y + rowh + 6, 0
        pos.append((x, y))
        x += im.width + 6
        rowh = max(rowh, im.height)
    sheet = Image.new('RGBA', (W, y + rowh), (60, 90, 120, 255))
    for im, p in zip(ims, pos):
        sheet.alpha_composite(im, p)
    sheet.save(sys.argv[2])
