"""Buffer-overflow guards: the longest text that can reach each fixed-size buffer.

English is longer than the Japanese, and the game copies text into fixed buffers
with strcpy / sprintf and no length checks. The audit (2026-10-18, disassembly with
tools/dev/flow.py) found the buffers below; this module measures the longest
possible expansion of every message / string that reaches one and fails the build
when it would not fit.

Expansion model (TAI5MSG, interpreter 0x347940/0x347A60): text bytes count as is,
{02} prints and %-fields count VAR bytes (the longest English name or table
entry), {02}xd prints a number (at most 11 bytes), {01}C inserts count the longest expansion of the inserted
message, {01}J the target instead of the rest. IF bodies end in a return (see _tree),
so IFs are alternatives: the longest path counts.

Buffers (limit = bytes of text, without the NUL):
  MSG_BUF     every TAI5MSG expansion goes to the message object's 1024-byte buffer
              (+0x308); the emitter stops at 1022 (0x3FE) but inserted strings
              (0x347090) are written whole, so the text must stay under 1022 - VAR.
  EVENT_BUF   event text expander 0x233270 -> 0x65C030 (2064 bytes, no check).
  RING        0x3488A0 = sprintf into one of 128 256-byte ring buffers (0x753150);
              messages used as its format string (0x2F8330 -> 0x3488A0).
  MENU_ITEM   0x4FE920 builds menus: strcpy(malloc(0x40), message) per item.
  SITES       sprintf(stack buffer, "%s", message) and similar single sites.
  LINE        message window run buffer (msgwindow.py, sp+0xA0, 128 bytes, no
              check): bytes per displayed line (tl.LINE_BYTES).

usage: .venv/bin/python tools/overflow.py      # report the longest expansions vs limits
"""
import functools, json, os, re, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import msgscript, setup, text

VAR = 32                 # a {02} print / %-field: longest English name (21) or table entry (items: 32)
NUMBER = 11              # 0x347110 prints numbers into a 32-byte stack buffer
MSG_BUF = 1022 - VAR     # emitter limit 0x3FE minus one unchecked insert
EVENT_BUF = 2063
RING = 255
MENU_ITEM = 63

def _ids(lo, hi):
    return list(range(lo, hi + 1))

# message id (as passed to 0x2F8330: < 1000 = msg00 entry, else block*1000 + entry)
# -> (limit, where)
SITES = {}
for _i in [443, 444] + _ids(450, 468):
    SITES[_i] = (71, 'sprintf("%s") into a 72-byte stack buffer (0x4D9F80, 0x4DA6E0, 0x4DB69C...)')
for _i in _ids(12690, 12747) + _ids(11161, 11184):
    SITES[_i] = (255, 'battle speech: strcpy into a 256-byte stack buffer (0x1EC91C)')
for _i in [1093, 1102, 1147, 1256, 1271, 1356, 1386, 1388, 1391, 14020]:
    SITES[_i] = (RING, 'format of ring_sprintf (256-byte ring buffer)')

# menus built by 0x4FE920 (ELF tables of u32 message ids: address, count)
MENU_TABLES = [(0x52DC80, 138), (0x52E0E0, 6), (0x52E100, 4), (0x52E110, 4), (0x52E120, 3),
               (0x52E130, 20), (0x52E180, 5), (0x52E1A0, 6), (0x52E1C0, 7), (0x52E1E0, 3),
               (0x52E1F0, 6), (0x52E208, 3), (0x52E220, 4), (0x52E230, 4), (0x52E240, 3),
               (0x52E250, 8), (0x52E270, 4), (0x52E280, 3), (0x52E290, 5), (0x653FF0 - 24880, 2),
               (0x52E2B0, 5), (0x653FF0 - 24872, 2), (0x52E2D0, 4), (0x52E2E0, 26),
               (0x52E350, 18), (0x52E3A0, 11)]

def menu_ids(elf):
    out = set()
    for va, n in MENU_TABLES:
        o = va - 0x100000 + 0x80
        out.update(struct.unpack_from('<%dI' % n, elf, o))
    return out

