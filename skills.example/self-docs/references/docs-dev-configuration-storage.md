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

## 定时消息

`ScheduledMessageStore` 合并读取循环定义和一次性待办，对调用方保留统一的任务列表及 CRUD 接口。消费一次性任务只改写待办文件。循环与一次性转换保留任务 ID，通过同一文件锁和一份写入意图记录完成两个文件的更新；中断后下次访问完成转换。

## 部署与维护

`config/managed/` 是部署根下的共享持久目录，Bot 与 Web 均可写入。Compose 在既有文本配置挂载下增加该目录的共享挂载，服务版本切换保留数据库和循环定义。发布上传排除本地 `config/managed/`。

配置备份命令自动保存配置库和配套的 `.runtime.db` 文件；恢复要求服务停止且两个文件齐全。两份文件共同保存本环境的配置与发布执行状态。业务库使用自己的备份流程。

存储迁移要求停服。迁移尚未完成时恢复整批备份；迁移完成后的回退反向转换存储，保留新产生的业务记录、配置修改、任务状态和已消费的一次性任务结果。
