# ComfyUI 工作流API调用规则

## 同步接口

### 地址与参数

- post:/api/v1/comfyui_run
- 入参例子

```json
{
  "token": "comfyui",  //必须
  "workflow_name": "工作流的名称 不含json后缀名", //必须 具体工作流名称不同
  "params": {   //参数区
    "INPUT_PROMPT_TEXT": "输入的提示词文本",
    "INPUT_NEGATIVE_PROMPT_TEXT": "输入的负向提示词文本"
  }
}
```

### 调用方法

- 调用后会等待一段时间，具体等待时间见工作流介绍！
- 返回值

```json
{
  "workflow_id": null,   // null 或者 任意
  "status": "success",
  "result": {   //会有多个文件，其中只有必要的文件是需要的，具体见后续工作流描述
    "images_0": "comfyui-hello_00002_.png"  //可以下载的文件
  }
}
```

- 如果调用失败，等10秒钟再去调用
- 文件下载地址
  GET
  https://ai4.newgoai.com/api/v1/comfyui_download/[filename]

## 异步（任务式）接口

### 概述

ComfyUI 异步任务接口提供了一种非阻塞的方式来执行 AI 生成任务。与同步接口不同，异步接口在提交任务后立即返回任务ID，客户端可以通过任务ID查询任务进度和结果，避免了长时间等待导致的超时问题。

**服务地址**: `https://ai4.newgoai.com`

**基础路径**: `/api/v1`

---

### 接口列表

#### 1. 提交任务

**接口**: `POST /comfyui_task/submit`

**功能**: 提交 ComfyUI 工作流任务，立即返回任务ID

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| workflow_name | string | 否 | 工作流名称（不含.json后缀），如 "hello" |
| workflow_json | string | 否 | 工作流JSON字符串（与workflow_name二选一） |
| params | object | 否 | 工作流参数，用于替换工作流中的输入节点 |

**请求示例**:

```json
{
  "workflow_name": "hello",
  "params": {
    "INPUT_PROMPT_TEXT": "一只可爱的猫"
  }
}
```

**响应示例**:

```json
{
  "task_id": "d09c1b06-c8eb-4936-9cb5-7651f3edcd0b",
  "status": "pending",
  "message": "任务已提交，请通过 /comfyui_task/status/{task_id} 查询进度"
}
```

**注意事项**:
- `workflow_name` 和 `workflow_json` 必须提供其中一个
- 任务提交后会立即进入执行队列
- 任务数据存储在 Redis 中，2小时后自动过期

---

#### 2. 查询任务状态

**接口**: `GET /comfyui_task/status/{task_id}`

**功能**: 查询任务的执行状态、进度和结果

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | string | 是 | 提交任务时返回的任务ID |

**响应示例**:

```json
{
  "task_id": "d09c1b06-c8eb-4936-9cb5-7651f3edcd0b",
  "status": "running",
  "current_node": "12",
  "prompt_id": "2e3a946c-3f78-4682-8379-c50733a3d0fd",
  "result": null,
  "error": null,
  "created_at": 1770705439.167708,
  "updated_at": 1770705439.4898257
}
```

**状态说明**:

| 状态 | 说明 |
|------|------|
| pending | 任务已提交，等待执行 |
| running | 任务正在执行中 |
| completed | 任务执行完成 |
| failed | 任务执行失败 |
| cancelled | 任务已取消 |

**响应字段说明**:

| 字段名 | 说明 |
|--------|------|
| status | 任务当前状态 |
| current_node | 当前正在执行的节点ID（仅在running状态时有值） |
| prompt_id | ComfyUI 内部任务ID |
| result | 执行结果，包含生成的文件列表（仅在completed状态时有值） |
| error | 错误信息（仅在failed状态时有值） |
| created_at | 任务创建时间戳 |
| updated_at | 最后更新时间戳 |

---

#### 3. 取消任务

**接口**: `POST /comfyui_task/cancel/{task_id}`

**功能**: 取消正在执行或等待中的任务

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | string | 是 | 提交任务时返回的任务ID |

**响应示例**:

```json
{
  "task_id": "d09c1b06-c8eb-4936-9cb5-7651f3edcd0b",
  "status": "cancelled",
  "message": "任务已取消"
}
```

**取消策略**:

| 任务状态 | 处理方式 | 说明 |
|----------|----------|------|
| pending | 从队列中删除 | 只删除自己的任务，不影响其他排队任务 |
| running | 发送中断指令 | 如果当前执行的是自己的任务则中断 |
| completed/failed/cancelled | 提示无需取消 | 任务已结束 |

