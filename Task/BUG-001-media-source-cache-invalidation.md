# Task BUG-001 — MediaSourceCache 失效映射清理

遵循 [开发流程](../docs/development-workflow.md) 和 [B 角色指南](../docs/agent-experience/task-planner-reviewer.md)。
用户本次明确要求将 [原草案](drafts/media-source-cache-invalidation.md) 登记为正式 Task，
替代先前仅规划、不纳入治理的限制。当前实施入口为 [根 TASK.md](../TASK.md)。

```text
Task ID: BUG-001
Work Type: BUGFIX
Parent Slice: N/A — standalone bug
Status: PLANNED
Task Base: c96b06e5246ce5edcd48153d4e18212a3193dc18
Contract Checkpoint: N/A — standalone bug
Plan Checkpoint: 1f2015c8a12171cd77719e8fe1d44979f91a9398
Difficulty: Low
Test Level: T4
Planner / Reviewer: B
Implementation Head: NOT SET
```

本任务不依赖 Slice 或 A。Task Base 固定为现有 `v0.9.2` 发布提交，不随规划文档提交
前移。Plan Checkpoint 指向已提交的正式计划；当前纯文档后继补记真实 SHA，避免自引用。

## Goal / 目标与结果映射

一个完整修复闭环：有效媒体源 URL 建立映射 → 同一有效 ID 收到无效 Path 时清理
旧映射 → Video 缓存未命中沿既有入口回退普通代理 → 再次收到有效 URL 时恢复 302。
本任务全部结果由下方 AC-1～10 定义，不使用 Slice RO。

“本次 Path”指实际处理到的 PlaybackInfo 内容，也可能来自 JSON 缓存，不保证每次
从 Jellyfin 获取最新信息。完整 PlaybackInfo JSON 缓存的 TTL 和刷新规则保持现状。

## 实际缺口与范围

需求来源为用户放在仓库根目录的 `JellyfinProxy 优化方案：MediaSourceCache 失效映射清理.md`。
原件保持工作区原状；本正式计划自包含，不把本地原件或历史 intake 报告作为实施前置。

已核对的真实实现：

- [MediaSourceCache](../services/media_source_cache.py)：`remember()` 遇到非字符串或
  非 HTTP(S) Path 直接返回，旧 URL 仍可被 `get()` 命中；畸形 IPv6 URL 可导致解析异常。
- [PlaybackService](../services/playback_service.py)：`modify()` 记录策略处理后的 Path；
  `remember_media_sources()` 在绕过修改时记录原始 Path，两者最终调用同一缓存方法。
- [PlaybackHandler](../handlers/playback_handler.py)：HIT / MISS / 禁用 JSON 缓存均有
  记录媒体源的既有路径；绕过修改时响应正文保持原始字节。
- [VideoHandler](../handlers/video_handler.py)：缓存命中返回 302，未命中直接调用现有代理。
- [核心测试](../tests/test_core.py)：已有本地路径不入缓存、UUID 归一化、302、绕过建映射
  等用例，缺少“先建有效映射，再写入无效 Path”的缺陷回归。

触发步骤：先对 `abc123` 记入 `https://media.example/old.mkv`，再对该 ID 处理本地路径、
`None`、空字符串、FTP 或缺少 host 的 URL。当前仍读到旧地址，预期只删除该 ID；
`http://[invalid` 当前在缓存方法中抛出 `ValueError`，预期同样清理旧映射。
这些现状调查只证明缺陷存在，不是修复结果。

现有 README、治理文档、用户原方案、历史 intake 与证据属于已有工作区内容。
登记时确认产品代码和测试与固定 Base 一致；Developer 开工时再次核对并保留其他改动，
不可把无关文件或历史证据一并暂存。当前仓库身份沿用已验证 GitHub 账户的既有提交署名。

### 允许修改的范围与实施顺序

1. 在 `tests/test_core.py` 补充缺陷复现及行为回归，每个删除场景先建立有效旧映射。
2. 产品代码仅修改 `services/media_source_cache.py` 的 `MediaSourceCache.remember()`。
   非字符串或空 ID 仍直接忽略；有效 ID 先调用原有标准化逻辑取得 cache key。
