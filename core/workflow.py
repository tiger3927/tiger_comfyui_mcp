"""workflow：API 格式工作流的校验、参数解析、参数注入。

一期只做用户导出的 API 格式（{node_id: {inputs, class_type, _meta}}）。
参数识别两级：
1. 约定优先：_meta.title 以 INPUT_ / OUTPUT_ 开头（沿用参考工程约定）
2. 启发式兜底：按 class_type 已知映射（T3.3，基础版）
"""
from __future__ import annotations

import json
import logging
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
