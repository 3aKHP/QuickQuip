<!--
  发布 PR：dev → main（docs/dev/branching.md「发布生命周期」）。
  标题格式：release: vX.Y.Z — <摘要>
  GitHub 不一定展示 PR 模板选择器，可显式指定本模板：
    gh pr create --base main --title "release: vX.Y.Z — <摘要>" \
      --template .github/PULL_REQUEST_TEMPLATE/release.md
  或在 compare URL 追加 ?template=PULL_REQUEST_TEMPLATE/release.md。
-->

## Summary

- 本版自上一 tag 以来承载的变更与重点。
- 目标版本与冻结的候选 SHA。
- 合并后在 main 已接受提交上打 `vX.Y.Z` tag，触发 release.yml。

## Release checklist

- [ ] `pyproject.toml` 版本冻结为目标版本
- [ ] `CHANGELOG.md`：`Unreleased` 汇总为新版本段，更新底部比较链接
- [ ] 公开文档、配置模板与 `prod.example/` 完成旧术语扫尾
- [ ] 分级要求的评审完成（至少 Standard；达到门槛时按 Huge 执行 Deep-CR）

## Test Plan

- [ ] `.venv/bin/ruff check .`
- [ ] `.venv/bin/python scripts/ci/validate_toml_examples.py`
- [ ] `.venv/bin/python -m pytest -n auto`
- [ ] `pnpm --dir frontend type-check`
- [ ] `pnpm --dir frontend build`
- [ ] tag 后发行产物核对：tag、Windows 懒人包、Docker 镜像 revision/digest 与 Release notes 一致
- [ ] 与风险相称的 Windows / Docker / Linux 消费者验收

## 合并后 / After merge

- [ ] 在 main 创建并推送 `vX.Y.Z` tag，触发 release.yml
- [ ] main 回灌 dev（可快进则 `--ff-only`，否则开 `chore/back-merge-vX.Y.Z` PR）
- [ ] 核对 dev 下一目标版本（常规发布后默认下一 Patch 的 `-dev.0`），必要时更新 `pyproject.toml`
- [ ] 清理已发布的本地 changelog 草稿与短分支

## Notes / Follow-ups

- ...
