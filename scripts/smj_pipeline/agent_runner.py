from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import time
from typing import Any, Callable


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

    def __init__(self, codex_bin: str = "codex", model: str = "gpt-5.2") -> None:
        self._codex_bin = codex_bin
        self._model = model

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

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig
        from codex_app_server.generated.v2_all import AgentMessageDeltaNotification

        overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
        mcp_cfg_path = self._write_mcp_config(workdir, library_id, overrides)
        config_overrides: list[str] = []
        if mcp_cfg_path is not None:
            config_overrides.append(f"mcp_servers_file=\"{mcp_cfg_path}\"")

        env = dict(os.environ)
        codex_home = str(overrides.get("codex_home", "") or "").strip()
        if codex_home:
            env["CODEX_HOME"] = str(Path(codex_home).resolve())

        sdk_config = AppServerConfig(
            codex_bin=self._codex_bin,
            config_overrides=tuple(config_overrides),
            cwd=workdir,
            env=env,
            client_name="kn_graph_chat",
            client_title="KN Graph Chat",
        )

        answer_chunks: list[str] = []
        final_answer = ""
        resolved_thread_id = ""

        with Codex(config=sdk_config) as codex:
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

            turn = thread.turn(
                input=query,
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
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig

        overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
        mcp_cfg_path = self._write_mcp_config(workdir, library_id, overrides)
        config_overrides: list[str] = []
        if mcp_cfg_path is not None:
            config_overrides.append(f"mcp_servers_file=\"{mcp_cfg_path}\"")

        with Codex(
            config=AppServerConfig(
                codex_bin=self._codex_bin,
                config_overrides=tuple(config_overrides),
                cwd=workdir,
            )
        ) as codex:
            t = codex.thread_start(model=self._model, cwd=workdir, personality="pragmatic")
            return {"thread": {"id": t.id}}

    def thread_list(
        self,
        workdir: str,
        archived: bool = False,
        limit: int = 100,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig

        with Codex(config=AppServerConfig(codex_bin=self._codex_bin, cwd=workdir)) as codex:
            resp = codex.thread_list(cwd=workdir, limit=limit)
            return {
                "data": [
                    {"id": t.id, "name": getattr(t, "name", "")}
                    for t in (resp.threads if hasattr(resp, "threads") else [])
                ]
            }

    def thread_read(
        self,
        thread_id: str,
        workdir: str,
        include_turns: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig

        with Codex(config=AppServerConfig(codex_bin=self._codex_bin, cwd=workdir)) as codex:
            thread = codex.thread_resume(thread_id, model=self._model, cwd=workdir)
            resp = thread.read(include_turns=include_turns)
            return resp.model_dump() if hasattr(resp, "model_dump") else {"thread": {"id": thread_id}}

    def thread_archive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig

        with Codex(config=AppServerConfig(codex_bin=self._codex_bin, cwd=workdir)) as codex:
            codex.thread_archive(thread_id)
            return {"archived": True}

    def thread_unarchive(
        self,
        thread_id: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig

        with Codex(config=AppServerConfig(codex_bin=self._codex_bin, cwd=workdir)) as codex:
            t = codex.thread_unarchive(thread_id)
            return {"thread": {"id": t.id}}

    def thread_set_name(
        self,
        thread_id: str,
        name: str,
        workdir: str,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from codex_app_server import Codex, AppServerConfig

        with Codex(config=AppServerConfig(codex_bin=self._codex_bin, cwd=workdir)) as codex:
            thread = codex.thread_resume(thread_id, model=self._model, cwd=workdir)
            thread.set_name(name)
            return {"renamed": True}

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

        async def _run() -> dict[str, Any]:
            answer_chunks: list[str] = []
            final_answer = ""
            session_id = ""
            tool_steps: dict[str, dict[str, Any]] = {}

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
            )
            if thread_id:
                options.resume = thread_id

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
                        raise RuntimeError(
                            f"agent_backend_unavailable:claude_code:{';'.join(errs)}"
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
                raise RuntimeError("agent_backend_unavailable:claude_code:empty_output")
            return {
                "answer": final_answer,
                "thread_id": session_id,
                "turn_id": session_id,
            }

        return asyncio.run(_run())

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
        # Session is created lazily in run_turn; return a reserved ID.
        import uuid

        tid = f"cc_{uuid.uuid4().hex}"
        return {"thread": {"id": tid}}

    def thread_list(
        self,
        workdir: str,
        archived: bool = False,
        limit: int = 100,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            import asyncio
            from claude_agent_sdk import list_sessions_from_store, InMemorySessionStore
        except ImportError:
            return {"data": []}
        store = InMemorySessionStore()
        sessions = asyncio.run(
            list_sessions_from_store(store=store, limit=min(limit, 200))
        )
        return {"data": [{"id": s.get("id", ""), "name": s.get("summary", "")} for s in sessions]}

    def thread_read(
        self,
        thread_id: str,
        workdir: str,
        include_turns: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"thread": {"id": thread_id}}

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


_DEFAULT_AGENT_SDK_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
    "WebSearch", "WebFetch", "Agent",
    "Task", "TaskOutput", "AskUserQuestion",
]


class AgentRunnerFactory:
    def __init__(self, codex_config_path: Path) -> None:
        self._codex_config_path = Path(codex_config_path)
        self._codex_model = self._read_model_from_config(codex_config_path)

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

    def build(self, backend: str) -> AgentRunner:
        b = str(backend or "").strip().lower()
        if b == "hermes":
            return HermesRunner()
        if b == "codex":
            return CodexRunner(codex_bin="codex", model=self._codex_model)
        if b == "claude_code":
            return ClaudeCodeRunner()
        raise RuntimeError(f"agent_backend_invalid:{b}")
