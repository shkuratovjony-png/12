from pathlib import Path
import base64
import hashlib
from PIL import Image

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / 'retro3'
OUT = ROOT / 'retro_visuals.jpg'

EXPECTED = {
    '00.b64':'d632a1e63fe5234c2e7b828b074d4597a7f6b7f6',
    '01.b64':'46529991366403fe16fbfcfb20f4e9a6c603e66a',
    '02.b64':'59802cec3fbf9978e6d3e12bc1745cef48647c02',
    '03.b64':'e1d0d0dc2766c97fc3446bdc4fb5440e08939507',
    '04.b64':'63e785ceb85cfa11777248c77067b49b86bc962b',
    '05.b64':'277f7427bcb58e68277a2b6e85cc7f6d156dde94',
    '06.b64':'99a155bb83b664bcab84109b23616b0f897b62e9',
    '07.b64':'776c786c6b4fc0b6140197fa975c721b39ecdf49',
    '08.b64':'618337ad5cad4759ed49eef5191079bc018597b5',
    '09.b64':'513b14d5fc68c105460bc321ceb32e6809e06a97',
    '10.b64':'1cd83fd4c47530d32496abbcc99b8638a6923846',
    '11.b64':'ac16e17d3801b126d0f41aa03a0cfa1fb873ab93',
    '12.b64':'d632e7737303bea69131339d4d58ac3556e7575a',
    '13.b64':'1e47fd7f8739f6ebfcf7f8799b5d87d9803a37f9',
    '14.b64':'90d5cbd84264015285f1ee7e0bc1cfbb01c3e6da',
    '15.b64':'750738f3d958dc43d29098dee8493ad3cdc50736',
    '16.b64':'b45c75bdec13e816832acdaeab59365017a59ef8',
    '17.b64':'be3d7408bf2ce03fd6ef5eb56a9dd71605928055',
    '18.b64':'a666499ed1af550bc7fd1160359948b659d47745',
    '19.b64':'b758fa3ab9a8ac167c8a0e3611b799381cec586f',
    '20.b64':'13ca0040a3a9d0499c3bd08a0bfbea80ffc79b6e',
    '21.b64':'2569314bdc289db4bb4fe9b95d3bfb252afc8bd4',
    '22.b64':'f180a350bd59af2abe95cb53552cab348e484093',
}

def git_blob_sha(text: str) -> str:
    data = text.encode('ascii')
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()

texts = {}
for i in range(21):
    name = f'{i:02d}.b64'
    p = PARTS / name
    if not p.exists():
        raise SystemExit(f'[build] retro visual chunk missing: {name}')
    text = p.read_text(encoding='ascii').strip()
    if len(text) != 4000:
        raise SystemExit(f'[build] retro visual chunk bad size: {name}={len(text)}')
    got = git_blob_sha(text)
    if got != EXPECTED[name]:
        raise SystemExit(f'[build] retro visual chunk checksum mismatch: {name} got={got}')
    texts[name] = text

# The final 4,440 chars can be represented as two normal files (4000 + 440),
# or as a single combined 21.b64 payload. Accept either form, but checksum both
# logical pieces independently before materializing the atlas.
p21 = PARTS / '21.b64'
p22 = PARTS / '22.b64'
t21 = p21.read_text(encoding='ascii').strip() if p21.exists() else ''
t22 = p22.read_text(encoding='ascii').strip() if p22.exists() else ''
if len(t21) == 4440:
    logical21, logical22 = t21[:4000], t21[4000:]
elif len(t21) == 4000 and len(t22) == 440:
    logical21, logical22 = t21, t22
else:
    raise SystemExit(f'[build] retro visual tail bad sizes: 21={len(t21)} 22={len(t22)}')
if git_blob_sha(logical21) != EXPECTED['21.b64']:
    raise SystemExit('[build] retro visual chunk checksum mismatch: 21.b64')
if git_blob_sha(logical22) != EXPECTED['22.b64']:
    raise SystemExit('[build] retro visual chunk checksum mismatch: 22.b64')

text = ''.join(texts[f'{i:02d}.b64'] for i in range(21)) + logical21 + logical22
if len(text) != 88440:
    raise SystemExit(f'[build] retro visual base64 bad length: {len(text)}')
raw = base64.b64decode(text, validate=True)
if len(raw) != 66328:
    raise SystemExit(f'[build] unexpected retro atlas size: {len(raw)}')
OUT.write_bytes(raw)
with Image.open(OUT) as im:
    if im.size != (900, 338):
        raise SystemExit(f'[build] retro atlas bad dimensions: {im.size}')
    im.verify()
print(f'[build] retro visual atlas materialized: {len(raw)} bytes', flush=True)
