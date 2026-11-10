import { onUnmounted, ref } from 'vue'
import { api } from './api.js'

/** Only the current request may publish a result, even if cancellation arrives late. */
export function useParseRequest() {
  const loading = ref(false)
  let controller
  let version = 0
  function cancel() {
    version++
    controller?.abort()
    loading.value = false
  }
  async function parse(url) {
    cancel()
    const current = version
    controller = new AbortController()
    loading.value = true
    try {
      const info = await api.parse(url, controller.signal)
      return current === version ? info : null
    } catch (error) {
      if (current !== version || error.name === 'AbortError') return null
      throw error
    } finally {
      if (current === version) loading.value = false
    }
  }
  onUnmounted(cancel)
  return { loading, parse, cancel }
}
