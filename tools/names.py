"""Person names: Japanese from the disc, English from tl/names_persons.json.

Runtime names live in the scenario files (TAI5DATA 5-12, ILNK subfile 16):
1200 x 24 bytes = family[9] | given[9] | u16 flag | u16 id | u16 id2, id = index.
The same person can be named differently per scenario (木下藤吉郎 / 羽柴秀吉), so
tl/names_persons.json is keyed by person id with optional per-scenario overrides:

  {"id": 564, "en": ["Toyotomi", "Hideyoshi"], "s1": ["Kinoshita", "Tokichiro"], ...}

s1-s8 = scenario files 5-12. The ELF officer table (860 x 176 bytes, sorted by reading)
(record i = person i) has each officer's canonical name and its reading (half-width kana), used here to
romanize (Hepburn, long vowels short, as in Nobunaga DS 2).

  names.py export   -> script/names_persons.json (jp + reading + suggested/current en)
"""
import json, os, re, struct, sys, unicodedata

sys.path.insert(0, os.path.dirname(__file__))
import asm, datafile, elfseg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'names_persons.json')
SCRIPT = os.path.join(ROOT, 'script', 'names_persons.json')
SCENARIOS = range(5, 13)            # TAI5DATA entries, scenario s1..s8
SUB, REC, COUNT = 16, 24, 1200
READ_SUB, READ_REC = 15, 44           # half-width kana readings
COPY_ENTRY = 86                     # holds a copy of scenario 4's name records
OFFICERS, OFF_REC, OFF_COUNT = 0x453FE0, 176, 860

def field(b):
    return b.split(b'\0')[0].decode('cp932', 'replace')

def ilnk_sub(entry, k):
    n = struct.unpack_from('<I', entry, 4)[0]
    offs = [struct.unpack_from('<I', entry, 8 + 4 * i)[0] for i in range(n)] + [len(entry)]
    return offs[k], offs[k + 1]

