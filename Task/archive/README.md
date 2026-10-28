# 历史任务与合同

[返回首页](../../README.md) · [当前 Task](../../TASK.md) · [当前 Slice](../../SLICE.md)

本目录保存已完成交付的计划、合同、完成报告及独立审查。下表只索引已有决定；归档本身
不签发新的 PASS。各记录中的“当前”“下一步”和中间状态属于当时阶段，不是新的实施指令。
当前产品行为以[配置与播放行为](../../docs/configuration.md)为准，版本变更见
[CHANGELOG](../../CHANGELOG.md)。

## 已完成交付

| 记录 | 范围 | 已有最终决定 |
| --- | --- | --- |
| [BUG-002](BUG-002-remove-danmu-video-handling.md#b-review-result) | 删除两个 danmu raw 视频特殊入口，普通 HTTP 透传及真正视频回归 | 独立 B PASS，2026-10-28 |
| [BUG-001](BUG-001-media-source-cache-invalidation.md) | 同一媒体源无效 Path 清理旧直链及回退 / 恢复 | 独立 B PASS，2026-10-24 |
| [Slice S1](S1-remove-playback-info-json-cache.md#a-final-review) | 删除完整 JSON 缓存、按配置覆盖字段、真实服务验证 | 独立 A PASS / CLOSED，2026-10-25 |
| [S1.1](S1.1-real-jellyfin-12.3-baseline.md) | 改前真实 Jellyfin 12.3 基线及补证 | 独立 B PASS，2026-10-25 |
| [S1.2](S1.2-remove-playback-info-cache.md) | 缓存撤除与保留能力回归 | 独立 B PASS，2026-10-25 |
| [S1.3](S1.3-playback-info-field-configuration.md) | 字段配置、默认不改及直链一致性 | 独立 B PASS，2026-10-25 |
| [S1.4](S1.4-candidate-real-validation-and-handoff.md#b-final-review-result2026-10-25当前有效) | 候选真实验证、RR-1 / RR-2 补证与交接 | 独立 B PASS，2026-10-25 |
| [S1 字段合同补充](S1-playback-info-field-overrides.md) | 两个字段表、执行顺序与 F-01～F-08 | S1 规范性组成部分，随合同保留 |

S1 审查固定范围为 `6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5..a0cc7cddff32da585923c5ff11d3977ea910d87a`，
原审查时版本为 0.9.3 / Unreleased；后续 1.0.0 版本整理不改变该范围。审查的真实服务结论
限于 HTTP 层，实机客户端与 arm64 / 第二架构验证为 **NOT RUN**，详见原记录。

原始证据位于工作区 `artifacts/validation-evidence/`，未纳入 Git；当前工作区可访问，
仅克隆仓库不会取得这些证据。历史链接保留其本地访问用途，不表示证据已在远端发布。
归档记录中的命令、文件清单、旧版本行为和历次失败保留原貌；其中的代码路径对应当时提交，
不能据此认为当前版本仍有已删除模块或配置。

## 已移除的过时草案

2026-10-25 文档治理移除了两份已被正式记录取代的草案：

| 原路径 | 替代记录 |
| --- | --- |
| `Task/drafts/media-source-cache-invalidation.md` | [BUG-001 完整计划与审查](BUG-001-media-source-cache-invalidation.md) |
| `Task/drafts/remove-playback-info-json-cache.md` | [S1 最终合同](S1-remove-playback-info-json-cache.md)；原 v1 的单 Task、固定字段改写和验证范围建议已被替代 |

需要复查原文时，可从清理前的真实提交读取：

```bash
git show 737fc0e42056136ec0a84963611272a7f3c8ef42:Task/drafts/media-source-cache-invalidation.md
git show 737fc0e42056136ec0a84963611272a7f3c8ef42:Task/drafts/remove-playback-info-json-cache.md
```

原 `Task/drafts/playback-info-field-overrides.md` 已纳入 S1 合同，移为本目录的
[字段合同补充](S1-playback-info-field-overrides.md)，保留全部规范和验收。
