"""Premium: 3 sent introduction requests per member-local calendar day.

Count refused and timed-out attempts, do not count unsubmitted reservations.
Production algorithm is extracted from the patched bot source. No network use.
"""
import ast,sqlite3
from pathlib import Path
src=Path("app.py").read_text(encoding="utf-8")
tree=ast.parse(src)
functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="sm_premium_requests_today"]
assert len(functions)==1,"Premium daily cap not installed"
assert "sm_premium_requests_today(buyer_uid) >= 3" in src,"Premium reservation must check three-request cap"
assert "_sm_premium_active(db,buyer_uid)" in src,"Quota must apply only to active Premium"
conn=sqlite3.connect(":memory:")
conn.row_factory=sqlite3.Row
conn.execute("CREATE TABLE intro_orders(buyer_user_id INTEGER,created_at TEXT,status TEXT)")
class Engine:
    def local_bounds(self,uid):
        assert uid==7
        return None,"Asia/Vladivostok","2026-11-08T14:00:00","2026-11-09T14:00:00"
def one(query,values):
    return conn.execute(query,values).fetchone()
ns={"one":one,"MATCH_PUSH_ENGINE":Engine(),"sm_local_day_bounds":lambda:None}
exec(compile(ast.Module(body=functions,type_ignores=[]),"app.py","exec"),ns)
count=ns["sm_premium_requests_today"]
conn.executemany("INSERT INTO intro_orders VALUES(7,?,?)",[
 ("2026-11-08T14:30:00","awaiting_response"),
 ("2026-11-08T17:30:00","declined"),
 ("2026-11-09T03:15:00","expired"),
 ("2026-11-09T05:15:00","reserved"),
 ("2026-11-07T05:15:00","accepted"),
 ("2026-11-09T17:15:00","accepted"),
])
assert count(7)==3,"Three used slots, even when refused or expired"
conn.execute("UPDATE intro_orders SET status='closed' WHERE status='awaiting_response'")
assert count(7)==2,"An unsent/closed reservation should not use slot"
print("[test] Premium daily 3-request limit including refused/expired, based on user's timezone PASS",flush=True)
