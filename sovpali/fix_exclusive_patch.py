from pathlib import Path

p = Path('patch_exclusive_matching.py')
s = p.read_text(encoding='utf-8')
s = s.replace("block = r'''", 'block = r"""', 1)
s = s.replace("# ---------------------------------------------------------------------------\n\n'''\n\ns = s.replace(anchor", '# ---------------------------------------------------------------------------\n\n"""\n\ns = s.replace(anchor', 1)
s = s.replace("admin_block = r'''", 'admin_block = r"""', 1)
s = s.replace("\n'''\nif admin_anchor in s:", '\n"""\nif admin_anchor in s:', 1)
p.write_text(s, encoding='utf-8')
print('[build] exclusive matching patch delimiters repaired', flush=True)
