import { fetchStats } from './stats'
import { listGroups as fetchGameGroups } from './game-economy'
import { listConversations } from './conversations'
import { fetchCronDashboard } from './cronDashboard'

export interface DashboardData {
  totalGroups: number
  totalMessages: number
  totalUsers: number
  totalGold: number
  goldUserCount: number
  groupMessages: { gid: string; count: number }[]
  ruleTriggers: { rule: string; count: number }[]
  cronJobs: { ok: number; error: number; total: number }
  llmConversations: { count: number; latest: string }
  failedSources: string[]
}

export async function fetchDashboardData(): Promise<DashboardData> {
  const results = await Promise.allSettled([
    fetchStats(),
    fetchGameGroups(),
    listConversations(),
    fetchCronDashboard(),
  ])

  const labels = ['消息统计', '游戏经济', 'LLM 对话', '调度器'] as const
  const failedSources: string[] = []
  let firstError: unknown = null

  results.forEach((res, idx) => {
    if (res.status === 'rejected') {
      failedSources.push(labels[idx])
      if (firstError === null) firstError = res.reason
    }
  })

  if (failedSources.length === results.length) {
    throw firstError instanceof Error ? firstError : new Error(String(firstError || '所有数据源加载失败'))
  }

  const stats: Record<string, any> = results[0].status === 'fulfilled' && results[0].value ? results[0].value : {}
  const gameGroups: { groups?: any[] } = results[1].status === 'fulfilled' && results[1].value ? results[1].value : { groups: [] }
  const convs: { conversations?: any[] } = results[2].status === 'fulfilled' && results[2].value ? results[2].value : { conversations: [] }
  const cron: { jobs?: any[] } = results[3].status === 'fulfilled' && results[3].value ? results[3].value : { jobs: [] }

  // Aggregate stats across all groups
  let totalMessages = 0
  const userSet = new Set<string>()
  const groupMessages: { gid: string; count: number }[] = []
  const ruleMap = new Map<string, number>()

  for (const [gid, gs] of Object.entries(stats)) {
    const s = gs as any
    totalMessages += s.total_messages || 0
    groupMessages.push({ gid, count: s.total_messages || 0 })
    for (const uid of Object.keys(s.user_messages || {})) userSet.add(uid)
    for (const [rule, cnt] of Object.entries(s.rule_triggers || {})) {
      ruleMap.set(rule, (ruleMap.get(rule) || 0) + (cnt as number))
    }
  }

  groupMessages.sort((a, b) => b.count - a.count)
  const ruleTriggers = Array.from(ruleMap.entries())
    .map(([rule, count]) => ({ rule, count }))
    .sort((a, b) => b.count - a.count)

  // Game economy
  let totalGold = 0
  let goldUserCount = 0
  for (const g of gameGroups.groups || []) {
    totalGold += g.total_gold || 0
    goldUserCount += g.user_count || 0
  }

  // Cron jobs
  const jobs = cron.jobs || []
  const cronOk = jobs.filter((j: any) => j.last_status === 'ok').length
  const cronError = jobs.filter((j: any) => j.last_status === 'error').length

  // LLM conversations
  const convList = convs.conversations || []
  const llmConvs = {
    count: convList.reduce((s: number, c: any) => s + (c.count || 0), 0),
    latest: convList[0]?.latest || '',
  }

  return {
    totalGroups: Object.keys(stats).length,
    totalMessages,
    totalUsers: userSet.size,
    totalGold,
    goldUserCount,
    groupMessages: groupMessages.slice(0, 5),
    ruleTriggers: ruleTriggers.slice(0, 5),
    cronJobs: { ok: cronOk, error: cronError, total: jobs.length },
    llmConversations: llmConvs,
    failedSources,
  }
}
