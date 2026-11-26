<!-- Generated from prod.example/README.md; do not edit -->

# 生产配置模板

本目录提供 QuickQuip 生产 Compose 和可选巡检配置。部署前按[协议端接入说明](../docs/admin/onebot-adapters.md#连接-quickquip)准备独立的 OneBot V11 服务。实际配置保存在 Git 忽略的 `prod/`，通用部署与巡检程序由仓库统一分发。

## 首次准备配置

在项目根目录执行：

```bash
mkdir -p prod
cp prod.example/docker-compose.yml prod/docker-compose.yml
```

PowerShell：

```powershell
New-Item -ItemType Directory -Force prod
Copy-Item prod.example/docker-compose.yml prod/docker-compose.yml
```

按部署环境编辑 `prod/docker-compose.yml`，并在根 `.env` 中配置应用凭据和部署方式。使用通知功能时，复制 `sendkey.env.example` 为 `prod/sendkey.env` 并填写运维通知密钥。

升级时直接保留现有的 `prod/` 目录即可，发布脚本会自动上传所需的服务端执行程序。若旧编排中仍捆绑了随栈启动的 LLBot 容器，请参考[拆分迁移步骤](../docs/admin/onebot-adapters.md#从随-quickquip-启动的-llbot-迁移)改为独立部署协议端。

对于旧 `prod/docker-compose.yml` 中保留的 `dockerfile: prod/Dockerfile`，自动发布脚本会在每个候选版本目录内从仓库的 `docker/Dockerfile.prod` 自动生成兼容构建文件，无需手动改动；若在项目根目录直接手动执行 `docker compose build`，请将该字段改为 `docker/Dockerfile.prod`。

## 目录职责

| 路径 | 内容 |
|---|---|
| `prod.example/docker-compose.yml` | 生产 Compose 模板 |
| `prod.example/sendkey.env.example` | 可选运维通知配置示例 |
| `prod/` | 实际 Compose、巡检配置及可选私有部署钩子 |
| `docker/Dockerfile.prod` | 受版本控制的生产镜像构建程序 |
| `scripts/deploy/` | 发布、回滚、迁移及配置管理入口 |
| `scripts/ops/` | 检查 Bot 在线状态、巡检通知和宿主机指标采集 |

发布命令、SSH 设置、存储迁移和恢复步骤见[部署工具指南](../scripts/deploy/README.md)。安装教程见[云端 Docker 部署](../docs/admin/deployment.md)。配置编辑与同步见 [qqconf](../docs/admin/config-workspace.md) 和 [qqsync](../docs/admin/config-sync.md)。

本模板默认启用环境变量在线管理与凭据热更新：由 `env-agent` 单独挂载部署根目录读写 `.env`，`quickquip` 仅挂载只读通信卷获取最新凭据快照，`web-admin` 额外挂载管理写入通信卷以提交修改。升级前的既有私有 `prod/docker-compose.yml` 若未接入 `env-agent`，会保持环境变量管理关闭并沿用容器启动时注入的环境变量；首次接入步骤与日常用法见[环境变量管理](../docs/admin/environment.md)。
