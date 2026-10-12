<template>
  <div class="routes-panel">
    <p class="routes-panel__intro">
      为每类报告任务指定依次尝试的模型（级联）。留空表示直接使用默认渠道；任务失败时按顺序回退到下一个候选。
    </p>
    <UiCard v-for="name in routeNames" :key="name" padding="lg">
      <h3 class="routes-panel__title">{{ ROUTE_LABELS[name]?.label || name }}</h3>
      <CascadeEditor :model-value="routeEntries(name)" :providers="providers" @update:model-value="setRoute(name, $event)" />
    </UiCard>

    <UiCard padding="lg">
      <h3 class="routes-panel__title">
        快速判定
        <UiInfoTip text="用一个小模型快速判断消息意图。留空渠道则跟随默认聊天渠道；留空模型则使用渠道默认模型。" />
      </h3>
      <div class="feature-grid">
        <div class="feature-grid__wide">
          <p class="sub-label">判定用模型</p>
          <ProviderPicker
            :provider-id="quickJudge.provider_id"
            :model="quickJudge.model"
            :providers="providers"
            empty-provider-label="跟随默认聊天渠道"
            @update:provider-id="patchQuickJudge({ provider_id: $event })"
            @update:model="patchQuickJudge({ model: $event })"
          />
        </div>
        <SettingField label="超时" unit="秒" :meta="metaFor('quick_judge', 'timeout')" :model-value="quickJudge.timeout" @update:model-value="patchQuickJudge({ timeout: $event })" />
        <SettingField label="输出上限" unit="token" :meta="metaFor('quick_judge', 'max_tokens')" :model-value="quickJudge.max_tokens" @update:model-value="patchQuickJudge({ max_tokens: $event })" />
      </div>
    </UiCard>

    <UiCard padding="lg">
      <h3 class="routes-panel__title">
        图片预处理
        <UiInfoTip text="发送图片前先由视觉模型生成文字描述。必须使用支持图片的模型。" />
      </h3>
      <div class="feature-grid">
        <SettingField label="启用图片预处理" :meta="{ type: 'boolean' }" :model-value="imagePrep.enabled" @update:model-value="patchImagePrep({ enabled: $event })" />
        <div class="feature-grid__wide">
          <p class="sub-label">预处理用模型</p>
          <ProviderPicker
            :provider-id="imagePrep.provider_id"
            :model="imagePrep.model"
            :providers="providers"
            empty-provider-label="（不选择）"
            @update:provider-id="patchImagePrep({ provider_id: $event })"
            @update:model="patchImagePrep({ model: $event })"
          />
          <p v-if="imagePrep.enabled && !imagePrep.provider_id" class="warn-text">已启用但未选择渠道，应用时将失败。</p>
        </div>
        <SettingField label="输出上限" unit="token" :meta="metaFor('image_preprocessing', 'max_tokens')" :model-value="imagePrep.max_tokens" @update:model-value="patchImagePrep({ max_tokens: $event })" />
        <SettingField label="温度" :meta="metaFor('image_preprocessing', 'temperature')" :model-value="imagePrep.temperature" @update:model-value="patchImagePrep({ temperature: $event })" />
        <SettingField class="feature-grid__wide" label="预处理提示词" :multiline="true" :model-value="imagePrep.prompt" @update:model-value="patchImagePrep({ prompt: $event })" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiCard from '../ui/UiCard.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import CascadeEditor from './CascadeEditor.vue'
import ProviderPicker from './ProviderPicker.vue'
import SettingField from './SettingField.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { ROUTE_LABELS, isObject, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const providers = computed<JsonObject[]>(() => Array.isArray(store.document.value?.providers) ? store.document.value.providers.filter(isObject) : [])
const routeNames = computed(() => store.metadata.value.route_names?.length ? store.metadata.value.route_names : Object.keys(ROUTE_LABELS))
const routes = computed<JsonObject>(() => isObject(store.document.value?.routes) ? store.document.value.routes : {})
const settings = computed<JsonObject>(() => isObject(store.document.value?.settings) ? store.document.value.settings : {})

function routeEntries(name: string): JsonValue[] {
  const value = routes.value[name]
  return Array.isArray(value) ? value : []
}
function setRoute(name: string, value: JsonValue[]) {
  store.updateSection('routes', { ...routes.value, [name]: value })
}

function settingsSection(name: string): JsonObject {
  return isObject(settings.value[name]) ? settings.value[name] as JsonObject : {}
}
const quickJudgeRaw = computed(() => settingsSection('quick_judge'))
const imagePrepRaw = computed(() => settingsSection('image_preprocessing'))
const quickJudge = computed(() => ({ provider_id: String(quickJudgeRaw.value.provider_id ?? ''), model: String(quickJudgeRaw.value.model ?? ''), timeout: quickJudgeRaw.value.timeout ?? 2, max_tokens: quickJudgeRaw.value.max_tokens ?? 64 }))
const imagePrep = computed(() => ({ enabled: imagePrepRaw.value.enabled === true, provider_id: String(imagePrepRaw.value.provider_id ?? ''), model: String(imagePrepRaw.value.model ?? ''), max_tokens: imagePrepRaw.value.max_tokens ?? 300, temperature: imagePrepRaw.value.temperature ?? 0.3, prompt: String(imagePrepRaw.value.prompt ?? '') }))

function patchQuickJudge(fields: JsonObject) { store.updateSettingsSection('quick_judge', { ...quickJudgeRaw.value, ...fields }) }
function patchImagePrep(fields: JsonObject) { store.updateSettingsSection('image_preprocessing', { ...imagePrepRaw.value, ...fields }) }
function metaFor(section: string, field: string) { return store.metadata.value.settings?.[section]?.[field] }
</script>

<style scoped>
.routes-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.routes-panel__intro {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.routes-panel__title {
  margin: 0 0 var(--qq-gap-sm);
  font-size: var(--qq-text-md);
  display: flex;
  align-items: center;
  gap: 6px;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--qq-gap-md);
}

.feature-grid__wide {
  grid-column: 1 / -1;
}

.sub-label {
  margin: 0 0 6px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-weight: 500;
}

.warn-text {
  margin: 6px 0 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-xs);
}

@media (max-width: 700px) {
  .feature-grid { grid-template-columns: 1fr; }
}
</style>
