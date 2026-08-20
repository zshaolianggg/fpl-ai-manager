
from __future__ import annotations
from collections import defaultdict
from .stats import norm_name
from .minutes import expected_minutes

GOAL_POINTS = {1:6,2:6,3:5,4:4}
CS_POINTS = {1:4,2:4,3:1,4:0}
PRIOR_XG90 = {1:0.01,2:0.05,3:0.18,4:0.32}
PRIOR_XA90 = {1:0.01,2:0.08,3:0.16,4:0.12}
CS_BY_FDR = {1:0.50,2:0.41,3:0.31,4:0.23,5:0.16}

def _num(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default

def fixture_map(fixtures, teams, next_gw, horizon=8):
    out = defaultdict(list)
    for f in fixtures:
        ev = f.get("event")
        if not ev or not (next_gw <= int(ev) < next_gw+horizon):
            continue
        h,a = int(f["team_h"]),int(f["team_a"])
        out[h].append({"gw":int(ev),"opponent":a,"opponent_name":teams[a],"venue":"H","difficulty":int(f.get("team_h_difficulty") or 3),"kickoff_time":f.get("kickoff_time")})
        out[a].append({"gw":int(ev),"opponent":h,"opponent_name":teams[h],"venue":"A","difficulty":int(f.get("team_a_difficulty") or 3),"kickoff_time":f.get("kickoff_time")})
    return out

def _understat_rates(row, pos):
    if not row:
        return PRIOR_XG90[pos], PRIOR_XA90[pos], 0.0
    mins = _num(row.get("time"))
    if mins <= 0:
        return PRIOR_XG90[pos], PRIOR_XA90[pos], 0.0
    return 90*_num(row.get("xG"))/mins, 90*_num(row.get("xA"))/mins, mins

def attacking_rates(player, ext_current, ext_prior):
    pos = int(player["element_type"])
    key = norm_name(player.get("web_name"))
    cur = ext_current.get(key)
    prior = ext_prior.get(key)
    cxg,cxa,cmins = _understat_rates(cur,pos)
    pxg,pxa,pmins = _understat_rates(prior,pos)
    # Official FPL xG/xA is mandatory base; external source can strengthen the rate.
    fmins = _num(player.get("minutes"))
    if fmins > 0:
        fxg = 90*_num(player.get("expected_goals"))/fmins
        fxa = 90*_num(player.get("expected_assists"))/fmins
    else:
        fxg,fxa = PRIOR_XG90[pos],PRIOR_XA90[pos]
    current_weight = min(0.80, max(fmins,cmins)/900.0)
    live_xg = (fxg + cxg)/2 if cmins else fxg
    live_xa = (fxa + cxa)/2 if cmins else fxa
    prior_xg = pxg if pmins else PRIOR_XG90[pos]
    prior_xa = pxa if pmins else PRIOR_XA90[pos]
    xg90 = current_weight*live_xg + (1-current_weight)*prior_xg
    xa90 = current_weight*live_xa + (1-current_weight)*prior_xa
    return max(0,xg90), max(0,xa90), ("MEDIUM" if current_weight >= .35 else "LOW")

def project_fixture(player, exp_minutes, xg90, xa90, f):
    pos = int(player["element_type"])
    mins_ratio = exp_minutes/90
    p_appear = min(1.0, exp_minutes/30.0)
    p60 = max(0.0,min(1.0,(exp_minutes-25)/40))
    appearance = p_appear + p60
    attack_mult = {1:1.18,2:1.09,3:1.0,4:.91,5:.82}.get(int(f["difficulty"]),1.0)
    if f["venue"]=="H": attack_mult *= 1.035
    goals = xg90*mins_ratio*attack_mult*GOAL_POINTS[pos]
    assists = xa90*mins_ratio*attack_mult*3
    cs = CS_BY_FDR.get(int(f["difficulty"]),.31) * CS_POINTS[pos] * p60
    saves = 0.0
    if pos == 1 and _num(player.get("minutes")) > 0:
        saves90 = 90*_num(player.get("saves"))/_num(player.get("minutes"))
        saves = (saves90/3.0)*mins_ratio
    bonus_rate = 0.0
    if _num(player.get("minutes")) > 0:
        bonus_rate = min(.8, 90*_num(player.get("bonus"))/_num(player.get("minutes")))
    conceded_penalty = -0.18*(1-CS_BY_FDR.get(int(f["difficulty"]),.31))*p60 if pos in {1,2} else 0
    return max(0.0, appearance+goals+assists+cs+saves+bonus_rate*mins_ratio+conceded_penalty)

def build_projections(players, teams, fixtures, next_gw, summaries, external, news_index, horizon=8):
    fmap = fixture_map(fixtures, teams, next_gw, horizon)
    rows=[]
    for p in players:
        pid=int(p["id"])
        hist=(summaries.get(pid) or {}).get("history",[])
        prior=external.get("prior",{}).get(norm_name(p.get("web_name")))
        em, min_conf = expected_minutes(p,hist,prior,news_index)
        xg90,xa90,rate_conf=attacking_rates(p,external.get("current",{}),external.get("prior",{}))
        per={}
        fixture_detail=[]
        for gw in range(next_gw,next_gw+horizon):
            pts=0.0
            for f in [x for x in fmap.get(int(p["team"]),[]) if x["gw"]==gw]:
                fp=project_fixture(p,em,xg90,xa90,f)
                pts += fp
                fixture_detail.append({**f,"projected_points":round(fp,2)})
            per[gw]=round(pts,2)
        def total(n): return round(sum(per.get(g,0) for g in range(next_gw,next_gw+n)),2)
        conf = "HIGH" if min_conf=="HIGH" and rate_conf=="MEDIUM" else ("MEDIUM" if min_conf!="LOW" else "LOW")
        rows.append({
            "player_id":pid,"player":p.get("web_name"),"team_id":int(p["team"]),"team":teams[int(p["team"])],
            "position":int(p["element_type"]),"price":int(p["now_cost"]),
            "expected_minutes":em,"xg90":round(xg90,3),"xa90":round(xa90,3),"confidence":conf,
            "gw1":total(1),"gw3":total(3),"gw6":total(6),"gw8":total(8),"per_gw":per,
            "fixtures":fixture_detail,"status":p.get("status"),"selected_by_percent":p.get("selected_by_percent")
        })
    return rows

def weighted_player_score(row, weights):
    return round(weights["gw1"]*row["gw1"] + weights["gw3"]*row["gw3"] + weights["gw6"]*row["gw6"],4)
