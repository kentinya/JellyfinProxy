# JellyfinProxy

JellyfinProxy 是一个基于 FastAPI 的异步反向代理。它会透明转发 Jellyfin
流量，并对 Jellyfin 已在 `PlaybackInfo` 响应中解析出的媒体 URL 应用策略。

## 参与开发

先阅读 [AGENTS.md](AGENTS.md) 和[开发流程](docs/development-workflow.md)，当前实施
范围见 [TASK.md](TASK.md)。只有新增大版本功能需要 A 规划 [Slice](SLICE.md)；
有 Slice 时 B 负责 Task 规划与独立审查，独立小版本 bug 则由 B 直接规划并收尾。
Developer 在两条路径中均负责实施、验证和交接。

规划模板：[Task](Task/TEMPLATE.md)、[Slice](Task/SLICE_TEMPLATE.md)。
流程来源与固定参考版本见[来源说明](docs/references.md)。
真实 Jellyfin 12.3 基线的准备、执行与证据说明见
[验证工具文档](docs/validation/jellyfin-12.3-baseline.md)。

## 源码运行

```bash
cd /opt/mediawarp
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py --config JellyfinProxy.toml
```

程序主要通过 `JellyfinProxy.toml` 读取配置，也可以使用环境变量覆盖配置项，
环境变量示例见 `.env.example`。

`BYPASS_CLIENTS` 是以英文逗号分隔的客户端列表。程序会忽略大小写，在
`User-Agent`、`X-Emby-Client` 和 `X-Emby-Device-Name` 请求头中进行
子字符串匹配。匹配成功的客户端将绕过所有播放信息修改，直接代理到 Jellyfin。

`PLAYBACK_BYPASS_CLIENTS` 和 `VIDEO_BYPASS_CLIENTS` 可分别绕过 PlaybackInfo
修改和 Video 重定向。TOML 中对应 `playback_bypass_clients` 与
`video_bypass_clients` 数组。例如，若 A 只改 PlaybackInfo、B 只改 Video、C
两者都改、D 两者都绕过，可配置：

```toml
bypass_clients = ["D"]
playback_bypass_clients = ["B"]
video_bypass_clients = ["A"]
```

C 无需出现在任何列表中。`bypass_clients` 优先级最高；同一个客户端如果也出现
在其他列表中，仍会绕过所有修改。

PlaybackInfo 请求会在应用日志中产生 `client_identified` 记录，包含
客户端名称、设备名称、设备 ID、User-Agent 以及最终选择的 `modify` 或 `bypass`
动作。客户端字段会清理控制字符并限制长度，认证信息不会写入日志。

`LOG_LEVEL` 控制日志级别，默认为 `INFO`。程序会为每个请求返回
`X-Request-ID` 响应头；如果请求已经携带合法的 `X-Request-ID`，程序会保留
该值，以便关联请求、上游访问和播放策略日志。应用日志不会记录查询参数、请求体
或认证请求头。

`LOG_FILE` 用于指定轮转日志文件，默认是在配置文件所在目录创建
`JellyfinProxy.log`。单个日志文件达到 10 MiB 后自动轮转，最多保留 5 个备份。
将 `LOG_FILE` 设置为空字符串可以关闭文件日志，只输出到标准输出。

`ACCESS_LOG_FILE` 用于指定独立的访问日志，默认为配置文件同目录下的
`access.log`。格式参考 MediaWarp，包含请求时间、状态码、耗时、HTTP 方法、
客户端 IP 和请求路径；查询串中的 API key、token 等认证值会自动脱敏。访问日志
采用相同的轮转规则，将 `ACCESS_LOG_FILE` 设置为空字符串可关闭写入。

代理不会打开或读取 STRM 文件。媒体元数据和 STRM 内容仍由 Jellyfin 负责
解析；JellyfinProxy 只分析 Jellyfin 返回的 HTTP(S)
`MediaSources[].Path`，并应用已配置的策略规则。

为避免客户端重复请求 PlaybackInfo 时再次触发 Jellyfin 使用 ffprobe 探测 STRM，
旧版本曾缓存成功的上游 PlaybackInfo 响应。该缓存已撤除：每个 PlaybackInfo 请求
都会独立转发到 Jellyfin，代理不再按 Item 复用响应正文，也不再提供缓存相关的
配置项、`X-JellyfinProxy-Cache` 响应头或缓存日志字段。因此首次请求（以及每次
刷新）都会等待 Jellyfin 自身完成解析，上游错误也会逐次显现，而不会被早前的
成功响应掩盖。旧配置中的 `playback_info_cache_enabled`、
`playback_info_cache_ttl_seconds`、`playback_info_cache_max_entries` 和
`playback_cache_bypass_clients`（以及对应大写环境变量）会被忽略且不生效，
无需删除即可启动。

