# tiger-comfyui-mcp 使用指南（MCP 调用者）

面向 MCP 客户端（LLM agent / 程序）的完整使用手册。本指南也可通过 MCP 工具
`comfyui_user_guide` 获取（内容同源）。

## 1. 服务全貌

单进程单端口双入口，同一个 `ComfyUIManager` 核心：

| 入口 | 路径 | 用途 |
|---|---|---|
| MCP（Streamable HTTP，stateless） | `http://<host>:<port>/mcp/` | LLM/agent 工具调用（**默认入口，本指南主体**） |
| REST WebAPI | `http://<host>:<port>/api/*` | **只留给有特殊用途的用户编程使用**（curl/脚本/前端集成），普通调用方（尤其 LLM agent）一律走 MCP |
| 产物下载 | `http://<host>:<port>/files/*` | 下载 `output/` 目录产物（**免认证**；文件名含随机任务前缀，实际不可猜测） |
| 服务根 | `http://<host>:<port>/` | 返回端点清单（无认证） |

后端代理一个或多个 ComfyUI 实例（config 的 `comfyui_instances`，可配
`workflow_rules` 工作流匹配规则）。**工作流对外可用性由顶层 `allowed_workflows`
全局白名单控制（fail-closed：为空/缺省 = 全不放行，`workflows/` 目录有文件 ≠
可用）**，list/describe/submit 均受其门控（§3.5）。**`comfyui_submit_task`
与 `comfyui_upload_file`
的 `instance` 参数必填**——先调 `comfyui_describe_workflow` 取
`routing.recommended_instance`（符合要求 ∩ 排队最少），upload/submit 串同一个实例
（媒体文件实例局部，实例间不通用）；`describe_workflow` 的 `instance` 可选
（定向 health 检查，缺省 = config 的 `default_instance`）。

## 2. 认证（两入口同一套 Bearer token）

| token | 权限 |
|---|---|
| `command_token` | 全权限（读 + 执行类：submit/cancel/upload） |
| `query_token` | 只读（执行类工具/REST 写路径一律 403） |

- 请求头：`Authorization: Bearer <token>`（MCP 与 REST 通用）。
- 两个 token 都没配 → 无认证模式（仅允许本机调试）。
- `/files/*` **不参与 Bearer 认证**（P5.20）：产物匿名可下载，安全边界是随机
  文件名（实例名+工作流+任务前缀，不可猜测）；`/mcp/` 与 `/api/*` 仍需 token。
- MCP 另有 **Host 白名单**（`server.mcp_allowed_hosts`）：非白名单地址连 `/mcp/`
  直接 421（DNS rebinding 防护）；公网访问需管理员把 `<IP>:*` 加入白名单。

## 3. MCP 工具（8 个）

| 工具 | 说明 | 读/写 |
|---|---|---|
| `comfyui_user_guide` | 返回本指南（Markdown） | 读 |
| `comfyui_status` | 各实例连接/登录状态、队列负载、GPU 显存 | 读 |
| `comfyui_list_workflows` | 列出**白名单内**（config `allowed_workflows`）可用工作流 + .md 摘要 + 每项 `instances`（实例规则放行的实例名，可直接据此选实例） | 读 |
| `comfyui_describe_workflow(name, instance?)` | 工作流输入参数/输出节点/拓扑 + `health`（executable/缺节点/缺模型）+ **`routing`（推荐实例 = 符合要求 ∩ 排队最少，见 §3.5）** + `stats`（本进程成败统计，调用前避坑） | 读 |
| `comfyui_submit_task(instance, ...)` | **唯一执行入口**：提交工作流，立即返回 `task_id`；**`instance` 必填**（取 describe 的 `routing.recommended_instance`；点名实例不匹配其规则→立即硬拒）；可选 `timeout_s`，默认 3600，含排队 | 写 |
| `comfyui_task_status(task_id)` | 节点级进度轮询；completed 后返回 `outputs`（本服务机上的产物绝对路径）+ **`outputs_urls`（产物公网下载直链，GET 即下、免认证）** 与 `text_outputs` | 读 |
| `comfyui_cancel_task(task_id)` | 取消：排队中=删远端队列，执行中=精准 `/interrupt`（不误伤共享实例他人任务） | 写 |
| `comfyui_upload_file(instance, ...)` | 上传素材到 ComfyUI，返回 `name`（供工作流媒体参数引用）；**`instance` 必填，且必须与 submit 同一实例** | 写 |

