"""Optional natal synastry and additional preferences for Sovpali rankings.

Swiss Ephemeris uses Moshier planetary calculations without remote requests.
When birth city/time cannot be verified locally, no natal chart is asserted.
The existing dating filters, location policy, directional offers and payments
are intentionally untouched.
"""
from datetime import datetime,timezone
from functools import lru_cache
from zoneinfo import ZoneInfo
import math

RUSSIAN_ALIASES={
"москва":"Moscow","санкт-петербург":"Saint Petersburg","питер":"Saint Petersburg",
"самара":"Samara","владивосток":"Vladivostok","артем":"Artem",
"артём":"Artem","екатеринбург":"Yekaterinburg","казань":"Kazan",
"новосибирск":"Novosibirsk","краснодар":"Krasnodar","ростов-на-дону":"Rostov-na-Donu",
"челябинск":"Chelyabinsk","омск":"Omsk","красноярск":"Krasnoyarsk",
"уфа":"Ufa","пермь":"Perm","иркутск":"Irkutsk","хабаровск":"Khabarovsk",
"сочи":"Sochi","волгоград":"Volgograd","тюмень":"Tyumen",
"южно-сахалинск":"Yuzhno-Sakhalinsk","ани́ва":"Aniva","анива":"Aniva"}
SIGN_NAMES=["Овен","Телец","Близнецы","Рак","Лев","Дева","Весы","Скорпион","Стрелец","Козерог","Водолей","Рыбы"]

def rowvalue(row,key,default=None):
    try:return row[key] if row[key] is not None else default
    except (TypeError,KeyError,IndexError):return default

@lru_cache(maxsize=1)
def city_index():
    import geonamescache
    cache=geonamescache.GeonamesCache(min_city_population=1000)
    idx={}
    for x in cache.get_cities().values():
        for name in [x.get("name",""),*x.get("alternatenames",[])]:
            key=str(name).strip().casefold()
            if key:
                idx.setdefault(key,[]).append(x)
    return idx

def city_info(raw):
    text=str(raw or "").strip().casefold().replace("ё","е")
    if not text:return None
    base=text.split(",")[0].strip()
    candidates=[]
    for name in {base,RUSSIAN_ALIASES.get(base,base).casefold()}:
        candidates.extend(city_index().get(name,[]))
    if not candidates:return None
    # Respect explicit country where supplied; otherwise prioritize a Russian
    # place name in this Russian-language product.
    if "росси" in text or "russia" in text or "," not in text:
        russian=[x for x in candidates if x.get("countrycode")=="RU"]
        if russian:candidates=russian
    # Avoid ambiguous small names: only accept a clear largest population.
    candidates=sorted(candidates,key=lambda x:int(x.get("population") or 0),reverse=True)
    if len(candidates)>1 and int(candidates[0].get("population") or 0)<2*int(candidates[1].get("population") or 0):
        return None
    item=candidates[0]
    zone=item.get("timezone")
    if not zone:return None
    try:return float(item["latitude"]),float(item["longitude"]),ZoneInfo(zone)
    except (KeyError,ValueError,TypeError):return None

