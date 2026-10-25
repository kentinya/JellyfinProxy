# Task S1.1 — 真实 Jellyfin 12.3 验证基线

当前 B 计划、实施与交接报告见 [S1.1 完整计划](Task/S1.1-real-jellyfin-12.3-baseline.md)，
Parent Slice 为已激活的 [S1 合同 v4](Task/S1-remove-playback-info-json-cache.md)。
本 Task 取得隔离真实 12.3 下 J / B-on / B-off 的功能基线；验证工具为可选手段，
缓存撤除、字段配置和候选最终验证仍由后续 Task 交付。

```text
Task ID: S1.1
Work Type: SLICE TASK
Parent Slice: S1
Status: READY FOR B REVIEW
Task Base: 9397dd4864d85ec2ba759ad4b8fa8812cb8b5b31
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: eac3245a1bd895d961f8cd522dec68de8935bbec
Implementation Head: 56d76339f2c3fae7cd2ef550cddedc0d9fb73aa5（上一轮）
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: PENDING — RR-1/RR-2 supplemented by Developer, awaiting independent B re-review
```

Developer 已按第二轮 B 重审的最小清单补取 RR-1 / RR-2 证据（其余 V2 / V3 / V4 有效证据保留，
不重跑整套基线）。本轮只改可执行验证工具与文档，产品源码相对 Slice Base 未变。

- RR-1：第二 ID 先在目标循环前用真实 PlaybackInfo 种入并确认 302，循环内不再为其发
  PlaybackInfo（`second_playback_requests_during_cycle = 0`），只核对其 Video；
  三步均 302 到 remote-a，目标最终为 remote-b，两者不同。
- RR-2：真实 TOML 使 `OverlapClient` 同时列入全局表与两个分支表（判定读取运行时实际配置），
  同一 Video URL 内两种查询名指向两个不同已种入源并各交换一次，实测精确名
  `MediaSourceId` 优先（产品既有行为，未修改）。

补充证据：`artifacts/validation-evidence/S1/s1-1-supplement-20261025-02/`（18/18 PASS，
含两次工具期望值写错的首次失败记录与 `tool-source-identity.json` 精确摘要）。
全回归 **182 passed in 3.30s**；`git diff --check` PASS；专属容器与端口已安全停止。
以下均为 Developer 自检，不是独立 B 或 A 结论。

全部 RO 仍为 NOT RUN：候选 C / F-01～08、真实客户端实机与打包未运行；S1 保持 ACTIVE，
A Final Review PENDING，不启动 S1.2。原报告、有效证据及未跟踪 `artifacts/` 保留。

历史 [BUG-001 — MediaSourceCache 失效映射清理](Task/BUG-001-media-source-cache-invalidation.md)
已获独立 B PASS，记录继续保留。既有未跟踪 `artifacts/` 保持原样，不纳入实现提交。

```text
Next Action: B independent re-review of S1.1 RR-1 / RR-2 evidence
```
