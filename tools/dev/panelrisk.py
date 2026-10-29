"""Panel overflow risk: entries whose English is wider (20 or 24 px font) or has more lines than
its Japanese, outside the measured boxes. usage: .venv/bin/python tools/dev/panelrisk.py out.json"""
import sys, json, collections
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import tl, msgscript, text

def jp_px(toks, full):
    return tl.jp_px(toks) * full // 24

def en_px(toks, font):
    tl.FONT = font
    return tl.measure(toks)[0]

def verified(n, i):
    if n <= 16 or n == 21: return True                 # message window (pages itself)
    if 17 <= n <= 20 and i < 200: return True
    if n == 23 and 84 <= i < 424: return True
    if n == 22 and i < 458: return True               # item descriptions (measured)
    if 28 <= n <= 32: return True
    if n == 27 and i >= 181: return True
    return False

def main():
  out = collections.defaultdict(list)
  for n in range(17, 33):
      for e in json.load(open(tl.setup.msg_json(n), encoding='utf-8')):
          i = e['id']
          if not e['en'] or verified(n, i): continue
          jt = msgscript.tokens(text.encode(e['jp']))
          et = msgscript.tokens(text.encode(e['en']))
          jl = [l for l in tl.lines_of([t for t in jt if t[0] in ('text','inline','nl')])]
          el = [l for l in tl.lines_of([t for t in et if t[0] in ('text','inline','nl')])]
          jl = [l for l in jl if l] or [[]]; el = [l for l in el if l] or [[]]
          js = max(jp_px(l, 20) for l in jl); jL = max(jp_px(l, 24) for l in jl)
          es = max(en_px(l, 'small') for l in el); eL = max(en_px(l, 'large') for l in el)
          wide = es > js or eL > jL
          more = len(el) > len(jl)
          if wide or more:
              out[n].append((i, len(jl), len(el), js, es, jL, eL))
  for n in sorted(out):
      r = out[n]
      ids = [x[0] for x in r]
      print('msg%02d: %d at risk (more lines %d, wider %d); ids %s' % (n, len(r), sum(x[2] > x[1] for x in r),
            sum(x[4] > x[3] or x[6] > x[5] for x in r), ' '.join(map(str, ids[:25])) + (' ...' if len(ids) > 25 else '')))
  json.dump({n: v for n, v in out.items()}, open(sys.argv[1], 'w'))

if __name__ == '__main__':
    main()
