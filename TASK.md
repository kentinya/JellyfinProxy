# ACTIVE IMPLEMENTATION TASK

[S1.4 最终候选真实验证与交接](Task/S1.4-candidate-real-validation-and-handoff.md)独立 B 审查为
**FIX REQUIRED**，Parent Slice 为已激活的 [S1 合同 v4](Task/S1-remove-playback-info-json-cache.md)。
在原 Task 补 RR-1 / RR-2 后重新交审，不新建工具建设任务。

```text
Task ID: S1.4
Work Type: SLICE TASK
Parent Slice: S1
Status: FIX REQUIRED
Task Base: a0cc7cddff32da585923c5ff11d3977ea910d87a
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Plan Checkpoint: d47a91e8909594d144c79d4bbd69f5eb87634a43
Implementation Head: a0cc7cddff32da585923c5ff11d3977ea910d87a — no product change was required
Product Candidate to Validate: a0cc7cddff32da585923c5ff11d3977ea910d87a
Difficulty: High
Test Level: T4
Planner / Reviewer: B
Independent Review: FIX REQUIRED
```

已核对候选归档 75/75 文件一致，缺省 / 空表与显式字段、绕过、302、同 ID 失效恢复等有效
结果保留；完整 pytest 213 passed、amd64 构建及冻结 smoke 复用。B 独立字段 / 配置测试
41 passed。Developer 的“47/47”标签不代表全部必需场景成立：候选认证 / 未知 Item 未执行；
取消验证仍经观测器；三套远程播放停止均只读到 302 / 0 字节。

RR-1：沿已有 PlaybackInfo 入口补真实候选认证 / 未知资源错误与无旧成功回放。
RR-2：产品直连真实 12.3 补媒体 Range / 提前断开释放，并在默认 / 旧两项 / 单字段配置下
跟随实际 302 读取媒体、停止、再次读取。只补缺口，复用有效证据，不强制新 CLI 或修观测器。
原证据：`artifacts/validation-evidence/S1/s1-4-candidate-20261025-01/`；
B 证据：`artifacts/validation-evidence/S1/s1-4-b-review-20261025-01/`。

未运行项如实保留：真实客户端（Infuse / Kodi / SenPlayer）**NOT RUN**，`arm64` 与第二架构
打包 **NOT RUN**；B 本轮真实独立重放 **NOT RUN**（明确缺口先退回）。已有取消 / 释放
仅为含观测器路径的局部证据。全部结论仅为 HTTP 层，不构成实机兼容或发布结论。

前序 [S1.1](Task/S1.1-real-jellyfin-12.3-baseline.md)、[S1.2](Task/S1.2-remove-playback-info-cache.md)、
[S1.3](Task/S1.3-playback-info-field-configuration.md) 的独立 B PASS 记录保留；本轮没有沿用旧
82 PASS 作为 C 结果，也没有把旧实例写成新实例。历史 [BUG-001](Task/BUG-001-media-source-cache-invalidation.md)
不变。版本仍是未发布 0.9.3 检查点 / Unreleased，未指定后继发行号；未 push / 发布 / 部署。
Slice 保持 ACTIVE，最终产品 Head 为 NOT SET，A Final Review 仍为 PENDING；既有 README 一行及全部
artifacts 保留，不纳入本次文档检查点。

```text
Next Action: Developer supplements S1.4 RR-1 / RR-2 and corrects evidence claims, then returns to independent B review
```
