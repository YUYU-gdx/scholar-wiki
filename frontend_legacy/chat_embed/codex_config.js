(function () {
  "use strict";

  const els = {
    appServerCommand: document.getElementById("codex-app-server-command"),
    appServerArgs: document.getElementById("codex-app-server-args"),
    healthArgs: document.getElementById("codex-healthcheck-args"),
    installCommand: document.getElementById("codex-install-command"),
    timeout: document.getElementById("codex-timeout-seconds"),
    extraEnv: document.getElementById("codex-extra-env"),
    model: document.getElementById("codex-model"),
    approvalPolicy: document.getElementById("codex-approval-policy"),
    sandboxMode: document.getElementById("codex-sandbox-mode"),
    personality: document.getElementById("codex-personality"),
    mcpServers: document.getElementById("codex-mcp-servers"),
    healthBtn: document.getElementById("codex-health-btn"),
    installBtn: document.getElementById("codex-install-btn"),
    saveBtn: document.getElementById("codex-save-btn"),
    status: document.getElementById("codex-status")
  };

  function jfetch(url, options) {
    return fetch(
      url,
      Object.assign({ headers: { "Content-Type": "application/json" } }, options || {})
    ).then(async function (resp) {
      const payload = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(payload.error || payload.reason || ("http_" + resp.status));
      }
      return payload;
    });
  }

  function setStatus(text, isError) {
    els.status.textContent = text || "";
    els.status.style.color = isError ? "#f17b7b" : "";
  }

  function parseJson(raw, fallback) {
    try {
      return JSON.parse(String(raw || "").trim() || JSON.stringify(fallback));
    } catch (_err) {
      return fallback;
    }
  }

  function fillConfig(cfg) {
    const c = cfg && typeof cfg === "object" ? cfg : {};
    els.appServerCommand.value = String(c.app_server_command || "");
    els.appServerArgs.value = JSON.stringify(Array.isArray(c.app_server_args) ? c.app_server_args : [], null, 2);
    els.healthArgs.value = JSON.stringify(Array.isArray(c.healthcheck_args) ? c.healthcheck_args : [], null, 2);
    els.installCommand.value = String(c.install_command || "");
    els.timeout.value = String(Number(c.timeout_seconds || 180));
    els.extraEnv.value = JSON.stringify(c.extra_env && typeof c.extra_env === "object" ? c.extra_env : {}, null, 2);
    els.model.value = String(c.model || "gpt-5.2");
    els.approvalPolicy.value = String(c.approval_policy || "never");
    els.sandboxMode.value = String(c.sandbox_mode || "workspace-write");
    els.personality.value = String(c.personality || "pragmatic");
    els.mcpServers.value = JSON.stringify(Array.isArray(c.mcp_servers) ? c.mcp_servers : [], null, 2);
  }

  function collectConfig() {
    return {
      app_server_command: String(els.appServerCommand.value || "").trim(),
      app_server_args: parseJson(els.appServerArgs.value, []),
      healthcheck_args: parseJson(els.healthArgs.value, []),
      install_command: String(els.installCommand.value || "").trim(),
      timeout_seconds: Number(els.timeout.value || 180),
      extra_env: parseJson(els.extraEnv.value, {}),
      model: String(els.model.value || "").trim(),
      approval_policy: String(els.approvalPolicy.value || "").trim(),
      sandbox_mode: String(els.sandboxMode.value || "").trim(),
      personality: String(els.personality.value || "").trim(),
      mcp_servers: parseJson(els.mcpServers.value, [])
    };
  }

  function loadConfig() {
    return jfetch("/chat/codex/config")
      .then(function (payload) {
        fillConfig(payload.config || {});
      })
      .catch(function (err) {
        setStatus("加载配置失败: " + String(err && err.message ? err.message : err), true);
      });
  }

  function saveConfig() {
    setStatus("保存中...", false);
    return jfetch("/chat/codex/config", {
      method: "POST",
      body: JSON.stringify(collectConfig())
    })
      .then(function () {
        setStatus("配置已保存", false);
      })
      .catch(function (err) {
        setStatus("保存失败: " + String(err && err.message ? err.message : err), true);
      });
  }

  function healthcheck() {
    setStatus("检测中...", false);
    return jfetch("/chat/codex/health")
      .then(function (payload) {
        const version = String(payload.version || "").trim();
        setStatus(version ? ("Codex 可用: " + version) : "Codex 可用", false);
      })
      .catch(function (err) {
        setStatus("Codex 不可用: " + String(err && err.message ? err.message : err), true);
      });
  }

  function installCodex() {
    setStatus("安装中...", false);
    return jfetch("/chat/codex/install", { method: "POST", body: "{}" })
      .then(function (payload) {
        const out = String(payload.stdout || "").trim();
        setStatus("安装完成" + (out ? (": " + out.slice(-120)) : ""), false);
      })
      .catch(function (err) {
        setStatus("安装失败: " + String(err && err.message ? err.message : err), true);
      });
  }

  els.saveBtn.onclick = function () {
    saveConfig().catch(function () {});
  };
  els.healthBtn.onclick = function () {
    healthcheck().catch(function () {});
  };
  els.installBtn.onclick = function () {
    installCodex().catch(function () {});
  };

  loadConfig().then(function () {
    return healthcheck();
  });
})();
