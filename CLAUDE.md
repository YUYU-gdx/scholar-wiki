# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# KN Graph

瀛︽湳鏂囩尞鐭ヨ瘑鍥捐氨鏋勫缓涓庨棶绛斿钩鍙帮紝鑱氱劍渚涘簲閾剧爺绌舵柟鍚戙€?
## 蹇€熷惎鍔?
```bash
# 鏂扮粺涓€鍏ュ彛锛團astAPI 鍗曟湇鍔★紝閲嶆瀯涓級锛?uv run python -m kn_graph serve --port 8013

# 鏃х増鍏ュ彛锛堜粛鍦ㄤ娇鐢級锛?# 涓?API 鏈嶅姟锛堝浘璋?+ 瀵硅瘽 + 鏂囩尞 + 宸ヤ綔鍖猴級锛岀鍙?8013
uv run python -m kn_graph serve --port 8013

# 寮傛绠＄嚎 API锛圥DF 瑙ｆ瀽 + 鎶藉彇浠诲姟锛夛紝绔彛 8021
uv run python -m kn_graph serve --port 8013

# 妗岄潰鍚姩鍣紙鍚屾椂鍚姩涓や釜鏈嶅姟骞舵墦寮€娴忚鍣級
uv run python -m kn_graph serve --port 8013

# 鍚姩 Celery worker锛堝垎甯冨紡绠＄嚎鎵ц锛?uv run python -m kn_graph worker
```

## 甯哥敤鍛戒护

```bash
# 杩愯鍏ㄩ儴娴嬭瘯锛坲nittest锛?uv run python -m unittest discover -s tests -p "test_*.py" -v

# 杩愯鍏ㄩ儴娴嬭瘯锛坧ytest锛?uv run pytest tests/ -v

# 杩愯鍗曚釜娴嬭瘯鏂囦欢
uv run python -m unittest tests/test_provider_registry.py -v
uv run pytest tests/test_provider_registry.py -v

# 杩愯鍗曚釜娴嬭瘯鐢ㄤ緥
uv run python -m unittest tests.test_provider_registry.TestProviderRegistry.test_load_config -v
uv run pytest tests/test_provider_registry.py::TestProviderRegistry::test_load_config -v
```

## 鏋舵瀯姒傝

### 褰撳墠鐘舵€侊細鍙屾湇鍔★紙姝ｅ湪缁熶竴锛?
1. **serve_graph_api.py** 鈥?鍩轰簬 stdlib `http.server`锛岀鍙?8013銆傚鐞嗗浘璋辫鍥俱€佸璇濅細璇濄€佹枃鐚绱€佸伐浣滃尯甯冨眬鍙婇潤鎬佸墠绔墭绠°€傚崟鏂囦欢绾?2000 琛屻€?2. **serve_async_pipeline_api.py** 鈥?鍩轰簬 FastAPI锛岀鍙?8021銆傚鐞?PDF 涓婁紶 鈫?瑙ｆ瀽 鈫?鎶藉彇鐨勭绾夸换鍔＄敓鍛藉懆鏈熴€?3. **kn_mcp_server.py** 鈥?stdin/stdout 鏂瑰紡鐨?MCP 宸ュ叿鏈嶅姟锛堥潪 HTTP锛夈€備负 Codex CLI 鎻愪緵 `rag_search` 鍜?`graph_search` 宸ュ叿銆?
### 鐩爣鐘舵€侊細鍗曚竴 FastAPI 搴旂敤 (`src/kn_graph/`)

閲嶆瀯灏嗕袱涓湇鍔″悎骞跺埌 `src/kn_graph/`锛岄噰鐢ㄥ熀浜庤矾鐢辩殑妯″潡鍖栬璁°€傝瑙?`docs/superpowers/specs/2026-04-30-backend-unification-design.md`銆?
```
src/kn_graph/
鈹溾攢鈹€ __main__.py          # 鍏ュ彛锛歱ython -m kn_graph serve|worker
鈹溾攢鈹€ app.py               # FastAPI 搴旂敤宸ュ巶锛屾寕杞芥墍鏈夎矾鐢?鈹溾攢鈹€ config.py            # Pydantic Settings锛堢幆澧冨彉閲忓墠缂€ KN_GRAPH_锛?鈹溾攢鈹€ routers/             # /graph/*, /chat/*, /literature/*, /pipeline/*, /workspace/*
鈹溾攢鈹€ models/              # Pydantic 璇锋眰/鍝嶅簲妯″瀷
鈹溾攢鈹€ services/            # 涓氬姟閫昏緫
鈹溾攢鈹€ migration.py         # 鏃ф暟鎹縼绉?鈹斺攢鈹€ workers/celery_app.py
```

