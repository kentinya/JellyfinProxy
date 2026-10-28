# Task BUG-002 — 删除两个 danmu raw 入口的视频特殊处理

遵循[开发流程](../docs/development-workflow.md)和
[B 角色指南](../docs/agent-experience/task-planner-reviewer.md)，当前入口见[根 TASK](../TASK.md)。

```text
Task ID: BUG-002
Work Type: BUGFIX
Parent Slice: N/A — standalone bug
Status: IN PROGRESS
Task Base: e4695d81596642363be8219441037da881f8a1ff
Contract Checkpoint: N/A — standalone bug
Plan Checkpoint: e10e1b66f2bb04bb62dff7df40ff93faea27570b
Implementation Head: NOT SET
Difficulty: Medium
Test Level: T4
Planner / Reviewer: B
```

## 目标与授权

用户于 2026-10-28 明确要求“规划一个 Task，删除 danmu 的两个处理”。本 Task 的
目标由这次指令定义：移除以下两个入口的视频特殊处理，统一沿现有普通代理转发：

- `/api/danmu/{id}/raw`
- `/emby/api/danmu/{id}/raw`

这是用户指定的兼容行为调整，按独立 Task 路径规划，不新增 Slice。原规则曾用于
Emby / SenPlayer 视频请求兼容，不将其引入历史改写成误实现；也不将本次删除认定为
SenPlayer 403 的根因修复。关闭弹幕后仍失败、直连成功等调查结果不改变本次明确范围。

首次登记仅规划；用户随后明确要求激活 Task，现可按本合同进入实施阶段。
本次激活只完成准入核对和状态登记，尚未实施产品变更。Plan Checkpoint 从 Git 解析为
已提交计划 `e10e1b66f2bb04bb62dff7df40ff93faea27570b`；Task Base 保持不变。

### 激活记录（2026-10-28）

- Status：`PLANNED → IN PROGRESS`，依据用户“激活 Task”指令。
- 准入核对：计划提交真实存在，Task Base 为其祖先，根 TASK 与本计划一致；跟踪文件
  无未提交改动，原有未跟踪 `artifacts/` 保留。
- 本次检查：文档链接、状态 / 检查点一致性及 `git diff --check`；产品修复测试 NOT RUN。
- 下一步：Developer 按已激活合同实施和隔离验证；部署、生产配置、服务与防火墙仍不在范围。

## 现状与行为合同

已核对当前真实代码、配置说明、`tests/test_core.py`、验证脚本及其测试：

- `routers/route_config.py` 的 `emby_danmu_raw` 规则把两个入口分类为 `VIDEO`。
- `handlers/video_handler.py` 从 raw 路径提取媒体源 ID，命中 `MediaSourceCache`
  时返回对应媒体 Path 的 302；未命中时调用普通代理。
- `handlers/dispatcher.py` 已有 DEFAULT 分支，可直接使用现有 `ProxyHandler`。
- 现有核心测试、`scripts/validation/scenarios.py` 的 RJ-05 / RJ-10，以及
  `scripts/validation/supplement.py` 的种入映射后检查，都包含 raw 返回视频 302 的预期。
- 当前 `docs/configuration.md` 仍声明 raw 支持视频直链，需随未来实现同步。
- 规划开始时跟踪文件无改动；已有未跟踪 `artifacts/` 保留原状，不纳入本 Task 提交。

| 请求 / 条件 | 当前行为 | 实施后的预期 |
| --- | --- | --- |
| 两个 raw 入口命中有效媒体映射 | 可由代理生成视频 302，跳过上游 | 每次普通代理到 Jellyfin，不查询或使用视频映射 |
| 两个 raw 入口未命中映射 | 普通代理到 Jellyfin | 保持普通代理，不合成响应 |
| raw 请求带媒体源 ID 查询参数或尾斜杠 | 仍可能进入视频处理 | 仍走普通代理，参数不能恢复特殊处理 |
| `/Videos/{id}/...`、`/videos/{id}/...`、`/video/...` | 现有直链及回退 | 保持现状 |

