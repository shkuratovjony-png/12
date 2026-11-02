from pathlib import Path

p = Path('patch_free_communication_test.py')
s = p.read_text(encoding='utf-8')
old = "        cur = c.execute('''INSERT INTO communication_requests(pair_low,pair_high,requester_user_id,target_user_id,score,status,created_at)\n                           VALUES(?,?,?,?,?,'pending',?) RETURNING id''',\n"
new = "        cur = c.execute(\"INSERT INTO communication_requests(pair_low,pair_high,requester_user_id,target_user_id,score,status,created_at) VALUES(?,?,?,?,?,'pending',?) RETURNING id\",\n"
if old not in s:
    raise SystemExit('[build] free-communication SQL quoting target not found')
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('[build] free communication patch SQL quoting repaired', flush=True)
