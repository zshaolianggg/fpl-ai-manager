
from __future__ import annotations
from pathlib import Path
from statistics import median
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, math
from .fpl import FPLClient

def quality(past):
    ranks=[int(x["rank"]) for x in past if x.get("rank")]
    if len(ranks)<3: return None
    med=median(ranks)
    t10=sum(r<=10000 for r in ranks); t50=sum(r<=50000 for r in ranks); t100=sum(r<=100000 for r in ranks)
    recency=0
    for i,r in enumerate(ranks[-4:],1): recency += (i/10)*(math.log10(max(r,1)))
    score=math.log10(max(med,1))+0.15*recency-0.85*t10-0.35*t50-0.15*t100
    return score,{"past_seasons":len(ranks),"median_rank":int(med),"best_rank":min(ranks),"top10k":t10,"top50k":t50,"top100k":t100}

def current_weight(gw):
    if gw<=5:return 0.0
    if gw<=7:return .20
    if gw<=9:return .30
    if gw<=11:return .50
    if gw<=13:return .60
    return .80

def should_refresh(cache,gw,every=4):
    if not cache:return True
    last=int(cache.get("refreshed_gw",0))
    return gw in {1,20} or gw-last>=every

def discover(client,cfg,gw,cache_path):
    path=Path(cache_path); path.parent.mkdir(parents=True,exist_ok=True)
    cache=json.loads(path.read_text()) if path.exists() else {}
    if not should_refresh(cache,gw,cfg["refresh_every_gws"]):
        return cache,[]
    candidates=[]
    for page in range(1,cfg["candidate_pages"]+1):
        try: blob=client.league_standings(cfg["overall_league_id"],page)
        except Exception as exc: return cache,[f"Elite discovery failed: {exc}"]
        candidates += [int(r["entry"]) for r in blob.get("standings",{}).get("results",[]) if r.get("entry")]
    scored=[]
    mids=list(dict.fromkeys(candidates))
    def fetch_quality(mid):
        try:
            hist=FPLClient().history(mid)
            q=quality(hist.get("past",[]))
            if not q:return None
            score,metrics=q
            return {"entry_id":mid,"score":score,**metrics}
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(fetch_quality,mid) for mid in mids]
        for f in as_completed(futs):
            row=f.result()
            if row:scored.append(row)
    historical=[x for x in scored if x["median_rank"]<=cfg["max_historical_median_rank"]]
    historical.sort(key=lambda x:x["score"])
    historical=historical[:cfg["historical_core_size"]]
    current=[x for x in scored if x["median_rank"]<=cfg["current_quality_floor_median_rank"]]
    current.sort(key=lambda x: next((i for i,v in enumerate(candidates) if v==x["entry_id"]),10**9))
    current=current[:cfg["current_cohort_size"]]
    cache={"refreshed_gw":gw,"historical":historical,"current":current}
    path.write_text(json.dumps(cache,indent=2))
    return cache,[]

def _signal(client,ids,gw):
    own=Counter(); cap=Counter(); observed=0
    def fetch(mid):
        try:return FPLClient().picks(mid,gw).get("picks",[])
        except Exception:return []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(fetch,mid) for mid in ids]
        for f in as_completed(futs):
            picks=f.result()
            if not picks:continue
            observed+=1
            for p in picks:
                pid=int(p["element"]);own[pid]+=1
                if p.get("is_captain"):cap[pid]+=1
    return observed,own,cap

def summarize(client,cache,public_gw,players_by_id,gw):
    if not public_gw:return {"status":"unavailable","reason":"No locked picks yet.","weight_current":0.0}
    hids=[x["entry_id"] for x in cache.get("historical",[])]
    cids=[x["entry_id"] for x in cache.get("current",[])]
    ho,hown,hcap=_signal(client,hids,public_gw)
    co,cown,ccap=_signal(client,cids,public_gw)
    cw=current_weight(gw); hw=1-cw
    rows=[]
    allp=set(hown)|set(cown)
    for pid in allp:
        hp=hown[pid]/ho if ho else 0; cp=cown[pid]/co if co else 0
        hc=hcap[pid]/ho if ho else 0; cc=ccap[pid]/co if co else 0
        rows.append({"player_id":pid,"player":players_by_id.get(pid,{}).get("web_name",str(pid)),
                     "ownership_percent":round(100*(hw*hp+cw*cp),1),
                     "captain_percent":round(100*(hw*hc+cw*cc),1)})
    rows.sort(key=lambda x:(x["ownership_percent"],x["captain_percent"]),reverse=True)
    return {"status":"ok" if (ho or co) else "unavailable","historical_observed":ho,"current_observed":co,
            "weight_historical":hw,"weight_current":cw,"players":rows[:60],
            "note":"Elite signal is a bounded risk/sanity input, never the core projection."}
