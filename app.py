import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import config
from model import vlm
from prompts import REPORT_PROMPT, SEGMENT_PROMPT
from video import extract_frames, fmt_ts, probe_duration

app = FastAPI()
jobs: dict[str, dict] = {}
# 一台电脑一次只跑一个模型推理，所有任务排队执行
gpu_lock = threading.Lock()

RECORD_DIR = config.DATA_DIR / "records"
VIDEO_DIR = config.DATA_DIR / "videos"


def parse_record_lines(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = [p.strip() for p in re.split(r"[｜|]", line.strip())]
        if len(parts) >= 3 and re.match(r"^\d{1,2}:\d{2}$", parts[0]):
            rows.append({"time": parts[0], "who": parts[1], "what": "｜".join(parts[2:])})
    return rows


def parse_report(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            # 模型偶尔把某一栏写成列表，统一成多行文本
            return {k: "\n".join(map(str, v)) if isinstance(v, list) else str(v)
                    for k, v in data.items()}
        except json.JSONDecodeError:
            pass
    return {"观察目的": "", "观察实录": "", "行为分析解读": text.strip(),
            "支持策略": "", "教师分析反思": ""}


NO_RECORD_REPORT = {
    "观察目的": "",
    "观察实录": "视频中没有识别到观察对象的明显行为。请确认视频画面中能看到观察对象，或调整“外貌特征”描述后重新分析。",
    "行为分析解读": "",
    "支持策略": "",
    "教师分析反思": "",
}


def run_job(job_id: str, video: Path, ctx: dict):
    job = jobs[job_id]
    job_dir = video.parent
    try:
        with gpu_lock:
            job["status"] = "running"
            job["message"] = "正在检查模型"
            vlm.load()

            duration = probe_duration(video)
            job["duration"] = fmt_ts(duration)
            starts = [s for s in range(0, int(duration) + 1, config.SEGMENT_SECONDS) if s < duration]
            job["total"] = len(starts) + 1  # 最后一步是汇总成记录表

            for i, start in enumerate(starts):
                end = min(start + config.SEGMENT_SECONDS, duration)
                job["message"] = f"正在分析 {fmt_ts(start)} – {fmt_ts(end)}"
                frames = extract_frames(video, job_dir / f"seg{i}", start, end,
                                        config.FRAME_INTERVAL, config.FRAME_MAX_SIDE)
                if not frames:
                    job["done"] += 1
                    continue
                prompt = SEGMENT_PROMPT.format(**ctx)
                text = vlm.describe_frames(
                    prompt, [(fmt_ts(t), p) for t, p in frames], config.SEGMENT_MAX_TOKENS)
                rows = parse_record_lines(text)
                job["records"].extend(rows)
                job["segments"].append({"range": f"{fmt_ts(start)} – {fmt_ts(end)}",
                                        "raw": text.strip(), "rows": rows})
                shutil.rmtree(job_dir / f"seg{i}", ignore_errors=True)
                job["done"] += 1

            job["message"] = "正在撰写观察记录表"
            records = "\n".join(f"{r['time']}｜{r['who']}｜{r['what']}" for r in job["records"])
            if records:
                text = vlm.chat(REPORT_PROMPT.format(records=records, **ctx), config.REPORT_MAX_TOKENS)
                job["report"] = parse_report(text)
            else:
                # 没有记录时不让模型写分析，否则它会凭空编造行为
                job["report"] = NO_RECORD_REPORT
            job["done"] += 1

            # 视频和完整记录归档到 data/，供"历史记录"查看，不再删除视频
            VIDEO_DIR.mkdir(parents=True, exist_ok=True)
            RECORD_DIR.mkdir(parents=True, exist_ok=True)
            saved = VIDEO_DIR / (job_id + video.suffix)
            shutil.move(str(video), saved)
            entry = {"id": job_id, "created": job["created"], "duration": job["duration"],
                     "meta": job["meta"], "records": job["records"],
                     "segments": job["segments"], "report": job["report"], "video": saved.name}
            (RECORD_DIR / f"{job_id}.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")

            job["status"] = "done"
            job["message"] = "完成"
    except Exception as e:  # 把错误展示给页面，而不是让任务静默卡住
        job["status"] = "error"
        job["message"] = f"分析失败：{e}"
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


@app.post("/api/analyze")
async def analyze(
    video: UploadFile = File(...),
    scene: str = Form(""),
    targets: str = Form(""),
    focus: str = Form(""),
    child: str = Form(""),
    klass: str = Form(""),
    date: str = Form(""),
    observer: str = Form(""),
):
    job_id = uuid.uuid4().hex[:12]
    job_dir = config.WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / ("video" + Path(video.filename or "v.mp4").suffix)
    with path.open("wb") as f:
        shutil.copyfileobj(video.file, f)

    ctx = {
        "scene": scene.strip() or "未说明",
        "targets": targets.strip() or "画面中的所有幼儿",
        "focus": focus.strip() or "幼儿在活动中的整体表现",
    }
    jobs[job_id] = {
        "status": "queued", "message": "排队中", "done": 0, "total": 1,
        "duration": "", "records": [], "segments": [], "report": None,
        "created": datetime.now().isoformat(timespec="seconds"),
        # 观察信息随记录一起归档
        "meta": {"child": child.strip(), "klass": klass.strip(), "date": date.strip(),
                 "observer": observer.strip(), **ctx},
    }
    threading.Thread(target=run_job, args=(job_id, path, ctx), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "任务不存在")
    return jobs[job_id]


@app.get("/api/history")
def history_list():
    items = []
    for p in RECORD_DIR.glob("*.json"):
        e = json.loads(p.read_text(encoding="utf-8"))
        items.append({"id": e["id"], "created": e["created"],
                      "duration": e["duration"], "meta": e.get("meta", {})})
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


def _load_entry(item_id: str) -> dict:
    path = RECORD_DIR / f"{item_id}.json"
    if not path.exists():
        raise HTTPException(404, "记录不存在")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/history/{item_id}")
def history_item(item_id: str):
    return _load_entry(item_id)


@app.get("/api/history/{item_id}/video")
def history_video(item_id: str):
    path = VIDEO_DIR / _load_entry(item_id)["video"]
    if not path.exists():
        raise HTTPException(404, "视频文件不存在")
    return FileResponse(path)


@app.delete("/api/history/{item_id}")
def history_delete(item_id: str):
    entry = _load_entry(item_id)
    (VIDEO_DIR / entry["video"]).unlink(missing_ok=True)
    (RECORD_DIR / f"{item_id}.json").unlink()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(config.BASE_DIR / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    shutil.rmtree(config.WORK_DIR, ignore_errors=True)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
