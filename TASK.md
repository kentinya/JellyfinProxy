# Task S1.1 — 真实 Jellyfin 12.3 验证基线

当前 B 计划见 [S1.1 完整计划](Task/S1.1-real-jellyfin-12.3-baseline.md)，
Parent Slice 为已激活的 [S1 合同 v3](Task/S1-remove-playback-info-json-cache.md)。
本 Task 先准备隔离真实 12.3、可播放素材和验证工具，取得 J / B-on / B-off 改前基线；
缓存撤除、字段配置和候选最终验证由后续 Task 交付。未配置 / 空表默认不改字段的合同不变。

```text
Task ID: S1.1
Work Type: SLICE TASK
Parent Slice: S1
Status: PLANNED
Task Base: 9397dd4864d85ec2ba759ad4b8fa8812cb8b5b31
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: NOT SET — Developer 开工时从 Git 解析
Implementation Head: NOT SET
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: PENDING
```

AC-1～11、范围、四部分测试计划与精确工具接口均以完整计划为准。
当前仅完成 B 规划；工具、产品实施与真实服务验证均未开始，pytest / 真实基线为 NOT RUN。
规划期间只读确认 Docker 可用及 8096 已被其他服务监听；实施必须使用专属环境，不接管该服务。
S1.1 的基线通过也不代表 Slice 或“其他功能完好保留”已经通过。

历史 [BUG-001 — MediaSourceCache 失效映射清理](Task/BUG-001-media-source-cache-invalidation.md)
已获独立 B PASS，记录继续保留；其历史回归与证据不构成本次 S1 验证结果。
既有未跟踪 `artifacts/` 保持原样，不纳入计划提交。

```text
Next Action: NONE — AUTHORIZED TASK PLANNING COMPLETE
```
