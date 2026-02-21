@echo off
chcp 65001 >nul

:: NovelFlow 后端启动脚本 (Windows)

echo ========================================
echo    NovelFlow 后端服务启动脚本
echo ========================================
echo.

:: 获取脚本所在目录
cd /d "%~dp0"

:: 停止已有的 uvicorn 进程
echo [1/4] 正在停止已有的服务...
taskkill /F /FI "WINDOWTITLE eq uvicorn*" 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
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

:: 启动服务
echo [3/4] 启动 NovelFlow 后端服务...
echo        服务将在 http://localhost:8000 运行
echo.

:: 方式1：前台运行（推荐开发使用，可以看到实时日志）
echo ========================================
echo  服务启动中... 按 Ctrl+C 停止服务
echo ========================================
echo.

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

:: 如果需要后台运行并输出到日志文件，请使用下面的代码替换上面的命令：
:: start /B python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1
:: timeout /t 3 /nobreak >nul
:: echo [4/4] 检查服务状态...
:: curl -s http://localhost:8000/api/health/ >nul 2>&1
:: if %errorlevel% == 0 (
::     echo        [OK] 服务启动成功！
::     echo        健康检查: http://localhost:8000/api/health/
::     echo        日志文件: %CD%\backend.log
:: ) else (
::     echo        [警告] 服务可能未完全启动，请检查日志: %CD%\backend.log
:: )

echo.
echo 服务已停止
pause
