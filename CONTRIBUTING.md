# Contributing to QuickQuip

感谢参与！本文件说明贡献者如何搭建环境、准备变更和提交 PR。开发文档导航见 [`docs/dev/README.md`](docs/dev/README.md)，分支与发布流程见 [`docs/dev/branching.md`](docs/dev/branching.md)。代码、测试和公开文档分别遵循 [`style.md`](docs/dev/style.md)、[`testing.md`](docs/dev/testing.md) 和 [`documenting.md`](docs/dev/documenting.md)。

## 环境搭建

项目用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境与依赖，需要 Python ≥ 3.11。源码位于 `src/`，开发环境通过可编辑安装加载这些包。

**Linux / WSL2：** 在仓库根目录执行：

```bash
uv venv                                          # 创建 .venv
uv pip install -r requirements-dev.txt           # 运行时 + 开发依赖
uv pip install -e .                              # 加载 src/ 下的包
.venv/bin/python -m pytest -n auto               # 验证
```

**Windows（PowerShell）：** 在仓库根目录执行：

```pwsh
uv venv                                          # 创建 .venv
uv pip install -r requirements-dev.txt
uv pip install -e .
.venv/Scripts/python.exe -m pytest -n auto
```

运行命令使用本平台虚拟环境内的 Python；也可激活虚拟环境后使用 `python`。

**Windows AI 协作配置：** 仓库里的 `CLAUDE.md` 使用 Linux 命令。Windows 协作者可以复制平台覆盖模板，再按本机环境调整：

```pwsh
cp CLAUDE.local.windows.example CLAUDE.local.md
```

`CLAUDE.local.md` 已被忽略。将这份覆盖交给所用协作工具加载，按其中的 Windows 说明执行；具体加载方式按工具配置确定。

**pre-push hook：** [`scripts/git-hooks/pre-push`](scripts/git-hooks/pre-push) 基于 uv，在推送前运行 Ruff、前端 type-check、配置校验、ID 字面量检查与 pytest。每位贡献者在本地安装一次；以下命令在 Bash 或 Git Bash 中执行：

```bash
cp scripts/git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

安装后确认 `git config --get core.hooksPath` 为空；配置了其他钩子目录时，应先处理该配置，模板自检会提示这个问题。可选的 [`pre-commit` 模板](scripts/git-hooks/pre-commit) 从已忽略的根目录 `.redact-ids` 读取私有 ID 清单，在提交前检查泄漏。

## 本地开发目录

草稿、计划、沙箱和私有笔记放在本地辅助目录中。把目录加入 `.git/info/exclude`，使目录及这条排除记录都保留在本机：

```text
# .git/info/exclude（示例，目录名自定）
/local/
```

该目录适合积累跨分支的本地材料。选择与仓库追踪路径没有重叠的目录名，便于切换分支时保留内容。

## CHANGELOG 流程

项目采用“本地草稿 + release 汇总”，减少并行开发对同一版本段的编辑冲突：

- **开发期**：`feat`、`fix`、`refactor` 级改动将用户可感知的变化写入本地草稿，正文附在 PR 描述里供审查；`CHANGELOG.md` 留给发布汇总。
- **发布期**：负责人以本地草稿为主，结合已合并历史核对遗漏，写入新版本段。Release 成功后清理已发布草稿。

汇总与发布步骤见 [`docs/dev/branching.md`](docs/dev/branching.md#发布生命周期)。

## Commit 规范

使用 Conventional Commits：`<type>(<scope>): <subject>`。需要说明动机时增加正文。

- type：`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `perf` / `style`
- scope 常用：`llm` / `chat` / `games` / `web-admin` / `niuniu` / `tieba` / `ci` / `docs`

## PR 与文档扫尾

变更按 [`docs/dev/branching.md`](docs/dev/branching.md) 的 Develop direct、Quick PR、Standard PR、Huge PR、Hot-Fix 或 Release 工作流执行。Standard PR 需要未参与实现的独立 CR 与一轮 Bot Review；Huge PR 还需要 Tier 2 Deep-CR。

PR 描述说明动机、范围、验证方式和未验证项。解决 Issue 时在正文单独使用 `Closes #<issue>`；仅关联工作使用 `Refs #<issue>`。

行为、配置、协议、命令、版本或路径变化后，搜索 `README.md`、`CHANGELOG.md`、`docs/`、配置模板与 `prod.example/` 中的旧术语，并在同一变更更新拥有该事实的文档。
