# Task 草案 — MediaSourceCache 失效映射清理

**当前状态：已登记为正式 Task BUG-001。**

按用户最新指令，正式计划见 [BUG-001](../BUG-001-media-source-cache-invalidation.md)，
当前实施入口见 [根 TASK.md](../../TASK.md)。原“仅草案、不纳入治理”的限制已由本次
登记指令替代。以下保留登记前的草案内容作为历史，不作为当前实施准入或状态依据。

---

## 登记前草案（历史）

**当时状态：DRAFT，未登记治理、未激活、未实施。**

来源：[JellyfinProxy 优化方案：MediaSourceCache 失效映射清理](<../../JellyfinProxy 优化方案：MediaSourceCache 失效映射清理.md>)。
本文件仅将方案细化为一个可执行、可验收的独立 bug 修复 Task 草案。
按用户要求，不登记根 TASK.md、不创建 Slice、不生成正式治理任务编号或检查点。
本次授权止于规划；原方案和产品代码保持原状。

| 项目 | 内容 |
|---|---|
| 规划职责 | B |
| 后续实施职责 | Developer |
| 类型 / 难度 | 独立 bug 修复 / Low |
| 调研源码 HEAD | `a6d4b3df562c9e15b8f4453381b7d7c6181f90e3` |
| 正式 Task Base / Plan Checkpoint | 未建立；上述 HEAD 仅标识本次调研版本 |
| Implementation Head | NOT SET |
| 建议实施单元 | 一个 Task，包含修复、缓存与播放回退验证 |

## 目标

当处理到一个有效 MediaSourceId 的新 Path 时，让该 ID 的缓存反映本次处理结果：
有效 HTTP(S) 地址新增或覆盖映射；无效 Path 删除该 ID 的旧映射。删除后的视频请求
沿现有路径回退普通代理。后续再次处理到有效 URL 时可重新建立映射并恢复 302。

“本次处理结果”包括读取到的 PlaybackInfo 缓存内容，不保证每次都从 Jellyfin 取得
最新数据；完整 PlaybackInfo JSON 缓存的有效期和刷新行为保持现状。

## 已核对的实现与缺口

- [MediaSourceCache](../../services/media_source_cache.py)：`remember()` 对非字符串或
  非 HTTP(S) Path 直接返回，导致同 ID 旧地址残留；`get()` 仍可命中并刷新其 LRU 位置。
- [PlaybackService](../../services/playback_service.py)：`modify()` 在策略处理后记录
  最终 Path；`remember_media_sources()` 在绕过修改时逐项记录原始 Path。
- [PlaybackHandler](../../handlers/playback_handler.py)：缓存 HIT、MISS 以及禁用 / 绕过
  JSON 缓存路径均会进入上述记录方法；绕过修改时保持原始响应正文。
- [VideoHandler](../../handlers/video_handler.py)：映射命中则 302，未命中直接调用现有
  ProxyHandler。修复不需要增加新的回退分支。
- [已有核心测试](../../tests/test_core.py)：覆盖首次本地路径不入缓存、UUID 归一化、
  有效 URL 重定向、绕过修改时建映射；尚未覆盖“先有有效映射，再收到无效 Path”。

本次只读复现：先写入 `abc123 → https://media.example/old.mkv`，再分别写入本地路径、
`None`、空字符串和 FTP 地址，旧地址均残留；`http://[invalid` 还会导致 `ValueError`。
这是现状调查，不是修复后的测试通过记录。

## 实施范围与步骤

产品逻辑只修改 [services/media_source_cache.py](../../services/media_source_cache.py)
的 `MediaSourceCache.remember()`；回归测试补在 [tests/test_core.py](../../tests/test_core.py)。

1. 补充“有效 → 无效 → 未命中 → 再次有效”的缺陷复现和关键边界测试。
2. 保留 ID 校验：非字符串或空 ID 直接忽略，不影响任何已有映射。
3. 对有效 ID 先计算现有标准化 cache key，再处理 Path；非字符串 Path 删除该 key。
4. 沿用现有 URL 判定：`urlparse()` 可解析、scheme 为 HTTP / HTTPS、netloc 非空。
   判定不通过时使用幂等删除；解析器抛出 `ValueError` 时，同样删除该 key 并返回。
   不扩展为新 URL 验证系统，不改变既有正常 URL 的接受规则。
5. 有效 URL 继续新增 / 覆盖、移动至 LRU 尾部，并沿用原有容量淘汰逻辑。
6. 通过现有 PlaybackInfo 与 Video 入口补充集成验证，再运行全部已有回归。

原方案的建议代码没有捕获 `urlparse()` 的 `ValueError`；步骤 4 仅在同一方法内补齐
“不可解析 Path 也应移除旧映射”的边界，不增加其他模块的产品改动。

## 验收条件

