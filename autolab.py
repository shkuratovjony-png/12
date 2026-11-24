"""Autonomous *bounded* strategy research: safe rule grammar, evolution, and gated paper signals.

No LLM, arbitrary code execution, credentials or Bybit order placement. Each candidate
is JSON data composed of conditions on historical closed bars. Validation chooses
one candidate; the holdout only evaluates that one. Daily re-review of rolling
history is NOT a fresh out-of-sample experiment; forward paper trading is needed.
"""
import hashlib
import json
import math
import os
import sys
import time
import warnings

for _env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_env] = "1"

import numpy as np
import pandas as pd

import risk
import store
from market import BAR

warnings.filterwarnings("ignore", category=RuntimeWarning)

FEATURES = ("mom4", "mom12", "mom24", "ema_gap", "rsi", "boll_z",
            "range_pos", "break_high", "break_low", "vol_ratio",
            "bar_body", "atr_ratio")
MAX_PROPOSALS = max(30, min(180, int(os.getenv("AUTOLAB_PROPOSALS", "100"))))
MIN_TRADES = 8
LOOKBACK = 65


def indicators(rows):
    """All features at bar i use OHLCV at/before i; never the next bar."""
    a = np.asarray(rows, dtype=float)
    if a.ndim != 2 or a.shape[1] != 6 or len(a) < LOOKBACK + 30:
        raise ValueError("Need at least 95 six-column candles")
    t, opening, high, low, close, volume = a.T
    c = pd.Series(close)
    h = pd.Series(high)
    l = pd.Series(low)
    v = pd.Series(volume)
    prev = c.shift(1)
    difference = c.diff()
    positive = difference.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    negative = (-difference.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 * positive / (positive + negative).replace(0, np.nan)
    ema_fast = c.ewm(span=12, adjust=False).mean()
    ema_slow = c.ewm(span=26, adjust=False).mean()
    mid = c.rolling(24, min_periods=24).mean()
    sigma = c.rolling(24, min_periods=24).std()
    high_prior = h.shift(1).rolling(24, min_periods=24).max()
    low_prior = l.shift(1).rolling(24, min_periods=24).min()
    true_range = pd.concat([h-l, (h-prev).abs(), (l-prev).abs()],axis=1).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    feature_map = {
        "mom4": c / c.shift(4) - 1,
        "mom12": c / c.shift(12) - 1,
        "mom24": c / c.shift(24) - 1,
        "ema_gap": (ema_fast - ema_slow) / c,
        "rsi": (rsi - 50) / 50,
        "boll_z": (c - mid) / sigma.replace(0, np.nan),
        "range_pos": (c - low_prior) / (high_prior - low_prior).replace(0, np.nan) * 2 - 1,
        "break_high": c / high_prior - 1,
        "break_low": c / low_prior - 1,
        "vol_ratio": v / v.shift(1).rolling(24, min_periods=24).mean().replace(0,np.nan)-1,
        "bar_body": (c - opening) / opening,
        "atr_ratio": atr / c
    }
    out = {key: np.asarray(series, dtype=float) for key, series in feature_map.items()}
    # Gaps in recent candles make signals invalid even if indicator values exist.
    gap = np.r_[0, np.cumsum((np.diff(t) != BAR).astype(int))]
    valid = np.zeros(len(t), dtype=bool)
    idx = np.arange(LOOKBACK, len(t))
    valid[idx] = (gap[idx] == gap[idx-LOOKBACK])
    for values in out.values():
        valid &= np.isfinite(values)
    return a, out, valid


def make_predicate(rng, feats, train_indices):
    feature = str(rng.choice(FEATURES))
    direction = int(rng.choice([-1, 1]))
    q = float(rng.choice([.65, .75, .85, .92]))
    known = feats[feature][train_indices] * direction
    known = known[np.isfinite(known)]
    if len(known) < 100:
        return {"feature":feature, "direction":direction, "threshold":0.0}
    # Thresholds selected ONLY from the earliest training portion.
    threshold = max(0.0, float(np.quantile(known, q)))
    return {"feature":feature, "direction":direction, "threshold":float(round(threshold, 9))}


def new_candidate(rng, feats, train_indices):
    count = int(rng.choice([1,2,2,3]))
    predicates = [make_predicate(rng, feats, train_indices) for _ in range(count)]
    return {"side":int(rng.choice([-1,1])), "all":predicates}


def mutate(parent, rng, feats, train_indices):
    candidate = json.loads(json.dumps(parent))
    act = int(rng.integers(4))
    if act == 0:
        candidate["side"] *= -1
    elif act == 1:
        candidate["all"][int(rng.integers(len(candidate["all"])))] = make_predicate(rng, feats, train_indices)
    elif act == 2 and len(candidate["all"]) < 3:
        candidate["all"].append(make_predicate(rng, feats, train_indices))
    elif act == 3 and len(candidate["all"]) > 1:
        candidate["all"].pop(int(rng.integers(len(candidate["all"]))))
    else:
        candidate["all"][0] = make_predicate(rng, feats, train_indices)
    return candidate


def validate(candidate):
    if not isinstance(candidate, dict) or candidate.get("side") not in (-1,1):
        return False
    predicates = candidate.get("all")
    if not isinstance(predicates, list) or not 1 <= len(predicates) <= 3:
        return False
    for p in predicates:
        if (not isinstance(p,dict) or p.get("feature") not in FEATURES
                or p.get("direction") not in (-1,1)
                or not isinstance(p.get("threshold"),(int,float))
                or not math.isfinite(p["threshold"])
                or p["threshold"] < 0):
            return False
    return True


def signals(candidate, feats, available):
    if not validate(candidate):
        raise ValueError("Invalid research candidate; arbitrary strategies forbidden")
    output = np.asarray(available, dtype=bool).copy()
    for p in candidate["all"]:
        output &= (feats[p["feature"]] * p["direction"] > p["threshold"])
    return np.where(output, candidate["side"], 0).astype(np.int8)


def summarize(candidate, a, feats, available, indices):
    sig = signals(candidate, feats, available)[indices]
    selected = indices[sig != 0]
    if len(selected) == 0:
        return {"return":0.0, "drawdown":0.0, "trades":0, "win_rate":0.0, "score":-100.0}
    side = sig[sig != 0].astype(float)
    # Enter at NEXT bar open and exit at NEXT bar close: one-bar paper hypothesis.
    nextbar = a[selected+1]
    move = side * (nextbar[:,4] / nextbar[:,1] - 1.0)
    stop_hit = np.where(side == 1,
                        nextbar[:,3] <= nextbar[:,1]*(1-risk.STOP),
                        nextbar[:,2] >= nextbar[:,1]*(1+risk.STOP))
    move = np.where(stop_hit, -risk.STOP, move)
    pnl = (move - risk.ROUND_TRIP) * risk.NOTIONAL_FRACTION
    curve = np.cumprod(np.r_[1.0, 1.0+pnl])
    dd = float(np.max(1-curve/np.maximum.accumulate(curve)))
    ret = float(curve[-1]-1)
    count = int(len(selected))
    score = ret-2.0*dd if count>=MIN_TRADES else -100.0+count/100
    return {"return":round(ret,8),"drawdown":round(dd,8),"trades":count,
            "win_rate":round(float(np.mean(pnl>0)),5),"score":round(score,8)}


def fingerprint(candidate):
    return hashlib.sha256(json.dumps(candidate,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16]


def research(symbol):
    now = time.time()
    rows = store.get("candles:"+symbol, [])
    a, f, valid = indicators(rows)
    n = len(a)
    if n < 800:
        raise ValueError("At least 800 15m candles required before research")
    # 50% first-period thresholds / 25% validation / 25% final untouched holdout.
    cut_train = int(n*.50)
    cut_val = int(n*.75)
    train_ix = np.arange(LOOKBACK, cut_train-2)
    validation_ix = np.arange(cut_train+2, cut_val-2)
    holdout_ix = np.arange(cut_val+2, n-1)
    if not (valid[train_ix].sum()>200 and valid[validation_ix].sum()>100
            and valid[holdout_ix].sum()>100):
        raise ValueError("Not enough contiguous market history")
    brain = store.get("autolab:"+symbol, {}) or {}
    old = brain.get("archive", [])[:10]
    rng = np.random.default_rng(int(now//86400)+sum(map(ord,symbol))*103)
    pool = []
    for member in old:
        genome = member.get("strategy")
        if validate(genome):
            pool.append(genome)
            for _ in range(3):
                pool.append(mutate(genome,rng,f,train_ix))
    while len(pool) < MAX_PROPOSALS:
        pool.append(new_candidate(rng,f,train_ix))
    tested = []
    visited=set()
    for candidate in pool[:MAX_PROPOSALS]:
        key=fingerprint(candidate)
        if key in visited:continue
        visited.add(key)
        val=summarize(candidate,a,f,valid,validation_ix)
        tested.append({"strategy":candidate,"id":key,"validation":val})
    tested.sort(key=lambda v:v["validation"]["score"],reverse=True)
    best=tested[0]
    # The holdout is evaluated once, for the single champion chosen on validation.
    final=summarize(best["strategy"],a,f,valid,holdout_ix)
    v=best["validation"]
    approved = (v["return"]>0 and final["return"]>0
                and v["trades"]>=MIN_TRADES and final["trades"]>=MIN_TRADES
                and v["drawdown"]<=.08 and final["drawdown"]<=.08)
    candidate_entry={"name":"autolab","version":str(int(now)), "id":best["id"],
                     "strategy":best["strategy"],"validation":v,"holdout":final}
    # Failed candidates cannot place simulated orders.
    store.put("champion:"+symbol, candidate_entry if approved else None)
    previous_count = int(brain.get("total_tested",0))
    archived = [{**e, "generation":int(brain.get("generation",0))+1}
                for e in tested[:10]]
    brain = {"generation":int(brain.get("generation",0))+1,
             "total_tested":previous_count+len(tested),
             "last_cycle":now, "last_approved":bool(approved),
             "archive":archived, "best_id":best["id"]}
    store.put("autolab:"+symbol,brain)
    report={"time":now,"symbol":symbol,"selected":"autolab","approved":bool(approved),
            "rows":n,"candidates":len(tested),"generation":brain["generation"],
            "lifetime_tested":brain["total_tested"],"validation":v,
            "holdout":final,"best_id":best["id"],"selected_params":best["strategy"],
            "holdout_from":int(a[holdout_ix[0],0]),
            "holdout_to":int(a[holdout_ix[-1]+1,0]),
            "limitations":"Rolling 15m historical test, no tick fills or independent forward proof. Repeated holdout review is not independent."}
    store.put("report:"+symbol, report)
    history=store.get("research_history",[])
    store.put("research_history",(history+[{"time":now,"symbol":symbol,"generation":brain["generation"],
             "candidates":len(tested),"approved":bool(approved),"validation":v,"holdout":final}])[-300:])
    return report


def prospective_signal(symbol):
    champion = store.get("champion:"+symbol)
    if not champion or champion.get("name")!="autolab":
        return 0
    a,f,valid = indicators(store.get("candles:"+symbol, []))
    return int(signals(champion["strategy"],f,valid)[-1])


if __name__ == "__main__":
    store.init()
    if len(sys.argv)<3 or sys.argv[1] != "evolve":
        raise SystemExit("usage: python autolab.py evolve BTCUSDT")
    print(json.dumps(research(sys.argv[2]),allow_nan=False))
