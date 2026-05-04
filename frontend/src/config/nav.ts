// Single source of truth for admin nav. Router in src/router/index.js reads
// path/component from here; AppNav reads key/label/icon.

import type { Component } from 'vue'
import StatsView from '../views/StatsView.vue'
import RulesView from '../views/RulesView.vue'
import GroupsView from '../views/GroupsView.vue'
import MemoryView from '../views/MemoryView.vue'
import SummaryView from '../views/SummaryView.vue'
import ConversationsView from '../views/ConversationsView.vue'
import PersonasView from '../views/PersonasView.vue'
import LlmAboutView from '../views/LlmAboutView.vue'
import GroupSettingsView from '../views/GroupSettingsView.vue'
import RateLimitView from '../views/RateLimitView.vue'
import TiebaView from '../views/TiebaView.vue'
import WordcloudView from '../views/WordcloudView.vue'
import ConfigView from '../views/ConfigView.vue'
import DiagnosticsView from '../views/DiagnosticsView.vue'
import McpDashboardView from '../views/McpDashboardView.vue'

export interface NavItem {
  key: string
  path: string
  label: string
  icon: string
  component: Component
}

export const NAV_ITEMS: NavItem[] = [
  { key: 'stats',          path: '/stats',          label: '统计',     icon: 'BarChart3',     component: StatsView },
  { key: 'rules',          path: '/rules',          label: '规则',     icon: 'ToggleLeft',    component: RulesView },
  { key: 'groups',         path: '/groups',         label: '群组',     icon: 'Users',         component: GroupsView },
  { key: 'memory',         path: '/memory',         label: '记忆',     icon: 'Brain',         component: MemoryView },
  { key: 'summary',        path: '/summary',        label: '总结',     icon: 'FileText',      component: SummaryView },
  { key: 'conversations',  path: '/conversations',  label: '对话',     icon: 'MessageCircle', component: ConversationsView },
  { key: 'personas',       path: '/personas',       label: '人格',     icon: 'Drama',         component: PersonasView },
  { key: 'llm-about',      path: '/llm-about',      label: '资料',     icon: 'BookUser',      component: LlmAboutView },
  { key: 'group-settings', path: '/group-settings', label: '群 LLM',   icon: 'SlidersHorizontal', component: GroupSettingsView },
  { key: 'rate-limit',     path: '/rate-limit',     label: '限流',     icon: 'Zap',           component: RateLimitView },
  { key: 'tieba',          path: '/tieba',          label: '贴吧',     icon: 'BookOpen',      component: TiebaView },
  { key: 'wordcloud',      path: '/wordcloud',      label: '词云',     icon: 'Newspaper',     component: WordcloudView },
  { key: 'config',         path: '/config',         label: '配置',     icon: 'Settings',      component: ConfigView },
  { key: 'diagnostics',    path: '/diagnostics',    label: '诊断',     icon: 'Stethoscope',   component: DiagnosticsView },
  { key: 'mcp-dashboard', path: '/mcp-dashboard', label: 'MCP',      icon: 'Server',        component: McpDashboardView },
]
