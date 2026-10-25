# S1 历史验证：Jellyfin 12.3 基线与工具

本文保留已关闭 Slice S1 的真实服务验证方法，便于复查历史证据。工具默认导出固定
Slice Base `6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5`（0.9.3），运行 J / B-on / B-off
改前对照组，不能用它的默认结果宣称当前 1.0 版本已完成验证。新验证的范围以对应任务为准。
工具是测试基础设施，不参与代理业务；产品代码不会导入 `scripts/validation/`。

S1 已于 2026-10-25 获[独立 A 最终 PASS / CLOSED](../../Task/archive/S1-remove-playback-info-json-cache.md#a-final-review)。
完整历史入口见[任务与合同索引](../../Task/archive/README.md)。下文证据在本工作区可访问，
未纳入 Git，仅克隆仓库不会取得这些文件。

按 [S1 合同 v4](../../Task/archive/S1-remove-playback-info-json-cache.md) 和
[历史 Task S1.1](../../Task/archive/S1.1-real-jellyfin-12.3-baseline.md)，本文工具链是**可选方式**，
不是实机功能验收前置。人工或短小 HTTP 客户端取得的有效真实证据同样可用；不必先修工具。
现有 `--server-lock` 新实例重建会因 server ID 不同失败；观测器积累全部媒体字节且会合成
连接失败响应，因此不能用它证明产品提前取消释放或直连 Jellyfin 不可达。
部分 PASS 判据不足，须核对原始证据；05 的校验结果实际为 20 PASS + 1 WARN，
不是 21 项全 PASS。下文保留现有工具用法，不代表这些限制已修复。

针对上述限制，S1.1 的 V1～V4 功能补证改用 `scripts/validation/supplement.py`（见第 10 节）：
产品直连真实 Jellyfin、只用已存在的 PlaybackInfo / Video / raw 入口、媒体只做有界读取，
提前取消与上游释放由受控源的 socket 账本判定。观测器不参与该路径。

- 合同要求固定 **Jellyfin Server 12.3**；其他版本、`latest` 或网页版本号一律拒绝。
- 工具记录组：`J`（当前工具实际经观测入口，不能当作独立直连证据）、`B-on`（固定 Slice Base，原默认缓存开启）、
  `B-off`（同一 Base，仅关闭 JSON 缓存）。三者使用同一服务器、同一素材、同一客户端策略。
- S1.1 基线证据：[`artifacts/validation-evidence/S1/s1-1-baseline-20261025-05`](../../artifacts/validation-evidence/S1/s1-1-baseline-20261025-05)。

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

`cwd` 为仓库根；`RUN_DIR` 使用新目录，不覆盖历史证据。以下为历史基线重跑命令，
其中创建 / 删除容器、建库、写入素材与停止服务的步骤须在取得对应隔离环境操作授权后执行。

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
- `--server-lock <path>`：原计划按既有锁重建；目前有上述新实例限制，不是 B 复现强制入口。
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

`scripts/validation/observatory.py` 是基线工具的旁路观测点。以下为设计约束；第 1 条的
“不合成”和第 2 条的“不缓冲”未完整实现，产品取消 / 不可达结论须使用前述直连补证。

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
- C（候选）对照项在 S1.1 标记 `NOT RUN — deferred to a later Slice task`；S1.4 使用本工具重新
  取得 J / B-on / B-off 基线后，以产品自身 `main.py --config` 启动候选 C，由同目录的
  `candidate_driver.py`（单次取证脚本，非产品 CLI）采集 C 分组证据。S1.4 独立 B 审查发现
  认证 / 未知 Item 未执行、取消仍经观测器、远程停止只读到 302；当时退回 RR-1 / RR-2。
  补证与新独立真实重放已完成，S1.4 最终 B PASS；完整 RJ / F-08 的结论须组合原证据与
  `s1-4-supplement-20261025-01/`、`s1-4-b-final-review-20261025-01/`，不能只依原行数判断。
  直连 J / C 的 Content-Length 逐值相同，以原始 JSON 和最终 B 更正为准，不采用补证
  README 的“C chunked / 无长度头”错误说明。工具限制保持记录，
  [A 最终审查](../../Task/archive/S1-remove-playback-info-json-cache.md#a-final-review)已 PASS / CLOSED。
  该脚本不是通用 `--groups C` 入口，也不修改产品；证据见
  [`s1-4-candidate-20261025-01`](../../artifacts/validation-evidence/S1/s1-4-candidate-20261025-01/README.md)。

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

重跑应固定产品 Base、镜像 digest 和素材摘要。`--server-lock` 目前会因新实例的 server ID
不同而失败，不作为可用的跨实例重建方法。取得隔离环境授权后，可以在新目录重新准备基线：

```bash
NEW=artifacts/validation-evidence/S1/s1-1-replay-$(date +%Y%m%d-%H%M%S)
.venv/bin/python scripts/validate_jellyfin_12_3.py doctor   --run-dir "$NEW"
.venv/bin/python scripts/validate_jellyfin_12_3.py prepare  --run-dir "$NEW" \
    --server-version 12.3 --base-ref 6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5
.venv/bin/python scripts/validate_jellyfin_12_3.py baseline --run-dir "$NEW" --cases RJ-02,RJ-04,RJ-05
.venv/bin/python scripts/validate_jellyfin_12_3.py stop     --run-dir "$NEW"
```

与原证据比较 `server.lock.json` 的镜像 digest、产品 Base 及 `evidence/media-inventory.json`
的素材摘要，再判断是否属于相同输入；仅镜像标签相同不足以复用结论。新目录会得到新的
Item ID，场景只要求同一次运行内同 ID。上例仅执行三个 RJ 场景，不代表全量通过。

源码、工具、认证、素材或镜像变化后按影响重跑；`verify-evidence` 的具体身份、覆盖与来源
检查以其报告为准，工具自检不能替代原始事务和产品直连证据。

## 9. 工具自检

```bash
.venv/bin/python -m pytest tests/test_real_jellyfin_validation.py
.venv/bin/python -m pytest
```

自检只证明工具逻辑：请求关联与计数、版本漂移拒绝、未白名单差异失败、摘要不被脱敏掩盖、
凭据不落盘、停止只处理所有权匹配的资源。**假上游与单元结果不能替代真实 12.3 基线，
也不能作为任何客户端兼容结论。**

## 10. S1.1 功能补证（V1～V4）

`scripts/validation/supplement.py` 只补历史 Task S1.1 的四个功能缺口，不替代全量基线，
也不修复上文的工具限制。它不经过观测器：`B-on` / `B-off` 产品进程的上游直接是
真实 Jellyfin 的地址，`J` 行是同一请求直连该 12.3 实例。

```bash
RUN_DIR=artifacts/validation-evidence/S1/s1-1-supplement-<timestamp>
.venv/bin/python scripts/validate_jellyfin_12_3.py doctor  --run-dir "$RUN_DIR"
.venv/bin/python scripts/validate_jellyfin_12_3.py prepare --run-dir "$RUN_DIR" \
    --server-version 12.3 --base-ref 6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5
.venv/bin/python scripts/validation/supplement.py --run-dir "$RUN_DIR"
.venv/bin/python scripts/validate_jellyfin_12_3.py stop --run-dir "$RUN_DIR"
```

| 检查 | 走的产品入口 | 判定依据 |
|---|---|---|
| `V2-raw-unseeded-*` | `/api/danmu/{id}/raw`、`/emby/api/danmu/{id}/raw` | 未种入时状态与正文须与直连 J 相同，不得 302 |
| `V2-raw-after-seeding` | 同上 + `PlaybackInfo` | 种入后须 302 到该 Item 自己的远端 URL |
| `V2-bypass-global-and-overlap` | `PlaybackInfo` + `/Videos/{id}/stream` | 全局 / 重叠客户端保持上游 `Protocol`、无 302；普通客户端仍被改写并 302。`OverlapClient` 必须同时出现在全局表与两个分支表（判定附带 `overlap_client_listed_in`） |
| `V2-bypass-route-independence` | 同上 | `VideoOnly` 只绕过 Video，`CacheOnly` 仍被改写 |
| `V2-id-priority-and-uuid` | `/Videos/...` 的 query 与 path 两种写法 | 两个已种入源下 query 覆盖 path，连字符与紧凑 UUID 都命中同一目标；同一 URL 同时带 `MediaSourceId` 与 `mediaSourceId` 且指向不同源时，按产品既有优先级（精确名 `MediaSourceId` 优先）解析，顺序与指向各交换一次 |
| `V1-second-mapping-preserved` | `PlaybackInfo`（仅种入一次）+ `/Videos/...` | 第二映射（remote-a）在目标 ID 有效→无效→有效全过程中保持 302，最终与目标的 remote-b 不同。种子之后循环内不再为该 ID 发 `PlaybackInfo`（HIT 也会重写映射），`second_playback_requests_during_cycle=0` |
| `V3-cancel-upstream-release` | `/Videos/...`（`VideoOnly` 客户端） | 传输中读 8192 字节即断开；受控源账本显示 `aborted_by_client=true` 且 `bytes_sent` < `Content-Length`；后续 Range 请求仍得真实字节 |
| `V4-direct-unreachable-and-recovery` | `PlaybackInfo` + `/System/Info/Public` | 停容器期间产品自身报错（非观测器合成），重启后 B-off 冷 / B-on 热均恢复 200 |

配置为产品自身 TOML 的 `matrix_overlap` 组合（`bypass_clients=["GlobalClient","OverlapClient"]`、
`playback_bypass_clients=["PlaybackOnly","OverlapClient"]`、
`video_bypass_clients=["VideoOnly","OverlapClient"]`、
`playback_cache_bypass_clients=["CacheOnly"]`），`OverlapClient` 同时列入全局与两个分支表，
因此重叠行是真实的全局 / 分支交集而非两组不相交列表；两组仅差 `playback_info_cache_enabled`。
`throttle` 夹具在补证时被改写为限速目标（保留同一 Item ID），因此取消一定发生在
传输途中；这是素材操作，不是产品改动。

结果写在 `evidence/supplement-checks.json`（逐项）与 `evidence/supplement-summary.json`
（汇总、产品 Base、镜像 digest、运行版本、工具身份）。这些记录是真实服务结果，
不是单元或假上游结果；仍不构成真实客户端（Infuse / Kodi / SenPlayer）兼容结论。
