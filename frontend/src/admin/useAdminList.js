import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export function useAdminList(fetchList, withVerified = false) {
  const route = useRoute()
  const router = useRouter()
  const search = ref(''), status = ref('all'), verified = ref('all')
  const items = ref([]), total = ref(0), loading = ref(false), error = ref('')
  const page = computed(() => Math.max(1, Number.parseInt(route.query.page, 10) || 1))
  const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)))
  let controller, version = 0, disposed = false
  async function load() {
    if (disposed) return
    controller?.abort()
    controller = new AbortController()
    const current = ++version
    loading.value = true
    error.value = ''
    items.value = []
    try {
      const data = await fetchList({
        page: page.value,
        search: typeof route.query.search === 'string' ? route.query.search.trim() : '',
        status: ['active', 'disabled'].includes(route.query.status) ? route.query.status : 'all',
        ...(withVerified ? { verified: ['verified', 'pending'].includes(route.query.verified) ? route.query.verified : 'all' } : {}),
      }, controller.signal)
      if (disposed || current !== version) return
      items.value = data.items
      total.value = data.total
      if (!data.items.length && page.value > 1 && data.total) go(Math.ceil(data.total / 20))
    } catch (e) {
      if (!disposed && current === version && e.name !== 'AbortError') error.value = e.message
    } finally { if (!disposed && current === version) loading.value = false }
  }
  function query(nextPage = 1) {
    return { ...(search.value.trim() ? { search: search.value.trim() } : {}), ...(status.value !== 'all' ? { status: status.value } : {}), ...(withVerified && verified.value !== 'all' ? { verified: verified.value } : {}), ...(nextPage > 1 ? { page: nextPage } : {}) }
  }
  function apply() {
    const next = query()
    if (JSON.stringify(Object.entries(next).sort()) === JSON.stringify(Object.entries(route.query).sort())) load()
    else router.replace({ query: next })
  }
  function go(nextPage) {
    const next = { ...route.query }
    if (nextPage > 1) next.page = nextPage
    else delete next.page
    router.replace({ query: next })
  }
  watch(() => route.query, () => {
    search.value = typeof route.query.search === 'string' ? route.query.search : ''
    status.value = ['active', 'disabled'].includes(route.query.status) ? route.query.status : 'all'
    verified.value = ['verified', 'pending'].includes(route.query.verified) ? route.query.verified : 'all'
    load()
  }, { immediate: true })
  onUnmounted(() => { disposed = true; version++; controller?.abort() })
  return { search, status, verified, items, total, loading, error, page, pages, apply, go, load }
}
