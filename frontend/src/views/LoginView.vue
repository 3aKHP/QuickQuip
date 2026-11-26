<template>
  <div class="login-shell">
    <UiCard padding="lg" shadow="md" class="login-card">
      <div class="login-card__head">
        <img src="/brand.svg" alt="" class="login-card__logo" width="48" height="48" aria-hidden="true">
        <h2>QuickQuip Admin</h2>
        <p class="muted">请输入管理员口令</p>
      </div>
      <form @submit.prevent="handleSubmit">
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
        <p v-if="displayError" class="login-card__error" role="alert">{{ displayError }}</p>
        <UiButton variant="primary" type="submit" :loading="submitting" class="login-card__submit">
          登录
        </UiButton>
      </form>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'

const props = defineProps<{
  submitting?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [password: string]
}>()

const password = ref('')
const localError = ref('')
const inputRef = ref<HTMLInputElement>()

const displayError = computed(() => localError.value || props.error || '')

watch(password, () => {
  if (localError.value) localError.value = ''
})

onMounted(() => {
  inputRef.value?.focus()
})

function handleSubmit() {
  if (!password.value.trim()) {
    localError.value = '请输入管理员口令。'
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
  width: min(100%, 400px);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 45%),
    var(--qq-shell-drawer-bg);
  border-color: var(--qq-shell-glass-border);
  backdrop-filter: blur(18px) saturate(1.22);
  -webkit-backdrop-filter: blur(18px) saturate(1.22);
  box-shadow: var(--qq-shadow-lg);
}

.login-card__head {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--qq-gap-lg);
}

.login-card__logo {
  width: 48px;
  height: 48px;
  margin-bottom: var(--qq-gap-sm);
}

.login-card__head h2 {
  font-size: var(--qq-text-lg);
  font-weight: 600;
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
  transition: border-color var(--qq-transition-fast);
}

.login-card__input:focus {
  outline: none;
  border-color: var(--qq-primary);
  box-shadow: 0 0 0 2px var(--qq-primary-soft);
}

.login-card__input:disabled {
  opacity: 0.6;
}

.login-card__error {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
  margin-top: var(--qq-gap-sm);
}

.login-card__submit {
  width: 100%;
  margin-top: var(--qq-gap-md);
}
</style>
