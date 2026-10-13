export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject
export interface JsonObject { [key: string]: JsonValue }
export interface FieldMetadata { type?: string; minimum?: number; maximum?: number | null; default?: JsonValue; inherit?: boolean; enum?: JsonValue[]; nullable?: boolean; description?: string }
export function isObject(value: unknown): value is JsonObject { return typeof value === 'object' && value !== null && !Array.isArray(value) }
export function fieldTemplate(key: string): JsonObject {
  const templates: Record<string, JsonObject> = {
    providers: { id: '', protocol: 'openai', client_fingerprint: 'default', base_url: '', api_key_env: '', auth_method: 'api_key', enabled: true, default_model: '', headers: {}, fallback_urls: [], proxy: '', parameters: {}, models: [], aliases: [] },
    models: { model: '', enabled: true, vision: true, context_window: null, parameters: {} },
    aliases: { alias: '', model: '' },
    entries: { provider_id: '', model: '' },
    style_profiles: { id: '', prompt: '' },
    pricing: { provider_id: null, model: '', input_per_mtok: 0, output_per_mtok: 0, cache_read_per_mtok: null, cache_write_per_mtok: null },
    daily_summary: { provider_id: '', model: '' },
    daily_briefing: { provider_id: '', model: '' },
    weekly_report: { provider_id: '', model: '' },
    monthly_report: { provider_id: '', model: '' },
    servers: { id: '', enabled: true, transport: 'stdio', command: '', args: [], env: {}, headers: {}, url: '' },
  }
  return templates[key] || {}
}
export function configError(error: unknown): { message: string; conflict: boolean; details: unknown } {
  const candidate = error as { status?: number; message?: string; data?: unknown }
  const data = isObject(candidate.data) ? candidate.data : {}
  const detail = isObject(data.detail) ? data.detail : data
  const message = typeof detail.message === 'string' ? detail.message : candidate.message || '操作失败'
  const field = typeof detail.field_path === 'string' && detail.field_path ? `（${detail.field_path}）` : ''
  return { message: message + field, conflict: candidate.status === 409 && (!detail.code || detail.code === 'revision_conflict'), details: detail.details }
}
export function parseConfigImport(text: string): JsonObject {
  if (new TextEncoder().encode(text).length > 1024 * 1024) throw new Error('配置文件超过 1 MiB')
  const document: unknown = JSON.parse(text)
  if (!isObject(document)) throw new Error('配置交换格式必须为 JSON 对象')
  return document
}
export function isOperationFinished(status: string) { return ['succeeded', 'failed', 'cancelled'].includes(status) }

/* ────────────────────────────────────────────────────────────────────────
 * 展示层词典：把人话标签、提示与分组集中在一处，组件只负责渲染。
 * ──────────────────────────────────────────────────────────────────────── */

export interface FieldLabel { label: string; hint?: string; unit?: string; placeholder?: string }

export const PROTOCOL_LABELS: Record<string, string> = {
  openai: 'OpenAI 兼容',
  claude: 'Claude（Anthropic）',
  gemini: 'Gemini（Google）',
  openai_responses: 'OpenAI Responses',
}

export const OPERATION_STATUS_LABELS: Record<string, string> = {
  queued: '排队中', running: '执行中', succeeded: '已成功', failed: '失败', cancelled: '已取消',
}

export const OPERATION_KIND_LABELS: Record<string, string> = { apply: '应用配置', probe: '模型探测' }

export const PARAM_SOURCE_LABELS: Record<string, string> = {
  builtin: '内置默认', runtime: '全局设置', provider: '渠道覆盖', model: '模型覆盖', automatic: '自动识别', unknown: '无法确定',
}