**注意事项**:
- 取消操作是"尽力而为"，已生成的文件可能仍会保留
- 取消后建议查询一次状态确认

---

### 客户端调用流程

#### 标准流程

```
1. POST /comfyui_task/submit
   ↓ 立即返回 task_id
2. GET /comfyui_task/status/{task_id} (轮询)
   ↓ 每隔2-3秒查询一次
3. 直到 status = completed/failed/cancelled/timeout
   ↓ 获取结果
4. 如需下载文件，使用 /comfyui_download/{filename}
```

#### 状态判断逻辑

客户端通过 `status` 字段判断任务状态：

```python
def handle_task_status(data):
    status = data["status"]
    
    if status == "completed":
        # ✅ 任务完成，可以下载结果
        result = data["result"]  # 如: {"images_0": "xxx.png"}
        for key, filename in result.items():
            download_file(filename)
            
    elif status == "running":
        # ⏳ 任务执行中，继续等待
        current_node = data.get("current_node")
        print(f"正在执行节点: {current_node}")
        
    elif status == "pending":
        # ⏳ 排队等待中
        print("任务排队中...")
        
    elif status == "failed":
        # ❌ 执行失败
        error = data.get("error")
        print(f"任务失败: {error}")
        
    elif status == "cancelled":
        # 🚫 任务已取消
        print("任务已被取消")
```

#### 超时判断（客户端实现）

服务端不主动标记超时，客户端根据 `created_at` 时间戳自行判断：

```python
import time

def check_task_timeout(task_data, timeout_seconds=600):
    """
    判断任务是否超时
    参数:
        timeout_seconds: 超时阈值（秒），默认10分钟
    返回:
        (是否超时, 已执行秒数)
    """
    created_at = task_data.get("created_at")
    if not created_at:
        return False, 0
    
    elapsed = time.time() - created_at
    if elapsed > timeout_seconds:
        return True, elapsed
    return False, elapsed

# 完整轮询示例（含超时判断）
def wait_for_task(task_id, timeout_seconds=600):
    """等待任务完成，支持超时判断"""
    while True:
        # 查询状态
        response = requests.get(f"{BASE_URL}/api/v1/comfyui_task/status/{task_id}")
        data = response.json()
        status = data["status"]
        
        # 1. 检查是否已结束
        if status in ["completed", "failed", "cancelled"]:
            return data
        
        # 2. 检查是否超时（针对 pending 和 running 状态）
        is_timeout, elapsed = check_task_timeout(data, timeout_seconds)
        if is_timeout:
            print(f"任务已超时（{elapsed:.0f}秒），正在取消...")
            # 调用取消接口
            requests.post(f"{BASE_URL}/api/v1/comfyui_task/cancel/{task_id}")
            return {"status": "timeout", "elapsed": elapsed}
        
        # 3. 打印进度
        if status == "running":
            print(f"执行中... 节点: {data.get('current_node')}, 已耗时: {elapsed:.0f}秒")
        else:
            print(f"等待中... 已耗时: {elapsed:.0f}秒")
        
        # 4. 等待后继续查询
        time.sleep(3)
```

**超时建议**：
- 图片生成：建议 2-5 分钟
- 视频生成：建议 5-15 分钟（根据视频长度）
- 复杂工作流：建议 10-30 分钟

#### 状态流转图

```
                    ┌─────────────┐
                    │   pending   │
                    │   (排队中)   │
                    └──────┬──────┘
                           │ 开始执行
                           ▼
                    ┌─────────────┐     ┌─────────────┐
         ┌─────────│   running   │────▶│  cancelled  │
         │         │   (执行中)   │     │   (已取消)   │
         │         └──────┬──────┘     └─────────────┘
         │                │
         ▼                ▼
┌─────────────┐    ┌─────────────┐
│   failed    │    │  completed  │
│   (失败)     │    │   (已完成)   │
└─────────────┘    └──────┬──────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  下载结果文件  │
                   └─────────────┘
```

#### 示例代码 (Python)

