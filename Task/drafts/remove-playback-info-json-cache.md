# 删除完整 PlaybackInfo JSON 缓存：设计方案 v1

日期：2026-10-24。依据用户要求：删除完整 PlaybackInfo JSON 缓存，其他功能保持不变，先提供设计。
设计依据为当前 [README](../../README.md)、[开发流程](../../docs/development-workflow.md)及实际代码。

后续用户已明确要求改为 Slice 并加入真实 Jellyfin 12.3 验证，现行合同见
[Slice S1](../S1-remove-playback-info-json-cache.md)。本文件保留为设计 v1 历史输入；
下文“不激活 Slice / 单 Task / 真实服务不作为验收”的原建议不再代表现行规划。
用户后续增加按字段配置，并明确未提供配置默认不改；原固定 Protocol / 转码字段自动修改将取消，
仅在显式配置时修改，详见现行 Slice 合同 v3 及其字段补充，以下原策略保留描述仅为 v1 历史。

```text
Status: DRAFT — DESIGN ONLY
Observed Source HEAD: 6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5
Plan Checkpoint: NOT SET
Implementation Head: NOT SET
Independent Review: PENDING
```

本文件只记录待审阅方案，不激活实施 Task 或 Slice，不代表已实现或通过独立审查。
调查时已跟踪文件无修改，存在未跟踪的 `artifacts/`，本次保留原样。

## 1. 删除边界

完整 JSON 缓存与媒体源直链映射是两个独立机制，本次仅撤除前者及其专属配置、策略和诊断。

| 机制 / 行为 | 当前实现 | 目标 |
|---|---|---|
| 完整 PlaybackInfo JSON 缓存 | `PlaybackInfoCache` 按 Item ID 保存上游正文，默认 TTL 6 小时、最多 4096 条 | 删除模块、实例和所有读写路径 |
| JSON 缓存客户端绕过 | `playback_cache_bypass_clients` 单独控制缓存读写 | 删除，所有 PlaybackInfo 均回源 |
| JSON 缓存诊断 | 代理添加 `X-JellyfinProxy-Cache: HIT/MISS`，记录缓存状态 | 停止生成响应头和相关日志字段 / 事件 |
| 媒体源直链映射 | `MediaSourceCache` 保存 `MediaSource.Id → Path`，最多 4096 条，无 TTL | 保留现有容量、LRU、UUID 归一化和失效清理 |
| PlaybackInfo 修改 | `PlaybackService`、`MediaSourceService`、`ProtocolFileRule` | 保留 |
| Video 302 与流式回退 | `VideoHandler`、`ProxyHandler` | 保留 |

采用实际删除，不保留可重新启用的 JSON 缓存开关；也不以新的响应缓存、请求合并、后台预热或
探测机制替代。直链映射继续共享现有行为，不借本次删除调整其认证隔离或生命周期。

## 2. 请求处理合同

对现有路由规则识别的 GET / POST `/Items/{id}/PlaybackInfo` 和
`/emby/Items/{id}/PlaybackInfo`，统一执行：

1. `Dispatcher` 沿用客户端识别和修改绕过判定，将 `modify` 传给 `PlaybackHandler`。
2. `PlaybackHandler` 每次调用现有 `JellyfinHttpClient.forward()`，不查询或保存完整响应。
   原方法、路径、查询、请求体和认证信息继续由现有 HTTP 层转发。
3. 上游非成功状态或正文无法解析为 JSON：保持现有状态码、正文及响应头适配，直接返回；
   不更新或清空既有直链映射，不增加旧 JSON 回退或新的异常转换。
4. 成功解析 JSON 且 `modify=True`：调用原 `PlaybackService.modify()`，保留媒体策略、
   `Protocol=File`、禁用转码等既有规则；由原逻辑记录策略处理后的媒体源直链。
5. 成功解析 JSON 且 `modify=False`：调用原 `remember_media_sources()` 记录直链，
   返回上游正文原有字节内容，不重序列化。此处字节指 `httpx` 解码后的正文，沿用现有
   编码与长度响应头适配，不新增压缩或流式行为。
6. 返回本次上游对应的结果，不再由代理附加缓存 HIT/MISS 标记。其他可透传响应头沿用原规则，
   不为此增加全局响应头过滤；`X-Request-ID`、版本头和日志脱敏继续生效。

同一 Item 连续或并发发起 N 次 PlaybackInfo 请求，应执行 N 次上游调用；不同用户、设备、
token、请求体、GET / POST、UUID 格式及有无 `/emby` 前缀均不复用完整响应。路由支持范围、
大小写和尾斜杠规则保持现状，不因删除缓存键的正则表达式扩大路由匹配。

## 3. 保持不变的播放与回退行为

