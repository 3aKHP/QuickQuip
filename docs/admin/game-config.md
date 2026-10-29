# 游戏系统管理

本文档面向部署者和群管理员，介绍 QuickQuip 内置小游戏的日常管理命令、金币经济、数值参数配置（`config/games.toml`）以及牛牛离线重置维护流程。

---

## 游戏操作与管理权限

### 1. 群友可用命令与中途取消规则

- **查看与结束游戏（向所有群友开放）**：
  - `/game list`：查看当前已注册的内置回合制游戏（**数字炸弹、21 点、俄罗斯轮盘**）。
  - `/game stop`：强制结束本群当前正在进行的游戏局。
  - *(注：**牛牛大作战**使用独立的一套中文命令体系，具体玩法与指令详见[群内小游戏手册](../user/group-games.md)。)*
- **中途结束游戏时的赌注退还规则**：
  - **21 点**：在**发牌前**取消游戏，会自动退还玩家已下的赌注；一旦**发牌后**再强制结束，已扣除的赌注将不予退还。
  - **俄罗斯轮盘**：在准备阶段尚未扣款；在**游玩阶段**中途取消，会将双方的赌注原路退还。

<a id="配置范围"></a>

### 2. 群管理员开关与后台金币管理

- **规则开关边界**：
  - 群管理员可使用 `/rules` 查看本群已登记的文本与接龙规则，并用 `/disable <rule_name>` 或 `/enable <rule_name>` 随时启用/停用**自定义接龙**等规则。
  - **注意**：内置的**数字炸弹、21 点、俄罗斯轮盘和牛牛**常驻可用，**没有**对应的规则总开关，也暂无全局或按群停用这些内置游戏的配置项（如需修改游戏底层实现或注册逻辑，请参考开发文档[游戏框架](../dev/game-framework.md)）。
- **金币经济管理**：
  - **群内日常命令**：供群友日常签到、查询余额和查看群内排行榜。
  - **Web Admin 管理员调账**：系统管理员可在 Web 后台的 **“金币”** 页面选择指定群和用户账户，手动填写增减金额及调整原因（所有人工调账操作均会强制记入后台审计日志）。

---

## 部署者配置（`config/games.toml`）

### 1. 配置文件加载与容错逻辑

所有经济与游戏数值参数集中在 `config/games.toml` 中管理。首次自定义时，请将 `config/games.toml.example` 复制为 `config/games.toml`，修改后**重启服务生效**（或通过 Web Admin“配置”页在线编辑后重启）。

```text
• config/games.toml 存在且合法 ──► 解析文件，按段覆盖对应游戏的默认参数（未写的字段自动保留默认值，无需全量填写）
• config/games.toml 不存在     ──► 静默使用全套内置默认值（不报错）
• config/games.toml 语法错误   ──► 记录 load_error 告警日志，并安全回退使用全套内置默认值
```

---

### 2. 游戏与经济关键参数速查表

完整注释请参考 `config/games.toml.example`，各模块核心参数如下：

#### （1）金币经济与回合制棋牌游戏

| 配置段 | 参数名 | 默认值 | 说明 |
|----|------|--------|------|
| **`[economy]`** | `sign_base_gold` | `10` | 每日签到基础金币奖励 |
| **`[economy]`** | `sign_streak_bonus` | `2` | 连续签到每日递增加成系数 |
| **`[economy]`** | `sign_max_streak_bonus` | `30` | 连续签到额外加成的最高上限 |
| **`[economy]`** | `affection_per_sign` | `1` | 每次签到增加的好感度点数 |
| **`[number_bomb]`** | `min_number` / `max_number` | `1` / `1000` | 数字炸弹的初始数字范围 |
| **`[number_bomb]`** | `timeout_seconds` | `60` | 数字炸弹单局超时秒数 |
| **`[blackjack]`** | `min_bet` | `20` | 21 点最低下注金币 |
| **`[blackjack]`** | `max_players` | `8` | 21 点单局最大参与玩家数 |
| **`[blackjack]`** | `dealer_stand_threshold` | `17` | 21 点庄家强制停牌点数阈值 |
| **`[blackjack]`** | `timeout_seconds` | `90` | 21 点单局超时秒数 |
| **`[russian_roulette]`** | `cylinder_slots` | `7` | 俄罗斯轮盘左轮弹仓总槽数 |
| **`[russian_roulette]`** | `min_bet` | `20` | 俄罗斯轮盘最低下注金币 |
| **`[russian_roulette]`** | `timeout_seconds` | `30` | 俄罗斯轮盘单回合操作超时秒数 |

