"""Message window: let a line hold more than 30 characters.

The message window (layout function 0x2FD5F0, window object in s5) gives every
character its own text object from a fixed array slot[3 lines][30 columns] at
window+0x98 (+line*0x78 +col*4), and logs each character to the backlog at column
x/12. With proportional English a 480-pixel line holds ~60 characters: columns 30+
spill into the next line's slots and are lost when that line is drawn.

The patch rewrites the per-character block (0x2FD894-0x2FD9E0): consecutive ASCII
characters of one colour share the slot of the run's first character, whose text is
re-set to the whole run, so a line uses one slot per run instead of one per
character. A run holds at most RUN_MAX (127) bytes: a character is appended only
while (char | run length) < 0x80, else it opens a new slot (at the same pen position),
so a long line can never write past the run buffer. Backlog columns become max(x/12, previous column + bytes) so English is
logged contiguously. The run buffer lives in the stack frame, enlarged from 0xA0 to
0x130 bytes; s6/s7 (pointers to sp+0x9D/0x9E in the original) are freed for use.

Frame locals: 0x88 run length (0 = no run), 0x8C next backlog column, 0x90 run
colour (0x88/0x8C are cleared together with one sd), 0xA0-0x12F run text (NUL-terminated, at most 127 + 1 bytes).
Slots are created with a maximum width of 64 pixels (+0x1C), which would wrap and
clip a run; new slots get 0 (no limit).
"""
from asm import assemble

BASE, FOFF = 0x100000, 0x80
FN = 0x2FD5F0                   # Koei the Best addresses (same registers as the original)
FN_RET = 0x2FDA28               # addiu sp, sp, 0xA0 (epilogue)
BLOCK, BLOCK_END = 0x2FD894, 0x2FD9E0
LOOP = 0x2FD640
SET_POS, SET_COLOUR, SET_TEXT, SHOW = 0x4735E0, 0x473770, 0x472E60, 0x473A60
SKIP_AT_LINE_START = 0x2FCF80
LOG = 0x2FF200
S6_S7_INIT = 0x2FD638           # addiu s6, sp, 0x9D / addiu s7, sp, 0x9E
SB_S6_2, SB_S7, SB_S6_1 = 0x2FD794, 0x2FD79C, 0x2FD9E8   # sb a0/zero via s6/s7
LOG_OBJ = 0x6D4F80
FRAME, NEW_FRAME = 0xA0, 0x130
RUN_MAX = 0x7F                  # longest run (the append test caps it)

