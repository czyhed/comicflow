@echo off
REM ComicFlow 停止全部 - 双击入口，实际逻辑在 stop-local.ps1

pushd "%~dp0.."
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
    pwsh -ExecutionPolicy Bypass -File "scripts\stop-local.ps1"
) else (
    powershell -ExecutionPolicy Bypass -File "scripts\stop-local.ps1"
)
popd
pause
