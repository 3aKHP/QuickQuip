# CI 发行物跨版本验收套件

本目录存放供 GitHub Actions 发行流水线（`.github/workflows/_release-artifacts.yml`）调用的跨版本升级与实机启动冒烟验收套件。

之所以固定以 **`v1.16.3`** 作为旧版测试基线，是因为 `v1.16.3` 是最后一代采用单配置库（`data/llm_config.db` schema 3）的版本；自 `v1.16.4` 起配置与运行存储拆分为双库布局（`schema 4`），需要通过 `migrate-storage` 完成停服迁移。CI 每次构建候选发行物时，都会检出 `v1.16.3` 源码生成真实的旧版基线数据，作为跨代存储迁移、失败恢复、反向回退、再次升级以及候选服务真实启动的自动化回归门禁。验收全程在隔离目录中使用合成配置与一次性管理口令运行，不连接真实的 QQ、LLM 或贴吧服务。

统一编排入口为 `scripts/ci/verify_release_upgrade.py`（完整参数见 `--help`），分阶段调用本目录下的两个测试模块：
- `storage_scenario.py`：分别在 `v1.16.3` 基线与当前候选版本的运行环境中执行数据构造、存储迁移、反向回退、旧版读取核验与二次升级；
- `live_candidate.py`：通过候选版本的标准入口拉起 Bot 与 Web Admin，验证后台 HTTP 登录、API 读写以及 Bot 配置加载心跳。

为防止误改本地真实环境，传入的目标安装目录必须是新建空目录或刚解压的可丢弃发行包；若目录内已存在 `.env` 或非空的 `data/`，脚本会立即拒绝执行。

在 CI 中，Windows 任务直接解压当次构建的候选 ZIP 包运行上述验收，Docker 任务则基于当次构建的发行镜像在断网容器中运行，验收报告与服务日志随 Actions 产物归档留存。Docker 发行流水线同时会运行 `scripts/ci/verify_onebot_compose.py`，用合成环境变量静态渲染并校验两套公开 Compose 模板的服务清单与正、反向 WebSocket 配置。
