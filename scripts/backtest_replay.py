#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from fpl_ai_manager.backtest.replay import replay_snapshot

p=argparse.ArgumentParser(description="Replay frozen FPL V2/V3 pre-deadline snapshot without network access")
p.add_argument("snapshot")
a=p.parse_args()
result=replay_snapshot(json.loads(Path(a.snapshot).read_text(encoding="utf-8")))
print(json.dumps(result,indent=2,default=str))
