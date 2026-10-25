# Slice S1 — 删除完整 JSON 缓存、按配置修改播放字段并验证既有能力

遵循[开发流程](../docs/development-workflow.md)和 [Slice 模板](SLICE_TEMPLATE.md)。
本轮用户明确要求按 Slice 规划，并增加真实 Jellyfin 12.3 验证；该要求优先于默认工作分类。
首轮目标为主动撤除功能；用户后续增加按配置修改播放字段，本合同同步纳入该新增能力，
保留原删除目标与真实服务验收，不改写历史 bug 范围。

```text
Slice ID: S1
Owner: A
Status: ACTIVE
Activated On: 2026-10-24
Contract Revision: 4 — functional acceptance; validation tools optional
Base SHA: 6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5
Contract Checkpoint: eb2775e53f5c26f7c6dd46294e62249e7bb8aa63
Implementation Head: NOT SET
Required Test Level: T4
Target Upstream: Jellyfin Server 12.3 (official v12.3)
Real Jellyfin Validation: PARTIAL — S1.4 RR-1 / RR-2 remain
Independent B Review: FIX REQUIRED — S1.4
A Final Review: PENDING
```

按用户本轮“激活 Slice”要求，本合同及规范性字段补充已激活；Base 保持固定。
Contract Checkpoint 已从 Git 解析，并由激活后的纯文档提交补记；该后继不移动 Base，不是实现候选。
首个 B Task [S1.1 — 真实 12.3 验证基线](S1.1-real-jellyfin-12.3-baseline.md)已由 Developer 实施并
交付工具与 J / B-on / B-off 基线；经 RR-1 / RR-2 补证及独立真实重放，当前为 B PASS，
详见该 Task 文末最终审查。S1.2 缓存撤除与 S1.3 字段配置的本地交付均已获独立 B PASS；
[S1.4 最终真实验证与交接](S1.4-candidate-real-validation-and-handoff.md)独立 B 审查为
FIX REQUIRED：保留已成立的字段 / 绕过 / 302 / 失效恢复及 amd64 构建证据，
补候选认证 / 未知 Item、直连取消与远程媒体停止（RR-1 / RR-2）。A 最终审查 PENDING。
激活前已有本会话的根 SLICE / TASK 修改、三份未跟踪方案文档及 `artifacts/`；
激活时只提交前五份合同相关文档，保留既有证据与用户文件。

## 用户目标

删除完整 PlaybackInfo JSON 缓存及其全部专属启用路径，使每次 PlaybackInfo 请求都向
Jellyfin 获取对应结果；其他现有代理、媒体策略、客户端绕过、直链映射、视频重定向、流式回退、
配置与日志能力按本合同保留。同时新增按 TOML 配置修改 PlaybackInfo 根字段和媒体源字段的能力，
未配置时不修改任何字段，显式配置时只修改列出的字段。原自动写入 Protocol=File、禁用转码的
默认行为按本轮用户要求取消；直链记录、302 和其他保留能力继续生效。
必须在真实 Jellyfin Server 12.3 上验证，不以单元或假上游结果代替。

字段配置、默认 / 空表语义、类型、执行顺序和 F-01～F-08 详见
[按字段配置修改合同补充](drafts/playback-info-field-overrides.md)，该补充是本合同规范性组成部分。

前期实现调查见[设计 v1](drafts/remove-playback-info-json-cache.md)。该文档保留为历史输入；
其中“不使用 Slice”“真实服务非验收项”“单 Task”的建议已由本合同替代。

## 当前基线与架构边界

以下为固定 Slice Base 的改前行为（不是当前实现）：`version.py` 为 0.9.3，
`PlaybackInfoCache` 按 Item ID 存原始上游 JSON，
默认 TTL 21600 秒、容量 4096；缓存键使不同用户、认证、设备、请求参数 / 请求体、方法及
两种 PlaybackInfo 前缀共享正文。缓存绕过与正文修改绕过相互独立。

`MediaSourceCache` 是另一套 `MediaSource.Id → Path` 内存映射，容量 4096、无 TTL，
负责 Video 302。`PlaybackService.modify()` 记录策略处理后的 Path；绕过正文修改时
`remember_media_sources()` 仍记录原 Path。有效→无效→有效 Path 的清理 / 恢复沿用 BUG-001。

