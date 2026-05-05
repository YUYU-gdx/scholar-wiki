from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class NvidiaChatCompletionsClient:
    def __init__(
        self,
        api_key: str,
        model: str = "z-ai/glm4.7",
        base_url: str = "https://integrate.api.nvidia.com/v1/chat/completions",
        # NVIDIA endpoint is typically much slower than Zhipu for long prompts.
        # Keep timeout generous; long HTML/context can take >60s before first full response.
        timeout_seconds: int = 180,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        # Retries are important for this provider due to slow/backlogged responses.
        max_retries: int = 3,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    def complete(self, user_content: str, system_prompt: str | None = None) -> str:
        # NOTE: This provider is latency-sensitive.
        # Large user_content (e.g., full paper HTML/text) can significantly increase response time.
        messages: list[dict[str, str]] = []
        if system_prompt is not None and str(system_prompt).strip():
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": str(user_content)})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(self.base_url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    data = json.loads(raw)
                    return _extract_content_text(data)
            except urllib.error.HTTPError as exc:
                last_error = exc
                # Backoff for throttling/server pressure; NVIDIA queueing can be long.
                if exc.code in (408, 429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("nvidia completion failed without explicit error")


def _extract_content_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("invalid nvidia response: missing choices")
    message = (choices[0] or {}).get("message")
    if not isinstance(message, dict):
        raise ValueError("invalid nvidia response: missing message")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    raise ValueError("invalid nvidia response: unsupported content shape")
