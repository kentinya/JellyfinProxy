# 开发流程

本文件统一定义角色交接、Slice / Task 生命周期、Git 检查点和验证要求。
长期约束见 [AGENTS](../AGENTS.md)，参考版本与迁移范围见[来源说明](references.md)。
流程规则不追认既有实现已获得独立审查；审查结论以对应记录为准。

## 1. 按工作范围选择路径

“大版本功能”指用户要求新增成体系能力、需要能力合同与架构规划的工作；“小版本 bug”
指修正现有行为与既定预期的偏差。按实际目标分类，不仅依据版本号、文件数量或风险高低。

| 场景 | A | B | Developer |
|---|---|---|---|
| 新增大版本功能 | 规划、激活 Slice，协调架构并作最终审查 | 根据真实仓库规划 Task，逐项独立审查，重评 Slice 全部结果 | 实现活动 Task，验证并提交完成报告 |
| 已有活动 Slice 的实施或修正 | 维护合同；实质变更时修订；最终审查 | 保持原职责，在原合同内规划和审查 | 在原 Task 内完成实现或修正 |
| 独立小版本 bug 修复 | 无需介入，不要求 Slice | 直接规划修复 Task、定义全部验收，独立审查并完成收尾 | 实施和交接要求相同 |

Slice 是一个完整能力的交付合同；Task 是一个可整体审查的行为闭环。
bug Task 可以没有 Parent Slice。无活动 Slice 不阻塞独立 bug 修复；已有 Slice 的历史
记录也不能成为独立 bug 的隐含合同。确实独立的 bug 可单列 Task，但不得用独立路径
绕开活动 Slice 的验收或实质变更要求。

纯文档和流程维护按用户授权直接执行适用检查，无需虚设产品 Slice 或实施 Task。
新增功能若超出原 bug 目标，先记录范围变化并重新分类；只有确属大版本功能才进入 A 路径。
范围已经由用户说明的，直接按其要求执行；实质不明的范围先完成调查，再集中澄清。

角色表示职责而非模型数量。独立 B 审查和 A 最终审查必须由未承担该范围实施的审查者
完成；B 可以同时负责规划和后续独立审查。实施者自检不能改写为独立 PASS。多代理仅在
用户或适用指令明确要求时使用；当前无法取得独立审查时保留待审并交接。

## 2. 状态和实施准入

```text
Task:  PLANNED -> IN PROGRESS -> READY FOR B REVIEW -> PASS
                               FIX REQUIRED -> IN PROGRESS（B 退回后）
Slice: PLANNED -> ACTIVE -> READY FOR A REVIEW -> PASS / CLOSED
                           FIX REQUIRED -> ACTIVE（A 退回后）
```

Task 不使用 CLOSED 状态。没有活动实施任务时，根 `TASK.md` 第一行固定为
`# NO ACTIVE IMPLEMENTATION TASK`。没有活动 Slice 时，根 `SLICE.md` 第一行为
`# NO ACTIVE SLICE`；这不禁止 `TASK.md` 中存在合法的独立 bug Task。

大版本功能的顺序：真实源码基线 → A 提交 ACTIVE Slice 合同 → B 提交 Task 计划 →
Developer 实现检查点 → 独立 B 审查 → 全部结果满足后 A 最终审查。

独立 bug 的顺序：B 调查真实基线与缺陷 → B 提交独立 Task 计划 → Developer 实现
检查点 → 独立 B 审查 → B 核对全部验收并收尾。该路径不等待 A 或 Slice 激活。

实施前核对：

1. 用户授权、工作区已有改动、根 TASK 及其归档计划一致；活动任务身份和工作类型明确。
2. Task 计划已提交，Base 是真实可达的完整 SHA，且是候选实现的祖先。
3. 有 Parent Slice 时，合同已激活且已提交，Task 目标映射到相应 RO；无 Parent Slice
   时，Task 必须自行写全预期行为、范围、验收和回归要求。
4. 执行 `git diff --check`，确认与计划有关的未提交变更均已识别；检查结果只说明相应
   条件，不能代替产品测试或独立审查。

Slice Base 和 Task Base 固定在实施前的真实基线，文档提交不使 Base 自动前移。
`Contract Checkpoint` 指已提交 ACTIVE Slice 合同；独立 bug 填 `N/A — standalone bug`。
`Plan Checkpoint` 指 B 计划提交，Developer 开工时从 Git 解析并记录，不在计划提交中
编造其自身 SHA。规划期尚不存在的实现 Head 一律为 `NOT SET`。