### 3.1 标准调用流程

```
comfyui_status                      # 确认实例 connected
comfyui_list_workflows              # 找可用工作流
comfyui_describe_workflow(name)     # 看 inputs 参数定义 + health 是否 executable
                                    # + 取 routing.recommended_instance（见 3.5）
comfyui_upload_file(instance, ...)  # 仅媒体输入工作流需要（见 3.2；instance=推荐值）
comfyui_submit_task(instance, workflow_name, params)  → task_id
comfyui_task_status(task_id)        # 按 3.3 的间隔轮询至 status=completed
                                    # completed：outputs_urls = 产物公网下载直链
                                    # （GET 即下载、免认证；见 3.4）
```

- `submit_task` 的 `instance` **必填**：用上面 describe 返回的
  `routing.recommended_instance`（或 candidates 中你确认的实例）；
  `upload_file` 的 `instance` 与其**同值**（媒体文件实例局部）。
- `submit_task` 的 `workflow_name`（workflows/ 下名称，不含 .json）与
  `prompt_json`（内联 API 格式 JSON 字符串）二选一；`params` 注入输入参数。
- 参数名以 `describe_workflow` 返回的 `inputs[].title` 为准（如
  `INPUT_SPEAK_TEXT`、`INPUT_IMAGE_FILE`、`seed`）。

### 3.2 媒体输入约定（重要）

全部工作流的媒体参数都是**文件名**（`INPUT_*_FILE`：图片/音频/视频），
不存在 base64/URL 媒体输入：

```
comfyui_upload_file(file_path=...)   # 或服务机上的素材
  → { "name": "xxx.png", "type": "input" }
comfyui_submit_task(params={"INPUT_IMAGE_FILE": "xxx.png", ...})
```

- **上传与执行必须同一实例**（`name` 是 ComfyUI 端的文件名，实例间不通用）。
- 文件在**本服务机**上：直接 `file_path`（最省心，后缀原样保留）。
- 文件在**客户端机器**（跨机器部署）：`file_b64`（裸 base64 或 data-URI；
  音频/视频建议配 `filename` 指明后缀）；
  注意 MCP 请求体 4MiB 上限 → b64 通道约限 **3MB 以内**原文件，
  大文件建议 scp/共享盘先搬上服务机再走 `file_path`。

### 3.3 轮询间隔约定（写进 submit_task 返回 hint）

| 任务类型 | 建议间隔 |
|---|---|
| 图片 / 语音生成类 | 10s |
| 视频生成类 | 20s |
| 视频类且多次轮询仍在排队（PENDING） | 扩展到 30s |

`task_status` 是即时状态读取（服务端 WS 实时维护），无长轮询——
间隔纯由调用方决定，更密费 LLM 轮次、更疏显得慢。

任务状态机：`PENDING`（已提交/排队）→ `RUNNING`（开始执行，
`progress_nodes` 给出已完成节点）→ 终态 `completed` / `FAILED` / `cancelled`。
`error` 字段带失败原因；`timeout_s` 超时后按状态停止并记 FAILED。

### 3.4 产物获取

- `task_status` completed 时返回两组路径：
  - `outputs`：**本服务机**上 `output/` 的绝对路径（带实例名+工作流+任务前缀，
    如 `mifengzhaopu_vibevoice_tts_clone_8f47e257_01_vibevoice_00001.mp3`）；
    MCP 客户端与服务机同机时可直接读；
  - **`outputs_urls`：产物公网下载直链**（`http://<host>:<port>/files/<文件名>`，
    GET 即下载、免认证）——**跨机器调用者一律用这些链接取产物**
    （浏览器/curl/程序请求均可，无需 scp、无需 token）。
- 服务未配置 `server.public_base_url` 时不返回 `outputs_urls`（此时自行用
  你连接服务的 `host:port` 拼 `/files/<outputs 里的文件名>`，同样免认证）。
- 任务表保留 24h / 最多 200 条（终态裁剪）；`output/` 文件保留 7 天。
  被裁剪的任务无法再经 task_status 取链接，但已取得的 `/files` 链接在
  产物保留期内仍有效。

### 3.5 路由语义（多实例：选哪个、为什么、怎么拒）

`describe_workflow` 的 `routing` 块是**选实例的唯一依据**（服务端不自动路由，
submit/upload 的 `instance` 必填）：

