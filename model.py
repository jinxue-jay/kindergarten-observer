import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

import config


class OllamaError(RuntimeError):
    pass


class VLM:
    def _request(self, path: str, payload: dict | None = None, timeout: float = 600) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(config.OLLAMA_URL + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise OllamaError(f"Ollama 返回错误：{e.read().decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise OllamaError("连接不上 Ollama，请确认 Ollama 已经安装并在运行") from e

    def load(self):
        """检查 Ollama 在运行且模型已下载。真正的加载由 Ollama 在第一次推理时完成。"""
        names = {m["name"] for m in self._request("/api/tags", timeout=10).get("models", [])}
        if config.MODEL_NAME not in names and f"{config.MODEL_NAME}:latest" not in names:
            raise OllamaError(f"还没有下载模型，请在命令行运行：ollama pull {config.MODEL_NAME}")

    def _chat(self, messages: list[dict], max_tokens: int) -> str:
        result = self._request("/api/chat", {
            "model": config.MODEL_NAME,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": config.NUM_CTX, "num_predict": max_tokens, "temperature": 0.2},
        })
        return result["message"]["content"]

    def describe_frames(self, instruction: str, frames: list[tuple[str, Path]], max_tokens: int) -> str:
        """frames: [(时间标签, 图片路径)]。每张图单独一条消息并带上时间标签，让模型能写出准确的时间点。"""
        messages = [
            {"role": "user", "content": f"[{ts}]",
             "images": [base64.b64encode(path.read_bytes()).decode()]}
            for ts, path in frames
        ]
        messages.append({"role": "user", "content": instruction})
        return self._chat(messages, max_tokens)

    def chat(self, text: str, max_tokens: int) -> str:
        return self._chat([{"role": "user", "content": text}], max_tokens)


vlm = VLM()
