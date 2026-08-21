import { request } from './index'

/** 可覆盖字段名：对应后端 GroupSettingsBody（routes/group_settings.py）与 GroupSettingsOverride dataclass */
export type GroupOverrideField =
  | 'enabled'
  | 'memory_enabled'
  | 'auto_memory_enabled'
  | 'provider_id'
  | 'model'
  | 'persona_id'
  | 'trigger_prefix'
  | 'allow_prefix'
  | 'allow_at'
  | 'history_limit'

/** 单字段取值：布尔开关 / 字符串 id 或前缀 / 数值上限；null 见下方三态约定 */
export type GroupOverrideValue = boolean | string | number | null

/**
 * 群级 override 草稿与读取形状（对应 GET /api/group-settings/{group_id}，
 * 即 GroupSettingsOverride 的 asdict 投影）。
 *
 * 三态约定：null = 跟随默认（无 override / 显式清空）；非 null = 显式覆盖值。
 * 第三态「未碰」不落在此类型上，由视图用 draft vs original 的 diff 表达——
 * diff 中缺省的字段不发送，后端 exclude_unset 保证其不被改动。
 */
export interface GroupOverrideDraft {
  enabled: boolean | null
  memory_enabled: boolean | null
  auto_memory_enabled: boolean | null
  provider_id: string | null
  model: string | null
  persona_id: string | null
  trigger_prefix: string | null
  allow_prefix: boolean | null
  allow_at: boolean | null
  history_limit: number | null
}

/**
 * PUT body（对应后端 model_dump(exclude_unset=True) 语义）：
 * 字段缺省 = 不动；显式 null = 清空该字段 override（回到默认）；其余 = 设为该值。
 */
export type GroupOverridePatch = Partial<Record<GroupOverrideField, GroupOverrideValue>>

/** GET /api/group-settings 列表元素：override 字段 + 归属元信息 */
export interface GroupOverrideEntry extends GroupOverrideDraft {
  group_id: string
  type: 'group' | 'private'
  updated_at: string | null
}

export interface GroupSettingsProviderOption {
  id: string
  default_model: string | null
  models: string[]
}

export interface GroupSettingsPersonaOption {
  id: string
  display_name: string | null
  scope: string[]
}

/**
 * GET /api/group-settings/options 的 defaults（全局默认配置投影）。
 * llm.toml 加载失败时后端返回空对象，故全部字段可选。
 */
export interface GroupSettingsDefaults {
  enabled?: boolean
  memory_enabled?: boolean
  auto_memory_enabled?: boolean
  provider_id?: string | null
  persona_id?: string | null
  trigger_prefix?: string | null
  allow_prefix?: boolean
  allow_at?: boolean
  history_limit?: number
}

export interface GroupSettingsOptions {
  providers: GroupSettingsProviderOption[]
  personas: GroupSettingsPersonaOption[]
  defaults: GroupSettingsDefaults
  load_error: string | null
}

export async function fetchOptions(): Promise<GroupSettingsOptions> {
  return request('/api/group-settings/options')
}

export async function listGroupSettings(): Promise<{ groups: GroupOverrideEntry[] }> {
  return request('/api/group-settings')
}

export async function fetchGroupSettings(groupId: string): Promise<GroupOverrideDraft> {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`)
}

export async function saveGroupSettings(
  groupId: string,
  fields: GroupOverridePatch,
): Promise<{ ok: boolean }> {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    body: JSON.stringify(fields),
  })
}

export async function clearGroupSettings(groupId: string): Promise<{ deleted: number }> {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`, {
    method: 'DELETE',
  })
}
