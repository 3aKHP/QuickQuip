# MCP Server 接入指南

本文面向已经能用 Bot 正常对话的部署者，说明如何接入 MCP 工具服务并确认工具实际执行。MCP 服务提供搜索、读文件等能力；模型提出工具请求后，QuickQuip 联系服务执行，再把结果交给模型组织回复。概念与协议详解见 [MCP 教程](../dev/mcp-tutorial.md)。

第一次接入可完成下方本地 echo 练习；已有服务地址和凭据时，从[接入清单](#接入清单)开始。JSON 示例是完整导出配置中的字段片段，表单填写与片段合入位置在清单中说明，完整保存、应用流程见 [LLM 配置管理](llm-configuration.md)。

## 首次接入：本地 echo 练习

这个服务把传入文字原样回显，方便核对“Bot → 工具服务 → 模型回复”的过程。练习适用于同一台电脑上运行的源码 Bot 或 Windows 包；需要 Web Admin 管理权限、支持工具调用的模型，以及用于运行练习服务的标准 Python 3.11 或更高版本。Windows 使用标准 Python 的 `py` 启动器。

### 1. 准备练习目录

在 Bot 主机的个人工作目录中创建独立目录，放在项目仓库或 Windows 包目录之外。安装固定版本的[官方 MCP Python SDK](https://pypi.org/project/mcp/1.26.0/)；下面命令在独立虚拟环境安装服务依赖。

Linux／macOS 的 Bash：

```bash
mkdir mcp-echo-lab
cd mcp-echo-lab
python3 -m venv .venv
.venv/bin/python -m pip install "mcp==1.26.0"
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory mcp-echo-lab
Set-Location mcp-echo-lab
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp==1.26.0"
```

### 2. 创建并启动服务

用文本编辑器在刚创建的目录保存 `echo_server.py`，内容如下：

```python
from mcp.server.fastmcp import FastMCP

server = FastMCP(
    "QuickQuip Echo", host="127.0.0.1", port=8017,
    stateless_http=True, json_response=True,
)


@server.tool()
def echo(text: str) -> str:
    """回显传入文本，供 MCP 接入测试。"""
    print(f"echo 收到：{text}", flush=True)
    return f"echo: {text}"


if __name__ == "__main__":
    server.run(transport="streamable-http")
```

在练习目录中启动。Bash 执行：

```bash
.venv/bin/python echo_server.py
```

PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe echo_server.py
```

终端出现 `Uvicorn running on http://127.0.0.1:8017` 后保持运行。MCP 端点为 `http://127.0.0.1:8017/mcp`：端点就是客户端提交 MCP 请求的完整地址，包含服务使用的路径。本例只监听本机回环地址，提供一个回显工具，无需账号或令牌。实现使用 SDK 1.26.0 的 Streamable HTTP，QuickQuip 使用缺省的 `legacy` 协商和 `2025-03-26` 版本即可；示例与官方 SDK 于 2026-10-14 核对。

容器中的 `127.0.0.1` 指向容器自身。本机练习使用直接运行在主机上的 Bot；容器 Bot 接入服务时，填写容器实际可达的地址：同一 Docker 网络中的服务可使用服务名，服务需监听该网络接口；宿主机服务需监听容器可达地址，并配置对应网关或路由。`host.docker.internal` 的解析取决于部署配置。生产接入可使用服务提供方已鉴权的 HTTPS 端点。

### 3. 在 Web Admin 添加服务

打开“LLM 配置 → 工具与技能”，开启“启用工具调用”。在“MCP 服务与状态”开启 MCP 总开关，点击“添加 MCP 服务”，填写：

| 表单项 | 值 |
|---|---|
| 服务 ID | `echo_lab` |
| 传输方式 | `http` |
| 服务地址 | `http://127.0.0.1:8017/mcp` |
| 请求头 | 留空 |
| 协议协商 | `legacy` |
| 协议版本 | `2025-03-26` |
| 只装载这些工具 | `echo` |

其余字段保留缺省值。若已有非空工具名单采用 `replace`，把 `mcp_echo_lab_echo` 加入该名单。点击顶部“保存草稿 → 应用到 Bot”，等待任务成功和 Bot 加载目标版本。刷新连接状态，`echo_lab` 应显示已连接、1 个工具；展开“已装载工具清单”可看到服务原始工具名 `echo`。Bot 使用的调用名称为 `mcp_echo_lab_echo`，由服务 ID 与原始工具名组成。

### 4. 调用并确认结果

在已开启 AI 的群或私聊发送下面的提问。这里使用默认 `/ai` 前缀；已修改前缀的会话使用实际设置：

```text
/ai 请调用 mcp_echo_lab_echo，text 参数为 quickquip-mcp-162，并告诉我工具返回了什么。如果工具尚未加载，请先搜索 echo 工具再调用。
```

服务终端出现 `echo 收到：quickquip-mcp-162`，表示服务已执行这次调用，并返回 `echo: quickquip-mcp-162`。机器人随后据此回复。确认时把服务终端的调用记录与机器人给出的工具结果对照。

若服务已连接而没有调用记录，检查当前模型是否支持工具调用，以及工具调用开关和工具名单；工具发现开启时，让模型先搜索并加载 echo。若显示连接失败，先确认服务终端保持运行、Bot 与服务在同一台主机、端口与 `/mcp` 路径一致，详细错误在“MCP 服务与状态”查看。

回显服务在本机执行；通过 Bot 测试会请求已配置的模型，按该模型渠道计费。后台“用量”显示模型费用，其他 MCP 服务自己的收费在对应服务账号核对。练习结束后，在 Web 停用或删除 `echo_lab` 并保存应用，再在服务终端按 Ctrl+C 停止服务。

## Transport 怎么选

| transport | 适用场景 | 关键字段 |
|---|---|---|
| `http` | 远程 MCP Streamable HTTP 服务（自建网关或第三方），单端点 POST | `url`、`headers` |
| `stdio` | 与 bot 同机的本地进程，随 bot 启停 | `command`、`args`、`env` |
| `docker` | 宿主机 Docker 直接运行官方未提供 http/sse 入口的社区镜像；需要原生 Docker daemon 与 docker.sock，容器化部署默认不推荐 | `image`、`mounts`、`env` |
| `sse` | 经典 HTTP+SSE 远程服务（旧式 sidecar） | `url` |

远程服务默认选 `http`：生产容器优先经已鉴权的 HTTPS Streamable HTTP 网关复用宿主机上的 MCP 服务。`sse` 用于只提供旧式入口的服务，`stdio` / `docker` 用于本机部署。

## 接入清单

先确认基础 LLM 对话可用，并在“LLM 配置 → 工具与技能”开启 `settings.runtime.tool_calling_enabled`。新建配置库的工具调用缺省关闭，Bot 通过此开关向模型提供已连接的 MCP 工具；若工具名单非空且采用 `settings.tools.enabled_mode = "replace"`，显式允许需要的 MCP 工具。以下配置与工具开关一并保存草稿并应用。

1. **拿到连接信息**：从服务提供方的接入说明取得 MCP 端点 URL、传输方式、协议版本和鉴权方法。端点包含服务使用的路径；凭据由该工具服务签发，与模型渠道的 API key 分别配置。先选择一个读类工具，按其所需权限申请凭据，并核对服务方计费说明。本地 server 还需准备启动命令或镜像，以及所需环境变量。
2. **写配置**：在“工具与技能 → MCP 服务与状态”打开 MCP 总开关，点击“添加 MCP 服务”，按示例填写服务 ID、传输方式和服务地址。以下为导出 JSON 内的字段对照，`mcp.example.com` 需替换为实际 MCP 端点：

   ```json
   {
     "settings": {
       "mcp": {
         "enabled": true,
         "servers": [
           {
             "id": "my_server",
             "transport": "http",
             "timeout_seconds": 30,
             "url": "https://mcp.example.com/mcp"
           }
         ]
       }
     }
   }
   ```

   使用 JSON 导入时，先导出完整配置，将示例服务对象追加到 `settings.mcp.servers`，设置 `settings.mcp.enabled` 并保留其他字段与已有服务；预览完整文件差异后再导入。`id` 在全部 server 间唯一，重复条目会被保存校验拒绝；`transport` 缺省为 `stdio`，`timeout_seconds` 缺省为 30，单个 server 的 `enabled` 缺省为 `true`，设为 `false` 可临时停用而保留配置。
3. **凭证走环境变量**：server 条目内的普通字符串支持 `${ENV_VAR}` 与 `${ENV_VAR:-default}` 展开；认证字段只保存 `${ENV_VAR}` 引用——未设置的 `${ENV_VAR}` 展开为空串，`${ENV_VAR:-default}` 展开为默认值。凭证一律写在仓库根 `.env`，配置数据库和 JSON 中仅保存变量引用：

   ```json
   {
     "env": {
       "GITHUB_TOOLSETS": "${GITHUB_TOOLSETS:-context,repos,issues}"
     }
   }
   ```

   上例在 `.env` 未定义 `GITHUB_TOOLSETS` 时取默认值，定义后取环境变量的值。
4. **生效**：保存草稿后单独应用，查询配置任务状态与 Bot 实际加载版本。MCP 配置发生变化时创建新的连接资源；价格等无关修改不会重连。`/llm mcp reload`（管理员）用于手动重连，docker transport 会拉取镜像。`.env` 修改需要重启 Bot；重启加载已发布配置。
5. **验证装载**：群内 `/llm mcp status` 查看，输出形如：

   ```text
   MCP 状态
   总开关：ON
   连接数：1/2
   工具数：7
   - prts_wiki [http] ON tools=7 server=ExampleMCPServer 1.0
   - fetch [sse] ERROR tools=0 error=连接超时
   ```

   `ON` 表示已连接，`OFF` 表示该 server 被停用，`ERROR` 表示装载失败；聊天面的 `error=` 只显示失败类别，脱敏后的具体错误文本在“LLM 配置 → 工具与技能 → MCP 服务与状态”查看。配置了 `negotiation` 的 http server 会在 transport 后附带协议纪元标记（如 `[http/auto/modern]`），表示协商模式与实际协商结果。
6. **调用与费用确认**：在已开启 AI 的会话中，请机器人调用选定的读类工具，给出明确参数；将服务调用日志与返回内容对照，核对预期结果，本地练习的方法见上文。模型调用用量和估算费用在 Web Admin“用量”页查看，工具服务的收费在该服务账号核对。需要巡检模型渠道时，管理员可另行执行 `/llm probe`；它会请求全部启用渠道的默认模型并可能产生费用。

## 需要鉴权的 HTTP 配置模板

服务提供方要求 Bearer token 时，按其说明取得令牌，将下方占位 URL 换成实际端点。令牌保存在根 `.env`，请求头字段填写变量引用；其他鉴权方法按提供方指定的 Header 名称填写。

```json
{
  "settings": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "id": "prts_wiki",
          "transport": "http",
          "timeout_seconds": 30,
          "url": "https://mcp.example.com/mcp",
          "headers": {
            "Authorization": "Bearer ${MCP_PRTS_WIKI_TOKEN}"
          }
        }
      ]
    }
  }
}
```

对应 `.env` 条目（体例同 `.env.example`）：

```env
# prts_wiki MCP 的鉴权 token，对应上面的服务配置。
MCP_PRTS_WIKI_TOKEN=your_token_here
```

## 常用进阶配置

| 字段 | 说明 |
|---|---|
| `include_tools` / `exclude_tools` | server 级工具过滤：`include_tools` 为空时接入该 server 全部工具，`exclude_tools` 在白名单之后生效；两项都支持 MCP 原始工具名或 QuickQuip 生成的工具名 |
| `allowed_tools` | 兼容旧配置的白名单字段，作用同 `include_tools`，新配置使用 `include_tools` |
| `tool_prefix` | 自定义工具名前缀；缺省按 server id 生成 `mcp_<id>_<工具名>` |
| `protocol_version` | legacy 握手的协议版本 pin，默认 `"2025-03-26"` |
| `negotiation` | 协议协商模式，仅 `http` transport 生效：`legacy`（默认）/ `auto` / `modern`；`auto` / `modern` 需同时配置 `supported_protocol_versions` |
| `image` / `mounts` | docker transport 的镜像与卷挂载，格式 `host:container` 或 `host:container:ro`，值支持 `${ENV_VAR}` 展开 |

字段全集与默认值见 [configuration.md](configuration.md) 的 `settings.mcp` 段，语义详解见 [mcp-tutorial.md](../dev/mcp-tutorial.md)。接入 GitHub MCP 这类大工具集时，建议先用 `include_tools` 收窄到读类工具，再交给 `tool_search` / `tool_list` 做按需发现加载。

## 排障

- **装载失败**：先看 `/llm mcp status` 的 `error=` 类别（配置错误 / 认证失败 / 连接超时 / 传输错误等）；显示“总开关：OFF”时检查 `settings.mcp.enabled = true` 是否已设。脱敏后的具体错误文本与手动重连入口在 “LLM 配置 → 工具与技能 → MCP 服务与状态”和“诊断”页。启动时的瞬时连接失败会自动重试（最多 3 次、间隔 2 秒），认证与配置类错误直接失败。
- **别名冲突**：不同 server 生成相同工具名时冲突工具全部不注册，status 标为配置错误；用 `tool_prefix` 区分。
- **server 已连接但工具没出现**：检查该 server 的 `include_tools` / `exclude_tools` 过滤，以及 `settings.tools` 的 `enabled` / `enabled_mode` 是否把 MCP 工具从工具面过滤掉。
- **工具已装载但模型没有调用**：确认当前模型支持工具调用，全局工具调用开关已应用；给出具体工具名称、参数和任务。工具发现启用时，模型先通过 `tool_search` 或 `tool_list` 加载工具，再发起调用。
- **stale session（http legacy）**：会话过期后 `tools/list` 等只读请求会最多自动重连 2 次；`tools/call` 不自动重放，当次调用失败，下一次调用走新会话。
- **工具结果大小边界**：resource 文本超过 60,000 code point 截断并附固定标记；图片单张上限 5 MiB、每个工具结果最多交付 5 张（仅 PNG / JPEG / GIF / WebP）。
- 深入排查见 [mcp-integration.md](../dev/mcp-integration.md)。

## 延伸阅读

- [docs/dev/mcp-tutorial.md](../dev/mcp-tutorial.md) — MCP 概念教程
- [configuration.md](configuration.md) — `data/llm_config.db` 字段全集
- [docs/dev/mcp-integration.md](../dev/mcp-integration.md) — MCP 集成设计与决策
