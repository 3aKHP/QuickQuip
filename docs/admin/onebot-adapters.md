# 接入 OneBot V11 协议端

QuickQuip 通过 NoneBot2 使用 OneBot V11。部署者自行安装协议端，负责 QQ 登录、升级、登录态和恢复。本页说明如何建立连接，以及各项 QuickQuip 功能需要协议端提供的能力。

## 连接 QuickQuip

按协议端自己的安装说明启动服务并登录机器人账号。连接鉴权启用时，在 QuickQuip 的根 `.env` 和协议端配置相同的 `ONEBOT_ACCESS_TOKEN`，WebSocket 握手使用 Bearer 令牌。根据部署位置选择下列一种连接方式。

### 正向 WebSocket

QuickQuip 主动连接协议端。在根 `.env` 中填写从 **Bot 进程**可达的地址。例如，Bot 和协议端同在一台主机上运行，且 Bot 使用主机 Python：

```env
DRIVER=~fastapi+~websockets
ONEBOT_WS_URLS=["ws://127.0.0.1:3001/"]
ONEBOT_ACCESS_TOKEN=replace_with_your_token
```

`3001` 是示例端口，请按协议端配置填写。Bot 在 Docker 内运行时，`127.0.0.1` 是 Bot 容器自身。使用从 Bot 容器可访问的协议端地址，或把两个容器加入同一个外部 Docker 网络，通过服务名或网络别名连接。

### 反向 WebSocket

协议端主动连接 QuickQuip。在根 `.env` 中设置 `ONEBOT_WS_URLS=[]`。在协议端填写 `ws://<Bot 可达地址>:8080/onebot/v11/ws` 和同一个访问令牌，端口用 Bot 实际监听的端口。反向连接需要支持 WebSocket 服务端的驱动，模板里的 `DRIVER` 可直接使用。

Docker 模板在容器内监听 `8080`。两个容器共享网络时用 `ws://quickquip:8080/onebot/v11/ws`。协议端从 Docker 网络外接入时，在实际使用的 Compose 中将 Bot 端口映射到协议端可达的主机接口，并按需要限制可访问的来源。

### 两个独立 Compose 使用共享网络

在 Docker 主机上为两套服务建立一个外部网络。以下使用 `onebot-shared` 为示例网络名：

```bash
docker network create onebot-shared
```

将以下片段合入实际部署的 QuickQuip Compose。使用 `deploy-v4` 时编辑本地的 `prod/docker-compose.yml`。如果服务已有其他网络，保留原列表并添加 `onebot-shared`。

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

在协议端的独立编排中也把协议服务接入此网络。如果协议端在网络上的服务名是 `onebot`，且正向端口是 `3001`，QuickQuip 使用 `ONEBOT_WS_URLS=["ws://onebot:3001/"]`。启动或重建 Bot 后，在日志中确认目标账号已连接，再在一个测试群发送“早安”并检查回复。修改连接地址或令牌后重启源码进程，Docker 部署则用更新的 `.env` 重建 Bot 容器。

## QuickQuip 的 OneBot V11 边界

群聊和私聊的基础收发需要 `message.group`、`message.private`、`send_group_msg` 和 `send_private_msg`。正向 WebSocket 需要协议端上报 `meta_event.lifecycle` 的 `connect` 事件和 `self_id`，供 NoneBot 注册账号。消息与发送参数使用段数组。

| 功能 | 所需事件、调用或消息段 |
|---|---|
| 命令与身份 | 群消息包括 `sender.card`、`nickname`、`role`。真实艾特使用 `at` 段。群成员名片查询使用 `get_group_member_info`，失败时显示已有名称或 QQ 号。 |
| 引用 | 解析入站 `reply` 需要 `get_msg` 返回被引用的消息及发送者 ID。启用引用回复时使用出站 `reply`，协议端显式拒绝该段时送达正文。 |
| 自消息归档 | 支持并启用扩展事件 `message_sent`。收到群自消息时归档一次，供日／周／月报使用。 |
| 撤回 | `notice.group_recall` 和 `notice.friend_recall`，用于清理消息上下文。 |
| 合并转发 | `send_group_forward_msg` 支持自定义节点 `name`、`uin`，`get_forward_msg` 支持读取嵌套节点。 |
| 图片 | 出站 `image` 使用 `base64://` 或 HTTP(S) URL，入站图片的 `data.url` 需可从 Bot 直接下载。 |
| 语音 | 出站 `record` 支持 base64。入站可直接提供转写文本，也可提供可读取的音频 URL 或文件。`get_record(out_format="wav")` 回退需要返回 Bot 所在环境可读的 `file` 路径。ASR 渠道须接受所得音频格式。 |

