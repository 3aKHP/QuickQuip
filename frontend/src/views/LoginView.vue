<template>
  <div class="auth-shell">
    <section class="card login-card">
      <h2>管理后台登录</h2>
      <p class="muted login-copy">
        请输入 Web Admin 口令。通过 nginx `auth_basic` 后，还需要应用层会话登录。
      </p>
      <form class="login-form" @submit.prevent="submit">
        <input
          v-model="password"
          type="password"
          placeholder="Admin Password"
          autocomplete="current-password"
          :disabled="submitting"
        />
        <button type="submit" :disabled="submitting || !password">
          {{ submitting ? '登录中...' : '登录' }}
        </button>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
    </section>
  </div>
</template>

<script>
export default {
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
