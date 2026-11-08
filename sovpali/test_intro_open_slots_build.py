"""Intro purchase slot regression: accepted relationships must not permanently
consume the 3 outstanding *unanswered* purchase slots.
"""
import ast,sqlite3
from pathlib import Path
src=Path("app.py").read_text(encoding="utf-8")
defs=[x for x in ast.parse(src).body if isinstance(x,ast.FunctionDef) and x.name=="sm_open_outgoing"]
assert len(defs)==1,defs
db=sqlite3.connect(":memory:")
db.row_factory=sqlite3.Row
db.execute("CREATE TABLE intro_orders(buyer_user_id INTEGER,status TEXT)")
def one(sql,params):
 return db.execute(sql,params).fetchone()
ns={"one":one}
exec(compile(ast.Module(body=defs,type_ignores=[]),"app.py","exec"),ns)
fn=ns["sm_open_outgoing"]
db.executemany("INSERT INTO intro_orders VALUES(1,?)",[("accepted",),("accepted",),("accepted",)])
assert fn(1)==0,"Three accepted relationships must NOT block future buyers"
db.executemany("INSERT INTO intro_orders VALUES(1,?)",[("reserved",),("awaiting_response",),("paid",)])
assert fn(1)==3
db.execute("UPDATE intro_orders SET status='declined' WHERE status='awaiting_response'")
assert fn(1)==2
print("[test] completed accepted intro releases buyer pending slot, active requests keep 3-open cap PASS",flush=True)
