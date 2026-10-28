# Slice S2 — 视频 HEAD 透传、GET/HEAD 处理日志与精确路由

遵循[开发流程](../docs/development-workflow.md)和 [Slice 模板](SLICE_TEMPLATE.md)。
用户要求规划一个 Slice，包含 HEAD 透传、视频请求日志和视频路由收紧三项结果，
并于 2026-10-28 明确授权激活。本合同现为 ACTIVE；尚未发布 B Task 或开始产品实施。

```text
Slice ID: S2
Owner: A
Status: ACTIVE
Planned On: 2026-10-28
Activated On: 2026-10-28
Contract Revision: 1
Base SHA: 3f997b53128305dd4e25b616b0794408ffefa859
Contract Checkpoint: NOT SET
Implementation Head: NOT SET
Required Test Level: T4
Independent B Review: PENDING
A Final Review: PENDING
```

Base 为规划时实际源码，产品版本为 `1.0.1`；不随纯文档提交前移。激活前已核对
Base 至当前 HEAD 仅有 S2 规划文档变更，产品源码未变化，Base 保持固定。
`Contract Checkpoint` 指已提交的 ACTIVE 合同，由激活提交产生后从 Git 解析，
以纯文档后继补记，避免自引用 SHA。原 PLANNED 提交保留为规划历史。
本次激活沿用规划中的三项 RO、细化边界和验收要求，仅更新生命周期状态。

## 用户目标

1. 视频 HEAD 请求直接透传 Jellyfin；GET 在规定的视频入口保持现有直链与回退逻辑。
2. GET/HEAD 视频请求产生可关联的应用日志，记录处理方式、映射命中情况和响应状态。
3. 视频特殊处理仅适用于 `/Videos/{itemId}/stream` 和
   `/Videos/{itemId}/stream.{container}`，其中 `Videos`、`stream` 不区分大小写。

用户给出的 `/Videos/abc/stream` 中，`abc` 按示例 itemId 理解，不是固定字面量。

## 当前基线与架构边界

| 当前事实 | 目标差异及受影响位置 |
| --- | --- |
| [路由表](../routers/route_config.py) 匹配任意 `/Videos/{id}/...`、`/videos/{id}/...` 及 `/video/...`，未限制方法 | 仅完整匹配两种 stream 路径，视频分类只接受 GET/HEAD；其他请求落到 DEFAULT |
| [VideoHandler](../handlers/video_handler.py) 不区分方法，查询映射后即可返回 302 | HEAD 在任何映射读取前透传；GET 保留查询 ID 优先级、路径 ID 兜底和 302 / 流式回退 |
| [Dispatcher](../handlers/dispatcher.py) 在 VideoHandler 之前处理客户端绕过 | 保持全局与 Video 绕过优先级，绕过路径也须进入视频结果日志覆盖面 |
| 现有 `client_identified`、`request_completed` 分别记录客户端和通用状态，缺少视频处理结果 | 新增统一的视频结果记录，覆盖 HEAD、GET 命中 / 未命中、绕过和响应前失败 |
| [普通代理](../handlers/proxy_handler.py) 使用 StreamingResponse 并关闭上游响应 | 复用现有转发和头适配；验证 HEAD 无正文、GET Range 与断连释放，按实际缺口最小修正 |
| [媒体源映射](../services/media_source_cache.py) 是容量 4096 的 LRU，读取命中会调整顺序，无效 Path 删除该 ID | HEAD / 绕过不查询、不改变 LRU；GET 日志复用同一次查找结果，不新增缓存机制 |

既有资产包括 [核心测试](../tests/test_core.py)、[日志测试](../tests/test_logging.py)、
应用工厂的假上游夹具、媒体源失效 / 恢复测试，以及普通流式代理测试。现有路由测试中
将 `master.m3u8`、HLS 子路径和 `/video/...` 认定为 VIDEO 的断言需要按本合同更新，
同时证明这些请求实际透传，不能只删除旧断言。

### MediaWarp 参考

