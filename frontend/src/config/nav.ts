import type { Component } from 'vue'
import DashboardView from '../views/DashboardView.vue'
import StatsView from '../views/StatsView.vue'
import RulesView from '../views/RulesView.vue'
import GroupsView from '../views/GroupsView.vue'
import MemoryView from '../views/MemoryView.vue'
import SummaryView from '../views/SummaryView.vue'
import ConversationsView from '../views/ConversationsView.vue'
import PersonasView from '../views/PersonasView.vue'
import LlmAboutView from '../views/LlmAboutView.vue'
import GroupSettingsView from '../views/GroupSettingsView.vue'
import AwakeningView from '../views/AwakeningView.vue'
import RateLimitView from '../views/RateLimitView.vue'
import TiebaView from '../views/TiebaView.vue'
import QuotesView from '../views/QuotesView.vue'
import WordcloudView from '../views/WordcloudView.vue'
import ConfigView from '../views/ConfigView.vue'
import LogsLiveView from '../views/LogsLiveView.vue'
import LogsTraceView from '../views/LogsTraceView.vue'
import LogsArchiveView from '../views/LogsArchiveView.vue'
import DiagnosticsView from '../views/DiagnosticsView.vue'
import McpDashboardView from '../views/McpDashboardView.vue'
import CronDashboardView from '../views/CronDashboardView.vue'
import AuditView from '../views/AuditView.vue'
import GameEconomyView from '../views/GameEconomyView.vue'
import NiuNiuView from '../views/NiuNiuView.vue'

export interface NavItem {
  key: string
  path: string
  label: string
  icon: string
  section: string
  component: Component
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
  { key: 'llm', label: 'LLM 工坊', icon: 'BrainCircuit', description: '记忆、人格、资料与诊断工具' },
  { key: 'content', label: '内容流', icon: 'Newspaper', description: '总结、贴吧与词云产物' },
  { key: 'system', label: '系统', icon: 'ServerCog', description: '配置、日志、定时任务与审计记录' },
  { key: 'games', label: '游戏', icon: 'Gamepad2', description: '金币经济与牛牛大作战' },
]

export const NAV_ITEMS: NavItem[] = [
  { key: 'home',           path: '/',               label: '概览',     icon: 'LayoutDashboard', section: 'overview', component: DashboardView },
  { key: 'stats',          path: '/stats',          label: '统计',     icon: 'BarChart3',       section: 'ops',      component: StatsView },
  { key: 'rules',          path: '/rules',          label: '规则',     icon: 'ToggleLeft',      section: 'ops',      component: RulesView },
  { key: 'groups',         path: '/groups',         label: '群组',     icon: 'Users',           section: 'ops',      component: GroupsView },
  { key: 'group-settings', path: '/group-settings', label: '群 LLM',   icon: 'SlidersHorizontal', section: 'ops',    component: GroupSettingsView },
  { key: 'awakening',      path: '/awakening',      label: '唤醒',     icon: 'BellRing',        section: 'ops',      component: AwakeningView },
  { key: 'rate-limit',     path: '/rate-limit',     label: '限流',     icon: 'Gauge',           section: 'ops',      component: RateLimitView },
  { key: 'memory',         path: '/memory',         label: '记忆',     icon: 'Brain',           section: 'llm',      component: MemoryView },
  { key: 'conversations',  path: '/conversations',  label: '对话',     icon: 'MessageCircle',   section: 'llm',      component: ConversationsView },
  { key: 'personas',       path: '/personas',       label: '人格',     icon: 'Drama',           section: 'llm',      component: PersonasView },
  { key: 'llm-about',      path: '/llm-about',      label: '资料',     icon: 'BookUser',        section: 'llm',      component: LlmAboutView },
  { key: 'diagnostics',    path: '/diagnostics',    label: '诊断',     icon: 'Stethoscope',     section: 'llm',      component: DiagnosticsView },
  { key: 'mcp-dashboard',  path: '/mcp-dashboard',  label: 'MCP',      icon: 'Network',         section: 'llm',      component: McpDashboardView },
  { key: 'summary',        path: '/summary',        label: '总结',     icon: 'FileText',        section: 'content',  component: SummaryView },
  { key: 'quotes',         path: '/quotes',         label: '语录',     icon: 'Quote',           section: 'content',  component: QuotesView },
  { key: 'tieba',          path: '/tieba',          label: '贴吧',     icon: 'BookOpen',        section: 'content',  component: TiebaView },
  { key: 'wordcloud',      path: '/wordcloud',      label: '词云',     icon: 'Cloud',           section: 'content',  component: WordcloudView },
  { key: 'config',         path: '/config',         label: '配置',     icon: 'Settings',        section: 'system',   component: ConfigView },
  { key: 'logs-live',      path: '/logs-live',      label: '实时日志', icon: 'Server',          section: 'system',   component: LogsLiveView },
  { key: 'logs-trace',     path: '/logs-trace',     label: 'LLM Trace', icon: 'FileCode',        section: 'system',   component: LogsTraceView },
  { key: 'logs-archive',   path: '/logs-archive',   label: '日志归档', icon: 'FolderOpen',      section: 'system',   component: LogsArchiveView },
  { key: 'cron-dashboard', path: '/cron-dashboard', label: '定时任务', icon: 'Clock',           section: 'system',   component: CronDashboardView },
  { key: 'audit',          path: '/audit',          label: '审计',     icon: 'ShieldCheck',     section: 'system',   component: AuditView },
  { key: 'game-economy',   path: '/game-economy',   label: '金币',     icon: 'Coins',           section: 'games',    component: GameEconomyView },
  { key: 'niuniu',         path: '/niuniu',         label: '牛牛',     icon: 'Swords',          section: 'games',    component: NiuNiuView },
]
