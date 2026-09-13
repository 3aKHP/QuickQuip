import { request } from './index'

export type RecordPart =
  | { type: 'text'; text: string }
  | { type: 'member'; qq: string; name: string; usage: 'mention' | 'identity'; display?: string }
  | { type: 'all' }
  | { type: 'media'; media: 'image' | 'record' | 'video' | 'face' | 'forward' | 'node' }

export type RecordBody = { version: 1; parts: RecordPart[] }
export type MemberCandidate = { qq: string; name: string }
export const emptyRecordBody = (): RecordBody => ({ version: 1, parts: [{ type: 'text', text: '' }] })

export async function fetchMemberCandidates(groupId: string, query: string): Promise<MemberCandidate[]> {
  const result = await request<unknown>(`/api/members/${groupId}?query=${encodeURIComponent(query)}`)
  if (!Array.isArray(result)) throw new Error('成员列表格式无效')
  return result.filter((item): item is MemberCandidate =>
    typeof item === 'object' && item !== null && typeof item.qq === 'string' && typeof item.name === 'string',
  )
}
