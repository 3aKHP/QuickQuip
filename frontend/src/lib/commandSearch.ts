/**
 * Command Palette 模糊检索与排序引擎（纯 TS，便于单元测试）。
 * 支持中文名称、域标签、路径、英文关键词与拼音首字母简拼。
 */
import type { NavItem, NavSection } from '../config/nav'

export type CommandKind = 'route' | 'action'
export type CommandActionId = 'toggle-theme' | 'toggle-motion' | 'logout'

export interface CommandEntry {
  id: string
  kind: CommandKind
  label: string
  section: string
  sectionLabel: string
  icon: string
  path?: string
  actionId?: CommandActionId
  keywords: string[]
}

/** 各路由的补充检索词（英文别名 + 拼音首字母 + 运维高频术语） */
export const NAV_KEYWORDS: Record<string, string[]> = {
  home:                 ['dashboard', 'overview', 'sy', 'gl', '首页', '总览', '仪表盘'],
  stats:                ['statistics', 'tj', '消息统计', '排行', '数据'],
  rules:                ['rule', 'gz', 'chat_rules', '开关', '关键词', '复读'],
  groups:               ['group', 'qz', '群列表', '群聊'],
  'group-settings':     ['qllm', 'override', '群覆盖', '群设置', '群配置'],
  awakening:            ['hx', 'boredom', '主动搭话', '无聊'],
  'rate-limit':         ['xl', 'ratelimit', '频率', '限速'],
  'llm-config':         ['llmpz', 'provider', 'mcp', 'model', '模型', '供应商', '工具', '人设配置'],
  personas:             ['rg', 'persona', '人设', '提示词', 'prompt'],
  skills:               ['skill', 'jn', '技能', '扩展'],
  'llm-about':          ['zl', 'about', '自我介绍', '资料卡'],
  memory:               ['jy', 'mem', '长期记忆', '印象'],
  conversations:        ['dh', 'chat', 'history', '会话', '聊天记录'],
  epochs:               ['jy', 'epoch', 'window', '锚点', '上下文窗口', '纪元看板'],
  'llm-usage':          ['yl', 'usage', 'token', 'cost', '费用', '消耗'],
  diagnostics:          ['zd', 'diag', 'probe', '连通性', '体检', '测试'],
  summary:              ['zj', 'report', '日报', '周报', '总结'],
  quotes:               ['yl', 'quote', '名言', '语录库'],
  tieba:                ['tb', '贴吧', '同步'],
  wordcloud:            ['cy', 'word', '词云图'],
  environment:          ['hjbl', 'env', 'secret', 'dotenv', '密钥', '变量'],
  config:               ['pz', 'toml', 'settings', '全局配置', '系统配置'],
  'logs-live':          ['ssrz', 'log', 'sse', 'stream', '实时', '日志流'],
  'logs-trace':         ['trace', 'rz', '请求追踪', 'llm日志'],
  'logs-archive':       ['rzgd', 'archive', '历史日志', '归档'],
  'cron-dashboard':     ['ddq', 'cron', 'scheduler', '计划任务', '调度'],
  'scheduled-messages': ['dsxx', 'schedule', '定时发送', '一次性任务', '定时'],
  audit:                ['sj', 'audit', '操作记录', '审计日志'],
  'game-economy':       ['jb', 'gold', 'economy', '金币', '经济', '排行榜'],
  niuniu:               ['nn', 'battle', '牛牛大作战', '决斗'],
}

export interface BuildCommandOptions {
  theme: 'light' | 'dark'
  lowMotion: boolean
}

