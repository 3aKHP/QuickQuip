<template>
  <div class="diag-view">
    <UiPageHeader title="诊断" subtitle="LLM 运行时操作、样本请求与文本规则回归测试" />

    <div v-if="botOffline" class="soft-note soft-note--warn" role="status">
      Bot 当前离线（无有效心跳上报）：本页的健康检查、重载与探活操作会入队等待，Bot 上线后按序执行；动作记录中的「等待」状态即来源于此。
    </div>

    <div class="diag-stack">
      <DiagRuntimeOpsCard />
      <DiagSampleCard />
      <DiagRegressionCard />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import DiagRuntimeOpsCard from '../components/diagnostics/DiagRuntimeOpsCard.vue'
import DiagSampleCard from '../components/diagnostics/DiagSampleCard.vue'
import DiagRegressionCard from '../components/diagnostics/DiagRegressionCard.vue'
import { fetchLlmConfigStatus } from '../api/llmConfiguration'

const botOffline = ref(false)

// 一次性探测复用 LLM 配置状态接口的 bot 心跳；接口失败时不误报离线
onMounted(async () => {
  try {
    const status = await fetchLlmConfigStatus()
    botOffline.value = !status.bot || status.bot.stale
  } catch {
    botOffline.value = false
  }
})
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