选择协议端时，按实际启用的功能核对该表。开启语音识别前用一条真实语音验证转写，QQ 原始 SILK／AMR 的应用侧兼容进度见 [Issue #354](https://github.com/3aKHP/QuickQuip/issues/354)。需要定时巡检时，按[巡检配置](../../scripts/ops/README.md)配置 HTTP API，使用 `get_status` 和 `get_login_info` 检查正向连接后的账号状态。

## 从随 QuickQuip 启动的 LLBot 迁移

适用于旧版 Compose 声明了 `llbot` 服务的部署。可将原实现移到独立编排，也可换用其他协议端。

1. 保存旧 Compose、根 `.env` 和旧端登录资产，记录现用镜像版本。为独立协议端准备网络、卷和连接配置。若计划复用原登录态，按协议端文档确认版本和挂载路径。
2. 使用旧 Compose 停止其中的 `llbot` 服务，再启动独立协议端并登录。同一个 QQ 账号按顺序切换。保留旧容器和状态目录以便恢复。
3. 在应用 Compose 中移除 `llbot` 服务及 Bot 的 `depends_on.llbot`，更新根 `.env` 的 OneBot 连接。已有 `deploy-v4` 版本布局时，先通过 [qqsync](config-sync.md) 把应用 Compose 和连接配置应用到当前版本，再执行下一次代码发布。手动 Compose 部署使用更新后的文件重新创建 Bot。
4. 确认 QuickQuip 连的是预期账号，检查群聊、私聊及自己启用的功能，再更新[运维巡检](../../scripts/ops/README.md)。配置和业务数据继续使用原有 QuickQuip 目录。

需要撤销协议端切换时，先停止新端与该账号的连接，再恢复旧端、网络及对应的 QuickQuip 连接配置。应用版本回滚沿用当前根 `.env`。显式选择仍声明 `llbot` 的旧应用发行目录时，Compose 会按其依赖启动旧服务，请先确认恢复方案和账号归属。

## 公开兼容记录

以下记录用于定位已验证的版本和场景。实际接入以部署者选用的版本及其功能检查为准。

| 实现 | 已记录的验证与状态 |
|---|---|
| [LLBot 7.3.2](https://github.com/LLOneBot/LuckyLilliaBot) | 历史验收使用镜像 `initialencounter/llonebot:v7.12.14-7.3.2-45758`。QuickQuip v1.12.2 验证群／私聊、图片、语音 ASR、合并转发和撤回。v1.16.1 开发期验证出站 `reply` 与 `at`。 |
| LLBot 8.x | 本项目暂无公开生产验收记录。 |
| [NapCat](https://github.com/NapNeko/NapCatQQ) | 曾用于生产。2026 年 5 月的离线与迁移记录见 [NapCat → LLBot](migration-napcat-to-llbot.md)。选用新版本时重新按当前契约验证。 |
| [SnowLuma](https://github.com/SnowLuma/SnowLuma) | 历史评估覆盖容器部署与主要调用。接入前按所选版本核对使用条款、QQ 客户端版本、媒体与转发兼容，以及重新登录和长期在线情况。 |

## 上线前核对

记录实际的协议端版本、镜像标识、QQ 客户端版本和连接方式。在独立部署中验证账号在线、群／私聊收发、已启用的引用与媒体能力、撤回、自消息归档，以及重启和断线重连。把可公开复现的版本与结果加到兼容记录中。
