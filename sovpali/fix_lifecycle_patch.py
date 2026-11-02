from pathlib import Path

p=Path('patch_lifecycle_funnel.py')
s=p.read_text(encoding='utf-8')
old='startup="await bot.initialize(); await bot.start(); xm_init_db(); asyncio.create_task(xm_maintenance(bot.bot))"'
new='startup="xm_init_db(); await bot.initialize(); await bot.start(); asyncio.create_task(xm_maintenance(bot.bot))"'
if old not in s:
    raise SystemExit('[build] lifecycle fixer: expected startup template not found')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('[build] lifecycle startup compatibility repaired',flush=True)
