(function () {
  "use strict";

  const els = {
    cliCommand: document.getElementById("codex-cli-command"),
    cliArgs: document.getElementById("codex-cli-args"),
    healthArgs: document.getElementById("codex-healthcheck-args"),
    installCommand: document.getElementById("codex-install-command"),
    timeout: document.getElementById("codex-timeout-seconds"),
    extraEnv: document.getElementById("codex-extra-env"),
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
    els.cliCommand.value = String(c.cli_command || "");
    els.cliArgs.value = JSON.stringify(Array.isArray(c.cli_args) ? c.cli_args : [], null, 2);
    els.healthArgs.value = JSON.stringify(Array.isArray(c.healthcheck_args) ? c.healthcheck_args : [], null, 2);
    els.installCommand.value = String(c.install_command || "");
    els.timeout.value = String(Number(c.timeout_seconds || 180));
    els.extraEnv.value = JSON.stringify(c.extra_env && typeof c.extra_env === "object" ? c.extra_env : {}, null, 2);
  }

  function collectConfig() {
    return {
      cli_command: String(els.cliCommand.value || "").trim(),
      cli_args: parseJson(els.cliArgs.value, []),
      healthcheck_args: parseJson(els.healthArgs.value, []),
      install_command: String(els.installCommand.value || "").trim(),
      timeout_seconds: Number(els.timeout.value || 180),
      extra_env: parseJson(els.extraEnv.value, {})
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
