<!-- Generated from docs/dev/adr/0027-history-investigation-executor.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0027：群历史查询与专用调查执行器

- 状态：Accepted
- 日期：2026-11-07
- 关联：[Issue #72](https://github.com/3aKHP/QuickQuip/issues/72)、[ADR-0005](0005-tool-result-retention.md)、[ADR-0007](0007-unified-chat-archive.md)、[ADR-0002](0002-business-session-identity.md)、[ADR-0003](0003-epoch-history-freezing.md)

## 背景

LLM 的自动上下文有意保持在最近消息窗口内（20 条现场 + 纪元会话）；相关发言
离开窗口后模型没有查证手段，表现为"忘记群里讨论过的事"。扩大窗口只会推迟
问题并持续抬高成本。归档侧（ADR-0007）已具备全群 always-on 的 SQLite 归档，
为"按需查询"提供了现成数据源，无需引入 OneBot 历史接口的基座兼容层。

## 决策

1. **数据源只用本地归档**：`chat/history_query.py` 提供 SQL 侧群/时间/成员/
   keyset 过滤、精确 LIKE 预筛、页/扫描/时限三帽与诚实状态（partial 不得
   包装成 empty）。OneBot `get_group_msg_history` 直读不进首版（留作后续
   补洞手段）。
2. **两个直接工具** `search_group_history` / `read_group_history`：同群限定
   （群号取自执行上下文，不接受模型指定）、私聊拒绝、来源引用
   （`hr1.<归档UUID>.<行ID>`）跨轮可回查、请求级游标不跨群不复用。
3. **一个委派工具** `investigate_group_history`：复杂问题交给独立上下文的
   调查执行器——独立 Session/epoch/trace 边界与用量归因，受限工具面
   （search/read/count 三件套；count 为后补的全量计数证无通道，见下方
   修订），复用既有工具循环而非复制协议拼装。报告由程序校验
   （引用必须来自本任务实际读取的来源），关键原文由程序取回并重过撤回与
   敏感检查；不把自由文本包装成成功。
4. **临时结果政策**：三个工具及 `search_recent_messages` 声明 ephemeral
   （ADR-0005 落地）：结果正文不入业务持久层，持久化声明参数走白名单，
   ephemeral 触达后的 Loop 原生副本整体省略。
5. **默认关闭**：`[group_history]` 全局面（document-only）+ 群级开关存
   LLM 运行库；双开才曝光工具面，handler 内双重校验。

## 后果

- 群聊正文进入模型上下文但不进入 llm.db 业务记录；已发送回复里的引用由
  撤回旁表在后续查询侧屏蔽（不承诺追溯消除已发出内容）。
- 调查执行器在父 Loop 持有同群 ScopeGate 期间运行，同群回复排队上限即
  调查时限（默认 240s，可配置）；并发全局 2、每群 1。
- 预算初值（模型调用 10/工具 20/单请求 24K/累计 160K）为实验起点，以
  生产测量校准（合成规模性能样本：100 万条下窄查询 p95 低于 300ms，
  全部低于建议线 500ms）。

## 修订（2026-11-07，上线首日生产校准）

生产首日实测（主群 52 万条归档）暴露两个预算形状问题，随证无通道一并修正：

- **计数证无**：搜索分页帽（单调用 5000 行）与工具帽的乘积远小于库容，
  子任务数学上无法证明「某词在窗口内从未出现」。受限面新增
  `count_group_history`（单条 `COUNT(*)` 复用搜索谓词，不受分页帽、
  仍受 2 秒查询时限），0 条命中即确定性证无；计数回执（`hr1c.` 前缀）
  与消息引用同入 `evidence_refs`（回执无消息内容，撤回语义不适用，
  证据合并绕过撤回复查早退门）。
- **工具帽改独立配置** `investigation_tool_calls`（默认 30）：原派生比值
  2× 在每轮并行 4 工具的批次效率下过紧（首日实测 20/20 撞帽与 18/20
  贴帽各一例，观测密度约 2.5 工具/轮）。
- **诚实标注**：软预算（工具帽/直查结果预算）触顶后收束的合法报告
  原实现误标 `completed`（触顶引导消息让模型出报告→校验通过→正常
  收尾路径），现如实标 `partial`；`suggested_followup` 限定写给另一
  会话执行（具体词+时间窗，禁游标），外层工具描述声明未决线索为
  可选项——三者共同压制外层主模型以 3.5 倍单 call 成本盲目接续补查
  （首日实测一例外层因此多花 5 轮）。
