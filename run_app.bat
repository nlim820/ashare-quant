@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   A-Share Quant Demo Launcher
echo ============================================
echo.
echo [1/2] Warming up local cache (internet needed on first run)...
"C:\Users\31652\AppData\Local\Programs\Python\Python314\python.exe" warm_cache.py
echo.
echo [2/2] Launching Streamlit...
echo If the browser does not open automatically, visit http://localhost:8501
"C:\Users\31652\AppData\Local\Programs\Python\Python314\python.exe" -m streamlit run app.py
pause
