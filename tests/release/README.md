# 发行物跨版本验收

这些程序用合成配置验证 v1.16.3 到候选发行物的迁移、回退、再次升级及实际 Bot/Web 启动。关闭真实 QQ、LLM 和贴吧连接，使用隔离安装与后台口令。

`storage_scenario.py` 由旧版或候选 Python 分阶段执行，检查数据库与任务状态；`live_candidate.py` 启动候选标准入口、访问后台并确认 Bot 加载新配置。入口为 `scripts/ci/verify_release_upgrade.py`，参数说明见其 `--help`。安装目录必须为可丢弃的新解压包或空目录，已有 `.env` 或非空 `data/` 会被拒绝。

CI 从固定 `v1.16.3` checkout 生成旧数据，Windows 从实际候选 ZIP 重新解压后执行，Docker 使用实际发行镜像且禁用容器外网。日志、依赖清单和版本身份随 Actions artifact 保留。
