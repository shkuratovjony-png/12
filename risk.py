"""Paper-only risk guard. No exchange order path exists."""
import time
from datetime import datetime,timezone
START=1000.0
TARGET_DAILY=0.10
MAX_DAY_LOSS=0.03
MAX_DRAWDOWN=0.15
NOTIONAL_FRACTION=0.25
STOP=0.0075
FEE=0.0006
SLIPPAGE=0.0001
ROUND_TRIP=2*(FEE+SLIPPAGE)
HOLD_SECONDS=900

def day():
    return datetime.now(timezone.utc).date().isoformat()

def initial():
    return {"balance":START,"peak":START,"day":day(),"day_start":START,"position":None,
            "trades":[],"last_signals":{},"halted":False,"equity":START}

def roll(s):
    if s["day"]!=day():
        s["day"]=day()
        s["day_start"]=s.get("equity",s["balance"])

def entry_allowed(s):
    roll(s)
    e=s.get("equity",s["balance"])
    if e <= s["peak"]*(1-MAX_DRAWDOWN): s["halted"]=True
    return not s["halted"] and e>s["day_start"]*(1-MAX_DAY_LOSS) and not s["position"]

def entry(s,symbol,side,bid,ask,model):
    if not entry_allowed(s) or side not in (-1,1): return False
    price=(ask if side==1 else bid)*(1+side*SLIPPAGE)
    notional=s["balance"]*NOTIONAL_FRACTION
    fee=notional*FEE
    s["balance"]-=fee
    s["equity"]=s["balance"]
    s["position"]={"symbol":symbol,"side":side,"entry":price,"qty":notional/price,
                   "opened":time.time(),"entry_fee":fee,"model":model}
    return True

def mark(s,bid,ask,now=None):
    roll(s)
    p=s["position"]
    if not p:return
    now=now or time.time()
    exit_price=(bid if p["side"]==1 else ask)*(1-p["side"]*SLIPPAGE)
    move=p["side"]*(exit_price/p["entry"]-1)
    gross=p["side"]*p["qty"]*(exit_price-p["entry"])
    fee=p["qty"]*exit_price*FEE
    equity=s["balance"]+gross-fee
    s["equity"]=equity
    s["peak"]=max(s["peak"],equity)
    reason=None
    if equity<=s["peak"]*(1-MAX_DRAWDOWN):
        s["halted"]=True;reason="drawdown"
    elif equity<=s["day_start"]*(1-MAX_DAY_LOSS):reason="daily_loss"
    elif move<=-STOP:reason="stop_observed"
    elif now-p["opened"]>=HOLD_SECONDS:reason="time_exit"
    if reason:
        s["balance"]=equity
        s["trades"]=(s["trades"]+[dict(p,exit=exit_price,closed=now,pnl=gross-fee-p["entry_fee"],reason=reason,
                                     balance=equity)])[-1000:]
        s["position"]=None
