from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

import requests

from kn_graph.providers.zhipu import ZhipuChatCompletionsClient
from kn_graph.providers.nvidia import NvidiaChatCompletionsClient

_SUPPORTED_PROVIDER_TYPES = {"zhipu", "nvidia", "openai_compatible"}
_ROOT_DIR = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_PATH = _ROOT_DIR / "config" / "llm_providers.json"


def _as_int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except Exception:
        return int(default)
    if value <= 0:
        return int(default)
    return value


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)


def _normalize_list(raw: Any, *, lower: bool = False) -> list[str]:
    if isinstance(raw, list):
        source = raw
    elif isinstance(raw, str):
        source = raw.split(",")
    else:
        source = []
    out: list[str] = []
    seen: set[str] = set()
    for item in source:
        text = str(item or "").strip()
        if not text:
            continue
        if lower:
            text = text.lower()
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"provider_config_not_found:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"provider_config_invalid:{path}")
    return payload


def _dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class OpenAICompatibleChatCompletionsClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: int = 90,
        temperature: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        if not str(api_key).strip():
            raise ValueError("api_key is required")
        self.api_key = str(api_key).strip()
        self.model = str(model).strip()
        self.base_url = str(base_url).strip()
        self.timeout_seconds = int(timeout_seconds)
        self.temperature = float(temperature)
        self.max_retries = int(max_retries)

    def complete_messages(self, messages: list[dict[str, str]], timeout_seconds: int | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        timeout = int(timeout_seconds or self.timeout_seconds)
        response = self._post(payload, stream=False, timeout_seconds=timeout)
        obj = response.json()
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        return str(msg.get("content", "") or "")

    def stream_messages(self, messages: list[dict[str, str]], timeout_seconds: int | None = None) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
        }
        timeout = int(timeout_seconds or self.timeout_seconds)
        with self._post(payload, stream=True, timeout_seconds=timeout) as response:
            for line in response.iter_lines(decode_unicode=True):
                text = str(line or "").strip()
                if not text.startswith("data:"):
                    continue
                data = text[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                choices = obj.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
                chunk = str(delta.get("content", "") or "")
                if chunk:
                    yield chunk

    def _post(self, payload: dict[str, Any], stream: bool, timeout_seconds: int) -> requests.Response:
        last_error: Exception | None = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=int(timeout_seconds),
                    stream=bool(stream),
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
        if last_error is not None:
            raise last_error
        raise RuntimeError("openai_compatible_request_failed")


class _LegacyTextClientAdapter:
    def __init__(self, client: Any):
        self._client = client

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, str]]) -> tuple[str, str]:
        system_prompt = ""
        body_lines: list[str] = []
        for message in messages:
            role = str(message.get("role", "user") or "user").strip()
            content = str(message.get("content", "") or "")
            if role == "system" and not system_prompt and content.strip():
                system_prompt = content
            else:
                body_lines.append(f"{role}: {content}")
        prompt = "\n".join(body_lines).strip() or ""
        return prompt, system_prompt

    def complete_messages(self, messages: list[dict[str, str]], timeout_seconds: int | None = None) -> str:
        _ = timeout_seconds
        prompt, system_prompt = self._messages_to_prompt(messages)
        return str(self._client.complete(prompt, system_prompt=system_prompt))

    def stream_messages(self, messages: list[dict[str, str]], timeout_seconds: int | None = None) -> Iterator[str]:
        text = self.complete_messages(messages=messages, timeout_seconds=timeout_seconds)
        for i in range(0, len(text), 24):
            yield text[i : i + 24]


