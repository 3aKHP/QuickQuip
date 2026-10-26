<!-- Generated from docs/dev/configuration-storage.md; do not edit -->

# 配置与运行存储

本文面向维护配置、业务持久化及部署代码的开发者，说明数据归属、发布输入和读写入口。已有安装的切换步骤见[存储迁移](../admin/storage-migration.md)，架构依据见 [ADR-0021](adr/0021-configuration-runtime-storage-separation.md)。

## 数据归属

| 存储 | 内容与所有者 |
|---|---|
| `config/managed/config.db` | schema 4；LLM 文档与关系投影、配置修订与历史、`scope_settings`、`niuniu_group_text` |
| `config/managed/scheduled_messages.json` | 循环任务定义，由定时消息服务读写 |
| `data/config_runtime.db` | schema 1；任务固定输入、任务队列、发布指针、加载状态和心跳 |
| `data/llm.db` | 对话、记忆、会话、纪元及 Agent 执行；`agent_scopes.private_chat_active` 保存私聊响应状态 |
| `data/niuniu.db` | 玩家与游戏操作记录 |
| `data/pending_scheduled_messages.json` | 一次性待办，由定时消息服务消费 |

其余独立配置文件保留原格式。聊天归档、报告、统计、审计、登录会话、用量和 Trace 等存储由各自领域维护。

配置修订、备注与历史属于本环境的配置管理数据。配置交换读取可编辑内容；目标环境沿用自身修订、历史和发布流程。

## 配置读写入口

`ConfigService` 负责 LLM 草稿、修订和发布请求，`ScopeSettingsRepository` 负责群与私聊的参数覆盖，`TextModeRepository` 负责群级游戏文案模式。Web 路由和业务服务通过这些入口操作配置。业务库的初始化只建立本领域运行表。

LLM 文档保存草稿后单独应用。作用域参数和游戏文案选择保存后供后续操作读取。配置写入沿用维护锁，配置同步维护期间返回忙碌状态；会话状态和业务记录继续由运行存储维护。

私聊的启停独立于参数覆盖。开始、结束和恢复会话时，活跃标志与业务会话变更在同一事务提交。Web 暂停和恢复响应只改变活跃标志，保留历史；重置参数清除覆盖项。

## 发布与执行

入队先固定配置历史，再把执行输入及任务写入运行库。运行库的 `execution_snapshots` 是任务绑定的不可变输入副本；后续草稿编辑保持与该输入隔离。入队失败可能留下未执行的历史快照，重试使用既有请求 ID 幂等规则。

Bot 从运行库读取任务固定输入，检查租约和启动身份，并在同一运行库事务中更新发布指针与任务阶段。实际加载完成后回报版本和组件状态。草稿修订、已发布版本和实际加载版本通过配置服务汇总，接口形状见[配置 API](llm-configuration-api.md)。

部署服务可在持有 Bot 生命周期独占锁时离线发布。目标通过本地配置、资产、凭据及作用域引用校验后，保存不可变执行输入和发布结果；最后实际加载版本保留，旧心跳与运行所有权失效。停止的 Bot 下次启动读取新发布版本。存在独立未完成应用时，离线发布报告冲突。

部署快照与独立编辑草稿可以使用不同修订。新修订号高于配置库中已分配的全部草稿、历史和快照编号，避免后续编辑复用发布输入的身份。发布规则见 [ADR-0023](adr/0023-online-and-offline-configuration-publication.md)。

## 原生服务控制

`bot.py` 与 `web_api.py` 的主入口共用 `configuration.process_supervisor`，Windows 的 `start.bat` 使用这些入口。父进程保留终端与日志流，通过 `data/qqconf/services/` 下的私有请求和回执控制子进程；子进程持有原有 Bot/Web 生命周期锁。暂停等待正常退出清理，恢复创建新子进程，父进程退出时子进程也会清理退出。Compose 提供容器的进程管理。

`configuration.process_control` 按项目与服务查询状态并请求暂停、恢复或停止，通过受管记录和锁识别服务。部署调用方记录各服务的原运行状态，在完成安装并释放停止证明后恢复应运行的服务。

## 定时消息

`ScheduledMessageStore` 合并读取循环定义和一次性待办，对调用方保留统一的任务列表及 CRUD 接口。消费一次性任务只改写待办文件。循环与一次性转换保留任务 ID，通过同一文件锁和一份写入意图记录完成两个文件的更新；中断后下次访问完成转换。

## 部署与维护

`config/managed/` 是部署根下的共享持久目录，Bot 与 Web 均可写入。Compose 在既有文本配置挂载下增加该目录的共享挂载，服务版本切换保留数据库和循环定义。发布上传排除本地 `config/managed/`。

配置备份命令自动保存配置库和配套的 `.runtime.db` 文件；恢复要求服务停止且两个文件齐全。两份文件共同保存本环境的配置与发布执行状态。业务库使用自己的备份流程。

存储迁移要求停服。迁移尚未完成时恢复整批备份；迁移完成后的回退反向转换存储，保留新产生的业务记录、配置修改、任务状态和已消费的一次性任务结果。

本地 [qqconf](config-workspace.md) 以独立工作副本管理可编辑配置。根 `.env` 选择 cloud 时写真实配置，选择 local 时写完整 `.config-staging/`。qqsync 安装暂存或单向同步真实配置，保持原服务状态；Bot/Web 标准入口在配置安装未完成时等待恢复。


## 同步事务与发布布局

`config_sync.session` 拥有发送端协调、方向及服务状态记录；`installation` 拥有接收端的配置维护、安装、验证和恢复。`reconciliation` 按字段合并，确认基线时仅接纳两端相同字段。发送端配置保持不变；未发布草稿回流不推进 published 通道基线。

逻辑快照包含 LLM 文档、作用域参数、游戏文案选择和受管文本。`layout` 将逻辑名称映射到真实路径：版本目录布局中，根 `.env`、data 配置、`config/managed/` 与运维通知文件位于共享根，其余配置位于选定 release。`ConfigService` 可以显式接收 data 目录，使候选资产校验与共享配置、运行数据库协作。

接收端在配置写锁下保存目标及前像，通过维护记录阻止独立写入。纯 LLM 热应用使用固定的部署快照，编辑草稿可以保留另一修订。停服安装持有 Bot/Web 两把生命周期锁，写完资产与逻辑配置后离线发布，再允许服务启动。恢复重新安装原配置并处理本次发布任务；历史快照、其他任务和业务库继续保留。

客户端记录位于 `data/config-sync/qqsync/client.json`，接收端记录位于 `qqsync/operations/`，共同基线位于 `qqsync/peers.json`。重复命令使用记录中的原路由、目标和服务状态。部署脚本的分阶段入口与独立命令共享接收端安装；代码部署在镜像构建前暂存配置，停服发布后切换版本，健康检查完成后确认。选择依据见 [ADR-0024](adr/0024-directional-configuration-deployment.md)。
