<!-- Generated from docs/admin/game-config.md; do not edit -->

# 游戏系统管理

本文档面向部署者和群管理员，介绍游戏相关的配置、开关和管理命令。

---

## 游戏操作与管理权限

`/game list` 查看已注册的数字炸弹、21 点和俄罗斯轮盘，`/game stop` 结束本群正在进行的游戏。这两个命令向群友开放。牛牛使用独立命令，玩法见[群内小游戏](../user/group-games.md)。

结束 21 点时，发牌前取消会退还赌注，发牌后结束保留已扣赌注。俄罗斯轮盘在准备阶段尚未扣款，游玩阶段取消会退还双方赌注。

群管理员可用 `/rules` 查看已登记规则，再用 `/disable <rule_name>` 或 `/enable <rule_name>` 调整自定义接龙等规则的回复。内置数字炸弹、21 点、俄罗斯轮盘和牛牛没有对应的规则总开关。

金币管理通过 Web Admin“金币”页进行：选择群和账户，填写增减金额及原因，操作写入审计日志。群内金币命令用于签到、余额和排行查询。

---

## 部署者配置

### 配置范围

`config/games.toml` 提供经济和游戏参数，当前没有全局或按群停用游戏的配置项。结束当前局使用 `/game stop`；调整游戏实现和注册方式的开发说明见[游戏框架](../dev/game-framework.md)。

### 游戏参数调整

所有游戏参数集中在 `config/games.toml` 中管理（不存在时使用默认值）。复制 `config/games.toml.example` 为 `config/games.toml` 后修改即可，重启生效。

全部可配项见模板文件注释，关键参数速查：

| 段 | 参数 | 默认值 | 说明 |
|----|------|--------|------|
| `[economy]` | `sign_base_gold` | 10 | 签到基础金币 |
| `[economy]` | `sign_streak_bonus` | 2 | 连续签到加成系数 |
| `[economy]` | `sign_max_streak_bonus` | 30 | 连续签到加成上限 |
| `[economy]` | `affection_per_sign` | 1 | 每次签到增加的好感度 |
| `[number_bomb]` | `min_number` / `max_number` | 1 / 1000 | 数字范围 |
| `[number_bomb]` | `timeout_seconds` | 60 | 超时秒数 |
| `[blackjack]` | `min_bet` | 20 | 最低赌注 |
| `[blackjack]` | `max_players` | 8 | 最大玩家数 |
| `[blackjack]` | `dealer_stand_threshold` | 17 | 庄家停牌阈值 |
| `[blackjack]` | `timeout_seconds` | 90 | 超时秒数 |
| `[russian_roulette]` | `cylinder_slots` | 7 | 弹仓槽数 |
| `[russian_roulette]` | `min_bet` | 20 | 最低赌注 |
| `[russian_roulette]` | `timeout_seconds` | 30 | 超时秒数 |
| `[niuniu]` | `fence_cooldown` | 180 | 击剑 CD（秒） |
| `[niuniu]` | `fenced_protection` | 300 | 被击保护期（秒） |
| `[niuniu]` | `glue_cooldown` | 180 | 打胶 CD（秒） |
| `[niuniu]` | `unsubscribe_gold` | 500 | 注销费用 |
| `[niuniu]` | `decay_rate_high` | 0.01 | 长度 > 50 时按此率缩短；长度 < -50 时，绝对值按此率的 0.4 倍缩小 |
| `[niuniu]` | `decay_rate_normal` | 0.005 | 长度在 -50 至 50 时：正侧按此率缩短，负侧绝对值按此率的 0.8 倍增加 |
| `[niuniu]` | `luck_sigma` | 1.0 | 打胶运势对数标准差（lg(x) ~ N(0, σ)） |
| `[niuniu]` | `fence_luck_sigma` | 1.0 | 击剑运势对数标准差（同上分布） |
| `[niuniu]` | `luck_power` | 0.75 | 运势幂压缩指数（luck^0.75：中位运势行为不变，仅温和化极端运势的实际影响） |
| `[niuniu]` | `glue_neg_shrink_depth` | 1.0 | 打胶凹侧 sublinear 加深强度（越大凹侧萎缩越深，1.0 为线性基准） |
| `[niuniu]` | `fence_critical_multiplier` | 1.8 | 击剑暴击倍率 |
| `[niuniu]` | `fence_dominate_multiplier` | 3.0 | 击剑牛头人支配倍率 |
| `[niuniu]` | `fence_dominate_sever_chance` | 0.4 | 牛头人腰斩触发概率 |
| `[niuniu]` | `fence_dominate_threshold` | 50.0 | 牛头人角色阈值（length ≥ N） |
| `[niuniu]` | `fence_devour_steal_ratio` | 0.3 | 魅魔吞噬窃取比例 |
| `[niuniu]` | `fence_devour_threshold` | 50.0 | 魅魔角色阈值（length ≤ -N） |
| `[niuniu]` | `fence_stake_mode` | "geo" | 击剑赌注基数模式（geo=双方长度几何均值，min=较短方） |
| `[niuniu]` | `fence_stake_base_min` | 0.10 | 赌注基数百分比下限 |
| `[niuniu]` | `fence_stake_base_max` | 0.15 | 赌注基数百分比上限 |
| `[niuniu]` | `fence_stake_balance_floor` | 0.5 | 失衡对局补偿下限（短方/长方） |
| `[niuniu]` | `fence_stake_mf_cap` | 30.0 | 运势乘数上限（极端运势日的单剑波动护栏） |
| `[niuniu]` | `glue_rpm_limit` | 30 | 打胶每分钟每群请求上限 |
| `[niuniu]` | `fence_rpm_limit` | 20 | 击剑每分钟每群请求上限 |
| `[niuniu]` | `rpm_window_seconds` | 60 | RPM 滑动窗口大小（秒） |
| `[niuniu]` | `niuniu_text_path` | `""` | 自定义牛牛文案 TOML 路径（为空使用内置 default） |
| `[niuniu]` | `niuniu_safe_text_path` | `""` | 和谐版牛牛文案 TOML 路径（为空使用内置 safe） |

