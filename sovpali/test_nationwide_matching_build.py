"""Regression: all matching channels work for different cities.

Pure offline build-time AST tests; no production data, Telegram or payment API.
"""
import ast
import html
from pathlib import Path

source=Path("app.py").read_text(encoding="utf-8")
tree=ast.parse(source)
fns=lambda name:[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
def load(fn,space):
    exec(compile(ast.Module(body=[fn],type_ignores=[]),"app.py","exec"),space)
    return space[fn.name]

a={"user_id":801,"gender":"Мужчина","city":"Екатеринбург","goal":"Серьёзные отношения","priority":"Семья"}
b={"user_id":802,"gender":"Женщина","city":"Москва","goal":"Серьёзные отношения","priority":"Семья"}
profiles={801:a,802:b}
space={
    "profile":lambda uid:profiles.get(int(uid)),
    "many":lambda sql,args:[p for uid,p in profiles.items() if uid!=int(args[0])],
    "eligible":lambda x,y:x["gender"]!=y["gender"],
    "xm_same_hub":lambda x,y:False, # if invoked, pair is in different regions
    "xm_pair_seen":lambda x,y:False,
    "xm_busy":lambda uid:False,
    "score":lambda x,y:83,
    "XM_MIN_SCORE":80,
    "sm_int":lambda k,d:d,
    "sm_auto_recipient_allowed":lambda uid:True,
    "sm_direction_owner":lambda x,y:None,
}
auto=fns("xm_candidates_for")
assert len(auto)>=2,"expected base and smart matchmaking selectors"
core=load(auto[0],space)
space["_sm_old_xm_candidates_for"]=core
smart=load(auto[-1],space)
assert [c["user_id"] for _,c in core(801)]==[802],"basic auto filter blocked a different city"
assert [c["user_id"] for _,c in smart(801)]==[802],"smart auto filter blocked a different city"
assert [c["user_id"] for _,c in smart(802)]==[801],"automatic matches must be possible in either direction"
assert space["xm_same_hub"](a["city"],b["city"]) is False,"test cities must really differ"

browse=load(fns("mp_candidates")[-1],space)
assert [c["user_id"] for _,c in browse(801)]==[802],"My Pair must include distant candidate"
assert [c["user_id"] for _,c in browse(802)]==[801],"reciprocal My Pair must include distant candidate"
pc=fns("pc_location_copy")
assert pc,"site copy compatibility lacks location copy"
location=load(pc[-1],{"html":html})
assert location(a,b)=="","different cities must not produce fake claims of shared region"
assert "Екатеринбург" in location(a,{**b,"city":"Екатеринбург"}),"matching city should be a positive note"

website=Path("pair_motion.py").read_text(encoding="utf-8")
t=ast.parse(website)
server_fn=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=="_pair_rows")
server_src=ast.get_source_segment(website,server_fn)
assert "xm_same_hub" not in server_src,"website must not reject valid distant pairing"
assert "allowed" in server_src and "load_pair_token" in server_src,"website must still verify signed link and eligibility"

# Score keeps a small 5-point positive city bonus with no hard location gate.
score_fn=fns("score")[-1]
score_source=ast.get_source_segment(source,score_fn)
assert "s+=5" in score_source and "a['city']" in score_source,"city bonus missing"
# The high-visibility cinematic copy must not falsely say users share a city.
frontend=Path("motion_site/src/Premium.tsx").read_text(encoding="utf-8")
assert "pair.same_city ?" in frontend,"motion headline must be city-conditional"
assert "ДВА ЧЕЛОВЕКА. ОДНА ВОЗМОЖНОСТЬ." in frontend,"location-neutral text missing"
print("[test] nationwide browse + auto offer + signed web + honest location text PASS",flush=True)
