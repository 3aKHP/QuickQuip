import { ref, onMounted } from 'vue'

interface UseAsyncDataOptions<T> {
  immediate?: boolean
  initialValue?: T | null
}

interface AsyncDataError {
  _isUnauthorized?: boolean
}

export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  { immediate = true, initialValue = null }: UseAsyncDataOptions<T> = {}
) {
  const data = ref<T | null>(initialValue ?? null)
  const loading = ref(false)
  const error = ref<unknown>(null)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      data.value = await fetcher()
    } catch (e: unknown) {
      const err = e as AsyncDataError
      if (err._isUnauthorized) return
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (immediate) onMounted(refresh)

  return { data, loading, error, refresh }
}
