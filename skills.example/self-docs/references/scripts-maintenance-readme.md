<!-- Generated from scripts/maintenance/README.md; do not edit -->

# 数据与资产维护脚本

所有维护脚本均在项目根目录运行（源码环境使用虚拟环境 Python，Windows 懒人包使用解压目录内的 `python\python.exe`）。执行会修改数据库的写入操作前，请先按对应指南停服并备份数据。

| 脚本 | 用途与参考文档 |
|---|---|
| `backfill_chat_archive.py` | 将早期 `data/daily_msgs/`、`data/wordcloud_msgs/` JSONL 历史导入统一归档库 `data/chat_archive.db`（架构背景见 [ADR-0007](../../docs/dev/adr/0007-unified-chat-archive.md)） |
| `backfill_record_identities.py` | 为存量记忆、语录与留言补齐结构化成员引用及索引；操作步骤见[记录身份迁移与验收](../../docs/admin/record-identities.md) |
| `sync_preset_skills.py` | 检测 `skills/` 与 `skills.example/` 的预置包漂移，传入 `--apply` 执行同步并保留备份；见 [Skill 系统](../../docs/admin/skills.md) |
| `reset_niuniu_lengths.py` | 基于本地备份离线生成全员重置为 10 cm 的候选库，保留历史流水与运势；见[牛牛数据维护](../../docs/admin/game-config.md#离线生成牛牛重置库) |
| `generate_responses_web_schema.py` | 从固定上游 Codex 提交生成 `web.run` 工具 schema（需本机安装 Rust 工具链并显式指定输出目录） |
| `refresh_sts_lexicon.py` | 刷新杀戮尖塔（STS）卡牌与词表静态资产 |

Docker 发行镜像与 Windows 发行包内置了前四项运行时维护脚本；日常配置编辑与跨环境同步请分别使用 [`qqconf`](../../docs/admin/config-workspace.md) 与 [`qqsync`](../../docs/admin/config-sync.md)。

## 统一聊天归档回灌示例（`backfill_chat_archive.py`）

从 `v1.15.2` 之前的旧环境升级且需保留历史 JSONL 消息时，先带 `--dry-run` 预览统计，确认无误后去掉 `--dry-run` 正式回灌（Windows 懒人包将 `python` 替换为 `python\python.exe`）：

```bash
python scripts/maintenance/backfill_chat_archive.py --dry-run
python scripts/maintenance/backfill_chat_archive.py
```

脚本会分别输出新增、归因回填、已存在、跳过与写入失败条数（存在写入失败时返回非零退出码）。确认写入失败为 `0` 且归档条数符合预期后，即可清理旧的 `data/daily_msgs/` 与 `data/wordcloud_msgs/` 目录。
