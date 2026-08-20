# QuickQuip 开发工作流与发布流程

本项目采用精简 GitFlow：`dev` 是日常集成分支，`main` 是发布专线。源码结构规则见 [`style.md`](style.md)，架构与领域所有权见 [`architecture.md`](architecture.md)。

## 硬规则

- 只有收到明确指令时才 commit、push、开 PR、合并或打 tag。
- 一个分支或 PR 只承载一个主要意图；大变更先拆分。
- 行为、配置、协议、部署契约或用户文档变化时，同一变更更新拥有该事实的文档；`feat`、`fix`、`refactor` 依项目约定维护本地 changelog 草稿。
- 不提交 secret、`.env`、`data/`、真实 `prod/`、本机工作材料或生成物。
- 使用 Conventional Commits；PR 保留 merge 历史，不 squash。

## 分支模型

```text
feature/fix/refactor/docs/test/chore/* → dev → release PR → main → tag / GitHub Release
                                      ↑                 │
                                      └── main back-merge┘
hotfix/* (仅生产阻断) ────────────────→ main → dev
```

| 分支 | 职责 | 默认落点 |
|---|---|---|
| `dev` | 日常集成与下一版本候选 | 所有日常 PR |
| `main` | 已发布版本与 release 专线 | release PR、生产 hotfix |
| `feat/*`、`fix/*`、`refactor/*`、`docs/*`、`test/*`、`chore/*`、`perf/*` | 短生命周期工作分支 | `dev` |
| `release/*` | 冻结的发布准备分支（仅当 release 需要额外收束） | `main` |
| `hotfix/*` | `main` 或已发布版本的阻断性修复 | `main` |

分支名采用 `<type>/<topic>` 或 `<type>/v<target-version>-<topic>`。`hotfix/*` 只能从 `main` 创建。

## 变更分级工作流

每次变更都按以下六级之一执行。分级决定分支形态、评审门槛和合并路径；难以判断时向上分级。

| 等级 | 范围 | 分支 | 评审 | 合并 |
|---|---|---|---|---|
| **Develop direct** | chore/docs、小范围、低风险 | 直接在 `dev` | 无 | 用户明确要求后 push |
| **Quick PR** | 小/中型低风险 | 从 `dev` 建短分支 | Bot Review，一轮 | Bot 通过后请求人工合并 |
| **Standard PR** | 中型或高风险域 | 从 `dev` 建短分支 | 独立 CR + Bot Review，并行 | 无未解决 Blocking/Should-fix 后请求人工合并 |
| **Huge PR** | 大型、跨模块、高风险 | 短分支；必要时拆多个 PR | 全量 Tier 2 Deep-CR；每个拆分 PR 保持 Standard | Deep-CR 结论收口后请求人工合并 |
| **Hot-Fix** | `main` 或 tag 的阻断回归 | 从 `main` | 按风险，非平凡变更至少 Tier 1 | PR 到 `main`，再回灌 `dev` |
| **Release** | 公开发布 | `dev → main`；必要时 `release/*` | 独立 CR + 发行物/消费者验收 | 合并 `main` 后打 tag |

### Develop direct

触发条件：仅限 chore/docs、小范围、低风险改动，并且用户明确要求 commit 与 push。完成最小验证后以可审查的 Conventional Commit 直接推送 `dev`；绝不直接推送 `main`。

### Quick PR

触发条件：不属于 chore/docs 的小/中型低风险改动，或作者希望通过 PR 审查的低风险改动。流程为：从 `dev` 创建短分支 → 实现与验证 → 向 `dev` 开 PR → Bot Review 一轮并处理其结论 → 无 Blocking 后请求人工合并。Quick PR 不要求独立 CR。

### Standard PR

触发条件：中型改动，或触及以下任一高风险域但未达到 Huge PR 门槛：provider/MCP 协议和流式行为、模型工具及外部副作用、持久化/迁移/恢复、LLM 触发与群隔离、敏感词和数据卫生、Web Admin API/鉴权、部署与发行、跨模块重构。

流程为：从 `dev` 创建短分支 → 实现与验证 → 开 PR → 并行运行两条评审：

- 未参与实现会话的独立 CR reviewer（Tier 1；可使用 `.claude/agents/quickquip-cr-reviewer.md`）。
- GitHub PR 侧 Bot Review，一轮。

将两条结论汇总为 Blocking、Should-fix、Nits、Verified claims。Blocking 必须修复；Should-fix 除非 PR 记录延后理由，否则修复。完成后请求人工合并。

### Huge PR

触发条件：大型、跨模块、高风险改动，以及面向 `main`、tag 或 release 准备的改动。高风险路径映射和数值门槛以 `scripts/check/deep-cr-trigger.sh <base>` 的输出为唯一权威；它无法解析 base 时 fail-safe 地要求 Deep-CR，而不会假定变更低风险。

开始前在本地私有工作区编写专题计划，写明目标与验收条件、涉及子系统、风险与失败模式，以及拆分方案。必要时把实现拆为多个 Standard PR，每个 PR 只保留一个主要意图。

整体变更执行 Tier 2 Deep-CR：先运行 `scripts/check/deep-cr-trigger.sh <base>`；当输出 `trigger: true` 时，组织五个独立透镜审查：

