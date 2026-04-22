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
    undoDeleteBtn: document.getElementById("undo-delete-btn")
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
    drawer.appendChild(summary);

    const list = document.createElement("div");
    list.className = "citation-list";
    citations.forEach(function (item, idx) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "citation-item-btn";
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

  function renderToolTrace(targetBubble, toolTrace) {
    if (!Array.isArray(toolTrace) || toolTrace.length === 0) return;
    if (targetBubble.querySelector(".tool-trace-drawer")) return;

    const drawer = document.createElement("details");
    drawer.className = "tool-trace-drawer";

    const summary = document.createElement("summary");
    summary.className = "tool-trace-summary";
    summary.textContent = "执行轨迹 (" + toolTrace.length + ")";
    drawer.appendChild(summary);

    const list = document.createElement("div");
    list.className = "tool-trace-list";

    toolTrace.forEach(function (entry, idx) {
      const item = entry && typeof entry === "object" ? entry : {};
      const row = document.createElement("div");
      row.className = "tool-trace-item";
      const header = document.createElement("div");
      header.className = "tool-trace-item-header";
      const stepName = String(item.step_id || item.tool || ("step_" + (idx + 1))).trim();
      const status = [String(item.backend || "").trim(), String(item.state || "").trim()].filter(Boolean).join(" · ");
      header.textContent = status ? (stepName + " (" + status + ")") : stepName;
      row.appendChild(header);

      const summaryText = String(item.summary || "").trim();
      if (summaryText) {
        const s = document.createElement("div");
        s.className = "tool-trace-item-summary";
        s.textContent = summaryText;
        row.appendChild(s);
      }

      const outputText = String(item.output_summary || item.output_excerpt || "").trim();
      if (outputText) {
        const o = document.createElement("div");
        o.className = "tool-trace-item-output";
        o.textContent = outputText;
        row.appendChild(o);
      }
      list.appendChild(row);
    });

    drawer.appendChild(list);
    targetBubble.appendChild(drawer);
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
    return jfetch("/chat/sessions").then(function (payload) {
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
    return jfetch("/chat/sessions/" + encodeURIComponent(sid)).then(function (payload) {
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
            renderToolTrace(bubble, m.tool_trace);
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
    return jfetch("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: title || LABELS.newSession, default_mode: "agent" })
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
    return fetch("/chat/sessions/" + encodeURIComponent(sid), { method: "DELETE" })
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
    return jfetch("/chat/sessions/" + encodeURIComponent(sid) + "/restore", { method: "POST", body: "{}" })
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
    const liveTrace = [];

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
      const mergedTrace = persistedTrace.length ? persistedTrace : liveTrace;
      if (mergedTrace.length) {
        renderToolTrace(bubble, mergedTrace);
      }
      bubble.setAttribute("data-stream-status", "completed");
      setChatStage("done", "");
      closeStream();
      stopReconnectTimer();
      stopCompletionWatch();
      setSendingState(false);
      refreshSessions().catch(function () {});
    }

    function finishFailed(errorPayload) {
      if (ended) return;
      ended = true;
      if (flushTimer) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
      const payload = errorPayload && typeof errorPayload === "object" ? errorPayload : {};
      const errorCode = String(payload.error_code || "").trim();
      const backend = String(payload.backend || "").trim();
      const text = typeof errorPayload === "string" ? errorPayload : String(payload.error || LABELS.unknownError);
      const detail = [backend, errorCode].filter(Boolean).join("/");
      content.textContent = LABELS.failed + ": " + (detail ? text + " [" + detail + "]" : text);
      bubble.setAttribute("data-stream-status", "failed");
      setChatStage("failed", text);
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
        liveTrace.push(payload);
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
        jfetch("/chat/sessions/" + encodeURIComponent(currentSessionId))
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
              finishFailed({ error: found.error_detail || LABELS.unknownError });
            }
          })
          .catch(function () {});
      }, 1500);
    }
  }

  function send() {
    if (!currentSessionId || isSending) return Promise.resolve();
    const text = String(els.prompt.value || "").trim();
    if (!text) return Promise.resolve();

    setSendingState(true);
    setChatStage("rewrite", "");
    addMessage("user", text, "");
    els.prompt.value = "";

    return jfetch("/chat/sessions/" + encodeURIComponent(currentSessionId) + "/messages", {
      method: "POST",
      body: JSON.stringify({
        content: text,
        mode: "agent",
        stream: true,
        library_id: getSelectedLibraryId()
      })
    })
      .then(function (payload) {
        attachStream(payload.stream_url, payload.assistant_message_id || "");
      })
      .catch(function (err) {
        addMessage("assistant", LABELS.failed + ": " + (err && err.message ? err.message : LABELS.unknownError));
        setChatStage("failed", err && err.message ? err.message : LABELS.unknownError);
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
      els.codexCliCommand.value = String(cfg.cli_command || "");
      els.codexCliArgs.value = JSON.stringify(Array.isArray(cfg.cli_args) ? cfg.cli_args : [], null, 2);
      els.codexHealthcheckArgs.value = JSON.stringify(Array.isArray(cfg.healthcheck_args) ? cfg.healthcheck_args : [], null, 2);
      els.codexInstallCommand.value = String(cfg.install_command || "");
      els.codexTimeoutSeconds.value = String(Number(cfg.timeout_seconds || 180));
      els.codexExtraEnv.value = JSON.stringify(cfg.extra_env && typeof cfg.extra_env === "object" ? cfg.extra_env : {}, null, 2);
    });
  }

  function collectCodexConfig() {
    return {
      cli_command: String(els.codexCliCommand.value || "").trim(),
      cli_args: safeJsonParse(els.codexCliArgs.value, []),
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

  els.undoDeleteBtn.onclick = function () {
    undoDeleteSession().catch(function () {});
  };

  els.librarySelect.onchange = function () {
    saveSelectedLibraryId(getSelectedLibraryId());
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
