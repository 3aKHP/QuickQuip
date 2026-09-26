<!-- Generated from docs/admin/record-identities.md; do not edit -->

# 记录身份迁移与验收

升级后，记忆、语录和留言会新增正文片段列与成员引用索引。应用启动只迁移数据库结构；旧正文继续通过兼容读取展示当前身份，原文始终可查。应用需要安装更新后的 `requirements.txt`。

## 预览与回填

在项目根目录执行，默认只读预览：

```bash
python scripts/backfill_record_identities.py
python scripts/backfill_record_identities.py --database memories --group 123456 --preview-limit 20
python scripts/backfill_record_identities.py --database quotes --record-id 42 --preview-limit 1
```

Docker 镜像与生产部署清单均包含本脚本。使用生产 compose 时，先按 [部署模板的手动 compose 访问说明](../../prod.example/README.md#manual-compose-access) 设置环境并进入 compose 目录，再在应用容器内执行预览：

```bash
docker compose --env-file "$QUICKQUIP_ENV_FILE" exec -T quickquip python scripts/backfill_record_identities.py --preview-limit 0
```

`--database` 可选 `memories`、`quotes`、`offline_messages`、`all`；默认扫描 `data/llm.db`、`data/quotes.db`、`data/offline_messages.db`。`--path` 可指定单个数据库路径，必须同时选择一个具体数据库。`--record-id` 使用数据库主键；语录的数据库 ID 与群内显示序号分别维护。`--preview-limit 0` 仅输出统计，适合生产存量只读盘点。

预览输出原文与当前可读正文，并统计 `scanned`（扫描）、`convertible`（包含可转换片段）、`unparsed`（普通文本或未识别格式）、`existing`（已有片段）、`concurrent_skipped`（并发跳过）、`failed`（失败）、`written`（写入）及 `index_repaired`（补充索引）。普通文本也可以补齐文本片段，原有内容保持不变。

确认预览后显式写入：

```bash
python scripts/backfill_record_identities.py --database memories --group 123456 --apply
```

每个数据库写入前使用 SQLite backup 生成同目录下带 UTC 时间戳的 `.identities-*.bak` 文件，并打印备份路径。每批默认 200 条，可用 `--batch-size` 调整。写入前在事务内核对源正文和片段值，遇到并发编辑或删除时跳过。已有片段保留，仅补充缺失引用索引；重复执行可继续完成剩余记录。任意失败返回非零退出码。

旧数据中合法 CQ 示例可能按历史提及展示；请通过预览和原文查看核对。工具仅依据保存的 QQ 转换，不调用模型推断身份。真实生产数据应先只读统计，再选择维护窗口执行需要的回填。

## 恢复与验收

恢复时停止 Bot 和 Web 的数据库写入，保留当前数据库及其 WAL/SHM 文件，使用选定备份的 SQLite backup 恢复目标数据库，然后重新启动服务。备份包含回填前的整个数据库；恢复范围包含同库其他业务表，应按事故窗口核对新增数据。

发布前在真实群聊核对：

1. 对已登记成员发送带艾特的 `/remember`，在 `/memories` 和后台查看标准身份，原文可查。
2. 引用带 `qq` 和 `name` 的消息收藏语录，确认未登记成员使用可用名字，原文中的 `/remember` 保留。
3. 修改身份名称后等待缓存刷新，确认群命令、后台和记忆模型输入一致；按旧快照、别名和 QQ 查询。
4. 给成员留言并包含后续成员艾特，核对待收列表与投递正文；历史展示仅为文字，投递通知艾特收件人。
5. 核对回填前后匹配总数和分页、重复执行统计、并发跳过以及备份恢复。