```python
import requests
import time

BASE_URL = "https://ai4.newgoai.com"

# 1. 提交任务
response = requests.post(f"{BASE_URL}/api/v1/comfyui_task/submit", json={
    "workflow_name": "hello",
    "params": {}
})
task_id = response.json()["task_id"]
print(f"任务已提交: {task_id}")

# 2. 轮询查询状态
while True:
    time.sleep(3)
    status_resp = requests.get(f"{BASE_URL}/api/v1/comfyui_task/status/{task_id}")
    data = status_resp.json()
    
    print(f"状态: {data['status']}, 当前节点: {data.get('current_node')}")
    
    if data["status"] in ["completed", "failed", "cancelled"]:
        break

# 3. 获取结果
if data["status"] == "completed":
    result = data["result"]
    print(f"生成成功: {result}")
    # 下载文件: GET /api/v1/comfyui_download/{filename}
else:
    print(f"任务失败: {data.get('error')}")
```

---

### 与同步接口对比

| 特性 | 同步接口 (/comfyui_run) | 异步接口 (/comfyui_task) |
|------|------------------------|-------------------------|
| 响应时间 | 等待任务完成（可能数分钟） | 立即返回（<100ms） |
| 超时风险 | 高 | 无 |
| 进度查询 | 不支持 | 支持实时查询 |
| 任务取消 | 不支持 | 支持 |
| 适用场景 | 短时间任务（<30秒） | 长时间任务（视频生成等） |

---

### 注意事项

1. **任务过期**: 任务数据在 Redis 中保存2小时，过期后无法查询
2. **并发执行**: ComfyUI 是单线程执行，同一时间只有一个任务在运行
3. **文件下载**: 生成的文件保存在服务器 output 目录，通过 `/comfyui_download/{filename}` 下载
4. **错误处理**: 建议客户端实现重试机制，网络异常时可重新查询状态

---

### 相关接口

- **文件下载**: `GET /api/v1/comfyui_download/{filename}`
- **工作流文档**: `GET /api/v1/comfyui_docs`
- **同步执行**: `POST /api/v1/comfyui_run`

---



# 使用工作流的技巧

## 场景和对应用法

人物说话，可以文生图，图生图，再单图配音；

人物唱歌，可以用唱歌音频文件，再单图配音；

视频接力生成，可以用第一段视频的尾帧，作为图生视频的首帧，继续生成视频

## 常见参数的范围能力限制

一般只能一次性生成5到7秒的视频（整数秒数），帧数要在时间对应的帧数上加1，如果FPS为16，就5秒是81帧，7秒是113帧；

视频常见的格式是：宽544、高960，或者宽960，高544，避免过大，导致工作流显存爆炸。

ltx2.0/ltx2.3系列模型的工作流，视频可以是1280X720或者720X1280，稍微大一些。

图片一般不要超过1920和1080。

图片配音生成视频的长度控制在30秒内，否则计算时间过长。

## 对于wan2.2视频模型的提示词技巧

最好用英语写提示词，以下是一个有效的提示词案例：

```markdown
Beat 1 (0-1.0s): She sprints violently towards the camera, hair whipping backwards, and abruptly turns her head to glance over her shoulder in sheer panic.

Beat 2 (1.0-2.0s): She whips her head back forward, eyes widening further, pumping her arms harder; the silver shoes in her hand swing wildly.
Beat 3 (2.0-3.0s): She suddenly loses traction on the carpet, stumbling forward; her body dips low as she nearly falls, legs flailing to regain balance.
Beat 4 (3.0-4.0s): She desperately hikes up the red dress with her free hand to clear her legs, muscles tense, recovering her stride with a frantic gasp.
Beat 5 (4.0-5.0s): She lunges forward into a full desperate sprint, accelerating until her face fills the frame and blurs out of focus as she passes the camera.
Camera work: Fast backward dolly (tracking shot) moving ahead of the subject, with handheld camera shake to emphasize the chaos and urgency.
Acting should be emotional and realistic.
4K details, natural color, cinematic lighting and shadows, crisp textures, clean edges, fine material detail, high microcontrast, realistic shading, accurate tone mapping, smooth gradients, realistic highlights, detailed fabric and hair, sharp and natural.
```

## 对于图像生成和编辑模型的提示词技巧

最好用英语写提示词。

如果是图生图，多图生图，最好用VL模型能力来生成提示词。

# 工作流介绍

后续都是各个工作流的详细介绍。

工作流可能执行时间很长，所以最好用30分钟作为超时，一般不会这么久。

一级标题是工作流的名称！

工作流介绍中包含：

- 分类（用途和应用场景描述）。
- 介绍（使用的要点）
- 参数，参数不注明必填的，是可以省略有默认值的。
- 预计时间，是指调用后等待的时间，单位是分钟。
- 输出文件的前缀，是指需要下载的文件的前缀。

---
