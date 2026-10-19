"""Create the working folder script/ from your own disc image and the English in tl/.

script/ holds the Japanese text extracted from the disc next to the English, so it
is generated on each machine and never distributed. Run this once after cloning
(and again after editing tl/), then tools/build.py.

usage: .venv/bin/python tools/setup.py [clean.iso]
"""
import hashlib, json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
import iso, msgfile, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'script')
TL = os.path.join(ROOT, 'tl')
CLEAN = os.path.join(ROOT, 'taiko_risshiden_5.iso')
CLEAN_SHA1 = '9d8bc973f6dca388a6982bc55d1ff76e0c9e34d3'
MSG = 'TAI5MSG.DAT'

def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()

def msg_json(n):
    return os.path.join(SCRIPT, 'msg', 'msg%02d.json' % n)

def export_messages(path):
    os.makedirs(os.path.join(SCRIPT, 'msg'), exist_ok=True)
    for n, strings in enumerate(msgfile.blocks(iso.read_file(path, MSG))):
        rows = [{'id': i, 'jp': text.decode(s), 'en': ''} for i, s in enumerate(strings)]
        json.dump(rows, open(msg_json(n), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CLEAN
    digest = sha1(path)
    if digest != CLEAN_SHA1:
        sys.exit('%s: SHA-1 %s does not match the clean dump (%s)' % (path, digest, CLEAN_SHA1))
    export_messages(path)
    import tl
    ok = True
    for n in range(len(os.listdir(os.path.join(SCRIPT, 'msg')))):
        if os.path.exists(os.path.join(TL, 'msg%02d.txt' % n)):
            ok &= tl.apply(n, check=False)
    if ok:
        import overflow
        errs = overflow.check_messages(overflow.json_getter(), overflow.clean_elf())
        print('\n'.join(errs))
        ok = not errs
    if not ok:
        sys.exit('errors in tl/: fix them and run setup again')
    print('script/ ready; now run tools/build.py')

if __name__ == '__main__':
    main()