/** 26 个请求参数的中文标签与说明；分组决定 ProvidersPanel 的展示结构 */
export const PARAM_LABELS: Record<string, FieldLabel> = {
  temperature: { label: '温度', hint: '采样温度，越高越发散。0–2。' },
  max_output_tokens: { label: '最大输出 token', hint: '单次回复允许生成的 token 上限。' },
  style_profile: { label: '风格档案', hint: '引用「回复风格」中定义的风格名。' },
  style_overrides: { label: '风格附加文本', hint: '拼接在风格档案之后的补充指令。' },
  reasoning_effort: { label: '思考档位', hint: '留空表示不发送思考参数。' },
  timeout_seconds: { label: '请求超时', unit: '秒', hint: '单次 API 请求的超时时间。' },
  stream_enabled: { label: '流式输出', hint: '开启后边生成边返回。' },
  user_agent: { label: 'User-Agent', hint: '请求头中的客户端标识，留空用默认。' },
  extra_body: { label: '附加请求体', hint: '整体合并进请求 JSON，键冲突时覆盖。' },
  prompt_caching: { label: '提示词缓存', hint: '对支持的渠道开启上下文缓存。' },
  cache_ttl: { label: '缓存时长', hint: '提示词缓存的保留时长。' },
  builtin_search: { label: '内置搜索', hint: '仅 Gemini 协议在请求级生效。' },
  responses_profile: { label: 'Responses 端点形态', hint: '仅 OpenAI Responses 协议使用。' },
  retry_max_attempts: { label: '最大重试次数', hint: '失败后的额外尝试次数，0 表示不重试。' },
  retry_base_delay: { label: '重试基础延迟', unit: '秒' },
  retry_jitter: { label: '重试抖动', hint: '0–1，延迟随机化比例。' },
  epoch_context_tokens: { label: '纪元上下文容量', unit: 'token' },
  epoch_cold_idle_seconds: { label: '冷纪元空闲判定时长', unit: '秒' },
  epoch_cold_target_tokens: { label: '冷态压缩目标', unit: 'token' },
  epoch_cold_trigger_tokens: { label: '冷态触发阈值', unit: 'token' },
  epoch_hot_target_tokens: { label: '热态压缩目标', unit: 'token' },
  epoch_cap_tokens: { label: '纪元容量上限', unit: 'token' },
  request_input_token_budget: { label: '单次请求输入预算', unit: 'token' },
  max_inline_media_bytes: { label: '内联媒体大小上限', unit: '字节', hint: '0 表示不限制。' },
  agent_replay_loop_tokens: { label: '代理回放循环 token 数', unit: 'token' },
}

export const PARAM_GROUP_LABELS: Record<string, string> = {
  generation: '生成', connection: '请求与连接', retry: '重试', epoch: '纪元', budget: '预算与媒体',
}

export const PARAM_GROUPS: Record<string, string[]> = {
  generation: ['temperature', 'max_output_tokens', 'style_profile', 'style_overrides', 'reasoning_effort', 'prompt_caching', 'cache_ttl', 'builtin_search', 'responses_profile'],
  connection: ['timeout_seconds', 'stream_enabled', 'user_agent', 'extra_body'],
  retry: ['retry_max_attempts', 'retry_base_delay', 'retry_jitter'],
  epoch: ['epoch_context_tokens', 'epoch_cold_idle_seconds', 'epoch_cold_target_tokens', 'epoch_cold_trigger_tokens', 'epoch_hot_target_tokens', 'epoch_cap_tokens'],
  budget: ['request_input_token_budget', 'max_inline_media_bytes', 'agent_replay_loop_tokens'],
}

export const PROVIDER_FIELD_LABELS: Record<string, FieldLabel> = {
  id: { label: '渠道 ID', hint: '全局唯一，创建后不可修改。只允许字母、数字、_ . -' },
  protocol: { label: '协议' },
  base_url: { label: 'API 地址', hint: '禁止在 URL 里直接写账号密码。', placeholder: 'https://api.example.com/v1' },
  api_key_env: { label: '密钥环境变量', hint: '只填写根目录 .env 里的变量名，不是密钥本身。', placeholder: 'EXAMPLE_API_KEY' },
  auth_method: { label: '认证方式' },
  enabled: { label: '启用该渠道' },
  default_model: { label: '默认模型', hint: '未指定模型时的兜底选择，必须在模型列表中。' },
  proxy: { label: '代理', placeholder: 'http://127.0.0.1:7890' },
  fallback_urls: { label: '备用地址', hint: '主地址失败时依次尝试。' },
  headers: { label: '附加请求头', hint: '涉及密钥的值必须写成 ${变量名} 引用。' },
}

