# 接入 OneBot V11 协议端

QuickQuip 基于 NoneBot2 通过 OneBot V11 协议收发 QQ 消息。协议端作为独立服务由管理员自行安装与维护，单独负责 QQ 账号登录、登录态持久化、版本升级与掉线恢复。本文说明如何建立 QuickQuip 与协议端的连接，以及各项功能所需的协议端能力。

## 连接 QuickQuip

先按所选协议端的文档启动服务并登录机器人 QQ 账号。启用连接鉴权时，在 QuickQuip 的根目录 `.env` 与协议端配置中填写完全一致的 `ONEBOT_ACCESS_TOKEN`，WebSocket 握手将通过 Bearer 令牌完成认证。请根据部署拓扑选择以下任一连接方式：

### 正向 WebSocket

由 QuickQuip 主动连接协议端。在根 `.env` 的 `ONEBOT_WS_URLS` 中填写从 **Bot 进程所在环境**可达的协议端地址。例如，Bot 与协议端运行在同一台宿主机上，且 Bot 采用宿主机 Python 直接启动时：

```env
DRIVER=~fastapi+~websockets
ONEBOT_WS_URLS=["ws://127.0.0.1:3001/"]
ONEBOT_ACCESS_TOKEN=replace_with_your_token
```

示例中的 `3001` 请替换为协议端实际监听的正向 WebSocket 端口。当 Bot 运行在 Docker 容器内时，`127.0.0.1` 指向 Bot 容器自身，请改为填写从 Bot 容器内部可访问的宿主机／网桥地址，或将双方容器接入同一个外部 Docker 网络后通过服务名连接。

### 反向 WebSocket

由协议端主动连接 QuickQuip。在根 `.env` 中设置 `ONEBOT_WS_URLS=[]`，并在协议端配置中填入 `ws://<Bot 可达地址>:8080/onebot/v11/ws` 及相同的访问令牌（端口号以 Bot 实际监听端口为准）。反向连接要求驱动器支持 WebSocket 服务端，`.env.example` 默认提供的 `DRIVER=~fastapi+~websockets` 可直接使用。

QuickQuip 的 Docker 模板在容器内固定监听 `8080` 端口：若双方容器位于同一共享网络，协议端可直接填写 `ws://quickquip:8080/onebot/v11/ws`；若协议端从 Docker 网络外部接入，则需在实际使用的 Compose 文件中将 Bot 的 `8080` 端口映射到协议端可达的宿主机网卡地址，并按需通过防火墙限制来源地址。

### 两个独立 Compose 使用共享网络

当 QuickQuip 与协议端各自使用独立的 Docker Compose 编排时，推荐在宿主机上创建一个外部共享网络将两者打通。以下以 `onebot-shared` 为例：

```bash
docker network create onebot-shared
```

将下列网络配置合入实际使用的 QuickQuip Compose 文件（使用 `deploy-v4` 时编辑本地 `prod/docker-compose.yml`；若 `quickquip` 服务已配置其他网络，保留原有列表并追加 `onebot-shared`）：

```yaml
services:
  quickquip:
    networks:
      - default
      - onebot-shared

networks:
  onebot-shared:
    external: true
```

同时在协议端的 Compose 文件中将协议端服务加入 `onebot-shared` 网络。假设协议端在该网络中的服务名为 `onebot`、正向 WebSocket 端口为 `3001`，则在 QuickQuip 根 `.env` 中设置 `ONEBOT_WS_URLS=["ws://onebot:3001/"]`。启动或重建 Bot 后，查看日志确认目标 QQ 号已成功连接，并在测试群发送“早安”验证收发。后续若修改了连接地址或令牌，源码运行需重启 Bot 进程，Docker 部署需基于更新后的 `.env` 重新创建 Bot 容器。

<a id="quickquip-的-onebot-v11-边界"></a>

## 各功能所需的协议端能力

群聊与私聊的基础收发要求协议端支持 `message.group`、`message.private` 事件以及 `send_group_msg`、`send_private_msg` 接口；采用正向 WebSocket 连接时，协议端还须在建连后上报携带 `self_id` 的 `meta_event.lifecycle`（`connect`）生命周期事件，供 NoneBot 注册机器人账号。**协议端的消息上报格式必须设为消息段数组（`array`）**（请勿设为 CQ 码字符串），QuickQuip 发出的消息参数同样使用消息段数组。

| 功能模块 | 所需的事件、API 调用或消息段支持 |
|---|---|
| 命令解析与身份识别 | 群消息事件需包含 `sender.card`、`nickname` 和 `role`；真实艾特使用 `at` 消息段；查询群成员名片调用 `get_group_member_info`，调用失败时回退显示已有缓存名称或 QQ 号。 |
| 引用消息与引用回复 | 解析入站 `reply` 消息段需要协议端支持 `get_msg` 并返回被引用消息正文与发送者 ID；开启引用回复时出站消息会附带 `reply` 段，若协议端明确报错拒绝该段，QuickQuip 会自动剥离引用头、降级重发纯正文。 |
| 自身发言归档 | 协议端需支持并开启扩展事件 `message_sent`；QuickQuip 收到机器人在群内发出的自身消息事件后将其归档一次，供每日总结、周报与月报汇总上下文。 |
| 消息撤回同步 | 需要上报 `notice.group_recall` 与 `notice.friend_recall` 事件，用于从近期缓冲与会话上下文中清理已撤回消息。 |
| 合并转发 | 长消息与报告发送依赖 `send_group_forward_msg` 支持自定义节点字段 `name`、`uin`；解析群友发来的合并转发卡片依赖 `get_forward_msg` 支持读取嵌套节点。 |
| 图片收发 | 出站 `image` 消息段使用 `base64://` 或 HTTP(S) URL；入站图片消息段的 `data.url` 需能从 Bot 运行环境直接下载。 |
| 语音收发与转写 | 出站 `record` 消息段支持 `base64://`。入站语音若已由协议端附带转写文本则直接复用，否则需提供可读的音频 URL 或本地文件路径：QuickQuip 会按字节魔数自动将原始 SILK（含腾讯前缀）解码为 16 kHz WAV；原始 AMR／AMR-WB 在运行环境装有系统 `ffmpeg` 时自动转为 WAV，未安装时按段跳过；常规 WAV、MP3 等标准音频直接透传。当消息段未提供可用 URL 或可读本地文件时，QuickQuip 会调用 `get_record(out_format="wav")` 回退获取音频，要求协议端返回 Bot 所在环境可直接读取的 `file` 路径。 |

