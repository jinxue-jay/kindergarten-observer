import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

# 使用 pip 包自带的 ffmpeg，Windows 上不需要另外安装
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> subprocess.CompletedProcess:
    # Windows 默认编码是 GBK，ffmpeg 输出是 UTF-8，这里显式指定避免乱码报错
    return subprocess.run([FFMPEG, *args], capture_output=True,
                          encoding="utf-8", errors="replace")


def probe_duration(video: Path) -> float:
    out = _run(["-hide_banner", "-i", str(video)]).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        raise ValueError("无法读取视频时长，文件可能已损坏或格式不受支持")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def extract_frames(video: Path, out_dir: Path, start: float, end: float,
                   interval: float, max_side: int) -> list[tuple[float, Path]]:
    """在 [start, end) 区间内每隔 interval 秒抽一帧，返回 (时间点, 图片路径) 列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = f"scale='if(gt(iw,ih),{max_side},-2)':'if(gt(iw,ih),-2,{max_side})'"
    result = _run(["-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
                   "-i", str(video), "-vf", f"fps=1/{interval},{scale}", "-q:v", "3",
                   str(out_dir / "f_%04d.jpg")])
    if result.returncode != 0:
        raise RuntimeError(f"抽帧失败：{result.stderr.strip()[-300:]}")
    frames = []
    for i, path in enumerate(sorted(out_dir.glob("f_*.jpg"))):
        t = start + i * interval
        if t < end:
            frames.append((t, path))
    return frames


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"
