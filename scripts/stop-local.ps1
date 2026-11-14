# 停止 ComicFlow 本地体验环境（保留数据卷）
# 用法:  powershell -ExecutionPolicy Bypass -File scripts/stop-local.ps1
#        （双击入口见 scripts/stop-all.bat）
#
# 同 start-local.ps1：必须存为 UTF-8 带 BOM，否则 PowerShell 5.1 会错解中文字节。
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
# 停前端 dev（占 5173 的 node/vite 进程）
Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*vite*5173*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
# 停后端容器（数据在卷中保留，下次 start-local 可继续）
docker compose stop
Write-Host '已停止。再次启动: powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1'
