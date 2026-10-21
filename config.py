from pathlib import Path

BASE_DIR = Path(__file__).parent
WORK_DIR = BASE_DIR / "work"  # 分析过程中的临时文件（抽出的帧），完成后删除
DATA_DIR = BASE_DIR / "data"  # 分析过的视频和观察记录，长期保存，供"历史记录"查看

# 模型由 Ollama 提供（https://ollama.com），先运行 ollama pull qwen3-vl:8b-instruct
OLLAMA_URL = "http://127.0.0.1:11434"
# 注意要用 instruct 版：qwen3-vl:8b 默认是 thinking 版，会先输出很长的思考过程。
# 显存不足 8GB 时可改为 qwen3-vl:4b-instruct
MODEL_NAME = "qwen3-vl:8b-instruct"
NUM_CTX = 16384           # 上下文长度。Ollama 里每帧 448px 约占 620 token，一段 15 帧约 9500 token

# 视频切段与抽帧参数
SEGMENT_SECONDS = 30      # 每段视频长度
FRAME_INTERVAL = 2.0      # 每隔几秒抽一帧
FRAME_MAX_SIDE = 448      # 帧的最长边像素

SEGMENT_MAX_TOKENS = 600
REPORT_MAX_TOKENS = 2000   # 记录表共五栏，留足输出空间

HOST = "127.0.0.1"        # 只在本机访问，孩子的视频不出这台电脑
PORT = 8000