export const MODEL_FIELD_LABELS: Record<string, FieldLabel> = {
  model: { label: '模型名', hint: 'API 请求中使用的模型名称。' },
  enabled: { label: '启用' },
  vision: { label: '支持图片', hint: '关闭后不会向该模型发送图片。' },
  context_window: { label: '上下文容量', hint: '留空自动识别；识别失败将无法参与长上下文任务。', unit: 'token' },
}

/** settings 十二 section 的中文名 */
export const SETTINGS_SECTION_LABELS: Record<string, string> = {
  runtime: '总开关与默认', triggers: '触发与回复', auto_search: '自动搜索', quick_judge: '快速判定',
  tools: '工具', skills: 'Skill', mcp: 'MCP 服务', daily_summary: '每日总结', daily_briefing: '每日播报',
  weekly_report: '每周报告', monthly_report: '每月报告', image_preprocessing: '图片预处理',
}

export const SETTINGS_FIELD_LABELS: Record<string, Record<string, FieldLabel>> = {
  runtime: {
    client_cluster: { label: '部署群标识', hint: '可选；仅 QuickQuip Profile 发送，所有渠道共用。', placeholder: 'my-cluster' },
    claude_code_device_id: { label: 'Claude Code 设备标识', hint: '可选的 64 位十六进制 ID；所有 CC 渠道共用。留空使用持久随机身份，可填写已有 CC 的 userID。' },
    enabled: { label: '启用 LLM 功能', hint: '总开关。开启前至少需要一个可用渠道。' },
    memory_enabled: { label: '启用记忆', hint: '关闭后不再读写群记忆。' },
    default_provider: { label: '默认渠道', hint: '留空自动使用第一个启用的渠道。' },
    default_persona: { label: '默认人格', hint: '未指定群人格时使用的人格名。' },
    history_limit: { label: '上下文消息条数', hint: '每轮带入的历史消息条数。' },
    history_max_messages_per_group: { label: '每群历史缓存上限' },
    memory_limit: { label: '每轮带入记忆条数' },
    memory_max_items_per_group: { label: '每群记忆条数上限' },
    max_prompt_chars: { label: '提示词长度上限', unit: '字符' },
    tool_calling_enabled: { label: '启用工具调用' },
    tool_max_rounds: { label: '工具调用最大轮数' },
    tool_max_calls_per_round: { label: '每轮最大工具调用数' },
    retry_max_attempts: PARAM_LABELS.retry_max_attempts!,
    retry_base_delay: PARAM_LABELS.retry_base_delay!,
    retry_jitter: PARAM_LABELS.retry_jitter!,
    auto_memory_enabled: { label: '自动记忆', hint: '按提示词自动提炼对话写入记忆。' },
    auto_memory_prompt: { label: '自动记忆提示词' },
    auto_memory_max_tokens: { label: '自动记忆输出上限', unit: 'token' },
    epoch_context_tokens: PARAM_LABELS.epoch_context_tokens!,
    epoch_cold_idle_seconds: PARAM_LABELS.epoch_cold_idle_seconds!,
    epoch_cold_target_tokens: PARAM_LABELS.epoch_cold_target_tokens!,
    epoch_cold_trigger_tokens: PARAM_LABELS.epoch_cold_trigger_tokens!,
    epoch_hot_target_tokens: PARAM_LABELS.epoch_hot_target_tokens!,
    epoch_cap_tokens: PARAM_LABELS.epoch_cap_tokens!,
    recent_context_token_budget: { label: '近期上下文 token 预算', unit: 'token' },
    recent_context_floor_seconds: { label: '近期上下文保底时长', unit: '秒' },
    request_input_token_budget: PARAM_LABELS.request_input_token_budget!,
    agent_record_retention_days: { label: '代理记录保留天数', unit: '天' },
    agent_record_max_loops_per_scope: { label: '单域代理循环上限' },
    agent_record_max_bytes_per_scope: { label: '单域代理记录字节上限', unit: '字节' },
    agent_delivery_intermediate_enabled: { label: '投递中间过程消息' },
    agent_delivery_final_enabled: { label: '投递最终结果消息' },
    agent_replay_loop_tokens: PARAM_LABELS.agent_replay_loop_tokens!,
    reply_split_threshold_chars: { label: '长回复拆分阈值', unit: '字符', hint: '超过该长度才拆分；必须不大于单条上限。' },
    reply_chunk_max_chars: { label: '拆分后单条上限', unit: '字符' },
    reply_send_interval_ms: { label: '逐条发送间隔', unit: '毫秒' },
    reply_max_chunks_per_loop: { label: '单轮最多发送条数' },
    mention_cooldown_seconds: { label: '同一用户触发冷却', unit: '秒' },
  },
  triggers: {
    default_prefix: { label: '触发前缀', placeholder: '/ai' },
    allow_prefix: { label: '允许前缀触发' },
    allow_at: { label: '允许 @ 触发' },
    empty_prompt_reply: { label: '空内容提示语', hint: '只发触发词没带内容时回复的提示。' },
  },
  auto_search: {
    enabled: { label: '启用自动搜索' },
    search_max_calls_per_round: { label: '每轮最大搜索次数' },
  },
  quick_judge: {
    provider_id: { label: '渠道', hint: '留空跟随默认聊天渠道。' },
    model: { label: '模型', hint: '留空使用该渠道的默认模型。' },
    timeout: { label: '超时', unit: '秒' },
    max_tokens: { label: '输出上限', unit: 'token' },
  },
  tools: {
    enabled: { label: '额外启用工具', hint: '在默认白名单与 MCP 工具之上追加。' },
    enabled_mode: { label: '启用方式', hint: '追加＝在默认集合上加；替换＝严格只用列表内工具。' },
    discovery_mode: { label: '工具发现', hint: '自动＝工具数量不足时按需检索。' },
    discovery_min_tools: { label: '触发发现的工具数下限' },
    discovery_search_limit: { label: '每次检索返回数' },
    discovery_max_loaded_tools: { label: '最多同时装载工具数' },
    always_loaded: { label: '常驻工具', hint: '无论发现机制如何都直接装载。' },
  },
  skills: {
    enabled: { label: '启用 Skill' },
    catalog_dir: { label: 'Skill 目录', hint: '留空使用项目根目录 skills/。' },
    catalog_max_bytes: { label: '目录清单字节上限', unit: '字节' },
    resource_max_bytes: { label: '单资源字节上限', unit: '字节' },
    search_max_results: { label: '检索结果上限' },
    search_max_output_bytes: { label: '检索输出字节上限', unit: '字节' },
    script_timeout_ms: { label: '脚本超时', unit: '毫秒' },
    script_max_output_bytes: { label: '脚本输出字节上限', unit: '字节' },
  },
  mcp: {
    enabled: { label: '启用 MCP' },
  },
  daily_summary: {
    enabled: { label: '启用每日总结' },
    generate_cron: { label: '生成时刻（cron）', placeholder: '0 6 * * *' },
    publish_cron: { label: '发布时刻（cron）', placeholder: '0 12 * * *' },
    min_messages: { label: '最少消息数', hint: '当天消息不足则跳过。' },
    summary_length_hint: { label: '篇幅提示', unit: '字' },
  },
  daily_briefing: {
    enabled: { label: '启用每日播报' },
    morning_cron: { label: '早间时刻（cron）' },
    noon_cron: { label: '午间时刻（cron）' },
    evening_cron: { label: '晚间时刻（cron）' },
    min_messages_for_llm: { label: 'LLM 播报的最少消息数' },
    active_users_limit: { label: '活跃用户展示数' },
    hot_words_limit: { label: '热词展示数' },
    sample_messages_limit: { label: '抽样消息数' },
    max_context_chars: { label: '上下文长度上限', unit: '字符' },
    max_output_chars: { label: '播报篇幅上限', unit: '字符' },
  },
  weekly_report: {
    enabled: { label: '启用每周报告' },
    generate_cron: { label: '生成时刻（cron）', placeholder: '0 9 * * 1' },
    publish_cron: { label: '发布时刻（cron）' },
    min_messages: { label: '最少消息数' },
    length_hint: { label: '篇幅提示', unit: '字' },
  },
  monthly_report: {
    enabled: { label: '启用每月报告' },
    generate_cron: { label: '生成时刻（cron）', placeholder: '0 9 1 * *' },
    publish_cron: { label: '发布时刻（cron）' },
    min_messages: { label: '最少消息数' },
    length_hint: { label: '篇幅提示', unit: '字' },
    input_char_budget: { label: '输入字符预算', unit: '字符' },
  },
  image_preprocessing: {
    enabled: { label: '启用图片预处理', hint: '发送图片前先用视觉模型生成描述。' },
    provider_id: { label: '渠道' },
    model: { label: '模型', hint: '留空使用该渠道的默认模型；必须是视觉模型。' },
    max_tokens: { label: '输出上限', unit: 'token' },
    temperature: { label: '温度' },
    prompt: { label: '预处理提示词' },
  },
}

