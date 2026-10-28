# Slice S2 — 视频 HEAD 透传、GET/HEAD 处理日志与精确路由

> 历史归档；原路径：`Task/S2-video-head-routing-and-logging.md`。2026-10-29 独立 A 最终 **PASS / CLOSED**。
> 保留修订、B 交接和未运行项；阶段性状态不作为当前实施指令。见[历史索引](README.md)。

遵循[开发流程](../../docs/development-workflow.md)和 [Slice 模板](../SLICE_TEMPLATE.md)。
本合同按用户“保留底线”的要求精简：保留三项产品结果、必要兼容与日志安全，
不把日志写法、缓存内部结构或额外测试工程作为交付目标。

```text
Slice ID: S2
Owner: A
Status: PASS / CLOSED
Closed On: 2026-10-29
Planned On: 2026-10-28
Activated On: 2026-10-28
Contract Revision: 2 — retain essential outcomes and acceptance
Revised On: 2026-10-28
Base SHA: 3f997b53128305dd4e25b616b0794408ffefa859
Contract Checkpoint: 88b5c25e40b2c4ee1139ed4458cc303e949666cb
Implementation Head: a2f7d46afc1339d3a3b91e57c7fa1db29749580f
Required Test Level: T4 — related tests and existing full regression; additional checks by actual impact
Independent B Review: PASS — S2.1 / RO-1～3, 2026-10-29
A Final Review: PASS — independent A final review, 2026-10-29
```

Base 保持规划时的真实源码，产品版本仍为 `1.0.1`，纯文档修订不使 Base 前移。
首个 [S2.1 计划](S2.1-video-request-handling-and-logging.md)已于 2026-10-28
激活；Developer 已完成实现、测试和文档同步，2026-10-29 独立 B 审查 PASS，
实现 Head 为 `a2f7d46afc1339d3a3b91e57c7fa1db29749580f`；全部 RO 已重评，独立 A 最终审查 PASS，Slice 已关闭。
Contract Checkpoint 已从 Git 解析，并由纯文档后继补记；
后续 B 计划以本修订为准，不以最初激活提交代替当前合同。

## 用户目标

1. 视频 HEAD 请求透传 Jellyfin；GET 保持现有直链与回退逻辑。
2. 增加 GET/HEAD 视频请求日志，能看出处理方式、映射命中情况和响应状态。
3. 视频特殊处理精确限制为 `/Videos/{itemId}/stream` 和
   `/Videos/{itemId}/stream.{container}`，`Videos`、`stream` 不区分大小写。

用户示例中的 `abc` 是可变 itemId 的示例，不是固定字面量。

## 当前基线与架构边界

以下保留固定 Slice Base 的改前行为，不是当前实现；目标实现与最终核对见文末 A 审查。

- [路由表](../../routers/route_config.py) 当前会匹配任意 `/Videos/{id}/...`、
  `/videos/{id}/...` 和 `/video/...`，需要收紧到上述两种格式。
- [VideoHandler](../../handlers/video_handler.py) 当前不区分方法，命中映射就返回 302；
  HEAD 应直接交给现有[普通代理](../../handlers/proxy_handler.py)，GET 沿用现有算法。
- [Dispatcher](../../handlers/dispatcher.py) 会提前处理客户端绕过，新增日志不能漏掉该分支。
  业务判断留在现有路由、策略和处理器，日志基础设施只负责输出与上下文。
- 复用现有[核心测试](../../tests/test_core.py)、[日志测试](../../tests/test_logging.py)和
  假上游夹具；不要求新增框架或另建日志、缓存抽象。

### MediaWarp 参考

