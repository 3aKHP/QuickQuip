<template>
  <div class="login-shell">
    <UiCard padding="lg" shadow="md" class="login-card">
      <div class="login-card__head">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" class="login-card__logo">
            <defs>
              <filter id="login-shadow" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.2" />
              </filter>
              <linearGradient id="login-grad1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#60A5FA" />
                <stop offset="100%" stop-color="#2563EB" />
              </linearGradient>
              <linearGradient id="login-grad2" x1="0%" y1="100%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#818CF8" />
                <stop offset="100%" stop-color="#3730A3" />
              </linearGradient>
              <linearGradient id="login-grad-tail" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#2DD4BF" />
                <stop offset="100%" stop-color="#0F766E" />
              </linearGradient>
            </defs>
            <g filter="url(#login-shadow)" transform="translate(24, 24) scale(0.82) translate(-24, -24)">
              <path d="M 24 42 A 18 18 0 1 0 11.27 11.27 A 22 22 0 1 1 24 42 Z" fill="url(#login-grad2)" opacity="0.95" />
              <path d="M 24 6 A 18 18 0 1 0 36.73 36.73 A 22 22 0 1 1 24 6 Z" fill="url(#login-grad1)" opacity="0.95" />
              <path d="M 22 26 C 28 26 38 34 44 44 C 38 40 30 32 24 30 C 22 29 20 27 22 26 Z" fill="url(#login-grad-tail)" opacity="0.95" />
            </g>
          </svg>
        <h2>QuickQuip Admin</h2>
        <p class="muted">请输入管理员口令</p>
      </div>
      <form @submit.prevent="handleSubmit">
        <div class="login-card__field">
          <UiIcon name="Lock" :size="16" class="login-card__field-icon" />
          <input
            ref="inputRef"
            v-model="password"
            type="password"
            placeholder="口令"
            class="login-card__input"
            :disabled="submitting"
            autofocus
          />
        </div>
        <p v-if="error" class="login-card__error">{{ error }}</p>
        <UiButton variant="primary" type="submit" :loading="submitting" class="login-card__submit">
          登录
        </UiButton>
      </form>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'

defineProps<{
  submitting?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [password: string]
}>()

const password = ref('')
const inputRef = ref<HTMLInputElement>()

onMounted(() => {
  inputRef.value?.focus()
})

function handleSubmit() {
  if (password.value.trim()) {
    emit('submit', password.value)
  }
}
</script>

<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--qq-gap-lg);
  background: var(--qq-bg);
}

.login-card {
  width: min(100%, 400px);
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
