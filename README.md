# JellyfinProxy

JellyfinProxy 是一个基于 FastAPI 的异步反向代理。它会透明转发 Jellyfin
流量，并对 Jellyfin 已在 `PlaybackInfo` 响应中解析出的媒体 URL 应用策略。

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

PlaybackInfo 和 Video 请求会在应用日志中产生 `client_identified` 记录，包含
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

处理 `PlaybackInfo` 时，代理会在内存中缓存有效的 HTTP(S)
`MediaSource.Id` 与 `Path`。后续 `/Videos/{id}/...` 或 `/videos/{id}/...`
请求携带匹配的 `MediaSourceId` 时，将返回 `302` 重定向至该 Path；缓存未命中或
Path 不是 HTTP(S) URL 时仍透明代理到 Jellyfin。
当视频请求没有 `MediaSourceId` 时，会尝试使用 `/Videos/{id}/...` 中的 ID；
32 位 UUID 的带连字符和无连字符格式视为同一个 ID。
兼容使用 `/emby/Items/{id}/PlaybackInfo` 查询播放信息、随后通过
`/emby/api/danmu/{id}/raw` 播放的客户端；raw 路径同样优先使用缓存的远程 Path。

透明代理响应采用异步流式传输，不会把完整视频加载到内存；Range、Content-Range、
Content-Length 和 Content-Encoding 等媒体响应头会原样保留。

## 版本管理

JellyfinProxy 遵循语义化版本规范。当前版本统一定义在 `version.py` 中，并会
显示在启动日志和 `X-JellyfinProxy-Version` 响应头中。不启动服务器也可以查询
版本：

```bash
.venv/bin/python main.py --version
```

每个版本的变更记录保存在 `CHANGELOG.md` 中。

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