| 场景 | 删除后要求 |
|---|---|
| 全局 `bypass_clients` | 继续优先于两类路由的独立绕过配置 |
| `playback_bypass_clients` | 仅绕过 PlaybackInfo 正文修改，仍回源、记录直链 |
| `video_bypass_clients` | 仅绕过 Video 重定向，继续透明流式代理 |
| 有效 HTTP(S) Path | 按原规则建立 / 更新媒体源映射，Video 可以返回 302 |
| 同一 ID 后续出现本地 / 空 / 无效 Path | 沿用既有失效清理，只删除该 ID 的旧映射，Video 回退代理 |
| 后续同一 ID 再出现有效 Path | 重新建立映射并恢复重定向 |
| 上游失败、非法 JSON、缺少该媒体源 | 不因本次响应整体清空映射，沿用原行为 |
| Video 参数与路径 | 保留 `MediaSourceId` / `mediaSourceId` 优先级、Videos 路径 ID、UUID 格式兼容 |
| danmu raw | 保留 `/emby/api/danmu/{id}/raw` 与 `/api/danmu/{id}/raw` |
| 未命中映射或 Video 绕过 | 保留 Range、206、媒体响应头、异步流式传输及上游资源释放 |

`MediaResolver` 在修改路径下可能抛出的既有畸形 URL 异常不在本次修复范围；不得将
`MediaSourceCache` 自身的解析异常处理扩大描述为整个播放链都能吞掉解析异常。
代理继续只使用 Jellyfin 返回的媒体信息，不打开 STRM、不运行 ffprobe、不访问 Jellyfin 数据库。

## 4. 配置迁移

删除以下 Settings 字段及其 TOML / 环境变量读取：

| TOML / Settings 字段 | 环境变量 |
|---|---|
| `playback_info_cache_enabled` | `PLAYBACK_INFO_CACHE_ENABLED` |
| `playback_info_cache_ttl_seconds` | `PLAYBACK_INFO_CACHE_TTL_SECONDS` |
| `playback_info_cache_max_entries` | `PLAYBACK_INFO_CACHE_MAX_ENTRIES` |
| `playback_cache_bypass_clients` | `PLAYBACK_CACHE_BYPASS_CLIENTS` |

推荐兼容策略：旧 TOML 中的这些键按现有未知键规则忽略，遗留环境变量不再读取、转换或校验。
在 TOML 语法合法的前提下，旧缓存值即使不符合原类型 / 数值约束，也不阻止启动；不能重新开启
已删除功能。无需保留废弃字段、专门兼容分支或新增启动告警。

`.env.example` 删除这四项。当前 `JellyfinProxy.toml` 本来就未列出这四项，无需人为补写后再删除。
README 明确说明旧配置无效、可移除。其余配置的默认值、环境覆盖优先级和路径解析规则不变。

## 5. 文件变更计划

| 文件 | 计划修改 |
|---|---|
| `services/playback_info_cache.py` | 删除 `PlaybackInfoCache`、`CachedPlaybackInfo` 及模块 |
| `handlers/playback_handler.py` | 删除缓存依赖、`cache` / `use_cache` 参数、缓存键与哈希 / 正则、HIT/MISS 分支和日志；保留回源处理 |
| `handlers/dispatcher.py` | 删除缓存注入和绕过判定；保留修改绕过；客户端日志移除 `cache=`，保留其他字段与清洗 |
| `policies/client_policy.py` | 删除缓存绕过构造参数、字段和 `should_bypass_playback_cache()`；保留其余三类绕过 |
| `main.py` | 删除缓存实例化、配置引用及注入参数，保留应用生命周期和上游关闭 |
| `config.py` | 删除四个专属字段及 `from_env()` / `from_file()` 中的读取 |
| `.env.example`、`README.md` | 移除当前功能说明和配置；保留直链映射说明，补充升级影响 |
| `AGENTS.md` | 只同步删除后不再存在的“PlaybackInfo 缓存绕过”约束，保留其他职责、优先级和缓存边界约束 |
| `tests/test_core.py` | 替换 JSON 缓存命中测试；去掉夹具和矩阵的缓存依赖，保留其他业务断言 |
| `tests/test_config.py`、`tests/test_logging.py` | 验证遗留配置忽略、其他配置不变，以及客户端日志不再宣称缓存开启 |
| `version.py`、`CHANGELOG.md` | 实施时按主动功能撤除确定新版本并新增记录；设计阶段不升级版本 |

`services/playback_service.py`、`services/media_source_cache.py`、`services/media_source_service.py`、
`handlers/video_handler.py`、`handlers/proxy_handler.py`、路由和 HTTP 基础设施预计无需改动。
历史 CHANGELOG、历史 Task / 审查报告和证据保留原貌，不把删除功能扩展成回滚整个 v0.9.0。
Docker / Compose 和 PyInstaller 当前没有显式注册该缓存模块，不为删除模块调整部署方式或依赖。