已于 2026-10-28 核对固定源码 `09fac019f228999dadd400d4421ab1c25be7fc20` 的
[JellyfinHandler.VideosHandler](https://github.com/AkimioJR/MediaWarp/blob/09fac019f228999dadd400d4421ab1c25be7fc20/internal/handler/jellyfin.go#L191-L196)：
其入口遇到 HEAD 即调用反向代理并返回。本项目只参考这一顺序，不移植其媒体查询、
STRM / AList 处理或其他路由规则。

## Required Outcomes / Surfaces

| ID | 必须交付的结果 | 验收面 |
| --- | --- | --- |
| RO-1 | HEAD 真正回源，合法入口的 GET 直链与回退不变 | AC-1、AC-2：方法、响应、映射命中 / 未命中及绕过 |
| RO-2 | GET/HEAD 视频日志准确、可关联且不泄露凭据 | AC-3：处理方式、命中情况、响应状态与安全 |
| RO-3 | 仅两种 stream 格式进入视频特殊处理，关键词大小写不敏感 | AC-4：合法入口及被排除入口的实际行为 |

### HEAD 与 GET 底线

- HEAD 直接按原方法访问 Jellyfin，不查询或修改直链映射，不生成媒体直链跳转。
  保留现有请求转发规则、上游状态及适用响应头，客户端不收到正文；不能因为无正文
  把上游表示视频大小的 Content-Length 改成 0。
- Jellyfin 自身返回的重定向和错误仍正常透传，不在代理端跟随重定向，
  也不能把上游自身的 302 误认为直链命中。连接失败等沿用现有异常处理。
- GET 保留当前媒体源 ID 选择顺序、UUID 规范化、客户端绕过、映射命中 302、
  未命中流式回退及失效后恢复逻辑，不因新增日志而重复查询映射或修改播放地址。
- 保持现有认证、Range、流式响应和上游资源释放，不把完整视频缓冲到内存。
  不要求检查缓存内部 LRU 排列，只验证 HEAD 不查映射、GET 行为不被破坏。

### 日志底线

- 合法视频入口的 GET/HEAD 在通常的 INFO 日志配置下可看到处理结果，包括策略绕过。
  能区分直链跳转和 Jellyfin 透传，区分映射命中、未命中，以及 HEAD / 绕过时未查询。
- 记录真实响应状态，并沿用现有请求 ID 关联。同一请求的处理方式和状态不能互相矛盾；
  响应状态不等于已完整播放。尚未取得上游响应的失败不能伪装成上游成功或命中。
- 复用现有日志和异常处理，不强制事件名、字段名、枚举值、单条格式、固定条数、
  新增异常分类或指定请求上下文传递方案。异常不必另造一套视频日志机制。
- 新增或改动的日志不得泄露 API key、token、Authorization、Cookie 或签名 URL，
  也不能因脱敏改变真实请求或重定向地址。不记录完整媒体 URL 是优先的简单做法。

### 路由底线

- 仅上述两种路径的 GET/HEAD 使用视频特殊处理，其他方法普通透传。
- 完整匹配两种路径，不增加 `/emby` 等前缀、尾随斜杠或额外路径段。
  itemId 和 container 都是非空单一路径段，不增加数字 / UUID 或具体容器白名单。
- `Videos` 和 `stream` 大小写不敏感；不规定必须采用 ASCII 专用匹配或某个正则。
  container 不额外限制点号，例如 `stream.mp4.extra` 不因含点被单独排除；
  本 Slice 不负责判断该容器能否播放。
- 查询参数不能把其他路径变成视频入口。不合规路径继续普通代理到 Jellyfin，
  不是由代理直接拒绝；即使携带已命中的 MediaSourceId 也不能产生视频直链跳转。
  `/video/...`、`master.m3u8`、HLS 子路径、字幕和两个 danmu raw 入口均如此。

## 约束、不变量与非目标

- 沿用现有职责分层和客户端绕过优先级，PlaybackInfo 修改绕过与 Video 绕过保持独立。
  不恢复完整 PlaybackInfo JSON 缓存，不新增缓存机制、直链探测或配置开关。
- 仅使用 Jellyfin 返回的媒体信息，不读取 STRM、不运行 ffprobe、不访问 Jellyfin 数据库。
- 不新增日志平台、监控系统、验证框架或与三项目标无关的重构。
- 实施时同步适用 README、配置行为文档及 CHANGELOG；版本只由 `version.py` 定义。
  本次仅修订合同，不修改产品代码、版本，也不授权 push、发布或生产部署。
- 保留已有未跟踪 `artifacts/` 和用户文件，不随本次文档修订暂存或清理。

## 最终验收

| ID | 必需验收底线 |
| --- | --- |
| AC-1 | 两种合法路径的 HEAD 在已有直链映射时仍按 HEAD 回源，不查映射；状态和适用响应头保留、无正文，上游重定向 / 错误正常透传 |
| AC-2 | 合法 GET 的命中跳转、未命中 / 失效回退、恢复和客户端绕过保持；原 ID 选择与规范化继续通过已有相关回归 |
| AC-3 | HEAD、GET 命中 / 未命中和策略绕过的日志能说明真实处理、查询情况和状态，关联正确且新增 / 改动的输出无凭据泄漏 |
| AC-4 | 两种格式及关键词混合大小写正确匹配；其他路径即使有同 ID 映射也实际普通回源，其他方法和 PlaybackInfo 不被误处理 |
| AC-5 | 通过受影响测试和现有完整回归，保留流式、Range 与资源释放，不因本 Slice 改动产生相关退化 |

B 按真实修改范围发布四部分测试计划，使用已有测试和夹具覆盖以上结果，
不要求穷举状态码、方法、客户端和路径的所有组合，也不验证缓存内部排列。
最终候选保留 T4 的现有完整回归门槛：在仓库根运行 `.venv/bin/python -m pytest`
和 `git diff --check`；相同最终输入的有效证据可复用。

不再无条件要求另做网络流式、断连与后续 Range 的整套取证。若实际修改到底层代理、
响应头 / 正文处理或释放路径，B 针对受影响行为安排必要补测；仅改路由和复用既有代理
分支时，不为合同额外搭建测试工程。不得将假上游结果冒充真实 Jellyfin 或实机兼容。

B 独立审查完整任务差异及上述结果，保留真实命令、输入身份、退出码、原始证据和
未运行项，按[开发流程](../../docs/development-workflow.md#5-证据与审查)执行。
产品结果均满足后再交 A 最终审查，不以精简合同代替实际验证。

## Task 索引

B 按真实调用链将三项结果合并为一个可整体审查的 Task，不预设后续任务。

| Task | 范围与结果映射 | 当前状态 |
| --- | --- | --- |
| [S2.1 — 视频请求处理与日志](S2.1-video-request-handling-and-logging.md) | HEAD 透传、GET 保留、精确路由、结果日志及必要回归 / 文档；RO-1～3、AC-1～5 | PASS（实现 Head `a2f7d46`），独立 B 审查与 RO-1～3 重评完成 |

原修订 1 的 S2.1～S2.3 是未发布建议，已由上述实际计划替代。B 在 S2.1 独立 PASS 后
重评全部 RO：满足则整理 Closure Packet 交 A；有实际缺口才规划修正或下一必要 Task。
当前根 [TASK](../../TASK.md) 已撤下活动实施入口，保留 S2.1 PASS 记录链接；不追加 Task，
本 Slice 已由独立 A 最终审查 PASS / CLOSED，不追加实施；记录移入历史档案。

## 修订记录

- 修订 1：原规划提交 `de75a8b9dfd937442e632d899de3cc60e3ce0157`，
  首次激活提交 `a15355e1c6ae6e602d69a0dacfa0f3ff743b2f1b`；原文保留于 Git。
- 修订 2：用户明确要求“保留底线”，保留三项 RO、必要兼容 / 安全和完整回归；
  取消固定日志写法、LRU 内部顺序检查、穷举矩阵、无条件网络取证及固定 Task 拆分，
  撤除 container 点号限制与 ASCII 专用匹配要求。原 H / G / L / R 验收索引由 AC-1～5
  替代，修订 1 的被撤条款不再是实施或审查门槛。修订 2 时尚未实施，不存在被抹去的
  测试失败或独立审查结论。

## Closure Packet

2026-10-29 由独立 B 整理；不改变修订 2 的合同内容，不代签 A 最终决定。
以下保留 B 交接时的状态；A 最终核对与关闭决定见下一节。

- Slice Base：`3f997b53128305dd4e25b616b0794408ffefa859`。
- Implementation Head：`a2f7d46afc1339d3a3b91e57c7fa1db29749580f`。
- Task Base：`3e6554645dc096e5a2b517b2050c4f8aa21505b7`；唯一 Task
  [S2.1 计划、完成报告与独立 B 审查](S2.1-video-request-handling-and-logging.md#b-review-result)：PASS。
- 文档后继：`798a42ea340a6b5a33fcf134634a0fa004c07900`、
  `bf2266155a81e6fdafb6e12c964fef0c25c33204`，以及本轮 B 审查文档；未改变可执行输入。

| Required Outcome | B 重评 | 证据与交付 |
| --- | --- | --- |
| RO-1 HEAD 回源、GET 保留 | PASS | S2.1 AC-1 / AC-2；HEAD 不查映射、保留方法与表示头；B 经同一应用验证 GET 命中 → 失效回退 → 恢复、全局 / Video 绕过；既有 ID / UUID 回归通过 |
| RO-2 视频日志 | PASS | S2.1 AC-3；真实应用请求 ID 自动关联，HEAD / 命中 / 未命中 / 两类绕过 / 上游自身 302 日志含义正确，认证与媒体地址不泄漏、不改业务响应 |
| RO-3 精确入口 | PASS | S2.1 AC-4；仅两种 stream 格式的 GET/HEAD，关键词大小写不敏感、container 可含点；其他入口带有效映射仍普通回源，其他方法与 PlaybackInfo 保持 |

- 最终门槛 / AC-5：B 独立 `.venv/bin/python -m pytest -q` 为 291 passed、exit 0；
  独立应用入口复现 PASS（9 个 MockTransport 事务、4 个媒体流关闭、7 条关联结果）。
  底层 HTTP / 流式代理 / 缓存与策略未改，不恢复已撤除的额外网络取证门槛。
- 证据：`artifacts/validation-evidence/S2/S2.1/20261029-b-review/`，以及 Developer
  `artifacts/validation-evidence/S2/S2.1/20261029T001128-run1/`；仅本机可读、未跟踪未推送。
- 不变量：全局绕过优先、PlaybackInfo / Video 策略分工、GET ID 顺序与规范化、映射失效
  及恢复保持；不恢复正文缓存、不读取 STRM / ffprobe / 数据库、不新增依赖或配置。
  无 P0 / P1 阻塞，无延期产品结果。
- P2：交付目录未找到 Developer 首次夹具失败的原始日志，仅有失败摘要；B 已独立重跑
  关键入口和完整回归，不据此伪称复核过历史 traceback，不新建修复 Task。
- 兼容影响：旧 `/video`、master / HLS / 字幕等退出视频重定向是合同预期，说明已同步。
  新日志中的状态表示取得响应，不表示完成播放。
- 真实 Jellyfin / 实机客户端 / Uvicorn 网络 / 打包 / 生产部署 / 性能：NOT RUN。
  本地假上游不构成真实兼容结论；这些项目不是修订 2 的额外门槛。
- 文档与状态：Task PASS，根 TASK 无活动实施任务；Slice READY FOR A REVIEW，
  A Final Review PENDING。README / configuration / CHANGELOG Unreleased 已核对；
  `version.py` 保持 1.0.1，尚未发布。最终档案迁移由 A 收尾协调。

## A Final Review

```text
Reviewed Range: 3f997b53128305dd4e25b616b0794408ffefa859..a2f7d46afc1339d3a3b91e57c7fa1db29749580f
Document / evidence successors reviewed through: fcc8dddafc4c64ceebbd78b29a33c3d6d9a3785c
Reviewer / Independence: A — 本轮独立最终审查，未承担 S2 产品、测试或 B 探测实现
Decision: PASS
P0 / P1 Blockers: NONE
Closure Reconciliation: PASS — RO-1～3、AC-1～5，限修订 2 本地验收边界
Slice Status: PASS / CLOSED
Next Action: NONE — AUTHORIZED WORK COMPLETE
```

### 审查范围与用户结果（2026-10-29）

核对完整 Slice Base..Implementation Head 的全部 12 个变更路径，覆盖路由、Dispatcher、
VideoHandler、两份测试、用户文档、合同、Task 和根状态；未只检查最后一次提交。
同时核对 `798a42ea340a6b5a33fcf134634a0fa004c07900`、
`bf2266155a81e6fdafb6e12c964fef0c25c33204`、
`fcc8dddafc4c64ceebbd78b29a33c3d6d9a3785c` 的文档后继与 B 原始交接证据。
Slice Base、修订 2 合同、Task Base 和 Plan Checkpoint 均为实现 Head 的真实祖先；
本轮不移动 Base / Implementation Head，不修改合同结果、验收含义或产品输入。

| 用户结果 / 验收 | A 最终决定与依据 |
| --- | --- |
| RO-1 / AC-1 | PASS：合法 HEAD 在 ID / 映射查找前回源，保留原方法、非零表示长度及适用头，不生成媒体直链 302；既有应用级测试覆盖两种格式、混合大小写、上游自身 302 / 404、无正文与关闭。A 从 create_app 复跑已存在的 HEAD 入口，实际 HTTP 适配收到 HEAD，映射零查询，认证 / Range 原样保留。 |
| RO-1 / AC-2 | PASS：GET 的 ID 选择、UUID、映射与策略算法未变；A 经现有 PlaybackInfo → GET 验证命中、无效 Path 清除后的 206 回退、重新有效后恢复，以及全局 / Video 绕过。既有相关回归与 B 的独立完整回归支持其余保留行为。 |
| RO-2 / AC-3 | PASS：新增日志在取得真实响应后记录 redirect / proxy、hit / miss / not_queried 与状态，绕过分支已覆盖；A 复跑核对 7 条自动关联记录，上游自身 302 为 proxy / miss，合成认证值和媒体地址均未泄漏，真实 Location 未被改写。取得响应前的失败沿用既有异常路径，不伪造成功状态。 |
| RO-3 / AC-4 | PASS：完整匹配仅放行两种 stream 格式的 GET / HEAD，关键词大小写不敏感、非空单段 ID / container、container 可含点；其他方法及 PlaybackInfo 分流未受误处理。A 从已有 master.m3u8 请求入口确认带有效映射仍回源且不查映射；其他排除路径由候选应用级回归覆盖。 |
| AC-5 / 全部 RO | PASS：复用相同最终输入的 B 独立完整回归 291 passed / exit 0；Range、流式、资源关闭、认证、PlaybackInfo 及失效恢复的既有回归未削弱。底层代理 / HTTP / 缓存 / 策略未改，README、configuration 与 CHANGELOG Unreleased 已同步，不恢复修订 2 撤除的额外验证工程。 |

架构与不变量保持：routers 识别，handlers 适配与分流，policies / services 原算法不变，
infrastructure 继续负责上游与日志上下文；全局绕过优先、PlaybackInfo / Video 绕过独立。
不恢复完整 JSON 缓存，不新增依赖、配置、直链探测、STRM 读取、ffprobe 或数据库访问。
所有补充探测均从现有 create_app 的 PlaybackInfo / 视频路径进入，只以 MockTransport
隔离上游网络；未构造产品中不存在的入口或不可触发的内部组合。

### 验证与证据复用

本轮证据目录：`artifacts/validation-evidence/S2/20261029T004209-a-final-review/`；
`source-identity-and-results.json` 保存完整 SHA、逐文件输入摘要、cwd、Python / 依赖版本、
夹具、准确命令、退出码、墙钟耗时和复用依据，`entry-probe.txt` 为本轮原始输出。
证据仅本机未跟踪工作区可读，未暂存、未推送；仅克隆仓库不能取得，不冒称远端可复核。

- **PASS（A 本轮新运行）**：`PYTHONPATH=. .venv/bin/python artifacts/validation-evidence/S2/S2.1/20261029-b-review/entry_probe.py`，exit 0，进程墙钟 1.326 s；9 个假上游事务、4 个媒体流关闭、7 条正确关联结果。核对脚本 SHA-256 与 B 交接一致，未改旧证据。
- **PASS（复用，非 A 新跑完整回归）**：B 的 `.venv/bin/python -m pytest -q` 原始日志，291 passed / 1 warning，exit 0，pytest 7.37 s / 进程墙钟 8.286 s。A 已核对当前全部跟踪非 Markdown 输入与实现候选一致，Python 3.11.2 与 FastAPI 0.142.2 / Starlette 1.7.0 / httpx 0.28.1 / pytest 9.1.1 亦一致；文档后继不要求机械重跑相同完整套件。
- **PASS（原始证据核对）**：Developer 107 passed 聚焦与 291 passed 完整日志、B 独立入口日志 / 完整回归 / 输入清单与 Closure Packet；唯一警告为既有 TestClient 的 httpx 弃用提示，不扩大为产品缺陷。
- **PASS**：完整实现范围与本轮文档 `git diff --check`、本地链接 / 锚点、状态 / 归档入口和非文档输入一致性；收尾结果见本轮 `closure-checks.txt`。

### 非阻塞项、未运行项与关闭

P2 保留：Developer 首次 3 failed / 33 passed 的夹具失败只交付了文字摘要，未找到原始
traceback；不声称 A 已复核历史失败原因，也不事后补造日志。最终候选有 B 的独立完整
重跑与 A 的入口复跑，未发现产品或结果阻塞，不为此自动新建 Task。

真实 Jellyfin、实机客户端、Uvicorn 网络、打包、部署、性能均 **NOT RUN**；本轮只做隔离
本地验收。TestClient 会抑制 HEAD 正文，无正文断言不能冒充真实网络观察；同时核对了
实际 HEAD 转发、表示头和未改动的 HTTP 流式实现，遵循修订 2，不另造网络验收门槛。
上游自身 302 仍可透传；新增日志状态只代表取得响应，不代表已完整播放。

三项用户结果与全部必要验收满足，独立 B PASS 和 A 最终 PASS 均已记录。合同 / Task
移入 `Task/archive/`，根 TASK / SLICE 恢复无活动入口，更新历史索引；原 Base / Head、
修订、阶段性待审记录和未运行项保留，不以归档改写既往决定。
版本仍为 `version.py` 的 1.0.1，产品变更仍列 Unreleased。本轮仅审查 / 文档收尾与普通
本地检查点，不发布、push、部署或自动启动下一项，也不介入独立小版本 bug。

```text
Next Action: NONE — AUTHORIZED WORK COMPLETE
```
