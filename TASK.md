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
Implementation Head: cfc790e22dc56c2016e09fd49b8e4189ce00a027
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: FIX REQUIRED — functional evidence gaps V1–V4
```

Developer 已交付工具、夹具、文档与三组真实基线；工具自报 82/82 不替代独立核对。
按用户要求已撤销工具建设 / 修复、锁重建和机器报告作为必需门槛，可人工或用短小客户端验证。
当前 **FIX REQUIRED** 仅因第二已种入 ID 保留、提前取消 / 上游释放、绕过 / ID / raw 边界、
产品直连不可达 / 恢复仍缺证据，不表示已证实产品缺陷。V1～V4、当前 AC / RO 重评与历史
审查纠正见完整 Task 的“当前 B 重规划与审查纠正”。已有有效证据继续复用。

B 全回归：174 passed；`doctor` PASS；文档 `prepare --server-lock` 退出 2，后续独立真实矩阵
当时 BLOCKED，专属资源已清理；当前不要求先修该入口。
证据：`artifacts/validation-evidence/S1/s1-1-b-review-20261025-01/`。
S1 保持 ACTIVE，产品未变；C 对照、RO-1～9 最终验收与 A 最终审查未完成，不启动 S1.2。

历史 [BUG-001 — MediaSourceCache 失效映射清理](Task/BUG-001-media-source-cache-invalidation.md)
已获独立 B PASS，记录继续保留；其历史回归与证据不构成本次 S1 验证结果。
既有未跟踪 `artifacts/` 保持原样，不纳入本次实现提交。

```text
Next Action: Developer supplements S1.1 V1–V4 functional evidence; B re-review required
```