鏂版棫鏈嶅姟鐨?URL 璺緞淇濇寔涓€鑷淬€?
### 鎶藉彇绠＄嚎锛堟牳蹇冧笟鍔￠€昏緫锛?
PDF 涓婁紶 鈫?MinerU 瑙ｆ瀽锛堚啋 markdown锛夆啋 LLM 鎶藉彇锛堚啋 缁撴瀯鍖?JSON锛屾寜 `extraction/schemas.py` 瀹氫箟锛夆啋 鏍￠獙 鈫?鍙€変汉宸ュ鏍?鈫?Postgres 鍏ュ簱 鈫?`build_graph_views.py` 鈫?`graph_views.json` 鐢?API 瀵瑰鏈嶅姟銆?
鍏抽敭绠＄嚎鑴氭湰浣嶄簬 `src/kn_graph/services/`锛?- `extraction/schemas.py` 鈥?鎶藉彇缁撴瀯鐨?Pydantic 妯″瀷锛堝彉閲忋€佺洿鎺ユ晥搴斻€佷氦浜掋€佽皟鑺傦級
- `extraction/extractor.py` 鈥?LLM 鎶藉彇鎵ц鍣?- `extraction/validator.py` 鈥?鎶藉彇鍚庢牎楠?- `storage/postgres_repo.py` 鈥?Postgres DDL 涓?CRUD
- `import_raw_outputs_to_postgres.py` 鈥?鎵归噺鍏ュ簱
- `build_graph_views.py` 鈥?浠?Postgres 鏋勫缓 `graph_views.json`

### graph_views.json

API 娑堣垂鐨勬牳蹇冨彧璇绘暟鎹骇鐗┿€傚寘鍚妭鐐癸紙鍙橀噺/姒傚康锛夈€佽竟锛堢洿鎺ユ晥搴旓級銆佽皟鑺傞摼鎺ャ€佷氦浜掗摼鎺ャ€佽鏂囧厓鏁版嵁鍙婃悳绱㈢储寮曘€傜敱 `build_graph_views.py` 浠?Postgres 鏋勫缓銆侫PI 閫氳繃 `active.json` 鈫?搴撴敞鍐岃〃 鈫?宸ヤ綔鍖鸿矾寰勬潵瑙ｆ瀽浣跨敤鍝釜 views 鏂囦欢銆?
### 鏂囩尞妫€绱?
鍩轰簬瀛︽湳璁烘枃鐗囨鐨勬贩鍚堝叧閿瘝+鍚戦噺妫€绱€侰hromaDB锛堝祵鍏ュ紡鍚戦噺鏁版嵁搴擄級瀛樺偍宓屽叆鍚戦噺锛孲QLite FTS5 鎻愪緵 BM25 鍏抽敭璇嶆绱紝RRF 铻嶅悎鎺掑簭銆備互鏂囩尞搴撲负鍗曚綅闅旂瀛樺偍銆?
### 瀵硅瘽鏈嶅姟

鍩轰簬 Codex CLI 鐨?Agent RAG 瀵硅瘽銆備細璇濆瓨鍌ㄥ湪 SQLite锛坄chat/store.sqlite`锛夈€傚璇濇湇鍔″皢鏂囩尞妫€绱€佸浘璋辨悳绱€佽鏂?鍙橀噺鏌ヨ鍙?Codex runner 閰嶇疆涓茶仈鍦ㄤ竴璧枫€?
### scholarai-workbench/

鐙珛鐨勫墠绔簲鐢紙Node.js / React + Vite + Tailwind锛夛紝鐢ㄤ簬闃呰鍜屾壒娉ㄥ鏈鏂囥€傚熀浜?Google AI Studio 搴旂敤妯℃澘鏋勫缓銆?*涓嶅悓浜?*宸插簾寮冪殑 `frontend/` 鐩綍锛堣鐩綍绂佹淇敼锛夈€?
## 閰嶇疆

| 鐜鍙橀噺 | 鐢ㄩ€?| 榛樿鍊?|
|---------------------|---------|---------|
| `KN_GRAPH_PORT` | 涓?API 绔彛 | `8013` |
| `KN_ASYNC_PIPELINE_PORT` | 绠＄嚎 API 绔彛 | `8021` |
| `CHAT_STORE_DSN` | 瀵硅瘽瀛樺偍 DSN | 鍐呭瓨 |
| `PIPELINE_JOB_STORE_DSN` | 绠＄嚎浠诲姟瀛樺偍 DSN | SQLite |
| `PIPELINE_EXECUTOR` | 鎵ц鍣ㄧ被鍨嬶紙`inline` 鎴?`celery`锛?| `inline` |
| `PIPELINE_REDIS_URL` | Celery broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | 鏅鸿氨 API 瀵嗛挜 | 鈥?|
| `NVIDIA_API_KEY` | NVIDIA API 瀵嗛挜 | 鈥?|
| `LLM_PROVIDER_CONFIG_PATH` | LLM 閰嶇疆鏂囦欢璺緞 | `config/llm_providers.json` |
| `CHROMADB_PATH` | ChromaDB 鎸佷箙鍖栫洰褰?| `{data_dir}/chromadb` |
| `GRAPH_EMBEDDING_MODEL` | 鍥捐氨鎼滅储鍙€夊祵鍏ユā鍨?| 锛堝搱甯屽洖閫€锛?|
| `LITERATURE_LIBRARY_INDEX_ROOT` | 鏂囩尞搴撶储寮曟牴鐩綍 | `outputs/literature_libraries` |
| `CHAT_CODEX_CONFIG_PATH` | Codex runner 閰嶇疆 | `outputs/chat/codex_runner_config.json` |

鎵€鏈夐厤缃」浣跨敤 `KN_GRAPH_` 鐜鍙橀噺鍓嶇紑銆傛湰鍦板紑鍙戣灏?`.env.example` 澶嶅埗涓?`.env`銆?
## Run 绠＄悊

绠＄嚎杈撳嚭鎸?run 缁勭粐鍦?`outputs/runs/` 涓嬨€俙outputs/runs/active.json` 鎸囧悜褰撳墠娲昏穬鐨?run銆備娇鐢?`src/kn_graph/services/` 涓殑鑴氭湰绠＄悊锛?- `list_runs.py` 鈥?鍒楀嚭鍙敤 run
- `activate_run.py` 鈥?鍒囨崲娲昏穬 run
- `finalize_batch_run.py` 鈥?瀹屾垚涓€涓壒閲?run