def block():
    return assemble(BLOCK, [
        ('lw', 'v0', 0x7C, 's5'),              # column
        ('bnez', 'v0', 'create'),
        ('nop',),
        ('jal', SKIP_AT_LINE_START),           # line start: skip leading blanks
        ('addu', 'a0', 's3', 'zero'),
        ('bnez', 'v0', LOOP),
        ('sd', 'zero', 0x88, 'sp'),            # new line: no run, backlog column 0
        'create:',                             # v0 = column (0 after the line-start call)
        ('lw', 't0', 0x80, 's5'),              # s6 = window + line*0x78 + col*4
        ('addiu', 'v1', 'zero', 0x78),
        ('mult', 'v1', 't0', 'v1'),
        ('addu', 'v1', 's5', 'v1'),
        ('sll', 't1', 'v0', 2),
        ('addu', 's6', 'v1', 't1'),
        ('lw', 'v0', 0x88, 'sp'),
        ('or', 'at', 's3', 'v0'),
        ('sltiu', 'at', 'at', 0x80),
        ('beqz', 'at', 'newslot'),             # not ASCII, or the run holds 127 bytes
        ('lw', 't3', 0x90, 'sp'),
        ('beqz', 'v0', 'newslot'),             # no run open
        ('addiu', 'a2', 'sp', 0xA0),
        ('bne', 't3', 's2', 'newslot'),        # colour changed
        ('addu', 't5', 'a2', 'v0'),            # append to the run, re-set its slot
        ('sb', 's3', 0, 't5'),
        ('sb', 'zero', 1, 't5'),
        ('addiu', 'v0', 'v0', 1),
        ('sw', 'v0', 0x88, 'sp'),
        ('lw', 'a0', 0x94, 's6'),
        ('jal', SET_TEXT),
        ('addu', 'a1', 'zero', 'zero'),
        ('lw', 'a0', 0x94, 's6'),
        ('jal', SHOW),
        ('addiu', 'a1', 'zero', 1),
        ('b', 'log2'),
        ('lw', 'v1', 0x84, 's5'),
        'newslot:',                            # as the original: one slot per char
        ('lw', 'a0', 0x98, 's6'),
        ('sh', 'zero', 0x1C, 'a0'),            # slot max width 64 -> none (runs)
        ('lw', 'a1', 0x90, 's5'),
        ('lw', 'v1', 0x84, 's5'),
        ('addu', 'a1', 'a1', 'v1'),            # x = origin + pen
        ('lw', 'a2', 0x88, 's5'),
        ('addiu', 'v1', 'zero', 26),
        ('mult', 'v1', 'a2', 'v1'),            # line * 26
        ('lw', 'v0', 0x94, 's5'),
        ('jal', SET_POS),
        ('addu', 'a2', 'v0', 'v1'),
        ('lw', 'a0', 0x98, 's6'),
        ('jal', SET_COLOUR),
        ('andi', 'a1', 's2', 0xFFFF),
        ('lw', 'a0', 0x98, 's6'),
        ('addu', 'a1', 'zero', 'zero'),
        ('jal', SET_TEXT),
        ('addiu', 'a2', 'sp', 0x9C),
        ('lw', 'a0', 0x98, 's6'),
        ('jal', SHOW),
        ('addiu', 'a1', 'zero', 1),
        ('sltiu', 'at', 's3', 0x80),           # ASCII opens a run
        ('sw', 'at', 0x88, 'sp'),
        ('sb', 's3', 0xA0, 'sp'),
        ('sb', 'zero', 0xA1, 'sp'),
        ('sw', 's2', 0x90, 'sp'),
        ('lw', 'v0', 0x7C, 's5'),
        ('addiu', 'v0', 'v0', 1),
        ('sw', 'v0', 0x7C, 's5'),
        'log:',                                # backlog column = max(x/12, next)
        ('lw', 'v1', 0x84, 's5'),
        'log2:',
        ('addiu', 'at', 'zero', 12),
        ('div', 'v1', 'at'),
        ('lw', 'v0', 0x8C, 'sp'),
        ('lui', 'a0', LOG_OBJ >> 16),
        ('mflo', 'a2'),
        ('slt', 'at', 'a2', 'v0'),
        ('movn', 'a2', 'v0', 'at'),
        ('sltiu', 'at', 's3', 0x100),
        ('addiu', 'v0', 'a2', 2),
        ('subu', 'v0', 'v0', 'at'),
        ('sw', 'v0', 0x8C, 'sp'),
        ('addiu', 'a0', 'a0', LOG_OBJ & 0xFFFF),
        ('addiu', 'a1', 'sp', 0x9C),
        ('jal', LOG),
        ('lw', 'a3', 0x80, 's5'),
        ('lw', 'v0', 0x84, 's5'),              # pen += width
        ('addu', 'v0', 'v0', 's1'),
        ('b', LOOP),
        ('sw', 'v0', 0x84, 's5'),
    ])

def apply(elf):
    def word(va):
        return int.from_bytes(elf[va - BASE + FOFF:va - BASE + FOFF + 4], 'little')
    def put(va, data):
        elf[va - BASE + FOFF:va - BASE + FOFF + len(data)] = data
    # sanity checks on the clean code
    assert word(FN) == 0x27BDFF60 and word(FN_RET) == 0x27BD00A0
    assert word(S6_S7_INIT) == 0x27B6009D and word(S6_S7_INIT + 4) == 0x27B7009E
    assert word(SB_S6_2) == 0xA2C40000 and word(SB_S7) == 0xA2E00000 and word(SB_S6_1) == 0xA2C00000
    assert word(BLOCK) == 0x8EA2007C, 'BLOCK is not lw v0, 0x7C(s5)'
    code = block()
    assert len(code) <= BLOCK_END - BLOCK, len(code) // 4
    put(BLOCK, code.ljust(BLOCK_END - BLOCK, b'\0'))
    put(FN, assemble(FN, [('addiu', 'sp', 'sp', -NEW_FRAME)]))
    put(FN_RET, assemble(FN_RET, [('addiu', 'sp', 'sp', NEW_FRAME)]))
    # s6/s7 no longer hold sp+0x9D/0x9E: initialise the run state instead
    put(S6_S7_INIT, assemble(S6_S7_INIT, [('sw', 'zero', 0x88, 'sp'), ('sw', 'zero', 0x8C, 'sp')]))
    put(SB_S6_2, assemble(SB_S6_2, [('sb', 'a0', 0x9D, 'sp')]))
    put(SB_S7, assemble(SB_S7, [('sb', 'zero', 0x9E, 'sp')]))
    put(SB_S6_1, assemble(SB_S6_1, [('sb', 'zero', 0x9D, 'sp')]))
