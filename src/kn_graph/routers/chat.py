from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from kn_graph.models.chat import (
    CreateSessionRequest,
    SendMessageRequest,
)
from kn_graph.services.chat_service import ChatService


def create_router(chat_service: ChatService) -> APIRouter:
    router = APIRouter(prefix="/chat", tags=["chat"])

    @router.get("/sessions")
    async def list_sessions(library_id: str = Query(default="")):
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        return chat_service.list_sessions(library_id=library_id)

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str, library_id: str = Query(default="")):
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        result = chat_service.get_session(session_id=session_id, library_id=library_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "session_not_found", "session_id": session_id})
        return result

    @router.post("/sessions")
    async def create_session(body: CreateSessionRequest):
        library_id = str(body.library_id or "").strip()
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        result = chat_service.create_session(title=body.title, library_id=library_id)
        return JSONResponse(status_code=201, content=result)

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, library_id: str = Query(default="")):
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        result = chat_service.delete_session(session_id=session_id, library_id=library_id)
        return result

    @router.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, body: SendMessageRequest):
        library_id = str(body.library_id or "").strip()
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        content = str(body.content or "").strip()
        if not content:
            return JSONResponse(status_code=400, content={"error": "content_required"})
        try:
            provider = str(body.provider or "codex").strip() or "codex"
            model = str(body.model or "").strip() or ("codex-local" if provider == "codex" else "")
            payload = chat_service.send_message(
                session_id=session_id,
                content=content,
                mode="agent",
                provider=provider,
                model=model,
                stream=body.stream,
                library_id=library_id,
            )
            return JSONResponse(
                status_code=202,
                content={
                    "session_id": session_id,
                    "assistant_message_id": payload.get("assistant_message_id"),
                    "user_message_id": payload.get("user_message_id"),
                    "stream_url": f"/chat/sessions/{session_id}/stream?message_id={payload.get('assistant_message_id', '')}",
                },
            )
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "session_not_found"})
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        except Exception as exc:
            detail = str(exc)
            error_code = detail.split(":", 1)[0] if ":" in detail else (detail or "chat_submit_failed")
            backend = "codex" if error_code.startswith("codex_") else ("hermes" if error_code.startswith("hermes_") else "")
            return JSONResponse(
                status_code=500,
                content={"error": "chat_submit_failed", "detail": detail, "error_code": error_code, "backend": backend},
            )

    @router.get("/sessions/{session_id}/stream")
    async def stream_session(session_id: str, message_id: str = Query(default=""), cursor: int = Query(default=0)):
        if not message_id:
            return JSONResponse(status_code=400, content={"error": "message_id_required"})

        async def event_generator():
            current_cursor = cursor
            for _ in range(240):
                rows, new_cursor, done = chat_service.read_events(
                    message_id=message_id, cursor=current_cursor,
                )
                for row in rows:
                    event_type = str(row.get("type", "delta") or "delta")
                    payload = {
                        "session_id": session_id,
                        "message_id": message_id,
                        "cursor": new_cursor,
                        **(row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}),
                    }
                    yield {"event": event_type, "data": json.dumps(payload, ensure_ascii=False)}
                current_cursor = new_cursor
                if done:
                    break
                yield {"event": "heartbeat", "data": "{}"}

        return EventSourceResponse(event_generator())

    @router.post("/sessions/{session_id}/restore")
    async def restore_session(session_id: str, library_id: str = Query(default="")):
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        result = chat_service.restore_session(session_id=session_id, library_id=library_id)
        if not isinstance(result, dict):
            return JSONResponse(status_code=500, content={"error": "chat_restore_failed"})
        if not bool(result.get("restored")):
            error = str(result.get("error", "restore_failed") or "restore_failed")
            status_code = 409 if error == "restore_window_expired" else 404
            return JSONResponse(status_code=status_code, content={"error": error, "session_id": session_id})
        return result

    @router.get("/codex/config")
    async def get_codex_config():
        config = chat_service.get_codex_config()
        return {"config": config}

    @router.post("/codex/config")
    async def save_codex_config(body: dict[str, Any]):
        saved = chat_service.save_codex_config(body)
        return {"ok": True, "config": saved}

    @router.get("/codex/health")
    async def check_codex_health():
        result = chat_service.check_codex_health()
        status_code = 200 if bool(result.get("available")) else 503
        return JSONResponse(status_code=status_code, content=result)

    @router.post("/codex/install")
    async def install_codex():
        config = chat_service.get_codex_config()
        install_cmd = str(config.get("install_command", "") or "").strip()
        if not install_cmd:
            return JSONResponse(status_code=400, content={"error": "codex_install_command_missing"})
        import subprocess
        import shlex
        try:
            proc = subprocess.run(
                shlex.split(install_cmd),
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
            )
            payload = {
                "ok": int(proc.returncode) == 0,
                "returncode": int(proc.returncode),
                "stdout": str(proc.stdout or "")[-4000:],
                "stderr": str(proc.stderr or "")[-4000:],
            }
            return JSONResponse(status_code=200 if payload["ok"] else 500, content=payload)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "codex_install_failed", "detail": str(exc)})

    @router.get("/codex/preflight")
    async def codex_preflight(library_id: str = Query(default="")):
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        from kn_graph.services.pipeline_service import PipelineService

        health_result = chat_service.check_codex_health()
        checks: list[dict[str, Any]] = []
        codex_check: dict[str, Any] = {
            "name": "codex_health",
            "passed": bool(health_result.get("available")),
            "stage": "codex_health",
            "backend": "codex",
        }
        if bool(health_result.get("available")):
            codex_check["code"] = "ok"
        else:
            codex_check["code"] = str(health_result.get("reason", "codex_unavailable") or "codex_unavailable")
            codex_check["suggestion"] = "确认 OpenAI 鉴权环境变量、Codex CLI 安装与网络可达性"
        codex_check["version"] = str(health_result.get("version", "") or "")
        codex_check["detail"] = json.dumps(health_result, ensure_ascii=False)
        checks.append(codex_check)

        workspace = chat_service._resolve_library_workspace(library_id)
        ws_check: dict[str, Any] = {
            "name": "workspace_path",
            "passed": False,
            "stage": "workspace_resolution",
            "backend": "builtin",
            "code": "workspace_path_missing",
            "detail": workspace or "",
        }
        if workspace:
            from pathlib import Path

            if Path(workspace).exists() and Path(workspace).is_dir():
                ws_check["passed"] = True
                ws_check["code"] = "ok"
            else:
                ws_check["suggestion"] = "请检查或重新配置 workspace 路径"
        checks.append(ws_check)

        lib_config = chat_service.get_library_codex_config(library_id)
        cfg_check: dict[str, Any] = {
            "name": "library_codex_config",
            "passed": False,
            "stage": "library_config",
            "backend": "builtin",
            "code": "library_codex_config_missing",
            "detail": "",
        }
        if isinstance(lib_config, dict) and str(lib_config.get("error", "")).strip():
            cfg_check["code"] = str(lib_config.get("error", "library_codex_config_missing"))
            cfg_check["detail"] = json.dumps(lib_config, ensure_ascii=False)
            cfg_check["suggestion"] = "请访问 /chat/codex/libraries/{library_id}/config 创建配置"
        else:
            cfg = lib_config if isinstance(lib_config, dict) else {}
            cfg_check["detail"] = json.dumps(cfg, ensure_ascii=False)[:1200]
            cfg_check["passed"] = True
            cfg_check["code"] = "ok"
        checks.append(cfg_check)

        from pathlib import Path
        import subprocess
        import sys

        mcp_check: dict[str, Any] = {
            "name": "mcp_rag_search_probe",
            "passed": False,
            "stage": "mcp_probe",
            "backend": "mcp",
            "code": "mcp_probe_failed",
            "detail": "",
        }
        probe_script = Path("scripts/smj_pipeline/mcp_probe.py")
        if not probe_script.exists():
            mcp_check["code"] = "mcp_probe_script_missing"
            mcp_check["detail"] = str(probe_script)
            mcp_check["suggestion"] = "确认 scripts/smj_pipeline/mcp_probe.py 已存在"
        else:
            base_url = f"http://127.0.0.1:8013"
            try:
                proc = subprocess.run(
                    [sys.executable, str(probe_script), "--api-base-url", base_url, "--library-id", library_id, "--query", "supply chain resilience", "--top-k", "1"],
                    cwd=str(Path(".").resolve()),
                    capture_output=True,
                    text=True,
                    timeout=35,
                    check=False,
                )
                out = str(proc.stdout or "").strip()
                err = str(proc.stderr or "").strip()
                mcp_check["detail"] = (out + ("\n" + err if err else "")).strip()[:2000]
                if int(proc.returncode) == 0:
                    mcp_check["passed"] = True
                    mcp_check["code"] = "ok"
                else:
                    mcp_check["code"] = f"mcp_probe_failed:{int(proc.returncode)}"
                    mcp_check["suggestion"] = "检查 kn_mcp_server、文献检索接口与 library_id 是否可用"
            except Exception as exc:
                mcp_check["code"] = "mcp_probe_exception"
                mcp_check["detail"] = str(exc)
                mcp_check["suggestion"] = "检查 Python 运行环境与 mcp_probe.py 可执行性"
        checks.append(mcp_check)

        critical_names = {"codex_health", "workspace_path", "library_codex_config"}
        failed = [x for x in checks if not bool(x.get("passed"))]
        warning_rows = [x for x in failed if str(x.get("name", "") or "").strip() not in critical_names]
        error_rows = [x for x in failed if str(x.get("name", "") or "").strip() in critical_names]
        if error_rows:
            severity = "error"
        elif warning_rows:
            severity = "warn"
        else:
            severity = "ok"
        ok = severity != "error"
        if severity == "ok":
            summary = "ok"
        elif severity == "warn":
            summary = "warn:" + ",".join(str(x.get("name", "")) for x in warning_rows)
        else:
            summary = "failed:" + ",".join(str(x.get("name", "")) for x in error_rows)
        from datetime import datetime, timezone

        for idx, row in enumerate(checks, start=1):
            name = str(row.get("name", "") or "").strip()
            row["check_id"] = f"preflight_{idx}_{name or 'check'}"
            if bool(row.get("passed")):
                row["severity"] = "ok"
            elif name in critical_names:
                row["severity"] = "error"
            else:
                row["severity"] = "warn"

        return {
            "ok": ok,
            "severity": severity,
            "library_id": library_id,
            "summary": summary,
            "checks": checks,
            "failed_count": len(failed),
            "warning_count": len(warning_rows),
            "error_count": len(error_rows),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @router.get("/codex/libraries/{library_id}/config")
    async def get_library_codex_config(library_id: str):
        result = chat_service.get_library_codex_config(library_id)
        if isinstance(result, dict) and str(result.get("error", "")).strip():
            code = str(result.get("error", "")).strip()
            status_code = 404 if code == "codex_workspace_path_missing" else 500
            return JSONResponse(status_code=status_code, content=result)
        return {"config": result}

    @router.post("/codex/libraries/{library_id}/config")
    async def save_library_codex_config(library_id: str, body: dict[str, Any]):
        result = chat_service.save_library_codex_config(library_id, body)
        if isinstance(result, dict) and str(result.get("error", "")).strip():
            code = str(result.get("error", "")).strip()
            status_code = 404 if code == "codex_workspace_path_missing" else 500
            return JSONResponse(status_code=status_code, content=result)
        return {"ok": True, "config": result}

    @router.post("/codex/libraries/{library_id}/skills/bootstrap")
    async def bootstrap_library_codex_skills(library_id: str):
        result = chat_service.bootstrap_library_codex_skills(library_id)
        if isinstance(result, dict) and str(result.get("error", "")).strip():
            code = str(result.get("error", "")).strip()
            status_code = 404 if code == "codex_workspace_path_missing" else 500
            return JSONResponse(status_code=status_code, content=result)
        return result

    @router.get("/provider-config")
    async def get_provider_config():
        result = chat_service.get_provider_config()
        return result

    @router.post("/provider-config")
    async def save_provider_config(body: dict[str, Any]):
        result = chat_service.update_provider_config(body)
        return {"ok": True, "config": result}

    @router.post("/provider-test")
    async def test_provider(body: dict[str, Any]):
        provider = str(body.get("provider", "") or "").strip().lower()
        if not provider:
            return JSONResponse(status_code=400, content={"error": "provider_required"})
        model = str(body.get("model", "") or "").strip()
        options = body.get("options", {})
        if not isinstance(options, dict):
            options = {}
        prompt = str(body.get("prompt", "") or "").strip() or "Reply with OK only."
        try:
            result = chat_service.test_provider(provider=provider, model=model, options=options, prompt=prompt)
            return result
        except Exception as exc:
            return JSONResponse(status_code=400, content={"error": "provider_test_failed", "detail": str(exc)})

    return router
