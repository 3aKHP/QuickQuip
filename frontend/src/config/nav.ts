import type { RouteComponent } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'

export interface NavItem {
  /** 路由构建的唯一真值源：router 以 `/${key}` 生成路径与 name；path 仅用于展示/链接 */
  key: string
  path: string
  label: string
  icon: string
  section: string
  /** 首页静态引入保证落地即用；其余页面均为路由级动态 import，按路由分包、首访时才加载 */
  component: RouteComponent | (() => Promise<RouteComponent>)
}

export interface NavSection {
  key: string
  label: string
  icon: string
  description: string
}

export const NAV_SECTIONS: NavSection[] = [
  { key: 'overview', label: '总览', icon: 'LayoutDashboard', description: '运行态与全局入口' },
  { key: 'ops', label: '群聊运营', icon: 'MessagesSquare', description: '群状态、规则、限流与 LLM 覆盖' },
  { key: 'llm', label: 'LLM 工坊', icon: 'BrainCircuit', description: '全局配置、人格与 Skill 资产、对话与诊断看板' },
  { key: 'content', label: '内容流', icon: 'Newspaper', description: '总结、贴吧与词云产物' },
  { key: 'system', label: '系统', icon: 'ServerCog', description: '配置、日志、调度监控与审计记录' },
  { key: 'games', label: '游戏', icon: 'Gamepad2', description: '金币经济与牛牛大作战' },
]

export const NAV_ITEMS: NavItem[] = [
  { key: 'home',           path: '/',               label: '概览',     icon: 'LayoutDashboard', section: 'overview', component: DashboardView },
  { key: 'stats',          path: '/stats',          label: '统计',     icon: 'BarChart3',       section: 'ops',      component: () => import('../views/StatsView.vue') },
  { key: 'rules',          path: '/rules',          label: '规则',     icon: 'ToggleLeft',      section: 'ops',      component: () => import('../views/RulesView.vue') },
  { key: 'groups',         path: '/groups',         label: '群组',     icon: 'Users',           section: 'ops',      component: () => import('../views/GroupsView.vue') },
  { key: 'group-settings', path: '/group-settings', label: '群 LLM',   icon: 'SlidersHorizontal', section: 'ops',    component: () => import('../views/GroupSettingsView.vue') },
  { key: 'awakening',      path: '/awakening',      label: '唤醒',     icon: 'BellRing',        section: 'ops',      component: () => import('../views/AwakeningView.vue') },
  { key: 'rate-limit',     path: '/rate-limit',     label: '限流',     icon: 'Gauge',           section: 'ops',      component: () => import('../views/RateLimitView.vue') },
  { key: 'llm-config',     path: '/llm-config',     label: 'LLM 配置', icon: 'SlidersHorizontal', section: 'llm',     component: () => import('../views/LlmConfigView.vue') },
  { key: 'personas',       path: '/personas',       label: '人格',     icon: 'Drama',           section: 'llm',      component: () => import('../views/PersonasView.vue') },
  { key: 'skills',         path: '/skills',         label: 'Skill',    icon: 'Sparkles',        section: 'llm',      component: () => import('../views/SkillsView.vue') },
  { key: 'llm-about',      path: '/llm-about',      label: '资料',     icon: 'BookUser',        section: 'llm',      component: () => import('../views/LlmAboutView.vue') },
  { key: 'memory',         path: '/memory',         label: '记忆',     icon: 'Brain',           section: 'llm',      component: () => import('../views/MemoryView.vue') },
  { key: 'conversations',  path: '/conversations',  label: '对话',     icon: 'MessageCircle',   section: 'llm',      component: () => import('../views/ConversationsView.vue') },
  { key: 'epochs',         path: '/epochs',         label: '纪元',     icon: 'Hourglass',       section: 'llm',      component: () => import('../views/EpochsView.vue') },
  { key: 'llm-usage',      path: '/llm-usage',      label: '用量',     icon: 'Activity',        section: 'llm',      component: () => import('../views/LlmUsageView.vue') },
  { key: 'diagnostics',    path: '/diagnostics',    label: '诊断',     icon: 'Stethoscope',     section: 'llm',      component: () => import('../views/DiagnosticsView.vue') },
  { key: 'summary',        path: '/summary',        label: '总结',     icon: 'FileText',        section: 'content',  component: () => import('../views/SummaryView.vue') },
  { key: 'quotes',         path: '/quotes',         label: '语录',     icon: 'Quote',           section: 'content',  component: () => import('../views/QuotesView.vue') },
  { key: 'tieba',          path: '/tieba',          label: '贴吧',     icon: 'BookOpen',        section: 'content',  component: () => import('../views/TiebaView.vue') },
  { key: 'wordcloud',      path: '/wordcloud',      label: '词云',     icon: 'Cloud',           section: 'content',  component: () => import('../views/WordcloudView.vue') },
  { key: 'config',         path: '/config',         label: '配置',     icon: 'Settings',        section: 'system',   component: () => import('../views/ConfigView.vue') },
  { key: 'logs-live',      path: '/logs-live',      label: '实时日志', icon: 'Server',          section: 'system',   component: () => import('../views/LogsLiveView.vue') },
  { key: 'logs-trace',     path: '/logs-trace',     label: 'LLM Trace', icon: 'FileCode',        section: 'system',   component: () => import('../views/LogsTraceView.vue') },
  { key: 'logs-archive',   path: '/logs-archive',   label: '日志归档', icon: 'FolderOpen',      section: 'system',   component: () => import('../views/LogsArchiveView.vue') },
  { key: 'cron-dashboard', path: '/cron-dashboard', label: '调度器监控', icon: 'Clock',           section: 'system',   component: () => import('../views/CronDashboardView.vue') },
  { key: 'scheduled-messages', path: '/scheduled-messages', label: '定时消息', icon: 'AlarmClock', section: 'system', component: () => import('../views/ScheduledMessagesView.vue') },
  { key: 'audit',          path: '/audit',          label: '审计',     icon: 'ShieldCheck',     section: 'system',   component: () => import('../views/AuditView.vue') },
  { key: 'game-economy',   path: '/game-economy',   label: '金币',     icon: 'Coins',           section: 'games',    component: () => import('../views/GameEconomyView.vue') },
  { key: 'niuniu',         path: '/niuniu',         label: '牛牛',     icon: 'Swords',          section: 'games',    component: () => import('../views/NiuNiuView.vue') },
]
