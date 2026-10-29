"""Simulate the strict rule: re-wrap each unverified unit in the 20px font at the width of its widest
Japanese line; list units that then need more lines than the Japanese. usage: tools/dev/panelsim.py"""
import sys, json, collections
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tl, msgscript, text
from panelrisk import jp_px, verified
tot = collections.Counter(); over = collections.defaultdict(list)
for n in range(17, 33):
    rows = json.load(open(tl.setup.msg_json(n), encoding='utf-8'))
    box = tl.Box(n, rows)
    for e in rows:
        i = e['id']
        if not e['en'] or verified(n, i): continue
        jt, spans = msgscript.units(text.encode(e['jp']))
        et, espans = msgscript.units(text.encode(e['en']))
        for (a, z), (ea, ez) in zip(spans, espans):
            jl = tl.lines_of(jt[a:z]); el = tl.lines_of(et[ea:ez])
            jw = max(jp_px(l, 20) for l in jl)
            if jw == 0: continue
            tl.FONT = 'small'
            # English as one flow with its explicit breaks kept
            lines = tl.wrap(et[ea:ez], jw)
            tot[n] += 1
            if len(lines) > len(jl):
                over[n].append(i)
for n in sorted(tot):
    print('msg%02d units %d, more lines than Japanese %d: %s' % (n, tot[n], len(over[n]), ' '.join(map(str, sorted(set(over[n]))[:30]))))
