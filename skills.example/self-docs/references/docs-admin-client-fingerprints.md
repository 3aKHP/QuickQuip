<!-- Generated from docs/admin/client-fingerprints.md; do not edit -->

# 请求指纹 Profile

Provider 的固定字段 `client_fingerprint` 选择客户端请求特征。四种协议均支持以下内置 Profile：

| ID | 行为 |
|---|---|
| `default` | 保留当前默认请求特征，作为升级后的缺省选择 |
| `quickquip` | QuickQuip 品牌 UA 与部署、纪元及版本标识，需要显式选择 |

在 Web Admin「LLM 配置 → 渠道」选择 Profile，保存草稿后应用。JSON 的 `client_fingerprint` 放在渠道对象内；模型参数覆盖不接受该字段。它与 OpenAI Responses 的 `responses_profile` 能力设置分别配置。

## 自有品牌请求头

默认 UA 为 `QuickQuip/<实际安装包版本>`，例如 `QuickQuip/1.16.2.dev1`。版本来自 `importlib.metadata`，缺少包元数据时使用 `unknown` 并记录诊断。Provider 参数 `user_agent` 优先于附加请求头中的 UA，附加 UA 优先于 Profile 默认 UA；请求头名称按大小写无关处理。

| 请求头 | 来源及生命周期 |
|---|---|
| `x-quickquip-install` | 首次使用时计算随机 UUID 字符串的 SHA-256，保存到 `data/client_identity.json`；跨重启稳定 |
| `x-quickquip-session` | 当前请求冻结的纪元 UUIDv4；纪元实际推进时改变，重启建立新纪元 |
| `x-quickquip-cluster` | 全局 `settings.runtime.client_cluster`；空字符串时省略 |
| `x-quickquip-client` | 实际安装包版本，与默认 UA 的版本来源相同 |

四个专有头仅在 `quickquip` Profile 下发送。Provider 的 `headers` 不接受这四个名称，包括不同大小写拼写；配置校验与运行时均拒绝手工覆盖。

cluster 在 Web 的全局设置中填写，部署内所有渠道共用，只使用可打印 ASCII。安装标识随数据卷备份恢复；复制数据卷会保留相同安装身份。创建独立部署时，在停止服务并保留原文件备份后，移走新部署的 `data/client_identity.json`，首次使用会生成新身份。损坏的身份文件会明确报错，需要管理员检查和恢复。

业务 Session 与纪元分别管理。业务 Session 标识持续对话，纪元标识当前上下文窗口；冷场、预算裁剪等窗口推进可以改变纪元并保留业务 Session。请求冻结纪元后，重试、备用地址和工具循环复用该值；辅助识图继承调用时的纪元。独立任务在每次操作开始时生成临时纪元，操作内部级联和重试复用。

Anthropic 的 `quickquip` Profile 移除默认 Claude Code 客户端身份头、Stainless 头、浏览器访问标记和 `claude-code` beta 项。其余现有能力声明、URL 与请求 Body 保持原有行为；专门的客户端 Body 对齐将在协议适配中完成。

## 编辑 Profile 文件

内置 TOML 随包分发，源码位置为 `src/quickquip/llm/client_fingerprints/defaults/`。将需要调整的文件复制到 `config/client_profiles/`，保留文件名与 `id`，编辑后重启 Bot 和 Web。相同 ID 使用本地文件整份覆盖；新增 ID 可定义独立 Profile。文件修改不会随配置「应用」自动重新加载，正在执行的操作继续使用其配置快照。

Profile 的最小文件示例：

```toml
format_version = 1
id = "custom"
label = "Custom Client"
user_agent = "CustomClient/{client_version}"

[headers]
accept = "application/json"

[protocols.openai]
[protocols.openai_responses]
```

文件名为 `custom.toml`。`protocols` 声明支持的协议，协议表可包含 `headers` 和 `bindings`。根表中的请求头用于全部已声明协议；协议表补充本协议的请求头，同一名称不能重复声明。

`user_agent` 仅支持 `{client_version}` 版本替换。动态 `bindings` 的来源为 `install_id`、`epoch_id`、`cluster_id`、`client_version`、`stainless_os`；前四个来源归属 `quickquip` Profile。自有 Profile 必须保留四个专有头及其对应绑定。认证与 `content-type` 由协议适配器管理，Profile 文件不接受这些头。

解析器拒绝未知字段、非法动态来源、重复头和不支持的协议。Profile 文件不保存密钥，不执行表达式或脚本。附加认证配置继续使用根目录 `.env` 的变量引用。

源码部署、wheel 和容器均包含内置模板。部署脚本保留当前 release 的本地覆盖文件，新候选中已有的同名文件优先；请同时备份覆盖目录与数据卷。
