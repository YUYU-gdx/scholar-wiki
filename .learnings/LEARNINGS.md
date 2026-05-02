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
