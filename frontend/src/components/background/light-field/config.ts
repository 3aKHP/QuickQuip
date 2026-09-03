// LightField 共享配置：粒子类型、视差常量、tone 阈值与环境判定

export interface Particle {
  x: number; y: number
  r: number; alpha: number; vx: number; vy: number
  twinkle: number; tone: number; layer: number
}

/** 粒子投影到屏幕后的坐标 */
export interface ScreenPoint {
  sx: number; sy: number
}

// 视差层：远 / 中 / 近，位移幅度递增营造纵深
export const LAYER_SHIFT = [0.7, 1.5, 3.0]

/** 归一化鼠标位移系数，驱动三层视差 */
export const PARALLAX = 0.008
/** 鼠标光晕 lerp 尾随系数 */
export const HALO_LERP = 0.07
/** 鼠标邻近增亮半径 */
export const GLOW_RADIUS = 210
/** 暗色连线最大距离（像素） */
export const LINK_MAX = 120
/** 近层连线粒子上限，避免每帧对全部近层粒子做 O(n²) 距离判定 */
export const LINK_MAX_PARTICLES = 36

// 暗色粒子 tone 阈值：英雄星 / 十字星 / 发光圆点
export const DARK_HERO_TONE = 0.85
export const DARK_CROSS_TONE = 0.55

// 亮色刻度粒子 tone 阈值：琥珀点缀 / 青 / 横竖向 / 双刻度 / 圆环
export const LIGHT_AMBER_TONE = 0.92
export const LIGHT_CYAN_TONE = 0.22
export const LIGHT_TICK_HORIZONTAL_TONE = 0.55
export const LIGHT_TICK_DOUBLE_TONE = 0.88
export const LIGHT_RING_TONE = 0.82

export function isMobile(): boolean {
  return window.innerWidth < 768
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
