@echo off
rem ============================================================
rem  双均线 + 240 趋势过滤「安检门」动画 · 一键启动
rem  双击本文件即可：自动启动后端 + 自动打开浏览器演示页
rem  （若浏览器未自动弹出，请手动访问 http://localhost:8765）
rem ============================================================
cd /d "%~dp0"
start "" "C:\Users\31652\AppData\Local\Programs\Python\Python314\python.exe" server.py
