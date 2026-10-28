# 配置与播放行为

[← 返回首页](../README.md)

[基础配置](#基础配置) · [客户端绕过](#客户端绕过) · [字段覆盖](#playbackinfo-字段覆盖) ·
[直链与回退](#直链与回退) · [日志](#日志) · [未发布变更](#未发布变更) ·
[1.0.1 升级](#从-100-升级到-101) · [0.9.x 升级](#从-09x-升级) · [常见问题](#常见问题)

## 基础配置

推荐编辑 [JellyfinProxy.toml](../JellyfinProxy.toml)，也可以通过 `--config` 指定文件。
不指定时，源码运行读取项目目录下的同名文件，独立二进制读取可执行文件旁的同名文件。

对应的环境变量优先于 TOML 配置。变量示例见 [.env.example](../.env.example)；程序不会自动
读取 `.env` 文件，需要由 shell、容器或服务管理器注入环境变量。所有配置在启动时读取，
修改后需要重启。

| TOML 配置 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `jellyfin_url` | `JELLYFIN_URL` | `http://127.0.0.1:8096` | 代理主机可访问的 Jellyfin 地址 |
| `listen_host` | `LISTEN_HOST` | `0.0.0.0` | 代理监听地址 |
| `listen_port` | `LISTEN_PORT` | `8097` | 代理监听端口 |
| `bypass_clients` | `BYPASS_CLIENTS` | `["Infuse", "Kodi"]` | 同时绕过播放信息修改与视频重定向 |
| `playback_bypass_clients` | `PLAYBACK_BYPASS_CLIENTS` | `[]` | 只绕过播放信息修改 |
| `video_bypass_clients` | `VIDEO_BYPASS_CLIENTS` | `[]` | 只绕过视频重定向 |
| `request_timeout_seconds` | `REQUEST_TIMEOUT_SECONDS` | `60` | 上游请求超时，单位秒 |
| `debug` | `DEBUG` | `false` | FastAPI 调试模式 |
| `log_level` | `LOG_LEVEL` | `INFO` | 日志级别 |
| `log_file` | `LOG_FILE` | `JellyfinProxy.log` | 应用日志路径，空字符串关闭文件输出 |
| `access_log_file` | `ACCESS_LOG_FILE` | `access.log` | 访问日志路径，空字符串关闭访问日志文件 |

TOML 客户端列表使用字符串数组，环境变量使用英文逗号分隔，例如：

```bash
export BYPASS_CLIENTS="Infuse,Kodi"
export PLAYBACK_BYPASS_CLIENTS="Client B"
export VIDEO_BYPASS_CLIENTS="Client A"
```

日志文件的相对路径以配置文件所在目录为基准。仓库的 Compose 配置通过环境变量关闭
两种日志文件：应用日志仍输出到标准输出，访问日志文件不再写入。

## 客户端绕过

程序在以下请求头中进行**不区分大小写的子字符串匹配**：

- `User-Agent`
- `X-Emby-Client`
- `X-Emby-Device-Name`

`bypass_clients` 优先级最高，命中后同时绕过播放信息修改和视频重定向。
另外两个列表独立生效，可组合使用：

```toml
bypass_clients = ["Client D"]
playback_bypass_clients = ["Client B"]
video_bypass_clients = ["Client A"]
```

| 客户端 | 应用已配置的 PlaybackInfo 字段覆盖 | 允许 Video 直链重定向 |
| --- | --- | --- |
| Client A | 是 | 否 |
| Client B | 否 | 是 |
| Client C（不在任何列表中） | 是 | 是 |
| Client D | 否 | 否 |

表中的“是”表示允许执行对应处理；未配置字段时不会覆盖字段，没有直链时不会重定向。

**PlaybackInfo 绕过不等于禁用直链。** 绕过时响应正文保持上游原始字节，同时仍记录有效的
媒体源地址。若还需要禁止该客户端直连，请使用 `video_bypass_clients` 或 `bypass_clients`。

## PlaybackInfo 字段覆盖

默认不覆盖字段，保留 Jellyfin 返回的字段值。两个可选表分别作用于响应根对象与远程媒体源：

```toml
[playback_info.response_fields]
ServerName = "Home Jellyfin"

[playback_info.media_source_fields]
Protocol = "File"
SupportsTranscoding = false
SupportsDirectPlay = true
```

**将这些表放在所有根配置之后。** TOML 表声明后继续写的字段属于该表；例如把
`listen_port` 写在 `[playback_info.media_source_fields]` 下，会将它当作媒体源覆盖字段。
示例配置已有这两个空表，请编辑原表，避免重复声明。

### 作用范围

| 配置表 | 覆盖范围 |
| --- | --- |
| `playback_info.response_fields` | PlaybackInfo 响应根对象的直接字段，不能覆盖 `MediaSources` 容器 |
| `playback_info.media_source_fields` | `MediaSources` 中每个 Path 为可用 HTTP(S) 地址的媒体源直接字段 |

- 表缺省或留空时不覆盖任何字段。只处理显式列出的字段：已有字段替换，缺少字段补入。
- 字段名区分大小写，与 Jellyfin JSON 一致；不支持点路径、数组下标或模板。
- `MediaStreams` 等嵌套对象不能按路径修改；数组和对象只能整体替换，不做深层合并。
- 媒体源 Path 是本地路径、缺失或无效地址时，不对该媒体源应用字段覆盖。
- 覆盖后的最终 `Id` / `Path` 用于视频直链映射；改变 `Id` 会清理旧 ID 的直链，其他 ID 不受影响。
- 这两个表只支持 TOML，没有对应环境变量，也不支持热更新。

### 值与校验

值保留 TOML 的原类型：字符串、布尔、整数、有限小数、数组和对象。
请按 Jellyfin JSON 的字段类型填写，例如布尔值使用 `false`，不要写成 `"false"`。

`NaN` / `Infinity`、TOML 日期和时间、空字段名、非表的 `playback_info` 等非法配置会在
启动时报错。字段配置校验错误只包含位置和类型，不打印配置值。

字段覆盖只修改响应内容，不会让 Jellyfin 或客户端获得原本不支持的播放或转码能力。

## 直链与回退

### 一次播放如何处理

1. 客户端通过代理请求 PlaybackInfo，每次请求都会转发到 Jellyfin。
2. 代理从响应中记录有效的 `MediaSource.Id → Path`；按客户端策略决定是否应用字段覆盖。
3. 后续视频 `GET` 请求找到对应直链且未命中 Video 绕过策略时，返回 `302`，由客户端访问媒体地址。
4. `HEAD` 视频请求始终按原方法透传 Jellyfin，不查询直链。视频 `GET` 没有直链或选择
   绕过时，透明代理到 Jellyfin；不合规路径同样普通代理。

媒体响应采用异步流式传输，不会把完整视频加载到内存；保留 Range、Content-Range、
Content-Length、Content-Encoding 等媒体响应语义。

### 支持的请求入口

| 入口 | 处理方式 |
| --- | --- |
| `GET` / `POST` `/Items/{id}/PlaybackInfo` | 获取播放信息、记录直链、按配置覆盖字段 |
| `GET` / `POST` `/emby/Items/{id}/PlaybackInfo` | 同上 |
| `GET` `/Videos/{id}/stream`、`GET` `/Videos/{id}/stream.{container}` | 优先按媒体源 ID 查找直链，未命中则代理 |
| `HEAD` 上述两种 stream 路径 | 按 HEAD 透传 Jellyfin，不查询直链 |
| `/emby/api/danmu/{id}/raw`、`/api/danmu/{id}/raw` | 普通代理到 Jellyfin，不使用视频直链映射 |

视频特殊处理只覆盖上表两种 stream 路径的 `GET` / `HEAD`，`Videos` 与 `stream`
不区分大小写。`{id}` 和 `{container}` 都必须是非空单一路径段；`stream.mp4.extra`
这类带多个点的 container 也属于合法入口，本代理不判断该容器能否播放。

`/Videos/{id}/...` 的其他子路径（例如 `master.m3u8`、HLS、字幕）、旧的 `/video/...`、
前缀、尾随斜杠和额外路径段均按普通代理转发，不查直链。即使这些路径携带已命中的
`MediaSourceId`，也不会返回视频 `302`。

视频 `GET` 请求优先使用非空的 `MediaSourceId`，其次为 `mediaSourceId`。两者都没有时，
使用 stream 路径中的 ID；该 ID 需要匹配已记录的媒体源 ID。32 位 UUID 的带连字符和
无连字符格式视为同一 ID。`HEAD` 不执行这一查找，始终回源。

两个 danmu raw 入口不属于视频直链入口：即使存在同 ID 的映射，也始终代理到 Jellyfin。
上游返回的状态、正文和适用的 `Content-Type` / `Location` 按普通 HTTP 代理转发。

### 地址映射与失效

直链映射保存在进程内存中。服务重启后，需要再次请求 PlaybackInfo 才能重新填充。
它与已删除的“完整 PlaybackInfo JSON 正文缓存”不同：每次播放信息请求仍会访问 Jellyfin，
上游错误不会被早前的成功响应掩盖。

同一媒体源后续给出本地路径、空值或不可用地址时，会删除该 ID 的旧直链；之后再收到有效
HTTP(S) 地址即可恢复。其他媒体源 ID 不受影响。

媒体源缓存会捕获自身 URL 解析的 `ValueError` 并清理对应映射；畸形 URL 仍可能在更早的
媒体分析阶段抛出异常，这一限制不属于缓存失效处理的覆盖范围。

## 日志

| 类型 | 默认位置 | 主要内容 |
| --- | --- | --- |
| 应用日志 | 标准输出 + `JellyfinProxy.log` | 启停、请求 ID、客户端识别和策略选择 |
| 访问日志 | `access.log` | 请求时间、状态码、耗时、方法、客户端 IP 和路径 |

两种日志文件均在达到 **10 MiB** 后轮转，最多保留 **5 个备份**。将对应路径设置为空字符串
可关闭该文件输出；关闭应用日志文件后仍保留标准输出。

PlaybackInfo 和 Video 请求会在应用日志中产生 `client_identified` 记录，包含
客户端名称、设备名称、设备 ID、User-Agent 以及最终选择的 `modify` 或 `bypass` 动作。
客户端字段会清理控制字符并限制长度。

合法视频 GET / HEAD 还会记录处理结果：处理方式（直链跳转或 Jellyfin 透传）、映射
命中情况（命中、未命中或未查询）和实际响应状态。视频 HEAD 与 Video 绕过不会查询
直链，因此显示为未查询；视频 GET 未命中后即使 Jellyfin 自身返回 302，也不会记录为
直链命中。这些记录沿用请求 ID 关联，不包含查询参数、Cookie 或直链地址。

应用请求日志不记录查询参数、请求体或认证请求头；访问日志中的 API key、token 等认证
查询参数会脱敏。访问日志格式参考 MediaWarp，与应用日志分开写入。

响应携带 `X-Request-ID`，可用于关联代理请求和上游访问；请求已携带合法值时会保留。
版本见启动日志和 `X-JellyfinProxy-Version` 响应头，也可在不启动服务时查询：

```bash
./JellyfinProxy --version
# 源码运行时：
.venv/bin/python main.py --version
```

## 未发布变更

视频 `HEAD` 请求现在始终按原方法透传 Jellyfin，不查询直链或返回 302。视频直链
特殊处理只作用于 `/Videos/{id}/stream` 与 `/Videos/{id}/stream.{container}` 的
GET / HEAD；`/video/...`、`master.m3u8`、HLS、字幕等路径改为普通代理。视频
GET / HEAD 的处理方式、映射命中情况和响应状态会写入应用日志，且不记录查询参数、
Cookie 或直链地址。

## 从 1.0.0 升级到 1.0.1

`/api/danmu/{id}/raw` 与 `/emby/api/danmu/{id}/raw` 不再使用视频直链映射，改为普通
代理到 Jellyfin；即使同 ID 已有映射，或请求携带 `MediaSourceId` / `mediaSourceId`，
也不会生成视频 `302`。Jellyfin 自身返回的重定向和错误响应仍会按普通代理规则转发。

原先依赖 raw 路径视频重定向的客户端将收到 Jellyfin 的普通响应，播放结果可能因此
变化；该兼容入口已移除。`/Videos/{id}/...`、`/videos/{id}/...` 和 `/video/...` 的直链、
失效清理及流式回退保留。无需新增配置项，原有 PlaybackInfo 字段覆盖和客户端绕过配置
继续生效。

## 从 0.9.x 升级

1. **确认字段需求。** 1.0 不再默认将远程源的 `Protocol` 改为 `File`，也不再默认将
   `SupportsTranscoding` 改为 `false`。需要旧效果时，显式配置这两个媒体源字段。
2. **预期每次请求上游。** 完整 PlaybackInfo JSON 缓存已删除，每次刷新都要等待 Jellyfin
   解析；缓存曾掩盖的上游错误也会逐次显现。
3. **清理旧配置（可选）。** 以下 TOML 项及对应大写环境变量会被忽略，无需删除即可启动：

   - `playback_info_cache_enabled`
   - `playback_info_cache_ttl_seconds`
   - `playback_info_cache_max_entries`
   - `playback_cache_bypass_clients`

`X-JellyfinProxy-Cache` 响应头、`playback_info_cache` 日志记录及 `client_identified` 的
`cache` 字段也已移除。Video 直链映射、绕过时的原始 PlaybackInfo 正文、地址失效清理与
流式回退均保留。完整变更见 [CHANGELOG](../CHANGELOG.md)。

## 常见问题

### 配置了直链，为什么视频仍经过 Jellyfin？

先确认客户端连接的是代理入口，再检查是否命中 `bypass_clients` 或 `video_bypass_clients`。
示例默认绕过 Infuse、Kodi。直链需要先由 PlaybackInfo 填充，视频请求的媒体源 ID 必须
匹配映射，Path 也必须是可用 HTTP(S) 地址；不满足时会回退到 Jellyfin。

### 返回了 302，客户端却播放失败？

重定向后由客户端访问媒体地址，请检查客户端网络是否能够访问该地址，以及地址自身是否
仍然有效。返回 302 只说明代理找到了直链，不代表客户端已成功读取媒体。

### 为什么还会等待 Jellyfin 解析 STRM？

JellyfinProxy 不自行读取 STRM 或调用 ffprobe，也不缓存完整播放信息正文。
每次 PlaybackInfo 请求都要等待 Jellyfin 返回；视频地址映射不会跳过这一步。
