# KN Graph ��Ŀ��������

## ���̹淶

- Ĭ�����̼��ܣ�`using-superpowers`���ڱ��ֿ��ڣ�������ִ��ʵ�ֻ����ǰ��Ӧ���ȵ��ò���ѭ `using-superpowers`��
- Python ����������ִ��ͳһʹ�� `uv`��
- �Ͻ�Ҫ�������û���д��ճ����༭ JSON ���ã������û������������ͨ����ȷ�ı����ؼ��ṩ��
- ִ�� Bash ����ʱ������ʼ�����ú����� timeout ���������룩����ֹ�޳�ʱ�������ȴ�����̨����Ӧʹ�� `Start-Process` �����������ý��������ѯȷ�Ͼ��������������ڽ�������ϡ�

## ��Ŀ����

KN Graph ������ѧ�����׵�֪ʶͼ�׹������ʴ�ƽ̨����������Χ�ƹ�Ӧ���������ĵĽ�����ʵ���ȡ����ϵ���������ӻ�����������ʴ�

## ��Ŀ�ṹ

```
kn_gragh/
������ src/kn_graph/                  �� ����������ع��У������ scripts/��
������ scripts/smj_pipeline/          �� ��ǰ�����ڣ���Ǩ�ƣ�
��   ������ serve_graph_api.py          �� ͼ��/Chat/���� API���˿� 8013��
��   ������ serve_async_pipeline_api.py �� �첽 Pipeline API���˿� 8021��
��   ������ kn_mcp_server.py            �� MCP ���߷�������stdin/stdout��
��   ������ ...                         �� ҵ��ű�����ȡ�����ݴ�����
������ config/                        �� LLM Provider ����
������ prompt/                         �� ��ȡ��ʾ��ģ��
������ outputs/                        �� ���в��graph_views.json �ȣ�
������ tests/                          �� ����
������ docs/                           �� �ĵ�
```

## ������ʽ

### ͳһ API ����Ŀ��ܹ�����ʵ�֣�

```bash
uv run python -m kn_graph serve --port 8013
```

### ��ǰ������ʽ���ع�ǰ��

```bash
# ͼ�� + Chat + ���� API
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013 --views-json outputs/.../graph_views.json --allow-non-supply-chain

# �첽 Pipeline API
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --host 127.0.0.1 --port 8021

# �������������Զ����������������� + ���������
uv run python scripts/smj_pipeline/app_launcher.py
```

### MCP ���߷�����

```bash
uv run python scripts/smj_pipeline/kn_mcp_server.py
```

## �ؼ�����

| �������� | ��; | Ĭ��ֵ |
|----------|------|--------|
| `KN_GRAPH_PORT` | Graph API �˿� | `8013` |
| `KN_ASYNC_PIPELINE_PORT` | �첽 Pipeline �˿� | `8021` |
| `CHAT_STORE_DSN` | Chat �洢 DSN | �ڴ� |
| `PIPELINE_JOB_STORE_DSN` | Pipeline �洢 DSN | SQLite |
| `PIPELINE_EXECUTOR` | ִ�������� | `inline` |
| `PIPELINE_REDIS_URL` | Celery broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | ���� API ��Կ | �� |
| `NVIDIA_API_KEY` | NVIDIA API ��Կ | �� |
| `LLM_PROVIDER_CONFIG_PATH` | LLM ����·�� | `config/llm_providers.json` |
| `CHROMADB_PATH` | ChromaDB 持久化目录 | `{data_dir}/chromadb` |

## �ع�״̬

- **������**����˺ϲ�Ϊ�� FastAPI Ӧ�ã���� `docs/superpowers/specs/2026-04-30-backend-unification-design.md`
- **��ֹ**����Ҫ�������޸� `frontend/` Ŀ¼�µ��κ�����

## ��� API �˵����

### �˿� 8013��Graph API �� �ع�ǰ��

| �� | �˵��� | �ؼ�·�� |
|----|--------|----------|
| Graph | 7 | `/graph/overview`, `/graph/full`, `/graph/search`, `/graph/neighborhood`, `/paper/{id}`, `/paper/{id}/files`, `/variable/{id}` |
| Chat | 15 | `/chat/sessions/*`, `/chat/codex/*`, `/chat/provider-*` |
| Literature | 4 | `/literature/search`, `/literature/libraries`, `/literature/import`, `/literature/answer` |
| Workspace | 3 | `/api/v2/workspace/layout*` |

### �˿� 8021��Pipeline API �� �ع�ǰ��

| �� | �˵��� | �ؼ�·�� |
|----|--------|----------|
| Health | 2 | `/healthz`, `/v1/pipeline/health` |
| Jobs | 5 | `/v1/jobs`, `/v1/jobs/{id}`, `/v1/jobs/{id}/result`, `/v1/jobs/{id}/cancel`, `/v1/jobs/{id}/retry` |
| Pipeline | 2 | `/v1/pipeline/parse-extract`, `/v1/pipeline/parse-extract/batch` |
| SSE | 1 | `/v1/jobs/{id}/events` |

## ����

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```
