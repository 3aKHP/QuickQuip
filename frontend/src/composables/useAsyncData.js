import { ref, onMounted } from 'vue'

export function useAsyncData(fetcher, { immediate = true, initialValue = null } = {}) {
  const data = ref(initialValue)
  const loading = ref(false)
  const error = ref(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      data.value = await fetcher()
    } catch (e) {
      if (e?._isUnauthorized) return
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (immediate) onMounted(refresh)

  return { data, loading, error, refresh }
}
