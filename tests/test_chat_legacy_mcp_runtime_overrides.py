from __future__ import annotations

from kn_graph.services.chat_legacy import ChatService


def _service_with_config(config: dict) -> ChatService:
    return ChatService(
        literature_search_fn=lambda q, k, library_id="": {},
        graph_search_fn=lambda q, k: [],
        paper_get_fn=lambda paper_id: None,
        variable_get_fn=lambda variable_id: None,
        library_codex_config_resolver_fn=lambda workspace, library_id: config,
    )


def test_codex_runtime_overrides_fall_back_to_default_mcp_when_library_config_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "kn_graph.services.mcp_launch.default_mcp_server_command_and_args",
        lambda: ("kn_graph.exe", ["mcp-server"]),
    )
    service = _service_with_config({})

    overrides = service._build_codex_runtime_overrides("", "lib_a")

    assert overrides["mcp_servers"] == [
        {
            "name": "kn_graph_tools",
            "command": "kn_graph.exe",
            "args": ["mcp-server"],
            "env": {},
        }
    ]


def test_codex_runtime_overrides_keep_configured_mcp_servers(monkeypatch) -> None:
    monkeypatch.setattr(
        "kn_graph.services.mcp_launch.default_mcp_server_command_and_args",
        lambda: ("fallback.exe", ["mcp-server"]),
    )
    service = _service_with_config(
        {
            "mcp_servers": [
                {
                    "name": "custom",
                    "command": "custom.exe",
                    "args": ["serve-mcp"],
                    "env": {"A": "B"},
                }
            ]
        }
    )

    overrides = service._build_codex_runtime_overrides("D:/ws/lib_a", "lib_a")

    assert overrides["mcp_servers"] == [
        {
            "name": "custom",
            "command": "custom.exe",
            "args": ["serve-mcp"],
            "env": {"A": "B"},
        }
    ]
