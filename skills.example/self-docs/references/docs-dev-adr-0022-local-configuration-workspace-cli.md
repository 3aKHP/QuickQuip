<!-- Generated from docs/dev/adr/0022-local-configuration-workspace-cli.md; do not edit -->

---
status: Superseded
superseded_by: [0024-directional-configuration-deployment.md]
---

# ADR-0022：以 qqconf 统一编辑本地持久化配置

- 记录日期：2026-10-26
- 原始决策日期：2026-10-26

后续决定见 [ADR-0024：工作副本与单向配置部署](0024-directional-configuration-deployment.md)。

## 背景

完成配置与运行数据存储分离（[ADR-0021](0021-configuration-runtime-storage-separation.md)）后，项目的可编辑持久化配置仍分散在 `config/managed/config.db` 以及多份 TOML、JSON、YAML 和根 `.env` 文件中。维护者希望在单一本地工作目录中完成日常编辑，让真实的 `config/` 与 `data/` 目录退居机器读写层；同时，初代工作副本（[ADR-0020](0020-editable-configuration-workspaces.md)）要求维护对象清单、显式传入计划编号与确认摘要，且整份文档粒度的冲突检测无法自动合并互不相干的字段改动，日常操作心智负担较重。

## 决定

推出统一的本地配置工作副本 CLI `qqconf`，将命令精简为展开 `unpack`、只读状态与基线刷新 `refresh` 以及写回打包 `pack`：

- **目录发现与格式映射**：默认工作副本位于受 `.gitignore` 忽略的 `.config-workspace/`。配置数据库中的逻辑内容拆分为工作副本 `db/` 子目录下的多份业务 TOML，其余受管文本文件保持原有格式与相对路径；工具按目录自动扫描发现配置对象，以正文内的稳定业务标识作为合并匹配键，隐藏基线由工具内部自动维护。
- **字段级三方合并**：写回时基于“共同基线、工作副本当前文本、本地真实配置”执行字段级三方合并。遇到同一字段双侧冲突时默认中止整次写回，管理员也可通过显式参数指定冲突字段优先采用的来源。写回前对合并后的完整目标配置执行跨文件引用与结构校验；LLM 配置写入后保存为草稿，实际发布生效交由后续部署流程触发。
- **按服务运行态分流落盘**：打包时若确认本地 Bot 与 Web 进程均已停止，则获取服务生命周期锁并直接写入真实配置目录；若任一服务正在运行或状态未知，则生成完整的 `.config-staging/` 暂存候选目录供部署工具消费。跨文件写操作记录持久化事务日志，中途异常中断后由下一次写命令自动恢复，预览模式全程保持只读。
- **纳管范围**：远端同步与部署工具仅以真实配置目录和 `.config-staging/` 为衔接桥梁，不直接读取工作副本。渠道凭据与环境变量、群级覆盖、循环定时消息及标准运维配置一并纳入 `qqconf` 本地管理；体积较大或具备独立安装流程的 Skill 包、协议端运行状态、HTTP Trace 实时诊断开关以及业务运行库不在工作副本内展开。

## 方案与理由

取消手工维护的对象注册清单、改为按目录扫描发现文件，更贴合日常直接新建渠道或人格文件的直觉；用正文内的稳定 ID 承担三方合并对齐，即可让排序文件只专注表达先后顺序。

将冲突粒度从整份文档细化到字段级，能够无感合并本地与后台各自修改的不同配置项，同时对顺序敏感的回退链与普通数组保持整体替换语义，避免数组元素错位拼接。预览与实际执行均在当下重读真实文件并校验版本，省去了人工复制校验摘要的步骤；服务运行期间自动分流到 `.config-staging/`，则把“随时在本地编辑打包”与“停服切换生效”解耦开来。

## 影响

既有旧版工作副本保留为本地备份，升级后通过重新执行 `qqconf unpack` 建立新版工作目录。工具侧新增统一配置注册表与独立恢复事务，测试需持续覆盖 TOML 注释与类型保真、凭据脱敏预览、服务运行态探测及断电／中断恢复；真实配置库与业务运行库的数据归属继续遵循 [ADR-0021](0021-configuration-runtime-storage-separation.md)。

## 依据与相关契约

- [qqconf 操作手册](../../admin/config-workspace.md)
- [工作副本契约](../config-workspace.md)、[配置与运行存储](../configuration-storage.md)
- [ADR-0020：持久 TOML 工作副本](0020-editable-configuration-workspaces.md)（由本记录替代）
- [ADR-0024：工作副本与单向配置部署](0024-directional-configuration-deployment.md)
