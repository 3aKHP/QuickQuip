<template>
  <div class="epoch-panel">
    <UiCard padding="lg">
      <h3 class="epoch-panel__title">
        纪元压缩阈值
        <UiInfoTip text="对话上下文持续增长时，先按冷态目标压缩；超过触发阈值后进入热态压缩；容量上限是不可逾越的天花板。" />
      </h3>
      <div class="epoch-bar" role="img" :aria-label="`冷态目标 ${values.epoch_cold_target_tokens}，冷态触发 ${values.epoch_cold_trigger_tokens}，热态目标 ${values.epoch_hot_target_tokens}，容量上限 ${values.epoch_cap_tokens}`">
        <div class="epoch-bar__segment epoch-bar__segment--cold" :style="{ left: '0%', width: pct(values.epoch_cold_target_tokens) }" />
        <div class="epoch-bar__segment epoch-bar__segment--trigger" :style="{ left: pct(values.epoch_cold_target_tokens), width: pct(values.epoch_cold_trigger_tokens - values.epoch_cold_target_tokens) }" />
        <div class="epoch-bar__segment epoch-bar__segment--hot" :style="{ left: pct(values.epoch_cold_trigger_tokens), width: pct(values.epoch_hot_target_tokens - values.epoch_cold_trigger_tokens) }" />
        <div class="epoch-bar__segment epoch-bar__segment--cap" :style="{ left: pct(values.epoch_hot_target_tokens), width: pct(values.epoch_cap_tokens - values.epoch_hot_target_tokens) }" />
      </div>
      <div class="epoch-legend">
        <span><i class="dot dot--cold" />0 ~ {{ values.epoch_cold_target_tokens }} 冷态目标</span>
        <span><i class="dot dot--trigger" />~ {{ values.epoch_cold_trigger_tokens }} 冷态触发</span>
        <span><i class="dot dot--hot" />~ {{ values.epoch_hot_target_tokens }} 热态目标</span>
        <span><i class="dot dot--cap" />~ {{ values.epoch_cap_tokens }} 容量上限</span>
      </div>
      <p v-if="chainError" class="epoch-error">{{ chainError }}</p>
      <SettingsForm section="runtime" :fields="epochFields" />
    </UiCard>

    <UiCard padding="lg">
      <h3 class="epoch-panel__title">代理</h3>
      <SettingsForm section="runtime" :fields="agentFields" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiCard from '../ui/UiCard.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import SettingsForm from './SettingsForm.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { epochChainError, isObject } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const epochFields = ['epoch_context_tokens', 'epoch_cold_idle_seconds', 'epoch_cold_target_tokens', 'epoch_cold_trigger_tokens', 'epoch_hot_target_tokens', 'epoch_cap_tokens']
const agentFields = ['agent_replay_loop_tokens', 'agent_record_retention_days', 'agent_record_max_loops_per_scope', 'agent_record_max_bytes_per_scope', 'agent_delivery_intermediate_enabled', 'agent_delivery_final_enabled']

const values = computed<Record<string, number>>(() => {
  const settings = store.document.value?.settings
  const runtime = isObject(settings) && isObject(settings.runtime) ? settings.runtime : {}
  const meta = store.metadata.value.settings?.runtime || {}
  const result: Record<string, number> = {}
  for (const field of epochFields) {
    const value = runtime[field]
    result[field] = typeof value === 'number' ? value : Number(meta[field]?.default ?? 0)
  }
  return result
})

const chainError = computed(() => epochChainError(values.value))

function pct(value: number) {
  const cap = Number(values.value.epoch_cap_tokens) || 1
  return `${Math.max(0, Math.min(100, (value / cap) * 100))}%`
}
</script>

<style scoped>
.epoch-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.epoch-panel__title {
  margin: 0 0 var(--qq-gap-md);
  font-size: var(--qq-text-md);
  display: flex;
  align-items: center;
  gap: 6px;
}

.epoch-bar {
  position: relative;
  height: 14px;
  border-radius: var(--qq-radius-full);
  overflow: hidden;
  background: var(--qq-surface-strong);
  margin-bottom: 8px;
}

.epoch-bar__segment {
  position: absolute;
  top: 0;
  bottom: 0;
}

.epoch-bar__segment--cold { background: var(--qq-epoch-cold); opacity: 0.75; }
.epoch-bar__segment--trigger { background: var(--qq-cyan); opacity: 0.75; }
.epoch-bar__segment--hot { background: var(--qq-epoch-hot); opacity: 0.8; }
.epoch-bar__segment--cap { background: var(--qq-danger); opacity: 0.55; }

.epoch-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  margin-bottom: var(--qq-gap-md);
}

.epoch-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot--cold { background: var(--qq-epoch-cold); }
.dot--trigger { background: var(--qq-cyan); }
.dot--hot { background: var(--qq-epoch-hot); }
.dot--cap { background: var(--qq-danger); }

.epoch-error {
  margin: 0 0 var(--qq-gap-sm);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}
</style>
