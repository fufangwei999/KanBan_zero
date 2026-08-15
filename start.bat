@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo [首次运行] 正在创建虚拟环境并安装依赖（PySide6，约 150MB，仅需一次）...
    py -3.12 -m venv venv
    venv\Scripts\python.exe -m pip install --upgrade pip -q
    venv\Scripts\python.exe -m pip install -r requirements.txt
)

venv\Scripts\python.exe main.py
