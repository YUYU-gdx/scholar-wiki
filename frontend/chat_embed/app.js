(function () {
  "use strict";

  const FALLBACK_PROVIDER_CONFIG = {
    default_provider: "zhipu",
    providers: [
      {
        id: "zhipu",
        type: "zhipu",
        aliases: ["glm"],
        api_key_env: "ZHIPU_API_KEY",
        default_model: "glm-4.5-flash",
        models: ["glm-4.5-flash", "glm-4.5", "glm-4.5-air"],
        base_url: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        timeout_seconds: 120
      },
      {
        id: "deepseek",
        type: "openai_compatible",
        aliases: [],
        api_key_env: "DEEPSEEK_API_KEY",
        default_model: "deepseek-chat",
        models: ["deepseek-chat", "deepseek-reasoner"],
        base_url: "https://api.deepseek.com/v1/chat/completions",
        timeout_seconds: 90
      }
    ]
  };

  const labels = {
    newSession: "鏂颁細璇?,
    thinking: "鎬濊€冧腑...",
    failed: "澶辫触",
    unknownError: "unknown",
    statusPrefix: "鐘舵€?,
    citationPrefix: "寮曠敤"
  };

  const els = {
    newSession: document.getElementById("new-session-btn"),
    providerSettingsBtn: document.getElementById("provider-settings-btn"),
    sessionList: document.getElementById("session-list"),
    feed: document.getElementById("chat-feed"),
    mode: document.getElementById("mode-select"),
    provider: document.getElementById("provider-select"),
    modelSelect: document.getElementById("model-select"),
    modelInput: document.getElementById("model-input"),
    prompt: document.getElementById("prompt-input"),
    send: document.getElementById("send-btn"),
    providerModal: document.getElementById("provider-modal"),
    providerModalClose: document.getElementById("provider-modal-close"),
    defaultProviderSelect: document.getElementById("default-provider-select"),
    providerRows: document.getElementById("provider-rows"),
    addProviderBtn: document.getElementById("add-provider-btn"),
    saveProviderConfigBtn: document.getElementById("save-provider-config-btn"),
    providerSaveStatus: document.getElementById("provider-save-status")
  };

  let currentSessionId = "";
  let currentStream = null;
  let currentWatchTimer = null;
  let currentReconnectTimer = null;
  let isSending = false;
  let providerConfig = JSON.parse(JSON.stringify(FALLBACK_PROVIDER_CONFIG));

  function setSendingState(next) {
    isSending = !!next;
    els.send.disabled = isSending;
  }

  async function jfetch(url, options) {
    const resp = await fetch(
      url,
      Object.assign({ headers: { "Content-Type": "application/json" } }, options || {})
    );
    const payload = await resp.json().catch(function () {
      return {};
    });
    if (!resp.ok) {
      throw new Error(payload.error || ("http_" + resp.status));
    }
    return payload;
  }

  function splitCsv(raw) {
    return String(raw || "")
      .split(",")
      .map(function (x) {
        return x.trim();
      })
      .filter(Boolean);
  }

  function sanitizeProviderItem(item) {
    const out = Object.assign({}, item || {});
    out.id = String(out.id || "").trim().toLowerCase();
    out.type = String(out.type || "openai_compatible").trim().toLowerCase();
    out.aliases = splitCsv(Array.isArray(out.aliases) ? out.aliases.join(",") : out.aliases).map(function (v) {
      return v.toLowerCase();
    });
    out.api_key_env = String(out.api_key_env || "").trim();
    out.default_model = String(out.default_model || "").trim();
    out.models = splitCsv(Array.isArray(out.models) ? out.models.join(",") : out.models);
    if (out.default_model && out.models.indexOf(out.default_model) < 0) {
      out.models.unshift(out.default_model);
    }
    if (!out.default_model && out.models.length > 0) {
      out.default_model = out.models[0];
    }
    out.base_url = String(out.base_url || "").trim();
    out.timeout_seconds = Number(out.timeout_seconds || 90);
    if (!Number.isFinite(out.timeout_seconds) || out.timeout_seconds <= 0) {
      out.timeout_seconds = 90;
    }
    return out;
  }

  function sanitizeProviderConfig(payload) {
    const rawProviders = Array.isArray(payload && payload.providers) ? payload.providers : [];
    const providers = rawProviders.map(sanitizeProviderItem).filter(function (x) {
      return !!x.id;
    });
    const fallback = JSON.parse(JSON.stringify(FALLBACK_PROVIDER_CONFIG));
    const next = {
      default_provider: String((payload && payload.default_provider) || "").trim().toLowerCase(),
      providers: providers.length ? providers : fallback.providers
    };
    if (!next.default_provider) {
      next.default_provider = next.providers[0] ? next.providers[0].id : "zhipu";
    }
    const knownIds = new Set(
      next.providers.map(function (p) {
        return p.id;
      })
    );
    if (!knownIds.has(next.default_provider)) {
      next.default_provider = next.providers[0] ? next.providers[0].id : "zhipu";
    }
    return next;
  }

  function findProviderItem(providerId) {
    const id = String(providerId || "").trim().toLowerCase();
    return (providerConfig.providers || []).find(function (p) {
      if (p.id === id) {
        return true;
      }
      return Array.isArray(p.aliases) && p.aliases.indexOf(id) >= 0;
    });
  }

  function getDefaultModelByProvider(providerId) {
    const hit = findProviderItem(providerId);
    return hit && hit.default_model ? hit.default_model : "glm-4.5-flash";
  }

  function refreshModelSelector() {
    const providerId = String(els.provider.value || "").trim().toLowerCase();
    const item = findProviderItem(providerId);
    const selected = String(els.modelSelect.value || "").trim();
    const customValue = String(els.modelInput.value || "").trim();
    const models = item && Array.isArray(item.models) ? item.models : [];
    const nextDefault = item && item.default_model ? item.default_model : "";

    els.modelSelect.innerHTML = "";
    models.forEach(function (model) {
      const option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      els.modelSelect.appendChild(option);
    });
    const customOption = document.createElement("option");
    customOption.value = "__custom__";
    customOption.textContent = "鑷畾涔夋ā鍨?;
    els.modelSelect.appendChild(customOption);

    if (selected && models.indexOf(selected) >= 0) {
      els.modelSelect.value = selected;
      els.modelInput.classList.add("hidden");
      return;
    }

    if (customValue && models.indexOf(customValue) < 0) {
      els.modelSelect.value = "__custom__";
      els.modelInput.classList.remove("hidden");
      return;
    }

    if (nextDefault && models.indexOf(nextDefault) >= 0) {
      els.modelSelect.value = nextDefault;
      els.modelInput.value = "";
      els.modelInput.classList.add("hidden");
      return;
    }

    if (models.length > 0) {
      els.modelSelect.value = models[0];
      els.modelInput.value = "";
      els.modelInput.classList.add("hidden");
      return;
    }

    els.modelSelect.value = "__custom__";
    els.modelInput.classList.remove("hidden");
    if (!els.modelInput.value) {
      els.modelInput.value = "custom-model";
    }
  }

  function getSelectedModel() {
    if (els.modelSelect.value === "__custom__") {
      return String(els.modelInput.value || "").trim();
    }
    return String(els.modelSelect.value || "").trim();
  }

  function refreshProviderSelectOptions() {
    const selected = String(els.provider.value || "").trim().toLowerCase();
    els.provider.innerHTML = "";
    (providerConfig.providers || []).forEach(function (item) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.id + " (" + item.type + ")";
      els.provider.appendChild(option);
    });
    const currentIds = new Set(
      (providerConfig.providers || []).map(function (p) {
        return p.id;
      })
    );
    if (selected && currentIds.has(selected)) {
      els.provider.value = selected;
    } else {
      els.provider.value = providerConfig.default_provider || "";
    }
    refreshModelSelector();
  }

  async function loadProviderConfig() {
    try {
      const payload = await jfetch("/chat/provider-config");
      providerConfig = sanitizeProviderConfig(payload);
    } catch (err) {
      console.warn("load provider config failed, fallback to local defaults", err);
      providerConfig = JSON.parse(JSON.stringify(FALLBACK_PROVIDER_CONFIG));
    }
    refreshProviderSelectOptions();
  }

  function setProviderSaveStatus(text, isError) {
    els.providerSaveStatus.textContent = text || "";
    els.providerSaveStatus.style.color = isError ? "#f07178" : "";
  }

  function addMessage(role, text, meta) {
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

    if (meta) {
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      node.appendChild(m);
    }

    els.feed.appendChild(node);
    els.feed.scrollTop = els.feed.scrollHeight;
    return node;
  }

  function renderSessions(items) {
    els.sessionList.innerHTML = "";
    (items || []).forEach(function (s) {
      const div = document.createElement("button");
      div.type = "button";
      div.className = "session-item" + (s.session_id === currentSessionId ? " active" : "");
      div.setAttribute("data-testid", "session-item");
      div.setAttribute("data-session-id", s.session_id || "");
      div.textContent = (s.title || labels.newSession) + " (" + (s.default_mode || "fast") + ")";
      div.onclick = function () {
        openSession(s.session_id).catch(function (err) {
          console.error(err);
        });
      };
      els.sessionList.appendChild(div);
    });
  }

  async function refreshSessions() {
    const payload = await jfetch("/chat/sessions");
    renderSessions(payload.sessions || []);
  }

  async function createSession(title) {
    const payload = await jfetch("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: title || labels.newSession, default_mode: "fast" })
    });
    currentSessionId = payload.session_id || "";
    await refreshSessions();
    await openSession(currentSessionId);
  }

  async function openSession(sessionId) {
    currentSessionId = sessionId;
    await refreshSessions();
    els.feed.innerHTML = "";
    const payload = await jfetch("/chat/sessions/" + encodeURIComponent(sessionId));
    const msgs = payload.messages || [];
    msgs.forEach(function (m) {
      const meta = m.role === "assistant" && m.status ? (labels.statusPrefix + ": " + m.status) : "";
      addMessage(m.role || "assistant", m.content || "", meta);
    });
    if (payload.session && payload.session.default_mode) {
      els.mode.value = payload.session.default_mode;
    }
  }

  function closeStream() {
    if (!currentStream) {
      return;
    }
    currentStream.close();
    currentStream = null;
  }

  function stopReconnectTimer() {
    if (currentReconnectTimer) {
      clearTimeout(currentReconnectTimer);
      currentReconnectTimer = null;
    }
  }

  function stopCompletionWatch() {
    if (currentWatchTimer) {
      clearInterval(currentWatchTimer);
      currentWatchTimer = null;
    }
  }

  function renderCitations(targetBubble, citations) {
    if (!citations || !citations.length) {
      return;
    }
    if (targetBubble.querySelector("[data-testid='message-citations']")) {
      return;
    }
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.setAttribute("data-testid", "message-citations");
    meta.textContent =
      labels.citationPrefix +
      ": " +
      citations
        .map(function (c, i) {
          return "[" + (i + 1) + "]" + (c.id || c.paper_id || "璇佹嵁");
        })
        .join("  ");
    targetBubble.appendChild(meta);
  }

  function attachStream(streamUrl, assistantMessageId) {
    closeStream();
    stopReconnectTimer();
    stopCompletionWatch();
    const bubble = addMessage("assistant", labels.thinking);
    bubble.setAttribute("data-stream-status", "running");
    const content = bubble.querySelector(".msg-content");
    let acc = "";
    let reconnectAttempts = 0;
    const maxReconnects = 4;
    let lastCursor = 0;
    let ended = false;

    function finishCompleted(payload) {
      if (ended) {
        return;
      }
      ended = true;
      if (payload.answer) {
        content.textContent = payload.answer;
      }
      if (payload.citations && payload.citations.length) {
        renderCitations(bubble, payload.citations);
      }
      bubble.setAttribute("data-stream-status", "completed");
      closeStream();
      stopReconnectTimer();
      stopCompletionWatch();
      setSendingState(false);
      refreshSessions().catch(function () {});
    }

    function finishFailed(errorText) {
      if (ended) {
        return;
      }
      ended = true;
      content.textContent = labels.failed + ": " + (errorText || labels.unknownError);
      bubble.setAttribute("data-stream-status", "failed");
      closeStream();
      stopReconnectTimer();
      stopCompletionWatch();
      setSendingState(false);
    }

    function connectEventSource() {
      if (ended || !isSending) {
        return;
      }
      const sep = streamUrl.indexOf("?") >= 0 ? "&" : "?";
      const url = streamUrl + sep + "cursor=" + encodeURIComponent(String(lastCursor || 0));
      const es = new EventSource(url);
      currentStream = es;

      es.addEventListener("started", function () {
        content.textContent = labels.thinking;
      });

      es.addEventListener("delta", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        if (payload.cursor !== undefined && payload.cursor !== null) {
          const parsed = Number(payload.cursor);
          if (!Number.isNaN(parsed) && parsed > lastCursor) {
            lastCursor = parsed;
          }
        }
        acc += payload.text || "";
        content.textContent = acc || labels.thinking;
        els.feed.scrollTop = els.feed.scrollHeight;
      });

      es.addEventListener("citation", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        if (payload.cursor !== undefined && payload.cursor !== null) {
          const parsed = Number(payload.cursor);
          if (!Number.isNaN(parsed) && parsed > lastCursor) {
            lastCursor = parsed;
          }
        }
        if (payload.citation) {
          renderCitations(bubble, [payload.citation]);
        }
      });

      es.addEventListener("completed", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        if (payload.cursor !== undefined && payload.cursor !== null) {
          const parsed = Number(payload.cursor);
          if (!Number.isNaN(parsed) && parsed > lastCursor) {
            lastCursor = parsed;
          }
        }
        finishCompleted(payload);
      });

      es.addEventListener("failed", function (evt) {
        const payload = JSON.parse(evt.data || "{}");
        finishFailed(payload.error || labels.unknownError);
      });

      es.onerror = function () {
        if (!isSending || ended) {
          return;
        }
        closeStream();
        if (reconnectAttempts < maxReconnects) {
          reconnectAttempts += 1;
          const delay = Math.min(1000 * reconnectAttempts, 4000);
          stopReconnectTimer();
          currentReconnectTimer = setTimeout(function () {
            connectEventSource();
          }, delay);
          return;
        }
        content.textContent = content.textContent || labels.thinking;
      };
    }

    connectEventSource();

    if (assistantMessageId) {
      currentWatchTimer = setInterval(async function () {
        if (!isSending || currentSessionId === "") {
          stopCompletionWatch();
          return;
        }
        try {
          const payload = await jfetch("/chat/sessions/" + encodeURIComponent(currentSessionId));
          const msgs = payload.messages || [];
          const found = msgs.find(function (m) {
            return String(m.message_id || "") === String(assistantMessageId);
          });
          if (!found) {
            return;
          }
          const status = String(found.status || "").toLowerCase();
          if (status === "completed") {
            content.textContent = found.content || content.textContent || "";
            if (found.citations && found.citations.length) {
              renderCitations(bubble, found.citations);
            }
            finishCompleted({
              answer: found.content || "",
              citations: found.citations || []
            });
            return;
          }
          if (status === "failed") {
            const detail = found.error_detail || labels.unknownError;
            finishFailed(detail);
          }
        } catch (_) {}
      }, 1500);
    }
  }

  async function send() {
    if (!currentSessionId || isSending) {
      return;
    }
    const text = (els.prompt.value || "").trim();
    if (!text) {
      return;
    }

    const finalModel = getSelectedModel();
    if (!finalModel) {
      addMessage("assistant", labels.failed + ": model_required");
      return;
    }

    setSendingState(true);
    addMessage("user", text);
    els.prompt.value = "";

    try {
      const payload = await jfetch("/chat/sessions/" + encodeURIComponent(currentSessionId) + "/messages", {
        method: "POST",
        body: JSON.stringify({
          content: text,
          mode: els.mode.value || "fast",
          provider: els.provider.value || providerConfig.default_provider || "zhipu",
          model: finalModel,
          stream: true
        })
      });
      attachStream(payload.stream_url, payload.assistant_message_id || "");
    } catch (err) {
      console.error(err);
      addMessage("assistant", labels.failed + ": " + (err && err.message ? err.message : labels.unknownError));
      setSendingState(false);
    }
  }

  function buildProviderRow(item, index) {
    const row = document.createElement("div");
    row.className = "provider-row";
    row.setAttribute("data-index", String(index));
    row.innerHTML = [
      '<div class="mode-group"><label>ID</label><input class="provider-id" /></div>',
      '<div class="mode-group"><label>Type</label><select class="provider-type"><option value="zhipu">zhipu</option><option value="nvidia">nvidia</option><option value="openai_compatible">openai_compatible</option></select></div>',
      '<div class="mode-group"><label>API Key Env</label><input class="provider-api-key-env" /></div>',
      '<div class="mode-group span-2"><label>Base URL</label><input class="provider-base-url" /></div>',
      '<div class="mode-group"><label>Default Model</label><input class="provider-default-model" /></div>',
      '<div class="mode-group span-2"><label>Models (逗号分隔)</label><input class="provider-models" /></div>',
      '<div class="mode-group span-2"><label>Aliases (逗号分隔)</label><input class="provider-aliases" /></div>',
      '<div class="mode-group"><label>Timeout(s)</label><input class="provider-timeout" type="number" min="1" step="1" /></div>',
      '<div class="provider-row-actions span-3"><button type="button" class="ghost-btn provider-test-btn">测试连接</button><span class="provider-test-status"></span><button type="button" class="ghost-btn remove-provider-btn">删除</button></div>'
    ].join("");
    row.querySelector(".provider-id").value = item.id || "";
    row.querySelector(".provider-type").value = item.type || "openai_compatible";
    row.querySelector(".provider-api-key-env").value = item.api_key_env || "";
    row.querySelector(".provider-base-url").value = item.base_url || "";
    row.querySelector(".provider-default-model").value = item.default_model || "";
    row.querySelector(".provider-models").value = (item.models || []).join(",");
    row.querySelector(".provider-aliases").value = (item.aliases || []).join(",");
    row.querySelector(".provider-timeout").value = String(item.timeout_seconds || 90);
    row.querySelector(".provider-test-btn").onclick = function () {
      testProviderConnectionForRow(row).catch(function (err) {
        console.error(err);
      });
    };
    row.querySelector(".remove-provider-btn").onclick = function () {
      row.remove();
      renderDefaultProviderSelectFromRows();
    };
    return row;
  }

  function extractProviderItemFromRow(row) {
    const id = String(row.querySelector(".provider-id").value || "").trim().toLowerCase();
    const type = String(row.querySelector(".provider-type").value || "").trim().toLowerCase();
    const api_key_env = String(row.querySelector(".provider-api-key-env").value || "").trim();
    const base_url = String(row.querySelector(".provider-base-url").value || "").trim();
    const default_model = String(row.querySelector(".provider-default-model").value || "").trim();
    const models = splitCsv(row.querySelector(".provider-models").value || "");
    const aliases = splitCsv(row.querySelector(".provider-aliases").value || "").map(function (x) {
      return x.toLowerCase();
    });
    const timeout_seconds = Number(row.querySelector(".provider-timeout").value || 90);
    return {
      id: id,
      type: type,
      aliases: aliases,
      api_key_env: api_key_env,
      default_model: default_model,
      models: models,
      base_url: base_url,
      timeout_seconds: Number.isFinite(timeout_seconds) && timeout_seconds > 0 ? Math.floor(timeout_seconds) : 90
    };
  }

  function setProviderTestStatus(row, text, isError) {
    const el = row.querySelector(".provider-test-status");
    if (!el) {
      return;
    }
    el.textContent = text || "";
    el.classList.toggle("error", !!isError);
    el.classList.toggle("success", !isError && !!text);
  }

  async function testProviderConnectionForRow(row) {
    const button = row.querySelector(".provider-test-btn");
    const item = sanitizeProviderItem(extractProviderItemFromRow(row));
    if (!item.id) {
      setProviderTestStatus(row, "请先填写 Provider ID", true);
      return;
    }
    if (!item.api_key_env) {
      setProviderTestStatus(row, "请先填写 API Key Env", true);
      return;
    }
    if (button) {
      button.disabled = true;
    }
    setProviderTestStatus(row, "测试中...", false);
    try {
      const resp = await jfetch("/chat/provider-test", {
        method: "POST",
        body: JSON.stringify({
          provider: item.id,
          provider_item: item,
          model: item.default_model || "",
          options: {
            api_key_env: item.api_key_env,
            base_url: item.base_url,
            timeout_seconds: item.timeout_seconds,
            temperature: 0,
            max_retries: 1
          }
        })
      });
      const preview = String(resp.response_preview || "").trim();
      setProviderTestStatus(row, preview ? ("连接成功: " + preview) : "连接成功", false);
    } catch (err) {
      setProviderTestStatus(row, "连接失败: " + (err && err.message ? err.message : labels.unknownError), true);
    } finally {
      if (button) {
        button.disabled = false;
      }
    }
  }

  function renderDefaultProviderSelectFromRows() {
    const ids = Array.from(els.providerRows.querySelectorAll(".provider-id"))
      .map(function (el) {
        return String(el.value || "").trim().toLowerCase();
      })
      .filter(Boolean);
    const current = String(els.defaultProviderSelect.value || "").trim().toLowerCase();
    els.defaultProviderSelect.innerHTML = "";
    ids.forEach(function (id) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      els.defaultProviderSelect.appendChild(option);
    });
    if (current && ids.indexOf(current) >= 0) {
      els.defaultProviderSelect.value = current;
    } else if (ids.length > 0) {
      els.defaultProviderSelect.value = ids[0];
    }
  }

  function renderProviderConfigModal(config) {
    const safe = sanitizeProviderConfig(config || providerConfig);
    els.providerRows.innerHTML = "";
    safe.providers.forEach(function (item, index) {
      const row = buildProviderRow(item, index);
      row.querySelector(".provider-id").addEventListener("input", renderDefaultProviderSelectFromRows);
      els.providerRows.appendChild(row);
    });
    renderDefaultProviderSelectFromRows();
    if (safe.default_provider) {
      els.defaultProviderSelect.value = safe.default_provider;
    }
    setProviderSaveStatus("");
  }

  function collectProviderConfigFromModal() {
    const rows = Array.from(els.providerRows.querySelectorAll(".provider-row"));
    const providers = rows.map(function (row) {
      return extractProviderItemFromRow(row);
    });
    const payload = {
      default_provider: String(els.defaultProviderSelect.value || "").trim().toLowerCase(),
      providers: providers
    };
    return sanitizeProviderConfig(payload);
  }

  async function saveProviderConfigFromModal() {
    try {
      const payload = collectProviderConfigFromModal();
      if (!payload.providers.length) {
        setProviderSaveStatus("鑷冲皯淇濈暀涓€涓?Provider銆?, true);
        return;
      }
      const resp = await jfetch("/chat/provider-config", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      providerConfig = sanitizeProviderConfig(resp.config || payload);
      refreshProviderSelectOptions();
      setProviderSaveStatus("淇濆瓨鎴愬姛锛屽凡鐢熸晥銆?, false);
    } catch (err) {
      setProviderSaveStatus("淇濆瓨澶辫触: " + (err && err.message ? err.message : labels.unknownError), true);
    }
  }

  function openProviderModal() {
    renderProviderConfigModal(providerConfig);
    els.providerModal.classList.remove("hidden");
  }

  function closeProviderModal() {
    els.providerModal.classList.add("hidden");
  }

  els.provider.onchange = function () {
    refreshModelSelector();
  };

  els.modelSelect.onchange = function () {
    if (els.modelSelect.value === "__custom__") {
      els.modelInput.classList.remove("hidden");
      if (!els.modelInput.value) {
        els.modelInput.value = "custom-model";
      }
    } else {
      els.modelInput.classList.add("hidden");
      els.modelInput.value = "";
    }
  };

  els.newSession.onclick = function () {
    createSession(labels.newSession).catch(console.error);
  };

  els.send.onclick = function () {
    send().catch(function (err) {
      console.error(err);
      setSendingState(false);
    });
  };

  els.prompt.onkeydown = function (evt) {
    if (evt.key === "Enter" && !evt.shiftKey) {
      evt.preventDefault();
      send().catch(function (err) {
        console.error(err);
        setSendingState(false);
      });
    }
  };

  els.providerSettingsBtn.onclick = function () {
    openProviderModal();
  };
  els.providerModalClose.onclick = function () {
    closeProviderModal();
  };
  els.providerModal.addEventListener("click", function (evt) {
    if (evt.target === els.providerModal) {
      closeProviderModal();
    }
  });
  els.addProviderBtn.onclick = function () {
    const row = buildProviderRow(
      {
        id: "",
        type: "openai_compatible",
        aliases: [],
        api_key_env: "",
        default_model: "",
        models: [],
        base_url: "",
        timeout_seconds: 90
      },
      0
    );
    row.querySelector(".provider-id").addEventListener("input", renderDefaultProviderSelectFromRows);
    els.providerRows.appendChild(row);
    renderDefaultProviderSelectFromRows();
  };
  els.saveProviderConfigBtn.onclick = function () {
    saveProviderConfigFromModal().catch(console.error);
  };

  loadProviderConfig()
    .then(function () {
      return refreshSessions();
    })
    .then(function () {
      return createSession(labels.newSession);
    })
    .catch(function (err) {
      console.error(err);
      addMessage("assistant", "鏃犳硶鍒濆鍖栦細璇濓紝璇锋鏌ュ悗绔?/chat 鎺ュ彛銆?);
    });
})();
