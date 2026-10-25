# Slice S1 — 删除完整 JSON 缓存、按配置修改播放字段并验证既有能力

已按本轮用户明确要求激活
[S1 — 删除完整 JSON 缓存、按配置修改播放字段并验证既有能力](Task/S1-remove-playback-info-json-cache.md)，
状态为 **ACTIVE**，激活日期为 **2026-10-24**。真实 Jellyfin Server **12.3** 的功能保留验证
是必需验收；合同激活不代表已实施或验证通过。

合同 v3 已纳入按 TOML 字段配置修改能力，包含响应根字段 / 媒体源字段两个作用域；
按用户最新要求，未配置 / 空表均不改字段，取消旧两项自动修改，仅显式表列出的字段生效。
绕过优先、直链一致性及真实验证要求保留；对应 RO-9 和 F-01～08。

- Slice Base：`6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5`。
- Contract Checkpoint：`eb2775e53f5c26f7c6dd46294e62249e7bb8aa63`。
- Implementation Head：`f0944486f3e721a6ab10fe75751573f1ba09ae86`（S1.1 工具与证据，产品未变）。
- 真实 Jellyfin 验证：S1.1 基线与工具交付完成（82/82 子项 PASS，仅 J / B-on / B-off）；
  候选 C 对照仍 NOT RUN；独立 B / A 审查：PENDING。
- 首个 B Task [S1.1 — 真实 12.3 验证基线](Task/S1.1-real-jellyfin-12.3-baseline.md)
  已实施并交为 **READY FOR B REVIEW**，当前入口见根 [TASK](TASK.md)。
- S1.2～S1.4 仍为建议顺序，待 S1.1 获独立 B PASS 后由 B 逐步规划。

```text
Next Action: B independent review of S1.1 (Task Base..Implementation Head)
```
