
def recommendation_confidence(state, chosen, projections_by_id, news_warnings, data_warnings, plan_gap):
    if not state.get("actionable"):
        return "LOW"
    xi=chosen.get("lineup",{}).get("starters",[])
    if not xi: return "LOW"
    conf=[projections_by_id[p].get("confidence","LOW") for p in xi]
    low=sum(x=="LOW" for x in conf)
    penalty=0
    if low>=5: penalty+=2
    elif low>=2: penalty+=1
    if news_warnings: penalty+=1
    if len(data_warnings)>=2: penalty+=1
    if plan_gap < .75: penalty+=1
    if penalty==0:return "HIGH"
    if penalty<=2:return "MEDIUM"
    return "LOW"
