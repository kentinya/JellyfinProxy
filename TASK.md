# Task BUG-001 — MediaSourceCache 失效映射清理

```text
Task ID: BUG-001
Work Type: BUGFIX
Parent Slice: N/A — standalone bug
Status: READY FOR B REVIEW
Task Base: c96b06e5246ce5edcd48153d4e18212a3193dc18
Contract Checkpoint: N/A — standalone bug
Plan Checkpoint: 1f2015c8a12171cd77719e8fe1d44979f91a9398
Difficulty: Low
Test Level: T4
Planner / Reviewer: B
Implementation Head: 0228dfdb43d4ab464839f38d63a59696d0d7d8ef
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

- Developer 已完成实现：`services/media_source_cache.py` 的 `remember()` 现在会在同一
  MediaSourceId 收到不可用 Path 时只删除该 ID 的旧映射；Video 未命中沿既有入口回退
  普通代理，后续有效 URL 可恢复 302。完整报告见
  [Task/BUG-001-media-source-cache-invalidation.md](Task/BUG-001-media-source-cache-invalidation.md)。
- 候选已提交：`Implementation Head` = `0228dfdb43d4ab464839f38d63a59696d0d7d8ef`（父提交
  `c9164177…`）。本轮测试日志仍作为未跟踪本地证据保存在
  `artifacts/validation-evidence/BUG-001/`。
- T4 本地门槛：`.venv/bin/python -m pytest` → 134 passed；`git diff --check` → exit 0；
  修复前首次失败记录在同一证据目录的 `-run1-red`。真实 Jellyfin、客户端兼容与打包 NOT RUN。
- 当前状态为 `READY FOR B REVIEW`；独立 B 审查仍为 PENDING，Developer 自检不构成 PASS。

```text
Next Action: B — INDEPENDENT REVIEW OF BUG-001 (PENDING)
```
