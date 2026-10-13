# 一次性脚本：把 4 个 MiniMax H3 工作流加入指定实例的 workflow_rules.only（幂等）。
# 用法：python scripts/_add_fasth3_u4p_whitelist.py <config.json 路径> [实例名]
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
inst_name = sys.argv[2] if len(sys.argv) > 2 else "U4P-8189"
c = json.loads(p.read_text(encoding="utf-8"))
add = [
    "video_minimax_h3_fasth3_f",
    "video_minimax_h3_fasth3_fl",
    "video_minimax_h3_fasth3_l",
    "video_minimax_h3_r2v",
]
for inst in c["comfyui_instances"]:
    if inst["name"] == inst_name:
        only = inst["workflow_rules"]["only"]
        for wf in add:
            if wf not in only:
                only.append(wf)
                print(f"added {wf} to {inst_name}.only")
        break
else:
    sys.exit(f"instance {inst_name!r} not found")
p.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
print("config_updated, only =", only)