删除的是代理的特殊分流，不是删除上游接口或禁止访问。若上游返回 XML、404、403
或自身的 302，代理按既有 HTTP 规则转发。不得硬编码 404 / XML、吞掉上游错误，或
把“不得生成视频 302”误写成“不得返回任何上游 302”。

原本依赖这两个入口的视频直链将交由 Jellyfin 处理，可能得到不同响应；这属于本次
明确调整的兼容范围，必须在未发布说明中写清。其他视频入口及其映射保留。

## 允许实施的范围

1. 从 `routers/route_config.py` 删除两个 raw 入口的视频路由规则，让其自然匹配 DEFAULT。
2. 从 `handlers/video_handler.py` 删除 danmu raw 专用 ID 提取分支，保留现有视频路径
   ID 提取、两种查询参数优先级及 UUID 归一化行为。
3. 修订 `tests/test_core.py` 的路由、raw 302 和混合视频矩阵：将 raw 转为真实应用
   装配下的透传测试，保留真正视频的映射失效 / 回退 / 恢复覆盖，不简单删掉全部用例。
4. 同步 `scripts/validation/scenarios.py`、`scripts/validation/supplement.py` 和
   `tests/test_real_jellyfin_validation.py`：raw 在映射种入前后都比较上游基线；不得保留
   “种入后应返回视频 302”或对 raw 无条件 PASS 的当前判定。
5. 同步 `docs/configuration.md`、`CHANGELOG.md` 的未发布说明及适用 README。
   `docs/validation/jellyfin-12.3-baseline.md` 应区分旧运行结论与修改后的工具预期；
   不改写 `Task/archive/`、历史 PASS 或历史产物。

不新增路由开关、客户端特判、弹幕解析、网盘签名或最终 URL 获取功能。不改
`ProxyHandler`、HTTP 基础设施、媒体缓存算法及 PlaybackInfo 字段规则；若发现必须
超出本范围的问题，先提交给 B 修订本计划，不能借本 Task 扩大实施。

## 验收条件

| 编号 | 场景 | 预期结果 |
| --- | --- | --- |
| AC-1 | 两个 raw 入口、带尾斜杠及现有 HTTP 入口支持的方法 | 实际分流为 DEFAULT，不进入 VideoHandler；带任一种媒体源 ID 查询参数也不改变分流 |
| AC-2 | 无映射、同 ID 有有效映射、先 PlaybackInfo 种入映射再请求 raw | 每次实际访问上游；响应不使用媒体映射、不生成视频 Location；后续真正视频仍可使用原映射 |
| AC-3 | 上游返回 200 XML、404、401 / 403、500 或自身 302 | 保留状态、正文及适用 Content-Type / Location；HEAD 对客户端无正文，沿用既有流式关闭行为 |
| AC-4 | raw 请求含编码路径 / 查询、认证哨兵或 Range；不同客户端绕过配置 | 按现有普通 HTTP 代理规则转发，不因 SenPlayer、全局或 Video 绕过列表重新启用 raw 特殊处理；认证值在日志 / 证据中脱敏 |
| AC-5 | 真正视频入口的映射命中、未命中、失效再恢复及绕过 | 302、查询 ID 优先级、路径 ID、UUID、Range / 206、表示头和上游释放保持既有行为；PlaybackInfo 修改与绕过仍按原合同建立映射 |
| AC-6 | 测试、验证脚本与当前说明 | raw 的当前 302 预期均转换为透传合同，有有效映射的负向回归；脚本能将错误重定向判 FAIL；兼容行为调整写清，历史记录不篡改 |
| AC-7 | 最终交接与独立审查 | 全部必要回归有真实证据，B 核对 AC-1～7；真实客户端和 403 结果独立标注，不将本 Task PASS 扩大为 SenPlayer 403 已解决 |

AC-1～4 通过 Router / Dispatcher 或 `create_app` 的真实装配验证，不能仅直接调用
VideoHandler 证明分流。默认调用链已不把 raw 交给 VideoHandler，不要求额外新增
针对所有非视频路径的防御机制。矩阵覆盖关键组合，不机械展开全部参数的笛卡尔积。

## 必要测试

