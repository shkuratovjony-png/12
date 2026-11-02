from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageEnhance, ImageOps, ImageStat

OUT = Path('assets')
OUT.mkdir(exist_ok=True)
W, H = 960, 540
UA = {'User-Agent': 'Mozilla/5.0 SovpaliBot/3.1'}

# В каждой теме ищем именно мужчину + женщину. Контекст фона меняется под вопрос.
QUERIES = {
    'welcome': 'romantic man woman couple sunset elegant',
    'gender': 'romantic man woman couple portrait elegant',
    'birth': 'romantic man woman couple astrology stars night',
    'place': 'romantic man woman couple travel old town sunset',
    'city': 'romantic man woman couple city night skyline',
    'goal': 'romantic man woman couple date sunset love',
    'priority': 'romantic man woman couple holding hands trust',
    'photo': 'romantic man woman couple selfie smiling',
    'matching': 'romantic man woman couple stars compatibility',
    'profile': 'romantic man woman couple portrait lifestyle',
    'pairs': 'romantic man woman couple close connection',
    'chats': 'romantic man woman couple cafe city',
    'more': 'romantic man woman couple walking city evening',
}


def candidates_pexels(query: str) -> list[str]:
    url = 'https://www.pexels.com/search/' + quote(query) + '/'
    text = requests.get(url, headers=UA, timeout=25).text
    found = re.findall(r'https://images\.pexels\.com/photos/\d+/pexels-photo-\d+\.jpeg[^"\'<> ]*', text)
    out = []
    for u in found:
        u = u.replace('&amp;', '&')
        base = u.split('?')[0]
        if base not in out:
            out.append(base)
    return out


def candidates_unsplash(query: str) -> list[str]:
    url = 'https://unsplash.com/s/photos/' + quote(query.replace(' ', '-'))
    text = requests.get(url, headers=UA, timeout=25).text
    found = re.findall(r'https://images\.unsplash\.com/photo-[^?"\'<> ]+', text)
    out = []
    for u in found:
        if u not in out:
            out.append(u)
    return out


def prepare(raw: bytes) -> bytes:
    im = Image.open(BytesIO(raw)).convert('RGB')
    if im.width < 600 or im.height < 400:
        raise ValueError('image too small')
    im = ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.43))
    # Сочная, но не кислотная подача для Telegram.
    im = ImageEnhance.Color(im).enhance(1.10)
    im = ImageEnhance.Contrast(im).enhance(1.06)
    im = ImageEnhance.Brightness(im).enhance(1.04)
    stat = ImageStat.Stat(im.resize((64, 36)))
    if sum(stat.mean) / 3 < 45:
        raise ValueError('image too dark')
    bio = BytesIO()
    im.save(bio, 'JPEG', quality=86, optimize=True, progressive=True)
    return bio.getvalue()


def fetch_image(url: str) -> bytes:
    sep = '&' if '?' in url else '?'
    final = url + sep + 'auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop'
    r = requests.get(final, headers=UA, timeout=30)
    r.raise_for_status()
    if 'image' not in r.headers.get('content-type', ''):
        raise ValueError('not image')
    return r.content


def vivid_fallback(name: str) -> bytes:
    # Никогда не отдаём чёрную заглушку: тёплый яркий фон как последняя страховка.
    im = Image.new('RGB', (W, H), (126, 63, 76))
    px = im.load()
    for y in range(H):
        t = y / max(1, H - 1)
        for x in range(W):
            s = x / max(1, W - 1)
            px[x, y] = (
                int(178 - 60*t + 22*s),
                int(95 - 28*t + 35*s),
                int(105 + 58*(1-t) + 15*s),
            )
    bio = BytesIO(); im.save(bio, 'JPEG', quality=84, optimize=True); return bio.getvalue()


def main():
    used = set()
    for name, query in QUERIES.items():
        dest = OUT / f'{name}.jpg'
        ok = False
        sources = []
        for getter in (candidates_pexels, candidates_unsplash):
            try:
                sources.extend(getter(query))
            except Exception as exc:
                print(f'[assets] {name}: search failed: {exc}', flush=True)
        for url in sources:
            if url in used:
                continue
            try:
                data = prepare(fetch_image(url))
                dest.write_bytes(data)
                used.add(url)
                print(f'[assets] {name}: ok', flush=True)
                ok = True
                break
            except Exception:
                continue
        if not ok:
            dest.write_bytes(vivid_fallback(name))
            print(f'[assets] {name}: vivid fallback', flush=True)

if __name__ == '__main__':
    main()
