## [LRN-20260502-001] best_practice

**Logged**: 2026-05-02T13:17:52Z
**Priority**: high
**Status**: pending
**Area**: frontend

### Summary
3D 图谱黑屏在“数据正常”时，优先检查 WebGL clearColor/alpha，而不是继续排查数据接口。

### Details
本次黑屏场景中调试面板显示 
odes:130、edges:115，说明图谱数据加载成功；但渲染器 clear:#000000，同时画布透明链路在部分环境下没有稳定透出浅色底层，导致视觉黑屏。

### Suggested Action
1. 在图谱诊断面板固定输出 clearColor/clearAlpha/ctxAlpha/nodes/edges。
2. 避免依赖透明清屏，图谱页显式设置浅色背景（scene/canvas/graph backgroundColor 同步）。
3. 黑屏排障先判定“渲染问题 vs 数据问题”，减少误改数据逻辑。

### Metadata
- Source: conversation
- Related Files: scholarai-workbench/public/frontend_legacy/graph_3d/index.html
- Tags: graph, threejs, webgl, debug, black-screen

---
## [LRN-20260502-002] best_practice

**Logged**: 2026-05-02T15:31:32Z
**Priority**: high
**Status**: pending
**Area**: frontend

### Summary
图谱渲染排障应先区分“数据有无”与“渲染链是否崩溃”，并用自动化脚本固定验收。

### Details
本次案例中 
odes/edges 正常、详情面板正常，但图谱空白。最终定位并非数据问题，而是渲染链 pageerror（tick 异常）。去掉高风险手动 force 调参后恢复显示。

### Suggested Action
1. 3D 图谱页默认采用“最小稳定初始化模板”。
2. 新增回归脚本：检查 pageerror、canvas/容器尺寸一致、截图非空白。
3. 只有在稳定基线上再逐步引入高级 force 调参，并逐项验收。

### Metadata
- Source: conversation
- Related Files: scholarai-workbench/public/frontend_legacy/graph_3d/index.html
- Tags: debugging-method, stability-first, playwright, graph-rendering

---