3. Path 非字符串、可解析但不满足原有 HTTP(S) + 非空 netloc 条件，或 `urlparse()`
   抛出 `ValueError` 时，使用幂等删除清理该 key。正常地址接受条件不扩大或收紧。
4. 有效 URL 保持新增 / 覆盖、LRU 更新及现有容量淘汰行为。
5. 沿现有 PlaybackInfo 与 Video 入口验证删除、回退和恢复，再执行最终候选门槛。

允许按实际行为同步 README 和 CHANGELOG 的未发布说明，以及本计划 / 根 TASK 的进度、
报告与审查记录；本 Task 不自动升级产品版本或发布。Handler、PlaybackService、
MediaResolver、路由、策略、JSON 缓存和配置实现均不在产品代码修改范围。

## 验收条件

| 编号 | 场景 | 预期结果 |
|---|---|---|
| AC-1 | 有效 HTTP / HTTPS 首次写入、同 ID 新 URL 覆盖 | 命中本次 URL；正常 302 保留 |
| AC-2 | 已有映射后收到本地路径、空字符串、`None`、非字符串、非 HTTP(S)、无 host 的地址 | 只删除该 ID；`get()` 返回 `None` |
| AC-3 | `remember()` 收到会使 `urlparse()` 抛出 `ValueError` 的地址 | 本方法不抛该异常；只删除该 ID 的旧映射 |
| AC-4 | 对不存在的 key 重复写入无效 Path；或传入无效 ID | 幂等、不报错，不删除其他 ID |
| AC-5 | 同一 UUID 的带连字符 / 紧凑格式、十六进制大小写变体用于写入和删除 | 原有归一化有效，旧 key 确实被删除；非 UUID ID 的大小写规则不变 |
| AC-6 | 删除 A 后读取 B；或 A 再次收到有效地址 | B 不受影响；A 可重新命中并恢复 302 |
| AC-7 | PlaybackInfo 的 HIT / MISS / 禁用缓存与修改 / 绕过修改组合处理无效 Path | 两条记录路径均删除旧映射；绕过修改的响应正文保持原样 |
| AC-8 | 映射删除后通过已有 Video 入口播放 | 实际进入普通代理并保留其响应，不使用旧 Location 返回 302 |
| AC-9 | PlaybackInfo 请求失败、JSON 无法解析、MediaSources 为空 / 缺失，或响应未包含某 ID | 不因此清理其他映射；未出现的 ID 保持原状 |
| AC-10 | 正常读写与容量溢出 | 默认 4096、已有自定义容量和 LRU 行为不变；删除不额外淘汰其他条目 |

AC-7 的端到端输入使用当前处理链可解析的无效 Path，如本地路径、空值、FTP 或缺少
host 的 URL。AC-3 单独验证缓存方法，并可验证绕过修改的记录路径。
有效 ID 对应的媒体源缺少 Path 时按 `None` 处理；整个响应未出现该 ID 不构成删除依据。

## 必要测试

修改规模为 Low，但涉及缓存一致性与播放回退，按 T4 执行全部已有回归及适用本地
集成。真实服务、性能和打包不在本次修复验收要求内，也不从本地夹具结果推导其通过。

### 开发 / 修正反馈

参数化覆盖 AC-1～6、AC-10。每个删除测试先建有效旧映射，并通过公开方法断言删除和
其他 ID 不受影响；UUID 用不同表示建立、删除同一 key。小容量测试验证 LRU，避免
仅断言内部字典实现。先保留首次失败，再验证修正结果。

```bash
.venv/bin/python -m pytest tests/test_core.py -k media_source_cache
```

播放链集成复用现有 Request 和假上游，覆盖 AC-7～9：

- 组合 `cache_mode=miss / hit / disabled` 和 `modify=True / False`。HIT 预填含无效
  Path 的 JSON 缓存，另行预置旧 URL，确认本次清理且不访问上游；绕过修改时正文原样。