核对日期：2026-10-28；仓库：[AkimioJR/MediaWarp](https://github.com/AkimioJR/MediaWarp)。
固定源码：`09fac019f228999dadd400d4421ab1c25be7fc20`。
其 [JellyfinHandler.VideosHandler 第 191～196 行](https://github.com/AkimioJR/MediaWarp/blob/09fac019f228999dadd400d4421ab1c25be7fc20/internal/handler/jellyfin.go#L191-L196)
在入口检查 `http.MethodHead`，调用 `ReverseProxy` 后立即返回，跳过后续媒体处理。
本 Slice 采用这一处理顺序，沿用本仓库 FastAPI / httpx 代理和媒体源映射。
MediaWarp 的媒体查询、STRM / AList 处理、路由正则和凭据配置不属于本次移植范围。

## Required Outcomes / Surfaces

| ID | 必须交付的结果 | 验收面 |
| --- | --- | --- |
| RO-1 | HEAD 始终回源，GET 在新路由范围内保持直链、回退和恢复 | H-01～H-03、G-01～G-03；方法 / 请求 / 响应头、无正文、映射无副作用、Range 与释放 |
| RO-2 | GET/HEAD 视频请求均有真实、可关联且不泄露认证值的结果日志 | L-01～L-04；处理动作、查询结果、响应状态、绕过 / 失败、请求 ID 和脱敏 |
| RO-3 | 仅两种 stream 路径的 GET/HEAD 进入视频处理，关键词大小写不敏感 | R-01～R-03；完整匹配、正反例、方法边界、非视频普通透传和迁移说明 |

### RO-1：HEAD / GET 行为合同

HEAD 的方法检查必须发生在直链映射读取之前。命中全局或 Video 绕过策略时仍走
普通代理；未命中策略的 HEAD 也直接走普通代理。两种情况均不查找直链、不调整 LRU、
不写入或删除映射，不向媒体直链发探测请求，也不额外请求 PlaybackInfo / Items。

HEAD 以原方法访问 Jellyfin，保留现有 raw path、原始查询串、认证及 Range / 条件头
转发规则。响应保留 Jellyfin 的状态和适用的表示头，例如 `Content-Type`、
`Content-Length`、`Content-Range`、`Accept-Ranges`、`ETag`、`Last-Modified`，
客户端不收到正文。不得因无正文将上游非零 `Content-Length` 改为 0。
沿用现有逐跳头过滤、Date / Server 适配及代理自身版本 / 请求 ID 头规则。
上游响应在正常完成、异常和取消时均应释放，不为 HEAD 消费完整媒体正文。

HEAD 不生成代理直链 302。若 Jellyfin 自身返回 3xx，则原样保留其状态及适用的
`Location`，不在代理端跟随；这是回源响应，不应被日志标记为直链命中。
上游 4xx / 5xx 也保留原码；连接失败 / 超时延续既有异常处理，不另设错误映射。

GET 在两种合法路径上保持以下顺序：

1. 全局绕过优先，其次为 Video 绕过；绕过直接代理且不查询映射。
2. 未绕过时，使用非空 `MediaSourceId`，其次为非空 `mediaSourceId`，两者均无值时
   才使用路径 itemId。查询 ID 未命中时不再改用路径 ID 尝试第二次查找。
3. 沿用 UUID 带 / 不带连字符的规范化，非 UUID ID 仍区分大小写；不改写真实请求路径。
4. 有可用映射返回现有 302 和实际媒体 URL；无映射则流式代理 Jellyfin。
   映射失效后回退、再次收到有效媒体源后恢复，其他 ID 不受影响。

“GET 保持现有直链逻辑”指上述合法入口中的算法；旧的其他视频入口按 RO-3 改为普通
代理，这是本 Slice 明确要求的行为变化。

### RO-2：视频结果日志合同

每个匹配 RO-3 的 GET/HEAD 请求在得到响应状态时，输出一条 INFO 级应用日志
`video_request_result`，沿用现有日志文件 / 标准输出、日志级别、轮转和请求 ID 上下文。
此结果日志须覆盖 Dispatcher 提前绕过分支，不能只在 VideoHandler 查映射时输出。

必需字段为现有上下文 `request_id`，以及 `method`、`action`、`reason`、`mapping`、
`status`。字段语义固定如下；不记录完整 PlaybackInfo JSON 缓存命中信息。

| 场景 | action | reason | mapping | status |
| --- | --- | --- | --- | --- |
| 未绕过的 HEAD | `proxy` | `head_passthrough` | `not_checked` | Jellyfin 返回码 |
| 全局或 Video 绕过的 GET/HEAD | `proxy` | `client_bypass` | `not_checked` | Jellyfin 返回码 |
| GET 映射命中 | `redirect` | `mapping_hit` | `hit` | `302` |
| GET 映射未命中 | `proxy` | `mapping_miss` | `miss` | Jellyfin 返回码 |

方法仍明确记录为 HEAD / GET，策略绕过分支的 reason 保持 `client_bypass`。
媒体源失效后的查找也是 `miss`：现有缓存没有失效历史，不能把普通未命中声称为过期
或失效。为输出日志不得额外调用 `get()`、刷新映射或增加墓碑 / TTL。

响应开始前的连接失败、超时或其他异常也须输出一条相同事件的失败记录：
`action` / `reason` / `mapping` 保留实际已选择的路径，`status` 对齐外层最终错误响应
（当前未处理异常为 500），另加 `outcome=error` 与安全的异常类别，避免假记上游状态。
成功取得 HTTP 响应可标记 `outcome=response`；上游 HTTP 4xx / 5xx 属于真实 HTTP 响应。
同一请求只产生一条该结果事件，既有通用请求 / 异常日志可以继续保留。

这里的状态表示代理选定并开始返回的 HTTP 响应状态，不表示客户端已经完整播放或
接收全部媒体字节。响应头发出后的流错误 / 客户端断连沿用既有异常处理，不补造新的
HTTP 状态，也不将已经返回的 200 / 206 改记成 500。

日志不包含媒体直链、上游 `Location`、签名 URL、查询参数、请求正文、API key、
token、Authorization 或 Cookie；异常类别不附带可能含完整 URL 的异常文本。
无需为新增事件输出媒体源 ID 或客户端原始头。若增加路径等辅助字段，必须去除查询串、
清理控制字符并限制长度；对日志的处理不能修改实际请求或 302 地址。
现有 `client_identified` 若保留，Video 的动作描述须与 HEAD 透传 / GET 重定向或回退
相容，避免继续将所有非绕过视频请求笼统标记为 `modify`。PlaybackInfo 日志语义保留。

示例（值均为示意）：

```text
request_id=req-1 video_request_result method=GET action=redirect reason=mapping_hit mapping=hit status=302 outcome=response
request_id=req-2 video_request_result method=HEAD action=proxy reason=head_passthrough mapping=not_checked status=200 outcome=response
request_id=req-3 video_request_result method=GET action=proxy reason=mapping_miss mapping=miss status=404 outcome=response
```

业务分支及映射结果由 Dispatcher / VideoHandler 决定。可在请求上下文中传递少量结果，
由一个明确的出口输出日志；具体接口由 B 根据实际实现规划。日志基础设施只负责格式、
上下文和安全输出，不通过解析 URL、状态码或日志文本重新判断业务路径。

### RO-3：路由语法与边界

仅 GET、HEAD 使用视频分类；其他方法即使路径相同也走 DEFAULT，按原方法透传，
不进行直链查询，不产生视频专属结果事件，通用请求日志仍生效。

两种合法路径都从根 `/` 开始，完整匹配，不允许额外前缀、尾随 `/` 或后续路径段。
itemId 是非空单一路径段，不新增数字 / UUID 限制；container 是非空单一扩展名，
不含 `/` 或 `.`，不设具体容器白名单。不统一转换 itemId 或 container 的大小写。
关键词大小写匹配仅针对 ASCII `Videos` / `stream`，不扩展其他路由的大小写规则。

等价语法可表达为以下 Python 正则配合 `fullmatch`，B 可以沿用等价的现有路由结构：

```python
r"/(?ai:videos)/(?P<item_id>[^/]+)/(?ai:stream)(?:\.(?P<container>[^/.]+))?"
```

| 必须匹配的 GET/HEAD 示例 | 必须落到 DEFAULT 的示例 |
| --- | --- |
| `/Videos/abc/stream` | `/Videos/abc`、`/Videos/abc/` |
| `/VIDEOS/abc/STREAM` | `/Videos/abc/stream/`、`/Videos/abc/stream.mp4/extra` |
| `/vIdEoS/abc/StReAm.mp4` | `/Videos/abc/stream.`、`/Videos/abc/stream.mp4.extra` |
| `/Videos/source-id/stream.mkv` | `/Videos//stream`、`/Videos/abc/original.mp4` |
| `/Videos/788be25d-f930-7eb4-19a2-316de9f9d699/stream` | `/Videos/abc/master.m3u8`、`/Videos/abc/hls/a.ts` |
| `/videos/abc/stream.MP4` | `/Videos/abc/Subtitles/0/Stream.srt`、`/video`、`/video/stream/movie.mkv` |
| `/Videos/abc/stream.m3u8` | `/emby/Videos/abc/stream`、`/prefix/Videos/abc/stream` |

`stream.m3u8` 符合第二种格式；按文件名 `master.m3u8` 或 HLS 子目录匹配的旧行为撤除。
查询参数不参与路由分类，不能靠 `MediaSourceId` 让不合规路径重新获得视频处理。
仍使用 FastAPI 的 `request.url.path` 进行识别；URL 解码后出现额外 `/` 的路径不满足
单段要求，实际回源继续使用原始编码路径和查询串，不新增路径重写。

所有 DEFAULT 请求按普通 HTTP 代理处理，保留上游返回的正文、状态及适用头；
“不生成视频直链 302”不等于拦截上游自身的 302。两个 danmu raw 入口继续属于 DEFAULT。

## 约束、不变量与非目标

- 沿用 `routers / handlers / policies / services / infrastructure` 分层；路由语法在
  routers，HTTP 方法适配和结果在 handlers，客户端策略在 policies，映射在 services。
- 全局绕过保持最高优先级；PlaybackInfo 修改绕过仍会填充媒体源映射，Video 绕过独立
  控制 GET 重定向。不得重引入完整 PlaybackInfo JSON 缓存及其配置或诊断。
- 仅依赖 Jellyfin 返回的媒体信息，不读取 STRM、不运行 ffprobe、不访问 Jellyfin 数据库，
  不增加直链探测、媒体下载或服务器端跟随重定向。
- 保持流式代理、Range / 条件请求、表示头、上游响应释放及有界内存；不缓存完整视频。
- 不增加新配置、依赖、日志平台、统计接口、缓存状态历史或其他视频入口。
- 规划与激活阶段仅维护合同，不修改产品代码、版本和发布说明中的已发布行为。实施后由对应 Task
  同步 README、配置行为文档和 CHANGELOG；版本唯一来源为 `version.py`，具体功能版本
  在实施 Task 确定，不因此自动发布、push、打标签或部署。
- 工作开始时只有未跟踪 `artifacts/`；保留全部既有用户文件和证据，不纳入本次提交。

## 最终验收

以下是后续实施的必需矩阵，不是本轮已执行结果。B 发布 Task 时补全准确聚焦命令、
夹具身份和四部分测试计划，并以完整源码差异和实际证据逐项核对。

| ID | 必需验证与判据 | 对应结果 |
| --- | --- | --- |
| H-01 | 两种合法入口、关键词混合大小写、有效 / 无映射的 HEAD 均仅发送一次上游 HEAD；查找次数为 0，映射内容与 LRU 顺序不变；随后 GET 仍可命中原映射 | RO-1、3 |
| H-02 | HEAD 200、206、304、302、404、416、500 的状态及适用表示 / 条件 / Location 头保留；非零 Content-Length 不改为 0，客户端正文为空，流被关闭 | RO-1 |
| H-03 | HEAD 的原始编码路径 / 查询串、认证、Range / 条件头正确回源；上游超时 / 连接失败和取消释放不泄漏，不发送 GET 或直链探测 | RO-1 |
| G-01 | GET 命中返回原始 302 地址，含签名参数仍保持正确；非空查询 ID 优先级、空值兜底、查询未命中不再尝试路径、UUID 规范化及普通 ID 大小写保留 | RO-1 |
| G-02 | GET 无映射 / 失效 / 恢复闭环，其他 ID 隔离；200 / 206 / 302 / 4xx / 5xx 回退响应、Range、原始路径 / 查询及释放符合现有代理合同 | RO-1 |
| G-03 | 全局 / Video 绕过下 GET/HEAD 均不查映射；仅 PlaybackInfo 绕过仍填充映射，非 Video 绕过的 GET 仍重定向；组合策略保持全局优先 | RO-1、2 |
| L-01 | HEAD、GET 命中 / 未命中、两类策略绕过均各有且仅有一条结果事件，所有必需字段和请求 ID 与同次响应一致 | RO-2 |
| L-02 | 上游自身 302 记录为 proxy，不记成 hit；上游 4xx / 5xx 保留真码；响应前异常记录实际错误状态和安全类别，无成功事件重复输出 | RO-2 |
| L-03 | 请求 / 直链 / 上游重定向中放入合成 API key、token、签名、Authorization、Cookie 哨兵值，应用结果日志及异常输出无泄漏；原转发与 Location 不被脱敏改写；辅助字段不能注入新日志行 | RO-2 |
| L-04 | 并发请求的请求 ID、动作、命中和状态不串扰；取得响应头即有日志，不等完整视频，不借日志额外查映射；普通请求与 PlaybackInfo 日志保留原职责 | RO-2 |
| R-01 | 路由正反例和 GET/HEAD 方法矩阵全部满足 RO-3；其他方法均为 DEFAULT，PlaybackInfo 原路由不受影响 | RO-3 |
| R-02 | 为排除路径种入同 ID 映射并携带查询 ID，应用入口仍真实回源；覆盖旧 `/video`、master / HLS、字幕、前缀 / 尾随段、两个 danmu raw，保留上游响应而非仅断言分类 | RO-3 |
| R-03 | 编码路径与查询不扩大分类，ASCII 混合大小写合法入口可 GET 重定向 / HEAD 回源；无路径重写，迁移文档说明旧入口变化 | RO-1、3 |

### 测试门槛与证据

- 开发反馈：复用并扩展现有 `tests/test_core.py` / `tests/test_logging.py`，覆盖上述分支；
  新建测试文件仅在有必要时使用，不要求另建验证框架。
- 最终候选为 T4：在仓库根运行 `.venv/bin/python -m pytest` 和 `git diff --check`。
  完整套件已覆盖相同聚焦输入时可复用，不机械重跑。
- 另用隔离本地 HTTP 上游和真实 HTTP 客户端验证 HEAD 无正文 / 头保留、GET Range、
  流式返回及中途断连释放；证明未读取完整媒体即返回 / 中断，并能继续后续 Range。
  可以复用符合最终输入的既有证据，不以会缓冲正文的 TestClient 单独证明网络流式特性。
- B 独立复现 HEAD 有映射仍回源、GET 命中 / 失效恢复、旧入口有映射仍回源及日志脱敏 / 状态；
  核对全部原始证据和最终候选 SHA，不能仅据实施者全绿摘要签发 PASS。
- 保留工作目录、命令、源码 SHA / 未提交摘要、Python / 依赖、配置与合成夹具身份、退出码、
  数量 / 耗时、首次失败和重跑，按[证据要求](../docs/development-workflow.md#5-证据与审查)
  保存至 S2 对应目录或 CI。记录访问边界，敏感值脱敏。
- 本 Slice 不新增真实 Jellyfin / 实机客户端或生产操作要求，也不继承 S1 的环境授权及
  12.3 版本锁。此类验证未执行时明确记 NOT RUN，不能把本地 HTTP 结果声称为真实兼容；
  仅修改当前涉及的代码 / 文档不要求二进制打包或发布。

交付文档必须明确两种入口、HEAD 回源与 GET 直链差异、其他方法 / 旧入口透传、日志字段
和“响应状态不代表完整播放”的含义。历史 CHANGELOG 事实保留，在新增版本条目说明变化。

## Task 索引

以下是 A 建议的三个行为闭环，尚非 B 计划；不预设后续 Base、实现 Head 或审查结论。
B 下一步依据本 ACTIVE 合同及真实前序结果逐项规划，可以在不改变 RO 的前提下调整划分。

| 建议顺序 | 行为闭环 | 依赖与结果 | 当前状态 |
| --- | --- | --- | --- |
| S2.1 | 精确路由 + HEAD 透传 + 合法 GET 保留 / 旧入口回源 | ACTIVE 合同；RO-1、3，包含失败、回退、释放和策略回归 | 未发布 B 计划 |
| S2.2 | 所有视频 GET/HEAD 分支的结果日志 | S2.1 独立 B PASS；RO-2，包含绕过、错误、并发和脱敏 | 未发布 B 计划 |
| S2.3 | 最终候选整体验证、迁移文档与版本协调 | 前序独立 B PASS；重评全部 RO，完成 T4 / HTTP 证据及 Closure Packet | 未发布 B 计划 |

当前根 [TASK](../TASK.md) 保持无活动实施任务。本轮完成合同激活与检查点记录后停止；
后续交 B 规划并提交首个 Task，不在本轮代替 B 规划或 Developer 实施。

## Closure Packet

- Base：`3f997b53128305dd4e25b616b0794408ffefa859`；Implementation Head：NOT SET。
- 全部 RO 对照与独立 B 决定：PENDING。
- 最终检查 / 原始证据 / 复用依据：NOT SET；产品验证 NOT RUN（仅完成规划与激活）。
- 不变量 / P2 / 延期：待实施与独立审查；没有已确认的延期结果。
- 真实 Jellyfin / 实机客户端 / 打包 / 生产部署：NOT RUN，不属本轮激活执行范围。
- 文档与状态协调：当前为 ACTIVE，无活动 Task；最终交付协调 PENDING。

## A Final Review

```text
Reviewed Range: NOT SET
Reviewer / Independence: NOT SET
Decision: PENDING
P0 / P1 Blockers: NOT SET
Closure Reconciliation: PENDING
Next Action: NONE — AUTHORIZED WORK COMPLETE
```

以上 Next Action 仅表示本轮激活授权已完成，不表示 Slice 已实施或验收。
未来移交：由 B 基于已提交的 ACTIVE 合同规划首个 Task；实施及独立审查结论均待后续实际产生。
