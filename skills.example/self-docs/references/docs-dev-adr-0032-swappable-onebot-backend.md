<!-- Generated from docs/dev/adr/0032-swappable-onebot-backend.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0032：协议端作为可替换的部署变量

- 记录日期：2026-11-19（2026-11-21 补充公开分发边界）
- 原始决策日期：未确认

## 背景

QuickQuip 使用 NoneBot2 接收 OneBot V11 事件并调用接口动作，QQ 账号登录、客户端协议版本与连接保活则由外部 OneBot 协议端负责维护。历次实际部署中，协议端的运行条件与社区维护状态多次变化，项目也曾因既有协议端频繁掉线而整体迁移。协议端的选型、兼容性验证与故障恢复因此需要独立于 QuickQuip 自身的代码发布周期。

## 决定

QuickQuip 的公开发行物和 Compose 模板提供应用及其配套服务。部署者自行取得、部署和维护满足 [OneBot 能力契约](../../admin/onebot-adapters.md#quickquip-的-onebot-v11-边界)的协议端。

应用以 OneBot V11 为连接边界。正向 WebSocket 由根 `.env` 的 `ONEBOT_WS_URLS` 指向协议端，反向 WebSocket 由协议端连接 Bot 的监听地址。两端分别配置相同的访问令牌。应用发布管理 QuickQuip 的服务和运行数据，协议端登录态及其生命周期由部署者独立管理。

## 方案与理由

- 固定随应用分发一个协议端可以减少首次安装步骤，但会把协议端支持周期、登录方式和镜像更新纳入应用发布。
- 在 QuickQuip 中再实现一层多协议抽象可以接入其他协议，但会增加一套应用侧契约和兼容工作。
- 采用 OneBot V11 消费者边界可以把选型、更换和版本验证交给部署流程。公开契约记录应用使用的事件、调用和消息段，兼容记录说明实际验证的版本和场景。

## 影响

更换协议端时，部署者准备服务和网络，切换连接配置，并验证启用的 QuickQuip 功能。协议端之间的差异集中在功能契约，例如自消息回显、合并转发和媒体文件交付。

回退协议端需要恢复原服务、登录态和连接配置，恢复时间取决于账号登录以及旧端是否可用。应用回滚使用当前共享 `.env`，协议端的切换作为独立运维操作执行。

## 依据与相关契约

- [OneBot 连接、能力与迁移](../../admin/onebot-adapters.md)
- [NapCat 至 LLBot 历史迁移](../../admin/migration-napcat-to-llbot.md)
- [协议端术语](../../glossary.md#onebot-backend)