export const ROUTE_LABELS: Record<string, FieldLabel> = {
  daily_summary: { label: '每日总结' },
  daily_briefing: { label: '每日播报' },
  weekly_report: { label: '每周报告' },
  monthly_report: { label: '每月报告' },
}

export const MCP_TRANSPORT_OPTIONS = ['stdio', 'http', 'sse', 'docker']
export const MCP_PULL_POLICY_OPTIONS = ['always', 'missing', 'never']
export const MCP_NEGOTIATION_OPTIONS = ['legacy', 'auto', 'modern']

/** 枚举值的中文显示名（提交仍用后端枚举值） */
export const ENUM_OPTION_LABELS: Record<string, Record<string, string>> = {
  'tools.enabled_mode': { append: '追加（默认集合之上追加）', replace: '替换（只用列表内工具）' },
  'tools.discovery_mode': { off: '关闭', on: '开启', auto: '自动（不足时按需检索）' },
}

/* ────────────────────────────────────────────────────────────────────────
 * 差异人话化：后端对数组段（providers/pricing/routes）整段返回 before/after，
 * 这里按对象身份（渠道 ID、价格组合、路由链）整理成可审查的增删改。
 * ──────────────────────────────────────────────────────────────────────── */

export interface ChangeSummary { title: string; lines: string[] }

