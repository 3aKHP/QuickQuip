<template>
  <div class="reports-panel">
    <p class="reports-panel__intro">
      报告类任务的生成/发布时刻（cron 表达式）与触发门槛。报告使用哪个模型在「功能路由」里配置。
    </p>
    <UiCard v-for="section in sections" :key="section" padding="lg">
      <h3 class="reports-panel__title">{{ SETTINGS_SECTION_LABELS[section] || section }}</h3>
      <SettingsForm :section="section" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import UiCard from '../ui/UiCard.vue'
import SettingsForm from './SettingsForm.vue'
import { SETTINGS_SECTION_LABELS } from '../../lib/llmConfig'

const sections = ['daily_summary', 'daily_briefing', 'weekly_report', 'monthly_report']
</script>

<style scoped>
.reports-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.reports-panel__intro {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.reports-panel__title {
  margin: 0 0 var(--qq-gap-md);
  font-size: var(--qq-text-md);
}
</style>
