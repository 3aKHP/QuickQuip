<!-- Generated from .github/PULL_REQUEST_TEMPLATE/release.md; do not edit -->

<!--
  发布 PR：dev 或 release/* → main（docs/dev/branching.md「发布生命周期」）。
  标题格式：release: vX.Y.Z — <摘要>
  GitHub 不一定展示 PR 模板选择器，可显式指定本模板：
    gh pr create --base main --title "release: vX.Y.Z — <摘要>" \
      --template .github/PULL_REQUEST_TEMPLATE/release.md
  或在 compare URL 追加 ?template=PULL_REQUEST_TEMPLATE/release.md。
-->

## Summary

- 本版自上一 tag 以来承载的变更与重点。
- 目标版本、普通累积版本／特殊里程碑，以及发行范围。
- 目标分支／上一 tag 基线、开发冻结 SHA、最终候选 SHA。
- 合并与最终 tag 分别等待维护者专门人工审核批准。

## Release checklist

- [ ] `pyproject.toml` 版本冻结为目标版本
- [ ] `CHANGELOG.md`：`Unreleased` 汇总为新版本段，更新底部比较链接
- [ ] `skills.example/` 有变动时，Release notes 含「预置 Skill 变动」小节（提示部署者运行 `scripts/sync_preset_skills.py` 同步）
- [ ] 公开文档、配置模板与 `prod.example/` 完成旧术语扫尾
- [ ] `README.md` 功能亮点清单与本版新增能力对照（新功能是否露出、既有描述是否过期）
- [ ] 独立发布专项 CR 完成：交付证据、发布一致性、重要集成边界
- [ ] Blocking 已修复；Should-fix 已修复或附延期理由
- [ ] 特殊里程碑的专项清单已确定并完成（普通 Release 注明不适用）

## Release CR

- 累计交付范围与已有 PR 证据：
- 发布准备新增差异：
- 实际检查的集成边界与代码／测试：
- Blocking / Should-fix / Nits：
- Verified claims / Not verified：

按 `docs/dev/branching.md` 的发布专项 CR 检查交付证据、发布准备差异和重要集成接口；复审范围由证据与具体问题确定。新增功能性修复按自身差异执行 Standard／Huge 规则。

## Test Plan

- [ ] `.venv/bin/ruff check .`
- [ ] `.venv/bin/python scripts/ci/validate_toml_examples.py`
- [ ] `.venv/bin/python -m pytest -n auto`
- [ ] `pnpm --dir frontend type-check`
- [ ] `pnpm --dir frontend test`
- [ ] `pnpm --dir frontend build`
- [ ] self-docs 同步、ID 检查及发布说明提取通过
- 未验证平台／真实渠道与后续安排：

## 人工合并审核

- [ ] 最终候选 SHA 的 CI 通过，评审结论与该 SHA 对应
- [ ] 维护者已专门批准该候选合并；批准记录：

候选变化后更新检查与结论，重新提交审核。合并与 tag 分别记录批准。

## 合并后 / After merge

- [ ] main 合并提交及 CI 核对完成
- [ ] 维护者单独批准 `vX.Y.Z` 的目标 SHA；批准记录：
- [ ] 获批后在 main 创建并推送 tag，触发 release.yml
- [ ] 核对发行 workflow 构建／smoke、tag、版本、Windows ZIP、镜像 revision/digest 与 Release notes
- [ ] main 回灌 dev（可快进则 `--ff-only`，否则开 `chore/back-merge-vX.Y.Z` PR）
- [ ] 核对 dev 下一目标版本（常规发布后默认下一 Patch 的 `-dev.0`），必要时更新 `pyproject.toml`
- [ ] 清理已发布的本地 changelog 草稿与短分支

## Notes / Follow-ups

- ...
