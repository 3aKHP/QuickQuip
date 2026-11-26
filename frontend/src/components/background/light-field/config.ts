// LightField 共享配置：粒子类型、视差常量、域染色板、声呐环与环境判定

export type RGB = [number, number, number]

export interface DomainPalette {
  primary: RGB
  secondary: RGB
}

export interface Particle {
  x: number; y: number
  r: number; alpha: number; vx: number; vy: number
  twinkle: number; tone: number; layer: number
}

/** 粒子投影到屏幕后的坐标 */
export interface ScreenPoint {
  sx: number; sy: number
}

/** 关键操作触发的克制声呐脉冲环 */
export interface SonarRing {
  x: number
  y: number
  radius: number
  maxRadius: number
  ageMs: number
  durationMs: number
  rgb: RGB
}

// 视差层：远 / 中 / 近，位移幅度递增营造纵深
export const LAYER_SHIFT = [0.7, 1.5, 3.0]

/** 归一化鼠标位移系数，驱动三层视差 */
export const PARALLAX = 0.008
/** 鼠标光晕 lerp 尾随系数 */
export const HALO_LERP = 0.07
/** 域染色平滑过渡 lerp 系数（60fps 基准） */
export const COLOR_LERP = 0.045
/** 鼠标邻近增亮半径 */
export const GLOW_RADIUS = 210
/** 暗色连线最大距离（像素） */
export const LINK_MAX = 120
/** 近层连线粒子上限，避免每帧对全部近层粒子做 O(n²) 距离判定 */
export const LINK_MAX_PARTICLES = 36
/** 同屏声呐环上限与持续时长 */
export const SONAR_MAX_RINGS = 3
export const SONAR_DURATION_MS = 780

// 暗色粒子 tone 阈值：英雄星 / 十字星 / 发光圆点
export const DARK_HERO_TONE = 0.85
export const DARK_CROSS_TONE = 0.55

// 亮色刻度粒子 tone 阈值：琥珀点缀 / 青 / 横竖向 / 双刻度 / 圆环
export const LIGHT_AMBER_TONE = 0.92
export const LIGHT_CYAN_TONE = 0.22
export const LIGHT_TICK_HORIZONTAL_TONE = 0.55
export const LIGHT_TICK_DOUBLE_TONE = 0.88
export const LIGHT_RING_TONE = 0.82

/** 六大工作域染色板（紧扣 variables.css 域色体系，保持蓝青家族统一感） */
export const DOMAIN_PALETTES: Record<string, DomainPalette> = {
  overview: { primary: [18, 183, 245], secondary: [6, 182, 212] },
  ops:      { primary: [24, 175, 245], secondary: [56, 189, 248] },
  llm:      { primary: [6, 182, 212],  secondary: [34, 211, 238] },
  content:  { primary: [8, 145, 178],  secondary: [20, 184, 166] },
  system:   { primary: [100, 130, 165], secondary: [56, 168, 216] },
  games:    { primary: [105, 112, 242], secondary: [56, 189, 248] },
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
