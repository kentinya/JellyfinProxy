# 真实 Jellyfin 12.3 基线与验证工具

本文说明 Slice S1 真实服务验证工具的**准备、执行、重跑与停止**。工具是测试基础设施，
不参与代理业务；产品代码不会导入 `scripts/validation/`。

- 合同要求固定 **Jellyfin Server 12.3**；其他版本、`latest` 或网页版本号一律拒绝。
- 对照组：`J`（直连 12.3，经透明观测入口）、`B-on`（固定 Slice Base，原默认缓存开启）、
  `B-off`（同一 Base，仅关闭 JSON 缓存）。三者使用同一服务器、同一素材、同一客户端策略。
- 当前证据：[`artifacts/validation-evidence/S1/s1-1-baseline-20261025-03`](../../artifacts/validation-evidence/S1/s1-1-baseline-20261025-03)。

## 1. 前置条件

| 项 | 要求 | 检查方式 |
|---|---|---|
| Docker | client / server 可用 | `doctor` |
| 官方镜像 | `jellyfin/jellyfin:12.3`（可用 `S1_JELLYFIN_IMAGE` 指定同一构建的其他引用） | `doctor` 显示 `present`，`prepare` 记录 digest |
| Python | 仓库 `.venv`，含 fastapi / httpx / uvicorn / pytest | `doctor` |
| 端口 | 18096 Jellyfin、18097 观测入口、18098 B-on、18099 B-off、18100 媒体源，仅 loopback | `doctor` 逐项报告占用者 |
| 磁盘 | 约 1 GiB（镜像缓存另计） | `doctor` |

端口被占用时工具**明确失败并打印占用进程**，不会接管 8096 / 8097 或任何已有容器。

## 2. 命令

`cwd` 为仓库根；`RUN_ID` 使用新目录，不覆盖历史证据。

```bash
RUN_DIR=artifacts/validation-evidence/S1/s1-1-baseline-$(date +%Y%m%d-%H%M)
.venv/bin/python scripts/validate_jellyfin_12_3.py doctor   --run-dir "$RUN_DIR"
.venv/bin/python scripts/validate_jellyfin_12_3.py prepare  --run-dir "$RUN_DIR" \
    --server-version 12.3 --base-ref 6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5
.venv/bin/python scripts/validate_jellyfin_12_3.py baseline --run-dir "$RUN_DIR"
.venv/bin/python scripts/validate_jellyfin_12_3.py stop     --run-dir "$RUN_DIR"
.venv/bin/python scripts/validate_jellyfin_12_3.py verify-evidence --run-dir "$RUN_DIR"
```

| 命令 | 行为 |
|---|---|
| `doctor` | 只读检查依赖、镜像、端口、Base 解析；不创建资源。不满足即非零退出 |
| `prepare` | 创建专属目录与容器、锁定镜像 digest（`server.lock.json`）、用镜像自带 ffmpeg 生成素材、建库 / 用户 / 素材，写入 `manifest.json`。同一 run-dir 再次执行只复用已有锁 |
| `baseline` | 按 `J → B-on → B-off` 执行 RJ-01～RJ-12；默认全量。任一必需子项非 PASS 则以非零退出，但仍执行引擎内进程清理 |
| `stop` | 只删除带本 run 所有权标签的容器和登记过的 pid；重复执行安全 |
| `verify-evidence` | 校验身份、覆盖、白名单、脱敏、事务账本与停止记录，不止检查文件存在 |

补充参数：

- `--cases RJ-02,RJ-05`：只跑指定场景（自动准备前置），不得把选择结果当成全量 PASS。
- `--groups J,B-off`：只跑指定对照组。
- `--server-lock <path>`：按既有锁重建（B 复现用），仍校验 digest / 版本 / 产品 Base。
- `--skip-pull`：镜像已在本地时跳过拉取。
- `stop --remove-files`：额外删除 run 目录（默认保留以便复核）。

## 3. 环境隔离与所有权

- 目录：`<run-dir>/{private,evidence,jellyfin,media,webroot,base-src,proxy,observatory}`，
  `private/` 与 `evidence/` 为 `0700`，凭据文件 `0600`。
- 容器：`s1-jellyfin-<run-id>-<timestamp>`，带标签
  `jellyfinproxy.s1.validation=1` 与 `jellyfinproxy.s1.run=<run-id>`。
  `stop` 在删除前重新核对标签，标签不符则保留并记入证据。
- 进程：观测入口与两个代理由工具以 `start_new_session` 启动，pid 记录在 manifest；
  清理时用 `/proc/<pid>/cwd` 与 cmdline 复核归属，pid 被系统回收时不会误杀。
- 子进程环境显式移除 `JELLYFIN_URL`、`LISTEN_*`、`*_BYPASS_CLIENTS`、
  `PLAYBACK_INFO_CACHE_*`、`LOG_*`、`PYTHONPATH`，避免开发者 shell 覆盖影响对照。
- 产品源码用 `git archive` 从固定 Base 导出到 `base-src/`，再复制成 `proxy/B-on`、
  `proxy/B-off`；不切换工作区、不采用未提交业务文件。`verify-evidence` 重新校验每个文件摘要。

## 4. 观测入口的边界

`scripts/validation/observatory.py` 是唯一的旁路观测点，规则如下：

1. 每个请求**真实转发**到同一 12.3；不缓存、不重试、不合成、不跟随重定向。
2. JSON 只保存**脱敏副本**与原始字节摘要；媒体只做流式计数与摘要，不缓冲完整视频。
3. 唯一声明的表示适配：向上游请求 `Accept-Encoding: identity`（RFC 9110 允许），
   保证记录的字节摘要与交付给客户端的字节一致；上游自身的 `Content-Encoding` 原样转发。
