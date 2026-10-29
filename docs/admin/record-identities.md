# 记录身份迁移与验收

升级后，长期记忆、群语录和离线留言中的成员提及可以跟随当前身份显示，也可以按成员名字、别名或 QQ 号检索。原始正文继续保留，便于核对收藏或写入时的内容。

**需要手动回填吗？** 启动新版应用会自动准备数据库结构，旧正文也能通过兼容读取显示。希望为历史记录补齐结构化片段和成员引用索引时，再运行本文的回填工具。先看预览，确认历史提及被正确识别后再写入。

运行前请安装更新后的 `requirements.txt`。脚本只处理指定的记忆、语录或留言记录，自动备份则保存该记录所在的整个数据库。

---

## 预览与回填

仓库提供了 `scripts/maintenance/backfill_record_identities.py` 维护脚本，用于为存量历史记录补齐正文片段与成员引用索引（Docker 镜像与生产部署清单均已内置该脚本）。

> **建议顺序**：先用 `--preview-limit 0` 查看总数，再选择一个群抽样预览，确认无误后在维护窗口执行写入（`--apply`）。

### 1. 第一步：只读预览与存量盘点（默认不改库）

不带 `--apply` 参数运行时，脚本始终处于**只读预览模式**。

- **本地 / 源码环境（在项目根目录执行）**：
  ```bash
  # 默认扫描全部三个数据库并输出预览
  python scripts/maintenance/backfill_record_identities.py

  # 扫描指定群（123456）的 memories 记录，并在扫描的前 20 条中展示尚未回填项
  python scripts/maintenance/backfill_record_identities.py --database memories --group 123456 --preview-limit 20

  # 按数据库主键 ID 精确预览 quotes 库中的单条记录
  python scripts/maintenance/backfill_record_identities.py --database quotes --record-id 42 --preview-limit 1
  ```
