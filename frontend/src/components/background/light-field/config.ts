// LightField 共享配置：粒子物理、视差常量、指针星座、域染色板、双环声呐与环境判定
import type { SonarKind } from '../../../lib/lightFieldBus'

export type RGB = [number, number, number]

export interface DomainPalette {
  primary: RGB
  secondary: RGB
}

export interface Particle {
  x: number; y: number
  /** 指针斥力 / 点击冲量引起的瞬态弹簧位移与速度 */
  ox: number; oy: number
  ovx: number; ovy: number
  r: number; alpha: number; vx: number; vy: number
  twinkle: number; tone: number; layer: number
}

/** 粒子投影到屏幕后的坐标 */
export interface ScreenPoint {
  sx: number; sy: number
}

/** 操作/点击触发的双环声呐与水波脉冲 */
export interface SonarRing {
  x: number
  y: number
  radius: number
  maxRadius: number
  ageMs: number
  durationMs: number
  rgb: RGB
  kind: SonarKind
}

// 视差层：远 / 中 / 近，位移幅度递增营造纵深
export const LAYER_SHIFT = [0.75, 1.65, 3.3]

/** 归一化鼠标位移系数，驱动三层视差 */
export const PARALLAX = 0.0095
/** 鼠标光晕 lerp 尾随系数 */
export const HALO_LERP = 0.09
/** 域染色平滑过渡 lerp 系数（60fps 基准） */
export const COLOR_LERP = 0.055
/** 鼠标邻近增亮半径 */
export const GLOW_RADIUS = 230
/** 指针星座牵丝半径与最大连线数 */
export const CURSOR_LINK_RADIUS = 175
export const CURSOR_LINK_MAX = 14
/** 指针柔韧物理斥力场半径、推力强度与弹簧回弹参数 */
export const REPEL_RADIUS = 155
export const REPEL_STRENGTH = 0.72
export const SPRING_K = 0.052
export const SPRING_DAMP = 0.84
/** 暗色粒子间连线最大距离（像素） */
export const LINK_MAX = 132
/** 近层连线粒子上限，约束每帧 O(n²) 判定规模 */
export const LINK_MAX_PARTICLES = 42
/** 同屏声呐/涟漪环上限与持续时长 */
export const SONAR_MAX_RINGS = 5
export const SONAR_DURATION_MS = 860
export const RIPPLE_DURATION_MS = 560

// 暗色粒子 tone 阈值：英雄星 / 十字星 / 发光圆点
export const DARK_HERO_TONE = 0.84
export const DARK_CROSS_TONE = 0.54

// 亮色刻度粒子 tone 阈值：琥珀点缀 / 青 / 横竖向 / 双刻度 / 圆环
export const LIGHT_AMBER_TONE = 0.92
export const LIGHT_CYAN_TONE = 0.22
export const LIGHT_TICK_HORIZONTAL_TONE = 0.55
export const LIGHT_TICK_DOUBLE_TONE = 0.88
export const LIGHT_RING_TONE = 0.82

/** 六大工作域染色板（紧扣 variables.css 域色体系，切换时形成清晰的流体氛围换色） */
export const DOMAIN_PALETTES: Record<string, DomainPalette> = {
  overview: { primary: [18, 183, 245], secondary: [6, 182, 212] },
  ops:      { primary: [28, 168, 250], secondary: [56, 189, 248] },
  llm:      { primary: [6, 188, 218],  secondary: [16, 185, 168] },
  content:  { primary: [8, 152, 186],  secondary: [20, 184, 166] },
  system:   { primary: [96, 134, 178], secondary: [56, 168, 216] },
  games:    { primary: [108, 102, 246], secondary: [56, 189, 248] },
}

export function resolveDomainPalette(domain: string): DomainPalette {
  return DOMAIN_PALETTES[domain] ?? DOMAIN_PALETTES.overview
}

export function isMobile(): boolean {
  return window.innerWidth < 768
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
