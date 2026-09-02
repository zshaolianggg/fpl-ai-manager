import json
from unittest.mock import patch
from fpl_ai_manager.ai import compact_payload, decide

def _payload(nproj=100, nplans=20):
    plans=[]
    for i in range(nplans):
        plans.append({"plan_id":f"p{i}","optimizer_rank":i+1,"chip":None,"transfers":[],"hit_cost":0,"bank_after":10,
                      "optimizer_score":100-i/10,"metrics":{"gw1":50,"gw3":150,"gw6":300,"weighted":140,"lineups":{"huge":"x"*1000}},
                      "lineup":{"starters":list(range(1,12)),"bench":[12,13,14,15],"captain":1,"vice":2},"squad_ids":list(range(1,16))})
    projs=[]
    for i in range(1,nproj+1):
        projs.append({"player_id":i,"name":f"P{i}","position":3,"team":"T","price":60,"expected_minutes":80,"confidence":"LOW",
                      "gw1":5,"gw3":15,"gw6":30,"per_gw":{g:{"mean_points":5,"p_start":.9,"p_zero_minutes":.05,"expected_minutes":80,"junk":"x"*3000} for g in range(1,9)}})
    return {"mode":"managed","report_type":"preview","delivery_mode":"standard","gameweek":3,"objective":"rank","risk_profile":"balanced",
            "state":{"mode":"managed","bank":10,"free_transfers":2,"chips_available":{}},"optimizer_plans":plans,"projection_evidence":projs,
            "multigw_shadow":[],"v2_v3_comparison":{},"captaincy_shadow":{},"decision_audit":{},"elite_signal":{},"chip_opportunities":{},
            "news":{"status":"DEGRADED","items":[]},"warnings":[],"policy":{}}

def test_compact_payload_is_bounded_and_drops_heavy_fields():
    c=compact_payload(_payload())
    raw=json.dumps(c,separators=(",",":"))
    assert len(c["optimizer_plans"]) <= 8
    assert len(c["projection_evidence"]) <= 40
    assert len(raw) < 120_000
    assert "lineups" not in raw
    assert "junk" not in raw

def test_decide_falls_back_to_rank_one_when_openai_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","x")
    with patch("fpl_ai_manager.ai.OpenAI") as cls:
        cls.return_value.responses.create.side_effect=RuntimeError("context too large")
        decision,resp=decide(_payload(),timeout=1)
    assert resp is None
    assert decision["plan_id"]=="p0"
    assert "deterministic optimizer rank #1" in decision["executive_reasoning"]
