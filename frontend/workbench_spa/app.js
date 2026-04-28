(function () {
  "use strict";

  const e = React.createElement;
  const { useEffect, useMemo, useRef, useState } = React;

  const panelTitles = {
    chat: "Chat",
    graph: "Graph 3D",
    import: "Import Pipeline",
    search: "Search",
  };

  function jsonFetch(url, init) {
    return fetch(url, init).then(async (resp) => {
      const text = await resp.text();
      let payload = {};
      try {
        payload = text ? JSON.parse(text) : {};
      } catch (_err) {
        payload = { raw: text };
      }
      if (!resp.ok) {
        const msg = payload && payload.error ? payload.error : "request_failed";
        throw new Error(msg + " (" + resp.status + ")");
      }
      return payload;
    });
  }

  function defaultLayoutConfig() {
    return {
      settings: {
        hasHeaders: true,
        reorderEnabled: true,
        selectionEnabled: false,
        showPopoutIcon: false,
        showCloseIcon: true,
      },
      dimensions: {
        borderWidth: 6,
        minItemHeight: 80,
        minItemWidth: 120,
        headerHeight: 34,
      },
      content: [
        {
          type: "row",
          content: [
            {
              type: "stack",
              width: 58,
              content: [
                { type: "component", componentName: "chat-panel", title: "Chat" },
                { type: "component", componentName: "search-panel", title: "Search" },
              ],
            },
            {
              type: "column",
              width: 42,
              content: [
                { type: "component", componentName: "graph-panel", title: "Graph 3D", height: 62 },
                { type: "component", componentName: "import-panel", title: "Import Pipeline", height: 38 },
              ],
            },
          ],
        },
      ],
    };
  }

  function buildPanelComponent(type) {
    const map = {
      chat: { componentName: "chat-panel", title: panelTitles.chat },
      graph: { componentName: "graph-panel", title: panelTitles.graph },
      import: { componentName: "import-panel", title: panelTitles.import },
      search: { componentName: "search-panel", title: panelTitles.search },
    };
    const item = map[type];
    if (!item) return null;
    return { type: "component", componentName: item.componentName, title: item.title };
  }

  function mountReactNode(container, componentFactory) {
    const host = document.createElement("div");
    host.className = "panel-wrap";
    container.getElement().append(host);
    const root = ReactDOM.createRoot(host);
    root.render(componentFactory());
    container.on("destroy", function () {
      root.unmount();
    });
  }

  function ImportPanel() {
    const [queueRows, setQueueRows] = useState([]);
    const [totalJobs, setTotalJobs] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(25);
    const [statusFilter, setStatusFilter] = useState("");
    const [queryText, setQueryText] = useState("");
    const [uploadLibraryId, setUploadLibraryId] = useState("");
    const [queueLibraryId, setQueueLibraryId] = useState("");
    const [libraries, setLibraries] = useState([]);
    const [selectedJobId, setSelectedJobId] = useState("");
    const [selectedJob, setSelectedJob] = useState(null);
    const [eventLines, setEventLines] = useState(["等待导入任务"]);
    const [queueUnavailable, setQueueUnavailable] = useState(false);
    const [busy, setBusy] = useState(false);
    const fileRef = useRef(null);
    const eventSourceRef = useRef(null);
    const ASYNC_BASE = useMemo(function () {
      try {
        const params = new URLSearchParams(window.location.search || "");
        const p = String(params.get("async_port") || "").trim() || "8021";
        return window.location.protocol + "//" + window.location.hostname + ":" + p;
      } catch (_err) {
        return "http://127.0.0.1:8021";
      }
    }, []);
    const terminalStatus = useMemo(function () {
      return new Set(["completed", "failed", "cancelled"]);
    }, []);

    const STAGE_LABELS = {
      accepted: "任务已接收",
      parse_pdf: "解析 PDF",
      extract_entities: "抽取信息",
      finalize: "整理结果",
      completed: "处理完成",
      failed: "处理失败",
      cancelled: "已取消",
    };

    const BEHAVIOR_LABELS = {
      queued: "任务排队中",
      accepted: "待处理",
      parse_pdf: "正在解析 PDF",
      extract_entities: "正在抽取结构化信息",
      finalize: "正在整理并入库",
      completed: "任务处理完成",
      failed: "任务处理失败",
      cancelled: "任务已取消",
    };

    const appendEventLine = function (line) {
      setEventLines(function (prev) {
        const next = prev.concat([line]);
        return next.slice(-20);
      });
    };

    const closeEventSource = function () {
      if (eventSourceRef.current) {
        try {
          eventSourceRef.current.close();
        } catch (_err) {
          // ignore
        }
      }
      eventSourceRef.current = null;
    };

    const isoToLocal = function (value) {
      const text = String(value || "").trim();
      if (!text) return "-";
      const dt = new Date(text);
      if (Number.isNaN(dt.getTime())) return text;
      return dt.toLocaleString();
    };

    const renderMarkdownHtml = function (markdownText) {
      const raw = String(markdownText || "");
      try {
        if (window.marked && typeof window.marked.parse === "function") {
          const parsed = window.marked.parse(raw);
          if (window.DOMPurify && typeof window.DOMPurify.sanitize === "function") {
            return window.DOMPurify.sanitize(parsed);
          }
          return parsed;
        }
      } catch (_err) {
        // ignore and fallback
      }
      return raw
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\n/g, "<br/>");
    };

    const buildStatusLine = function (row, eventType) {
      const status = String((row && row.status) || "");
      const stage = String((row && row.stage) || "");
      const progress = Number(row && row.progress);
      if (status === "queued") {
        return "已进入队列，等待处理";
      }
      if (status === "running") {
        const label = STAGE_LABELS[stage] || stage || "处理中";
        if (Number.isFinite(progress)) {
          return label + " · " + String(Math.max(0, Math.min(100, Math.round(progress)))) + "%";
        }
        return label;
      }
      if (status === "completed") return "处理完成";
      if (status === "failed") return "处理失败";
      if (status === "cancelled") return "任务已取消";
      if (eventType && STAGE_LABELS[eventType]) return STAGE_LABELS[eventType];
      return "处理中";
    };

    const behaviorText = function (row) {
      const status = String((row && row.status_code) || (row && row.status) || "").toLowerCase();
      const stage = String((row && row.stage_code) || (row && row.stage) || "").toLowerCase();
      const cancelRequested = Boolean(row && row.requested_cancel);
      if (cancelRequested && (status === "queued" || status === "running")) {
        return "取消中";
      }
      if (status === "running") {
        return BEHAVIOR_LABELS[stage] || ("处理中(" + (stage || "unknown") + ")");
      }
      if (status === "queued") return BEHAVIOR_LABELS.accepted;
      return BEHAVIOR_LABELS[status] || "状态更新";
    };

    const applyJobPayload = function (row, eventType) {
      if (!row || typeof row !== "object") return;
      const status = String(row.status || "").toLowerCase();
      const stage = String(row.stage || "");
      const progressNum = Number(row.progress);
      const progressText = Number.isFinite(progressNum) ? String(Math.max(0, Math.min(100, Math.round(progressNum)))) + "%" : "";
      const statusLine = buildStatusLine(row, eventType);
      const stageLabel = STAGE_LABELS[stage] || STAGE_LABELS[eventType] || stage || status || "update";
      appendEventLine(stageLabel + (progressText ? " (" + progressText + ")" : ""));
      if (selectedJobId && String(row.job_id || "") === selectedJobId) {
        setSelectedJob(Object.assign({}, row, { status_line: statusLine }));
      }
      if (terminalStatus.has(status)) {
        closeEventSource();
      }
    };

    const refreshQueue = async function (forcePage, forceRequest) {
      if (queueUnavailable && !forceRequest) return;
      try {
        const targetPage = Math.max(1, Number(forcePage || page) || 1);
        const params = new URLSearchParams();
        params.set("page", String(targetPage));
        params.set("page_size", String(pageSize));
        if (statusFilter) params.set("status", statusFilter);
        if (queryText.trim()) params.set("q", queryText.trim());
        if (queueLibraryId) params.set("library_id", queueLibraryId);
        const payload = await jsonFetch(ASYNC_BASE + "/v1/jobs?" + params.toString(), { method: "GET" });
        const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
        setQueueRows(jobs);
        setTotalJobs(Number(payload.total || 0));
        setQueueUnavailable(false);
      } catch (err) {
        const msg = String(err || "");
        if (msg.indexOf("(404)") >= 0) {
          setQueueUnavailable(true);
          appendEventLine("任务队列接口不可用（404）：请重启桌面应用，确保 async 后端已启动且端口正确。");
          return;
        }
        appendEventLine("任务列表刷新失败: " + msg);
      }
    };

    const startEventStream = function (sseUrl) {
      closeEventSource();
      if (!sseUrl || !window.EventSource) {
        appendEventLine("当前环境不支持 SSE，改用列表轮询刷新");
        return;
      }
      try {
        const source = new window.EventSource(sseUrl);
        eventSourceRef.current = source;
        source.onopen = function () {
          appendEventLine("已连接状态流");
        };
        const handleEvent = function (eventType, evt) {
          try {
            const row = JSON.parse(evt.data || "{}");
            applyJobPayload(row, eventType);
          } catch (_err) {
            // ignore bad event payload
          }
        };
        ["accepted", "stage_started", "stage_progress", "stage_done", "completed", "failed", "cancelled"].forEach(function (eventType) {
          source.addEventListener(eventType, function (evt) {
            handleEvent(eventType, evt);
          });
        });
        source.onmessage = function (evt) {
          handleEvent("message", evt);
        };
        source.onerror = function () {
          appendEventLine("状态流中断，已保留队列轮询刷新");
          closeEventSource();
        };
      } catch (_err) {
        appendEventLine("状态流连接失败");
      }
    };

    useEffect(function () {
      jsonFetch("/literature/libraries")
        .then(function (payload) {
          const rows = Array.isArray(payload.libraries) ? payload.libraries : [];
          setLibraries(rows);
          const fallback = String(payload.default_library_id || "").trim() || (rows[0] ? String(rows[0].library_id || "").trim() : "");
          setUploadLibraryId(fallback);
          setQueueLibraryId("");
        })
        .catch(function () {
          setLibraries([]);
          setUploadLibraryId("");
          setQueueLibraryId("");
        });
    }, []);

    useEffect(function () {
      refreshQueue(1, true);
      const timer = window.setInterval(function () {
        refreshQueue();
      }, 1800);
      return function () {
        window.clearInterval(timer);
        closeEventSource();
      };
    }, [statusFilter, queryText, queueLibraryId, page]);

    useEffect(function () {
      if (!selectedJobId) {
        closeEventSource();
        setSelectedJob(null);
        return;
      }
      jsonFetch(ASYNC_BASE + "/v1/jobs/" + encodeURIComponent(selectedJobId), { method: "GET" })
        .then(function (payload) {
          setSelectedJob(payload);
          startEventStream(ASYNC_BASE + "/v1/jobs/" + encodeURIComponent(selectedJobId) + "/events");
        })
        .catch(function (err) {
          appendEventLine("任务详情加载失败: " + String(err));
        });
      return function () {
        closeEventSource();
      };
    }, [selectedJobId]);

    const submitFiles = async function () {
      try {
        const files = fileRef.current && fileRef.current.files ? Array.from(fileRef.current.files) : [];
        if (!files.length) {
          appendEventLine("请选择一个或多个 PDF 文件");
          return;
        }
        if (!uploadLibraryId) {
          appendEventLine("请选择文献库");
          return;
        }
        setBusy(true);
        const form = new FormData();
        files.forEach(function (file) {
          form.append("files", file, file.name);
        });
        form.append("library_id", uploadLibraryId);
        const payload = await jsonFetch(ASYNC_BASE + "/v1/pipeline/parse-extract/batch", { method: "POST", body: form });
        appendEventLine("批量入队完成：成功 " + String(payload.accepted_count || 0) + "，失败 " + String(payload.rejected_count || 0));
        const accepted = Array.isArray(payload.accepted) ? payload.accepted : [];
        if (accepted.length) {
          setSelectedJobId(String(accepted[0].job_id || ""));
        }
        setPage(1);
        await refreshQueue(1, true);
      } catch (err) {
        appendEventLine("批量导入失败: " + String(err));
      } finally {
        setBusy(false);
      }
    };

    const actionJob = async function (kind, row) {
      try {
        const jobId = String(row && row.job_id ? row.job_id : "");
        if (!jobId) return;
        setBusy(true);
      if (kind === "cancel") {
          const payload = await jsonFetch(ASYNC_BASE + "/v1/jobs/" + encodeURIComponent(jobId) + "/cancel", { method: "POST" });
          appendEventLine("已请求取消任务: " + String(payload.job_id || jobId));
          await refreshQueue(undefined, true);
          return;
        }
        if (kind === "retry") {
          const payload = await jsonFetch(ASYNC_BASE + "/v1/jobs/" + encodeURIComponent(jobId) + "/retry", { method: "POST" });
          const newJob = payload && payload.new_job ? payload.new_job : {};
          const newJobId = String(newJob.job_id || "");
          appendEventLine("重试已创建新任务: " + (newJobId || "unknown"));
          if (newJobId) setSelectedJobId(newJobId);
          await refreshQueue(1, true);
        }
      } catch (err) {
        appendEventLine("任务操作失败: " + String(err));
      } finally {
        setBusy(false);
      }
    };

    const statusText = function (row) {
      return buildStatusLine(row || {}, "");
    };

    const statusClass = function (row) {
      const status = String((row && row.status) || "").toLowerCase();
      if (status === "completed") return "status-pill status-completed";
      if (status === "failed") return "status-pill status-failed";
      if (status === "cancelled") return "status-pill status-cancelled";
      if (status === "running") return "status-pill status-running";
      if (status === "queued") return "status-pill status-queued";
      return "status-pill";
    };

    const totalPages = Math.max(1, Math.ceil(Math.max(0, totalJobs) / pageSize));
    const STAGE_FLOW = ["accepted", "parse_pdf", "extract_entities", "finalize"];
    const STAGE_FLOW_LABELS = {
      accepted: "待处理",
      parse_pdf: "解析",
      extract_entities: "抽取",
      finalize: "整理",
    };
    const stageIndexFor = function (row) {
      const status = String((row && row.status_code) || (row && row.status) || "").toLowerCase();
      const stage = String((row && row.stage_code) || (row && row.stage) || "").toLowerCase();
      if (status === "queued") return 0;
      const idx = STAGE_FLOW.indexOf(stage);
      if (idx >= 0) return idx;
      if (status === "completed") return STAGE_FLOW.length - 1;
      return 0;
    };
    const stepClass = function (row, step) {
      const status = String((row && row.status_code) || (row && row.status) || "").toLowerCase();
      const idx = stageIndexFor(row);
      const target = STAGE_FLOW.indexOf(step);
      if (status === "failed" || status === "cancelled") {
        if (target === idx) return "fsm-step failed";
        if (target < idx) return "fsm-step done";
        return "fsm-step pending";
      }
      if (status === "completed") return "fsm-step done";
      if (target < idx) return "fsm-step done";
      if (target === idx) return "fsm-step active";
      return "fsm-step pending";
    };
    const selectedJobInList =
      selectedJobId && queueRows.length ? queueRows.find(function (x) { return String(x.job_id || "") === selectedJobId; }) : null;
    const currentJob = selectedJob || selectedJobInList || null;
    const currentResult = currentJob && currentJob.result && typeof currentJob.result === "object" ? currentJob.result : {};
    const currentExtract = currentResult.extract && typeof currentResult.extract === "object" ? currentResult.extract : {};
    const currentSummary = currentExtract.summary && typeof currentExtract.summary === "object" ? currentExtract.summary : {};
    const relationHints = []
      .concat(currentSummary.relational_variables || [])
      .concat(currentSummary.relationships || [])
      .slice(0, 8);
    const markdownText = [
      "# AI 沉淀详情",
      "",
      "## 元数据",
      "- 任务ID: `" + String(currentJob && currentJob.job_id ? currentJob.job_id : "-") + "`",
      "- 文件: " + String(currentJob && currentJob.file_name ? currentJob.file_name : "-"),
      "- 文献库: " + String(currentJob && currentJob.library_id ? currentJob.library_id : "-"),
      "- 当前状态: " + String(currentJob ? behaviorText(currentJob) : "-"),
      "- 创建时间: " + isoToLocal(currentJob && currentJob.created_at),
      "- 更新时间: " + isoToLocal(currentJob && currentJob.updated_at),
      "",
      "## 核心变量",
      Object.keys(currentSummary || {}).length
        ? Object.keys(currentSummary)
            .slice(0, 12)
            .map(function (key) {
              const value = currentSummary[key];
              return "- **" + key + "**: " + (typeof value === "string" ? value : JSON.stringify(value));
            })
            .join("\n")
        : "- 暂无抽取变量",
      "",
      "## 因果关系图（摘要）",
      relationHints.length
        ? relationHints
            .map(function (item, idx) {
              if (typeof item === "string") return String(idx + 1) + ". " + item;
              try {
                return String(idx + 1) + ". " + JSON.stringify(item);
              } catch (_err) {
                return String(idx + 1) + ". [complex relation]";
              }
            })
            .join("\n")
        : "暂无关系数据，可在任务完成后查看。",
    ].join("\n");
    const markdownHtml = renderMarkdownHtml(markdownText);

    return e(
      "div",
      { className: "panel-body" },
      e("h3", null, "AI 知识工作台"),
      queueUnavailable
        ? e("div", { className: "error-box", style: { marginBottom: "8px" } }, "任务队列接口不可用（404）。请重启应用后重试。")
        : null,
      e(
        "div",
        { className: "panel-form import-toolbar" },
        e(
          "select",
          {
            value: uploadLibraryId,
            onChange: function (evt) {
              setUploadLibraryId(evt.target.value);
            },
          },
          e("option", { value: "" }, "选择上传文献库"),
          libraries.map(function (row, idx) {
            const id = String(row && row.library_id ? row.library_id : "");
            const label = id + " (" + String(row && row.paper_count ? row.paper_count : 0) + ")";
            return e("option", { key: "import-lib-" + idx, value: id }, label);
          })
        ),
        e(
          "select",
          {
            value: queueLibraryId,
            onChange: function (evt) {
              setQueueLibraryId(evt.target.value);
              setPage(1);
            },
          },
          e("option", { value: "" }, "队列: 全部文献库"),
          libraries.map(function (row, idx) {
            const id = String(row && row.library_id ? row.library_id : "");
            const label = "队列: " + id;
            return e("option", { key: "queue-lib-" + idx, value: id }, label);
          })
        ),
        e("input", {
          ref: fileRef,
          type: "file",
          multiple: true,
          accept: "application/pdf",
        }),
        e("button", { className: "primary-action", onClick: submitFiles, disabled: busy }, busy ? "处理中..." : "上传并入队"),
        e(
          "select",
          {
            value: statusFilter,
            onChange: function (evt) {
              setStatusFilter(evt.target.value);
              setPage(1);
            },
          },
          e("option", { value: "" }, "全部状态"),
          e("option", { value: "queued" }, "queued"),
          e("option", { value: "running" }, "running"),
          e("option", { value: "completed" }, "completed"),
          e("option", { value: "failed" }, "failed"),
          e("option", { value: "cancelled" }, "cancelled")
        ),
        e("input", {
          value: queryText,
          onChange: function (evt) {
            setQueryText(evt.target.value);
            setPage(1);
          },
          placeholder: "搜索任务ID/文件名",
        }),
        e("button", { onClick: function () { refreshQueue(undefined, true); }, disabled: busy }, "刷新")
      ),
      e(
        "div",
        { className: "knowledge-layout" },
        e(
          "section",
          { className: "list-column" },
          e("div", { className: "column-title" }, "任务列表"),
          e(
            "div",
            { className: "list-frame" },
            e(
              "div",
              { className: "task-card-list full-height" },
              queueRows.length
                ? queueRows.map(function (row) {
                    const id = String(row.job_id || "");
                    const display = String(row.display_name || row.file_name || "-");
                    const stageCode = String((row.stage_code || row.stage || "")).toLowerCase();
                    return e(
                      "article",
                      {
                        key: "card-" + id,
                        className: "task-card task-row" + (selectedJobId === id ? " active" : ""),
                        onClick: function () {
                          setSelectedJobId(id);
                        },
                      },
                      e(
                        "div",
                        { className: "task-row-head" },
                        e("div", { className: "task-card-title", title: display }, display),
                        e("span", { className: statusClass(row) }, behaviorText(row))
                      ),
                      e(
                        "div",
                        { className: "task-fields" },
                        e("span", null, "库: " + String(row.library_id || "-")),
                        e("span", null, "阶段: " + (STAGE_LABELS[stageCode] || stageCode || "-")),
                        e("span", null, "进度: " + String(row.progress || 0) + "%"),
                        e("span", null, "创建: " + isoToLocal(row.created_at)),
                        e("span", null, "更新: " + isoToLocal(row.updated_at))
                      ),
                      e(
                        "div",
                        { className: "task-fsm" },
                        STAGE_FLOW.map(function (step) {
                          return e(
                            "div",
                            { key: id + "-fsm-" + step, className: stepClass(row, step) },
                            e("span", { className: "dot" }),
                            e("span", null, STAGE_FLOW_LABELS[step])
                          );
                        })
                      ),
                      e(
                        "div",
                        { className: "task-actions" },
                        row.can_cancel
                          ? e(
                              "button",
                              {
                                onClick: function (evt) {
                                  evt.stopPropagation();
                                  actionJob("cancel", row);
                                },
                              },
                              "取消"
                            )
                          : null,
                        row.can_retry
                          ? e(
                              "button",
                              {
                                onClick: function (evt) {
                                  evt.stopPropagation();
                                  actionJob("retry", row);
                                },
                              },
                              "重试"
                            )
                          : null,
                        e("span", { className: "helper task-id" }, id)
                      )
                    );
                  })
                : e("div", { className: "helper" }, "暂无任务")
            ),
            e(
              "div",
              { className: "stream-pagination panel-form pinned-pagination" },
              e("button", { disabled: page <= 1, onClick: function () { setPage(Math.max(1, page - 1)); } }, "上一页"),
              e("span", { className: "helper" }, "第 " + String(page) + " / " + String(totalPages) + " 页"),
              e("button", { disabled: page >= totalPages, onClick: function () { setPage(Math.min(totalPages, page + 1)); } }, "下一页"),
              e("span", { className: "helper" }, "总计 " + String(totalJobs) + " 条")
            )
          )
        ),
        e(
          "aside",
          { className: "detail-column" },
          e("div", { className: "column-title" }, "沉淀详情"),
          currentJob
            ? e(
                "div",
                { className: "detail-meta helper" },
                e("div", null, "当前行为: " + behaviorText(currentJob)),
                String(currentJob.error_code || "").trim() || String(currentJob.error_detail || "").trim()
                  ? e(
                      "div",
                      { className: "error-box" },
                      e("div", null, "错误码: " + String(currentJob.error_code || "-")),
                      e("div", null, "错误详情: " + String(currentJob.error_detail || "-"))
                    )
                  : null
              )
            : e("div", { className: "helper" }, "选择任务后查看沉淀详情"),
          e("div", {
            className: "markdown-preview",
            dangerouslySetInnerHTML: { __html: markdownHtml },
          }),
          e(
            "ul",
            { className: "result-list helper", style: { marginTop: "10px", marginBottom: "0" } },
            eventLines.map(function (line, idx) {
              return e("li", { key: "event-line-" + idx }, line);
            })
          )
        )
      )
    );
  }

  function SearchPanel() {
    const [query, setQuery] = useState("");
    const [mode, setMode] = useState("variable");
    const [libraryId, setLibraryId] = useState("");
    const [libraries, setLibraries] = useState([]);
    const [graphHits, setGraphHits] = useState([]);
    const [litHits, setLitHits] = useState([]);
    const [error, setError] = useState("");

    useEffect(function () {
      jsonFetch("/literature/libraries")
        .then(function (payload) {
          const rows = Array.isArray(payload.libraries) ? payload.libraries : [];
          setLibraries(rows);
          const fallback = String(payload.default_library_id || "").trim() || (rows[0] ? String(rows[0].library_id || "").trim() : "");
          setLibraryId(fallback);
        })
        .catch(function () {
          setLibraries([]);
          setLibraryId("");
        });
    }, []);

    const runSearch = async function () {
      try {
        if (!query.trim()) {
          setError("请输入查询词");
          return;
        }
        if (!libraryId) {
          setError("请选择文献库");
          return;
        }
        setError("");
        const [graphPayload, litPayload] = await Promise.all([
          jsonFetch("/graph/search?mode=" + encodeURIComponent(mode) + "&query=" + encodeURIComponent(query) + "&limit=10"),
          jsonFetch("/literature/search?query=" + encodeURIComponent(query) + "&top_k=10&library_id=" + encodeURIComponent(libraryId)),
        ]);
        setGraphHits(Array.isArray(graphPayload.results) ? graphPayload.results : []);
        const merged = Array.isArray(litPayload.merged_hits) ? litPayload.merged_hits : [];
        setLitHits(merged);
      } catch (err) {
        setError(String(err));
      }
    };

    return e(
      "div",
      { className: "panel-body" },
      e("h3", null, "图谱 / 文献搜索"),
      e(
        "div",
        { className: "panel-form" },
        e("input", {
          value: query,
          onChange: function (evt) {
            setQuery(evt.target.value);
          },
          placeholder: "query",
        }),
        e(
          "select",
          {
            value: mode,
            onChange: function (evt) {
              setMode(evt.target.value);
            },
          },
          e("option", { value: "variable" }, "variable"),
          e("option", { value: "paper" }, "paper")
        ),
        e(
          "select",
          {
            value: libraryId,
            onChange: function (evt) {
              setLibraryId(evt.target.value);
            },
          },
          e("option", { value: "" }, "library"),
          libraries.map(function (row, idx) {
            const id = String(row && row.library_id ? row.library_id : "");
            const label = id + " (" + String(row && row.paper_count ? row.paper_count : 0) + ")";
            return e("option", { key: "lib-" + idx, value: id }, label);
          })
        ),
        e("button", { onClick: runSearch }, "搜索")
      ),
      error ? e("div", { className: "helper" }, error) : null,
      e("div", { className: "search-subtitle" }, "Graph 命中"),
      e(
        "div",
        { className: "search-cards" },
        graphHits.slice(0, 10).map(function (item, idx) {
          return e(
            "article",
            { className: "search-card", key: "g-" + idx },
            e("div", { className: "search-card-kind" }, item.kind || "graph"),
            e("div", { className: "search-card-title" }, item.title || item.id || "-")
          );
        })
      ),
      e("div", { className: "search-subtitle" }, "Literature 命中"),
      e(
        "div",
        { className: "search-cards" },
        litHits.slice(0, 10).map(function (item, idx) {
          const title = item.title || item.paper_id || item.id || "-";
          return e(
            "article",
            { className: "search-card", key: "l-" + idx },
            e("div", { className: "search-card-kind" }, "paper"),
            e("div", { className: "search-card-title" }, title)
          );
        })
      )
    );
  }

  function App() {
    const containerRef = useRef(null);
    const layoutRef = useRef(null);
    const [layoutName, setLayoutName] = useState("default");
    const [knownLayouts, setKnownLayouts] = useState([]);
    const [status, setStatus] = useState("ready");

    const refreshLayoutNames = async function () {
      try {
        const payload = await jsonFetch("/api/v2/workspace/layouts", { method: "GET" });
        const rows = Array.isArray(payload.layouts) ? payload.layouts : [];
        setKnownLayouts(rows.map(function (x) { return String(x.name || ""); }).filter(Boolean));
      } catch (_err) {
        setKnownLayouts([]);
      }
    };

    const saveCurrentLayout = async function () {
      if (!layoutRef.current) return;
      const config = layoutRef.current.toConfig();
      try {
        window.localStorage.setItem("workbench:layout:" + (layoutName || "default"), JSON.stringify(config));
      } catch (_err) {
        // ignore localStorage failures
      }
      setStatus("saving...");
      try {
        await jsonFetch("/api/v2/workspace/layout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: layoutName || "default", layout: config }),
        });
        setStatus("saved");
        await refreshLayoutNames();
      } catch (err) {
        setStatus("save failed: " + err);
      }
    };

    const addPanel = function (type) {
      const item = buildPanelComponent(type);
      if (!item || !layoutRef.current) return;
      const stacks = layoutRef.current.root.getItemsByType("stack");
      if (stacks.length > 0) {
        stacks[0].addChild(item);
      } else if (layoutRef.current.root.contentItems.length > 0) {
        layoutRef.current.root.contentItems[0].addChild(item);
      }
    };

    const linkGraphToChat = function () {
      if (!layoutRef.current) return;
      const stacks = layoutRef.current.root.getItemsByType("stack");
      const chatItem = {
        type: "component",
        componentName: "chat-panel",
        title: panelTitles.chat + " (from graph)",
        componentState: { fromNode: "var::a" },
      };
      if (stacks.length > 0) {
        stacks[0].addChild(chatItem);
      } else if (layoutRef.current.root.contentItems.length > 0) {
        layoutRef.current.root.contentItems[0].addChild(chatItem);
      }
    };

    const rebuildLayout = async function () {
      if (!containerRef.current) return;
      let config = defaultLayoutConfig();
      try {
        const raw = window.localStorage.getItem("workbench:layout:" + (layoutName || "default"));
        if (raw) {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") {
            config = parsed;
          }
        }
      } catch (_err) {
        // ignore localStorage failures
      }
      try {
        const payload = await jsonFetch("/api/v2/workspace/layout?name=" + encodeURIComponent(layoutName || "default"), {
          method: "GET",
        });
        if (payload && payload.layout && typeof payload.layout === "object") {
          config = payload.layout;
        }
      } catch (_err) {
        // use default config
      }

      if (layoutRef.current) {
        layoutRef.current.destroy();
        layoutRef.current = null;
      }

      const layout = new window.GoldenLayout(config, containerRef.current);
      layout.registerComponent("chat-panel", function (container) {
        const host = document.createElement("div");
        host.className = "panel-wrap";
        host.setAttribute("data-testid", "panel-chat");
        host.setAttribute("data-panel-type", "chat");
        const fromNode = container._config && container._config.componentState && container._config.componentState.fromNode;
        const chatUrl = fromNode ? "/frontend/chat/?from_node=" + encodeURIComponent(fromNode) : "/frontend/chat/";
        host.innerHTML = '<iframe class="panel-iframe" src="' + chatUrl + '"></iframe>';
        container.getElement().append(host);
      });
      layout.registerComponent("graph-panel", function (container) {
        const host = document.createElement("div");
        host.className = "panel-wrap";
        host.setAttribute("data-testid", "panel-graph");
        host.setAttribute("data-panel-type", "graph");
        host.innerHTML = '<iframe class="panel-iframe" src="/frontend/"></iframe>';
        container.getElement().append(host);
      });
      layout.registerComponent("import-panel", function (container) {
        mountReactNode(container, function () {
          return e("div", { "data-testid": "panel-import", "data-panel-type": "import" }, e(ImportPanel));
        });
      });
      layout.registerComponent("search-panel", function (container) {
        mountReactNode(container, function () {
          return e("div", { "data-testid": "panel-search", "data-panel-type": "search" }, e(SearchPanel));
        });
      });

      let timer = null;
      layout.on("stateChanged", function () {
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          saveCurrentLayout();
        }, 1200);
      });

      layout.init();
      layoutRef.current = layout;
      setStatus("layout loaded");
    };

    useEffect(function () {
      rebuildLayout();
      refreshLayoutNames();
    }, []);

    return e(
      "div",
      { className: "workbench-shell", "data-testid": "workbench-root" },
      e(
        "div",
        { className: "wb-toolbar" },
        e(
          "div",
          { className: "wb-toolbar-group" },
          e("span", { className: "wb-brand" }, "KN Graph Studio"),
          e("span", { className: "wb-chip" }, "Desktop Workbench")
        ),
        e(
          "div",
          { className: "wb-toolbar-group" },
          e("input", {
            value: layoutName,
            list: "layout-name-list",
            onChange: function (evt) {
              setLayoutName(evt.target.value);
            },
            placeholder: "layout name",
          }),
          e(
            "datalist",
            { id: "layout-name-list" },
            knownLayouts.map(function (name) {
              return e("option", { key: "layout-opt-" + name, value: name });
            })
          ),
          e("button", { className: "primary", onClick: rebuildLayout }, "加载布局"),
          e("button", { "data-testid": "save-layout-btn", onClick: saveCurrentLayout }, "保存布局"),
          e("button", { "data-testid": "open-panel-chat", onClick: function () { addPanel("chat"); } }, "+Chat"),
          e("button", { "data-testid": "open-panel-graph", onClick: function () { addPanel("graph"); } }, "+Graph"),
          e("button", { "data-testid": "open-panel-import", onClick: function () { addPanel("import"); } }, "+Import"),
          e("button", { "data-testid": "open-panel-search", onClick: function () { addPanel("search"); } }, "+Search"),
          e("button", { "data-testid": "graph-to-chat-btn", onClick: linkGraphToChat }, "打开 Chat")
        ),
        e(
          "div",
          { className: "wb-toolbar-group" },
          null
        )
      ),
      e("div", { ref: containerRef, className: "wb-layout", id: "workbench-layout" })
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(e(App));
})();
