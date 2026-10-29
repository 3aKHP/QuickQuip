<template>
  <div class="ui-page-header">
    <div v-if="domainIcon" class="ui-page-header__brick" :style="brickStyle" aria-hidden="true">
      <UiIcon :name="domainIcon" :size="20" />
    </div>
    <div class="ui-page-header__info">
      <h1 class="ui-page-header__title">{{ title }}</h1>
      <p v-if="subtitle || $slots.subtitle" class="ui-page-header__subtitle">{{ subtitle }} <slot name="subtitle" /></p>
    </div>
    <div v-if="$slots.actions" class="ui-page-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import UiIcon from './UiIcon.vue'
import { NAV_ITEMS } from '../../config/nav'

defineProps<{
  title: string
  subtitle?: string
}>()

// 域图标砖：由当前路由自动派生所属工作域的图标与域色（六域锚点，见 variables.css --qq-domain-*）
// 按 route.name 匹配：router 以 item.key 构建路由，key 是唯一真值源
const route = useRoute()
const navItem = computed(() => NAV_ITEMS.find((item) => item.key === route.name))
const domainIcon = computed(() => navItem.value?.icon)
const section = computed(() => navItem.value?.section || '')

const brickStyle = computed(() => {
  if (section.value === 'overview') {
    // 总览域：唯一使用品牌渐变的 hero 位
    return { background: 'var(--qq-gradient-brand)', color: 'var(--qq-on-primary)' }
  }
  if (!section.value) return {}
  return {
    background: `var(--qq-domain-${section.value}-soft)`,
    color: `var(--qq-domain-${section.value})`,
  }
})
</script>

<style scoped>
.ui-page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-lg);
  padding-bottom: var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
}

.ui-page-header__brick {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-xl);
  flex-shrink: 0;
}

.ui-page-header__info {
  flex: 1;
  min-width: 0;
}

.ui-page-header__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-shrink: 0;
}

.ui-page-header__title {
  font-family: var(--qq-font-display);
  font-size: var(--qq-text-xl);
  font-weight: 600;
  color: var(--qq-text);
  line-height: 1.3;
  /* CJK 标题优先在词边界折行，仅整词仍溢出时才词内断行 */
  word-break: keep-all;
  overflow-wrap: break-word;
}

.ui-page-header__subtitle {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  margin-top: var(--qq-gap-xs);
  overflow-wrap: break-word;
}

@media (max-width: 767px) {
  /* info 保留最小宽度，避免标题被 brick 与 actions 过度挤压 */
  .ui-page-header__info {
    min-width: 12rem;
  }

  /* actions 独占一行并受行宽约束：flex-basis:100% 使容器按行宽定宽，
     任意数量按钮在行宽内折行、整体右对齐 */
  .ui-page-header__actions {
    flex-basis: 100%;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
}
</style>
