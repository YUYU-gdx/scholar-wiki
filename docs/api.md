# ͼ�� API ��Լ

## 1. ������Ϣ
- ����ű���`scripts/smj_pipeline/serve_graph_api.py`
- Ĭ�ϵ�ַ��`http://127.0.0.1:8013`
- Ĭ��������Դ��`outputs/runs/active.json` ָ��� `graph_views.json`
- Ĭ�����ݷ�Χ���ƣ������� `outputs/smj_supply_chain_batch` �µ� `graph_views.json`������ſ�������ʽ�� `--allow-non-supply-chain`

## 2. ����������ѡ��
- ʹ�û run��
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013
```
- ��ʽָ����ͼ�ļ���
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --views-json outputs/runs/<run_id>/graph_views.json --port 8013
```

## 3. ͨ��Լ��
- ���нӿڷ��� `application/json; charset=utf-8`����̬��Դ���⣩��
- ��ѯ������������
  - �ַ�������Ϊ��ʱ��Ĭ��ֵ������
  - ��ֵ�����Ƿ��ᴥ�� Python ת���쳣����ǰ��ͳһ�����װ����
- 404 ������
  - `/paper/{id}` �Ҳ������� `{"error":"paper_not_found","paper_id":"..."}`��
  - `/variable/{id}` �� `/graph/neighborhood?node_id=...` �Ҳ������� `{"error":"node_not_found","node_id":"..."}`��

## 4. API �б�

### 4.1 `GET /graph/full`
- ��;������ȫ��ͼ���ݡ�
- ��Ӧ��
  - `meta`
  - `nodes[]`
  - `edges[]`
  - `moderation_links[]`
  - `interaction_links[]`

### 4.2 `GET /graph/overview`
- ��;������Ԥ���������ͼ�������������٣���
- ��Ӧ��
  - `meta`
  - `nodes[]`��`overview.node_ids` ��Ӧ�ڵ㣩
  - `edges[]`��`overview.edge_indexes` ��Ӧ�ߣ�
  - `moderation_links[]`
  - `interaction_links[]`

### 4.3 `GET /graph/neighborhood`
- ��;������ĳ�ڵ�ľֲ�����
- ������
  - `node_id` ����
  - `hops` Ĭ�� `1`
  - `limit_nodes` Ĭ�� `350`
  - `limit_edges` Ĭ�� `900`
- ��Ӧ��
  - `node_id`
  - `nodes[]`
  - `edges[]`
  - `moderation_links[]`��������ڵ���أ�
  - `interaction_links[]`��������ڵ���أ�

### 4.4 `GET /graph/search`
- ��;������/���ļ������ؼ��� + ���ع�ϣ����������֣���
- ������
  - `mode=variable|paper`��Ĭ�� `variable`
  - `query` �� `q`
  - `limit` �� `top_k`��Ĭ�� `20`
  - `keyword_weight`��Ĭ�� `0.5`
  - `vector_weight`��Ĭ�� `0.5`
  - `vector_backend`���ɴ� `hash|embedding`����ǰʵ��ʹ�� `hash`
- ��Ӧ��
  - `results[]`
  - `search_meta`
    - `vector_backend_requested`
    - `vector_backend_used`
    - `note`�������� embedding ��δ����ʱ���� fallback ˵����

### 4.5 `GET /paper/{paper_id_or_doi}`
- <U+7528><U+9014><U+FF1A><U+8FD4><U+56DE><U+5355><U+7BC7><U+8BBA><U+6587><U+8BE6><U+60C5><U+3002>
- <U+5339><U+914D><U+987A><U+5E8F><U+FF1A><U+5148><U+6309> `paper_map` key<U+FF0C><U+5931><U+8D25><U+540E><U+518D><U+904D><U+5386> `paper_id` / `doi`<U+3002>
- <U+54CD><U+5E94><U+4E3B><U+8981><U+5B57><U+6BB5><U+FF1A>
  - <U+5143><U+6570><U+636E><U+FF1A>`paper_id`<U+3001>`doi`<U+3001>`publication_date`<U+3001>`online_date`<U+3001>`publication_year`<U+3001>`paper_citation_count`
  - <U+6587><U+4EF6><U+8DEF><U+5F84><U+FF1A>`source_pdf_path`<U+3001>`source_md_path`<U+3001>`offline_html_path`<U+3001>`article_url`
  - <U+63D0><U+53D6><U+4FE1><U+606F><U+FF1A>`extractability_status`<U+3001>`paper_type`<U+3001>`extractability_reason`<U+3001>`extractability_evidence_section`
  - <U+7ED3><U+6784><U+5316><U+6570><U+636E><U+FF1A>`paper_domains[]`<U+3001>`context_variables[]`<U+3001>`operationalization{}`<U+3001>`variable_definitions[]`<U+3001>`main_effects[]`<U+3001>`moderations[]`<U+3001>`interactions[]`