- 处理后调用真实 VideoHandler，用记录调用的假代理验证实际回退及其响应。覆盖
  `MediaSourceId` / `mediaSourceId`、无查询参数的 Videos ID 和既有 danmu raw 入口。
- 验证上游失败、不可解析 JSON、空 / 缺失列表、只含其他媒体源均不清库；包含有效
  ID 但缺少 Path 的媒体源应只清理自身。
- 保留策略改写后的最终 Path、`Protocol = File`、禁转码、客户端绕过和流式代理回归。

```bash
.venv/bin/python -m pytest tests/test_core.py
```

### 最终检查点门槛

```bash
.venv/bin/python -m pytest
git diff --check
```

全部现有测试和新增 AC 对应测试须通过；使用本地假上游，不访问生产服务。
完整套件覆盖同一聚焦输入时可说明复用，不机械重复；最终候选的可执行输入变化后
按影响重跑，T4 的全部回归要求保留。

### B 独立验证

由未承担该修复实施的 B 审查完整 `Task Base..Implementation Head`，核对全部 AC、
真实输入身份和原始证据，并独立复现 AC-2、AC-5、AC-7～9 的关键行为：精确删除、
等价 UUID key、HIT / 绕过记录、Video 实际代理回退及不清库场景。
相同候选与输入的其他证据可明确复用，不能只凭 Developer 的全绿摘要签发 PASS。
缺少独立审查时保持 PENDING，存在阻塞则 FIX REQUIRED 并在原 Task 内追加修正。

### 证据与重跑

记录完整候选 SHA、未提交输入摘要、命令与 cwd、Python / 依赖版本、配置和夹具身份、
退出码、数量 / 耗时、首次失败与重跑、AC 映射、复用及 NOT RUN 项。
证据放 `artifacts/validation-evidence/BUG-001/<run-id>/` 或 CI artifact，保留至 B 最终
决定，交接时说明可访问方式。只用本地证据时明确其读取范围，不称远端可复核。

历史发布 / intake 的 38 项既有回归仅为修复前基线，不能抵扣本次新增 AC 或最终候选
T4 验证。只改文档且可执行输入相同时可复用运行证据，但重查任务身份、链接和状态。

## 非目标与已知边界

- 不按整个 MediaSources 列表推断完整媒体源集合，不因响应失败、列表为空或缺少某 ID
  清除该 ID，更不清空缓存。
- 不改变 UUID 或普通 ID 归一化、JSON 缓存共享 key / TTL / 绕过规则、正常 302 和流式
  回退行为；不新增 TTL、持久化、配置、依赖或远程 URL 可达性 / 签名有效性检测。
- `modify=True` 会先经过 MediaResolver，某些畸形 URL 可能在到达 `remember()` 前抛出
  异常；本任务只保证缓存方法的 AC-3，不宣称整条解析链异常处理已经修复。
- 不依赖 Jellyfin PR 的合并 / 发布状态，不据此关闭 JSON 缓存；不访问真实 Jellyfin、
  生产媒体库，不执行发布、部署或自动 push。

## Developer Completion Report

- Changed Files / Implemented：NOT SET
- Acceptance Mapping：PENDING
- Tests and Results / Evidence：NOT RUN — 尚未实施修复
- Decisions / Risks / Remaining Outcomes：AC-1～10 待本次候选验证；解析链边界见上文
- Plan Checkpoint：1f2015c8a12171cd77719e8fe1d44979f91a9398
- Implementation Head：NOT SET

## B Review Result

```text
Reviewed Range: NOT SET
Reviewer / Independence: NOT SET
Decision: PENDING
Acceptance / Required Outcomes all satisfied: PENDING
Slice Required Outcomes all satisfied: N/A — standalone bug
Evidence / Reuse / NOT RUN: NOT RUN — 尚无修复候选
Blockers / Remaining Risks: NOT SET
Next: DEVELOPER — IMPLEMENT BUG-001 AFTER PLAN CHECKPOINT VERIFICATION
```

B PASS 且全部 AC 满足后，由 B 保存完成报告与审查结果、同步适用文档并撤下根活动
Task；Task 本身保持 PASS，不使用 CLOSED，不生成 A 最终审查或 Slice PASS。
