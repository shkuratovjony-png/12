from io import BytesIO
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter
import math, random

W,H=960,540
BG_TOP=(17,12,32)
BG_BOTTOM=(52,20,67)
GOLD=(236,195,120)
ROSE=(211,96,143)
IVORY=(248,238,224)

THEMES={
    'welcome':'heart', 'gender':'people', 'looking':'orbit', 'birth':'zodiac',
    'time':'clock', 'place':'pin', 'city':'city', 'goal':'rings',
    'priority':'diamond', 'photo':'portrait', 'matching':'constellation',
    'profile':'portrait', 'pairs':'heart', 'chats':'bubbles', 'more':'stars'
}

def _gradient():
    im=Image.new('RGB',(W,H),BG_TOP); p=im.load()
    for y in range(H):
        t=y/(H-1)
        r=int(BG_TOP[0]*(1-t)+BG_BOTTOM[0]*t)
        g=int(BG_TOP[1]*(1-t)+BG_BOTTOM[1]*t)
        b=int(BG_TOP[2]*(1-t)+BG_BOTTOM[2]*t)
        for x in range(W): p[x,y]=(r,g,b)
    return im

def _stars(draw, seed=7, shift=0):
    rnd=random.Random(seed)
    for i in range(85):
        x=(rnd.randrange(W)+shift*(i%5))%W; y=rnd.randrange(H)
        r=1 if i%4 else 2
        a=180 if i%3 else 235
        c=(min(255,GOLD[0]+a//10),min(255,GOLD[1]+a//16),min(255,GOLD[2]+a//20))
        draw.ellipse((x-r,y-r,x+r,y+r),fill=c)

def _glow(base, center=(W//2,H//2), radius=180):
    layer=Image.new('RGBA',(W,H),(0,0,0,0)); d=ImageDraw.Draw(layer)
    cx,cy=center
    for r in range(radius,10,-10):
        alpha=max(0,int(38*(1-r/radius)))
        d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(232,170,210,alpha))
    layer=layer.filter(ImageFilter.GaussianBlur(18))
    return Image.alpha_composite(base.convert('RGBA'),layer)

def _heart(d,cx,cy,s):
    pts=[]
    for i in range(240):
        t=2*math.pi*i/239
        x=16*math.sin(t)**3
        y=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
        pts.append((cx+x*s,cy-y*s))
    d.line(pts+[pts[0]],fill=GOLD,width=max(3,int(s/2)))
    d.ellipse((cx-7,cy-7,cx+7,cy+7),fill=ROSE)

def _zodiac(d,cx,cy,s):
    d.ellipse((cx-s,cy-s,cx+s,cy+s),outline=GOLD,width=5)
    d.ellipse((cx-s*.72,cy-s*.72,cx+s*.72,cy+s*.72),outline=ROSE,width=3)
    for i in range(12):
        a=2*math.pi*i/12
        x1=cx+math.cos(a)*s*.78; y1=cy+math.sin(a)*s*.78
        x2=cx+math.cos(a)*s*.98; y2=cy+math.sin(a)*s*.98
        d.line((x1,y1,x2,y2),fill=IVORY,width=2)
        d.ellipse((x2-4,y2-4,x2+4,y2+4),fill=GOLD)
    _heart(d,cx,cy,s/15)

def _clock(d,cx,cy,s):
    d.ellipse((cx-s,cy-s,cx+s,cy+s),outline=GOLD,width=6)
    for i in range(12):
        a=2*math.pi*i/12-math.pi/2
        x=cx+math.cos(a)*s*.82; y=cy+math.sin(a)*s*.82
        d.ellipse((x-4,y-4,x+4,y+4),fill=IVORY)
    d.line((cx,cy,cx,cy-s*.45),fill=ROSE,width=7)
    d.line((cx,cy,cx+s*.35,cy+s*.18),fill=GOLD,width=7)
    d.ellipse((cx-9,cy-9,cx+9,cy+9),fill=IVORY)

def _pin(d,cx,cy,s):
    d.ellipse((cx-s*.55,cy-s*.7,cx+s*.55,cy+s*.4),outline=GOLD,width=6)
    d.polygon([(cx-s*.35,cy+s*.2),(cx+s*.35,cy+s*.2),(cx,cy+s)],outline=GOLD)
    d.ellipse((cx-s*.15,cy-s*.28,cx+s*.15,cy+s*.02),fill=ROSE)

def _city(d,cx,cy,s):
    x=cx-s
    widths=[.25,.18,.32,.2,.27]; hs=[.6,.85,.45,.72,.55]
    for i,(w,h) in enumerate(zip(widths,hs)):
        ww=s*w; hh=s*h
        d.rounded_rectangle((x,cy+s*.45-hh,x+ww,cy+s*.45),radius=7,outline=GOLD,width=4)
        for yy in range(int(cy+s*.45-hh+18),int(cy+s*.45-12),28):
            d.rectangle((x+12,yy,x+22,yy+10),fill=ROSE)
        x+=ww+18
    d.line((cx-s*1.05,cy+s*.47,cx+s*1.05,cy+s*.47),fill=IVORY,width=3)

def _rings(d,cx,cy,s):
    d.ellipse((cx-s*.75,cy-s*.45,cx+s*.15,cy+s*.45),outline=GOLD,width=8)
    d.ellipse((cx-s*.15,cy-s*.45,cx+s*.75,cy+s*.45),outline=ROSE,width=8)

def _diamond(d,cx,cy,s):
    pts=[(cx,cy-s),(cx+s*.85,cy-s*.25),(cx+s*.55,cy+s*.8),(cx,cy+s),(cx-s*.55,cy+s*.8),(cx-s*.85,cy-s*.25)]
    d.polygon(pts,outline=GOLD)
    d.line((pts[0],pts[3]),fill=ROSE,width=3)
    d.line((pts[1],pts[4]),fill=IVORY,width=2)
    d.line((pts[2],pts[5]),fill=IVORY,width=2)

def _portrait(d,cx,cy,s):
    d.ellipse((cx-s*.28,cy-s*.8,cx+s*.28,cy-s*.24),outline=GOLD,width=6)
    d.arc((cx-s*.8,cy-s*.05,cx+s*.8,cy+s*1.1),190,350,fill=ROSE,width=8)
    d.ellipse((cx-s*.95,cy-s*.95,cx+s*.95,cy+s*.95),outline=IVORY,width=2)

def _bubbles(d,cx,cy,s):
    d.rounded_rectangle((cx-s,cy-s*.55,cx+s*.25,cy+s*.2),radius=35,outline=GOLD,width=6)
    d.polygon([(cx-s*.3,cy+s*.2),(cx-s*.08,cy+s*.2),(cx-s*.25,cy+s*.48)],fill=GOLD)
    d.rounded_rectangle((cx-s*.15,cy-s*.05,cx+s,cy+s*.65),radius=35,outline=ROSE,width=6)

def _people(d,cx,cy,s):
    for dx,col in [(-s*.38,GOLD),(s*.38,ROSE)]:
        d.ellipse((cx+dx-s*.22,cy-s*.65,cx+dx+s*.22,cy-s*.21),outline=col,width=6)
        d.arc((cx+dx-s*.45,cy-s*.15,cx+dx+s*.45,cy+s*.75),190,350,fill=col,width=8)

def _orbit(d,cx,cy,s):
    d.ellipse((cx-s,cy-s*.45,cx+s,cy+s*.45),outline=GOLD,width=4)
    d.ellipse((cx-s*.55,cy-s,cx+s*.55,cy+s),outline=ROSE,width=4)
    d.ellipse((cx-s*.12,cy-s*.12,cx+s*.12,cy+s*.12),fill=IVORY)
    d.ellipse((cx+s*.78-10,cy-10,cx+s*.78+10,cy+10),fill=GOLD)

def _constellation(d,cx,cy,s):
    pts=[(cx-s*.8,cy+s*.25),(cx-s*.42,cy-s*.2),(cx-s*.05,cy+s*.05),(cx+s*.25,cy-s*.5),(cx+s*.72,cy-s*.15),(cx+s*.45,cy+s*.5)]
    d.line(pts,fill=GOLD,width=4)
    for i,(x,y) in enumerate(pts):
        r=9 if i in (0,3,5) else 6
        d.ellipse((x-r,y-r,x+r,y+r),fill=ROSE if i%2 else IVORY)
    _heart(d,cx+s*.05,cy+s*.12,s/22)

def _stars_symbol(d,cx,cy,s):
    for i in range(7):
        a=2*math.pi*i/7; x=cx+math.cos(a)*s*.7; y=cy+math.sin(a)*s*.7
        d.line((x-13,y,x+13,y),fill=GOLD,width=3); d.line((x,y-13,x,y+13),fill=ROSE,width=3)

DRAWERS={'heart':_heart,'zodiac':_zodiac,'clock':_clock,'pin':_pin,'city':_city,'rings':_rings,'diamond':_diamond,'portrait':_portrait,'bubbles':_bubbles,'people':_people,'orbit':_orbit,'constellation':_constellation,'stars':_stars_symbol}

@lru_cache(maxsize=32)
def visual(theme):
    name=THEMES.get(theme,theme)
    im=_gradient(); d=ImageDraw.Draw(im); _stars(d,seed=11)
    im=_glow(im); d=ImageDraw.Draw(im)
    DRAWERS.get(name,_stars_symbol)(d,W//2,H//2,155)
    d.rounded_rectangle((70,55,W-70,H-55),radius=34,outline=(236,195,120,120),width=2)
    bio=BytesIO(); im.convert('RGB').save(bio,'JPEG',quality=91,optimize=True); bio.seek(0); bio.name=f'{theme}.jpg'; return bio.getvalue()

@lru_cache(maxsize=8)
def animation(theme='welcome'):
    frames=[]
    for f in range(7):
        im=_gradient(); d=ImageDraw.Draw(im); _stars(d,seed=11,shift=f*3)
        im=_glow(im,radius=190+f*3); d=ImageDraw.Draw(im)
        name=THEMES.get(theme,theme); DRAWERS.get(name,_stars_symbol)(d,W//2,H//2,150+f*2)
        d.rounded_rectangle((70,55,W-70,H-55),radius=34,outline=GOLD,width=2)
        frames.append(im.convert('P',palette=Image.ADAPTIVE))
    bio=BytesIO(); frames[0].save(bio,'GIF',save_all=True,append_images=frames[1:],duration=120,loop=0,optimize=True); bio.seek(0); bio.name=f'{theme}.gif'; return bio.getvalue()

def as_file(data,name):
    bio=BytesIO(data); bio.name=name; return bio
