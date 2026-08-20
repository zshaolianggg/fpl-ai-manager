
from __future__ import annotations
from collections import Counter
POSITION_COUNTS={1:2,2:5,3:5,4:3}

def validate_squad(squad_ids,players_by_id,budget_spent=None,budget_limit=None):
    errors=[]
    if len(squad_ids)!=15 or len(set(squad_ids))!=15:errors.append("Squad must contain 15 unique players.")
    pos=Counter();clubs=Counter()
    for pid in squad_ids:
        p=players_by_id.get(int(pid))
        if not p:errors.append(f"Unknown player id {pid}.");continue
        pos[int(p["element_type"])]+=1;clubs[int(p["team"])]+=1
    if dict(pos)!=POSITION_COUNTS:errors.append(f"Position counts invalid: {dict(pos)}")
    if clubs and max(clubs.values())>3:errors.append("More than three players from one club.")
    if budget_spent is not None and budget_limit is not None and budget_spent>budget_limit:errors.append("Budget exceeded.")
    return errors

def validate_plan(plan,players_by_id,proj_by_id,state=None,gw=None,recomputed_metrics=None):
    errors=validate_squad(plan["squad_ids"],players_by_id)
    if plan.get("bank_after",0)<0:errors.append("Negative bank.")
    lu=plan.get("lineup")
    if not lu:errors.append("Missing lineup.")
    else:
        starters=lu["starters"]
        if len(starters)!=11 or not set(starters).issubset(set(plan["squad_ids"])):errors.append("Invalid starting XI.")
        if lu["captain"] not in starters or lu["vice_captain"] not in starters:errors.append("Captain/vice not in XI.")
        if lu["captain"]==lu["vice_captain"]:errors.append("Captain and vice are identical.")
        pc=Counter(proj_by_id[x]["position"] for x in starters)
        if pc[1]!=1 or pc[2]<3 or pc[3]<2 or pc[4]<1:errors.append("Illegal XI formation.")
    if state:
        chip=plan.get("chip")
        if chip and not state.get("chips_available",{}).get(chip,False):errors.append(f"Chip {chip} is not available.")
        if gw==1 and chip in {"wildcard","freehit"}:errors.append(f"{chip} unavailable in GW1.")
        if state.get("mode")=="managed_squad":
            if chip not in {"wildcard","freehit"}:
                expected=int(state["bank"])+sum(int(t["sell"]) for t in plan["transfers"])-sum(int(t["buy"]) for t in plan["transfers"])
                if expected!=int(plan["bank_after"]):errors.append("Bank arithmetic mismatch.")
                expected_hit=max(0,len(plan["transfers"])-int(state["free_transfers"]))*4
                if expected_hit!=int(plan["hit_cost"]):errors.append("Transfer hit arithmetic mismatch.")
            else:
                budget=int(state["bank"])+sum(int(x["selling_price"]) for x in state["squad"])
                spend=sum(int(proj_by_id[x]["price"]) for x in plan["squad_ids"])
                if spend>budget:errors.append("Chip rebuild exceeds verified team purchasing budget.")
        elif state.get("mode")=="gw1_initial_build":
            spend=sum(int(proj_by_id[x]["price"]) for x in plan["squad_ids"])
            if spend>1000:errors.append("GW1 squad exceeds £100.0m.")
    if recomputed_metrics:
        for key in ("gw1","gw3","gw6","gw8","weighted"):
            if abs(float(plan["metrics"][key])-float(recomputed_metrics[key]))>.03:
                errors.append(f"Projection metric mismatch: {key}.")
    return errors
