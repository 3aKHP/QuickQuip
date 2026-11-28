/**
 * LightField 与状态条共享的轻量事件总线（纯 TS，无 Vue/DOM 强依赖）。
 * 负责：
 * - 工作域染色同步（overview / ops / llm / content / system / games）
 * - 路由切换跃迁冲量（与顶部 route-trace-sweep 同步）
 * - 关键运维操作的克制声呐脉冲环
 * - API 活跃度脉冲（驱动 StatusBar 实时心电波形）
 */

export type WarpDirection = 'forward' | 'back' | 'switch'
export type SonarKind = 'action' | 'success' | 'error' | 'ripple'

export interface SonarEvent {
  x?: number
  y?: number
  kind: SonarKind
  scale?: number
}

export type LightFieldEvent =
  | { type: 'domain'; domain: string }
  | { type: 'warp'; direction: WarpDirection; intensity?: number }
  | { type: 'sonar'; payload: SonarEvent }

export interface ApiActivitySnapshot {
  inFlight: number
  lastPulseAt: number
  lastOk: boolean
}

type LightFieldListener = (event: LightFieldEvent) => void
type ApiActivityListener = (snapshot: ApiActivitySnapshot) => void

const fieldListeners = new Set<LightFieldListener>()
const apiListeners = new Set<ApiActivityListener>()

let currentDomain = 'overview'
let inFlight = 0
let lastPulseAt = 0
let lastOk = true

export function subscribeLightField(listener: LightFieldListener): () => void {
  fieldListeners.add(listener)
  return () => { fieldListeners.delete(listener) }
}

export function getLightFieldDomain(): string {
  return currentDomain
}

export function setLightFieldDomain(domain: string): void {
  const normalized = domain || 'overview'
  if (normalized === currentDomain) return
  currentDomain = normalized
  const event: LightFieldEvent = { type: 'domain', domain: normalized }
  for (const fn of fieldListeners) fn(event)
}

export function triggerRouteWarp(direction: WarpDirection = 'switch', intensity?: number): void {
  const event: LightFieldEvent = intensity !== undefined
    ? { type: 'warp', direction, intensity }
    : { type: 'warp', direction }
  for (const fn of fieldListeners) fn(event)
}

export function triggerLightFieldSonar(opts: Partial<SonarEvent> = {}): void {
  const payload: SonarEvent = {
    x: opts.x,
    y: opts.y,
    kind: opts.kind ?? 'action',
  }
  if (opts.scale !== undefined) payload.scale = opts.scale
  const event: LightFieldEvent = {
    type: 'sonar',
    payload,
  }
  for (const fn of fieldListeners) fn(event)
}

export function getApiActivityState(): ApiActivitySnapshot {
  return { inFlight, lastPulseAt, lastOk }
}

export function subscribeApiActivity(listener: ApiActivityListener): () => void {
  apiListeners.add(listener)
  return () => { apiListeners.delete(listener) }
}

export function notifyApiActivity(phase: 'start' | 'end', ok = true): void {
  if (phase === 'start') {
    inFlight += 1
  } else {
    inFlight = Math.max(0, inFlight - 1)
    lastOk = ok
  }
  lastPulseAt = Date.now()
  const snap: ApiActivitySnapshot = { inFlight, lastPulseAt, lastOk }
  for (const fn of apiListeners) fn(snap)
}

export function resetLightFieldBus(): void {
  currentDomain = 'overview'
  inFlight = 0
  lastPulseAt = 0
  lastOk = true
}
