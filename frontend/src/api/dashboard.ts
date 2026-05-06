import { fetchStats } from './stats'
import { fetchKnownGroups } from './groups'
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
}

export async function fetchDashboardData(): Promise<DashboardData> {
  const [stats, known, gameGroups, convs, cron] = await Promise.all([
    fetchStats().catch(() => ({})),
    fetchKnownGroups().catch(() => ({ groups: [] })),
    fetchGameGroups().catch(() => ({ groups: [] })),
    listConversations().catch(() => ({ conversations: [] })),
    fetchCronDashboard().catch(() => ({ jobs: [] })),
  ])

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
  const llmConvs = { count: convList.reduce((s: number, c: any) => s + (c.count || 0), 0), latest: convList[0]?.latest || '' }

  return {
    totalGroups: (known.groups || []).length,
    totalMessages,
    totalUsers: userSet.size,
    totalGold,
    goldUserCount,
    groupMessages: groupMessages.slice(0, 5),
    ruleTriggers: ruleTriggers.slice(0, 5),
    cronJobs: { ok: cronOk, error: cronError, total: jobs.length },
    llmConversations: llmConvs,
  }
}
