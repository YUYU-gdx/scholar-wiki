(function () {
  "use strict";

  const LABELS = {
    newSession: "新会话",
    thinking: "思考中...",
    failed: "失败",
    unknownError: "unknown",
    defaultLibrary: "默认文献库"
  };

  const STAGE_LABELS = {
    ready: "就绪",
    rewrite: "正在整理问题",
    retrieve: "正在检索段落证据",
    generate: "正在生成回答",
    failed: "失败",
    done: "完成"
  };

  const LIBRARY_STORAGE_KEY = "kn_chat_selected_library_id";

  const els = {
    newSession: document.getElementById("new-session-btn"),
    settingsBtn: document.getElementById("provider-settings-btn"),
    sessionList: document.getElementById("session-list"),
    feed: document.getElementById("chat-feed"),
    librarySelect: document.getElementById("library-select"),
    prompt: document.getElementById("prompt-input"),
    send: document.getElementById("send-btn"),
    chatStatusStrip: document.getElementById("chat-status-strip"),

    settingsModal: document.getElementById("provider-modal"),
    settingsClose: document.getElementById("provider-modal-close"),
    saveConfigBtn: document.getElementById("save-provider-config-btn"),
    saveStatus: document.getElementById("provider-save-status"),
    codexHealthBtn: document.getElementById("codex-health-btn"),
    codexInstallBtn: document.getElementById("codex-install-btn"),
    codexCliCommand: document.getElementById("codex-cli-command"),
    codexCliArgs: document.getElementById("codex-cli-args"),
    codexHealthcheckArgs: document.getElementById("codex-healthcheck-args"),
    codexInstallCommand: document.getElementById("codex-install-command"),
    codexTimeoutSeconds: document.getElementById("codex-timeout-seconds"),
    codexExtraEnv: document.getElementById("codex-extra-env"),

    citationModal: document.getElementById("citation-modal"),
    citationModalClose: document.getElementById("citation-modal-close"),
    citationSentence: document.getElementById("citation-sentence"),
    citationParagraph: document.getElementById("citation-paragraph"),

    undoToast: document.getElementById("undo-toast"),
    undoToastText: document.getElementById("undo-toast-text"),
    undoDeleteBtn: document.getElementById("undo-delete-btn"),

    preflightModal: document.getElementById("preflight-modal"),
    preflightSummary: document.getElementById("preflight-summary"),
    preflightDetails: document.getElementById("preflight-details"),
    preflightClose: document.getElementById("preflight-modal-close"),
    preflightOk: document.getElementById("preflight-modal-ok")
  };

  let currentSessionId = "";
  let currentStream = null;
  let currentWatchTimer = null;
  let currentReconnectTimer = null;
  let isSending = false;
  let pendingDelete = null;

  function jfetch(url, options) {
    return fetch(
      url,
      Object.assign({ headers: { "Content-Type": "application/json" } }, options || {})
    ).then(async function (resp) {
      const payload = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        const msg = payload && payload.error ? payload.error : (payload && payload.reason ? payload.reason : "http_" + resp.status);
        throw new Error(msg);
      }
      return payload;
    });
  }

  function formatPreflightDetails(payload) {
    const checks = Array.isArray(payload && payload.checks) ? payload.checks : [];
    const lines = [];
    checks.forEach(function (item, idx) {
      const row = item && typeof item === "object" ? item : {};
      lines.push("[" + (idx + 1) + "] " + String(row.name || "check"));
      lines.push("  passed: " + (row.passed ? "true" : "false"));
      lines.push("  stage: " + String(row.stage || ""));
      lines.push("  code: " + String(row.code || ""));
      lines.push("  backend: " + String(row.backend || ""));
      if (row.detail) lines.push("  detail: " + String(row.detail));
      if (row.suggestion) lines.push("  suggestion: " + String(row.suggestion));
      lines.push("");
    });
    if (!lines.length) {
      lines.push("未收到检查明细。");
    }
    return lines.join("\n").trim();
  }

  function showPreflightModal(payload) {
    const summary = String((payload && payload.summary) || "preflight_failed").trim();
    els.preflightSummary.textContent = "Summary: " + summary;
    els.preflightDetails.textContent = formatPreflightDetails(payload || {});
    els.preflightModal.classList.remove("hidden");
  }

  function closePreflightModal() {
    els.preflightModal.classList.add("hidden");
  }

  function runPreflight(libraryId) {
    const url = "/chat/codex/preflight?library_id=" + encodeURIComponent(String(libraryId || "").trim());
    return fetch(url, { method: "GET" })
      .then(async function (resp) {
        const payload = await resp.json().catch(function () {
          return {};
        });
        if (!resp.ok) {
          const err = new Error("preflight_http_failed");
          err.payload = payload || {};
          throw err;
        }
        return payload || {};
      });
  }

  function fmtNow() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    return hh + ":" + mm + ":" + ss;
  }

  function setSendingState(next) {
    isSending = !!next;
    els.send.disabled = isSending;
    els.prompt.disabled = isSending;
  }

  function setChatStage(stage, detail) {
    const key = String(stage || "done");
    const base = STAGE_LABELS[key] || STAGE_LABELS.ready;
    const extra = String(detail || "").trim();
    if (key === "done") {
      els.chatStatusStrip.textContent = STAGE_LABELS.done;
      return;
    }
    if (key === "failed") {
      els.chatStatusStrip.textContent = extra ? (STAGE_LABELS.failed + ": " + extra) : STAGE_LABELS.failed;
      return;
    }
    els.chatStatusStrip.textContent = extra ? (base + " · " + extra) : base;
  }

  function getSelectedLibraryId() {
    return String((els.librarySelect && els.librarySelect.value) || "").trim();
  }

  function withLibraryQuery(url, libraryId) {
    const lib = String(libraryId || getSelectedLibraryId() || "").trim();
    if (!lib) return String(url || "");
    return String(url || "") + (String(url || "").indexOf("?") >= 0 ? "&" : "?") + "library_id=" + encodeURIComponent(lib);
  }

  function saveSelectedLibraryId(libraryId) {
    try {
      localStorage.setItem(LIBRARY_STORAGE_KEY, String(libraryId || "").trim());
    } catch (_err) {}
  }

  function renderLibraryOptions(libraries, defaultLibraryId) {
    const rows = Array.isArray(libraries) ? libraries : [];
    els.librarySelect.innerHTML = "";

    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = LABELS.defaultLibrary;
    els.librarySelect.appendChild(defaultOption);

    rows.forEach(function (item) {
      const option = document.createElement("option");
      option.value = String(item.library_id || "").trim();
      const count = Number(item.paper_count || 0);
      option.textContent = option.value + " (" + count + ")";
      els.librarySelect.appendChild(option);
    });

    let remembered = "";
    try {
      remembered = String(localStorage.getItem(LIBRARY_STORAGE_KEY) || "").trim();
    } catch (_err) {
      remembered = "";
    }
    const preferred = remembered || String(defaultLibraryId || "").trim();
    if (preferred) {
      const hit = rows.some(function (x) {
        return String(x.library_id || "").trim() === preferred;
      });
      els.librarySelect.value = hit ? preferred : "";
    }
    saveSelectedLibraryId(getSelectedLibraryId());
  }

  function loadLibraries() {
    return jfetch("/literature/libraries")
      .then(function (payload) {
        renderLibraryOptions(payload.libraries || [], payload.default_library_id || "");
      })
      .catch(function () {
        renderLibraryOptions([], "");
      });
  }

  function closeStream() {
    if (currentStream) {
      currentStream.close();
      currentStream = null;
    }
  }

  function stopReconnectTimer() {
    if (currentReconnectTimer) {
      window.clearTimeout(currentReconnectTimer);
      currentReconnectTimer = null;
    }
  }

  function stopCompletionWatch() {
    if (currentWatchTimer) {
      window.clearInterval(currentWatchTimer);
      currentWatchTimer = null;
    }
  }

  function addMessage(role, text, meta) {
    const row = document.createElement("div");
    row.className = "msg-row " + (role === "user" ? "user" : "assistant");

    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.textContent = role === "user" ? "U" : "AI";

    const node = document.createElement("div");
    node.className = "msg " + (role === "user" ? "msg-user" : "msg-assistant");
    node.setAttribute("data-testid", role === "user" ? "message-user" : "message-assistant");
    if (role === "assistant") {
      node.setAttribute("data-stream-status", "idle");
    }

    const content = document.createElement("div");
    content.className = "msg-content";
    content.textContent = text || "";
    node.appendChild(content);

    const metaRow = document.createElement("div");
    metaRow.className = "msg-meta-row";
    const metaEl = document.createElement("div");
    metaEl.className = "meta";
    metaEl.textContent = meta || "";
    const timeEl = document.createElement("div");
    timeEl.className = "msg-time";
    timeEl.textContent = fmtNow();
    metaRow.appendChild(metaEl);
    metaRow.appendChild(timeEl);
    node.appendChild(metaRow);

    if (role === "user") {
      row.appendChild(node);
      row.appendChild(avatar);
    } else {
      row.appendChild(avatar);
      row.appendChild(node);
    }

    els.feed.appendChild(row);
    els.feed.scrollTop = els.feed.scrollHeight;
    return node;
  }

  function openCitationModal(citation) {
    const c = citation && typeof citation === "object" ? citation : {};
    const context = c.context && typeof c.context === "object" ? c.context : {};
    const sentence = context.sentence && typeof context.sentence === "object" ? context.sentence : {};
    const paragraph = context.paragraph && typeof context.paragraph === "object" ? context.paragraph : {};
    const sentenceText = String(sentence.text || c.text || "未找到句子证据").trim();
    const paragraphText = String(paragraph.text || c.text || "未找到段落证据").trim();
    els.citationSentence.textContent = sentenceText;
    els.citationParagraph.textContent = paragraphText;
    els.citationModal.classList.remove("hidden");
  }

  function renderCitations(targetBubble, citations) {
    if (!Array.isArray(citations) || citations.length === 0) return;
    if (targetBubble.querySelector(".citation-drawer")) return;
    const drawer = document.createElement("details");
    drawer.className = "citation-drawer";
    const summary = document.createElement("summary");
    summary.setAttribute("data-testid", "message-citations");
    summary.textContent = "引用证据 (" + citations.length + ")";
    summary.addEventListener("click", function (evt) {
      evt.preventDefault();
      drawer.open = !drawer.open;
    });
    drawer.appendChild(summary);

    const list = document.createElement("div");
    list.className = "citation-list";
    citations.forEach(function (item, idx) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "citation-item-btn";
      try {
        btn.setAttribute("data-citation-payload", JSON.stringify(item || {}));
      } catch (_err) {}
      const title = String(item.title || item.id || item.paper_id || ("ref_" + (idx + 1))).trim();
      const snippet = String(item.text || "").trim().slice(0, 120);
      btn.innerHTML =
        '<div class="citation-item-title">[' + (idx + 1) + "] " + title + "</div>" +
        '<div class="citation-item-snippet">' + (snippet || "点击查看片段详情") + "</div>";
      btn.onclick = function () {
        openCitationModal(item);
      };
      list.appendChild(btn);
    });
    drawer.appendChild(list);
    targetBubble.appendChild(drawer);
  }

  function _safeStringify(value, fallback) {
    if (value === null || typeof value === "undefined") return fallback || "";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch (_err) {
      return fallback || String(value);
    }
  }

  function _clip(text, cap) {
    const s = String(text || "").trim();
    if (!s) return "";
    if (s.length <= cap) return s;
    return s.slice(0, cap) + "...";
  }

  function _cleanProcessText(text) {
    const s = String(text || "").trim();
    if (!s) return "";
    return s.replace(/\s+/g, " ").trim();
  }

  function _normalizeTraceEntry(raw, idx, eventType) {
    const item = raw && typeof raw === "object" ? raw : {};
    const backend = _cleanProcessText(item.backend || "") || "codex";
    const state = _cleanProcessText(item.state || "") || (eventType === "agent_item_started" ? "started" : "");
    const kind = _cleanProcessText(item.kind || "") || (eventType && eventType.indexOf("agent_item") === 0 ? "agent_item" : "tool");
    const stepId = String(item.step_id || item.id || item.tool || ("step_" + (idx + 1))).trim();
    const tool = _cleanProcessText(item.tool || "");
    const itemName = _cleanProcessText(item.item || "");
    const event = _cleanProcessText(item.event || eventType || "");
    const summary =
      _cleanProcessText(item.summary || "") ||
      _cleanProcessText(item.label || "") ||
      _cleanProcessText(item.text || "") ||
      (tool ? ("工具: " + tool) : "") ||
      (itemName ? ("项: " + itemName) : "");
    const outputSummary = _cleanProcessText(item.output_summary || item.output_excerpt || "");
    const argsPreview = _cleanProcessText(item.args_preview || "");
    const detail = _cleanProcessText(item.detail || "");
    return {
      traceKey: String(item.trace_key || stepId || ("trace_" + (idx + 1))).trim(),
      step_id: stepId,
      backend: backend,
      kind: kind,
      state: state,
      tool: tool,
      item: itemName,
      event: event,
      summary: _clip(summary, 280),
      output_summary: _clip(outputSummary, 320),
      args_preview: _clip(argsPreview, 280),
      detail: _clip(detail, 420)
    };
  }

  function _processLine(item, idx) {
    const row = item && typeof item === "object" ? item : {};
    const step = String(row.step_id || ("step_" + (idx + 1))).trim();
    const kind = String(row.kind || "").trim();
    const state = String(row.state || "").trim();
    const summary = _cleanProcessText(row.summary || row.output_summary || row.detail || "");
    const tags = [kind, state].filter(Boolean).join(" · ");
    const prefix = tags ? ("[" + tags + "] ") : "";
    return prefix + step + (summary ? (" - " + summary) : "");
  }

  function _ensureProcessStream(targetBubble) {
    let box = targetBubble.querySelector(".process-stream");
    if (box) return box;
    box = document.createElement("div");
    box.className = "process-stream";
    const list = document.createElement("div");
    list.className = "process-stream-list";
    box.appendChild(list);
    const content = targetBubble.querySelector(".msg-content");
    if (content && content.parentNode) {
      content.parentNode.insertBefore(box, content);
    } else {
      targetBubble.appendChild(box);
    }
    return box;
  }

  function _renderProcessRows(container, rows) {
    if (!container) return;
    const arr = Array.isArray(rows) ? rows : [];
    const list = container.querySelector(".process-stream-list");
    if (!list) return;
    list.innerHTML = "";
    arr.forEach(function (entry, idx) {
      const item = entry && typeof entry === "object" ? entry : {};
      const row = document.createElement("div");
      row.className = "process-stream-item";
      row.setAttribute("data-trace-state", String(item.state || "").trim() || "unknown");
      row.textContent = _processLine(item, idx);
      list.appendChild(row);
    });
  }

  function _buildMergedProcessSummary(rows) {
    const arr = Array.isArray(rows) ? rows : [];
    if (!arr.length) return "";
    const lines = arr.slice(0, 8).map(function (x, idx) {
      return (idx + 1) + ". " + _processLine(x, idx);
    });
    return "过程摘要：\n" + lines.join("\n");
  }

  function _mergeProcessIntoMessage(targetBubble, finalAnswer, rows) {
    const content = targetBubble.querySelector(".msg-content");
    if (!content) return;
    const summary = _buildMergedProcessSummary(rows);
    const answer = String(finalAnswer || "").trim();
    if (summary) {
      content.textContent = summary + (answer ? ("\n\n" + answer) : "");
    } else {
      content.textContent = answer;
    }
    const stream = targetBubble.querySelector(".process-stream");
    if (stream && stream.parentNode) {
      stream.parentNode.removeChild(stream);
    }
  }

  function renderToolTrace(targetBubble, toolTrace) {
    if (!Array.isArray(toolTrace) || toolTrace.length === 0) return;
    const drawer = _ensureProcessStream(targetBubble);
    const normalized = toolTrace.map(function (entry, idx) {
      return _normalizeTraceEntry(entry, idx, "tool_call");
    });
    _renderProcessRows(drawer, normalized);
  }

  function renderSessions(payload) {
    const sessions = Array.isArray(payload && payload.sessions) ? payload.sessions : [];
    els.sessionList.innerHTML = "";
    sessions.forEach(function (item) {
      const sid = String(item.session_id || "").trim();
      const row = document.createElement("div");
      row.className = "session-row";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "session-item" + (sid === currentSessionId ? " active" : "");
      btn.setAttribute("data-testid", "session-item");
      btn.textContent = String(item.title || LABELS.newSession);
      btn.onclick = function () {
        openSession(sid).catch(function () {});
      };

      const del = document.createElement("button");
      del.type = "button";
      del.className = "session-delete-btn";
      del.textContent = "✕";
      del.onclick = function (evt) {
        evt.stopPropagation();
        deleteSession(sid).catch(function () {});
      };

      row.appendChild(btn);
      row.appendChild(del);
      els.sessionList.appendChild(row);
    });
  }

  function refreshSessions() {
    return jfetch(withLibraryQuery("/chat/sessions")).then(function (payload) {
      renderSessions(payload || {});
      return payload || {};
    });
  }

  function openSession(sessionId) {
    const sid = String(sessionId || "").trim();
    if (!sid) return Promise.resolve();
    currentSessionId = sid;
    closeStream();
    stopReconnectTimer();
    stopCompletionWatch();
    return jfetch(withLibraryQuery("/chat/sessions/" + encodeURIComponent(sid))).then(function (payload) {
      els.feed.innerHTML = "";
      const messages = Array.isArray(payload.messages) ? payload.messages : [];
      messages.forEach(function (m) {
        const role = String(m.role || "assistant").toLowerCase() === "user" ? "user" : "assistant";
        const bubble = addMessage(role, String(m.content || ""));
        if (role === "assistant") {
          if (Array.isArray(m.citations) && m.citations.length) {
            renderCitations(bubble, m.citations);
          }
          if (Array.isArray(m.tool_trace) && m.tool_trace.length) {
            const normalizedHistoryTrace = m.tool_trace.map(function (entry, idx) {
              return _normalizeTraceEntry(entry, idx, "tool_call");
            });
            _mergeProcessIntoMessage(bubble, String(m.content || ""), normalizedHistoryTrace);
          }
          const status = String(m.status || "").toLowerCase();
          if (status === "completed") {
            bubble.setAttribute("data-stream-status", "completed");
          } else if (status === "failed") {
            bubble.setAttribute("data-stream-status", "failed");
          }
        }
      });
      renderSessions({ sessions: [payload.session].concat([]) });
      return refreshSessions();
    });
  }

  function createSession(title) {
    const libraryId = getSelectedLibraryId();
    if (!libraryId) return Promise.reject(new Error("library_id_required"));
    return jfetch("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: title || LABELS.newSession, default_mode: "agent", library_id: libraryId })
    }).then(function (payload) {
      const sid = String(payload.session_id || "").trim();
      return refreshSessions().then(function () {
        return openSession(sid);
      });
    });
  }

  function startUndoToast(sessionId, undoDeadlineIso) {
    if (pendingDelete && pendingDelete.timer) {
      window.clearTimeout(pendingDelete.timer);
    }
    const deadlineMs = Date.parse(String(undoDeadlineIso || ""));
    const now = Date.now();
    const ttl = Number.isFinite(deadlineMs) ? Math.max(1000, deadlineMs - now) : 5000;
    pendingDelete = {
      sessionId: String(sessionId || ""),
      timer: window.setTimeout(function () {
        els.undoToast.classList.add("hidden");
        pendingDelete = null;
      }, ttl)
    };
    els.undoToastText.textContent = "会话已删除";
    els.undoToast.classList.remove("hidden");
  }

  function deleteSession(sessionId) {
    const sid = String(sessionId || "").trim();
    if (!sid) return Promise.resolve();
    return fetch(withLibraryQuery("/chat/sessions/" + encodeURIComponent(sid)), { method: "DELETE" })
      .then(function (resp) {
        return resp.json().then(function (payload) {
          if (!resp.ok) throw new Error(payload.error || "delete_failed");
          return payload;
        });
      })
      .then(function (payload) {
        if (sid === currentSessionId) {
          currentSessionId = "";
          els.feed.innerHTML = "";
        }
        startUndoToast(sid, String(payload.undo_deadline || ""));
        return refreshSessions();
      });
  }

  function undoDeleteSession() {
    if (!pendingDelete || !pendingDelete.sessionId) return Promise.resolve();
    const sid = pendingDelete.sessionId;
    return jfetch(withLibraryQuery("/chat/sessions/" + encodeURIComponent(sid) + "/restore"), { method: "POST", body: "{}" })
      .then(function () {
        if (pendingDelete && pendingDelete.timer) {
          window.clearTimeout(pendingDelete.timer);
        }
        pendingDelete = null;
        els.undoToast.classList.add("hidden");
        return refreshSessions();
      });
  }

  function attachStream(streamUrl, assistantMessageId) {
    closeStream();
    stopReconnectTimer();
    stopCompletionWatch();

    const bubble = addMessage("assistant", LABELS.thinking);
    bubble.setAttribute("data-stream-status", "running");
    const content = bubble.querySelector(".msg-content");
    let acc = "";
    let buffer = "";
    let flushTimer = null;
    let reconnectAttempts = 0;
    let lastCursor = 0;
    let ended = false;
    const liveTraceRows = [];
    const liveTraceIndex = {};
    const liveProcessBox = _ensureProcessStream(bubble);

    function upsertLiveTrace(eventType, payload) {
      const normalized = _normalizeTraceEntry(payload, liveTraceRows.length, eventType);
      const key = String(normalized.traceKey || normalized.step_id || "").trim();
      if (!key) return;
      const existingIdx = Object.prototype.hasOwnProperty.call(liveTraceIndex, key) ? liveTraceIndex[key] : -1;
      if (existingIdx < 0) {
        liveTraceIndex[key] = liveTraceRows.length;
        liveTraceRows.push(normalized);
      } else {
        const prev = liveTraceRows[existingIdx];
        const merged = Object.assign({}, prev, normalized);
        if (eventType === "agent_item_delta") {
          const prevSummary = String(prev.summary || "").trim();
          const nextSummary = String(normalized.summary || "").trim();
          merged.summary = nextSummary || prevSummary;
          merged.detail = nextSummary || String(prev.detail || "").trim();
        }
        liveTraceRows[existingIdx] = merged;
      }
      _renderProcessRows(liveProcessBox, liveTraceRows);
    }

    function flushBuffer() {
      if (!buffer) return;
      acc += buffer;
      buffer = "";
      content.textContent = acc || LABELS.thinking;
      els.feed.scrollTop = els.feed.scrollHeight;
    }

    function scheduleFlush() {
      if (flushTimer) return;
      flushTimer = window.setTimeout(function () {
        flushTimer = null;
        flushBuffer();
      }, 60);
    }

    function finishCompleted(payload) {
      if (ended) return;
      ended = true;
      if (flushTimer) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
      flushBuffer();
      if (payload.answer) {
        content.textContent = payload.answer;
      }
      if (Array.isArray(payload.citations) && payload.citations.length) {
        renderCitations(bubble, payload.citations);
      }
      const persistedTrace = Array.isArray(payload.tool_trace) ? payload.tool_trace : [];
      const mergedTrace = persistedTrace.length
        ? persistedTrace.map(function (entry, idx) { return _normalizeTraceEntry(entry, idx, "tool_call"); })
        : liveTraceRows;
      _mergeProcessIntoMessage(bubble, payload.answer || acc, mergedTrace);
      bubble.setAttribute("data-stream-status", "completed");
      setChatStage("done", "");
      closeStream();
      stopReconnectTimer();
      stopCompletionWatch();
      setSendingState(false);
      refreshSessions().catch(function () {});
    }

    function normalizeFailure(errorPayload) {
      const payload = errorPayload && typeof errorPayload === "object" ? errorPayload : {};
      const rawText = typeof errorPayload === "string" ? errorPayload : String(payload.error || LABELS.unknownError);
      const text = String(rawText || "").trim() || LABELS.unknownError;
      let errorCode = String(payload.error_code || "").trim();
      if (!errorCode && text) {
        const m = text.match(/^([a-zA-Z0-9._-]+):/);
        if (m && m[1]) errorCode = m[1];
      }
      if (!errorCode) errorCode = text;
      const backend = String(payload.backend || "").trim();
      const detail = [backend, errorCode].filter(Boolean).join("/");
      return { text: text, errorCode: errorCode, backend: backend, detail: detail };
    }

    function finishFailed(errorPayload) {
      if (ended) return;
      ended = true;
      if (flushTimer) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
      const normalized = normalizeFailure(errorPayload);
      const text = normalized.text;
      const detail = normalized.detail;
      if (liveTraceRows.length) {
        _mergeProcessIntoMessage(
          bubble,
          LABELS.failed + ": " + (detail ? text + " [" + detail + "]" : text),
          liveTraceRows
        );
      } else {
        content.textContent = LABELS.failed + ": " + (detail ? text + " [" + detail + "]" : text);
      }
      bubble.setAttribute("data-stream-status", "failed");
      setChatStage("failed", detail ? (text + " [" + detail + "]") : text);
      closeStream();
      stopReconnectTimer();
      stopCompletionWatch();
      setSendingState(false);
    }

    function onCursor(payload) {
      const parsed = Number(payload.cursor);
      if (!Number.isNaN(parsed) && parsed > lastCursor) {
        lastCursor = parsed;
      }
    }

    function connectEventSource() {
      if (ended || !isSending) return;
      const sep = streamUrl.indexOf("?") >= 0 ? "&" : "?";
      const es = new EventSource(streamUrl + sep + "cursor=" + encodeURIComponent(String(lastCursor || 0)));
      currentStream = es;

      es.addEventListener("started", function () {
        setChatStage("rewrite", "");
      });

      es.addEventListener("status", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        const stage = String(payload.stage || "").trim() || "retrieve";
        const label = String(payload.label || "").trim();
        setChatStage(stage, label && label !== (STAGE_LABELS[stage] || "") ? label : "");
      });

      es.addEventListener("delta", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        const chunk = String(payload.text || "");
        if (chunk) {
          buffer += chunk;
          scheduleFlush();
        }
      });

      es.addEventListener("tool_call", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        upsertLiveTrace("tool_call", payload);
      });

      es.addEventListener("agent_item_started", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        upsertLiveTrace("agent_item_started", payload);
      });

      es.addEventListener("agent_item_delta", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        upsertLiveTrace("agent_item_delta", payload);
      });

      es.addEventListener("agent_item_completed", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        upsertLiveTrace("agent_item_completed", payload);
      });

      es.addEventListener("completed", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        onCursor(payload);
        finishCompleted(payload);
      });

      es.addEventListener("failed", function (evt) {
        finishFailed(JSON.parse(evt.data || "{}"));
      });

      es.onerror = function () {
        if (!isSending || ended) return;
        closeStream();
        if (reconnectAttempts < 4) {
          reconnectAttempts += 1;
          const delay = Math.min(1000 * reconnectAttempts, 4000);
          stopReconnectTimer();
          currentReconnectTimer = window.setTimeout(function () {
            connectEventSource();
          }, delay);
          return;
        }
        finishFailed("stream_disconnected");
      };
    }

    connectEventSource();

    if (assistantMessageId) {
      currentWatchTimer = window.setInterval(function () {
        if (!isSending || !currentSessionId) {
          stopCompletionWatch();
          return;
        }
        jfetch(withLibraryQuery("/chat/sessions/" + encodeURIComponent(currentSessionId)))
          .then(function (payload) {
            const messages = Array.isArray(payload.messages) ? payload.messages : [];
            const found = messages.find(function (m) {
              return String(m.message_id || "") === String(assistantMessageId);
            });
            if (!found) return;
            const status = String(found.status || "").toLowerCase();
            if (status === "completed") {
              finishCompleted({
                answer: found.content || "",
                citations: found.citations || [],
                tool_trace: found.tool_trace || []
              });
            } else if (status === "failed") {
              finishFailed({
                error: found.error_detail || LABELS.unknownError,
                error_code: found.error_code || "",
                backend: found.error_backend || ""
              });
            }
          })
          .catch(function () {});
      }, 1500);
    }
  }

  function send() {
    if (isSending) return Promise.resolve();
    const text = String(els.prompt.value || "").trim();
    if (!text) return Promise.resolve();
    const libraryId = getSelectedLibraryId();
    if (!libraryId) {
      addMessage("assistant", LABELS.failed + ": library_id_required");
      setChatStage("failed", "library_id_required");
      return Promise.resolve();
    }
    if (!currentSessionId) {
      return createSession(LABELS.newSession).then(function () {
        return send();
      });
    }

    setSendingState(true);
    setChatStage("retrieve", "发送前自检");
    return runPreflight(libraryId)
      .then(function (preflightPayload) {
        const preflight = preflightPayload && typeof preflightPayload === "object" ? preflightPayload : {};
        const severity = String(preflight.severity || (preflight.ok ? "ok" : "error")).trim().toLowerCase();
        if (severity === "error" || preflight.ok === false && !String(preflight.severity || "").trim()) {
          showPreflightModal(preflight);
          setChatStage("failed", String(preflight.summary || "preflight_failed"));
          setSendingState(false);
          return Promise.resolve();
        }
        if (severity === "warn") {
          showPreflightModal(preflight);
          setChatStage("retrieve", "自检告警，继续执行");
        }
        setChatStage("rewrite", "");
        Array.from(els.feed.querySelectorAll("[data-testid='message-assistant'][data-stream-status='completed'], [data-testid='message-assistant'][data-stream-status='failed']")).forEach(function (node) {
          node.setAttribute("data-stream-status", "history");
        });
        addMessage("user", text, "");
        els.prompt.value = "";

        return jfetch("/chat/sessions/" + encodeURIComponent(currentSessionId) + "/messages", {
          method: "POST",
          body: JSON.stringify({
            content: text,
            mode: "agent",
            stream: true,
            library_id: libraryId
          })
        })
          .then(function (payload) {
            attachStream(payload.stream_url, payload.assistant_message_id || "");
          });
      })
      .catch(function (err) {
        const payload = err && err.payload && typeof err.payload === "object" ? err.payload : null;
        if (payload) {
          showPreflightModal(payload);
          setChatStage("failed", String(payload.summary || "preflight_failed"));
        } else {
          addMessage("assistant", LABELS.failed + ": " + (err && err.message ? err.message : LABELS.unknownError));
          setChatStage("failed", err && err.message ? err.message : LABELS.unknownError);
        }
        setSendingState(false);
      });
  }

  function safeJsonParse(raw, fallback) {
    try {
      return JSON.parse(String(raw || "").trim() || JSON.stringify(fallback));
    } catch (_err) {
      return fallback;
    }
  }

  function setConfigStatus(text, isError) {
    els.saveStatus.textContent = text || "";
    els.saveStatus.style.color = isError ? "#f17b7b" : "";
  }

  function loadCodexConfig() {
    setConfigStatus("", false);
    return jfetch("/chat/codex/config").then(function (payload) {
      const cfg = payload.config || {};
      els.codexCliCommand.value = String(cfg.app_server_command || "");
      els.codexCliArgs.value = JSON.stringify(Array.isArray(cfg.app_server_args) ? cfg.app_server_args : [], null, 2);
      els.codexHealthcheckArgs.value = JSON.stringify(Array.isArray(cfg.healthcheck_args) ? cfg.healthcheck_args : [], null, 2);
      els.codexInstallCommand.value = String(cfg.install_command || "");
      els.codexTimeoutSeconds.value = String(Number(cfg.timeout_seconds || 180));
      els.codexExtraEnv.value = JSON.stringify(cfg.extra_env && typeof cfg.extra_env === "object" ? cfg.extra_env : {}, null, 2);
    });
  }

  function collectCodexConfig() {
    return {
      app_server_command: String(els.codexCliCommand.value || "").trim(),
      app_server_args: safeJsonParse(els.codexCliArgs.value, []),
      healthcheck_args: safeJsonParse(els.codexHealthcheckArgs.value, []),
      install_command: String(els.codexInstallCommand.value || "").trim(),
      timeout_seconds: Number(els.codexTimeoutSeconds.value || 180),
      extra_env: safeJsonParse(els.codexExtraEnv.value, {})
    };
  }

  function saveCodexConfig() {
    const payload = collectCodexConfig();
    return jfetch("/chat/codex/config", {
      method: "POST",
      body: JSON.stringify(payload)
    })
      .then(function () {
        setConfigStatus("配置已保存", false);
      })
      .catch(function (err) {
        setConfigStatus("保存失败: " + (err && err.message ? err.message : LABELS.unknownError), true);
      });
  }

  function runCodexHealth() {
    setConfigStatus("检测中...", false);
    return jfetch("/chat/codex/health")
      .then(function (payload) {
        const version = String(payload.version || "").trim();
        setConfigStatus(version ? ("Codex 可用: " + version) : "Codex 可用", false);
      })
      .catch(function (err) {
        setConfigStatus("Codex 不可用: " + (err && err.message ? err.message : LABELS.unknownError), true);
      });
  }

  function installCodex() {
    setConfigStatus("正在安装 Codex...", false);
    return jfetch("/chat/codex/install", { method: "POST", body: "{}" })
      .then(function (payload) {
        const out = String(payload.stdout || "").trim();
        setConfigStatus("安装完成" + (out ? (": " + out.slice(-120)) : ""), false);
      })
      .catch(function (err) {
        setConfigStatus("安装失败: " + (err && err.message ? err.message : LABELS.unknownError), true);
      });
  }

  function openSettingsModal() {
    window.location.href = "/frontend/chat/codex.html";
  }

  function closeSettingsModal() {
    els.settingsModal.classList.add("hidden");
  }

  els.newSession.onclick = function () {
    createSession(LABELS.newSession).catch(function (err) {
      addMessage("assistant", LABELS.failed + ": " + (err && err.message ? err.message : LABELS.unknownError));
      setChatStage("failed", err && err.message ? err.message : LABELS.unknownError);
    });
  };

  els.send.onclick = function () {
    send().catch(function () {
      setSendingState(false);
    });
  };

  els.prompt.onkeydown = function (evt) {
    if (evt.key === "Enter" && !evt.shiftKey) {
      evt.preventDefault();
      send().catch(function () {
        setSendingState(false);
      });
    }
  };

  els.settingsBtn.onclick = openSettingsModal;
  els.settingsClose.onclick = closeSettingsModal;
  els.settingsModal.addEventListener("click", function (evt) {
    if (evt.target === els.settingsModal) closeSettingsModal();
  });

  els.saveConfigBtn.onclick = function () {
    saveCodexConfig().catch(function () {});
  };
  if (els.codexHealthBtn) {
    els.codexHealthBtn.onclick = function () {
      runCodexHealth().catch(function () {});
    };
  }
  if (els.codexInstallBtn) {
    els.codexInstallBtn.onclick = function () {
      installCodex().catch(function () {});
    };
  }

  els.citationModalClose.onclick = function () {
    els.citationModal.classList.add("hidden");
  };
  els.citationModal.addEventListener("click", function (evt) {
    if (evt.target === els.citationModal) els.citationModal.classList.add("hidden");
  });

  els.preflightClose.onclick = closePreflightModal;
  els.preflightOk.onclick = closePreflightModal;
  els.preflightModal.addEventListener("click", function (evt) {
    if (evt.target === els.preflightModal) closePreflightModal();
  });

  els.undoDeleteBtn.onclick = function () {
    undoDeleteSession().catch(function () {});
  };

  els.feed.addEventListener("click", function (evt) {
    const target = evt.target && evt.target.closest ? evt.target.closest(".citation-item-btn") : null;
    if (!target) return;
    try {
      const raw = String(target.getAttribute("data-citation-payload") || "").trim();
      if (!raw) return;
      const payload = JSON.parse(raw);
      openCitationModal(payload);
    } catch (_err) {}
  });

  els.librarySelect.onchange = function () {
    saveSelectedLibraryId(getSelectedLibraryId());
    currentSessionId = "";
    els.feed.innerHTML = "";
    refreshSessions()
      .then(function (payload) {
        const sessions = Array.isArray(payload && payload.sessions) ? payload.sessions : [];
        if (sessions.length > 0) {
          return openSession(String(sessions[0].session_id || ""));
        }
        return createSession(LABELS.newSession);
      })
      .catch(function () {});
  };

  setChatStage("ready", "");
  loadLibraries()
    .then(function () {
      return refreshSessions();
    })
    .then(function (payload) {
      const sessions = Array.isArray(payload && payload.sessions) ? payload.sessions : [];
      if (sessions.length > 0) {
        return openSession(String(sessions[0].session_id || ""));
      }
      return createSession(LABELS.newSession);
    })
    .catch(function () {
      addMessage("assistant", "无法初始化聊天会话，请检查后端服务。", "");
      setChatStage("failed", "初始化失败");
    });
})();
