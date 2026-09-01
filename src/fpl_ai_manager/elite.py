from __future__ import annotations
from pathlib import Path
from statistics import median
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from time import monotonic
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


def _executor_results(callables, max_workers, budget_seconds):
    """Run optional bulk FPL calls under a wall-clock budget.

    In-flight requests use short HTTP timeouts. Once the budget expires we keep
    partial results and abandon the remaining optional enrichment work.
    """
    ex=ThreadPoolExecutor(max_workers=max_workers)
    futures=[ex.submit(fn) for fn in callables]
    out=[]; timed_out=False
    deadline=monotonic()+max(1.0,float(budget_seconds))
    try:
        pending=set(futures)
        while pending:
            remaining=deadline-monotonic()
            if remaining<=0:
                timed_out=True; break
            try:
                f=next(as_completed(pending, timeout=remaining))
            except TimeoutError:
                timed_out=True; break
            pending.remove(f)
            try:
                value=f.result()
                if value is not None: out.append(value)
            except Exception:
                pass
        for f in pending: f.cancel()
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return out,timed_out


def discover(client,cfg,gw,cache_path,runtime_cfg=None):
    runtime_cfg=runtime_cfg or {}
    path=Path(cache_path); path.parent.mkdir(parents=True,exist_ok=True)
    cache=json.loads(path.read_text()) if path.exists() else {}
    if not should_refresh(cache,gw,cfg["refresh_every_gws"]):
        return cache,[]
    warnings=[]; candidates=[]
    bulk_timeout=float(runtime_cfg.get("bulk_fpl_timeout_seconds",6))
    bulk_retries=int(runtime_cfg.get("bulk_fpl_retries",1))
    budget=float(runtime_cfg.get("elite_discovery_budget_seconds",90))
    started=monotonic()
    for page in range(1,cfg["candidate_pages"]+1):
        if monotonic()-started>=budget:
            warnings.append("Elite discovery budget exhausted while reading standings; stale/partial cohort used.")
            break
        try: blob=FPLClient(timeout=bulk_timeout,retries=bulk_retries).league_standings(cfg["overall_league_id"],page)
        except Exception as exc:
            warnings.append(f"Elite standings page {page} unavailable: {exc}")
            break
        candidates += [int(r["entry"]) for r in blob.get("standings",{}).get("results",[]) if r.get("entry")]
    mids=list(dict.fromkeys(candidates))
    remaining=max(1.0,budget-(monotonic()-started))
    def make_fetch(mid):
        def fetch():
            try:
                hist=FPLClient(timeout=bulk_timeout,retries=bulk_retries).history(mid)
                q=quality(hist.get("past",[]))
                if not q:return None
                score,metrics=q
                return {"entry_id":mid,"score":score,**metrics}
            except Exception:return None
        return fetch
    scored,timed_out=_executor_results([make_fetch(mid) for mid in mids],8,remaining)
    if timed_out:
        warnings.append(f"Elite discovery hit its {budget:.0f}s budget; partial cohort used and recommendation continued.")
    if not scored:
        if cache:
            warnings.append("Elite refresh produced no usable rows; retained cached cohort.")
            return cache,warnings
        return {"refreshed_gw":gw,"historical":[],"current":[]},warnings+["Elite cohort unavailable; continuing without elite signal."]
    historical=[x for x in scored if x["median_rank"]<=cfg["max_historical_median_rank"]]
    historical.sort(key=lambda x:x["score"]); historical=historical[:cfg["historical_core_size"]]
    position={mid:i for i,mid in enumerate(candidates)}
    current=[x for x in scored if x["median_rank"]<=cfg["current_quality_floor_median_rank"]]
    current.sort(key=lambda x:position.get(x["entry_id"],10**9)); current=current[:cfg["current_cohort_size"]]
    new_cache={"refreshed_gw":gw,"historical":historical,"current":current,"partial":bool(timed_out)}
    path.write_text(json.dumps(new_cache,indent=2))
    return new_cache,warnings


def _signal(client,ids,gw,runtime_cfg=None):
    runtime_cfg=runtime_cfg or {}
    bulk_timeout=float(runtime_cfg.get("bulk_fpl_timeout_seconds",6))
    bulk_retries=int(runtime_cfg.get("bulk_fpl_retries",1))
    budget=float(runtime_cfg.get("elite_signal_budget_seconds",75))
    own=Counter(); cap=Counter(); observed=0
    def make_fetch(mid):
        def fetch():
            try:return FPLClient(timeout=bulk_timeout,retries=bulk_retries).picks(mid,gw).get("picks",[])
            except Exception:return []
        return fetch
    rows,timed_out=_executor_results([make_fetch(mid) for mid in ids],8,budget)
    for picks in rows:
        if not picks:continue
        observed+=1
        for p in picks:
            pid=int(p["element"]);own[pid]+=1
            if p.get("is_captain"):cap[pid]+=1
    return observed,own,cap,timed_out


def summarize(client,cache,public_gw,players_by_id,gw,runtime_cfg=None):
    if not public_gw:return {"status":"unavailable","reason":"No locked picks yet.","weight_current":0.0}
    runtime_cfg=runtime_cfg or {}
    hids=[x["entry_id"] for x in cache.get("historical",[])]
    cids=[x["entry_id"] for x in cache.get("current",[])]
    # Split the configured total signal budget between the two cohorts.
    total=float(runtime_cfg.get("elite_signal_budget_seconds",75))
    half_cfg={**runtime_cfg,"elite_signal_budget_seconds":max(5.0,total/2)}
    ho,hown,hcap,hto=_signal(client,hids,public_gw,half_cfg)
    co,cown,ccap,cto=_signal(client,cids,public_gw,half_cfg)
    cw=current_weight(gw); hw=1-cw
    rows=[]
    allp=set(hown)|set(cown)
    for pid in allp:
        hp=hown[pid]/ho if ho else 0; cp=cown[pid]/co if co else 0
        hc=hcap[pid]/ho if ho else 0; cc=ccap[pid]/co if co else 0
        rows.append({"player_id":pid,"player":players_by_id.get(pid,{}).get("web_name",str(pid)),
                     "ownership_percent":round(100*(hw*hp+cw*cp),1),"captain_percent":round(100*(hw*hc+cw*cc),1)})
    rows.sort(key=lambda x:(x["ownership_percent"],x["captain_percent"]),reverse=True)
    return {"status":"ok" if (ho or co) else "unavailable","historical_observed":ho,"current_observed":co,
            "weight_historical":hw,"weight_current":cw,"players":rows[:60],"partial":bool(hto or cto),
            "note":"Elite signal is a bounded risk/sanity input, never the core projection. Partial elite data is allowed when the runtime budget expires."}
