# Contributing to QuickQuip

感谢参与!本文件是**全贡献者通用**的约定。开发文档职责见 [`docs/dev/README.md`](docs/dev/README.md)，分支模型、变更分级与发布流程见 [`docs/dev/branching.md`](docs/dev/branching.md)，代码规范见 [`docs/dev/style.md`](docs/dev/style.md)。

## 环境搭建

项目用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境与依赖(uv 跨平台,环境搭建命令一致)。Python ≥ 3.11,可编辑安装是 src layout 的硬性要求(让 Python 解析 `src/` 下的包)。

**Linux / WSL2(canonical 环境):**

```bash
uv venv                                          # 创建 .venv(.venv/bin/ 布局)
uv pip install -r requirements-dev.txt           # 运行时 + 开发依赖
uv pip install -e .                              # 可编辑安装(src layout 必须)
.venv/bin/python -m pytest -n auto               # 验证
```

**Windows(PowerShell):**

```pwsh
uv venv                                          # 创建 .venv(.venv\Scripts\ 布局)
uv pip install -r requirements-dev.txt
uv pip install -e .
.venv/Scripts/python.exe -m pytest -n auto
```

环境搭建命令(`uv venv`、`uv pip install`)跨平台一致;运行测试直接调 venv 内 python,路径按平台写(Linux `.venv/bin/python`、Windows `.venv/Scripts/python.exe`),或激活 venv 后直接 `python`。

**AI 协作指令的跨平台处理:** 仓库里的 `CLAUDE.md` 是 Linux canonical 版本(AI 每次会话加载,保持精简、不掺双平台内容)。Windows 协作者请把平台覆盖写入本地(不被追踪)的 `CLAUDE.local.md`:

```pwsh
cp CLAUDE.local.windows.example CLAUDE.local.md
```

`CLAUDE.local.md` 加载优先级高于 `CLAUDE.md`,AI 会话中 Windows 覆盖生效。

**pre-push hook:** 仓库提供跨平台 hook 模板(`scripts/git-hooks/pre-push`,基于 uv),push 前自动跑 ruff + 前端 type-check + 配置校验 + pytest,镜像 CI。git hooks 不被追踪,各贡献者本地安装一次:

```bash
cp scripts/git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

## 本地开发目录

每位开发者建议在本地建立一个**不被 git 追踪**的辅助目录,存放草稿、计划、沙箱、私有笔记等。排除方式用 `.git/info/exclude`(本地生效、本身不进仓库),而非 `.gitignore`(后者会被追踪并推送,把该目录的存在暴露到公开仓库):

```text
# .git/info/exclude(示例;目录名按个人习惯)
/local/
```

该目录**分支无关**(不被追踪 → 切换分支内容不变),适合累积跨分支的本地材料。目录名按个人习惯自定。

## CHANGELOG 流程(避免并行冲突)

并行 feature 分支若都直接编辑 `CHANGELOG.md` 的 `## [Unreleased]`,合并时必在该处冲突——代码按文件域隔离不冲突,但 CHANGELOG 是单文件汇聚点。本项目用“本地草稿 + release 汇总”规避:

- **开发期**:`feat/fix/refactor` 级改动**不直接编辑 `CHANGELOG.md`**,改把条目写进你的本地开发目录下的草稿子目录;草稿正文同时附在 PR 描述里,便于 review
- **release 期**:由 release 负责人汇总本地草稿(主,保留“为什么重要”语境)+ 已合并 commit 历史(兜底,防漏),写入 `CHANGELOG.md` 新版本段;release 确认后清掉已发布草稿

草稿存在各自不被追踪的本地目录,并行 feature 互不冲突。release 汇总的具体步骤见 [`docs/dev/branching.md`](docs/dev/branching.md)。

## Commit 规范

Conventional Commits:`<type>(<scope>): <subject>`,多行 body 说明动机。

- type:`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `perf` / `style`
- scope 常用:`llm` / `chat` / `games` / `web-admin` / `niuniu` / `tieba` / `ci` / `docs`

## PR 与文档扫尾

变更按 [`docs/dev/branching.md`](docs/dev/branching.md) 的 Develop direct、Quick PR、Standard PR、Huge PR、Hot-Fix 或 Release 工作流执行。Standard PR 需要未参与实现的独立 CR 与一轮 Bot Review；Huge PR 还需要 Tier 2 Deep-CR。

PR 描述说明动机、范围、验证方式和未验证项。解决 Issue 时在正文单独使用 `Closes #<issue>`；仅关联工作使用 `Refs #<issue>`。

行为、配置、协议、命令、版本或路径变化后，搜索 `README.md`、`CHANGELOG.md`、`docs/`、配置模板与 `prod.example/` 中的旧术语，并在同一变更更新拥有该事实的文档。
