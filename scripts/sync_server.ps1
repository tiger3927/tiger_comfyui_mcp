# sync_server.ps1：把门户相关改动增量 scp 到部署服务器（本机 Windows 中转）。
# 约束（记忆）：服务器之间不互连，跨机搬运一律经本机；这里只做 本机 → 大牛。
#
# 用法：
#   powershell -File scripts\sync_server.ps1
#   powershell -File scripts\sync_server.ps1 -RemoteBase /data/tiger/tiger_comfyui_mcp
param(
  [string]$Remote = "root@119.84.39.2",
  [string]$RemotePort = "20022",
  [string]$RemoteBase = "/data/tiger/tiger_comfyui_mcp",
  [string]$LocalBase = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

# 门户 + 被改动的 core/server 文件（相对项目根）
$files = @(
  "main.py",
  "portal\__init__.py", "portal\app.py", "portal\sync.py", "portal\db.py",
  "portal\accounts.py", "portal\billing.py", "portal\config.py",
  "portal\security.py", "portal\errors.py",
  "portal\routers\__init__.py", "portal\routers\auth.py", "portal\routers\me.py",
  "portal\routers\tokens.py", "portal\routers\tasks.py",
  "portal\routers\recharges.py", "portal\routers\pay.py", "portal\routers\admin.py",
  "core\tasks.py", "core\manager.py",
  "core\tickets.py",
  "server\rest_api.py", "server\mcp_tools.py", "server\user-guide.md",
  "scripts\reconcile.py", "scripts\seed_admin.py",
  "config.example.json", ".gitignore"
)

foreach ($f in $files) {
  $local = Join-Path $LocalBase $f
  if (-not (Test-Path $local)) { Write-Warning "缺失本地文件 $f，跳过"; continue }
  $remote = "$RemoteBase/$($f -replace '\\','/')"
  $remoteDir = Split-Path $remote -Parent
  ssh -p $RemotePort $Remote "mkdir -p '$remoteDir'" | Out-Null
  Write-Host "scp $f → $Remote:$remote"
  scp -P $RemotePort $local "$Remote:$remote"
}

# workflows 整目录（*.md 摘要 + *.json 工作流）
$localWf = Join-Path $LocalBase "workflows"
if (Test-Path $localWf) {
  Write-Host "scp workflows\ → $Remote:$RemoteBase/workflows（整目录）"
  scp -P $RemotePort -r $localWf "$Remote:$RemoteBase/"
} else {
  Write-Warning "本地 workflows 目录缺失，跳过"
}

Write-Host ""
Write-Host "同步完成 → $Remote:$RemoteBase（共 $($files.Count) 个文件）"
