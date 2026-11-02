from pathlib import Path

p = Path('patch_single_payer_intro.py')
s = p.read_text(encoding='utf-8')
s = s.replace("block = r'''\n", 'block = r"""\n', 1)
s = s.replace("\n'''\n\n# timedelta is already imported", '\n"""\n\n# timedelta is already imported', 1)
s = s.replace('    """Atomically reserve both people before opening a checkout.\n\n    Returns (\'reserved\', order) or (\'busy\', existing_order_or_none).\n    The two participant-lock inserts make opposite-direction simultaneous buys\n    impossible: A->B and B->A cannot both commit.\n    """', "    '''Atomically reserve both people before opening a checkout.\n\n    Returns ('reserved', order) or ('busy', existing_order_or_none).\n    The two participant-lock inserts make opposite-direction simultaneous buys\n    impossible: A->B and B->A cannot both commit.\n    '''", 1)
s = s.replace('    """Idempotent post-webhook transition. Does not trust Telegram callbacks."""', "    '''Idempotent post-webhook transition. Does not trust Telegram callbacks.'''", 1)
p.write_text(s, encoding='utf-8')
print('[build] single-payer patch quoting repaired', flush=True)
