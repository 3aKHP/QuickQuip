<template>
  <div class="diag-view">
    <UiPageHeader title="诊断" subtitle="LLM 运行时操作、样本请求与文本规则回归测试" />

    <div class="diag-stack">
      <DiagRuntimeOpsCard />
      <DiagSampleCard />
      <DiagRegressionCard />
    </div>
  </div>
</template>

<script setup lang="ts">
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import DiagRuntimeOpsCard from '../components/diagnostics/DiagRuntimeOpsCard.vue'
import DiagSampleCard from '../components/diagnostics/DiagSampleCard.vue'
import DiagRegressionCard from '../components/diagnostics/DiagRegressionCard.vue'
</script>

<style scoped>
.diag-view {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
  min-height: 0;
}

.diag-stack {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
}
</style>
