# Contributing to QuickQuip

感谢参与!本文件是**全贡献者通用**的约定。分支模型与发布流程见 [`docs/dev/branching.md`](docs/dev/branching.md),代码规范见 [`docs/dev/style.md`](docs/dev/style.md)。

## 本地开发目录

每位开发者建议在本地建立一个**不被 git 追踪**的辅助目录,存放草稿、计划、沙箱、私有笔记等。排除方式用 `.git/info/exclude`(本地生效、本身不进仓库),而非 `.gitignore`(后者会被追踪并推送,把该目录的存在暴露到公开仓库):

```text
# .git/info/exclude(示例;目录名按个人习惯)
/local/
```

该目录**分支无关**(不被追踪 → 切换分支内容不变),适合累积跨分支的本地材料。目录名按个人习惯自定。

## CHANGELOG 流程(避免并行冲突)

并行 feature 分支若都直接编辑 `CHANGELOG.md` 的 `## [Unreleased]`,合并时必在该处冲突——代码按文件域隔离不冲突,但 CHANGELOG 是单文件汇聚点。本项目用"本地草稿 + release 汇总"规避:

- **开发期**:`feat/fix/refactor` 级改动**不直接编辑 `CHANGELOG.md`**,改把条目写进你的本地开发目录下的草稿子目录;草稿正文同时附在 PR 描述里,便于 review
- **release 期**:由 release 负责人汇总本地草稿(主,保留"为什么重要"语境)+ 已合并 commit 历史(兜底,防漏),写入 `CHANGELOG.md` 新版本段;release 确认后清掉已发布草稿

草稿存在各自不被追踪的本地目录,并行 feature 互不冲突。release 汇总的具体步骤见 [`docs/dev/branching.md`](docs/dev/branching.md)。

## Commit 规范

Conventional Commits:`<type>(<scope>): <subject>`,多行 body 说明动机。

- type:`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `perf` / `style`
- scope 常用:`llm` / `chat` / `games` / `web-admin` / `niuniu` / `tieba` / `ci` / `docs`
