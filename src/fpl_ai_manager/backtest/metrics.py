from __future__ import annotations
from math import sqrt

def projection_metrics(predicted: dict[int,float], actual: dict[int,float]):
    pairs=[(float(predicted[p]),float(actual[p])) for p in predicted.keys() & actual.keys()]
    if not pairs:return {"n":0,"mae":None,"rmse":None,"bias":None}
    err=[a-p for p,a in pairs]
    return {
        "n":len(pairs),
        "mae":sum(abs(x) for x in err)/len(err),
        "rmse":sqrt(sum(x*x for x in err)/len(err)),
        "bias":sum(err)/len(err),
    }

def transfer_gain(actual_selected: float, actual_baseline: float, hit_cost: float=0.0):
    return float(actual_selected)-float(actual_baseline)-float(hit_cost)

def captain_regret(actual_captain: float, best_actual_starter: float):
    return max(0.0,float(best_actual_starter)-float(actual_captain))
