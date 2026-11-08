"""Build-time regression tests for one-way matched pair browsing.

No production database, network request, payment or Telegram account is touched.
Extract the final candidate-browser function from the generated app.py using AST.
"""
import ast
from pathlib import Path

tree=ast.parse(Path("app.py").read_text(encoding="utf-8"))
matches=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=="mp_candidates"]
assert len(matches)>=1,"mp_candidates missing"
fn=matches[-1]
namespace={}
exec(compile(ast.Module(body=[fn],type_ignores=[]),"app.py","exec"),namespace)
browse=namespace["mp_candidates"]

profile_a={"user_id":101,"gender":"Мужчина","city":"Екатеринбург","goal":"Серьёзные отношения"}
profile_b={"user_id":102,"gender":"Женщина","city":"Екатеринбург","goal":"Серьёзные отношения"}
records=[profile_a,profile_b]
namespace.update({
 "profile":lambda uid:next((p for p in records if p["user_id"]==uid),None),
 "many":lambda sql,args:[{**p,"is_banned":0} for p in records if p["user_id"]!=args[0]],
 "eligible":lambda a,b:a["gender"]!=b["gender"],
 "xm_same_hub":lambda a,b:a.strip().casefold()==b.strip().casefold(),
 "score":lambda a,b:93,
})
assert [p["user_id"] for _,p in browse(101)]==[102],"A must see B"
assert [p["user_id"] for _,p in browse(102)]==[101],"B must see A"
# Browsing does not by itself assign a pair. But after A received B by
# automatic notification, the reverse B->A MUST disappear from Top-3.
class Direction:
    def __init__(self): self.owner=None;self.busy=set()
    def pair_owner(self,a,b): return self.owner
    def target_in_active_request(self,uid):return uid in self.busy
direction=Direction()
namespace["MATCH_PUSH_ENGINE"]=direction
assert [p["user_id"] for _,p in browse(102)]==[101],"Unassigned pair may be browsed"
direction.owner=101
assert [p["user_id"] for _,p in browse(101)]==[102],"Recipient A keeps B in their selection"
assert browse(102)==[],"B MUST NOT receive or browse A after B was sent to A"
direction.owner=None
direction.busy.add(102)
assert browse(101)==[],"Pending consent must hide a candidate from manual Top-3"
direction.busy.clear()
assert [p["user_id"] for _,p in browse(101)]==[102],"Decline or timeout should restore a candidate"

# Historical direction locks, busy flags and offers must NOT be required by
# this browse function: none are supplied to the test's namespace.
records[1]={**records[1],"gender":"Мужчина"}
assert browse(101)==[],"same-gender profiles must honor current eligibility"
records[1]={**records[1],"gender":"Женщина","city":"Пермь"}
assert [p["user_id"] for _,p in browse(101)]==[102],"different cities must be allowed"
print("[test] directional Top-3: no reciprocal profile after auto-send; nationwide eligibility PASS",flush=True)