检查祖先关系可使用 `git merge-base --is-ancestor <Base> <Head>`。无真实提交、Git
不可写或缺少真实提交身份时，保留草案及实际阻塞，不捏造 SHA 或另建 Git 目录绕过。

## 3. 规划与范围变更

A 使用 [Slice 模板](../Task/SLICE_TEMPLATE.md) 定义用户结果、Required Outcomes / Surfaces、
架构边界、不变量、非目标、Base、最终验收及 Closure Packet。B 使用
[Task 模板](../Task/TEMPLATE.md) 规划实施，不把预想的接口当成已有代码。

有 Slice 时，B 按成功、失败和恢复闭环拆分，一般为 3～7 个 Task；超过 8 个应检查
是否只是在按文件拆分。依赖真实前序结果逐步规划，不提前制造不存在的 Head。
每次 Task PASS 后，B 重新核对全部 RO，决定下一必要 Task 或移交 A。

独立 bug 通常一个 Task 即可，包含触发条件、复现证据、实际行为、预期行为、
受影响入口、修复边界、成功 / 失败 / 回退验收与必要回归。复杂缺陷可拆成相互依赖
的 bug Task，但应保留共同缺陷目标和验收索引，由 B 负责整体核对，不强造 Slice。

改变 Slice RO、架构边界、安全不变量或验收含义时，A 先修订合同，B 再调整计划。
独立 bug 中由 B 维护计划；超出用户已授权目标的变化先协调范围，不能靠改验收把
失败写成通过。事实修正不抹去历史结论；冻结或缩减范围时记录原因与未完成项。

Developer 按活动 Task 自主完成必要实现、修正、隔离验证与普通本地检查点。
交接报告记录变更、行为、真实实现 Head、测试证据、未满足验收和限制，再置为
`READY FOR B REVIEW`。审查要求修复时追加提交，在原 Task 内继续，不重写已审历史。

## 4. 测试等级

| 等级 | 适用变更 | 最终候选要求 |
|---|---|---|
| T0 | 事实文档或流程维护，无产品行为变化 | 链接、角色 / 状态 / 模板一致性、补丁空白检查 |
| T1 | 只补充已有行为的测试 | 新增与受影响测试 |
| T2 | 单模块、低风险修正 | 聚焦模块测试和适用静态检查 |
| T3 | 路由、HTTP、配置或跨模块接入 | 聚焦、相关集成和受影响回归 |
| T4 | 认证隔离、并发、缓存一致性、持久化或关键播放兼容 | 全部已有回归及适用的运行、故障恢复或打包验证 |

小版本 bug 也可能是 T4；测试等级不决定是否需要 A。业务需求或架构变化不能冒充
T0。B 在计划中写准确命令和适用门槛，不移植 Go 项目的编译、race 或治理命令。

本仓库现有命令示例（仓库根目录，使用已安装 pytest 的虚拟环境）：

```bash
.venv/bin/python -m pytest tests/test_core.py
.venv/bin/python -m pytest tests/test_config.py tests/test_logging.py tests/test_version.py
.venv/bin/python -m pytest
git diff --check
```

具体 Task 按行为选择用例或 `-k` 条件；示例并不要求每次重复运行以上全部命令。
环境缺少 pytest 时如实说明并准备开发依赖，不能因运行时依赖文件没有 pytest 就称测试通过。
二进制或部署包变化再执行[构建与发布](releasing.md)中的相应构建验证。

测试计划包含四部分：开发 / 修正反馈、最终候选门槛、B 独立验证、证据与重跑。
开发先覆盖复现缺陷和直接影响，最终候选执行选定等级门槛。完整套件已覆盖相同聚焦
输入时注明复用，不机械重跑；真实上游、取消 / 断连、回退、内存或打包的单独要求仍须满足。
最终候选的源码、配置或其他可执行输入变化后，按影响重跑；T4 保留完整回归要求。

B 核对原始证据与输入身份，独立复现约定关键行为，不因角色改变就重复所有相同输入，
也不能只看“全绿”标签。只有 B 能调整既定测试计划并写明理由；不得删除测试、弱化
断言或隐藏首次失败、skip 以获取通过。有明确缺陷可先退回，未运行项如实列出。

## 5. 证据与审查

