# Task S1.2 — 缓存撤除与保留能力回归

当前 B 计划见 [S1.2 完整计划](Task/S1.2-remove-playback-info-cache.md)，
Parent Slice 为已激活的 [S1 合同 v4](Task/S1-remove-playback-info-json-cache.md)。

```text
Task ID: S1.2
Work Type: SLICE TASK
Parent Slice: S1
Status: PLANNED
Task Base: 7a436110eb8456bacb350b015835246b6802ffa2
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: NOT SET
Implementation Head: NOT SET
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: PENDING — implementation not started
```

S1.2 撤除完整 PlaybackInfo JSON 缓存及四项专属配置、缓存绕过与诊断，保留逐请求转发、
修改绕过原文、直链填充、Video 302 和流式回退；范围、AC-1～8 与四部分测试计划已明确。
旧字段默认规则暂保留至 S1.3，最终真实候选对照在 S1.4；不将中间检查点称为 Slice 完成。
Developer 开工时解析本计划的真实提交作为 Plan Checkpoint。

前序 [S1.1](Task/S1.1-real-jellyfin-12.3-baseline.md) 已获独立 B **PASS**，审查完整
`9397dd4864d85ec2ba759ad4b8fa8812cb8b5b31..56d76339f2c3fae7cd2ef550cddedc0d9fb73aa5`。
RR-1 / RR-2 经原始证据核对与真实官方 12.3.0 独立重放通过；18/18 补证、182 项回归通过。
本轮证据：`artifacts/validation-evidence/S1/s1-1-b-final-review-20261025-01/`。
专属资源已停止，产品与 0.9.3 未改；原证据及未跟踪 artifacts/ 保留且不纳入 Git。

全部 RO 仍未完成，候选 C / F-01～08、真实客户端实机与打包 NOT RUN；
Slice ACTIVE，A Final Review PENDING。历史
[BUG-001](Task/BUG-001-media-source-cache-invalidation.md) 独立 B PASS 记录保留。

```text
Next Action: Developer implements planned S1.2
```