### 4.6 `GET /paper/{paper_id_or_doi}/files`
- <U+7528><U+9014><U+FF1A><U+8FD4><U+56DE><U+8BBA><U+6587><U+5BF9><U+5E94><U+7684><U+53EF><U+8BFB><U+6587><U+4EF6><U+5217><U+8868><U+FF08>PDF / Markdown / HTML<U+FF09><U+3002>
- <U+53C2><U+6570><U+FF1A>`library_id`<U+FF08><U+53EF><U+9009><U+FF09>
- <U+54CD><U+5E94><U+793A><U+4F8B><U+FF1A>
  ```json
  {
    "paper_id": "doi_smith2023",
    "library_id": "supply_chain",
    "files": {
      "pdf": { "path": "D:\\data\\...\\source\\smith2023.pdf", "name": "smith2023.pdf", "size_bytes": 2345678 },
      "markdown": { "path": "D:\\data\\...\\mineru\\latest\\full.md", "name": "full.md", "size_bytes": 45678 }
    },
    "default_view": "pdf"
  }
  ```
- <U+53EF><U+7528><U+6587><U+4EF6><U+4F18><U+5148><U+7EA7><U+FF1A>PDF > Markdown > HTML<U+3002>`default_view` <U+4E3A> `"none"` <U+65F6><U+8868><U+793A><U+65E0><U+53EF><U+8BFB><U+6587><U+4EF6><U+3002>
- Markdown <U+68C0><U+6D4B><U+903B><U+8F91><U+FF1A><U+82E5> `source_md_path` <U+4E3A><U+6587><U+4EF6><U+5219><U+76F4><U+63A5><U+8FD4><U+56DE><U+FF1B><Ux82E5> <U+4E3A><U+76EE><U+5F55> <U+5219> <U+67E5><U+627E>`full.md`<U+3001>`merged.md`<U+3001>`output.md`<U+3002>
- 404 <U+54CD><U+5E94><U+FF1A>`{"error":"paper_not_found","paper_id":"..."}`

### 4.7 `GET /variable/{var_id}`
- ��;�����ر����ڵ����鼰���ľۺ���ͼ��
- ��Ӧ�����ֶΣ�
  - `node`
  - `paper_count_total`
  - `paper_count_edge`
  - `paper_count_moderation`
  - `paper_count_interaction`
  - `papers[]`�����ݽṹ���� `mentions`��
  - `paper_groups[]`��ǰ�����ýṹ��
    - `paper_id`��`doi`��`publication_year`
    - `open_local_html`��`open_online_url`
    - `concepts[]`������ `variable_definitions`��
    - `measurement_methods[]`������ `operationalization`��
    - `relations[]`��`direct_effect` / `moderation` / `interaction` ժҪ��

### 4.8 `POST /literature/import`
- ��;�����������嵥����ɱ�׼��/�з�/embedding/������
- �����壺
  - `manifest_path`��JSONL �嵥·�������
  - `library_id`�����׿��ʶ����ѡ�����鴫��Ҳ�ɷ��� `options.library_id`��
  - `options`��Ԥ����չ��������ѡ��
- ��Ӧ�����ֶΣ�
  - `library_id`
  - `imported_count`
  - `sentence_count`
  - `paragraph_count`
  - `document_count`

��С����ʾ������ƪ MD����
```json
{
  "manifest_path": "outputs/literature_base/manifest_one.jsonl"
}
```

