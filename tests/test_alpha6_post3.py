from fpl_ai_manager.captaincy import candidate, captain_pair_value
from fpl_ai_manager.lineup import production_captain_audit
from fpl_ai_manager.render import render_report
from fpl_ai_manager.explainer import SYSTEM


def _row(pid,pos,mean,xg90=0.0,xa90=0.0,p_app=.98):
    return {
        "player_id":pid,"position":pos,"price":80,"expected_minutes":82,"confidence":"LOW",
        "selected_by_percent":"10","xg90":xg90,"xa90":xa90,"per_gw":{3:mean},
        "fixtures":[{"gw":3,"projection":{"p_appearance":p_app,"variance":4.0,"p10":max(0,mean-2),"p90":mean+3,"p_10_plus":min(1,mean/15),"p_return":min(1,(xg90+xa90)*.7)}}],
        "minutes_projection":{"p_appearance":p_app},
    }


def test_captaincy_calibration_rewards_attacking_upside_but_mean_still_matters():
    safe=_row(1,3,5.0,xg90=.05,xa90=.05)
    attacker=_row(2,4,4.8,xg90=.75,xa90=.15)
    a=candidate(safe,3); b=candidate(attacker,3)
    assert b.utility > a.utility
    # Expected points still dominates a truly large gap.
    huge=candidate(_row(3,3,7.0,xg90=.05,xa90=.05),3)
    assert huge.utility > b.utility


def test_production_captain_audit_explains_premium_anchor_rule():
    proj={
      1:_row(1,3,5.2,xg90=.1,xa90=.1),
      2:{**_row(2,4,4.7,xg90=.8,xa90=.1),"price":150,"selected_by_percent":"60"},
      3:_row(3,3,3.0,xg90=.1,xa90=.1),
    }
    audit=production_captain_audit([1,2,3],proj,3)
    assert audit["captain"]==2
    assert "premium-anchor" in audit["reason"]


def test_explainer_instructions_are_beginner_friendly():
    assert "casual or beginner" in SYSTEM
    assert "Avoid internal engineering terms" in SYSTEM


def test_report_has_beginner_action_section_and_plain_close_call_language():
    players={i:{"web_name":f"P{i}"} for i in range(1,40)}
    proj={i:{"position":1 if i in (1,12) else (2 if i<7 else 3),"price":50} for i in range(1,40)}
    plan={"plan_id":"p","transfers":[{"out":20,"in":30,"sell":45,"buy":40}],"hit_cost":0,"bank_after":25,"chip":None,
          "lineup":{"starters":list(range(1,12)),"bench":[12,13,14,15],"captain":1,"vice_captain":2},
          "metrics":{"gw1":50,"gw3":150,"gw6":300,"weighted":140},"squad_ids":list(range(1,16))}
    decision={"confidence":"LOW","executive_reasoning":"Simple reason.","chip_reasoning":"Hold.","elite_signal":"Neutral.","news_summary":[],"risks":[],
              "alternative_plan_id":None,"transfer_signals":[],"ai_explanation_used":False}
    audit={"production_engine":"V2 managed optimizer","decision_authority":"deterministic","equivalence_band_points":.75}
    text=render_report(3,"preview","standard","managed",plan,decision,players,proj,decision_audit=audit)
    assert "## What to do" in text
    assert "Money left in the bank:" in text
    assert "£2.5m" in text
    assert "Close-call rule" in text
