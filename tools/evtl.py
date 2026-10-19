"""Translation helper for the event scripts (TAI5DATA 244-574, see tools/evscript.py).

tl/ev/NNN.txt holds the English of entry NNN (no Japanese), one block per string:

    # comment
    @<script>.<n>     string n (0, 1, ... in script order) of script <script>
    English text, possibly over several physical lines (joined with spaces).

  \\n or ||  forced line break        \\_  a space that line stripping would eat
  =          (whole block) keep the Japanese
  Escapes are copied from `show` as printed and may move: \\#XXXX person name
  (XXXX & 0x7FF = person id; +0x800 given name, +0x1000 family name), \\%NN pronoun /
  address word (msg00 entry, English already; \\%02 \\%04 \\%20 take 3 more hex digits,
  a person id), \\&NN, \\Xnnn (dates, ages, places, numbers...). \\%NN may be dropped,
  the others must stay. '%' becomes full-width ％ (the message window treats it as a
  control character).

Dialogue (11, 12, 13, 5A text) is wrapped to the message window (480 px, 3 lines a
page) and may use as many pages as the Japanese; choices (15) and labels (1E 4A 42)
must fit the widest Japanese line; names (5A speaker, 3C) at most 8 bytes each.

usage:
    evtl.py show  NNN [script] [--todo]   # print the Japanese strings (--todo: only the
                                   # ones without English, own or from an identical twin)
    evtl.py apply NNN [batch.txt]  # merge a batch into tl/ev/NNN.txt and validate
    evtl.py stats                  # progress per entry
    evtl.py names                  # name pairs (5A / 3C) still without English
"""
import functools, json, os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
import evscript, setup, text, tl

ROOT = setup.ROOT
TL_EV = os.path.join(setup.TL, 'ev')

WINDOW = (480, 3)
NARRATION = (432, 3)
LABEL_PX = {0x15: 240}           # choice menu items (assumed; verify)            # 13: centred narration box (estimated 2026-10-18; verify)
DIALOGUE = {0x11, 0x12, 0x13}   # + the text (third string) of 5A
NAME_BYTES = 8                  # 5A speaker / 3C names: 9-byte fields
LINE_BYTES = tl.LINE_BYTES
FULL_PX, HALF_PX = 24, 12
NAME_PX, NAME_BYTES_DEFAULT = 150, 20     # a person whose English name is unknown (hero...)
VAR_PX, VAR_BYTES = 80, 12                # \Xnnn values (numbers, places, dates)

ESC = re.compile(rb'\\(#[0-9A-Fa-f]{4}|%(?:02|04|20)[0-9A-Fa-f]{3}|%[0-9A-Fa-f]{2}|&[0-9A-Fa-f]{2}'
                 rb'|[0-9;<=>?A-Za-z][0-9A-Fa-f]{3})')
PRONOUN = 0x547720              # jump table of the \% cases: index -> msg00 entry
FULL_LATIN = re.compile('[０-９Ａ-Ｚａ-ｚ]')

# ---------------------------------------------------------------- data access

@functools.lru_cache(None)
def _source():
    """-> function(entry) -> bytes of the clean TAI5DATA entry."""
    ext = os.path.join(ROOT, 'extract')
    import datafile, iso
    if os.path.exists(os.path.join(ext, 'TAI5DATA.DAT')):
        elf = open(os.path.join(ext, 'SLPM_656.74'), 'rb').read()
        f = open(os.path.join(ext, 'TAI5DATA.DAT'), 'rb')
        rows = datafile.toc(elf)
        def get(i):
            s, z = rows[i]
            f.seek(s * 2048)
            return f.read(z)
        return get, elf
    recs = iso.records(setup.CLEAN)
    elf = iso.read_file(setup.CLEAN, 'SLPM_656.74', recs)
    data = iso.read_file(setup.CLEAN, 'TAI5DATA.DAT', recs)
    return (lambda i: datafile.entry(data, elf, i)), elf

def clean_entry(i):
    return _source()[0](i)

@functools.lru_cache(None)
def pronouns():
    elf = _source()[1]
    word = lambda va: int.from_bytes(elf[va - 0x100000 + 0x80:va - 0x100000 + 0x84], 'little')
    out = {}
    for i in range(0x34):
        w = word(word(PRONOUN + 4 * i) + 4)
        if w >> 16 == 0x2410:          # addiu s0, zero, N
            out[i] = w & 0xFFFF
    return out

