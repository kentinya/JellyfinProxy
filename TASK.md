# Task S1.1 — 真实 Jellyfin 12.3 验证基线

当前 B 计划、实施与交接报告见 [S1.1 完整计划](Task/S1.1-real-jellyfin-12.3-baseline.md)，
Parent Slice 为已激活的 [S1 合同 v3](Task/S1-remove-playback-info-json-cache.md)。
本 Task 交付隔离真实 12.3、可播放素材与验证工具，并取得 J / B-on / B-off 改前基线；
缓存撤除、字段配置和候选最终验证仍由后续 Task 交付。

```text
Task ID: S1.1
Work Type: SLICE TASK
Parent Slice: S1
Status: FIX REQUIRED
Task Base: 9397dd4864d85ec2ba759ad4b8fa8812cb8b5b31
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: eac3245a1bd895d961f8cd522dec68de8935bbec
Implementation Head: cfc790e22dc56c2016e09fd49b8e4189ce00a027
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: FIX REQUIRED — B review 2026-10-25
```

Developer 已交付工具、夹具、文档与三组真实基线，工具输出 82/82 子项 PASS；独立 B 核对
完整 Base..Head、原始事务及现有 CLI 后决定 **FIX REQUIRED**。锁定构建的新目录重建失败，
第二 ID 保留、提前取消 / 上游释放、绕过 / ID / raw 矩阵和产品不可达验证存在必需缺口。
修正范围 R1～R5、逐项 AC 与 RO 重评见完整 Task 的 B Review Result。

B 全回归：174 passed；`doctor` PASS；文档 `prepare --server-lock` 退出 2，后续独立真实矩阵
BLOCKED，专属资源已清理。证据：`artifacts/validation-evidence/S1/s1-1-b-review-20261025-01/`。
S1 保持 ACTIVE，产品未变；C 对照、RO-1～9 最终验收与 A 最终审查未完成，不启动 S1.2。

历史 [BUG-001 — MediaSourceCache 失效映射清理](Task/BUG-001-media-source-cache-invalidation.md)
已获独立 B PASS，记录继续保留；其历史回归与证据不构成本次 S1 验证结果。
既有未跟踪 `artifacts/` 保持原样，不纳入本次实现提交。

```text
Next Action: Developer fixes S1.1 R1–R5; B re-review required
```
