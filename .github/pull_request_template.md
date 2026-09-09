<!--
  一个 PR 只承载一个主要意图（docs/dev/branching.md「硬规则」）。

  分级——保留适用的一项（docs/dev/branching.md「变更分级工作流」）：
    Quick PR        Bot Review 一轮
    Standard PR     未参与实现的独立 CR + Bot Review，并行
    Huge PR         先在本地私有工作区写专题计划；全量 Tier 2 Deep-CR
    Hot-Fix         main/tag 阻断回归；合并后回灌 dev
    Release         dev → main；改用 release 模板
  （chore/docs 小改动直接在 dev 上提交，不经过 PR。）

  Issue 关联：解决 Issue 时下方 `Closes #<issue>` 单独一行是权威关闭
  声明；仅关联未完成的用 `Refs #<issue>`，并在 issue 上留跟踪评论。
  无关联 issue 时删除 Closes 行。

  feat/fix/refactor：把本地 changelog 草稿正文附进本 PR 描述，
  便于 review（CONTRIBUTING.md「CHANGELOG 流程」）。
-->

Grade: Quick PR

Closes #<issue>

## Summary

- ...

## Test Plan

- [ ] `.venv/bin/ruff check .`
- [ ] `.venv/bin/python -m pytest -n auto`
- [ ] `.venv/bin/python scripts/ci/validate_toml_examples.py`（配置模板有变时）
- [ ] `pnpm --dir frontend type-check`（前端有变时）
- [ ] `pnpm --dir frontend build`（前端有变时）
- [ ] 与变更类型相称的定向测试 / smoke

## Notes / Follow-ups

- ...
