from pathlib import Path

BASE_DIR = Path(__file__).parent
WORK_DIR = BASE_DIR / "work"  # 上传的视频和抽出的帧，分析完成后自动删除

# 模型由 Ollama 提供（https://ollama.com），先运行 ollama pull qwen3-vl:8b-instruct
OLLAMA_URL = "http://127.0.0.1:11434"
# 注意要用 instruct 版：qwen3-vl:8b 默认是 thinking 版，会先输出很长的思考过程。
# 显存不足 8GB 时可改为 qwen3-vl:4b-instruct
MODEL_NAME = "qwen3-vl:8b-instruct"
NUM_CTX = 8192            # 上下文长度，每段 15 帧约占 2000 token

# 视频切段与抽帧参数
SEGMENT_SECONDS = 30      # 每段视频长度
FRAME_INTERVAL = 2.0      # 每隔几秒抽一帧
FRAME_MAX_SIDE = 448      # 帧的最长边像素

SEGMENT_MAX_TOKENS = 600
REPORT_MAX_TOKENS = 1500

HOST = "127.0.0.1"        # 只在本机访问，孩子的视频不出这台电脑
PORT = 8000
