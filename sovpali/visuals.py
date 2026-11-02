from io import BytesIO
from functools import lru_cache
import random
import requests
from PIL import Image, ImageOps, ImageEnhance, ImageDraw, ImageFilter

W,H=1200,675

# Direct image CDN URLs. Unlike the old /photos/{id}/download route,
# these return the actual JPG bytes and are much more reliable on Render.
URLS={
    'welcome':'https://images.unsplash.com/photo-1768508948944-7441672df71e?auto=format&fit=crop&w=1600&q=85',
    'gender':'https://images.unsplash.com/photo-1768508948944-7441672df71e?auto=format&fit=crop&w=1600&q=85',
    'birth':'https://images.unsplash.com/photo-1729335511883-29eade10006b?auto=format&fit=crop&w=1600&q=85',
    'place':'https://images.unsplash.com/photo-1594886801338-b81548345f77?auto=format&fit=crop&w=1600&q=85',
    'city':'https://images.unsplash.com/photo-1594886801338-b81548345f77?auto=format&fit=crop&w=1600&q=85',
    'goal':'https://images.unsplash.com/photo-1782786661330-33cfd2d0e05d?auto=format&fit=crop&w=1600&q=85',
    'priority':'https://images.unsplash.com/photo-1782786661330-33cfd2d0e05d?auto=format&fit=crop&w=1600&q=85',
    'photo':'https://images.unsplash.com/photo-1768508948944-7441672df71e?auto=format&fit=crop&w=1600&q=85',
    'matching':'https://images.unsplash.com/photo-1782786661330-33cfd2d0e05d?auto=format&fit=crop&w=1600&q=85',
    'profile':'https://images.unsplash.com/photo-1768508948944-7441672df71e?auto=format&fit=crop&w=1600&q=85',
    'pairs':'https://images.unsplash.com/photo-1768508948944-7441672df71e?auto=format&fit=crop&w=1600&q=85',
    'chats':'https://images.unsplash.com/photo-1594886801338-b81548345f77?auto=format&fit=crop&w=1600&q=85',
    'more':'https://images.unsplash.com/photo-1729335511883-29eade10006b?auto=format&fit=crop&w=1600&q=85',
}

def _prepare(raw:bytes)->bytes:
    im=Image.open(BytesIO(raw)).convert('RGB')
    im=ImageOps.fit(im,(W,H),method=Image.Resampling.LANCZOS,centering=(0.5,0.48))
    im=ImageEnhance.Color(im).enhance(1.14)
    im=ImageEnhance.Contrast(im).enhance(1.06)
    im=ImageEnhance.Brightness(im).enhance(1.04)
    bio=BytesIO(); im.save(bio,'JPEG',quality=90,optimize=True,progressive=True)
    return bio.getvalue()

def _fallback(theme:str)->bytes:
    # Bright premium fallback instead of the old black rectangle.
    top=(40,26,78); bottom=(176,69,118)
    im=Image.new('RGB',(W,H),top); px=im.load()
    for y in range(H):
        t=y/(H-1)
        r=int(top[0]*(1-t)+bottom[0]*t); g=int(top[1]*(1-t)+bottom[1]*t); b=int(top[2]*(1-t)+bottom[2]*t)
        for x in range(W): px[x,y]=(r,g,b)
    glow=Image.new('RGBA',(W,H),(0,0,0,0)); d=ImageDraw.Draw(glow); rnd=random.Random(theme)
    for _ in range(28):
        x=rnd.randint(0,W); y=rnd.randint(0,H); rr=rnd.randint(18,75)
        d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(255,210,160,rnd.randint(18,55)))
    glow=glow.filter(ImageFilter.GaussianBlur(28)); im=Image.alpha_composite(im.convert('RGBA'),glow).convert('RGB')
    bio=BytesIO(); im.save(bio,'JPEG',quality=90,optimize=True); return bio.getvalue()

@lru_cache(maxsize=32)
def visual(theme:str)->bytes:
    url=URLS.get(theme,URLS['welcome'])
    try:
        r=requests.get(url,timeout=18,headers={'User-Agent':'Mozilla/5.0 SovpaliBot/3.0'})
        r.raise_for_status()
        if 'image' not in r.headers.get('content-type','').lower():
            raise ValueError('photo host returned non-image content')
        return _prepare(r.content)
    except Exception as e:
        print(f'[visual-download] {theme}: {e}',flush=True)
        return _fallback(theme)

def animation(theme:str='welcome')->bytes:
    return visual(theme)

def as_file(data:bytes,name:str):
    bio=BytesIO(data); bio.name=name.rsplit('.',1)[0]+'.jpg'; return bio
