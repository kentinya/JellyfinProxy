# Task BUG-002 — 删除两个 danmu raw 入口的视频特殊处理

当前计划：[BUG-002 完整计划](Task/BUG-002-remove-danmu-video-handling.md)。

```text
Task ID: BUG-002
Work Type: BUGFIX
Parent Slice: N/A — standalone bug
Status: IN PROGRESS
Task Base: e4695d81596642363be8219441037da881f8a1ff
Contract Checkpoint: N/A — standalone bug
Plan Checkpoint: e10e1b66f2bb04bb62dff7df40ff93faea27570b
Implementation Head: NOT SET
Difficulty: Medium
Test Level: T4
Planner / Reviewer: B
```

按用户明确要求规划：删除 `/api/danmu/{id}/raw` 和 `/emby/api/danmu/{id}/raw` 的
视频特殊分流及路径 ID 提取，让其走现有普通代理。保留其他视频入口、映射与回退。

这是主动调整已有兼容行为，不认定历史规则错误或本次 403 根因。用户已明确要求
激活，现进入实施阶段；本次只完成实施准入核对和状态登记，产品实现尚未开始。
按[开发流程](docs/development-workflow.md)走独立 Task 路径；全部范围、AC-1～7、
T4 测试与独立审查要求见完整计划，当前审查 PENDING。激活不包含生产环境操作。

已完成记录见[历史索引](Task/archive/README.md)，Slice 状态见 [SLICE](SLICE.md)。

```text
Next Action: Developer 按 BUG-002 合同实施并完成 T4 隔离验证，再移交独立 B 审查
```