export function buildCommandEntries(
  items: NavItem[],
  sections: NavSection[],
  opts: BuildCommandOptions,
): CommandEntry[] {
  const sectionMap = new Map(sections.map(s => [s.key, s.label]))
  const routeEntries: CommandEntry[] = items.map((item) => ({
    id: `route:${item.key}`,
    kind: 'route',
    label: item.label,
    section: item.section,
    sectionLabel: sectionMap.get(item.section) || item.section,
    icon: item.icon,
    path: item.path,
    keywords: [
      item.key,
      item.path,
      ...(NAV_KEYWORDS[item.key] ?? []),
    ],
  }))

  const actionEntries: CommandEntry[] = [
    {
      id: 'action:toggle-theme',
      kind: 'action',
      actionId: 'toggle-theme',
      label: opts.theme === 'dark' ? '切换为亮色主题' : '切换为暗色主题',
      section: 'action',
      sectionLabel: '快捷操作',
      icon: opts.theme === 'dark' ? 'Sun' : 'Moon',
      keywords: ['theme', 'dark', 'light', 'zt', '主题', '暗色', '亮色', '深色', '浅色'],
    },
    {
      id: 'action:toggle-motion',
      kind: 'action',
      actionId: 'toggle-motion',
      label: opts.lowMotion ? '关闭低动态模式' : '开启低动态模式',
      section: 'action',
      sectionLabel: '快捷操作',
      icon: opts.lowMotion ? 'Zap' : 'ZapOff',
      keywords: ['motion', 'reduced', 'ddt', '低动态', '动画', '流畅', '节能'],
    },
    {
      id: 'action:logout',
      kind: 'action',
      actionId: 'logout',
      label: '退出管理台登录',
      section: 'action',
      sectionLabel: '快捷操作',
      icon: 'LogOut',
      keywords: ['logout', 'signout', 'tc', '退出', '登出', '注销'],
    },
  ]

  return [...routeEntries, ...actionEntries]
}

/**
 * 计算单个候选词与查询串的匹配分（0 表示不匹配，越高越靠前）：
 * - 完全相等：120
 * - 前缀命中：96
 * - 子串命中：76（越靠前分越高）
 * - 有序模糊字符命中：30..64（连续命中加分）
 */
export function fuzzyScore(query: string, candidate: string): number {
  const q = query.trim().toLowerCase()
  const c = candidate.toLowerCase()
  if (!q) return 1
  if (c === q) return 120
  if (c.startsWith(q)) return 96
  const idx = c.indexOf(q)
  if (idx >= 0) return Math.max(66, 84 - idx)

  // 有序子序列模糊匹配
  let qi = 0
  let streak = 0
  let bonus = 0
  for (let ci = 0; ci < c.length && qi < q.length; ci++) {
    if (c[ci] === q[qi]) {
      qi += 1
      streak += 1
      bonus += streak > 1 ? 6 : 2
    } else {
      streak = 0
    }
  }
  if (qi < q.length) return 0
  return Math.min(64, 30 + bonus - Math.min(20, c.length - q.length))
}

export function searchCommandEntries(
  entries: CommandEntry[],
  rawQuery: string,
  recentPaths: string[] = [],
): CommandEntry[] {
  const q = rawQuery.trim()
  if (!q) {
    // 空输入：最近访问置顶，其次按自然菜单顺序返回
    if (!recentPaths.length) return entries
    const rank = new Map(recentPaths.map((p, idx) => [p, idx]))
    return entries.slice().sort((a, b) => {
      const ra = a.path !== undefined && rank.has(a.path) ? rank.get(a.path)! : Number.MAX_SAFE_INTEGER
      const rb = b.path !== undefined && rank.has(b.path) ? rank.get(b.path)! : Number.MAX_SAFE_INTEGER
      return ra - rb
    })
  }

  const scored: Array<{ entry: CommandEntry; score: number; index: number }> = []
  entries.forEach((entry, index) => {
    let best = Math.max(
      fuzzyScore(q, entry.label) * 1.15,
      fuzzyScore(q, entry.sectionLabel) * 0.85,
    )
    for (const kw of entry.keywords) {
      const s = fuzzyScore(q, kw)
      if (s > best) best = s
    }
    if (best > 0) scored.push({ entry, score: best, index })
  })

  scored.sort((a, b) => b.score - a.score || a.index - b.index)
  return scored.map(item => item.entry)
}
