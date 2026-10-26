---
status: Accepted
superseded_by: []
---

# ADR-0025：统一分发运维程序并分离生产配置

- 记录日期：2026-10-27
- 原始决策日期：2026-10-27

## 背景

生产模板同时包含程序、配置示例和历史维护入口。部署者复制整套目录后会在私有副本中修改连接参数。公共程序升级需要与这些副本人工合并，存储迁移或配置协议更新容易遗漏。

## 决定

通用部署程序放在 `scripts/deploy/`，其中 `server/` 保存远端事务执行程序，`legacy/` 保存历史部署与恢复入口。巡检程序放在 `scripts/ops/`，数据和资产维护放在 `scripts/maintenance/`。这些程序由 Git 统一维护。

`prod.example/` 分发生产 Compose 与通知配置模板。私有 `prod/` 保存真实 Compose、通知配置和协议端登录资产。部署特有的外部集成可放在 `prod/hooks/deployment.sh`，由通用程序在成功发布或回滚后调用；该私有程序按部署资产上传，其内容由部署者维护。生产构建程序放在 `docker/Dockerfile.prod`，环境差异通过根 `.env` 和 Compose 构建参数表达。

部署与配置同步从根 `.env` 读取连接默认值，命令行参数可覆盖。服务器程序随部署自动安装到 `scripts/ops/`。发行目录中的 `prod/docker-compose.yml` 和部署根的 `prod/sendkey.env` 保持现有路径；历史事务恢复继续识别旧发行目录中的程序位置。

## 方案与理由

继续复制整套程序需要部署者处理代码与私有配置的合并。统一分发程序后，代码升级负责更新行为，私有目录承载环境差异。按任务分类提供稳定入口，可以保留模块职责并缩小日常需要关注的文件范围。

## 影响

Docker 构建、上传清单、维护命令与文档引用采用新路径。已有私有程序副本先归档，再保留配置；旧版本的事务与回滚资料按原协议使用。已有 cron 在新版服务器程序安装后调整到 `scripts/ops/`。

本决定补充事务部署的文件所有权和分发方式，发布与失败恢复继续遵守 ADR-0011。

## 依据与相关契约

- [脚本导航](../../../scripts/README.md)
- [生产配置模板](../../../prod.example/README.md)
- [事务部署](0011-transactional-deployment-recovery.md)
- [工作副本与单向配置部署](0024-directional-configuration-deployment.md)
