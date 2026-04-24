from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any, Callable


def _safe_json(text: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else dict(fallback)
    except Exception:
        return dict(fallback)


@dataclass(slots=True)
class CodexRunnerConfig:
    app_server_command: str
    app_server_args: list[str]
    healthcheck_args: list[str]
    timeout_seconds: int
    install_command: str
    extra_env: dict[str, str]
    model: str
    approval_policy: str
    sandbox_mode: str
    personality: str
    mcp_servers: list[dict[str, Any]]


def default_codex_config() -> dict[str, Any]:
    return {
        "app_server_command": "codex",
        "app_server_args": ["app-server", "--listen", "stdio://"],
        "healthcheck_args": ["--version"],
        "timeout_seconds": 180,
        "install_command": "npm install -g @openai/codex",
        "extra_env": {},
        "model": "gpt-5.2",
        "approval_policy": "never",
        "sandbox_mode": "workspace-write",
        "personality": "pragmatic",
        "mcp_servers": [
            {
                "name": "kn_graph_tools",
                "command": "uv",
                "args": ["run", "python", "-m", "scripts.smj_pipeline.kn_mcp_server"],
                "env": {},
            }
        ],
    }


def _normalize_app_server_args(raw_args: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw_args:
        val = str(item or "").strip()
        if not val:
            continue
        out.append(val)
    return out or ["app-server", "--listen", "stdio://"]


def _decode_text(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_legacy_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Map legacy CLI-exec config fields into app-server config fields."""
    out = dict(payload)
    if "app_server_command" not in out and "cli_command" in out:
        out["app_server_command"] = out.get("cli_command")
    if "app_server_args" not in out:
        if isinstance(out.get("cli_args"), list):
            # Old config used `exec`; new default is app-server.
            out["app_server_args"] = ["app-server", "--listen", "stdio://"]
    return out


def load_codex_config(config_path: Path) -> CodexRunnerConfig:
    fallback = default_codex_config()
    merged = dict(fallback)
    path = Path(config_path)
    if path.exists():
        payload = _safe_json(path.read_text(encoding="utf-8"), fallback)
        payload = _normalize_legacy_config(payload)
        merged.update(payload)
    timeout_seconds = int(merged.get("timeout_seconds", 180) or 180)
    app_server_args_raw = merged.get("app_server_args", fallback["app_server_args"])
    health_raw = merged.get("healthcheck_args", fallback["healthcheck_args"])
    extra_env_raw = merged.get("extra_env", {})
    mcp_raw = merged.get("mcp_servers", fallback["mcp_servers"])
    mcp_servers = [x for x in (mcp_raw if isinstance(mcp_raw, list) else fallback["mcp_servers"]) if isinstance(x, dict)]
    model_name = str(merged.get("model", fallback["model"]) or fallback["model"]).strip()
    if model_name == "gpt-5.4":
        model_name = "gpt-5.2"
    return CodexRunnerConfig(
        app_server_command=str(merged.get("app_server_command", "codex") or "codex").strip(),
        app_server_args=_normalize_app_server_args([str(x) for x in (app_server_args_raw if isinstance(app_server_args_raw, list) else fallback["app_server_args"])]),
        healthcheck_args=[str(x) for x in (health_raw if isinstance(health_raw, list) else fallback["healthcheck_args"])],
        timeout_seconds=max(15, timeout_seconds),
        install_command=str(merged.get("install_command", fallback["install_command"]) or fallback["install_command"]).strip(),
        extra_env={str(k): str(v) for k, v in (extra_env_raw.items() if isinstance(extra_env_raw, dict) else [])},
        model=model_name,
        approval_policy=str(merged.get("approval_policy", fallback["approval_policy"]) or fallback["approval_policy"]).strip(),
        sandbox_mode=str(merged.get("sandbox_mode", fallback["sandbox_mode"]) or fallback["sandbox_mode"]).strip(),
        personality=str(merged.get("personality", fallback["personality"]) or fallback["personality"]).strip(),
        mcp_servers=mcp_servers,
    )


class AgentRunner:
    backend = "unknown"

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend, "available": False}


class HermesRunner(AgentRunner):
    backend = "hermes"

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        _ = query, workdir, library_id, runtime_overrides, on_event
        raise RuntimeError("agent_backend_unavailable:hermes")


class _JsonRpcStdio:
    def __init__(self, command: list[str], env: dict[str, str], cwd: str, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            env=env,
        )
        self._q: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._err_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._err_reader.start()

    def _read_stdout(self) -> None:
        assert self._proc.stdout is not None
        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                break
            line = _decode_text(raw).strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if isinstance(msg, dict):
                self._q.put(msg)

    def _read_stderr(self) -> None:
        assert self._proc.stderr is not None
        while True:
            raw = self._proc.stderr.readline()
            if not raw:
                break
            text = _decode_text(raw).strip()
            if text:
                self._stderr_lines.append(text)

    def _send(self, payload: dict[str, Any]) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        assert self._proc.stdin is not None
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def request(
        self,
        method: str,
        params: dict[str, Any] | None,
        request_id: int,
        on_notification: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

        deadline = time.time() + self._timeout_seconds
        while time.time() < deadline:
            timeout = max(0.1, min(1.0, deadline - time.time()))
            try:
                msg = self._q.get(timeout=timeout)
            except queue.Empty:
                continue
            if "id" in msg and int(msg.get("id", -1)) == int(request_id):
                if isinstance(msg.get("error"), dict):
                    err = msg["error"]
                    raise RuntimeError(f"app_server_request_failed:{method}:{err}")
                result = msg.get("result")
                return result if isinstance(result, dict) else {}
            if on_notification is not None and "method" in msg:
                on_notification(msg)
        raise RuntimeError(f"app_server_timeout:{method}")

    def poll_notifications(
        self,
        on_notification: Callable[[dict[str, Any]], None],
        until: Callable[[dict[str, Any]], bool],
        timeout_seconds: int,
    ) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            timeout = max(0.1, min(1.0, deadline - time.time()))
            try:
                msg = self._q.get(timeout=timeout)
            except queue.Empty:
                continue
            if "method" not in msg:
                continue
            on_notification(msg)
            if until(msg):
                return
        raise RuntimeError("app_server_timeout:turn")

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=2)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    @property
    def stderr_tail(self) -> str:
        if not self._stderr_lines:
            return ""
        return "\n".join(self._stderr_lines[-10:])


class CodexRunner(AgentRunner):
    backend = "codex"

    def __init__(self, config: CodexRunnerConfig) -> None:
        self._config = config

    def _resolve_command(self) -> str:
        command = str(self._config.app_server_command or "codex").strip()
        if not command:
            raise RuntimeError("agent_backend_unavailable:codex")
        resolved = shutil.which(command)
        if resolved:
            return resolved
        if Path(command).exists():
            return command
        raise RuntimeError("agent_backend_unavailable:codex")

    def health(self) -> dict[str, Any]:
        try:
            command = self._resolve_command()
        except Exception:
            return {"backend": self.backend, "available": False, "reason": "codex_cli_not_found"}
        try:
            proc = subprocess.run(
                [command, *self._config.healthcheck_args],
                capture_output=True,
                text=False,
                timeout=max(5, min(30, self._config.timeout_seconds)),
                check=False,
                env={**os.environ, **self._config.extra_env},
            )
        except Exception as exc:
            return {"backend": self.backend, "available": False, "reason": f"codex_healthcheck_failed:{exc}"}
        if int(proc.returncode) != 0:
            detail = (_decode_text(proc.stderr) or _decode_text(proc.stdout) or "").strip()[:400]
            return {"backend": self.backend, "available": False, "reason": f"codex_healthcheck_failed:{detail}"}
        version = (_decode_text(proc.stdout) or _decode_text(proc.stderr) or "").strip().splitlines()
        return {"backend": self.backend, "available": True, "version": version[0] if version else ""}

    def _build_mcp_config(self, workdir: str, library_id: str = "", runtime_overrides: dict[str, Any] | None = None) -> Path:
        cfg = {
            "mcpServers": {},
        }
        overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
        source_servers = overrides.get("mcp_servers")
        servers = source_servers if isinstance(source_servers, list) else self._config.mcp_servers
        for item in servers:
            name = str(item.get("name", "")).strip()
            cmd = str(item.get("command", "")).strip()
            if not name or not cmd:
                continue
            args = [str(x) for x in (item.get("args") if isinstance(item.get("args"), list) else [])]
            env = {str(k): str(v) for k, v in ((item.get("env") if isinstance(item.get("env"), dict) else {}).items())}
            if str(library_id or "").strip():
                env.setdefault("KN_DEFAULT_LIBRARY_ID", str(library_id or "").strip())
            cfg["mcpServers"][name] = {"command": cmd, "args": args, "env": env}
        path = Path(workdir) / ".codex" / "mcp_servers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _bootstrap_auth_into_codex_home(codex_home: Path, env: dict[str, str]) -> None:
        """
        When CODEX_HOME is isolated per library, it may miss login artifacts and cause 401.
        Copy only auth essentials from an existing global/home codex dir.
        """
        src_candidates: list[Path] = []
        env_home = str(env.get("CODEX_HOME", "") or "").strip()
        if env_home:
            src_candidates.append(Path(env_home).expanduser().resolve())
        src_candidates.append((Path.home() / ".codex").resolve())

        src_dir: Path | None = None
        for cand in src_candidates:
            if not cand.exists() or not cand.is_dir():
                continue
            if (cand / "auth.json").exists():
                src_dir = cand
                break
        if src_dir is None:
            return

        for rel in ("auth.json", "cap_sid"):
            src = src_dir / rel
            dst = codex_home / rel
            if not src.exists() or not src.is_file():
                continue
            try:
                if dst.exists() and dst.is_file() and dst.stat().st_size > 0:
                    continue
            except Exception:
                pass
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except Exception:
                continue

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = self._resolve_command()
        overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
        mcp_cfg = self._build_mcp_config(workdir, library_id=library_id, runtime_overrides=overrides)
        argv = [command, *self._config.app_server_args, "-c", f"mcp_servers_file=\"{str(mcp_cfg)}\""]
        env = {**os.environ, **self._config.extra_env}
        codex_home = str(overrides.get("codex_home", "") or "").strip()
        if codex_home:
            env["CODEX_HOME"] = codex_home
            codex_home_path = Path(codex_home).resolve()
            codex_home_path.mkdir(parents=True, exist_ok=True)
            self._bootstrap_auth_into_codex_home(codex_home_path, env={**os.environ, **self._config.extra_env})

        transport = _JsonRpcStdio(argv, env=env, cwd=workdir, timeout_seconds=self._config.timeout_seconds)
        try:
            req_id = 1

            def _notify(msg: dict[str, Any]) -> None:
                if on_event is not None:
                    on_event(msg)

                # Best-effort auto resolution for server-initiated approval/elicitations.
                method = str(msg.get("method", "") or "")
                if method.endswith("/requestApproval") and "id" in msg:
                    try:
                        transport._send({
                            "jsonrpc": "2.0",
                            "id": msg.get("id"),
                            "result": {"decision": "accept"},
                        })
                    except Exception:
                        pass
                if method == "mcpServer/elicitation/request" and "id" in msg:
                    try:
                        transport._send({
                            "jsonrpc": "2.0",
                            "id": msg.get("id"),
                            "result": {"action": "decline", "content": None},
                        })
                    except Exception:
                        pass

            transport.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "kn_graph_chat",
                        "title": "KN Graph Chat",
                        "version": "0.1.0",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                    },
                },
                req_id,
                on_notification=_notify,
            )
            req_id += 1
            transport.notify("initialized", {})

            thread_res = transport.request(
                "thread/start",
                {
                    "model": self._config.model,
                    "cwd": workdir,
                    "approvalPolicy": self._config.approval_policy,
                    "sandbox": str(self._config.sandbox_mode or "workspace-write"),
                    "personality": self._config.personality,
                },
                req_id,
                on_notification=_notify,
            )
            req_id += 1
            thread = thread_res.get("thread") if isinstance(thread_res.get("thread"), dict) else {}
            thread_id = str(thread.get("id", "")).strip()
            if not thread_id:
                raise RuntimeError("app_server_thread_start_failed")

            # Restrict loaded skills to workspace project-level skill definitions.
            project_skills_raw = overrides.get("project_skills")
            project_skills = project_skills_raw if isinstance(project_skills_raw, list) else []
            allowed_skill_paths: set[str] = set()
            allowed_skill_names: set[str] = set()
            for item in project_skills:
                if not isinstance(item, dict):
                    continue
                spath = str(item.get("path", "") or "").strip()
                sname = str(item.get("name", "") or "").strip()
                if spath:
                    try:
                        allowed_skill_paths.add(str(Path(spath).resolve()))
                    except Exception:
                        allowed_skill_paths.add(spath)
                if sname:
                    allowed_skill_names.add(sname)
            if allowed_skill_paths or allowed_skill_names:
                try:
                    skills_res = transport.request(
                        "skills/list",
                        {"forceReload": False, "cwds": [workdir]},
                        req_id,
                        on_notification=_notify,
                    )
                    req_id += 1
                    rows = skills_res.get("data") if isinstance(skills_res.get("data"), list) else []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        for item in row.get("skills", []) if isinstance(row.get("skills"), list) else []:
                            if not isinstance(item, dict):
                                continue
                            raw_path = str(item.get("path", "") or "").strip()
                            raw_name = str(item.get("name", "") or "").strip()
                            enabled = bool(item.get("enabled"))
                            norm_path = ""
                            if raw_path:
                                try:
                                    norm_path = str(Path(raw_path).resolve())
                                except Exception:
                                    norm_path = raw_path
                            allow = (norm_path in allowed_skill_paths) or (raw_name in allowed_skill_names)
                            if allow == enabled:
                                continue
                            params: dict[str, Any] = {"enabled": allow}
                            if raw_path:
                                params["path"] = raw_path
                            elif raw_name:
                                params["name"] = raw_name
                            else:
                                continue
                            transport.request("skills/config/write", params, req_id, on_notification=_notify)
                            req_id += 1
                except Exception:
                    pass

            turn_input: list[dict[str, Any]] = []
            turn_input.append({"type": "text", "text": str(query or "")})

            turn_res = transport.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": turn_input,
                    "cwd": workdir,
                    "model": self._config.model,
                    "approvalPolicy": self._config.approval_policy,
                },
                req_id,
                on_notification=_notify,
            )
            turn = turn_res.get("turn") if isinstance(turn_res.get("turn"), dict) else {}
            turn_id = str(turn.get("id", "")).strip()

            answer_chunks: list[str] = []
            final_answer = ""
            turn_status = ""
            turn_error = ""
            last_runtime_error = ""

            def _capture(msg: dict[str, Any]) -> None:
                nonlocal final_answer, turn_status, turn_error, last_runtime_error
                _notify(msg)
                method = str(msg.get("method", "") or "")
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                if method == "item/agentMessage/delta":
                    delta = str(params.get("delta", "") or "")
                    if delta:
                        answer_chunks.append(delta)
                elif method == "item/completed":
                    item = params.get("item") if isinstance(params.get("item"), dict) else {}
                    if str(item.get("type", "")) == "agentMessage":
                        txt = str(item.get("text", "") or "")
                        if txt:
                            final_answer = txt
                elif method == "error":
                    err = params.get("error") if isinstance(params.get("error"), dict) else {}
                    msg_text = str(err.get("message", "") or "").strip()
                    if msg_text:
                        last_runtime_error = msg_text
                elif method == "turn/completed":
                    t = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                    if turn_id and str(t.get("id", "")).strip() != turn_id:
                        return
                    turn_status = str(t.get("status", "") or "").strip().lower()
                    err = t.get("error") if isinstance(t.get("error"), dict) else {}
                    turn_error = str(err.get("message", "") or "").strip()

            def _until_done(msg: dict[str, Any]) -> bool:
                method = str(msg.get("method", "") or "")
                if method != "turn/completed":
                    return False
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                t = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                if turn_id and str(t.get("id", "")).strip() != turn_id:
                    return False
                return True

            transport.poll_notifications(_capture, _until_done, timeout_seconds=self._config.timeout_seconds)
            text = final_answer.strip() or "".join(answer_chunks).strip()
            if not text:
                detail = turn_error or last_runtime_error
                if turn_status == "failed" or detail:
                    reason = detail or "turn_failed"
                    raise RuntimeError(f"agent_backend_unavailable:codex:turn_failed:{reason}")
                raise RuntimeError("agent_backend_unavailable:codex:empty_output")
            return {
                "answer": text,
                "thread_id": thread_id,
                "turn_id": turn_id,
            }
        except RuntimeError:
            raise
        except Exception as exc:
            detail = f"{exc}"
            stderr = transport.stderr_tail
            if stderr:
                detail = f"{detail}; stderr={stderr}"
            raise RuntimeError(f"agent_backend_unavailable:codex:{detail}")
        finally:
            transport.close()


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