处理 `PlaybackInfo` 时，代理会在内存中缓存有效的 HTTP(S)
`MediaSource.Id` 与 `Path`。即使客户端绕过 PlaybackInfo 修改，也会记录直链，
同时保持绕过客户端的响应正文原样返回。
当同一 `MediaSourceId` 后续传入媒体源缓存的 Path 不是可用 HTTP(S) 地址（本地路径、
空值、非 HTTP(S) 协议或缺少 host）时，缓存会删除该 ID 的旧直链，只影响这一个 ID；
之后再次处理到有效地址会重新建立映射并恢复重定向。缓存方法也会捕获自身 URL 解析的
`ValueError` 并清理该 ID；修改 PlaybackInfo 时，畸形 URL 仍可能在此前的
MediaResolver 阶段抛出异常，本次修复不覆盖该阶段。
Video 是否重定向仍由 Video 绕过配置控制。后续 `/Videos/{id}/...` 或 `/videos/{id}/...`
请求携带匹配的 `MediaSourceId` 或 `mediaSourceId` 时，将返回 `302` 重定向至该 Path；缓存未命中或
Path 不是 HTTP(S) URL 时仍透明代理到 Jellyfin。
当视频请求没有 `MediaSourceId` 和 `mediaSourceId` 时，会尝试使用 `/Videos/{id}/...` 中的 ID；
32 位 UUID 的带连字符和无连字符格式视为同一个 ID。
兼容使用 `/emby/Items/{id}/PlaybackInfo` 查询播放信息、随后通过
`/emby/api/danmu/{id}/raw` 播放的客户端；raw 路径同样优先使用缓存的远程 Path。
SenPlayer 使用的无 `/emby` 前缀 `/api/danmu/{id}/raw` 也采用相同处理。

透明代理响应采用异步流式传输，不会把完整视频加载到内存；Range、Content-Range、
Content-Length 和 Content-Encoding 等媒体响应头会原样保留。

## 按字段修改 PlaybackInfo

代理默认不修改 PlaybackInfo 的字段：Jellyfin 返回什么就返回什么。旧版本曾固定把
远程媒体源的 `Protocol` 改为 `File` 并把 `SupportsTranscoding` 置为 `false`，
该自动修改已取消。需要同样效果时必须显式配置：

```toml
[playback_info.response_fields]
ServerName = "Home Jellyfin"

[playback_info.media_source_fields]
Protocol = "File"
SupportsTranscoding = false
SupportsDirectPlay = true
```

作用域与规则：

- `playback_info.response_fields` 作用于 PlaybackInfo 响应根对象的直接字段；
  `playback_info.media_source_fields` 作用于 `MediaSources` 数组中每个可用 HTTP(S)
  媒体源的直接字段。`MediaStreams` 等嵌套对象不在范围内，也不支持点路径、数组下标
  或模板。
- 两个表缺省或为空时都不修改任何字段；只有显式列出的字段才会被覆盖，未列出的字段
  一律保持 Jellyfin 的返回值。已存在字段被替换，缺少字段被补入。
- 值保持 TOML 的原类型：字符串、布尔、整数、有限小数、数组和对象。数组 / 对象整体
  替换该字段，不做深层合并。代理不按字段名推测类型，因此请按 Jellyfin JSON 的类型
  填写（例如布尔值写成 `false` 而不是 `"false"`）。
- 字段名与 Jellyfin JSON 一致且区分大小写。`response_fields` 不能覆盖 `MediaSources`
  容器；媒体源字段统一通过 `media_source_fields` 配置。
- 媒体源字段覆盖只作用于 Path 是可用 HTTP(S) 地址的媒体源。本地路径、缺失或无效
  Path 的媒体源不会被修改，仍按既有逻辑透传并清理其直链。
- 覆盖后的最终 `Id` / `Path` 用于 Video 重定向：配置改变 `Id` 时，旧 ID 的直链映射会
  被清理，其他 ID 不受影响。
- 该配置在启动时读取，修改后需要重启；没有热更新，也不提供对应环境变量。
- 类型或结构非法（例如 `NaN` / `Infinity`、TOML 日期 / 时间、空字段名、非表的
  `playback_info`）会在启动时报错，错误信息只包含配置位置和类型，不打印配置值。

该配置只改变 PlaybackInfo 响应中的字段值，不代表 Jellyfin 或客户端因此真正支持某种
播放 / 转码方式。

## 版本管理

JellyfinProxy 遵循语义化版本规范。当前版本统一定义在 `version.py` 中，并会
显示在启动日志和 `X-JellyfinProxy-Version` 响应头中。不启动服务器也可以查询
版本：

```bash
.venv/bin/python main.py --version
```

每个版本的变更记录保存在 `CHANGELOG.md` 中。
下载见 [GitHub Releases](https://github.com/kentinya/JellyfinProxy/releases)，
双架构构建、校验与发布步骤见[发布说明](docs/releasing.md)。

## 独立二进制

程序可以使用两个文件独立部署：Linux 可执行文件 `JellyfinProxy` 和放在其旁边
的配置文件 `JellyfinProxy.toml`。

启动命令：

```bash
./JellyfinProxy --config ./JellyfinProxy.toml
```

`log_file` 使用相对路径时，会相对于配置文件所在目录进行解析。环境变量仍可用于
覆盖文件中的配置。

在目标 Linux 架构上构建可执行文件：

```bash
.venv/bin/pip install -r requirements-build.txt
.venv/bin/pyinstaller --noconfirm --clean JellyfinProxy.spec
```

构建结果位于 `dist/JellyfinProxy`。PyInstaller 生成的可执行文件与操作系统和
CPU 架构相关，因此不同平台需要分别构建。

## Docker Compose

项目提供的 Compose 配置使用宿主网络模式，使默认上游地址
`http://127.0.0.1:8096` 可以访问宿主机上已发布端口的 Jellyfin：

```bash
cd /opt/mediawarp
docker compose up -d --build
docker compose ps
docker compose logs -f jellyfinproxy
```

启动前请编辑 `JellyfinProxy.toml`。Compose 配置将 `LOG_FILE` 设置为空，日志
只写入标准输出并由 Docker 管理。

重启服务：

```bash
docker compose restart jellyfinproxy
```

停止并删除容器：

```bash
docker compose down
```
