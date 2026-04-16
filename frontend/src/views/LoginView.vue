<template>
  <div class="auth-shell">
    <UiCard padding="lg" shadow="lg" class="login-card">
      <div class="login-brand">
        <UiIcon name="Bot" :size="28" />
        <h2>管理后台登录</h2>
      </div>
      <p class="muted login-copy">
        请输入 Web Admin 口令。通过 nginx <code>auth_basic</code> 后，还需要应用层会话登录。
      </p>
      <form class="login-form" @submit.prevent="submit">
        <div class="input-wrap">
          <UiIcon name="Lock" :size="16" class="input-icon" />
          <input
            v-model="password"
            type="password"
            placeholder="Admin Password"
            autocomplete="current-password"
            :disabled="submitting"
          />
        </div>
        <UiButton
          type="submit"
          variant="primary"
          :disabled="submitting || !password"
          :loading="submitting"
        >
          登录
        </UiButton>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
    </UiCard>
  </div>
</template>

<script>
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'

export default {
  components: { UiCard, UiButton, UiIcon },
  props: {
    submitting: { type: Boolean, default: false },
    error: { type: String, default: '' },
  },
  emits: ['submit'],
  data: () => ({ password: '' }),
  methods: {
    submit() {
      if (!this.password || this.submitting) return
      this.$emit('submit', this.password)
      this.password = ''
    },
  },
}
</script>

<style scoped>
.login-card {
  width: min(100%, 420px);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.login-brand h2 {
  margin: 0;
  font-size: 20px;
  color: var(--qq-text);
}

.login-copy {
  margin-bottom: 18px;
  line-height: 1.6;
}

.login-form {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.input-wrap {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}

.input-icon {
  position: absolute;
  left: 12px;
  color: var(--qq-text-muted);
  pointer-events: none;
}

.input-wrap input {
  width: 100%;
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 9px 12px 9px 36px;
  font-size: 14px;
  outline: none;
  transition: border-color var(--qq-transition-fast), box-shadow var(--qq-transition-fast);
}

.input-wrap input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.error {
  color: var(--qq-danger);
  font-size: 13px;
}

.muted {
  color: var(--qq-text-muted);
  font-size: 13px;
}

code {
  padding: 1px 4px;
  border-radius: 4px;
  background: var(--qq-surface-elevated);
  font-family: var(--qq-font-mono);
  font-size: 12px;
}
</style>