主要修改面为缓存模块、PlaybackHandler、Dispatcher、ClientPolicy、main 装配、Settings、
配置示例、测试和适用文档。沿用现有职责划分，VideoHandler、ProxyHandler、路由、上游 HTTP、
MediaSourceCache 的内部容量 / LRU 机制预计无需调整。新增字段能力需要演进 PlaybackService、
MediaSourceService 相关字段规则及装配；取消原固定两项的默认修改，两字段集合默认都为空，
保留策略扩展点且应用无隐式修改规则。
具体文件边界由 B 根据实际基线核对。

### Jellyfin 12.3 的已知上游边界

2026-10-24 核对了官方 [12.3 发布页](https://github.com/jellyfin/jellyfin/releases/tag/v12.3)。
固定目标为真实官方 12.3 构建，不以其他版本或 `latest` 代替；实际运行时还须采集服务版本和
构建 / 镜像摘要，网页核对不能证明本机已运行该版本。

官方 [12.0 发布说明](https://github.com/jellyfin/jellyfin/releases/tag/v12.0)记载移除了
`/emby/*` / `/mediabrowser/*` 旧前缀，旧认证默认禁用。固定版本的
[MediaInfoController](https://github.com/jellyfin/jellyfin/blob/v12.3/Jellyfin.Api/Controllers/MediaInfoController.cs)
仍定义 GET / POST `/Items/{itemId}/PlaybackInfo`。

因此需分别验证“代理仍识别旧路由”和“12.3 上游是否提供旧接口”。本 Slice 不新增旧前缀重写、
不启用旧认证，不安装未授权插件来制造兼容结论。旧前缀透传得到上游错误时记录实际错误和基线；
不能写成旧客户端播放成功。正常 PlaybackInfo 后的 danmu raw 302 可使用真实媒体源 ID 验证，
即使上游本身没有该 raw 接口。

## Required Outcomes / Surfaces

| ID | 必须交付的结果 | 验收面与证据 |
|---|---|---|
| RO-1 | 完整响应缓存彻底撤除 | 无缓存模块 / 实例 / 键 / 读写 / 请求合并或替代响应缓存；同 Item 连续及并发 N 次请求产生 N 次真实上游调用；响应来自对应调用 |
| RO-2 | 请求转发和显式 PlaybackInfo 修改 | GET / POST 的方法、路径、查询、正文、认证独立转发；无配置保持上游字段，显式旧两项可恢复原规则；定制只允许配置声明的字段差异；绕过修改时正文与同次上游正文一致 |
| RO-3 | 客户端绕过行为保留 | 全局优先，PlaybackInfo 与 Video 独立；大小写不敏感的三类身份头匹配保留；绕过 PlaybackInfo 修改仍填充直链，Video 绕过仍流式代理 |
| RO-4 | 媒体源映射与 Video 能力保留 | 302、ID 查询优先级、Videos 路径 ID、UUID 格式、两种 danmu raw、容量 / LRU、单 ID 失效与恢复、其他 ID 不受影响均有证据 |
| RO-5 | 失败与媒体代理语义保留 | 本地媒体 / 映射未命中回退；Range / 206、响应头、流式与取消 / 关闭资源；错误 / 非 JSON / 缺媒体源的原处理不扩大或吞错 |
| RO-6 | 升级配置与诊断一致 | 删除四项缓存配置、缓存绕过策略、代理生成的 HIT/MISS 与 cache 日志字段；旧项忽略不生效，其余配置、请求 ID、版本头、日志清洗 / 脱敏 / 输出保持 |
| RO-7 | 真实 Jellyfin 12.3 功能保留验证完成 | 本文 RJ-01～RJ-12 全部取得对应真实证据；直连、Base 与候选对照，清晰区分缓存撤除的预期差异、既有上游限制和新增回归 |
| RO-8 | 可独立审查并完成版本交接 | 全套 pytest 与适用 T4 检查、更新 README / 配置示例 / AGENTS / CHANGELOG，version.py 单一版本来源；完整证据、独立 B 与 A 审查及 Closure Packet |
| RO-9 | 按配置修改播放字段 | 两个作用域缺省 / 空表均不改字段；仅显式配置生效；类型、覆盖优先级、绕过、直链一致性及并发隔离满足 F-01～F-08；未配置和显式配置分别完成真实播放闭环 |

## 约束、不变量与非目标

1. 保留完整 JSON 缓存撤除目标，不回滚整个 0.9.0；保留 SenPlayer raw 入口和其他独立能力。
   新增字段覆盖以 RO-9 为边界；用户授权取消旧两项自动修改，缺省不改字段，显式配置所列字段
   允许产生对应差异。不得把该默认变化误报为未授权回归或仍宣称默认沿用旧修改规则。
2. 删除 `playback_info_cache_enabled`、`playback_info_cache_ttl_seconds`、
   `playback_info_cache_max_entries`、`playback_cache_bypass_clients` 及对应大写环境变量读取。
   TOML 语法合法时这些旧键按未知键忽略；不再转换 / 校验旧值，不保留可重新开启功能的分支。
3. 每次均走原上游请求路径；成功 JSON 按原 `modify` 分支处理。非成功和解析失败按原规则返回；
   不清空全部直链、不增加旧正文回退或新错误转换。删除缓存会使以前被命中掩盖的上游错误显现。
4. 代理不再生成 `X-JellyfinProxy-Cache`；其他可透传头沿用原适配，不为此增加全局过滤。
5. 保持业务响应中的真实播放 URL；日志和交接证据中的 key、token、Cookie、签名 URL 脱敏。
6. 产品代理不打开 STRM、不运行 ffprobe、不操作 Jellyfin 数据库；测试工具可创建专属测试素材，
   Jellyfin 自行解析 / 探测。不得将测试夹具的文件操作移入代理业务。
7. 不调整直链映射认证隔离、容量或 LRU；字段覆盖后的映射必须与最终 Id / Path 一致，覆盖改变
   身份 / 地址时按补充合同清理相关旧映射。不修复既有 MediaResolver 畸形 URL 异常。
   发现的前置问题须记录，不能无说明扩张本 Slice 或弱化验收。
8. 真实验证优先使用隔离服务与小型专属媒体库；不从仓库示例地址或历史记录推导
   对生产 Jellyfin、真实用户媒体库、配置或部署的操作授权。
9. 不承诺降低 Jellyfin 探测次数；撤除后请求数 / 延迟可能增加。记录观测，不设无依据的性能结论。
10. 不把 HTTP 客户端模拟视为 Infuse / Kodi / SenPlayer 实机兼容；没有实机执行时分别记 NOT RUN。

## 真实 Jellyfin 12.3 验证合同

### 用户授权的验证范围修订（v4）

按用户“调整 Slice 和 Task 内部的不符合我直接需求的内容”的明确要求，由 B 同步本合同和
Task；这是用户直接授权的范围调整，不记作 A 审查或 A PASS。产品验收对象是缓存撤除、
按配置修改字段及既有代理功能保留；验证工具不是产品交付目标。

真实 Jellyfin 验证可用现有工具、人工操作或短小 HTTP 客户端完成。不强制新建 / 修复
CLI、观测代理、版本锁重建、机器报告校验器或工具测试框架。工具失败只有在使所依赖的
功能证据无效且无替代证据时，才影响该功能项；不得据此阻塞其他已成立的结果。
不能用删掉工具门槛代替补足缺失的真实功能证据，也不能因此直接签发 PASS。

只从现有产品入口、受支持的 Jellyfin API 和实际可触发的使用场景验证；不构造不存在的
入口或扩展无关畸形输入。每轮先核对已有交付，仅补缺口及变更影响项；测试累计时间必须
小于该轮总用时的 50%，不得为凑比例空等。预算内不能完成的部分如实交接。

### 环境与输入身份

- 使用官方 12.3 的实际服务器进程 / 容器，记录运行版本、构建或镜像摘要及影响结论的
  配置 / 插件信息；禁止版本不匹配后降级替代。无需特定锁文件或自动化重建入口；
  新实例的 server / Item ID 可以变化，只需记录与素材的对应关系。
- 优先复用已授权的隔离测试环境；需要新建时使用临时配置和数据目录、测试账号、
  受限网络监听及独立代理端口，不挂载生产数据目录。
  媒体夹具至少包含可播放的本地短视频、指向受控 HTTP(S) 媒体服务的 STRM、第二个独立媒体源，
  以及可通过测试库刷新呈现有效→本地 / 无效→有效 Path 的同一媒体源。记录素材身份、ID 和刷新步骤。
- 同一 ID 转换必须通过 Jellyfin 支持的测试库操作形成真实响应，不能直接改 Jellyfin 数据库，
  也不能用手工构造 JSON 冒充真实返回。如果特定转换无法产生，保存现象与输入，保持对应必需项
  BLOCKED，不能只用单元覆盖就宣称真实转换已通过。
- 使用至少两个测试用户 / token 和两个设备身份、不同 DeviceProfile / 请求正文，采用 12.3
  默认支持的认证方式。凭据仅经进程环境 / 测试私有输入传入，不提交到仓库或打印到日志。
- 运行前完成真实服务就绪、版本核实、素材可播放与端点能力探测；缺少真实依赖时说明原因，
  必需项用 BLOCKED / NOT RUN 保留，不能自动 skip 后关闭 Slice。

### 对照方法

对同一构建和对应素材核对以下四组；复用输入一致且已核实的证据，仅补缺口。
各场景明确冷 / 热缓存、映射是否种入；需要清空时重启代理，不要求每项机械重建环境。

| 对照组 | 用途 |
|---|---|
| J：直连 Jellyfin 12.3 | 确认真实上游状态、接口支持、媒体数据与媒体字节 |
| B-on：固定 Slice Base，原默认缓存开启 | 留下改动前用户可见行为，识别缓存命中、旧响应与被掩盖的错误 |
| B-off：同一 Base，仅在隔离配置关闭 JSON 缓存 | 比较应保持不变的回源处理、媒体策略、绕过和 Video 行为 |
| C：最终 Implementation Head | 不含已删除配置依赖，执行相同输入，证明预期撤除和其他能力保留 |

B-off 是已有功能的对照配置，不是给候选保留缓存开关。C 分未配置 / 空表、显式配置旧两项和其他
定制字段三类输入。未配置 / 空表的全部 JSON 字段须与同次上游一致；相对 B-off 的预期差异包括
不再强制 Protocol=File / SupportsTranscoding=false，以及缓存撤除、专属配置 / 诊断撤除和版本更新。
显式配置旧两项时，用于对照 B-off 证明原字段修改效果仍可获得；其他定制配置只允许配置表列出的
字段变化及最终 Id / Path 对直链的相应影响。会话 ID、时间等上游动态字段
按明确白名单记录并验证来源，不能用“动态字段”掩盖认证、流地址、策略或响应状态差异。

如使用旁路观测工具，所依赖的记录必须来自真实 12.3，不能把工具合成正文或故障当作产品结果；
也可通过服务日志、受控媒体源及直接 HTTP 请求取证。媒体数据保持流式，观测不完整积累媒体。
绕过正文的字节一致性对比同一次上游事务，
不以另发一次可能产生新 PlaySessionId 的直连请求作字节相等断言。

旧 `/emby/Items/...` 可能在 B-on 命中无前缀请求的 JSON 缓存而返回成功，但 J / B-off / C
收到上游错误；这应明确归因于撤除跨前缀缓存复用。不可新增路由改写来隐藏差异，也不能宣称
12.3 恢复了旧前缀支持。

### 必需验证矩阵

| ID | 场景 | 真实验证与保留判据 | 对应 RO |
|---|---|---|---|
| RJ-01 | 版本与基础透明代理 | 确认运行官方 12.3；经代理获取公共信息、测试账号的媒体列表和可用元数据 / 图片；状态、内容与约定头适配符合 J / B-off | RO-2、5、7 |
| RJ-02 | 连续 / 并发 PlaybackInfo | 同一 Item、GET / POST、不同用户 / token / 设备 / 正文执行；C 每次均真实回源，核对请求及会话字段来源，无代理生成的缓存头 | RO-1、2、7 |
| RJ-03 | 缺省 / 显式字段与非目标字段 | 使用实际 HTTP(S) MediaSources；未配置 / 空表的全部字段与同次上游一致；显式配置旧两项恢复原效果；单字段 / 其他定制验证仅改列出字段、补字段与原类型 | RO-2、7、9 |
| RJ-04 | 三类客户端绕过矩阵 | 普通、仅 PlaybackInfo 绕过、仅 Video 绕过、全局绕过及重叠；三类身份头、大小写匹配；默认 / 定制两套字段配置下绕过均保持原文、填充直链和独立 Video 行为 | RO-3、7、9 |
| RJ-05 | 远程直链与 ID 兼容 | 真实 PlaybackInfo 建立映射；两种查询参数及冲突优先级、无参数路径 ID、UUID 两种格式、大小写 Videos、两种 raw 均验证 302；跟随到受控源实际读取有限媒体字节 | RO-4、7 |
| RJ-06 | 直链更新、精确失效与恢复 | 在同一代理实例依次取得同一 ID 的真实有效→无效→有效 Path，验证旧 302→真实上游回退→新 302；第二 ID 不受影响；每步保留 Jellyfin 原始响应的脱敏证据 | RO-4、5、7 |
| RJ-07 | 本地媒体 / 映射未命中 / Video 绕过 | 对真正支持的媒体端点请求 Range，比较 J / B-off / C 的 206、Content-Range、Content-Length、字节摘要及无意外 Location；验证 HTTP 层可读取媒体 | RO-3、5、7 |
| RJ-08 | 播放与流式资源生命周期 | 对实际媒体开始读取、跳转 Range、停止 / 断开；观测分块到达、上游释放及后续请求正常，结合资源关闭回归；不能完整缓冲视频后再宣称流式通过 | RO-5、7 |
| RJ-09 | 真实认证 / 不存在资源与故障恢复 | 成功请求后再用无效凭据 / 未知 Item，请求确实到 12.3 并保留实际错误；仅在隔离服务中制造短时不可达并恢复，验证没有旧 JSON 成功回退且服务恢复后可继续请求 | RO-1、5、7 |
| RJ-10 | 旧前缀与 raw 未命中边界 | 采集 J 的旧前缀与无插件 raw 实际状态，与 B-off / C 比较；302 命中另由 RJ-05 证明；此项通过只代表识别 / 透传保持，不代表上游提供了接口 | RO-2、4、5、7 |
| RJ-11 | 配置、日志、请求 ID 和版本 | 在 C 使用新配置及遗留缓存键 / 环境变量启动，请求结果均不启用缓存；缺省 / 空表无隐式字段修改，显式表及启动校验正确；默认配置样例不启用修改；原三类绕过、请求 ID、版本头及日志脱敏可核查 | RO-6、7、9 |
| RJ-12 | 综合播放闭环与差异核对 | 远程和本地各执行 PlaybackInfo→媒体访问→Range 跳转→停止→再次请求；默认 / 定制字段配置分别核验播放与映射一致性；逐项列 B-on / B-off / C 差异，仅有合同允许差异 | RO-1～7、9 |

新字段配置的 F-01～F-08 加入现有 RJ 场景和本地测试，不通过改名减少原 12 组真实验证覆盖。
原始非 JSON、可控 5xx、无法由真实服务稳定产生的畸形输入、LRU 容量等仍由单元 / 假上游
作确定性覆盖，结果单列，不能冒充真实 Jellyfin 场景。真实服务输入确实产生这些结果时可追加证据。

真实客户端的“开始 / 拖动 / 停止”可作为额外实机记录，但 RJ-08 / RJ-12 的 HTTP 媒体闭环
不因此升级成所有真实客户端兼容认证；实机缺失不改变必需真实服务器矩阵。

### 执行步骤与证据

1. 在 S1.1 中完成依赖检查、官方构建固定、隔离服务初始化、素材与账号准备，保存 J、B-on、
   B-off 的预期结果和输入清单；不要等删完缓存才补造改动前基线。
2. 仅通过支持的 API / 测试库流程刷新素材；测试工具使用独立账号 / 数据，Jellyfin 自身承担探测。
3. 记录实际采用的准备、请求和停止步骤即可；现有验证脚本可选，已知限制见 S1.1。
   不要求先修复工具、重建自动化环境或补齐机器校验报告才能继续功能验证。
4. S1.2 / S1.3 完成缓存撤除、字段配置实现与本地回归后，S1.4 在同一固定服务和相同夹具输入上执行
   C 的未配置 / 空表、显式旧两项及其他定制配置；各场景明确所需代理状态，
   RJ-06 内部保留同一实例。不得沿用 Base 进程中的内存映射当作候选结果。
5. 按场景保留足以证明结论的调用计数、状态 / 响应头、脱敏字段对照或原文摘要、
   有限媒体读取和断连 / 恢复记录；关联实际构建、配置、素材与命令，保留失败及重跑。
6. 独立 B 复现每次回源、字段覆盖优先级 / 空表 / 启动校验、绕过原文与直链、失效 / 恢复、
   真实 Range 和旧前缀边界；审查其余原始证据。
7. 最终候选可执行输入变化后重跑受影响真实场景与 T4 全套回归；若候选仍有产品变更，不能仅复用
   更早候选的真实验证。纯文档后继可在输入相同的条件下复用并说明依据。

建议证据根为 `artifacts/validation-evidence/S1/<run-id>/`，按开发流程记录源码、输入身份、
命令、结果及原始产物；不强制特定目录结构、JSON schema、机器校验器或逐文件工具摘要。
对每个 RJ 标记 PASS / FAIL / NOT RUN / BLOCKED / SKIPPED 及原因；必须提供可供审查者访问的
交接副本，不能只写临时目录。认证值脱敏，原始明文凭据不进入交接包。

## 最终验收

### 开发 / 修正反馈

由 B 在各 Task 中按实际变更确定聚焦用例；现有起点为：

```bash
.venv/bin/python -m pytest tests/test_core.py tests/test_config.py tests/test_logging.py
```

替换只为缓存命中服务的断言 / 维度；保留 BUG-001 的清理、回退和恢复业务断言，不能通过
删除保留能力测试或弱化断言获得通过。

### 最终候选门槛

```bash
.venv/bin/python -m pytest
git diff --check
```

同时必须满足 RO-1～9、F-01～08、RJ-01～12 和真实构建身份核验。假上游、真实 Jellyfin、真实客户端、
性能与打包结果分别报告。没有真实 12.3 或任一必需项仍 FAIL / BLOCKED / NOT RUN / SKIPPED，
不得将 RO-7 或 Slice 标为 PASS；只能继续解决或由 A 如实处理范围变更。

### B 独立验证与最终审查

B 核对完整 Task 范围、真实输入和原始证据，并独立复现前述关键场景。每次 Task PASS 后重评
全部 RO。全部 Task 独立 B PASS 后整理 Closure Packet，交未承担本范围产品实施的 A 最终审查。
合同激活不自动创建多个代理；没有独立审查时保持 PENDING，不把实施自检写成独立结论。

### 证据与适用边界

最终报告明确性能观测、真实客户端和打包的覆盖范围，不夸大为全设备兼容认证。若改动二进制 /
部署包配置，按[发布说明](../docs/releasing.md)追加适用构建验证。未知的环境问题和既有上游
限制保留在对照表；新增回归必须修复，不以“上游差异”为由豁免。

## Task 索引

以下交付顺序由 A 建议；S1.1 已由 B 发布完整计划，其余仍为建议单元。精确 AC、命令、
Task Base 与拆分由 B 依据已激活合同与实际结果逐步制定，不提前制造后继 Head。

| 建议单元 | 完整交付闭环 | 依赖 / 结果映射 | 当前状态 |
|---|---|---|---|
| [S1.1 — 真实 12.3 验证基线](S1.1-real-jellyfin-12.3-baseline.md) | 核实真实构建与隔离素材，取得 J、B-on、B-off 功能基线和可复核步骤，明确旧路由限制；工具可选 | 首个 Task；支撑 RO-1～8 的基线，准备 RO-9 对照 | 独立 B PASS；RR-1 / RR-2 补证及独立真实重放完成；C 对照 NOT RUN |
| [S1.2 — 缓存撤除与保留能力回归](S1.2-remove-playback-info-cache.md) | 原子完成 JSON 缓存撤除、旧配置 / 诊断清理和对应本地回归 | 依赖 S1.1；RO-1～6 | 独立 B PASS；本地 AC-1～8 成立，真实 C 待 S1.4 |
| [S1.3 — 字段配置与策略闭环](S1.3-playback-info-field-configuration.md) | 完成两个作用域、默认 / 空表、类型校验、绕过、直链一致性和本地验收；最终版本 / 文档交接归 S1.4 | 依赖 S1.2；RO-2～6、8、9；F-01～07 本地，F-08 归 S1.4 | 独立 B PASS；AC-1～9 本地成立，F-08 NOT RUN |
| [S1.4 — 候选真实验证与交接](S1.4-candidate-real-validation-and-handoff.md) | 默认 / 定制配置执行全部 RJ、F-08、对照差异、适用构建、必要修正与重跑、独立 B 审查及最终 RO 核对 | 依赖 S1.3；RO-1～9 | 独立 B FIX REQUIRED；只补 RR-1 / RR-2，保留有效结果及构建 / 回归 |

## Closure Packet

- Base：`6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5`；Implementation Head：NOT SET。
- Contract Checkpoint：`eb2775e53f5c26f7c6dd46294e62249e7bb8aa63`；
  [S1.1 计划](S1.1-real-jellyfin-12.3-baseline.md)的 Plan Checkpoint 为 `eac3245`；
  S1.1 已审实现 Head 为 `56d76339f2c3fae7cd2ef550cddedc0d9fb73aa5`，产品未变；
  原工具 Head 为 `cfc790e22dc56c2016e09fd49b8e4189ce00a027`。最新独立 B 决定 PASS，
  RR-1 / RR-2 与 V3 / V4 已核实并独立真实重放。
- S1.2 独立 B PASS，实施 Head `74992bbd004a53c0522bb49e5c0229131b00ec88`；S1.3 独立 B PASS，
  实施 Head `a0cc7cddff32da585923c5ff11d3977ea910d87a`，文档后继 `e903fa9`。
  S1.3 B 证据：`artifacts/validation-evidence/S1/s1-3-b-review-20261025-01/`，
  41 项独立聚焦、五组 HTTP 假上游闭环通过，复用相同候选全量 213 passed。
  S1.4 已由 Developer 交审：Plan Checkpoint `d47a91e`，产品候选仍为 `a0cc7cd`（无需变更），
  真实验证证据 `artifacts/validation-evidence/S1/s1-4-candidate-20261025-01/`；
  B 已审至文档检查点 `6b5c825318093ac1f58cd64a854ce944cdd0c8fe`，结论 FIX REQUIRED；
  B 证据 `artifacts/validation-evidence/S1/s1-4-b-review-20261025-01/`。
  A 最终审查 PENDING，最终 Implementation Head 仍 NOT SET。
- 最新全部 RO 重评见 S1.4 B 审查：RO-1～4 / 6 的已交付结果保留；RO-5 / 7 / 8 / 9
  尚未完整满足。F-01～07 与 F-08 字段 / 绕过 / 302 部分成立，认证 / 未知资源、直连生命周期
  与默认 / 定制远程媒体停止须补 RR-1 / RR-2。`amd64` 构建与 213 项回归复用，
  B 独立字段 / 配置 41 passed。局部结果不构成完整真实矩阵或 Slice PASS。
- 真实 Jellyfin 构建 / 素材 / 配置 / 测试工具身份与原始证据：见 S1.1 报告
  （`artifacts/validation-evidence/S1/s1-1-baseline-20261025-05/`），补证为
  `artifacts/validation-evidence/S1/s1-1-supplement-20261025-01/`；原 B 审查证据为
  `artifacts/validation-evidence/S1/s1-1-b-review-20261025-01/`，前轮重审为
  `artifacts/validation-evidence/S1/s1-1-b-rereview-20261025-01/`；最终独立复审 / 重放为
  `artifacts/validation-evidence/S1/s1-1-b-final-review-20261025-01/`，补证 02 保留，C 对照仍 NOT RUN。
- B-on / B-off / C 已观察差异符合缓存撤除与显式字段合同；不变量未发现产品违规，
  必需证据缺口见 RR-1 / RR-2。README 既有一行范围差异为非阻塞文档项，保留未暂存。
- README / AGENTS / CHANGELOG / 版本已核对；未发布 0.9.3 / Unreleased 不变。
  根状态已协调为 FIX REQUIRED / ACTIVE，完整 Closure Packet 待补证及 B PASS 后整理。
- 官方版本与接口说明查询：已完成，只作为规划依据，不是运行验证。

## 合同修订记录

- v1：按用户要求将完整 JSON 缓存撤除规划为 Slice，纳入真实 Jellyfin 12.3 的 12 组必需验证。
- v2：用户增加按配置修改播放字段；新增 RO-9 与 F-01～08、两个配置作用域，扩展 RJ-03 / 04 /
  11 / 12 和对照差异合同，将建议交付顺序调整为四个完整单元。当时建议缺省沿用旧两项，已由 v3 替代。
- v3：用户明确“未提供配置时默认不改”；两个字段集合缺省 / 空表均不修改，取消旧两项自动装配，
  显式配置才修改字段。同步 F-01 / 02 / 08、RJ-03 / 11、对照差异和默认配置示例要求。
  Base、原 JSON 缓存删除目标、直链及其他保留能力、12 组必需真实验证不变。
- 2026-10-24：用户明确要求激活 Slice；合同 v3 由 PLANNED 变为 ACTIVE，建立本地激活检查点。
  范围与验收不变，B Task 计划、产品实现、真实服务验证和独立审查仍待完成。
- 2026-10-25：按用户要求由 B 发布 S1.1 验证基线计划；仅同步状态与索引，合同范围、
  Base 和 Contract Checkpoint 不变。工具 / 产品实现、真实基线和独立审查未开始。
- 2026-10-25：S1.1 工具和基线交付后独立 B 审查为 FIX REQUIRED；174 项回归通过，
  文档锁定构建复现失败及既定真实验收缺口记录于 S1.1；RO-1～9 重评均未完成，合同不变。
- v4（2026-10-25）：按用户直接要求撤销工具建设 / 修复、自动重建和机器校验作为必交付门槛；
  允许人工 / 简短客户端验证，复用有效证据并仅补功能缺口。纠正首轮 B 将工具问题一并阻塞
  的范围；产品 RO、字段语义、真实 12.3 验证和独立审查保留。Base 与原检查点不移动，
  本次普通文档修订提交为 v4 的后继记录，不冒充新的产品实现或 A 审查。
- 2026-10-25：S1.1 补证独立 B 重审仍为 FIX REQUIRED；接受 V3 / V4 和 V2 已完成输入，
  仅余 V1 检查前重新种入、V2 全局 / 分支重叠及两个查询名冲突补证。全回归 179 passed；
  全部 RO 已重评，交付仍未完成。本条仅协调状态与证据索引，不改合同 v4 范围或验收。

- 2026-10-25：S1.1 完整 Base..Head 最终独立 B PASS；RR-1 / RR-2 经原始记录与独立真实
  12.3 重放通过，18/18 补证与 182 项回归通过。全部 RO 重评仍未完成；B 发布 S1.2
  缓存撤除计划，未开始产品实施。此条只更新索引 / 状态，不改变合同或签发 A 结论。

- 2026-10-25：S1.2 / S1.3 完整 Base..Head 独立 B PASS，缓存撤除及字段配置本地交付成立；
  全部 RO 重评后发布 S1.4 真实候选 / 版本交接计划。S1.3 未升版本，实际仍为未发布 0.9.3
  检查点 / Unreleased；未指定后继发行号，不伪造版本或发行。这里只协调建议拆分、事实状态和
  证据索引，不变更 RO / 字段语义或签发 A 结论。必需 C 矩阵和最终交接未完成。

- 2026-10-25：S1.4 Developer 交付。在新建隔离官方 12.3 实例上重取 J / B-on / B-off 82/82，
  完成候选 C 的 8 套配置 47/47 真实功能检查（RJ-01～12、F-08）、amd64 原生构建与冻结二进制
  smoke、完整 pytest 213 passed。产品候选未变（Implementation Head 仍为 a0cc7cd），未造实现提交。
  本条只记录实施交付与证据索引，不改变 RO / 字段语义，也不构成独立 B 或 A 结论；
  真客户端与 arm64 仍 NOT RUN，版本仍为未发布 0.9.3 检查点。

- 2026-10-25：S1.4 独立 B 审至文档检查点 `6b5c825`，决定 FIX REQUIRED。
  上条“47/47 / F-08”属于 Developer 交付陈述，不能作为最终结论；候选认证 / 未知 Item
  未执行，取消仍经观测器，三套配置远程停止均只读到 302 / 0 字节。仅在原 S1.4 补
  RR-1 / RR-2，保留其他有效结果与原始证据；全部 RO 已重评，合同范围不变。

## A Final Review

```text
Reviewed Range: NOT SET
Reviewer / Independence: NOT SET
Decision: PENDING
P0 / P1 Blockers: B reports S1.4 RR-1 / RR-2; A assessment remains PENDING
Closure Reconciliation: PENDING
Next Action: PENDING — AFTER S1.4 RR-1 / RR-2 AND INDEPENDENT B PASS
```

当前 S1.1 基线及 S1.2 / S1.3 本地交付均获独立 B PASS；缓存撤除和字段配置已经实现，
S1.4 候选 C 的真实 12.3 证据已审为 FIX REQUIRED，RR-1 / RR-2 补证前不宣称矩阵 / F-08 完整通过；
amd64 构建及已成立结果保留，
版本仍为未发布 0.9.3 检查点，未 push / 发布。
只有满足上述门槛并获独立 B PASS 与独立 A 最终 PASS 才能关闭 Slice；
Developer 交付不能替代独立审查，真客户端与 arm64 仍 NOT RUN。

```text
Next Action: Developer supplements S1.4 RR-1 / RR-2; A final review follows only after independent B PASS
```
