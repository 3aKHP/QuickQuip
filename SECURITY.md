# 安全策略 / Security Policy

[中文](#中文) · [English](#english)

## 中文

### 支持版本

QuickQuip 以滚动方式维护，安全修复落在最新稳定发行线上。

| 版本 | 安全支持 |
|------|----------|
| 最新稳定版 | 支持。 |
| 旧版本 | 不支持。报告前请先升级。 |
| `dev` 分支 / `-dev.N` / `-rc.N` 构建 | 发布前尽力修复；不作为生产支持线。 |

### 如何报告漏洞

请勿通过公开的 GitHub issue 报告安全漏洞。

请使用以下私密渠道：

1. 发送邮件至 `cccp1945@vip.qq.com`，主题前缀 `[QuickQuip security]`。
2. 使用 GitHub 私密漏洞上报：打开仓库 **Security** 标签页，选择 **Report a vulnerability**。

欢迎使用中文或英文报告。

请尽量包含以下信息：

- 受影响版本：发行 tag、commit 或 Docker 镜像 tag/digest。
- 部署形态：Docker Compose、Windows 懒人包或源码运行；OneBot 协议实现端及其版本。
- Web Admin 面板是否暴露在网络中，以及防护方式。
- 清晰的复现步骤或概念验证（PoC）。
- 预期影响，例如 Web Admin 鉴权绕过、密钥或聊天归档泄漏、提示词注入引发不安全的工具副作用、拒绝服务。
- 相关日志与配置，并移除敏感信息（API 密钥、token、群号与账号号）。

### 范围

以下影响 QuickQuip 本身的报告最有价值：

- Web Admin 边界：鉴权、会话处理、API 授权与远程配置编辑。
- 密钥处理：provider API 密钥与管理 token，含日志与 LLM 调用 trace 中的脱敏。
- 不可信内容处理：聊天消息解析、提示词注入引发的不安全工具调用、MCP 桥接结果处理。
- 持久化与数据卫生：SQLite 数据库、聊天归档与文件路径处理。
- 打包与部署：本仓库分发的 Docker 镜像、发行包、示例配置与部署脚本。
- 正常部署下可触达的依赖漏洞。
- 源码、CI 或示例文件中意外泄漏 token、路径或敏感配置。

以下通常不在范围内：

- QQ 客户端、OneBot 协议实现端（LLBot、NapCat 等）或 LLM provider 自身的问题。
- 仓库之外的部署侧错误：反向代理、防火墙或平台账号的配置失误。
- 仅影响不支持版本的漏洞。
- 无实际 QuickQuip 影响的自动化扫描报告。
- GitHub 或外部服务的可用性。

### 协同披露

我们会在 7 天内确认有效报告，随后按严重程度协调修复与发布计划。安全修复发布在最新稳定线上，通常为补丁版本。

请在公开披露前给维护者留出合理的调查与修复时间。如希望被致谢，可在发行说明或公告中列入署名。

本项目目前不设漏洞赏金计划。

---

## English

### Supported Versions

QuickQuip is maintained as a rolling project; security fixes land on the latest stable release line.

| Version | Security support |
|---------|------------------|
| Latest stable release | Supported. |
| Older releases | Not supported. Please upgrade before reporting. |
| `dev` branch / `-dev.N` / `-rc.N` builds | Best-effort fixes before release; not a production support line. |

### Reporting a Vulnerability

Please do not report security vulnerabilities through public GitHub issues.

Use one of these private channels:

1. Email `cccp1945@vip.qq.com` with the subject prefix `[QuickQuip security]`.
2. Use GitHub's private vulnerability reporting: open the repository **Security** tab and choose **Report a vulnerability**.

Reports in English or Chinese are welcome.

Please include as much of the following as you can:

- Affected version: release tag, commit, or Docker image tag/digest.
- Deployment shape: Docker Compose, Windows bundle, or source checkout; the OneBot protocol implementation and its version.
- Whether the Web Admin panel is exposed to a network, and how it is protected.
- A clear reproduction case or proof of concept.
- Expected impact, such as Web Admin auth bypass, secret or chat-archive exposure, prompt injection leading to unsafe tool side effects, or denial of service.
- Relevant logs and configuration with secrets removed (API keys, tokens, group or account numbers).

### Scope

Security reports are most useful when they affect QuickQuip itself, including:

- Web Admin boundaries: authentication, session handling, API authorization, and remote configuration editing.
- Secret handling: provider API keys and admin tokens, including redaction in logs and LLM call traces.
- Untrusted content handling: parsing of chat messages, prompt injection leading to unsafe tool calls, and MCP bridge result handling.
- Persistence and data hygiene: SQLite databases, chat archives, and file path handling.
- Packaging and deployment: Docker images, release bundles, example configurations, and deploy scripts shipped in this repository.
- Dependency vulnerabilities that are reachable through a normal deployment.
- Accidental exposure of tokens, paths, or sensitive configuration in source, CI, or example files.

The following are generally out of scope:

- Issues in QQ clients, OneBot protocol implementations (LLBot, NapCat, and similar), or LLM providers.
- Deployer-side mistakes in reverse proxies, firewalls, or platform accounts outside this repository.
- Vulnerabilities that only affect unsupported versions.
- Automated scanning reports without a practical QuickQuip impact.
- Availability of GitHub or external services.

### Coordinated Disclosure

We aim to acknowledge valid reports within 7 days, then coordinate a fix and release plan based on severity. Security fixes are released on the latest stable line, typically as a patch release.

Please give the maintainer reasonable time to investigate and publish a fix before public disclosure. Credit can be included in release notes or advisories if you want to be acknowledged.

This project does not currently offer a bug bounty program.
