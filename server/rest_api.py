"""REST 端点：/api/* + /files/*。与 MCP 工具调同一批 core 方法。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.manager import ComfyUIError, ComfyUIManager, workflow_in_whitelist
from core.workflow import (
    load_named_workflow,
    parse_workflow_params,
)

logger = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    workflow_name: str = ""
    prompt_json: str = ""
    params: Optional[dict[str, Any]] = None
    instance: str = ""  # P5.13：必填（取 describe 的 routing.recommended_instance）；
                        # 空/缺失 → manager 抛 ComfyUIError → 400
    timeout_s: float = 3600.0


def _wf(mgr: ComfyUIManager, workflow_name: str, prompt_json: str) -> tuple[dict, str]:
    if workflow_name:
        return load_named_workflow(mgr.workflows_dir, workflow_name), workflow_name
    if prompt_json:
        import json
        return json.loads(prompt_json), "inline"
    raise HTTPException(400, "必须提供 workflow_name 或 prompt_json")


def build_router(mgr: ComfyUIManager) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/status")
    async def status():
        return {"instances": await mgr.status_all()}

    @r.get("/workflows")
    async def workflows():
        # P5.19：与 MCP list_workflows 同源（目录 ∩ 顶层白名单 + instances 标注）
        return {"workflows": mgr.list_workflows_gated()}

    @r.get("/workflows/{name}")
    async def workflow_detail(name: str, instance: str = Query("")):
        ok_wl, reason_wl = workflow_in_whitelist(
            mgr.config.allowed_workflows, name)
        if not ok_wl:
            # 404 不泄露"存在但未放行"（与"文件不存在"同态，P5.19 fail-closed）
            raise HTTPException(404, f"工作流不存在或未列入白名单：{name}（{reason_wl}）")
        try:
            wf = load_named_workflow(mgr.workflows_dir, name)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        params = parse_workflow_params(wf)
        health = await mgr.workflow_health(wf, name, instance or None)
        routing = await mgr.route_workflow(wf, name)  # P5.13：与 MCP describe 同源
        return {"name": name,
                "inputs": [p.to_dict() for p in params if p.kind == "input"],
                "outputs": [p.to_dict() for p in params if p.kind == "output"],
                "nodes": {nid: {"class_type": (n or {}).get("class_type", ""),
                                "title": ((n or {}).get("_meta") or {}).get("title", "")}
                          for nid, n in wf.items()},
                "health": health,
                "routing": routing,
                "stats": mgr.tasks.workflow_stats(name)}

    @r.post("/tasks", status_code=202)
    async def create_task(body: TaskRequest):
        """唯一执行入口：立即返回 task_id，用 GET /api/tasks/{id} 轮询。"""
        try:
            wf, wf_name = _wf(mgr, body.workflow_name, body.prompt_json)
            task_id = await mgr.submit_workflow(
                instance=body.instance, workflow=wf,
                params=body.params, workflow_name=wf_name,
                timeout_s=body.timeout_s,
            )
        except ComfyUIError as e:
            raise HTTPException(400, str(e))
        return {"task_id": task_id}

    @r.get("/tasks/{task_id}")
    async def task_status(task_id: str):
        # P5.20：与 MCP 同源 task_view（outputs + outputs_urls 下载直链）
        view = mgr.task_view(task_id)
        if view is None:
            raise HTTPException(404, f"任务不存在：{task_id}")
        return view

    @r.post("/tasks/{task_id}/cancel")
    async def task_cancel(task_id: str):
        ok, message = await mgr.cancel_task(task_id)
        if not ok and "不存在" in message:
            raise HTTPException(404, message)
        return {"ok": ok, "message": message}

    @r.post("/upload")
    async def upload(file: UploadFile = File(...),
                     file_type: str = Query("input"),
                     instance: str = Query("")):
        # P5.13：instance 必填（与 submit 同一实例；取 describe 的
        # routing.recommended_instance）——参数错误归 400 而非 502
        if not instance:
            raise HTTPException(400, "instance 查询参数必填"
                                     "（与 submit 同一实例，取 describe 的 "
                                     "routing.recommended_instance）")
        suffix = Path(file.filename or "upload.png").suffix or ".png"
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            result = await mgr.upload_image(instance, tmp_path,
                                            image_type=file_type)
        except ComfyUIError as e:
            raise HTTPException(502, str(e))
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return result

    return r


def files_router(mgr: ComfyUIManager) -> APIRouter:
    r = APIRouter(prefix="/files")

    @r.get("/{path:path}")
    async def download(path: str):
        """下载 output/ 产物（路径穿越防护）。"""
        base = mgr.output_dir.resolve()
        target = (base / path).resolve()
        if base != target and base not in target.parents:
            raise HTTPException(403, "路径越界")
        if not target.is_file():
            raise HTTPException(404, f"文件不存在：{path}")
        return FileResponse(target, filename=target.name)

    return r
