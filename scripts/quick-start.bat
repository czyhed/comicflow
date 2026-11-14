@echo off
REM ComicFlow 快速启动 - 双击入口，实际逻辑在 start-local.ps1
REM
REM 只做一件事：调用 start-local.ps1，启动 Docker 真实栈（API 在宿主 18000）
REM 加前端 dev（代理到 18000）。
REM
REM 不要在这里改成 `uv run uvicorn ... --port 8000`：本机 8000 上的进程默认
REM 全 Mock Provider，会静默产出假资产，看起来"跑通了"其实什么都没生成。
REM 真实栈的 Provider 开关由 .env 决定（PROVIDER_MODE / VISUAL_PROVIDER_MODE 等）。

pushd "%~dp0.."
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
    pwsh -ExecutionPolicy Bypass -File "scripts\start-local.ps1"
) else (
    powershell -ExecutionPolicy Bypass -File "scripts\start-local.ps1"
)
popd
pause
