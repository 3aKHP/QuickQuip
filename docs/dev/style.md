# QuickQuip 代码规范与架构硬原则

面向所有协作者（人类与 AI）。本文件记录 QuickQuip 的代码架构硬原则、反模式与重构节奏，作为工程规范的事实参考。

日常工作流见 [`../../CLAUDE.md`](../../CLAUDE.md)；项目目录与分层结构见 [`architecture.md`](architecture.md)；Commit 与 CHANGELOG 规范见 [`../../AGENTS.md`](../../AGENTS.md)。

---

## 代码规范与架构

**项目维护者对代码架构和模块化解耦要求很高**。上帝文件和面条代码是底线问题，在它们出现之前就要阻止。以下是硬性原则，不是 "nice to have"。

### 文件大小与职责

- **单一职责**：一个文件只干一件事。`common/sensitive_filter` 只负责敏感词过滤，不混限流；单位/格式换算类逻辑独立成纯函数模块，不放业务路径里
- **文件长度预警线**：Python 源文件超过 ~400 行就要问"这能不能拆"。`llm/service.py`（1300+ 行）、`llm/provider.py`（1200+ 行）、`llm/mcp.py`（1000+ 行）、`chat/awakening.py`（950+ 行）已显著超标，属于待重构积压——新功能不该继续往里堆
- **业务层只做业务**：纯解析、数学、统计、过滤**必须**抽到独立模块或类。`adapters/nonebot/` 只保留 matcher 注册和命令分发骨架，对业务函数的调用回到 `quickquip.*` 业务层

### 分层纪律

```
src/quickquip/{chat,common,llm,games,generation,tieba,search}/  ← 框架无关的业务逻辑
src/quickquip/adapters/nonebot/                                  ← NoneBot2 适配层（matcher / 命令注册 / 调度）
src/plugins/                                                     ← NoneBot2 插件入口 shim（只 re-export）
src/quickquip/app/                                               ← 应用组装（流水线装配、Web Admin）
```

**允许的依赖方向**：`plugins → adapters/nonebot → 业务层 → common`；`app → 业务层`。**禁止**：

- 业务层（`chat/`、`llm/`、`games/` 等）里直接 `import nonebot` 或注册 matcher
- `plugins/` shim 里写业务逻辑（只允许 re-export 指向 `quickquip.*`）
- `common/` 反向依赖 `chat/`、`llm/` 等上层业务包
- 适配层里写纯业务算法（应下沉到业务层）

### 抽取的触发条件

遇到以下任一情况**立即**抽成独立单元，不要等下次 PR：

- 同一段逻辑或常量在 ≥2 个地方出现（DRY）
- 一个函数超过 ~50 行或嵌套超过 3 层
- 一段逻辑有明显的"状态 + 更新 + 查询"三要素（→ 独立类）
- 一段逻辑需要单独测试（→ 独立纯函数或模块）

### 模块化 vs 过度抽象

不要为了抽而抽。**单次使用、少于 10 行、语义清晰**的内联代码不需要抽。判断基准："如果我明天给这块代码写单测或者重用它，现在的形状会让我想重写吗？"——会就抽，不会就留着。

### 命名与样式

- 遵循 [PEP 8](https://peps.python.org/pep-0008/)；ruff 已配 `line-length = 100`，规则集 `E + F`
- 公开 API（模块顶层函数/类、非 `_` 前缀）必须有 docstring，说明 **what + why**，不说 **how**
- 纯函数优先放模块顶层；有状态的用 `class`
- 不写"废话注释"（`# increment i by 1`）；非显而易见的约束、反直觉的 workaround 必须注释
- `dataclass` 保持 data-only——不在 `dataclass` 里塞业务方法，相关纯函数放到同模块顶层
- 常量用 `UPPER_CASE` 模块级变量；跨模块共享的常量集中到一个 `constants` 模块，禁止散落

### 前端（Vue 3）专项

`frontend/` 是 Web Admin SPA（Vue 3 + `<script setup>` + TypeScript + Vite）。SPA 层容易变成面条，额外要求：

- **组件 props 只接 data**——不接服务实例；数据获取走 `composables/` 或 `api/`
- **不在 `<script setup>` 里堆业务逻辑**——超过 ~50 行或有明显状态管理的，抽到 `composables/useXxx.ts`
- **单文件组件超过 ~300 行要拆**——拆子组件到 `components/`，或拆 composable
- **类型定义集中**——API 响应类型放 `api/`，组件局部类型定义在 `<script setup>` 顶部
- 不要让一个组件根据状态返回多个截然不同的整页 UI（`v-if="loading"` → `v-else-if="error"` → `v-else` 一长串）——拆成多个子组件，在父组件分支

### 触及现有坏味道时

遵循"**童子军规则**"：

- **离开比到来时更干净一点**。改一个函数顺手把它的命名、缩进、局部变量理顺
- **不做 "顺便大重构"**：看到 `llm/service.py` 面条不代表可以在 bugfix PR 里顺手把它拆了。**专门开一个 `refactor(llm)` PR**，说明动机、范围、验证方式
- **拆一个坏文件的 PR，不要再顺便加新功能**。保持重构 PR 的 diff 尽量只在移动代码

### 常见反模式（见到就阻止）

这些是维护者看一眼就会皱眉的东西。不要在本仓库出现：

- 千行以上的单文件业务模块（存量积压例外，但不应新增）
- 业务层（`chat/`、`llm/`、`games/` 等）里出现 `import nonebot` 或 NoneBot matcher 注册
- `if kind == "a" / elif kind == "b"` 每处都要手动加分支的"类型 tag"（考虑 `Enum` + `match`，或拆成独立的策略类/分发字典）
- 杂物工具模块（`utils.py` / `helpers.py` 堆放互不相关函数）——按主题拆专用的模块
- 跨层调用（业务层直接 `import nonebot`；`plugins/` 里写业务；`common/` 反向依赖上层）
- 同一份常量或字面量在多个文件散落（必须走模块级常量或 `constants` 模块）
- 配置读取散落在多个模块（应集中到 `llm/config.py`、`generation/config.py` 等专用 config 模块）

### 何时是重构 PR 的好时机

- 准备在某个模块加新功能，发现"得先清理才能干净地加"—— **先开一个 refactor PR，merge 后再开 feature PR**
- AI CR（Claude / Gemini code review）里连续两次指出同一类坏味道
- 文件大小、嵌套深度跨过预警线
