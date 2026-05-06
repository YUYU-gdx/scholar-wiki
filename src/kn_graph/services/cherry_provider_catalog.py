from __future__ import annotations

from typing import Any

# Snapshot from Cherry Studio provider defaults (simplified to OpenAI-compatible fields used by KN Graph).
_PROVIDER_LIST: list[dict[str, str]] = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com"},
    {"id": "anthropic", "name": "Anthropic", "base_url": "https://api.anthropic.com"},
    {"id": "gemini", "name": "Gemini", "base_url": "https://generativelanguage.googleapis.com"},
    {"id": "silicon", "name": "SiliconFlow", "base_url": "https://api.siliconflow.cn"},
    {"id": "dashscope", "name": "阿里百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/"},
    {"id": "doubao", "name": "豆包", "base_url": "https://ark.cn-beijing.volces.com/api/v3/"},
    {"id": "zhipu", "name": "智谱", "base_url": "https://open.bigmodel.cn/api/paas/v4/"},
    {"id": "moonshot", "name": "Moonshot", "base_url": "https://api.moonshot.cn"},
    {"id": "minimax", "name": "MiniMax", "base_url": "https://api.minimaxi.com/v1/"},
    {"id": "qiniu", "name": "Qiniu", "base_url": "https://api.qnaigc.com"},
    {"id": "ppio", "name": "PPIO", "base_url": "https://api.ppinfra.com/v3/openai/"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1/"},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai"},
    {"id": "together", "name": "Together", "base_url": "https://api.together.xyz"},
    {"id": "fireworks", "name": "Fireworks", "base_url": "https://api.fireworks.ai/inference"},
    {"id": "nvidia", "name": "NVIDIA", "base_url": "https://integrate.api.nvidia.com"},
    {"id": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai"},
    {"id": "perplexity", "name": "Perplexity", "base_url": "https://api.perplexity.ai/"},
    {"id": "github", "name": "GitHub Models", "base_url": "https://models.github.ai/inference/"},
    {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434"},
    {"id": "lmstudio", "name": "LM Studio", "base_url": "http://localhost:1234"},
    {"id": "new-api", "name": "New API", "base_url": "http://localhost:3000"},
]


def provider_presets() -> list[dict[str, str]]:
    return [dict(item) for item in _PROVIDER_LIST]


def provider_map() -> dict[str, dict[str, str]]:
    return {item["id"]: dict(item) for item in _PROVIDER_LIST}


def default_endpoint_url(base_url: str) -> str:
    root = str(base_url or "").strip().rstrip("/")
    if not root:
        return ""
    return f"{root}/v1/chat/completions"


def default_embedding_endpoint_url(base_url: str) -> str:
    root = str(base_url or "").strip().rstrip("/")
    if not root:
        return ""
    return f"{root}/embeddings"


def attach_provider_meta(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["provider_presets"] = provider_presets()
    return out