## 6. 验收与验证计划

实施按 T4 准备，覆盖缓存撤除、会话响应新鲜度和关键播放回归。现有业务测试保持验收强度；
只删除因功能撤除已不成立的“应命中 JSON 缓存”断言及对应测试维度。

| 验收项 | 可核验证据 |
|---|---|
| AC-1 每次请求都回源 | 假上游计数：相同请求连续 / 并发 N 次得到 N 次调用，不合并请求 |
| AC-2 返回本次上游结果 | 假上游逐次返回不同 `PlaySessionId`、媒体数据和自定义头；确认第二次使用新结果，修改模式只发生原策略变更 |
| AC-3 请求内容独立转发 | 覆盖不同用户、设备、认证、查询、POST 请求体、GET / POST 与两种路由前缀，核对实际发往假上游的内容 |
| AC-4 绕过优先级不变 | 通过真实 Dispatcher 的全局 / PlaybackInfo / Video 绕过矩阵；PlaybackInfo 原文返回仍能填充直链 |
| AC-5 直链能力不退化 | 保留 ID 兼容、302、两种 raw、无效 Path 单 ID 清理、其他 ID 保留及恢复用例；有效→无效→有效在同一服务实例连续验证 |
| AC-6 失败行为不变 | 已成功请求后再返回 401 / 500 / 非 JSON，确认实际回源并返回本次结果；原映射处理及传输异常行为不变 |
| AC-7 配置可升级 | 新配置和含四项旧配置的配置均可加载；遗留无效缓存值不参与校验，其他配置覆盖规则保持 |
| AC-8 移除专属诊断 | 上游未带缓存头时代理不生成该头；无 HIT/MISS 日志和 `cache=enabled/bypass`，其余日志 / 脱敏保留 |
| AC-9 入口及代理回归 | FastAPI 生命周期和请求入口使用假上游验证；保留 Range / 206、分块传输及正常结束后关闭上游的原回归 |
| AC-10 删除完整且文档一致 | 运行时代码与当前配置示例无残留启用路径；README / AGENTS / 新版本记录一致，历史记载不改写 |

开发反馈命令（仓库根目录）：

```bash
.venv/bin/python -m pytest tests/test_core.py tests/test_config.py tests/test_logging.py
```

最终候选门槛：

```bash
.venv/bin/python -m pytest
git diff --check
```

独立 B 验证重点为每次回源、同一实例直链失效 / 恢复、绕过矩阵、遗留配置及响应头；其余相同
可执行输入可结合原始证据复核。没有独立审查者时保持 PENDING，不自签 PASS。

证据记录真实源码 SHA / 工作区摘要、Python / 依赖版本、命令、配置与夹具身份、退出码、计数、
耗时和原始日志。测试要隔离环境变量，认证值只用合成夹具并在证据中脱敏；保留首次失败及重跑。
可执行输入变化后按影响重跑，最终 T4 保留全套回归。测试数因删除缓存维度而变化时列出对应关系，
不以历史通过数量代替本次验证。

真实 Jellyfin、客户端兼容、实际探测耗时和部署 / 打包不属于本次设计验证；未执行时分别标为
NOT RUN，不能以假上游结果代替。后续若修改打包配置，应再按发布说明增加适用构建验证。

## 7. 预期影响与交付顺序

删除后重复 PlaybackInfo 不再被代理缓存截获，每次等待 Jellyfin；Jellyfin 可能再次触发 STRM
探测，上游请求数和延迟可能增加。代理不再长期保存完整 JSON，但仍需解析当前请求的 JSON，
媒体源直链映射也继续存在，不能据此承诺具体内存降幅或性能结果。

各请求获得对应的最新上游状态、会话字段和响应头；不再复用其他请求的完整正文。JSON 缓存的
HIT/MISS 监控需要随功能撤除调整；视频直链命中后的 302 和未命中后的流式回退继续按原合同执行。

建议作为一个完整实施 Task 交付：先固化本方案的删除边界与验收并建立计划检查点，再完成代码、
配置、测试及文档同步，执行最终回归，交独立 B 审查。此目标是用户要求的功能撤除，不虚构成现有
bug，也不新增大版本能力 Slice。实施前固定真实 Task Base；新版本号由实施计划按撤除性质确定，
不将本次功能删除写成向后兼容的 bugfix。

本次仅新增此设计草案。文档核查结果在交付时报告；产品测试、实施和独立审查均未执行。
本次设计授权完成后不自动开始代码删除、提交、push、发布或真实服务操作。

```text
Next Action: NONE — AUTHORIZED DESIGN WORK COMPLETE
```
