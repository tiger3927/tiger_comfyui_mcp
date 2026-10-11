import { ref, onMounted, onBeforeUnmount } from 'vue'

// 移动端断点：< 768px 视为手机（对齐 Element Plus 的 :md 断点边界）
const QUERY = '(max-width: 767px)'

// 响应式 isMobile composable：Layout 据此切换「固定侧栏 / 抽屉 + 汉堡」
export function useIsMobile() {
  const isMobile = ref(
    typeof window !== 'undefined' ? window.matchMedia(QUERY).matches : false,
  )

  let mql = null
  const onChange = (e) => { isMobile.value = e.matches }

  onMounted(() => {
    mql = window.matchMedia(QUERY)
    if (typeof mql.addEventListener === 'function') mql.addEventListener('change', onChange)
    else mql.addListener(onChange) // 旧版 Safari
  })
  onBeforeUnmount(() => {
    if (!mql) return
    if (typeof mql.removeEventListener === 'function') mql.removeEventListener('change', onChange)
    else mql.removeListener(onChange)
  })

  return { isMobile }
}