function compactJson(value: JsonValue, limit = 200): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (text === undefined) return '（空）'
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function byIdentity(list: JsonValue[], keyOf: (item: JsonObject) => string): Map<string, JsonObject> {
  const map = new Map<string, JsonObject>()
  for (const item of list) if (isObject(item)) map.set(keyOf(item), item)
  return map
}

function changedKeys(before: JsonObject, after: JsonObject): string[] {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)])
  return [...keys].filter(key => JSON.stringify(before[key] ?? null) !== JSON.stringify(after[key] ?? null))
}

function describeProviders(before: JsonValue, after: JsonValue): string[] {
  if (!Array.isArray(before) || !Array.isArray(after)) return []
  const beforeMap = byIdentity(before, item => String(item.id ?? ''))
  const afterMap = byIdentity(after, item => String(item.id ?? ''))
  const lines: string[] = []
  for (const [id, item] of afterMap) if (!beforeMap.has(id)) lines.push(`新增渠道 ${id}（${(item.models as JsonValue[])?.length ?? 0} 个模型）`)
  for (const id of beforeMap.keys()) if (!afterMap.has(id)) lines.push(`删除渠道 ${id}`)
  for (const [id, next] of afterMap) {
    const prev = beforeMap.get(id)
    if (!prev) continue
    for (const key of changedKeys(prev, next)) {
      const label = PROVIDER_FIELD_LABELS[key]?.label || key
      if (key === 'models') {
        const prevModels = byIdentity(Array.isArray(prev.models) ? prev.models : [], m => String(m.model ?? ''))
        const nextModels = byIdentity(Array.isArray(next.models) ? next.models : [], m => String(m.model ?? ''))
        for (const name of nextModels.keys()) if (!prevModels.has(name)) lines.push(`渠道 ${id}：新增模型 ${name}`)
        for (const name of prevModels.keys()) if (!nextModels.has(name)) lines.push(`渠道 ${id}：删除模型 ${name}`)
        for (const [name, model] of nextModels) {
          const old = prevModels.get(name)
          if (!old) continue
          for (const modelKey of changedKeys(old, model)) {
            if (modelKey === 'parameters') {
              lines.push(...describeParams(isObject(old.parameters) ? old.parameters : {}, isObject(model.parameters) ? model.parameters : {}, `渠道 ${id} · 模型 ${name}`))
            } else {
              lines.push(`渠道 ${id} · 模型 ${name}：${MODEL_FIELD_LABELS[modelKey]?.label || modelKey} ${compactJson(old[modelKey] ?? null, 40)} → ${compactJson(model[modelKey] ?? null, 40)}`)
            }
          }
        }
        // 同一集合的顺序变化也要可审查
        const prevOrder = (Array.isArray(prev.models) ? prev.models : []).map(m => isObject(m) ? String(m.model ?? '') : '').filter(Boolean)
        const nextOrder = (Array.isArray(next.models) ? next.models : []).map(m => isObject(m) ? String(m.model ?? '') : '').filter(Boolean)
        if (prevOrder.length === nextOrder.length && prevOrder.every(name => nextOrder.includes(name)) && JSON.stringify(prevOrder) !== JSON.stringify(nextOrder)) {
          lines.push(`渠道 ${id}：模型顺序 ${prevOrder.join('、')} → ${nextOrder.join('、')}`)
        }
      } else if (key === 'parameters') {
        lines.push(...describeParams(isObject(prev.parameters) ? prev.parameters : {}, isObject(next.parameters) ? next.parameters : {}, `渠道 ${id}`))
      } else if (key === 'aliases') {
        lines.push(`渠道 ${id}：别名变更`)
      } else {
        lines.push(`渠道 ${id}：${label} ${compactJson(prev[key] ?? null, 60)} → ${compactJson(next[key] ?? null, 60)}`)
      }
    }
  }
  // 渠道自身的顺序变化
  const prevIds = before.filter(isObject).map(item => String(item.id ?? ''))
  const nextIds = after.filter(isObject).map(item => String(item.id ?? ''))
  if (prevIds.length === nextIds.length && prevIds.every(id => nextIds.includes(id)) && JSON.stringify(prevIds) !== JSON.stringify(nextIds)) {
    lines.push(`渠道顺序：${prevIds.join('、')} → ${nextIds.join('、')}`)
  }
  return lines
}

