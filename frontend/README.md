# QuickQuip Web Admin 前端

Web 管理后台（`quickquip-admin-v2`）的前端工程，一个 Vue 3 单页应用。构建产物由后端 FastAPI 以 StaticFiles 挂在 `/ops/` 下，随 `python web_api.py` 一同提供。

## 技术栈

Vue 3.5（`<script setup>`）+ TypeScript strict + Vite 8 + vue-router 4（hash 模式，base `/ops/`）。图表用 echarts 6，Markdown 渲染用 marked + dompurify，图标用 @lucide/vue。包管理使用 pnpm（Node 24）。

## 目录约定

```
src/
├── views/        # 路由页面（30 个）
├── components/   # ui/ 设计系统组件 + llm-config 等业务域子目录
├── api/          # 后端接口封装，每个领域一个模块；API 响应类型归属此处
├── composables/  # 可复用状态与请求编排
├── config/       # nav.ts：导航唯一真值源
├── charts/  lib/  styles/
tests/            # 测试双栈（见下文）
```

路由由 `config/nav.ts` 派生：新增页面在此登记，路由路径与名称按 `key` 生成。除首页静态引入外，页面组件一律路由级动态 import，按路由分包（首屏 gzip 约 69 KB）。

鉴权不依赖前端路由守卫：`App.vue` 呈现登录门，API 返回 401 时重置登录态，会话与同源检查由后端强制。鉴权结构与反向代理配置见 [docs/admin/web-admin.md](../docs/admin/web-admin.md)。

## 开发命令

```bash
pnpm install
pnpm dev          # vite 开发服务器，/ops/api 代理到 127.0.0.1:5104（需后端在跑）
pnpm build        # 产出 dist/
pnpm type-check   # vue-tsc 严格类型检查
```

## 测试双栈

| 栈 | 位置 | 运行器 | 适用场景 |
|---|---|---|---|
| 存量 harness | `tests/*.test.cjs`（59 例） | `node --test`，自建 vm harness 执行 `<script setup>` 编译产物 | 既有视图与 store 逻辑回归 |
| vitest | `tests/unit/*.test.ts`（26 例） | vitest + @vue/test-utils + happy-dom，配置在 `vite.config.ts` 的 `test` 字段 | 新组件、composable 与路由测试优先写在这里 |

```bash
pnpm test         # 依次跑两套
pnpm test:unit    # 只跑 vitest
```

## 部署

`pnpm build` 产出 `frontend/dist/`（gitignore），由后端挂载到 `/ops/`；服务器上的构建与反代流程见 [docs/admin/deployment.md](../docs/admin/deployment.md)。LLM 配置页的页面任务、字段语义与接口接线契约见 [docs/dev/llm-configuration-frontend.md](../docs/dev/llm-configuration-frontend.md)。
