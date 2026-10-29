"""biofit.py NN [file.txt]: over-long card bios (msg28-32) -> id, lines, the English, and the
words that spill past line 6. With a tl-format file, checks that file's entries instead."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import tl
tl.FONT = 'small'
W = tl.widths()
wid = lambda s: sum(W.get(c, 0) for c in s)
def lines(body):
    out = ['']
    for w in body.split(' '):
        t = (out[-1] + ' ' + w).strip()
        if out[-1] and wid(t) > 410: out.append(w)
        else: out[-1] = t
    return out
n = int(sys.argv[1])
src = tl.parse_tl(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'tl', 'msg%02d.txt' % n))
bad = 0
for k, v in sorted(src.items(), key=lambda kv: int(kv[0].split('.')[0])):
    dates, _, body = v.partition('\\n')
    ls = lines(body.replace('\\n', ' '))
    if len(ls) > 6:
        bad += 1
        print('@%s  (%d lines; cut at least: %r)' % (k, len(ls), ' '.join(ls[6:])))
        print(v); print()
print('over-long:', bad, file=sys.stderr)
