from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
start = s.find('def set_funnel(')
if start == -1:
    raise SystemExit('[build] set_funnel not found')
end = s.find('\ndef ', start + 1)
if end == -1:
    raise SystemExit('[build] end of set_funnel not found')

new = '''def set_funnel(uid, step, rank, action=''):
    t = now()
    execute(\"\"\"INSERT INTO funnel_state(user_id,current_step,current_rank,max_rank,last_action,updated_at)
             VALUES(?,?,?,?,?,?)
             ON CONFLICT(user_id) DO UPDATE SET
               current_step=excluded.current_step,
               current_rank=excluded.current_rank,
               max_rank=CASE WHEN funnel_state.max_rank > excluded.max_rank THEN funnel_state.max_rank ELSE excluded.max_rank END,
               last_action=excluded.last_action,
               updated_at=excluded.updated_at\"\"\",
            (uid, step, rank, rank, action, t))
'''

s = s[:start] + new + s[end:]
p.write_text(s, encoding='utf-8')
print('[build] funnel placeholder mismatch fixed', flush=True)
