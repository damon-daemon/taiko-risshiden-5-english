"""Translation helper for TAI5MSG: show units, validate + wrap + apply English.

A message is split into text units by tools/msgscript.py: the runs of text between
structural codes (conditions, END, variant/register commands). Only units are
translated; the structure around them is kept byte for byte.

tl/msgNN.txt holds the English (no Japanese), one block per unit:

    # comment (a line starting with #; English text never does)
    @<entry>          unit 0 of the entry (same as @<entry>.0)
    @<entry>.<unit>
    English text, possibly over several physical lines (joined with spaces).

  \\n or ||  forced line break        \\_  a space that line stripping would eat
  =          (whole block) keep the Japanese of this unit
  Inline codes are copied from `show` as printed ({02}{01}d = a variable,
  {01}C1{00} = insert msg00 entry 0x31, {1B}C3..{1B}C0 = colour, %w = field filled
  in by the game). They may move; {01}C/{02} inserts may be dropped (word endings,
  pronouns), not added. Kana toggles ({1B}K {1B}H {1B}k) are dropped from English.
  A '%' that is not one of the unit's %-fields becomes full-width ％.

Units are word-wrapped (proportional widths from tools/latinfont.py) to the box of
their block and checked: <= LINE_BYTES bytes per line (message window run buffer),
lines per page, and the whole message re-parsed must keep the Japanese structure.

usage:
    tl.py show  NN [from] [to]     # print Japanese units (codes visible) to translate
    tl.py apply NN [batch.txt]     # merge batch into tl/msgNN.txt, validate, rebuild
                                   # script/msg/msgNN.json (no batch: tl/msgNN.txt only)
    tl.py stats                    # progress per block
"""
import collections, json, os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
import latinfont, msgfile, msgscript, setup, text

ROOT = setup.ROOT
TL = setup.TL

# Boxes per block: (width px, lines per page). Blocks not listed use FIT: each unit is
# wrapped to its widest Japanese line (at least the block's usual line width) and may
# not have more lines than the Japanese. Measured: msg21 in the message window
# (480 px, 3 lines a page; it wraps longer lines itself, so a unit may fill as many
# pages as its Japanese does when shown). The other window blocks are assumed from
# their Japanese (lines <= ~400 px, <= 3 lines); check them in the emulator.
WINDOW = (480, 3)
BOXES = {n: WINDOW for n in list(range(17)) + [21, 24]}
# msg22 #0-457 = item/treasure descriptions: the same 20px-font panel as the card texts
# (wraps by character at 320 px, 5 lines; measured 2026-10-28 on the Valuables detail).
BOXES[23] = (360, 5)   # msg23 card descriptions (same panel as msg22; see NOT_WINDOW)
BOXES[25] = (396, 11)  # msg25 battle advisor panel: widest Japanese line / most lines in the block
BOXES[26] = (420, 9)   # msg26 battle advisor (castle defense lines)
BOXES[27] = (420, 9)   # msg27 #0-165 battle advisor (low-troop lines); see NOT_WINDOW/ENTRY_BOXES
# msg28-32 = officer bios on the main-menu Card List hero cards (dates line, then a paragraph):
# a 20px-font panel that wraps by character at ~440 px and holds 6 lines (measured 2026-10-28).
# More lines run off the panel and corrupt memory (issue #8: menus vanish, loading hangs).
for _n in range(28, 33): BOXES[_n] = (410, 6, 'small')
# Entries of window blocks shown elsewhere (FIT mode instead of the window box):
# msg08 #402-438 = main-menu / new-officer help panels, msg10 #350+ = facility guide,
# msg11 #531-603 = battle and merchant-war guide, #789-822 = aptitude results, duel guide.
NOT_WINDOW = {8: range(402, 439), 10: range(350, 1000), 11: {*range(531, 604), *range(789, 823)},
              22: range(458, 1000),  # msg22 #458+ = town descriptions (wider panel)
              # msg23: #0-83 one-line technique effects, #305-368 battle tactics, #424+ bios
              23: {*range(0, 84), *range(305, 369), *range(424, 1000)},
              24: range(215, 1000),  # msg24 #215+ = mission help pages
              27: range(166, 181)}   # msg27 #166-180 = tea-ware crafting prompts
