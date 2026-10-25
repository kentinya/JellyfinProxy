# Task S1.1 — 真实 Jellyfin 12.3 验证基线

当前 B 计划、实施与交接报告见 [S1.1 完整计划](Task/S1.1-real-jellyfin-12.3-baseline.md)，
Parent Slice 为已激活的 [S1 合同 v4](Task/S1-remove-playback-info-json-cache.md)。
本 Task 取得隔离真实 12.3 下 J / B-on / B-off 的功能基线；验证工具为可选手段，
缓存撤除、字段配置和候选最终验证仍由后续 Task 交付。

```text
Task ID: S1.1
Work Type: SLICE TASK
Parent Slice: S1
Status: FIX REQUIRED
Task Base: 9397dd4864d85ec2ba759ad4b8fa8812cb8b5b31
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: eac3245a1bd895d961f8cd522dec68de8935bbec
Implementation Head: 9ebfac4ec5869470195376b757843fed1129c1cf
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: FIX REQUIRED — V3/V4 evidence accepted; V1/V2 have remaining gaps
```

最新独立 B 重审覆盖完整 Base..Implementation Head 及 `1f1cc95` 文档后继，结论为
**FIX REQUIRED（功能证据不足，未认定产品缺陷）**。Developer 的 18/18 为工具自报。

- V1：每步检查第二 ID 前重新请求其 PlaybackInfo，会补回直链，不能证明旧映射未被误清。
  仅需预先种入并确认 302，之后目标转换期间不再请求第二 ID 的 PlaybackInfo，直接核对其 Video。
- V2：query 覆盖 path、两种 UUID、raw 未种入回退及分支重叠证据保留；仍须补两个查询名指向
  不同已种入源的冲突，以及同一身份实际同时列入全局 / 分支配置的输入。
- V3 / V4：接受真实提前断流与上游释放、后续 206、产品直连故障恢复及 B-on 热缓存遮挡证据。
  不重跑已成立基线，不要求修锁重建、观测器或扩建工具。

B 本轮全回归 **179 passed in 4.04s**（进程 4.792s），完整范围空白检查 PASS；测试时间小于
本轮用时 50%。原包产品源码与固定 Base 相符，补证工具 14 文件摘要与实现 Head 相符。
审查证据：`artifacts/validation-evidence/S1/s1-1-b-rereview-20261025-01/`。
本轮真实服务独立重放 NOT RUN：已有明确证据缺口，先退回最小补证，未新建 / 停启服务。
全部 RO 已重评，候选 C / F-01～08、真实客户端和打包仍 NOT RUN；S1 ACTIVE，A PENDING，
不启动 S1.2。原报告、有效证据及未跟踪 `artifacts/` 保留。

历史 [BUG-001 — MediaSourceCache 失效映射清理](Task/BUG-001-media-source-cache-invalidation.md)
已获独立 B PASS，记录继续保留。既有未跟踪 `artifacts/` 保持原样，不纳入实现提交。

```text
Next Action: Developer supplements only remaining S1.1 V1/V2 evidence; B re-review
```
