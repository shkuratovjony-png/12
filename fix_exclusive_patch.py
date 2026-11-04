from pathlib import Path

p = Path('patch_exclusive_matching.py')
s = p.read_text(encoding='utf-8')

# Repair outer raw-string delimiters so embedded SQL triple-quotes are valid.
s = s.replace("block = r'''", 'block = r"""', 1)
s = s.replace("# ---------------------------------------------------------------------------\n\n'''\n\ns = s.replace(anchor", '# ---------------------------------------------------------------------------\n\n"""\n\ns = s.replace(anchor', 1)
s = s.replace("admin_block = r'''", 'admin_block = r"""', 1)
s = s.replace("\n'''\nif admin_anchor in s:", '\n"""\nif admin_anchor in s:', 1)

# Initialize the matching table inside start_bot. By that point the existing
# application startup has already run init_db(), and this anchor is stable even
# when backup/analytics patches change the main guard.
old_start = 's = s.replace(start_anchor, start_anchor + "; asyncio.create_task(xm_maintenance(bot.bot))", 1)'
new_start = 's = s.replace(start_anchor, "xm_init_db(); " + start_anchor + "; asyncio.create_task(xm_maintenance(bot.bot))", 1)'
if old_start in s:
    s = s.replace(old_start, new_start, 1)

section_start = s.find('# Ensure DB tables are available before the bot starts.')
section_end = s.find('# Add a simple admin view for queue health and conversion.', section_start)
if section_start != -1 and section_end != -1:
    s = s[:section_start] + '# Matching tables are initialized in start_bot after base DB setup.\n\n' + s[section_end:]

p.write_text(s, encoding='utf-8')
print('[build] exclusive matching patch compatibility repaired', flush=True)
