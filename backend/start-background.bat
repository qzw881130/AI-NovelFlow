@echo off
chcp 65001 >nul

:: NovelFlow 后端后台启动脚本 (Windows)
:: 此脚本会在后台启动服务，输出到日志文件

echo ========================================
echo    NovelFlow 后端服务启动脚本 (后台模式)
echo ========================================
echo.

:: 获取脚本所在目录
cd /d "%~dp0"

:: 停止已有的 uvicorn 进程
echo [1/4] 正在停止已有的服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo        终止进程 PID: %%a
    taskkill /F /PID %%a 2>nul
)
timeout /t 2 /nobreak >nul

:: 激活虚拟环境
echo [2/4] 检查虚拟环境...
if exist "venv\Scripts\activate.bat" (
    echo        激活虚拟环境...
    call venv\Scripts\activate.bat
) else (
    echo [错误] 找不到虚拟环境 venv 目录
    pause
    exit /b 1
)

:: 启动服务（后台运行）
echo [3/4] 启动 NovelFlow 后端服务...
echo        服务将在 http://localhost:8000 运行
echo.

:: 创建日志文件
if exist "backend.log" (
    echo [%date% %time%] 服务重新启动 >> backend.log
) else (
    echo [%date% %time%] 服务首次启动 > backend.log
)

:: 使用 start 命令在新窗口中启动服务
start "NovelFlow Backend" cmd /c "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2^>^&1 ^| tee -a backend.log"

:: 等待服务启动
timeout /t 3 /nobreak >nul

:: 检查服务是否启动成功
echo [4/4] 检查服务状态...
curl -s http://localhost:8000/api/health/ >nul 2>&1
if %errorlevel% == 0 (
    echo        [OK] 服务启动成功！
    echo.
    echo ========================================
    echo  服务地址: http://localhost:8000
    echo  健康检查: http://localhost:8000/api/health/
    echo  日志文件: %CD%\backend.log
    echo ========================================
) else (
    echo        [警告] 服务可能未完全启动
    echo        请检查日志: %CD%\backend.log
)

echo.
echo 查看日志命令: type backend.log
echo 实时查看日志: tail -f backend.log  (需安装 Git Bash)
echo.
echo 停止服务: 关闭标题为 "NovelFlow Backend" 的窗口，或运行 stop.bat
pause
