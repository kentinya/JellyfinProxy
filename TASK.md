# Task BUG-001 — MediaSourceCache 失效映射清理

```text
Task ID: BUG-001
Work Type: BUGFIX
Parent Slice: N/A — standalone bug
Status: PLANNED
Task Base: c96b06e5246ce5edcd48153d4e18212a3193dc18
Contract Checkpoint: N/A — standalone bug
Plan Checkpoint: NOT SET
Difficulty: Low
Test Level: T4
Planner / Reviewer: B
Implementation Head: NOT SET
```

完整计划与后续完成报告、独立审查记录统一维护在
[Task/BUG-001-media-source-cache-invalidation.md](Task/BUG-001-media-source-cache-invalidation.md)。
本文件作为当前任务入口；身份、Base、计划检查点和状态应与完整计划同步。

## 用户目标与授权

用户已要求将 [历史草案](Task/drafts/media-source-cache-invalidation.md) 登记为正式 Task。
本次指令替代先前“不纳入治理”的限制。该任务为独立小版本 bug，由 B 规划及审查，
Developer 按计划实施；无需 A 或 Slice。

修复同一 MediaSourceId 收到无效 Path 后旧 URL 残留的问题，删除后沿现有 Video 入口
回退普通代理；后续收到有效 URL 可重新建立映射。代码范围仅限
`services/media_source_cache.py` 的 `remember()` 及必要测试，详见完整计划 AC-1～10。

## 开工与交接

- 计划检查点形成后记录实际 SHA；Developer 开工前核对该提交、固定 Base 和已有改动。
- 开始实施时同步为 `IN PROGRESS`；按 T4 完成全部回归与计划指定的缓存 / 播放链验证。
- 完成后填写真实实现 Head 和证据，交为 `READY FOR B REVIEW`；独立 B 审查仍为 PENDING。
- 当前仅完成规划登记，尚无产品实现、修复验证或审查 PASS。

```text
Next Action: DEVELOPER — IMPLEMENT BUG-001 AFTER PLAN CHECKPOINT VERIFICATION
```