移除已有播放兼容入口并调整路由、HTTP 集成和既有验证矩阵，按 T4 保留全部回归及
适用的隔离运行验证。计划登记和本次激活只做 T0 检查；产品修复测试在实施时执行。

### 开发 / 修正反馈

先增加名称包含 `danmu` 的新合同回归，在未修复基线上记录首次失败。两个前缀都覆盖
“同 ID 已有视频映射但上游返回 XML / 404”；再覆盖媒体源 ID 查询不能恢复重定向。
使用假上游或隔离本地 HTTP fixture，不访问生产 Jellyfin / OpenList。

```bash
.venv/bin/python -m pytest tests/test_core.py -k danmu
.venv/bin/python -m pytest tests/test_core.py -k 'danmu or routes or video or bypass or proxy or stream'
.venv/bin/python -m pytest tests/test_real_jellyfin_validation.py
```

XML 与视频夹具使用不同正文、Content-Type、URL，检查上游实际收到的请求及响应
关闭。验证工具测试同时覆盖正确透传 PASS 与错误视频 302 的 FAIL，不能只改说明文字。

### 最终候选门槛

```bash
.venv/bin/python -m pytest
git diff --check
```

完整运行已覆盖相同聚焦输入时可明确复用，不机械重跑；最终候选可执行输入变化后
按影响重跑，T4 全回归保留。真实 Jellyfin / Emby / SenPlayer、生产部署、性能与打包
不在本次自动执行范围；没有运行就写 NOT RUN，不从假上游结果推导实机兼容。

### B 独立验证

未承担实现的 B 审查完整 `Task Base..Implementation Head`，独立核实两个 raw 入口
在有效映射与两种媒体源 ID 查询下仍透传、上游错误 / 自身 3xx 保留，以及真正视频的
命中 / 回退 / 恢复。核对验证工具能拒绝错误结果、当前与历史文档边界清楚。
相同候选的其他完整回归可核验后复用；缺少独立审查时保持 PENDING，不自签 PASS。

### 证据与重跑

未来证据放 `artifacts/validation-evidence/BUG-002/<run-id>/` 或 CI artifact，记录完整
源码 SHA、未提交输入摘要、cwd、准确命令、Python / 依赖版本、配置与夹具身份、
退出码、数量 / 耗时、首次失败与重跑、AC 对照及证据访问边界。认证值脱敏，不能
提交真实 token、Cookie 或完整签名 URL；现状观察不能替代修复后的测试与独立审查。

## 非目标和环境边界

- 按已激活合同实施，不创建子代理；本次激活提交只更新任务文档，不包含产品实现。
- 不再调查或承诺修复本次 403，不恢复之前已删除的 Task 或提交。
- 不移除真正视频入口，不改缓存、PlaybackInfo 字段或客户端绕过的原有合同。
- 不读取 STRM、运行 ffprobe、操作 Jellyfin 数据库或安装插件。
- 不改部署配置、服务、日志配置、外部反代、WebSocket、iptables 或其他生产环境。
- 不 push、发布或升级版本；实施时只补适用的未发布说明，历史版本说明保持原貌。
- 原有未跟踪 `artifacts/` 保留，不随计划提交暂存或清理。

## Developer Completion Report

- Changed Files / Implemented：NOT RUN — 已激活，产品实现尚未开始。
- Acceptance Mapping：PENDING。
- Tests and Results / Evidence：修复测试 NOT RUN；本次只检查任务文档和实施准入。
- Decisions / Risks / Remaining Outcomes：移除 raw 视频兼容是用户指定范围；403 因果未定。
- Plan Checkpoint：e10e1b66f2bb04bb62dff7df40ff93faea27570b。
- Implementation Head：NOT SET。

## B Review Result

```text
Reviewed Range: NOT SET
Reviewer / Independence: NOT SET
Decision: PENDING
Acceptance / Required Outcomes all satisfied: PENDING
Slice Required Outcomes all satisfied: N/A — standalone bug
Evidence / Reuse / NOT RUN: 修复测试与独立审查 NOT RUN
Blockers / Remaining Risks: 尚未实施；不承诺 403 或客户端兼容结果
Next: Developer 按已激活合同实施并完成 T4 隔离验证，再移交独立 B 审查
```
