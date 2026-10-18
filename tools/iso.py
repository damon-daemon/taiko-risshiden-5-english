"""Minimal ISO 9660 access for the PS2 disc: read files, write a patched copy.

The game opens every file by name (sceCdSearchFile), so a rebuilt file may move to a
new LBA as long as its directory record is updated. Files that still fit in their
original sectors are rewritten in place; larger ones are moved into the space of the
padding file DUMMY.TR5 (never read by the game), which shrinks accordingly. The image
size, volume descriptors and every untouched sector stay as on the clean disc.
"""
import os, shutil, struct

SECTOR = 2048
PAD_FILE = 'DUMMY.TR5'

class Record:
    def __init__(self, path, rec_off, lba, size, is_dir):
        self.path, self.rec_off, self.lba, self.size, self.is_dir = path, rec_off, lba, size, is_dir

    @property
    def sectors(self):
        return (self.size + SECTOR - 1) // SECTOR

def _read_dir(f, lba, size, prefix, out):
    f.seek(lba * SECTOR)
    data = f.read(size)
    pos = 0
    while pos < len(data):
        n = data[pos]
        if n == 0:                      # records never cross sectors; skip to next
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        ext, length = struct.unpack_from('<I4xI', data, pos + 2)
        flags, nlen = data[pos + 25], data[pos + 32]
        name = data[pos + 33:pos + 33 + nlen]
        if name not in (b'\0', b'\1'):
            name = name.decode('ascii').split(';')[0]
            rec = Record(prefix + name, lba * SECTOR + pos, ext, length, bool(flags & 2))
            out[rec.path] = rec
            if rec.is_dir:
                _read_dir(f, ext, length, rec.path + '/', out)
        pos += n
    return out

def records(path):
    """{'SLPM_656.74': Record, 'MOVIE/KOEILOGO.PSS': Record, ...}"""
    with open(path, 'rb') as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        assert pvd[1:6] == b'CD001', 'not an ISO 9660 image'
        ext, length = struct.unpack_from('<I4xI', pvd, 156 + 2)
        return _read_dir(f, ext, length, '', {})

def read_file(path, name, recs=None):
    rec = (recs or records(path))[name]
    with open(path, 'rb') as f:
        f.seek(rec.lba * SECTOR)
        return f.read(rec.size)

def _set_record(f, rec, lba, size):
    f.seek(rec.rec_off + 2)
    f.write(struct.pack('<I', lba) + struct.pack('>I', lba) +
            struct.pack('<I', size) + struct.pack('>I', size))

def _write_extent(f, lba, data, clear_sectors):
    f.seek(lba * SECTOR)
    f.write(data)
    pad = clear_sectors * SECTOR - len(data)
    if pad > 0:
        f.write(bytes(pad))

EVICT_MAX = 16 << 20        # files up to this size may be moved to make room for a neighbour

def write_image(clean, out, files):
    """Copy clean to out and replace files ({iso name: bytes}). Returns moved names.

    A file that outgrows its sectors grows in place when the sectors after it are
    free or held only by small files (<= EVICT_MAX), which are then moved instead
    (TAI5DATA.DAT is followed by TAI5MSG.DAT); otherwise the file itself moves."""
    recs = records(clean)
    files = {n: d for n, d in files.items() if read_file(clean, n, recs) != d}
    place = {n: (r.lba, r.sectors) for n, r in recs.items() if not r.is_dir and n != PAD_FILE}
    pad = recs[PAD_FILE]
    free_lba, free_end = pad.lba, pad.lba + pad.sectors
    moved = []

    def relocate(name, need):
        nonlocal free_lba
        if free_lba + need > free_end:
            raise RuntimeError('%s: no room left in %s' % (name, PAD_FILE))
        place[name] = (free_lba, need)
        free_lba += need
        moved.append(name)

    for name, data in sorted(files.items(), key=lambda kv: -len(kv[1])):
        lba, have = place[name]
        need = (len(data) + SECTOR - 1) // SECTOR
        if need <= have:
            continue
        blockers = [n for n, (l, k) in place.items() if n != name and l < lba + need and l + k > lba]
        sizes = [len(files[n]) if n in files else recs[n].size for n in blockers]
        if all(sz <= EVICT_MAX for sz in sizes) and lba + need <= pad.lba:
            for n, sz in zip(blockers, sizes):
                relocate(n, max(place[n][1], (sz + SECTOR - 1) // SECTOR))
            place[name] = (lba, need)
        else:
            relocate(name, need)

    tmp = out + '.part'
    shutil.copyfile(clean, tmp)
    with open(tmp, 'r+b') as f:
        for name in moved:                                 # clear old copies first
            _write_extent(f, recs[name].lba, b'', recs[name].sectors)
        for name, (lba, k) in place.items():
            if name in files or name in moved:
                data = files[name] if name in files else read_file(clean, name, recs)
                clear = recs[name].sectors if lba == recs[name].lba else k
                _write_extent(f, lba, data, max(k if lba == recs[name].lba else 0, clear))
                _set_record(f, recs[name], lba, len(data))
        if free_lba != pad.lba:
            _set_record(f, pad, free_lba, (free_end - free_lba) * SECTOR)
    os.replace(tmp, out)
    return moved
