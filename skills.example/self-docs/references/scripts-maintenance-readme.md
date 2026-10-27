<!-- Generated from scripts/maintenance/README.md; do not edit -->

# 数据与资产维护

在项目根目录运行。执行会修改数据的操作前，按对应指南确认维护范围和备份。

| 程序 | 用途与说明 |
|---|---|
| `backfill_chat_archive.py` | 回灌统一聊天归档，支持 `--dry-run`；见[聊天归档](../../docs/dev/adr/0007-unified-chat-archive.md) |
| `backfill_record_identities.py` | 回填记录身份；见[记录身份维护](../../docs/admin/record-identities.md) |
| `sync_preset_skills.py` | 检查预置 Skill 差异，`--apply` 同步并保留备份；见[Skills](../../docs/admin/skills.md) |
| `reset_niuniu_lengths.py` | 从本地备份生成全员 10 cm 的离线候选库，保留历史与运势；见[牛牛数据维护](../../docs/admin/game-config.md#离线生成牛牛重置库) |
| `refresh_sts_lexicon.py` | 更新 STS 词库资产 |

镜像与发行目录包含归档、身份回填和 Skill 同步程序。配置日常编辑使用 qqconf，配置部署与回流使用 qqsync。