### 配置文件加载逻辑

```
config/games.toml 存在 → 解析，每段覆盖对应游戏的默认值
config/games.toml 不存在 → 全部使用默认值（无报错）
config/games.toml 解析失败 → load_error 记录错误，全部回退默认值
```

任何未在 TOML 中显式设置的字段保留默认值，无需全量填写。

### 牛牛文案系统

QuickQuip 内置两套牛牛文案预设，通过 TOML 文件驱动，支持按群切换：

| 模式 | 说明 |
|------|------|
| `default` | 原版文案，包含“打胶”“击剑”等措辞 |
| `safe` | 和谐版文案，事件描述和长度评价语调整为更中性的表达 |

**加载逻辑**：`config/games.toml` 中的 `niuniu_text_path` / `niuniu_safe_text_path` 指向自定义 TOML 文件；为空时使用内置默认文案。自定义文案为**逐项覆盖**：事件按 `name`、长度评价与运势提示按区间、消息字典按键覆盖，未写入文件的条目自动从内置 `default` 文案继承补全。

**群级切换**：管理员通过 `/牛牛文案 [模式名]` 命令切换本群文案模式（默认 `default`）。Web Admin 牛牛面板的“文案模式管理”卡片可视化操作群组文案设置。切换记录存储在 `niuniu_group_text` 表中。

**扩展自定义文案**：参考 `config/niuniu_text.toml.example` 的格式，复制后修改对应键，在 `games.toml` 中设置 `niuniu_text_path` 指向该文件即可。

### 数据库文件

| 文件 | 存储内容 | 引擎 |
|------|---------|------|
| `data/game_economy.db` | 金币账户、签到记录 | SQLite |
| `data/niuniu.db` | 牛牛用户数据、操作记录、群文案模式覆盖 | SQLite |
| `data/game_scores.json` | 数字炸弹猜中次数排行 | JSON |

---

## 故障排查

### 游戏无响应

1. 确认游戏是否注册成功：机器人启动时会输出已注册的游戏列表
2. 检查本群是否已有进行中的游戏；需要结束当前局时使用 `/game stop`
3. 自定义接龙检查 `/rules` 中的规则状态；内置游戏检查启动日志和命令返回的错误

### 金币异常

1. 金币数据在 `data/game_economy.db`，可用任意 SQLite 浏览器查看
2. 在 Web Admin“审计”页检查人工余额调整，在游戏记录中核对结算
3. 金币转移在同一事务中执行；失败操作会回滚，可根据日志检查原因

### NiuNiu 数据问题

1. 用户数据在 `data/niuniu.db` 的 `niuniu_users` 表
2. 操作记录在 `niuniu_records` 表，可用于排查异常长度变化
3. 动作冷却存储在内存中，重启机器人后清空冷却状态
4. 文案模式切换通过 `/牛牛文案 <模式名>` 命令或 Web Admin 牛牛面板操作，数据存储在 `niuniu_group_text` 表
