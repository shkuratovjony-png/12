"""Public copy-trader CSV research. Never copies orders or uses trader credentials.
Observed closed trades are descriptive, not a reconstructed causal trading rule.
"""
import csv,io,time,logging,math,re,statistics
from datetime import datetime,timezone
from collections import Counter,defaultdict
import requests,store
from pathlib import Path
URLS={"AlfaRomeo":"https://top.plonex.trade/trades.csv/65427036?tdir=desc&tsort=closed","PlymouthTrade":"https://top.plonex.trade/trades.csv/72410661?tdir=desc&tsort=closed"}
VIEW={}
def normalized(s):
    return re.sub(r"[^a-zа-я0-9]","",str(s).lower())
def parse_num(v):
    s=str(v or "").strip().replace("\u2212","-").replace("\u00a0","").replace(" ","").replace("%","")
    if "," in s and "." not in s:s=s.replace(",",".")
    else:s=s.replace(",","")
    try:
        x=float(s);return x if math.isfinite(x) else None
    except ValueError:return None
def stamp(v):
    v=str(v or "").strip()
    try:
        x=float(v)
        if x>1e12:x/=1000
        if x>1e9:return x
    except ValueError:pass
    try:
        t=datetime.fromisoformat(v.replace("Z","+00:00"))
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:return None
def parse(raw):
    reader=csv.DictReader(io.StringIO(raw),dialect=csv.Sniffer().sniff(raw[:4096],delimiters=",;\t"))
    headers=reader.fieldnames or []
    out=[]
    for row in reader:
        d={normalized(k):v for k,v in row.items() if k}
        def get(*ks):
            return next((d[normalized(k)] for k in ks if normalized(k) in d and d[normalized(k)] not in ("",None)),"")
        pos=get("position","позиция","symbol","торговая пара")
        symbol=str(get("symbol","pair","instrument","торговая пара","символ")).upper()
        hit=re.search(r"[A-Z0-9]+USDT",symbol+" "+str(pos).upper())
        if not hit:continue
        direction=str(get("side","direction","направление","positionSide"))+" "+str(pos)
        direction=direction.lower()
        side=1 if any(t in direction for t in ("long","buy","лонг")) else -1 if any(t in direction for t in ("short","sell","шорт")) else 0
        op=stamp(get("opened_utc","opened (UTC)","opened","opened_at","open_time","openTime","entry_time","created_time","createdAt","открыта","открытие (UTC)"))
        cl=stamp(get("closed_utc","closed (UTC)","closed","closed_at","close_time","closeTime","exit_time","updated_time","updatedAt","закрыта","закрытие (UTC)"))
        entry=parse_num(get("entry","entry_price","avg_entry_price","avgEntryPrice","openPrice","цена входа","вход"))
        exit=parse_num(get("closed_price","exit","exit_price","avg_exit_price","avgExitPrice","closePrice","цена выхода","выход"))
        pnl=parse_num(get("net_profit","pnl","pnl_usdt","realizedPnl","closedPnl","profit","прибыль"))
        qty=parse_num(get("qty","quantity","size","количество"))
        margin=parse_num(get("margin","маржа","positionMargin"))
        lev=parse_num(get("leverage","плечо"))
        if lev is None:
            m=re.search(r"(\d+(?:\.\d+)?)\s*[xх]",str(pos).lower());lev=float(m.group(1)) if m else None
        if side and op and cl and cl>=op and entry and entry>0 and exit and exit>0:
            out.append(dict(symbol=hit.group(),side=side,opened=op,closed=cl,entry=entry,exit=exit,pnl=pnl,qty=qty,margin=margin,leverage=lev))
    if not out:raise ValueError("No recognized trade rows; headers="+repr(headers)[:400])
    return sorted(out,key=lambda x:x["opened"])
def median(xs):
    return statistics.median(xs) if xs else None
