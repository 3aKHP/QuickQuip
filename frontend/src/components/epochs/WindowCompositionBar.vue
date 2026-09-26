<template>
  <div class="window-bar">
    <div class="bar-row">
      <div class="zone zone-out">
        <TransitionGroup name="seg">
          <div
            v-for="block in outBlocks"
            :key="block.key"
            class="seg"
            :class="`seg-${block.role}`"
            :style="{ flexGrow: Math.max(block.tokens, 10) }"
            :title="block.title"
          />
        </TransitionGroup>
      </div>
      <div class="anchor-mark"><i>锚点 #{{ anchorId }}</i></div>
      <div class="zone zone-live">
        <TransitionGroup name="seg">
          <div
            v-for="block in liveBlocks"
            :key="block.key"
            class="seg"
            :class="`seg-${block.role}`"
            :style="{ flexGrow: Math.max(block.tokens, 10) }"
            :title="block.title"
          />
        </TransitionGroup>
      </div>
    </div>
    <div class="bar-foot">
      <span>已出窗 {{ outTotalRows }} 条 · {{ fmtTokens(outTotalTokens) }} tokens（LLM 不可见）{{ outTokensApprox ? '（≈ 截断估算）' : '' }}</span>
      <span>窗口内 {{ window.length }} 条 · {{ fmtTokens(windowTokens) }} tokens</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 纪元窗口构成条：锚点罩住哪段对话。
 *
 * 每条消息一个色块（宽 ∝ token），锚点左侧灰化斜纹为已出窗区，右侧虚线框
 * 为活窗口；过长列表头端折叠为"合并块"。只渲染 id/role/token 元数据，
 * 不含任何正文——悬浮提示也只有计量信息。
 */
import { computed } from 'vue'
import type { EpochWindowMessage } from '../../api/epochs'

const props = defineProps<{
  /** 锚点前采样（后端按 id DESC 返回，outBlocks 内反转为正序；元数据） */
  out: EpochWindowMessage[]
  /** 窗口内（ASC，元数据） */
  window: EpochWindowMessage[]
  anchorId: number
  outTotalRows: number
  outTotalTokens: number
  outTokensApprox: boolean
}>()

const OUT_MAX = 26
const LIVE_MAX = 60

interface Block {
  key: string
  tokens: number
  role: string
  title: string
}

function fmtTokens(value: number): string {
  return `${(value / 1000).toFixed(1)}k`
}

function toBlock(message: EpochWindowMessage): Block {
  const who = message.role === 'user' ? '用户消息' : message.role === 'bot' ? 'bot 回复' : '系统/工具行'
  return {
    key: `m${message.id}`,
    tokens: message.tokens,
    role: message.role,
    title: `#${message.id} · ${who} · ${message.tokens} tok · ${message.ts.slice(11, 16)}`,
  }
}

/** 超出上限时头端折叠成合并块（宽度 ∝ 合计 token） */
function blocksFor(list: EpochWindowMessage[], max: number): Block[] {
  if (list.length <= max) return list.map(toBlock)
  const aggN = list.length - max + 1
  const head = list.slice(0, aggN)
  const rest = list.slice(aggN)
  return [
    {
      key: `agg${head[0].id}-${head[head.length - 1].id}`,
      tokens: head.reduce((sum, item) => sum + item.tokens, 0),
      role: 'agg',
      title: `${aggN} 条较早消息合并`,
    },
    ...rest.map(toBlock),
  ]
}

// 后端出窗采样按 id DESC 返回（最新在前）；构成条左旧右新，
// 先反转为正序，头端折叠合并的才是最老的消息
const outBlocks = computed(() => blocksFor([...props.out].reverse(), OUT_MAX))
const liveBlocks = computed(() => blocksFor(props.window, LIVE_MAX))
const windowTokens = computed(() => props.window.reduce((sum, item) => sum + item.tokens, 0))
</script>

<style scoped>
.bar-row {
  display: flex;
  align-items: stretch;
  min-height: 58px;
  margin-top: 28px;
}
.zone {
  display: flex;
  gap: 2px;
  padding: 4px;
  border-radius: 9px;
  min-width: 0;
}
.zone-out {
  background: repeating-linear-gradient(
    135deg,
    var(--qq-epoch-stripe-a),
    var(--qq-epoch-stripe-a) 6px,
    var(--qq-epoch-stripe-b) 6px,
    var(--qq-epoch-stripe-b) 12px
  );
  flex: 0 1 auto;
  max-width: 38%;
  overflow: hidden;
}
.zone-live {
  background: color-mix(in srgb, var(--qq-primary) 7%, transparent);
  outline: 1.5px dashed color-mix(in srgb, var(--qq-primary) 45%, transparent);
  outline-offset: 3px;
  flex: 1 1 auto;
  overflow: hidden;
}
.seg {
  border-radius: 4px;
  min-width: 4px;
  transition: flex-grow 0.6s ease, opacity 0.6s ease, filter 0.6s ease;
}
.seg-user { background: var(--qq-epoch-user); }
.seg-bot { background: var(--qq-epoch-bot); }
.seg-other { background: var(--qq-epoch-neutral); }
.seg-agg {
  background: repeating-linear-gradient(
    135deg,
    var(--qq-epoch-stripe-agg-a),
    var(--qq-epoch-stripe-agg-a) 3px,
    var(--qq-epoch-stripe-agg-b) 3px,
    var(--qq-epoch-stripe-agg-b) 7px
  );
}
.zone-out .seg { filter: grayscale(1); opacity: 0.38; }
/* TransitionGroup：新块升起入场、离场淡出（reorder 的平滑位移由 flex-grow 过渡承担） */
.seg-enter-active { transition: opacity 0.7s ease, transform 0.7s ease; }
.seg-leave-active { transition: opacity 0.4s ease; }
.seg-enter-from { opacity: 0; transform: translateY(7px); }
.seg-leave-to { opacity: 0; }
.anchor-mark {
  flex: none;
  width: 0;
  position: relative;
}
.anchor-mark::before {
  content: "";
  position: absolute;
  top: -6px;
  bottom: -6px;
  left: -1.5px;
  border-left: 3px solid var(--qq-primary);
  border-radius: 2px;
}
.anchor-mark i {
  position: absolute;
  top: -26px;
  left: -4px;
  font-style: normal;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--qq-primary);
  white-space: nowrap;
  background: var(--qq-surface);
  padding: 0 6px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--qq-primary) 35%, transparent);
}
.bar-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--qq-text-muted);
  flex-wrap: wrap;
  gap: 8px;
  font-variant-numeric: tabular-nums;
}
@media (prefers-reduced-motion: reduce) {
  .seg, .seg-enter-active, .seg-leave-active { transition: none; }
}
</style>
