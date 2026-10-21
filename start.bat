@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo 还没有安装，请先双击运行 install.bat
    pause
    exit /b 1
)
echo 小宝ai@孙老师已启动，浏览器会自动打开 http://127.0.0.1:8000
echo 使用期间请不要关闭这个窗口。
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python app.py
pause
