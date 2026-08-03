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

`LOG_LEVEL` 控制日志级别，默认为 `INFO`。程序会为每个请求返回
`X-Request-ID` 响应头；如果请求已经携带合法的 `X-Request-ID`，程序会保留
该值，以便关联请求、上游访问和播放策略日志。日志不会记录查询参数、请求体或
认证请求头。

`LOG_FILE` 用于指定轮转日志文件，默认是在配置文件所在目录创建
`JellyfinProxy.log`。单个日志文件达到 10 MiB 后自动轮转，最多保留 5 个备份。
将 `LOG_FILE` 设置为空字符串可以关闭文件日志，只输出到标准输出。

代理不会打开或读取 STRM 文件。媒体元数据和 STRM 内容仍由 Jellyfin 负责
解析；JellyfinProxy 只分析 Jellyfin 返回的 HTTP(S)
`MediaSources[].Path`，并应用已配置的策略规则。

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
