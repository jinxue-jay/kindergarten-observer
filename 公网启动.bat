@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo 还没有安装，请先双击运行 install.bat
    pause
    exit /b 1
)
where cloudflared >nul 2>nul
if errorlevel 1 (
    echo [缺少 cloudflared] 请先在命令行运行：winget install Cloudflare.cloudflared
    pause
    exit /b 1
)
rem 本机服务没开的话先开一个窗口跑着
netstat -ano | findstr /c:":8000" | findstr /c:"LISTENING" >nul 2>nul
if errorlevel 1 start "小宝ai-本机服务" .venv\Scripts\python app.py
echo 公网隧道已启动，最新公网地址会写进本目录的 公网地址.txt（断线重连后地址会变）。
echo 使用期间请不要关闭这个窗口。
.venv\Scripts\python tunnel_keeper.py
pause
