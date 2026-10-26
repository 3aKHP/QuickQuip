<!-- Generated from scripts/README.md; do not edit -->

# 项目脚本

在项目根目录执行这些脚本。通用程序随仓库更新，私有生产配置保存在 `prod/`。

| 目录 | 用途 | 常用入口 |
|---|---|---|
| [deploy/](deploy/README.md) | 云端 Docker 发布、回滚和迁移 | `bash scripts/deploy/deploy-v4.sh`、`scripts/deploy/deploy-v4.ps1` |
| [ops/](ops/README.md) | 登录检查、定时巡检和宿主机指标 | `bash scripts/ops/check_bot_local.sh` |
| [maintenance/](maintenance/README.md) | 数据回灌、词库更新和预置 Skill 同步 | 按对应维护任务选择脚本 |
| `ci/` | 文档、示例、发行说明及依赖检查 | CI 与开发者检查使用 |
| `check/` | 变更风险识别 | `bash scripts/check/deep-cr-trigger.sh dev` |
| `git-hooks/` | 提交与推送检查 | 见[贡献指南](../CONTRIBUTING.md) |

`deploy/server/` 保存部署驱动上传的事务执行程序；`deploy/legacy/` 保存历史部署和配置恢复入口。部署者配置 Compose 与根 `.env`，通用脚本保持仓库版本。
