@echo off
chcp 65001 >nul

echo ========================================
echo    NovelFlow 后端服务停止脚本
echo ========================================
echo.

:: 查找并停止 uvicorn 进程
echo 正在查找 NovelFlow 后端服务...

:: 方式1：查找端口 8000 的进程
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo        发现进程 PID: %%a，正在终止...
    taskkill /F /PID %%a 2>nul
    if !errorlevel! == 0 (
        set FOUND=1
        echo        [OK] 进程已终止
    )
)

:: 方式2：查找 uvicorn 进程名
taskkill /F /IM "uvicorn.exe" 2>nul
if %errorlevel% == 0 (
    set FOUND=1
    echo        [OK] uvicorn.exe 已终止
)

:: 方式3：查找 python 进程中包含 app.main 的
for /f "tokens=2" %%a in ('tasklist ^| findstr python') do (
    taskkill /F /PID %%a 2>nul
)

if %FOUND% == 1 (
    echo.
    echo [OK] 服务已成功停止
) else (
    echo.
    echo [提示] 未发现运行中的服务
)

echo.
pause