def profile(rows):
    pnl=[x["pnl"] for x in rows if x["pnl"] is not None]
    by=defaultdict(list)
    for x in rows:by[(x["symbol"],x["side"])].append(x)
    adds=[];simultaneous=[]
    for xs in by.values():
        latest=[]
        for x in xs:
            latest=[z for z in latest if z["closed"]>=x["opened"]]
            if latest:
                prior=latest[-1]
                adds.append(x["side"]*(x["entry"]/prior["entry"]-1))
            latest.append(x)
    clusters=[]
    for x in rows:
        if not clusters or x["opened"]-clusters[-1][0]["opened"]>180:clusters.append([])
        clusters[-1].append(x)
    return {"rows":len(rows),"first":rows[0]["opened"],"last":max(x["closed"] for x in rows),"symbols":dict(Counter(x["symbol"] for x in rows)),"long_share":sum(x["side"]==1 for x in rows)/len(rows),"median_hold_seconds":median([x["closed"]-x["opened"] for x in rows]),"median_margin":median([x["margin"] for x in rows if x["margin"] is not None]),"leverage":dict(Counter(str(x["leverage"]) for x in rows if x["leverage"] is not None)),"pnl_rows":len(pnl),"net_pnl":sum(pnl),"win_share":sum(x>0 for x in pnl)/len(pnl) if pnl else None,"overlapping_entries":len(adds),"median_signed_add_distance":median(adds),"adverse_add_share":sum(x<0 for x in adds)/len(adds) if adds else None,"basket_clusters":sum(len({x["symbol"] for x in c})>=3 for c in clusters),"largest_basket":max(len({x["symbol"] for x in c}) for c in clusters)}
def compare(a,b):
    other=defaultdict(list)
    for x in b:other[(x["symbol"],x["side"])].append(x)
    matched=0;both=0
    for x in a:
        candidates=[y for y in other[(x["symbol"],x["side"])] if abs(x["opened"]-y["opened"])<=180]
        if candidates:
            matched+=1
            if any(abs(x["closed"]-y["closed"])<=180 for y in candidates):both+=1
    return {"alfa_entries":len(a),"matched_entries_3min":matched,"matched_entries_and_exits_3min":both}
def worker():
    global VIEW
    while True:
        profiles={};errors={};data={}
        for name,url in URLS.items():
            try:
                local=Path(__file__).parent/"leader_data"/(name+".csv")
                if local.is_file():
                    rows=parse(local.read_text(encoding="utf-8-sig"));store.put("leader_trades:"+name,rows)
                    data[name]=rows;profiles[name]=profile(rows)
                    logging.info("LEADER IMPORT uploaded %s rows=%s",name,len(rows));continue
                r=requests.get(url,timeout=20,allow_redirects=False,stream=True)
                r.raise_for_status()
                if r.status_code!=200:raise ValueError("HTTP "+str(r.status_code))
                payload=bytearray()
                for chunk in r.iter_content(65536):
                    payload.extend(chunk)
                    if len(payload)>8_000_000:raise ValueError("CSV exceeds import limit")
                rows=parse(payload.decode("utf-8-sig"));store.put("leader_trades:"+name,rows)
                data[name]=rows;profiles[name]=profile(rows)
                logging.info("LEADER IMPORT %s rows=%s profile=%s",name,len(rows),profiles[name])
            except Exception as e:
                errors[name]=str(e)[:500];logging.warning("LEADER IMPORT %s failed: %s",name,errors[name])
                rows=store.get("leader_trades:"+name,[]) or []
                if rows:data[name]=rows;profiles[name]=profile(rows)
        common=compare(data["AlfaRomeo"],data["PlymouthTrade"]) if len(data)==2 else {}
        VIEW={"time":time.time(),"profiles":profiles,"comparison":common,"errors":errors,"mode":"descriptive research only; no live copy orders"}
        store.put("leader_research_v1",VIEW)
        logging.info("LEADER RESEARCH %s",VIEW)
        time.sleep(3600)
def selftest():
    raw="Position,Qty,Margin,ROI,PnL,Entry,Exit,Opened (UTC),Closed (UTC)\nBTCUSDT Long Cross 5x,0.01,20,1,2,100,102,2026-11-01 01:00,2026-11-01 01:05\n"
    rows=parse(raw)
    assert len(rows)==1 and rows[0]["leverage"]==5 and profile(rows)["median_hold_seconds"]==300
