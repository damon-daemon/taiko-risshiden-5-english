"""TAI5MSG.DAT: the message file.

File: (offset, size) u32 pairs, zero-terminated, then blocks at 0x40-aligned offsets.
Each block byte is stored as (plain + 0xA5) & 0xFF; the zero padding after a block is
not obfuscated. Plain block: u16 count, u32 offsets[count] (from block start), then the
strings. A string is the byte range up to the next string (normally ending 05 05 05,
sometimes with several 05 05 05-separated parts). Strings are never shared.
"""
import struct

KEY = 0xA5
ALIGN = 0x40
HEADER = 0x140          # room for the offset table (33 blocks use 0x108)

def _plain(raw):
    return bytes((x - KEY) & 0xFF for x in raw)

def _stored(plain):
    return bytes((x + KEY) & 0xFF for x in plain)

def blocks(data):
    """-> list of blocks, each a list of string byte strings."""
    table, i = [], 0
    while (e := struct.unpack_from('<II', data, i))[0]:
        table.append(e)
        i += 8
    out = []
    for off, size in table:
        raw = data[off:off + size]
        b = _plain(raw)
        n = struct.unpack_from('<H', b)[0]
        ptrs = list(struct.unpack_from('<%dI' % n, b, 2))
        end = len(raw.rstrip(b'\0'))
        out.append([b[a:c] for a, c in zip(ptrs, ptrs[1:] + [end])])
    return out

def pack_block(strings):
    n = len(strings)
    body, ptrs = bytearray(), []
    for s in strings:
        ptrs.append(2 + 4 * n + len(body))
        body += s
    return _stored(struct.pack('<H%dI' % n, n, *ptrs) + bytes(body))

def pack(block_list):
    assert 8 * (len(block_list) + 1) <= HEADER
    table, out = [], bytearray(HEADER)
    for strings in block_list:
        blk = pack_block(strings)
        padded = (len(blk) + ALIGN - 1) // ALIGN * ALIGN
        table.append((len(out), padded))
        out += blk + bytes(padded - len(blk))
    for k, e in enumerate(table):
        struct.pack_into('<II', out, 8 * k, *e)
    # the clean file ends right after the last block's data, rounded up to 16 bytes
    last = pack_block(block_list[-1])
    end = table[-1][0] + (len(last) + 15) // 16 * 16
    return bytes(out[:end])
