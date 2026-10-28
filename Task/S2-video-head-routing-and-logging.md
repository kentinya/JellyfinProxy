# Slice S2 — 视频 HEAD 透传、GET/HEAD 处理日志与精确路由

遵循[开发流程](../docs/development-workflow.md)和 [Slice 模板](SLICE_TEMPLATE.md)。
本合同按用户“保留底线”的要求精简：保留三项产品结果、必要兼容与日志安全，
不把日志写法、缓存内部结构或额外测试工程作为交付目标。

```text
Slice ID: S2
Owner: A
Status: ACTIVE
Planned On: 2026-10-28
Activated On: 2026-10-28
Contract Revision: 2 — retain essential outcomes and acceptance
Revised On: 2026-10-28
Base SHA: 3f997b53128305dd4e25b616b0794408ffefa859
Contract Checkpoint: 88b5c25e40b2c4ee1139ed4458cc303e949666cb
Implementation Head: NOT SET
Required Test Level: T4 — related tests and existing full regression; additional checks by actual impact
Independent B Review: PENDING
A Final Review: PENDING
```

Base 保持规划时的真实源码，产品版本仍为 `1.0.1`，纯文档修订不使 Base 前移。
首个 [S2.1 计划](S2.1-video-request-handling-and-logging.md)已于 2026-10-28
激活为 IN PROGRESS；本轮仅更新状态，尚无产品代码改动。
Contract Checkpoint 已从 Git 解析，并由纯文档后继补记；
后续 B 计划以本修订为准，不以最初激活提交代替当前合同。

## 用户目标

1. 视频 HEAD 请求透传 Jellyfin；GET 保持现有直链与回退逻辑。
2. 增加 GET/HEAD 视频请求日志，能看出处理方式、映射命中情况和响应状态。
3. 视频特殊处理精确限制为 `/Videos/{itemId}/stream` 和
   `/Videos/{itemId}/stream.{container}`，`Videos`、`stream` 不区分大小写。

用户示例中的 `abc` 是可变 itemId 的示例，不是固定字面量。

## 当前基线与架构边界

- [路由表](../routers/route_config.py) 当前会匹配任意 `/Videos/{id}/...`、
  `/videos/{id}/...` 和 `/video/...`，需要收紧到上述两种格式。
- [VideoHandler](../handlers/video_handler.py) 当前不区分方法，命中映射就返回 302；
  HEAD 应直接交给现有[普通代理](../handlers/proxy_handler.py)，GET 沿用现有算法。
- [Dispatcher](../handlers/dispatcher.py) 会提前处理客户端绕过，新增日志不能漏掉该分支。
  业务判断留在现有路由、策略和处理器，日志基础设施只负责输出与上下文。
- 复用现有[核心测试](../tests/test_core.py)、[日志测试](../tests/test_logging.py)和
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
未运行项，按[开发流程](../docs/development-workflow.md#5-证据与审查)执行。
产品结果均满足后再交 A 最终审查，不以精简合同代替实际验证。

## Task 索引

B 按真实调用链将三项结果合并为一个可整体审查的 Task，不预设后续任务。

| Task | 范围与结果映射 | 当前状态 |
| --- | --- | --- |
| [S2.1 — 视频请求处理与日志](S2.1-video-request-handling-and-logging.md) | HEAD 透传、GET 保留、精确路由、结果日志及必要回归 / 文档；RO-1～3、AC-1～5 | IN PROGRESS，独立 B 决定 PENDING |

原修订 1 的 S2.1～S2.3 是未发布建议，已由上述实际计划替代。B 在 S2.1 独立 PASS 后
重评全部 RO：满足则整理 Closure Packet 交 A；有实际缺口才规划修正或下一必要 Task。
当前根 [TASK](../TASK.md) 指向已激活的 S2.1；本轮仅记录激活与计划检查点，不修改产品代码。

## 修订记录

- 修订 1：原规划提交 `de75a8b9dfd937442e632d899de3cc60e3ce0157`，
  首次激活提交 `a15355e1c6ae6e602d69a0dacfa0f3ff743b2f1b`；原文保留于 Git。
- 修订 2：用户明确要求“保留底线”，保留三项 RO、必要兼容 / 安全和完整回归；
  取消固定日志写法、LRU 内部顺序检查、穷举矩阵、无条件网络取证及固定 Task 拆分，
  撤除 container 点号限制与 ASCII 专用匹配要求。原 H / G / L / R 验收索引由 AC-1～5
  替代，修订 1 的被撤条款不再是实施或审查门槛。当前尚未实施，不存在被抹去的测试失败
  或独立审查结论。

## Closure Packet

- Base：`3f997b53128305dd4e25b616b0794408ffefa859`；Implementation Head：NOT SET。
- 全部 RO 对照与独立 B 决定：PENDING；最终产品验证与证据：NOT RUN / NOT SET。
- 不变量 / P2 / 延期：待实施与独立审查；无已确认的延期结果。
- 真实 Jellyfin / 实机客户端 / 打包 / 生产部署：NOT RUN，本次不新增此类操作要求。
- 文档与状态协调：修订 2，ACTIVE；当前 Task S2.1 为 IN PROGRESS；最终交付协调 PENDING。

## A Final Review

```text
Reviewed Range: NOT SET
Reviewer / Independence: NOT SET
Decision: PENDING
P0 / P1 Blockers: NOT SET
Closure Reconciliation: PENDING
Next Action: NONE — AUTHORIZED WORK COMPLETE
```

本轮 Task 激活授权已完成，不表示产品已实现或验收；后续由 Developer 按 S2.1 计划实施。