class _ExtractionClientAdapter:
    def __init__(self, message_client: Any):
        self._message_client = message_client

    def complete(self, user_content: str, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt is not None and str(system_prompt).strip():
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": str(user_content)})
        return str(self._message_client.complete_messages(messages=messages))


class ProviderRegistry:
    def __init__(self, config_path: Path | None = None) -> None:
        env_path = str(os.getenv("LLM_PROVIDER_CONFIG_PATH", "")).strip()
        if config_path is not None:
            self._config_path = Path(config_path)
        elif env_path:
            self._config_path = Path(env_path)
        else:
            self._config_path = _DEFAULT_CONFIG_PATH
        self._providers: dict[str, dict[str, Any]] = {}
        self._alias_to_id: dict[str, str] = {}
        self._default_provider = ""
        self._payload: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        payload = _load_json(self._config_path)
        self._apply_payload(payload)

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        providers_raw = payload.get("providers")
        if not isinstance(providers_raw, list) or not providers_raw:
            raise RuntimeError("provider_config_missing_providers")
        providers: dict[str, dict[str, Any]] = {}
        aliases: dict[str, str] = {}
        for item in providers_raw:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id", "") or "").strip().lower()
            ptype = str(item.get("type", "") or "").strip().lower()
            if not pid:
                continue
            if ptype not in _SUPPORTED_PROVIDER_TYPES:
                raise RuntimeError(f"provider_type_unsupported:{pid}:{ptype}")
            if pid in providers:
                raise RuntimeError(f"provider_id_duplicate:{pid}")
            provider = dict(item)
            provider["id"] = pid
            provider["type"] = ptype
            provider["aliases"] = _normalize_list(provider.get("aliases"), lower=True)
            provider["models"] = _normalize_list(provider.get("models"))
            provider["default_model"] = str(provider.get("default_model", "") or "").strip()
            if provider["default_model"] and provider["default_model"] not in provider["models"]:
                provider["models"].insert(0, provider["default_model"])
            if not provider["default_model"] and provider["models"]:
                provider["default_model"] = provider["models"][0]
            providers[pid] = provider
            aliases[pid] = pid
            for alias in provider.get("aliases", []):
                name = str(alias or "").strip().lower()
                if not name:
                    continue
                if name in aliases and aliases[name] != pid:
                    raise RuntimeError(f"provider_alias_duplicate:{name}")
                aliases[name] = pid

        default_provider = str(payload.get("default_provider", "") or "").strip().lower()
        if not default_provider:
            default_provider = "zhipu"
        default_provider = aliases.get(default_provider, default_provider)
        if default_provider not in providers:
            default_provider = next(iter(providers.keys()))
        self._providers = providers
        self._alias_to_id = aliases
        self._default_provider = default_provider
        self._payload = {
            "default_provider": self._default_provider,
            "providers": [dict(self._providers[pid]) for pid in self._providers.keys()],
        }

    @property
    def config_path(self) -> Path:
        return self._config_path

    def get_config(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload, ensure_ascii=False))

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("provider_config_invalid_payload")
        self._apply_payload(payload)
        _dump_json(self._config_path, self.get_config())
        self.reload()
        return self.get_config()

    @property
    def default_provider(self) -> str:
        return self._default_provider

    def list_provider_names(self) -> list[str]:
        return sorted(self._alias_to_id.keys())

    def resolve_provider_id(self, provider: str | None) -> str:
        raw = str(provider or "").strip().lower()
        if not raw:
            return self._default_provider
        resolved = self._alias_to_id.get(raw)
        if resolved:
            return resolved
        raise RuntimeError(f"unsupported_provider:{provider}")

    def create_message_client(
        self,
        provider: str | None,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        resolved_id = self.resolve_provider_id(provider)
        item = dict(self._providers[resolved_id])
        options_map = dict(options or {})
        provider_type = str(item.get("type", "")).strip().lower()
        model_name = str(model or options_map.get("model") or item.get("default_model", "")).strip()
        api_key_env = str(options_map.get("api_key_env") or item.get("api_key_env", "")).strip()
        api_key_value = str(options_map.get("api_key") or os.getenv(api_key_env, "")).strip()
        base_url = str(options_map.get("base_url") or item.get("base_url", "")).strip()
        timeout_seconds = _as_int(options_map.get("timeout_seconds", item.get("timeout_seconds", 300)), 300)
        temperature = _as_float(options_map.get("temperature", item.get("temperature", 0.2)), 0.2)
        max_retries = _as_int(options_map.get("max_retries", item.get("max_retries", 3)), 3)
        if not api_key_value:
            raise RuntimeError(f"missing_env:{api_key_env or 'LLM_API_KEY'}")

        if provider_type == "zhipu":
            if not model_name:
                model_name = "glm-4.5-flash"
            client = ZhipuChatCompletionsClient(
                api_key=api_key_value,
                model=model_name,
                base_url=base_url or "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_retries=max_retries,
            )
            return _LegacyTextClientAdapter(client)

        if provider_type == "nvidia":
            if not model_name:
                model_name = "z-ai/glm4.7"
            max_tokens = _as_int(options_map.get("max_tokens", item.get("max_tokens", 4096)), 4096)
            client = NvidiaChatCompletionsClient(
                api_key=api_key_value,
                model=model_name,
                base_url=base_url or "https://integrate.api.nvidia.com/v1/chat/completions",
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=max_retries,
            )
            return _LegacyTextClientAdapter(client)

        if provider_type == "openai_compatible":
            if not model_name:
                model_name = "chat-model"
            return OpenAICompatibleChatCompletionsClient(
                api_key=api_key_value,
                model=model_name,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_retries=max_retries,
            )

        raise RuntimeError(f"unsupported_provider_type:{provider_type}")

    def create_extraction_client(
        self,
        provider: str | None,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        return _ExtractionClientAdapter(
            self.create_message_client(
                provider=provider,
                model=model,
                options=options,
            )
        )