## 鏂囨。绱㈠紩

- 椤圭洰瑙勭害鎬昏锛歚docs/project_spec_index.md`
- 鍥捐氨 API 瑙勭害锛歚docs/api.md`
- 寮傛绠＄嚎 API 瑙勭害锛歚docs/async_pipeline_api.md`
- 鏁版嵁妯″瀷瑙勭害锛歚docs/data_model.md`
- 鏂囦欢瀛樺偍涓庣鍙ｈ绾︼細`docs/storage_and_port_conventions.md`
- 鍚庣缁熶竴璁捐锛歚docs/superpowers/specs/2026-04-30-backend-unification-design.md`

## 閲嶆瀯鐘舵€?
- **杩涜涓?*锛氬悗绔粺涓€涓哄崟涓€ `src/kn_graph/` FastAPI 鍖呫€傝繃娓℃湡闂?`src/kn_graph/services/` 涓殑鏃ц剼鏈粛鍙甯镐娇鐢ㄣ€傛柊浠ｇ爜搴旀斁鍏?`src/kn_graph/`銆?- **绂佹**锛氫笉寰楀垱寤烘垨淇敼 `frontend/` 鐩綍鐨勪换浣曞唴瀹广€?
## LLM 鎻愪緵鍟嗛厤缃?
- 閰嶇疆鏂囦欢锛歚config/llm_providers.json`
- 瀵硅瘽銆佸紓姝ョ绾垮拰鎶藉彇鍧囦娇鐢ㄥ悓涓€涓彁渚涘晢娉ㄥ唽琛細`src/kn_graph/providers/registry.py`
- 瑕嗙洊閰嶇疆璺緞锛歚set LLM_PROVIDER_CONFIG_PATH=path/to/config.json`

# 打包方案

打包出的所有结果和过程产物放到`D:\Code\kn_gragh\dist_exe`

  A. 连接隔离（最关键）

  - 删除 preload 的硬编码 BACKEND_BASE=8013。
  - API 初始化改为“启动时异步拿主进程 runtime url（IPC）”，并缓存。
  - 安装版 main.cjs 禁止复用外部已有后端（你已经做了大半），且固定基准端口 8014。
  - 增加后端握手校验：前端首次请求 /healthz 时带一个随机 session token，主进程启动后端时注入同 token，不匹配就拒绝（彻底防串到 dev）。

  B. 目录隔离

  - dev（命令行前后端分离）：
      - 强制固定 KN_GRAPH_DATA_DIR=D:\AppData\KNGraphApp-dev（写死，不读系统环境）。
  - 安装版：
      - 强制 data_dir=<安装目录>\data
      - 强制 workspaces_dir=<安装目录>\workspaces（或 <安装目录>\data\workspaces，二选一，建议后者更整齐）
  - 后端 Settings 中生产模式禁止从 os.getenv("KN_GRAPH_DATA_DIR")覆盖，避免外部污染。

  C. 构建隔离（每次都重建后端）

  - 新增单一发布命令 npm run dist:release（在 scholarai-workbench）：
      1. uv run pyinstaller ..\kn_graph.spec
      2. 拷贝 ..\dist\kn_graph.exe -> ..\dist_exe\kn_graph.exe
      3. electron-builder
  - 禁止直接用 npm run dist 发版（可保留但 CI/文档只允许 dist:release）。
  - 在打包前做强校验：如果 dist_exe/kn_graph.exe 时间戳早于 src/kn_graph 最新改动，直接失败。

  D. 可观测性（防回归）

  - 增加 /v1/runtime/info 返回：
      - mode(dev|packaged)
      - port
      - data_dir
      - workspaces_dir
      - backend_exe
      - pid
  - 设置页显示这几个字段，一眼看出是否串环境。