# Entries with their own box inside a block: msg27 #181+ = tea-party dialogue (message window).
# msg00 #445-449 = profession blurbs on the hero-select screen (panel wraps at ~340 px, 3 lines;
# measured 2026-10-18).
ENTRY_BOXES = {27: [(range(181, 1000), WINDOW)], 0: [(range(445, 450), (336, 3))]}
# msg17-20 #0-199 = officer bios (dates line, then a paragraph): shown in the hero/officer
# Biography tab, a 20px-font panel that wraps by character at ~220 px (measured
# 2026-10-18: "Seng|oku"), 12 lines fit (no scrolling: more run off the panel).
for _n in range(17, 21):
    ENTRY_BOXES.setdefault(_n, []).append((range(0, 200), (216, 12, "small")))
# msg23 #84-423 = card texts (titles, sights, techniques, battle tactics, other cards) on the
# main-menu Card List: a 20px-font panel that wraps by character at 320 px and holds 5 lines
# (measured 2026-10-28, issue #8); no dates line.
ENTRY_BOXES.setdefault(23, []).append((range(84, 424), (310, 5, 'small', 0)))
ENTRY_BOXES.setdefault(22, []).append((range(0, 458), (310, 5, 'small', 0)))
# Panels not measured yet: text past a fixed panel corrupts memory (issue #8), so these units
# keep to their Japanese: no line wider than its widest line in the 24px or the 20px font, and
# no more lines. (msg24 #0-214 is the message window, which pages itself.)
STRICT = {**{n: range(200, 1000) for n in range(17, 21)}, 22: range(458, 1000),
          23: {*range(0, 84), *range(424, 1000)}, 24: range(215, 1000),
          25: range(1000), 26: range(1000), 27: range(181)}
LINE_BYTES = 120          # layout warning only: msgwindow caps a run at 127 bytes in code
FULL_PX, HALF_PX = 24, 12  # full-width / half-width (kana) cells in the 24px font
VAR_PX, VAR_BYTES = 120, 20   # an inserted name or number ({02} print)
FIELD_PX, FIELD_BYTES = 40, 8  # %w-style field
FLOW_PX = 700             # wider Japanese lines are paragraphs the text object flows

KANA_TOGGLE = re.compile(rb'\x1b[KHk]')
FULL_LATIN = re.compile('[０-９Ａ-Ｚａ-ｚ]')

_W = {}
FONT = 'large'            # font of the box being wrapped (a 3rd element of a box sets it)

def widths():
    if FONT not in _W:
        _W[FONT] = {c: g[1] for c, g in latinfont.render(FONT).items()}
    return _W[FONT]

# ---------------------------------------------------------------- script access

def load(n):
    return json.load(open(setup.msg_json(n), encoding='utf-8'))

