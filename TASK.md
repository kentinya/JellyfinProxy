# ACTIVE IMPLEMENTATION TASK

[S1.4 最终候选真实验证与交接](Task/S1.4-candidate-real-validation-and-handoff.md)已按独立 B 审查
**FIX REQUIRED** 补证 RR-1 / RR-2，现为 **READY FOR B REVIEW**；Parent Slice 为已激活的
[S1 合同 v4](Task/S1-remove-playback-info-json-cache.md)。不新建工具建设任务。

```text
Task ID: S1.4
Work Type: SLICE TASK
Parent Slice: S1
Status: READY FOR B REVIEW
Task Base: a0cc7cddff32da585923c5ff11d3977ea910d87a
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: d47a91e8909594d144c79d4bbd69f5eb87634a43
Implementation Head: a0cc7cddff32da585923c5ff11d3977ea910d87a — no product change was required
Product Candidate to Validate: a0cc7cddff32da585923c5ff11d3977ea910d87a
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: AWAITING RE-REVIEW — B 已 FIX REQUIRED，Developer 已在原 Task 补证
```

本轮只补 B 指出的两个缺口，未改产品源码，未重跑整套基线 / 47 行矩阵。
RR-1：沿既有 `/Items/{id}/PlaybackInfo` 入口，先成功后无效认证、格式合法但确实不存在的
非零 Item GUID，`C-default` 与 `C-direct` 均得到 200 / 401 / 404 / 200，与真实 12.3 直连
参照一致，无旧 JSON 成功回放，未用全零 GUID 冒充未知 Item。
RR-2：产品直连真实 12.3，Video bypass 流式读取 16 384 B 后客户端停止，受控源在
32 768 / 85 112 处 `aborted_by_client` 释放，后续 Range 正常；J 与候选在同一媒文件上的
三个 Range 窗口状态 / Content-Range / 字节摘要相等（Content-Length 声明差异单独记录）；
默认 / 旧两项 / 单字段三套配置均真正跟随 302 读取媒体、停止、再请求成功。

补证目录 `artifacts/validation-evidence/S1/s1-4-supplement-20261025-01/`（新隔离实例
server id `15e16ebe…`，7/7 PASS）；三次丢弃的 attempt 与其原因一并保留（均为脚本 /
断言缺陷，非产品缺陷）。完整 pytest 213 passed、`git diff --check` clean 复用相同可执行
输入；am64 构建与 frozen smoke 未重跑，沿用既有证据。

未运行项如实保留：真实客户端（Infuse / Kodi / SenPlayer）**NOT RUN**，`arm64` 与第二架构
打包 **NOT RUN**，B 本轮真实独立重放 **NOT RUN**（待本轮复核）。补证目录的
`verify-evidence` 为 9 PASS / 1 FAIL（缺 `evidence/results.json`，因未重跑 baseline），
属范围说明而非产品结论；21/21 结果仍属 `s1-4-candidate-20261025-01/`。全部结论仍仅为
HTTP 层，不构成实机兼容或发布结论。

前序 [S1.1](Task/S1.1-real-jellyfin-12.3-baseline.md)、[S1.2](Task/S1.2-remove-playback-info-cache.md)、
[S1.3](Task/S1.3-playback-info-field-configuration.md) 的独立 B PASS 记录保留；初版 47/47、
“C 返回 401 / 404”与远程停止的失实表述已在原 Task 逐条更正，历史原文未删。历史
[BUG-001](Task/BUG-001-media-source-cache-invalidation.md) 不变。版本仍是未发布 0.9.3
检查点 / Unreleased，未指定后继发行号；未 push / 发布 / 部署。Slice 保持 ACTIVE，最终
产品 Head 为 NOT SET，A Final Review 仍为 PENDING；既有 README 一行及全部 artifacts 保留，
不纳入本轮文档检查点。

```text
Next Action: independent B re-review of S1.4 RR-1 / RR-2 supplemental evidence
```
