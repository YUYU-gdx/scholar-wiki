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
    const [optionsText, setOptionsText] = useState('{"llm_provider":"zhipu"}');
    const [jobId, setJobId] = useState("");
    const [resultText, setResultText] = useState("");
    const fileRef = useRef(null);

    const submitFile = async function () {
      try {
        const file = fileRef.current && fileRef.current.files ? fileRef.current.files[0] : null;
        if (!file) {
          setResultText("请选择 PDF 文件");
          return;
        }
        const form = new FormData();
        form.append("file", file, file.name);
        if ((optionsText || "").trim()) {
          form.append("options", optionsText);
        }
        const payload = await jsonFetch("/v1/pipeline/parse-extract", { method: "POST", body: form });
        setJobId(String(payload.job_id || ""));
        setResultText(JSON.stringify(payload, null, 2));
      } catch (err) {
        setResultText(String(err));
      }
    };

    const fetchJob = async function (kind) {
      try {
        if (!jobId) {
          setResultText("请先创建任务");
          return;
        }
        if (kind === "cancel") {
          const payload = await jsonFetch("/v1/jobs/" + encodeURIComponent(jobId) + "/cancel", { method: "POST" });
          setResultText(JSON.stringify(payload, null, 2));
          return;
        }
        const suffix = kind === "result" ? "/result" : "";
        const payload = await jsonFetch("/v1/jobs/" + encodeURIComponent(jobId) + suffix, { method: "GET" });
        setResultText(JSON.stringify(payload, null, 2));
      } catch (err) {
        setResultText(String(err));
      }
    };

    return e(
      "div",
      { className: "panel-body" },
      e("h3", null, "导入 / 解析 / 抽取"),
      e(
        "div",
        { className: "panel-form" },
        e("input", { ref: fileRef, type: "file", accept: "application/pdf" }),
        e("button", { onClick: submitFile }, "上传并创建任务")
      ),
      e(
        "div",
        { className: "panel-form" },
        e("textarea", {
          value: optionsText,
          onChange: function (evt) {
            setOptionsText(evt.target.value);
          },
          placeholder: "options JSON",
        })
      ),
      e(
        "div",
        { className: "panel-form" },
        e("input", {
          value: jobId,
          onChange: function (evt) {
            setJobId(evt.target.value);
          },
          placeholder: "job_id",
        }),
        e("button", { onClick: function () { fetchJob("status"); } }, "查询状态"),
        e("button", { onClick: function () { fetchJob("result"); } }, "查询结果"),
        e("button", { onClick: function () { fetchJob("cancel"); } }, "取消任务")
      ),
      e("pre", { className: "helper" }, resultText || "等待操作")
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
          e(
            "span",
            { className: "status" },
            status,
            knownLayouts.length ? " | layouts: " + knownLayouts.join(", ") : ""
          )
        )
      ),
      e("div", { ref: containerRef, className: "wb-layout", id: "workbench-layout" })
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(e(App));
})();
