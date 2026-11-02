from pathlib import Path

p = Path('setup_runner.py')
s = p.read_text(encoding='utf-8')
old = """def launch_app(token: str):
    os.environ['BOT_TOKEN'] = token.strip()
    runpy.run_path('app.py', run_name='__main__')
"""
new = """def launch_app(token: str):
    os.environ['BOT_TOKEN'] = token.strip()
    try:
        from backup_b2 import start_backup_worker
        start_backup_worker()
    except Exception as e:
        print(f'[backup] startup warning: {type(e).__name__}: {e}', flush=True)
    runpy.run_path('app.py', run_name='__main__')
"""
if old not in s:
    raise SystemExit('[build] setup runner launch block not found')
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('[build] automatic B2 backup worker wired via setup runner', flush=True)
