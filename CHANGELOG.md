# Changelog

本文件记录主仓库中已提交的可见变更。

## Unreleased

- 当前无未发布的主仓库变更。

## 2026-03-16

### fix: apply code review updates

Git: `bfdfcd0`

- 修正 `plugins/tz_tackcer.py` 文件命名并重命名为 `plugins/tz_tracker.py`
- 新增 `plugins/tz_utils.py`，承载时区计算与地点格式化相关纯函数
- 收窄 `like_reply` 触发范围，并为 `i_do` 增加常见口语过滤
- 为复读检测器与接龙管理器增加按群状态上限，控制长期运行时的内存增长
- 新增 `plugins/__init__.py`
- 同步更新测试、README、`.env.example` 与 `dev/` 忽略规则

### init: scaffold QuickQuip project

Git: `3dc2ab0`

- 初始化 QuickQuip 项目骨架
- 建立 NoneBot2 入口、插件目录与规则驱动回复逻辑
- 添加说明文档、环境示例与基础测试脚本

## 版本号对照表

| 版本 | Git |
|------|-----|
| 0.2.0 | `bfdfcd0` |
| 0.1.0 | `3dc2ab0` |