交接须能定位完整源码 SHA、未提交输入的精确摘要、工作目录、命令、Python / 依赖版本、
配置和夹具身份、退出码、数量 / 耗时、原始日志或产物、首次失败与重跑、验收对应项。
证据可保存在 `artifacts/validation-evidence/<run-id>/` 或 CI artifact；说明访问方式，
不能只交临时目录或只有本机可读的链接却称远端已可复核。

证据至少保留至对应 B 最终决定；有 Slice 时保留至 A 最终决定。纯文档后继提交在
可执行输入相同时可复用运行证据，但重新检查受影响文档和状态。没有运行就用
NOT RUN、受阻用 BLOCKED、跳过用 SKIPPED，不能替换为 PASS。

B 审查完整 `Task Base..Implementation Head`，逐项记录验收、证据、剩余问题，给出
PASS 或 FIX REQUIRED。若未取得独立审查，Decision 保持 PENDING，Task 保持待审。
夹具 / 假上游、真实 Jellyfin、真实客户端和打包结果分开报告；单元结果不扩大为兼容结论。

## 6. Git 与交接

提交前审阅 status、完整 diff、未跟踪文件、空白和秘密，仅暂存明确属于任务的文件。
使用普通追加提交保留历史；不自动 push、重写历史、clean / reset 或修改 origin。
本地实现提交不等于部署或发布授权。

报告中的 Implementation Head 指向实际实现候选，不把后续纯文档提交当成新实现。
记录审查范围及文档后继关联，不使用自引用 SHA。计划、完成报告与审查记录保留在
`Task/<task-id>.md` 或明确可达的 Git 检查点，再更新根 TASK 指针；完成后的归档见第 8 节。

## 7. 两条路径的收尾

有 Slice：全部 Task 独立 B PASS 后，B 重评全部 RO，执行合同最终检查，整理 Closure
Packet（Base / Head、RO 对照、Task 索引、证据、不变量、P2 和未运行项），置为
`READY FOR A REVIEW`。A 审完整 `Slice Base..Implementation Head` 和用户结果，记录
Reviewed Range、Decision、P0 / P1 阻塞；结论可为 PASS、FIX REQUIRED 或 PARTIAL / RESCOPE。
只有 A 的最终 PASS 才能将 Slice 标为 `PASS / CLOSED`，部分交付不冒充完整通过。

独立 bug：独立 B PASS 后，B 核对该缺陷全部验收（多个关联 Task 时核对整体结果）、
回归和剩余风险，保存计划 / 完成报告 / 审查结果，撤下根活动 Task。收尾由 B 负责，
不生成 A 审查、Slice Closure Packet 或虚假的 Slice PASS。

两条路径均同步适用的 README、变更记录和状态文件；若工作开始时这些文件不存在，
只为实际需要建立，不复制参考仓库的历史账本。没有活动 Task 时恢复固定首行。
授权范围完成后记录 `Next Action: NONE — AUTHORIZED WORK COMPLETE`，不自动启动下一项。
非阻塞 P2 单列，不无限延长当前交付，也不自动转为新授权。

关闭 Slice 后发现其原范围阻塞，应保留原审查记录；若需要重开该 Slice，仍由 A
维护原合同。用户仅要求独立小版本回归修复时走 B 路径，并关联历史 Slice，不伪造
原 Slice 曾通过新修复的审查。

收尾时仅在有新方法时补充角色指南，用“问题 → 做法 → 适用条件”记录，每次每份
最多 1～3 条，不移植参考项目的复盘结论。

## 8. 文档维护与历史归档

根 `TASK.md` / `SLICE.md` 只保留当前状态与必要入口。完成收尾的 Task、Slice 合同及其
规范性补充移入 `Task/archive/`，更新[历史索引](../Task/archive/README.md)和相对链接；
模板留在 `Task/`。归档不改变 Base、Head、验收、历次退回、审查决定或未运行项。
历史报告中的文件清单和命令保留当时路径，复查对应提交时使用原路径。

被正式计划完全取代的草案可从当前树移除，在历史索引记录替代文档与可达 Git 版本；
仍属于合同的补充必须随合同归档。未完成草案保留明确的 DRAFT 状态，不充当实施入口。
用户文件与未跟踪证据不随文档清理删除。

纯文档维护按 T0 核对本地链接与锚点、角色 / 状态 / 模板一致性，并运行 `git diff --check`。
证据只在本机存在时明确标注访问边界。没有产品行为变化时不升级版本，也不重跑产品测试。
