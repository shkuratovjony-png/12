from pathlib import Path
import re

p=Path('app.py')
s=p.read_text(encoding='utf-8')

if 'import hashlib,hmac' not in s:
    marker='from __future__ import annotations\n'
    if marker in s:
        s=s.replace(marker, marker+'import hashlib,hmac\n', 1)
    else:
        s='import hashlib,hmac\n'+s

pattern=r"request\.form\.get\(['\"]u['\"]\)\s*==\s*ADMIN_(?:USER|USERNAME)\s+and\s+request\.form\.get\(['\"]p['\"]\)\s*==\s*ADMIN_PASSWORD"
replacement=(
    "hmac.compare_digest(request.form.get('u',''), 'evgeniy_admin') and "
    "hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', request.form.get('p','').encode('utf-8'), "
    "bytes.fromhex('82befa010c7d0e78572f1174eb3a1025'), 300000).hex(), "
    "'6a29605bb690399b352de64c89ff9ae5bbd8c24150806f45b9350be4fe252a02')"
)
s2,n=re.subn(pattern,replacement,s,count=1)
if n!=1:
    raise SystemExit(f'[build] admin credential target count={n}')
p.write_text(s2,encoding='utf-8')
print('[build] hashed admin credentials applied', flush=True)
