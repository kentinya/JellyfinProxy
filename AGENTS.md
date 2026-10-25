# 仓库开发约束

项目：JellyfinProxy，基于 Python / FastAPI 的异步 Jellyfin 反向代理。

开始工作先阅读本文件、[开发流程](docs/development-workflow.md)、[README](README.md)、
[当前 Task](TASK.md)。涉及大版本功能时再阅读[当前 Slice](SLICE.md)。按职责阅读
[A](docs/agent-experience/slice-owner-architect-final-reviewer.md)、
[B](docs/agent-experience/task-planner-reviewer.md)、
[Developer](docs/agent-experience/developer-implementation-role.md) 指南。
流程参考项目与固定源码版本见[来源说明](docs/references.md)。用户本次及既有会话授权优先。

## 角色与任务入口

- **只有新增大版本功能时才需要 A 规划 Slice**：A 定义完整能力合同、架构边界和最终验收；
  B 在已激活 Slice 内规划 Task、独立审查并重评全部 Required Outcomes；Developer 实施。
- **仅修复小版本 bug 时，由 B 直接承担规划任务**：B 根据实际代码确认缺陷、范围、
  验收和测试，建立独立 Task；Developer 实施后仍交独立 B 审查。无需新建或激活 Slice，
  无需 A 规划或最终审查。
- 已有活动 Slice 内的问题留在原 Slice / Task 修正，B 继续履行原有职责；改变 Slice
  结果或边界时由 A 修订合同。独立 bug 修复不因涉及多个模块或测试等级高就强制转给 A。
- Developer 职责在两条路径中相同：按活动 Task 实现、修复、验证和交接，提供可核验证据，
  不擅自扩大范围，不签发自己的独立 B 审查或 A 最终审查 PASS。
- A / B / Developer 是职责划分，不自动授权创建多个代理；仅在用户或适用指令明确要求时委派。
  缺少独立审查时保留待审状态。

## 业务边界与代码组织

- 以 README 和真实代码为现有行为依据。新增要求写进对应合同或 Task，不从参考项目
  移植业务需求、历史任务、凭据、授权或 PASS 结论。
- 代理只使用 Jellyfin 返回的媒体信息，不主动打开 STRM 文件、运行 ffprobe 或操作
  Jellyfin 数据库。改变这些边界须有用户需求和明确的范围变更记录。
- 保持流式代理、Range 等媒体响应语义及上游资源释放；避免将完整视频缓冲进内存。
- 分清全局绕过、PlaybackInfo 修改绕过和 Video 重定向绕过的职责，保留全局优先级。
  完整 PlaybackInfo JSON 缓存及其绕过配置已撤除；媒体源直链映射仍保留。
  映射命中、失效、未命中和绕过路径的改变须说明对播放与回退的影响。
- `routers/` 负责路由识别，`handlers/` 负责 HTTP 适配，`policies/` 负责客户端策略，
  `services/` 负责媒体与缓存逻辑，`infrastructure/` 负责上游 HTTP 和日志等基础设施。
  优先沿用现有结构，避免将业务判断放入基础设施。
- 应用日志和交接证据中的 API key、token、Cookie、签名 URL 等认证值必须脱敏。
  业务响应按代理和重定向合同处理，不能因日志要求修改实际播放地址。
- 版本唯一来源为 `version.py`，发布行为变化同步 `CHANGELOG.md` 和适用的 README。
  仅调整开发规则不自动升级产品版本。

## 工作与验证

先检查 `git status --short --branch` 和相关完整 diff，保留已有修改与未跟踪用户文件。
先读相关实现、配置和测试，再制定或执行任务。实施准入、Git 检查点及状态以开发流程为准。

本仓库已有 pytest 测试，可用 `.venv/bin/python -m pytest` 运行；Task 按影响面指定聚焦
命令及最终门槛。纯文档改动检查链接、角色和状态一致性及 `git diff --check`，无需新增
产品测试。本仓库尚无参考项目的 `scripts/check_governance.py`，不得把不存在的检查写成已通过。

只对授权范围作必要变更和隔离验证；真实 Jellyfin、媒体库、生产代理配置或部署需要对应
操作授权，不能从示例地址或历史记录推导。只读检查和已授权任务内的普通实现、修复、
本地验证持续完成，不为每个可逆步骤重复请求许可。

提交使用明确文件清单，不能把用户文件一并暂存。不自动 push、发布、重写历史或破坏性
清理。没有真实提交就保留 `NOT SET`，不编造 Base、Head、用户身份或审查结果。

验证结果区分 PASS、FAIL、NOT RUN、BLOCKED、SKIPPED。单元 / 假上游测试不能冒充真实
Jellyfin 或客户端兼容结果；未运行和受阻项说明原因。具体证据要求见开发流程。
