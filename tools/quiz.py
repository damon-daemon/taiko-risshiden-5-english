"""Kanji-reading quiz: one of the 18 question types a friend asks (vtable 0x526A80, this one
0x2978C0): random(65) picks a question, it is copied into string slot 0 (0x2F6050, 128
bytes) and shown by msg07 #509 ("{02}yd ... How is that read?"); 0x294DA0 shuffles the four
readings into a choice menu, the first one is the correct answer.

Data (Koei the Best): QUESTIONS = 65 string pointers, READINGS = 65 x 4 string pointers;
nothing else references these strings. tl/quiz.txt keeps only English: the question template
gets the kanji from the disc ({1} = the quoted 「...」 part, {2} = the kanji after it), the
readings are romaji. English is written in place when it fits the old string, else into the
English segment with the table word repointed.
"""
import os, re, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import elfseg, elfstr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'quiz.txt')
QUESTIONS, READINGS, COUNT = 0x526560, 0x526670, 65
LIMIT = 32          # {02}yd prints count as overflow.VAR bytes; choices go into 64-byte menu items
QUOTE = re.compile('^(.*?)(「[^」]*」)(.*)$')

def load():
    out = {}
    for line in open(TL, encoding='utf-8').read().splitlines():
        if line.strip() and not line.startswith('#'):
            k, q, a = line.split('\t')
            out[int(k)] = (q, [x.strip() for x in a.split('|')])
    return out

def japanese(elf):
    """[(question, [4 readings])] of the clean ELF."""
    w = lambda va: struct.unpack_from('<I', elf, va - elfseg.VBASE + elfseg.FOFF)[0]
    s = lambda va: elfstr.slot(elf, va)[0].decode('cp932')
    return [(s(w(QUESTIONS + 4 * i)), [s(w(READINGS + 16 * i + 4 * k)) for k in range(4)])
            for i in range(COUNT)]

def english(clean_elf):
    """{table word vaddr: (string vaddr, English bytes)} for every question and reading."""
    jp, tl, errors, out = japanese(clean_elf), load(), [], {}
    if sorted(tl) != list(range(COUNT)):
        raise ValueError('quiz: tl/quiz.txt must have questions 0-%d' % (COUNT - 1))
    w = lambda va: struct.unpack_from('<I', clean_elf, va - elfseg.VBASE + elfseg.FOFF)[0]
    for i, (q, answers) in sorted(tl.items()):
        jq, ja = jp[i]
        m = QUOTE.match(jq)
        if not q.isascii() or '{1}' not in q or not m or '{2}' in q and not m.group(3):
            errors.append('quiz %d: template %r (ASCII with {1}; {2} only if the Japanese has kanji after 」)' % (i, q))
            continue
        qb = q.replace('{1}', m.group(2)).replace('{2}', m.group(3)).encode('cp932')
        if len(answers) != 4 or not all(a.isascii() and a for a in answers):
            errors.append('quiz %d: needs 4 ASCII readings' % i)
            continue
        same = lambda x, y: x.lower() == y.lower()
        for a in range(4):
            for b in range(a + 1, 4):
                if same(answers[a], answers[b]) != (ja[a] == ja[b]):
                    errors.append('quiz %d: readings %d and %d must differ exactly where the Japanese does'
                                  % (i, a, b))
        for b in [qb] + [a.encode() for a in answers]:
            if len(b) > LIMIT:
                errors.append('quiz %d: %r is %d bytes > %d' % (i, b, len(b), LIMIT))
        out[QUESTIONS + 4 * i] = (w(QUESTIONS + 4 * i), qb)
        for k in range(4):
            at = READINGS + 16 * i + 4 * k
            out[at] = (w(at), answers[k].encode())
    if errors:
        raise ValueError('\n'.join(errors))
    return out

def apply(elf, clean_elf, seg):
    """Write the quiz; returns (strings, moved)."""
    moved, text = 0, {}
    for at, (va, b) in sorted(english(clean_elf).items()):
        if text.setdefault(va, b) != b:             # a string shared by two table words
            raise ValueError('quiz: %x is used twice with different English' % va)
        jp, room = elfstr.slot(clean_elf, va)
        if len(b) <= room:
            o = va - elfseg.VBASE + elfseg.FOFF
            elf[o:o + room + 1] = b + bytes(room + 1 - len(b))
        else:
            elfseg.patch(elf, at, struct.pack('<I', seg.add(b + b'\0', 1)))
            moved += 1
    return COUNT * 5, moved

if __name__ == '__main__':
    import edition
    elf = open(os.path.join(ROOT, 'extract', edition.ELF), 'rb').read()
    for at, (va, b) in sorted(english(elf).items()):
        print('%x %x %s' % (at, va, b.decode('cp932')))
