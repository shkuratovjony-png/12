from pathlib import Path

p=Path('app.py')
s=p.read_text(encoding='utf-8')
anchor="from pair_web import pair_link, register_pair_web\n"
if anchor not in s: raise SystemExit('[build] motion: pair-web import not found')
if 'from pair_motion import register_pair_motion' not in s:
    s=s.replace(anchor,anchor+"from pair_motion import register_pair_motion\n",1)
anchor="register_pair_web(app, globals())\n"
if anchor not in s: raise SystemExit('[build] motion: route registration missing')
if 'register_pair_motion(app, globals())' not in s:
    s=s.replace(anchor,anchor+"register_pair_motion(app, globals())\n",1)
p.write_text(s,encoding='utf-8')
print('[build] real profile motion site connected to shared database',flush=True)
