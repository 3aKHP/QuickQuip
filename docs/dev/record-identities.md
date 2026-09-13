# 记录正文与成员身份契约

记忆、语录和留言以 QQ 作为稳定关联键，展示名称按“本群标准身份 → 本群已知名片 → 消息段名称或记录快照 → QQ 占位”解析。群级身份覆盖同 QQ 的全局条目；同名的不同 QQ 保留为多个候选。私聊记录使用既有 `private:<QQ>` 作用域，仅使用全局身份。

## 分层与缓存

`common/identity.py` 定义身份表和合并规则，`common/identity_sources.py` 提供独立于 LLM provider 的文件缓存与身份快照，`app/identities.py` 装配 Bot 和 Web 的来源。`llm/identity.py` 保留兼容导入，`LLMService.group_identities()` 保留服务入口。

Bot 与 Web 使用各自的进程缓存。每份文件至多每 5 秒检查一次修改时间与大小；加载失败记录日志并保留上次有效资料。`/llm reload` 显式失效 Bot 缓存。Web 从共享 `data/stats.json` 读取群名片。Bot 在写入入口复用有界 OneBot 名片查询；列表读取仅使用身份快照。

## 正文与持久化

正文格式为 `{"version": 1, "parts": [...]}`，按数组顺序渲染：

| 类型 | 字段 | 含义 |
|---|---|---|
| `text` | `text` | 普通文字，保留原文 |
| `member` | `qq`、`name`、`usage` | QQ、记录时名称、用途 `mention` 或 `identity` |
| `all` | 无 | 全体成员提及 |
| `media` | `media` | `image`、`record`、`video`、`face`、`forward`、`node` 的可读占位 |

结构化 OneBot 消息逐段转换，命令前缀只从命令文字段剥离。文本段中的 CQ 示例保持文字。引用消息提供字符串时，在适配层解析完整 CQ 码及参数转义。记录正文保留机器人和全体成员提及；纯媒体消息继续无法收藏为语录。

`memories`、`quotes`、`offline_messages` 各新增可空 `content_parts_json`，并各自维护 `<table>_member_refs(group_id, record_id, qq)`。正文、片段与引用索引在同一事务中写入；删除触发器同步清理引用索引。记忆归属 `user_id` 与正文提及分别维护，手动 `/remember` 保持群级记忆。

启动只迁移结构。缺少片段的历史正文在读取时兼容解析合法 CQ 提及及有明确边界的 `@QQ数字`；普通数字、名字和已失去 QQ 的 `@名字` 保持原文。历史来源无法区分 CQ 示例和序列化消息，兼容展示结果可通过原文查看核对。

## API 与编辑

原有路由和 `content` 字段保留，新增 `content_display`、`content_parts`、`user_display`，语录保留 `sender_display`。`content` 为写入时的兼容正文，`content_display` 使用当前身份；成员片段中的 `name` 为快照，读取附加的 `display` 为当前名称。

记忆创建与更新可传 `content_parts`。服务端校验版本、类型、QQ 和长度，再生成兼容正文。仅传 `content` 时作为纯文本保存；仅修改标签或置信度时保留片段。正文变化时重新维护引用索引。后台以文字输入和可删除、可替换的成员块编辑，并提供原文查看。

`GET /ops/api/members/{group_id}?query=...` 受管理后台既有鉴权保护，按本群标准名、别名、名片和 QQ 返回候选，候选附 QQ。明确选择成员才建立引用。

## 检索与消费

记录匹配保留正文关键词能力，并增加明确成员名字、别名、QQ、结构化艾特的关联匹配。匹配、去重在分页和数量限制之前完成；语录作者查询与正文提及查询分别处理。历史兼容解析与显式回填采用同一正文规则。

Chat 自动检索和记忆工具限定在群记忆及当前用户个人记忆内。人物志先按目标 QQ 选择个人记忆，再应用置信度排序和数量上限。归属标签与事实正文分别传给模型。自动记忆继续使用既有事实字符串输出协议和归属约束，模型自行写出的人名保持纯文本。

`/forget` 复用记忆列表匹配规则；`/forget #编号` 精确删除本群记录。成员名字产生多个候选时要求提供 QQ 或编号，保留记录。

历史内容发送为显式 OneBot 文本段；通知发送方单独构造真正的 at 段。原始聊天归档与 Chat 历史冻结内容保持既有契约。游戏、经济账户和榜单不属于本正文模型。

显式迁移与恢复流程见 [管理员迁移说明](../admin/record-identities.md)。
