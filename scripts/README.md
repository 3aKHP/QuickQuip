# 项目脚本

除远端服务器上运行的巡检与采集脚本外，以下命令均在本地项目根目录执行。仓库受控脚本随代码版本更新，服务器私有编排与通知密钥保存在 Git 忽略的 `prod/` 目录中。

| 目录 | 用途 | 常用入口 |
|---|---|---|
| [deploy/](deploy/README.md) | 云端 Docker 发布、回滚和迁移 | `bash scripts/deploy/deploy-v4.sh`、`scripts/deploy/deploy-v4.ps1` |
| [ops/](ops/README.md) | Bot 在线状态、定时巡检和宿主机指标 | `bash scripts/ops/check_bot_local.sh` |
| [maintenance/](maintenance/README.md) | 数据回灌、词库更新和预置 Skill 同步 | 按对应维护任务选择脚本 |
| `ci/` | 文档、示例、发行说明及依赖检查 | CI 与开发者检查使用 |
| `check/` | 变更风险识别 | `bash scripts/check/deep-cr-trigger.sh dev` |
| `git-hooks/` | 提交与推送检查 | 见[贡献指南](../CONTRIBUTING.md) |

其中 `deploy/server/` 存放发布脚本自动上传到服务器的远端事务执行程序，`deploy/legacy/` 存放归档的旧版发布与配置维护入口。日常使用时只需维护根目录 `.env` 与 `prod/` 下的私有配置，通用脚本直接沿用仓库版本即可。
