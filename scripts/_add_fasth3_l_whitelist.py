# 一次性脚本：在 config.json 中为 video_minimax_h3_fasth3_l 加白名单（幂等）。
# 用法：cd <项目根> && python scripts/_add_fasth3_l_whitelist.py
import json
import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "config.json"
c = json.loads(p.read_text(encoding="utf-8"))
wf = "video_minimax_h3_fasth3_l"
anchor = "video_minimax_h3_fasth3_fl"

for inst in c["comfyui_instances"]:
    if inst["name"] == "U5P-0":
        only = inst["workflow_rules"]["only"]
        if wf not in only:
            only.insert(only.index(anchor) + 1, wf)
            print(f"added to {inst['name']}.workflow_rules.only")

if wf not in c["allowed_workflows"]:
    c["allowed_workflows"].insert(c["allowed_workflows"].index(anchor) + 1, wf)
    print("added to allowed_workflows")

p.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
print("config_updated")