选型或升级协议端时，请对照上表核对拟启用功能的支持情况。首次开启语音识别（ASR）前，建议在测试群发送一条真实语音，检验转写链路与音频大小上限配置（详见[多模态配置](configuration.md#3-asr--语音消息识别语音转文字)）。如需配置定时在线巡检，可按[运维巡检说明](../../scripts/ops/README.md)开启协议端的 HTTP API，由巡检脚本调用 `get_status` 和 `get_login_info` 核对正向连接后的账号在线状态。

## 从随 QuickQuip 启动的 LLBot 迁移

早期版本的 Compose 编排曾在同一套文件中内置声明 `llbot` 服务。将该服务拆分为独立协议端（或换用其他协议端实现）时，请按以下顺序操作：

1. **备份现状与准备独立编排**：完整备份旧 Compose 文件、根 `.env` 和旧协议端登录态目录，并记录现用镜像标签；为独立协议端准备好专属目录、网络、数据卷与连接配置。若打算直接复用原登录态，请先对照目标协议端文档确认版本兼容性与容器内挂载路径。
2. **先停旧端、再启新端**：在旧 Compose 中先停止 `llbot` 服务，再启动独立协议端并登录 QQ。**同一个 QQ 账号切勿在新旧两个协议端同时在线**，务必严格按“先停后启”顺序切换，避免触发互踢或账号风控；旧容器与原状态目录先保留不动，以便出问题时快速恢复。
3. **更新 QuickQuip 编排与连接地址**：从 QuickQuip 的应用 Compose 中移除 `llbot` 服务定义及 `quickquip` 下的 `depends_on.llbot`，并更新根 `.env` 中的 OneBot 连接参数。使用 `deploy-v4` 版本目录布局的环境，先通过 [qqsync](config-sync.md) 将新 Compose 与连接配置推送生效，再执行后续代码发布；手工维护 Compose 的环境直接用新文件重新创建 `quickquip` 容器。
4. **核验业务与更新巡检**：检查日志确认 QuickQuip 已连上预期 QQ 号，在群聊和私聊中实测日常收发与已启用的媒体功能，最后同步更新[运维巡检配置](../../scripts/ops/README.md)。原有的 QuickQuip 配置与业务数据目录保持不变。

迁移后若需回退回旧协议端，同样应先在独立协议端断开该 QQ 账号，再恢复旧端容器、网络及根 `.env` 连接配置。日常执行 `deploy-v4 --rollback` 回滚应用版本时会沿用当前的根 `.env`；但若显式指定回滚到早期仍声明了 `llbot` 服务的旧发行目录（`releases/<id>`），Compose 会按当时的依赖重新拉起旧 `llbot` 容器——执行此类跨代回滚前请务必先停用外部协议端并确认登录态归属，防止同一账号双端冲突。

## 公开兼容记录

下表汇总已验证过的协议端版本与测试范围，供选型参考：

| 实现 | 已记录的验证与状态 |
|---|---|
| [LLBot 7.3.2](https://github.com/LLOneBot/LuckyLilliaBot) | 历史验收使用镜像 `initialencounter/llonebot:v7.12.14-7.3.2-45758`。QuickQuip v1.12.2 验证群聊／私聊、图片、语音 ASR、合并转发和撤回；v1.16.1 开发期验证出站 `reply` 与 `at`。 |
| LLBot 8.x | 本项目暂无公开生产验收记录。 |
| [NapCat](https://github.com/NapNeko/NapCatQQ) | 曾用于生产环境，2026 年 5 月的离线排障与迁移经过见 [NapCat → LLBot 迁移记录](migration-napcat-to-llbot.md)；选用新版本时请对照上文能力表重新核验。 |
| [SnowLuma](https://github.com/SnowLuma/SnowLuma) | 历史评估覆盖容器部署与主要接口调用。正式接入前请结合所选版本核对使用条款、配套 QQ 客户端版本、媒体与合并转发兼容性，以及重登和长期在线表现。 |

## 上线前核对

建议在自己的运维记录中留存实际部署的协议端版本、镜像标识、配套 QQ 客户端版本及连接方式，并在正式投入群聊前逐项验证：账号在线状态、群聊与私聊收发、已启用的引用回复与图片／语音能力、消息撤回、自身发言归档，以及容器重启和断线重连后的自动恢复表现。若你完成了可公开复现的新版本兼容验证，欢迎提交 PR 补充到上方兼容记录表中分享。