#### （2）牛牛大作战（`[niuniu]`）数值参数

| 类别 | 参数名 | 默认值 | 说明 |
|----|----|------|--------|
| **冷却、保护与限流** | `fence_cooldown` | `180` | 击剑冷却时间 CD（秒） |
| | `fenced_protection` | `300` | 被人击剑后的免战保护期（秒） |
| | `glue_cooldown` | `180` | 打胶冷却时间 CD（秒） |
| | `unsubscribe_gold` | `500` | 注销重开牛牛所需的金币费用 |
| | `glue_rpm_limit` | `30` | 打胶每分钟每群最大请求上限（RPM） |
| | `fence_rpm_limit` | `20` | 击剑每分钟每群最大请求上限（RPM） |
| | `rpm_window_seconds` | `60` | RPM 限流滑动窗口大小（秒） |
| **自然衰减与运势** | `decay_rate_high` | `0.01` | **高水位衰减率**：当 `长度 > 50` 时按此比例缩短；当 `长度 < -50` 时，其绝对值按此比例的 **0.4 倍**向零回缩 |
| | `decay_rate_normal` | `0.005` | **常规区间（`-50` 至 `50`）变化率**：正数侧按此比例缩短；负数侧绝对值按此比例的 **0.8 倍**继续加深 |
| | `luck_sigma` | `1.0` | 打胶每日运势的对数正态分布标准差（$\lg(x) \sim \mathcal{N}(0, \sigma)$） |
| | `fence_luck_sigma` | `1.0` | 击剑每日运势的对数正态分布标准差（分布同上） |
| | `luck_power` | `0.75` | 打胶运势幂压缩指数（计算 $\text{luck}^{0.75}$：保持中位数运势不变，仅温和收敛极端欧皇/非酋运势的影响） |
| | `glue_neg_shrink_depth` | `1.0` | 打胶在负数（凹侧）区间的亚线性（sublinear）加深强度（数值越大凹侧萎缩越深，`1.0` 为线性基准） |
| **击剑对数奖励与倍率** | `fence_reward_base` | `0.8` | 击剑对数奖励公式的基础保底厘米数 |
| | `fence_reward_scale` | `1.5` | 击剑对数奖励的增长强度系数（必须 `> 0`） |
| | `fence_reward_length_scale` | `30.0` | 击剑双方体量尺度分母（必须 `> 0`） |
| | `fence_loss_ratio` | `0.5` | 击剑败者损失长度占胜者奖励的比例（范围 `0`～`1`；与机器人对战时盈亏同样对称生效） |
| | `fence_critical_multiplier` | `1.8` | 击剑普通暴击倍率 |
| | `fence_dominate_threshold` | `50.0` | 触发“牛头人”角色的最低长度阈值（`length ≥ N`） |
| | `fence_dominate_multiplier` | `2.0` | 牛头人支配胜利倍率 |
| | `fence_dominate_sever_chance` | `0.4` | 牛头人触发“重斩”事件的概率 |
| | `fence_heavy_multiplier` | `3.0` | 牛头人重斩奖励倍率 |
| | `fence_devour_threshold` | `50.0` | 触发“魅魔”角色的凹陷深度阈值（`length ≤ -N`） |
| | `fence_devour_multiplier` | `2.5` | 魅魔吞噬胜利奖励倍率 |
| **自定义文案路径** | `niuniu_text_path` | `""` | 自定义原版（`default`）牛牛文案 TOML 路径（留空使用内置文案） |
| | `niuniu_safe_text_path` | `""` | 自定义和谐版（`safe`）牛牛文案 TOML 路径（留空使用内置和谐版文案） |

