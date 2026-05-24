---
name: scrapling
description: 中文学术抓取与下载技能模板。用于检索与下载论文 PDF，统一目录与脚本规范，并结合本项目 MCP 能力完成导入准备。
---

# scrapling（中文模板）

本技能用于在当前 workspace 内进行学术文献检索、网页抓取与 PDF 下载，并按统一目录规范落盘。

## 1. 强制目录规范（必须遵守）

- 所有下载的论文 PDF：
  - 必须保存到 `workspace/downloads/`（可按主题建子目录）。
- 所有爬虫/下载脚本：
  - 必须保存到 `workspace/crawler_scripts/`。
- 产出清单：
  - 建议保存 `workspace/downloads/download_manifest.json`（含标题、来源、DOI、下载链接、本地路径、下载状态）。

推荐结构：

```text
workspace/
├─ downloads/
│  ├─ ai_washing/
│  ├─ green_washing/
│  ├─ digital_washing/
│  └─ download_manifest.json
└─ crawler_scripts/
   ├─ search_and_download.py
   └─ README.md
```

## 2. 安装与依赖

建议环境：Python 3.10+

```bash
# 二选一
uv tool install "scrapling[shell]"
# 或
pip install "scrapling[all]>=0.4.2"

# 安装浏览器与相关依赖（用于 fetch/stealthy-fetch）
scrapling install --force
```

常用命令：

```bash
scrapling extract get "https://example.com" output.md
scrapling extract fetch "https://example.com" output.md --network-idle
scrapling extract stealthy-fetch "https://example.com" output.md --solve-cloudflare
```

## 3. 学术搜索引擎（可优先使用）

- Google Scholar
- Semantic Scholar
- OpenAlex
- Crossref
- Lens.org
- BASE (Bielefeld Academic Search Engine)
- CORE
- arXiv
- SSRN
- RePEc

## 4. 学术数据库（视权限与可访问性使用）

- Web of Science
- Scopus
- JSTOR
- ScienceDirect (Elsevier)
- SpringerLink
- Wiley Online Library
- Taylor & Francis Online
- SAGE Journals
- Emerald Insight
- IEEE Xplore
- ACM Digital Library
- ProQuest
- EBSCOhost
- ABI/INFORM
- Business Source 系列数据库
- INFORMS PubsOnline

## 5. UTD24 期刊列表

1. Academy of Management Journal
2. Academy of Management Review
3. Accounting Review
4. Administrative Science Quarterly
5. Contemporary Accounting Research
6. Information Systems Research
7. Journal of Accounting and Economics
8. Journal of Accounting Research
9. Journal of Consumer Research
10. Journal of Finance
11. Journal of Financial Economics
12. Journal of International Business Studies
13. Journal of Marketing
14. Journal of Marketing Research
15. Journal of Operations Management
16. Management Science
17. Manufacturing & Service Operations Management
18. Marketing Science
19. MIS Quarterly
20. Operations Research
21. Organization Science
22. Production and Operations Management
23. Review of Financial Studies
24. Strategic Management Journal

## 6. FT50 期刊列表

1. Academy of Management Journal
2. Academy of Management Review
3. Accounting, Organizations and Society
4. Administrative Science Quarterly
5. American Economic Review
6. Contemporary Accounting Research
7. Econometrica
8. Entrepreneurship Theory and Practice
9. Harvard Business Review
10. Human Relations
11. Human Resource Management
12. Information Systems Research
13. Journal of Accounting and Economics
14. Journal of Accounting Research
15. Journal of Applied Psychology
16. Journal of Business Ethics
17. Journal of Business Venturing
18. Journal of Consumer Psychology
19. Journal of Consumer Research
20. Journal of Finance
21. Journal of Financial and Quantitative Analysis
22. Journal of Financial Economics
23. Journal of International Business Studies
24. Journal of Management
25. Journal of Management Information Systems
26. Journal of Management Studies
27. Journal of Marketing
28. Journal of Marketing Research
29. Journal of Operations Management
30. Journal of Political Economy
31. Journal of the Academy of Marketing Science
32. Management Science
33. Manufacturing and Service Operations Management
34. Marketing Science
35. MIS Quarterly
36. Operations Research
37. Organization Science
38. Organizational Behavior and Human Decision Processes
39. Production and Operations Management
40. Quarterly Journal of Economics
41. Research Policy
42. Review of Accounting Studies
43. Review of Economic Studies
44. Review of Finance
45. Sloan Management Review
46. Strategic Entrepreneurship Journal
47. Strategic Management Journal
48. The Accounting Review
49. The Journal of Finance
50. The Review of Financial Studies

## 7. 本项目可用 MCP（用于导入/问答前的证据检索与变量映射）

本项目 MCP 服务名：`kn_graph_tools`

可用工具：

1. `rag_search`
2. `graph_variable_neighbors`
3. `graph_variable_concept_search`

说明：

- `kn_graph_tools` 主要用于文献证据检索、变量概念映射、变量邻域关系查询。
- 抓取下载后，可先把 PDF 落到 `downloads/`，再按项目导入流程进入语料库。

## 8. 执行要求（默认）

- 优先下载可公开访问/开放获取的 PDF。
- 浏览器抓取默认要求优先使用本机浏览器（如 Chrome，启用 `--real-chrome`），以便复用用户机构网络与登录权限环境。
- 每次任务都输出 `download_manifest.json`。
- 对失败链接记录原因（403/404/timeout/非 PDF）。
- 不要把脚本散落在根目录；统一写入 `crawler_scripts/`。
- 如站点有 robots.txt、ToS 或反爬限制，需遵守相关要求。

## 9. 最小交付清单

- `downloads/` 下分类 PDF 文件。
- `downloads/download_manifest.json`。
- `crawler_scripts/` 下可复用脚本与简要说明。
