@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   A-Share Quant Demo Launcher
echo ============================================
echo.

REM 自动探测解释器：优先 py 启动器（Windows 官方安装自带），其次 python。
REM 刻意不写死本机绝对路径 —— 否则别人 clone 后双击必然失败。
set PYTHON=
where py >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=py -3
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PYTHON=python
    )
)

if "%PYTHON%"=="" (
    echo [ERROR] 未找到 Python 解释器。
    echo         请安装 Python 3.9-3.13，安装时勾选 "Add Python to PATH"。
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 检查依赖（首次运行需联网）...
%PYTHON% -m pip install -q -r requirements.txt
echo.
echo [2/3] 预热本地缓存（首次运行需联网；已缓存则秒过）...
%PYTHON% warm_cache.py
echo.
echo [3/3] 启动 Streamlit...
echo     浏览器若未自动打开，请手动访问 http://localhost:8501
echo.
%PYTHON% -m streamlit run app.py

pause
