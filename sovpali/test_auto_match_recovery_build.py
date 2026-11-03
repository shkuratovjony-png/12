"""Build-time tests of the automatic-match diagnosis and prioritisation.

Uses fake users in memory. Never connects to Telegram or production Postgres.
"""
import ast
from datetime import datetime,timedelta
from pathlib import Path
app=Path("app.py").read_text(encoding="utf-8")
tree=ast.parse(app)
functions={n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
for name in ("am_possible_count","xm_maintenance","mp_candidates","sm_auto_recipient_allowed"):
    assert name in functions,name+" missing"
maintenance=ast.get_source_segment(app,functions["xm_maintenance"])
assert "completed_at DESC" in maintenance,"recent registrations must be first"
assert "xm_try_offer" in maintenance,"maintenance must deliver queue"
assert "5*60" in maintenance,"queue polling interval missing"
assert "am_cleanup_legacy_browse_locks" in maintenance,"stale browse locks not released"
scope={"datetime":datetime,"timedelta":timedelta}
exec(compile(ast.Module(body=[functions["am_possible_count"]],type_ignores=[]),"app.py","exec"),scope)
a={"user_id":101,"gender":"Мужчина","city":"Екатеринбург","goal":"Серьёзные отношения"}
b={"user_id":102,"gender":"Женщина","city":"Екатеринбург","goal":"Серьёзные отношения"}
scope.update({
"many":lambda sql:[a,b],
"eligible":lambda a,b:a["gender"]!=b["gender"],
"xm_same_hub":lambda a,b:a.casefold()==b.casefold(),
"score":lambda a,b:94,
"sm_int":lambda key,default:default,
"xm_pair_seen":lambda a,b:False,
"xm_busy":lambda a:False,
"sm_now":lambda:datetime(2026,11,3,12),
})
data=scope["am_possible_count"]()
assert data["eligible_gender_pairs"]==1,data
assert data["same_city_pairs"]==1,data
assert data["same_goal_pairs"]==1,data
assert data["high_score_pairs"]==1,data
assert data["unoffered_free_pairs"]==1,data
scope["score"]=lambda a,b:79
low=scope["am_possible_count"]()
assert low["high_score_pairs"]==0,low
scope["score"]=lambda a,b:94
scope["sm_now"]=lambda:datetime(2026,11,3,20)
late=scope["am_possible_count"]()
assert late["quiet_hours"] is True,late
print("[test] auto-match eligibility, quiet window, latest-first requeue PASS",flush=True)
