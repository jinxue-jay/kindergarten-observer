import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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
CLASS_FILE = config.DATA_DIR / "classes.json"  # 班级和孩子名单


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
    return {"标题": "", "观察内容": "", "观察实录": "", "分析与跟进": text.strip()}


LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>小宝ai@孙老师</title>
<style>
  body { margin:0; min-height:100vh; display:grid; place-items:center; background:#fdf6ec;
    font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; color:#4a3f35; }
  .box { background:#fffdf8; border:2px solid #f0e2cf; border-radius:22px; padding:36px 40px; text-align:center; }
  .logo { font-size:40px; }
  h1 { font-size:20px; margin:10px 0 4px; }
  p { color:#9b8a78; font-size:13px; margin:0 0 20px; }
  input { width:220px; padding:10px 14px; border:2px solid #f0e2cf; border-radius:13px; font:inherit; text-align:center; }
  input:focus { outline:none; border-color:#f59e52; }
  button { display:block; width:100%; margin-top:14px; padding:11px; border:0; border-radius:14px;
    background:linear-gradient(135deg,#f6ad5f,#e8812c); color:#fff; font:inherit; font-weight:700; cursor:pointer; }
</style></head><body>
<div class="box">
  <div class="logo">🌻</div>
  <h1>小宝ai@孙老师</h1>
  <p>请输入访问口令（向孙老师索取）</p>
  <input id="code" type="password" placeholder="访问口令">
  <button onclick="go()">进入</button>
</div>
<script>
function go() {
  document.cookie = 'xb_code=' + encodeURIComponent(document.getElementById('code').value)
    + ';max-age=31536000;path=/;SameSite=Lax';
  location.reload();
}
document.getElementById('code').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
</script></body></html>"""


@app.middleware("http")
async def check_access(request: Request, call_next):
    """页面经公网隧道分享，所有请求都要带口令，防止陌生人上传视频、翻看孩子的记录。"""
    if request.cookies.get("xb_code") == config.ACCESS_CODE:
        return await call_next(request)
    if request.url.path == "/":
        return HTMLResponse(LOGIN_PAGE)
    return JSONResponse({"detail": "需要访问口令"}, status_code=401)


NO_RECORD_REPORT = {
    "标题": "",
    "观察内容": "",
    "观察实录": "视频中没有识别到观察对象的明显行为。请确认视频画面中能看到观察对象，或调整“外貌特征”描述后重新分析。",
    "分析与跟进": "",
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
                # meta 里有 child/klass 和 ctx 的全部字段，标题需要用年龄段
                text = vlm.chat(REPORT_PROMPT.format(records=records, **job["meta"]),
                                config.REPORT_MAX_TOKENS)
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


@app.get("/api/classes")
def classes_get():
    if CLASS_FILE.exists():
        return json.loads(CLASS_FILE.read_text(encoding="utf-8"))
    return []


@app.put("/api/classes")
def classes_put(classes: list = Body(...)):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLASS_FILE.write_text(json.dumps(classes, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True}


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
