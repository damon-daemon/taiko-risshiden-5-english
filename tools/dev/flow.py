"""Forward data flow of a value through the code, for the buffer-overflow audit.

From a start site (an instruction that puts a translated string or a name into a
register) the value is followed through register moves, pointer arithmetic and stack
spills along the fall-through path (unconditional `b` is followed; jr / j / ~120
instructions end it) to every call that receives it. Each call is reported with the
argument the value is in and the destination a0 (sp+X with an estimated buffer size,
a global, or another register), which is what the audit needs for strcpy / strcat /
sprintf-style sinks.

  calls(start_va, reg)            -> [Call]
  gp_loads(slot_va)               -> [(va, reg)] of lw reg, slot-gp(gp)
  addr_loads(target)              -> [(va, reg)] of lui/addiu pairs building target
  callers(fn)                     -> [va] of jal fn
  frame(va)                       -> (function start, frame size, sorted sp offsets)

usage: .venv/bin/python tools/dev/flow.py ret 0x301720     # value returned by fn
       .venv/bin/python tools/dev/flow.py addr 0x5470a0    # a string address
       .venv/bin/python tools/dev/flow.py ui 123           # UI table string 123
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mips

GP = 0x653FF0
UI_TABLE = 0x64C048
ARGS = [4, 5, 6, 7, 8, 9, 10, 11]                   # a0-a3, t0-t3 (EABI)
CALLER_SAVED = {1, 2, 3, *range(4, 16), 24, 25}
SP = 29

# known sinks: name -> (dst arg, text args, note)
SINKS = {
    0x33DF70: 'strcpy',  0x12BE10: 'strcat',  0x33DFB0: 'strncpy',
    0x340B00: 'sprintf', 0x340AD0: 'vsprintf', 0x3488A0: 'ring_sprintf(256)',
    0x12BC10: 'sprintf', 0x12C088: 'strcpy', 0x12C2D8: 'strncpy', 0x33E080: 'strcat',
    0x12A770: 'memcpy',
    0x469C60: 'text_set(1064)', 0x469D20: 'text_set2(1104)', 0x33DF20: 'strlen',
}

def s16(x):
    return x - 0x10000 if x & 0x8000 else x

def word(va):
    return mips.word(va)

def callers(fn):
    j = 0x0C000000 | (fn >> 2) & 0x3FFFFFF
    return [va for va in range(mips.BASE, mips.TEXT_END, 4) if word(va) == j]

def gp_loads(slot):
    off = slot - GP
    out = []
    for va in range(mips.BASE, mips.TEXT_END, 4):
        w = word(va)
        if w >> 26 in (0x23, 0x37) and (w >> 21) & 31 == 28 and s16(w & 0xFFFF) == off:
            out.append((va, (w >> 16) & 31))
    return out

def addr_loads(target):
    return [(va, (word(va) >> 16) & 31) for va, t in mips.refs(target, target + 1) if va < mips.TEXT_END
            and word(va) >> 26 in (0x09, 0x0D, 0x19)]

def writes(w):
    op = w >> 26
    if op == 0:
        f = w & 0x3F
        if f in (8, 0x18, 0x19, 0x1A, 0x1B, 0x11, 0x13):      # jr, mult/div, mthi/mtlo
            return None if f in (8, 0x11, 0x13) else ((w >> 11) & 31 or None)
        return (w >> 11) & 31
    if op == 0x1C:
        return (w >> 11) & 31
    if op in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x18, 0x19, 0x1A, 0x1B, 0x1E, 0x37) or 0x20 <= op <= 0x27:
        return (w >> 16) & 31
    if op == 0x03:
        return 31
    return None

def frame(va):
    """-> (start, size, sorted sp offsets used) of the function containing va."""
    a = va
    while a > mips.BASE:
        w = word(a)
        if w >> 16 == 0x27BD and w & 0x8000:                 # addiu sp, sp, -N
            break
        a -= 4
    start, size = a, -s16(word(a) & 0xFFFF)
    offs = set()
    b = start + 4
    while b < mips.TEXT_END:
        w = word(b)
        op, rs = w >> 26, (w >> 21) & 31
        if w >> 16 == 0x27BD and not w & 0x8000:              # epilogue addiu sp, sp, N
            if b - va > 0 or True:
                pass
        if rs == SP and (op in (0x09, 0x19) or 0x1E <= op <= 0x3F):
            offs.add(s16(w & 0xFFFF))
        if w >> 16 == 0x27BD and w & 0x8000 and b > start + 4:   # next function
            break
        b += 4
    return start, size, sorted(offs)

def buf_size(va, off):
    start, size, offs = frame(va)
    nxt = [o for o in offs if o > off]
    return min(nxt[0] if nxt else size, size) - off, size

Call = collections.namedtuple('Call', 'site callee args dst')

def describe_a0(site, start):
    """Where a0 points at the call at site: scan back to start."""
    reg = 4
    a = site + 4                      # delay slot first
    seen = 0
    while a >= start and seen < 60:
        if a == site:
            a -= 4
            continue
        w = word(a)
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if writes(w) == reg:
            if op in (0x09, 0x19) and rs == SP:
                return ('stack', s16(imm))
            if op in (0x09, 0x19, 0x0D):
                # lui + addiu?
                b = a - 4
                while b >= start and a - b < 64:
                    x = word(b)
                    if x >> 26 == 0x0F and (x >> 16) & 31 == rs:
                        return ('global', ((x & 0xFFFF) << 16) + (imm if op == 0x0D else s16(imm)))
                    if writes(x) == rs:
                        break
                    b -= 4
                return ('reg+%d' % s16(imm), mips.REG[rs])
            if op == 0 and (w & 0x3F) in (0x21, 0x25, 0x2D) and 0 in (rs, rt):
                reg = rt if rs == 0 else rs
                if reg == SP:
                    return ('stack', 0)
                a -= 4; seen += 1
                continue
            if op == 0x23 and rs == 28:
                return ('gpword', GP + s16(imm))
            if op in (0x23, 0x37) and rs == SP:
                return ('spill', s16(imm))
            if op == 0x03 or (op == 0 and (w & 0x3F) == 9):
                return ('ret', None)
            return ('other', '%08x' % a)
        if a != site + 4 and op == 0x03 and reg in CALLER_SAVED:
            return ('ret', '%08x' % a)
        a -= 4; seen += 1
    return ('unknown', mips.REG[reg])

def calls(start, reg, limit=120, deref=False):
    """Follow the value in reg (written by the instruction at start)."""
    taint, slots, out = {reg}, set(), []
    va, n = start + 4, 0
    fstart = frame(start)[0]
    prev = word(start - 4)
    if prev >> 26 == 0x03 and reg in ARGS:             # start is a jal's delay slot
        out.append(Call(start - 4, (prev & 0x3FFFFFF) << 2, [ARGS.index(reg)], describe_a0(start - 4, fstart)))
        taint -= CALLER_SAVED
    while n < limit and (taint or slots):
        w = word(va)
        op, rs, rt, rd, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, w & 0xFFFF
        if op == 0x03:                                        # jal: delay slot first
            d = word(va + 4)
            taint, slots = _step(d, taint, slots, deref)
            target = (w & 0x3FFFFFF) << 2
            hit = [i for i, r in enumerate(ARGS) if r in taint]
            if hit:
                out.append(Call(va, target, hit, describe_a0(va, fstart)))
            taint -= CALLER_SAVED
            va += 8; n += 2
            continue
        if op == 0x02 or (op == 0 and (w & 0x3F) in (8, 9)):
            if op == 0 and (w & 0x3F) == 9:                 # jalr
                taint -= CALLER_SAVED
                va += 8; n += 2
                continue
            break
        if op == 0x04 and rs == 0 and rt == 0:                # b target
            taint, slots = _step(word(va + 4), taint, slots, deref)
            va = va + 4 + 4 * s16(imm); n += 2
            continue
        taint, slots = _step(w, taint, slots, deref)
        va += 4; n += 1
    return out

def _step(w, taint, slots, deref=False):
    taint, slots = set(taint), set(slots)
    op, rs, rt, rd, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, w & 0xFFFF
    if op in (0x2B, 0x3F, 0x1F) and rs == SP:                 # spill
        (slots.add if rt in taint else slots.discard)(s16(imm))
        return taint, slots
    if op in (0x23, 0x37, 0x1E) and rs == SP:                 # reload
        (taint.add if s16(imm) in slots else taint.discard)(rt)
        return taint, slots
    wr = writes(w)
    if wr is None or wr == 0:
        return taint, slots
    src = False
    if deref and op in (0x23, 0x37) and rs in taint:          # element of a pointer table
        src = True
    elif op in (0x09, 0x19) and rs in taint:                  # ptr + offset
        src = True
    elif op == 0 and (w & 0x3F) in (0x21, 0x25, 0x2D, 0x0B, 0x0A) and (rs in taint or rt in taint):
        src = True
    (taint.add if src else taint.discard)(wr)
    return taint, slots

def report(starts, label):
    sinks = collections.Counter()
    for va, reg in starts:
        for c in calls(va, reg):
            name = SINKS.get(c.callee, '%08x' % c.callee)
            dst = c.dst
            extra = ''
            if dst[0] == 'stack':
                size, fs = buf_size(c.site, dst[1])
                extra = ' size~%d (frame %d)' % (size, fs)
            elif dst[0] == 'global':
                dst = ('global', '%08x' % dst[1])
            print('%s from %08x: call %08x %-18s args %s dst %s%s' % (label, va, c.site, name, c.args, dst, extra))
            sinks[name] += 1
    print('# sinks:', dict(sinks.most_common(40)))

if __name__ == '__main__':
    cmd, a = sys.argv[1], int(sys.argv[2], 0)
    if cmd == 'ret':
        report([(va + 4, 2) for va in callers(a)], 'ret')    # v0 after the call (start = delay slot)
    elif cmd == 'addr':
        report(addr_loads(a), 'addr')
    elif cmd == 'ui':
        report(gp_loads(UI_TABLE + 4 * a), 'ui%d' % a)

IGNORE = {0x100690: 'debug printf (no-op)', 0x33DF20: 'strlen', 0x33E0C0: 'strcmp',
          0x467CB0: 'measure text', 0x478D80: 'draw text (no copy)', 0x469E50: 'text_set3(1104)'}
COPY = {'memcpy', 'strcpy', 'strcat', 'sprintf', 'vsprintf', 'strncpy', 'ring_sprintf(256)'}

def summary(fn, arg, depth=1, seen=None):
    """Sinks reached by argument arg of fn -> [(call, name, dst)]."""
    seen = seen if seen is not None else set()
    if (fn, arg) in seen:
        return []
    seen.add((fn, arg))
    out = []
    for c in calls(fn - 4, ARGS[arg]):
        name = SINKS.get(c.callee) or IGNORE.get(c.callee)
        if name:
            if name in COPY:
                out.append((c.site, name, c.args, c.dst))
        elif depth > 0:
            for i in c.args:
                for s in summary(c.callee, i, depth - 1, seen):
                    out.append(s)
    return out

_INDEX = None

def index():
    """One pass over the code -> ({gp offset: [(va, reg)]}, {address: [(va, reg)]}) of
    lw/ld reg, off(gp) and lui + addiu/ori pairs building an address."""
    global _INDEX
    if _INDEX is None:
        gp, addr = collections.defaultdict(list), collections.defaultdict(list)
        lui, clear_at = {}, None
        for va in range(mips.BASE, mips.TEXT_END, 4):
            w = word(va)
            op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
            if op == 0x0F:
                lui[rt] = (imm << 16, va)
            else:
                if op in (0x23, 0x37) and rs == 28:
                    gp[s16(imm)].append((va, rt))
                if op in (0x09, 0x0D, 0x19) and rs in lui and va - lui[rs][1] < 64:
                    t = lui[rs][0] + (imm if op == 0x0D else s16(imm))
                    addr[t & 0xFFFFFFFF].append((va, rt))
                wr = writes(w)
                if wr in lui and not (op in (0x09, 0x0D, 0x19) and wr == rs):
                    del lui[wr]
            if clear_at == va:                  # a jump's delay slot has run
                lui.clear()
                clear_at = None
            if op in (2, 3) or (op == 0 and (w & 0x3F) in (8, 9)):
                clear_at = va + 4
        _INDEX = gp, addr
    return _INDEX
