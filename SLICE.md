# Slice S1 — 删除完整 JSON 缓存、按配置修改播放字段并验证既有能力

已按本轮用户明确要求激活
[S1 — 删除完整 JSON 缓存、按配置修改播放字段并验证既有能力](Task/S1-remove-playback-info-json-cache.md)，
状态为 **ACTIVE**，激活日期为 **2026-10-24**。真实 Jellyfin Server **12.3** 的功能保留验证
是必需验收；合同激活不代表已实施或验证通过。

合同 v4 保留按 TOML 字段配置修改能力，包含响应根字段 / 媒体源字段两个作用域；
按用户最新要求，未配置 / 空表均不改字段，取消旧两项自动修改，仅显式表列出的字段生效。
绕过优先、直链一致性及真实验证要求保留；对应 RO-9 和 F-01～08。
本次按用户直接要求将工具建设 / 修复、自动重建和机器校验改为可选手段，允许人工或短小
HTTP 客户端取证；先复用已有有效结果，仅补实际功能缺口，不据此签发功能 PASS。

- Slice Base：`6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5`。
- Contract Checkpoint：`eb2775e53f5c26f7c6dd46294e62249e7bb8aa63`。
- S1.1 Implementation Head：`9ebfac4ec5869470195376b757843fed1129c1cf`（本轮 V1～V4 补证，产品未变；此前工具 Head 为 `cfc790e22dc56c2016e09fd49b8e4189ce00a027`）；Slice 最终候选仍为 NOT SET。
- 真实 Jellyfin 验证：S1.1 工具输出 82/82 PASS（仅 J / B-on / B-off），独立 B 核对后为
  **FIX REQUIRED**。Developer 补证工具自报 18/18 PASS，独立 B 重审接受 V3 提前断流 / 释放
  和 V4 直连故障恢复；V1 每步重新种入第二映射，V2 尚缺全局 / 分支实际重叠及两个查询名
  的不同目标冲突，仅补这两项。原基线与其余有效补证保留，不要求修锁重建或观测器。
  补证与 B 重审证据分别为 `artifacts/validation-evidence/S1/s1-1-supplement-20261025-01/`、
  `artifacts/validation-evidence/S1/s1-1-b-rereview-20261025-01/`。
  候选 C 对照仍 NOT RUN；A 最终审查：PENDING。
- 首个 B Task [S1.1 — 真实 12.3 验证基线](Task/S1.1-real-jellyfin-12.3-baseline.md)
  当前为 **FIX REQUIRED**，完整 AC / RO 重评及最小返修见 Task 文末最新 B 重审，入口见根 [TASK](TASK.md)。
- S1.2～S1.4 仍为建议顺序，待 S1.1 获独立 B PASS 后由 B 逐步规划。

```text
Next Action: Developer supplements only remaining S1.1 V1/V2 evidence; B re-review
```
