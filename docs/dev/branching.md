# QuickQuip 分支模型与发布流程

本项目采用**精简 GitFlow**：一条常驻 `dev` 集成分支 + 一条 `main` 发布专线。所有日常改动先进 `dev`，积累到一定量或需要发版时再通过 release PR 合入 `main` 并打 tag。

代码规范与架构硬原则见 [`style.md`](style.md)。本文件只讲分支与发布节奏；Commit message 格式与 CHANGELOG 修改规则遵循项目既有约定（Conventional Commits + Keep a Changelog）。

---

## 分支总览

```
                     ┌─────────────────────────────────────────────┐
                     │                                             ▼
   feature/fix/  ──▶ dev  ──(release PR)──▶  main  ──(tag vX.Y.Z)──▶ GitHub Release
   refactor/chore     ▲                          │
   (短生命周期)        └───── back-merge ────────┘
                          (main → dev)
```

| 分支 | 角色 | 常驻 | 允许的直接 push | 默认 PR base |
|---|---|---|---|---|
| `main` | 发布专线，每个 release commit 对应一个 tag | 是 | 仅 hotfix | — |
| `dev` | 集成分支，所有日常改动的汇聚点 | 是 | chore/docs 小修补 | — |
| `feat/*` / `fix/*` / `refactor/*` / `docs/*` / `chore/*` / `test/*` / `perf/*` | 短生命周期工作分支 | 否 | — | **dev** |
| `hotfix/*` | 紧急修复，仅生产事故时使用 | 否 | — | **main** |

---

## 日常工作流

1. **拉分支**：`git checkout -b <type>/<topic> dev`（base 必须是 dev，不是 main）
2. **实现**：遵循 [`style.md`](style.md) 的单一职责、400 行预警线、分层纪律。feat/fix/refactor 级改动**不直接编辑 `CHANGELOG.md`**，改记一条本地 changelog 草稿（机制见 [`CONTRIBUTING.md`](../CONTRIBUTING.md)），草稿正文附 PR 描述
3. **本地验证**：pre-push hook 会自动跑 ruff + type-check + pytest；失败则修，不加 `--no-verify`
4. **推送 + 开 PR**：PR base 选 dev。PR 描述写清动机、范围、验证方式
5. **CI + Review**：CI 在所有 PR 上自动跑；@khpilot bot 会提供自动化 code review
6. **合并**：`gh pr merge --merge`（保留完整分支历史，**不 squash**）
7. **删分支**：合并后删掉本地和远程 feature 分支

---

## Release 流程

> 触发条件：`dev` 积累了足够多的改动，或外部要求发布新版本。

1. **在 dev 上 bump 版本**：编辑 `pyproject.toml` 的 `version` 字段
2. **整理 CHANGELOG**（遵循项目 Keep a Changelog 约定）：
   - 汇总本期改动：以协作者本地维护的 changelog 草稿（主，机制见 [`CONTRIBUTING.md`](../CONTRIBUTING.md)）+ 已合并 commit 历史（兜底）为来源，按对应分类写入 `## [Unreleased]` 段（草稿暂不清，保留至 release 确认后；见第 6 步）
   - 将 `## [Unreleased]` 改为 `## [X.Y.Z] - YYYY-MM-DD`（版本号不带 `v` 前缀）
   - 在其上方插入新的空 `## [Unreleased]` 段
   - 在文件底部的链接区更新 `[Unreleased]` 和新版本的比较链接
3. **commit + push 到 dev**
4. **开 release PR**：`dev → main`，标题 `release: vX.Y.Z — <一句话摘要>`
5. **合并 release PR**：`gh pr merge --merge`
6. **打 tag**：在 main 上 `git tag vX.Y.Z && git push origin vX.Y.Z`
   - tag push 会触发 `release.yml`：完整 tests + Windows lazy package + Docker 镜像 + GitHub Release
   - release 流水线通过后，清掉已发布的本地 changelog 草稿（草稿不进 git，删除前确认 CHANGELOG 已正确汇总）
7. **back-merge main → dev**：
   - 若 dev 是 main 的直接祖先（常见）：`git checkout dev && git merge --ff-only main && git push`
   - 若 dev 已有新提交（release 后又开了 feature）：开一个 `chore/back-merge-vX.Y.Z` PR，base = dev

**版本号约定**：遵循语义化版本。特殊版本号可作为致敬（如 v1.7.10、v1.8.9 致敬 Minecraft），需在 CHANGELOG 该版本段开头写明致敬理由。

---

## 例外：紧急 hotfix 直接上 main

> 仅当生产事故、安全漏洞等**等不及走 dev → main 双跳**的情况。日常改动禁止走这条路。

1. **拉分支**：`git checkout -b hotfix/<topic> main`（base 是 main）
2. **修复 + 补 CHANGELOG**：hotfix 不走草稿流程，直接编辑 `CHANGELOG.md`（在对应版本段或新建一个 patch 版本段）
3. **PR 回 main**：`gh pr merge --merge`
4. **打 tag**：`vX.Y.Z+1`（patch 号）
5. **back-merge main → dev**：同 release 流程的第 7 步，**不可省略**，否则 dev 永久落后

---

## 分支命名

格式：`<type>/<topic>` 或 `<type>/v<version>-<topic>`

- `type` 用 Conventional Commits 类型：`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `perf` / `style`
- `hotfix` 是**专用类型**，base 必须为 main，见上方[例外：紧急 hotfix](#例外紧急-hotfix-直接上-main) 章节，不纳入常规 dev 工作流
- 发版期对齐的多分支工作用 `<type>/v<version>-<topic>`（如 `feat/v1.9.0-proxy-support`）
- 零星 PR 用 `<type>/<topic>` 即可（如 `docs/branching-model`）

---

## chore / docs 落点

- **默认进 dev**：版本号 bump、typo、文档微调等小修补，直接 push 到 dev 即可（不走 PR 也可，走 PR 更利于触发 CI）
- **禁止直接上 main**：除 release 窗口期的 release commit 和上述 hotfix 例外

---

## CI 与保护规则

- **CI 触发**（`.github/workflows/ci.yml`）：`push` 到 `main` 或 `dev`、以及所有 `pull_request` 都会跑 tests；tag push 触发完整 release 流水线
- **分支保护**（建议配置，对应"dev 为主、main 留例外"模型）：
  - `main`：要求 PR、要求 CI 通过、禁止 force push、留 admin bypass
  - `dev`：允许直接 push（chore/docs 小修补）、要求 CI 通过、禁止 force push