`manifest_one.jsonl` ���������� JSON����
```json
{"paper_id":"0ecc6383-a6cb-407f-bc57-a9d0f99a19bc","doi":"md::0ecc6383-a6cb-407f-bc57-a9d0f99a19bc","title":"0ecc6383-a6cb-407f-bc57-a9d0f99a19bc","source_path":"outputs/mineru_recovery_full_from_outputs_20260419_120258/downloads/final_named/0ecc6383-a6cb-407f-bc57-a9d0f99a19bc.md"}
```

�ɹ���Ӧʾ����
```json
{
  "manifest_path": "outputs/literature_base/manifest_one.jsonl",
  "imported_count": 1,
  "sentence_count": 120,
  "paragraph_count": 18,
  "document_count": 1
}
```

������������������
- `WEAVIATE_URL`������ `http://127.0.0.1:8090`��
- `ZHIPU_API_KEY`
- ��ѡ��`LITERATURE_EMBEDDING_MODEL`��Ĭ�� `embedding-3`��

### 4.9 `GET /literature/search`
- ��;��˫·�ٻأ��ؼ��� BM25 + ���� RAG��������Ȩ RRF �ںϡ�
- ������
  - `query`�����
  - `library_id`����ѡ���������ڸÿ����ٻأ��������⣩
  - `top_k` Ĭ�� `20`
  - `levels`��`sentence|paragraph|document`���ɶ���ƴ�ӣ�Ĭ�� `sentence`
  - `keyword_weight` Ĭ�� `0.4`
  - `rag_weight` Ĭ�� `0.6`
  - `include_expanded_context` Ĭ�� `true`
- ��Ӧ�����ֶΣ�
  - `keyword_hits[]`
  - `rag_hits[]`
  - `merged_hits[]`
  - `search_meta`
    - `library_filter_applied`���Ƿ�ɹ�Ӧ�ÿ����
    - `library_filter_mode`��`weaviate_where`��ԭ�����ˣ��� `paper_id_registry`��Ӧ�ò���������ˣ�
    - `library_registry_paper_count`��Ӧ�ò�������е����������� fallback ģʽ�����壩

### 4.10 `POST /literature/answer`
- ��;�����ٻؽ�������ɻش�GLM chat����
- �����壺
  - `query`�����
  - `library_id`����ѡ���������ڸÿ����ٻأ�
  - `top_k` Ĭ�� `5`
  - `levels` Ĭ�� `["sentence"]`
  - `keyword_weight` Ĭ�� `0.4`
  - `rag_weight` Ĭ�� `0.6`
- ��Ӧ�����ֶΣ�
  - `answer`
  - `citations[]`
  - `retrieval`�������ٻ���ϸ��

## 5. ��̬��Դ�ӿ�
- `GET /`

## 6. ������������ӿ���Ϊ��أ�
- `GRAPH_EMBEDDING_MODEL`
  - ���������� embedding ������ͼ��
  - ��ǰʵ���Ի��˵���ϣ�������������������ⲿ embedding ����

## 7. Chat API��������

### 7.1 `POST /chat/sessions`
- ��;�������Ự��
- �����壺
  - `title`����ѡ��
  - `default_mode`��`fast|agent`����ѡ��Ĭ�� `fast`��
- ��Ӧ��`{session_id, title, default_mode, created_at, updated_at}`

### 7.2 `GET /chat/sessions`
- ��;����ȡ�Ự�б���������ʱ�䵹�򣩡�
- ��Ӧ��`{sessions:[...]}`

### 7.3 `GET /chat/sessions/{session_id}`
- ��;����ȡ�Ự��������ʷ��Ϣ��
- ��Ӧ��
  - `session`
  - `messages[]`���� `role`��`content`��`status`��`citations`��`retrieval`��`tool_trace`��

### 7.4 `POST /chat/sessions/{session_id}/messages`
- ��;���ύ��Ϣ�������ش�
- �����壺
  - `content`�����
  - `mode`: `fast|agent`
  - `provider`: `glm|zhipu|deepseek`
  - `model`����ѡ��
  - `stream`����ѡ��Ĭ�� `true`��
- ��Ӧ��`202`
  - `assistant_message_id`
  - `user_message_id`
  - `stream_url`

### 7.5 `GET /chat/sessions/{session_id}/stream?message_id=...`
- ��;��SSE �¼�����
- �¼����ͣ�
  - `started`
  - `delta`
  - `tool_call`
  - `citation`
  - `completed`
  - `failed`


