from pathlib import Path

p=Path('app.py')
s=p.read_text(encoding='utf-8')
start=s.find("@app.get('/admin/lifecycle')")
if start==-1:
    raise SystemExit('[build] lifecycle runtime fixer: admin route not found')
end=s.find('# -----------------------------------------------------------------------------',start)
if end==-1:
    raise SystemExit('[build] lifecycle runtime fixer: route end not found')
route=s[start:end].rstrip()+"\n\n"
s=s[:start]+s[end:]
health=s.find("@app.get('/health')")
if health==-1:
    raise SystemExit('[build] lifecycle runtime fixer: health anchor not found')
s=s[:health]+route+s[health:]
p.write_text(s,encoding='utf-8')
print('[build] lifecycle admin route moved after auth helpers',flush=True)