- **`recommended_instance`** = 符合要求且排队最少：
  - 符合要求 = 该实例 config 的 `workflow_rules` 放行 ∩ 实例可达；
  - 排队最少 = 各候选实例 `score = pending×1.0 + running×2.0`（config
    `routing.weights` 可配，执行中任务权重大于排队）取最低分；
  - 平局 → config 的 `default_instance`；
  - 全不可达/全被规则排除 → `recommended_instance: null` + `reason`
    （本地解析照常，但此时没有可提交目标）。
- **`candidates[]`** 每个实例一条：`supported`（规则放行）/ `excluded_reason`
  （被排除原因：规则 or 不可达）/ `queued` / `running` / `health`（参考）/
  `score`（参与打分才有值）/ `as_of`（探测时间）。
- **`allowed_workflows` 全局白名单（config 顶层，P5.19；管理员配置）**：
  服务对外暴露哪些工作流的**总闸**——`list_workflows` 只返回白名单内的
  （每项附 `instances` 标注），`describe_workflow` / `submit_task` 点名白名单
  外 → **立即报错**（"未通过全局白名单"，不建任务）。**fail-closed：为空/
  缺省 = 全不放行**（与实例规则相反：实例 rules 缺省 = 全支持）。条目支持
  通配符 `* ? [seq]`（大小写敏感，与实例规则一致）。
- **`workflow_rules` 表达（config 侧，管理员配置；实例级）**：
  - `only: [...]`（只能）：白名单，非空时不命中 = 该实例不支持；
  - `exclude: [...]`（排除）：黑名单，命中 = 不支持；
  - 条目支持通配符 `* ? [seq]`（对工作流名，不含 .json，大小写敏感，
    如 `qwen_image_edit_*`）；**评估顺序固定 exclude → only → 都空 = 全支持**。
  两层语义：全局白名单 = 暴露面（目录有 ≠ 可用）；实例规则 = 硬件能力。
- **硬拒**：`submit_task` 的工作流不在全局白名单、或点名的 `instance` 不匹配
  其 `workflow_rules` 时均**立即报错**（"未通过全局白名单：…" /
  "实例 X 不支持工作流 Y：…"），不排队、不建任务；
  `prompt_json` 内联执行无工作流名，不受白名单与实例规则限制（硬件匹配
  调用方负责）。
- **health 是参考不是门**：`candidates[].health`（缺节点/缺模型）只提示
  "去了可能跑不动"，不影响 `recommended_instance`（门要是动态的，推荐就
  不可预测）；点名执行前可先 `describe_workflow(name, instance=点名值)`
  看定向 health。

## 4. REST WebAPI（程序化调用，端点一览）

> **定位**：REST 调用**只留给有特殊用途的用户编程使用**（需要非 MCP 集成、
> 自有服务间调用、批量脚本等场景）。普通调用方——尤其是 LLM agent——
> **一律使用 MCP 工具**（§3），功能等价且语义更完整（health/stats/指南/
> 错误提示）。本节仅为有特殊用途的编程用户提供端点参考。

Base = `http://<host>:<port>`，认证同 §2（MCP 与 REST 同一套 Bearer；
`/files/*` 例外：免认证）。

| 方法 | 路径 | 对应 MCP 工具 | 说明 |
|---|---|---|---|
| GET | `/api/status` | `comfyui_status` | 各实例状态 |
| GET | `/api/workflows` | `comfyui_list_workflows` | **白名单内**工作流列表 + 摘要 + `instances` 标注（同 MCP） |
| GET | `/api/workflows/{name}?instance=` | `comfyui_describe_workflow` | 参数解析 + health + **routing（同 MCP）** + stats；白名单外 → 404 |
| POST | `/api/tasks` | `comfyui_submit_task` | **唯一执行入口**，202 返回 `{"task_id": ...}`；body：`{workflow_name?, prompt_json?, params?, instance（必填）, timeout_s?}`；缺/空 instance、不在全局白名单或实例规则不匹配 → 400 |
| GET | `/api/tasks/{task_id}` | `comfyui_task_status` | 任务进度（字段与 MCP 相同） |
| POST | `/api/tasks/{task_id}/cancel` | `comfyui_cancel_task` | 取消 |
| POST | `/api/upload?file_type=&instance=` | `comfyui_upload_file` | multipart 上传（`file` 字段），返回 `name`；**`instance` 查询参数必填**（缺 → 400） |
| GET | `/files/{path}` | —（MCP 无对应工具；`task_status` 返回的 `outputs_urls` 即指向本端点的直链） | 下载 `output/` 产物（含路径穿越防护，**免认证**） |

