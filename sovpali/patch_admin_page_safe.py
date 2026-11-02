from pathlib import Path

p=Path('app.py')
s=p.read_text(encoding='utf-8')
old="return BASE.format(nav=nav,body=body)"
new="return BASE.replace('{nav}', nav).replace('{body}', body)"
if old not in s:
    raise SystemExit('[build] expected admin page format call not found')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('[build] admin page rendering made format-safe', flush=True)