def scenario_names(entry):
    """[(family, given)] x 1200 of one scenario file."""
    a, b = ilnk_sub(entry, SUB)
    sub = entry[a:b]
    return [(field(sub[i * REC:i * REC + 9]), field(sub[i * REC + 9:i * REC + 18]))
            for i in range(len(sub) // REC)]

def officers(elf):
    """{person id: (canonical name, reading)} from the ELF officer table (record i =
    person i; a few canonical names are the common name, 島左近 for 島清興)."""
    return {i: (field(elf[OFFICERS + i * OFF_REC:OFFICERS + i * OFF_REC + 17]),
                field(elf[OFFICERS + i * OFF_REC + 17:OFFICERS + i * OFF_REC + 34]))
            for i in range(OFF_COUNT)}

# ---------------------------------------------------------------- romanization

KANA = {
    'きゃ': 'kya', 'きゅ': 'kyu', 'きょ': 'kyo', 'しゃ': 'sha', 'しゅ': 'shu', 'しょ': 'sho',
    'ちゃ': 'cha', 'ちゅ': 'chu', 'ちょ': 'cho', 'にゃ': 'nya', 'にゅ': 'nyu', 'にょ': 'nyo',
    'ひゃ': 'hya', 'ひゅ': 'hyu', 'ひょ': 'hyo', 'みゃ': 'mya', 'みゅ': 'myu', 'みょ': 'myo',
    'りゃ': 'rya', 'りゅ': 'ryu', 'りょ': 'ryo', 'ぎゃ': 'gya', 'ぎゅ': 'gyu', 'ぎょ': 'gyo',
    'じゃ': 'ja', 'じゅ': 'ju', 'じょ': 'jo', 'ぢゃ': 'ja', 'ぢゅ': 'ju', 'ぢょ': 'jo',
    'びゃ': 'bya', 'びゅ': 'byu', 'びょ': 'byo', 'ぴゃ': 'pya', 'ぴゅ': 'pyu', 'ぴょ': 'pyo',
    'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o',
    'か': 'ka', 'き': 'ki', 'く': 'ku', 'け': 'ke', 'こ': 'ko',
    'さ': 'sa', 'し': 'shi', 'す': 'su', 'せ': 'se', 'そ': 'so',
    'た': 'ta', 'ち': 'chi', 'つ': 'tsu', 'て': 'te', 'と': 'to',
    'な': 'na', 'に': 'ni', 'ぬ': 'nu', 'ね': 'ne', 'の': 'no',
    'は': 'ha', 'ひ': 'hi', 'ふ': 'fu', 'へ': 'he', 'ほ': 'ho',
    'ま': 'ma', 'み': 'mi', 'む': 'mu', 'め': 'me', 'も': 'mo',
    'や': 'ya', 'ゆ': 'yu', 'よ': 'yo', 'ら': 'ra', 'り': 'ri', 'る': 'ru', 'れ': 're', 'ろ': 'ro',
    'わ': 'wa', 'ゐ': 'i', 'ゑ': 'e', 'を': 'o', 'ん': 'n',
    'が': 'ga', 'ぎ': 'gi', 'ぐ': 'gu', 'げ': 'ge', 'ご': 'go',
    'ざ': 'za', 'じ': 'ji', 'ず': 'zu', 'ぜ': 'ze', 'ぞ': 'zo',
    'だ': 'da', 'ぢ': 'ji', 'づ': 'zu', 'で': 'de', 'ど': 'do',
    'ば': 'ba', 'び': 'bi', 'ぶ': 'bu', 'べ': 'be', 'ぼ': 'bo',
    'ぱ': 'pa', 'ぴ': 'pi', 'ぷ': 'pu', 'ぺ': 'pe', 'ぽ': 'po',
    'ぁ': 'a', 'ぃ': 'i', 'ぅ': 'u', 'ぇ': 'e', 'ぉ': 'o', 'ー': '',
}

def hiragana(s):
    """Half-width / full-width katakana -> hiragana."""
    s = unicodedata.normalize('NFKC', s)
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in s)

def romaji(kana):
    """Hepburn romanization of a hiragana reading, long vowels written short
    (ou/oo -> o, uu -> u), as in common English usage (Hojo Ujiyasu)."""
    out, i = '', 0
    while i < len(kana):
        if kana[i] == 'っ' and i + 1 < len(kana):
            nxt = KANA.get(kana[i + 1:i + 3]) or KANA.get(kana[i + 1], '')
            out += 't' if nxt.startswith('ch') else nxt[:1]
            i += 1
            continue
        two = KANA.get(kana[i:i + 2])
        if two:
            out += two
            i += 2
            continue
        out += KANA.get(kana[i], kana[i])
        i += 1
    out = re.sub('ou(?![aiueo])|oo', 'o', out)          # but Inoue, Sakanoue
    out = re.sub('uu', 'u', out)
    return out.capitalize()

# ---------------------------------------------------------------- in-game lookup
#
# The records keep their Japanese, so names typed by the player still work. The
# getters look the record's (family, given) pair up in a table of hashes and return
# the English instead; unknown pairs are shown as stored.
#
#   en_part(a0 = record, a1 = 0 family / 1 given) -> v0 = string
#   msg fields 'e'/'f' (0x2F2AD0) copy en_part(); 'g' and the 143 other callers of the
#   full-name getter 0x301720 get family + ' ' + given; the officer-table name path
#   of 0x28B910 (flag set) gets the canonical English name of person a0 < 860.

STRCPY, STRCAT, NAMEBUF, GETBUF = 0x33DF70, 0x12BE10, 0x753150, 0x348870
FULL_NAME = 0x301720
SPRINTF = 0x3488A0
RANK_FAMILY = [(0x4D6EC8, 's1'), (0x4DA5E4, 's2'), (0x4E06AC, 's3')]   # rank + family sprintf
HERO_CARD = 0x2D3B34             # hero-select card name text object
MSG_FAMILY, MSG_FAMILY_FALLBACK, MSG_GIVEN = 0x2F2B9C, 0x2F2BBC, 0x2F2BE0
OFFICER_NAME = 0x28B948          # jal 0x28B340 (officer record) in 0x28B910
OFFICER_RECORD = 0x28B340

FNV_BASIS, FNV_PRIME = 0x811C9DC5, 0x01000193
PART_MARK = 0xFD                 # + 0 family / 1 given: hash prefix of a single part
POOL, POOL_REC, POOL_COUNT = 0x41DFE0, 19, 200   # ELF: generated given names (name[9], reading[9], kind)
POOL_TL = os.path.join(ROOT, 'tl', 'names_pool.txt')

def part_hash(kind, b):
    h = FNV_BASIS
    for c in bytes([PART_MARK + kind]) + b[:9]:
        h = (h ^ c) * FNV_PRIME & 0xFFFFFFFF
    return h

def name_hash(family, given):
    """FNV-1a over the family bytes (at most 9), 0xFF, the given bytes (at most 9)."""
    h = FNV_BASIS
    for c in family[:9] + b'\xff' + given[:9]:
        h = (h ^ c) * FNV_PRIME & 0xFFFFFFFF
    return h

def _hash_loop(lbl, start, end):
    return [
        ('addu', 't2', 'a0', 'zero'), ('addiu', 't2', 't2', start), ('addiu', 't3', 'a0', end),
        lbl + ':', ('beq', 't2', 't3', lbl + '_d'), ('lbu', 't4', 0, 't2'),
        ('beqz', 't4', lbl + '_d'), ('nop',),
        ('xor', 't1', 't1', 't4'), ('mult', 't1', 't1', 't9'),
        ('b', lbl), ('addiu', 't2', 't2', 1),
        lbl + '_d:']

def _bsearch(lbl, table, count, shift):
    """Binary search of t1 in a sorted table of (hash, ...) entries of 1 << shift bytes:
    t7 = entry, branches to lbl_hit; falls through on a miss."""
    return [
        ('lui', 't6', asm.hi(table)), ('addiu', 't6', 't6', asm.lo(table)),
        ('addu', 't2', 'zero', 'zero'), ('addiu', 't3', 'zero', count),
        lbl + ':', ('sltu', 't4', 't2', 't3'), ('beqz', 't4', lbl + '_miss'), ('nop',),
        ('addu', 't5', 't2', 't3'), ('srl', 't5', 't5', 1),
        ('sll', 't7', 't5', shift), ('addu', 't7', 't7', 't6'), ('lw', 't8', 0, 't7'),
        ('beq', 't8', 't1', lbl + '_hit'), ('sltu', 't4', 't8', 't1'),
        ('beqz', 't4', lbl + '_up'), ('nop',),
        ('b', lbl), ('addiu', 't2', 't5', 1),
        lbl + '_up:', ('b', lbl), ('addu', 't3', 't5', 'zero'),
        lbl + '_miss:']

def lookup_code(table, count, parts, nparts):
    return ([
        'en_part:',
        ('lui', 't1', FNV_BASIS >> 16), ('ori', 't1', 't1', FNV_BASIS & 0xFFFF),
        ('lui', 't9', FNV_PRIME >> 16), ('ori', 't9', 't9', FNV_PRIME & 0xFFFF)] + _hash_loop('h1', 0, 9) + [
        ('addiu', 't4', 'zero', 0xFF), ('xor', 't1', 't1', 't4'), ('mult', 't1', 't1', 't9')] + _hash_loop('h2', 9, 18)
        + _bsearch('bs', table, count, 4) + [
        # no pair: look the part up alone (generated people: pool given names)
        ('sll', 't0', 'a1', 3), ('addu', 't0', 't0', 'a1'), ('addu', 'a2', 'a0', 't0'),
        ('lui', 't1', FNV_BASIS >> 16), ('ori', 't1', 't1', FNV_BASIS & 0xFFFF),
        ('addiu', 't4', 'a1', PART_MARK), ('xor', 't1', 't1', 't4'), ('mult', 't1', 't1', 't9'),
        ('addu', 'a3', 'a0', 'zero'), ('addu', 'a0', 'a2', 'zero')] + _hash_loop('h3', 0, 9) + [
        ('addu', 'a0', 'a3', 'zero')]
        + _bsearch('ps', parts, nparts, 3) + [
        ('jr', 'ra'), ('addu', 'v0', 'a2', 'zero'),
        'ps_hit:', ('jr', 'ra'), ('lw', 'v0', 4, 't7'),
        'bs_hit:', ('sll', 't4', 'a1', 2), ('addu', 't7', 't7', 't4'),
        ('jr', 'ra'), ('lw', 'v0', 4, 't7'),
        # copy_family / copy_given (a0 = person object, a1 = destination)
        'copy_family:', ('b', 'copy'), ('addiu', 'a2', 'zero', 0),
        'copy_given:', ('addiu', 'a2', 'zero', 1),
        'copy:', ('addiu', 'sp', 'sp', -0x20), ('sd', 'ra', 0x10, 'sp'), ('sd', 's0', 0, 'sp'),
        ('addu', 's0', 'a1', 'zero'), ('lw', 'a0', 4, 'a0'),
        ('jal', 'en_part'), ('addu', 'a1', 'a2', 'zero'),
        ('addu', 'a0', 's0', 'zero'), ('jal', STRCPY), ('addu', 'a1', 'v0', 'zero'),
        ('ld', 'ra', 0x10, 'sp'), ('ld', 's0', 0, 'sp'), ('jr', 'ra'), ('addiu', 'sp', 'sp', 0x20),
        # full_name (a0 = person object) -> v0 = NAMEBUF: family [' ' given]
        # full_rec (a0 = name record: family[9] given[9]) -> the same
        'full_name:', ('lw', 'a0', 4, 'a0'),
        'full_rec:', ('addiu', 'sp', 'sp', -0x30), ('sd', 'ra', 0x20, 'sp'), ('sd', 's0', 0, 'sp'),
        ('sd', 's1', 8, 'sp'), ('sd', 's2', 0x10, 'sp'), ('addu', 's1', 'a0', 'zero'),
        ('lui', 'a0', asm.hi(NAMEBUF)), ('jal', GETBUF), ('addiu', 'a0', 'a0', asm.lo(NAMEBUF)),
        ('sb', 'zero', 0, 'v0'), ('addu', 's0', 'v0', 'zero'),
        ('addu', 'a0', 's1', 'zero'), ('jal', 'en_part'), ('addu', 'a1', 'zero', 'zero'),
        ('addu', 'a0', 's0', 'zero'), ('jal', STRCAT), ('addu', 'a1', 'v0', 'zero'),
        ('addu', 'a0', 's1', 'zero'), ('jal', 'en_part'), ('addiu', 'a1', 'zero', 1),
        ('addu', 's2', 'v0', 'zero'), ('lbu', 't0', 0, 's2'), ('beqz', 't0', 'fn_end'),
        ('lbu', 't0', 0, 's0'), ('beqz', 't0', 'fn_given'), ('nop',),
        ('addu', 'a0', 's0', 'zero'), ('lui', 'a1', asm.hi(SPACE_ADDR[0])),
        ('jal', STRCAT), ('addiu', 'a1', 'a1', asm.lo(SPACE_ADDR[0])),
        'fn_given:', ('addu', 'a0', 's0', 'zero'), ('jal', STRCAT), ('addu', 'a1', 's2', 'zero'),
        'fn_end:', ('addu', 'v0', 's0', 'zero'), ('ld', 'ra', 0x20, 'sp'), ('ld', 's0', 0, 'sp'),
        ('ld', 's1', 8, 'sp'), ('ld', 's2', 0x10, 'sp'), ('jr', 'ra'), ('addiu', 'sp', 'sp', 0x30),
        # officer_name (a0 = person id) -> canonical English name, else the officer record
        'officer_name:', ('sltiu', 't0', 'a0', OFF_COUNT), ('beqz', 't0', 'on_rec'),
        ('lui', 't1', asm.hi(CANON_ADDR[0])), ('addiu', 't1', 't1', asm.lo(CANON_ADDR[0])),
        ('sll', 't0', 'a0', 2), ('addu', 't1', 't1', 't0'), ('jr', 'ra'), ('lw', 'v0', 0, 't1'),
        'on_rec:', ('j', OFFICER_RECORD), ('nop',)])

SPACE_ADDR, CANON_ADDR = [0], [0]

def english(rec, scen):
    """English [family, given] of a tl record for scenario number scen (1-8)."""
    return rec.get('s%d' % scen, rec['en'])

def name_pairs(data, clean_elf, tl=None, extra=True):
    """-> (pairs, cut): Japanese (family, given) bytes -> English [family, given] of
    every scenario record (+ the event-script names of tl/ev/names.txt when extra),
    and full English pair -> the 8-byte record form."""
    tl = tl or load_tl()
    pairs = {}                                   # Japanese (family, given) -> English
    for s in SCENARIOS:
        for i, (fa, gi) in enumerate(scenario_names(datafile.entry(data, clean_elf, s))):
            if i in tl and (fa or gi):
                key = (fa.encode('cp932'), gi.encode('cp932'))
                en = english(tl[i], s - 4)
                if pairs.setdefault(key, en) != en:
                    print('names: %s%s is %s and %s' % (fa, gi, pairs[key], en))
    if extra:
        import evtl
        for key, en in evtl.event_name_pairs().items():
            pairs.setdefault(key, list(en))
    # The runtime records themselves get English cut to 8 bytes a part (code that reads
    # a record directly shows that); the lookup maps both the Japanese and the cut
    # English pair to the full English.
    cut = {}                                     # full English pair -> record pair
    used = {}
    for en in sorted(set(map(tuple, pairs.values()))):
        fa, gi = en[0].encode('ascii'), en[1].encode('ascii')
        for c in (fa[:8], gi[:8]), (fa[:8], gi[:7] + gi[-1:]), (fa[:7] + fa[-1:], gi[:8]):
            if used.setdefault(c, en) == en:
                cut[en] = c
                break
        else:
            raise ValueError('names: no unique 8-byte form for %s' % (en,))
    return pairs, cut

EV_GIVEN, EV_FAMILY = 0x233478, 0x233490     # event text \#XXXX +0x800 / +0x1000 forms

def apply(elf, data, seg, clean_elf):
    """Add the English name tables and lookup code to seg and hook the getters."""
    tl = load_tl()
    pairs, cut = name_pairs(data, clean_elf, tl)
    e86 = bytearray(datafile.entry(data, clean_elf, COPY_ENTRY))
    changes = {}
    for s in SCENARIOS:
        e = bytearray(datafile.entry(data, clean_elf, s))
        a, b = ilnk_sub(e, SUB)
        old = bytes(e[a:b])
        for i in range(min(COUNT, (b - a) // REC)):
            fa, gi = field(e[a + i * REC:a + i * REC + 9]), field(e[a + i * REC + 9:a + i * REC + 18])
            if i in tl and (fa or gi):
                cf, cg = cut[tuple(english(tl[i], s - 4))]
                e[a + i * REC:a + i * REC + 18] = cf.ljust(9, b'\0') + cg.ljust(9, b'\0')
        k = e86.find(old)
        if k >= 0:
            e86[k:k + len(old)] = e[a:b]
        # readings (subfile 15: family[10] | given[10] | data, 44 bytes, by person id):
        # cleared. The reading line converts them to hiragana and turns ASCII into
        # garbage (converter not found yet); an empty line is the clean choice.
        # Risk: lists sorted by reading lose their order (check in the emulator).
        a, b = ilnk_sub(e, READ_SUB)
        old = bytes(e[a:b])
        for i in range(min(COUNT, (b - a) // READ_REC)):
            if i in tl:
                e[a + i * READ_REC:a + i * READ_REC + 20] = bytes(20)
        k = e86.find(old)
        if k >= 0:
            e86[k:k + len(old)] = e[a:b]
        changes[s] = bytes(e)
    changes[COPY_ENTRY] = bytes(e86)
    datafile.apply(data, elf, changes)
    for key, en in list(pairs.items()):
        pairs.setdefault(cut[tuple(en)], en)
    strings = {}
    def string(t):
        if t not in strings:
            strings[t] = seg.add(t.encode('ascii') + b'\0', 1)
        return strings[t]
    rows, by_hash = {}, {}
    for (fa, gi), (efa, egi) in pairs.items():
        h = name_hash(fa, gi)
        other = by_hash.setdefault(h, (fa, gi, efa, egi))
        assert other[2:] == (efa, egi), 'hash collision %08x: %r %r' % (h, other, (fa, gi, efa, egi))
        rows[h] = (string(efa), string(egi))
    SPACE_ADDR[0] = string(' ')
    canon = b''.join(struct.pack('<I', string(tl[i].get('elf') or ' '.join(x for x in tl[i]['en'] if x)))
                     for i in range(OFF_COUNT))
    CANON_ADDR[0] = seg.add(canon, 4)
    table = seg.add(b''.join(struct.pack('<4I', h, f, g, 0) for h, (f, g) in sorted(rows.items())), 16)
    # single parts: the pool, then every part of the pairs that always has the same English
    seen = {}
    for (fa, gi), en in pairs.items():
        for kind, jp in enumerate((fa, gi)):
            if jp and en[kind]:
                seen.setdefault((kind, jp), set()).add(en[kind])
    single = {k: v.pop() for k, v in seen.items() if len(v) == 1}
    for i, en in load_pool().items():
        jp = bytes(clean_elf[POOL + i * POOL_REC:POOL + i * POOL_REC + 9]).split(b'\0')[0]
        single[(1, jp)] = en
    part_rows = {}
    for (kind, jp), en in single.items():
        h = part_hash(kind, jp)
        assert part_rows.setdefault(h, (kind, jp, en)) == (kind, jp, en), 'part hash collision %08x' % h
    parts = seg.add(b''.join(struct.pack('<2I', h, string(en)) for h, (k, jp, en) in sorted(part_rows.items())), 8)
    lines = lookup_code(table, len(rows), parts, len(part_rows))
    code_at = seg.end + (-seg.end % 4)
    code = asm.assemble(code_at, lines)
    labels = asm.labels(code_at, lines)
    seg.add(code, 4)
    p = lambda va, lines: elfseg.patch(elf, va, asm.assemble(va, lines))
    # msg field 'e': (delay slot of 'beqz s1') a1 = dst; copy_family(obj = s2)
    p(MSG_FAMILY, [('addu', 'a1', 's1', 'zero'), ('jal', labels['copy_family']), ('addu', 'a0', 's2', 'zero'), ('nop',)])
    p(MSG_FAMILY_FALLBACK, [('addu', 'a1', 's1', 'zero'), ('jal', labels['copy_given']), ('addu', 'a0', 's2', 'zero'), ('nop',)])
    p(MSG_GIVEN, [('addu', 'a1', 's1', 'zero'), ('jal', labels['copy_given']), ('addu', 'a0', 's2', 'zero'), ('nop',)])
    p(FULL_NAME, [('j', labels['full_name']), ('nop',)])
    # rank + family name: sprintf(NAMEBUF, "%s %s", rank, record) reads the cut family
    # part; rank_family(fmt, rank, record) formats with en_part(record, family)
    stub = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(stub, [
        ('addiu', 'sp', 'sp', -32), ('sd', 'ra', 0, 'sp'), ('sw', 'a0', 8, 'sp'), ('sw', 'a1', 12, 'sp'),
        ('addu', 'a0', 'a2', 'zero'), ('jal', labels['en_part']), ('addu', 'a1', 'zero', 'zero'),
        ('addu', 'a3', 'v0', 'zero'), ('lw', 'a2', 12, 'sp'), ('lw', 'a1', 8, 'sp'),
        ('lui', 'a0', asm.hi(NAMEBUF)), ('jal', SPRINTF), ('addiu', 'a0', 'a0', asm.lo(NAMEBUF)),
        ('ld', 'ra', 0, 'sp'), ('jr', 'ra'), ('addiu', 'sp', 'sp', 32)]), 4)
    for at, reg in RANK_FAMILY:
        o = at - elfseg.VBASE + elfseg.FOFF
        w = struct.unpack_from('<7I', elf, o)
        assert w[0] == 0x3C040075 and w[1] == 0x3C05005B and w[5] == 0x0C0D2228, hex(at)
        lo = w[4] & 0xFFFF
        p(at, [('lui', 'a0', 0x5B), ('addu', 'a1', 'v0', 'zero'), ('addu', 'a2', reg, 'zero'),
               ('addiu', 'a0', 'a0', lo - 0x10000 if lo & 0x8000 else lo), ('nop',), ('jal', stub), ('nop',)])
    # hero-select card (0x2D3B34): text object made with "%s %s" and the person's
    # record parts (8-byte cut forms) -> "%s" with full_name(person s4)
    o = HERO_CARD - elfseg.VBASE + elfseg.FOFF
    assert bytes(elf[o:o + 8]) == struct.pack('<2I', 0x0040202D, 0x3C0B0058)   # move a0, v0; lui t3, 0x58
    fmt = seg.add(b'%s\0', 1)
    at = seg.end + (-seg.end % 4)
    seg.add(asm.assemble(at, [('addiu', 'sp', 'sp', -16), ('sd', 'ra', 0, 'sp'), ('sw', 'a0', 8, 'sp'),
                              ('jal', labels['full_name']), ('addu', 'a0', 's4', 'zero'),
                              ('lw', 'a0', 8, 'sp'), ('ld', 'ra', 0, 'sp'), ('jr', 'ra'), ('addiu', 'sp', 'sp', 16)]), 4)
    p(HERO_CARD, [('jal', at), ('addu', 'a0', 'v0', 'zero'), ('lui', 't3', asm.hi(fmt)),
                  ('addu', 'a1', 'zero', 'zero'), ('addu', 'a2', 'zero', 'zero'), ('addu', 'a3', 'zero', 'zero'),
                  ('addu', 't0', 'zero', 'zero'), ('addu', 't1', 'zero', 'zero'), ('addiu', 't2', 'zero', 1),
                  ('addiu', 't3', 't3', asm.lo(fmt)), ('sd', 'v0', 0, 'sp'), ('nop',), ('jal', 0x469E50), ('nop',)])
    p(OFFICER_NAME, [('jal', labels['officer_name'])])
    # event text expander 0x233270: \#XXXX with the given / family form copied the
    # record part (cut form) -> en_part(record, kind); v0 = person object
    o = EV_GIVEN - elfseg.VBASE + elfseg.FOFF
    assert struct.unpack_from('<7I', elf, o)[::6] == (0x8C420004, 0x8C450004), 'event name hooks'
    for va, kind in (EV_GIVEN, 1), (EV_FAMILY, 0):
        at = seg.end + (-seg.end % 4)
        seg.add(asm.assemble(at, [
            ('addiu', 'sp', 'sp', -16), ('sd', 'ra', 0, 'sp'), ('lw', 'a0', 4, 'v0'),
            ('jal', labels['en_part']), ('addiu', 'a1', 'zero', kind),
            ('addu', 'a1', 'v0', 'zero'), ('addu', 'a0', 's1', 'zero'),
            ('ld', 'ra', 0, 'sp'), ('j', 0x233180), ('addiu', 'sp', 'sp', 16)]), 4)
        p(va, [('jal', at), ('nop',)] + ([('b', 0x233EB0), ('addu', 's1', 's1', 'v0')] if kind else []))
    # The ELF officer table itself (read directly by 0x28B340's callers: hero cards,
    # lists): name[17] = English (short form "F. Given" when over 16 characters),
    # reading[17] cleared (English shows no kana reading line).
    # The 7 per-scenario full-name slots (+0x28, 17 bytes each; hero cards) get the
    # English of the matching Japanese pair (same short form).
    joined = {fa + gi: en for (fa, gi), en in pairs.items()}
    for i in range(OFF_COUNT):
        o = OFFICERS + i * OFF_REC
        elf[o:o + 34] = officer_short(tl[i]).encode('ascii').ljust(34, b'\0')
        for k in range(7):
            so = o + 0x28 + 17 * k
            jp = bytes(clean_elf[so:so + 17]).split(b'\0')[0]
            if jp:
                en = joined.get(jp)
                short = officer_short({'en': en}) if en else officer_short(tl[i])
                elf[so:so + 17] = short.encode('ascii').ljust(17, b'\0')
    return len(rows)

def officer_short(rec):
    """Canonical English name in at most 16 characters."""
    n = rec.get('elf') or ' '.join(x for x in rec['en'] if x)
    if len(n) > 16:
        fa, gi = (n.split(' ', 1) + [''])[:2] if rec.get('elf') else rec['en']
        n = fa[:1] + '. ' + gi if fa and gi else n[:16]
    assert len(n) <= 16, n
    return n


def load_pool():
    out = {}
    if os.path.exists(POOL_TL):
        for line in open(POOL_TL, encoding='ascii').read().splitlines():
            if line.strip():
                k, _, v = line.partition('\t')
                out[int(k)] = v
    return out

def load_tl():
    return {r['id']: r for r in json.load(open(TL, encoding='utf-8'))} if os.path.exists(TL) else {}

def export(elf, data):
    """script/names_persons.json: per person id the Japanese of every scenario, the
    officer reading and the English from tl/ (if any)."""
    tl = load_tl()
    scen = {s: scenario_names(datafile.entry(data, elf, s)) for s in SCENARIOS}
    offi = officers(elf)
    rows = []
    for i in range(COUNT):
        jp = {'s%d' % (s - 4): list(scen[s][i]) for s in SCENARIOS}
        r = {'id': i, 'jp': jp}
        if i in offi:
            r['officer'] = list(offi[i])
        r.update({k: v for k, v in tl.get(i, {}).items() if k != 'id'})
        rows.append(r)
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    json.dump(rows, open(SCRIPT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rows

if __name__ == '__main__':
    import mmap
    elf = open(os.path.join(ROOT, 'extract', 'SLPM_656.74'), 'rb').read()
    f = open(os.path.join(ROOT, 'extract', 'TAI5DATA.DAT'), 'rb')
    data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    if sys.argv[1:] == ['export']:
        print(len(export(elf, data)), 'persons ->', SCRIPT)
