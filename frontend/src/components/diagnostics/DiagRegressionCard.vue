<template>
  <UiCard padding="md" shadow="sm" class="diag-card">
    <div class="diag-card__head">
      <span class="diag-card__icon"><UiIcon name="ListChecks" :size="18" /></span>
      <div>
        <h3>文本规则回归<UiInfoTip text="只走本地正则规则管线，不调用 LLM、不产生费用。" /></h3>
        <p>每行一条样本，快速确认哪些规则命中。</p>
      </div>
    </div>

    <div class="form-row">
      <div class="field grow">
        <label>测试样本（`标签 | 文本`）</label>
        <textarea
          v-model="regressionInput"
          rows="8"
          placeholder="标签1 | 你好世界&#10;标签2 | 今天天气真好"
        />
      </div>
    </div>

    <div class="form-actions">
      <UiButton icon="Play" :loading="regressionLoading" @click="runRegress">运行</UiButton>
    </div>

    <div v-if="regressionError" class="error-block">{{ regressionError }}</div>

    <div v-if="regressionResults.length" class="regression-results">
      <div v-for="(r, i) in regressionResults" :key="i" class="regression-item" :class="{ matched: r.matched }">
        <div class="regression-head">
          <span class="regression-label">{{ r.label || `#${i + 1}` }}</span>
          <span class="regression-text">{{ r.text }}</span>
          <UiTag size="sm" :variant="r.matched ? 'success' : 'info'">{{ r.matched ? '命中' : '未命中' }}</UiTag>
        </div>
        <div v-if="r.rules.length" class="regression-rules">
          <div v-for="(rule, j) in r.rules" :key="j" class="regression-rule">
            <span class="rule-name">{{ rule.name }}</span>
            <span class="rule-patterns">{{ rule.patterns.join(' | ') }}</span>
            <span class="rule-prio">P{{ rule.priority }}</span>
          </div>
        </div>
      </div>
    </div>
  </UiCard>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiTag from '../ui/UiTag.vue'
import { runRegression } from '../../api/diagnostics'
import type { RegressionResult } from '../../api/diagnostics'

const regressionLoading = ref(false)
const regressionError = ref<string | null>(null)
const regressionResults = ref<RegressionResult[]>([])
const regressionInput = ref('')

async function runRegress() {
  regressionLoading.value = true
  regressionError.value = null
  regressionResults.value = []
  try {
    const lines = regressionInput.value.split('\n').filter(line => line.trim())
    if (!lines.length) {
      regressionError.value = '请至少输入一条测试样本'
      return
    }
    const samples = lines.map(line => {
      const pipe = line.indexOf('|')
      if (pipe >= 0) {
        return { label: line.slice(0, pipe).trim(), text: line.slice(pipe + 1).trim() }
      }
      return { label: '', text: line.trim() }
    })
    const data = await runRegression(samples)
    regressionResults.value = data.samples || []
  } catch (e: unknown) {
    regressionError.value = (e as Error).message
  } finally {
    regressionLoading.value = false
  }
}
</script>

<style scoped>
.diag-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--qq-gap-md);
  background: linear-gradient(180deg, var(--qq-surface), var(--qq-surface-elevated));
}

.diag-card__head {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: var(--qq-gap-sm);
  align-items: center;
}

.diag-card__icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
}

.diag-card__head h3 {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 0 0 2px;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
  line-height: 1.3;
}

.diag-card__head p {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
}

.regression-results {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.form-row,
.form-actions,
.regression-head,
.regression-rule {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.field {
  display: flex;
  min-width: 160px;
  flex-direction: column;
  gap: 4px;
}

.field.grow {
  flex: 1;
  min-width: 220px;
}

.field label {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
}

textarea {
  resize: vertical;
}

.regression-label,
.rule-name,
.rule-prio {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.error-block {
  padding: var(--qq-gap-sm);
  background: var(--qq-danger-soft);
  border: 1px solid var(--qq-danger-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.regression-item {
  overflow: hidden;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface);
  padding: var(--qq-gap-sm);
}

.regression-item.matched {
  border-color: var(--qq-primary-border);
  background: var(--qq-primary-soft);
}

.regression-text,
.rule-patterns {
  flex: 1;
  min-width: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.rule-patterns {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.regression-rules {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: var(--qq-gap-sm);
  padding-top: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
}

@media (max-width: 640px) {
  .diag-card__head {
    grid-template-columns: 32px minmax(0, 1fr);
  }

  .diag-card__icon {
    width: 32px;
    height: 32px;
  }

  .field,
  .field.grow {
    min-width: 100%;
  }
}
</style>
