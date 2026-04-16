// Navigation configuration.
// This array is the single source of truth for the admin sidebar/topnav.
// When migrating to vue-router in the future, map this directly to route records.

import StatsView from '../views/StatsView.vue'
import RulesView from '../views/RulesView.vue'
import GroupsView from '../views/GroupsView.vue'
import MemoryView from '../views/MemoryView.vue'
import SummaryView from '../views/SummaryView.vue'
import ConfigView from '../views/ConfigView.vue'

export const NAV_ITEMS = [
  { key: 'stats',   label: '统计', icon: 'BarChart3',  component: StatsView },
  { key: 'rules',   label: '规则', icon: 'ToggleLeft', component: RulesView },
  { key: 'groups',  label: '群组', icon: 'Users',      component: GroupsView },
  { key: 'memory',  label: '记忆', icon: 'Brain',      component: MemoryView },
  { key: 'summary', label: '总结', icon: 'FileText',   component: SummaryView },
  { key: 'config',  label: '配置', icon: 'Settings',   component: ConfigView },
]

// Future route migration snippet (kept here for reference):
// const routes = NAV_ITEMS.map(item => ({
//   path: `/${item.key}`,
//   name: item.key,
//   component: item.component,
// }))
