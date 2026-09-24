<template>
  <div class="envelope-bar">
    <div v-if="total > 0" class="envbar">
      <TransitionGroup name="envseg">
        <div
          v-for="block in blocks"
          :key="block.key"
          class="seg"
          :class="`seg-${block.key}`"
          :style="{ flexGrow: Math.max(block.tokens, 4) }"
          :title="block.title"
        >
          <em v-if="block.label">{{ block.label }}</em>
        </div>
      </TransitionGroup>
    </div>
    <p v-else class="empty">该时刻之前没有缓存的信封分解（信封不落库，只保留最近一封）。</p>
    <div class="bar-foot">
      <span v-if="total > 0">本封合计 {{ total }} tokens ≈ 每轮固定成本</span>
      <span>每轮重渲染 · 不吃前缀缓存 · 按全价计</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 【轮次上下文】信封构成条：最近一封的六段 token 分解。
 *
 * 段键与后端 build_turn_envelope_segments 一致（vocab 段含黑话解释）；
 * 空段整段省略。数据只来自 epoch_snapshot 的实时缓存——信封组装时渲染、
 * 不落库是前缀缓存契约，历史时刻只展示"最近一封"。
 */
import { computed } from 'vue'

const props = defineProps<{
  parts: Record<string, number> | null
}>()

const ENV_META: ReadonlyArray<{ key: string; name: string }> = [
  { key: 'time', name: '时间' },
  { key: 'festival', name: '节日' },
  { key: 'participants', name: '参与成员' },
  { key: 'mentions', name: '艾特档案' },
  { key: 'memories', name: '持久记忆' },
  { key: 'vocab', name: '词表命中' },
]

const total = computed(() =>
  ENV_META.reduce((sum, meta) => sum + (props.parts?.[meta.key] ?? 0), 0),
)

interface Block {
  key: string
  tokens: number
  title: string
  label: string | null
}

const blocks = computed<Block[]>(() => {
  const sum = total.value
  if (!props.parts || sum <= 0) return []
  const out: Block[] = []
  for (const meta of ENV_META) {
    const value = props.parts[meta.key] ?? 0
    if (!value) continue
    out.push({
      key: meta.key,
      tokens: value,
      title: `${meta.name} · ${value} tok（占 ${Math.round((value / sum) * 100)}%）`,
      label: value / sum >= 0.09 ? `${meta.name} ${value}` : null,
    })
  }
  return out
})

defineExpose({ total })
</script>

<style scoped>
.envbar {
  display: flex;
  gap: 2px;
  min-height: 40px;
  padding: 4px;
  border-radius: 9px;
  background: color-mix(in srgb, var(--qq-accent) 7%, transparent);
  outline: 1.5px dashed color-mix(in srgb, var(--qq-accent) 45%, transparent);
  outline-offset: 3px;
}
.seg {
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 4px;
  min-width: 4px;
  transition: flex-grow 0.6s ease;
}
.seg em {
  font-style: normal;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.28);
  white-space: nowrap;
  pointer-events: none;
}
.seg-time { background: var(--qq-env-time); }
.seg-festival { background: var(--qq-env-festival); }
.seg-participants { background: var(--qq-env-participants); }
.seg-mentions { background: var(--qq-env-mentions); }
.seg-memories { background: var(--qq-env-memories); }
.seg-vocab { background: var(--qq-env-vocab); }
.envseg-enter-active { transition: opacity 0.5s ease, transform 0.5s ease; }
.envseg-enter-from { opacity: 0; transform: translateY(6px); }
.empty {
  font-size: 12.5px;
  color: var(--qq-text-muted);
  padding: 10px 2px;
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
  .seg, .envseg-enter-active { transition: none; }
}
</style>