@functools.lru_cache(None)
def person_names():
    """person id -> list of English full names (all scenario variants)."""
    out = {}
    for r in json.load(open(os.path.join(setup.TL, 'names_persons.json'), encoding='utf-8')):
        forms = [r['en']] + [v for k, v in r.items() if re.fullmatch(r's\d+', k)]
        out[r['id']] = [f for f in forms if isinstance(f, list)]
    return out

def units(entry):
    """-> [(script, n, ins, j)] for every string of the entry."""
    e = evscript.Entry(clean_entry(entry))
    out = []
    for k, (items, _) in enumerate(e.scripts):
        for n, (path, ins, j) in enumerate(evscript.strings(items)):
            out.append((k, n, ins, j))
    return e, out

def kind(ins, j):
    if ins.op in DIALOGUE or ins.op == 0x5A and j == 2:
        return 'dialogue'
    if ins.op == 0x3C or ins.op == 0x5A:
        return 'name'
    return 'label'

# ---------------------------------------------------------------- names
#
# 5A (dialogue with a temporary speaker name) and 3C (rename a person) carry Japanese
# name parts; the game copies them into a person's 9-byte name record. They are not
# translated per string: a pair known from tl/names_persons.json gets the record form
# names.py gives it (the name lookup then shows the full English); other pairs are
# listed once in tl/ev/names.txt, keyed by their first occurrence:
#     @<entry>.<script>.<n>      n = the string number of the family part
#     Family|Given               either may be empty; shown as "Family Given"
# 3C's kana readings are cleared (the reading line cannot show ASCII).

NAMES_TL = os.path.join(TL_EV, 'names.txt')
NAME_KEY = re.compile(r'@(\d+)\.(\d+)\.(\d+)\s*')

def parse_names(path=NAMES_TL):
    out, key = {}, None
    if not os.path.exists(path):
        return out
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        m = NAME_KEY.fullmatch(line)
        if m:
            key = tuple(map(int, m.groups()))
        elif line and not line.startswith('#') and key:
            fa, _, gi = line.partition('|')
            out[key] = (fa.strip(), gi.strip())
            key = None
    return out

@functools.lru_cache(None)
def event_name_pairs():
    """Japanese (family, given) bytes -> English (family, given) from tl/ev/names.txt."""
    out = {}
    for (entry, k, n), en in parse_names().items():
        try:
            e, us = units(entry)
        except Exception:
            continue
        for kk, nn, ins, j in us:
            if (kk, nn) == (k, n) and j == 0:
                out[(ins.strs[0], ins.strs[1])] = en
    return out

class _FileData:
    def __init__(self, f):
        self.f = f
    def __getitem__(self, s):
        self.f.seek(s.start)
        return self.f.read(s.stop - s.start)

@functools.lru_cache(None)
def record_names():
    """Japanese (family, given) -> (family, given) bytes for the 9-byte record."""
    import names
    get, elf = _source()
    ext = os.path.join(ROOT, 'extract', 'TAI5DATA.DAT')
    if os.path.exists(ext):
        data = _FileData(open(ext, 'rb'))
    else:
        import iso
        data = iso.read_file(setup.CLEAN, 'TAI5DATA.DAT')
    pairs, cut = names.name_pairs(data, elf)
    return {jp: cut[tuple(en)] for jp, en in pairs.items()}

def name_units(entry):
    """-> [(script, n, ins, mapped or None)] for every 5A / 3C of the entry."""
    e, us = units(entry)
    rec = record_names()
    return [(k, n, ins, rec.get((ins.strs[0], ins.strs[1])))
            for k, n, ins, j in us if ins.op in (0x5A, 0x3C) and j == 0]

# ---------------------------------------------------------------- measuring

