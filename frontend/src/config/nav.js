// Single source of truth for admin nav. Router in src/router/index.js reads
// path/component from here; AppNav reads key/label/icon.

import StatsView from '../views/StatsView.vue'
import RulesView from '../views/RulesView.vue'
import GroupsView from '../views/GroupsView.vue'
import MemoryView from '../views/MemoryView.vue'
import SummaryView from '../views/SummaryView.vue'
import ConfigView from '../views/ConfigView.vue'

export const NAV_ITEMS = [
  { key: 'stats',   path: '/stats',   label: '统计', icon: 'BarChart3',  component: StatsView },
  { key: 'rules',   path: '/rules',   label: '规则', icon: 'ToggleLeft', component: RulesView },
  { key: 'groups',  path: '/groups',  label: '群组', icon: 'Users',      component: GroupsView },
  { key: 'memory',  path: '/memory',  label: '记忆', icon: 'Brain',      component: MemoryView },
  { key: 'summary', path: '/summary', label: '总结', icon: 'FileText',   component: SummaryView },
  { key: 'config',  path: '/config',  label: '配置', icon: 'Settings',   component: ConfigView },
]
