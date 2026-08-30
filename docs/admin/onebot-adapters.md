# OneBot 适配器状态与选择

QuickQuip 应用层只依赖 NoneBot2 + OneBot V11 契约，不绑定任何具体协议端实现。本文档是 OneBot 协议端（下称"适配器"）的状态入口：QuickQuip 实际依赖的协议边界、各候选适配器的部署 profile 与验证状态、以及更换适配器前的统一验证清单。

更换适配器时，QuickQuip 业务代码无需改动——只需替换协议端部署、调整 `.env` 中的 OneBot 连接配置。历史上 NapCat → LLBot 的迁移即按此方式进行（见 [migration-napcat-to-llbot.md](migration-napcat-to-llbot.md)）。

## QuickQuip 的 OneBot V11 边界

任何 OneBot V11 实现只要满足以下边界，理论上都可对接 QuickQuip；实际可用性以逐项验证为准（见文末验证清单）。

**连接拓扑**

- QuickQuip 默认正向 WebSocket：`ONEBOT_WS_URLS` 指向适配器 WS 服务端，`DRIVER` 须包含 `~websockets`（纯 `~fastapi` 无 WS client 能力）。
- 也支持反向 WS：适配器主动连接 QuickQuip 的 `ws://<bot 地址>:8080/onebot/v11/ws/`，此时 QuickQuip 侧无需 WS client。
- 鉴权统一走 `ONEBOT_ACCESS_TOKEN`（Bearer），两侧同值。

**事件面**

| 事件 | 用途 |
|---|---|
| `message.group` | 群消息入口；依赖 `sender.card` / `nickname` / `role`、`to_me`、reply 段 |
| `message.private` | 私聊消息入口（会话管理、AI 配置、记忆管理） |
| `notice.group_recall` / `notice.friend_recall` | 撤回事件，用于消息上下文清理 |

**action 面**

| 调用 | 用途 |
|---|---|
| `send_group_msg` / `send_private_msg` | 普通发送（段数组格式） |
| `send_group_forward_msg` | 合并转发；自定义节点 `name` / `uin` 必须被尊重 |
| `get_forward_msg` | 合并转发递归读取（深度 8 + 循环检测） |
| `get_record(file, out_format="wav")` | 语音转本地路径，供 ASR 链路使用 |
| `get_msg` | NoneBot 对 reply 段的隐式强依赖（返回被引用消息的 message / sender / user_id） |

**消息段**

- 出站：`text`、`at`、`image`（base64:// 或 http(s) URL）、`record`（base64）。
- 入站：`image` 段 `data.url` 需可直连 GET（LLM 视觉、图生图直下）；语音经 `data.url` → 本地路径 → `get_record` 三级回退。

**运行时职责**（适配器无关）

`.env`（应用密钥与连接配置）、`data/`（持久化数据）、`config/`（运行配置）、Web Admin（5104）、日志目录的职责划分见 [deployment.md](deployment.md)。

## 适配器 profile

每个适配器独立记录部署形态、已验证能力与准入状态。**状态取值**：`生产基线`（默认 Compose 路径指向它）/ `条件性候选`（满足前置验证后可进入迁移评估）/ `NO-GO`（当前不评估，复评需重新举证）/ `不在候选池`。

### LLBot 7.3.2 — 生产基线

