
from pathlib import Path
from datetime import datetime, timezone
import json

PATH=Path(".state/report_state.json")

def load():
    if not PATH.exists(): return {"gameweeks":{}}
    try:return json.loads(PATH.read_text())
    except Exception:return {"gameweeks":{}}

def save(data):
    PATH.parent.mkdir(parents=True,exist_ok=True)
    PATH.write_text(json.dumps(data,indent=2,default=str))

def gw_state(data,gw):
    return data.setdefault("gameweeks",{}).setdefault(str(gw),{})

def mark_sent(gw,kind,delivery=None,plan=None,news=None):
    data=load(); g=gw_state(data,gw)
    g[f"{kind}_sent_at"]=datetime.now(timezone.utc).isoformat()
    if kind=="final":
        g["delivery_mode"]=delivery
        g["final_plan"]=plan
        g["final_news"]=news or {}
    save(data)

def mark_late_checked(gw):
    data=load(); g=gw_state(data,gw)
    g["late_check_done_at"]=datetime.now(timezone.utc).isoformat()
    save(data)
