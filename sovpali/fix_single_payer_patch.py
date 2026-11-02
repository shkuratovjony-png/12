from pathlib import Path

p = Path('patch_single_payer_intro.py')
s = p.read_text(encoding='utf-8')
s = s.replace("block = r'''\n", 'block = r"""\n', 1)
s = s.replace("\n'''\n\n# timedelta is already imported", '\n"""\n\n# timedelta is already imported', 1)
p.write_text(s, encoding='utf-8')
print('[build] single-payer patch quoting repaired', flush=True)