| 项 | 值 |
|---|---|
| 上游 | [LLOneBot/LuckyLilliaBot](https://github.com/LLOneBot/LuckyLilliaBot) |
| 镜像 | `initialencounter/llonebot:v7.12.14-7.3.2-45758`（固定 tag，不使用 `latest`） |
| 原理 | PMHQ 外部内存 Hook 真 QQ 客户端（独立进程，QQ 进程空间无修改） |
| 运行形态 | Docker；内置 NTQQ 3.2.25-45758 |
| OneBot 入口 | 正向 WS `3001`（token 鉴权）；反向 WS 需在 WebUI 配置 |
| WebUI | `3080`（扫码登录、网络方式配置） |
| 卷 | `llbot-qq/`（登录态，切勿丢失）、`llbot-data/`（配置与运行时数据） |
| 快速登录 | `QUICK_LOGIN_QQ` 环境变量；有时效性，失效需重新扫码 |
| 已验证能力 | v1.12.2 Windows/Linux Docker 验收：群/私聊、图片、语音 ASR、合并转发、撤回事件全链路真实消息验证 |

**版本 pin 说明**：上游 `latest` 自 2026-08 起漂移到 pmhq 8.x——启动即要求在 auth.luckylillia.com 注册获取 `auth_token`（部分账号需人工审核），新部署会直接卡死在授权提示上。因此模板固定在 7.3.2。如需更换版本：NTQQ 强制升级导致旧构建无法登录时，到上游 Docker Hub 挑选新的 `vX.Y.Z-…` tag 更新模板；升级前先确认目标版本的授权要求。

**风险**：7.x 线已停止更新（最后 tag 2026-05-24），后续维护有限；版本跑道受 NTQQ 强制升级地板限制，到期需更换基座。

**运维细节**（DNS entrypoint 修正、重启与快速登录、登录态过期处理）：见 [deployment.md](deployment.md) 的 LLBot 章节。

### LLBot 8.x — 不在候选池

LLBot 8.x 未经过本项目生产验证，不在当前候选池。

### NapCat — NO-GO，等待严格复评

| 项 | 值 |
|---|---|
| 上游 | [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ)（MIT，全开源） |
| 原理 | Electron/JS 注入真 QQ 客户端 |
| 历史地位 | QuickQuip 曾以 NapCat 为默认适配器，2026-05 因风控波迁出（[迁移记录](migration-napcat-to-llbot.md)） |

**NO-GO 依据**：2026 年 5 月中下旬腾讯高强度风控打击期间，生产环境反复出现频繁 `KickedOffLine`、静默断联（无错误日志停止推送、手机端同步被踢），反检测实验分支（[PR #1768](https://github.com/NapNeko/NapCatQQ/pull/1768)）未合入且未解决问题（社区讨论见 [Issue #1728](https://github.com/NapNeko/NapCatQQ/issues/1728)）。

**复评门槛**（全部满足才重新进入评估）：

- 当前正式 Docker artifact 与目标 QQ 版本（旧版组合的稳定样本不能替代当前版本证据；未合入的反检测 PR 不能视为修复证明）。
- 隔离测试账号，至少 72 小时（最好 7 天）连续运行。
- 覆盖：踢下线、静默断联、重新登录、二维码刷新、手机端并行登录、图片/语音/合并转发、撤回事件。

### SnowLuma — 条件性候选

| 项 | 值 |
|---|---|
| 上游 | [SnowLuma/SnowLuma](https://github.com/SnowLuma/SnowLuma) |
| 原理 | native addon ptrace 注入真 NTQQ 客户端，解析其内部协议包并转换为 OneBot V11 |
| 运行形态 | Docker（官方镜像内置 Linux QQ + noVNC，需 `SYS_PTRACE` 等 capability）/ Windows 原生 |
| OneBot 入口 | 正向 WS `3001`（token 鉴权），与 LLBot 拓扑兼容 |
| 登录 | 仅扫码（noVNC 或桌面 QQ 窗口）；无快速登录对应物 |

**已评估优点**：OneBot action 面覆盖 QuickQuip 主要需求（含 NapCat 扩展 `send_group_forward_msg` / `get_record` 等）；hook 真客户端架构，协议签名由客户端自身完成（公开架构文档与源码可查）；当前无远程授权设施，无人值守仅需本地 EULA 环境变量确认。

**前置条件**（进入生产前必须完成）：

1. **部署授权澄清**：其 TS 层为源码可见非商业许可（非 OSI），EULA 对"并入第三方 Docker 镜像 / 自动化脚本部署"要求书面授权——需与作者书面确认 compose 自动化部署的边界。
2. **运行时出流量审计**：核心 native hook 组件闭源分发，需以容器出向网络目标清单收口隐私边界。
3. **QQ 版本跟进实测**：QQ Linux 3.2.32 存在"hook 连接成功但登录身份不上报"的公开报告（issue 已被自动关闭，未确认修复）；需 pin 一个版本观察完整的 NTQQ 升级适配周期。
4. **兼容实测三件套**：`send_group_forward_msg` 自定义 `uin`/`name` 节点、`get_record` 返回本地路径形态、入站 `image` 段 `data.url` 直连性。
5. **隔离账号试运行**：2-4 周风控观察（全新设备登录，登录态不可从 LLBot 迁移）。

## 迁移前统一验证清单

任何候选适配器进入生产前，单独固定以下证据：

1. 源码、发行物、镜像 tag 与 digest。
2. 目标 QQ 客户端版本、架构和部署形态。
3. OneBot 连接成功与在线状态。
4. 群消息、私聊消息和自消息回显。
5. `text`、`at`、`image`、`record` 的收发。
6. 合并转发节点的自定义 `name`、`uin`、递归读取与长消息回退。
7. `get_record(out_format="wav")` 返回值及 ASR 实际链路。
8. 图片/语音 URL 的有效期、直连性和失败行为。
9. 撤回事件和消息上下文清理。
10. 重启、登录态恢复、断线重连和重新登录。
11. 运行期间的出向网络目标与隐私边界。
12. 账号风控、设备风险、静默断联和不可恢复登录故障。

**证据分级**：静态源码 / 发行物 / 运行时 / 真实消费者 / 长周期稳定性五层，逐层收集。单次成功、绿色 CI 或上游 README 声明不能单独构成生产准入依据。

## profile 状态更新规则

- 状态变更（如候选 → 生产基线、NO-GO → 复评中）须附对应层级的证据链接或验收记录，不接受口头或上游宣传依据。
- 每次适配器相关 release 验收后，更新本页的已验证能力与版本 pin。
- 历史迁移记录（[migration-napcat-to-llbot.md](migration-napcat-to-llbot.md)）只记录当时的迁移决策与环境，不承担现行运维职责；现行部署细节以本页 profile 与 [deployment.md](deployment.md) 为准。
