"""The disc this patch is for: Taiko Risshiden V, Koei the Best (SLPM-66267).

The original release (SLPM-65674) was supported up to v0.10.3; its addresses live on in
git history. Best was rebuilt with another compiler, so every ELF address differs.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIAL = 'SLPM-66267'
ELF = 'SLPM_662.67'
CLEAN = os.path.join(ROOT, 'taiko_risshiden_5_best.iso')
CLEAN_SHA1 = '345e3c2d28e5ce035c36b1709b08f826e5899bc9'
CLEAN_SIZE = 1576206336
CLEAN_CRC32 = '45c7d445'
CLEAN_MD5 = 'cd37b6da12cf2e66fedbc02314a75a0e'

def extract(name):
    """Path of a file extracted from the clean disc (extract/, git-ignored; dev tools)."""
    return os.path.join(ROOT, 'extract', name)