| 编号 | 场景 | 预期结果 |
|---|---|---|
| AC-1 | 有效 HTTP / HTTPS 首次写入、同 ID 新 URL 覆盖 | 命中本次 URL；正常 302 保留 |
| AC-2 | 已有映射后收到本地路径、空字符串、`None`、非字符串、非 HTTP(S)、无 host 的地址 | 只删除该 ID；`get()` 返回 `None` |
| AC-3 | `remember()` 收到会使 `urlparse()` 抛出 `ValueError` 的地址 | 本方法不抛该异常；只删除该 ID 的旧映射 |
| AC-4 | 对不存在的 key 重复写入无效 Path；或传入无效 ID | 幂等、不报错，不删除其他 ID |
| AC-5 | 使用同一 UUID 的带连字符 / 紧凑格式、十六进制大小写变体进行写入和删除 | 沿用现有归一化，旧 key 确实被删除；普通非 UUID ID 的大小写规则不变 |
| AC-6 | 删除 A 后读取 B；或 A 再次收到有效地址 | B 不受影响；A 可重新命中并恢复 302 |
| AC-7 | PlaybackInfo 的 HIT / MISS / 禁用缓存与修改 / 绕过修改组合处理无效 Path | 两条记录路径均删除旧映射；绕过修改的响应正文保持原样 |
| AC-8 | 映射删除后通过已有 Video 入口播放 | 实际进入普通代理，保留其响应，不使用旧 Location 发生 302 |
| AC-9 | PlaybackInfo 请求失败、JSON 无法解析、MediaSources 为空 / 缺失，或响应未包含某 ID | 不因此清空其他映射；未出现的 ID 保持原状 |
| AC-10 | 正常读写与容量溢出 | 默认 4096、已有自定义容量和 LRU 行为不变；删除不额外淘汰其他条目 |

AC-7 的端到端输入使用当前正常处理链可解析的无效 Path，例如本地路径、空值、
FTP 或缺少 host 的 URL；AC-3 单独验证缓存方法，也可验证绕过修改的记录路径。

## 测试计划

### 开发反馈

使用参数化用例覆盖 AC-1～6、AC-10；每个删除场景必须先建立有效旧映射，避免仅测试
空缓存而漏掉本次缺陷。UUID 用例使用不同表示分别建立与删除同一映射。
容量测试使用小容量与公开 `remember()` / `get()` 行为确认淘汰顺序，无需填充 4096 条。

```bash
.venv/bin/python -m pytest tests/test_core.py -k media_source_cache
```

### 播放链集成

- 复用现有假上游与 Request 夹具，组合 `cache_mode=miss / hit / disabled` 和
  `modify=True / False`。HIT 场景预填含无效 Path 的 JSON 缓存，并另外预置旧 URL，
  证明本次 HIT 会清理旧映射且不访问上游；不要拿同一有效缓存体假装最新无效结果。
- 处理后调用真实 VideoHandler，使用记录调用的假代理确认确实回退；覆盖查询参数
  `MediaSourceId` / `mediaSourceId`、无查询参数的 Videos 路径及已有 danmu raw 入口。
  有效 URL 继续重定向的既有用例作为正向回归。
- 独立覆盖上游失败、不可解析 JSON、空 / 缺失列表、只返回其他媒体源等不清理场景，
  确认旧条目仍可读；Path 缺失但包含有效 Id 的媒体源则按 `None` 清理该 ID。
- 保留策略重写后的最终 Path、`Protocol = File`、禁转码、客户端绕过和流式代理回归。

```bash
.venv/bin/python -m pytest tests/test_core.py
```

### 最终候选与复核

```bash
.venv/bin/python -m pytest
git diff --check
```

完整套件已覆盖相同聚焦用例时不机械重复；源码或测试输入变化后重跑受影响项。
复核重点为 AC-2、AC-5、AC-7～9：删除的精确 ID、UUID 等价 key、缓存 HIT 与绕过
记录、真实回退调用、空列表不清库。验证采用本地夹具，不依赖生产 Jellyfin 或远程 URL。

### 证据与结果

后续实施时记录候选源码身份、实际命令、配置 / 夹具、退出码、用例数量、首次失败与
重跑，以及 AC 对照。单元 / 假上游结果只证明本地行为，不写成真实客户端兼容已通过。

当前：**仅完成代码调查和缺陷只读复现；未新增测试、未运行修复验证、未实施产品修改。**

## 保留的边界与非目标

- 仅处理本次实际出现、且具有有效 ID 的媒体源；不因列表为空、请求失败或未返回某 ID
  删除该 ID，更不按整份 PlaybackInfo 推断完整媒体源集合。
- 不调整 PlaybackInfo JSON 缓存的 TTL、启停、共享 key、刷新与绕过规则，不增加
  MediaSourceCache 的 TTL、持久化、配置项或新依赖。
- 不探测远程 URL 是否可达或签名是否过期；格式仍符合既有规则的地址继续按有效处理。
- 不修改 Handler、PlaybackService、MediaResolver、路由或策略实现，不改变正常 302、
  缓存未命中回退、媒体头及流式行为。
- `modify=True` 路径会先经过 MediaResolver，其对某些畸形 URL 也可能抛出异常，尚未
  到达 `remember()`；本草案不把缓存局部防护描述为整条解析链异常修复。若未来要求
  整条链对所有畸形 URL 均安全处理，应另行明确范围。
- 不依赖原方案提及的 Jellyfin PR 合并或发布状态，也不据此关闭现有 JSON 缓存。
- 本草案不安排版本升级、打包、部署、治理登记或正式审查状态流转；未来执行前重新
  核对源码和实际工作范围。本次没有正式完成报告或审查 PASS。