4. 传输层只过滤 hop-by-hop 头，并剔除 `date` / `server`（避免与 uvicorn 重复）。
5. 记录 `range`、状态、`content-range`、`location` 摘要、分块时间、是否被客户端取消。
6. 每事务带唯一 ID，客户端请求头 `X-Request-ID` 与之关联；场景计数只按该 ID 归因。

客户端与服务端都被要求携带 `X-Request-ID`，因此“本次请求是否回源”“回源几次”可逐事务核对。

## 5. 素材与夹具

| 键 | 内容 | 用途 |
|---|---|---|
| `local` | 本地 mp4 + 本地 poster.jpg | RJ-07 / 08 / 12 的真实本地 Range 与流式 |
| `remote` | `.strm` 指向受控 HTTP 源 `remote-a.mp4` | RJ-02～05 的远程直链、302、字段比较 |
| `remote_two` | 独立第二个媒体源 `remote-b.mp4` | RJ-06 第二 ID 不受影响 |
| `multi` | 一个 Item 两个本地版本 | 多 MediaSource 覆盖 |
| `dynamic` | `.strm`，远程 ↔ 本地路径之间切换 | RJ-06 同 ID 有效→无效→有效 |
| `throttle` | `.strm` 指向限速源 | RJ-08 断连可观测 |

媒体全部由固定镜像内的 `ffmpeg` 生成（小尺寸 testsrc + sine），摘要记录在
`evidence/media-inventory.json`。受控源是工具自身的 `MediaServer`，同时监听 `127.0.0.1`
与 docker 桥网关地址并共享同一请求账本：验证客户端跟随 `Location`（loopback），
Jellyfin 容器经网关访问，两者读取同一份字节，地址记录在 manifest。

**同 ID 转换的可复现做法**（12.3 实测）：仅改写 STRM 内容再扫描，Jellyfin 会保留旧
MediaSource；先删除 STRM 扫描、再写回并扫描，Jellyfin 才会用同 Item ID 解析到新目标。
工具即用后者，不使用数据库改写或手工 JSON。

## 6. 结果语义

- 每个 RJ 拆成若干子项，逐项记录 `PASS / FAIL / BLOCKED / NOT RUN / SKIPPED` 及原因。
- `B-on` 命中旧 JSON 缓存、跨前缀复用、认证被旧缓存掩盖等是**改前现象**，按事实记录，
  不作为失败，也不代表上游认证通过。`cache_masked_auth` 字段标记这类行。
- `TranscodingUrl` 出现在差异清单是因为 Jellyfin 把 `Protocol` / `TranscodingSubProtocol`
  编进该 URL；代理不编辑该字段，证据中单独说明。
- 动态字段白名单只有 `PlaySessionId` 与 `MediaSources[].ETag`，每条都带说明；
  32 位十六进制 Item ID 属正常值，不作为凭据泄漏。
- C（候选）对照项在 S1.1 标记 `NOT RUN — deferred to a later Slice task`。

## 7. 证据包

`evidence/` 主要文件：

| 文件 | 内容 |
|---|---|
| `prepare.json` | 端口、库、Item ID、运行版本、镜像 digest |
| `media-inventory.json` | 素材与受控源文件的大小与 SHA256 |
| `results.json` | 逐子项结果与结构化细节（含计数、摘要、差异位置） |
| `summary.md` | 人读汇总表与统计 |
| `comparison.json` | 按场景分组的 J / B-on / B-off 对照 |
| `transactions-<group>.jsonl` | 每组脱敏事务账本（含请求 ID、状态、字节摘要、取消标记） |
| `stop.json`、`stop-history.jsonl` | 首次停止记录与后续幂等调用历史 |
| `verify-evidence.json` | 自检结果（身份、覆盖、白名单、脱敏） |

另有 `manifest.json`（运行身份、工具 Head、产品 Base、进程登记）和
`server.lock.json`（镜像引用 / digest / 架构 / 标签 / 实际运行版本 / 产品 Base）。
明文凭据只在 `private/credentials.json`，不在证据包内，`verify-evidence` 会检查这一点。

## 8. 重跑与复现

- 同一 `server.lock.json` + 相同素材摘要 + 相同 Base 即可重跑；新 run-dir 会得到新的
  Item ID，场景只要求“同一次运行内同 ID”，不要求跨环境一致。
- 复现他人证据：

```bash
SRC=artifacts/validation-evidence/S1/s1-1-baseline-20261025-03
NEW=artifacts/validation-evidence/S1/s1-1-b-lock-replay
.venv/bin/python scripts/validate_jellyfin_12_3.py prepare  --run-dir "$NEW" --server-lock "$SRC/server.lock.json"
.venv/bin/python scripts/validate_jellyfin_12_3.py baseline --run-dir "$NEW" --cases RJ-02,RJ-04,RJ-05
.venv/bin/python scripts/validate_jellyfin_12_3.py stop     --run-dir "$NEW"
```

- 源码、工具、认证、素材或镜像变化后按影响重跑；`verify-evidence` 会拒绝工具 Head
  与产品 Base 不一致或来源被篡改的证据包。

## 9. 工具自检

```bash
.venv/bin/python -m pytest tests/test_real_jellyfin_validation.py
.venv/bin/python -m pytest
```

自检只证明工具逻辑：请求关联与计数、版本漂移拒绝、未白名单差异失败、摘要不被脱敏掩盖、
凭据不落盘、停止只处理所有权匹配的资源。**假上游与单元结果不能替代真实 12.3 基线，
也不能作为任何客户端兼容结论。**
