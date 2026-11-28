<template>
  <div class="login-shell">
    <UiCard
      padding="lg"
      shadow="lg"
      class="login-card qq-glow-card qq-tilt-card"
      :class="{ 'login-card--shake': shaking, 'login-card--error': Boolean(displayError) }"
      data-glow-card
      data-tilt-card
      data-tilt-max="3.2"
      @animationend="onShakeEnd"
    >
      <span class="qq-beam" aria-hidden="true" />
      <div class="login-card__inner">
        <div class="login-card__head">
          <div class="login-card__logo-wrap qq-stagger-item" style="--stagger-i: 0">
            <span class="login-card__halo" aria-hidden="true" />
            <img src="/brand.svg" alt="" class="login-card__logo" width="52" height="52" aria-hidden="true">
          </div>
          <h2 class="qq-stagger-item" style="--stagger-i: 1">QuickQuip Admin</h2>
          <p class="muted qq-stagger-item" style="--stagger-i: 2">请输入管理员口令</p>
        </div>
        <form class="qq-stagger-item" style="--stagger-i: 3" @submit.prevent="handleSubmit">
          <input
            type="text"
            name="username"
            autocomplete="username"
            value="admin"
            hidden
            tabindex="-1"
            aria-hidden="true"
          />
          <div class="login-card__field">
            <UiIcon name="Lock" :size="16" class="login-card__field-icon" />
            <input
              ref="inputRef"
              v-model="password"
              type="password"
              name="password"
              autocomplete="current-password"
              placeholder="口令"
              class="login-card__input"
              :disabled="submitting"
              autofocus
            />
          </div>
          <Transition name="error-pop">
            <p v-if="displayError" class="login-card__error" role="alert">{{ displayError }}</p>
          </Transition>
          <UiButton variant="primary" type="submit" :loading="submitting" class="login-card__submit">
            登录
          </UiButton>
        </form>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import { useMotionPrefs } from '../composables/useMotionPrefs'
import { triggerLightFieldSonar } from '../lib/lightFieldBus'

const props = defineProps<{
  submitting?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [password: string]
}>()

const { lowMotion } = useMotionPrefs()
const password = ref('')
const localError = ref('')
const shaking = ref(false)
const inputRef = ref<HTMLInputElement>()

const displayError = computed(() => localError.value || props.error || '')

function isReducedMotion(): boolean {
  if (lowMotion.value) return true
  try {
    return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

function triggerShake() {
  triggerLightFieldSonar({ kind: 'error' })
  if (isReducedMotion()) {
    shaking.value = false
    return
  }
  shaking.value = false
  nextTick(() => {
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => { shaking.value = true })
    } else {
      shaking.value = true
    }
  })
}

function onShakeEnd(e: AnimationEvent) {
  if (e.animationName.includes('login-shake')) {
    shaking.value = false
  }
}

watch(password, () => {
  if (localError.value) localError.value = ''
})

// 服务端返回鉴权错误时同样触发物理摇头与光场警示环
watch(() => props.error, (val) => {
  if (val) triggerShake()
})

onMounted(() => {
  inputRef.value?.focus()
})

function handleSubmit() {
  if (!password.value.trim()) {
    localError.value = '请输入管理员口令。'
    triggerShake()
    inputRef.value?.focus()
    return
  }
  localError.value = ''
  emit('submit', password.value)
}
</script>

<style scoped>
.login-shell {
  position: relative;
  z-index: 1;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  place-items: center;
  padding: var(--qq-gap-lg);
}

.login-card {
  width: min(100%, 408px);
  border-radius: var(--qq-radius-xl);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 45%),
    var(--qq-shell-drawer-bg);
  border-color: var(--qq-shell-glass-border);
  backdrop-filter: blur(22px) saturate(1.28);
  -webkit-backdrop-filter: blur(22px) saturate(1.28);
  box-shadow:
    var(--qq-shadow-lg),
    0 18px 48px rgba(18, 60, 95, 0.12);
  transition: border-color var(--qq-transition-base), box-shadow var(--qq-transition-base);
}

.login-card--error {
  border-color: var(--qq-danger-border);
  box-shadow:
    var(--qq-shadow-lg),
    0 0 0 1px var(--qq-danger-soft);
}

.login-card--shake {
  animation: login-shake 420ms var(--qq-ease-out);
}

@keyframes login-shake {
  0%, 100% { translate: 0 0; }
  16% { translate: -9px 0; }
  34% { translate: 8px 0; }
  52% { translate: -5px 0; }
  70% { translate: 4px 0; }
  86% { translate: -2px 0; }
}

.login-card__inner {
  position: relative;
  z-index: 1;
}

.login-card__head {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--qq-gap-lg);
}

.login-card__logo-wrap {
  position: relative;
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  margin-bottom: var(--qq-gap-sm);
}

.login-card__halo {
  position: absolute;
  inset: -6px;
  border-radius: 22px;
  background: radial-gradient(circle, var(--qq-primary-glow), transparent 68%);
  opacity: 0.55;
  animation: login-halo-breathe 3.6s ease-in-out infinite;
  pointer-events: none;
}

@keyframes login-halo-breathe {
  0%, 100% { transform: scale(0.92); opacity: 0.42; }
  50% { transform: scale(1.08); opacity: 0.72; }
}

.login-card__logo {
  position: relative;
  z-index: 1;
  width: 52px;
  height: 52px;
  display: block;
  border-radius: var(--qq-radius-xl);
  box-shadow: 0 6px 20px var(--qq-primary-shadow);
}

.login-card__head h2 {
  font-family: var(--qq-font-display);
  font-size: var(--qq-text-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--qq-text);
}

.muted {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  margin-top: var(--qq-gap-xs);
}

.login-card__field {
  position: relative;
  display: flex;
  align-items: center;
}

.login-card__field-icon {
  position: absolute;
  left: 12px;
  color: var(--qq-text-muted);
  pointer-events: none;
  transition: color var(--qq-transition-fast);
}

.login-card__field:focus-within .login-card__field-icon {
  color: var(--qq-primary-ink);
}

.login-card__input {
  width: 100%;
  height: 44px;
  padding: 0 12px 0 36px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-base);
  transition:
    border-color var(--qq-transition-fast),
    box-shadow var(--qq-transition-fast),
    background var(--qq-transition-fast);
}

.login-card__input:focus {
  outline: none;
  border-color: var(--qq-primary);
  box-shadow: 0 0 0 3px var(--qq-primary-soft);
}

.login-card__input:disabled {
  opacity: 0.6;
}

.login-card__error {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
  margin-top: var(--qq-gap-sm);
}

.error-pop-enter-active {
  transition: opacity 180ms var(--qq-ease-out), transform 220ms var(--qq-ease-spring);
}

.error-pop-leave-active {
  transition: opacity 120ms var(--qq-ease-out);
}

.error-pop-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

.error-pop-leave-to {
  opacity: 0;
}

.login-card__submit {
  width: 100%;
  margin-top: var(--qq-gap-md);
}

@media (prefers-reduced-motion: reduce) {
  .login-card--shake,
  .login-card__halo {
    animation: none;
  }

  .error-pop-enter-active,
  .error-pop-leave-active {
    transition: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .login-card--shake,
html[data-motion="reduced"] .login-card__halo {
  animation: none;
}

html[data-motion="reduced"] .error-pop-enter-active,
html[data-motion="reduced"] .error-pop-leave-active {
  transition: none;
}
</style>
