<!-- Generated from prod.example/README.md; do not edit -->

# 生产配置模板

本目录提供生产 Compose 和可选巡检通知配置。实际配置保存在 Git 忽略的 `prod/`，通用部署与巡检程序由仓库统一分发。

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

已有 `prod/` 保留自己的配置。更新项目代码会更新通用程序，部署时自动上传所需服务器程序。

已有 Compose 中的 `dockerfile: prod/Dockerfile` 可继续由部署脚本使用；部署时会从仓库中的生产 Dockerfile 生成发行目录内的兼容构建文件。手动在项目根目录构建时，将该字段更新为 `docker/Dockerfile.prod`。

## 目录职责

| 路径 | 内容 |
|---|---|
| `prod.example/docker-compose.yml` | 生产 Compose 模板 |
| `prod.example/sendkey.env.example` | 可选运维通知配置示例 |
| `prod/` | 真实 Compose、通知配置、LLBot 登录目录及可选私有部署钩子 |
| `docker/Dockerfile.prod` | 受版本控制的生产镜像构建程序 |
| `scripts/deploy/` | 发布、回滚、迁移及配置管理入口 |
| `scripts/ops/` | 检查登录状态、巡检通知和宿主机指标采集 |

发布命令、SSH 设置、存储迁移和恢复步骤见[部署工具指南](../scripts/deploy/README.md)。安装教程见[云端 Docker 部署](../docs/admin/deployment.md)。配置编辑与同步见[qqconf](../docs/admin/config-workspace.md)和[qqsync](../docs/admin/config-sync.md)。
