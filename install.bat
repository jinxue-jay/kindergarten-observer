@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==== 幼儿行为观察助手：安装 ====
echo.

python --version >nul 2>nul
if errorlevel 1 (
    echo [缺少 Python] 请先安装 Python 3.10 或更新版本：https://www.python.org/downloads/
    echo 安装时务必勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

where ollama >nul 2>nul
if errorlevel 1 (
    echo [缺少 Ollama] 请先安装 Ollama：https://ollama.com/download/windows
    echo 安装完成后重新运行本脚本。
    pause
    exit /b 1
)

echo [1/3] 创建 Python 虚拟环境...
if not exist .venv python -m venv .venv
if errorlevel 1 goto fail

echo [2/3] 安装依赖（使用清华镜像）...
.venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto fail

echo [3/3] 下载模型 qwen3-vl:8b-instruct（约 6GB，需要一些时间）...
ollama pull qwen3-vl:8b-instruct
if errorlevel 1 goto fail

echo.
echo 安装完成！双击 start.bat 启动。
pause
exit /b 0

:fail
echo.
echo 安装失败，请把上面的错误信息截图保存。
pause
exit /b 1