- **生产 Docker Compose 环境（在容器内执行存量盘点）**：
  请先按 [部署模板的手动 Compose 访问说明](../../scripts/deploy/README.md#manual-compose-access) 导出环境变量并进入 Compose 目录，再执行：
  ```bash
  docker compose --env-file "$QUICKQUIP_ENV_FILE" exec -T quickquip \
    python scripts/maintenance/backfill_record_identities.py --preview-limit 0
  ```

#### 命令行参数说明

| 参数 | 取值与使用规则 |
|---|---|
| `--database` | 可选 `memories`、`quotes`、`offline_messages` 或 `all`（默认 `all`，依次扫描 `data/llm.db`、`data/quotes.db`、`data/offline_messages.db`） |
| `--path <路径>` | 自定义单个数据库文件路径（**注意**：使用 `--path` 时，`--database` 必须同时显式指定为某一个具体数据库，不能是 `all`） |
| `--group <群号>` | 仅筛选处理指定 QQ 群的记录 |
| `--record-id <ID>` | 仅处理指定**数据库主键 ID** 的单条记录（注意：群语录的数据库主键 ID 与群内展示序号是分别维护的） |
| `--preview-limit <N>` | 仅在扫描的前 N 条中打印尚未回填记录的详情；不限制扫描或写入总数。设为 **`0`** 时只输出统计 |
| `--batch-size <N>` | 每批读取的记录数，默认 **`200`**；写入时逐条使用事务核对和更新 |

#### 预览输出与统计指标含义

预览模式会对照打印每条记录的“原始文本”与“转换后当前可读正文”，并汇总以下 8 项指标：

| 统计字段 | 含义说明 |
|---|---|
| `scanned` | 本次扫描的记录总数 |
| `convertible` | 包含可转换成员提及/身份片段的记录数 |
| `unparsed` | 纯普通文本或未识别特殊格式的记录数（注：普通文本同样支持补齐基础文本片段，原有内容保持不变） |
| `existing` | 已经存在结构化片段的记录数（写入时会保留原有片段，仅检查并补齐缺失的引用索引） |
| `concurrent_skipped` | 写入前在事务内复核时，发现源正文或片段刚被并发修改/删除而安全跳过的记录数 |
| `failed` | 处理失败的记录数（只要有任何一条失败，脚本退出码即返回非零值） |
| `written` | 实际写入更新片段的记录数 |
| `index_repaired` | 已有片段完整、仅单独补齐了成员引用索引的记录数 |

> **关于历史 CQ 码的兼容提示**：身份转换严格依据已保存的 QQ 号进行。如果历史旧数据正文中包含合法的 `[CQ:at,...]` 文本示例，转换时可能会被识别并按历史提及展示——请在执行前通过预览输出和原文查看功能核对确认。

---

### 2. 第二步：确认无误后执行写入（`--apply`）

确认预览结果符合预期后，加上 **`--apply`** 参数正式执行写入：

```bash
python scripts/maintenance/backfill_record_identities.py --database memories --group 123456 --apply
```

**写入前的备份与检查**：
1. **自动前置备份**：在对每个目标数据库执行写入前，脚本会自动调用 SQLite backup API 在同一目录下生成一份带 UTC 时间戳的备份文件（命名格式为 `<原库名>.identities-<时间戳>.bak`），并在终端打印出完整备份路径。
2. **并发修改检查与继续回填**：每条记录写入前，都会在事务内部再次核对源正文与当前片段值；若期间刚好被用户或后台修改/删除则自动跳过（计入 `concurrent_skipped`）。如果中途中断或跳过，直接**重复运行同一命令**即可继续处理剩余记录。

---

## 恢复与验收

### 1. 如何从自动备份回退数据库？

备份包含回填前的整个数据库。例如恢复 `data/llm.db` 会同时恢复其中的聊天与会话数据。先核对备份之后产生的业务记录，确认接受退回该时点，再执行恢复。

**停止 Bot、Web，以及会自动拉起它们的任务**。保留当前数据库和日志配套文件，随后用 SQLite backup 将选定备份写回原库。下面的代码会保存现场、核对备份完整性和表名，并在恢复后再次检查数据库。

先按[牛牛维护的执行环境说明](game-config.md#先选好执行环境)选择源码、Windows 或一次性 Compose 容器入口。代码块内 `data/` 应指向真实业务数据目录；Compose 的 Bot、Web 已停止时，用 `run --rm --no-deps -T web-admin python -`，不要使用依赖运行中容器的 `exec`。

下面以记忆库为例。把 `source` 换成回填输出的实际备份路径；恢复语录或留言时，同时修改 `target` 和 `table`。`scene` 使用新的目录名，以免覆盖之前的现场。

```bash
python - <<'PY'
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import time

source = Path('data/llm.db.identities-实际时间戳.bak').resolve()
target = Path('data/llm.db').resolve()
table = 'memories'  # 语录：quotes；留言：offline_messages
scene = Path('data/identities-before-restore')
if not source.is_file() or not target.is_file() or source == target:
    raise SystemExit('检查备份与目标路径，二者必须是不同的现有文件。')
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as origin:
    if origin.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise SystemExit('备份完整性检查失败，未恢复。')
    if table not in ('memories', 'quotes', 'offline_messages'):
        raise SystemExit('请选择正确的业务表名。')
    if not origin.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        raise SystemExit('备份不含指定业务表，请重新核对备份来源。')
    scene.mkdir()
    for suffix in ('', '-wal', '-shm', '-journal'):
        item = Path(str(target) + suffix)
        if item.exists():
            shutil.copy2(item, scene / item.name)
    with closing(sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=3)) as restored:
        started = time.monotonic()
        def progress(status, remaining, total):
            if time.monotonic() - started > 3 and status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise RuntimeError('目标库仍被占用，保持停服并检查残留连接。')
        origin.backup(restored, pages=256, progress=progress)
        if restored.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise SystemExit('恢复后的完整性检查失败，保持停服并保留现场。')
        count = restored.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
print('恢复完成：', target, '记录数：', count, '恢复前现场：', scene)
PY
```

目标文件名分别是记忆 `data/llm.db`、语录 `data/quotes.db`、留言 `data/offline_messages.db`。路径不存在、备份损坏或表名不符时，代码会在恢复前退出。若提示数据库忙，继续保持停服并检查残留连接；处理后换一个现场目录名重试。成功后核对记录数量和抽样原文，再恢复服务。

---

### 2. 回填后怎样确认结果？

先检查脚本输出：`failed` 应为 0；`written` 是更新片段的数量，`index_repaired` 是只补齐引用索引的数量。有 `concurrent_skipped` 时说明部分记录在检查期间发生变化，可再次预览后重跑。重复执行后，已经完成的记录通常计入 `existing`，且 `written` 与 `index_repaired` 应为 0；错误或并发修改需按具体输出处理。

在后台抽样对照记录原文、当前显示和成员检索结果。需要验证聊天体验时，可以在测试群补做以下检查：

- [ ] **1. 登记成员的记忆写入与查看**：对已在身份表中登记的群成员发送一条带 `@` 的 `/remember` 记忆，随后在群内执行 `/memories` 以及在 Web Admin“记忆”页查看，确认均展示为标准身份名称，且点击“查看原文”可正常对照。
- [ ] **2. 未登记成员的语录收藏**：引用一条带有发送者 `qq` 和昵称 `name` 的消息执行语录收藏，确认未登记在身份表中的成员能正常回退显示其可用群名片/昵称，且原文中的 `/remember` 等指令文本完整保留。
- [ ] **3. 改名联动与多维检索**：修改某个成员的标准身份名称，等待缓存刷新后，确认群命令输出、Web 后台展示以及注入给 LLM 的记忆输入均已同步更新为新名字；同时测试按该成员的**旧名称快照、别名和 QQ 号**均能正常搜索命中。
- [ ] **4. 离线留言与收件通知**：给某位群成员发送离线留言，并在留言正文中 `@` 另一位成员。核对待收留言列表与最终触发投递时的正文：确认历史留言内容展示为纯文本称呼（不误触发二次群艾特），仅在投递通知头部正常 `@` 提醒收件人本人。
- [ ] **5. 核对数量**：检查回填前后的记录总数与分页展示一致，并核对上文的重复执行统计。备份恢复演练使用数据库副本进行。
