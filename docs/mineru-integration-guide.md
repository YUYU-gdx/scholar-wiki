# MinerU 集成完全指南

> 本文档面向需要理解、调用或扩展 MinerU 解析能力的开发者（或 AI 模型）。
> 涵盖所有调用方式、API 协议、数据格式、命名规范与脚本编排。
> **不包含任何 API Key，所有密钥均通过环境变量引用。**

---

## 目录

1. [整体架构](#1-整体架构)
2. [MinerU v4 Precise API 协议详解](#2-mineru-v4-precise-api-协议详解)
3. [单文件解析：mineru_single_pdf_runner.py](#3-单文件解析mineru_single_pdf_runnerrpy)
4. [批量解析：run_mineru_v4_precise_batch.py](#4-批量解析run_mineru_v4_precise_batchpy)
5. [一键编排：run_mineru_v4_precise_storage.py](#5-一键编排run_mineru_v4_precise_storagepy)
6. [Agent 分块解析流水线](#6-agent-分块解析流水线)
7. [CLI 本地解析方式](#7-cli-本地解析方式)
8. [恢复与补捞：recover_mineru_v4_batches.py](#8-恢复与补捞recover_mineru_v4_batchespy)
9. [产物后处理脚本](#9-产物后处理脚本)
10. [Manifest 构建（输入准备）](#10-manifest-构建输入准备)
11. [公共工具模块：mineru_agent_common.py](#11-公共工具模块mineru_agent_commonpy)
12. [命名规范与约定](#12-命名规范与约定)
13. [数据格式字典](#13-数据格式字典)
14. [错误码参考](#14-错误码参考)
15. [完整调用示例](#15-完整调用示例)

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         调用入口层                                   │
│                                                                     │
│  ┌──────────────────────┐  ┌─────────────────────────────────────┐  │
│  │ Pipeline API (8021)  │  │ run_mineru_v4_precise_storage.py   │  │
│  │ (单文件异步解析)      │  │ (一键编排：扫描→清单→批量→下载)      │  │
│  │ → mineru_single_     │  │                                     │  │
│  │   pdf_runner.py      │  └──────────────┬──────────────────────┘  │
│  └──────────┬───────────┘                 │                         │
│             │                             │                         │
│             ▼                             ▼                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │             run_mineru_v4_precise_batch.py                    │   │
│  │          (批量提交+轮询+下载的核心引擎)                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│             │                              ▲                        │
│             ▼                              │                        │
│  ┌─────────────────────┐    ┌───────────────────────────────────┐  │
│  │   MinerU v4 API    │    │   recover_mineru_v4_batches.py     │  │
│  │  (mineru.net/api)  │    │   (从本地痕迹补捞已提交的批次)       │  │
│  └─────────────────────┘    └───────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────┐    ┌───────────────────────────────────┐  │
│  │  MinerU CLI 本地     │    │   Agent 分块流水线                 │  │
│  │  (mineru -i ... -o) │    │   (split→run_agent_chunks→merge)  │  │
│  └─────────────────────┘    └───────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    产物后处理                                │    │
│  │  extract_and_rename │ reorganize_mineru_zips_by_title      │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**三种解析模式**：

| 模式 | 适用场景 | 核心脚本 |
|------|----------|----------|
| v4 Precise（远程 API） | 大批量、高精度解析 | `run_mineru_v4_precise_batch.py` |
| v4 Single（远程 API 封装） | 单文件异步解析（Pipeline API 调用） | `mineru_single_pdf_runner.py` |
| CLI 本地解析 | 小规模、本机已安装 mineru | `literature/service.py` → `_run_mineru_to_dir()` |

---

## 2. MinerU v4 Precise API 协议详解

### 2.1 Base URL

```
默认: https://mineru.net/api/v4
可配置: --base-url 参数或 base_url options 字段
```

### 2.2 认证

所有请求必须携带 HTTP Header：

```
Authorization: Bearer <你的API密钥>
Content-Type: application/json
```

API 密钥通过环境变量获取，**不硬编码在代码中**：
- 环境变量名默认为 `MINERU_API_KEY`
- 可通过 `--api-key-env` 参数自定义（如 `MINERU_API_KEY_V2`）
- 在代码中通过 `os.getenv("MINERU_API_KEY")` 读取

### 2.3 步骤一：创建文件上传 URL（获取 batch_id + upload_url）

**请求**：

```
POST {base_url}/file-urls/batch
```

**请求体（JSON）**：

```json
{
  "files": [
    {
      "name": "10.1111_sj.12345.pdf",
      "data_id": "10_1111_sj_12345"
    }
  ],
  "model_version": "vlm",
  "enable_table": true,
  "is_ocr": false,
  "enable_formula": true,
  "language": "en"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `files` | array | 文件列表，每次只提交 1 个文件（当前实现） |
| `files[].name` | string | PDF 文件名，用于服务端识别 |
| `files[].data_id` | string | 业务标识，通常=`safe_id()` 生成的 ID |
| `model_version` | string | 解析模型版本，默认 `"vlm"` |
| `enable_table` | bool | 是否启用表格识别，默认 `true` |
| `is_ocr` | bool | 是否强制 OCR，默认 `false` |
| `enable_formula` | bool | 是否启用公式识别，默认 `true` |
| `language` | string | 文档语言，默认 `"en"` |

**成功响应（HTTP 200）**：

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "batch_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "file_urls": [
      "https://mineru.net/api/v4/file-upload/presigned-upload-url-xxx"
    ]
  }
}
```

| 响应字段 | 说明 |
|----------|------|
| `code` | `0` = 成功，非 0 = 失败 |
| `data.batch_id` | 批次唯一 ID，后续轮询必需 |
| `data.file_urls[0]` | 预签名上传 URL |

**失败情况**：

- HTTP 非 200 → 检查是否可重试（见 2.6）
- `code != 0` → 业务层错误，检查 `msg`

### 2.4 步骤二：上传 PDF 文件

```
PUT {upload_url}
Content-Type: application/octet-stream (或直接二进制流)
Body: PDF 文件的原始二进制内容
```

- 超时建议：300 秒（大文件需要时间）
- 成功返回 HTTP 200 或 201

### 2.5 步骤三：轮询解析结果

```
GET {base_url}/extract-results/batch/{batch_id}
Authorization: Bearer <API密钥>
```

**成功响应（HTTP 200, code=0）**：

```json
{
  "code": 0,
  "data": {
    "extract_result": [
      {
        "state": "done",
        "file_name": "10.1111_sj.12345.pdf",
        "full_zip_url": "https://mineru.net/api/v4/file-download/xxx.zip",
        "err_msg": ""
      }
    ]
  }
}
```

**状态值（`state` 字段）**：

| state 值 | 含义 | 应对 |
|-----------|------|------|
| `"done"` | 解析完成 | 下载 `full_zip_url` |
| `"failed"` | 解析失败 | 记录 `err_msg`，标记失败 |
| 其他（如 `"processing"`、`"pending"` | 仍在处理 | 继续轮询 |

**轮询参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--poll-interval-seconds` | 8.0 | 两次轮询之间的等待秒数 |
| `--max-poll-seconds` | 3600 | 单任务最大轮询时长（超时后标记失败） |

### 2.6 步骤四：下载结果 ZIP

```
GET {full_zip_url}
```

- ZIP 文件内含解析产物（markdown、HTML、图片等）
- 核心文件：`full.md`（完整 Markdown）
- 超时建议：180 秒

### 2.7 重试机制

| 场景 | 策略 |
|------|------|
| 可重试错误 | HTTP 429/限流/网络超时/频率限制 |
| 不可重试错误 | HTTP 非429 + 非 code=0 的明确业务错误 |
| 重试参数 | `--max-retries 3`, `--retry-delays "8,20,60"`（秒） |
| 抖动 | `_jitter_sleep()`: 随机 ±20% 的基础延迟 |

**判断是否可重试的关键字**（`_is_retryable()`）：

```
"429", "limit", "frequency", "busy", "timeout", "network", "exceeded", "限频", "超时"
```

---

## 3. 单文件解析：mineru_single_pdf_runner.py

### 3.1 定位

这是被 Pipeline API (`serve_async_pipeline_api.py`) 动态加载的**单文件同步封装**。它内部调用 `run_mineru_v4_precise_batch.py` 的 `_submit_one()` 和 `_poll_one()` 完成一次完整的解析。

### 3.2 函数签名

```python
def parse_single_pdf(
    pdf_path: Path,                    # PDF 文件路径
    run_dir: Path,                      # 运行时工作目录
    options: dict[str, Any] | None = None,  # 可选配置
    progress_cb: Callable[[int, str], None] | None = None,  # 进度回调 (percent, stage)
    cancel_cb: Callable[[], bool] | None = None,  # 取消检查回调
) -> dict[str, Any]:
```

### 3.3 options 字典

| 键 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `base_url` | str | `"https://mineru.net/api/v4"` | API 基地址 |
| `model_version` | str | `"vlm"` | 模型版本 |
| `disable_table` | bool | False | 禁用表格识别 |
| `is_ocr` | bool | False | 强制 OCR |
| `disable_formula` | bool | False | 禁用公式识别 |
| `language` | str | `"en"` | 文档语言 |
| `max_retries` | int | 3 | 最大重试次数 |
| `poll_interval_seconds` | float | 8.0 | 轮询间隔 |
| `max_poll_seconds` | int | 3600 | 最大轮询时间 |
| `api_key_env` | str | `"MINERU_API_KEY"` | API 密钥环境变量名 |
| `source_id` | str | `"upload::{pdf文件名}"` | 业务标识 |
| `retry_delays` | str | `"8,20,60"` | 重试延迟序列 |

### 3.4 返回值

```python
{
    "markdown_path": "/path/to/run_dir/parse/parsed.md",
    "html_path": "/path/to/run_dir/parse/parsed.html",
    "zip_path": "/path/to/run_dir/zips/{safe_id}.zip",
    "page_count": 42,
    "batch_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 3.5 异常类型

`MinerUSinglePdfError(code, detail)`:

| code | 含义 |
|------|------|
| `mineru_input_missing` | PDF 文件不存在 |
| `pdf_unreadable` | PyMuPDF 无法读页数（损坏的 PDF） |
| `mineru_api_key_missing` | 环境变量中无 API 密钥 |
| `mineru_submit_failed` | 提交到 MinerU API 失败 (detail=原始 error) |
| `job_cancelled` | cancel_cb 回调返回 True |
| `mineru_poll_timeout` | 超过 max_poll_seconds 仍未完成 |
| `mineru_remote_failed` | 服务端返回 state=failed |
| `mineru_output_missing` | ZIP 中找不到 full.md |
| `pdf_unreadable` | PDF 打开失败或页数 <= 0 |

### 3.6 进度回调

进度回调接收两个参数：`(percent: int, stage: str)`

| stage | percent 范围 | 含义 |
|-------|-------------|------|
| `submit_start` | 8 | 开始提交 |
| `submitted` | 18 | 已提交 |
| `polling` | 20–80 | 轮询中 |
| `parse_done` | 45 | 解析完成 |

### 3.7 解析产物提取

`_extract_full_markdown(zip_path, parse_dir)` 从下载的 ZIP 中：

1. 清空并创建 `{parse_dir}/mineru_zip_unpacked/` 解压目录
2. 解压 ZIP
3. 以 `rglob("full.md")` 搜索 full.md
4. 复制到 `{parse_dir}/parsed.md`
5. 生成 `{parse_dir}/parsed.html`（用 `<pre>` 包裹 Markdown 文本）

---

## 4. 批量解析：run_mineru_v4_precise_batch.py

### 4.1 定位

这是**核心批处理引擎**。它从 JSONL manifest 读取待解析条目，逐条提交到 MinerU v4 API、轮询状态、下载结果，支持断点续跑、日额度控制和并发控制。

### 4.2 命令行使用

```bash
uv run python scripts/smj_pipeline/run_mineru_v4_precise_batch.py \
  --manifest outputs/.../manifest_pdf_v4.jsonl \
  --run-dir outputs/.../run_20260401_120000 \
  --api-key-env MINERU_API_KEY \
  --base-url https://mineru.net/api/v4 \
  --model-version vlm \
  --language en \
  --daily-page-limit 0 \
  --daily-file-limit 5000 \
  --max-inflight 2 \
  --submission-mode coupled \
  --max-retries 3 \
  --retry-delays "8,20,60" \
  --poll-interval-seconds 8.0 \
  --max-poll-seconds 3600 \
  --seed 42
```

### 4.3 完整参数表

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--manifest` | Path | **必填** | JSONL manifest 文件路径 |
| `--run-dir` | Path | **必填** | 运行输出目录 |
| `--api-key-env` | str | `MINERU_API_KEY` | 环境变量名 |
| `--base-url` | str | `https://mineru.net/api/v4` | API 基地址 |
| `--model-version` | str | `vlm` | 解析模型 |
| `--language` | str | `en` | 文档语言 |
| `--enable-table` | flag | True（默认开启） | 启用表格 |
| `--disable-table` | flag | False | 禁用表格 |
| `--is-ocr` | flag | False | 强制 OCR |
| `--enable-formula` | flag | True（默认开启） | 启用公式 |
| `--disable-formula` | flag | False | 禁用公式 |
| `--submit-interval-seconds` | float | 2.0 | 提交间隔 |
| `--poll-interval-seconds` | float | 8.0 | 轮询间隔 |
| `--max-poll-seconds` | int | 3600 | 最大轮询时间 |
| `--max-inflight` | int | 2 | 最大并发在途任务数 |
| `--submission-mode` | `coupled`\|`decoupled` | `coupled` | 提交模式（见 4.5） |
| `--max-submitted-inflight` | int | 0 | decoupled 模式下的并发上限（0=无限） |
| `--max-retries` | int | 3 | 最大重试次数 |
| `--retry-delays` | str | `"8,20,60"` | 重试延迟（逗号分隔秒数） |
| `--daily-page-limit` | int | 0 | 每日页数上限（0=无限） |
| `--daily-file-limit` | int | 5000 | 每日文件数上限（0=无限） |
| `--daily-state-file` | Path | `{run-dir}/daily_quota_state_v4.json` | 日额度状态文件 |
| `--limit` | int | 0 | 仅处理前 N 条（0=全部） |
| `--seed` | int | 42 | 随机种子 |

### 4.4 目录结构产出

```
{run-dir}/
├── checkpoint_v4.json              # 断点续跑 checkpoint
├── daily_quota_state_v4.json       # 日额度追踪
├── run_v4_summary.json             # 运行总结
├── failed.jsonl                    # 失败条目汇总
├── tasks/                          # 每个条目的详细日志
│   ├── {safe_id}/
│   │   ├── request_file_urls.json  # 创建请求体
│   │   ├── response_file_urls.json # 创建响应体
│   │   ├── response_file_urls_status.txt
│   │   ├── response_upload_status.txt
│   │   ├── response_upload.txt
│   │   ├── batch_id.txt            # 批次 ID
│   │   ├── poll_log.json           # 轮询日志
│   │   └── response_final.json     # 最终轮询响应
├── zips/                           # 下载的 ZIP 产物
│   ├── {safe_id}.zip
```

### 4.5 提交模式

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `coupled` | 提交受 `--max-inflight` 限制，只有轮询完成腾出空位才继续提交 | 保守、低额度 |
| `decoupled` | 提交与轮询独立，提交仅受 `--max-submitted-inflight`（若 > 0）限制 | 快速消费 |

### 4.6 断点续跑

checkpoint_v4.json 中每个 item 有 `status` 字段：

| status | 含义 | 续跑处理 |
|--------|------|----------|
| `pending` | 未提交 | 重新提交 |
| `submitted` / `running` | 已提交/轮询中 | 直接恢复轮询 |
| `done` | 已完成 | 跳过 |
| `failed` | 失败（默认不重试） | 跳过（除非手动改回 pending） |

### 4.7 日额度控制

`daily_quota_state_v4.json` 格式：

```json
{
  "date": "2026-04-30",
  "submitted_pages": 1200,
  "submitted_files": 50,
  "done_files": 45,
  "failed_files": 5,
  "updated_at": "2026-04-30T14:30:00"
}
```

- 当 `submitted_pages + 当前文件页数 > daily_page_limit` 时暂停（limit > 0 时生效）
- 当 `submitted_files >= daily_file_limit` 时暂停（limit > 0 时生效）
- 日期变更自动重置计数

---

## 5. 一键编排：run_mineru_v4_precise_storage.py

### 5.1 定位

这是最高层的编排脚本，串联三步：**构建 Manifest → 批量解析 → 生成结果**。

### 5.2 执行流程

```
1. build_storage_pdf_v4_manifest.py  →  生成 manifest_pdf_v4.jsonl
2. run_mineru_v4_precise_batch.py    →  逐条提交+轮询+下载
3. 输出 run_v4_summary.json
```

### 5.3 命令行使用

```bash
uv run python scripts/smj_pipeline/run_mineru_v4_precise_storage.py \
  --pdf-root D:\zoyerofile\storage \
  --run-root outputs/mineru_v4_precise_storage \
  --run-id run_20260401 \
  --max-size-mb 200 \
  --max-pages 200 \
  --max-inflight 1 \
  --submission-mode decoupled
```

### 5.4 参数详解

| 参数 | 说明 |
|------|------|
| `--pdf-root` | PDF 文件根目录，递归扫描所有 `.pdf` |
| `--run-root` | 运行根目录，每次运行会创建 `{run-root}/{run-id}/` 子目录 |
| `--run-id` | 运行 ID（留空则自动生成 `run_{timestamp}`） |
| `--max-size-mb` | 单文件大小上限（MB），默认 200 |
| `--max-pages` | 单文件页数上限，默认 200 |
| `--scan-limit` | 扫描时仅取前 N 个 PDF（0=全部） |
| `--limit` | 提交时仅处理前 N 条（0=全部） |
| 其他参数 | 直接透传给 `run_mineru_v4_precise_batch.py` |

---

## 6. Agent 分块解析流水线

### 6.1 概述

对于大 PDF（B/C 类），采用 "分块提交" 策略：将 PDF 按 `page_range` 拆分，每块单独提交到 MinerU Agent API，最后合并。

### 6.2 编排脚本：run_mineru_agent_class_bc.py

```bash
uv run python scripts/smj_pipeline/run_mineru_agent_class_bc.py \
  --run-root outputs/mineru_agent_class_bc \
  --chunk-pages 20 \
  --limit-chunks 0
```

可选跳过步骤：`--skip-manifest`, `--skip-split`, `--skip-run`, `--skip-merge`

### 6.3 流水线步骤

```
步骤 1: build_class_bc_pdf_manifest.py
  → 扫描 B/C 类 PDF，生成 manifest_pdf.jsonl

步骤 2: split_into_agent_chunks.py
  → 读取 manifest_pdf.jsonl，按 chunk-pages 分块，生成 manifest_chunks.jsonl
  → 每行包含: chunk_id, doi, pdf_path, page_start, page_end, page_range

步骤 3: run_agent_chunks_safe.py
  → 逐块提交到 MinerU Agent API (https://mineru.net/api/v1/agent)
  → 下载每块的解析结果

步骤 4: merge_chunk_markdown.py
  → 合并同一 DOI 的所有分块 markdown
```

### 6.4 分块 Manifest 格式

每行 JSONL：

```json
{
  "chunk_id": "10_1111_sj_12345__1-20",
  "doc_class": "B",
  "doi": "10.1111/sj.12345",
  "pdf_path": "/path/to/10.1111_sj.12345.pdf",
  "file_name": "10.1111_sj.12345.pdf",
  "chunk_index": 0,
  "page_start": 1,
  "page_end": 20,
  "page_range": "1-20",
  "source_page_count": 45
}
```

`chunk_id` 生成规则：`safe_id(f"{doi}__{page_start}-{page_end}")`

---

## 7. CLI 本地解析方式

### 7.1 使用场景

当本机已安装 `mineru` CLI 工具时，可以直接本地调用，不经过远程 API。

### 7.2 调用方式

通过环境变量 `MINERU_CMD` 配置命令模板：

```
默认: mineru -i {input} -o {output}
自定义: MINERU_CMD="mineru --lang en -i {input} -o {output}"
```

- `{input}` → 替换为 PDF 文件路径
- `{output}` → 替换为输出目录路径

### 7.3 代码位置

- `literature/service.py` → `_run_mineru_to_dir()`
- `literature/dataset_tools.py` → `_pdf_to_html_with_mineru()`

### 7.4 产物发现逻辑

```
1. 递归搜索 out_dir 中所有 *.html 文件 → 优先使用
2. 如无 HTML，搜索所有 *.md 文件
3. 都没有 → 抛出 RuntimeError("mineru_no_output")
```

### 7.5 错误码

| 错误信息 | 含义 |
|----------|------|
| `mineru_not_installed:{command}` | `which` 找不到 mineru 命令 |
| `mineru_failed:{detail}` | mineru 进程返回非 0 |
| `mineru_no_output` | mineru 执行成功但无 html/md 产物 |

### 7.6 dataset_tools 中的 normalize_to_html 流程

```
1. 优先使用内联 HTML (row["html"])
2. 无内联 HTML && 源文件是 .pdf → 调用 mineru CLI
3. 无内联 HTML && 源文件是 .html/.htm → 直接读取
4. 无内联 HTML && 源文件是 .md/.txt → 直接读取
```

---

## 8. 恢复与补捞：recover_mineru_v4_batches.py

### 8.1 场景

当批量解析运行中断后，本地可能残留提交时得到的 `batch_id`（分布在 checkpoint、日志等文件中）。本脚本扫描这些痕迹，通过 API 查询每个 batch_id 的状态，下载已完成的结果。

### 8.2 执行流程

```
1. 加载 manifest（获取 DOI 列表用于猜测文件名→DOI 映射）
2. 扫描 search-roots 下的文本文件，正则提取 UUID 格式的 batch_id
3. 对每个候选 batch_id 调用 GET /extract-results/batch/{batch_id}
4. 将有效（code=0）的结果标记为 valid
5. 对 state=done 的结果下载 full_zip_url
6. 输出 recovered_batch_index.jsonl + zips 目录
```

### 8.3 命令行

```bash
uv run python scripts/smj_pipeline/recover_mineru_v4_batches.py \
  --manifest outputs/.../manifest_pdf_v4.jsonl \
  --run-dir outputs/mineru_recovery_20260401_120000 \
  --search-roots outputs/ logs/ \
  --mineru-api-key-env MINERU_API_KEY \
  --base-url https://mineru.net/api/v4
```

### 8.4 产出

```
{run-dir}/
├── checkpoint_discovery.json       # 发现阶段 checkpoint
├── checkpoint_download.json        # 下载阶段 checkpoint
├── recovered_batch_index.jsonl    # 有效批次索引
├── downloads/
│   └── zips_raw/                  # 下载的 ZIP 文件
├── recovery_discovery_summary.json
└── recovery_unpack_summary.json   # (如后续运行 extract_and_rename)
```

---

## 9. 产物后处理脚本

### 9.1 extract_and_rename_mineru_outputs.py

解压 ZIP → 提取 full.md → 按 DOI 或标题重命名。

```bash
uv run python scripts/smj_pipeline/extract_and_rename_mineru_outputs.py \
  --run-dir outputs/mineru_recovery_... \
  --index-jsonl outputs/.../recovered_batch_index.jsonl \
  --zips-dir outputs/.../downloads/zips_raw
```

**命名优先级**：
1. 唯一标题（`full.md` 中的首个 `# 标题`）
2. DOI（`doi_guess` → `_sanitize_name()`)
3. batch_id（`safe_id(batch_id, 120)`）

**产出**：
```
{run-dir}/
├── downloads/
│   ├── unpacked/                  # 解压目录
│   └── final_named/               # 重命名后的 .md 文件
├── naming_map.csv                 # 命名映射 (batch_id → final_name)
├── duplicate_title_report.csv     # 重复标题报告
├── checkpoint_unpack.json         # 解压 checkpoint
└── recovery_unpack_summary.json
```

### 9.2 reorganize_mineru_zips_by_title.py

从 ZIP 文件直接解压并重组织，产出结构化目录：

```bash
uv run python scripts/smj_pipeline/reorganize_mineru_zips_by_title.py \
  --zip-dir outputs/.../zips \
  --out-dir outputs/.../organized
```

**产出**：
```
{out-dir}/
├── markdown/        # {doc_name}.md（含链接重写）
├── pdf/             # {doc_name}.pdf（原始 PDF，如存在）
├── json/            # {doc_name}__{原文件名}.json
├── images/          # {doc_name}/ 图片子目录
└── index.tsv        # 索引文件
```

**链接重写规则**：
- 图片相对路径 `images/xxx` → `../images/{doc_name}/xxx`
- 远程 URL（http/https/ftp/data/mailto）→ 保持不变
- 锚点链接（`#xxx`）→ 保持不变

**Windows 安全文件名**（`sanitize_windows_name()`）：
- 禁止字符 `<>:"/\|?*` → `_`
- 保留名（CON, PRN, AUX 等）→ 加 `_` 前缀
- 去除末尾空格和点号
- 截断至 180 字符

---

## 10. Manifest 构建（输入准备）

### 10.1 build_storage_pdf_v4_manifest.py

扫描本地目录中所有 PDF 文件，生成 v4 批量解析用的 manifest。

```bash
uv run python scripts/smj_pipeline/build_storage_pdf_v4_manifest.py \
  --pdf-root D:\zoyerofile\storage \
  --run-dir outputs/.../run_20260401 \
  --max-size-mb 200 \
  --max-pages 200 \
  --limit 0
```

**Manifest 行格式（v4 precise）**：

```json
{
  "doc_class": "storage",
  "source_id": "storage::relative/path/to/paper.pdf",
  "doi": "storage::relative/path/to/paper.pdf",
  "pdf_path": "D:\\zoyerofile\\storage\\relative\\path\\to\\paper.pdf",
  "file_name": "paper.pdf",
  "file_size_bytes": 3456789,
  "page_count": 42,
  "eligible": true,
  "ineligible_reason": ""
}
```

** ineligible 条件**：
- `file_size_bytes > max_size_bytes` → `"oversize"`
- `page_count <= 0` → `"pdf_unreadable"`
- `page_count > max_pages` → `"over_max_pages"`

**source_id 生成规则**：`f"storage::{pdf_path.relative_to(pdf_root).as_posix()}"`

**产出文件**：
- `manifest_pdf_v4.jsonl` — 全量 manifest
- `manifest_oversize_v4.jsonl` — 超大文件清单
- `manifest_overpages_v4.jsonl` — 超页数清单
- `manifest_unreadable_v4.jsonl` — 不可读文件清单
- `manifest_pdf_v4_summary.json` — 统计信息

### 10.2 build_class_bc_v4_manifest.py

为 B/C 类论文构建 v4 manifest（与 storage 版类似，但输入来自分类 manifest JSONL）。

```bash
uv run python scripts/smj_pipeline/build_class_bc_v4_manifest.py \
  --class-b-manifest outputs/.../manifest_class_b.jsonl \
  --class-c-manifest outputs/.../manifest_class_c.jsonl \
  --pdf-root outputs/.../success/pdf \
  --run-dir outputs/.../bc_run \
  --max-size-mb 200 \
  --max-pages 200
```

**额外产出**：`manifest_no_pdf_v4.jsonl`（有 DOI 但找不到 PDF 的条目）

### 10.3 build_class_bc_pdf_manifest.py

Agent 分块模式用的 manifest 构建（注意：`--max-size-mb` 默认 10，与 v4 的 200 不同）。

```bash
uv run python scripts/smj_pipeline/build_class_bc_pdf_manifest.py \
  --class-b-manifest outputs/.../manifest_class_b.jsonl \
  --class-c-manifest outputs/.../manifest_class_c.jsonl \
  --pdf-root outputs/.../success/pdf \
  --run-dir outputs/.../bc_run
```

---

## 11. 公共工具模块：mineru_agent_common.py

### 11.1 iter_jsonl(path) → Iterator[dict]

逐行读取 JSONL 文件，每行解析为 dict。跳过空行。

### 11.2 write_jsonl(path, rows)

将 dict 列表写入 JSONL 文件（每行一个 JSON，`ensure_ascii=False`，末尾换行）。

### 11.3 write_json(path, payload)

写入格式化 JSON（缩进 2，`ensure_ascii=False`）。

### 11.4 write_json_atomic(path, payload)

原子写入 JSON：先写 `.json.tmp`，再 `replace()` 覆盖目标文件，避免中途崩溃导致文件损坏。

### 11.5 safe_id(text, max_len=96) → str

**核心命名函数**，整个项目中用于生成文件名、目录名、batch item_id 等。

```
规则:
1. 将非 [a-zA-Z0-9._-] 的字符替换为 "_"
2. 合并连续 "_" 为单个 "_"
3. 去除首尾的 "." 和 "_"
4. 如果结果为空，使用 "item"
5. 如果长度 > max_len，取前 (max_len-11) 个字符 + "_" + SHA1 前10位
```

**示例**：
```
safe_id("10.1111/sj.12345", 96)       → "10_1111_sj_12345"
safe_id("storage::path/to/file.pdf", 96) → "storage__path_to_file_pdf"
safe_id("upload::my paper.pdf", 120)    → "upload__my_paper_pdf"
safe_id("abcdefghijk..." (200字符), 96) → "abcdefghijk..._a1b2c3d4e5"  (前85字符 + "_" + hash10位)
```

### 11.6 canonical_pdf_name(path) → str

将文件路径 stem 归一化：`normalize_key(path.stem)` → 去除非 `[a-z0-9]` 字符并转小写。

### 11.7 normalize_key(value) → str

去掉所有非 `[a-z0-9]` 字符，转小写。

### 11.8 find_pdf_for_doi(doi, pdf_index) → Path | None

- 先对 DOI 做 `normalize_key()` 查找
- 如果找不到，尝试从 DOI 中提取 `1002smj\d+` 模式的短关键词做模糊匹配

---

## 12. 命名规范与约定

### 12.1 文件命名

| 场景 | 命名规则 | 示例 |
|------|----------|------|
| 任务子目录 | `safe_id(item_id, 120)` | `tasks/10_1111_sj_12345/` |
| ZIP 产物 | `safe_id(batch_id, 120) + ".zip"` | `zips/a1b2c3d4_e5f6_7890_abcd_ef1234567890.zip` |
| Manifest 文件 | `{描述}_v4.jsonl` 或 `{描述}.jsonl` | `manifest_pdf_v4.jsonl` |
| Checkpoint 文件 | `checkpoint_*.json` | `checkpoint_v4.json`, `checkpoint_unpack.json` |
| 日志文件 | `response_*.json`, `response_*.txt` | `response_file_urls.json` |
| 总结文件 | `*_summary.json` | `run_v4_summary.json` |

### 12.2 状态枚举值

#### item 状态（checkpoint 中）

| 值 | 含义 |
|----|------|
| `pending` | 等待提交 |
| `submitted` | 已提交到 API |
| `running` | 已提交且正在轮询 |
| `done` | 完成（ZIP 已下载） |
| `failed` | 失败（不可重试） |

#### 解析产物状态（extract_and_rename 中）

| 值 | 含义 |
|----|------|
| `done` | 解压并重命名成功 |
| `failed` | 失败 |
| `missing_md` | ZIP 中找不到 full.md |

#### 发现阶段状态（recover 中）

| 值 | 含义 |
|----|------|
| `pending` | 未检查 |
| `valid` | API 确认有效 |
| `invalid` | API 返回错误 |

### 12.3 时间戳格式

所有时间戳使用 ISO 8601 格式：`2026-04-30T14:30:00.123456`

运行 ID 时间戳格式：`20260430_143000`（用于目录名）

### 12.4 JSONL 约定

- 每行一个有效 JSON 对象
- 空行跳过
- 编码：UTF-8
- `ensure_ascii=False`（保留中文）

### 12.5 原子写入

所有重要文件（checkpoint、state）使用 `write_json_atomic()`：
1. 写入 `{path}.json.tmp`
2. `path.replace()` 原子替换

---

## 13. 数据格式字典

### 13.1 v4 Manifest 行（JSONL）

```json
{
  "item_id": "10_1111_sj_12345",
  "doi": "10.1111/sj.12345",
  "source_id": "storage::path/to/paper.pdf",
  "doc_class": "storage",
  "pdf_path": "/absolute/path/to/paper.pdf",
  "file_name": "paper.pdf",
  "page_count": 42,
  "file_size_bytes": 3456789
}
```

### 13.2 Checkpoint 条目（checkpoint_v4.json）

```json
{
  "item_id": "10_1111_sj_12345",
  "doi": "10.1111/sj.12345",
  "source_id": "storage::...",
  "doc_class": "storage",
  "pdf_path": "/absolute/path",
  "file_name": "paper.pdf",
  "page_count": 42,
  "file_size_bytes": 3456789,
  "status": "done",
  "batch_id": "uuid-here",
  "zip_path": "/path/to/zips/10_1111_sj_12345.zip",
  "full_zip_url": "https://...",
  "attempt": 1,
  "started_at": "2026-04-30T10:00:00",
  "submitted_at": "2026-04-30T10:00:05",
  "next_poll_at": 1746012345.67,
  "updated_at": "2026-04-30T10:05:00",
  "finished_at": "2026-04-30T10:10:00"
}
```

### 13.3 提交请求体

```json
{
  "files": [
    {
      "name": "paper.pdf",
      "data_id": "10_1111_sj_12345"
    }
  ],
  "model_version": "vlm",
  "enable_table": true,
  "is_ocr": false,
  "enable_formula": true,
  "language": "en"
}
```

### 13.4 运行总结（run_v4_summary.json）

```json
{
  "run_dir": "/path/to/run_dir",
  "manifest": "/path/to/manifest_pdf_v4.jsonl",
  "total_records": 500,
  "submitted_now": 480,
  "done_now": 450,
  "failed_now": 30,
  "pending_left": 20,
  "inflight_left": 0,
  "daily_state_file": "/path/to/daily_quota_state_v4.json",
  "daily_state": {
    "date": "2026-04-30",
    "submitted_pages": 12000,
    "submitted_files": 480,
    "done_files": 450,
    "failed_files": 30
  },
  "pause_reason": "",
  "checkpoint": "/path/to/checkpoint_v4.json"
}
```

### 13.5 单文件解析结果（parse_meta.json）

```json
{
  "markdown_path": "/path/to/parsed.md",
  "html_path": "/path/to/parsed.html",
  "zip_path": "/path/to/zips/safe_id.zip",
  "page_count": 42,
  "batch_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

## 14. 错误码参考

### 14.1 MinerUSinglePdfError 错误码

| code | 触发条件 | 可恢复 |
|------|----------|--------|
| `mineru_input_missing` | PDF 文件路径不存在 | 否（需修正路径） |
| `pdf_unreadable` | PyMuPDF 无法读取或页数 <= 0 | 否（损坏的 PDF） |
| `mineru_api_key_missing` | 环境变量中无 API 密钥 | 否（需配置环境变量） |
| `mineru_submit_failed` | API 提交失败（含原始 error 信息） | 视 error 类型 |
| `job_cancelled` | cancel_cb 返回 True | 否（用户主动取消） |
| `mineru_poll_timeout` | 超过 max_poll_seconds | 是（可延长超时重试） |
| `mineru_remote_failed` | 服务端返回 state=failed | 视 err_msg |
| `mineru_output_missing` | ZIP 中无 full.md | 否 |

### 14.2 批量引擎错误信息格式

| 格式 | 示例 |
|------|------|
| `create_http:{status_code}` | `create_http:429` |
| `create_code:{code}:{msg}` | `create_code:1001:rate_limit` |
| `missing_batch_id_or_upload_url` | 创建成功但响应缺少关键字段 |
| `upload_http:{status_code}` | `upload_http:403` |
| `poll_http:{status_code}` | `poll_http:502` |
| `poll_code:{code}:{msg}` | `poll_code:1002:processing` |
| `remote_failed:{err_msg}` | `remote_failed:conversion_error` |
| `poll_timeout` | 超过 max_poll_seconds |
| `exception:{type}:{message}` | `exception:ConnectionError:timeout` |

### 14.3 dataset_tools 错误归一化

| 原始错误模式 | 归一化码 |
|--------------|----------|
| `mineru_not_installed:*` | `pdf_mineru_unavailable` |
| `mineru_failed:*` | `pdf_mineru_failed` |
| `mineru_no_output` | `pdf_mineru_no_output` |
| 其他 | 保持原样 |

---

## 15. 完整调用示例

### 15.1 单文件解析（Python 代码调用）

```python
from pathlib import Path
from mineru_single_pdf_runner import parse_single_pdf

result = parse_single_pdf(
    pdf_path=Path("paper.pdf"),
    run_dir=Path("outputs/single_parse"),
    options={
        "base_url": "https://mineru.net/api/v4",
        "model_version": "vlm",
        "language": "en",
        "poll_interval_seconds": 10.0,
        "max_poll_seconds": 1800,
    },
    progress_cb=lambda pct, stage: print(f"[{pct}%] {stage}"),
)
print(result["markdown_path"])  # parsed.md 的路径
print(result["page_count"])      # PDF 页数
```

### 15.2 批量解析（命令行）

```bash
# 步骤1：构建 manifest
uv run python scripts/smj_pipeline/build_storage_pdf_v4_manifest.py \
  --pdf-root /path/to/pdfs \
  --run-dir outputs/batch_run \
  --max-size-mb 200 \
  --max-pages 200

# 步骤2：运行批量解析
uv run python scripts/smj_pipeline/run_mineru_v4_precise_batch.py \
  --manifest outputs/batch_run/manifest_pdf_v4.jsonl \
  --run-dir outputs/batch_run \
  --base-url https://mineru.net/api/v4 \
  --max-inflight 2 \
  --daily-file-limit 500

# 步骤3（如中断后恢复）：
uv run python scripts/smj_pipeline/recover_mineru_v4_batches.py \
  --manifest outputs/batch_run/manifest_pdf_v4.jsonl \
  --run-dir outputs/recovery \
  --search-roots outputs/batch_run

# 步骤4：解压重命名
uv run python scripts/smj_pipeline/extract_and_rename_mineru_outputs.py \
  --run-dir outputs/recovery
```

### 15.3 一键编排（Storage 模式）

```bash
uv run python scripts/smj_pipeline/run_mineru_v4_precise_storage.py \
  --pdf-root /path/to/pdfs \
  --run-root outputs/mineru_v4 \
  --max-inflight 1 \
  --submission-mode decoupled \
  --daily-file-limit 1000
```

### 15.4 B/C 类分块解析

```bash
uv run python scripts/smj_pipeline/run_mineru_agent_class_bc.py \
  --run-root outputs/mineru_agent_bc \
  --chunk-pages 20
```

### 15.5 CLI 本地解析（环境变量配置）

```bash
# 在 .env 中设置：
MINERU_CMD=mineru -i {input} -o {output}

# 或自定义命令：
MINERU_CMD="mineru --lang zh -i {input} -o {output}"
```

### 15.6 ZIP 产物重组织

```bash
uv run python scripts/smj_pipeline/reorganize_mineru_zips_by_title.py \
  --zip-dir outputs/batch_run/zips \
  --out-dir outputs/organized
```

---

## 附录 A：脚本索引

| 脚本 | 位置 | 用途 |
|------|------|------|
| `mineru_agent_common.py` | `scripts/smj_pipeline/` | 公共工具（safe_id, JSONL, 原子写入） |
| `mineru_single_pdf_runner.py` | `scripts/smj_pipeline/` | 单文件同步解析封装 |
| `run_mineru_v4_precise_batch.py` | `scripts/smj_pipeline/` | v4 Precise 批量解析核心引擎 |
| `run_mineru_v4_precise_storage.py` | `scripts/smj_pipeline/` | 一键编排（扫描→清单→批量） |
| `run_mineru_agent_class_bc.py` | `scripts/smj_pipeline/` | B/C 类分块一键编排 |
| `build_storage_pdf_v4_manifest.py` | `scripts/smj_pipeline/` | 构建 Storage 模式 manifest |
| `build_class_bc_v4_manifest.py` | `scripts/smj_pipeline/` | 构建 B/C 类 v4 manifest |
| `build_class_bc_pdf_manifest.py` | `scripts/smj_pipeline/` | 构建 B/C 类 Agent manifest |
| `split_into_agent_chunks.py` | `scripts/smj_pipeline/` | PDF → 分块拆分 |
| `recover_mineru_v4_batches.py` | `scripts/smj_pipeline/` | 断点恢复与补捞 |
| `extract_and_rename_mineru_outputs.py` | `scripts/smj_pipeline/` | ZIP 解压 + 重命名 |
| `reorganize_mineru_zips_by_title.py` | `scripts/smj_pipeline/` | ZIP → 结构化目录 |

## 附录 B：环境变量

| 变量名 | 用途 | 默认值 |
|--------|------|--------|
| `MINERU_API_KEY` | v4 API 密钥 | （无默认值，必须设置） |
| `MINERU_CMD` | CLI 本地调用命令模板 | `mineru -i {input} -o {output}` |

## 附录 C：v4 API 端点汇总

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/file-urls/batch` | 创建批次+获取上传 URL |
| PUT | `{upload_url}` | 上传 PDF 二进制 |
| GET | `/extract-results/batch/{batch_id}` | 轮询解析结果 |
| GET | `{full_zip_url}` | 下载结果 ZIP |