---

<a id="击剑奖励与配置升级"></a>

### 3. 击剑奖励数学公式与配置升级说明

#### 击剑对数奖励计算公式
设对战双方的当前长度绝对值几何平均体量为 $g = \sqrt{|A| \times |B|}$：
1. **基础体量奖励**：
   $$\text{BaseReward} = \text{fence\_reward\_base} + \text{fence\_reward\_scale} \times \ln\left(1 + \frac{g}{\text{fence\_reward\_length\_scale}}\right)$$
2. **每日运势乘数**：
   $$\text{LuckMult} = 0.5 + 0.5 \times \log_2\left(1 + \sqrt{\text{luck}}\right)$$
3. **最终结算**：将 `基础体量奖励 × 每日运势乘数 × (0.8～1.2 随机浮动) × 特殊事件倍率`，四舍五入保留两位小数（`0.01 cm`）。
   - 两条对数曲线与玩家总长度均**不设硬性上限**；若打出平局则双方均无损益（打胶继续使用其独立的原有运势公式）。

#### 旧版配置升级清理与浮点数精度保护
- **移除已废弃的旧版击剑参数**：从旧版本升级 `config/games.toml` 时，请删掉已废弃的 `fence_stake_*`、`fence_devour_steal_ratio`、`fence_draw_min/max` 以及 `fence_bot_phantom_min/max`（如果未删除，加载时会自动忽略它们并打印日志提示；新增的对数奖励参数若未填写会自动使用默认值，`luck_power` 则继续用于控制打胶）。
- **天文数字长度的精度保护（自动拦截）**：
  由于玩家长度使用 SQLite 双精度浮点数（Float）存储，如果老服历史膨胀导致某玩家长度过大、使得本次计算出的奖励无法在浮点数中精确表示到 `0.01 cm`，击剑命令会**自动停止结算并提示管理员执行离线重置**（本局双方的长度、历史流水与冷却时间均保持原状不变）。此时请管理员按文末的[离线重置流程](#离线生成牛牛重置库)重置数值后再继续游戏。

---

### 4. 牛牛文案系统与存储数据库

#### 双模式文案与逐项覆盖继承
QuickQuip 内置了两套由 TOML 驱动的牛牛文案预设，支持按群独立切换：
- **`default`（原版模式，默认）**：包含“打胶”、“击剑”等原汁原味的趣味措辞。
- **`safe`（和谐模式）**：将所有事件描述与长度评价语替换为更温和中性的表达。

- **如何切换本群文案模式？**
  群管理员可在群内发送 `/牛牛文案 default` 或 `/牛牛文案 safe` 实时切换；系统管理员也可在 Web Admin“牛牛”面板的 **“文案模式管理”** 卡片中可视化切换（各群的文案选择保存在共享配置库 `config/managed/config.db` 的 `niuniu_group_text` 表中）。
- **如何编写自定义文案？**
  参考 `config/niuniu_text.toml.example` 复制出一份新文件，并在 `config/games.toml` 中将 `niuniu_text_path`（或 `niuniu_safe_text_path`）指向你的文件路径。自定义文案支持**增量逐项覆盖**——事件按 `name` 匹配、长度评价与运势提示按区间匹配、消息字典按键名匹配，任何你没有在自定义文件中写出的条目，都会自动从内置 `default` 文案中继承补全。

#### 游戏相关数据存储位置

| 文件路径 | 存储引擎 | 保存的数据内容 |
|------|---------|------|
| `data/game_economy.db` | SQLite | 各群金币账户余额、每日签到与连续签到记录 |
| `data/niuniu.db` | SQLite | 牛牛玩家数据（`niuniu_users` 表）与历史操作流水（`niuniu_records` 表）；注：群文案模式选择保存在共享配置库中 |
| `data/game_scores.json` | JSON | 数字炸弹猜中次数排行榜 |

---

## 故障排查与离线维护

### 1. 常见问题排查

- **发送游戏命令无响应？**
  1. 查看 Bot 启动日志，确认对应游戏模块已在启动时成功注册；
  2. 检查本群是否有一局卡住未结束的游戏，可发送 `/game stop` 强制结束当前局；
  3. 如果是自定义接龙无响应，发送 `/rules` 检查该规则是否被管理员禁用；若是内置游戏报错，请查看 Bot 运行日志中的具体异常信息。
- **金币余额或结算异常？**
  1. 可使用任意 SQLite 工具打开 `data/game_economy.db` 核对原始表数据；
  2. 登录 Web Admin **“审计”** 页检查是否有管理员手动调账记录，并结合游戏记录核对胜负结算；
  3. 单次账户增减与跨账户转账各自有数据库事务保护；一局游戏的下注和派奖分阶段执行。若中途出错，请结合错误日志与已完成的扣款、派奖记录核对余额。
- **牛牛长度变化疑问或冷却重置？**
  1. 玩家当前数值保存在 `data/niuniu.db` 的 `niuniu_users` 表，每一步加减明细均记录在 `niuniu_records` 流水表中，可直接查询溯源；
  2. 玩家的打胶/击剑冷却时间（CD）仅保存在进程内存中，**重启 Bot 后所有人的冷却状态会自动清空**。

---

### 离线生成牛牛重置库

需要开启新赛季，或击剑提示历史长度过大、无法精确结算时，可以把全体玩家的长度重置为 10 cm。下面的流程先保存生产备份，再在本地生成新库，检查通过后才安装。玩家账号、注册时间、运势与旧流水会保留；长度和更新时间会改变，每人新增一条 `reset_length` 流水。

从备份开始到安装检查完成，Bot 和 Web 都应保持停止。期间也暂停会自动启动它们的服务管理任务。这样本地候选才会包含安装前的全部游戏记录。

#### 先选好执行环境

下文的 Python 命令要求 Python 3.11+。路径 `data/niuniu.db` 必须指向这次要维护的数据库；操作前核对实际目录，特别是服务器上的共享数据目录。

| 环境 | 停服与执行位置 |
|---|---|
| 源码安装 | 停止启动 Bot、Web 的终端进程或服务管理任务。在项目根目录使用项目虚拟环境的 Python。 |
| Windows 懒人包 | 关闭 Bot、Web 并确认进程退出。在包根目录使用 `python\python.exe`。 |
| 根目录 Compose 模板 | 在项目根目录执行 `docker compose -f docker-compose.example.yml stop quickquip web-admin`；数据位于本目录的 `data/`。 |
| 平铺生产 Compose | 在 `prod/` 执行 `docker compose --env-file ../.env stop quickquip web-admin`。维护 Python 代码通过下方一次性容器入口执行。 |
| deploy-v4 版本目录 | 先按[手动 Compose 访问步骤](../../scripts/deploy/README.md#manual-compose-access)设置环境并进入当前 Compose 目录；执行 `docker compose --env-file "$QUICKQUIP_ENV_FILE" stop quickquip web-admin`。数据库位于部署根共享 `data/`。 |

以下多行代码块采用 Bash 的 `python - <<'PY'` 写法。不同环境只需替换代码块的入口和结束行，Python 正文共用：

| 环境 | 开始行 | 结束行 |
|---|---|---|
| 源码 Bash | `python - <<'PY'` | `PY` |
| Windows PowerShell | `@'` | `'@ \| & .\python\python.exe -` |
| 根目录 Compose（Bash） | `docker compose -f docker-compose.example.yml run --rm --no-deps -T web-admin python - <<'PY'` | `PY` |
| 平铺生产 Compose（Bash） | `docker compose --env-file ../.env run --rm --no-deps -T web-admin python - <<'PY'` | `PY` |
| 版本目录 Compose（Bash） | `docker compose --env-file "$QUICKQUIP_ENV_FILE" run --rm --no-deps -T web-admin python - <<'PY'` | `PY` |

一次性容器使用现有镜像和共享挂载，执行完 Python 就退出；`--no-deps` 保持 Bot 与 Web 停止。标准模板在 `/app` 执行，下文 `data/` 对应共享数据目录。本地生成候选使用你电脑上的项目 Python，无需启动容器。

#### 第一步：保存现场、归并 WAL 并取得备份

SQLite 可能把刚提交的数据暂存在 `-wal` 文件里。先保存当前主文件及其配套文件，再执行 checkpoint，把这些数据归并进主文件。下面的命令会检查归并是否成功，再切换为单文件日志模式并复制出备份。

在**存放生产数据的环境**执行。`niuniu-before-reset` 和 `niuniu-backup.db` 是本次维护的新名称；如果已存在，换一组名称并同步修改后文路径，保留之前的备份。

```bash
python - <<'PY'
from contextlib import closing
from pathlib import Path
import hashlib
import shutil
import sqlite3

source = Path('data/niuniu.db').resolve()
backup = Path('data/niuniu-backup.db')
if not source.is_file() or backup.exists():
    raise SystemExit('检查源数据库路径，并为备份选择尚不存在的文件名。')
scene = Path('data/niuniu-before-reset')
scene.mkdir()  # 已存在时停止，避免覆盖上次现场
for suffix in ('', '-wal', '-shm', '-journal'):
    item = Path(str(source) + suffix)
    if item.exists():
        shutil.copy2(item, scene / item.name)
with closing(sqlite3.connect(source.as_uri() + '?mode=rw', uri=True, timeout=3)) as db:
    result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
    if result[0] != 0:
        raise SystemExit(f'数据库仍被占用，保持停服并检查连接：{result}')
    if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
        raise SystemExit('未切换到 DELETE 模式，停止后续操作。')
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise SystemExit('数据库完整性检查失败，保留现场并排查。')
with source.open('rb') as src, backup.open('xb') as dst:
    shutil.copyfileobj(src, dst)
with backup.open('rb') as f:
    print('backup_sha256:', hashlib.file_digest(f, 'sha256').hexdigest())
print('备份完成：', backup)
PY
```

成功时会输出 `backup_sha256` 和备份路径，请保存这两项。出现 `database is locked`、归并失败或完整性错误时，保持服务停止，检查是否还有数据库浏览器、维护进程或守护任务占用文件。处理后使用新的现场目录名重试，成功前不要继续安装候选。

云端部署在本地终端把备份下载到本地项目的 `data/niuniu-backup.db`。例如部署根为 `/opt/QuickQuip`：

```bash
scp user@server:/opt/QuickQuip/data/niuniu-backup.db data/niuniu-backup.db
```

将账号、服务器和路径替换为实际值；下载目标也使用尚不存在的文件名。本地安装的备份已经在本机，可直接进入下一步。

#### 第二步：在本地预览并生成候选库

在**本地项目根目录**先核对下载文件的 SHA-256，与第一步输出一致后运行预览：

```bash
python -c "import hashlib; print(hashlib.file_digest(open('data/niuniu-backup.db', 'rb'), 'sha256').hexdigest())"
python scripts/maintenance/reset_niuniu_lengths.py --source data/niuniu-backup.db --output data/niuniu-reset.db
```

Windows 懒人包将命令开头的 `python` 换为 `python\python.exe`。预览输出 `players`（人数）、`existing_records`（旧流水条数）和 `source_sha256`，不会创建候选库。核对人数、记录数符合预期，再执行：

```bash
python scripts/maintenance/reset_niuniu_lengths.py --source data/niuniu-backup.db --output data/niuniu-reset.db --apply
```

成功结果包含 `applied: true`、`added_records` 和 `candidate_sha256`。新增流水数应等于玩家数。脚本还会逐项检查其他玩家字段、全部旧流水与源备份是否保持不变；如果目标已存在，它会拒绝覆盖，请另选候选文件名。

可以再用下面的只读命令核对新旧库；预期得到相同人数、候选中非 10 cm 的人数为 0，且新增流水数等于人数：

```bash
python - <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3

for name in ('niuniu-backup.db', 'niuniu-reset.db'):
    path = Path('data') / name
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise SystemExit(f'{name} 完整性检查失败')
        players, non_ten = db.execute(
            'SELECT COUNT(*), COUNT(CASE WHEN length != 10 THEN 1 END) FROM niuniu_users'
        ).fetchone()
        records = db.execute('SELECT COUNT(*) FROM niuniu_records').fetchone()[0]
        print(name, 'players=', players, 'non_ten=', non_ten, 'records=', records)
PY
```

#### 第三步：上传并安装候选库

云端部署先将候选上传到**生产数据库同一目录**下的新文件。以下命令在本地执行，上传前确认服务器没有同名的待检查文件：

```bash
scp data/niuniu-reset.db user@server:/opt/QuickQuip/data/niuniu.db.new
```

本地安装则在项目根目录将候选复制成 `data/niuniu.db.new`；Bash 使用 `cp -n data/niuniu-reset.db data/niuniu.db.new`，PowerShell 使用 `Copy-Item data/niuniu-reset.db data/niuniu.db.new`。复制前先确认目标不存在。

保持停服，在**生产数据所在环境**执行下面的安装块。将 `expected` 替换为第二步输出的 `candidate_sha256`。它会校验文件、核对所属用户与组，并沿用原库的访问权限后原子替换。

```bash
python - <<'PY'
from contextlib import closing
from pathlib import Path
import hashlib
import os
import sqlite3
import stat

expected = '填入 candidate_sha256'
target = Path('data/niuniu.db').resolve()
candidate = target.with_name('niuniu.db.new')
if not target.is_file() or not candidate.is_file():
    raise SystemExit('正式库或候选库路径不存在。')
if any(Path(str(target) + s).exists() for s in ('-wal', '-shm', '-journal')):
    raise SystemExit('正式库仍有日志配套文件；确认停服并重新完成 checkpoint 后再安装。')
with candidate.open('rb') as f:
    actual = hashlib.file_digest(f, 'sha256').hexdigest()
if actual != expected:
    raise SystemExit('候选 SHA-256 不符，停止替换。')
with closing(sqlite3.connect(candidate.as_uri() + '?mode=ro', uri=True)) as db:
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise SystemExit('候选完整性检查失败，停止替换。')
old, new = target.stat(), candidate.stat()
if (old.st_uid, old.st_gid) != (new.st_uid, new.st_gid):
    raise SystemExit('候选所属用户或组不同；按原库设置后重试。')
os.chmod(candidate, stat.S_IMODE(old.st_mode))
with candidate.open('r+b') as f:
    os.fsync(f.fileno())
os.replace(candidate, target)
print('安装完成：', target)
PY
```

Linux 上若提示所属用户或组不同，可在**宿主机项目根或部署根**用 `ls -l data/niuniu.db data/niuniu.db.new` 查看；具有相应权限时执行 `sudo chown --reference=data/niuniu.db data/niuniu.db.new`，再重试安装。校验失败时保留文件，重新核对来源或上传结果。

安装成功后，在正式库上运行第二步同样的只读查询（文件名改为 `niuniu.db`），确认全员 10 cm、旧流水与新增重置流水数量正确，再启动服务。源码和懒人包使用平时的启动入口；Compose 使用原来的参数执行 `up -d quickquip web-admin`。应用会重新启用 WAL。随后可在后台查看重置流水；群聊对战验证可按自己的维护安排进行。

#### 如果需要回退

回退会恢复备份时点的整个牛牛库。若服务已恢复运行，先保存重置后产生的数据，再决定是否回退；第一步的旧备份不包含这些新记录。

1. 再次停止 Bot、Web 和自动拉起任务；按第一步保存新的现场并归并 WAL，使用新的现场目录和备份文件名。
2. 将保留的 `niuniu-backup.db` 复制或上传为生产目录下的 `niuniu.db.new`。
3. 重用第三步安装块，将 `expected` 改为第一步保存的 `backup_sha256`。校验通过后替换正式库。
4. 核对恢复后的玩家数、长度和旧流水，再启动与备份兼容的程序版本。
