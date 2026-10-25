# Slice S1 — 删除完整 JSON 缓存、按配置修改播放字段并验证既有能力

当前合同：[S1 合同 v4](Task/S1-remove-playback-info-json-cache.md)，状态 **ACTIVE**。
字段配置遵循[规范性补充](Task/drafts/playback-info-field-overrides.md)：两个作用域缺省 / 空表
均不改字段，只有显式表生效；绕过优先、直链一致性和真实 12.3 验证要求保留。
工具建设 / 修复与机器校验为可选手段，先复用有效功能证据，仅补实际缺口。

- Slice Base：`6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5`。
- Contract Checkpoint：`eb2775e53f5c26f7c6dd46294e62249e7bb8aa63`。
- [S1.1](Task/S1.1-real-jellyfin-12.3-baseline.md)：独立 B **PASS**，
  Implementation Head `56d76339f2c3fae7cd2ef550cddedc0d9fb73aa5`；产品未变。
  改前 J / B-on / B-off 基线及 RR-1 / RR-2 已接受；独立真实补证 18/18、回归 182 passed。
  最终审查证据：`artifacts/validation-evidence/S1/s1-1-b-final-review-20261025-01/`；
  原 05 基线、补证 01 / 02 与历轮 B 记录保留。
- [S1.2](Task/S1.2-remove-playback-info-cache.md)：**B PASS**，Implementation Head
  `74992bbd004a53c0522bb49e5c0229131b00ec88`；AC-1～8 本地范围通过。B 审查发现并修正
  README 将 `client_identified` 覆盖面写窄的纯文档问题；全套 pytest 167 passed。证据见
  `artifacts/validation-evidence/S1/s1-2-impl-20261025-01/`，本地假上游不代表真实 12.3。
- [S1.3](Task/S1.3-playback-info-field-configuration.md)：**READY FOR B REVIEW**，Task Base
  `62eb64c932fea1b0f02afd941c2108468df91d6d`；实现 Head `a0cc7cddff32da585923c5ff11d3977ea910d87a`
  （本地实现候选，非最终产品 Head）。已交付缺省 / 空表不改、显式字段表、严格启动校验与最终
  直链一致性；独立 B 审查尚 PENDING。证据见
  `artifacts/validation-evidence/S1/s1-3-impl-20261025-01/`（未跟踪），为假上游与单元结果。
  F-08 / 最终真实候选对照留给 S1.4。
- S1.4 最终真实对照待 S1.3 获得 B PASS 后逐步规划。
- RO-1～9 均未完成；候选 C / F-01～08 / C 的 RJ-01～12 为 NOT RUN，
  最终产品 Implementation Head 为 NOT SET，A Final Review **PENDING**。

```text
Next Action: B independently reviews S1.3 (Task Base 62eb64c..a0cc7cd)
```