/** 参数覆盖层的逐字段差异：中文名 + 旧值 → 新值（null 表示恢复继承） */
function describeParams(prev: JsonObject, next: JsonObject, prefix: string): string[] {
  return changedKeys(prev, next).map(key => {
    const label = PARAM_LABELS[key]?.label || key
    const oldText = prev[key] === null || prev[key] === undefined ? '跟随上层' : compactJson(prev[key] ?? null, 40)
    const newText = next[key] === null || next[key] === undefined ? '跟随上层' : compactJson(next[key] ?? null, 40)
    return `${prefix}：${label} ${oldText} → ${newText}`
  })
}

function describePricing(before: JsonValue, after: JsonValue): string[] {
  if (!Array.isArray(before) || !Array.isArray(after)) return []
  const keyOf = (item: JsonObject) => `${item.provider_id ?? '*'}::${String(item.model ?? '')}`
  const nameOf = (item: JsonObject) => item.provider_id ? `仅 ${item.provider_id} 的 ${item.model}` : `${item.model}（全渠道兜底）`
  const beforeMap = byIdentity(before, keyOf)
  const afterMap = byIdentity(after, keyOf)
  const lines: string[] = []
  for (const [key, item] of afterMap) if (!beforeMap.has(key)) lines.push(`新增价格 ${nameOf(item)}：输入 ${compactJson(item.input_per_mtok ?? null, 20)} / 输出 ${compactJson(item.output_per_mtok ?? null, 20)}`)
  for (const [key, item] of beforeMap) if (!afterMap.has(key)) lines.push(`删除价格 ${nameOf(item)}`)
  for (const [key, next] of afterMap) {
    const prev = beforeMap.get(key)
    if (!prev) continue
    for (const field of changedKeys(prev, next).filter(k => !['source', 'confidence'].includes(k))) {
      lines.push(`价格 ${nameOf(next)}：${PRICE_FIELD_LABELS[field] || field} ${compactJson(prev[field] ?? null, 20)} → ${compactJson(next[field] ?? null, 20)}`)
    }
  }
  return lines
}

const PRICE_FIELD_LABELS: Record<string, string> = {
  input_per_mtok: '输入价', output_per_mtok: '输出价', cache_read_per_mtok: '缓存读价', cache_write_per_mtok: '缓存写价',
}

