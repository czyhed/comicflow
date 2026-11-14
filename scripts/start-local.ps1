# 启动 ComicFlow 本地体验环境（Docker 后端 + 前端 dev）
# 用法:  powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
#        （有 PowerShell 7 时也可用 pwsh；双击入口见 scripts/quick-start.bat）
#
# 本文件必须存为 UTF-8 **带 BOM**：Windows PowerShell 5.1 会把无 BOM 的 UTF-8
# 按 ANSI 读，中文注释的字节被错解后 { } 配对错乱，整个脚本报 MissingEndCurlyBrace。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1) 确保 Docker Desktop 引擎可用
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $exe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
  if (Test-Path $exe) { Start-Process $exe; Write-Host '正在启动 Docker Desktop…' }
  $deadline = (Get-Date).AddMinutes(5)
  do { Start-Sleep -Seconds 5; docker info *> $null } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
  if ($LASTEXITCODE -ne 0) { throw 'Docker 引擎未能就绪，请手动打开 Docker Desktop' }
}

# 2) 启动后端容器（postgres/redis/minio/api/worker/beat；数据在卷中保留）
docker compose up -d
$deadline = (Get-Date).AddMinutes(3)
do {
  Start-Sleep -Seconds 3
  try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:18001/health -TimeoutSec 3).StatusCode -eq 200 } catch { $ok = $false }
} while (-not $ok -and (Get-Date) -lt $deadline)
if (-not $ok) { throw 'API 未就绪，请看 docker compose ps' }
Write-Host '后端 API 就绪: http://127.0.0.1:18001/health'

# 3) 启动前端 dev（代理到 18000）
Push-Location (Join-Path $root 'frontend')
if (-not (Test-Path '.env.local')) {
  Set-Content -Path '.env.local' -Value 'VITE_API_PROXY_TARGET=http://127.0.0.1:18000'
}
$proc = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*vite*5173*' }
if (-not $proc) {
  Start-Process -FilePath (Join-Path $root 'frontend\node_modules\.bin\vite.cmd') `
    -ArgumentList '--host','127.0.0.1','--port','5173','--strictPort' `
    -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden
}
Pop-Location

$deadline = (Get-Date).AddSeconds(30)
do {
  Start-Sleep -Milliseconds 800
  try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:5173/ -TimeoutSec 2).StatusCode -eq 200 } catch { $ok = $false }
} while (-not $ok -and (Get-Date) -lt $deadline)
if ($ok) { Write-Host '前端就绪: http://127.0.0.1:5173 （浏览器打开体验）' }
else { Write-Host '前端未响应，请在 frontend 目录手动运行:  .\node_modules\.bin\vite --host 127.0.0.1 --port 5173' }
