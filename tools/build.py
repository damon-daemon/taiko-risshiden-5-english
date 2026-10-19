"""Rebuild the disc image with the translated text and produce a patch.

usage: .venv/bin/python tools/build.py [clean.iso] [out.iso]
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
import battlename, datafile, evtl, gfx, menugfx, msgbuf, nameentry, scenarios, elfseg, elfstr, elftables, iso, msgfile, msgwindow, nameplate, names, setup, text, ui, vwf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF = 'SLPM_656.74'
DATA = 'TAI5DATA.DAT'

def build_messages(clean_msg):
    blocks = msgfile.blocks(clean_msg)
    changed = 0
    for n in range(len(blocks)):
        for row in json.load(open(setup.msg_json(n), encoding='utf-8')):
            data = text.encode(row['en'] or row['jp'])
            if data != blocks[n][row['id']]:
                blocks[n][row['id']] = data
                changed += 1
    msgbuf.check([len(msgfile.pack_block(b)) for b in blocks])
    return msgfile.pack(blocks), changed

def main():
    clean = sys.argv[1] if len(sys.argv) > 1 else setup.CLEAN
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'build', 'taiko_risshiden_5_en.iso')
    recs = iso.records(clean)
    msg, changed = build_messages(iso.read_file(clean, setup.MSG, recs))
    print('messages: %d strings changed' % changed)
    elf = bytearray(iso.read_file(clean, ELF, recs))
    data = bytearray(iso.read_file(clean, DATA, recs))
    clean_elf = bytes(elf)
    fonts = vwf.apply(elf, lambda i: datafile.entry(data, clean_elf, i))
    datafile.apply(data, elf, fonts)
    datafile.apply(data, elf, scenarios.apply(data, elf))
    datafile.apply(data, elf, menugfx.apply(data, elf, lambda i: datafile.entry(data, clean_elf, i)))
    datafile.apply(data, elf, gfx.apply(elf, lambda i: datafile.entry(data, clean_elf, i)))
    ev = evtl.apply_all()
    datafile.apply(data, elf, ev)
    print('events: %d entries' % len(ev))
    msgwindow.apply(elf)
    seg = elfseg.Segment()
    n = names.apply(elf, data, seg, clean_elf)
    nameplate.apply(elf, seg)
    print('ui: %d strings' % ui.apply(elf, seg))
    t = elftables.apply(elf, clean_elf)
    elftables.apply_code(elf, seg)
    n_str, n_moved = elfstr.apply(elf, clean_elf, seg)
    battlename.apply(elf, seg)
    nameentry.apply(elf)
    msgbuf.apply(elf, seg)
    print('elf strings: %d (%d moved)' % (n_str, n_moved))
    print('tables: %d names in %d tables' % (sum(t.values()), len(t)))
    heap = elfseg.apply(elf, seg)
    print('names: %d Japanese name pairs -> English; segment %d bytes, heap from 0x%X'
          % (n, len(seg.data), heap))
    print('fonts: proportional Latin glyphs in entries %s' % sorted(fonts))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    moved = iso.write_image(clean, out, {setup.MSG: msg, ELF: bytes(elf), DATA: bytes(data)})
    print('rebuilt %s%s' % (out, ' (moved: %s)' % ', '.join(moved) if moved else ''))
    patch = os.path.splitext(out)[0] + '.xdelta'
    try:
        subprocess.run(['xdelta3', '-e', '-f', '-9', '-S', 'djw', '-B', str(1 << 30), '-s', clean, out, patch], check=True)
        print('patch %s (%d bytes)' % (patch, os.path.getsize(patch)))
    except FileNotFoundError:
        print('xdelta3 not installed; skipped patch')

if __name__ == '__main__':
    main()
