"""workflow：API 格式工作流的校验、参数解析、参数注入。

一期只做用户导出的 API 格式（{node_id: {inputs, class_type, _meta}}）。
参数识别两级：
1. 约定优先：_meta.title 以 INPUT_ / OUTPUT_ 开头（沿用参考工程约定）
2. 启发式兜底：按 class_type 已知映射（T3.3，基础版）
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from schemas.models import WorkflowParam

logger = logging.getLogger(__name__)

# 启发式映射（class_type -> 候选输入参数键；仅当节点无 INPUT_ 标题约定时生效）
_HEURISTIC_INPUT: dict[str, list[str]] = {
    "LoadImage": ["image"],
    "LoadImageFromPath": ["image_path"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CLIPTextEncode": ["text"],
    "KSampler": ["seed", "steps", "cfg"],
    "KSamplerAdvanced": ["noise_seed", "steps", "cfg"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "LoraLoader": ["strength_model", "strength_clip"],
    "VHS_LoadVideo": ["video"],
    "VHS_VideoCombine": ["filename"],
}
_HEURISTIC_OUTPUT: set[str] = {
    "SaveImage", "SaveAnimatedWEBP", "SaveWEBP",
    "VHS_VideoCombine", "SaveVideo", "SaveAudio",
    "ShowText", "ShowText|py",
}


# ----------------------------------------------------------------------
# 校验
# ----------------------------------------------------------------------
def validate_api_workflow(prompt: Any) -> tuple[bool, Optional[str]]:
    """校验 API 格式工作流。返回 (ok, error)。"""
    if not isinstance(prompt, dict) or not prompt:
        return False, "工作流必须是 JSON 对象（API 格式 prompt 字典）"
    for node_id, node in prompt.items():
        if not isinstance(node_id, str):
            return False, f"节点 id 必须是字符串，收到 {type(node_id).__name__}"
        if not isinstance(node, dict):
            return False, f"节点 {node_id} 必须是对象"
        if "class_type" not in node:
            return False, f"节点 {node_id} 缺少 class_type"
        inputs = node.get("inputs")
        if inputs is not None and not isinstance(inputs, dict):
            return False, f"节点 {node_id} 的 inputs 必须是对象"
    # 连线引用检查
    for node_id, node in prompt.items():
        for key, val in (node.get("inputs") or {}).items():
            if isinstance(val, (list, tuple)) and len(val) == 2:
                src, _ = val
                if isinstance(src, str) and src not in prompt:
                    return False, f"节点 {node_id} 的输入 {key} 引用了不存在的节点 {src}"
    # INPUT_ 标题重复检查（参数注入/手术均按标题匹配，重复 = 参数打偏或节点删不掉）
    seen: dict[str, list[str]] = {}
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        title = (node.get("_meta") or {}).get("title", "") or ""
        if title.startswith("INPUT_"):
            seen.setdefault(title, []).append(str(node_id))
    for title, ids in seen.items():
        if len(ids) > 1:
            return False, (f"参数标题 {title!r} 被 {len(ids)} 个节点共用（{', '.join(ids)}）："
                           f"参数注入与文件手术按标题匹配，必须唯一")
    return True, None


def load_workflow_file(path: str | Path) -> dict:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_workflow_files(workflows_dir: str | Path) -> list[dict]:
    """列出目录下可用工作流（*.json，排除 *.backup）及同名 .md 摘要首行。"""
    d = Path(workflows_dir)
    out: list[dict] = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        if f.name.endswith(".backup"):
            continue
        md = f.with_suffix(".md")
        summary = ""
        if md.is_file():
            try:
                for line in md.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        summary = line
                        break
            except OSError:
                pass
        out.append({"name": f.stem, "file": f.name, "summary": summary,
                    "has_md": md.is_file()})
    return out


def load_named_workflow(workflows_dir: str | Path, name: str) -> dict:
    """按名称加载 workflows/{name}.json（名称里可带 .json）。"""
    d = Path(workflows_dir)
    for cand in (d / f"{name}.json", d / name):
        if cand.is_file():
            return load_workflow_file(cand)
    raise FileNotFoundError(f"工作流不存在：{name}（目录 {d}）")


# ----------------------------------------------------------------------
# 参数解析
# ----------------------------------------------------------------------
def _first_text_input(node: dict) -> Optional[str]:
    """节点里第一个可注入的输入键（字符串/数值输入，排除连线）。"""
    for key, val in (node.get("inputs") or {}).items():
        if not isinstance(val, (list, tuple)):
            return key
    return None


def parse_workflow_params(workflow: dict) -> list[WorkflowParam]:
    """解析输入/输出参数。约定（INPUT_/OUTPUT_ 标题）优先，启发式兜底。"""
    params: list[WorkflowParam] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        title = (node.get("_meta") or {}).get("title", "") or ""

        # 约定输入
        if title.startswith("INPUT_"):
            key = _first_text_input(node)
            if key:
                params.append(WorkflowParam(
                    node_id=node_id, class_type=class_type, title=title,
                    kind="input", param=key, default=node["inputs"].get(key),
                ))
            continue
        # 约定输出
        if title.startswith("OUTPUT_"):
            params.append(WorkflowParam(
                node_id=node_id, class_type=class_type, title=title,
                kind="output", param=None,
            ))
            continue
        # 启发式输入
        if class_type in _HEURISTIC_INPUT:
            for key in _HEURISTIC_INPUT[class_type]:
                if key in (node.get("inputs") or {}):
                    params.append(WorkflowParam(
                        node_id=node_id, class_type=class_type,
                        title=title or class_type, kind="input",
                        param=key, default=node["inputs"][key],
                    ))
            continue
        if class_type in _HEURISTIC_OUTPUT:
            params.append(WorkflowParam(
                node_id=node_id, class_type=class_type,
                title=title or class_type, kind="output", param=None,
            ))
    return params


# ----------------------------------------------------------------------
# 参数注入
# ----------------------------------------------------------------------
def inject_params(workflow: dict, params: dict[str, Any]) -> tuple[dict, list[str], list[str]]:
    """把 {参数名: 值} 注入工作流（深拷贝，不改原 dict）。

    匹配顺序：INPUT_ 标题精确 -> 去 INPUT_ 前缀 -> 启发式 param 键。
    返回 (新工作流, 已注入 [名字], 未匹配 [名字])。
    """
    parsed = parse_workflow_params(workflow)
    inputs = [p for p in parsed if p.kind == "input"]
    new = json.loads(json.dumps(workflow, ensure_ascii=False))
    applied: list[str] = []
    unmatched: list[str] = []

    for name, value in params.items():
        target: Optional[WorkflowParam] = None
        for p in inputs:
            if p.title == name:                      # INPUT_X 精确
                target = p
                break
        if target is None:
            for p in inputs:
                if p.title.removeprefix("INPUT_") == name:  # 去前缀
                    target = p
                    break
        if target is None:
            for p in inputs:
                if p.param == name:                 # 输入键名
                    target = p
                    break
        if target is None:
            unmatched.append(name)
            continue
        if target.node_id in new and isinstance(new[target.node_id].get("inputs"), dict):
            new[target.node_id]["inputs"][target.param or "text"] = value
            applied.append(name)
        else:
            unmatched.append(name)
    return new, applied, unmatched


# ----------------------------------------------------------------------
# JSON 手术：删除未提供参数的文件槽节点
# ----------------------------------------------------------------------
# 文件槽标题：INPUT_ 前缀 + 数字编号 + _FILE 后缀（如 INPUT_IMAGE_1_FILE）。
# 非数字命名（如 INPUT_IMAGE_FIRST_FILE）不在手术范围内，保持原样。
_FILE_SLOT_TITLE = re.compile(r"^INPUT_.+\d+_FILE$")


def _family_member(key: str) -> Optional[tuple[str, str, int]]:
    """'images.image_3' -> ('images', 'image', 3)；非变长列表槽命名返回 None。"""
    m = re.match(r"^(.+)\.([^.]*?)_(\d+)$", key)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def _resolve_provided_titles(workflow: dict,
                             params: dict[str, Any]) -> set[str]:
    """按 inject_params 同款三级匹配，返回实际提供了取值的 INPUT_ 节点标题集合。"""
    inputs = [p for p in parse_workflow_params(workflow) if p.kind == "input"]
    provided: set[str] = set()
    for name in params:
        target: Optional[WorkflowParam] = None
        for p in inputs:
            if p.title == name:
                target = p
                break
        if target is None:
            for p in inputs:
                if p.title.removeprefix("INPUT_") == name:
                    target = p
                    break
        if target is None:
            for p in inputs:
                if p.param == name:
                    target = p
                    break
        if target is not None:
            provided.add(target.title)
    return provided


def prune_unsupplied_file_nodes(workflow: dict,
                                params: dict[str, Any]) -> tuple[dict, list[str]]:
    """手术：删除未提供对应参数的 INPUT_...N_FILE 节点，并清理消费侧列表槽连线。

    例：10 个文件槽只传 3 个参数 -> 删 7 个 LoadImage 节点 + 消费节点上
    对应的 images.image_4..image_10 键。

    fail-closed（拿不准就报错，绝不静默改图）：
    - 未提供节点指向消费节点的「必需单输入」（非变长列表槽，如 first_frame）
      -> 报错中止；
    - 每个列表槽剩余成员必须连续且含最小编号（最小编号的文件参数必传）
      -> 缺号/缺首位报错中止；
    - 全部文件槽都未提供 -> 报错（至少传一张图）。
    返回 (新工作流, 被删节点标题列表)；不修改入参 dict。
    """
    file_nodes: dict[str, str] = {}  # node_id -> title
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        title = (node.get("_meta") or {}).get("title", "") or ""
        if _FILE_SLOT_TITLE.match(title):
            file_nodes[nid] = title
    if not file_nodes:
        return workflow, []

    provided = _resolve_provided_titles(workflow, params)
    missing = {nid: t for nid, t in file_nodes.items() if t not in provided}
    if not missing:
        return workflow, []
    if len(missing) == len(file_nodes):
        raise ValueError(
            "该工作流至少需要传 1 张参考图：未提供任何文件参数"
            f"（可用：{', '.join(sorted(file_nodes.values()))}）")

    # 逐列表槽校验（原图上、删除前）：必需单输入护栏 + 连续性 + 最小编号必传
    checked: set[tuple[str, str, str]] = set()
    for nid, title in missing.items():
        for cid, c in workflow.items():
            inputs = c.get("inputs") or {}
            for key, val in inputs.items():
                if not (isinstance(val, (list, tuple))
                        and len(val) == 2 and val[0] == nid):
                    continue
                mem = _family_member(key)
                if mem is None:
                    raise ValueError(
                        f"{title} 连接在必需单输入上（节点 {cid} "
                        f"{c.get('class_type')}.{key}），不可删除：该工作流需要"
                        f"此图，请提供对应参数")
                fam = (cid, mem[0], mem[1])
                if fam in checked:
                    continue
                checked.add(fam)
                members: dict[int, str] = {}
                for k in inputs:
                    m = _family_member(k)
                    if m and (m[0], m[1]) == (mem[0], mem[1]):
                        members[m[2]] = k
                kept: set[int] = set()
                for num, k in members.items():
                    src = workflow[cid]["inputs"][k]
                    src_id = src[0] if isinstance(src, (list, tuple)) else None
                    if src_id in file_nodes and file_nodes[src_id] not in provided:
                        continue
                    kept.add(num)
                if not kept:
                    raise ValueError(
                        f"图片输入组 {mem[0]}.{mem[1]} 至少需要传 1 张：未提供任何对应文件参数")
                # 可删的高位槽在 max(kept) 以上；lo..max(kept) 区间内不得有洞
                lo = min(members)
                need = [members[i] for i in range(lo, max(kept) + 1)
                        if i not in kept]
                if need:
                    raise ValueError(
                        "文件参数须从最小编号开始连续提供（缺 "
                        + "、".join(need) + "；已提供 "
                        + "、".join(members[i] for i in sorted(kept)) + "）")

    new = json.loads(json.dumps(workflow, ensure_ascii=False))
    pruned: list[str] = []
    for nid, title in missing.items():
        for cid, c in new.items():
            inputs = c.get("inputs") or {}
            for k in list(inputs):
                val = inputs[k]
                if isinstance(val, (list, tuple)) and len(val) == 2 and val[0] == nid:
                    del inputs[k]
        del new[nid]
        pruned.append(title)
    return new, pruned


# ----------------------------------------------------------------------
# JSON 手术（混合多参考制度）：multi_ref
# ----------------------------------------------------------------------
# 适用于 minimax h3 r2v 类工作流：IMAGE/VIDEO/AUDIO 各成数字家族，
# 每类可为 0；提供则必须从最小编号连续；INPUT_..._FILE_N_ADD 卫星节点
# （如 GetVideoComponents）随缺失的父文件节点级联摘除，消费侧连线全清。
_SAT_TITLE = re.compile(r"^INPUT_.+_FILE_\d+_ADD$")
_FILE_TITLE_NUM = re.compile(r"^INPUT_(.+?)_(\d+)_FILE$")


def _is_conn(val: Any) -> bool:
    """[src_node_id, slot] 连线值。"""
    return (isinstance(val, (list, tuple)) and len(val) == 2
            and isinstance(val[0], str))


def prune_multi_ref_file_nodes(workflow: dict,
                               params: dict[str, Any]) -> tuple[dict, list[str]]:
    """手术（混合多参考制度）：摘除未提供参数的 INPUT_...N_FILE 节点及其卫星。

    规则（与 image_edit 制度的差异）：
    - 每个数字家族（按 title 词干分组，如 IMAGE/VIDEO/AUDIO）允许整体缺失（0 合法），
      不存在"至少 1 个"与全局 0 拦截；
    - 某家族只要有提供，必须是自最小编号起的连续前缀 -> 缺低位/缺号报错中止；
    - 缺失节点的消费侧必须是带点变长列表槽或 _ADD 卫星；卫星仅在其全部连线输入源
      都已在删除集内时级联摘除（半保留父节点 -> 报错），且其输出必须落在列表槽
      上（落在必需单输入 -> 报错）。fail-closed。
    返回 (新工作流, 被删节点标题列表)；不修改入参 dict。
    """
    file_nodes: dict[str, str] = {}
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        title = (node.get("_meta") or {}).get("title", "") or ""
        if _FILE_SLOT_TITLE.match(title):
            file_nodes[nid] = title
    if not file_nodes:
        return workflow, []

    provided = _resolve_provided_titles(workflow, params)
    missing = {nid for nid, t in file_nodes.items() if t not in provided}
    if not missing:
        return workflow, []

    # 1) 逐家族连续性（文件编号空间）：已提供编号须为最小编号起的连续前缀。
    #    家族按 title 前缀分组（INPUT_{词干}）；成员标题 = 前缀 + _{编号}_FILE
    families: dict[str, dict[int, str]] = {}
    for nid, title in file_nodes.items():
        m = _FILE_TITLE_NUM.match(title)
        if not m:
            continue
        prefix = f"INPUT_{m.group(1)}"
        families.setdefault(prefix, {})[int(m.group(2))] = title
    for prefix, members in sorted(families.items()):
        lo = min(members)
        kept = {n for n in members
                if f"{prefix}_{n}_FILE" in provided}
        if not kept:
            continue  # 整族缺失 -> 全删（0 合法）
        hi = max(kept)
        need = [members[i] for i in range(lo, hi + 1) if i not in kept]
        if need:
            raise ValueError(
                f"{prefix}_N_FILE 文件参数须从最小编号开始连续提供：缺 "
                + "、".join(need)
                + "（已提供 " + "、".join(members[i] for i in sorted(kept)) + "）")

    # 2) 级联闭包：缺失文件节点 -> 拉入其 _ADD 卫星（fail-closed）
    titles: dict[str, str] = {
        nid: ((workflow[nid].get("_meta") or {}).get("title", "") or f"节点 {nid}")
        for nid in workflow if isinstance(workflow[nid], dict)}
    delete: set[str] = set(missing)
    while True:
        progressed = False
        for cid, c in workflow.items():
            if cid in delete or not isinstance(c, dict):
                continue
            inputs = c.get("inputs") or {}
            bare_to_delete = {
                v[0] for k, v in inputs.items()
                if _is_conn(v) and _family_member(k) is None and v[0] in delete}
            if not bare_to_delete:
                continue
            if not _SAT_TITLE.match(titles.get(cid, "")):
                k0 = next(k for k, v in inputs.items()
                          if _is_conn(v) and _family_member(k) is None
                          and v[0] in delete)
                raise ValueError(
                    f"{titles[inputs[k0][0]]} 连接在必需单输入上（节点 {cid} "
                    f"{c.get('class_type', '?')}.{k0}），不可删除：该工作流需要"
                    f"此文件，请提供对应参数")
            srcs = {v[0] for v in inputs.values() if _is_conn(v)}
            unready = sorted(srcs - delete)
            if unready:
                raise ValueError(
                    f"卫星节点 {titles[cid]}（节点 {cid}）同时被保留节点 {unready} "
                    f"喂养，无法级联删除")
            for cid2, c2 in workflow.items():
                if cid2 in delete or not isinstance(c2, dict):
                    continue
                for k2, v2 in (c2.get("inputs") or {}).items():
                    if _is_conn(v2) and v2[0] == cid:
                        if _family_member(k2) is None:
                            raise ValueError(
                                f"卫星节点 {titles[cid]}（节点 {cid}）的输出落在"
                                f"必需单输入上（节点 {cid2} "
                                f"{c2.get('class_type', '?')}.{k2}），不可删除")
            delete.add(cid)
            progressed = True
        if not progressed:
            break

    # 3) 摘除 + 清所有消费侧连线（按键级全扫：多消费/多输出槽一次清净）
    new = json.loads(json.dumps(workflow, ensure_ascii=False))
    pruned = [titles[nid] for nid in delete]
    for nid in delete:
        for cid, c in new.items():
            inputs = c.get("inputs") or {}
            for k in list(inputs):
                if _is_conn(inputs[k]) and inputs[k][0] == nid:
                    del inputs[k]
        del new[nid]
    return new, pruned