def target(lo, hi):
    i = lo | hi << 8
    return (0, i) if i < 1000 else (i // 1000, i % 1000)

def split_id(i):
    return (0, i) if i < 1000 else (i // 1000, i % 1000)

# ---------------------------------------------------------------- messages

def _tree(toks):
    """tokens -> nodes: ('t', bytes, kind) | ('if', [body nodes]) | ('ret',).
    05 05 04 IF: when false the interpreter skips to the matching 05 05 05; when true
    it runs the body, whose 05 05 05 is a return (0x347F40: pop the {01}C call stack,
    or end the message when it is empty). So a taken IF ends the message there."""
    root = []
    stack = [root]
    for kind, b in toks:
        if kind == 'if':
            node = ('if', [])
            stack[-1].append(node)
            stack.append(node[1])
        elif kind == 'end':
            stack[-1].append(('ret',))
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].append(('t', b, kind))
    return root

class Measure:
    """Longest expansion of TAI5MSG messages; get(block, entry) -> bytes or None."""

    def __init__(self, get):
        self.get = get
        self.memo = {}
        self.active = set()

    def msg(self, n, i):
        k = (n, i)
        if k in self.memo:
            return self.memo[k]
        if k in self.active:                # recursion: count as one variable
            return VAR
        b = self.get(n, i)
        if b is None:
            return 0
        self.active.add(k)
        try:
            v = self.seq(_tree(msgscript.tokens(b)))[0]
        except msgscript.ParseError:
            v = len(b) + 8 * VAR
        self.active.discard(k)
        self.memo[k] = v
        return v

    def item(self, kind, b):
        """-> (bytes, stop) of one inline token."""
        if kind == 'text':
            return len(b), False
        if kind == 'nl':
            return 1, False
        if kind == 'cmd':
            if b[:2] == b'\x01J' and len(b) >= 4:
                return self.msg(*target(b[2], b[3])), True
            return 0, False
        # inline
        c = b[0]
        if c == 0x01 and b[1:2] == b'C' and len(b) >= 4:
            return self.msg(*target(b[2], b[3])), False
        if c == 0x02 and len(b) == 3 and b[2] == 0x64:
            return NUMBER, False                # field 'd': the raw value (0x2F2B30)
        if c == 0x02 or c == 0x25:
            return VAR, False
        return len(b), False

    def seq(self, nodes):
        """-> (longest bytes, always returns). A taken IF returns inside its body;
        a skipped one lets the text after it run."""
        total = best = 0
        for node in nodes:
            if node[0] == 'if':
                v, _ = self.seq(node[1])
                best = max(best, total + v)
                continue
            if node[0] == 'ret':
                return max(best, total), True
            v, stop = self.item(node[2], node[1])
            total += v
            if stop:
                return max(best, total), True
        return max(best, total), False

    def lines(self, n, i):
        """Longest displayed line (bytes) of a message: per line between newlines,
        with inserted messages' own longest line (approximation: the whole insert)."""
        b = self.get(n, i)
        if b is None:
            return 0
        best = 0
        for part in re.split(rb'\n', b):
            # the line's own expansion, measured as a message of its own
            try:
                v = self.seq(_tree(msgscript.tokens(part)))[0]
            except msgscript.ParseError:
                v = len(part)
            best = max(best, v)
        return best

# Fixed text panels that must not get more lines than they hold: a text object wraps by
# character at its own width and keeps drawing lines past its height, which corrupts
# memory (issue #8: Card List hero cards, msg28-32 = dates line + 6 body lines; after
# ~20 overflowing cards the menus vanish and loading a save hangs).
# msg23 #84-423 = the other card types' texts: a narrower panel, 5 lines (no dates line).
# block: [(entries, body lines, object wrap width px, font, lines before the body)]
PANELS = {n: [(range(1000), 6, 440, 'small', 1)] for n in range(28, 33)}
PANELS[23] = [(range(84, 424), 5, 320, 'small', 0)]
PANELS[22] = [(range(0, 458), 5, 320, 'small', 0)]   # item descriptions (same panel)

@functools.lru_cache(None)
def _font_widths(font):
    import latinfont
    return {ord(c): g[1] for c, g in latinfont.render(font).items() if len(c) == 1}

def panel_lines(b, width, font):
    """Lines of a message as its text object shows them (explicit lines plus the
    object's own character wrap at width)."""
    w = _font_widths(font)
    out = []
    for part in b.split(b'\n'):
        x, n, i = 0, 1, 0
        while i < len(part):
            c = part[i]
            if c < 0x20:                        # control codes: no width
                i += 1; continue
            if 0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC:
                cw, i = 20, i + 2
            else:
                cw, i = w.get(c, 10), i + 1
            if x + cw > width:
                n, x = n + 1, 0
            x += cw
        out.append(n)
    return out

# ---------------------------------------------------------------- checks

def check_messages(get, elf, blocks_count=33, sizes=None):
    """-> list of error strings. get(block, entry) -> final bytes or None."""
    m = Measure(get)
    errs = []
    for n in range(blocks_count):
        for i in range(sizes[n] if sizes else 1000):
            b = get(n, i)
            if b is None:
                continue
            v = m.msg(n, i)
            if v > MSG_BUF:
                errs.append('msg%02d #%d: expands to %d bytes > %d (message buffer)' % (n, i, v, MSG_BUF))
    for n, panels in sorted(PANELS.items()):
        for ids, limit, width, font, head in panels:
            for i in ids:
                b = get(n, i) if not sizes or i < sizes[n] else None
                if b is None:
                    continue
                # IF bodies (05 05 04 ... 05 05 05) are alternatives: the longest counts
                v = max(sum(panel_lines(part, width, font)[head:])
                        for part in re.split(rb'\x05\x05[\x04\x05]', b))
                if v > limit:
                    errs.append('msg%02d #%d: %d lines > %d (fixed panel: text past it corrupts memory)'
                                % (n, i, v, limit))
    for mid, (limit, where) in sorted(SITES.items()):
        v = m.msg(*split_id(mid))
        if v > limit:
            errs.append('msg%02d #%d: expands to %d bytes > %d: %s' % (split_id(mid) + (v, limit, where)))
    for mid in sorted(menu_ids(elf)):
        v = m.msg(*split_id(mid))
        if v > MENU_ITEM:
            errs.append('msg%02d #%d: expands to %d bytes > %d: menu item (strcpy into malloc(64), 0x4FE920)'
                        % (split_id(mid) + (v, MENU_ITEM)))
    return errs

# ---------------------------------------------------------------- event scripts

EV_ESC = re.compile(rb'\\(#[0-9A-Fa-f]{4}|%(?:02|04|20)[0-9A-Fa-f]{3}|%[0-9A-Fa-f]{2}|&[0-9A-Fa-f]{2}'
                    rb'|[0-9;<=>?A-Za-z][0-9A-Fa-f]{3})')
EV_DIALOGUE = {0x11, 0x12, 0x13}       # + the third string of 5A: message window text

class EventMeasure:
    """Expanded bytes of event strings (expander 0x233270): \\#XXXX person name (form
    0x2000 = nothing), \\%NN / \\&NN = a msg00 entry (pronoun table 0x547720), other
    escapes = a value (VAR)."""

    def __init__(self, msg):
        import evtl
        self.msg, self.pronouns, self.names = msg, evtl.pronouns(), evtl.person_names()
        self.z = VAR             # \\Z00n = a text variable set by op 1E (set per entry)

    def esc(self, e):
        c = e[:1]
        if c == b'#':
            v = int(e[1:], 16)
            pid, form = v & 0x7FF, v & 0x3800
            if form == 0x2000:
                return 0
            forms = self.names.get(pid)
            if not forms:
                return VAR
            return max(len(f[1] if form == 0x800 else f[0] if form == 0x1000 else '%s %s' % tuple(f))
                       for f in forms)
        if c in (b'%', b'&'):
            mid = self.pronouns.get(int(e[1:3], 16))
            return self.msg.msg(*split_id(mid)) if mid is not None else 0
        if c == b'Z':
            return self.z
        return VAR

    def size(self, b):
        n, pos = 0, 0
        for m in EV_ESC.finditer(b):
            n += m.start() - pos + self.esc(m.group(1))
            pos = m.end()
        return n + len(b) - pos

def event_strings(entries):
    """entries {entry: bytes} -> yield (entry, script, n, op, j, string)."""
    import evscript
    for entry, data in sorted(entries.items()):
        e = evscript.Entry(data)
        for k, (items, _) in enumerate(e.scripts):
            for n, (path, ins, j) in enumerate(evscript.strings(items)):
                yield entry, k, n, ins.op, j, ins.strs[j]

EV_NAME = 8              # 5A / 3C name parts: copied into 9-byte record fields with an
                         # SJIS strncpy (n = 9 / 10: 10 / 11 bytes written, 0x302140, 0x3C)

def check_events(entries, msg):
    """entries {entry: bytes} -> errors: expansion > EVENT_BUF (0x233270 has no check),
    5A / 3C name parts > EV_NAME bytes (after expansion)."""
    em = EventMeasure(msg)
    errs = []
    z = {}
    for entry, k, n, op, j, s in event_strings(entries):
        if op == 0x1E:
            z[entry] = max(z.get(entry, 0), len(s))
    for entry, k, n, op, j, s in event_strings(entries):
        em.z = z.get(entry, VAR)
        v = em.size(s)
        tag = '%03d@%d.%d' % (entry, k, n)
        if v > EVENT_BUF:
            errs.append('%s: expands to %d bytes > %d (event text buffer 0x65C030)' % (tag, v, EVENT_BUF))
        if (op == 0x5A and j < 2 or op == 0x3C) and v > EV_NAME:
            errs.append('%s: name part %r expands to %d bytes > %d (9-byte record field)' % (tag, s, v, EV_NAME))
    return errs

# ---------------------------------------------------------------- ELF strings

TOWN_ROOM = 22           # a town / base name (elftables towns room)
# UI strings (tl/ui.txt index) -> (limit in bytes, where). Name parts written into a
# person's 9-byte name fields by 0x302140 (SJIS strncpy n = 9: up to 10 bytes, so a
# 9-byte part puts its NUL on the next field / the record's flag at +0x12): <= 8.
UI_LIMITS = {i: (8, 'temporary speaker name part, 9-byte record field (0x302140)')
             for i in (0, 67, 68, 69, 70, 71, 1620, 1621, 1622, 1625, 1626, 1627, 1628)}
# sprintf(48-byte stack buffer, fmt, base name) at 0x3C2294 / 0x3C22AC
UI_FORMATS = {482: (47, TOWN_ROOM, 'sprintf into a 48-byte stack buffer (0x3C2294)'),
              483: (47, TOWN_ROOM, 'sprintf into a 48-byte stack buffer (0x3C22AC)')}
# elfstr: strcpy(16-byte buffer, terrain) + strcat(" Combat") at 0x254678
# terrain name (table 0x54A4F0, or ' 城' 0x54A520) + ' Combat' (0x54A528)
ELFSTR_PAIRS = [((va, 0x54A528), 15, 'strcpy + strcat into a 16-byte stack buffer (0x254678)')
                for va in (0x54A4A8, 0x54A4B0, 0x54A4B8, 0x54A4C0, 0x54A4C8, 0x54A4D0, 0x54A4D8, 0x54A4E0, 0x54A520)]
# record tables (elftables.py): bytes of an English name
TABLE_LIMITS = {'techniques': (15, 'technique rename: strcpy into 16-byte stack buffers (0x32B488)')}
PRINT_BUF = 63           # {02} prints go to a 64-byte stack buffer (0x347CAC)

def _fmt_len(b):
    return len(re.sub(rb'%[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]', b'', b))

def check_ui(tl):
    """tl {index: str} (tl/ui.txt) -> errors."""
    errs = []
    for i, (limit, where) in UI_LIMITS.items():
        if i in tl and len(tl[i].encode('ascii')) > limit:
            errs.append('ui %d %r: %d bytes > %d: %s' % (i, tl[i], len(tl[i]), limit, where))
    for i, (limit, arg, where) in UI_FORMATS.items():
        if i in tl:
            n = _fmt_len(tl[i].encode('ascii')) + arg
            if n > limit:
                errs.append('ui %d %r: %d bytes with a %d-byte argument > %d: %s' % (i, tl[i], n, arg, limit, where))
    return errs

def check_elfstr(tl, slot_text):
    """tl {vaddr: str}; slot_text(va) -> the Japanese bytes (for strings left as is)."""
    errs = []
    get = lambda va: tl[va].encode('cp932') if va in tl else slot_text(va)
    for vas, limit, where in ELFSTR_PAIRS:
        n = sum(len(get(va)) for va in vas)
        if n > limit:
            errs.append('elfstr %s: %d bytes > %d: %s' % ('+'.join('%x' % v for v in vas), n, limit, where))
    return errs

def check_table(name, rows):
    """rows {index: English} of an elftables table -> errors."""
    errs = []
    limit, where = TABLE_LIMITS.get(name, (VAR, '{02} prints are counted as VAR bytes (overflow.VAR)'))
    for i, en in sorted(rows.items()):
        if len(en.encode('cp932')) > min(limit, VAR):
            errs.append('table %s %d %r: %d bytes > %d: %s' % (name, i, en, len(en), min(limit, VAR), where))
    return errs

def check_names(full_names):
    errs = []
    for n in full_names:
        if len(n.encode('ascii')) > VAR:
            errs.append('name %r: %d bytes > VAR %d (message prints, 64-byte print buffer)' % (n, len(n), VAR))
    return errs

def clean_elf():
    import evtl
    return evtl._source()[1]

def json_getter():
    rows = {}
    def get(n, i):
        if n not in rows:
            p = setup.msg_json(n)
            rows[n] = {r['id']: r for r in json.load(open(p, encoding='utf-8'))} if os.path.exists(p) else {}
        r = rows[n].get(i)
        if r is None:
            return None
        return text.encode(r['en'] or r['jp'])
    return get

def main():
    elf = clean_elf()
    get = json_getter()
    m = Measure(get)
    worst = []
    for n in range(33):
        for i in range(1000):
            if get(n, i) is not None:
                worst.append((m.msg(n, i), n, i))
    worst.sort(reverse=True)
    print('longest message expansions:', ['msg%02d #%d %d' % (n, i, v) for v, n, i in worst[:12]])
    errs = check_messages(get, elf)
    print('\n'.join(errs) or 'no message overflows')
    print('%d errors' % len(errs))

if __name__ == '__main__':
    main()
