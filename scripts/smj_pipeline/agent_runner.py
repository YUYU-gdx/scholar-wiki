from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


def _safe_json(text: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else dict(fallback)
    except Exception:
        return dict(fallback)


@dataclass(slots=True)
class CodexRunnerConfig:
    cli_command: str
    cli_args: list[str]
    healthcheck_args: list[str]
    timeout_seconds: int
    install_command: str
    extra_env: dict[str, str]


def default_codex_config() -> dict[str, Any]:
    return {
        "cli_command": "codex",
        "cli_args": ["exec", "--cwd", "{workdir}", "--skip-git-repo-check", "{prompt}"],
        "healthcheck_args": ["--version"],
        "timeout_seconds": 180,
        "install_command": "npm install -g @openai/codex",
        "extra_env": {},
    }


def load_codex_config(config_path: Path) -> CodexRunnerConfig:
    fallback = default_codex_config()
    merged = dict(fallback)
    path = Path(config_path)
    if path.exists():
        payload = _safe_json(path.read_text(encoding="utf-8"), fallback)
        merged.update(payload)
    timeout_seconds = int(merged.get("timeout_seconds", 180) or 180)
    cli_args_raw = merged.get("cli_args", fallback["cli_args"])
    health_raw = merged.get("healthcheck_args", fallback["healthcheck_args"])
    extra_env_raw = merged.get("extra_env", {})
    return CodexRunnerConfig(
        cli_command=str(merged.get("cli_command", "codex") or "codex").strip(),
        cli_args=[str(x) for x in (cli_args_raw if isinstance(cli_args_raw, list) else fallback["cli_args"])],
        healthcheck_args=[str(x) for x in (health_raw if isinstance(health_raw, list) else fallback["healthcheck_args"])],
        timeout_seconds=max(10, timeout_seconds),
        install_command=str(merged.get("install_command", fallback["install_command"]) or fallback["install_command"]).strip(),
        extra_env={str(k): str(v) for k, v in (extra_env_raw.items() if isinstance(extra_env_raw, dict) else [])},
    )


class AgentRunner:
    backend = "unknown"

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend, "available": False}

    def run(self, prompt: str, workdir: str) -> str:
        raise NotImplementedError


class HermesRunner(AgentRunner):
    backend = "hermes"

    def run(self, prompt: str, workdir: str) -> str:
        _ = prompt, workdir
        raise RuntimeError("agent_backend_unavailable:hermes")


class CodexRunner(AgentRunner):
    backend = "codex"

    def __init__(self, config: CodexRunnerConfig) -> None:
        self._config = config

    def _resolve_command(self) -> str:
        command = str(self._config.cli_command or "codex").strip()
        if not command:
            raise RuntimeError("agent_backend_unavailable:codex")
        resolved = shutil.which(command)
        if resolved:
            return resolved
        if Path(command).exists():
            return command
        raise RuntimeError("agent_backend_unavailable:codex")

    def _render_args(self, prompt: str, workdir: str, use_healthcheck: bool = False) -> list[str]:
        if use_healthcheck:
            raw_args = self._config.healthcheck_args
        else:
            raw_args = self._config.cli_args
        args: list[str] = []
        for item in raw_args:
            args.append(
                str(item or "")
                .replace("{prompt}", prompt)
                .replace("{workdir}", workdir)
            )
        if (not use_healthcheck) and not any("{prompt}" in x for x in raw_args):
            args.append(prompt)
        return args

    def health(self) -> dict[str, Any]:
        try:
            command = self._resolve_command()
        except Exception:
            return {"backend": self.backend, "available": False, "reason": "codex_cli_not_found"}
        try:
            proc = subprocess.run(
                [command, *self._render_args(prompt="", workdir=os.getcwd(), use_healthcheck=True)],
                capture_output=True,
                text=True,
                timeout=max(5, min(30, self._config.timeout_seconds)),
                check=False,
                env={**os.environ, **self._config.extra_env},
            )
        except Exception as exc:
            return {"backend": self.backend, "available": False, "reason": f"codex_healthcheck_failed:{exc}"}
        if int(proc.returncode) != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            return {"backend": self.backend, "available": False, "reason": f"codex_healthcheck_failed:{detail}"}
        version = (proc.stdout or proc.stderr or "").strip().splitlines()
        return {"backend": self.backend, "available": True, "version": version[0] if version else ""}

    def run(self, prompt: str, workdir: str) -> str:
        command = self._resolve_command()
        proc = subprocess.run(
            [command, *self._render_args(prompt=prompt, workdir=workdir, use_healthcheck=False)],
            capture_output=True,
            text=True,
            timeout=self._config.timeout_seconds,
            check=False,
            env={**os.environ, **self._config.extra_env},
        )
        if int(proc.returncode) != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:1200]
            raise RuntimeError(f"agent_backend_unavailable:codex:{detail}")
        text = (proc.stdout or "").strip()
        if not text:
            text = (proc.stderr or "").strip()
        if not text:
            raise RuntimeError("agent_backend_unavailable:codex:empty_output")
        return text


class AgentRunnerFactory:
    def __init__(self, codex_config_path: Path) -> None:
        self._codex_config_path = Path(codex_config_path)

    def build(self, backend: str) -> AgentRunner:
        b = str(backend or "").strip().lower()
        if b == "hermes":
            return HermesRunner()
        if b == "codex":
            return CodexRunner(load_codex_config(self._codex_config_path))
        raise RuntimeError(f"agent_backend_invalid:{b}")

