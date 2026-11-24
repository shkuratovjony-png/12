"""Common paper execution on observed order books. No order API.
Depth is discounted to account for competition; residual slippage is a scenario,
not a measured fill. All-or-none market simulation; insufficient depth rejects.
"""
import math
LATENCY=1.
DEPTH_FRACTION=.5
BUFFER=.0001
def fill(q,side,*,quantity=None,notional=None,slip=BUFFER):
    if side not in (-1,1) or (quantity is None)==(notional is None):raise ValueError("Specify exactly one size")
    if not q:return None
    levels=q.get("asks" if side==1 else "bids",[])
    best=q["ask" if side==1 else "bid"]
    remaining=float(quantity if quantity is not None else notional)
    if not math.isfinite(remaining) or remaining<=0:return None
    qty=cost=0.
    for p,size in levels:
        p=float(p);size=float(size)*DEPTH_FRACTION
        if not (math.isfinite(p) and math.isfinite(size) and p>0 and size>0):continue
        price=p*(1+side*slip)
        take=min(size,remaining if quantity is not None else remaining/price)
        qty+=take;cost+=take*price;remaining-=take if quantity is not None else take*price
        if remaining<=1e-8*max(1.,float(quantity if quantity is not None else notional)):break
    if remaining>1e-8*max(1.,float(quantity if quantity is not None else notional)) or qty<=0:return None
    price=cost/qty
    return {"price":price,"qty":qty,"notional":cost,"best":best,"slippage":side*(price/best-1),
            "spread":(q["ask"]-q["bid"])/((q["ask"]+q["bid"])/2),"book_age":q.get("age"),"quote_time":q.get("time")}
def selftest():
    q={"ask":100.,"bid":99.,"asks":[[100.,2.],[101.,4.]],"bids":[[99.,2.],[98.,4.]]}
    f=fill(q,1,quantity=2.,slip=0.)
    assert abs(f["price"]-100.5)<1e-10 and f["qty"]==2.
    assert fill(q,1,quantity=4.) is None
    assert abs(fill(q,-1,quantity=2.,slip=0.)["price"]-98.5)<1e-10
    assert abs(fill(q,1,notional=150.,slip=0.)["notional"]-150.)<1e-10