1. provider 与 MCP 协议、重试、取消、未信任结果；
2. LLM 工具、外部副作用、敏感词与成功语义；
3. SQLite/文件持久化、迁移、锁、关闭与恢复；
4. 消息触发、群隔离、限流、Web Admin 与配置契约；
5. 全局结构、依赖方向、上帝结构与目录归属。

每个候选发现由未产出该发现的 reviewer 重新检查所引契约和 `file:line`，按 0/25/50/75/100 评分；仅保留置信度至少 80、确属本变更引入且契约引用正确的发现。最后再将幸存发现归入 Blocking、Should-fix、Nits、Verified claims。Deep-CR 是 Standard PR 的补充，不替代每个拆分 PR 的独立 CR 与 Bot Review。

### Hot-Fix

仅用于 `main` 或已发布 tag 的阻断回归，例如机器人不能启动、provider 请求全面失败、跨群/敏感数据泄漏、持久化损坏、工具重复副作用或 Web Admin 失去基本可用性。流程：从 `main` 建分支 → 修复最小失败路径 → 可行时增加回归测试 → 更新 CHANGELOG 和相关文档 → 本地验证 → PR 到 `main` → 打 patch tag → 回灌 `dev`。日常紧急修复仍走 `dev`。

### Release

Release 在 `dev` 上冻结版本、CHANGELOG 与发行范围；若需要额外收束，可使用 `release/v<version>-<topic>`。发布评审至少达到 Standard，满足 Deep-CR 触发条件时按 Huge 执行，并完成与风险相称的 Windows/Docker/Linux 消费者验收。详情见下方「发布生命周期」。

## 日常迭代与验证

1. 对齐范围：说明改动、可能涉及的文件、风险和成功条件。
2. 选择以上分级；除 Develop direct 外均从 `dev` 创建短分支。
3. 以小且可审查的提交实现；只有收到指令才 commit。
4. 更新拥有该行为或边界的文档、配置模板与本地 changelog 草稿。
5. 执行与风险相称的验证；PR 合并前按等级完成评审。

| 变更类型 | 最小验证 |
|---|---|
| 仅文档 | 链接与过时术语搜索；可行时运行前端 type-check |
| 小型 Python 改动 | `.venv/bin/ruff check .` 与相关 pytest |
| 小型前端改动 | `pnpm --dir frontend type-check` 与必要的 build/组件检查 |
| LLM/MCP、持久化、消息管线、Web Admin、配置或部署 | Ruff、相关 pytest、前端 type-check（触及前端时）、示例配置校验与实际边界 smoke |
| release / `main` 候选 | 完整 pytest、Ruff、示例配置校验、前端 type-check/build、发行 workflow 产物验证，以及可行的真实消费者验收 |

常用命令：

```bash
.venv/bin/ruff check .
.venv/bin/python scripts/ci/validate_toml_examples.py
.venv/bin/python -m pytest -n auto
pnpm --dir frontend type-check
pnpm --dir frontend build
```

无法执行的网络、Playwright、真实 provider 或平台验证必须在 PR/交接中明确报告为未验证，而不能作为通过。

## 两级代码评审

- **Tier 1（默认）**：对所有 Standard PR 和非平凡 Hot-Fix 运行一轮独立、只读的 CR。`.claude/agents/quickquip-cr-reviewer.md` 是可复用的 reviewer 定义；任何未参与实现的合格审查者均可执行相同契约。
- **Tier 2（Deep-CR）**：仅用于 Huge PR。五个领域 finder 独立寻找候选，再由其他审查者复核证据与置信度。`scripts/check/deep-cr-trigger.sh` 只负责确定是否达到门槛；它不替代实际审查。

评审输出统一使用：Blocking（合并前修复）、Should-fix（除非记录延后理由否则修复）、Nits（可选）和 Verified claims（可记录于 PR/merge notes）。

## 发布生命周期

1. 在 `dev` 冻结候选 SHA、`pyproject.toml` 版本、CHANGELOG、公开文档和配置模板。
2. 汇总本地 changelog 草稿与已合并历史，将 `Unreleased` 形成新版本段并更新比较链接；确认草稿在 release 成功后再清理。
3. 为 `dev → main` 开 release PR，标题为 `release: vX.Y.Z — <摘要>`；完成分级要求的评审和验证。
4. 合并 release PR 后，在 `main` 的已接受提交上创建并推送 `vX.Y.Z` tag。
5. tag 触发 `release.yml`：完整测试、Windows 懒人包、Docker 镜像与 GitHub Release。核对 tag、版本、ZIP、镜像 revision/digest 和 Release notes 一致。
6. 把 `main` 回灌 `dev`：若能快进则 `git merge --ff-only main`；否则开 `chore/back-merge-vX.Y.Z` PR。确认 post-merge CI 后清理已发布的本地草稿与短分支。

## CI、Issue 与文档扫尾

- CI 在 `main`、`dev` push 和 PR 上运行；tag 运行发行 workflow。`main` 应要求 PR、成功 CI 和禁止 force push；`dev` 禁止 force push，Develop direct 例外只适用于 chore/docs。
- 解决 Issue 的 PR 正文使用单独一行 `Closes #<issue>`；仅关联但未完成的使用 `Refs #<issue>`。
- 行为、配置、协议、命令、版本或路径变化后，按范围对 `README.md`、`CHANGELOG.md`、`CONTRIBUTING.md`、`docs/`、配置模板与 `prod.example/` 搜索旧术语。发现陈旧说明在同一变更中更新。
