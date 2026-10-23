# Task [ID] — [一个完整修复或用户行为]

遵循[开发流程](../docs/development-workflow.md)。复制到根 TASK.md 时将链接改为相对根目录。
有 Slice 使用 `S<slice>.<task>`；独立 bug 可使用 `BUG-<序号>`。

```text
Task ID: [ID]
Work Type: SLICE TASK | BUGFIX
Parent Slice: [Slice ID 或 N/A — standalone bug]
Status: PLANNED
Task Base: [实施前真实完整 SHA]
Contract Checkpoint: [ACTIVE Slice 合同完整 SHA 或 N/A — standalone bug]
Plan Checkpoint: NOT SET
Difficulty: Low | Medium | High
Test Level: T0 | T1 | T2 | T3 | T4
Planner / Reviewer: B
```

Plan Checkpoint 由 Developer 在开工时记录实际 B 计划提交；不填写自引用 SHA。

## 目标与结果映射

[有 Slice：对应哪些 RO；独立 bug：完整修复目标与全部验收索引，不依赖 Slice。]

## 实际缺口与范围

- 用户需求 / 缺陷来源：
- 已阅读的代码、配置和测试：
- 已有工作区改动及处理边界：
- 触发 / 复现步骤、实际与预期行为（bug 必填）：
- 根因依据与允许修改的行为：
- 受影响入口、依赖和不变量：

## 验收条件

[AC-1..n：成功、失败、回退 / 恢复与受影响兼容行为，逐项可验证。]

## 必要测试

### 开发 / 修正反馈

[缺陷复现、新行为和直接影响测试，准确命令与风险。]

### 最终候选门槛

[按等级列回归、静态检查及适用集成 / 真实服务 / 构建要求。]

### B 独立验证

[需独立复现的关键行为、原始证据和允许复用的范围。]

### 证据与重跑

[源码 SHA / 工作区摘要、命令与 cwd、版本 / 配置 / 夹具、原始日志位置、退出码、
计数 / 耗时、首次失败、复用依据和变化后的重跑要求。]

## 非目标

[不属于当前授权的能力、发布或环境操作。]

## Developer Completion Report

- Changed Files / Implemented：
- Acceptance Mapping：
- Tests and Results / Evidence：
- Decisions / Risks / Remaining Outcomes：
- Plan Checkpoint：NOT SET
- Implementation Head：NOT SET

## B Review Result

```text
Reviewed Range: NOT SET
Reviewer / Independence: NOT SET
Decision: PENDING
Acceptance / Required Outcomes all satisfied: PENDING
Slice Required Outcomes all satisfied: [PENDING 或 N/A — standalone bug]
Evidence / Reuse / NOT RUN: NOT SET
Blockers / Remaining Risks: NOT SET
Next: PENDING
```

独立 bug 在 B PASS 且全部验收满足后由 B 收尾；有 Slice 则重评全部 RO，按结果继续
必要 Task 或移交 A。归档完整记录后再撤下根活动 TASK。
