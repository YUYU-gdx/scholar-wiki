# Graph + Chat Behavior Matrix

## Scope
- Page scope: `/frontend/` (graph) and `/frontend/chat/` (chat)
- Chain scope: graph page load -> graph interaction -> jump to chat -> send message -> SSE terminal -> citation rendering -> return to graph -> error handling
- Data scope: deterministic local fixture only (no online dependency)

## User Behavior Matrix

| ID | User Behavior | Trigger | Expected UI | Expected API/Protocol | Test Case |
|---|---|---|---|---|---|
| B01 | Open graph entry page | Visit `/frontend/` | 3D graph container visible; status appears | `GET /graph/overview` returns fixture nodes/edges | `test_graph_page_load_and_click_jump_to_chat` |
| B02 | 3D interaction: hover node | Move pointer over node chip | Node style changes / status text updates to hovered node | None (frontend local state) | `test_graph_page_hover_and_drag_interaction` |
| B03 | 3D interaction: drag canvas | Drag on graph viewport | Drag state text changes and persists when pointer up | None (frontend local state) | `test_graph_page_hover_and_drag_interaction` |
| B04 | 3D interaction: click node | Click variable node | Selection status updates; chat button enabled | None (frontend local state) | `test_graph_page_load_and_click_jump_to_chat` |
| B05 | Jump to chat from graph | Click CTA in graph page | Browser navigates to `/frontend/chat/?from_node=<id>` | `GET /frontend/chat/` static route served | `test_graph_page_load_and_click_jump_to_chat` |
| B06 | Chat bootstraps session | Chat page auto initializes | Session list and first session rendered | `POST /chat/sessions`, `GET /chat/sessions/{id}` | `test_chat_send_message_sse_completed_and_citations` |
| B07 | Send user message | Type + click send | User bubble appears; assistant enters thinking state | `POST /chat/sessions/{id}/messages` with `stream=true` | `test_chat_send_message_sse_completed_and_citations` |
| B08 | SSE completed terminal | Assistant stream emits completion | Assistant final answer replaces thinking state | `GET /chat/sessions/{id}/stream?...` receives `started/delta/completed` | `test_chat_send_message_sse_completed_and_citations` |
| B09 | Citation rendering | Completed payload contains citations | Citation meta line rendered in assistant bubble | SSE `completed` payload includes `citations[]` | `test_chat_send_message_sse_completed_and_citations` |
| B10 | Return to graph | Click "返回变量搜索" | Browser returns `/frontend/` page | `GET /frontend/` static route served | `test_return_to_graph_from_chat` |
| B11 | SSE failed terminal (exception flow) | Send trigger message for failure | Assistant bubble shows `失败: <reason>` | SSE emits `started/failed` terminal event | `test_chat_sse_failed_terminal_event` |
| B12 | Chat API request error (exception flow) | Send blank/invalid content | Error bubble rendered and send unlocked | `POST /chat/sessions/{id}/messages` returns `400 content_required` | `test_chat_request_validation_error_flow` |

## Coverage Notes
- At least one required graph interaction is covered via both `hover` and `drag`.
- End-to-end chat path explicitly verifies SSE terminal states (`completed` and `failed`) and citation UI rendering.
- All tests run against an in-process test server with deterministic fixture graph views and fake chat service.
