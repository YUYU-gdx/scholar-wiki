from __future__ import annotations

import json
import hmac
import hashlib
import time
import urllib.error
import urllib.request
import base64
from typing import Any


class ZhipuChatCompletionsClient:
    def __init__(
        self,
        api_key: str,
        model: str = "GLM-4.7-Flash",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        timeout_seconds: int = 120,
        temperature: float = 0.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_retries = max_retries

    def complete(self, user_content: str, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt is not None and str(system_prompt).strip():
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": str(user_content)})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._build_auth_token()}",
            "Content-Type": "application/json",
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
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
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
        raise RuntimeError("zhipu completion failed without explicit error")

    def _build_auth_token(self) -> str:
        # Zhipu API keys are commonly in "<id>.<secret>" format and require JWT-like signing.
        if "." not in self.api_key:
            return self.api_key
        api_id, secret = self.api_key.split(".", 1)
        return _build_zhipu_jwt(api_id, secret)


def _extract_content_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("invalid zhipu response: missing choices")
    message = (choices[0] or {}).get("message")
    if not isinstance(message, dict):
        raise ValueError("invalid zhipu response: missing message")
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
    raise ValueError("invalid zhipu response: unsupported content shape")


def _build_zhipu_jwt(api_id: str, secret: str, ttl_seconds: int = 1800) -> str:
    now_ms = int(time.time() * 1000)
    exp_ms = now_ms + ttl_seconds * 1000
    header = {"alg": "HS256", "sign_type": "SIGN"}
    body = {"api_key": api_id, "exp": exp_ms, "timestamp": now_ms}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    body_b64 = _b64url(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_b64}.{body_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url(signature)
    return f"{header_b64}.{body_b64}.{sig_b64}"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
