# 流程来源与适配

参考仓库：[kentinya/STRM-Generator-GO](https://github.com/kentinya/STRM-Generator-GO)。
本次核对日期：2026-10-24；固定源码提交：
`4d16846722f31aa9615494b90df715cf4b5bb6df`。

主要依据：

- [仓库约束 AGENTS.md](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/AGENTS.md)
- [开发流程](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/docs/development-workflow.md)
- [A 指南](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/docs/agent-experience/slice-owner-architect-final-reviewer.md)、
  [B 指南](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/docs/agent-experience/task-planner-reviewer.md)、
  [Developer 指南](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/docs/agent-experience/developer-implementation-role.md)
- [Task 模板](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/Task/TEMPLATE.md)

保留能力合同 / 实施单元分工、完整 Base..Head 审查、独立验收、T0～T4、四部分
测试计划、证据复用与如实报告、本地 Git 检查点和授权完成后停止等方法。

按用户要求调整角色入口：只有新增大版本功能由 A 规划 Slice；有 Slice 时 B 维持
原职责；独立小版本 bug 由 B 直接规划、独立审查并收尾，Developer 职责保持一致。
验证命令和业务边界改为当前 Python / FastAPI 仓库的真实情况。

不迁入参考项目的产品需求、Go 工具链、检查脚本、历史 Slice / Task、环境实例、
认证权限或审查结论。本次不新建自动治理程序；准入和状态一致性按开发流程人工核对。