def esc_size(e):
    """(px, bytes) of an escape (without the backslash) when shown in English."""
    c = e[:1]
    if c == b'#':
        v = int(e[1:], 16)
        pid, form = v & 0x7FF, v & 0x3800
        names = person_names().get(pid)
        if not names or form == 0x2000:
            return (0, 0) if form == 0x2000 else (NAME_PX, NAME_BYTES_DEFAULT)
        parts = [n[1] if form == 0x800 else n[0] if form == 0x1000 else '%s %s' % tuple(n)
                 for n in names]
        return max(measure_text(p.encode('cp932'))[0] for p in parts), max(len(p) for p in parts)
    if c == b'%':
        mid = pronouns().get(int(e[1:3], 16))
        if mid is None:
            return 0, 0
        return tl.insert_size(b'\x01C' + bytes([mid & 0xFF, mid >> 8]))
    if c == b'&':
        return NAME_PX, NAME_BYTES_DEFAULT
    return VAR_PX, VAR_BYTES

def measure_text(b):
    W = tl.widths()
    px = nb = i = 0
    while i < len(b):
        c = b[i]
        if (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC) and i + 1 < len(b):
            px += FULL_PX; nb += 2; i += 2
        else:
            px += W.get(chr(c), HALF_PX) if c < 0x80 else HALF_PX
            nb += 1; i += 1
    return px, nb

def measure(line):
    px = nb = 0
    pos = 0
    for m in ESC.finditer(line):
        a, b = measure_text(line[pos:m.start()])
        c, d = esc_size(m.group(1))
        px += a + c; nb += b + d
        pos = m.end()
    a, b = measure_text(line[pos:])
    return px + a, nb + b

def wrap(s, width):
    """Word-wrap bytes s (b'\\n' = forced break) to width px -> list of lines."""
    out = []
    for para in s.split(b'\n'):
        line = b''
        for w in [w for w in para.split(b' ') if w]:
            cand = line + b' ' + w if line else w
            if line and measure(cand)[0] > width:
                out.append(line)
                line = w
            else:
                line = cand
        out.append(line)
    return out

# ---------------------------------------------------------------- tl files

def tl_path(entry):
    return os.path.join(TL_EV, '%03d.txt' % entry)

KEY = re.compile(r'@(\d+)\.(\d+)\s*')

def parse_tl(path):
    """-> {(script, n): text}"""
    out, key, buf = {}, None, []
    def flush():
        if key is not None:
            out[key] = ' '.join(buf)
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        m = KEY.fullmatch(line)
        if m:
            flush()
            key, buf = (int(m.group(1)), int(m.group(2))), []
        elif line.lstrip().startswith('#'):
            continue
        elif key is not None and line.strip():
            buf.append(line.strip())
    flush()
    return out

