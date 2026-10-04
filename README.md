# tiger_comfyui_mcp

基于 ComfyUI 的 WebSocket/HTTP 协议实现的 MCP 工具服务，支持 `comfyui_login` 插件认证、多实例、工作流执行与解析。单进程双入口：

| 入口 | 端点 | 用途 |
| --- | --- | --- |
| MCP（Streamable HTTP，stateless） | `/mcp/` | 供 LLM / IDE MCP 客户端调用 |
| REST | `/api/*`、`/files/*` | 供脚本/调试直接调用 |

默认监听 `0.0.0.0:18800`（`config.json` 可改）。

本项目采用 qwen3.8-27b 模型开发和升级！

## 快速开始

```bash
# 本项目约定依赖装在 conda base（不建 venv）；用虚拟环境的把 python 换成对应解释器即可
python -m pip install mcp fastapi uvicorn aiohttp pydantic

# 启动
python main.py
```

启动日志会提示认证模式：**`command_token`/`query_token` 均未配置 = 无认证运行（仅限本机调试）**，远程访问务必配置。

## 配置（config.json）

| 字段 | 说明 |
| --- | --- |
| `comfyui_instances` | ComfyUI 实例列表 `[{name, url, password, workflow_rules?}]`（多实例：newgoai / 蜜蜂找铺 等） |
| `comfyui_instances[].workflow_rules` | 实例工作流匹配规则（P5.13）：`{exclude: [...], only: [...]}`——**排除**（黑名单，命中=不支持）/**只能**（白名单，非空且不命中=不支持）/条目支持通配符 `* ? [seq]`（fnmatch，对工作流名不含 .json，大小写敏感）；**评估顺序固定 exclude→only→都空=全支持**；不配 = 该实例全支持 |
| `default_instance` | 默认实例名（路由平局打破 + describe 定向 health 检查未传 instance 时用；submit/upload 的 instance 必填，不用于兜底） |
| `routing.weights` | 路由打分权重（P5.13）：`score = pending×pending + running×running`，供 describe 的 routing 块选"符合要求 ∩ 排队最少"实例；默认 `{pending: 1.0, running: 2.0}` |
| `server.host` / `server.port` | 监听地址/端口，默认 `0.0.0.0:18800` |
| `server.mcp_allowed_hosts` / `server.mcp_allowed_origins` | MCP `/mcp/` 的 Host/Origin 白名单（mcp 2.x DNS rebinding 防护；不配置=仅放行 localhost，用其他地址连 `/mcp/` 报 421）；支持 `host:*` 通配端口，如 `"119.84.39.2:*"` |
| `command_token` | 全权限 Bearer token（可调用执行类工具） |
| `query_token` | 只读 Bearer token（状态/列表/描述/任务查询；执行类 403） |
| `workflows_dir` / `output_dir` / `log_dir` | 工作流目录 / 生成产物落盘 / 日志 |
| `output_retention_days` | `output/` 产物保留天数，默认 7，≤0=不清理；启动时 + 每 `cleanup_interval_hours` 小时按 mtime 扫删 |
| `cleanup_interval_hours` | 周期清理间隔（小时），默认 6，≤0=仅启动时跑一次 |
| `task_retention_hours` | 终态任务（completed/failed/cancelled）保留时长（小时），默认 24，≤0=不按时间裁剪；进行中任务不受影响 |
| `task_max_retained` | 终态任务最大保留条数，默认 200，≤0=不限 |

工作流资产在 `workflows/`（json 为 API 格式 prompt 字典，同名 .md 为说明，含"所需节点"清单）。
参数注入约定：`_meta.title` 以 `INPUT_` 开头的节点为输入参数（如 `INPUT_POSITIVE_TEXT`），`OUTPUT_` 开头为文本输出；无约定时按 class_type 启发式识别。
**媒体输入约定**：全部工作流的媒体参数均为**文件名**（`INPUT_*_FILE`，如 `INPUT_IMAGE_FILE`/`INPUT_AUDIO_FILE`/`INPUT_VIDEO_FILE`）——先调 `comfyui_upload_file` 上传取返回的 `name`，再以 `params` 注入（上传与执行须同一实例）；工作流不存在 base64/URL 媒体输入。

**多实例路由（P5.13）**：`comfyui_describe_workflow` 返回 `routing` 块——`recommended_instance` = 符合要求（`workflow_rules` ∩ 可达）且排队最少（`routing.weights` 加权最低分，平局→`default_instance`）；`candidates` 列各实例 `supported/excluded_reason/queued/running/health/score`。**实例选择由调用方完成**：`comfyui_submit_task` / `comfyui_upload_file` 的 `instance` 参数**必填**（空→立即报错），点名实例不匹配其 `workflow_rules` 时**立即硬拒**（不排队后炸）；服务端不自动路由。内联 `prompt_json` 无名字，不受实例规则限制。

## MCP 接入

MCP 客户端配置（Streamable HTTP）：

```json
{
  "mcpServers": {
    "tiger-comfyui-mcp": {
      "url": "http://127.0.0.1:18800/mcp/",
      "headers": { "Authorization": "Bearer <command_token>" }
    }
  }
}
```

> 端点用带尾斜杠的 `/mcp/`（`/mcp` 会 307 重定向）。

### 工具清单（8 个）

| 工具 | 说明 | 权限 |
| --- | --- | --- |
| `comfyui_user_guide` | 返回完整使用指南（`server/user-guide.md`：MCP 工具 + REST WebAPI 全貌、认证、轮询约定、错误码排障） | 读 |
| `comfyui_status` | 各实例连接/队列状态 | 读 |
| `comfyui_list_workflows` | 列出工作流 + .md 摘要 | 读 |
| `comfyui_describe_workflow(name, instance?)` | 解析输入参数/输出节点/拓扑 + `health`（executable / nodes_missing 缺自定义节点 / models_missing 缺模型文件；实例不可达时降级 `checked: false`，本地解析照常）+ `routing`（P5.13：recommended_instance=符合要求∩排队最少 + candidates 明细 + reason + as_of；全不可达→null）+ `stats`（本进程内存成败统计：success_rate + 最近 5 类失败去重合并，调用前避坑用；重启清零） | 读 |
| `comfyui_submit_task(instance, ...)` | 唯一执行入口：提交工作流执行，立即返回 task_id（**`instance` 必填**，取 describe 的 `routing.recommended_instance`；点名实例不匹配其 `workflow_rules` 立即硬拒；可选 `timeout_s`，默认 3600，含排队等待） | 写 |
| `comfyui_task_status(task_id)` | 轮询节点级进度（建议 10–30s 间隔；completed 后返回含 outputs 本地文件路径） | 读 |
| `comfyui_cancel_task(task_id)` | 取消（pending 取消 job / running 走 /interrupt） | 写 |
| `comfyui_upload_file(instance, ...)` | 上传文件（**`instance` 必填**，与 submit 同一实例；`file_path` 或 `file_b64`；base64 支持 data-URI，音频/视频建议配 `filename`；返回 name 供工作流媒体参数引用） | 写 |

执行统一为"提交 → task_id → 轮询"：`comfyui_submit_task` 的 `workflow_name`（workflows/ 下的名称）与 `prompt_json`（内联 JSON）二选一，`params` 注入输入参数，如：

```json
// instance 先取 comfyui_describe_workflow 的 routing.recommended_instance
{ "name": "comfyui_submit_task",
  "arguments": { "instance": "newgoai",
                  "workflow_name": "hello",
                  "params": { "INPUT_POSITIVE_TEXT": "一只戴帽子的橘猫",
                              "ckpt_name": "SDXL/epicrealismXL_vxviiCrystalclear.safetensors" } } }
// 立即返回 { "task_id": "abc123...", "hint": "..." }
// 轮询 comfyui_task_status（建议 10–30s 间隔）直至 status=completed
```

媒体输入工作流走"先上传、后按文件名调用"两步（上传与执行须**同一 instance**，同取 routing 推荐值）：

```json
{ "name": "comfyui_upload_file",
  "arguments": { "instance": "newgoai", "file_path": "D:\\素材\\ref.png" } }
// 返回 { "name": "17480000000000_ref.png" }（落入该实例 ComfyUI 的 input/ 目录）

{ "name": "comfyui_submit_task",
  "arguments": { "instance": "newgoai", "workflow_name": "qwen_image_edit_1",
                  "params": { "INPUT_IMAGE_1_FILE": "17480000000000_ref.png",
                              "INPUT_PROMPT_VALUE": "图1的人物摆出胜利姿势" } } }
// 轮询 comfyui_task_status 直至 completed，outputs 即产物
```

任务完成后 `comfyui_task_status` 返回的 `outputs` 为本地文件绝对路径（`output/` 下，带实例名+工作流前缀），MCP 客户端可直接读文件，不返回 base64 大字符串。终态任务保留 24h/最多 200 条，被裁剪后产物仍在 `output/`（7 天保留期），可经 `/files` 下载。

## REST 调用

```bash
# 状态（$tok 换成你的 command_token 或 query_token）
curl -H "Authorization: Bearer $tok" "http://127.0.0.1:18800/api/status"

# 执行（唯一入口：提交拿 task_id，再轮询 /api/tasks/{id}；instance 必填——
# 取 GET /api/workflows/{name} 的 routing.recommended_instance）
curl -X POST "http://127.0.0.1:18800/api/tasks" \
  -H "Authorization: Bearer $tok" -H "Content-Type: application/json" \
  -d '{"instance":"newgoai","workflow_name":"hello","params":{"INPUT_POSITIVE_TEXT":"test"}}'
# 缺 instance 或空 → 400（P5.13）
# 返回 {"task_id":"abc123..."}，轮询：
curl -H "Authorization: Bearer $tok" "http://127.0.0.1:18800/api/tasks/abc123..."

# 下载产物（/files/ 对应 output/ 目录）
curl -H "Authorization: Bearer $tok" -o out.png "http://127.0.0.1:18800/files/newgoai_hello_xxxx_00_ComfyUI_00001_.png"
```

> Windows 下把反斜杠续行 `\` 改为 `` ` `` 并去掉 `#!/` 之外的差异即可，或直接用 PowerShell `Invoke-RestMethod`。

## 相关文档

- `server/user-guide.md` — 使用指南（MCP + REST 全貌；MCP 工具 `comfyui_user_guide` 可在线获取）
- `AGENTS.md` — 智能体项目指南
- `PowerShell_Fix.md` — 智能体调用 PowerShell 避坑
