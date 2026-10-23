# B：Task 规划 / 独立审查

遵循[开发流程](../development-workflow.md)和 [Task 模板](../../Task/TEMPLATE.md)。

## 有 Slice 时

- 先检查 ACTIVE 合同与真实仓库，再围绕成功、失败和恢复闭环规划 Task；定义
  Difficulty、Test Level、范围、验收及四部分测试计划。
- 独立审查完整 Task Base..Implementation Head，核对输入身份、原始证据和关键复现。
  结论为 PASS 或 FIX REQUIRED，不以实施者报告代替审查。
- 每次 PASS 重新评估 Slice 全部 RO，决定下一必要 Task 或整理最终交接包给 A。
  合同实质变化先交 A 修订，B 不自行弱化 RO。

## 仅修复独立小版本 bug 时

- 直接承担缺陷规划：调查触发条件、现状与预期差异、根因依据、受影响入口，定义
  修复目标、边界、不变量、验收和回归。Parent Slice 和 Contract Checkpoint 明确填 N/A。
- 在根 TASK 发布计划并交 Developer；不要求 A 先建 Slice。多模块或高风险只影响
  拆分和测试等级，不自动改变角色路径。
- Developer 交接后履行同等独立审查要求；通过后核对该缺陷全部目标，保存报告、
  协调文档并撤下活动 Task。整个流程由 B 收尾，不补造 A 最终审查。

B 可规划并审查同一任务，但不得同时实施该范围后再自签独立 PASS。
证据不足时明确缺口，已授权范围已满足时不为非阻塞润色不断追加任务。
