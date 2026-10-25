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
Implementation Head: NOT SET — 本轮补证提交尚未创建
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: PENDING — V1–V4 evidence supplied, re-review required
```

Developer 本轮只补 V1～V4 功能缺口，未改产品、未改版本、未修观测器、未重跑已成立基线。
新增 `scripts/validation/supplement.py`：产品直连真实 Jellyfin（不经观测器），只用既有
PlaybackInfo / Video / raw 入口，媒体仅做有界读取，提前取消与上游释放由受控源 socket 账本判定。

真实补证结果 18/18 PASS（`artifacts/validation-evidence/S1/s1-1-supplement-20261025-01/`）：
V1 第二映射全程保持 302；V2 真实重叠 / 全局绕过、query 覆盖 path、两种 UUID、raw 未种入
透传与种入后 302；V3 传输中 16384 字节即断开，源账本 `aborted_by_client=true`、
`bytes_sent=32768 < 85112`，后续 Range 仍得真实 206；V4 产品直连不可达时自身报错，
重启后三组恢复 200，B-on 的 `HIT` 行按改前缓存遮挡单列。

测试：`tests/test_real_jellyfin_validation.py` 45 passed；全回归 179 passed；
`git diff --check` PASS；凭据自查 162 文件 0 泄漏；已停止本 run 专属容器。

既有有效证据（12.3.0、三组真实事务、字段差异、本地 Range、同 ID 302→200→302、
B 全回归 174 passed、`doctor` PASS）继续复用，不整套重跑。真实客户端实机、打包构建、
候选 C 对照仍 NOT RUN。S1 保持 ACTIVE，A 最终审查未开始，不启动 S1.2。

历史 [BUG-001 — MediaSourceCache 失效映射清理](Task/BUG-001-media-source-cache-invalidation.md)
已获独立 B PASS，记录继续保留。既有未跟踪 `artifacts/` 保持原样，不纳入实现提交。

```text
Next Action: B independent re-review of S1.1 V1–V4 evidence
```
