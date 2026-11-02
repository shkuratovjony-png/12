from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
old = "if __name__=='__main__':\n    init_db(); threading.Thread(target=bot_thread,daemon=True).start(); serve(app,host='0.0.0.0',port=PORT,threads=8)"
new = """if __name__=='__main__':
    init_db()
    try:
        from backup_b2 import start_backup_worker
        start_backup_worker()
    except Exception as e:
        print(f'[backup] startup warning: {type(e).__name__}: {e}', flush=True)
    threading.Thread(target=bot_thread,daemon=True).start()
    serve(app,host='0.0.0.0',port=PORT,threads=8)"""
if old not in s:
    raise SystemExit('[build] app startup block not found')
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('[build] automatic B2 backup worker wired', flush=True)
