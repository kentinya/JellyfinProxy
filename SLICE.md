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
- [S1.3](Task/S1.3-playback-info-field-configuration.md)：独立 B **PASS**，完整审查
  `62eb64c932fea1b0f02afd941c2108468df91d6d..a0cc7cddff32da585923c5ff11d3977ea910d87a`
  及 e903fa9 文档后继。AC-1～9 本地成立；B 独立 41 项、五组 HTTP 假上游闭环通过，
  复用相同候选的 213 项全套。证据：`artifacts/validation-evidence/S1/s1-3-b-review-20261025-01/`。
  这不是真实 Jellyfin 或 Slice PASS。
- [S1.4](Task/S1.4-candidate-real-validation-and-handoff.md)：独立 B **FIX REQUIRED**，Task Base 与
  Implementation Head 均为 `a0cc7cddff32da585923c5ff11d3977ea910d87a`（产品无需变更，未为造提交
  修改产品），Plan Checkpoint `d47a91e`。候选 C 在新建隔离官方 12.3 实例上运行 8 套配置；
  Developer 自报 47 条 PASS，B 发现候选认证 / 未知 Item 未执行、取消路径仍经观测器、
  三套配置远程停止只有 302 / 0 字节；RR-1 / RR-2 在原 Task 补证。有效字段 / 绕过 / 302 /
  失效恢复结果保留，`amd64` 构建 / frozen smoke 与完整 213 passed 复用；B 独立 41 passed。
  原证据：`artifacts/validation-evidence/S1/s1-4-candidate-20261025-01/`；
  B 证据：`artifacts/validation-evidence/S1/s1-4-b-review-20261025-01/`。
- RO 全量重评见 S1.4 B 记录：RO-1～4 / 6 的已交付结果保留；RO-5 / 7 / 8 / 9 尚未完整满足。
  F-01～07 及 F-08 字段部分成立，真实完整播放闭环仍需补证。
  最终产品 Implementation Head 为 **NOT SET**，A Final Review **PENDING**，Slice 仍 ACTIVE。
  当前版本仍为未发布 0.9.3 检查点，变化记录在 Unreleased；不自动编号或发布。

```text
Next Action: Developer supplements S1.4 RR-1 / RR-2; independent B review must pass before A final review
```