@lru_cache(maxsize=4000)
def natal(date_text,time_text,birth_city):
    if not time_text:return None
    location=city_info(birth_city)
    if not location:return None
    import swisseph as swe
    try:
        local=datetime.strptime(date_text+" "+time_text,"%d.%m.%Y %H:%M").replace(tzinfo=location[2])
        utc=local.astimezone(timezone.utc)
        hour=utc.hour+utc.minute/60+utc.second/3600
        jd=swe.julday(utc.year,utc.month,utc.day,hour)
        planets={}
        for key,obj in [("sun",swe.SUN),("moon",swe.MOON),("venus",swe.VENUS),("mars",swe.MARS)]:
            planets[key]=swe.calc_ut(jd,obj,swe.FLG_MOSEPH)[0][0]%360
        houses,ascmc=swe.houses_ex(jd,location[0],location[1],b"P")
        planets["ascendant"]=ascmc[0]%360
        planets["ascendant_sign"]=SIGN_NAMES[int(planets["ascendant"]//30)%12]
        planets["moon_sign"]=SIGN_NAMES[int(planets["moon"]//30)%12]
        return planets
    except Exception:return None

def diff(a,b):
    delta=abs(float(a)-float(b))%360
    return min(delta,360-delta)

def aspect(x,y):
    d=diff(x,y)
    for angle,score,orb,name in [(0,1.0,9,"соединение"),(60,.80,6,"секстиль"),(120,.90,8,"трин"),(180,.35,8,"оппозиция"),(90,.25,7,"квадрат")]:
        if abs(d-angle)<=orb:return score,name
    return .50,"без точного мажорного аспекта"

def natal_pair(a,b):
    if not a or not b:return None
    pair=[("sun","moon",2),("moon","sun",2),("moon","moon",3),("venus","mars",2),("mars","venus",2),("venus","venus",1),("sun","sun",1)]
    points=0;total=0;details=[]
    for p,q,w in pair:
        val,label=aspect(a[p],b[q]);points+=val*w;total+=w
        if label!="без точного мажорного аспекта" and len(details)<3:details.append(p+"–"+q+": "+label)
    return round(points/total*100),details

def wrap(existing):
    oldscore=existing["score"];oldastro=existing.get("pc_astro_pct")
    oldcopy=existing.get("pc_astro_copy");oldreasons=existing["reasons"]
    def extra(row):
        uid=rowvalue(row,"user_id")
        if not uid:return None
        try:return existing["one"]("SELECT * FROM natal_profile_data WHERE user_id=?",(int(uid),))
        except Exception:return None
    def pair(a,b):
        x,y=extra(a),extra(b)
        c1=natal(str(rowvalue(a,"birth_date","")),str(rowvalue(x,"birth_time","")),str(rowvalue(a,"birth_place","")))
        c2=natal(str(rowvalue(b,"birth_date","")),str(rowvalue(y,"birth_time","")),str(rowvalue(b,"birth_place","")))
        return x,y,c1,c2,natal_pair(c1,c2)
    def calc_score(a,b):
        base=int(oldscore(a,b));x,y,c1,c2,syn=pair(a,b);delta=0
        if x and y:
            # Lifestyle is not a rigid filter; complementary temperaments can work.
            for key in ("lifestyle","relationship_style"):
                v1,v2=rowvalue(x,key),rowvalue(y,key)
                if v1 and v2:delta+=2 if v1==v2 else -1
            plan1,plan2=rowvalue(x,"family_plan"),rowvalue(y,"family_plan")
            if plan1 and plan2:delta+=3 if plan1==plan2 else (-7 if "Пока" not in (plan1+" "+plan2) else -1)
        if syn:
            delta+=round((syn[0]-55)/6) # astrologically weighted, never a hard exclusion
        return max(20,min(98,base+delta))
    def calc_astro(a,b):
        x,y,c1,c2,syn=pair(a,b)
        if syn:return syn[0]
        return int(oldastro(a,b)) if callable(oldastro) else 70
    def calc_copy(a,b):
        basic=oldcopy(a,b) if callable(oldcopy) else ""
        x,y,c1,c2,syn=pair(a,b)
        if not syn:return basic+"\\nНатальная синастрия доступна, когда известны точное время и распознанный город рождения обоих участников."
        return (basic+"\\n<b>Натальная синастрия (символический разбор):</b> "
                "Луна: "+c1["moon_sign"]+" и "+c2["moon_sign"]+
                "; асценденты: "+c1["ascendant_sign"]+" и "+c2["ascendant_sign"]+
                ". Сопоставлены Солнце, Луна, Венера, Марс и основные аспекты.")
    def calc_reasons(a,b):
        out=list(oldreasons(a,b))
        x,y,c1,c2,syn=pair(a,b)
        if x and y and rowvalue(x,"lifestyle") and rowvalue(x,"lifestyle")==rowvalue(y,"lifestyle"):
            out.append("вам близок повседневный ритм жизни")
        if syn:out.append("в натальной синастрии сопоставлены положения Луны, Венеры и Марса")
        return out[:5]
    return calc_score,calc_astro,calc_copy,calc_reasons

def install(ns):
    ns["score"],ns["pc_astro_pct"],ns["pc_astro_copy"],ns["reasons"]=wrap(ns)
    print("[compatibility] natal synastry and lifestyle layer enabled",flush=True)
