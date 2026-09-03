/**
 * 定时消息简易模式 ⇄ 5 段 cron 的纯函数映射。
 *
 * 契约：
 * - cron 语义固定为 Asia/Shanghai 钟面（与后端 APScheduler 时区一致），
 *   与浏览器本地时区无关——比较与回填一律走北京钟面；
 * - 周字段 0=周一 … 6=周日（APScheduler 惯例，不支持 7）；
 * - 钉死月/日的 cron：recurring=false 才是"仅一次"；recurring=true 是"每年重复"，
 *   简易模式表达不了，解析时返回 null 由调用方回落高级模式。
 */

export type Frequency = 'daily' | 'weekly' | 'monthly' | 'once'

export interface SimpleFields {
  frequency: Frequency
  time: string // "HH:MM"，daily/weekly/monthly 使用
  weekday: number // 0=周一 … 6=周日
  dayOfMonth: number
  onceAt: string // "YYYY-MM-DDTHH:MM"（datetime-local 格式），once 使用
}

export const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export const DEFAULT_SIMPLE_FIELDS: SimpleFields = {
  frequency: 'daily',
  time: '08:00',
  weekday: 0,
  dayOfMonth: 1,
  onceAt: '',
}

const pad = (n: number) => String(n).padStart(2, '0')

/** 当前时刻的 Asia/Shanghai 钟面 [年, 月, 日, 时, 分]，与浏览器本地时区无关。 */
export function beijingWallClock(): [number, number, number, number, number] {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date())
  const get = (t: Intl.DateTimeFormatPartTypes) => Number(parts.find(p => p.type === t)?.value)
  return [get('year'), get('month'), get('day'), get('hour'), get('minute')]
}

/** "YYYY-MM-DDTHH:MM" → [年, 月, 日, 时, 分]；格式不完整返回 null。 */
function parseLocalInput(v: string): [number, number, number, number, number] | null {
  const m = v.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/)
  if (!m) return null
  return [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4]), Number(m[5])]
}

/** once 的触发时刻是否在北京时间的未来（分钟粒度；恰为当前分钟视为已过，与后端 <= 判定一致）。 */
export function onceAtInFuture(onceAt: string): boolean {
  const t = parseLocalInput(onceAt)
  if (!t) return false
  const now = beijingWallClock()
  for (let i = 0; i < 5; i++) {
    if (t[i] !== now[i]) return t[i] > now[i]
  }
  return false
}

/** 简易模式字段 → 5 段 cron；选择器未填完整（如 once 未选日期、time 被清空）时返回 null。 */
export function assembleCron(s: SimpleFields): string | null {
  if (s.frequency === 'once') {
    const t = parseLocalInput(s.onceAt)
    if (!t) return null
    return `${t[4]} ${t[3]} ${t[2]} ${t[1]} *`
  }
  const tm = s.time.match(/^(\d{2}):(\d{2})$/)
  if (!tm) return null
  const h = Number(tm[1])
  const m = Number(tm[2])
  if (s.frequency === 'daily') return `${m} ${h} * * *`
  if (s.frequency === 'weekly') return `${m} ${h} * * ${s.weekday}`
  return `${m} ${h} ${s.dayOfMonth} * *`
}

const INT_RE = /^\d+$/
const inRange = (v: string, lo: number, hi: number) =>
  INT_RE.test(v) && Number(v) >= lo && Number(v) <= hi

/** 5 段 cron → 简易模式字段；无法用简易模式表达时返回 null。
 *  拒绝的情形：字段非纯整数（步进/列表/范围）、数值越界、不存在的日历日期
 *  （如 2 月 31 日）、recurring=true 且钉死月/日（"每年重复"语义）。 */
export function parseCronToSimple(cron: string, recurring: boolean): SimpleFields | null {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return null
  const [mi, h, d, mo, w] = parts
  if (!inRange(mi, 0, 59) || !inRange(h, 0, 23)) return null
  const base: SimpleFields = { ...DEFAULT_SIMPLE_FIELDS, time: `${pad(Number(h))}:${pad(Number(mi))}` }
  if (d === '*' && mo === '*' && w === '*') return { ...base, frequency: 'daily' }
  if (d === '*' && mo === '*' && inRange(w, 0, 6)) return { ...base, frequency: 'weekly', weekday: Number(w) }
  if (inRange(d, 1, 31) && mo === '*' && w === '*') return { ...base, frequency: 'monthly', dayOfMonth: Number(d) }
  if (inRange(d, 1, 31) && inRange(mo, 1, 12) && w === '*') {
    if (recurring) return null // 钉死月/日的周期任务 = 每年重复，简易模式无此选项
    // cron 不含年份：按北京钟面判断今年该时刻是否已过，已过（含恰为当前分钟）则取明年
    const [bjY, bjMo, bjD, bjH, bjMi] = beijingWallClock()
    const tail = [Number(mo), Number(d), Number(h), Number(mi)]
    const nowTail = [bjMo, bjD, bjH, bjMi]
    let year = bjY
    let passed = true
    for (let i = 0; i < 4; i++) {
      if (tail[i] !== nowTail[i]) {
        passed = tail[i] < nowTail[i]
        break
      }
    }
    if (passed) year += 1
    // 日历真实性校验（如平年 2 月 29 日）：无法表达则回落高级模式
    if (Number(d) > new Date(year, Number(mo), 0).getDate()) return null
    return {
      ...base,
      frequency: 'once',
      onceAt: `${year}-${pad(Number(mo))}-${pad(Number(d))}T${pad(Number(h))}:${pad(Number(mi))}`,
    }
  }
  return null
}
