from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
from typing import Any, Callable

# Directory containing the vendored codex_app_server package
_CODEX_APP_SERVER_DIR = str(Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline")


class AgentRunner:
    backend = "unknown"

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend, "available": False}

    def thread_start(
        self,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = workdir, library_id, runtime_overrides
        raise RuntimeError(f"agent_backend_unavailable:{self.backend}")

    def thread_list(
        self,
        workdir: str,
        archived: bool = False,
        limit: int = 100,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = workdir, archived, limit, runtime_overrides
        raise RuntimeError(f"agent_backend_unavailable:{self.backend}")

    def thread_read(
        self,
        thread_id: str,
        workdir: str,
        include_turns: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = thread_id, workdir, include_turns, runtime_overrides
        raise RuntimeError(f"agent_backend_unavailable:{self.backend}")

    def thread_archive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = thread_id, workdir, runtime_overrides
        raise RuntimeError(f"agent_backend_unavailable:{self.backend}")

    def thread_unarchive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = thread_id, workdir, runtime_overrides
        raise RuntimeError(f"agent_backend_unavailable:{self.backend}")

    def thread_set_name(
        self,
        thread_id: str,
        name: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = thread_id, name, workdir, runtime_overrides
        raise RuntimeError(f"agent_backend_unavailable:{self.backend}")


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


class CodexRunner(AgentRunner):
    """Agent runner using the vendored Codex SDK (``codex_app_server``).

    The SDK handles subprocess lifecycle, JSON-RPC transport, and notification
    parsing internally.  This runner is a thin adapter from the SDK surface to
    the ``AgentRunner`` interface.
    """

    backend = "codex"

    def __init__(self, codex_bin: str = "codex", model: str = "gpt-5.2", agent_config: dict[str, Any] | None = None) -> None:
        self._codex_bin = codex_bin
        self._model = model
        self._agent_config = dict(agent_config or {})

    # ------------------------------------------------------------------
    # AgentRunner interface
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        try:
            resolved = shutil.which(self._codex_bin)
            if not resolved:
                resolved = self._codex_bin
            proc = subprocess.run(
                [resolved, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            version = (proc.stdout or proc.stderr or "").strip().splitlines()
            available = int(proc.returncode) == 0
            return {
                "backend": self.backend,
                "available": available,
                "version": version[0] if version and available else "",
                "reason": "" if available else f"exit_code={proc.returncode}",
            }
        except FileNotFoundError:
            return {"backend": self.backend, "available": False, "reason": "codex_cli_not_found"}
        except Exception as exc:
            return {"backend": self.backend, "available": False, "reason": str(exc)}

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        thread_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        import sys as _sys

        _sys.path.insert(0, _CODEX_APP_SERVER_DIR)
        from codex_app_server.generated.v2_all import AgentMessageDeltaNotification

        answer_chunks: list[str] = []
        final_answer = ""
        resolved_thread_id = ""

        with self._open_codex(workdir, library_id, runtime_overrides) as codex:
            if thread_id:
                resolved_thread_id = thread_id
                try:
                    thread = codex.thread_resume(
                        thread_id,
                        model=self._model,
                        cwd=workdir,
                        personality="pragmatic",
                    )
                except Exception:
                    thread = codex.thread_start(
                        model=self._model,
                        cwd=workdir,
                        personality="pragmatic",
                    )
                    resolved_thread_id = thread.id
            else:
                thread = codex.thread_start(
                    model=self._model,
                    cwd=workdir,
                    personality="pragmatic",
                )
                resolved_thread_id = thread.id

            from codex_app_server import TextInput

            turn = thread.turn(
                input=TextInput(query),
                cwd=workdir,
            )

            for event in turn.stream():
                if on_event is not None:
                    on_event(_notification_to_dict(event))

                payload = event.payload
                if isinstance(payload, AgentMessageDeltaNotification):
                    delta = payload.delta or ""
                    if delta:
                        answer_chunks.append(delta)

                if (
                    event.method == "turn/completed"
                    and hasattr(payload, "turn")
                    and payload.turn is not None
                ):
                    turn_id = payload.turn.id
                    if payload.turn.status.value == "failed":
                        err_msg = ""
                        if payload.turn.error is not None:
                            err_msg = payload.turn.error.message or ""
                        raise RuntimeError(
                            f"agent_backend_unavailable:codex:turn_failed:{err_msg}"
                        )
                    for item in payload.turn.items or []:
                        agent_msg = item.root if hasattr(item, "root") else item
                        text = getattr(agent_msg, "text", None)
                        if text:
                            final_answer = str(text)
                    break

        answer = final_answer.strip() or "".join(answer_chunks).strip()
        if not answer:
            raise RuntimeError("agent_backend_unavailable:codex:empty_output")
        return {
            "answer": answer,
            "thread_id": resolved_thread_id,
            "turn_id": turn.id if "turn" in dir() else "",
        }

    def thread_start(
        self,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._open_codex(workdir, library_id, runtime_overrides) as codex:
            t = codex.thread_start(model=self._model, cwd=workdir, personality="pragmatic")
            return {"thread": {"id": t.id}}

    def thread_list(
        self,
        workdir: str,
        archived: bool = False,
        limit: int = 100,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._open_codex(workdir, runtime_overrides=runtime_overrides) as codex:
            resp = codex.thread_list(cwd=workdir, limit=limit)
            threads = resp.data if hasattr(resp, "data") else []
            return {
                "data": [
                    {"id": t.id, "name": t.name or "", "preview": (t.preview or "")[:200]}
                    for t in (threads if isinstance(threads, list) else [])
                ]
            }

    def thread_read(
        self,
        thread_id: str,
        workdir: str,
        include_turns: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._open_codex(workdir, runtime_overrides=runtime_overrides) as codex:
            thread = codex.thread_resume(thread_id, model=self._model, cwd=workdir)
            resp = thread.read(include_turns=include_turns)
            raw: dict[str, Any] = resp.model_dump() if hasattr(resp, "model_dump") else {}
            thread_data = raw.get("thread", {}) if isinstance(raw, dict) else {}
            messages: list[dict[str, Any]] = []
            if include_turns:
                for turn in (thread_data.get("turns", []) if isinstance(thread_data, dict) else []):
                    for item in (turn.get("items", []) if isinstance(turn, dict) else []):
                        item_type = str(item.get("type", "") or "")
                        if item_type == "userMessage":
                            content_parts = []
                            for block in (item.get("content", []) if isinstance(item, dict) else []):
                                if isinstance(block, dict) and isinstance(block.get("text"), str):
                                    content_parts.append(block["text"])
                            messages.append({
                                "message_id": str(item.get("id", "") or ""),
                                "session_id": thread_id,
                                "role": "user",
                                "content": "".join(content_parts),
                                "status": "completed",
                            })
                        elif item_type == "agentMessage":
                            messages.append({
                                "message_id": str(item.get("id", "") or ""),
                                "session_id": thread_id,
                                "role": "assistant",
                                "content": str(item.get("text", "") or ""),
                                "status": "completed",
                            })
            return {
                "thread": {
                    "id": str(thread_data.get("id", thread_id) or thread_id),
                    "title": str(thread_data.get("name", "") or ""),
                    "created_at": thread_data.get("createdAt", thread_data.get("created_at", "")),
                },
                "messages": messages,
            }

    def thread_archive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._open_codex(workdir, runtime_overrides=runtime_overrides) as codex:
            try:
                codex.thread_archive(thread_id)
            except Exception:
                pass  # freshly created thread may not have persisted yet
            return {"archived": True}

    def thread_unarchive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._open_codex(workdir, runtime_overrides=runtime_overrides) as codex:
            try:
                t = codex.thread_unarchive(thread_id)
                return {"thread": {"id": t.id}}
            except Exception:
                return {"thread": {"id": thread_id, "unarchived": True}}

    def thread_set_name(
        self,
        thread_id: str,
        name: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._open_codex(workdir, runtime_overrides=runtime_overrides) as codex:
            thread = codex.thread_resume(thread_id, model=self._model, cwd=workdir)
            thread.set_name(name)
            return {"renamed": True}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_codex(
        self,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
    ) -> Any:
        """Create a ``Codex`` context manager configured for *workdir*."""
        import sys as _sys

        _sys.path.insert(0, _CODEX_APP_SERVER_DIR)
        from codex_app_server import Codex, AppServerConfig

        # Resolve the codex binary path (the SDK needs a full path, not just "codex").
        codex_bin = self._codex_bin
        resolved = shutil.which(codex_bin)
        if resolved:
            codex_bin = resolved
        elif not Path(codex_bin).exists():
            raise RuntimeError("agent_backend_unavailable:codex:cli_not_found")

        overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
        mcp_cfg_path = self._write_mcp_config(workdir, library_id, overrides)
        config_overrides: list[str] = []
        if mcp_cfg_path is not None:
            config_overrides.append(f"mcp_servers_file=\"{mcp_cfg_path}\"")

        env = dict(os.environ)
        codex_home = str(overrides.get("codex_home", "") or "").strip()
        if codex_home:
            env["CODEX_HOME"] = str(Path(codex_home).resolve())
        # Inject agent provider config as env vars
        ac = self._agent_config
        agent_api_key = str(ac.get("api_key", "") or "").strip()
        agent_base_url = str(ac.get("base_url", "") or "").strip()
        if agent_api_key:
            env["CODEX_API_KEY"] = agent_api_key
        if agent_base_url:
            env["CODEX_BASE_URL"] = agent_base_url

        return Codex(
            config=AppServerConfig(
                codex_bin=codex_bin,
                config_overrides=tuple(config_overrides),
                cwd=workdir,
                env=env,
                client_name="kn_graph_chat",
                client_title="KN Graph Chat",
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_mcp_config(
        workdir: str, library_id: str, overrides: dict[str, Any]
    ) -> Path | None:
        source = overrides.get("mcp_servers")
        servers = source if isinstance(source, list) else []
        if not servers:
            return None
        cfg: dict[str, Any] = {"mcpServers": {}}
        for item in servers:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            cmd = str(item.get("command", "") or "").strip()
            if not name or not cmd:
                continue
            args = [str(x) for x in (item.get("args") if isinstance(item.get("args"), list) else [])]
            env = {
                str(k): str(v)
                for k, v in (
                    (item.get("env") if isinstance(item.get("env"), dict) else {}).items()
                )
            }
            if str(library_id or "").strip():
                env.setdefault("KN_DEFAULT_LIBRARY_ID", str(library_id or "").strip())
            cfg["mcpServers"][name] = {"command": cmd, "args": args, "env": env}
        path = Path(workdir) / ".codex" / "mcp_servers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _notification_to_dict(notification: Any) -> dict[str, Any]:
    """Convert a Codex SDK ``Notification`` to the legacy dict format expected
    by ``_on_app_event``."""
    payload = notification.payload
    if hasattr(payload, "model_dump"):
        params = payload.model_dump(by_alias=True, mode="json", exclude_none=True)
    elif hasattr(payload, "params"):
        params = dict(getattr(payload, "params", {}))
    else:
        params = {}
    return {"method": notification.method, "params": params}


class ClaudeCodeRunner(AgentRunner):
    """Agent runner using the Claude Agent SDK (claude-agent-sdk).

    The SDK runs the agent loop in-process with Anthropic API (or compatible)
    for LLM inference and local tool execution.  It requires the
    ``claude-agent-sdk`` package and ``ANTHROPIC_API_KEY`` (or compatible)
    environment variable.

    Session lifecycle is managed through the SDK's built-in session store.
    """

    backend = "claude_code"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})

    # ------------------------------------------------------------------
    # AgentRunner interface
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return {"backend": self.backend, "available": False, "reason": "claude_agent_sdk_not_installed"}
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY", "")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        ).strip()
        if not api_key:
            return {"backend": self.backend, "available": False, "reason": "ANTHROPIC_API_KEY not set"}
        return {"backend": self.backend, "available": True}

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        thread_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        # Bridge ANTHROPIC_AUTH_TOKEN → ANTHROPIC_API_KEY if the SDK expects it.
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
            if token:
                os.environ["ANTHROPIC_API_KEY"] = token

        import asyncio
        import queue
        from claude_agent_sdk import (
            query as claude_query,
            ClaudeAgentOptions,
            AssistantMessage,
            TextBlock,
            ThinkingBlock,
            ToolUseBlock,
            ToolResultBlock,
            ServerToolUseBlock,
            ServerToolResultBlock,
            SystemMessage,
            ResultMessage,
            HookMatcher,
        )

        overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
        mcp_servers = self._build_mcp_servers(overrides, library_id)

        # Queue to communicate tool results from PostToolUse hook to message loop.
        tool_result_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        async def _on_post_tool_use(
            input_data: dict[str, Any],  # PostToolUseHookInput
            tool_use_id: str,
            context: Any = None,
        ) -> dict[str, Any]:
            """Hook callback: fires after every tool execution."""
            try:
                payload = {
                    "type": "toolResult",
                    "tool_use_id": str(tool_use_id or input_data.get("tool_use_id", "")),
                    "tool_name": str(input_data.get("tool_name", "") or ""),
                    "tool_input": input_data.get("tool_input", {}),
                    "tool_response": input_data.get("tool_response", None),
                }
                tool_result_queue.put_nowait(payload)
            except queue.Full:
                pass
            return {}

        stderr_lines: list[str] = []

        def _on_stderr(line: str) -> None:
            stderr_lines.append(line)

        async def _run() -> dict[str, Any]:
            answer_chunks: list[str] = []
            final_answer = ""
            session_id = ""
            tool_steps: dict[str, dict[str, Any]] = {}

            cfg = self._config
            claude_model = str(cfg.get("model", "") or "").strip()
            claude_api_key = str(cfg.get("api_key", "") or "").strip()
            claude_base_url = str(cfg.get("base_url", "") or "").strip()

            sdk_env: dict[str, str] = {}
            if claude_api_key:
                sdk_env["ANTHROPIC_AUTH_TOKEN"] = claude_api_key
            if claude_base_url:
                sdk_env["ANTHROPIC_BASE_URL"] = claude_base_url

            options = ClaudeAgentOptions(
                allowed_tools=_DEFAULT_AGENT_SDK_TOOLS,
                permission_mode="bypassPermissions",
                cwd=workdir,
                mcp_servers=mcp_servers,
                include_partial_messages=True,
                hooks={
                    "PostToolUse": [
                        HookMatcher(matcher=".*", hooks=[_on_post_tool_use])
                    ],
                },
                model=claude_model or None,
                env=sdk_env,
                stderr=_on_stderr,
            )
            tid = str(thread_id or "").strip()
            if tid:
                parts = tid.split("-")
                is_uuid = len(parts) == 5 and all(len(p) in (8, 4, 4, 4, 12) for p in parts) and all(c in "0123456789abcdef-" for c in tid.lower())
                if is_uuid:
                    options.resume = tid

            async for message in claude_query(prompt=query, options=options):
                # Drain pending tool results from hook callbacks
                self._drain_tool_results(tool_result_queue, tool_steps, on_event)

                if isinstance(message, SystemMessage):
                    if message.subtype == "init" and isinstance(message.data, dict):
                        session_id = str(message.data.get("session_id", "") or "")
                        self._notify(
                            on_event,
                            "system/init",
                            {
                                "session_id": session_id,
                                "model": str(message.data.get("model", "") or ""),
                            },
                        )

                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text = str(block.text or "")
                            if text:
                                answer_chunks.append(text)
                                self._notify(
                                    on_event,
                                    "item/agentMessage/delta",
                                    {"delta": text},
                                )

                        elif isinstance(block, ThinkingBlock):
                            self._notify(
                                on_event,
                                "item/thinking/delta",
                                {"thinking": str(block.thinking or "")},
                            )

                        elif isinstance(block, ToolUseBlock):
                            tool_id = str(block.id or "")
                            tool_steps[tool_id] = {
                                "name": str(block.name or ""),
                                "input": block.input,
                            }
                            self._notify(
                                on_event,
                                "item/started",
                                {
                                    "item": {
                                        "id": tool_id,
                                        "type": "toolCall",
                                        "tool": block.name,
                                        "arguments": block.input,
                                    }
                                },
                            )

                        elif isinstance(block, ServerToolUseBlock):
                            tool_id = str(block.id or "")
                            tool_steps[tool_id] = {
                                "name": str(block.name or ""),
                                "input": block.input,
                            }
                            self._notify(
                                on_event,
                                "item/started",
                                {
                                    "item": {
                                        "id": tool_id,
                                        "type": "serverToolCall",
                                        "tool": block.name,
                                        "arguments": block.input,
                                    }
                                },
                            )

                        elif isinstance(block, ToolResultBlock):
                            tool_id = str(block.tool_use_id or "")
                            info = tool_steps.get(tool_id, {})
                            self._notify(
                                on_event,
                                "item/completed",
                                {
                                    "item": {
                                        "id": tool_id,
                                        "type": "toolCall",
                                        "tool": info.get("name", ""),
                                        "status": "failed" if block.is_error else "completed",
                                        "result": {"content": block.content},
                                        "isError": block.is_error,
                                    }
                                },
                            )

                        elif isinstance(block, ServerToolResultBlock):
                            tool_id = str(block.tool_use_id or "")
                            info = tool_steps.get(tool_id, {})
                            self._notify(
                                on_event,
                                "item/completed",
                                {
                                    "item": {
                                        "id": tool_id,
                                        "type": "serverToolCall",
                                        "tool": info.get("name", ""),
                                        "status": "completed",
                                        "result": {"structuredContent": block.content},
                                    }
                                },
                            )

                elif isinstance(message, ResultMessage):
                    # Final drain
                    self._drain_tool_results(tool_result_queue, tool_steps, on_event)
                    if message.is_error:
                        errs = message.errors or [message.result or "unknown_error"]
                        detail = ";".join(errs)
                        if stderr_lines:
                            detail = detail + " | stderr: " + "".join(stderr_lines)[-500:]
                        raise RuntimeError(
                            f"agent_backend_unavailable:claude_code:{detail}"
                        )
                    final_answer = str(message.result or "").strip() or "".join(
                        answer_chunks
                    ).strip()
                    self._notify(
                        on_event,
                        "turn/completed",
                        {
                            "turn": {
                                "id": session_id or (message.session_id or ""),
                                "status": "completed",
                            }
                        },
                    )
                    return {
                        "answer": final_answer,
                        "thread_id": message.session_id or session_id,
                        "turn_id": message.session_id or session_id,
                    }

            # Final drain (just in case)
            self._drain_tool_results(tool_result_queue, tool_steps, on_event)
            final_answer = "".join(answer_chunks).strip()
            if not final_answer:
                detail = "empty_output"
                if stderr_lines:
                    detail = detail + " | stderr: " + "".join(stderr_lines)[-500:]
                raise RuntimeError(f"agent_backend_unavailable:claude_code:{detail}")
            return {
                "answer": final_answer,
                "thread_id": session_id,
                "turn_id": session_id,
            }

        try:
            return asyncio.run(_run())
        except RuntimeError:
            raise
        except Exception as exc:
            detail = str(exc)
            if stderr_lines:
                detail = detail + " | stderr: " + "".join(stderr_lines)[-500:]
            raise RuntimeError(f"agent_backend_unavailable:claude_code:{detail}") from exc

    @staticmethod
    def _drain_tool_results(
        result_queue: Any,
        tool_steps: dict[str, dict[str, Any]],
        on_event: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        """Pull pending tool results from the hook callback queue and emit events."""
        import queue as _queue

        while True:
            try:
                payload = result_queue.get_nowait()
            except _queue.Empty:
                break
            tool_id = str(payload.get("tool_use_id", "") or "")
            if not tool_id:
                continue
            info = tool_steps.get(tool_id, {})
            tool_response = payload.get("tool_response")
            is_error = (
                isinstance(tool_response, dict)
                and tool_response.get("is_error", False)
            )
            ClaudeCodeRunner._notify(
                on_event,
                "item/completed",
                {
                    "item": {
                        "id": tool_id,
                        "type": "toolCall",
                        "tool": info.get("name", payload.get("tool_name", "")),
                        "status": "failed" if is_error else "completed",
                        "result": {"content": tool_response},
                        "isError": is_error,
                    }
                },
            )

    def thread_start(
        self,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import uuid

        tid = str(uuid.uuid4())
        return {"thread": {"id": tid}}

    def thread_list(
        self,
        workdir: str,
        archived: bool = False,
        limit: int = 100,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = archived, runtime_overrides
        from claude_agent_sdk import list_sessions as claude_list_sessions

        sessions = claude_list_sessions(
            directory=workdir, limit=limit, include_worktrees=True
        )
        return {
            "data": [
                {
                    "id": s.session_id,
                    "name": s.custom_title or s.summary or "",
                    "preview": (s.first_prompt or "")[:200],
                    "last_modified": s.last_modified,
                    "created_at": s.created_at,
                    "git_branch": s.git_branch,
                }
                for s in sessions
            ]
        }

    def thread_read(
        self,
        thread_id: str,
        workdir: str,
        include_turns: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = runtime_overrides
        from claude_agent_sdk import get_session_messages, get_session_info

        info = get_session_info(thread_id, directory=workdir)
        messages: list[dict[str, Any]] = []
        if include_turns:
            raw = get_session_messages(thread_id, directory=workdir)
            for m in raw:
                msg_content = ""
                msg_obj = m.message if hasattr(m, "message") else None
                if isinstance(msg_obj, dict):
                    content = msg_obj.get("content", "")
                    if isinstance(content, str):
                        msg_content = content
                    elif isinstance(content, list):
                        parts = []
                        for block in content:
                            if isinstance(block, dict) and isinstance(block.get("text"), str):
                                parts.append(block["text"])
                        msg_content = "".join(parts)
                messages.append(
                    {
                        "message_id": m.uuid if hasattr(m, "uuid") else "",
                        "session_id": thread_id,
                        "role": m.type if hasattr(m, "type") else "user",
                        "content": msg_content,
                        "status": "completed",
                    }
                )
        return {
            "thread": {
                "id": thread_id,
                "title": info.custom_title or info.summary if info else "",
                "created_at": info.created_at if info else None,
            },
            "messages": messages,
        }

    def thread_archive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            import asyncio
            from claude_agent_sdk import delete_session
        except ImportError:
            return {"archived": True}
        asyncio.run(delete_session(session_id=thread_id))
        return {"archived": True}

    def thread_unarchive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Agent SDK sessions are not archivable in the Codex sense.
        return {"unarchived": True}

    def thread_set_name(
        self,
        thread_id: str,
        name: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            import asyncio
            from claude_agent_sdk import rename_session
        except ImportError:
            return {"renamed": True}
        asyncio.run(rename_session(session_id=thread_id, name=name))
        return {"renamed": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _notify(
        on_event: Callable[[dict[str, Any]], None] | None,
        method: str,
        params: dict[str, Any],
    ) -> None:
        if on_event is None:
            return
        try:
            on_event({"method": method, "params": dict(params)})
        except Exception:
            pass

    @staticmethod
    def _build_mcp_servers(
        overrides: dict[str, Any], library_id: str
    ) -> dict[str, dict[str, Any]]:
        servers: dict[str, dict[str, Any]] = {}
        source = overrides.get("mcp_servers")
        items = source if isinstance(source, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            cmd = str(item.get("command", "") or "").strip()
            if not name or not cmd:
                continue
            args = [str(x) for x in (item.get("args") if isinstance(item.get("args"), list) else [])]
            env = {
                str(k): str(v)
                for k, v in (
                    (item.get("env") if isinstance(item.get("env"), dict) else {}).items()
                )
            }
            if str(library_id or "").strip():
                env.setdefault("KN_DEFAULT_LIBRARY_ID", str(library_id or "").strip())
            servers[name] = {
                "type": "stdio",
                "command": cmd,
                "args": args,
                "env": env,
            }
        return servers


class GeminiCLIRunner(AgentRunner):
    """Agent runner using the Gemini CLI (``gemini``) subprocess.

    Spawns ``gemini`` with stream-json output, injects provider config via
    environment variables, and translates CLI events to the AgentRunner
    notification format.
    """

    backend = "gemini_cli"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})

    # ------------------------------------------------------------------
    # AgentRunner interface
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["gemini", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            version = (proc.stdout or proc.stderr or "").strip().splitlines()
            available = int(proc.returncode) == 0
            return {
                "backend": self.backend,
                "available": available,
                "version": version[0] if version and available else "",
                "reason": "" if available else f"exit_code={proc.returncode}",
            }
        except FileNotFoundError:
            api_key = (
                os.environ.get("GEMINI_API_KEY", "")
                or str(self._config.get("api_key", "") or "").strip()
            )
            return {
                "backend": self.backend,
                "available": False,
                "reason": "gemini_cli_not_found" if not api_key else "gemini_cli_not_found (GEMINI_API_KEY set)",
            }
        except Exception as exc:
            return {"backend": self.backend, "available": False, "reason": str(exc)}

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        thread_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        cfg = self._config
        api_key = str(cfg.get("api_key", "") or "").strip()
        model = str(cfg.get("model", "") or "").strip()
        base_url = str(cfg.get("base_url", "") or "").strip()

        resolved = shutil.which("gemini")
        if not resolved:
            raise RuntimeError("agent_backend_unavailable:gemini_cli:cli_not_found")

        cmd = [resolved, "--output-format", "stream-json", "--verbose"]
        if model:
            cmd.extend(["--model", model])
        if thread_id:
            cmd.extend(["--resume", thread_id])

        env = dict(os.environ)
        if api_key:
            env["GEMINI_API_KEY"] = api_key
        if base_url:
            env["GEMINI_BASE_URL"] = base_url

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=env,
        )

        try:
            if proc.stdin:
                proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": query}}) + "\n")
                proc.stdin.flush()
                proc.stdin.close()

            answer_chunks: list[str] = []
            final_answer = ""
            resolved_thread_id = thread_id

            if proc.stdout:
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(msg, dict):
                        continue

                    msg_type = str(msg.get("type", "") or "")
                    if msg_type in ("assistant", "content_block_delta"):
                        delta = ""
                        if msg_type == "assistant":
                            content = msg.get("content", [])
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict):
                                        delta = str(block.get("text", "") or "")
                                        if delta:
                                            break
                        else:
                            delta_data = msg.get("delta", {})
                            if isinstance(delta_data, dict):
                                delta = str(delta_data.get("text", "") or "")
                        if delta:
                            answer_chunks.append(delta)
                            if on_event:
                                on_event({
                                    "method": "item/agentMessage/delta",
                                    "params": {"delta": delta},
                                })

                    elif msg_type in ("session",):
                        sid = str(msg.get("session_id", "") or "")
                        if sid:
                            resolved_thread_id = sid
                            if on_event:
                                on_event({
                                    "method": "system/init",
                                    "params": {"session_id": sid, "model": model},
                                })

                    elif msg_type in ("tool_call", "tool_use"):
                        tool_id = str(msg.get("id", "") or f"tc_{len(answer_chunks)}")
                        tool_name = str(msg.get("name", "") or "")
                        if on_event:
                            on_event({
                                "method": "item/started",
                                "params": {
                                    "item": {
                                        "id": tool_id,
                                        "type": "toolCall",
                                        "tool": tool_name,
                                        "arguments": msg.get("input", {}),
                                    }
                                },
                            })

                    elif msg_type in ("tool_result",):
                        tool_id = str(msg.get("tool_use_id", "") or "")
                        is_error = bool(msg.get("is_error", False))
                        if on_event:
                            on_event({
                                "method": "item/completed",
                                "params": {
                                    "item": {
                                        "id": tool_id,
                                        "type": "toolCall",
                                        "tool": str(msg.get("name", "") or ""),
                                        "status": "failed" if is_error else "completed",
                                        "result": {"content": msg.get("content", "")},
                                        "isError": is_error,
                                    }
                                },
                            })

                    elif msg_type in ("result", "done"):
                        final_answer = str(msg.get("result", "") or "").strip()
                        if not final_answer and msg_type == "result":
                            final_answer = str(msg.get("text", "") or "").strip()
                        if on_event:
                            on_event({
                                "method": "turn/completed",
                                "params": {"turn": {"id": resolved_thread_id, "status": "completed"}},
                            })
                        break

            answer = final_answer or "".join(answer_chunks).strip()
            if not answer:
                raise RuntimeError("agent_backend_unavailable:gemini_cli:empty_output")
            return {
                "answer": answer,
                "thread_id": resolved_thread_id,
                "turn_id": resolved_thread_id,
            }

        finally:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
            except Exception:
                pass

    def thread_start(
        self,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import uuid

        tid = str(uuid.uuid4())
        return {"thread": {"id": tid}}

    def thread_list(
        self,
        workdir: str,
        archived: bool = False,
        limit: int = 100,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = archived, runtime_overrides
        chats_dir = self._gemini_chats_dir(workdir)
        if chats_dir is None:
            return {"data": []}

        sessions: list[dict[str, Any]] = []
        for f in sorted(chats_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.suffix not in (".json", ".jsonl"):
                continue
            info = self._parse_gemini_session_info(f)
            if info is None:
                continue
            sessions.append(info)
            if len(sessions) >= limit:
                break
        return {"data": sessions}

    def thread_read(
        self,
        thread_id: str,
        workdir: str,
        include_turns: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = runtime_overrides
        chats_dir = self._gemini_chats_dir(workdir)
        if chats_dir is None:
            return {"thread": {"id": thread_id}, "messages": []}

        for f in chats_dir.iterdir():
            if f.suffix not in (".json", ".jsonl"):
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if thread_id not in content:
                continue
            if f.suffix == ".json":
                return self._parse_gemini_json_session(content, thread_id, include_turns)
            else:
                return self._parse_gemini_jsonl_session(content, thread_id, include_turns)

        return {"thread": {"id": thread_id}, "messages": []}

    # ------------------------------------------------------------------
    # Gemini session file helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _gemini_project_name(workdir: str) -> str:
        import re
        from pathlib import Path

        name = Path(workdir).name
        name = re.sub(r"[^a-zA-Z0-9]", "-", name).lower()
        return name

    @staticmethod
    def _gemini_chats_dir(workdir: str) -> Path | None:
        from pathlib import Path

        project_name = GeminiCLIRunner._gemini_project_name(workdir)
        chats_dir = Path.home() / ".gemini" / "tmp" / project_name / "chats"
        return chats_dir if chats_dir.is_dir() else None

    @staticmethod
    def _parse_gemini_session_info(file_path: Path) -> dict[str, Any] | None:
        import json
        import re

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        # Extract session ID and start time from filename: session-<ts>-<hash>.<ext>
        name = file_path.stem  # e.g. session-2026-04-24T09-09-e47c5adc
        m = re.match(r"session-(.+?)-([a-f0-9]+)$", name)
        start_time = ""
        short_hash = ""
        if m:
            start_time = m.group(1).replace("T", " ")
            short_hash = m.group(2)

        title = ""
        session_id = ""

        if file_path.suffix == ".json":
            try:
                data = json.loads(content)
                session_id = data.get("sessionId", "")
                msgs = data.get("messages", [])
                for msg in msgs:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        c = msg.get("content", "")
                        if isinstance(c, list):
                            for block in c:
                                if isinstance(block, dict) and block.get("text"):
                                    title = str(block["text"])[:200]
                                    break
                        elif isinstance(c, str):
                            title = c[:200]
                        if title:
                            break
            except json.JSONDecodeError:
                return None
        else:  # .jsonl
            first_line = content.split("\n", 1)[0]
            try:
                meta = json.loads(first_line)
                session_id = meta.get("sessionId", "")
            except json.JSONDecodeError:
                pass
            # Parse lines for first user message
            for line in content.split("\n"):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("type") == "user":
                    c = entry.get("content", [])
                    if isinstance(c, list):
                        for block in c:
                            if isinstance(block, dict) and block.get("text"):
                                title = str(block["text"])[:200]
                                break
                    if title:
                        break

        if not session_id:
            session_id = short_hash

        last_modified = int(file_path.stat().st_mtime * 1000)

        return {
            "id": session_id,
            "name": title or name,
            "preview": title[:200],
            "last_modified": last_modified,
        }

    @staticmethod
    def _parse_gemini_json_session(content: str, thread_id: str, include_turns: bool) -> dict[str, Any]:
        import json

        data = json.loads(content)
        session_id = data.get("sessionId", thread_id)
        start_time = data.get("startTime", "")

        messages: list[dict[str, Any]] = []
        if include_turns:
            for msg in data.get("messages", []):
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                c = msg.get("content", "")
                text = ""
                if isinstance(c, list):
                    parts = []
                    for block in c:
                        if isinstance(block, dict) and block.get("text"):
                            parts.append(str(block["text"]))
                    text = "".join(parts)
                elif isinstance(c, str):
                    text = c
                messages.append({
                    "message_id": str(msg.get("id", "")),
                    "session_id": session_id,
                    "role": role,
                    "content": text,
                    "status": "completed",
                })

        return {
            "thread": {"id": session_id, "title": "", "created_at": start_time},
            "messages": messages,
        }

    @staticmethod
    def _parse_gemini_jsonl_session(content: str, thread_id: str, include_turns: bool) -> dict[str, Any]:
        import json

        session_id = thread_id
        start_time = ""

        messages: list[dict[str, Any]] = []
        for line in content.split("\n"):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            # First line: session metadata
            if "sessionId" in entry and "kind" in entry:
                session_id = entry.get("sessionId", thread_id)
                start_time = entry.get("startTime", "")
                continue
            # $set lines are metadata updates
            if "$set" in entry:
                continue
            entry_type = entry.get("type", "")
            if entry_type not in ("user", "assistant"):
                continue
            if not include_turns:
                continue
            c = entry.get("content", [])
            text = ""
            if isinstance(c, list):
                parts = []
                for block in c:
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(str(block["text"]))
                text = "".join(parts)
            elif isinstance(c, str):
                text = c
            messages.append({
                "message_id": entry.get("id", entry.get("uuid", "")),
                "session_id": session_id,
                "role": entry_type,
                "content": text,
                "status": "completed",
            })

        return {
            "thread": {"id": session_id, "title": "", "created_at": start_time},
            "messages": messages,
        }

    def thread_archive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"archived": True}

    def thread_unarchive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"unarchived": True}

    def thread_set_name(
        self,
        thread_id: str,
        name: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"renamed": True}


_DEFAULT_AGENT_SDK_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
    "WebSearch", "WebFetch", "Agent",
    "Task", "TaskOutput", "AskUserQuestion",
]


class AgentRunnerFactory:
    def __init__(self, codex_config_path: Path) -> None:
        self._codex_config_path = Path(codex_config_path)
        self._config_dir = self._codex_config_path.parent
        self._codex_model = self._read_model_from_config(codex_config_path)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_model_from_config(config_path: Path) -> str:
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    model = str(data.get("model", "") or "").strip()
                    if model:
                        return model
        except Exception:
            pass
        return "gpt-5.2"

    def _read_agent_config(self, agent_id: str) -> dict[str, Any]:
        """Read the agent-specific config file (provider/model/api_key/base_url)."""
        if agent_id == "codex":
            path = self._codex_config_path
        else:
            path = self._config_dir / f"{agent_id}_config.json"
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, backend: str) -> AgentRunner:
        b = str(backend or "").strip().lower()
        config = self._read_agent_config(b)
        if b == "hermes":
            return HermesRunner()
        if b == "codex":
            model = str(config.get("model", "") or "").strip() or self._codex_model
            return CodexRunner(codex_bin="codex", model=model, agent_config=config)
        if b == "claude_code":
            return ClaudeCodeRunner(config=config)
        if b == "gemini_cli":
            return GeminiCLIRunner(config=config)
        raise RuntimeError(f"agent_backend_invalid:{b}")