def write_tl(path, new):
    """Merge {(script, n): text} into a tl file (blocks replaced in place, new ones appended)."""
    lines = open(path, encoding='utf-8').read().split('\n') if os.path.exists(path) else []
    out, i, done = [], 0, set()
    while i < len(lines):
        m = KEY.fullmatch(lines[i])
        key = (int(m.group(1)), int(m.group(2))) if m else None
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
    for k in sorted(set(new) - done):
        out += ['@%d.%d' % k, new[k]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')

# ---------------------------------------------------------------- validation

def english_bytes(src):
    s = src.replace(' || ', '\n').replace('||', '\n').replace('\\n ', '\n').replace('\\n', '\n')
    s = s.replace('\\_', ' ').replace(' \n', '\n')
    return text.encode(re.sub(r'(?<!\\)%', '％', s))

def escapes(b):
    return sorted(m.group(1) for m in ESC.finditer(b))

def check(jp, en, k, op=None):
    """-> (errors, warnings, final bytes)"""
    errs, warns = [], []
    if FULL_LATIN.search(en.decode('cp932', 'replace')):
        errs.append('full-width Latin/digits in English')
    if b'\\' in ESC.sub(b'', en):
        errs.append('backslash that is not an escape')
    je, ee = escapes(jp), escapes(en)
    for x in ee:
        if x in je:
            je.remove(x)
        else:
            errs.append('escape not in the Japanese: \\%s' % x.decode())
    for x in je:
        if x[:1] != b'%':
            errs.append('missing escape \\%s' % x.decode())
    if any(c < 0x20 and c != 0x0A for c in en):
        errs.append('control byte in English')
    if k == 'name':
        errs.append('names are translated in tl/ev/names.txt')
        return errs, warns, en
    if k == 'dialogue':
        width, page = NARRATION if op == 0x13 else WINDOW
        jl = [measure(l)[0] for l in jp.split(b'\n')]
        shown = sum(max(1, -(-x // width)) for x in jl)
        max_lines = -(-shown // page) * page
    else:
        # choices / labels: not wrapped; the menu sizes itself (check the real limits).
        # 1E sets a text variable (\\Z00n, e.g. the hero's career) shown inside other text.
        if op == 0x1E:
            return errs, warns, en
        width = max([LABEL_PX.get(op, 0)] + [measure(l)[0] for l in jp.split(b'\n')])
        max_lines = jp.count(b'\n') + 1
        for i, l in enumerate(en.split(b'\n')):
            if measure(l)[0] > width:
                warns.append('line %d is %d px > %d' % (i + 1, measure(l)[0], width))
        if en.count(b'\n') + 1 > max_lines:
            warns.append('%d lines > %d' % (en.count(b'\n') + 1, max_lines))
        return errs, warns, en
    lines = wrap(en, width)
    for i, l in enumerate(lines):
        px, nb = measure(l)
        if px > width:
            warns.append('line %d is %d px > %d' % (i + 1, px, width))
        if nb > LINE_BYTES:
            warns.append('line %d is %d bytes > %d' % (i + 1, nb, LINE_BYTES))
    if len(lines) > max_lines:
        warns.append('%d lines > %d' % (len(lines), max_lines))
    return errs, warns, b'\n'.join(lines)

def english_entry(entry, units_en, log, use_memory=True):
    """Apply {(script, n): text} to a clean entry -> rebuilt bytes (or None if unchanged).
    use_memory: strings without English take that of an identical Japanese string."""
    e, us = units(entry)
    index = {(k, n): (ins, j) for k, n, ins, j in us}
    changed = False
    rec = record_names()
    for k, n, ins, j in us:
        if ins.op in (0x5A, 0x3C) and j == 0:
            new = rec.get((ins.strs[0], ins.strs[1]))
            if new:
                ins.strs[0], ins.strs[1] = new
                if ins.op == 0x3C:
                    ins.strs[2] = ins.strs[3] = b''
                changed = True
    if use_memory:
        mem = memory()
        units_en = dict(units_en)
        for k, n, ins, j in us:
            if (k, n) not in units_en and kind(ins, j) != 'name':
                src = mem.get((kind(ins, j), ins.strs[j]))
                if src is not None:
                    units_en[(k, n)] = src
    for key, src in sorted(units_en.items()):
        tag = '%03d@%d.%d' % ((entry,) + key)
        if key not in index:
            log('%s ERROR no such string' % tag, True); continue
        if src.strip() == '=':
            continue
        ins, j = index[key]
        try:
            en = english_bytes(src)
        except ValueError as x:
            log('%s ERROR %s' % (tag, x), True); continue
        errs, warns, final = check(ins.strs[j], en, kind(ins, j), ins.op)
        for x in errs:
            log('%s ERROR %s' % (tag, x), True)
        for x in warns:
            log('%s warn  %s' % (tag, x), False)
        if not errs:
            ins.strs[j] = final
            changed = True
    if not changed:
        return None
    try:
        return e.build()
    except evscript.ParseError as x:
        log('%03d ERROR %s' % (entry, x), True)
        return None

def tl_entries():
    out = []
    for name in sorted(os.listdir(TL_EV)) if os.path.isdir(TL_EV) else []:
        m = re.fullmatch(r'(\d{3})\.txt', name)
        if m:
            out.append(int(m.group(1)))
    return out

@functools.lru_cache(None)
def memory():
    """(kind, Japanese) -> English source from every tl/ev file (lowest entry first).
    Case variants repeat a lot of text: one translation serves every copy."""
    mem = {}
    for entry in tl_entries():
        en = parse_tl(tl_path(entry))
        for k, n, ins, j in units(entry)[1]:
            src = en.get((k, n))
            if src is not None and src.strip() != '=':
                mem.setdefault((kind(ins, j), ins.strs[j]), src)
    return mem

def apply(entry, batch=None):
    path = tl_path(entry)
    units_en = parse_tl(path) if os.path.exists(path) else {}
    new = {}
    if batch and os.path.abspath(batch) != os.path.abspath(path):
        new = parse_tl(batch)
        units_en.update(new)
        print('%03d: %d blocks from %s' % (entry, len(new), batch))
    bad = []
    def log(msg, err):
        print(msg)
        if err:
            bad.append(msg)
    data = english_entry(entry, units_en, log, use_memory=False)
    if data is not None and not bad:
        import overflow             # buffer limits (expander buffer, 9-byte name fields)
        for x in overflow.check_events({entry: data}, overflow.Measure(overflow.json_getter())):
            log('ERROR ' + x, True)
    if bad and new:
        print('%03d: %d errors: nothing written' % (entry, len(bad)))
    elif new:
        write_tl(path, new)
    print('%03d: %d/%d strings translated here, %d errors' % (entry, len(units_en), len(units(entry)[1]), len(bad)))
    return not bad

def apply_all():
    """For build.py: {entry: English bytes} for every entry with English of its own or
    from the memory (exits on errors)."""
    out, bad = {}, []
    def log(msg, err):
        if err:
            bad.append(msg)
    mem = memory()
    own = set(tl_entries())
    for entry in script_entries():
        if entry not in own and not mem:
            continue
        units_en = parse_tl(tl_path(entry)) if entry in own else {}
        new = english_entry(entry, units_en, log)
        if new is not None:
            out[entry] = new
    if bad:
        sys.exit('errors in tl/ev:\n' + '\n'.join(bad))
    return out

# ---------------------------------------------------------------- show / stats

def show(entry, script=None, todo=False):
    e, us = units(entry)
    done = parse_tl(tl_path(entry)) if os.path.exists(tl_path(entry)) else {}
    mem = memory() if todo else {}
    count = {}
    for k, n, ins, j in us:
        key = (kind(ins, j), ins.strs[j])
        count[key] = count.get(key, 0) + 1
    seen = set()
    for k, n, ins, j in us:
        if script is not None and k != script or kind(ins, j) == 'name':
            continue
        key = (kind(ins, j), ins.strs[j])
        if todo:
            if (k, n) in done or key in mem or key in seen:
                continue
            seen.add(key)
        s = text.decode(ins.strs[j]).replace('\n', '⏎')
        print('@%d.%d%s [%02X%s]%s  %s' % (k, n, ' [done]' if (k, n) in done else '', ins.op,
                                          '.%d' % j if len(ins.strs) > 1 else '',
                                          ' x%d' % count[key] if todo and count[key] > 1 else '', s))

def script_entries():
    return [i for i in evscript.entries() if evscript.is_script(clean_entry(i))]

def list_names():
    """Name pairs (5A / 3C) without English: first occurrence key, count, Japanese."""
    seen = {}
    for i in script_entries():
        for k, n, ins, mapped in name_units(i):
            if mapped:
                continue
            jp = (ins.strs[0], ins.strs[1])
            if jp not in seen:
                seen[jp] = ['@%d.%d.%d' % (i, k, n), 0, ins.op]
            seen[jp][1] += 1
    for jp, (key, c, op) in sorted(seen.items(), key=lambda x: -x[1][1]):
        print('%-14s %4d [%02X]  %s | %s' % (key, c, op, text.decode(jp[0]), text.decode(jp[1])))
    print('%d pairs without English' % len(seen))

def stats():
    """Per entry: strings with English (own or from the memory) / all."""
    tot = done = 0
    mem = memory()
    for i in script_entries():
        own = parse_tl(tl_path(i)) if os.path.exists(tl_path(i)) else {}
        us = [(k, n, ins, j) for k, n, ins, j in units(i)[1] if kind(ins, j) != 'name']
        d = sum(1 for k, n, ins, j in us if (k, n) in own or (kind(ins, j), ins.strs[j]) in mem)
        tot += len(us); done += d
        if d:
            print('%03d %5d/%5d' % (i, d, len(us)))
    print('total %d/%d strings' % (done, tot))

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    args = [a for a in sys.argv[2:] if a != '--todo']
    if cmd == 'show':
        show(int(args[0]), int(args[1]) if len(args) > 1 else None, '--todo' in sys.argv)
    elif cmd == 'apply':
        sys.exit(0 if apply(int(args[0]), args[1] if len(args) > 1 else None) else 1)
    elif cmd == 'stats':
        stats()
    elif cmd == 'names':
        list_names()
    else:
        sys.exit(__doc__)
