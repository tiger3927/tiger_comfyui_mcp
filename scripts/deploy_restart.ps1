# deploy_restart.ps1：同步 + 对账 + 重启服务（先停 → 对账 → 启，防丢账/孤儿 freeze）。
#
# 用法：
#   powershell -File scripts\deploy_restart.ps1
#   powershell -File scripts\deploy_restart.ps1 -Service tiger_comfyui_mcp -RemoteBase /data/tiger/tiger_comfyui_mcp
#
# 说明：服务名/启动方式按服务器实际部署调整（conda base 环境跑 main.py）。
# 若用 systemd：把 -Service 设成 unit 名；若是 nohup 手起，设 -NoService 走进程模式。
param(
  [string]$Remote = "root@119.84.39.2",
  [string]$RemotePort = "20022",
  [string]$RemoteBase = "/data/tiger/tiger_comfyui_mcp",
  [string]$Service = "tiger_comfyui_mcp",
  [switch]$NoService
)

$ErrorActionPreference = "Stop"

# 1) 增量同步
& (Join-Path $PSScriptRoot "sync_server.ps1") -Remote $Remote -RemotePort $RemotePort `
  -RemoteBase $RemoteBase

if ($NoService) {
  # 进程模式：kill 旧进程 → 对账 → 重新 nohup 起
  ssh -p $RemotePort $Remote "pkill -f 'python.*main.py' 2>/dev/null; sleep 1"
  ssh -p $RemotePort $Remote "cd $RemoteBase && python scripts/reconcile.py --apply --config config.json"
  ssh -p $RemotePort $Remote "cd $RemoteBase && nohup python main.py >> log/server.out 2>&1 &"
  Write-Host "部署完成（进程模式）：$Remote:$RemoteBase"
} else {
  # systemd 模式
  ssh -p $RemotePort $Remote "systemctl stop $Service 2>/dev/null || true"
  ssh -p $RemotePort $Remote "cd $RemoteBase && python scripts/reconcile.py --apply --config config.json"
  ssh -p $RemotePort $Remote "systemctl start $Service && systemctl status $Service --no-pager"
  Write-Host "部署完成（systemd: $Service）@ $Remote"
}
