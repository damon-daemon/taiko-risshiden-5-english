"""Message window: let a line hold more than 30 characters.

The message window (layout function 0x2F97A0, window object in s5) gives every
character its own text object from a fixed array slot[3 lines][30 columns] at
window+0x98 (+line*0x78 +col*4), and logs each character to the backlog at column
x/12. With proportional English a 480-pixel line holds ~60 characters: columns 30+
spill into the next line's slots and are lost when that line is drawn.

The patch rewrites the per-character block (0x2F9A78-0x2F9BCC): consecutive ASCII
characters of one colour share the slot of the run's first character, whose text is
re-set to the whole run, so a line uses one slot per run instead of one per
character. Backlog columns become max(x/12, previous column + bytes) so English is
logged contiguously. The run buffer lives in the stack frame, enlarged from 0xA0 to
0x120 bytes; s6/s7 (pointers to sp+0x9D/0x9E in the original) are freed for use.

Frame locals: 0x88 run length (0 = no run), 0x8C run colour, 0x90 next backlog
column, 0xA0-0x11F run text (NUL-terminated). The run length is not checked (no
room); a line of the window never holds more than RUN_MAX bytes if the text tools
keep every line under that.
Slots are created with a maximum width of 64 pixels (+0x1C), which would wrap and
clip a run; new slots get 0 (no limit).
"""
from asm import assemble

BASE, FOFF = 0x100000, 0x80
FN = 0x2F97A0
BLOCK, BLOCK_END = 0x2F9A78, 0x2F9BCC
LOOP = 0x2F97F0
SET_POS, SET_COLOUR, SET_TEXT, SHOW = 0x46A3D0, 0x46A580, 0x469C60, 0x46A8B0
SKIP_AT_LINE_START = 0x2F9150
LOG = 0x2FB390
LOG_OBJ = 0x6D3FF0
FRAME, NEW_FRAME = 0xA0, 0x120
RUN_MAX = 0x7E                  # run buffer: the tl validator keeps lines shorter

def block():
    return assemble(BLOCK, [
        ('lw', 'v0', 0x7C, 's5'),              # column
        ('bnez', 'v0', 'create'),
        ('nop',),
        ('jal', SKIP_AT_LINE_START),           # line start: skip leading blanks
        ('addu', 'a0', 's3', 'zero'),
        ('bnez', 'v0', LOOP),
        ('sw', 'zero', 0x88, 'sp'),            # new line: no run, backlog column 0
        ('sw', 'zero', 0x90, 'sp'),
        'create:',
        ('lw', 't0', 0x80, 's5'),              # s6 = window + line*0x78 + col*4
        ('addiu', 'v1', 'zero', 0x78),
        ('mult', 'v1', 't0', 'v1'),
        ('addu', 'v1', 's5', 'v1'),
        ('lw', 't1', 0x7C, 's5'),
        ('sll', 't1', 't1', 2),
        ('addu', 's6', 'v1', 't1'),
        ('sltiu', 'at', 's3', 0x80),
        ('beqz', 'at', 'newslot'),             # not ASCII
        ('lw', 'v0', 0x88, 'sp'),
        ('beqz', 'v0', 'newslot'),             # no run open
        ('lw', 't3', 0x8C, 'sp'),
        ('bne', 't3', 's2', 'newslot'),        # colour changed
        ('addiu', 'a2', 'sp', 0xA0),
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
        ('sw', 's2', 0x8C, 'sp'),
        ('lw', 'v0', 0x7C, 's5'),
        ('addiu', 'v0', 'v0', 1),
        ('sw', 'v0', 0x7C, 's5'),
        'log:',                                # backlog column = max(x/12, next)
        ('lw', 'v1', 0x84, 's5'),
        'log2:',
        ('addiu', 'at', 'zero', 12),
        ('div', 'v1', 'at'),
        ('lw', 'v0', 0x90, 'sp'),
        ('lui', 'a0', LOG_OBJ >> 16),
        ('mflo', 'a2'),
        ('slt', 'at', 'a2', 'v0'),
        ('movn', 'a2', 'v0', 'at'),
        ('sltiu', 'at', 's3', 0x100),
        ('addiu', 'v0', 'a2', 2),
        ('subu', 'v0', 'v0', 'at'),
        ('sw', 'v0', 0x90, 'sp'),
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
    assert word(FN) == 0x27BDFF60 and word(0x2F9C08) == 0x27BD00A0
    assert word(0x2F97E8) == 0x27B6009D and word(0x2F97EC) == 0x27B7009E
    code = block()
    assert len(code) <= BLOCK_END - BLOCK, len(code) // 4
    put(BLOCK, code.ljust(BLOCK_END - BLOCK, b'\0'))
    put(FN, assemble(FN, [('addiu', 'sp', 'sp', -NEW_FRAME)]))
    put(0x2F9C08, assemble(0x2F9C08, [('addiu', 'sp', 'sp', NEW_FRAME)]))
    # s6/s7 no longer hold sp+0x9D/0x9E: initialise the run state instead
    put(0x2F97E8, assemble(0x2F97E8, [('sw', 'zero', 0x88, 'sp'), ('sw', 'zero', 0x90, 'sp')]))
    put(0x2F9954, assemble(0x2F9954, [('sb', 'a0', 0x9D, 'sp')]))
    put(0x2F995C, assemble(0x2F995C, [('sb', 'zero', 0x9E, 'sp')]))
    put(0x2F9970, assemble(0x2F9970, [('sb', 'zero', 0x9D, 'sp')]))
