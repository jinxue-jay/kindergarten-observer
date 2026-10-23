# 保持公网隧道在线：cloudflared 掉线就自动重开，
# 把最新的公网地址写到 公网地址.txt（每次重连地址都会变）。
import re
import shutil
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
URL_FILE = BASE_DIR / "公网地址.txt"
CLOUDFLARED = shutil.which("cloudflared") or "cloudflared"


def run_once():
    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--region", "us", "--protocol", "http2",
         "--url", "http://127.0.0.1:8000"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace")
    for line in proc.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            URL_FILE.write_text(
                f"公网地址：{m.group(0)}\n"
                f"更新时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                "断线重连后地址会变化，以本文件最新内容为准。\n", encoding="utf-8")
            print("公网地址：", m.group(0), flush=True)
    return proc.wait()


if __name__ == "__main__":
    while True:
        try:
            run_once()
        except Exception as e:
            print("隧道异常：", e, flush=True)
        print("隧道断开，5 秒后自动重连……", flush=True)
        time.sleep(5)