def save(n, rows):
    json.dump(rows, open(setup.msg_json(n), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

_ROWS = {}

def rows_of(n):
    if n not in _ROWS:
        _ROWS[n] = load(n)
    return _ROWS[n]

def target(lo, hi):
    """Message inserted by {01}C / {01}J lo hi -> (block, entry)."""
    i = lo | hi << 8
    return (0, i) if i < 1000 else (i // 1000, i % 1000)

# ---------------------------------------------------------------- measuring

def insert_size(code, depth=0):
    """(px, bytes) of an inline code when shown."""
    k = code[0]
    if k == 0x02:
        return VAR_PX, VAR_BYTES
    if k == 0x25:
        return FIELD_PX, FIELD_BYTES
    if k == 0x01 and len(code) == 4 and depth < 3:
        b, e = target(code[2], code[3])
        try:
            row = rows_of(b)[e]
        except (IndexError, FileNotFoundError):
            return 0, 0
        s = text.encode(row['en'] or row['jp'])
        toks, spans = msgscript.units(s)
        best = (0, 0)
        for a, z in spans:
            first = []
            for kind, t in toks[a:z]:
                if kind == 'nl':
                    break
                first.append((kind, t))
            best = max(best, measure(first, depth + 1))
        return best
    return 0, 0

def measure(toks, depth=0):
    """(px, bytes) of one line given as tokens."""
    px = nb = 0
    W = widths()
    for kind, t in toks:
        if kind == 'text':
            i = 0
            while i < len(t):
                c = t[i]
                if msgscript._sjis_lead(c) and i + 1 < len(t):
                    px += FULL_PX; nb += 2; i += 2
                    continue
                px += W.get(chr(c), HALF_PX) if c < 0x80 else HALF_PX
                nb += 1; i += 1
        elif kind == 'inline':
            p, b = insert_size(t, depth)
            px += p; nb += b
    return px, nb

def jp_px(toks):
    """Width of a Japanese line in the 24px font as the game shows it: half-width kana stand
    for full-width hiragana, the voicing marks combine with them."""
    px = 0
    for kind, t in toks:
        if kind == 'text':
            i = 0
            while i < len(t):
                c = t[i]
                if msgscript._sjis_lead(c) and i + 1 < len(t):
                    px += FULL_PX; i += 2; continue
                px += FULL_PX if 0xA1 <= c <= 0xDD else 0 if c in (0xDE, 0xDF) else HALF_PX
                i += 1
        elif kind == 'inline':
            px += insert_size(t)[0]
    return px

_ENDS = {}

def ends_line(code):
    """True if a {01}C/J insert's text ends with a newline (the line ends there)."""
    if not (code[0] == 0x01 and len(code) == 4):
        return False
    if code not in _ENDS:
        b, e = target(code[2], code[3])
        try:
            row = rows_of(b)[e]
        except (IndexError, FileNotFoundError):
            _ENDS[code] = False
            return False
        toks, spans = msgscript.units(text.encode(row['en'] or row['jp']))
        _ENDS[code] = any(toks[z - 1][0] == 'nl' for a, z in spans)
    return _ENDS[code]

def lines_of(toks):
    """Split tokens into display lines; a line ended by an insert that itself ends
    with a newline gets a ('soft', b'') marker (no newline is written after it)."""
    out, cur = [], []
    for kind, t in toks:
        if kind == 'nl':
            out.append(cur); cur = []
        else:
            cur.append((kind, t))
            if kind == 'inline' and ends_line(t):
                out.append(cur + [('soft', b'')]); cur = []
    return out + [cur]

def join_lines(lines):
    out = b''
    for i, l in enumerate(lines):
        out += b''.join(t for k, t in l)
        if i < len(lines) - 1 and not (l and l[-1][0] == 'soft'):
            out += b'\n'
    return out

# ---------------------------------------------------------------- wrapping

def words(toks):
    """Split a token line into words (lists of tokens) at ASCII spaces."""
    out, cur = [], []
    for kind, t in toks:
        if kind != 'text':
            cur.append((kind, t)); continue
        parts = t.split(b' ')
        for j, p in enumerate(parts):
            if j:
                out.append(cur); cur = []
            if p:
                cur.append(('text', p))
    out.append(cur)
    return [w for w in out if w]

def join(ws):
    toks = []
    for j, w in enumerate(ws):
        if j:
            toks.append(('text', b' '))
        toks += w
    return toks

def wrap(toks, width):
    """Word-wrap tokens (with 'nl' forced breaks) -> list of lines (token lists)."""
    out = []
    for para in lines_of(toks):
        line = []
        for w in words(para):
            if line and measure(join(line + [w]))[0] > width:
                out.append(join(line)); line = [w]
            else:
                line.append(w)
        out.append(join(line))
    return out

class Box:
    def __init__(self, n, rows):
        self.n = n
        self.fixed = BOXES.get(n)
        ws = []
        for r in rows:
            toks, spans = msgscript.units(text.encode(r['jp']))
            for a, z in spans:
                ls = lines_of(toks[a:z])
                if len(ls) > 1:
                    ws += [measure(l)[0] for l in ls if measure(l)[0] <= FLOW_PX]
        ws.sort()
        self.floor = ws[len(ws) * 3 // 4] if ws else 0

    def limits(self, jp_toks, entry=None):
        """(width px, max lines, lines per page or 0) for a unit."""
        jl = [measure(l)[0] for l in lines_of(jp_toks)]
        global FONT
        if entry in STRICT.get(self.n, ()):
            # wrapped in the 20px font at the Japanese width in that font: the English is
            # narrower than that in the 24px font too
            FONT = 'small'
            jl = [jp_px(l) for l in lines_of(jp_toks)]
            manual = [x for x in jl if x <= FLOW_PX]
            if len(manual) < len(jl):
                return max([self.floor] + manual) * 20 // 24, 10 ** 6, 0
            return max(jl) * 20 // 24, len(jl), 0
        fixed = next((b for r, b in ENTRY_BOXES.get(self.n, ()) if entry in r), None)
        if not fixed and entry not in NOT_WINDOW.get(self.n, ()):
            fixed = self.fixed
        FONT = fixed[2] if fixed and len(fixed) > 2 else 'large'
        if fixed:
            # the window wraps long lines itself: count the lines as shown
            w, page = fixed[:2]
            if len(fixed) > 2:          # a fixed panel: page = all the lines it holds
                head = fixed[3] if len(fixed) > 3 else 1
                return w, page + head, page  # + the dates line (bios), which goes to its own field
            shown = sum(max(1, -(-x // w)) for x in jl)
            return w, -(-shown // page) * page, page
        manual = [x for x in jl if x <= FLOW_PX]
        flowing = len(manual) < len(jl)
        return max([self.floor] + manual), 10 ** 6 if flowing else len(jl), 0

# ---------------------------------------------------------------- tl files

KEY = re.compile(r'@(\d+)(?:-(\d+))?(?:\.(\d+|\*))?\s*')

def parse_tl(path):
    """-> {key: text}, key as written without '@': '12', '12.3', '12.*' or '63-99.*'."""
    out, key, buf = {}, None, []
    def flush():
        if key is not None:
            out[key] = ' '.join(buf)
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        m = KEY.fullmatch(line)
        if m:
            flush()
            a, b, u = m.groups()
            if b and u != '*':
                sys.exit('%s: %s: a range needs .*' % (path, line))
            key = '%s%s%s' % (a, '-' + b if b else '', '.' + u if u and u != '0' else '')
            buf = []
        elif line.lstrip().startswith('#'):
            continue
        elif key is not None and line.strip():
            buf.append(line.strip())
    flush()
    return out

def _key_order(k):
    m = re.fullmatch(r'(\d+)(?:-(\d+))?(?:\.(\d+|\*))?', k)
    a, b, u = m.groups()
    return int(a), int(b or a), -1 if u == '*' else int(u or 0)

def expand(units, rows):
    """{key: text} -> {(entry, unit): text}; explicit units beat N.*, which beats ranges."""
    out = {}
    spec = sorted(units, key=lambda k: (('-' not in k) + ('*' not in k), _key_order(k)))
    for k in spec:
        a, b, u = _key_order(k)
        for e in range(a, (b if a == b else min(b, len(rows) - 1)) + 1):
            if u >= 0 or e >= len(rows):
                out[(e, max(u, 0))] = units[k]
            else:
                n = len(msgscript.units(text.encode(rows[e]['jp']))[1])
                for i in range(n):
                    out[(e, i)] = units[k]
    return out

def write_tl(path, new):
    """Merge {key: text} into a tl file: existing blocks are replaced in place (comments
    and order kept), new ones appended in key order."""
    lines = open(path, encoding='utf-8').read().split('\n') if os.path.exists(path) else []
    out, i, done = [], 0, set()
    while i < len(lines):
        m = KEY.fullmatch(lines[i])
        key = None
        if m:
            a, b, u = m.groups()
            key = '%s%s%s' % (a, '-' + b if b else '', '.' + u if u and u != '0' else '')
        if key in new:
            out += [lines[i], new[key]]
            done.add(key)
            i += 1
            while i < len(lines) and lines[i].strip() and not KEY.fullmatch(lines[i]) \
                    and not lines[i].lstrip().startswith('#'):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    while out and out[-1] == '':
        out.pop()
    for k in sorted(set(new) - done, key=_key_order):
        out += ['@' + k, new[k]]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')

def english_bytes(src, jp_unit):
    """Batch text -> bytes: codes decoded, kana toggles dropped (a leading one is kept
    when the Japanese has it: it separates text from a number before it), '%' that
    is not one of the Japanese %-fields made full-width."""
    s = src.replace(' || ', '\n').replace('||', '\n').replace('\\n ', '\n').replace('\\n', '\n')
    s = s.replace('\\_', ' ').replace(' \n', '\n')
    b = text.encode(s)
    lead = KANA_TOGGLE.match(jp_unit)
    b = (lead.group() if lead else b'') + KANA_TOGGLE.sub(b'', b)
    fields = {t for k, t in msgscript.tokens(jp_unit) if k == 'inline' and t[:1] == b'%'}
    return b''.join(t if k != 'inline' or t[:1] != b'%' or t in fields else '％'.encode('cp932') + t[1:]
                    for k, t in msgscript.tokens(b))

# ---------------------------------------------------------------- validation

def code_str(t):
    """A code as written in tl/ files: printable ASCII as is, other bytes {XX}."""
    return ''.join(chr(c) if 0x20 <= c <= 0x7E and c not in (0x7B, 0x7D) else '{%02X}' % c for c in t)

def unit_str(toks):
    """Japanese unit for display: text decoded, codes via code_str, kana toggles dropped."""
    return ''.join(text.decode(t) if k in ('text', 'nl') else '' if KANA_TOGGLE.fullmatch(t) else code_str(t)
                   for k, t in toks)

def inline_codes(toks):
    return collections.Counter(t for k, t in toks if k == 'inline' and not KANA_TOGGLE.fullmatch(t))

DROPPABLE = (0x02, 0x25)

def check_unit(jp_toks, en):
    errs, warns = [], []
    try:
        et = msgscript.tokens(en)
    except msgscript.ParseError as e:
        return ['parse: %s' % e], warns, None
    bad = [t for k, t in et if k not in msgscript.INLINE]
    if bad:
        errs.append('structural code in English: %s' % ' '.join(code_str(t) for t in bad))
    jc, ec = inline_codes(jp_toks), inline_codes(et)
    extra = ec - jc
    for t in extra.elements():
        if t[0] == 0x02 and len(t) == 3:
            warns.append('added variable %s' % code_str(t))
        else:
            errs.append('code not in the Japanese: %s' % code_str(t))
    for t, n in (jc - ec).items():
        if t[0] == 0x01 and t[1] == 0x43 or t[0] in DROPPABLE:
            if t[0] == 0x02:
                warns.append('dropped variable %s' % code_str(t))
        else:
            errs.append('missing code %s' % code_str(t))
    if FULL_LATIN.search(en.decode('cp932', 'replace')):
        errs.append('full-width Latin/digits in English')
    return errs, warns, et

def build_entry(jp, units_en, box, tag, log):
    """Substitute English units into one message. -> en string ('' if none)."""
    global FONT
    jb = text.encode(jp)
    toks, spans = msgscript.units(jb)
    out = [t for k, t in toks]
    used = False
    for u, (a, z) in enumerate(spans):
        src = units_en.pop(u, None)
        if src is None:
            continue
        if src.strip() == '=':
            used = True
            continue
        jp_unit = b''.join(t for k, t in toks[a:z])
        try:
            en = english_bytes(src, jp_unit)
        except ValueError as e:
            log('%s.%d ERROR %s' % (tag, u, e), True); continue
        errs, warns, et = check_unit(toks[a:z], en)
        if et is None or errs:
            for e in errs:
                log('%s.%d ERROR %s' % (tag, u, e), True)
            for w in warns:
                log('%s.%d warn  %s' % (tag, u, w), False)
            continue
        width, max_lines, page = box.limits(toks[a:z], int(tag.split('@')[1]))
        lines = wrap(et, width)
        for i, l in enumerate(lines):
            px, nb = measure(l)
            if px > width:
                warns.append('line %d is %d px > %d' % (i + 1, px, width))
            if nb > LINE_BYTES:
                warns.append('line %d is %d bytes > %d' % (i + 1, nb, LINE_BYTES))
        strict = int(tag.split('@')[1]) in STRICT.get(box.n, ())
        if strict:
            errs += [w for w in warns if ' px > ' in w]
            warns = [w for w in warns if ' px > ' not in w]
        if len(lines) > max_lines:
            (errs if strict else warns).append('%d lines > %d%s' % (len(lines), max_lines, ' (%d a page)' % page if page else ''))
        if errs:
            for e in errs:
                log('%s.%d ERROR %s' % (tag, u, e), True)
            for w in warns:
                log('%s.%d warn  %s' % (tag, u, w), False)
            continue
        for w in warns:
            log('%s.%d warn  %s' % (tag, u, w), False)
        new = join_lines(lines)
        for i in range(a, z):
            out[i] = b''
        out[a] = new
        used = True
    for u in units_en:
        log('%s.%d ERROR no such unit (entry has %d)' % (tag, u, len(spans)), True)
    if not used:
        return ''
    nb = b''.join(out)
    # the rebuilt message must parse to the same structure as the Japanese
    try:
        new_struct = [t for k, t in msgscript.tokens(nb) if k not in msgscript.INLINE]
    except msgscript.ParseError as e:
        log('%s ERROR rebuilt message does not parse: %s' % (tag, e), True)
        return ''
    if new_struct != [t for k, t in toks if k not in msgscript.INLINE]:
        log('%s ERROR English changes the message structure (text after a code eaten as '
            'its argument? a digit right after a condition number needs {1B}H before it)' % tag, True)
        return ''
    return text.decode(nb)

def apply(n, batch=None, check=True):
    path = os.path.join(TL, 'msg%02d.txt' % n)
    units = parse_tl(path) if os.path.exists(path) else {}
    if batch and os.path.abspath(batch) != os.path.abspath(path):
        new = parse_tl(batch)
        units.update(new)
        print('msg%02d: %d blocks from %s' % (n, len(new), batch))
    rows = load(n)
    _ROWS[n] = rows
    box = Box(n, rows)
    per = collections.defaultdict(dict)
    for (e, u), src in expand(units, rows).items():
        per[e][u] = src
    bad = []
    def log(msg, err):
        print(msg)
        if err:
            bad.append(msg)
    # two passes: an insert of a later entry of this block is measured as its English
    # from the first (silent) pass, not as its Japanese
    for r in rows:
        r['en'] = ''
    first = {e: build_entry(rows[e]['jp'], dict(us), box, 'msg%02d@%d' % (n, e), lambda m, err: None)
             for e, us in per.items() if e < len(rows)}
    for e, en in first.items():
        rows[e]['en'] = en
    for e, us in sorted(per.items()):
        if e >= len(rows):
            log('msg%02d@%d ERROR no such entry' % (n, e), True); continue
        rows[e]['en'] = build_entry(rows[e]['jp'], dict(us), box, 'msg%02d@%d' % (n, e), log)
    if check and not bad:
        # buffer limits (overflow.py): every message that reaches a fixed buffer, with
        # this block's new English (inserts cross blocks, so all of them are measured)
        import overflow
        base = overflow.json_getter()
        def get(b, i):
            if b == n:
                return text.encode(rows[i]['en'] or rows[i]['jp']) if i < len(rows) else None
            return base(b, i)
        elf = overflow.clean_elf()
        known = set(overflow.check_messages(base, elf))   # other blocks' errors are theirs
        for x in overflow.check_messages(get, elf):
            if x not in known or x.startswith('msg%02d ' % n):
                log('ERROR ' + x, True)
    if bad and batch:
        print('msg%02d: %d errors: nothing written' % (n, len(bad)))
    else:
        save(n, rows)
        if batch and os.path.abspath(batch) != os.path.abspath(path):
            os.makedirs(TL, exist_ok=True)
            write_tl(path, new)
    total = sum(len(msgscript.units(text.encode(r['jp']))[1]) for r in rows)
    print('msg%02d: %d/%d units translated, %d errors' % (n, len(expand(units, rows)), total, len(bad)))
    return not bad

# ---------------------------------------------------------------- show / stats

def context(toks, a):
    """What leads to a unit: the structural code just before it."""
    for k, t in reversed(toks[:a]):
        if k == 'if':
            return 'if ' + text.decode(t[3:])
        if k == 'end':
            return 'else'
        if k == 'cmd':
            return text.decode(t)
        if k not in msgscript.INLINE:
            break
    return ''

def show(n, a=0, b=None):
    rows = load(n)
    path = os.path.join(TL, 'msg%02d.txt' % n)
    done = expand(parse_tl(path), rows) if os.path.exists(path) else {}
    for r in rows[a:b]:
        toks, spans = msgscript.units(text.encode(r['jp']))
        for u, (x, z) in enumerate(spans):
            jp = unit_str(toks[x:z])
            ctx = context(toks, x)
            print('@%d%s%s%s  %s' % (r['id'], '.%d' % u if u else '', ' [done]' if (r['id'], u) in done else '',
                                     '  # ' + ctx if ctx else '', jp.replace('\n', '⏎')))

def stats():
    tot = done = 0
    for n in range(len(os.listdir(os.path.join(setup.SCRIPT, 'msg')))):
        rows = load(n)
        t = sum(len(msgscript.units(text.encode(r['jp']))[1]) for r in rows)
        path = os.path.join(TL, 'msg%02d.txt' % n)
        d = len(expand(parse_tl(path), rows)) if os.path.exists(path) else 0
        tot += t; done += d
        print('msg%02d %5d/%5d' % (n, d, t))
    print('total %d/%d units' % (done, tot))

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'show':
        show(int(sys.argv[2]), *(int(x) for x in sys.argv[3:5]))
    elif cmd == 'apply':
        sys.exit(0 if apply(int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    elif cmd == 'stats':
        stats()
    else:
        sys.exit(__doc__)