function describeRoutes(fieldPath: string, before: JsonValue, after: JsonValue): string[] {
  const name = fieldPath.replace(/^routes\.?/, '')
  const label = ROUTE_LABELS[name]?.label || name
  const chainOf = (value: JsonValue) => (Array.isArray(value) ? value : [])
    .map(entry => entry === '@default' ? '默认渠道' : isObject(entry) ? `${entry.provider_id}/${entry.model}` : String(entry))
  const beforeChain = chainOf(before)
  const afterChain = chainOf(after)
  if (JSON.stringify(beforeChain) === JSON.stringify(afterChain)) return []
  const text = (chain: string[]) => chain.length ? chain.join(' → ') : '（空，等同默认渠道）'
  return [`${label}：${text(beforeChain)} ⇒ ${text(afterChain)}`]
}

function describeStyleProfiles(before: JsonValue, after: JsonValue): string[] {
  if (!isObject(before) || !isObject(after)) return []
  const lines: string[] = []
  for (const name of Object.keys(after)) if (before[name] === undefined) lines.push(`新增风格 ${name}`)
  for (const name of Object.keys(before)) if (after[name] === undefined) lines.push(`删除风格 ${name}`)
  for (const name of Object.keys(after)) if (before[name] !== undefined && before[name] !== after[name]) lines.push(`修改风格 ${name}`)
  return lines
}

/**
 * 把一条 {field_path, before, after} 差异整理成人类可读摘要。
 * lines 为空表示无法结构化（调用方回退到原始 JSON 展示）。
 */
export function describeChange(fieldPath: string, before: JsonValue, after: JsonValue): ChangeSummary {
  if (fieldPath === 'providers') return { title: '渠道', lines: describeProviders(before, after) }
  if (fieldPath === 'pricing') return { title: '价格', lines: describePricing(before, after) }
  if (fieldPath === 'style_profiles') return { title: '回复风格', lines: describeStyleProfiles(before, after) }
  if (fieldPath.startsWith('routes')) {
    const names = fieldPath === 'routes' && isObject(before) && isObject(after)
      ? [...new Set([...Object.keys(before), ...Object.keys(after)])]
      : [fieldPath.replace(/^routes\.?/, '')]
    const lines = names.flatMap(name => describeRoutes(name, isObject(before) ? before[name] ?? [] : before, isObject(after) ? after[name] ?? [] : after))
    return { title: '功能路由', lines }
  }
  return { title: fieldPath, lines: [] }
}

/** 从字符串中提取 ${VAR} / ${VAR:-default} 形式的环境变量名 */
export function envVarRefs(value: unknown): string[] {
  if (typeof value !== 'string') return []
  const names: string[] = []
  for (const match of value.matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}/g)) names.push(match[1]!)
  return names
}

/** 收集一个渠道对象里被引用的全部环境变量名（api_key_env + headers/proxy/URL 内联引用） */
export function providerEnvVars(provider: JsonObject): string[] {
  const names = new Set<string>()
  if (typeof provider.api_key_env === 'string' && provider.api_key_env) names.add(provider.api_key_env)
  for (const value of Object.values(isObject(provider.headers) ? provider.headers : {})) for (const name of envVarRefs(value)) names.add(name)
  for (const key of ['base_url', 'proxy']) for (const name of envVarRefs(provider[key])) names.add(name)
  if (Array.isArray(provider.fallback_urls)) for (const url of provider.fallback_urls) for (const name of envVarRefs(url)) names.add(name)
  return [...names]
}

/** 纪元六参数的顺序约束（文档级强校验同款）：返回第一条不满足的提示，满足返回空串 */
export function epochChainError(values: Record<string, unknown>): string {
  const n = (key: string) => (typeof values[key] === 'number' ? values[key] as number : NaN)
  const [ctx, target, trigger, hot, cap] = ['epoch_context_tokens', 'epoch_cold_target_tokens', 'epoch_cold_trigger_tokens', 'epoch_hot_target_tokens', 'epoch_cap_tokens'].map(n)
  if ([ctx, target, trigger, hot, cap].some(value => Number.isNaN(value))) return ''
  if (!(target > 0 && target < trigger)) return '冷态压缩目标必须大于 0 且小于冷态触发阈值'
  if (!(trigger <= hot)) return '冷态触发阈值必须不大于热态压缩目标'
  if (!(hot < cap)) return '热态压缩目标必须小于纪元容量上限'
  if (!(ctx > 0)) return '纪元上下文容量必须大于 0'
  return ''
}