### curl 示例

```bash
TOK=<command_token>
BASE=http://119.84.39.2:18503

# 实例状态
curl -H "Authorization: Bearer $TOK" $BASE/api/status

# 工作流参数定义（含 routing 推荐实例）
curl -H "Authorization: Bearer $TOK" "$BASE/api/workflows/qwen3_tts_clone"

# 提交执行（唯一入口；instance 必填——取上面 routing.recommended_instance）
curl -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"instance":"newgoai",
       "workflow_name":"qwen3_tts_clone",
       "params":{"INPUT_SPEAK_TEXT":"你好","INPUT_AUDIO_FILE":"ref.mp3"}}' \
  $BASE/api/tasks                       # → 202 {"task_id":"..."}

# 轮询进度
curl -H "Authorization: Bearer $TOK" $BASE/api/tasks/<task_id>

# 取消
curl -X POST -H "Authorization: Bearer $TOK" $BASE/api/tasks/<task_id>/cancel

# 上传素材（multipart；instance 必填，与 submit 同一实例）
curl -H "Authorization: Bearer $TOK" -F "file=@ref.png" \
  "$BASE/api/upload?file_type=input&instance=newgoai"    # → {"name":"...png"}

# 下载产物（免认证；文件名来自 task_status 的 outputs / outputs_urls）
curl -o out.mp3 \
  "$BASE/files/mifengzhaopu_vibevoice_tts_clone_8f47e257_01_vibevoice_00001.mp3"
```

## 5. 错误码与排障

| 现象 | 原因 / 处理 |
|---|---|
| `421`（连 `/mcp/`） | Host 不在白名单 → 让管理员把 `<IP>:*` 加入 `server.mcp_allowed_hosts` 并重启服务 |
| `401` | token 缺失/错误；或无认证模式下被禁用路径（正常部署不应出现） |
| `403` | 用了 `query_token` 调执行类工具/写路径 → 换 `command_token` |
| `404 任务不存在` | task_id 写错，或任务表已被 24h/200 条裁剪（产物仍可经 `/files` 拿） |
| `400 必须提供 workflow_name 或 prompt_json` | submit 两个工作流来源都没给 |
| `未通过全局白名单`（submit/describe 报错，REST 为 400/404） | 工作流不在 config 顶层 `allowed_workflows`（**为空/缺省 = 全不放行**）→ 管理员把工作流名加入白名单并重启服务 |
| `400 / 报错 "instance 必填"` | submit/upload 没给 instance（或给了空串）→ 先 `describe_workflow` 取 `routing.recommended_instance` |
| `400 / 报错 "实例 X 不支持工作流 Y"` | 点名的 instance 不匹配其 `workflow_rules`（规则硬拒，零成本）→ 换 `routing.candidates` 中 `supported=true` 的实例 |
| `routing.recommended_instance: null` | 全实例不可达或被规则排除 → 看 `candidates[].excluded_reason`；实例侧修网络/登录或找管理员调 `workflow_rules` |
| 任务 `FAILED` + error | 看 error 文本：常见为缺节点（describe 的 health.nodes_missing）、缺模型（models_missing）、远端执行报错 |
| `comfyui_status` 实例 `connected: false` | ComfyUI 端不可达/登录失败 → 查实例 url/password 与网络 |
| 提交即返回但一直 PENDING | 远端排队中（共享实例他人任务多）→ 按 §3.3 延长轮询间隔；不要重复 submit |

## 6. 调用纪律（LLM agent 必读）

1. 动手前先 `describe_workflow` 看 `inputs`、`health.executable` 与
   `routing.recommended_instance`，不要猜参数名、不要猜实例。
2. 一个任务只 submit 一次；后续用 task_status 跟踪，需要放弃才 cancel。
3. `upload_file` / `submit_task` 的 `instance` **必填且同值**（= recommended_instance；
   媒体输入先 upload 再注入 `name`，不要把 base64 塞进 params）；点名换实例前先
   看 `routing.candidates` 的 `supported` / `health`。
4. 轮询间隔按 §3.3；不要在同一轮对话里连发多次 task_status。
5. 大文件（>3MB）跨机器传输优先 scp/共享盘，不走 b64 参数。
6. 白名单内工作流清单与中文摘要：`comfyui_list_workflows`（每个工作流另有 .md 文档；清单外的工作流一律不可提交——目录有文件 ≠ 可用）。
