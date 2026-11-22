@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 优先 python，其次 py 启动器（Microsoft Store 版常只有 py）
set "PY="
python -V >nul 2>nul && set "PY=python"
if not defined PY (
    py -3 -V >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [错误] 未找到 Python，请安装 Python 3.10+ 并勾选 "Add python.exe to PATH"
    pause
    exit /b 1
)

%PY% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo 首次运行，正在安装依赖 PySide6 ...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行: %PY% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

%PY% "%~dp0app\main.py"
if errorlevel 1 pause
